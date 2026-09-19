"""地形高程:抓取 AWS Terrain Tiles(terrarium 格式 PNG)拼成高程网格。

原理:terrarium 瓦片把每个像素的海拔藏进 RGB 三个颜色通道——
高度 = R×256 + G + B/256 − 32768(单位米)。
把框选区盖到的瓦片拼成一张大图,再按大约 10 米一格的目标精度
缩成一张 N×N 的小网格(边长不超过 512),建模时就拿它查高度。

抓不到也不报错:凑合用平地、记条警告,任务照常往下走。
"""

from __future__ import annotations

import asyncio
import io
import logging
import math

import httpx
import numpy as np
from PIL import Image

from app.config import Settings
from app.services.projection import Projector
from app.utils.geom import lonlat_to_tile

logger = logging.getLogger("app.terrain")


class TerrainGrid:
    """一张盖住框选区的高程网格,坐标系是局部米制(原点=框选中心)。

    z 数组第 0 行对应最南边(y 最小),第 0 列对应最西边(x 最小)。
    """

    def __init__(self, origin_x: float, origin_y: float, dx: float,
                 nx: int, ny: int, z: np.ndarray, dy: float | None = None) -> None:
        self.origin_x = origin_x  # 西南角的局部 x(米)
        self.origin_y = origin_y  # 西南角的局部 y(米)
        self.dx = dx              # x 方向格点间距(米)
        self.dy = dx if dy is None else dy  # y 方向间距(框选区不是正方形时和 dx 不一样)
        self.nx = nx
        self.ny = ny
        self.z = z                # 形状 (ny, nx) 的高程数组(米)
        self.median_height = float(np.median(z))

    def sample(self, x: float, y: float) -> float:
        """查任意点的高度:落在哪四个格点中间,就在这四个高度之间平滑地猜一个;问到网格外就用最边上的值。"""
        fx = (x - self.origin_x) / self.dx
        fy = (y - self.origin_y) / self.dy
        fx = min(max(fx, 0.0), self.nx - 1.0)
        fy = min(max(fy, 0.0), self.ny - 1.0)
        x0, y0 = int(fx), int(fy)
        x1, y1 = min(x0 + 1, self.nx - 1), min(y0 + 1, self.ny - 1)
        tx, ty = fx - x0, fy - y0
        z00 = self.z[y0, x0]
        z10 = self.z[y0, x1]
        z01 = self.z[y1, x0]
        z11 = self.z[y1, x1]
        return float(
            (z00 * (1 - tx) + z10 * tx) * (1 - ty) + (z01 * (1 - tx) + z11 * tx) * ty
        )

    @classmethod
    def flat(cls, width_m: float, height_m: float) -> TerrainGrid:
        """平地兜底:一张 2×2 的零高程网格。"""
        return cls(-width_m / 2, -height_m / 2, width_m, 2, 2,
                   np.zeros((2, 2), dtype=np.float64), dy=height_m)


def _decode_terrarium(img: Image.Image) -> np.ndarray:
    """按文件头那个公式,把 terrarium PNG 解回海拔米数。"""
    arr = np.asarray(img.convert("RGB"), dtype=np.float64)
    return arr[:, :, 0] * 256.0 + arr[:, :, 1] + arr[:, :, 2] / 256.0 - 32768.0


def _pick_zoom(bbox: tuple[float, float, float, float], z_max: int) -> int:
    """挑一个缩放级别,让图上一像素大概对应地上 10 米。

    经验数字:Web 墨卡托在级别 z 时,赤道附近一像素约 156543/2^z 米。
    """
    _, min_lat, _, max_lat = bbox
    lat = math.radians(max(abs(min_lat), abs(max_lat), 1e-6))
    meters_per_px = 156543.03392 * math.cos(lat)
    z = round(math.log2(meters_per_px / 10.0))
    return int(min(max(z, 0), z_max))


async def fetch_terrain(
    bbox: tuple[float, float, float, float],
    projector: Projector,
    *,
    settings: Settings,
    on_progress=None,
    cancel_event: asyncio.Event | None = None,
) -> TerrainGrid | None:
    """抓瓦片、拼出高程网格;实在抓不到就返回 None,调用方会凑合用平地。"""
    min_lon, min_lat, max_lon, max_lat = bbox
    try:
        z = _pick_zoom(bbox, settings.terrain_z_max)
        tx0, ty0 = lonlat_to_tile(min_lon, max_lat, z)   # 左上(北)
        tx1, ty1 = lonlat_to_tile(max_lon, min_lat, z)   # 右下(南)
        n_tiles = (tx1 - tx0 + 1) * (ty1 - ty0 + 1)
        if n_tiles > settings.terrain_max_tiles:
            raise ValueError(
                f"needs {n_tiles} terrain tiles > limit {settings.terrain_max_tiles}"
            )
        if on_progress:
            on_progress(0.05, f"terrain z={z}, {n_tiles} tiles")

        # 并发抓瓦片(最多 8 个同时)
        sem = asyncio.Semaphore(8)
        mosaic = np.full(((ty1 - ty0 + 1) * 256, (tx1 - tx0 + 1) * 256), np.nan)
        done_count = 0

        async with httpx.AsyncClient(timeout=httpx.Timeout(30)) as client:
            async def grab(tx: int, ty: int) -> None:
                nonlocal done_count
                async with sem:
                    if cancel_event and cancel_event.is_set():
                        raise asyncio.CancelledError()
                    url = settings.terrain_url_template.format(z=z, x=tx, y=ty)
                    resp = await client.get(url)
                    resp.raise_for_status()
                    tile = _decode_terrarium(Image.open(io.BytesIO(resp.content)))
                    py = (ty - ty0) * 256
                    px = (tx - tx0) * 256
                    mosaic[py:py + 256, px:px + 256] = tile
                    done_count += 1
                    if on_progress:
                        on_progress(0.1 + 0.8 * done_count / n_tiles,
                                    f"terrain tiles {done_count}/{n_tiles}")

            await asyncio.gather(*(grab(tx, ty)
                                   for ty in range(ty0, ty1 + 1)
                                   for tx in range(tx0, tx1 + 1)))

        if on_progress:
            on_progress(0.95, "resampling terrain grid")
        return _resample(mosaic, z, bbox, projector, settings.grid_max_verts)
    except Exception as exc:  # noqa: BLE001 - 地形抓不到就凑合用平地,别让任务挂掉
        logger.warning("terrain fetch failed, falling back to flat: %s", exc)
        return None


def _resample(mosaic: np.ndarray, z: int, bbox, projector: Projector,
              grid_max: int) -> TerrainGrid:
    """把拼好的瓦片大图缩成局部坐标系下的 N×N 小网格(numpy 整块一起算,快)。"""
    n = 2.0 ** z * 256.0  # 该缩放级别全球总像素数

    # 目标网格尺寸:约 10 米格距,上下限 64~grid_max
    width_m = projector.width_m
    height_m = projector.height_m
    nx = int(min(max(round(width_m / 10.0), 64), grid_max))
    ny = int(min(max(round(height_m / 10.0), 64), grid_max))
    x0, y0 = -width_m / 2, -height_m / 2
    dx = width_m / max(nx - 1, 1)
    dy = height_m / max(ny - 1, 1)

    # 每个网格点:局部米 → 经纬度 → 全球像素位置 → 在大图上平滑地取个高度
    xs = x0 + np.arange(nx) * (width_m / max(nx - 1, 1))
    ys = y0 + np.arange(ny) * (height_m / max(ny - 1, 1))
    grid_x, grid_y = np.meshgrid(xs, ys)                    # 形状 (ny, nx)
    lons, lats = projector.to_lonlat_grid(grid_x, grid_y)
    px = (lons + 180.0) / 360.0 * n
    lat_rad = np.radians(lats)
    py = (1.0 - np.arcsinh(np.tan(lat_rad)) / math.pi) / 2.0 * n
    grid = _bilinear(mosaic, px.ravel(), py.ravel()).reshape(ny, nx)

    # 没抓到的角落可能是 NaN,用有效值的中位数补上;万一整张图都是 NaN
    # (理论上不该发生),就把中位数也兜成 0,免得 NaN 混进后面的 JSON 统计
    if np.isnan(grid).any():
        fill = float(np.nanmedian(grid))
        if math.isnan(fill):
            fill = 0.0
        grid = np.where(np.isnan(grid), fill, grid)
    return TerrainGrid(x0, y0, float(dx), nx, ny, grid, dy=float(dy))


def _bilinear(img: np.ndarray, px: np.ndarray, py: np.ndarray) -> np.ndarray:
    """位置带小数时,就在周围四个像素之间平滑地猜一个值;问到图外就用最边上的像素。

    没抓到的瓦片区域是 NaN,猜出来照样是 NaN,留给调用方统一补。
    """
    h, w = img.shape
    px = np.clip(px, 0, w - 1)
    py = np.clip(py, 0, h - 1)
    x0 = np.floor(px).astype(int)
    y0 = np.floor(py).astype(int)
    x1 = np.minimum(x0 + 1, w - 1)
    y1 = np.minimum(y0 + 1, h - 1)
    tx = px - x0
    ty = py - y0
    top = img[y0, x0] * (1 - tx) + img[y0, x1] * tx
    bottom = img[y1, x0] * (1 - tx) + img[y1, x1] * tx
    return top * (1 - ty) + bottom * ty
