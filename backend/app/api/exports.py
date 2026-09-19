"""导出相关的接口:发起导出、查列表、下载做好的文件。"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse

from app.api.deps import get_broker, get_db, get_task_manager
from app.config import get_settings
from app.core.errors import AppError, ExportNotFound, TaskNotFound, TaskStateError
from app.core.events import EventBroker
from app.core.task_manager import TaskManager
from app.db import Database
from app.schemas import ExportCreate, ExportRead
from app.services.export import FORMATS, run_export
from app.services.export.registry import ExportContext
from app.services.mesh.scene import LAYER_ORDER

logger = logging.getLogger("app.export")

router = APIRouter(tags=["exports"])

# 导出也是重活,同时最多跑 2 个,多出来的排队等
_export_sem: asyncio.Semaphore | None = None
# 在跑的导出任务攥在手里:不攥着的话,极端情况下垃圾回收会把没人认领的任务收走。
# 按任务 id 分抽屉放,删任务时好把它的导出一个个找出来停掉
_export_tasks: dict[str, set[asyncio.Task]] = {}


def _track_export(task_id: str, t: asyncio.Task) -> None:
    _export_tasks.setdefault(task_id, set()).add(t)
    t.add_done_callback(lambda _t: _untrack_export(task_id, _t))


def _untrack_export(task_id: str, t: asyncio.Task) -> None:
    drawer = _export_tasks.get(task_id)
    if drawer is not None:
        drawer.discard(t)
        if not drawer:
            _export_tasks.pop(task_id, None)


async def stop_exports_for_task(task_id: str) -> None:
    """删任务前调用:把这个任务还在跑的导出停掉,最多等 10 秒让线程里的活收尾。

    不停就删的话,导出线程还会往刚删掉的目录里重建文件,留下没人认领的孤儿目录。"""
    running = list(_export_tasks.get(task_id, ()))
    for t in running:
        t.cancel()
    if running:
        await asyncio.wait(running, timeout=10)


def _sem() -> asyncio.Semaphore:
    global _export_sem
    if _export_sem is None:
        _export_sem = asyncio.Semaphore(2)
    return _export_sem


async def recover_stuck_exports(db: Database) -> None:
    """服务重启时调用:上回没跑完的导出肯定续不上了,统一标成失败,
    免得它们永远停在"排队中/进行中"。"""
    stuck = await db.fetch_all(
        "SELECT id, task_id, format FROM exports WHERE status IN ('QUEUED','RUNNING')"
    )
    for row in stuck:
        await db.update_export(
            row["id"], status="FAILED", error="interrupted by server restart"
        )
        logger.info("export %s (%s) marked failed: interrupted by restart",
                    row["id"], row["format"])


@router.post("/tasks/{task_id}/exports", response_model=ExportRead)
async def create_export(
    task_id: str,
    body: ExportCreate,
    tm: TaskManager = Depends(get_task_manager),
    db: Database = Depends(get_db),
    broker: EventBroker = Depends(get_broker),
) -> dict:
    """发起一次导出。只有跑完(COMPLETED)的任务能导,没跑完的不接。"""
    task = await tm.get(task_id)
    if task is None:
        raise TaskNotFound(task_id)
    if task["status"] != "COMPLETED":
        raise TaskStateError(f"task status is {task['status']}, exports need COMPLETED")
    fmt = body.format
    if fmt not in FORMATS():
        raise AppError(f"unknown format: {fmt}")
    # 图层名单只能是认识的图层,前端要是传了怪名字直接打回,
    # 不然拼错一个字就会"看起来全被过滤光"还不报错
    layers: frozenset[str] | None = None
    if body.layers is not None:
        unknown = set(body.layers) - set(LAYER_ORDER)
        if unknown:
            raise AppError(f"unknown layers: {sorted(unknown)}")
        # 全勾了就当"不过滤"——导出器能走整包快路径(比如 GLB 直接复制)
        layers = frozenset(body.layers) if set(body.layers) != set(LAYER_ORDER) else None

    now = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + "Z"
    export_id = uuid.uuid4().hex[:10]
    exp = {
        "id": export_id,
        "task_id": task_id,
        "format": fmt,
        "status": "QUEUED",
        "progress": 0.0,
        "filename": None,
        "error": None,
        "created_at": now,
        "updated_at": now,
    }
    await db.insert_export(exp)
    t = asyncio.get_running_loop().create_task(_run_export(exp, task, broker, layers))
    _track_export(task_id, t)
    return exp


async def _run_export(exp: dict, task: dict, broker: EventBroker,
                      layers: frozenset[str] | None = None) -> None:
    """在后台跑导出:一边跑一边把状态写进数据库、把进度广播给前端。"""
    db = _get_app_db()
    fmt = exp["format"]
    settings = get_settings()
    task_dir = settings.tasks_dir / exp["task_id"]
    export_dir = task_dir / "exports" / exp["id"]
    export_dir.mkdir(parents=True, exist_ok=True)

    async def emit(event: str, progress: float | None = None,
                   message: str | None = None, **extra) -> None:
        fields = dict(extra)
        if progress is not None:
            fields["progress"] = progress
        await db.update_export(exp["id"], **fields)
        broker.publish({
            "type": "export_progress" if event == "progress" else f"export_{event}",
            "task_id": exp["task_id"],
            "export_id": exp["id"],
            "format": fmt,
            "progress": progress,
            "message": message,
        })

    try:
        async with _sem():
            await db.update_export(exp["id"], status="RUNNING")
            await emit("progress", 0.0, "export started")
            # 导出重活是在旁边线程里跑的,进度回调也从线程里来;
            # 广播站的家伙事只能在主线程碰,得先把消息扔回主线程再发
            loop = asyncio.get_running_loop()

            def on_progress(frac: float, msg: str | None = None) -> None:
                loop.call_soon_threadsafe(broker.publish, {
                    "type": "export_progress",
                    "task_id": exp["task_id"],
                    "export_id": exp["id"],
                    "format": fmt,
                    "progress": round(frac, 3),
                    "message": msg,
                })
                # 进度也落一份到库里:不走事件流、只轮询列表的客户端才看得到
                asyncio.run_coroutine_threadsafe(
                    db.update_export(exp["id"], progress=round(frac, 3)), loop)

            from app.utils.caching import read_json

            meta = read_json(task_dir / "meta.json")
            ctx = ExportContext(
                task_id=exp["task_id"], task_dir=task_dir, export_dir=export_dir,
                meta=meta, settings=settings, on_progress=on_progress,
                layers=layers,
            )
            filename = await run_export(fmt, ctx)
            await emit("done", 1.0, filename, status="COMPLETED", filename=filename)
    except asyncio.CancelledError:
        # 任务被删时导出会跟着被停。库里的行马上也要删了,但万一没删
        # (以后别的场景也用它),给它留个明确的结局别停在"进行中"
        try:
            await db.update_export(exp["id"], status="FAILED", error="cancelled")
        except Exception:  # noqa: BLE001 - 收尾动作,失败就算了
            pass
        raise
    except Exception as exc:  # noqa: BLE001 - 什么错都得接住,落库再广播出去
        logger.exception("export %s failed", exp["id"])
        await emit("error", None, str(exc), status="FAILED", error=str(exc))


def _get_app_db() -> Database:
    """后台任务不在请求里,享受不到依赖注入,只能从全局 app 上把 db 拿过来。"""
    from app.main import app

    return app.state.db


@router.get("/tasks/{task_id}/exports", response_model=list[ExportRead])
async def list_exports(task_id: str,
                       tm: TaskManager = Depends(get_task_manager),
                       db: Database = Depends(get_db)) -> list[dict]:
    if await tm.get(task_id) is None:
        raise TaskNotFound(task_id)
    return await db.list_exports(task_id)


@router.get("/exports/{export_id}", response_model=ExportRead)
async def get_export(export_id: str, db: Database = Depends(get_db)) -> dict:
    exp = await db.get_export(export_id)
    if exp is None:
        raise ExportNotFound(export_id)
    return exp


@router.get("/exports/{export_id}/download")
async def download_export(export_id: str, db: Database = Depends(get_db)) -> FileResponse:
    exp = await db.get_export(export_id)
    if exp is None:
        raise ExportNotFound(export_id)
    if exp["status"] != "COMPLETED" or not exp["filename"]:
        raise AppError(f"export not ready (status={exp['status']})")
    path = (get_settings().tasks_dir / exp["task_id"] / "exports" / export_id
            / exp["filename"])
    if not path.is_file():
        raise ExportNotFound(f"file {exp['filename']}")
    return FileResponse(path, filename=exp["filename"])
