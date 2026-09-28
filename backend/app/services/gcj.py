"""GCJ-02 火星坐标纠偏:把中国大陆的加偏坐标换回真实 WGS-84 经纬度。

大陆法规要求公开地图对真实坐标(WGS-84)叠加一层非线性偏移,俗称
"火星坐标"(GCJ-02),偏移量各地不同,从几十米到六百多米(广州一带
最大)。微软 Overture 的
建筑足迹在中国源自加偏的 Bing 影像,拿去和 OSM 这类真实坐标数据对齐前,
得先做逆变换换回 WGS-84。

公式用业内通行的那套拟合常数(同 googollee/eviltransform 等开源实现,
数值完全一致、结果互可校验),只依赖标准库 math。所有函数都是纯函数,
坐标单位一律是"度"。
"""

from __future__ import annotations

import math

# 克拉索夫斯基椭球长半轴(米)和第一偏心率的平方,公式自带的常数
a = 6378245.0
ee = 0.00669342162296594323


def in_china(lon: float, lat: float) -> bool:
    """粗判一个点要不要做 GCJ-02 纠偏:落在大陆框内,且不在港澳台三个框里。

    港澳台的地图不加偏,直接用 WGS-84,所以要从纠偏范围里抠掉。判定就是
    纯矩形框,不查境界数据——香港框的北界画在 22.55°N,深圳湾沿岸 22.5°N
    以南一小条深圳地界会被误判跳过纠偏,粗判可接受,不值得为它引境界数据。
    """
    # 大陆粗框
    if not (72.004 <= lon <= 137.8347 and 0.8293 <= lat <= 55.8271):
        return False
    if 119.95 <= lon <= 122.01 and 21.82 <= lat <= 25.32:  # 台湾
        return False
    if 113.82 <= lon <= 114.51 and 22.13 <= lat <= 22.55:  # 香港
        return False
    if 113.42 <= lon <= 113.62 and 22.06 <= lat <= 22.24:  # 澳门
        return False
    return True


def _transform_lat(x: float, y: float) -> float:
    """偏移量的纬度分量。x/y 是减掉(105°, 35°)基准点后的局部坐标。"""
    ret = -100.0 + 2.0 * x + 3.0 * y + 0.2 * y * y + 0.1 * x * y + 0.2 * math.sqrt(abs(x))
    ret += (20.0 * math.sin(6.0 * x * math.pi) + 20.0 * math.sin(2.0 * x * math.pi)) * 2.0 / 3.0
    ret += (20.0 * math.sin(y * math.pi) + 40.0 * math.sin(y / 3.0 * math.pi)) * 2.0 / 3.0
    ret += (160.0 * math.sin(y / 12.0 * math.pi) + 320.0 * math.sin(y * math.pi / 30.0)) * 2.0 / 3.0
    return ret


def _transform_lon(x: float, y: float) -> float:
    """偏移量的经度分量,参数含义同 _transform_lat。"""
    ret = 300.0 + x + 2.0 * y + 0.1 * x * x + 0.1 * x * y + 0.1 * math.sqrt(abs(x))
    ret += (20.0 * math.sin(6.0 * x * math.pi) + 20.0 * math.sin(2.0 * x * math.pi)) * 2.0 / 3.0
    ret += (20.0 * math.sin(x * math.pi) + 40.0 * math.sin(x / 3.0 * math.pi)) * 2.0 / 3.0
    ret += (150.0 * math.sin(x / 12.0 * math.pi) + 300.0 * math.sin(x / 30.0 * math.pi)) * 2.0 / 3.0
    return ret


def _delta(lon: float, lat: float) -> tuple[float, float]:
    """算 (lon, lat) 处的偏移量(度),返回 (d_lon, d_lat)。

    前两行是拟合公式出的"原始偏移",后一段把它按椭球上每度对应的实际
    弧长折成度数(纬度方向和经度方向的折算系数不一样)。正向加偏和逆向
    纠偏共用这一段,区别只在代入哪个点、最后加还是减。
    """
    dlat = _transform_lat(lon - 105.0, lat - 35.0)
    dlon = _transform_lon(lon - 105.0, lat - 35.0)
    rad_lat = lat / 180.0 * math.pi
    magic = 1 - ee * math.sin(rad_lat) ** 2
    sqrt_magic = math.sqrt(magic)
    dlat = (dlat * 180.0) / ((a * (1 - ee)) / (magic * sqrt_magic) * math.pi)
    dlon = (dlon * 180.0) / (a / sqrt_magic * math.cos(rad_lat) * math.pi)
    return dlon, dlat


def wgs2gcj(lon: float, lat: float) -> tuple[float, float]:
    """WGS-84 → GCJ-02,正向加偏。主要给测试和校验用;境外点原样返回。"""
    if not in_china(lon, lat):
        return lon, lat
    dlon, dlat = _delta(lon, lat)
    return lon + dlon, lat + dlat


def gcj2wgs(lon: float, lat: float) -> tuple[float, float]:
    """GCJ-02 → WGS-84,一阶近似:在 gcj 坐标处算偏移量,直接减掉。

    真正的偏移量该在 wgs 坐标处算,但偏移随位置缓变,拿 gcj 点近似一下,
    结果和真值差一两米,日常够用;要更准走 gcj2wgs_exact。
    """
    if not in_china(lon, lat):
        return lon, lat
    dlon, dlat = _delta(lon, lat)
    return lon - dlon, lat - dlat


def gcj2wgs_exact(
    lon: float, lat: float, tol: float = 1e-7, max_iter: int = 10
) -> tuple[float, float]:
    """GCJ-02 → WGS-84,迭代收敛版,误差能压到 1e-7 度(约 1 厘米)以内。

    不动点迭代:拿一阶近似当起点,每轮把 guess 正向加偏一遍,和目标比
    出差值,再把 guess 往回修(偏移量始终用 guess 当前位置重算,这正是
    迭代比一阶准的原因)。偏移随位置缓变,所以两三轮就收敛到位。
    """
    wlon, wlat = gcj2wgs(lon, lat)
    for _ in range(max_iter):
        dlon, dlat = wgs2gcj(wlon, wlat)
        dlon -= lon
        dlat -= lat
        if abs(dlon) < tol and abs(dlat) < tol:
            break
        wlon -= dlon
        wlat -= dlat
    return wlon, wlat


def rectify_features(buildings: list) -> int:
    """把一批建筑(原地修改)从 GCJ-02 整体平移回 WGS-84,返回实际纠偏的栋数。

    楼的尺度不过几十上百米,而偏移量在几公里尺度上才缓变,所以每栋只在
    外环的中心点算一次逆偏移,全部顶点统一平移,精度足够(残差 <1 厘米)。
    中心落在境外(港澳台/国外)的楼 gcj2wgs 会原样返回,自然跳过。

    入参是 osm_parse.BuildingFeature 列表(duck typing,不 import 保持本模块零依赖)。
    """
    fixed = 0
    for b in buildings:
        xs = [p[0] for p in b.outer]
        ys = [p[1] for p in b.outer]
        cx = (min(xs) + max(xs)) / 2
        cy = (min(ys) + max(ys)) / 2
        wlon, wlat = gcj2wgs_exact(cx, cy)
        dx, dy = wlon - cx, wlat - cy
        if dx == 0.0 and dy == 0.0:
            continue
        b.outer = [(x + dx, y + dy) for x, y in b.outer]
        b.inners = [[(x + dx, y + dy) for x, y in ring] for ring in b.inners]
        fixed += 1
    return fixed
