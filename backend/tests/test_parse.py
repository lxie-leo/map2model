"""OSM 解析:分类对不对、宽度怎么定、高度怎么补、隧道要不要留。"""

from app.services.osm_parse import parse_osm, resolve_building_heights


def test_parse_counts(sample_payload):
    feats = parse_osm(sample_payload)
    # 3 个独立 way 建筑 + 1 个 relation 建筑 = 4(最后一个只有 2 个点,被丢弃)
    assert len(feats.buildings) == 4
    assert len(feats.roads) == 2            # residential(tunnel)被过滤
    assert len(feats.railways) == 1
    assert len(feats.waterways) == 1
    assert len(feats.water_polys) == 1      # natural=water
    assert len(feats.greens) == 2           # grass + park


def test_tunnel_dropped(sample_payload):
    feats = parse_osm(sample_payload)
    assert all(r.kind != "tunnel" for r in feats.roads)
    # 303 号 way 是 tunnel=yes 的 residential,不该出现为重复坐标
    # (它被直接跳过,上面 count 已验证)


def test_width_resolution(sample_payload):
    feats = parse_osm(sample_payload)
    primary = next(r for r in feats.roads if r.kind == "primary")
    assert primary.width == 14.0          # lanes=4 × 3.5
    assert primary.bridge is True
    residential = next(r for r in feats.roads if r.kind == "residential")
    assert residential.width == 7.0        # lanes=2 × 3.5
    river = feats.waterways[0]
    assert river.width == 30.0             # width 标签


def test_relation_hole(sample_payload):
    feats = parse_osm(sample_payload)
    donut = next(b for b in feats.buildings if b.inners)
    assert len(donut.outer) >= 4
    assert len(donut.inners) == 1


def _ring(lon0, lat0, size):
    """造一个边长约 size(度) 的闭合方块。"""
    pts = [(lon0, lat0), (lon0 + size, lat0), (lon0 + size, lat0 + size), (lon0, lat0 + size)]
    return pts + [pts[0]]


def test_multi_outer_relation():
    """一块地画成好几片的 relation(比如多片森林):每片都得留下来,
    不能只认第一片;挖洞的内环还得跟对主人。"""
    payload = {"elements": [{
        "type": "relation", "id": 1,
        "tags": {"natural": "wood", "name": "Split Forest"},
        "members": [
            {"type": "way", "role": "outer", "geometry": [dict(lon=x, lat=y) for x, y in _ring(0, 0, 0.001)]},
            {"type": "way", "role": "outer", "geometry": [dict(lon=x, lat=y) for x, y in _ring(0.01, 0, 0.001)]},
            # 这片林中空地位于第一片里面,洞应该跟着第一片
            {"type": "way", "role": "inner", "geometry": [dict(lon=x, lat=y) for x, y in _ring(0.0002, 0.0002, 0.0006)]},
        ],
    }]}
    feats = parse_osm(payload)
    assert len(feats.greens) == 2          # 两片都在,以前只留第一片
    holed = [g for g in feats.greens if g.inners]
    assert len(holed) == 1                 # 洞只挂在包含它的那片上
    assert len(holed[0].inners) == 1


def test_height_backfill(sample_payload):
    feats = parse_osm(sample_payload)
    resolve_building_heights(feats.buildings)
    by_name = {b.name: b for b in feats.buildings}
    assert by_name["Tall Tower"].height == 25.0      # height 标签优先
    assert by_name["Flat Block"].height == 9.6       # levels 3 × 3.2
    assert by_name["Donut Building"].height == 40.0
    no_tags = [b for b in feats.buildings if b.name is None]
    # 已知高度 [25, 40],标准中位数取中间两个的平均 → 32.5
    assert no_tags[0].height == 32.5
