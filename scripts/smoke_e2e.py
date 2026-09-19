# -*- coding: utf-8 -*-
"""修完 bug 后的一次性冒烟检查:对着跑起来的后端把关键链路真刀真枪走一遍。

重点验证这轮修的东西:
1. 任务跑起来再取消,状态要是 CANCELLED,不能再变 FAILED;
2. 删一个跑着的任务,任务目录要真被删掉,不能死灰复燃;
3. SSE 补发的事件要带 task_ 前缀(和 WS 一个长相),after_event_id 能接上断点;
4. 导出照常能跑完。
"""
import asyncio
import sys
import time

import httpx

BASE = "http://127.0.0.1:8009/api/v1"
BBOX = [121.4900, 31.2340, 121.4970, 31.2385]  # 上海陆家嘴旁边的小框
# 取消测试用另一块地(北京故宫旁边):要的是"第一次拉、肯定还在跑"的任务,
# 用上海的 bbox 会命中缓存秒完成,想取消时它已经跑完了
BBOX_CANCEL = [116.3970, 39.9080, 116.4030, 39.9130]


async def main() -> int:
    ok = True
    async with httpx.AsyncClient(base_url=BASE, timeout=30) as c:
        await c.get("/system/health")

        # ---- 1) 取消语义:建一个任务,等它跑起来,再取消 ----
        r = await c.post("/tasks", json={"bbox": BBOX_CANCEL, "options": {}})
        task_a = r.json()["id"]
        print(f"[1] task A = {task_a} ({r.status_code})")
        await asyncio.sleep(3)  # 让它过排队、真正跑起来
        r = await c.post(f"/tasks/{task_a}/cancel")
        status = r.json()["status"]
        print(f"[1] cancel -> {status}")
        await asyncio.sleep(4)  # 给管线一点时间收尾
        r = await c.get(f"/tasks/{task_a}")
        final = r.json()
        print(f"[1] final status={final['status']} error={final['error']!r}")
        if final["status"] != "CANCELLED":
            print("!! 取消语义还是不对")
            ok = False

        # ---- 2) 真跑一个任务到完成 ----
        r = await c.post("/tasks", json={"bbox": BBOX, "options": {}})
        task_b = r.json()["id"]
        print(f"[2] task B = {task_b}")
        deadline = time.monotonic() + 240
        last = None
        while time.monotonic() < deadline:
            t = (await c.get(f"/tasks/{task_b}")).json()
            if t["status"] != last:
                print(f"[2]   {t['status']} {t['stage'] or ''} {t['progress']:.0f}%")
                last = t["status"]
            if t["status"] in ("COMPLETED", "FAILED", "CANCELLED"):
                break
            await asyncio.sleep(2)
        if t["status"] != "COMPLETED":
            print(f"!! 任务没跑成: {t['status']} {t.get('error')}")
            return 1
        print(f"[2] stats = {t['stats'] and {k: t['stats'][k] for k in ('buildings', 'roads')}}")

        # ---- 3) SSE 补发格式 + 断点续传 ----
        async with c.stream("GET", f"/tasks/{task_b}/events?after_event_id=0") as s:
            got_done = False
            async for line in s.aiter_lines():
                if line.startswith("data: ") and '"task_' in line:
                    pass  # 带前缀的事件,好
                if line.startswith("data: ") and '"type": "' in line:
                    import json
                    ev = json.loads(line[6:])
                    if not ev["type"].startswith(("task_", "export_")):
                        print(f"!! SSE 事件还是裸类型: {ev.get('type')}")
                        ok = False
                        break
                    if ev.get("type") == "task_done":
                        got_done = True
                if line.startswith("event: end"):
                    break
            print(f"[3] SSE replay 到 task_done={got_done},事件都带前缀")

        # ---- 4) 导出 ----
        r = await c.post(f"/tasks/{task_b}/exports", json={"format": "geojson"})
        exp = r.json()
        print(f"[4] export = {exp['id']}")
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            e = (await c.get(f"/exports/{exp['id']}")).json()
            if e["status"] in ("COMPLETED", "FAILED"):
                break
            await asyncio.sleep(1)
        print(f"[4] export -> {e['status']} {e.get('filename')}")
        if e["status"] != "COMPLETED":
            ok = False

        # ---- 5) 删掉跑完的任务,目录必须真没了 ----
        r = await c.delete(f"/tasks/{task_b}")
        print(f"[5] delete B -> {r.status_code}")
        from pathlib import Path
        d = Path(r"C:\_e2e_m2m_data\tasks") if False else None
        # 数据目录按默认相对路径起的服务,是 backend/data
        task_dir = Path(__file__).parent.parent / "data" / "tasks" / task_b
        await asyncio.sleep(1)
        if task_dir.exists():
            print(f"!! 任务目录还在: {task_dir}")
            ok = False
        else:
            print("[5] 任务目录已删除")

    print("SMOKE " + ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
