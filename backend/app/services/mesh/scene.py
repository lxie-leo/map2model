"""场景组装:六个图层的网格合成一个 trimesh.Scene,导出成枢纽文件 hub.glb。

- 内部坐标是"Z 朝上",glTF 规范要求"Y 朝上",导出前统一换轴 (x, z, -y);
- 每个图层一个叫得出名字的节点(TERRAIN/BUILDING/...),前端靠节点名开关图层;
- 每层一种纯色材质(白模风格),颜色和 2D 地图同一套调色板。
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import trimesh
from trimesh.visual import TextureVisuals
from trimesh.visual.material import PBRMaterial

from app.services.vector.draw2d import PALETTE_3D

logger = logging.getLogger("app.mesh.scene")

# 图层节点顺序(也决定了 glTF 里的节点列表顺序)
LAYER_ORDER = ["TERRAIN", "GREEN", "WATER", "BUILDING", "ROAD", "RAILWAY"]


def _to_yup(mesh: trimesh.Trimesh) -> trimesh.Trimesh:
    """把"Z 朝上"换成 glTF 要的"Y 朝上":坐标 (x,y,z) 变 (x,z,-y)。

    注意三角形顶点顺序不用动:这个换法只是把整个空间"转了个方向"
    (数学上叫行列式为 +1),不翻转空间,面朝哪边转完还朝哪边。
    要是顺手把顶点顺序也对调一下,所有面就全翻到背面去了。
    """
    v = mesh.vertices[:, [0, 2, 1]].copy()
    v[:, 2] *= -1
    return trimesh.Trimesh(vertices=v, faces=mesh.faces, process=False)


def _hex_rgb(color: str) -> list[int]:
    return [int(color[i:i + 2], 16) for i in (1, 3, 5)]


def build_scene(zup_layers: dict[str, trimesh.Trimesh | None]) -> trimesh.Scene:
    """把 {图层名: Z 朝上网格} 组装成 Y 朝上的场景(每层带自己的颜色)。"""
    scene = trimesh.Scene()
    for name in LAYER_ORDER:
        mesh = zup_layers.get(name)
        if mesh is None or len(mesh.faces) == 0:
            continue
        m = _to_yup(mesh)
        m.name = name  # 保证 glb 里的 geometry 名就是图层名(读回时按名字分组)
        rgb = _hex_rgb(PALETTE_3D[name])
        mat = PBRMaterial(
            name=name,
            baseColorFactor=[rgb[0], rgb[1], rgb[2], 255],
            metallicFactor=0.0,
            roughnessFactor=0.95,
        )
        m.visual = TextureVisuals(material=mat)
        # geom_name 决定 glb 里的 geometry 名(读回时按它分组),node_name 是场景图节点
        scene.add_geometry(m, node_name=name, geom_name=name)
    return scene


def scene_bounds_zup(zup_layers: dict[str, trimesh.Trimesh | None]) -> dict | None:
    """把所有图层的点倒在一起,算一个刚好罩住的大盒子(Z 朝上的局部米坐标),3D Tiles 要用它写 boundingVolume。"""
    pts = [m.vertices for m in zup_layers.values() if m is not None and len(m.vertices)]
    if not pts:
        return None
    all_v = np.concatenate(pts, axis=0)
    return {
        "min": all_v.min(axis=0).tolist(),
        "max": all_v.max(axis=0).tolist(),
    }


def write_hub(task_dir: Path, scene: trimesh.Scene) -> Path:
    """导出枢纽文件 hub.glb(所有 3D 格式导出都以它为源)。"""
    path = task_dir / "hub.glb"
    scene.export(file_obj=str(path), file_type="glb")
    logger.info("hub.glb written: %.1f MB", path.stat().st_size / 1e6)
    return path


def load_hub_scene(task_dir: Path) -> trimesh.Scene:
    """导出器用:读回 hub.glb(节点名/材质都保留)。"""
    return trimesh.load(str(task_dir / "hub.glb"), force="scene")
