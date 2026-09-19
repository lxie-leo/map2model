"""SQLite 数据库(开了 WAL 模式)。一共三张表:tasks(任务)、task_events(进度事件)、exports(导出记录)。

坑:SQLite 不喜欢好几个协程同时写,会互相打架。
所以所有写操作都过同一把锁排队,一个写完再轮下一个,这样全程共用一个连接也不出乱子。
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any

import aiosqlite

_SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    id          TEXT PRIMARY KEY,
    status      TEXT NOT NULL DEFAULT 'QUEUED',
    stage       TEXT,
    progress    REAL NOT NULL DEFAULT 0,
    bbox        TEXT NOT NULL,
    area_km2    REAL NOT NULL DEFAULT 0,
    options     TEXT NOT NULL DEFAULT '{}',
    warnings    TEXT NOT NULL DEFAULT '[]',
    error       TEXT,
    stats       TEXT,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    completed_at TEXT
);
CREATE TABLE IF NOT EXISTS task_events (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id  TEXT NOT NULL,
    ts       TEXT NOT NULL,
    type     TEXT NOT NULL,
    stage    TEXT,
    progress REAL,
    message  TEXT
);
CREATE INDEX IF NOT EXISTS idx_task_events_task ON task_events(task_id, id);
CREATE TABLE IF NOT EXISTS exports (
    id         TEXT PRIMARY KEY,
    task_id    TEXT NOT NULL,
    format     TEXT NOT NULL,
    status     TEXT NOT NULL DEFAULT 'QUEUED',
    progress   REAL NOT NULL DEFAULT 0,
    filename   TEXT,
    error      TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_exports_task ON exports(task_id);
"""


def _now() -> str:
    """当前 UTC 时间,统一存成 2026-01-01T00:00:00Z 这种格式。"""
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + "Z"


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._conn: aiosqlite.Connection | None = None
        self._write_lock = asyncio.Lock()

    async def connect(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(self.path)
        self._conn.row_factory = aiosqlite.Row
        # WAL 模式:写的时候不影响别人读
        await self._conn.execute("PRAGMA journal_mode=WAL")
        # 同步档位放低一点写起来快很多,最坏掉电丢最后一条,能接受
        await self._conn.execute("PRAGMA synchronous=NORMAL")
        await self._conn.executescript(_SCHEMA)
        await self._conn.commit()

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    @property
    def conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("Database not connected")
        return self._conn

    # --- 通用读写 ---------------------------------------------------------
    async def execute(self, sql: str, params: tuple = ()) -> None:
        async with self._write_lock:
            await self.conn.execute(sql, params)
            await self.conn.commit()

    async def fetch_one(self, sql: str, params: tuple = ()) -> dict[str, Any] | None:
        async with self._conn.execute(sql, params) as cur:
            row = await cur.fetchone()
        return dict(row) if row else None

    async def fetch_all(self, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
        async with self._conn.execute(sql, params) as cur:
            rows = await cur.fetchall()
        return [dict(r) for r in rows]

    # --- 任务表 -----------------------------------------------------------
    async def insert_task(self, task: dict[str, Any]) -> None:
        await self.execute(
            "INSERT INTO tasks (id, status, stage, progress, bbox, area_km2, options,"
            " warnings, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                task["id"],
                task["status"],
                task.get("stage"),
                task.get("progress", 0),
                json.dumps(task["bbox"]),
                task["area_km2"],
                json.dumps(task.get("options", {})),
                json.dumps(task.get("warnings", [])),
                task["created_at"],
                task["created_at"],
            ),
        )

    async def update_task(self, task_id: str, **fields: Any) -> None:
        if not fields:
            return
        cols = ", ".join(f"{k} = ?" for k in fields)
        await self.execute(
            f"UPDATE tasks SET {cols}, updated_at = ? WHERE id = ?",
            (*fields.values(), _now(), task_id),
        )

    async def update_task_if(self, task_id: str, expect_status: str, **fields: Any) -> bool:
        """只在任务还处于 expect_status 状态时才更新,改了返回 True。

        用在进度上报上:任务已经完结(成功/失败/取消)后,迟到的进度消息
        就别再写了,免得把定论又改回"运行中"。
        """
        if not fields:
            return False
        cols = ", ".join(f"{k} = ?" for k in fields)
        async with self._write_lock:
            cur = await self.conn.execute(
                f"UPDATE tasks SET {cols}, updated_at = ? WHERE id = ? AND status = ?",
                (*fields.values(), _now(), task_id, expect_status),
            )
            await self.conn.commit()
            return cur.rowcount > 0

    async def get_task(self, task_id: str) -> dict[str, Any] | None:
        row = await self.fetch_one("SELECT * FROM tasks WHERE id = ?", (task_id,))
        return self._decode_task(row) if row else None

    async def list_tasks(self, limit: int = 100) -> list[dict[str, Any]]:
        rows = await self.fetch_all(
            "SELECT * FROM tasks ORDER BY created_at DESC, id DESC LIMIT ?", (limit,)
        )
        return [self._decode_task(r) for r in rows]

    @staticmethod
    def _decode_task(row: dict[str, Any]) -> dict[str, Any]:
        """入库时 bbox/options 这些被存成了 JSON 字符串,读出来要还原成对象。"""
        row["bbox"] = json.loads(row["bbox"])
        row["options"] = json.loads(row["options"])
        row["warnings"] = json.loads(row["warnings"])
        row["stats"] = json.loads(row["stats"]) if row["stats"] else None
        return row

    # --- 事件表 ----------------------------------------------------------
    async def insert_event(
        self,
        task_id: str,
        type_: str,
        stage: str | None = None,
        progress: float | None = None,
        message: str | None = None,
    ) -> int:
        async with self._write_lock:
            cur = await self.conn.execute(
                "INSERT INTO task_events (task_id, ts, type, stage, progress, message)"
                " VALUES (?,?,?,?,?,?)",
                (task_id, _now(), type_, stage, progress, message),
            )
            await self.conn.commit()
            return cur.lastrowid or 0

    async def events_after(self, task_id: str, after_id: int = 0) -> list[dict[str, Any]]:
        return await self.fetch_all(
            "SELECT * FROM task_events WHERE task_id = ? AND id > ? ORDER BY id",
            (task_id, after_id),
        )

    # --- 导出表 ---------------------------------------------------------
    async def insert_export(self, exp: dict[str, Any]) -> None:
        await self.execute(
            "INSERT INTO exports (id, task_id, format, status, progress, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?,?)",
            (
                exp["id"],
                exp["task_id"],
                exp["format"],
                exp.get("status", "QUEUED"),
                exp.get("progress", 0),
                exp["created_at"],
                exp["created_at"],
            ),
        )

    async def update_export(self, export_id: str, **fields: Any) -> None:
        if not fields:
            return
        cols = ", ".join(f"{k} = ?" for k in fields)
        await self.execute(
            f"UPDATE exports SET {cols}, updated_at = ? WHERE id = ?",
            (*fields.values(), _now(), export_id),
        )

    async def get_export(self, export_id: str) -> dict[str, Any] | None:
        return await self.fetch_one("SELECT * FROM exports WHERE id = ?", (export_id,))

    async def list_exports(self, task_id: str) -> list[dict[str, Any]]:
        return await self.fetch_all(
            "SELECT * FROM exports WHERE task_id = ? ORDER BY created_at DESC, id DESC",
            (task_id,),
        )
