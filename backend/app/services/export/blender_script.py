"""这段脚本不是我们跑的,是丢给 Blender 自带的 Python 跑的:进 hub.glb,转成 fbx/dae。

调用方式:blender --factory-startup -b -P blender_script.py -- <input.glb> <output> <fmt>
"-" 一长串是 Blender 自己的开关,"--" 后面的才是传给脚本的参数:
输入 hub.glb、输出路径、目标格式(fbx/dae)。
"""

import sys

argv = sys.argv[sys.argv.index("--") + 1:]  # 只拿 "--" 之后的参数
src, dst, fmt = argv[0], argv[1], argv[2]

import bpy  # noqa: E402  (Blender 家的库,只有 Blender 里才有,放前面必挂)

bpy.ops.wm.read_factory_settings(use_empty=True)  # 开个全空场景,不带默认立方体那套
# GLB 是 Y-up,Blender 认 Z-up——导入器会自动转好,不用我们操心
bpy.ops.import_scene.gltf(filepath=src)

if fmt == "fbx":
    bpy.ops.export_scene.fbx(
        filepath=dst,
        use_selection=False,   # 全场景都导,不是只导选中的
        apply_unit_scale=True,  # 尺度按米写,免得进了 Unity 变成巨人国
        add_leaf_bones=False,   # 我们没有骨骼,别让它画蛇添足加空骨骼
        bake_space_transform=True,  # 把变换直接烤进顶点,减少导入端歪七扭八的坑
    )
elif fmt == "dae":
    bpy.ops.wm.collada_export(filepath=dst, selected=False)
else:
    raise ValueError(f"unsupported format: {fmt}")

print(f"map2model: exported {dst}")
