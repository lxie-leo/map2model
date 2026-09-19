"""导出 OBJ + MTL(建模圈最老牌的通用格式,啥软件都能开)。

从 hub.glb 把场景读回来再写成 OBJ 文本。OBJ 官方没规定哪根轴是"上",
但 CAD 和建模软件里大家习惯 Z 朝上——跟我们内部坐标一致,所以这里
原样直写、一根轴都不用转(不像 GLB 那样得转给 Blender 看)。
每个图层写一个 o 对象,再配一个 usemtl 指到 .mtl 里的颜色。
"""

from __future__ import annotations

import numpy as np

from app.services.export.registry import ExportContext, load_hub, register
from app.services.vector.draw2d import PALETTE_3D


@register("obj", "3D", "OBJ + MTL")
def export_obj(ctx: ExportContext) -> str:
    ctx.on_progress(0.2, "loading hub.glb")
    scene = load_hub(ctx)
    obj_name = f"{ctx.task_id}.obj"
    mtl_name = f"{ctx.task_id}.mtl"
    obj_path = ctx.export_dir / obj_name
    mtl_path = ctx.export_dir / mtl_name

    # 收集各图层网格。hub 里存的是 Y-up(给 Blender 看的),这里转回 Z-up:
    # (x,y,z) → (x,-z,y)。这只是把空间转了个方向,不是镜像,所以三角形
    # 顶点顺序原样保留就行(顶点顺序一翻面就全朝里了)
    geoms: list[tuple[str, np.ndarray, np.ndarray]] = []
    for name in scene.geometry:
        mesh = scene.geometry[name]
        v = mesh.vertices[:, [0, 2, 1]].copy()
        v[:, 1] *= -1
        geoms.append((name, v, mesh.faces))

    ctx.on_progress(0.5, f"writing {len(geoms)} layers")
    with open(obj_path, "w", encoding="utf-8", newline="\n") as fo:
        fo.write(f"# map2model export (Z-up, meters, origin=bbox center)\nmtllib {mtl_name}\n")
        # 每个图层一口气写完 o + 顶点 + 材质 + 面,再写下一层。
        # OBJ 的面只认"最近一个 o"分组,要是先写完所有顶点再回头写面,
        # 所有面都会被算到最后一个 o 头上,导入软件里就分不了组了
        offset = 1  # OBJ 数顶点从 1 开始(不是 0),各图层顶点号接着上一轮往下编
        for name, v, f in geoms:
            fo.write(f"o {name}\n")
            for x, y, z in v:
                fo.write(f"v {x:.3f} {y:.3f} {z:.3f}\n")
            fo.write(f"usemtl mat_{name}\n")
            for a, b, c in f:
                fo.write(f"f {a + offset} {b + offset} {c + offset}\n")
            offset += len(v)

    with open(mtl_path, "w", encoding="utf-8", newline="\n") as fm:
        for name in dict.fromkeys(n for n, _, _ in geoms):
            color = PALETTE_3D.get(name, "#cccccc")
            r = int(color[1:3], 16) / 255
            g = int(color[3:5], 16) / 255
            b = int(color[5:7], 16) / 255
            fm.write(f"newmtl mat_{name}\nKd {r:.3f} {g:.3f} {b:.3f}\nKa 0 0 0\nKs 0 0 0\nd 1\nillum 1\n\n")

    ctx.on_progress(1.0, "obj ready")
    return obj_name
