"""线状要素(道路/铁路/河流):经纬度换成本地坐标,并裁到框选区附近。"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from shapely.geometry import LineString

from app.services.osm_parse import LineFeature
from app.services.projection import Projector


@dataclass
class LineLocal:
    """一条折线(以框选中心为原点,单位米)+ 宽度等属性"""

    pts: np.ndarray            # (n, 2)
    kind: str                  # 类别(residential / rail / river ...)
    width: float               # 这条线要铺多宽(米)
    bridge: bool = False
    name: str | None = None


def _dedup(pts: np.ndarray) -> np.ndarray:
    # 去掉相邻重复点(零长度的段会让后面的铺路计算除零)
    keep = np.ones(len(pts), dtype=bool)
    keep[1:] = np.linalg.norm(np.diff(pts, axis=0), axis=1) > 1e-6
    return pts[keep]


def to_local_lines(feats: list[LineFeature], projector: Projector) -> list[LineLocal]:
    # Overpass 对 way 的规矩是"有节点在框内就给整条":一条几百米的路、
    # 几十公里的河,只要蹭到框,全线都会回来。裁到框附近(放宽 50 米),
    # 不然模型会往外飞出去老大一块
    clip = projector.local_box(pad_m=50.0)
    out: list[LineLocal] = []
    for lf in feats:
        pts = _dedup(np.asarray(projector.to_local_many(lf.coords), dtype=np.float64))
        if len(pts) < 2:
            continue
        cut = LineString(pts).intersection(clip)
        if cut.is_empty:
            continue
        # 一条线穿出框再进来,会被切成好几段;裁剪的交点上偶尔混进孤立
        # 的点,只留真正的线段
        segs = cut.geoms if hasattr(cut, "geoms") else [cut]
        for seg in segs:
            if seg.geom_type != "LineString" or seg.is_empty:
                continue
            seg_pts = _dedup(np.asarray(seg.coords, dtype=np.float64))
            if len(seg_pts) < 2:
                continue
            out.append(
                LineLocal(
                    pts=seg_pts, kind=lf.kind, width=lf.width or 3.0,
                    bridge=lf.bridge, name=lf.name,
                )
            )
    return out
