"""面状要素(水面/绿地):经纬度换成本地坐标。"""

from __future__ import annotations

from dataclasses import dataclass

from shapely.geometry import Polygon
from shapely.geometry.polygon import orient
from shapely.validation import make_valid

from app.services.osm_parse import PolyFeature
from app.services.projection import Projector


@dataclass
class PolyLocal:
    """一块面(以框选中心为原点,单位米)"""

    poly: Polygon
    kind: str      # water / wetland / forest / park / grass ...
    name: str | None


def to_local_polys(feats: list[PolyFeature], projector: Projector) -> list[PolyLocal]:
    # 裁剪矩形比框选区放宽 50 米:贴边的水面/绿地还能完整露出,不至于齐着框边被切平
    clip = projector.local_box(pad_m=50.0)
    out: list[PolyLocal] = []
    for pf in feats:
        outer = projector.to_local_many(pf.outer)
        inners = [projector.to_local_many(r) for r in pf.inners]
        if len(outer) < 3:
            continue
        poly = Polygon(outer, inners)
        if not poly.is_valid:
            poly = make_valid(poly)
        if poly.is_empty or poly.geom_type not in ("Polygon", "MultiPolygon"):
            continue
        if poly.geom_type == "MultiPolygon":
            poly = max(poly.geoms, key=lambda p: p.area)
        # relation 的成员可能延伸出框选区几十公里(比如整条黄浦江),
        # 裁到框附近,不然模型会往外飞出去老大一块
        poly = poly.intersection(clip)
        if not poly.is_valid:
            poly = make_valid(poly)
        if poly.is_empty or poly.geom_type not in ("Polygon", "MultiPolygon"):
            continue
        if poly.geom_type == "MultiPolygon":
            # 裁出来的不相邻地块都是框内真实存在的(两条分开的河),全部保留
            for p in poly.geoms:
                if p.area >= 2.0:
                    out.append(PolyLocal(poly=orient(p, sign=1.0), kind=pf.kind, name=pf.name))
            continue
        if poly.area < 2.0:
            continue
        out.append(PolyLocal(poly=orient(poly, sign=1.0), kind=pf.kind, name=pf.name))
    return out
