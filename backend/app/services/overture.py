"""从 Overture Maps 开放数据拉取框选区域的建筑足迹。

Overture 建筑层是微软拿 Bing 影像机器学习提的足迹,中国大陆覆盖远好于 OSM
(代价是高度基本没有、中国区坐标疑似带 GCJ-02 偏移,后者在解析后统一纠,见 gcj.py)。

数据放 AWS S3 公开桶,免 key 匿名可读,但文件不按地区切:全球 500 多个 parquet
混在一起,只做过空间聚类排序。所以取数分两步走:

1. 建行组索引(每个 release 只做一次):并行扫全部文件的 footer,
   把每个行组的包围盒记下来存成本地索引。这一步要几百上千个 HTTP 请求,
   慢网下十几分钟,但建完一劳永逸;
2. 查索引命中哪些行组,只把这些组的相关列拉回来,按每行的 bbox 精筛,
   转成 BuildingFeature 序列化缓存。之后同一块地重复框选直接读盘。

整个活儿是重 IO,在管线里由调用方丢进线程池跑;这里只用普通同步代码。
"""

from __future__ import annotations

import gzip
import json
import logging
import os
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.fs as pafs
import pyarrow.parquet as pq
import shapely

from app.config import Settings
from app.core.errors import FetchError
from app.services.osm_parse import BuildingFeature
from app.utils.caching import sha256_hex, write_json_atomic

logger = logging.getLogger("app.overture")

OVERTURE_ATTRIBUTION = "Buildings © Overture Maps Foundation (CDLA-Permissive 2.0)"

# 只读需要的列:几何、行级 bbox、名称、类别、高度/层数(都很稀疏但能捞一点是一点)
_COLS = ["bbox", "geometry", "names.primary", "class", "subtype", "height", "num_floors"]

# 建索引时并发的文件数(pyarrow 读 parquet 会释放 GIL,线程池吃得到多核/多连接)
_INDEX_WORKERS = 16


@dataclass
class _RowGroupBox:
    """一个行组的包围盒(经纬度),用 footer 统计算出来的粗框。"""

    file_i: int
    group_i: int
    x0: float
    y0: float
    x1: float
    y1: float


def _s3fs(settings: Settings) -> pafs.S3FileSystem:
    return pafs.S3FileSystem(
        anonymous=True,
        region=settings.overture_s3_region,
        request_timeout=settings.overture_timeout,
    )


def _prefix(settings: Settings) -> str:
    return f"{settings.overture_s3_bucket}/release/{settings.overture_release}/theme=buildings/type=building"


def _index_path(settings: Settings) -> Path:
    return settings.overture_cache_dir / f"rg-index-{settings.overture_release}.json.gz"


def _group_bbox(md: pq.FileMetaData, group_i: int, col_idx: dict[str, int]) -> tuple[float, float, float, float] | None:
    """从 footer 统计里抠出行组包围盒;拿不到统计返回 None(调用方按'必命中'兜底)。"""
    box: dict[str, tuple[float, float]] = {}
    for sub in ("xmin", "xmax", "ymin", "ymax"):
        ci = col_idx.get(f"bbox.{sub}")
        if ci is None:
            return None
        st = md.row_group(group_i).column(ci).statistics
        if not st or not st.has_min_max:
            return None
        box[sub] = (float(st.min), float(st.max))
    # 行级 bbox 理论上 xmin<xmax,但退化点(塔状建筑)两者相等,
    # 合并两个方向的统计当组级包围盒最稳
    return (
        min(box["xmin"][0], box["xmax"][0]),
        min(box["ymin"][0], box["ymax"][0]),
        max(box["xmin"][1], box["xmax"][1]),
        max(box["ymin"][0], box["ymax"][1]),
    )


def _build_index(
    fs: pafs.S3FileSystem,
    files: list[str],
    settings: Settings,
    on_progress,
    cancel_event,
) -> list[_RowGroupBox]:
    """并行扫所有文件 footer,攒出行组索引。半路取消/失败就把已扫的扔掉,下次重来。"""
    boxes: list[_RowGroupBox] = []
    done = 0
    t0 = time.monotonic()

    def scan_one(file_i: int) -> list[_RowGroupBox] | None:
        if cancel_event is not None and cancel_event.is_set():
            return None
        try:
            with fs.open_input_file(files[file_i]) as fh:
                md = pq.ParquetFile(fh).metadata
                col_idx = {md.schema.column(i).path: i for i in range(md.num_columns)}
                out: list[_RowGroupBox] = []
                for g in range(md.num_row_groups):
                    bb = _group_bbox(md, g, col_idx)
                    if bb is None:
                        # 没统计就只能当它全覆盖,保证不漏数据(代价是这一组每次都会被拉)
                        out.append(_RowGroupBox(file_i, g, -180.0, -90.0, 180.0, 90.0))
                    else:
                        out.append(_RowGroupBox(file_i, g, *bb))
                return out
        except Exception:
            # 个别文件网络抖了不能把整次索引弄废:记一个"全覆盖"占位(group_i=-1),
            # 以后每次查询都会试读它整个文件(读取侧自带重试+跳过),数据不漏
            logger.exception("scan footer failed, marking file as full-coverage: %s", files[file_i])
            return [_RowGroupBox(file_i, -1, -180.0, -90.0, 180.0, 90.0)]

    with ThreadPoolExecutor(_INDEX_WORKERS) as pool:
        futures = [pool.submit(scan_one, i) for i in range(len(files))]
        try:
            for fut in as_completed(futures):
                result = fut.result()
                if result:
                    boxes.extend(result)
                done += 1
                if done % 32 == 0 or done == len(files):
                    if on_progress:
                        frac = 0.05 + 0.7 * done / len(files)
                        on_progress(frac, f"indexing footers {done}/{len(files)}")
                    logger.debug("index progress %d/%d %.1fs", done, len(files), time.monotonic() - t0)
        except Exception:
            for f in futures:
                f.cancel()
            raise
    if cancel_event is not None and cancel_event.is_set():
        raise FetchError("cancelled")
    return boxes


def _load_or_build_index(
    fs: pafs.S3FileSystem, settings: Settings, on_progress, cancel_event
) -> tuple[list[str], list[_RowGroupBox]]:
    """行组索引:本地有就读,没有就建一遍存下来(原子写,防半截文件)。"""
    files = [
        f.path for f in fs.get_file_info(pafs.FileSelector(_prefix(settings), recursive=False))
        if f.type == pafs.FileType.File
    ]
    if not files:
        raise FetchError(f"no overture files under {_prefix(settings)} (release 不存在或桶改版了?)")

    idx_path = _index_path(settings)
    if idx_path.exists():
        with gzip.open(idx_path, "rt", encoding="utf-8") as fh:
            blob = json.load(fh)
        if blob.get("file_count") == len(files):
            boxes = [
                _RowGroupBox(*b) for b in blob["boxes"]
            ]
            return files, boxes
        # 文件数对不上说明数据改版了,重建
        logger.warning("overture index stale (%s files on record, %s now), rebuilding", blob.get("file_count"), len(files))

    boxes = _build_index(fs, files, settings, on_progress, cancel_event)
    # 临时文件名要随机:两个任务同时第一次建索引,固定名会互相覆盖再互相顶掉
    idx_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(idx_path.parent), suffix=".tmp")
    os.close(fd)
    try:
        with gzip.open(tmp, "wt", encoding="utf-8") as fh:
            json.dump({"file_count": len(files), "boxes": [[b.file_i, b.group_i, b.x0, b.y0, b.x1, b.y1] for b in boxes]}, fh)
        Path(tmp).replace(idx_path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return files, boxes


def _read_hit_groups(
    fs: pafs.S3FileSystem,
    files: list[str],
    boxes: list[_RowGroupBox],
    bbox: tuple[float, float, float, float],
    settings: Settings,
    on_progress,
    cancel_event,
) -> pa.Table | None:
    """把与框选相交的行组拉回来,按每行的 bbox 精筛,拼成一张表。"""
    w, s, e, n = bbox
    hits = [b for b in boxes if b.x1 >= w and b.x0 <= e and b.y1 >= s and b.y0 <= n]
    by_file: dict[int, list[int]] = {}
    for b in hits:
        by_file.setdefault(b.file_i, []).append(b.group_i)

    tables: list[pa.Table] = []
    total = len(by_file)
    done = 0
    read_errors: list[str] = []

    def read_file_once(file_i: int) -> pa.Table | None:
        with fs.open_input_file(files[file_i]) as fh:
            pf = pq.ParquetFile(fh)
            groups = by_file[file_i]
            if -1 in groups:
                return pf.read(columns=_COLS)  # 索引期失败的文件,整文件都读
            parts = [pf.read_row_group(g, columns=_COLS) for g in sorted(groups)]
        return pa.concat_tables(parts) if len(parts) > 1 else parts[0]

    def read_file(file_i: int) -> pa.Table | None:
        """读一个文件命中的行组,网络抖动了就歇口气再试两回。"""
        if cancel_event is not None and cancel_event.is_set():
            return None
        for attempt in range(3):
            try:
                return read_file_once(file_i)
            except Exception:
                if attempt == 2 or (cancel_event is not None and cancel_event.is_set()):
                    read_errors.append(files[file_i])
                    logger.exception("read overture file failed: %s", files[file_i])
                    return None  # 单文件失败不拖垮整批,最后统一报
                time.sleep(2.0 * (attempt + 1))

    with ThreadPoolExecutor(_INDEX_WORKERS) as pool:
        futures = [pool.submit(read_file, fi) for fi in by_file]
        for fut in as_completed(futures):
            t = fut.result()
            if t is not None and t.num_rows:
                tables.append(t)
            done += 1
            if on_progress and (done % 8 == 0 or done == total):
                on_progress(0.75 + 0.2 * done / max(total, 1), f"downloading buildings {done}/{total}")
    if cancel_event is not None and cancel_event.is_set():
        raise FetchError("cancelled")
    if not tables:
        if read_errors:
            # 命中的文件一个都没读下来(多半是网络),交给上层走降级逻辑
            raise FetchError(f"overture: all {len(read_errors)} hit files unreadable")
        return None  # 一行都没命中
    table = pa.concat_tables(tables)
    if read_errors:
        logger.warning(
            "overture: %d/%d files unreadable (network?), results may be incomplete: %s",
            len(read_errors), total, read_errors[:3],
        )

    # 行级精筛:几何的外接框和框选相交才留
    # (ChunkedArray 不支持和标量直接比大小,pc 的比较函数本身就收得了标量)
    bb = table.column("bbox")
    mask = (
        pc.and_(
            pc.and_(pc.less_equal(pc.struct_field(bb, "xmin"), e),
                    pc.greater_equal(pc.struct_field(bb, "xmax"), w)),
            pc.and_(pc.less_equal(pc.struct_field(bb, "ymin"), n),
                    pc.greater_equal(pc.struct_field(bb, "ymax"), s)),
        )
    )
    return table.filter(mask)


def _names_primary(table: pa.Table) -> list:
    """把 names.primary 列拍平成字符串列表。

    坑:按 "names.primary" 做列投影时,不同 pyarrow 版本/读法吐回来的列名不一样
    (有的叫 "names.primary",有的只给半个 struct、叫 "names"),这里几种都认。
    """
    for col_name in ("names.primary", "names", "primary"):
        if col_name in table.column_names:
            col = table.column(col_name)
            if pa.types.is_struct(col.type):
                return pc.struct_field(col, "primary").to_pylist()
            return col.to_pylist()
    raise KeyError("names.primary 列不见了,_COLS 是不是改了?")


def _to_building_features(table: pa.Table) -> list[BuildingFeature]:
    """箭头表 → BuildingFeature 列表。MultiPolygon 拆成多栋,属性各自继承。"""
    out: list[BuildingFeature] = []
    n = table.num_rows
    if not n:
        return out
    names = _names_primary(table)
    classes = table.column("class").to_pylist()
    heights = table.column("height").to_pylist()
    floors = table.column("num_floors").to_pylist()
    wkb_list = table.column("geometry").to_pylist()
    for i in range(n):
        wkb = wkb_list[i]
        if not wkb:
            continue
        geom = shapely.from_wkb(wkb)
        polys = list(geom.geoms) if geom.geom_type == "MultiPolygon" else [geom]
        for poly in polys:
            if poly.geom_type != "Polygon" or poly.is_empty:
                continue
            out.append(BuildingFeature(
                outer=[(x, y) for x, y in poly.exterior.coords],
                inners=[[ (x, y) for x, y in ring.coords] for ring in poly.interiors],
                height=float(heights[i]) if heights[i] is not None else None,
                levels=float(floors[i]) if floors[i] is not None else None,
                name=names[i] or None,
                cls=classes[i] or None,
            ))
    return out


def _cache_key(bbox: tuple[float, float, float, float], settings: Settings) -> str:
    w, s, e, n = (round(v, 6) for v in bbox)
    return sha256_hex(f"overture|{settings.overture_release}|{w},{s},{e},{n}")


def fetch_overture(
    bbox: tuple[float, float, float, float],
    *,
    settings: Settings,
    on_progress=None,
    cancel_event=None,
) -> Path:
    """抓框选区域的 Overture 建筑,返回序列化缓存文件路径(内容见 parse_overture)。"""
    out_path = settings.overture_cache_dir / f"{_cache_key(bbox, settings)}.json"
    if out_path.exists():
        if on_progress:
            on_progress(1.0, "overture cache hit")
        return out_path

    fs = _s3fs(settings)
    if on_progress:
        on_progress(0.02, "listing overture files")
    files, boxes = _load_or_build_index(fs, settings, on_progress, cancel_event)
    if on_progress:
        on_progress(0.75, f"index ready: {len(boxes)} row groups")

    table = _read_hit_groups(fs, files, boxes, bbox, settings, on_progress, cancel_event)
    feats = _to_building_features(table) if table is not None else []
    if len(feats) > settings.overture_max_features:
        # 超上限截断,避免框太密把内存/导出撑爆(和 max_buildings 同一个思路)
        logger.warning("overture features truncated: %d -> %d", len(feats), settings.overture_max_features)
        feats = feats[: settings.overture_max_features]

    if on_progress:
        on_progress(0.95, f"got {len(feats)} buildings")
    write_json_atomic(out_path, {
        "release": settings.overture_release,
        "bbox": list(bbox),
        "count": len(feats),
        "features": [
            {
                "outer": f.outer, "inners": f.inners,
                "height": f.height, "levels": f.levels,
                "name": f.name, "cls": f.cls,
            }
            for f in feats
        ],
    })
    if on_progress:
        on_progress(1.0, f"overture done: {len(feats)} buildings")
    return out_path


def parse_overture(path: Path) -> list[BuildingFeature]:
    """把 fetch_overture 的缓存读回 BuildingFeature 列表。"""
    blob = json.loads(path.read_text(encoding="utf-8"))
    return [
        BuildingFeature(
            outer=[tuple(p) for p in f["outer"]],
            inners=[[tuple(p) for p in ring] for ring in f.get("inners", [])],
            height=f.get("height"), levels=f.get("levels"),
            name=f.get("name"), cls=f.get("cls"),
        )
        for f in blob["features"]
    ]
