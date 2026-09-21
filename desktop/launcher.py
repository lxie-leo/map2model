"""桌面版启动器:双击 exe 后干的事都在这儿。

流程一句话:占住单实例锁 → 备好数据目录和日志 → 让后端把前端一起伺服起来
(随机空闲端口,只听本机回环)→ 等健康检查通过 → 开一个 WebView2 独立窗口。

两个自检模式都不开窗口,给打包验收用:
  --smoke       快检:服务能起、17 种导出格式都注册且可用(不联网)
  --smoke-task  深检:走真网络建真任务,15 种非 Blender 格式全真导一遍(需联网)
"""

from __future__ import annotations

import atexit
import os
import socket
import sys
import threading
import traceback
import webbrowser
from pathlib import Path

SMOKE = "--smoke" in sys.argv
# 深度自检:--smoke 只查"模块都在不在",这个走真网络建真任务、真导出,
# 把 pyproj/pyogrio/pxr 这些只有跑到才有答案的库全压一遍
SMOKE_TASK = "--smoke-task" in sys.argv
# 诊断模式:打印冻结环境的模块定位细节、试 import 出问题的包,排查打包问题用
DIAG = "--diag" in sys.argv

# 这些环境变量必须在 import app 之前就位,所以全部放在模块顶部、任何后端导入之前执行


def _repo_root() -> Path:
    """源码运行时定位仓库根(frozen 后走 _frozen_paths 那套,不走这里)。"""
    return Path(__file__).resolve().parent.parent


def _load_local_env() -> None:
    """读 exe 旁边的 map2model.env(KEY=VALUE,一行一个),给桌面用户留的配置旋钮。

    典型用途:Blender 装在非默认位置时写 M2M_BLENDER_PATH=D:\\Blender\\blender.exe,
    免得去改系统环境变量。源码运行时读 desktop/map2model.env。
    """
    if getattr(sys, "frozen", False):
        env_file = Path(sys.executable).parent / "map2model.env"
    else:
        env_file = _repo_root() / "desktop" / "map2model.env"
    if not env_file.is_file():
        return
    for line in env_file.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


def _data_dir() -> Path:
    """数据落 %LOCALAPPDATA%\\map2model(数据库、任务产物、日志都在这)。

    map2model.env 里写了 M2M_DATA_DIR 的话从那儿走(日志也跟着搬)。
    """
    if os.environ.get("M2M_DATA_DIR"):
        d = Path(os.environ["M2M_DATA_DIR"])
    else:
        base = os.environ.get("LOCALAPPDATA") or str(Path.home())
        d = Path(base) / "map2model"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _frontend_dist() -> Path:
    """找前端 dist:打包后躺在 _internal 里;源码运行就是仓库里那份。"""
    if getattr(sys, "frozen", False):
        # PyInstaller 6 的 onedir 布局:exe 旁边有个 _internal 目录
        p = Path(sys.executable).parent / "_internal" / "frontend" / "dist"
    else:
        p = _repo_root() / "frontend" / "dist"
    if not (p / "index.html").is_file():
        raise RuntimeError(f"前端产物不在 {p},先跑 pnpm build 或检查打包配置")
    return p


def _setup_stderr() -> None:
    """把 stdout/stderr 接到日志文件。

    exe 是无控制台(console=False)的,sys.stdout 会是 None;
    而后端的日志配置引用了 sys.stdout,不重定向的话启动就炸。
    """
    logs = DATA_DIR / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    log_file = logs / "desktop.log"
    # 日志太老太大会一直涨,超过 5MB 就滚一份,再超就把旧的覆盖掉
    if log_file.exists() and log_file.stat().st_size > 5 * 1024 * 1024:
        old = logs / "desktop.old.log"
        if old.exists():
            old.unlink()
        log_file.rename(old)
    f = open(log_file, "a", encoding="utf-8", buffering=1)  # noqa: SIM115 - 进程活着就不关
    sys.stdout = f
    sys.stderr = f


# ---- 模块级初始化:环境变量必须在 import app 之前就位,所以全在这执行 ----
_load_local_env()
DATA_DIR = _data_dir()
os.environ.setdefault("M2M_DATA_DIR", str(DATA_DIR))
os.environ["PYTHONUTF8"] = "1"  # 传给后面起的子进程(比如 Blender)
os.environ["PYTHONUNBUFFERED"] = "1"
# 日志先接上:后面找前端产物一旦失败,错误信息有地方落。
# 源码跑 --smoke 时留着重定向前的控制台,输出直接给人看;
# 打包产物跑 --smoke 没有控制台,照样得重定向(不然日志配置启动就炸)
if not ((SMOKE or SMOKE_TASK or DIAG) and sys.stdout is not None):
    _setup_stderr()
os.environ.setdefault("M2M_SERVE_STATIC", "1")
os.environ.setdefault("M2M_STATIC_DIR", str(_frontend_dist()))


def _msg_box(text: str, title: str = "map2model") -> None:
    """弹个系统提示框(没有控制台,报错只能靠它让人看见)。"""
    import ctypes

    ctypes.windll.user32.MessageBoxW(0, text, title, 0)


def _acquire_single_instance() -> bool:
    """Win32 互斥量保证只跑一个实例;已有实例在跑就返回 False。"""
    import ctypes

    # 句柄必须留在外面别被回收,不然锁等于没加
    global _MUTEX
    _MUTEX = ctypes.windll.kernel32.CreateMutexW(None, False, "Local\\map2model-desktop")
    return ctypes.windll.kernel32.GetLastError() != 183  # 183 = ERROR_ALREADY_EXISTS


_MUTEX = None


def _pick_free_port() -> int:
    """问系统要一个当前空闲的端口。极小概率选完被别人抢,抢了就启动失败,认了。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _start_server(port: int):
    """在线程里起 uvicorn。信号处理器只能装在主线程,这里遮掉不然直接 ValueError。"""
    import app.main
    import uvicorn

    class _ThreadedServer(uvicorn.Server):
        def install_signal_handlers(self) -> None:  # pragma: no cover - 线程侧的防御
            pass

    server = _ThreadedServer(uvicorn.Config(app.main.app, host="127.0.0.1", port=port))
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    return server, t


def _wait_healthy(port: int, timeout: float = 30.0) -> None:
    """轮询健康检查直到服务就绪;超时抛异常(信息里带日志路径,方便排查)。

    默认给 30 秒:首次运行杀软要扫完几百兆的产物目录,15 秒不够。
    """
    import time

    import httpx

    deadline = time.monotonic() + timeout
    last_err: Exception | None = None
    with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=2.0) as c:
        while time.monotonic() < deadline:
            try:
                if c.get("/api/v1/system/health").status_code == 200:
                    return
            except Exception as e:  # noqa: BLE001 - 启动窗口期连不上是正常现象
                last_err = e
            time.sleep(0.15)
    raise RuntimeError(
        f"后端 {timeout}s 内没就绪(最后错误:{last_err}),"
        f"详细日志在 {DATA_DIR / 'logs' / 'desktop.log'}"
    )


def _smoke(port: int) -> int:
    """自检模式:断言所有非 Blender 格式都可用,给 CI 当打包产物的验收。"""
    import httpx

    base = f"http://127.0.0.1:{port}"
    with httpx.Client(base_url=base, timeout=10.0) as c:
        caps = c.get("/api/v1/system/capabilities").json()
    # fbx/dae 依赖本机装没装 Blender,状态跟着机器走;其余格式必须全部可用,
    # 有一个是 false 就说明打包漏收了依赖
    blender_fmts = {"fbx", "dae"}
    broken = [
        f for f, ok in caps["formats"].items() if not ok and f not in blender_fmts
    ]
    if broken:
        print(f"SMOKE FAIL: 这些格式在打包产物里不可用: {broken}")
        return 1
    # 格式总数也得对上:导出器是运行时动态加载的,漏打包不会报错、只会悄悄少几个,
    # 上面那轮查不出来,靠总数兜底
    if len(caps["formats"]) != 17:
        print(f"SMOKE FAIL: 格式数量不对(应 17 实际 {len(caps['formats'])})")
        return 1
    blender_note = {f: caps["formats"][f] for f in sorted(blender_fmts & set(caps["formats"]))}
    print(f"SMOKE OK: {len(caps['formats'])} formats, blender-dependent: {blender_note}")
    return 0


def _smoke_task(port: int) -> int:
    """深度自检:走真网络建一个小任务,再把 15 种非 Blender 格式全真导一遍。

    --smoke 只能证明"模块找得到",pyproj 的坐标系转换、pyogrio 的 GDAL、
    pxr 的 USD 写出、trimesh 的 GLB 读写,都得真跑一遍才知道冻结后没坏。
    上海陆家嘴旁的小框,和后端测试用的是同一块地。
    """
    import time

    import httpx

    base = f"http://127.0.0.1:{port}"
    fail: list[str] = []
    with httpx.Client(base_url=base, timeout=300.0) as c:
        r = c.post("/api/v1/tasks", json={"bbox": [121.4900, 31.2340, 121.4970, 31.2385]})
        if r.status_code != 200:
            print(f"SMOKE-TASK FAIL: 建任务失败 {r.status_code} {r.text[:300]}")
            return 1
        tid = r.json()["id"]

        # 等任务到头(真网络 + 地形,正常 1-2 分钟,给足 5 分钟)
        task = {}
        deadline = time.monotonic() + 300
        while time.monotonic() < deadline:
            task = c.get(f"/api/v1/tasks/{tid}").json()
            if task["status"] in ("COMPLETED", "FAILED", "CANCELLED"):
                break
            time.sleep(1.0)
        if task.get("status") != "COMPLETED":
            print(f"SMOKE-TASK FAIL: 任务没完成({task.get('status')}): {task.get('error')}")
            return 1
        print(f"task ok: {task['stats']}")

        # 15 个非 Blender 格式全查文件头:导出报成功但内容是错的,不能等用户拿到手才发现
        # (glb/gpkg/usdz 依赖冻结风险最高,其余格式的头校验基本是白拿的保险)
        checks: dict[str, object] = {
            "glb": lambda b: b[:4] == b"glTF",
            "obj": lambda b: b[:2] == b"# " and b"mtllib" in b[:4096],
            # 二进制 STL:80 字节头后面是三角形数量,数量为 0 等于空模型
            "stl": lambda b: len(b) > 84 and int.from_bytes(b[80:84], "little") > 0,
            "usdz": _usdz_looks_right,
            "dxf": lambda b: b"SECTION" in b[:200],
            "svg": lambda b: b"<svg" in b[:4096],
            "pdf": lambda b: b[:5] == b"%PDF-",
            "png": lambda b: b[:8] == b"\x89PNG\r\n\x1a\n",
            "geojson": lambda b: b[:1] in (b"{", b"["),
            "gpkg": lambda b: b[:15] == b"SQLite format 3",
            "shp": lambda b: b[:2] == b"PK",  # 图层四件套按 zip 打包
            "kml": lambda b: b"<kml" in b[:4096],
            "kmz": lambda b: b[:2] == b"PK",
            "cityjson": lambda b: b"CityJSON" in b[:4096],
            "3dtiles": lambda b: b[:2] == b"PK",  # tileset.json 连同 tiles/ 打成 zip
        }
        # 想多验不在这儿的(比如装了 Blender 后的 fbx/dae),设 M2M_SMOKE_TASK_FORMATS=fbx,dae
        for extra in os.environ.get("M2M_SMOKE_TASK_FORMATS", "").split(","):
            if extra.strip() and extra.strip() not in checks:
                checks[extra.strip()] = lambda b: len(b) > 0
        for fmt, check in checks.items():
            r = c.post(f"/api/v1/tasks/{tid}/exports", json={"format": fmt})
            if r.status_code != 200:
                fail.append(f"{fmt}: 建导出失败 {r.text[:200]}")
                continue
            eid = r.json()["id"]
            exp = {}
            deadline = time.monotonic() + 180
            while time.monotonic() < deadline:
                exp = c.get(f"/api/v1/exports/{eid}").json()
                if exp["status"] in ("COMPLETED", "FAILED"):
                    break
                time.sleep(0.5)
            if exp.get("status") != "COMPLETED":
                fail.append(f"{fmt}: 导出失败 {str(exp.get('error'))[:200]}")
                continue
            content = c.get(f"/api/v1/exports/{eid}/download").content
            if not check(content):
                fail.append(f"{fmt}: 文件内容不对(前 32 字节 {content[:32]!r})")
            else:
                print(f"export ok: {fmt} ({len(content)} bytes)")

    if fail:
        print("SMOKE-TASK FAIL:")
        for f in fail:
            print(f"  - {f}")
        return 1
    print("SMOKE-TASK OK")
    return 0


def _usdz_looks_right(content: bytes) -> bool:
    """USDZ 是 zip 包,首条目必须是未压缩的 model.usdc(苹果 AR 的硬规矩)。"""
    import io
    import zipfile

    try:
        with zipfile.ZipFile(io.BytesIO(content)) as z:
            first = z.infolist()[0]
            return (
                first.filename.endswith(".usdc")
                and first.compress_type == zipfile.ZIP_STORED
            )
    except Exception:  # noqa: BLE001 - 打不开就当不对
        return False


def _diag() -> int:
    """诊断模式:摸清冻结环境里模块自定位的实情,专治打包疑难杂症。"""
    import ctypes
    import importlib
    import traceback

    print("frozen:", getattr(sys, "frozen", False), "MEIPASS:", getattr(sys, "_MEIPASS", None))
    print("CWD:", os.getcwd())

    for mod in ("pyogrio", "pyogrio._io", "pxr", "pxr.Tf"):
        try:
            m = importlib.import_module(mod)
            print(f"import {mod}: OK, __file__ = {getattr(m, '__file__', None)}")
        except Exception:  # noqa: BLE001 - 诊断模式要的就是把失败原样打出来
            print(f"import {mod}: FAILED")
            traceback.print_exc()

    # 直接用绝对路径加载 DLL,把"找不到"和"初始化失败"区分开
    meipass = Path(getattr(sys, "_MEIPASS", "."))
    for dll_rel in ("pyogrio.libs", "pxr"):
        d = meipass / dll_rel
        if not d.is_dir():
            print(f"{dll_rel}: 目录不存在")
            continue
        for dll in sorted(d.glob("*.dll"))[:3]:
            try:
                ctypes.WinDLL(str(dll))
                print(f"WinDLL {dll.name}: OK")
            except Exception as e:  # noqa: BLE001 - 诊断模式要的就是把失败原样打出来
                print(f"WinDLL {dll.name}: {e}")
    return 0


def main() -> int:
    if DIAG:
        return _diag()

    if not (SMOKE or SMOKE_TASK) and not _acquire_single_instance():
        _msg_box("map2model 已经在运行了。")
        return 0

    port = _pick_free_port()
    server, thread = _start_server(port)
    atexit.register(lambda: setattr(server, "should_exit", True))
    try:
        _wait_healthy(port)

        if SMOKE or SMOKE_TASK:
            code = _smoke(port) if SMOKE else _smoke_task(port)
            server.should_exit = True
            thread.join(timeout=10)
            return code

        url = f"http://127.0.0.1:{port}"
        print(f"ready at {url}", flush=True)
        try:
            import webview

            # 默认是关的:WebView2 的下载请求会被 pywebview 静默取消,
            # 表现就是点「下载」毫无反应。打开后走「另存为」对话框(默认在下载目录)
            webview.settings["ALLOW_DOWNLOADS"] = True
            webview.create_window(
                "map2model", url, width=1440, height=900, min_size=(1024, 640)
            )
            # 显式指定 WebView2,别静默退到老掉牙的 MSHTML(那玩意跑不动地图)
            webview.start(gui="edgechromium")
        except Exception:  # noqa: BLE001 - WebView2 缺失等一切窗口问题都退到浏览器
            traceback.print_exc()
            webbrowser.open(url)
            _msg_box(
                "没能打开独立窗口(多半是系统缺 WebView2 运行时),\n"
                "已在默认浏览器里打开 map2model。\n"
                "关掉本窗口即退出程序。"
            )
        return 0
    finally:
        server.should_exit = True
        # 给足收尾时间:有任务在跑时 TaskManager 要等它们停,5 秒可能不够
        thread.join(timeout=10)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:  # noqa: BLE001 - 顶层兜底,无控制台进程不能静默死
        traceback.print_exc()
        if not (SMOKE or SMOKE_TASK or DIAG):
            _msg_box(
                "map2model 启动失败,详细原因请看日志:\n"
                f"{DATA_DIR / 'logs' / 'desktop.log'}"
            )
        sys.exit(1)
