"""GCJ-02 纠偏:往返准不准、边界认不认得、境外动不动。"""

import math

from app.services.gcj import gcj2wgs, gcj2wgs_exact, in_china, wgs2gcj

# 1 度纬度约 111 公里,拿度数换算米数用
_M_PER_DEG = 111_000.0

# 三个城市的 WGS-84 坐标,纬度从南到北拉开,顺带覆盖不同的偏移方向
_CITIES = [
    ("上海人民广场", 121.4633, 31.2323),
    ("北京天安门", 116.3975, 39.9087),
    ("广州", 113.2644, 23.1291),
]


def _dist_m(lon1, lat1, lon2, lat2):
    """两个点的平面距离(米)。偏移量就几百米,小范围内当平面算足够准。"""
    dx = (lon2 - lon1) * math.cos(math.radians((lat1 + lat2) / 2))
    dy = lat2 - lat1
    return math.hypot(dx, dy) * _M_PER_DEG


def test_roundtrip_and_offset_magnitude():
    for name, lon, lat in _CITIES:
        glon, glat = wgs2gcj(lon, lat)
        wlon, wlat = gcj2wgs_exact(glon, glat)
        # 加偏再纠偏,应该回到原地,误差 1e-6 度(约 0.1 米)以内
        assert abs(wlon - lon) < 1e-6, name
        assert abs(wlat - lat) < 1e-6, name
        # 加偏量得在 100~700 米量级:接近 0 说明压根没加上,超出去说明公式不对
        # (上限不是 600:珠三角是全国偏移最大的区域,广州实测约 620 米)
        offset_m = _dist_m(lon, lat, glon, glat)
        assert 100 <= offset_m <= 700, (name, offset_m)


def test_exact_beats_first_order():
    for name, lon, lat in _CITIES:
        glon, glat = wgs2gcj(lon, lat)
        # 同一个 gcj 点,迭代版往回凑得不该比一阶版差
        exact_err = _dist_m(*gcj2wgs_exact(glon, glat), lon, lat)
        first_err = _dist_m(*gcj2wgs(glon, glat), lon, lat)
        assert exact_err <= first_err, name


def test_in_china():
    # 大陆框内的边角:最北漠河、最南三亚、最西喀什,加哈尔滨、上海
    for lon, lat in [(122.5, 53.5), (109.5, 18.2), (75.99, 39.47), (126.6, 45.8), (121.4633, 31.2323)]:
        assert in_china(lon, lat) is True
    # 港澳台在框内但不纠偏
    for lon, lat in [(121.56, 25.03), (114.17, 22.32), (113.55, 22.20)]:
        assert in_china(lon, lat) is False
    # 境外:东京、纽约、伦敦
    for lon, lat in [(139.7, 35.7), (-74.0, 40.7), (0.12, 51.5)]:
        assert in_china(lon, lat) is False


def test_outside_china_identity():
    # 境外不加偏,正反变换都该原样吐回去
    for lon, lat in [(139.7, 35.7), (-74.0, 40.7), (0.12, 51.5)]:
        assert wgs2gcj(lon, lat) == (lon, lat)
        assert gcj2wgs(lon, lat) == (lon, lat)
        assert gcj2wgs_exact(lon, lat) == (lon, lat)


def test_exact_converges():
    # 收敛到位的标志:拿结果再正向加偏一遍,和目标 gcj 点对得上
    # (残差小于默认 tol,说明默认 10 轮内就收敛了,不用数轮数)
    for name, lon, lat in _CITIES:
        glon, glat = wgs2gcj(lon, lat)
        wlon, wlat = gcj2wgs_exact(glon, glat)
        clon, clat = wgs2gcj(wlon, wlat)
        assert abs(clon - glon) < 1e-7, name
        assert abs(clat - glat) < 1e-7, name
