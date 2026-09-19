"""地点搜索:把地名翻译成坐标(地理编码)。

走 photon 服务(komoot 提供,数据来自 OpenStreetMap)。选它而不是
官方 Nominatim,是因为 Nominatim 主站在中国大陆基本连不上,photon
实测可达。由后端代查而不是浏览器直连——统一出口好控制超时,
顺手做个小缓存,同一个词短时间内重复搜不发第二次请求。
"""

from __future__ import annotations

import time

import httpx

from app.config import Settings
from app.core.errors import FetchError

_CACHE_TTL = 600.0  # 同一个词 10 分钟内重搜,直接回缓存
_CACHE_MAX = 200

# 词 -> (存入时间, 结果列表)
_cache: dict[str, tuple[float, list[dict]]] = {}

# photon 的地址片段,按从细到粗的顺序拼成一行完整地址
_ADDR_KEYS = ("name", "street", "district", "city", "county", "state", "country")


def _format_place(p: dict) -> str:
    """把地址片段拼成一行,重复的(比如 name 和 street 同名)只留一个。"""
    parts = [p.get(k) for k in _ADDR_KEYS]
    return ", ".join(dict.fromkeys(x for x in parts if x))


def _to_result(f: dict) -> dict | None:
    p = f.get("properties") or {}
    geom = f.get("geometry") or {}
    coords = geom.get("coordinates") or []
    if len(coords) != 2:
        return None
    name = p.get("name") or p.get("street") or p.get("city") or "未命名地点"
    # extent 是可选的(点状地点没有):顺序 西,北,东,南,换成熟悉的 西,南,东,北
    ext = p.get("extent")
    bbox = [ext[0], ext[3], ext[2], ext[1]] if isinstance(ext, list) and len(ext) == 4 else None
    return {
        "name": name,
        "display_name": _format_place(p) or name,
        "bbox": bbox,
        "center": [coords[0], coords[1]],
    }


async def search_place(q: str, settings: Settings) -> list[dict]:
    """搜一个地名,最多回 6 条候选,每条带名字、完整地址、中心和范围(可能没有)。"""
    q = q.strip()
    if not q:
        return []

    now = time.monotonic()
    hit = _cache.get(q)
    if hit and now - hit[0] < _CACHE_TTL:
        return hit[1]

    try:
        async with httpx.AsyncClient(
            # photon 门口的 nginx 只放行浏览器样子的 UA,自报家门的会被 403 拒掉
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36"
                ),
            },
            timeout=settings.geocode_timeout,
            follow_redirects=True,
        ) as client:
            resp = await client.get(
                settings.geocode_endpoint,
                params={"q": q, "limit": 6, "lang": "default"},
            )
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPError as exc:
        raise FetchError(f"地点搜索服务连不上: {exc}") from exc

    results = [r for f in data.get("features", []) if (r := _to_result(f))]

    if len(_cache) >= _CACHE_MAX:
        _cache.clear()  # 简单粗暴:满了整个清掉,冷词反正还会再搜
    _cache[q] = (now, results)
    return results
