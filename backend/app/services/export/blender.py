"""导出 FBX / DAE:这俩格式专利/规格封闭,没有靠谱的纯 Python 库,
只能借 Blender 的命令行模式帮我们转一手。

Blender 转格式要开它自带的命令行模式(blender -b 不开窗口,
-P 跑我们给的脚本)。没装 Blender 的话 capabilities 早把按钮禁用了,
正常到不了这里。
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from app.services.export.registry import ExportContext, find_blender, load_hub, register

_TIMEOUT = 600  # 等 Blender 的上限,秒(大模型转 FBX 可能挺慢)


def _blender_export(ctx: ExportContext, fmt: str) -> str:
    blender = find_blender(ctx.settings)
    if blender is None:
        raise ImportError("Blender executable not found")
    script = Path(__file__).parent / "blender_script.py"
    out = ctx.export_dir / f"{ctx.task_id}.{fmt}"
    # 前端关了图层时,先过滤出一份临时 glb 再交给 Blender(用完就删)
    src = ctx.task_dir / "hub.glb"
    filtered: Path | None = None
    if ctx.layers is not None:
        filtered = ctx.export_dir / "_filtered_hub.glb"
        ctx.on_progress(0.05, "packing filtered glb")
        load_hub(ctx).export(file_obj=str(filtered), file_type="glb")
        src = filtered
    ctx.on_progress(0.1, f"launching blender ({fmt})")
    cmd = [
        blender, "--factory-startup", "-b",
        "-P", str(script), "--",
        str(src), str(out), fmt,
    ]
    # --factory-startup = 不加载用户自己的配置和插件,不让它们捣乱
    # errors="replace":Blender 的输出里偶尔混几个不合法的字节,不兜着
    # 会直接抛编码异常,连报错内容都看不到
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, errors="replace",
                              timeout=_TIMEOUT)  # noqa: S603
        if proc.returncode != 0 or not out.exists():
            tail = (proc.stderr or proc.stdout or "")[-1500:]  # 只留报错末尾 1500 字,够排查了
            raise RuntimeError(f"Blender export failed (exit {proc.returncode}):\n{tail}")
    finally:
        if filtered is not None:
            filtered.unlink(missing_ok=True)
    ctx.on_progress(1.0, f"{fmt} ready")
    return out.name


@register("fbx", "3D", "FBX (needs Blender)", blender=True)
def export_fbx(ctx: ExportContext) -> str:
    return _blender_export(ctx, "fbx")


@register("dae", "3D", "DAE Collada (needs Blender)", blender=True)
def export_dae(ctx: ExportContext) -> str:
    return _blender_export(ctx, "dae")
