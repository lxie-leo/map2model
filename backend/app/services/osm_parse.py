"""把 Overpass 返回的 JSON 解析成结构化要素(建筑/道路/铁路/水系/绿地)。

Overpass 带 `out geom` 时,每条 way 直接附上坐标,不用再回头查节点;
relation(比如带内院的建筑、大公园)的成员线段也各自带坐标,
这里负责把它们首尾接起来拼成完整的圈:外圈当形状本体,内圈负责在中间挖洞。
"""

from __future__ import annotations

import logging
import statistics
from dataclasses import dataclass, field

from shapely.geometry import LineString, MultiLineString
from shapely.ops import linemerge, polygonize

logger = logging.getLogger("app.osm_parse")

# 道路宽度兜底表(米):先看 width 标签,再看 lanes×3.5,都没有就用这张表
ROAD_WIDTH: dict[str, float] = {
    "motorway": 20.0, "motorway_link": 12.0,
    "trunk": 16.0, "trunk_link": 10.0,
    "primary": 12.0, "primary_link": 8.0,
    "secondary": 10.0, "secondary_link": 7.0,
    "tertiary": 8.0, "tertiary_link": 6.0,
    "residential": 6.5, "living_street": 5.5,
    "unclassified": 5.0, "service": 3.5,
    "pedestrian": 3.0, "footway": 1.8, "path": 1.2,
    "cycleway": 2.0, "steps": 1.5, "track": 2.5,
}

RAIL_WIDTH: dict[str, float] = {
    "rail": 4.0, "light_rail": 4.0, "subway": 4.0,
    "tram": 2.5, "monorail": 3.0, "narrow_gauge": 3.0, "funicular": 3.0,
}

WATERWAY_WIDTH: dict[str, float] = {
    "river": 18.0, "stream": 4.0, "canal": 12.0, "ditch": 2.5, "drain": 2.5,
}


@dataclass
class BuildingFeature:
    """一栋建筑:外环 + 内环(内院/天井),坐标是经纬度"""

    outer: list[tuple[float, float]]
    inners: list[list[tuple[float, float]]] = field(default_factory=list)
    height: float | None = None      # height 标签(米)
    levels: float | None = None      # building:levels 标签(层数)
    name: str | None = None

    @property
    def ring(self) -> list[tuple[float, float]]:
        return self.outer


@dataclass
class LineFeature:
    """一条线状要素(道路/铁路/河流),坐标是经纬度"""

    coords: list[tuple[float, float]]
    kind: str                        # 具体类别,如 residential / rail / river
    width: float | None = None       # 已解析的宽度(米),None 表示待回填
    bridge: bool = False
    name: str | None = None


@dataclass
class PolyFeature:
    """一块面状要素(湖泊/湿地/森林/公园等),坐标是经纬度"""

    outer: list[tuple[float, float]]
    inners: list[list[tuple[float, float]]] = field(default_factory=list)
    kind: str = "water"              # water / wetland / wood / scrub / forest / grass / park ...
    name: str | None = None


@dataclass
class Features:
    """一个区域解析出的全部要素"""

    buildings: list[BuildingFeature] = field(default_factory=list)
    roads: list[LineFeature] = field(default_factory=list)
    railways: list[LineFeature] = field(default_factory=list)
    waterways: list[LineFeature] = field(default_factory=list)
    water_polys: list[PolyFeature] = field(default_factory=list)
    greens: list[PolyFeature] = field(default_factory=list)


def _parse_number(value) -> float | None:
    """OSM 标签里的数字可能是 '12 m' 这种带单位的,取前面的数字部分"""
    if value is None:
        return None
    try:
        return float(str(value).split()[0].removesuffix("m").removesuffix("."))
    except (ValueError, IndexError):
        return None


def _way_coords(el: dict) -> list[tuple[float, float]]:
    geom = el.get("geometry") or []
    return [(p["lon"], p["lat"]) for p in geom if "lon" in p and "lat" in p]


def _members_to_rings(el: dict) -> tuple[list[list[tuple]], list[list[tuple]]]:
    """把 relation 成员的线段拼成闭合的圈:外圈一组、内圈(挖洞用)一组。

    拼法:先让 shapely 把同一边的线段首尾接起来(linemerge),
    再围成闭合的面(polygonize)。
    """
    outer_lines, inner_lines = [], []
    for m in el.get("members", []):
        geom = m.get("geometry")
        if not geom:
            continue
        coords = [(p["lon"], p["lat"]) for p in geom if "lon" in p and "lat" in p]
        if len(coords) < 2:
            continue
        (inner_lines if m.get("role") == "inner" else outer_lines).append(coords)

    def _to_rings(lines: list[list[tuple]]) -> list[list[tuple]]:
        if not lines:
            return []
        merged = linemerge(MultiLineString([LineString(c) for c in lines]))
        # linemerge 的结果可能是单条线,也可能是多条线的集合,统一变成列表
        if isinstance(merged, LineString):
            lines_iter = [merged]
        else:
            lines_iter = list(merged.geoms)
        rings = []
        for poly in polygonize(lines_iter):
            rings.append(list(poly.exterior.coords)[:-1])  # 去掉首尾重复的闭合点
        if not rings:  # 拼不成环(数据不完整),记条日志跳过
            logger.debug("relation %s: ring assembly failed for %d lines", el.get("id"), len(lines))
        return rings

    return _to_rings(outer_lines), _to_rings(inner_lines)


def _assign_inners(outers: list[list[tuple]], inners: list[list[tuple]]) -> list[list[list[tuple]]]:
    """一块地可能分成好几片(比如带岛的多片森林):每个外环都是独立的一块。

    内环是挖洞用的(湖心的岛、楼里的院子),得看它落在哪一片里面,
    就跟着哪一片走;哪片都不在的内环是数据画歪了,扔掉别硬塞。
    """
    from shapely.geometry import Polygon

    polys = [Polygon(o) for o in outers]
    groups: list[list[list[tuple]]] = [[] for _ in outers]
    for ring in inners:
        point = Polygon(ring).representative_point()
        for i, poly in enumerate(polys):
            if poly.contains(point):
                groups[i].append(ring)
                break
    return groups


def parse_osm(payload: dict) -> Features:
    """解析 Overpass 响应,产出各图层要素(坐标仍是经纬度)"""
    feats = Features()
    for el in payload.get("elements", []):
        etype, tags = el.get("type"), el.get("tags", {})
        if not tags:
            continue

        if etype == "way":
            coords = _way_coords(el)
            if len(coords) < 2:
                continue
            _parse_way(el, tags, coords, feats)
        elif etype == "relation":
            _parse_relation(el, tags, feats)
    return feats


def _parse_way(el: dict, tags: dict, coords: list, feats: Features) -> None:
    name = tags.get("name")

    if "building" in tags:
        feats.buildings.append(
            BuildingFeature(
                outer=coords,
                height=_parse_number(tags.get("height") or tags.get("building:height")),
                levels=_parse_number(tags.get("building:levels")),
                name=name,
            )
        )
        return

    if "highway" in tags:
        hw = tags["highway"]
        if tags.get("tunnel") not in (None, "no"):
            return  # 隧道不生成模型
        # 不在宽度表里的道路类别统一按 unclassified 处理,保证有默认宽度
        hw_norm = hw if hw in ROAD_WIDTH else "unclassified"
        feats.roads.append(
            LineFeature(
                coords=coords, kind=hw_norm,
                width=_resolve_road_width(tags, hw_norm),
                bridge=tags.get("bridge") not in (None, "no"),
                name=name,
            )
        )
        return

    if "railway" in tags:
        rw = tags["railway"]
        if rw in RAIL_WIDTH:
            if tags.get("tunnel") not in (None, "no"):
                return  # 地下铁路不生成模型
            feats.railways.append(
                LineFeature(
                    coords=coords, kind=rw,
                    width=_parse_number(tags.get("width")) or RAIL_WIDTH[rw],
                    bridge=tags.get("bridge") not in (None, "no"),
                    name=name,
                )
            )
        return

    if "waterway" in tags:
        ww = tags["waterway"]
        if ww in WATERWAY_WIDTH:
            feats.waterways.append(
                LineFeature(
                    coords=coords, kind=ww,
                    width=_parse_number(tags.get("width")) or WATERWAY_WIDTH[ww],
                    name=name,
                )
            )
        return

    # 面状要素:way 本身就是环(首尾坐标相同)
    if len(coords) >= 4:
        ring = coords[:-1] if coords[0] == coords[-1] else coords
        kind = _poly_kind(tags)
        if kind:
            if kind in ("water", "wetland"):
                feats.water_polys.append(PolyFeature(outer=ring, kind=kind, name=name))
            else:
                feats.greens.append(PolyFeature(outer=ring, kind=kind, name=name))


def _poly_kind(tags: dict) -> str | None:
    """判断 way/relation 属于哪类面状要素,返回类别名;不属于则返回 None"""
    if tags.get("natural") in ("water", "wetland", "wood", "scrub"):
        return tags["natural"]
    if tags.get("landuse") in ("forest", "grass", "meadow", "recreation_ground",
                               "village_green", "cemetery", "farmland", "orchard"):
        return tags["landuse"]
    if tags.get("leisure") in ("park", "garden", "playground", "pitch", "golf_course"):
        return tags["leisure"]
    return None


def _parse_relation(el: dict, tags: dict, feats: Features) -> None:
    if "building" in tags:
        outers, inners = _members_to_rings(el)
        # 一栋楼画成好几块的(建筑群 relation),每块单独算一栋,别只留第一块
        for outer, my_inners in zip(outers, _assign_inners(outers, inners)):
            feats.buildings.append(
                BuildingFeature(
                    outer=outer, inners=my_inners,
                    height=_parse_number(tags.get("height") or tags.get("building:height")),
                    levels=_parse_number(tags.get("building:levels")),
                    name=tags.get("name"),
                )
            )
        return

    if "waterway" in tags:
        outers, inners = _members_to_rings(el)
        for outer, my_inners in zip(outers, _assign_inners(outers, inners)):
            feats.water_polys.append(PolyFeature(outer=outer, inners=my_inners, kind="water", name=tags.get("name")))
        return

    kind = _poly_kind(tags)
    if kind:
        outers, inners = _members_to_rings(el)
        for outer, my_inners in zip(outers, _assign_inners(outers, inners)):
            pf = PolyFeature(outer=outer, inners=my_inners, kind=kind, name=tags.get("name"))
            (feats.water_polys if kind in ("water", "wetland") else feats.greens).append(pf)


def _resolve_road_width(tags: dict, hw: str) -> float | None:
    """道路宽度:width 标签优先,其次 lanes×3.5,最后类别默认值"""
    w = _parse_number(tags.get("width"))
    if w and w > 0:
        return w
    lanes = _parse_number(tags.get("lanes"))
    if lanes and lanes > 0:
        return lanes * 3.5
    return ROAD_WIDTH.get(hw)


def resolve_building_heights(buildings: list[BuildingFeature]) -> None:
    """坑:OSM 里建筑的高度经常没人填,这里给它们补上。

    顺序:height 标签优先 → 没有就按楼层数 ×3.2 米估 → 再不行用已知高度的中位数
    → 全都没有就按 6 米算。
    """
    known = [
        b.height for b in buildings if b.height and b.height > 0
    ]
    if not known:
        known = [b.levels * 3.2 for b in buildings if b.levels and b.levels > 0]
    median = statistics.median(known) if known else None
    for b in buildings:
        if b.height and b.height > 0:
            continue
        if b.levels and b.levels > 0:
            b.height = round(b.levels * 3.2, 1)
        elif median:
            b.height = round(median, 1)
        else:
            b.height = 6.0
