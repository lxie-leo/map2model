"""静态伺服(桌面版同源托管)的测试。

重点是两条边界:开开关后前端能正常伺服且 API 不被遮挡;
不开开关时一切照旧(这是网页版零回归的自动证明)。
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from app.config import get_settings
from app.main import create_app

INDEX_HTML = "<!doctype html><html><body>map2model</body></html>"


@pytest.fixture
def fake_dist(tmp_path: Path) -> Path:
    """造假的前端 dist:index.html + 一个 assets 文件,够测路由就行。"""
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text(INDEX_HTML, encoding="utf-8")
    (dist / "assets" / "app.js").write_text("console.log(1)", encoding="utf-8")
    return dist


async def make_client(monkeypatch, tmp_path, dist_on: bool, static_dir: Path | None):
    """按开关状态现造一个 app 实例并包成测试客户端。

    不能复用模块级的 app —— 它在导入时就已经按当时的配置建好了,
    这里必须重新 create_app() 才能吃到新环境变量。
    """
    monkeypatch.setenv("M2M_DATA_DIR", str(tmp_path / "data"))
    if dist_on:
        monkeypatch.setenv("M2M_SERVE_STATIC", "1")
        monkeypatch.setenv("M2M_STATIC_DIR", str(static_dir))
    else:
        monkeypatch.delenv("M2M_SERVE_STATIC", raising=False)
        monkeypatch.delenv("M2M_STATIC_DIR", raising=False)
    get_settings.cache_clear()
    app = create_app()
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    )


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    """settings 带 lru_cache,进出都清一次,免得脏配置漏到别的测试。"""
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


async def test_static_off_root_is_404(monkeypatch, tmp_path):
    """开关没开:GET / 还是 FastAPI 默认的 JSON 404 —— 网页版行为不变的证明。"""
    async with await make_client(monkeypatch, tmp_path, dist_on=False, static_dir=None) as c:
        res = await c.get("/")
        assert res.status_code == 404
        assert res.headers["content-type"].startswith("application/json")


async def test_serves_index_and_assets(monkeypatch, tmp_path, fake_dist):
    """开关开了:/ 出 index.html,assets 静态文件原样伺服。"""
    async with await make_client(monkeypatch, tmp_path, True, fake_dist) as c:
        res = await c.get("/")
        assert res.status_code == 200
        assert "map2model" in res.text
        res = await c.get("/assets/app.js")
        assert res.status_code == 200
        assert "javascript" in res.headers["content-type"]


async def test_spa_deep_link_falls_back_to_index(monkeypatch, tmp_path, fake_dist):
    """/viewer/xxx 这种前端深链,磁盘上没文件,回 index.html 让 vue-router 接手。"""
    async with await make_client(monkeypatch, tmp_path, True, fake_dist) as c:
        res = await c.get("/viewer/some-task")
        assert res.status_code == 200
        assert "map2model" in res.text


async def test_api_miss_stays_json_404(monkeypatch, tmp_path, fake_dist):
    """打错的 API 地址必须给 JSON 404,绝不能回退成 HTML 页面。"""
    async with await make_client(monkeypatch, tmp_path, True, fake_dist) as c:
        res = await c.get("/api/v1/nope")
        assert res.status_code == 404
        assert res.headers["content-type"].startswith("application/json")
        assert res.json()["detail"] == "Not Found"


async def test_api_routes_not_shadowed(monkeypatch, tmp_path, fake_dist):
    """挂了静态伺服后,真 API 路由照常工作(health 不碰 db,不用起 lifespan)。"""
    async with await make_client(monkeypatch, tmp_path, True, fake_dist) as c:
        res = await c.get("/api/v1/system/health")
        assert res.status_code == 200
        assert res.json()["status"] == "ok"


async def test_head_and_post_on_spa(monkeypatch, tmp_path, fake_dist):
    """HEAD 照常工作;POST 到未匹配路径给 JSON 405,不能吐 HTML。"""
    async with await make_client(monkeypatch, tmp_path, True, fake_dist) as c:
        res = await c.head("/")
        assert res.status_code == 200
        res = await c.post("/viewer/some-task")
        assert res.status_code == 405
        assert res.headers["content-type"].startswith("application/json")


async def test_path_traversal_no_leak(monkeypatch, tmp_path, fake_dist):
    """路径穿越尝试(../ 的编码形式)不许读到静态目录外的文件。"""
    async with await make_client(monkeypatch, tmp_path, True, fake_dist) as c:
        res = await c.get("/assets/%2e%2e/%2e%2e/%2e%2e/app/config.py")
        # 两种可接受结局:404,或被 SPA 回退成首页 —— 唯独不能是文件内容
        assert res.status_code in (200, 404)
        assert "sqlite" not in res.text.lower()
        assert "cors_origins" not in res.text


async def test_missing_asset_falls_back_to_index(monkeypatch, tmp_path, fake_dist):
    """不存在的静态资源回首页(和 nginx try_files 的行为一致),不算泄漏。"""
    async with await make_client(monkeypatch, tmp_path, True, fake_dist) as c:
        res = await c.get("/assets/missing.js")
        assert res.status_code == 200
        assert "map2model" in res.text


async def test_bad_static_dir_fails_fast(monkeypatch, tmp_path):
    """开关开了但目录没 index.html:启动就报错,比跑起来白屏好排查。"""
    monkeypatch.setenv("M2M_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("M2M_SERVE_STATIC", "1")
    monkeypatch.setenv("M2M_STATIC_DIR", str(tmp_path / "empty"))
    get_settings.cache_clear()
    with pytest.raises(RuntimeError, match="M2M_STATIC_DIR"):
        create_app()
