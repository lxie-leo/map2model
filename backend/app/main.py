"""应用入口,启动命令:uvicorn app.main:app

启动时先把日志、数据库、事件广播、任务管理器备好,再挂上 API 路由和 CORS;
退出时反过来收尾:停掉在跑的任务、关数据库。
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.router import api_router
from app.config import get_settings
from app.core.errors import AppError
from app.core.events import EventBroker
from app.core.task_manager import TaskManager
from app.db import Database
from app.logging_conf import setup_logging
from app.static_host import mount_static

logger = logging.getLogger("app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    setup_logging()
    db = Database(settings.db_path)
    await db.connect()
    broker = EventBroker()
    tm = TaskManager(settings, db, broker)
    await tm.start()
    from app.api.exports import recover_stuck_exports

    await recover_stuck_exports(db)
    app.state.db = db
    app.state.broker = broker
    app.state.task_manager = tm
    logger.info(
        "map2model backend started (data dir: %s)", settings.data_dir.resolve(),
    )
    try:
        yield  # 应用跑在这儿;从这里往下是退出时的收尾
    finally:
        await tm.shutdown()
        await db.close()
        logger.info("map2model backend stopped")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="map2model",
        version=settings.version,
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(api_router, prefix=settings.api_prefix)
    # 桌面版开的静态伺服(挂在最后,挡不住上面的 API 路由);网页版默认关闭,等于没这行
    mount_static(app, settings)

    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status,
            content={"error": {"code": exc.code, "message": exc.message}},
        )

    return app


app = create_app()
