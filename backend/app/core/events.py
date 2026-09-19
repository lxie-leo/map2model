"""进程内的小广播站。

任务管理器每往 SQLite 存一条进度事件,顺便往这里也发一份;
WebSocket 和 SSE 接口从这儿订阅,再转给前端页面。
每个订阅者一条队列,队列满了就扔掉最旧的消息——宁可丢几条进度,
也不能让收得慢的客户端把任务本身拖死。
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Any

_MAX_QUEUE = 512


def to_broadcast(row: dict) -> dict:
    """把数据库里存的事件行转成要广播出去的格式。

    库里存的是短名(progress/done/...),广播时给它们统一戴上 task_ 前缀,
    和前端约定一致;断线重连后补发历史事件也走这个函数,
    保证两条通道(Websocket 实时、SSE 补发)发出来的是一个长相。
    """
    t = row["type"]
    return {
        "type": "task_progress" if t in ("progress", "stage") else f"task_{t}",
        "id": row["id"],
        "task_id": row["task_id"],
        "ts": row["ts"],
        "event": t,
        "stage": row.get("stage"),
        "progress": row.get("progress"),
        "message": row.get("message"),
    }


class EventBroker:
    def __init__(self) -> None:
        self._subs: dict[str | None, set[asyncio.Queue]] = defaultdict(set)
        self._lock = asyncio.Lock()

    async def subscribe(self, task_id: str | None = None) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=_MAX_QUEUE)
        async with self._lock:
            self._subs[task_id].add(q)
        return q

    async def unsubscribe(self, q: asyncio.Queue, task_id: str | None = None) -> None:
        async with self._lock:
            self._subs[task_id].discard(q)
            if not self._subs[task_id]:
                self._subs.pop(task_id, None)

    def publish(self, event: dict[str, Any]) -> None:
        """广播一条事件,发出去就不管:发给"什么都收"和"只收这个任务"的两类订阅者。"""
        task_id = event.get("task_id")
        for key in ({None, task_id}):
            for q in list(self._subs.get(key, ())):
                try:
                    q.put_nowait(event)
                except asyncio.QueueFull:
                    try:
                        q.get_nowait()  # 队列满了:扔掉最旧的一条腾位置
                        q.put_nowait(event)
                    except (asyncio.QueueEmpty, asyncio.QueueFull):
                        pass
