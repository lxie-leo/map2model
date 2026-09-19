"""坐标换算:把经纬度变成"以框选区中心为原点"的平面坐标(单位:米)。

- 用 UTM 投影,X 往东、Y 往北都是真实米数,3D 模型直接拿来用;
- 原点放在框选区正中间:UTM 坐标动辄几十万,数字太大会算不准;
- 顺手带上 ECEF(地心坐标)换算,导出 3D Tiles 时要靠它
  告诉 Cesium 这块模型该摆在地球的哪个位置。
"""

from __future__ import annotations

import math

from pyproj import Transformer


class Projector:
    def __init__(self, bbox: tuple[float, float, float, float]) -> None:
        self.bbox = bbox
        min_lon, min_lat, max_lon, max_lat = bbox
        self.center_lon = (min_lon + max_lon) / 2
        self.center_lat = (min_lat + max_lat) / 2

        # UTM 分带:北半球是 32601~32660(东京 32601,上海 32651),
        # 南半球用的是另一排号 32701~32760,拿错了坐标系就整个对不上地
        zone = int((self.center_lon + 180) / 6) + 1
        zone = min(max(zone, 1), 60)
        self.epsg = (32600 if self.center_lat >= 0 else 32700) + zone

        self._to_utm = Transformer.from_crs("EPSG:4326", f"EPSG:{self.epsg}", always_xy=True)
        self._to_wgs = Transformer.from_crs(f"EPSG:{self.epsg}", "EPSG:4326", always_xy=True)
        # 地心坐标(ECEF),给 3D Tiles 用
        self._to_ecef = Transformer.from_crs("EPSG:4326", "EPSG:4978", always_xy=True)

        # 把框选区中心设为原点 (0,0)
        self.ox, self.oy = self._to_utm.transform(self.center_lon, self.center_lat)
        # 量一下框选区横竖各有多少米宽
        self.width_m = abs(self.to_local(max_lon, self.center_lat)[0] * 2)
        self.height_m = abs(self.to_local(self.center_lon, max_lat)[1] * 2)

    def to_local(self, lon: float, lat: float) -> tuple[float, float]:
        """经纬度 -> 局部平面坐标(米,原点=框选中心)"""
        x, y = self._to_utm.transform(lon, lat)
        return x - self.ox, y - self.oy

    def to_local_many(self, coords: list[tuple[float, float]]) -> list[tuple[float, float]]:
        return [self.to_local(lon, lat) for lon, lat in coords]

    def local_box(self, pad_m: float = 0.0):
        """框选区在本地坐标里的矩形(四周可放宽 pad_m 米),裁面状要素用。

        OSM 的 relation(整条江、整片森林)成员会延伸出框选区几十公里,
        不拿这个矩形裁一刀,模型会往外飞出去老大一块。"""
        from shapely.geometry import box

        hw, hh = self.width_m / 2 + pad_m, self.height_m / 2 + pad_m
        return box(-hw, -hh, hw, hh)

    def to_lonlat(self, x: float, y: float) -> tuple[float, float]:
        """局部平面坐标(米)-> 经纬度"""
        return self._to_wgs.transform(x + self.ox, y + self.oy)

    def to_lonlat_grid(self, xs, ys):
        """批量版:两个 numpy 数组(形状任意)的局部坐标 -> 经纬度"""
        return self._to_wgs.transform(xs + self.ox, ys + self.oy)

    def ecef(self, lon: float, lat: float, h: float = 0.0) -> tuple[float, float, float]:
        """经纬度+高程 -> 地心直角坐标 ECEF(米)"""
        return self._to_ecef.transform(lon, lat, h)

    def enu_to_ecef_matrix(self, h0: float = 0.0) -> list[float]:
        """算 3D Tiles 要的 transform:告诉我们这个局部小世界
        "东、北、上"各对应地球的哪个方向、原点在地球的哪里。

        返回 4x4 矩阵摊平的 16 个数(列主序),直接填进 tileset.json 的 transform 字段。
        h0 取区域平均高度,当作局部坐标的地面基准。
        """
        lon = math.radians(self.center_lon)
        lat = math.radians(self.center_lat)
        # 三个轴的方向:东、北、上(都是单位向量,用地心坐标表示)
        east = (-math.sin(lon), math.cos(lon), 0.0)
        north = (-math.sin(lat) * math.cos(lon), -math.sin(lat) * math.sin(lon), math.cos(lat))
        up = (math.cos(lat) * math.cos(lon), math.cos(lat) * math.sin(lon), math.sin(lat))
        ox, oy, oz = self.ecef(self.center_lon, self.center_lat, h0)
        return [
            east[0], east[1], east[2], 0.0,
            north[0], north[1], north[2], 0.0,
            up[0], up[1], up[2], 0.0,
            ox, oy, oz, 1.0,
        ]
