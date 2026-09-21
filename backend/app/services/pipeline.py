"""任务主管线:抓数据 → 抓地形 → 解析 → 建模 → 写枢纽文件。

每个阶段都会通过 ctx.progress 上报进度(阶段内 0~1,
任务管理器负责折算成全局 0~100),阶段之间顺手检查有没有被取消。
费 CPU 的步骤丢到旁边线程去干(anyio.to_thread),别把主服务卡住。
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import anyio
import numpy as np
import trimesh

from app.config import Settings
from app.core.errors import TaskCancelled
from app.services import osm_parse, overpass
from app.services import terrain as terrain_svc
from app.services.mesh import scene as scene_svc
from app.services.mesh.extrude import extrude_buildings
from app.services.mesh.ribbon import (
    LIFT_RAIL,
    LIFT_ROAD,
    build_layer_ribbons,
    build_water_surface,
)
from app.services.mesh.terrain_mesh import build_terrain_mesh
from app.services.projection import Projector
from app.services.vector.buildings import to_local_buildings
from app.services.vector.lines import to_local_lines
from app.services.vector.polys import to_local_polys
from app.utils.caching import read_json, write_json_atomic

logger = logging.getLogger("app.pipeline")


@dataclass
class PipelineContext:
    """一个任务的全部运行上下文。"""

    task_id: str
    task_dir: Path
    bbox: tuple[float, float, float, float]
    options: dict[str, Any]
    cancel_event: asyncio.Event
    progress: Callable          # (stage, 0~1, message) -> None
    warn: Callable              # (message) -> None
    settings: Settings


def _check_cancel(cancel_event: asyncio.Event) -> None:
    if cancel_event.is_set():
        raise TaskCancelled()


@dataclass
class _LocalData:
    """解析并转到局部坐标后的全部要素(建模的输入)。"""

    buildings: list = field(default_factory=list)
    roads: list = field(default_factory=list)
    railways: list = field(default_factory=list)
    waterways: list = field(default_factory=list)
    water_polys: list = field(default_factory=list)
    greens: list = field(default_factory=list)
    preview_features: list = field(default_factory=list)  # lonlat,给前端 2D 回显


async def run_pipeline(ctx: PipelineContext) -> dict[str, Any]:
    """跑完五个阶段,返回统计信息(会存进任务记录)。"""
    # ---- 阶段 1:抓 OSM 数据 ----
    def overpass_progress(frac: float, msg: str | None = None) -> None:
        ctx.progress("FETCH_OVERPASS", frac, msg)

    osm_path = await overpass.fetch_overpass(
        ctx.bbox, settings=ctx.settings, on_progress=overpass_progress,
        cancel_event=ctx.cancel_event,
    )
    _check_cancel(ctx.cancel_event)

    # ---- 阶段 2:抓地形(抓不到就凑合用平地) ----
    projector = Projector(ctx.bbox)
    grid: terrain_svc.TerrainGrid | None = None
    if ctx.options.get("terrain", True):
        def terrain_progress(frac: float, msg: str | None = None) -> None:
            ctx.progress("FETCH_TERRAIN", frac, msg)

        grid = await terrain_svc.fetch_terrain(
            ctx.bbox, projector, settings=ctx.settings,
            on_progress=terrain_progress, cancel_event=ctx.cancel_event,
        )
        if grid is None:
            ctx.warn("Failed to fetch terrain data; fell back to flat ground "
                     "(buildings/roads will sit at the 0 m baseline)")
    if grid is None:
        grid = terrain_svc.TerrainGrid.flat(projector.width_m, projector.height_m)
    ctx.progress("FETCH_TERRAIN", 1.0, "terrain ready")
    _check_cancel(ctx.cancel_event)

    # ---- 阶段 3:解析矢量 + 转局部坐标(CPU,进线程池) ----
    def parse_progress(frac: float, msg: str | None = None) -> None:
        ctx.progress("PARSE_VECTOR", frac, msg)

    local = await anyio.to_thread.run_sync(_parse_and_localize, osm_path, projector, ctx)
    _check_cancel(ctx.cancel_event)

    # ---- 阶段 4:建模(CPU,进线程池) ----
    def mesh_progress(frac: float, msg: str | None = None) -> None:
        ctx.progress("BUILD_MESH", frac, msg)

    zup_layers = await anyio.to_thread.run_sync(
        _build_meshes, local, grid, ctx.options, mesh_progress, ctx.cancel_event
    )
    _check_cancel(ctx.cancel_event)

    # ---- 阶段 5:写枢纽文件 ----
    # 组场景、写 GLB/GeoJSON 都是几十上百毫秒到秒级的重活,也得进线程池,
    # 不然大任务收尾时整个服务(进度推送、心跳)会卡住
    ctx.progress("WRITE_HUB", 0.2, "assembling scene")

    def _write_hub() -> Path:
        return scene_svc.write_hub(ctx.task_dir, scene_svc.build_scene(zup_layers))

    hub_path = await anyio.to_thread.run_sync(_write_hub)

    stats = {
        "buildings": len(local.buildings),
        "roads": len(local.roads),
        "railways": len(local.railways),
        "waterways": len(local.waterways),
        "water_polys": len(local.water_polys),
        "greens": len(local.greens),
        "terrain": {
            "source": "aws-terrarium" if grid.nx > 2 else "flat",
            "min_h": round(float(grid.z.min()), 2),
            "max_h": round(float(grid.z.max()), 2),
            "median_h": round(grid.median_height, 2),
            "grid": f"{grid.nx}x{grid.ny}",
        },
        "hub_mb": round(hub_path.stat().st_size / 1e6, 2),
    }

    # 2D 预览 GeoJSON(前端"2D Map"标签直接渲染它)
    ctx.progress("WRITE_HUB", 0.6, "writing preview")
    await anyio.to_thread.run_sync(
        write_json_atomic,
        ctx.task_dir / "preview.geojson",
        {"type": "FeatureCollection", "features": local.preview_features},
    )
    # 任务元信息(导出器做坐标换算要用)
    ctx.progress("WRITE_HUB", 0.85, "writing meta")
    await anyio.to_thread.run_sync(
        write_json_atomic,
        ctx.task_dir / "meta.json",
        {
            "bbox": list(ctx.bbox),
            "epsg": projector.epsg,
            "center_lon": projector.center_lon,
            "center_lat": projector.center_lat,
            "width_m": round(projector.width_m, 2),
            "height_m": round(projector.height_m, 2),
            "median_h": round(grid.median_height, 2),
            "options": ctx.options,
            "stats": stats,
        },
    )
    return stats


# ---------------------------------------------------------------------------
# 阶段 3 的实现(在线程池里跑)
# ---------------------------------------------------------------------------

def _parse_and_localize(
    osm_path: Path, projector: Projector, ctx: PipelineContext
) -> _LocalData:
    ctx.progress("PARSE_VECTOR", 0.1, "parsing overpass json")
    payload = read_json(osm_path)
    feats = osm_parse.parse_osm(payload)

    ctx.progress("PARSE_VECTOR", 0.35, f"parsed: {len(feats.buildings)} buildings")
    osm_parse.resolve_building_heights(feats.buildings)

    opts = ctx.options
    local = _LocalData()
    if opts.get("buildings", True):
        local.buildings = to_local_buildings(
            feats.buildings, projector,
            max_buildings=ctx.settings.max_buildings, warn=ctx.warn,
        )
    ctx.progress("PARSE_VECTOR", 0.55, "converting to local coordinates")
    if opts.get("roads", True):
        local.roads = to_local_lines(feats.roads, projector)
    if opts.get("railways", True):
        local.railways = to_local_lines(feats.railways, projector)
    if opts.get("water", True):
        local.waterways = to_local_lines(feats.waterways, projector)
        local.water_polys = to_local_polys(feats.water_polys, projector)
    if opts.get("green", True):
        local.greens = to_local_polys(feats.greens, projector)

    # 2D 预览要素(经纬度 + 属性),按图层归类
    local.preview_features = _build_preview_features(local, projector)
    ctx.progress("PARSE_VECTOR", 1.0, "vector ready")
    return local


def _build_preview_features(local: _LocalData, projector: Projector) -> list[dict]:
    """把建模实际用的要素转成前端好渲染的 GeoJSON 要素列表。

    要用"过滤修型之后"的 local(超上限砍掉的、太小的、坏掉的都不在了),
    不能用刚解析出来的原始要素——不然预览、统计、3D 模型、导出文件
    各说各话,会出现"预览两万栋楼、模型里一万栋"的对不上账。
    """
    out: list[dict] = []

    def line_f(pts: np.ndarray, layer: str, props: dict) -> dict:
        lons, lats = projector.to_lonlat_grid(pts[:, 0], pts[:, 1])
        coords = [[float(lo), float(la)] for lo, la in zip(lons, lats)]
        return {
            "type": "Feature",
            "properties": {"layer": layer, **props},
            "geometry": {"type": "LineString", "coordinates": coords},
        }

    def poly_f(poly, layer: str, props: dict) -> dict:
        def ring_lonlat(ring) -> list[list[float]]:
            arr = np.asarray(ring.coords)
            lons, lats = projector.to_lonlat_grid(arr[:, 0], arr[:, 1])
            return [[float(lo), float(la)] for lo, la in zip(lons, lats)]

        rings = [ring_lonlat(poly.exterior)]
        for r in poly.interiors:
            rings.append(ring_lonlat(r))
        return {
            "type": "Feature",
            "properties": {"layer": layer, **props},
            "geometry": {"type": "Polygon", "coordinates": rings},
        }

    for g in local.greens:
        out.append(poly_f(g.poly, "green", {"kind": g.kind, "name": g.name}))
    for w in local.water_polys:
        out.append(poly_f(w.poly, "water", {"kind": w.kind, "name": w.name}))
    for w in local.waterways:
        out.append(line_f(w.pts, "water", {"kind": w.kind, "name": w.name}))
    for b in local.buildings:
        out.append(poly_f(b.poly, "building", {"height": b.height, "name": b.name}))
    for r in local.roads:
        out.append(line_f(r.pts, "road", {
            "kind": r.kind, "width": r.width, "bridge": r.bridge, "name": r.name,
        }))
    for r in local.railways:
        out.append(line_f(r.pts, "railway", {
            "kind": r.kind, "width": r.width, "bridge": r.bridge, "name": r.name,
        }))
    return out


# ---------------------------------------------------------------------------
# 阶段 4 的实现(在线程池里跑)
# ---------------------------------------------------------------------------

def _build_meshes(
    local: _LocalData,
    grid: terrain_svc.TerrainGrid,
    options: dict,
    progress: Callable,
    cancel_event: asyncio.Event,
) -> dict[str, Any]:
    layers: dict[str, Any] = {}

    layers["TERRAIN"] = build_terrain_mesh(grid)
    progress(0.05, "terrain mesh done")

    if local.greens:
        meshes = []
        for g in local.greens:
            m = build_water_surface(g.poly, grid, cut=0.03)  # 绿地贴地 +0.03 米
            if len(m.faces):
                meshes.append(m)
        if meshes:
            layers["GREEN"] = trimesh.util.concatenate(meshes)
    progress(0.15, "green areas done")

    if local.water_polys:
        meshes = []
        for w in local.water_polys:
            m = build_water_surface(w.poly, grid, cut=-0.25)
            if len(m.faces):
                meshes.append(m)
        if meshes:
            layers["WATER"] = trimesh.util.concatenate(meshes)
    if local.waterways:
        layers["WATER"] = _merge(
            layers.get("WATER"),
            build_layer_ribbons(local.waterways, -0.25, grid,
                                cancel_event=cancel_event),
        )
    progress(0.3, "water done")

    if local.buildings:
        def bprog(f: float, msg: str | None = None) -> None:
            progress(0.3 + 0.5 * f, msg)

        layers["BUILDING"] = extrude_buildings(
            local.buildings, grid, on_progress=bprog, cancel_event=cancel_event,
        )
    progress(0.85, "buildings done")

    if local.roads:
        def rprog(f: float, msg: str | None = None) -> None:
            progress(0.85 + 0.08 * f, msg)

        layers["ROAD"] = build_layer_ribbons(
            local.roads, LIFT_ROAD, grid, on_progress=rprog, cancel_event=cancel_event,
        )
    if local.railways:
        layers["RAILWAY"] = build_layer_ribbons(
            local.railways, LIFT_RAIL, grid, cancel_event=cancel_event,
        )
    progress(1.0, "meshes ready")
    return layers


def _merge(a, b):
    """把两个网格合成一个;哪边是空的(None 或没有面)都能应付。"""
    if a is None and b is None:
        return None
    if a is None:
        return b
    if b is None or len(b.faces) == 0:
        return a
    if len(a.faces) == 0:
        return b
    return trimesh.util.concatenate([a, b])
