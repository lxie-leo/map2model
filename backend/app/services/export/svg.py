"""SVG 导出:矢量图,Inkscape / Illustrator / Figma 都能开。"""

from __future__ import annotations

from app.services.export.registry import ExportContext, register
from app.services.vector.draw2d import PALETTE, DrawDoc, draw_doc_from_preview, legend_for


def _fmt(v: float) -> str:
    # 保留两位小数再去掉尾巴上的 0("3.50"→"3.5","2.00"→"2"),文件能小一圈
    return f"{v:.2f}".rstrip("0").rstrip(".")


def _polyline_svg(pts, fill: str | None, stroke: str | None, sw: float, dash: bool) -> str:
    # y 取负:地图 Y 向北为正,SVG 的 Y 却向下长,不翻的话图是倒的
    d = "M " + " L ".join(f"{_fmt(x)},{_fmt(-y)}" for x, y in pts) + (" Z" if fill else "")
    attrs = [f'd="{d}"']
    if fill:
        attrs.append(f'fill="{fill}"')
    else:
        attrs.append('fill="none"')
    if stroke:
        attrs.append(f'stroke="{stroke}" stroke-width="{_fmt(sw)}"')
        attrs.append("stroke-linejoin=\"round\" stroke-linecap=\"round\"")
    if dash:
        attrs.append('stroke-dasharray="3,2"')
    return "<path " + " ".join(attrs) + "/>"


def render_svg(doc: DrawDoc, scale_px: float = 3.0) -> str:
    """把画图指令(DrawDoc)拼成 SVG 字符串。坐标本身是米,再乘 scale 变成像素出图。"""
    w, h = doc.width_m, doc.height_m
    px_w, px_h = int(w * scale_px), int(h * scale_px)
    body: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{px_w}" height="{px_h}" '
        f'viewBox="{-w / 2:.1f} {-h / 2:.1f} {w:.1f} {h:.1f}">',
        f'<rect x="{-w / 2:.1f}" y="{-h / 2:.1f}" width="{w:.1f}" height="{h:.1f}" fill="{PALETTE["background"]}"/>',
    ]
    for it in doc.items:
        if it.layer == "road":
            # 道路画两层:先粗一圈灰色打底,再叠细白线当路面,交叉路口才不会断开
            body.append(_polyline_svg(it.pts, None, PALETTE["road_casing"],
                                      it.stroke_width + 0.8, False))
            body.append(_polyline_svg(it.pts, None, it.stroke, it.stroke_width, False))
        else:
            body.append(_polyline_svg(it.pts, it.fill, it.stroke, it.stroke_width, it.dash))

    # 左下角画图例(每种颜色一个色块+名字)。用 translate 挪到自己的坐标系里画,
    # 不受上面 y 翻转的影响,文字不会倒着。只列画布上真画了的图层
    legend = legend_for(doc)
    leg_x = -w / 2 + 2.0
    leg_y = -h / 2 + 2.0
    body.append(f'<g transform="translate({leg_x:.1f},{leg_y:.1f})">')
    body.append(f'<rect x="-0.6" y="-0.6" width="9" height="{1.1 * len(legend) + 1:.1f}" '
                f'fill="white" stroke="#999" stroke-width="0.15" opacity="0.9"/>')
    for i, (label, color) in enumerate(legend):
        ty = i * 1.1
        body.append(f'<rect x="0" y="{ty}" width="1.6" height="0.8" fill="{color}" '
                    f'stroke="#777" stroke-width="0.1"/>')
        body.append(f'<text x="2.2" y="{ty + 0.75}" font-size="0.9" fill="#333">{label}</text>')
    body.append("</g>")
    body.append("</svg>")
    return "\n".join(body)


@register("svg", "2D", "SVG (vector)")
def export_svg(ctx: ExportContext) -> str:
    from app.services.export.registry import read_preview

    ctx.on_progress(0.3, "building draw list")
    doc = draw_doc_from_preview(read_preview(ctx), ctx.meta)
    ctx.on_progress(0.7, "rendering svg")
    filename = f"{ctx.task_id}.svg"
    (ctx.export_dir / filename).write_text(render_svg(doc), encoding="utf-8")
    ctx.on_progress(1.0, "svg ready")
    return filename
