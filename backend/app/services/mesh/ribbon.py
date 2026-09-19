"""顺着道路/铁路/河流的走向,左右各扩出半个宽度,铺成一条贴地的带子。

转角怎么办:每个顶点取前后两段"垂直方向"的平均往外偏,弯就自然张开;
偏移量最多 2 倍半宽,不然急弯处会戳出尖刺。
各层都要垫高一点点,不然和地形/别的图层贴在同一高度会闪面(z-fighting):
  绿地 +0.03 < 道路 +0.08 < 铁路 +0.12 < 桥 +2.0
水面反过来,往地面以下沉 0.25 米。
"""

from __future__ import annotations

import numpy as np
import trimesh
from shapely.geometry.polygon import orient

from app.services.terrain import TerrainGrid
from app.utils.geom import ensure_faces_up, triangulate_polygon

# 各图层垫高多少米(不垫会被地形或别的层盖住)
LIFT_GREEN = 0.03
LIFT_ROAD = 0.08
LIFT_RAIL = 0.12
LIFT_BRIDGE = 2.0
WATER_CUT = -0.25


def build_ribbon(
    pts: np.ndarray,
    width: float,
    lift: float,
    terrain: TerrainGrid,
) -> trimesh.Trimesh:
    """把一条折线铺成贴地的带子(三角形拼的)。lift 是垫高多少米,桥就传 LIFT_BRIDGE。"""
    n = len(pts)
    if n < 2 or width <= 0:
        return trimesh.Trimesh()
    half = width / 2.0

    # 每一段的朝向,和它左手边垂直的方向
    seg = pts[1:] - pts[:-1]                      # (n-1, 2)
    seg_len = np.linalg.norm(seg, axis=1)         # (n-1,)
    # 太短的段(<0.5 米)不要:OSM 数据里常有两个点挤在一起的情况,
    # 段比路宽还短的话左右扩出去的带子会自己交叉,翻出朝下的三角
    if (seg_len < 0.5).any():
        keep = [0]
        for i in range(1, len(pts)):
            if np.linalg.norm(pts[i] - pts[keep[-1]]) >= 0.5 or i == len(pts) - 1:
                keep.append(i)
        pts = pts[np.asarray(keep)]
        n = len(pts)
        if n < 2:
            return trimesh.Trimesh()
        seg = pts[1:] - pts[:-1]
        seg_len = np.linalg.norm(seg, axis=1)
    dirs = seg / seg_len[:, None]
    normals = np.stack([-dirs[:, 1], dirs[:, 0]], axis=1)  # 左手边的垂直方向

    # 每个顶点往外偏的方向(头尾两端只能用单侧方向)
    miter = np.zeros((n, 2))
    miter[0] = normals[0]
    miter[-1] = normals[-1]
    for i in range(1, n - 1):
        m = normals[i - 1] + normals[i]
        norm = np.linalg.norm(m)
        if norm < 1e-9:            # 180 度折返,任取一侧
            m = normals[i]
            norm = 1.0
        m = m / norm
        # 偏移量最多 2 倍半宽,不然急弯处会戳出尖刺
        cos_a = max(np.dot(m, normals[i]), 0.5)
        miter[i] = m / cos_a

    # 提醒:这两个变量名跟实际方向是反的(normals 是行进方向的左手边,
    # 加 half 那个才是真左侧)。带子左右对称,存哪边数学上等价,但下面
    # 的三角形绕向是跟这套赋值配对的——想"纠正"名字先连带改绕向
    left = pts - miter * half       # (n, 2)
    right = pts + miter * half      # (n, 2)
    z = np.array([terrain.sample(x, y) for x, y in pts]) + lift

    verts = np.empty((n * 2, 3))
    verts[0::2, :2] = left          # 偶数下标 = left 变量
    verts[0::2, 2] = z
    verts[1::2, :2] = right         # 奇数下标 = right 变量
    verts[1::2, 2] = z

    faces = []
    for i in range(n - 1):
        a, b = i * 2, i * 2 + 1        # 当前段左、右
        c, d = (i + 1) * 2, (i + 1) * 2 + 1  # 下一段左、右
        # 顶点按 (a,c,b)/(b,c,d) 摆,面朝上;要是摆成 (a,b,c) 面就朝下,
        # 从上往下看会整条消失(渲染只画朝观众的那一面)
        faces.append((a, c, b))
        faces.append((b, c, d))

    # 再兜一道底:急弯/特殊数据下左右带子可能交叉,个别三角会翻到朝下,
    # 挨个查一遍,朝下的翻回来(带子永远该朝上)
    faces = ensure_faces_up(verts, np.asarray(faces))
    return trimesh.Trimesh(vertices=verts, faces=faces, process=False)


def build_water_surface(
    poly,
    terrain: TerrainGrid,
    cut: float = WATER_CUT,
) -> trimesh.Trimesh:
    """水面:切成小三角形后,每个顶点贴着地面往下沉 cut 米(水面比地面低一点)。"""
    poly = orient(poly, sign=1.0)
    v2, faces = triangulate_polygon(poly)  # 三角化内部已保证方向统一逆时针(面朝上)
    verts = np.empty((len(v2), 3))
    verts[:, :2] = v2
    verts[:, 2] = [terrain.sample(x, y) + cut for x, y in v2]
    return trimesh.Trimesh(vertices=verts, faces=np.asarray(faces), process=False)


def build_layer_ribbons(
    lines: list,
    lift: float,
    terrain: TerrainGrid,
    *,
    on_progress=None,
    cancel_event=None,
) -> trimesh.Trimesh:
    """把同一图层的整组线都铺成带子,再合成一个网格。"""
    meshes: list[trimesh.Trimesh] = []
    for i, ln in enumerate(lines):
        if i % 500 == 0:
            if cancel_event is not None and cancel_event.is_set():
                from app.core.errors import TaskCancelled

                raise TaskCancelled()
            if on_progress:
                on_progress(i / max(len(lines), 1))
        actual_lift = LIFT_BRIDGE if ln.bridge else lift
        m = build_ribbon(ln.pts, ln.width, actual_lift, terrain)
        if len(m.faces) > 0:
            meshes.append(m)
    if not meshes:
        return trimesh.Trimesh()
    return trimesh.util.concatenate(meshes)
