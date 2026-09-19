"""几何朝向的体检:面该朝上/朝外/朝下的,每种网格都单独验一遍。

这些朝向以前靠 trimesh 的 fix_normals() 兜底,但它只对"封闭且顶点
共享"的网格管用,带子、墙皮这种单片它分不清上下,曾经整层朝下、
从上往下看就消失。现在方向在代码里手工摆正,这些测试防着退化。
"""

from __future__ import annotations

import json

import numpy as np
import trimesh
from shapely.geometry import Polygon, box

from app.services.mesh.extrude import _extrude_one
from app.services.mesh.ribbon import build_ribbon, build_water_surface
from app.services.mesh.terrain_mesh import build_terrain_mesh
from app.services.mesh.scene import _to_yup
from app.services.terrain import TerrainGrid
from app.services.vector.buildings import BuildingLocal
from app.utils.geom import triangulate_polygon


def _flat(size: float = 1000.0, h: float = 5.0) -> TerrainGrid:
    """一块平地:盖住 ±size/2 的正方形,高程全是 h 米。"""
    n = 21
    return TerrainGrid(-size / 2, -size / 2, size / (n - 1), n, n,
                       np.full((n, n), h))


def _outward_dots(mesh: trimesh.Trimesh, center_xy=np.zeros(2)) -> np.ndarray:
    """每个面的法线在水平方向上是否从 center_xy 指向外(正值=朝外)。"""
    rel = mesh.triangles_center[:, :2] - center_xy
    return np.einsum("ij,ij->i", mesh.face_normals[:, :2], rel)


def test_ribbon_faces_up():
    m = build_ribbon(np.array([[0.0, -50.0], [0.0, 0.0], [50.0, 0.0]]),
                     6.0, 0.08, _flat())
    assert len(m.faces) == 4  # 两段,每段两个三角
    assert (m.face_normals[:, 2] > 0.99).all()  # 带子必须朝上


def test_building_roof_up_walls_outward():
    m = _extrude_one(BuildingLocal(poly=box(-20, -10, 20, 10), height=15.0, name=None),
                     _flat())
    top = 5.0 + 15.0
    roof = np.isclose(m.triangles_center[:, 2], top, atol=0.5)
    assert roof.sum() == 2  # 方形屋顶两个三角
    assert (m.face_normals[roof][:, 2] > 0.99).all()
    assert (_outward_dots(m)[~roof] > 0).all()  # 墙一律从楼中心指向外


def test_building_courtyard_walls_face_into_hole():
    outer = box(-20, -20, 20, 20)
    hole = box(-5, -5, 5, 5)
    poly = Polygon(outer.exterior, [hole.exterior])
    m = _extrude_one(BuildingLocal(poly=poly, height=15.0, name=None), _flat())
    top = 5.0 + 15.0
    roof = np.isclose(m.triangles_center[:, 2], top, atol=0.5)
    # 外墙(离楼中心远)朝外;内院墙(在洞边上)朝楼中心——也就是朝内院
    r = np.linalg.norm(m.triangles_center[:, :2], axis=1)
    outer_wall = (~roof) & (r > 12)
    inner_wall = (~roof) & (r < 8)
    assert outer_wall.sum() >= 8 and (_outward_dots(m)[outer_wall] > 0).all()
    assert inner_wall.sum() >= 8 and (_outward_dots(m)[inner_wall] < 0).all()


def test_to_yup_keeps_winding():
    tri = trimesh.Trimesh(vertices=[[0, 0, 0], [1, 0, 0], [0, 1, 0]],
                          faces=[[0, 1, 2]], process=False)
    n = _to_yup(tri).face_normals[0]
    # Z 朝上的面转成 Y 朝上后,法线原指 +Z 现在应指 +Y(转方向不是镜像)
    assert n[1] > 0.99 and abs(n[0]) < 0.01 and abs(n[2]) < 0.01


def test_triangulate_polygon_faces_up():
    poly = Polygon(box(-10, -10, 10, 10).exterior, [box(-3, -3, 3, 3).exterior])
    verts, faces = triangulate_polygon(poly)
    assert len(faces) >= 8  # 带洞的方形至少 8 个三角
    tri = verts[faces]
    cross = ((tri[:, 1, 0] - tri[:, 0, 0]) * (tri[:, 2, 1] - tri[:, 0, 1])
             - (tri[:, 2, 0] - tri[:, 0, 0]) * (tri[:, 1, 1] - tri[:, 0, 1]))
    assert (cross > 0).all()  # 每个三角都逆时针(面朝上)


def test_water_surface_faces_up():
    m = build_water_surface(box(-30, -30, 30, 30), _flat())
    assert len(m.faces) >= 2
    assert (m.face_normals[:, 2] > 0.99).all()


def test_terrain_mesh_faces_up():
    m = build_terrain_mesh(_flat())
    assert (m.face_normals[:, 2] > 0.99).all()


def test_cityjson_solid_winding(tmp_path):
    """CityJSON 每栋楼是个封闭盒子:顶朝上、底朝下、墙朝外(以前墙是穿楼的斜窗帘)。"""
    from app.services.export import cityjson as cj
    from app.services.export.registry import ExportContext

    task_dir = tmp_path / "t"
    task_dir.mkdir()
    export_dir = tmp_path / "exp"
    export_dir.mkdir()
    ring = [[0.001, 0.001], [0.003, 0.001], [0.003, 0.002],
            [0.001, 0.002], [0.001, 0.001]]
    preview = {"type": "FeatureCollection", "features": [{
        "type": "Feature",
        "properties": {"layer": "building", "height": 12.0, "name": ""},
        "geometry": {"type": "Polygon", "coordinates": [ring]},
    }]}
    (task_dir / "preview.geojson").write_text(json.dumps(preview), encoding="utf-8")
    ctx = ExportContext(task_id="t", task_dir=task_dir, export_dir=export_dir,
                        meta={"bbox": [0.0, 0.0, 0.004, 0.003], "median_h": 3.0},
                        settings=None, on_progress=lambda *a: None)
    data = json.loads((export_dir / cj.export_cityjson(ctx)).read_text(encoding="utf-8"))

    sc = data["transform"]["scale"][0]
    tr = data["transform"]["translate"]
    verts = [np.array([v[0] * sc + tr[0], v[1] * sc + tr[1], v[2] * sc + tr[2]])
             for v in data["vertices"]]
    obj = next(iter(data["CityObjects"].values()))
    shell = obj["geometry"][0]["boundaries"][0]
    assert len(shell) == 6  # 底 + 顶 + 四面墙

    h0, h1 = 3.0, 15.0
    center_xy = np.mean([[v[0], v[1]] for v in verts], axis=0)
    for ring_idx in shell:
        pts = [verts[i] for i in ring_idx[0]]
        assert len({round(p[2], 3) for p in pts}) <= 2  # 每个面都在一个竖直/水平平面里
        n = np.zeros(3)
        for k in range(len(pts)):
            n += np.cross(pts[k], pts[(k + 1) % len(pts)])
        n = n / 2.0  # 面积向量:长度是面积,方向是面的朝向
        zs = [p[2] for p in pts]
        if min(zs) > 10:      # 屋顶
            assert n[2] > 0
        elif max(zs) < 5:     # 墙底
            assert n[2] < 0
        else:                 # 墙:水平方向从楼中心指向外
            cen = np.mean(pts, axis=0)
            assert n[:2] @ (cen[:2] - center_xy) > 0
