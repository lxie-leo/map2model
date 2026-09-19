"""地点搜索接口:GET /api/v1/geocode?q=地名"""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.config import get_settings
from app.services.geocode import search_place

router = APIRouter(tags=["geocode"])


@router.get("/geocode")
async def geocode(q: str = Query(min_length=1, max_length=200)) -> list[dict]:
    return await search_place(q, get_settings())
