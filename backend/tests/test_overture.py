"""Overture 取数:全程离线——本地 parquet 冒充 S3 桶,不碰外网。

集成测试里 fetch_overture 整个被 fake 替身换掉了,行组索引/footer 统计裁剪、
行级 bbox 精筛、WKB→BuildingFeature 转换这些真实逻辑只有这里覆盖得到。
"""

import json
from pathlib import Path

import pyarrow as pa
import pyarrow.fs as pafs
import pyarrow.parquet as pq
import pytest
import shapely
from shapely.geometry import MultiPolygon, Polygon

# 仿真实 Overture 建筑层的列结构:bbox 是 struct,geometry 是 WKB 二进制,
# names 只放 primary 一个字段(读 "names.primary" 够用),高度/层数可空
_SCHEMA = pa.schema([
    ("bbox", pa.struct([
        ("xmin", pa.float64()), ("ymin", pa.float64()),
        ("xmax", pa.float64()), ("ymax", pa.float64()),
    ])),
    ("geometry", pa.binary()),
    ("names", pa.struct([("primary", pa.string())])),
    ("class", pa.string()),
    ("subtype", pa.string()),
    ("height", pa.float64()),
    ("num_floors", pa.float64()),
])

# 两个行组一个在上海小片、一个在东京,隔得足够远,行组裁剪必须整组排除对方
SH_BBOX = (121.4900, 31.2340, 121.4970, 31.2385)
TK_BBOX = (139.7000, 35.7000, 139.7100, 35.7100)


def _rect(x, y, s):
    return Polygon([(x, y), (x + s, y), (x + s, y + s), (x, y + s)])


def _row(poly, *, name=None, cls=None, subtype=None, height=None, floors=None):
    bounds = poly.bounds
    return {
        "bbox": {"xmin": bounds[0], "ymin": bounds[1], "xmax": bounds[2], "ymax": bounds[3]},
        "geometry": shapely.to_wkb(poly),
        "names": {"primary": name},
        "class": cls, "subtype": subtype,
        "height": height, "num_floors": floors,
    }


def _shanghai_rows():
    return [
        _row(_rect(121.4905, 31.2345, 0.0005), name="上海测试楼",
             cls="commercial", subtype="retail", height=45.5),
        _row(_rect(121.4930, 31.2355, 0.0004), cls="residential", floors=6),
        # MultiPolygon:一栋楼两片,应该拆成两栋、属性各自继承
        _row(MultiPolygon([_rect(121.4950, 31.2350, 0.0004), _rect(121.4960, 31.2360, 0.0003)]),
             height=12.3),
    ]


def _tokyo_rows():
    donut = Polygon(
        _rect(139.7020, 35.7010, 0.0006).exterior.coords,
        [_rect(139.7023, 35.7013, 0.0002).exterior.coords],
    )
    return [
        _row(_rect(139.7005, 35.7005, 0.0006), name="東京テスト棟", cls="residential", height=30.0),
        _row(donut, floors=3),
    ]


def _write_fake_release(bucket: Path) -> Path:
    """写一个两行组的 parquet 冒充 Overture release。一次 write_table 一个行组,
    两组楼必须分开写,footer 统计才会分开、行组裁剪才有东西可裁。"""
    path = bucket / "part-0000.parquet"
    with pq.ParquetWriter(path, _SCHEMA) as w:
        w.write_table(pa.Table.from_pylist(_shanghai_rows(), schema=_SCHEMA))
        w.write_table(pa.Table.from_pylist(_tokyo_rows(), schema=_SCHEMA))
    return path


@pytest.fixture
def overture_env(tmp_path, monkeypatch):
    """本地 parquet 冒充 S3 + 数据目录指到 tmp,fetch_overture 全程离线可跑。"""
    monkeypatch.setenv("M2M_DATA_DIR", str(tmp_path / "data"))
    from app.config import get_settings

    get_settings.cache_clear()
    settings = get_settings()

    bucket = tmp_path / "overture"
    bucket.mkdir()
    _write_fake_release(bucket)

    import app.services.overture as ov

    monkeypatch.setattr(ov, "_s3fs", lambda s: pafs.LocalFileSystem())
    # LocalFileSystem 的 selector 路径不带桶名、用正斜杠(Windows 下 as_posix 防反斜杠)
    monkeypatch.setattr(ov, "_prefix", lambda s: bucket.as_posix())

    yield ov, settings
    get_settings.cache_clear()


def test_fake_parquet_has_row_group_stats(tmp_path):
    """footer 统计是行组索引的地基:仿造的 parquet 得真带 bbox 的 min/max 统计,
    不然索引建出来全是"必命中"兜底,裁剪逻辑等于没测。"""
    bucket = tmp_path / "overture"
    bucket.mkdir()
    md = pq.ParquetFile(_write_fake_release(bucket)).metadata
    assert md.num_row_groups == 2
    col_idx = {md.schema.column(i).path: i for i in range(md.num_columns)}
    for g in range(md.num_row_groups):
        for sub in ("xmin", "ymin", "xmax", "ymax"):
            st = md.row_group(g).column(col_idx[f"bbox.{sub}"]).statistics
            assert st is not None and st.has_min_max


def test_fetch_shanghai(overture_env):
    ov, settings = overture_env
    feats = ov.parse_overture(ov.fetch_overture(SH_BBOX, settings=settings))
    # 组1 两栋普通楼 + MultiPolygon 拆出的两片 = 4;东京组整个被行组裁剪挡掉
    assert len(feats) == 4

    named = next(f for f in feats if f.name)
    assert named.name == "上海测试楼"
    assert named.cls == "commercial"
    assert named.height == 45.5
    assert named.levels is None
    assert len(named.outer) == 5                 # 4 个角 + 闭合点
    assert named.outer[0] == pytest.approx((121.4905, 31.2345))
    assert named.inners == []

    by_levels = [f for f in feats if f.levels == 6.0]
    assert len(by_levels) == 1                   # 只有层数那栋
    assert by_levels[0].cls == "residential"
    assert by_levels[0].height is None

    parts = [f for f in feats if f.height == 12.3]
    assert len(parts) == 2                       # MultiPolygon 拆成两栋

    # 行组索引建完落了盘,下次查询不用再扫 footer
    assert ov._index_path(settings).exists()


def test_fetch_tokyo(overture_env):
    ov, settings = overture_env
    feats = ov.parse_overture(ov.fetch_overture(TK_BBOX, settings=settings))
    assert len(feats) == 2                       # 上海组整个被挡掉

    tower = next(f for f in feats if f.name)
    assert tower.name == "東京テスト棟"
    assert tower.cls == "residential"
    assert tower.height == 30.0

    donut = next(f for f in feats if f.levels == 3.0)
    assert donut.height is None
    assert len(donut.inners) == 1                # 带内院的楼,内环读得回来
    assert len(donut.inners[0]) == 5


def test_fetch_nothing(overture_env):
    """谁都不中的框选(大西洋上):不炸,写 count=0 的缓存,再调直接走缓存。"""
    ov, settings = overture_env
    bbox = (0.0, 0.0, 0.1, 0.1)
    p = ov.fetch_overture(bbox, settings=settings)
    assert p.exists()
    blob = json.loads(p.read_text(encoding="utf-8"))
    assert blob["count"] == 0
    assert ov.parse_overture(p) == []
    assert ov.fetch_overture(bbox, settings=settings) == p


def test_cache_hit_returns_same_path(overture_env, monkeypatch):
    """同一 bbox 二次调用:直接吃磁盘缓存,连"远端"都不该碰一下。"""
    ov, settings = overture_env
    p1 = ov.fetch_overture(SH_BBOX, settings=settings)

    def _boom(s):
        raise AssertionError("缓存命中时不该再碰远端")

    monkeypatch.setattr(ov, "_s3fs", _boom)
    p2 = ov.fetch_overture(SH_BBOX, settings=settings)
    assert p2 == p1
    assert len(ov.parse_overture(p2)) == 4
