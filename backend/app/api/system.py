"""系统接口:/health 给外部探活用;capabilities 告诉前端哪些导出格式这台机器能用。"""

from __future__ import annotations

import time

from fastapi import APIRouter, Depends

from app.config import Settings, get_settings
from app.services.export import capabilities as export_capabilities

router = APIRouter(tags=["system"])


@router.get("/system/health")
async def health() -> dict:
    return {
        "status": "ok",
        "version": get_settings().version,
        "time": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + "Z",
    }


@router.get("/system/capabilities")
async def capabilities(settings: Settings = Depends(get_settings)) -> dict:
    caps = export_capabilities(settings)
    return {
        "version": settings.version,
        "blender_path": caps["blender_path"],
        "formats": caps["formats"],
        "groups": caps["groups"],
    }
