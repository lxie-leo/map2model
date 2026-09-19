"""地点搜索的离线测试:HTTP 请求换成假数据,不碰外网。"""

from __future__ import annotations

import httpx

from app.services import geocode as geo_mod


def _install_fake_client(monkeypatch, rows) -> None:
    """把 geocode 里发请求的 httpx.AsyncClient 换成只会回假数据的替身。

    rows 是 Feature 列表,形状照抄 photon 的返回(GeoJSON FeatureCollection)。
    """

    class FakeResp:
        def raise_for_status(self) -> None:
            pass

        def json(self) -> dict:
            return {"type": "FeatureCollection", "features": rows}

    class FakeClient:
        def __init__(self, **kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def get(self, url, params=None):
            return FakeResp()

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)


def _feature(name: str, city: str, lon: float, lat: float, extent=None) -> dict:
    return {
        "type": "Feature",
        "properties": {"name": name, "city": city, "extent": extent},
        "geometry": {"type": "Point", "coordinates": [lon, lat]},
    }


async def test_geocode_converts_extent(client, monkeypatch):
    """photon 的范围顺序(西,北,东,南)要转成全项目通用的(西,南,东,北)。"""
    _install_fake_client(monkeypatch, [
        _feature("陆家嘴", "上海市", 121.5, 31.23, extent=[121.48, 31.25, 121.52, 31.2]),
    ])
    geo_mod._cache.clear()

    r = await client.get("/api/v1/geocode", params={"q": "陆家嘴"})
    assert r.status_code == 200, r.text
    rows = r.json()
    assert rows[0]["name"] == "陆家嘴"
    assert rows[0]["bbox"] == [121.48, 31.2, 121.52, 31.25]
    assert rows[0]["center"] == [121.5, 31.23]


async def test_geocode_point_without_extent(client, monkeypatch):
    """点状地点没有范围:bbox 给空,只回中心。"""
    _install_fake_client(monkeypatch, [_feature("东方明珠", "上海市", 121.4997, 31.2397)])
    geo_mod._cache.clear()

    r = await client.get("/api/v1/geocode", params={"q": "东方明珠"})
    assert r.status_code == 200
    rows = r.json()
    assert rows[0]["bbox"] is None
    assert rows[0]["center"] == [121.4997, 31.2397]


async def test_geocode_caches_repeat_query(client, monkeypatch):
    """同一个词短时间重搜,不再发第二次请求。"""
    calls = []

    class FakeResp:
        def raise_for_status(self) -> None:
            pass

        def json(self) -> dict:
            return {
                "type": "FeatureCollection",
                "features": [_feature("外滩", "上海市", 121.49, 31.24)],
            }

    class FakeClient:
        def __init__(self, **kwargs) -> None:
            pass

        async def __aenter__(self):
            calls.append(1)
            return self

        async def __aexit__(self, *args):
            pass

        async def get(self, url, params=None):
            return FakeResp()

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
    geo_mod._cache.clear()

    for _ in range(2):
        r = await client.get("/api/v1/geocode", params={"q": "外滩"})
        assert r.status_code == 200
    assert len(calls) == 1  # 第二次走了缓存
