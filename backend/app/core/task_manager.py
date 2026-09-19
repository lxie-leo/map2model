"""任务的大管家:接活、排队、限制同时跑几个、汇报进度、支持中途取消。

一个任务的一生:QUEUED(排队)→ RUNNING(跑着,分五个阶段)→ COMPLETED / FAILED / CANCELLED。
五个阶段在总进度(0-100)里各占一段:
  抓 OSM 数据 0-35 / 抓地形 35-50 / 解析矢量 50-65 / 建网格 65-90 / 写枢纽文件 90-100
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import traceback
import uuid
from dataclasses import dataclass, field
from typing import Any

from app.config import Settings
from app.core.errors import BadRequest, TaskStateError
from app.core.events import EventBroker, to_broadcast
from app.db import Database
from app.services import pipeline

logger = logging.getLogger("app.task_manager")

STAGE_WEIGHTS: dict[str, tuple[float, float]] = {
    "FETCH_OVERPASS": (0.0, 35.0),
    "FETCH_TERRAIN": (35.0, 50.0),
    "PARSE_VECTOR": (50.0, 65.0),
    "BUILD_MESH": (65.0, 90.0),
    "WRITE_HUB": (90.0, 100.0),
}

_PROGRESS_THROTTLE = 0.1  # 两条进度至少隔 0.1 秒才发,太密了前端也刷不过来


@dataclass
class _Runtime:
    """任务在内存里的临时状态(要长期保存的那些存数据库里,两边分工)。"""

    cancel_event: asyncio.Event = field(default_factory=asyncio.Event)
    aio_task: asyncio.Task | None = None
    started: bool = False
    warnings: list[str] = field(default_factory=list)
    last_progress_ts: float = 0.0
    last_stage: str | None = None
    loop: asyncio.AbstractEventLoop | None = None  # 主事件循环,干重活的线程靠它把消息扔回主线程


def new_task_id() -> str:
    return uuid.uuid4().hex[:12]


class TaskManager:
    def __init__(self, settings: Settings, db: Database, broker: EventBroker) -> None:
        self.settings = settings
        self.db = db
        self.broker = broker
        self._sem = asyncio.Semaphore(settings.task_concurrency)
        self._runtime: dict[str, _Runtime] = {}
        self._tasks: set[asyncio.Task] = set()

    # --- 生命周期 ---------------------------------------------------------
    async def start(self) -> None:
        """服务重启后,上个进程没跑完的任务肯定续不上了,统一标成 FAILED,免得永远卡在 RUNNING。"""
        stuck = await self.db.fetch_all(
            "SELECT id FROM tasks WHERE status IN ('QUEUED','RUNNING')"
        )
        for row in stuck:
            await self.db.update_task(
                row["id"], status="FAILED", error="interrupted by server restart"
            )
            await self._emit(row["id"], "error", message="interrupted by server restart")

    async def shutdown(self) -> None:
        """退出前给每个任务发取消信号,等它们都收完尾再走。"""
        for rt in self._runtime.values():
            rt.cancel_event.set()
        for t in self._tasks:
            if not t.done():
                t.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()

    # --- 创建 / 查询 ------------------------------------------------------
    async def create(self, bbox: tuple[float, float, float, float], options: dict) -> dict:
        """新建任务:先看面积超没超上限,再入库、排上队。"""
        from app.utils.geom import bbox_area_km2

        area = bbox_area_km2(bbox)
        if area > self.settings.max_bbox_area_km2:
            raise BadRequest(
                f"bbox area {area:.2f} km² exceeds limit {self.settings.max_bbox_area_km2} km²"
            )
        now = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + "Z"
        task_id = new_task_id()
        task = {
            "id": task_id,
            "status": "QUEUED",
            "stage": None,
            "progress": 0.0,
            "bbox": list(bbox),
            "area_km2": area,
            "options": options,
            "warnings": [],
            "error": None,
            "stats": None,
            "created_at": now,
            "updated_at": now,
        }
        await self.db.insert_task(task)
        task_dir = self.settings.tasks_dir / task_id
        task_dir.mkdir(parents=True, exist_ok=True)

        rt = _Runtime()
        rt.loop = asyncio.get_running_loop()
        self._runtime[task_id] = rt
        rt.aio_task = asyncio.create_task(self._run_wrapper(task_id, rt))
        self._tasks.add(rt.aio_task)
        rt.aio_task.add_done_callback(self._tasks.discard)
        await self._emit(task_id, "queued", message=f"task {task_id} queued ({area:.2f} km²)")
        return task

    async def get(self, task_id: str) -> dict | None:
        return await self.db.get_task(task_id)

    async def list(self, limit: int = 100) -> list[dict]:
        return await self.db.list_tasks(limit)

    async def cancel(self, task_id: str) -> dict:
        """取消任务:还没开跑的直接改状态完事;已经在跑的设个取消标志,让管线自己找机会停下。"""
        task = await self.db.get_task(task_id)
        if task is None:
            from app.core.errors import TaskNotFound

            raise TaskNotFound(task_id)
        status = task["status"]
        if status in ("COMPLETED", "FAILED", "CANCELLED"):
            raise TaskStateError(f"task already {status}")
        rt = self._runtime.get(task_id)
        if status == "QUEUED" and (rt is None or not rt.started):
            if rt is not None:
                rt.cancel_event.set()  # 双保险:万一它刚好抢到名额正要开跑,开跑后还会再查一次
            # 只有真的把状态从 QUEUED 改成 CANCELLED 的人才发事件:
            # 任务协程那边拿到信号量后也会做同样的条件改写,两边谁先谁后,
            # 事件都只发一条
            if await self._finish_if(task_id, "QUEUED", "CANCELLED"):
                await self._emit(task_id, "cancelled", message="cancelled before start")
        else:
            assert rt is not None
            rt.cancel_event.set()
            # 光设标志的话,任务要等到下一个检查点才停——要是它正卡在等
            # Overpass 响应的几十秒里,取消就"没反应"。直接打断它当前
            # 正在等的活,然后最多等 5 秒让它把状态写完
            if rt.aio_task is not None and not rt.aio_task.done():
                rt.aio_task.cancel()
                try:
                    await asyncio.wait_for(asyncio.shield(rt.aio_task), timeout=5)
                except (asyncio.CancelledError, TimeoutError, Exception):
                    pass  # 收尾超时也没事,它会在后台把状态写完
        return await self.db.get_task(task_id) or task

    async def stop(self, task_id: str) -> None:
        """让任务真正停下来并等它收完尾。删任务前必须走这一步,
        不然边跑边删,文件和目录会被重新写出来。"""
        rt = self._runtime.get(task_id)
        if rt is None:
            return
        rt.cancel_event.set()
        if rt.aio_task is not None and not rt.aio_task.done():
            rt.aio_task.cancel()
            try:
                await rt.aio_task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001 - 等收尾,结果不管
                pass

    # --- 工作协程 ------------------------------------------------------------
    async def _run_wrapper(self, task_id: str, rt: _Runtime) -> None:
        """任务主体。先拿到信号量(限制同时跑几个)才真正开跑。"""
        try:
            async with self._sem:
                task = await self.db.get_task(task_id)
                if task is None:
                    return
                # 拿到名额后再核一遍:排队期间被取消的就别开跑了。谁先把库
                # 从 QUEUED 改成 CANCELLED 谁负责发那条取消事件,这样
                # 取消接口和这边同时发现,事件也只发一条
                if task["status"] == "CANCELLED" or rt.cancel_event.is_set():
                    if task["status"] != "CANCELLED":
                        if await self._finish_if(task_id, "QUEUED", "CANCELLED"):
                            await self._emit(task_id, "cancelled", message="cancelled before start")
                    return
                rt.started = True
                # try 要从这儿的第一个 await 就开始罩着:不然硬取消正好打在
                # "改 RUNNING / 发开始事件"这两个 await 中间的话,异常没人接,
                # 任务就永远停在 RUNNING 了
                try:
                    await self.db.update_task(task_id, status="RUNNING")
                    await self._emit(task_id, "stage", stage="FETCH_OVERPASS", progress=0.0,
                                     message="task started")
                    task_dir = self.settings.tasks_dir / task_id
                    ctx = pipeline.PipelineContext(
                        task_id=task_id,
                        task_dir=task_dir,
                        bbox=tuple(task["bbox"]),
                        options=task["options"],
                        cancel_event=rt.cancel_event,
                        progress=lambda stage, frac, msg=None: self._progress(rt, task_id, stage, frac, msg),
                        warn=lambda msg: self._warn(rt, task_id, msg),
                        settings=self.settings,
                    )
                    stats = await pipeline.run_pipeline(ctx)
                    await self.db.update_task(task_id, stats=json.dumps(stats, ensure_ascii=False))
                    await self._finish(task_id, "COMPLETED")
                    await self._emit(task_id, "done", progress=100.0, message="task completed")
                except asyncio.CancelledError:
                    # 被硬取消(用户点取消/服务退出)。取消之后再 await 会立刻
                    # 再抛取消异常,收尾写库的活得包进 shield 里护着才能做完
                    try:
                        await asyncio.shield(self._cancel_finish(task_id))
                    except (asyncio.CancelledError, Exception):
                        pass  # shield 里的活会继续跑完,这里被打断也不影响
                    raise
                except Exception as exc:  # noqa: BLE001 - 任务最外层,什么异常都得接住
                    if rt.cancel_event.is_set():
                        # 用户按了取消,管线是"顺着取消的意思想办法停"时抛的错
                        # (比如抓数据时发现取消标志就抛"cancelled"),这算取消成功,不算失败
                        logger.info("task %s cancelled (via %s)", task_id, type(exc).__name__)
                        await self._finish(task_id, "CANCELLED")
                        await self._emit(task_id, "cancelled", message="task cancelled")
                    else:
                        logger.error("task %s failed: %s\n%s", task_id, exc, traceback.format_exc())
                        await self._finish(task_id, "FAILED", error=str(exc))
                        await self._emit(task_id, "error", message=str(exc))
        finally:
            self._runtime.pop(task_id, None)

    async def _cancel_finish(self, task_id: str) -> None:
        """硬取消后的收尾:落库 + 广播(包在 shield 里调用)。"""
        await self._finish(task_id, "CANCELLED")
        await self._emit(task_id, "cancelled", message="task cancelled")

    async def _finish(self, task_id: str, status: str, error: str | None = None) -> None:
        fields: dict[str, Any] = {
            "status": status,
            "stage": None,
            "progress": 100.0 if status == "COMPLETED" else None,
        }
        fields = {k: v for k, v in fields.items() if v is not None or k == "stage"}
        if error is not None:
            fields["error"] = error
        if status in ("COMPLETED", "FAILED", "CANCELLED"):
            fields["completed_at"] = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + "Z"
        await self.db.update_task(task_id, **fields)

    async def _finish_if(self, task_id: str, expect: str, status: str) -> bool:
        """带条件地写终态:只有当前状态还是 expect 时才改写成 status。

        返回是否真的改了。两个地方同时想写终态(比如取消接口和任务协程
        都发现该取消)时,靠数据库的条件更新保证只有一方成功,事件也就只发一条。
        """
        fields: dict[str, Any] = {"status": status, "stage": None}
        if status in ("COMPLETED", "FAILED", "CANCELLED"):
            fields["completed_at"] = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + "Z"
        return await self.db.update_task_if(task_id, expect, **fields)

    # --- 进度与事件 ---------------------------------------------------
    def _progress(
        self, rt: _Runtime, task_id: str, stage: str, frac: float, message: str | None
    ) -> None:
        """进度回调。可能是从干重活的线程里调过来的,得先安全地扔回主事件循环再处理。"""
        if rt.loop is None or rt.loop.is_closed():
            return
        try:
            rt.loop.call_soon_threadsafe(
                self._progress_on_loop, rt, task_id, stage, frac, message
            )
        except RuntimeError:
            pass  # 循环已关闭,任务正在收尾

    def _progress_on_loop(
        self, rt: _Runtime, task_id: str, stage: str, frac: float, message: str | None
    ) -> None:
        lo, hi = STAGE_WEIGHTS[stage]
        global_frac = min(1.0, max(0.0, frac))
        progress = lo + (hi - lo) * global_frac
        now = time.monotonic()
        stage_change = stage != rt.last_stage
        if not stage_change and (now - rt.last_progress_ts) < _PROGRESS_THROTTLE:
            return
        rt.last_progress_ts = now
        rt.last_stage = stage
        # 发出去就不管了,不等着写库和广播做完——重活代码不会卡在这一步
        asyncio.get_running_loop().create_task(
            self._progress_write(task_id, stage, round(progress, 2), message, stage_change)
        )

    async def _progress_write(
        self, task_id: str, stage: str, progress: float, message: str | None, stage_change: bool
    ) -> None:
        # 只在任务还在跑时才写:刚完结的瞬间可能还有一条迟到的新进度,
        # 不拦着它就会把"已完成"改回"运行中"
        if not await self.db.update_task_if(
            task_id, "RUNNING", stage=stage, progress=progress
        ):
            return
        await self._emit(
            task_id,
            "stage" if stage_change else "progress",
            stage=stage,
            progress=progress,
            message=message,
        )

    def _warn(self, rt: _Runtime, task_id: str, message: str) -> None:
        """警告回调:也可能是从工作线程调过来的,一样先扔回主循环。"""
        if rt.loop is None or rt.loop.is_closed():
            return
        try:
            rt.loop.call_soon_threadsafe(self._warn_on_loop, rt, task_id, message)
        except RuntimeError:
            pass

    def _warn_on_loop(self, rt: _Runtime, task_id: str, message: str) -> None:
        rt.warnings.append(message)
        asyncio.get_running_loop().create_task(
            self._warn_write(task_id, message, list(rt.warnings))
        )

    async def _warn_write(self, task_id: str, message: str, warnings: list[str]) -> None:
        await self.db.update_task(task_id, warnings=json.dumps(warnings, ensure_ascii=False))
        await self._emit(task_id, "warning", message=message)
        logger.warning("task %s: %s", task_id, message)

    async def _emit(
        self,
        task_id: str,
        type_: str,
        stage: str | None = None,
        progress: float | None = None,
        message: str | None = None,
    ) -> None:
        event_id = await self.db.insert_event(
            task_id, type_, stage=stage, progress=progress, message=message
        )
        self.broker.publish(
            to_broadcast({
                "id": event_id,
                "task_id": task_id,
                "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + "Z",
                "type": type_,
                "stage": stage,
                "progress": progress,
                "message": message,
            })
        )
