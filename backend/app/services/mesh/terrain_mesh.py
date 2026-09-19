"""把高程网格变成一张连绵起伏的地面:每个方格斜切一刀,分成两个三角形。"""

from __future__ import annotations

import numpy as np
import trimesh

from app.services.terrain import TerrainGrid


def build_terrain_mesh(grid: TerrainGrid) -> trimesh.Trimesh:
    """每个格子斜着切一刀分成两个三角形,整张地面面朝上。"""
    nx, ny = grid.nx, grid.ny
    xs = grid.origin_x + np.arange(nx) * grid.dx
    ys = grid.origin_y + np.arange(ny) * grid.dy
    grid_x, grid_y = np.meshgrid(xs, ys)          # (ny, nx)

    verts = np.empty((nx * ny, 3))
    verts[:, 0] = grid_x.ravel()
    verts[:, 1] = grid_y.ravel()
    verts[:, 2] = grid.z.ravel()

    idx = np.arange(nx * ny).reshape(ny, nx)
    a = idx[:-1, :-1].ravel()      # 左下
    b = idx[:-1, 1:].ravel()       # 右下
    c = idx[1:, :-1].ravel()       # 左上
    d = idx[1:, 1:].ravel()        # 右上
    # 三角形顶点按这个顺序排,面才朝上(+Z),不用再让 trimesh 猜方向
    faces = np.stack([np.concatenate([a, b]),
                      np.concatenate([b, d]),
                      np.concatenate([c, c])], axis=1)

    return trimesh.Trimesh(vertices=verts, faces=faces, process=False)
