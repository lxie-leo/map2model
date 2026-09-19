"""导出格式注册表:登记每种格式的元信息、依赖、导出函数。

- hub 策略:3D 格式从任务目录的 hub.glb 读网格;GIS/2D 格式从
  preview.geojson(经纬度+属性)重建,坐标换算用 meta.json;
- 每种格式声明 requires(需要能 import 的 Python 包)和 blender
  (需要装 Blender),capabilities 据此上报,前端据此禁用按钮。
"""

from __future__ import annotations

import asyncio
import importlib
import importlib.util
import logging
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import anyio

from app.config import Settings

logger = logging.getLogger("app.export")


@dataclass
class FormatInfo:
    name: str                 # 格式标识(API 用)
    label: str                # 显示名(中文)
    group: str                # "3D" | "2D" | "GIS"
    requires: tuple[str, ...] = ()   # 依赖的 Python 包
    blender: bool = False     # 需要 Blender 可执行文件
    ext: str = ""             # 生成文件扩展名(默认用 name)


@dataclass
class ExportContext:
    """一次导出要用到的全部信息都装在这里,挨个传给导出函数。"""

    task_id: str
    task_dir: Path
    export_dir: Path          # 导出产物目录(已建好)
    meta: dict[str, Any]      # 任务 meta.json 内容
    settings: Settings
    on_progress: Callable[[float, str | None], None]  # (0~1, 消息)
    # 前端图层面板里勾掉的图层不进导出(存大写图层名)。
    # None = 全部都要(前端全开时走这条路,导出器可按"整包"快路径处理)
    layers: frozenset[str] | None = None


def load_hub(ctx: ExportContext):
    """读回 hub.glb 场景给 3D 导出器用;关掉的图层顺手删掉。

    全开(layers=None)时原样返回——GLB 导出可以直接复制文件,别的
    格式也不用白忙一场重建场景。"""
    import trimesh

    from app.services.mesh.scene import load_hub_scene

    scene = load_hub_scene(ctx.task_dir)
    if ctx.layers is None:
        return scene
    out = trimesh.Scene()
    for name, mesh in scene.geometry.items():
        if name in ctx.layers:
            out.add_geometry(mesh, node_name=name, geom_name=name)
    return out


def read_preview(ctx: ExportContext) -> dict:
    """读 preview.geojson 给 2D/GIS 导出器用;关掉的图层的要素不进结果。

    注意 geojson 里的图层名是小写(road/green/...),跟 3D 网格的大写
    名字是一套东西的两种写法,这里对齐一下。地形(TERRAIN)只在 3D
    网格里、不在矢量数据里,开关它不影响这份结果。"""
    from app.utils.caching import read_json

    data = read_json(ctx.task_dir / "preview.geojson")
    if ctx.layers is None:
        return data
    keep = {name.lower() for name in ctx.layers}
    feats = []
    for feat in data.get("features", []):
        layer = (feat.get("properties") or {}).get("layer")
        # 没写图层归属的要素(如果有)不掺和过滤,原样保留
        if not layer or layer.lower() in keep:
            feats.append(feat)
    # 拷一层再改:read_json 带缓存,直接改会把缓存内容也动了
    return {**data, "features": feats}


# 每种格式的导出函数:ExportContext -> 文件名(相对 export_dir)
Exporter = Callable[[ExportContext], Any]


_REGISTRY: dict[str, tuple[FormatInfo, Exporter]] = {}


def register(fmt: str, group: str, label: str, *,
             requires: tuple[str, ...] = (), blender: bool = False, ext: str = ""):
    """给导出函数戴上 @register 帽子,它就自动进了格式登记簿。"""

    def deco(fn: Exporter) -> Exporter:
        _REGISTRY[fmt] = (FormatInfo(fmt, label, group, requires, blender, ext or fmt), fn)
        return fn

    return deco


def FORMATS() -> dict[str, FormatInfo]:
    _ensure_loaded()
    return {name: info for name, (info, _) in _REGISTRY.items()}


def _ensure_loaded() -> None:
    """导入所有导出器模块,触发注册(只做一次)。"""
    if _REGISTRY:
        return
    import importlib as _il

    for mod in (
        "glb", "obj", "stl", "usdz", "blender",
        "dxf", "svg", "pdf", "png", "geojson",
        "gis", "kml", "cityjson", "tiles3d",
    ):
        try:
            _il.import_module(f"app.services.export.{mod}")
        except Exception:  # noqa: BLE001 - 单个导出器 import 失败不影响其它
            logger.exception("exporter module failed to load: %s", mod)


async def run_export(fmt: str, ctx: ExportContext) -> str:
    """真正干活:按格式名找到导出函数并执行,返回生成的文件名。
    有的导出函数是同步的、有的是异步的;同步的不能堵住事件循环,
    丢后台线程里跑。"""
    _ensure_loaded()
    if fmt not in _REGISTRY:
        raise KeyError(f"unknown export format: {fmt}")
    info, fn = _REGISTRY[fmt]
    for mod in info.requires:
        if importlib.util.find_spec(mod) is None:
            raise ImportError(
                f"格式 {info.label} 需要安装 Python 包 {mod}(pip install map2model-backend[{_extra_for(mod)}])"
            )
    if info.blender and find_blender(ctx.settings) is None:
        raise ImportError("未检测到 Blender,无法导出该格式(安装 Blender 后自动启用)")

    if asyncio.iscoroutinefunction(fn):
        return await fn(ctx)
    # 同步导出函数可能要跑好几秒(建网格、写大文件),直接在事件循环里
    # 跑会把整个服务卡住(连进度都推不出去),丢到工作线程里跑
    return await anyio.to_thread.run_sync(fn, ctx)


def _extra_for(module: str) -> str:
    return {"geopandas": "gis", "pyogrio": "gis", "pxr": "usd"}.get(module, "dev")


def _module_available(mod: str) -> bool:
    try:
        return importlib.util.find_spec(mod) is not None
    except (ImportError, ValueError):
        return False


_blender_cache: str | None | bool = False  # False = 还没找过


def find_blender(settings: Settings) -> str | None:
    """找 Blender 可执行文件:PATH 里找,再翻 Program Files 的多版本目录。"""
    global _blender_cache
    if settings.blender_path not in ("auto", ""):
        return settings.blender_path if Path(settings.blender_path).exists() else None
    if _blender_cache is not False:
        return _blender_cache  # type: ignore[return-value]
    found = shutil.which("blender")
    if not found:
        # PATH 里没有,翻 Program Files 下各版本的 Blender 目录
        hits: list[Path] = []
        for base in (
            Path(r"C:\Program Files\Blender Foundation"),
            Path(r"C:\Program Files (x86)\Blender Foundation"),
        ):
            if base.is_dir():
                hits += base.glob("*/blender.exe")
        if hits:
            found = str(max(hits, key=lambda p: p.parent.name))  # 取版本号最新的
            logger.info("blender detected: %s", found)
    _blender_cache = found
    if found and not found.startswith("C:"):
        logger.info("blender detected: %s", found)  # Program Files 的已在上面记过
    return found


def capabilities(settings: Settings) -> dict[str, Any]:
    """上报每种格式是否可用(前端据此点亮/禁用导出按钮)。"""
    _ensure_loaded()
    blender_ok = find_blender(settings) is not None
    fmts: dict[str, bool] = {}
    for name, (info, _) in _REGISTRY.items():
        ok = all(_module_available(m) for m in info.requires)
        if ok and info.blender:
            ok = blender_ok
        fmts[name] = ok
    groups: dict[str, list[str]] = {"3D": [], "2D": [], "GIS": []}
    for name, (info, _) in _REGISTRY.items():
        groups.setdefault(info.group, []).append(name)
    return {
        "formats": fmts,
        "groups": groups,
        "blender_path": find_blender(settings),
    }
