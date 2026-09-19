"""导出 USDZ(Apple AR 用的格式,iPhone/Mac 上点开就能立在桌面上看)。

用 usd-core(pip 装的 pxr 包)原生写 USD,不用劳驾 Blender。
坐标省事:hub.glb 是 Y-up,USD 默认也认 Y 是上,几何原样搬。
USDZ 说白了就是个 zip:把 usd 模型文件打包改个后缀。第一样东西必须
是 usdc 模型且不许压缩(Apple 的规矩)。优先用 USD 自带的 ZipFileWriter
(它会自动做 64 字节对齐,苹果要求的),没有这个工具就退回标准库手写。
"""

from __future__ import annotations

import gc
import zipfile

from app.services.export.registry import ExportContext, load_hub, register


@register("usdz", "3D", "USDZ(AR 快速预览)", requires=("pxr",))
def export_usdz(ctx: ExportContext) -> str:
    import numpy as np
    from pxr import Usd, UsdGeom, Vt

    from app.services.vector.draw2d import PALETTE_3D

    ctx.on_progress(0.2, "loading hub.glb")
    scene = load_hub(ctx)
    stage = Usd.Stage.CreateNew(str(ctx.export_dir / "model.usdc"))
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.y)
    UsdGeom.SetStageMetersPerUnit(stage, 1.0)

    ctx.on_progress(0.4, "writing USD prims")
    for name in scene.geometry:
        mesh = scene.geometry[name]
        prim = UsdGeom.Mesh.Define(stage, f"/Scene/{name}")
        points = mesh.vertices.astype(np.float32)
        prim.CreatePointsAttr(Vt.Vec3fArray.FromNumpy(points))
        counts = [3] * len(mesh.faces)
        prim.CreateFaceVertexCountsAttr(Vt.IntArray(counts))
        # pxr 0.26 不认 numpy 的整数数组,得先转回普通 Python 列表
        prim.CreateFaceVertexIndicesAttr(
            Vt.IntArray(mesh.faces.astype(np.int32).ravel().tolist())
        )
        prim.CreateSubdivisionSchemeAttr().Set(UsdGeom.Tokens.none)
        color = PALETTE_3D.get(name, "#cccccc")
        rgb = tuple(int(color[i:i + 2], 16) / 255 for i in (1, 3, 5))
        prim.CreateDisplayColorAttr().Set([rgb])
    stage.GetRootLayer().Save()

    ctx.on_progress(0.8, "packing usdz")
    usdc_path = ctx.export_dir / "model.usdc"
    filename = f"{ctx.task_id}.usdz"
    usdz_path = ctx.export_dir / filename

    writer = getattr(Usd, "ZipFileWriter", None)
    if writer is not None:
        w = writer.Open(str(usdz_path))
        try:
            w.AddFile(str(usdc_path))
        finally:
            w.Close()
    else:
        # 手动打包:zip 里第一个必须是 usdc 模型文件,而且只能"存"不能压
        # (ZIP_STORED = 原样塞进去;压缩了苹果的 AR 就不认)。
        # 还得保证每个文件内容从 64 的倍数那个字节开始(苹果的硬规矩):
        # 办法是往 zip 头部塞一截没用的填充字节,把内容顶到对齐的位置
        offset = 0  # 下一个文件的头从 zip 的第几个字节开始
        with zipfile.ZipFile(usdz_path, "w") as zf:
            arcname = "model.usdc"
            zi = zipfile.ZipInfo(arcname)
            header = 30 + len(arcname.encode())  # zip 本地头 30 字节 + 文件名
            pad = -(offset + header) % 64
            if pad:
                zi.extra = b"\x00" * pad  # 填充塞进"扩展字段",解压工具会忽略它
            zi.compress_type = zipfile.ZIP_STORED
            zf.writestr(zi, usdc_path.read_bytes())
            offset = zf.fp.tell()

    # 中间文件 model.usdc 用完了删掉。pxr 会一直攥着它的内存映射,
    # Windows 不许删还开着的文件,得先让内存里的舞台对象散掉再删
    del stage
    gc.collect()
    usdc_path.unlink(missing_ok=True)

    ctx.on_progress(1.0, "usdz ready")
    return filename
