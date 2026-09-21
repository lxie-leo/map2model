"""建筑:经纬度换成本地坐标,坏轮廓能修就修,数量超了按面积砍。"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
from shapely.geometry import Polygon
from shapely.geometry.polygon import orient
from shapely.validation import make_valid

from app.services.osm_parse import BuildingFeature
from app.services.projection import Projector

logger = logging.getLogger("app.vector.buildings")


@dataclass
class BuildingLocal:
    """一栋建筑(以框选中心为原点,X 往东 Y 往北,单位米)"""

    poly: Polygon      # 修好方向的外环+内环(外环逆时针)
    height: float      # 要顶起来多高(米)
    name: str | None


def to_local_buildings(
    buildings: list[BuildingFeature],
    projector: Projector,
    *,
    max_buildings: int,
    warn=None,
) -> list[BuildingLocal]:
    out: list[BuildingLocal] = []
    for bf in buildings:
        outer = projector.to_local_many(bf.outer)
        inners = [projector.to_local_many(r) for r in bf.inners]
        if len(outer) < 3:
            continue
        poly = Polygon(outer, inners)
        if not poly.is_valid:
            poly = make_valid(poly)  # 自相交等坏数据,能修就修
        if poly.is_empty or poly.geom_type not in ("Polygon", "MultiPolygon"):
            continue
        if poly.geom_type == "MultiPolygon":
            poly = max(poly.geoms, key=lambda p: p.area)  # 多块就取最大那块
        poly = orient(poly, sign=1.0)  # 外环转逆时针
        if poly.area < 1.0:  # 小于 1 平方米的碎块直接扔
            continue
        out.append(BuildingLocal(poly=poly, height=bf.height or 6.0, name=bf.name))

    # 超上限时按面积从大到小保留(大建筑更重要)
    if len(out) > max_buildings:
        out.sort(key=lambda b: b.poly.area, reverse=True)
        dropped = len(out) - max_buildings
        out = out[:max_buildings]
        if warn:
            warn(f"Building count over limit: kept the largest {max_buildings} by area, "
                 f"dropped {dropped} small buildings")
    return out


def ring_xy(poly: Polygon) -> np.ndarray:
    """外环坐标数组(去掉闭合点)。"""
    return np.asarray(poly.exterior.coords)[:-1]
