"""导出 KML / KMZ(Google Earth 的格式,KMZ 就是把 kml 打成 zip)。

让建筑在地球上是立体的诀窍:每个多边形坐标带上第三维(高度),再打开
extrude(挤出)开关、高度设成"相对地面",Earth 就自动从地面拉到楼顶,
屋顶和侧壁都不用我们画。其他地物平贴在地面(clamp)就行。
"""

from __future__ import annotations

from app.services.export.registry import ExportContext, register

# KML 的颜色顺序很怪:透明度、蓝、绿、红(aabbggrr),跟网页常用的
# rrggbb 正好反着,直接抄网页色号会红绿互换、满屏怪色
_KML_COLORS = {
    "building": "ffd0c8bc",   # 米白
    "road": "ffffffff",
    "railway": "ff4a4a4a",
    "water": "ffe8cfa8",
    "green": "ffa8d6b7",
}


@register("kml", "GIS", "KML")
def export_kml(ctx: ExportContext, kmz: bool = False) -> str:
    import simplekml

    from app.services.export.registry import read_preview

    preview = read_preview(ctx)
    kml = simplekml.Kml()
    # 文件夹名固定英文,跟其它导出格式保持一致
    folders = {
        "building": kml.newfolder(name="Buildings"),
        "road": kml.newfolder(name="Roads"),
        "railway": kml.newfolder(name="Railways"),
        "water": kml.newfolder(name="Water"),
        "green": kml.newfolder(name="Green"),
    }

    total = max(len(preview.get("features", [])), 1)
    for i, feat in enumerate(preview.get("features", [])):
        if i % 200 == 0:
            ctx.on_progress(0.2 + 0.7 * i / total, "writing features")
        props = feat.get("properties", {})
        kind = props.get("layer")
        geom = feat.get("geometry", {})
        folder = folders.get(kind)
        if folder is None:
            continue
        color = _KML_COLORS.get(kind, "ffcccccc")

        if geom.get("type") == "Polygon":
            rings = geom["coordinates"]
            pol = folder.newpolygon(name=props.get("name") or "")
            pol.polystyle.color = color
            if kind == "building":
                h = float(props.get("height") or 6.0)
                pol.outerboundaryis = [(lon, lat, h) for lon, lat in rings[0]]
                if len(rings) > 1:
                    pol.innerboundaryis = [
                        [(lon, lat, h) for lon, lat in r] for r in rings[1:]
                    ]
                pol.extrude = 1
                pol.altitudemode = simplekml.AltitudeMode.relativetoground
            else:
                pol.outerboundaryis = rings[0]
                if len(rings) > 1:
                    pol.innerboundaryis = rings[1:]
                pol.altitudemode = simplekml.AltitudeMode.clamptoground
        elif geom.get("type") == "LineString":
            ln = folder.newlinestring(name=props.get("name") or "")
            ln.coords = geom["coordinates"]
            ln.altitudemode = simplekml.AltitudeMode.clamptoground
            ln.linestyle.color = color
            # KML 线宽的单位是"像素"不是米。宽度属性存的是米(路面真实
            # 宽度),直接塞进去 30 米的路会粗成 30 像素的腊肠;按一半换算
            # 再夹在 1~8 像素之间,远近看着都合适
            w_m = float(props.get("width") or 2)
            ln.linestyle.width = min(max(round(w_m * 0.5), 1), 8)

    if kmz:
        filename = f"{ctx.task_id}.kmz"
        kml.savekmz(str(ctx.export_dir / filename))
    else:
        filename = f"{ctx.task_id}.kml"
        kml.save(str(ctx.export_dir / filename))
    ctx.on_progress(1.0, "kml ready")
    return filename


@register("kmz", "GIS", "KMZ (zipped)")
def export_kmz(ctx: ExportContext) -> str:
    return export_kml(ctx, kmz=True)
