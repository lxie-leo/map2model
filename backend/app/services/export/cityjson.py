"""导出 CityJSON 2.0(智慧城市圈的标准格式,专存城市 3D 模型)。

每栋楼一个方盒子(LoD1:不看屋顶造型,只看高度)。盒子要封闭:
底面朝天(朝下)、屋顶朝天(朝上)、四壁围一圈。
省空间的招:坐标不存一长串小数,而是先乘 1000 取整存毫米数,
文件头里记一笔"缩放 0.001 + 平移量"让软件自己还原——整数好压缩,
文件小一大截,毫米级精度也够用。
"""

from __future__ import annotations

import numpy as np

from app.services.export.registry import ExportContext, register
from app.utils.geom import ensure_ccw


@register("cityjson", "GIS", "CityJSON 2.0")
def export_cityjson(ctx: ExportContext) -> str:
    from app.services.export.registry import read_preview
    from app.services.projection import Projector
    from app.utils.caching import write_json_atomic

    preview = read_preview(ctx)
    meta = ctx.meta
    h0 = float(meta.get("median_h") or 0.0)  # 这块地的平均地面高度,楼从这儿往上长
    projector = Projector(tuple(meta["bbox"]))

    ctx.on_progress(0.2, "collecting buildings")
    verts: list[tuple[float, float, float]] = []
    city_objects: dict = {}
    n = 0
    for feat in preview.get("features", []):
        props = feat.get("properties", {})
        if props.get("layer") != "building":
            continue
        geom = feat.get("geometry", {})
        if geom.get("type") != "Polygon":
            continue
        ring = geom["coordinates"][0]
        if len(ring) < 4:
            continue
        h = float(props.get("height") or 6.0)
        xy = np.asarray(projector.to_local_many([(c[0], c[1]) for c in ring[:-1]]))
        # 内部坐标是以框选中心当原点的,写 CityJSON 前平移回真实 UTM 位置
        xy[:, 0] += projector.ox
        xy[:, 1] += projector.oy

        m = len(xy)
        # 点序统一成逆时针(从上往下看)。后面墙、底、顶的朝向全是按
        # "逆时针"推出来的,方向乱的话面就朝里了
        xy = ensure_ccw(xy)
        # 屋顶一圈正着存(面朝上);墙底那圈也正着存,拼底面的时候再倒着用(面朝下)
        roof_idx = list(range(len(verts), len(verts) + m))
        for i in range(m):
            verts.append((float(xy[i, 0]), float(xy[i, 1]), h0 + h))
        ground_fwd = list(range(len(verts), len(verts) + m))
        for i in range(m):
            verts.append((float(xy[i, 0]), float(xy[i, 1]), h0))
        ground_idx = ground_fwd[::-1]

        # 侧壁:轮廓每条边竖一块四边形墙皮。点按"底i→底j→顶j→顶i"排,
        # 逆时针轮廓这么走墙面正好朝外
        # CityJSON 的"面"写成环的列表(头一个环是外圈,后面可挂洞),
        # 所以每个面都要单独包一层 []
        surfaces: list[list[list[int]]] = [[ground_idx], [roof_idx]]
        for i in range(m):
            j = (i + 1) % m
            surfaces.append([[ground_fwd[i], ground_fwd[j], roof_idx[j], roof_idx[i]]])

        n += 1
        city_objects[f"building-{n}"] = {
            "type": "Building",
            "attributes": {
                "height": h,
                "measuredHeight": h,
                "name": props.get("name") or "",
            },
            "geometry": [{"type": "Solid", "lod": "1", "boundaries": [surfaces]}],
        }

    if not city_objects:
        raise ValueError("No building features, cannot generate CityJSON")

    ctx.on_progress(0.6, "quantizing vertices")
    arr = np.asarray(verts)
    translate = arr.min(axis=0)
    scale = 0.001  # 坐标存毫米级整数,换算精度足够、文件更小
    quantized = np.round((arr - translate) / scale).astype(np.int64)

    # 一样的点只存一份(CityJSON 的硬规矩,两栋楼共用的墙角也不能存两次),
    # inverse 记下"老编号对应新编号里的哪一个",回头好改面里的引用
    uniq, inverse = np.unique(quantized, axis=0, return_inverse=True)
    inverse = inverse.tolist()

    def remap(idx: list[int]) -> list[int]:
        return [inverse[i] for i in idx]

    for obj in city_objects.values():
        for geom in obj["geometry"]:
            geom["boundaries"] = [
                [[remap(ring) for ring in surface] for surface in shell]
                for shell in geom["boundaries"]
            ]

    cityjson = {
        "type": "CityJSON",
        "version": "2.0",
        "transform": {
            "scale": [scale, scale, scale],
            "translate": [float(v) for v in translate],
        },
        "metadata": {
            "referenceSystem": f"https://www.opengis.net/def/crs/EPSG/0/{projector.epsg}",
            "geographicalExtent": [
                float(arr[:, 0].min()), float(arr[:, 1].min()), float(arr[:, 2].min()),
                float(arr[:, 0].max()), float(arr[:, 1].max()), float(arr[:, 2].max()),
            ],
        },
        "CityObjects": city_objects,
        "vertices": uniq.astype(int).tolist(),
    }
    filename = f"{ctx.task_id}.city.json"
    write_json_atomic(ctx.export_dir / filename, cityjson)
    ctx.on_progress(1.0, f"cityjson ready ({len(city_objects)} buildings)")
    return filename
