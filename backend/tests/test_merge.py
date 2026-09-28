"""OSM × Overture 建筑合并判重:IoU、包含率、退化楼、空列表、内环保留。

单位直接用小数度:0.001 度约当 100 米,不必换算精确。
"""

from app.services.building_merge import merge_buildings
from app.services.osm_parse import BuildingFeature


def _rect(lon0, lat0, size, dx=0.0, dy=0.0):
    """画一个闭合方块环,dx/dy 是整体平移量(度)。"""
    pts = [
        (lon0 + dx, lat0 + dy),
        (lon0 + size + dx, lat0 + dy),
        (lon0 + size + dx, lat0 + size + dy),
        (lon0 + dx, lat0 + size + dy),
    ]
    return pts + [pts[0]]


def _b(lon0, lat0, size, dx=0.0, dy=0.0, **kw):
    return BuildingFeature(outer=_rect(lon0, lat0, size, dx, dy), **kw)


def test_iou_dedup_keeps_osm_version():
    """同一栋楼微扰:100x100 的楼整体挪 3 米,IoU ≈ 0.89 过线,判重留 OSM 版。"""
    osm_b = _b(121.49, 31.23, 0.001)
    ov_b = _b(121.49, 31.23, 0.001, dx=0.00003, dy=0.00003)
    merged, dropped = merge_buildings([osm_b], [ov_b])
    assert dropped == 1
    assert len(merged) == 1
    assert merged[0] is osm_b


def test_far_apart_both_kept_osm_first():
    """两栋相距一公里开外的楼互不相干:都保留,顺序 OSM 在前。"""
    osm_b = _b(121.49, 31.23, 0.001)
    ov_b = _b(121.50, 31.24, 0.001)
    merged, dropped = merge_buildings([osm_b], [ov_b])
    assert dropped == 0
    assert len(merged) == 2
    assert merged[0] is osm_b
    assert merged[1] is ov_b


def test_containment_drops_overture():
    """一边描大了一圈的同一栋楼:交集占小面积 100% 判重。

    尺寸故意取 100 vs 140:IoU 只有 0.51,过不了 0.55 的线,
    这条用例专测包含率(_MERGE_CONTAIN)分支。
    """
    osm_b = _b(121.49, 31.23, 0.001)
    ov_b = _b(121.49, 31.23, 0.0014)
    merged, dropped = merge_buildings([osm_b], [ov_b])
    assert dropped == 1
    assert len(merged) == 1
    assert merged[0] is osm_b


def test_empty_inputs():
    ov_b = _b(121.49, 31.23, 0.001)
    merged, dropped = merge_buildings([], [ov_b])
    assert dropped == 0
    assert merged == [ov_b]

    osm_b = _b(121.49, 31.23, 0.001)
    merged, dropped = merge_buildings([osm_b], [])
    assert dropped == 0
    assert merged == [osm_b]

    assert merge_buildings([], []) == ([], 0)


def test_degenerate_buildings():
    """退化楼(外环只有 3 个点,构不成面):OSM 侧的保留,Overture 侧的直接丢,
    且两种都不参与判重、不计入 dropped。"""
    good_osm = _b(121.49, 31.23, 0.001)
    bad_osm = BuildingFeature(outer=[(121.49, 31.24), (121.4901, 31.24), (121.4901, 31.2401)])
    good_ov = _b(121.492, 31.23, 0.001)
    bad_ov = BuildingFeature(outer=[(121.49, 31.25), (121.4901, 31.25), (121.4901, 31.2501)])

    merged, dropped = merge_buildings([good_osm, bad_osm], [good_ov, bad_ov])
    assert dropped == 0
    # 顺序:能判重的 OSM 在前 → 保留的 Overture 补后 → OSM 侧退化楼垫底
    assert merged == [good_osm, good_ov, bad_osm]


def test_inner_rings_preserved():
    """带内院(天井)的楼合并后内环原样保留,两边都是。"""
    donut_osm = BuildingFeature(
        outer=_rect(121.49, 31.23, 0.001),
        inners=[_rect(121.4903, 31.2303, 0.0004)],
    )
    donut_ov = BuildingFeature(
        outer=_rect(121.495, 31.235, 0.001),
        inners=[_rect(121.4953, 31.2353, 0.0004)],
    )
    merged, dropped = merge_buildings([donut_osm], [donut_ov])
    assert dropped == 0
    assert len(merged) == 2
    for b in merged:
        assert len(b.inners) == 1
        assert len(b.inners[0]) == 5      # 4 个角 + 闭合点
    assert merged[0].inners[0][0] == (121.4903, 31.2303)
    assert merged[1].inners[0][0] == (121.4953, 31.2353)


def test_mixed_batch():
    """一锅里混着重复和新增:重复的 Overture 丢掉,新增的补在 OSM 后面。"""
    a = _b(121.49, 31.23, 0.001)
    b = _b(121.496, 31.236, 0.001)
    dup_of_a = _b(121.49, 31.23, 0.001, dx=0.00003)
    fresh = _b(121.50, 31.24, 0.001)
    merged, dropped = merge_buildings([a, b], [dup_of_a, fresh])
    assert dropped == 1
    assert merged == [a, b, fresh]
