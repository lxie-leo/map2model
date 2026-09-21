"""导出 GPKG 和 SHP(两种 GIS 软件的当家格式,QGIS/ArcGIS 直接开),用 geopandas 写。

两种格式脾气不同:GPKG 是个单文件数据库,一库里塞多层随便放;
SHP 是老古董,一个文件只装得下一层数据(还得 .shp/.dbf/.shx 一伙作伴),
所以每个图层写一组、统统塞进 zip 交给用户。
坐标都带真实坐标系(UTM,就是给这块地分配的"门牌" EPSG 编号),
进 GIS 软件能直接叠在卫星图上。
"""

from __future__ import annotations

from app.services.export.registry import ExportContext, register
from app.services.projection import Projector


def _build_layer_frames(preview: dict, projector: Projector):
    """把预览里的要素按图层分拣:建筑归建筑、路归路,攒成 geopandas 要的形状。"""
    from shapely.geometry import LineString, Polygon

    layers: dict[str, dict] = {}

    def bucket(name: str, gtype: str):
        if name not in layers:
            layers[name] = {"gtype": gtype, "geoms": [], "props": []}

    for feat in preview.get("features", []):
        props = dict(feat.get("properties", {}))
        geom = feat.get("geometry", {})
        kind = props.get("layer")
        gtype = geom.get("type")
        if gtype == "Polygon":
            rings = geom.get("coordinates", [])
            # 环是首尾闭合的,至少要 4 个坐标(3 个不重合的点)才围得出面;
            # OSM 里偶尔有残缺的"两点建筑",直接跳过,别让 shapely 报错
            rings = [r for r in rings if len(r) >= 4]
            if not rings:
                continue
            shp = Polygon(
                projector.to_local_many([(c[0], c[1]) for c in rings[0]]),
                [projector.to_local_many([(c[0], c[1]) for c in r]) for r in rings[1:]],
            )
            if kind == "building":
                bucket("buildings", "Polygon")
                layers["buildings"]["geoms"].append(shp)
                layers["buildings"]["props"].append({
                    "height": props.get("height"), "name": props.get("name"),
                })
            elif kind == "water":
                bucket("water", "Polygon")
                layers["water"]["geoms"].append(shp)
                layers["water"]["props"].append({"kind": props.get("kind")})
            elif kind == "green":
                bucket("green", "Polygon")
                layers["green"]["geoms"].append(shp)
                layers["green"]["props"].append({"kind": props.get("kind")})
        elif gtype == "LineString":
            coords = geom.get("coordinates", [])
            if len(coords) < 2:
                continue
            shp = LineString(projector.to_local_many([(c[0], c[1]) for c in coords]))
            target = {"road": "roads", "railway": "railways", "water": "waterways"}.get(kind)
            if target is None:
                continue
            bucket(target, "LineString")
            layers[target]["geoms"].append(shp)
            layers[target]["props"].append({
                "kind": props.get("kind"), "width": props.get("width"),
                "name": props.get("name"),
            })

    # 内部坐标原点在框选中心,方便建模;GIS 要的是地图像样的真实位置,
    # 所以整体平移回真实坐标(加回当初减掉的偏移),并挂上 EPSG 编号
    ox, oy = projector.ox, projector.oy
    from shapely.affinity import translate

    frames = []
    for name, data in layers.items():
        import geopandas as gpd

        geoms = [translate(g, xoff=ox, yoff=oy) for g in data["geoms"]]
        gdf = gpd.GeoDataFrame(data["props"], geometry=geoms,
                               crs=f"EPSG:{projector.epsg}")
        frames.append((name, gdf))
    return frames


def _load(ctx: ExportContext):
    from app.services.export.registry import read_preview

    preview = read_preview(ctx)
    projector = Projector(tuple(ctx.meta["bbox"]))
    return preview, projector


@register("gpkg", "GIS", "GPKG (QGIS)", requires=("geopandas", "pyogrio"))
def export_gpkg(ctx: ExportContext) -> str:
    preview, projector = _load(ctx)
    ctx.on_progress(0.4, "building layers")
    frames = _build_layer_frames(preview, projector)
    if not frames:
        raise ValueError("No vector features to export")
    filename = f"{ctx.task_id}.gpkg"
    path = ctx.export_dir / filename
    for i, (name, gdf) in enumerate(frames):
        ctx.on_progress(0.4 + 0.5 * (i + 1) / len(frames), f"writing layer {name}")
        gdf.to_file(path, layer=name, driver="GPKG")
    ctx.on_progress(1.0, "gpkg ready")
    return filename


@register("shp", "GIS", "SHP (zipped)", requires=("geopandas", "pyogrio"))
def export_shp(ctx: ExportContext) -> str:
    preview, projector = _load(ctx)
    ctx.on_progress(0.3, "building layers")
    frames = _build_layer_frames(preview, projector)
    if not frames:
        raise ValueError("No vector features to export")
    tmp_dir = ctx.export_dir / "shp_tmp"
    tmp_dir.mkdir(exist_ok=True)
    for i, (name, gdf) in enumerate(frames):
        ctx.on_progress(0.3 + 0.5 * (i + 1) / len(frames), f"writing layer {name}")
        gdf.to_file(tmp_dir / f"{name}.shp", encoding="utf-8")
    from app.utils.fs import zip_dir

    filename = f"{ctx.task_id}_shp.zip"
    zip_dir(tmp_dir, ctx.export_dir / filename)
    for p in tmp_dir.iterdir():
        p.unlink()
    tmp_dir.rmdir()
    ctx.on_progress(1.0, "shp ready")
    return filename
