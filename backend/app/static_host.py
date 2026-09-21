"""桌面版的静态文件伺服:让后端自己把前端 dist 也端出来。

只有配置里开了 serve_static 才生效(桌面版启动器会设 M2M_SERVE_STATIC=1);
网页版的 Docker/nginx 部署不设这个变量,这个模块等于不存在,行为零变化。

挂在 "/" 上要放在所有 API 路由之后,FastAPI 按注册顺序匹配,API 先命中,
剩下的才轮到静态文件 —— 这样既伺服前端又不遮挡接口。
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import FileResponse, JSONResponse
from starlette.staticfiles import StaticFiles

from app.config import Settings


class SpaStaticFiles(StaticFiles):
    """带 SPA 回退的静态伺服:前端路由是 history 模式,/viewer/xxx 这种
    深链刷新时磁盘上没有对应文件,得回 index.html 让 vue-router 接手。
    但 /api 开头的不许回退 —— 打错的接口地址就该给 JSON 404,不能塞个
    HTML 页面回去,不然前端解析错误体直接懵。
    """

    def __init__(self, directory: Path, api_prefix: str):
        self.api_prefix = api_prefix
        # 自己存 index 路径,不依赖父类的 directory 属性(它在 Starlette
        # 各版本里名字和类型都变过,靠它容易踩兼容坑)
        self.index_file = directory / "index.html"
        super().__init__(directory=directory, html=True)

    async def get_response(self, path: str, scope):
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code != 404:
                raise
            # 没匹配上的 API 路径照常 404,和 nginx 部署下打到后端的行为一致
            if scope.get("path", "").startswith(self.api_prefix):
                return JSONResponse({"detail": "Not Found"}, status_code=404)
            # 其余路径(index.html 之外的随便什么深链)都回首页
            return FileResponse(self.index_file)


def mount_static(app: FastAPI, settings: Settings) -> None:
    """按配置把前端静态目录挂上;开关没开就什么都不做。"""
    if not settings.serve_static:
        return
    if settings.static_dir is None or not (settings.static_dir / "index.html").is_file():
        raise RuntimeError(
            "serve_static 开了但 static_dir 没指到有效目录(缺 index.html)。"
            "检查 M2M_STATIC_DIR 是否指向 vite build 出来的 dist,"
            "或者干脆别设 M2M_SERVE_STATIC。"
        )
    app.mount("/", SpaStaticFiles(settings.static_dir, settings.api_prefix), name="spa")
