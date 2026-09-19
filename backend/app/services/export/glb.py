"""GLB 导出:直接复制枢纽文件(生成时就是标准 Y-up glTF 2.0)。

前端关了图层时不能整包照抄了,读回场景删掉不要的图层再重新打包。"""

from __future__ import annotations

import shutil

from app.services.export.registry import ExportContext, load_hub, register


@register("glb", "3D", "GLB(glTF 2.0)")
def export_glb(ctx: ExportContext) -> str:
    filename = f"{ctx.task_id}.glb"
    if ctx.layers is None:
        ctx.on_progress(0.2, "copying hub.glb")
        shutil.copyfile(ctx.task_dir / "hub.glb", ctx.export_dir / filename)
    else:
        ctx.on_progress(0.2, "packing filtered glb")
        load_hub(ctx).export(file_obj=str(ctx.export_dir / filename), file_type="glb")
    ctx.on_progress(1.0, "glb ready")
    return filename
