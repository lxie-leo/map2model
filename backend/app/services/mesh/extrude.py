"""把房子从地面顶起来:四面砌墙、顶上封盖。

- 墙底埋到轮廓各点地面高度的最低点再往下 1 米(保证嵌进坡地,不悬空);
- 墙顶 = 各点地面高度的最高点 + 楼高(顶是平的,LoD1 风格);
- 顶面用 earcut 切成一个个小三角形(带内院/天井的复杂房子也能切)。
- 墙体本身从墙底一直砌到墙顶,斜坡落差全被墙盖住,不用再单独补裙边。
"""

from __future__ import annotations

import numpy as np
import trimesh
from shapely.geometry.polygon import orient

from app.services.terrain import TerrainGrid
from app.services.vector.buildings import BuildingLocal
from app.utils.geom import triangulate_polygon


def extrude_buildings(
    buildings: list[BuildingLocal],
    terrain: TerrainGrid,
    *,
    on_progress=None,
    cancel_event=None,
) -> trimesh.Trimesh:
    meshes: list[trimesh.Trimesh] = []
    for i, b in enumerate(buildings):
        if i % 200 == 0:
            if cancel_event is not None and cancel_event.is_set():
                from app.core.errors import TaskCancelled

                raise TaskCancelled()
            if on_progress:
                on_progress(i / max(len(buildings), 1))
        m = _extrude_one(b, terrain)
        if m is not None and len(m.faces) > 0:
            meshes.append(m)
    if not meshes:
        return trimesh.Trimesh()
    return trimesh.util.concatenate(meshes)


def _extrude_one(b: BuildingLocal, terrain: TerrainGrid) -> trimesh.Trimesh | None:
    poly = orient(b.poly, sign=1.0)  # 外环逆时针
    verts: list[list[float]] = []
    faces: list[tuple[int, int, int]] = []

    ring = np.asarray(poly.exterior.coords)[:-1]  # 去掉闭合点
    if len(ring) < 3:
        return None
    ground = np.array([terrain.sample(x, y) for x, y in ring])
    base_z = float(ground.min()) - 1.0
    top_z = float(ground.max()) + b.height

    # --- 顶面(切成小三角形,统一高度 top_z) ---
    # triangulate_polygon 出来的三角形方向已保证逆时针(面朝上)
    tv, tf = triangulate_polygon(poly)
    top_offset = len(verts)
    for v in tv:
        verts.append([float(v[0]), float(v[1]), top_z])
    for f in tf:
        faces.append((int(f[0]) + top_offset, int(f[1]) + top_offset, int(f[2]) + top_offset))

    # --- 侧壁(外环和每个内环都要) ---
    for ring_pts, ring_ground in _iter_rings(poly, terrain, ring, ground):
        n = len(ring_pts)
        for i in range(n):
            j = (i + 1) % n
            p_i, p_j = ring_pts[i], ring_pts[j]
            # 侧壁四边形按 (a,c,bb)/(a,d,c) 摆,墙面朝"沿轮廓走时的右手边"。
            # 外环逆时针,右手边是楼外面;内环(内院)顺时针,右手边正好是
            # 内院——所以内外环用同一套公式,不用分开讨论
            a = _v(verts, p_i, base_z)
            bb = _v(verts, p_i, top_z)
            c = _v(verts, p_j, top_z)
            d = _v(verts, p_j, base_z)
            faces.append((a, c, bb))
            faces.append((a, d, c))

    # 这里不调 trimesh 的 fix_normals():它只对"每个顶点都共享、边边相接"
    # 的封闭网格才起作用,我们上面每个顶点都是单独建的、方向也手工摆对了
    return trimesh.Trimesh(vertices=np.asarray(verts), faces=np.asarray(faces), process=False)


def _iter_rings(poly, terrain, outer_ring, outer_ground):
    """依次给出外环和各内环(内院)的点与地面高程。

    外环逆时针、内环顺时针(orient 保证的 Shapely 规矩),两者墙面
    朝向都按"行进方向右手边"推,正好一个朝楼外一个朝内院。
    """
    yield outer_ring, outer_ground
    for inner in poly.interiors:
        pts = np.asarray(inner.coords)[:-1]
        if len(pts) < 3:
            continue
        yield pts, np.array([terrain.sample(x, y) for x, y in pts])


def _v(verts: list, p: np.ndarray, z: float) -> int:
    verts.append([float(p[0]), float(p[1]), float(z)])
    return len(verts) - 1
