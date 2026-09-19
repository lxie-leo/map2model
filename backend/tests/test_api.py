"""API 全链路:健康检查 → 建任务 → 等完成 → 预览/下载 → 导出 → 下载导出。"""

import asyncio
import json

from tests.conftest import BBOX, wait_task

PREFIX = "/api/v1"


async def test_health(client):
    r = await client.get(f"{PREFIX}/system/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"


async def test_capabilities(client):
    r = await client.get(f"{PREFIX}/system/capabilities")
    assert r.status_code == 200
    body = r.json()
    assert body["formats"]["svg"] is True
    assert body["formats"]["glb"] is True
    assert "3D" in body["groups"] and "2D" in body["groups"] and "GIS" in body["groups"]


async def test_bbox_too_large(client):
    huge = (100.0, 20.0, 102.0, 22.0)  # 约 2 万平方公里
    r = await client.post(f"{PREFIX}/tasks", json={"bbox": huge})
    assert r.status_code == 400
    assert "exceeds" in r.json()["error"]["message"]


async def test_full_task_flow(client):
    # 1. 创建
    r = await client.post(f"{PREFIX}/tasks", json={"bbox": list(BBOX)})
    assert r.status_code == 200, r.text
    task = r.json()
    tid = task["id"]
    assert task["status"] in ("QUEUED", "RUNNING")

    # 2. 等完成(离线假数据,应当很快)
    task = await wait_task(client, tid)
    assert task["status"] == "COMPLETED", task.get("error")
    # 解析出 4 栋,其中 801 号只有 2 个点,建模时被过滤 → 3
    assert task["stats"]["buildings"] == 3
    assert task["progress"] == 100.0
    assert 0 < task["area_km2"] < 1.0

    # 3. 预览 GeoJSON
    r = await client.get(f"{PREFIX}/tasks/{tid}/preview/geojson")
    assert r.status_code == 200
    fc = r.json()
    layers = {f["properties"]["layer"] for f in fc["features"]}
    assert {"building", "road", "railway", "water", "green"} <= layers

    # 4. hub.glb 下载
    r = await client.get(f"{PREFIX}/tasks/{tid}/files/hub.glb")
    assert r.status_code == 200
    assert r.content[:4] == b"glTF"

    # 5. 事件流(补放历史)
    r = await client.get(f"{PREFIX}/tasks/{tid}/events?after_event_id=0")
    assert r.status_code == 200
    assert "stage" in r.text or "done" in r.text

    # 6. 导出 SVG
    r = await client.post(f"{PREFIX}/tasks/{tid}/exports", json={"format": "svg"})
    assert r.status_code == 200, r.text
    exp = r.json()
    for _ in range(100):
        r = await client.get(f"{PREFIX}/exports/{exp['id']}")
        exp = r.json()
        if exp["status"] in ("COMPLETED", "FAILED"):
            break
        await asyncio.sleep(0.1)
    assert exp["status"] == "COMPLETED", exp.get("error")

    # 7. 下载导出
    r = await client.get(f"{PREFIX}/exports/{exp['id']}/download")
    assert r.status_code == 200
    assert b"<svg" in r.content[:100]

    # 8. 导出列表
    r = await client.get(f"{PREFIX}/tasks/{tid}/exports")
    assert len(r.json()) == 1

    # 9. 删除任务
    r = await client.delete(f"{PREFIX}/tasks/{tid}")
    assert r.status_code == 200
    r = await client.get(f"{PREFIX}/tasks/{tid}")
    assert r.status_code == 404


async def test_export_before_complete(client):
    r = await client.post(f"{PREFIX}/tasks", json={"bbox": list(BBOX)})
    tid = r.json()["id"]
    r = await client.post(f"{PREFIX}/tasks/{tid}/exports", json={"format": "svg"})
    assert r.status_code == 409
    await wait_task(client, tid)
    await client.delete(f"{PREFIX}/tasks/{tid}")
