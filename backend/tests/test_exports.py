"""导出器:2D(SVG/PDF/PNG/DXF)和 GIS(GeoJSON/KML/CityJSON/3D Tiles)。

环境里没装的依赖(usd-core 等)自动跳过对应用例。
"""

import json

import pytest

from app.services.export.registry import ExportContext, FORMATS, _ensure_loaded
from app.services.mesh.extrude import extrude_buildings
from app.services.mesh.ribbon import build_ribbon, build_water_surface
from app.services.mesh.scene import build_scene, write_hub
from app.services.mesh.terrain_mesh import build_terrain_mesh
from app.services.osm_parse import parse_osm, resolve_building_heights
from app.services.projection import Projector
from app.services.vector.buildings import to_local_buildings
from app.services.vector.lines import to_local_lines
from app.services.vector.polys import to_local_polys
from tests.conftest import BBOX


@pytest.fixture(scope="module")
def task_dir(tmp_path_factory, sample_payload_module):
    """造一个"已完成的任务目录":hub.glb + preview.geojson + meta.json。"""
    d = tmp_path_factory.mktemp("task") / "t0"
    d.mkdir()
    p = Projector(BBOX)
    feats = parse_osm(sample_payload_module)
    resolve_building_heights(feats.buildings)

    buildings = to_local_buildings(feats.buildings, p, max_buildings=1000)
    roads = to_local_lines(feats.roads, p)
    water = to_local_polys(feats.water_polys, p)
    greens = to_local_polys(feats.greens, p)

    from app.services.terrain import TerrainGrid

    grid = TerrainGrid.flat(p.width_m, p.height_m)
    layers = {
        "TERRAIN": build_terrain_mesh(grid),
        "BUILDING": extrude_buildings(buildings, grid),
    }
    import trimesh

    if roads:
        layers["ROAD"] = build_ribbon(roads[0].pts, roads[0].width, 0.08, grid)
    if water:
        layers["WATER"] = build_water_surface(water[0].poly, grid)
    if greens:
        layers["GREEN"] = build_water_surface(greens[0].poly, grid, cut=0.03)
    write_hub(d, build_scene(layers))

    # preview.geojson(直接从解析结果造)
    features = []
    for b in feats.buildings:
        features.append({
            "type": "Feature",
            "properties": {"layer": "building", "height": b.height, "name": b.name},
            "geometry": {"type": "Polygon", "coordinates": [b.outer]},
        })
    for r in feats.roads:
        features.append({
            "type": "Feature",
            "properties": {"layer": "road", "kind": r.kind, "width": r.width},
            "geometry": {"type": "LineString", "coordinates": r.coords},
        })
    for r in feats.railways:
        features.append({
            "type": "Feature",
            "properties": {"layer": "railway", "kind": r.kind, "width": r.width},
            "geometry": {"type": "LineString", "coordinates": r.coords},
        })
    for w in feats.water_polys:
        features.append({
            "type": "Feature",
            "properties": {"layer": "water", "kind": w.kind},
            "geometry": {"type": "Polygon", "coordinates": [w.outer]},
        })
    for g in feats.greens:
        features.append({
            "type": "Feature",
            "properties": {"layer": "green", "kind": g.kind},
            "geometry": {"type": "Polygon", "coordinates": [g.outer]},
        })
    (d / "preview.geojson").write_text(
        json.dumps({"type": "FeatureCollection", "features": features}), encoding="utf-8"
    )
    (d / "meta.json").write_text(json.dumps({
        "bbox": list(BBOX), "epsg": p.epsg,
        "center_lon": p.center_lon, "center_lat": p.center_lat,
        "width_m": round(p.width_m, 2), "height_m": round(p.height_m, 2),
        "median_h": 4.0, "options": {}, "stats": {},
    }), encoding="utf-8")
    return d


@pytest.fixture(scope="module")
def sample_payload_module():
    from tests.conftest import FIXTURES

    with open(FIXTURES / "overpass_sample.json", encoding="utf-8") as f:
        return json.load(f)


def _ctx(task_dir, tmp_path, layers=None) -> ExportContext:
    from app.config import get_settings

    export_dir = tmp_path / "exports"
    export_dir.mkdir(exist_ok=True)
    return ExportContext(
        task_id="t0", task_dir=task_dir, export_dir=export_dir,
        meta=json.loads((task_dir / "meta.json").read_text(encoding="utf-8")),
        settings=get_settings(),
        on_progress=lambda f, m=None: None,
        layers=layers,
    )


def test_formats_registered():
    fmts = FORMATS()
    for expect in ("glb", "obj", "stl", "svg", "pdf", "png", "dxf", "geojson",
                   "kml", "cityjson", "3dtiles"):
        assert expect in fmts, f"{expect} missing"


def test_svg(task_dir, tmp_path):
    from app.services.export.svg import export_svg

    name = export_svg(_ctx(task_dir, tmp_path))
    text = (tmp_path / "exports" / name).read_text(encoding="utf-8")
    assert text.startswith("<svg")
    assert 'fill="#b7d6a8"' in text       # 绿地
    assert 'fill="#a8cfe8"' in text       # 水面
    assert text.count("<path") > 5


def test_pdf(task_dir, tmp_path):
    from app.services.export.pdf import export_pdf

    name = export_pdf(_ctx(task_dir, tmp_path))
    data = (tmp_path / "exports" / name).read_bytes()
    assert data[:5] == b"%PDF-"


def test_png(task_dir, tmp_path):
    from app.services.export.png import export_png

    name = export_png(_ctx(task_dir, tmp_path))
    data = (tmp_path / "exports" / name).read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n"


def test_dxf(task_dir, tmp_path):
    import ezdxf

    from app.services.export.dxf import export_dxf

    name = export_dxf(_ctx(task_dir, tmp_path))
    doc = ezdxf.readfile(tmp_path / "exports" / name)
    layers = {l.dxf.name for l in doc.layers}
    assert {"M2M_BUILDING", "M2M_ROAD", "M2M_WATER", "M2M_GREEN"} <= layers


def test_geojson(task_dir, tmp_path):
    from app.services.export.geojson import export_geojson

    name = export_geojson(_ctx(task_dir, tmp_path))
    fc = json.loads((tmp_path / "exports" / name).read_text(encoding="utf-8"))
    assert fc["type"] == "FeatureCollection"
    assert len(fc["features"]) > 8


def test_kml(task_dir, tmp_path):
    from app.services.export.kml import export_kml

    name = export_kml(_ctx(task_dir, tmp_path))
    text = (tmp_path / "exports" / name).read_text(encoding="utf-8")
    assert "<kml" in text and "extrude>1" in text


def test_cityjson(task_dir, tmp_path):
    from app.services.export.cityjson import export_cityjson

    name = export_cityjson(_ctx(task_dir, tmp_path))
    cj = json.loads((tmp_path / "exports" / name).read_text(encoding="utf-8"))
    assert cj["type"] == "CityJSON"
    assert cj["version"] == "2.0"
    # fixture 里 4 栋建筑,其中 801 号只有 2 个点被跳过 → 3 个 CityObject
    assert len(cj["CityObjects"]) == 3
    assert cj["transform"]["scale"] == [0.001] * 3
    verts = cj["vertices"]
    assert all(isinstance(v[0], int) for v in verts)  # 顶点都存成整数了(文件更小)


def test_tiles3d(task_dir, tmp_path):
    import zipfile

    from app.services.export.tiles3d import export_tiles3d

    name = export_tiles3d(_ctx(task_dir, tmp_path))
    path = tmp_path / "exports" / name
    assert path.suffix == ".zip"
    with zipfile.ZipFile(path) as zf:
        names = zf.namelist()
        assert "tileset.json" in names
        tileset = json.loads(zf.read("tileset.json"))
        assert tileset["asset"]["version"] == "1.1"
        assert len(tileset["root"]["transform"]) == 16
        assert any(n.startswith("tiles/") for n in names)


def test_obj(task_dir, tmp_path):
    from app.services.export.obj import export_obj

    name = export_obj(_ctx(task_dir, tmp_path))
    text = (tmp_path / "exports" / name).read_text(encoding="utf-8")
    assert "o BUILDING" in text
    assert "usemtl mat_BUILDING" in text
    assert "mtllib" in text
    assert (tmp_path / "exports" / "t0.mtl").exists()


def test_gpkg_skip_without_geopandas(task_dir, tmp_path):
    pytest.importorskip("geopandas")
    from app.services.export.gis import export_gpkg

    name = export_gpkg(_ctx(task_dir, tmp_path))
    assert (tmp_path / "exports" / name).exists()


# ---- 图层过滤:前端图层面板关掉的图层不该出现在导出结果里 ----


def test_geojson_layer_filter(task_dir, tmp_path):
    """矢量导出:只要建筑和铁路,输出的要素图层也只能是这俩。"""
    from app.services.export.geojson import export_geojson

    name = export_geojson(_ctx(task_dir, tmp_path, layers=frozenset({"BUILDING", "RAILWAY"})))
    fc = json.loads((tmp_path / "exports" / name).read_text(encoding="utf-8"))
    got = {f["properties"]["layer"] for f in fc["features"]}
    assert got == {"building", "railway"}


def test_svg_layer_filter(task_dir, tmp_path):
    """2D 导出:关掉绿地和水,画布上就不该再出现它们的颜色。"""
    from app.services.export.svg import export_svg

    layers = frozenset({"BUILDING", "ROAD", "TERRAIN", "RAILWAY"})
    name = export_svg(_ctx(task_dir, tmp_path, layers=layers))
    text = (tmp_path / "exports" / name).read_text(encoding="utf-8")
    assert 'fill="#b7d6a8"' not in text   # 绿地没了
    assert 'fill="#a8cfe8"' not in text   # 水面没了
    # 楼还在
    assert 'fill="#ddd5c9"' in text


def test_obj_layer_filter(task_dir, tmp_path):
    """3D 导出:只要建筑,OBJ 里就不该再有地形/道路等别的对象。"""
    from app.services.export.obj import export_obj

    name = export_obj(_ctx(task_dir, tmp_path, layers=frozenset({"BUILDING"})))
    text = (tmp_path / "exports" / name).read_text(encoding="utf-8")
    assert "o BUILDING" in text
    assert "o TERRAIN" not in text
    assert "o ROAD" not in text
    assert "o WATER" not in text


def test_glb_layer_filter(task_dir, tmp_path):
    """GLB:关了图层要重新打包,读回来的场景只剩勾选的图层;
    全开时走复制快路径,文件内容和 hub 一模一样。"""
    import trimesh

    from app.services.export.glb import export_glb

    name = export_glb(_ctx(task_dir, tmp_path, layers=frozenset({"BUILDING", "ROAD"})))
    scene = trimesh.load(str(tmp_path / "exports" / name), force="scene")
    assert set(scene.geometry) == {"BUILDING", "ROAD"}

    name = export_glb(_ctx(task_dir, tmp_path))  # layers=None = 全部
    got = (tmp_path / "exports" / name).read_bytes()
    assert got == (task_dir / "hub.glb").read_bytes()  # 整包照抄,没重新打包
