"""地形重采样这层的测试:以前测试全用假地形把它整个换掉了,
这层真代码反而没人管,出过一次"真地形永远走不通"的大 bug,这里补上。"""

import numpy as np
import pytest

from app.services.projection import Projector
from app.services.terrain import TerrainGrid, _bilinear, _resample


def test_bilinear_shape_and_values():
    """采样点数进多少出多少,值要正好落在周围四个像素的加权平均上。"""
    img = np.arange(16, dtype=float).reshape(4, 4)
    out = _bilinear(img, np.array([1.5, 2.5]), np.array([0.5, 1.5]))
    assert out.shape == (2,)
    # (px=1.5, py=0.5) 周围四像素是 1,2,5,6,正中 → 3.5
    assert out[0] == pytest.approx(3.5)
    # (px=2.5, py=1.5) 周围四像素是 6,7,10,11,正中 → 8.5
    assert out[1] == pytest.approx(8.5)


def test_bilinear_clamps_outside():
    """问到图外,拿最边上的像素顶上。"""
    img = np.arange(16, dtype=float).reshape(4, 4)
    edge = _bilinear(img, np.array([-5.0, 99.0]), np.array([-5.0, 99.0]))
    assert edge[0] == pytest.approx(0.0)   # 左上角
    assert edge[1] == pytest.approx(15.0)  # 右下角


def test_resample_non_square_grid():
    """非正方形框选:行列数不同,行距列距也得各管各的。"""
    bbox = (121.49, 31.23, 121.50, 31.24)  # 约 0.96 x 1.11 km,不是正方形
    proj = Projector(bbox)
    mosaic = np.full((64, 64), 42.0)
    grid = _resample(mosaic, 10, bbox, proj, 512)
    assert grid.z.shape == (grid.ny, grid.nx)
    assert grid.nx != grid.ny
    # 横向总跨度要等于框选宽,纵向等于框选高(以前 y 借 x 的间距,会差出几十米)
    assert abs((grid.nx - 1) * grid.dx - proj.width_m) < 1e-6
    assert abs((grid.ny - 1) * grid.dy - proj.height_m) < 1e-6
    # 源图是常数,采样出来也得是常数
    assert np.allclose(grid.z, 42.0)


def test_sample_uses_dy():
    """长方形网格查高度:y 方向要按 y 自己的间距算,不能借 x 的。"""
    z = np.array([[0.0, 0.0], [10.0, 10.0]])  # 南边 0 米,北边 10 米
    grid = TerrainGrid(0.0, 0.0, dx=100.0, nx=2, ny=2, z=z, dy=200.0)
    assert grid.sample(0.0, 0.0) == pytest.approx(0.0)   # 西南角
    assert grid.sample(0.0, 100.0) == pytest.approx(5.0)  # y 走到一半,高度也一半
    assert grid.sample(50.0, 0.0) == pytest.approx(0.0)   # x 方向两点同高
    # y 方向超出网格,钳在最北一行
    assert grid.sample(0.0, 500.0) == pytest.approx(10.0)


def test_flat_grid_matches_bbox():
    """平地兜底网格:横竖跨度正好是框选的宽和高。"""
    grid = TerrainGrid.flat(500.0, 300.0)
    assert (grid.nx - 1) * grid.dx == pytest.approx(500.0)
    assert (grid.ny - 1) * grid.dy == pytest.approx(300.0)
    assert np.all(grid.z == 0.0)
