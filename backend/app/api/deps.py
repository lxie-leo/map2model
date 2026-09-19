"""把 app.state 上的公共对象(db、任务管理器、事件广播)取出来递给路由函数,省得到处碰全局变量。"""

from __future__ import annotations

from fastapi import Request, WebSocket

from app.core.events import EventBroker
from app.core.task_manager import TaskManager
from app.db import Database


def get_db(request: Request) -> Database:
    return request.app.state.db


def get_broker(request: Request) -> EventBroker:
    return request.app.state.broker


# WebSocket 路由专用:握手时 FastAPI 手里只有 WebSocket,给不出上面的 Request,
# 参数标注对不上它就干脆不传,get_broker() 空参调用直接炸成 500、连接被拒
def get_broker_ws(websocket: WebSocket) -> EventBroker:
    return websocket.app.state.broker


def get_task_manager(request: Request) -> TaskManager:
    return request.app.state.task_manager
