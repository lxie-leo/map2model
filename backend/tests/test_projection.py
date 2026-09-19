"""坐标换算:UTM 分带对不对、经纬度和本地坐标来回换、ENU→ECEF 矩阵检查。"""

import numpy as np

from app.services.projection import Projector
from tests.conftest import BBOX


def test_utm_zone():
    p = Projector(BBOX)  # 上海 121.5°E → 51 区
    assert p.epsg == 32651


def test_southern_hemisphere_epsg():
    """南半球得用 327xx 那排编号(悉尼 ~151°E → 56 区),用北带的会把坐标全带偏。"""
    p = Projector((151.20, -33.87, 151.23, -33.85))  # 悉尼
    assert p.epsg == 32756
    p2 = Projector((151.20, 33.85, 151.23, 33.87))   # 同经度北半球对照
    assert p2.epsg == 32656


def test_round_trip():
    p = Projector(BBOX)
    for lon, lat in [(121.4900, 31.2340), (121.4970, 31.2385), (121.4935, 31.2362)]:
        x, y = p.to_local(lon, lat)
        lon2, lat2 = p.to_lonlat(x, y)
        assert abs(lon2 - lon) < 1e-7
        assert abs(lat2 - lat) < 1e-7


def test_local_extent():
    p = Projector(BBOX)
    # 框选区边角应该落在 ±半宽/半高 附近(米)
    x, _ = p.to_local(BBOX[0], p.center_lat)
    assert abs(abs(x) - p.width_m / 2) < 1.0
    _, y = p.to_local(p.center_lon, BBOX[3])
    assert abs(abs(y) - p.height_m / 2) < 1.0


def test_enu_matrix():
    p = Projector(BBOX)
    m = np.asarray(p.enu_to_ecef_matrix(10.0)).reshape(4, 4).T  # 列主序 → 行主序
    # 旋转部分应该是三个互相垂直的单位向量
    rot = m[:3, :3]
    assert np.allclose(rot @ rot.T, np.eye(3), atol=1e-9)
    assert np.isclose(np.linalg.det(rot), 1.0, atol=1e-9)
    # 平移部分 = 框选中心的地心坐标
    ox, oy, oz = p.ecef(p.center_lon, p.center_lat, 10.0)
    assert np.allclose(m[:3, 3], [ox, oy, oz], atol=1e-6)
