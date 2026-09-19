"""任务相关的接口:建任务、查任务、取消、删除;进度走 SSE 流;产物文件也从这里下载。"""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse, StreamingResponse

from app.api.deps import get_broker, get_db, get_task_manager
from app.core.errors import AppError, TaskNotFound
from app.core.events import EventBroker, to_broadcast
from app.core.task_manager import TaskManager
from app.db import Database
from app.schemas import TaskCreate, TaskRead

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.post("", response_model=TaskRead)
async def create_task(
    body: TaskCreate,
    tm: TaskManager = Depends(get_task_manager),
) -> dict:
    return await tm.create(tuple(body.bbox), body.options.model_dump())


@router.get("", response_model=list[TaskRead])
async def list_tasks(
    limit: int = 100,
    tm: TaskManager = Depends(get_task_manager),
) -> list[dict]:
    return await tm.list(limit)


@router.get("/{task_id}", response_model=TaskRead)
async def get_task(task_id: str, tm: TaskManager = Depends(get_task_manager)) -> dict:
    task = await tm.get(task_id)
    if task is None:
        raise TaskNotFound(task_id)
    return task


@router.delete("/{task_id}")
async def delete_task(
    task_id: str,
    tm: TaskManager = Depends(get_task_manager),
    db: Database = Depends(get_db),
) -> dict:
    """删任务:还在跑的先取消并等它真正停下来,再把数据库里的记录挨个清掉,
    最后顺手删掉任务文件夹。不等它停就删,任务还会往目录里写文件,等于白删。"""
    task = await tm.get(task_id)
    if task is None:
        raise TaskNotFound(task_id)
    if task["status"] in ("QUEUED", "RUNNING"):
        await tm.stop(task_id)
    # 这个任务还有导出在后台跑的话也得停:不停就删,导出线程会把刚删掉的
    # 目录又建出来,留下没人认领的孤儿文件夹
    from app.api.exports import stop_exports_for_task

    await stop_exports_for_task(task_id)
    await db.execute("DELETE FROM task_events WHERE task_id = ?", (task_id,))
    await db.execute("DELETE FROM exports WHERE task_id = ?", (task_id,))
    await db.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
    # 顺手清掉任务目录
    from app.config import get_settings

    task_dir = get_settings().tasks_dir / task_id
    if task_dir.exists():
        import shutil

        shutil.rmtree(task_dir, ignore_errors=True)
    return {"deleted": task_id}


@router.post("/{task_id}/cancel", response_model=TaskRead)
async def cancel_task(task_id: str, tm: TaskManager = Depends(get_task_manager)) -> dict:
    return await tm.cancel(task_id)


@router.get("/{task_id}/events")
async def task_events(
    task_id: str,
    after_event_id: int = 0,
    watch: str | None = None,
    tm: TaskManager = Depends(get_task_manager),
    db: Database = Depends(get_db),
    broker: EventBroker = Depends(get_broker),
):
    """SSE 进度流:先把断线期间漏掉的历史事件补发一遍,再接着推实时消息;
    重连时带上 after_event_id,就知道从哪儿开始补。
    watch=exports 表示"任务结束后还要接着听导出进度"(导出事件走同一条频道,
    但只有带了这个参数,流才会等导出全跑完才收)。"""
    task = await tm.get(task_id)
    if task is None:
        raise TaskNotFound(task_id)
    watch_exports = watch == "exports"

    async def no_active_exports() -> bool:
        rows = await db.fetch_all(
            "SELECT 1 FROM exports WHERE task_id = ? AND status IN ('QUEUED','RUNNING') LIMIT 1",
            (task_id,),
        )
        return not rows

    async def gen():
        queue = await broker.subscribe(task_id)
        try:
            # 先补发断线期间的历史事件(转成和 WebSocket 一样的广播格式),
            # 补发里如果已经能看到任务的终局,发条收尾消息就完事
            for row in await db.events_after(task_id, after_event_id):
                ev = to_broadcast(row)
                yield f"id: {ev['id']}\ndata: {json.dumps(ev, ensure_ascii=False)}\n\n"
                if ev["event"] in ("done", "error", "cancelled") and (
                    not watch_exports or await no_active_exports()
                ):
                    yield "event: end\ndata: {}\n\n"
                    return
            fresh = await tm.get(task_id)
            if fresh is None or fresh["status"] in ("COMPLETED", "FAILED", "CANCELLED"):
                # 补发里没看到终局,但任务其实已经完了(比如补到的事件之后任务
                # 恰好收尾):再核一次库,别让这条流空转下去。
                # watch=exports 的流要等到"确实没有导出在跑"才收摊——
                # 还有导出在跑就接着等,一个都没有就别干耗着了
                if not watch_exports or await no_active_exports():
                    yield "event: end\ndata: {}\n\n"
                    return
            while True:
                try:
                    ev = await asyncio.wait_for(queue.get(), timeout=15)
                except TimeoutError:
                    yield ": keepalive\n\n"  # 15 秒没消息就发条空行,告诉对面这条连接还活着
                    continue
                # 导出事件没带自增编号(只有任务事件有)。id 行只在真有编号时
                # 才发:按浏览器规矩,发一条空的 id 行会把对面的"断点编号"
                # 清成空,重连时就会从零重放一大堆旧进度
                if ev.get("id") is not None:
                    yield f"id: {ev['id']}\n"
                yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
                et = ev.get("type")
                if et in ("export_done", "export_error") and await no_active_exports():
                    # 盯导出的流:最后一个导出也完结了,这条流功成身退
                    yield "event: end\ndata: {}\n\n"
                    return
                if ev.get("event") in ("done", "error", "cancelled") and (
                    not watch_exports or await no_active_exports()
                ):
                    yield "event: end\ndata: {}\n\n"
                    return
        finally:
            await broker.unsubscribe(queue, task_id)

    return StreamingResponse(gen(), media_type="text/event-stream")


@router.get("/{task_id}/files/{filename}")
async def task_file(task_id: str, filename: str, tm: TaskManager = Depends(get_task_manager)):
    """下载任务产物(hub.glb / preview.geojson / meta.json)。文件名先检查一遍,防止用 ../ 之类的写法摸到目录外面。"""
    import re

    if not re.fullmatch(r"[\w.\-]+", filename):
        raise AppError("bad filename")
    task = await tm.get(task_id)
    if task is None:
        raise TaskNotFound(task_id)
    from app.config import get_settings

    path = get_settings().tasks_dir / task_id / filename
    if not path.is_file():
        raise TaskNotFound(f"file {filename}")
    return FileResponse(path, filename=filename)


@router.get("/{task_id}/preview/geojson")
async def preview_geojson(task_id: str, tm: TaskManager = Depends(get_task_manager)):
    """2D 地图预览用的 GeoJSON,任务跑完才有。"""
    task = await tm.get(task_id)
    if task is None:
        raise TaskNotFound(task_id)
    from app.config import get_settings

    path = get_settings().tasks_dir / task_id / "preview.geojson"
    if not path.is_file():
        raise TaskNotFound("preview (task not finished?)")
    return FileResponse(path, media_type="application/geo+json")
