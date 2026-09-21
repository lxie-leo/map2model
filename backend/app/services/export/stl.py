"""导出 STL(3D 打印机的老搭档,只有三角形,别的啥都不带)。

把所有图层合成一个二进制 STL。STL 这格式没有材质、颜色、单位的概念,
就是一堆积木三角形,所以图层信息保不住,适合拿去打印或快速预览。
坐标按 Z-up 原样写(打印机都认 Z 朝上,不用转轴)。
"""

from __future__ import annotations

import logging

import numpy as np
import trimesh

from app.services.export.registry import ExportContext, load_hub, register

logger = logging.getLogger("app.export.stl")


@register("stl", "3D", "STL (triangle mesh)")
def export_stl(ctx: ExportContext) -> str:
    ctx.on_progress(0.3, "loading hub.glb")
    scene = load_hub(ctx)
    meshes = []
    for name in scene.geometry:
        mesh = scene.geometry[name]
        v = mesh.vertices[:, [0, 2, 1]].copy()  # hub 是 Y-up,换回 Z-up:Y/Z 互换,方向转一下就行
        v[:, 1] *= -1
        # 只是转方向不是镜像,三角形顶点顺序保持原样,面才朝外
        meshes.append(trimesh.Trimesh(vertices=v, faces=mesh.faces, process=False))
    if not meshes:
        raise ValueError("Scene is empty, cannot export STL")
    merged = trimesh.util.concatenate(meshes)

    # 打印软件喜欢"完全封闭"的模型(像不漏水的盒子)。建筑本来就是封的,
    # 但地形是张皮,底下漏着,所以在下面盖一块薄板把它兜住
    ctx.on_progress(0.7, "capping bottom")
    try:
        from shapely.geometry import MultiPolygon
        from trimesh.path.polygons import projected

        ground_z = float(np.percentile(merged.vertices[:, 2], 0.5)) - 1.0
        # trimesh 的投影:地块连成一片给 Polygon,被河/路切开的多块给
        # MultiPolygon,老版本还可能给列表——三种都接,逐块盖板
        poly = projected(merged, normal=[0, 0, 1])
        if isinstance(poly, (list, tuple)):
            poly = poly[0] if poly else None
        if poly is not None and not poly.is_empty:
            pieces = list(poly.geoms) if isinstance(poly, MultiPolygon) else [poly]
            caps = [
                trimesh.creation.extrude_polygon(p, 0.1, translate=[0, 0, ground_z])
                for p in pieces if not p.is_empty
            ]
            if caps:
                merged = trimesh.util.concatenate([merged, *caps])
    except Exception as exc:  # noqa: BLE001 - 盖不上就算了,多数查看器照样能开
        # 静默吞掉的话,缺依赖这种该修的问题也会被当成"盖不上"混过去
        # (实测就发生过:投影缺 rtree 空间索引,封底悄悄失效了很久)
        logger.warning("STL bottom cap skipped: %s", exc)
        ctx.on_progress(0.8, "bottom cap skipped")

    # STL 没有写单位的地方,切片软件一律当毫米看。内部坐标是米,
    # 出手前统一放大 1000 倍,不然 500 米的模型在切片软件里只有 0.5 米
    merged.apply_scale(1000.0)

    filename = f"{ctx.task_id}.stl"
    ctx.on_progress(0.9, "writing stl")
    merged.export(file_obj=str(ctx.export_dir / filename), file_type="stl")
    ctx.on_progress(1.0, "stl ready")
    return filename
