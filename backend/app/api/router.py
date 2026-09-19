"""API 总路由:把各个模块的接口拼到一起,统一挂在 /api/v1 下面。"""

from fastapi import APIRouter

from app.api import exports, geocode, system, tasks, ws

api_router = APIRouter()
api_router.include_router(system.router)
api_router.include_router(tasks.router)
api_router.include_router(exports.router)
api_router.include_router(geocode.router)
api_router.include_router(ws.router)
