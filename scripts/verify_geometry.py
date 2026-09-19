# -*- coding: utf-8 -*-
"""几何修复后的真数据验证:进程内跑一遍管线,再把所有 3D/GIS 格式导一遍,
逐个检查"面朝向/索引/对齐/打包"这些这次修过的点。

用法(在 backend 目录):
    .\\.venv\\Scripts\\python.exe ..\\scripts\\verify_geometry.py
"""
from __future__ import annotations

import asyncio
import json
import shutil
import struct
import sys
import zipfile
from pathlib import Path

import numpy as np

BACKEND = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND))
import os

os.chdir(BACKEND)

OK = []
FAIL = []


def check(name: str, cond: bool, detail: str = "") -> None:
    (OK if cond else FAIL).append(name)
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail else ""))


async def main() -> None:
    from app.config import Settings
    from app.services import pipeline
    from app.services.export import registry
    from app.services.mesh.scene import LAYER_ORDER, load_hub_scene

    task_id = "geomchk"
    task_dir = BACKEND / "data" / "tasks" / task_id
    if task_dir.exists():
        shutil.rmtree(task_dir)
    task_dir.mkdir(parents=True)

    settings = Settings()
    ctx = pipeline.PipelineContext(
        task_id=task_id,
        task_dir=task_dir,
        bbox=(121.4900, 31.2340, 121.4970, 31.2385),  # 上海小框(Overpass 有缓存)
        options={},
        cancel_event=asyncio.Event(),
        progress=lambda *a: None,
        warn=lambda msg: print("  warn:", msg),
        settings=settings,
    )
    stats = await pipeline.run_pipeline(ctx)
    print("stats:", {k: stats[k] for k in ("buildings", "roads") if k in stats})
    check("pipeline completes", stats.get("buildings", 0) > 0)

    # ---- hub.glb:各层面朝向 ----
    scene = load_hub_scene(task_dir)
    flat_up = {"TERRAIN", "GREEN", "WATER", "ROAD", "RAILWAY"}  # 平铺层,该朝上(Y-up 里是 +Y)
    # 框选区本地尺寸(hub 是 Y-up:x=本地x,z=−本地y),图层最远只许出头这么多米
    from app.services.projection import Projector

    proj = Projector((121.4900, 31.2340, 121.4970, 31.2385))
    lim_x = proj.width_m / 2 + 200
    lim_y = proj.height_m / 2 + 200
    for name in scene.geometry:
        m = scene.geometry[name]
        ny = m.face_normals[:, 1]
        down = (ny < -0.5).sum()
        if name == "BUILDING":
            # 楼没有底面,朝下的三角应该几乎没有(顶朝上、墙朝四周)
            check(f"glb BUILDING no bottom faces", down <= max(2, len(m.faces) // 500),
                  f"{down}/{len(m.faces)}")
        elif name in flat_up:
            check(f"glb {name} all faces up", down == 0, f"{down} down / {len(m.faces)}")
        far = np.abs(m.vertices[:, 0]).max(), np.abs(m.vertices[:, 2]).max()
        check(f"glb {name} inside bbox", far[0] <= lim_x and far[1] <= lim_y,
              f"x±{far[0]:.0f}m y±{far[1]:.0f}m (限 {lim_x:.0f}/{lim_y:.0f})")

    # ---- 逐格式导出 ----
    export_dir = task_dir / "exports" / "chk"
    export_dir.mkdir(parents=True, exist_ok=True)
    from app.services.export.registry import ExportContext

    for fmt in ("glb", "obj", "stl", "cityjson", "usdz", "3dtiles", "pdf",
                "svg", "png", "dxf", "geojson", "kml", "kmz", "gpkg", "shp"):
        ectx = ExportContext(task_id=task_id, task_dir=task_dir, export_dir=export_dir,
                             meta=json.loads((task_dir / "meta.json").read_text(encoding="utf-8")),
                             settings=settings, on_progress=lambda *a: None)
        try:
            fname = await registry.run_export(fmt, ectx)
            check(f"export {fmt}", True, fname)
        except Exception as exc:  # noqa: BLE001
            check(f"export {fmt}", False, repr(exc))
            continue

        p = export_dir / fname
        if fmt in ("svg", "png", "dxf", "kml", "kmz", "gpkg", "shp"):
            # 这些格式做两件事:文件非空;要素数量抽查(gpkg/shp 用 geopandas 数)
            check(f"{fmt} file not empty", p.stat().st_size > 100, f"{p.stat().st_size} B")
            if fmt in ("gpkg", "shp"):
                try:
                    import geopandas as gpd

                    n = len(gpd.read_file(str(p)))
                    check(f"{fmt} has features", n > 0, f"{n} features")
                except Exception as exc:  # noqa: BLE001
                    check(f"{fmt} has features", False, repr(exc))
            continue
        if fmt == "obj":
            import trimesh
            m = trimesh.load(str(p), force="mesh", process=False)
            down = int((m.face_normals[:, 2] < -0.5).sum())  # OBJ 是 Z-up,朝下看 z 列
            check("obj faces mostly up", down <= max(2, len(m.faces) // 500),
                  f"{down} down / {len(m.faces)}")
        elif fmt == "geojson":
            # 导出的 GeoJSON 是经纬度:所有坐标都该落在框选区附近(±0.02°,
            # 留出放宽 50 米的余量)。要是投影/裁剪/回投哪里坏了,这里最先暴露
            data = json.loads(p.read_text(encoding="utf-8"))
            lons, lats = [], []
            for f in data.get("features", []):
                g = f.get("geometry")
                if g is None:
                    continue

                def walk(node):
                    if isinstance(node, (list, tuple)) and len(node) >= 2 \
                            and isinstance(node[0], (int, float)):
                        lons.append(node[0]); lats.append(node[1])
                    elif isinstance(node, (list, tuple)):
                        for x in node:
                            walk(x)

                walk(g["coordinates"])
            bbox = (121.4900, 31.2340, 121.4970, 31.2385)
            ok = (min(lons) >= bbox[0] - 0.02 and max(lons) <= bbox[2] + 0.02
                  and min(lats) >= bbox[1] - 0.02 and max(lats) <= bbox[3] + 0.02)
            check("geojson coords inside bbox", ok and len(lons) > 0,
                  f"lon {min(lons):.4f}~{max(lons):.4f} lat {min(lats):.4f}~{max(lats):.4f}")
        elif fmt == "stl":
            import trimesh
            m = trimesh.load(str(p), force="mesh", process=False)
            # 单位毫米:尺寸该是米制 bbox 的几百~上千倍
            ext = m.bounds[1] - m.bounds[0]
            check("stl in millimeters", ext.max() > 100.0, f"max extent {ext.max():.0f}")
            # 封底板真的盖上了:底板朝下,朝下的面就该有一批(没盖的话全场景没有朝下面)
            down = int((m.face_normals[:, 2] < -0.5).sum())
            check("stl bottom cap present", down > 50, f"{down} down faces")
        elif fmt == "usdz":
            with zipfile.ZipFile(p) as zf:
                info = zf.infolist()[0]
                # 本地头 30 字节 + 文件名 + 扩展字段之后才是文件内容
                with open(p, "rb") as f:
                    hdr = f.read(30)
                    name_len, extra_len = struct.unpack("<HH", hdr[26:30])
                    data_off = 30 + name_len + extra_len
                check("usdz first file is usdc + stored",
                      info.filename.endswith(".usdc") and info.compress_type == 0)
                check("usdz 64-byte aligned", data_off % 64 == 0, f"data at {data_off}")
        elif fmt == "cityjson":
            data = json.loads(p.read_text(encoding="utf-8"))
            sc = data["transform"]["scale"][0]
            tr = data["transform"]["translate"]
            verts = [np.array([v[0]*sc+tr[0], v[1]*sc+tr[1], v[2]*sc+tr[2]])
                     for v in data["vertices"]]
            bad = 0
            total = 0
            for obj in data["CityObjects"].values():
                shell = obj["geometry"][0]["boundaries"][0]
                for ring_idx in shell:
                    pts = [verts[i] for i in ring_idx[0]]
                    n = np.zeros(3)
                    for k in range(len(pts)):
                        n += np.cross(pts[k], pts[(k + 1) % len(pts)])
                    total += 1
                    zs = [q[2] for q in pts]
                    h0 = min(v[2] for v in verts)
                    if min(zs) > h0 + 1:       # 顶
                        if n[2] <= 0:
                            bad += 1
                    elif max(zs) < h0 + 1:     # 底
                        if n[2] >= 0:
                            bad += 1
            check("cityjson all surfaces wound outward", bad == 0, f"{bad}/{total} bad")
        elif fmt == "3dtiles":
            with zipfile.ZipFile(p) as zf:
                names = zf.namelist()
                check("3dtiles zip has tileset + glbs",
                      "tileset.json" in names and any(n.endswith(".glb") for n in names),
                      f"{len(names)} files")
                check("3dtiles zip excludes itself",
                      not any(n.endswith(".zip") for n in names))
                ts = json.loads(zf.read("tileset.json"))
                check("3dtiles root transform is 4x4", len(ts["root"]["transform"]) == 16)

    print()
    print(f"== {len(OK)} pass, {len(FAIL)} fail ==")
    if FAIL:
        print("FAILED:", *FAIL, sep="\n  - ")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
