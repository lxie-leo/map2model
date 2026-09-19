"""导出 GeoJSON(经纬度坐标的通用矢量格式,QGIS/网页地图都认)。

预览文件 preview.geojson 本身就是现成的 WGS84 GeoJSON,复制一份改名完事。"""

from __future__ import annotations

from app.services.export.registry import ExportContext, read_preview, register
from app.utils.caching import write_json_atomic


@register("geojson", "GIS", "GeoJSON")
def export_geojson(ctx: ExportContext) -> str:
    ctx.on_progress(0.5, "packaging geojson")
    preview = read_preview(ctx)
    filename = f"{ctx.task_id}.geojson"
    write_json_atomic(ctx.export_dir / filename, preview)
    ctx.on_progress(1.0, "geojson ready")
    return filename
