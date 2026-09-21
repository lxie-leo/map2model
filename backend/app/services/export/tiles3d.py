"""导出 3D Tiles 1.1(Cesium 这类数字地球吃的格式,能飞着看的大场景)。

思路:整个模型太大,一个文件甩给浏览器会卡死,所以像切蛋糕一样
一分为四,哪块三角形太多就继续切,每小块(叶子)最多 2 万个三角形,
各自存成一个 glb。Cesium 远看只拿粗块,走近了才加载细块。

几个关键参数,用人话说:
- geometricError = "离多远之内必须看清这块细节"。根节点值最大,
  越往下越小,叶子填 0(已是最细,不用再换);
- refine = REPLACE:走近了用小块整个替掉大块,而不是叠在上面;
- root 的 transform 是个 4x4 矩阵,负责把"以框选中心为原点、
  东西南北朝正的方向"换算成"以地心为原点"的坐标——16 个数字的
  排法 Cesium 认一种,照 Projector 给的塞进去就行,把模型钉在地球上
  该在的位置(海拔取这块地的平均高程)。
最后 tileset.json 加一堆 glb 打成一个 zip 交付。
"""

from __future__ import annotations

import numpy as np
import trimesh

from app.services.export.registry import ExportContext, load_hub, register
from app.services.mesh.scene import build_scene
from app.services.projection import Projector
from app.utils.fs import zip_dir

_LEAF_MAX_TRIS = 20_000
_MAX_DEPTH = 8


@register("3dtiles", "GIS", "3D Tiles 1.1 (Cesium)")
def export_tiles3d(ctx: ExportContext) -> str:
    ctx.on_progress(0.05, "loading hub.glb")
    scene = load_hub(ctx)

    # 1) 写进 glb 的顶点保持 hub 的 Y-up 原样——3D Tiles 1.1 规定 glTF 内容
    #    就用 glTF 自己的 Y-up 约定,Cesium 加载时会自动转到地球坐标。
    #    (早期版本这里手动换过 Z-up,结果模型在 Cesium 里躺倒 90°、飞出
    #    包围盒被剔除,整个场景什么都看不见)
    #    切分用的重心和包围盒才要 Z-up(它们属于瓦片坐标系:东/北/上),
    #    在下面单独换算,和写进 glb 的顶点分开算
    layer_data: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    for name in scene.geometry:
        mesh = scene.geometry[name]
        layer_data[name] = (np.asarray(mesh.vertices), mesh.faces)

    def to_zup(pts: np.ndarray) -> np.ndarray:
        # Y-up(x东/y上/z南)→ Z-up(x东/y北/z上):Y/Z 互换再翻北向,
        # 只是转方向不是镜像,面朝向不变
        p = pts[:, [0, 2, 1]].copy()
        p[:, 1] *= -1
        return p

    # 2) 给每个三角形记一笔:中心点在哪、属于哪个图层、是第几张脸(切分用)
    all_centroids: list[np.ndarray] = []
    tri_layer: list[str] = []
    tri_face: list[int] = []
    for name, (v, f) in layer_data.items():
        if len(f) == 0:
            continue
        c = to_zup(v[f].mean(axis=1))  # 每个三角形重心的平均位置,换到 Z-up 再记
        all_centroids.append(c[:, :2])  # 切分只看平面上落在哪,不管高度
        tri_layer.extend([name] * len(f))
        tri_face.extend(range(len(f)))
    if not tri_layer:
        raise ValueError("Scene is empty, cannot generate 3D Tiles")
    centroids = np.concatenate(all_centroids)
    tri_layer_arr = np.asarray(tri_layer)
    tri_face_arr = np.asarray(tri_face)
    total = len(tri_layer_arr)

    # 高度范围也在 Z-up 里量(就是 hub 的 y 轴)
    zmin = float(min(v[:, 1].min() for v, _ in layer_data.values()))
    zmax = float(max(v[:, 1].max() for v, _ in layer_data.values()))

    ctx.on_progress(0.15, f"quadtree split ({total} triangles)")
    tiles_dir = ctx.export_dir / "tiles"
    tiles_dir.mkdir(parents=True, exist_ok=True)
    leaf_counter = [0]

    def write_leaf(tri_ids: np.ndarray) -> dict:
        # 一刀切到底了:把这块的三角形按图层拼成小场景写成 glb。
        # 只带走这个块用到的顶点(重新编号),别把整个图层都塞进瓦片
        leaf_counter[0] += 1
        leaf_name = f"{leaf_counter[0]:04d}"
        by_layer: dict[str, list[int]] = {}
        for t in tri_ids:
            by_layer.setdefault(tri_layer_arr[t], []).append(tri_face_arr[t])
        zup_meshes: dict[str, trimesh.Trimesh] = {}
        for lname, face_rows in by_layer.items():
            v, f = layer_data[lname]
            sub_faces = f[np.asarray(face_rows)]
            used = np.unique(sub_faces)
            remap = np.full(len(v), -1, dtype=np.int64)
            remap[used] = np.arange(len(used))
            sub_v = v[used]
            sub_f = remap[sub_faces]
            m = trimesh.Trimesh(vertices=sub_v, faces=sub_f, process=False)
            zup_meshes[lname] = m
        glb_path = tiles_dir / f"{leaf_name}.glb"
        build_scene(zup_meshes).export(file_obj=str(glb_path), file_type="glb")

        pts = centroids[tri_ids]
        cx, cy = (pts[:, 0].min() + pts[:, 0].max()) / 2, (pts[:, 1].min() + pts[:, 1].max()) / 2
        return {
            "boundingVolume": {"box": [
                float(cx), float(cy), (zmin + zmax) / 2,
                float(pts[:, 0].max() - cx), 0, 0,
                0, float(pts[:, 1].max() - cy), 0,
                0, 0, float(zmax - zmin) / 2 or 1.0,
            ]},
            "geometricError": 0,
            "content": {"uri": f"tiles/{leaf_name}.glb"},
        }

    def build_node(tri_ids: np.ndarray, depth: int) -> dict:
        if len(tri_ids) <= _LEAF_MAX_TRIS or depth >= _MAX_DEPTH:
            return write_leaf(tri_ids)
        pts = centroids[tri_ids]
        mx = (pts[:, 0].min() + pts[:, 0].max()) / 2
        my = (pts[:, 1].min() + pts[:, 1].max()) / 2
        # 按中线切四块(左下/右下/左上/右上),跟切蛋糕一样
        children = []
        x = pts[:, 0]
        y = pts[:, 1]
        for cond in ((x < mx) & (y < my), (x >= mx) & (y < my),
                     (x < mx) & (y >= my), (x >= mx) & (y >= my)):
            sub = tri_ids[cond]
            if len(sub):
                children.append(build_node(sub, depth + 1))
        if len(children) == 1:
            return children[0]  # 四刀下去全落在一块(三角形挤在同一处),不用再分,直接当叶子
        done = len(tri_ids)
        ctx.on_progress(0.15 + 0.7 * (1 - done / total), f"tiles {leaf_counter[0]}, {done} left")
        diag = float(np.linalg.norm(pts.max(axis=0) - pts.min(axis=0)))
        return {
            "boundingVolume": {"box": [
                float(mx), float(my), (zmin + zmax) / 2,
                float(pts[:, 0].max() - mx), 0, 0,
                0, float(pts[:, 1].max() - my), 0,
                0, 0, float(zmax - zmin) / 2 or 1.0,
            ]},
            "geometricError": diag,
            "refine": "REPLACE",
            "children": children,
        }

    root = build_node(np.arange(total), depth=0)

    # transform:把局部米制坐标钉到地球上的那 16 个数(Cesium 认的排法),
    # 海拔基准用这块地的平均高程,不然整块地会陷进海里或悬在半空
    projector = Projector(tuple(ctx.meta["bbox"]))
    h0 = float(ctx.meta.get("median_h") or 0.0)
    tileset = {
        "asset": {"version": "1.1"},
        "geometricError": float(root["geometricError"]),
        "root": {**root, "transform": projector.enu_to_ecef_matrix(h0)},
    }

    ctx.on_progress(0.9, "packing zip")
    from app.utils.caching import write_json_atomic

    write_json_atomic(ctx.export_dir / "tileset.json", tileset)
    filename = f"{ctx.task_id}_3dtiles.zip"
    zip_dir(ctx.export_dir, ctx.export_dir / filename)  # tileset.json 连同 tiles/ 里的 glb 一锅端进 zip
    # 打完包把散着的文件清掉,只留 zip 交付
    for p in tiles_dir.iterdir():
        p.unlink()
    tiles_dir.rmdir()
    (ctx.export_dir / "tileset.json").unlink()
    ctx.on_progress(1.0, f"3dtiles ready ({leaf_counter[0]} tiles)")
    return filename
