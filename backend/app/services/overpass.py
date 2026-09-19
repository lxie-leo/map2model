"""从 Overpass API 抓取框选区域的 OSM 矢量数据(建筑/道路/铁路/水系/绿地)。

抓取思路(应对中国大陆的网络环境):
1. 先发一个"合并大查询"(用 out geom 直接带出坐标,省得再一个个查节点);
2. 不行就拆成 3 个小查询(建筑 / 线状要素 / 面状要素)分开重试;
3. 一个镜像站打不通就换下一个,每败一次多歇一会儿再试;
4. 抓到的结果按查询内容存在本地,同一块地重复框选直接读盘。
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from pathlib import Path

import httpx

from app.config import Settings
from app.core.errors import FetchError
from app.utils.caching import sha256_hex, stream_to_file, write_json_atomic

logger = logging.getLogger("app.overpass")

# 道路/铁路/水系要抓的类别(正则)
_RAIL_TYPES = "rail|light_rail|subway|tram|monorail|narrow_gauge|funicular"
_WATERWAY_TYPES = "river|stream|canal|ditch|drain"
_NATURAL_POLY = "water|wetland|wood|scrub"
_LANDUSE_POLY = (
    "forest|grass|meadow|recreation_ground|village_green|cemetery|farmland|orchard"
)
_LEISURE_POLY = "park|garden|playground|pitch|golf_course"


def _bbox_str(bbox: tuple[float, float, float, float]) -> str:
    # Overpass 的顺序是:南,西,北,东(纬度在前)
    min_lon, min_lat, max_lon, max_lat = bbox
    return f"{min_lat},{min_lon},{max_lat},{max_lon}"


def build_query(bbox: tuple[float, float, float, float], timeout: int = 120) -> str:
    """合并大查询:所有要素类型一把抓。timeout 是给 Overpass 服务端的处理时限(秒)"""
    b = _bbox_str(bbox)
    return f"""
[out:json][timeout:{timeout}];
(
  way["building"]({b});
  relation["building"]({b});
  way["highway"]({b});
  way["railway"~"^({_RAIL_TYPES})$"]({b});
  way["waterway"~"^({_WATERWAY_TYPES})$"]({b});
  relation["waterway"~"^({_WATERWAY_TYPES})$"]({b});
  way["natural"~"^({_NATURAL_POLY})$"]({b});
  relation["natural"~"^({_NATURAL_POLY})$"]({b});
  way["landuse"~"^({_LANDUSE_POLY})$"]({b});
  relation["landuse"~"^({_LANDUSE_POLY})$"]({b});
  way["leisure"~"^({_LEISURE_POLY})$"]({b});
  relation["leisure"~"^({_LEISURE_POLY})$"]({b});
);
out geom;
""".strip()


def build_split_queries(bbox: tuple[float, float, float, float], timeout: int = 120) -> list[str]:
    """大查询失败后的 3 个子查询:建筑 / 线状 / 面状"""
    b = _bbox_str(bbox)
    buildings = f'[out:json][timeout:{timeout}];(way["building"]({b});relation["building"]({b}););out geom;'
    linear = (
        f'[out:json][timeout:{timeout}];('
        f'way["highway"]({b});'
        f'way["railway"~"^({_RAIL_TYPES})$"]({b});'
        f'way["waterway"~"^({_WATERWAY_TYPES})$"]({b});'
        f'relation["waterway"~"^({_WATERWAY_TYPES})$"]({b});'
        f');out geom;'
    )
    polygons = (
        f'[out:json][timeout:{timeout}];('
        f'way["natural"~"^({_NATURAL_POLY})$"]({b});relation["natural"~"^({_NATURAL_POLY})$"]({b});'
        f'way["landuse"~"^({_LANDUSE_POLY})$"]({b});relation["landuse"~"^({_LANDUSE_POLY})$"]({b});'
        f'way["leisure"~"^({_LEISURE_POLY})$"]({b});relation["leisure"~"^({_LEISURE_POLY})$"]({b});'
        f');out geom;'
    )
    return [buildings, linear, polygons]


async def _try_endpoint(
    client: httpx.AsyncClient,
    endpoint: str,
    query: str,
    out_path: Path,
) -> Path:
    """向一个镜像站发查询,边收边写临时文件(免得大响应撑爆内存),验完再转正"""
    # 临时文件名带上 attempt/sub0 + 一小段随机号:名字的部分让中间产物
    # 各有各的,随机号让两个任务同时抓同一块地时也不挤同一个文件
    # (挤同一个的话,Windows 上一个开着、另一个想换名,会莫明报"拒绝访问")
    tmp = out_path.with_name(f"{out_path.name}.{uuid.uuid4().hex[:8]}.downloading")
    try:
        async with client.stream(
            "POST", endpoint, data={"data": query},
            headers={"User-Agent": "map2model/0.1 (study project)"},
        ) as resp:
            resp.raise_for_status()
            await stream_to_file(resp.aiter_bytes(chunk_size=1 << 16), tmp)
        # 写完读回来验一下,确认真是 Overpass 的正经回应,不是半截报错页
        with open(tmp, encoding="utf-8") as f:
            payload = json.load(f)
        if "elements" not in payload:
            raise ValueError(f"unexpected overpass response from {endpoint}: no 'elements'")
    except BaseException:
        tmp.unlink(missing_ok=True)  # 失败的半截文件别赖在缓存目录里
        raise
    tmp.replace(out_path)
    return out_path


async def fetch_overpass(
    bbox: tuple[float, float, float, float],
    *,
    settings: Settings,
    on_progress=None,
    cancel_event: asyncio.Event | None = None,
) -> Path:
    """抓 OSM 数据,返回缓存文件路径。镜像全试遍了还不行才抛 FetchError。"""
    # 服务端处理时限跟着客户端超时走(留 15 秒给数据传输),免得客户端还在傻等
    # 服务端早就掐了的情况白白走完一轮镜像
    server_timeout = max(25, int(settings.overpass_timeout) - 15)
    query = build_query(bbox, server_timeout)
    key = sha256_hex(query)
    cached = settings.cache_dir / f"{key}.json"
    if cached.exists():
        logger.info("overpass cache hit %s", key[:12])
        if on_progress:
            on_progress(1.0, f"cache hit {key[:12]}")
        return cached

    if on_progress:
        on_progress(0.02, "querying overpass")
    timeout = httpx.Timeout(connect=15, read=settings.overpass_timeout, write=30, pool=15)
    errors: list[str] = []

    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        # 第一轮:合并大查询挨个镜像站试,失败就歇一会儿再换下一个
        attempt_path = settings.cache_dir / f"{key}.attempt"
        merged_ok = False
        for i, endpoint in enumerate(settings.overpass_endpoints):
            if cancel_event and cancel_event.is_set():
                raise FetchError("cancelled")
            try:
                if on_progress:
                    on_progress(
                        min(0.9, 0.1 + i * 0.2), f"overpass try {i + 1}/{len(settings.overpass_endpoints)}: {endpoint.split('/')[2]}"
                    )
                await _try_endpoint(client, endpoint, query, attempt_path)
                merged_ok = True
                break
            except Exception as exc:  # noqa: BLE001 - 端点级失败继续换下一个
                errors.append(f"{endpoint}: {exc}")
                logger.warning("overpass endpoint failed: %s", errors[-1])
                await asyncio.sleep(min(2**i, 8))
        if merged_ok:
            attempt_path.replace(cached)
            if on_progress:
                on_progress(1.0, "overpass data fetched")
            return cached

        # 第二轮:拆成 3 个小查询,一个一个补齐
        logger.warning("merged query failed on all endpoints, trying split queries")
        merged_elements: list[dict] = []
        seen: set[tuple[str, int]] = set()
        for qi, sub in enumerate(build_split_queries(bbox, server_timeout)):
            if cancel_event and cancel_event.is_set():
                raise FetchError("cancelled")
            sub_path = settings.cache_dir / f"{key}.sub{qi}"
            done = False
            for i, endpoint in enumerate(settings.overpass_endpoints):
                try:
                    if on_progress:
                        on_progress(0.3 + qi * 0.2, f"split query {qi + 1}/3 retry {i + 1}")
                    await _try_endpoint(client, endpoint, sub, sub_path)
                    done = True
                    break
                except Exception as exc:  # noqa: BLE001
                    errors.append(f"sub{qi} {endpoint}: {exc}")
                    await asyncio.sleep(min(2**i, 8))
            if not done:
                raise FetchError(
                    "all overpass endpoints failed for split query "
                    f"{qi + 1}; last errors: {'; '.join(errors[-3:])}"
                )
            with open(sub_path, encoding="utf-8") as f:
                for el in json.load(f).get("elements", []):
                    sig = (el.get("type", ""), el.get("id", 0))
                    if sig not in seen:
                        seen.add(sig)
                        merged_elements.append(el)
            sub_path.unlink(missing_ok=True)

    settings.cache_dir.mkdir(parents=True, exist_ok=True)
    # 合并结果也要走"先写临时文件再改名"的老规矩:直写的话,进程半路被
    # 掐会留下半截 JSON,以后同框选的任务一读缓存就报错,还回回都错
    write_json_atomic(
        cached,
        {"version": 0.6, "generator": "map2model-merge", "elements": merged_elements},
    )
    if on_progress:
        on_progress(1.0, f"overpass data fetched ({len(merged_elements)} elements, split)")
    return cached
