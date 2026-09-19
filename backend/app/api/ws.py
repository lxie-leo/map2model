"""WebSocket 接口:任务进度、导出进度都从这儿实时往外推。

推的消息有这么几种:
- task_progress / task_stage:任务进度和阶段切换
- task_done / task_error / task_cancelled / task_warning:任务跑完/出错/被取消/有警告
- export_progress / export_done / export_error:导出的进度和结果
前端可以发 {"action": "subscribe", "task_id": "..."} 只听某一个任务,
什么都不发就全都收。
"""

from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect

from app.api.deps import get_broker_ws
from app.core.events import EventBroker

logger = logging.getLogger("app.ws")

router = APIRouter()


@router.websocket("/ws")
async def websocket_endpoint(
    ws: WebSocket, broker: EventBroker = Depends(get_broker_ws)
) -> None:
    await ws.accept()
    task_filter: str | None = None
    queue = await broker.subscribe(None)  # 默认收全部
    loop = asyncio.get_running_loop()
    recv_task: asyncio.Task | None = None
    send_task: asyncio.Task | None = None
    try:
        await ws.send_text(json.dumps({"type": "hello", "version": "1"}))
        recv_task = loop.create_task(ws.receive_text())
        send_task = loop.create_task(queue.get())

        while True:
            # 同时盯着两件事:队列里有消息要发、客户端发消息过来,哪件先来处理哪件
            done, _ = await asyncio.wait(
                {recv_task, send_task}, return_when=asyncio.FIRST_COMPLETED
            )
            if send_task in done:
                ev = send_task.result()
                if task_filter is None or ev.get("task_id") == task_filter:
                    await ws.send_text(json.dumps(ev, ensure_ascii=False))
                send_task = loop.create_task(queue.get())
            if recv_task in done:
                try:
                    msg = json.loads(recv_task.result())
                except (json.JSONDecodeError, WebSocketDisconnect):
                    break
                if msg.get("action") == "subscribe":
                    task_filter = msg.get("task_id")
                    await ws.send_text(json.dumps({
                        "type": "subscribed", "task_id": task_filter,
                    }))
                elif msg.get("action") == "ping":
                    # 前端定时问一句"还在吗",回个 pong 让它放心
                    await ws.send_text(json.dumps({"type": "pong"}))
                recv_task = loop.create_task(ws.receive_text())
    except (WebSocketDisconnect, RuntimeError):
        pass  # 客户端断开是常事,不算错误,安静收尾就行
    finally:
        for t in (recv_task, send_task):
            if t is not None:
                t.cancel()
        await broker.unsubscribe(queue, None)
