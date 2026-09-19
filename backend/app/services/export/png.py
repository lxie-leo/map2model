"""导出 PNG(位图版地图):用 matplotlib 画成图片,不挑系统能直接看。"""

from __future__ import annotations

from app.services.export.registry import ExportContext, register
from app.services.vector.draw2d import LEGEND, PALETTE, DrawDoc, draw_doc_from_preview


def render_png(doc: DrawDoc, out_path, dpi: int = 200) -> None:
    import matplotlib

    matplotlib.use("Agg")  # 纯软件画图、不弹窗口,必须在 pyplot 之前切好
    # 图例文字是中文,matplotlib 自带的 DejaVu 字体没做汉字,列一串常见
    # 中文字体让它挨个找,找到哪个用哪个(顺带关掉负号变方块的问题)
    matplotlib.rcParams["font.sans-serif"] = [
        "Microsoft YaHei", "SimHei", "Noto Sans CJK SC", "WenQuanYi Micro Hei",
        "PingFang SC", "DejaVu Sans",
    ]
    matplotlib.rcParams["axes.unicode_minus"] = False
    import matplotlib.pyplot as plt
    from matplotlib.colors import to_rgba
    from matplotlib.lines import Line2D
    from matplotlib.patches import Polygon as MplPolygon
    from matplotlib.patches import Rectangle

    # 目标:长边撑到 4000 像素上下,够印刷也够放大看
    scale_px = 4000 / max(doc.width_m, doc.height_m)
    fig_w = doc.width_m * scale_px / dpi
    fig_h = doc.height_m * scale_px / dpi
    fig = plt.figure(figsize=(fig_w, fig_h), dpi=dpi)
    ax = fig.add_axes([0, 0, 1, 1])  # 画布整个铺满,不留白边和坐标轴
    ax.set_facecolor(to_rgba(PALETTE["background"]))
    m_to_pt = fig_w * 72 / doc.width_m  # 米换算成 pt:matplotlib 画线粗细只认 pt

    for it in doc.items:
        if it.kind == "polygon" and it.fill:
            ax.add_patch(MplPolygon(
                it.pts, closed=True, facecolor=to_rgba(it.fill),
                edgecolor=to_rgba(it.stroke or it.fill), linewidth=max(it.stroke_width * m_to_pt, 0.3),
            ))
        else:
            if it.layer == "road":
                # 道路同 SVG:先粗灰打底再叠细白路面,路口处才能连上
                ax.add_line(Line2D(
                    it.pts[:, 0], it.pts[:, 1],
                    color=to_rgba(PALETTE["road_casing"]),
                    linewidth=max((it.stroke_width + 0.8) * m_to_pt, 0.5),
                    solid_capstyle="round",
                ))
            ax.add_line(Line2D(
                it.pts[:, 0], it.pts[:, 1], color=to_rgba(it.stroke),
                linewidth=max(it.stroke_width * m_to_pt, 0.5),
                linestyle=(0, (3, 2)) if it.dash else "solid",
                solid_capstyle="round",
            ))

    # 图例(右下角)
    for i, (label, color) in enumerate(LEGEND):
        y = -doc.height_m / 2 + 1.5 + (len(LEGEND) - 1 - i) * 3.0
        ax.add_patch(Rectangle((doc.width_m / 2 - 14, y), 3, 2,
                               facecolor=to_rgba(color), edgecolor="#777", linewidth=0.5))
        ax.text(doc.width_m / 2 - 10, y + 0.6, label, fontsize=9, color="#333", va="center")

    ax.set_xlim(-doc.width_m / 2, doc.width_m / 2)
    ax.set_ylim(-doc.height_m / 2, doc.height_m / 2)
    ax.set_aspect("equal")
    ax.axis("off")
    fig.savefig(out_path, dpi=dpi)
    plt.close(fig)


@register("png", "2D", "PNG(位图)")
def export_png(ctx: ExportContext) -> str:
    from app.services.export.registry import read_preview

    ctx.on_progress(0.3, "building draw list")
    doc = draw_doc_from_preview(read_preview(ctx), ctx.meta)
    ctx.on_progress(0.6, "rendering png")
    filename = f"{ctx.task_id}.png"
    render_png(doc, ctx.export_dir / filename)
    ctx.on_progress(1.0, "png ready")
    return filename
