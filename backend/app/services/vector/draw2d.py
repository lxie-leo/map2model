"""2D 制图:把预览 GeoJSON 变成一份"画什么、什么颜色、画多粗"的指令清单,
不带任何像素概念。

SVG / PDF / PNG / DXF 四种导出都吃同一份 DrawDoc,风格才不会跑偏。
图层颜色全在这里定(3D 场景用同一套色调,两边看着是同一张图)。
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from app.services.projection import Projector

# ---- 统一调色板(六图层 + 纸底色) ----
PALETTE = {
    "background": "#f2efe9",   # 纸底色
    "terrain": "#c8c3ba",
    "green": "#b7d6a8",
    "green_edge": "#9cc48c",
    "water": "#a8cfe8",
    "water_edge": "#8ab8da",
    "building": "#ddd5c9",
    "building_edge": "#8f887e",
    "road_casing": "#b9b4ad",  # 路的外描边(白路在底色上靠它显形)
    "road_fill": "#ffffff",
    "railway": "#4a4a4a",
    "wetland": "#bcd9e8",
}
PALETTE_3D = {
    "TERRAIN": "#c8c3ba",
    "BUILDING": "#ded7cb",
    "ROAD": "#a8a8a8",
    "RAILWAY": "#6b6f73",
    "WATER": "#a8cfe8",
    "GREEN": "#b7d6a8",
}

# 图例(和前端图层开关同一套说法);条目顺序和下面 _LEGEND_LAYERS 一一对应
LEGEND = [
    ("绿地", PALETTE["green"]),
    ("水体", PALETTE["water"]),
    ("建筑", PALETTE["building"]),
    ("道路", PALETTE["road_fill"]),
    ("铁路", PALETTE["railway"]),
]

_LEGEND_LAYERS = ("green", "water", "building", "road", "railway")


def legend_for(doc: DrawDoc) -> list[tuple[str, str]]:
    """导出用的图例:只列画布上真正画出来的图层。

    前端关掉某些图层再导出时,图上已经没有它们,图例还列着就是骗人了。"""
    used = {it.layer for it in doc.items}
    return [item for item, layer in zip(LEGEND, _LEGEND_LAYERS) if layer in used]


@dataclass
class DrawItem:
    """一条绘制指令:多边形(带填充/描边)或折线(只有描边)。

    kind: "polygon" | "polyline"
    pts: (n, 2) 局部米制坐标(x 向东, y 向北)
    stroke_width 单位是米,导出器按各自比例换算成像素/点。
    layer: 便于渲染器特判(比如道路画"灰边白芯"两层)。
    """

    kind: str
    pts: np.ndarray
    fill: str | None = None
    stroke: str | None = None
    stroke_width: float = 0.0
    layer: str = ""
    dash: bool = False


@dataclass
class DrawDoc:
    """一份完整的 2D 地图绘制文档。items 顺序即遮挡顺序(先画的在底下)。"""

    items: list[DrawItem] = field(default_factory=list)
    width_m: float = 0.0
    height_m: float = 0.0


def draw_doc_from_preview(preview: dict, meta: dict) -> DrawDoc:
    """从任务的 preview.geojson + meta.json 重建绘制文档(导出器入口)。"""
    projector = Projector(tuple(meta["bbox"]))
    doc = DrawDoc(width_m=meta["width_m"], height_m=meta["height_m"])

    # 先按图层分桶,再按遮挡顺序倒进 doc:
    # 绿地 → 水面 → 建筑 → 道路 → 铁路(道路的灰边由渲染器叠画)
    greens: list[DrawItem] = []
    waters: list[DrawItem] = []
    buildings: list[DrawItem] = []
    roads: list[DrawItem] = []
    railways: list[DrawItem] = []

    for feat in preview.get("features", []):
        props = feat.get("properties", {})
        layer = props.get("layer")
        geom = feat.get("geometry", {})
        gtype = geom.get("type")

        if gtype == "Polygon":
            rings = [
                np.asarray(projector.to_local_many([(c[0], c[1]) for c in ring]))
                for ring in geom.get("coordinates", [])
            ]
            if not rings:
                continue
            item = DrawItem(
                kind="polygon", pts=rings[0], layer=layer,
                fill={"green": PALETTE["green"], "water": PALETTE["water"],
                      "building": PALETTE["building"]}.get(layer, "#cccccc"),
                stroke={"green": PALETTE["green_edge"], "water": PALETTE["water_edge"],
                        "building": PALETTE["building_edge"]}.get(layer),
                stroke_width=0.3,
            )
            if layer == "green":
                greens.append(item)
            elif layer == "water":
                waters.append(item)
            elif layer == "building":
                buildings.append(item)
        elif gtype == "LineString":
            pts = np.asarray(projector.to_local_many(
                [(c[0], c[1]) for c in geom.get("coordinates", [])]
            ))
            if len(pts) < 2:
                continue
            if layer == "water":
                waters.append(DrawItem("polyline", pts, stroke=PALETTE["water"],
                                       stroke_width=max(float(props.get("width") or 2), 1.5),
                                       layer="water"))
            elif layer == "road":
                roads.append(DrawItem("polyline", pts, stroke=PALETTE["road_fill"],
                                      stroke_width=float(props.get("width") or 3.0),
                                      layer="road"))
            elif layer == "railway":
                railways.append(DrawItem("polyline", pts, stroke=PALETTE["railway"],
                                         stroke_width=max(float(props.get("width") or 2), 1.2),
                                         layer="railway", dash=True))

    doc.items = greens + waters + buildings + roads + railways
    return doc
