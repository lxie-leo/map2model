"""导出 DXF(AutoCAD 的图纸格式):用 ezdxf 库写 R2018 版,单位米。

CAD 里图层就是一摞透明描图纸,同类东西放同一层,关灯就整层隐藏,
所以建筑/道路/铁路/水/绿地各归各层,名字统一 M2M_ 前缀:
M2M_BUILDING / M2M_ROAD / M2M_RAILWAY / M2M_WATER / M2M_GREEN。
建筑写成闭合的多段线,在 CAD 里选中一拉就能挤出成体块。
坐标是局部米制(X 东 Y 北,原点=框选中心),进 CAD 后量出来的就是真实米数。
"""

from __future__ import annotations

import ezdxf

from app.services.export.registry import ExportContext, register
from app.services.projection import Projector

# 图层名 → AutoCAD 老色号(ACI,1~255 的经典编号,1红2黄3绿4青…沿用就是了)
_DXF_LAYERS = {
    "M2M_BUILDING": 8,   # 深灰
    "M2M_ROAD": 7,       # 白/黑(随背景)
    "M2M_RAILWAY": 6,    # 紫
    "M2M_WATER": 4,      # 青
    "M2M_GREEN": 3,      # 绿
}


@register("dxf", "2D", "DXF (AutoCAD)")
def export_dxf(ctx: ExportContext) -> str:
    from app.services.export.registry import read_preview

    ctx.on_progress(0.2, "reading preview")
    preview = read_preview(ctx)
    projector = Projector(tuple(ctx.meta["bbox"]))

    doc = ezdxf.new("R2018", setup=False)
    # 单位声明:DXF 里 6 代表米,写别的 AutoCAD 会当成英寸,模型直接缩水 2.54 倍。
    # ezdxf 新版把枚举名改来改去,干脆直接写数字最稳
    doc.header["$INSUNITS"] = 6
    msp = doc.modelspace()
    for name, color in _DXF_LAYERS.items():
        doc.layers.add(name=name, color=color)

    def layer_of(kind: str) -> str:
        return {
            "building": "M2M_BUILDING", "road": "M2M_ROAD", "railway": "M2M_RAILWAY",
            "water": "M2M_WATER", "green": "M2M_GREEN",
        }[kind]

    ctx.on_progress(0.5, "writing entities")
    for feat in preview.get("features", []):
        props = feat.get("properties", {})
        kind = props.get("layer")
        if kind not in ("building", "road", "railway", "water", "green"):
            continue
        geom = feat.get("geometry", {})
        layer = layer_of(kind)
        if geom.get("type") == "Polygon":
            ring = geom["coordinates"][0]
            pts = projector.to_local_many([(c[0], c[1]) for c in ring])
            closed = kind in ("building", "water", "green")  # 有面积的才闭合首尾
            msp.add_lwpolyline(pts, close=closed, dxfattribs={"layer": layer})
        elif geom.get("type") == "LineString":
            pts = projector.to_local_many([(c[0], c[1]) for c in geom["coordinates"]])
            msp.add_lwpolyline(pts, dxfattribs={"layer": layer})

    filename = f"{ctx.task_id}.dxf"
    doc.saveas(ctx.export_dir / filename)
    ctx.on_progress(1.0, "dxf ready")
    return filename
