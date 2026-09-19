"""配置都集中在这儿:默认值写在下面,想改就写进 .env 文件或环境变量(变量名前面加 M2M_)。"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="M2M_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "map2model"
    version: str = "0.1.0"
    api_prefix: str = "/api/v1"
    cors_origins: list[str] = ["*"]

    # --- 抓数据相关(Overpass 网址、地形瓦片)---
    # Overpass 网址从上往下试,前面连不上或超时就换下一个
    overpass_endpoints: list[str] = [
        "https://overpass.kumi.systems/api/interpreter",
        "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
        "https://overpass-api.de/api/interpreter",
        "https://overpass.osm.jp/api/interpreter",
    ]
    overpass_timeout: float = 120.0
    # 地点搜索(地理编码)用的 photon 服务网址。
    # 不用官方 Nominatim:它的主站在中国大陆连不上,photon 实测可达
    geocode_endpoint: str = "https://photon.komoot.io/api"
    geocode_timeout: float = 10.0
    # 地形高程瓦片的网址模板,{z}/{x}/{y} 用的时候再填
    terrain_url_template: str = (
        "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"
    )
    terrain_z_max: int = 13
    terrain_max_tiles: int = 64

    # --- 各种上限,防止框的区域太大把内存/磁盘撑爆 ---
    max_bbox_area_km2: float = 25.0  # 框选最大 25 km²,再大直接拒收
    max_buildings: int = 20000
    grid_max_verts: int = 512

    # --- 运行时杂项 ---
    task_concurrency: int = 2  # 同时最多跑 2 个任务,多了排队等着
    blender_path: str = "auto"  # auto = 自己去找 Blender,找不到就禁用 FBX/DAE
    data_dir: Path = Path("data")

    @property
    def cache_dir(self) -> Path:
        return self.data_dir / "cache" / "overpass"

    @property
    def tasks_dir(self) -> Path:
        return self.data_dir / "tasks"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "app.db"

    def ensure_dirs(self) -> None:
        for p in (self.data_dir, self.cache_dir, self.tasks_dir):
            p.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    """第一次调用时读配置、建好目录,之后一直返回同一个对象。"""
    settings = Settings()
    settings.ensure_dirs()
    return settings
