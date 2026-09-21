# -*- mode: python ; coding: utf-8 -*-
# PyInstaller 打包配置:把后端 + 前端 dist + pywebview 壳冻成 onedir 产物。
# 构建:desktop/build-desktop.ps1(不要直接手跑 pyinstaller,环境它负责备)。

import os
from PyInstaller.utils.hooks import (
    collect_all,
    collect_data_files,
    collect_dynamic_libs,
    collect_submodules,
)

HERE = os.path.abspath(".")

# ---- 动态导入的模块,静态分析看不见,必须点名 ----
hidden = (
    # 导出器注册表是运行时 importlib 动态加载的,漏一个就是 unknown export format
    collect_submodules("app")
    # trimesh 的读写器全是懒加载,漏了表现为到点才 ImportError
    + collect_submodules("trimesh")
    # uvicorn 的 loop/protocol 也是按名字动态挑的
    + collect_submodules("uvicorn")
    + collect_submodules("webview")
    # pyogrio 的 C 扩展(_geometry/_io/_ogr...)互相按模块名引用,
    # 依赖分析只盯见了 _io 一个,漏了 _geometry 就报"GDAL DLL not on PATH"(误导)
    + [m for m in collect_submodules("pyogrio") if not m.startswith("pyogrio.tests")]
    + [
        # 后端本体:launcher 只在函数里动态 import,pathex 指到 backend/,
        # 这里必须点名根包(collect_submodules 走 editable 安装找不到它,会空手而归)
        "app",
        "app.main",
        # pywebview 官方给的 PyInstaller 配方:窗口后端和 .NET 桥都是动态加载
        "webview.platforms.edgechromium",
        "webview.platforms.winforms",
        "clr_loader",
        "pythonnet",
        # 三角化引擎在 geom.py 里 try/except 导入,漏了会静默降级成纯 Python(慢)
        "mapbox_earcut",
    ]
)

datas = [
    # 前端产物整目录带上,launcher 会去 _internal/frontend/dist 找
    ("../frontend/dist", "frontend/dist"),
    # Blender 导出脚本:blender.py 用 Path(__file__) 找它,而 __file__ 指向
    # 的是磁盘路径;模块本身进了 PYZ 压缩包,没有对应的真实文件,必须按原位放一份
    ("../backend/app/services/export/blender_script.py", "app/services/export"),
]
datas += collect_data_files("trimesh")
datas += collect_data_files("webview")
# pyogrio 自带的 GDAL/PROJ 数据文件(gdal_data/、proj_data/),缺了 GPKG 写坐标参照会炸
datas += collect_data_files("pyogrio")

binaries = []
# pyogrio 的 GDAL 全家桶 DLL(hooks-contrib 有钩子,这里再兜一层底,重复了会自动去重)
binaries += collect_dynamic_libs("pyogrio")

# usd-core(pxr)没有现成钩子,插件注册靠 plugInfo.json,数据/子模块/DLL 全收
_pxr_datas, _pxr_bins, _pxr_hidden = collect_all("pxr")
datas += _pxr_datas
binaries += _pxr_bins
hidden += _pxr_hidden

a = Analysis(
    ["launcher.py"],
    # SPECPATH 是 PyInstaller 注入的 spec 所在目录(desktop/),跟从哪个目录启动无关;
    # 别用 os.path.abspath("."),那个是 CWD,拼 ".." 会指到仓库外面去
    pathex=[os.path.abspath(os.path.join(SPECPATH, "..", "backend"))],
    binaries=binaries,
    datas=datas,
    hiddenimports=hidden,
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        "tkinter",  # 用不上还占体积
        "pip",
        "setuptools",
        "PyInstaller",
    ],
    noarchive=False,
)

# uv 的 Python 发行版(python-build-standalone)自带的 msvcp140.dll 是 2020 年的 14.26,
# pxr 的 usd_ms.dll 按新工具链编译,进程里先加载到这份老库,DllMain 就会失败
# (报"初始化例程失败",已定位并复现验证)。这里把混进来的老库剔除,
# 换成构建机系统里的当前版本——venv 里能正常 import pxr 靠的就是系统这份。
a.binaries = [
    b for b in a.binaries if os.path.basename(b[0]).lower() != "msvcp140.dll"
]
_sys_msvc = os.path.join(
    os.environ.get("SystemRoot", r"C:\Windows"), "System32", "msvcp140.dll"
)
a.binaries.append(("msvcp140.dll", _sys_msvc, "BINARY"))

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="map2model",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,  # UPX 压缩是杀软误报重灾区,不开
    console=False,  # 无控制台窗口;日志全走 %LOCALAPPDATA%/map2model/logs
    icon="icon.ico" if os.path.exists(os.path.join(HERE, "icon.ico")) else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="map2model",
)
