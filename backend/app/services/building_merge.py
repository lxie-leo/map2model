"""OSM 建筑和 Overture 建筑合并去重。

两个来源都画了同一栋楼时留 OSM(标签、高度、名称通常更全),
Overture 只负责补 OSM 没画的缺。判"是不是同一栋"用两个标准,满足其一:
1. 交并比(IoU)够高——两边描的是差不多的形状;
2. 交集占较小那个的比例够高——一边把楼描小了/描大了,但明显是同一栋。

全部用 shapely 的 STRtree 做空间索引,两万栋楼的量级也是秒级。
"""

from __future__ import annotations

from shapely.errors import GEOSException
from shapely.geometry import Polygon
from shapely.strtree import STRtree

from app.services.osm_parse import BuildingFeature

# 判重阈值:IoU 或交集占比较小一方的比例
_MERGE_IOU = 0.55
_MERGE_CONTAIN = 0.8


def _to_poly(b: BuildingFeature) -> Polygon | None:
    """构多边形;构不成的(退化楼,点太少/环坏)返回 None 不参与判重。"""
    if len(b.outer) < 4:
        return None
    try:
        p = Polygon(b.outer, b.inners)
        return p if not p.is_empty else None
    except (GEOSException, ValueError):
        return None


def _inter_area(p: Polygon, q: Polygon) -> float:
    """两个多边形的交集面积,坏了就各自修一下再算。"""
    try:
        return p.intersection(q).area
    except (GEOSException, ValueError):
        return p.buffer(0).intersection(q.buffer(0)).area


def merge_buildings(
    osm: list[BuildingFeature], overture: list[BuildingFeature]
) -> tuple[list[BuildingFeature], int]:
    """合并两个来源的建筑列表,返回(合并结果, 被判定重复丢掉的 Overture 数)。

    OSM 在前(同一栋楼保留 OSM 版),Overture 补在后面。
    """
    if not osm:
        return list(overture), 0
    if not overture:
        return list(osm), 0

    # OSM 侧构不成多边形的退化楼:不进判重索引,原样保留交给下游既有过滤
    indexed: list[tuple[BuildingFeature, Polygon]] = []
    leftovers: list[BuildingFeature] = []
    for b in osm:
        p = _to_poly(b)
        if p is not None:
            indexed.append((b, p))
        else:
            leftovers.append(b)
    if not indexed:
        return leftovers + list(overture), 0

    osm_feats = [b for b, _ in indexed]
    osm_polys = [p for _, p in indexed]
    tree = STRtree(osm_polys)

    kept: list[BuildingFeature] = []
    dropped = 0
    for b in overture:
        p = _to_poly(b)
        if p is None:
            continue  # Overture 侧的退化楼直接不要(OSM 没有的话它也没建模价值)
        dup = False
        for i in tree.query(p):
            inter = _inter_area(p, osm_polys[i])
            if inter <= 0:
                continue
            smaller = min(p.area, osm_polys[i].area)
            union = p.area + osm_polys[i].area - inter
            if (inter / union if union > 0 else 0) >= _MERGE_IOU or (
                inter / smaller if smaller > 0 else 0
            ) >= _MERGE_CONTAIN:
                dup = True
                break
        if dup:
            dropped += 1
        else:
            kept.append(b)
    return osm_feats + kept + leftovers, dropped
