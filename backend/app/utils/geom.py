"""几何方面的工具:算 bbox 面积、经纬度换瓦片编号、把多边形切成三角形。

切三角形优先用 mapbox_earcut,又快又准,带孔的也不怕。
坑:本机 Python 3.14 装不上它(没有对应的安装包),那就用备胎方案
"德劳奈三角剖分":先把边界点连成一片三角形,再把中心落在多边形外面
(或者正好在孔里)的三角形扔掉,剩下的就是想要的。
"""

from __future__ import annotations

import math

import numpy as np
from pyproj import Geod
from shapely.geometry import Polygon

_GEOD = Geod(ellps="WGS84")

try:  # 先试着 import mapbox_earcut(大多数 Python 版本都有现成的安装包)
    import mapbox_earcut as _earcut
except ImportError:  # pragma: no cover - 装没装看运行环境
    _earcut = None


def bbox_area_km2(bbox: tuple[float, float, float, float]) -> float:
    """算 bbox 的面积,单位平方公里。按地球是个椭球来算——经纬度的格子越往两极越窄,直接当方块乘会算大。"""
    min_lon, min_lat, max_lon, max_lat = bbox
    area_m2 = abs(
        _GEOD.geometry_area_perimeter(
            Polygon(
                [
                    (min_lon, min_lat),
                    (max_lon, min_lat),
                    (max_lon, max_lat),
                    (min_lon, max_lat),
                ]
            )
        )[0]
    )
    return area_m2 / 1e6


def lonlat_to_tile(lon: float, lat: float, z: int) -> tuple[int, int]:
    """经纬度换算成第 z 层的瓦片编号 (x, y)。最后夹一下范围,免得边缘点算出界。"""
    n = 2**z
    x = int((lon + 180.0) / 360.0 * n)
    lat_rad = math.radians(lat)
    y = int((1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n)
    return min(max(x, 0), n - 1), min(max(y, 0), n - 1)


def ensure_ccw(ring: np.ndarray) -> np.ndarray:
    """把环的方向统一成逆时针(Shapely 规定外环得这么转,方向反了它不认)。"""
    if _signed_area(ring) < 0:
        return ring[::-1]
    return ring


def _signed_area(ring: np.ndarray) -> float:
    """鞋带公式算带符号的面积:正数是逆时针,负数是顺时针。"""
    x, y = ring[:, 0], ring[:, 1]
    return 0.5 * float(np.sum(x * np.roll(y, -1) - np.roll(x, -1) * y))


def triangulate_polygon(poly: Polygon) -> tuple[np.ndarray, np.ndarray]:
    """把多边形切成一堆三角形,带孔的也能切。返回(顶点数组 n×2,三角形索引 m×3)。

    保证每个三角形都是逆时针方向(面朝上),调用方不用再自己检查翻转。
    """
    verts, faces = (_triangulate_earcut(poly) if _earcut is not None
                    else _triangulate_delaunay(poly))
    return verts, ensure_faces_up(verts, faces)


def ensure_faces_up(verts: np.ndarray, faces: np.ndarray) -> np.ndarray:
    """检查每个三角形的方向,朝下的把后两个顶点换一下位置(换了就朝上)。

    只看 x/y 平面上的投影方向,适合"摊在地面上"的面(高度不参与判向)。
    """
    faces = np.asarray(faces, dtype=np.int64).copy()
    if len(faces) == 0:
        return faces
    tri = verts[faces]
    cross = ((tri[:, 1, 0] - tri[:, 0, 0]) * (tri[:, 2, 1] - tri[:, 0, 1])
             - (tri[:, 2, 0] - tri[:, 0, 0]) * (tri[:, 1, 1] - tri[:, 0, 1]))
    flip = cross < 0
    faces[flip] = faces[flip][:, [0, 2, 1]]
    return faces


def _triangulate_earcut(poly: Polygon) -> tuple[np.ndarray, np.ndarray]:
    rings = [np.asarray(poly.exterior.coords)[:-1]]
    for inner in poly.interiors:
        rings.append(np.asarray(inner.coords)[:-1])
    verts = np.concatenate(rings, axis=0)
    ring_ends = np.cumsum([len(r) for r in rings])
    faces = _earcut.triangulate_float64(verts, ring_ends).reshape(-1, 3)
    return verts, faces


def _triangulate_delaunay(poly: Polygon) -> tuple[np.ndarray, np.ndarray]:
    """备胎方案:边界点做德劳奈三角剖分,只留中心还在多边形里的三角形。"""
    from matplotlib.tri import Triangulation

    rings = [np.asarray(poly.exterior.coords)[:-1]]
    for inner in poly.interiors:
        rings.append(np.asarray(inner.coords)[:-1])
    verts = np.concatenate(rings, axis=0)
    tri = Triangulation(verts[:, 0], verts[:, 1])
    faces = tri.get_masked_triangles()
    centroids = verts[faces].mean(axis=1)
    from shapely.geometry import Point

    keep = [i for i, c in enumerate(centroids) if poly.covers(Point(c))]
    return verts, np.asarray(faces)[keep]
