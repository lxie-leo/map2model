"""接口收发数据用的结构定义(pydantic v2):前端传的参数不对会被自动打回,不用手写检查。"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

BBox = tuple[float, float, float, float]  # (min_lon, min_lat, max_lon, max_lat),按西、南、东、北四条边算

TaskStatus = Literal["QUEUED", "RUNNING", "COMPLETED", "FAILED", "CANCELLED"]
TaskStage = Literal[
    "FETCH_OVERPASS", "FETCH_TERRAIN", "PARSE_VECTOR", "BUILD_MESH", "WRITE_HUB"
]
ExportFormat = Literal[
    "glb", "obj", "stl", "usdz", "fbx", "dae",
    "dxf", "svg", "pdf", "png", "geojson",
    "gpkg", "shp", "kml", "kmz", "cityjson", "3dtiles",
]


class TaskOptions(BaseModel):
    buildings: bool = True
    roads: bool = True
    railways: bool = True
    water: bool = True
    green: bool = True
    terrain: bool = True


class TaskCreate(BaseModel):
    bbox: BBox = Field(..., description="min_lon, min_lat, max_lon, max_lat")
    options: TaskOptions = Field(default_factory=TaskOptions)

    @model_validator(mode="after")
    def _check(self) -> TaskCreate:
        """检查一下 bbox 合不合法:经度 -180~180、纬度 -90~90,西要小于东、南要小于北,不对就报错。"""
        w, s, e, n = self.bbox
        if not (-180 <= w < e <= 180 and -90 <= s < n <= 90):
            raise ValueError("invalid bbox: expect (min_lon, min_lat, max_lon, max_lat)")
        return self


class TaskRead(BaseModel):
    id: str
    status: TaskStatus
    stage: TaskStage | None = None
    progress: float = 0
    bbox: BBox
    area_km2: float = 0
    options: TaskOptions = Field(default_factory=TaskOptions)
    warnings: list[str] = Field(default_factory=list)
    error: str | None = None
    stats: dict[str, Any] | None = None
    created_at: str
    updated_at: str


class TaskEventRead(BaseModel):
    id: int
    task_id: str
    ts: str
    type: str
    stage: TaskStage | None = None
    progress: float | None = None
    message: str | None = None


class ExportCreate(BaseModel):
    format: ExportFormat
    # 只导这些图层(大写名,同 3D 场景的图层 key);不传 = 全部都要。
    # 对应详情页图层面板里的勾选状态
    layers: list[str] | None = None


class ExportRead(BaseModel):
    id: str
    task_id: str
    format: str
    status: TaskStatus
    progress: float = 0
    filename: str | None = None
    error: str | None = None
    created_at: str
    updated_at: str


class CapabilitiesRead(BaseModel):
    version: str
    blender_path: str | None
    formats: dict[str, bool]
    groups: dict[str, list[str]]


class HealthRead(BaseModel):
    status: str
    version: str
    time: str
