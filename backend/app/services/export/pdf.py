"""导出 PDF(打印用的制图版本):reportlab 画,自动挑纸张大小,右下角带图例。"""

from __future__ import annotations

from app.services.export.registry import ExportContext, register
from app.services.vector.draw2d import PALETTE, DrawDoc, draw_doc_from_preview, legend_for

# 常见 A 系列纸横放时的尺寸(宽,高),单位 pt(PDF 自带的长度单位,1 pt = 1/72 英寸)
_PAGES = [(842, 595), (1191, 842), (1684, 1191)]  # A4, A3, A2
_MARGIN = 28  # 四周留白,pt

# 图例文字是英文,自带 Helvetica 就够;以前为画汉字备过一串系统字体探测,
# 已随图例英文化删掉——将来若要往 PDF 里画地名等数据文本,得重新引入 CJK 字体


def render_pdf(doc: DrawDoc, out_path) -> None:
    from reportlab.lib.colors import HexColor
    from reportlab.pdfgen import canvas as rl_canvas

    # 挑纸:先试 A3,塞不下就升 A2,再不行 A1;都塞不下就用 A1 缩着放
    scale = 0.0
    page = _PAGES[-1]
    for pw, ph in _PAGES:
        s = min((pw - 2 * _MARGIN) / doc.width_m, (ph - 2 * _MARGIN) / doc.height_m)
        if s >= 1.0:  # 至少 1 米换 1 pt,再小线条就糊了
            scale, page = s, (pw, ph)
            break
    else:
        scale = min((page[0] - 2 * _MARGIN) / doc.width_m,
                    (page[1] - 2 * _MARGIN) / doc.height_m)
    pw, ph = page

    c = rl_canvas.Canvas(str(out_path), pagesize=(pw, ph))
    ox = pw / 2                  # 框选中心(局部坐标原点)放在纸面正中
    oy = ph / 2

    def X(x: float) -> float:
        return ox + x * scale

    def Y(y: float) -> float:    # PDF 的 y 恰好也朝上,跟我们的坐标一个方向,直接加
        return oy + y * scale

    c.setFillColor(HexColor(PALETTE["background"]))
    c.rect(X(-doc.width_m / 2), Y(-doc.height_m / 2),
           doc.width_m * scale, doc.height_m * scale, fill=1, stroke=0)

    def draw_pts(pts, fill, stroke, sw_m):
        p = c.beginPath()
        p.moveTo(X(pts[0][0]), Y(pts[0][1]))
        for x, y in pts[1:]:
            p.lineTo(X(x), Y(y))
        if fill:
            p.close()
        if fill:
            c.setFillColor(HexColor(fill))
        if stroke:
            c.setStrokeColor(HexColor(stroke))
            c.setLineWidth(max(sw_m * scale, 0.2))
        c.drawPath(p, fill=1 if fill else 0, stroke=1 if stroke else 0)

    for it in doc.items:
        if it.layer == "road":
            draw_pts(it.pts, None, PALETTE["road_casing"], it.stroke_width + 0.8)
            draw_pts(it.pts, None, it.stroke, it.stroke_width)
        else:
            draw_pts(it.pts, it.fill, it.stroke, it.stroke_width)

    # 图例画在左下角:白底框 + 一排色块和名字,从下往上数着画。
    # 只列画布上真画了的图层(前端关掉的图层不该出现在图例里)
    legend = legend_for(doc)
    lx, ly = _MARGIN, _MARGIN
    c.setFillColor(HexColor("#ffffff"))
    c.setStrokeColor(HexColor("#999999"))
    c.rect(lx, ly, 110, 14 * len(legend) + 8, fill=1, stroke=1)
    for i, (label, color) in enumerate(legend):
        ty = ly + 14 * len(legend) - 6 - i * 14
        c.setFillColor(HexColor(color))
        c.rect(lx + 8, ty, 12, 8, fill=1, stroke=0)
        c.setFillColor(HexColor("#333333"))
        c.setFont("Helvetica", 8)
        c.drawString(lx + 26, ty + 1, label)
    c.showPage()
    c.save()


@register("pdf", "2D", "PDF (map sheet)")
def export_pdf(ctx: ExportContext) -> str:
    from app.services.export.registry import read_preview

    ctx.on_progress(0.3, "building draw list")
    doc = draw_doc_from_preview(read_preview(ctx), ctx.meta)
    ctx.on_progress(0.7, "rendering pdf")
    filename = f"{ctx.task_id}.pdf"
    render_pdf(doc, ctx.export_dir / filename)
    ctx.on_progress(1.0, "pdf ready")
    return filename
