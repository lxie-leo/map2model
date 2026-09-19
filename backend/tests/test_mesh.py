"""建模:把房子顶起来、把路铺成带子、水面、场景组装和 hub.glb 导出。"""

import numpy as np

from app.services.mesh.extrude import extrude_buildings
from app.services.mesh.ribbon import build_ribbon, build_water_surface
from app.services.mesh.scene import build_scene, load_hub_scene, write_hub
from app.services.mesh.terrain_mesh import build_terrain_mesh
from app.services.osm_parse import parse_osm, resolve_building_heights
from app.services.projection import Projector
from app.services.terrain import TerrainGrid
from app.services.vector.buildings import to_local_buildings
from app.services.vector.lines import to_local_lines
from app.services.vector.polys import to_local_polys
from tests.conftest import BBOX


def _local_features(sample_payload):
    p = Projector(BBOX)
    feats = parse_osm(sample_payload)
    resolve_building_heights(feats.buildings)
    return {
        "buildings": to_local_buildings(feats.buildings, p, max_buildings=1000),
        "roads": to_local_lines(feats.roads, p),
        "water_polys": to_local_polys(feats.water_polys, p),
        "projector": p,
    }


def test_extrude(sample_payload, fake_terrain):
    d = _local_features(sample_payload)
    mesh = extrude_buildings(d["buildings"], fake_terrain)
    assert len(mesh.vertices) > 0
    assert len(mesh.faces) >= 4 * 3  # 至少 4 栋建筑,每栋顶面 2 个三角形起步
    # 高度方向有起伏(顶面 > 底面)
    assert mesh.vertices[:, 2].max() > mesh.vertices[:, 2].min() + 5.0


def test_ribbon(sample_payload, fake_terrain):
    d = _local_features(sample_payload)
    road = d["roads"][0]
    mesh = build_ribbon(road.pts, road.width, 0.08, fake_terrain)
    assert len(mesh.vertices) == 2 * len(road.pts)
    assert len(mesh.faces) == 2 * (len(road.pts) - 1)
    # 展宽后的顶点应该比中心线宽(左右分开)
    left = mesh.vertices[0, :2]
    right = mesh.vertices[1, :2]
    width_actual = np.linalg.norm(right - left)
    assert road.width * 0.5 < width_actual < road.width * 2.5


def test_water_surface(sample_payload, fake_terrain):
    d = _local_features(sample_payload)
    lake = d["water_polys"][0]
    mesh = build_water_surface(lake.poly, fake_terrain, cut=-0.25)
    assert len(mesh.faces) >= 1
    # 水面顶点 z 都在地形附近 -0.25
    zs = mesh.vertices[:, 2]
    assert zs.max() - zs.min() < 12.0  # 起伏地形上水面随坡度,但不会夸张


def test_terrain_mesh(fake_terrain):
    mesh = build_terrain_mesh(fake_terrain)
    assert len(mesh.vertices) == fake_terrain.nx * fake_terrain.ny
    assert len(mesh.faces) == 2 * (fake_terrain.nx - 1) * (fake_terrain.ny - 1)


def test_scene_and_hub(tmp_path, sample_payload, fake_terrain):
    d = _local_features(sample_payload)
    layers = {
        "TERRAIN": build_terrain_mesh(fake_terrain),
        "BUILDING": extrude_buildings(d["buildings"], fake_terrain),
    }
    for road in d["roads"]:
        layers["ROAD"] = build_ribbon(road.pts, road.width, 0.08, fake_terrain)
    scene = build_scene(layers)
    assert set(scene.geometry) == {"TERRAIN", "BUILDING", "ROAD"}
    hub = write_hub(tmp_path, scene)
    assert hub.exists()
    assert hub.read_bytes()[:4] == b"glTF"  # GLB 文件开头的固定标识

    # 读回来:图层名还在,坐标已转 Y-up
    loaded = load_hub_scene(tmp_path)
    assert set(loaded.geometry) >= {"BUILDING"}
    v = loaded.geometry["BUILDING"].vertices
    # 原始建筑 z 在 [-9, 48](高度 25/40 + 地形),Y-up 后应体现在 Y 轴
    assert v[:, 1].max() > 15.0
