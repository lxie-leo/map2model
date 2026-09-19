"""WebSocket 接口的回归测试。

这个端点曾经坏过都没被发现:依赖注入在 WS 路由里拿不到 Request,
直接空参调用炸成 500,连接被拒。这里把握手、欢迎语、心跳、订阅
都过一遍,再坏能立刻红。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def ws_client(tmp_path, monkeypatch):
    """把 app 完整跑起来(数据放临时目录),给测试一条真的 WS 连接。"""
    monkeypatch.setenv("M2M_DATA_DIR", str(tmp_path / "data"))
    from app.config import get_settings

    get_settings.cache_clear()
    from app.main import app

    with TestClient(app) as c:
        yield c
    get_settings.cache_clear()


def test_ws_hello_ping_subscribe(ws_client: TestClient):
    with ws_client.websocket_connect("/api/v1/ws") as ws:
        # 连上先收一句问好(握手能成立本身就证明依赖注入没炸)
        assert ws.receive_json() == {"type": "hello", "version": "1"}

        # 心跳:问一句"还在吗",回个 pong
        ws.send_json({"action": "ping"})
        assert ws.receive_json() == {"type": "pong"}

        # 只听某一个任务
        ws.send_json({"action": "subscribe", "task_id": "t1"})
        assert ws.receive_json() == {"type": "subscribed", "task_id": "t1"}
