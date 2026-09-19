"""测试公共设施:一套离线的任务环境(OSM 和地形全用假数据)和现成的 API 客户端。"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import numpy as np
import pytest

FIXTURES = Path(__file__).parent / "fixtures"
# 上海陆家嘴附近的小框选区(约 0.6 x 0.5 公里)
BBOX = (121.4900, 31.2340, 121.4970, 31.2385)


@pytest.fixture
def sample_payload() -> dict:
    with open(FIXTURES / "overpass_sample.json", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def fake_terrain():
    """带一点起伏的假地形(正弦坡),比平地更能暴露建模 bug。"""
    from app.services.terrain import TerrainGrid

    nx = ny = 64
    xs = np.linspace(-300, 300, nx)
    ys = np.linspace(-300, 300, ny)
    gx, gy = np.meshgrid(xs, ys)
    z = 5.0 * np.sin(gx / 120.0) + 3.0 * np.cos(gy / 90.0)  # ±8 米起伏
    return TerrainGrid(-300.0, -300.0, 600 / (nx - 1), nx, ny, z)


@pytest.fixture
async def client(tmp_path, monkeypatch, sample_payload, fake_terrain):
    """把整个 app 跑起来(离线:OSM 和地形都换成假数据,不碰外网)。"""
    monkeypatch.setenv("M2M_DATA_DIR", str(tmp_path / "data"))
    from app.config import get_settings

    get_settings.cache_clear()

    import app.services.overpass as overpass_mod
    import app.services.terrain as terrain_mod

    async def fake_fetch_overpass(bbox, *, settings, on_progress=None, cancel_event=None):
        p = tmp_path / "fake_osm.json"
        p.write_text(json.dumps(sample_payload), encoding="utf-8")
        if on_progress:
            on_progress(1.0, "fixture")
        return p

    async def fake_fetch_terrain(bbox, projector, *, settings, on_progress=None, cancel_event=None):
        if on_progress:
            on_progress(1.0, "fixture terrain")
        return fake_terrain

    monkeypatch.setattr(overpass_mod, "fetch_overpass", fake_fetch_overpass)
    monkeypatch.setattr(terrain_mod, "fetch_terrain", fake_fetch_terrain)

    from app.main import app

    transport = httpx.ASGITransport(app=app)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test", timeout=30
        ) as c:
            yield c
    get_settings.cache_clear()


async def wait_task(client: httpx.AsyncClient, task_id: str, timeout: float = 60.0) -> dict:
    """每隔一小会儿问一次,等任务跑到头(完成/失败/取消都算)。"""
    import asyncio

    for _ in range(int(timeout / 0.1)):
        r = await client.get(f"/api/v1/tasks/{task_id}")
        assert r.status_code == 200, r.text
        task = r.json()
        if task["status"] in ("COMPLETED", "FAILED", "CANCELLED"):
            return task
        await asyncio.sleep(0.1)
    raise TimeoutError(f"task {task_id} did not finish in {timeout}s")
