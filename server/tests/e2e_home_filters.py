"""首页筛选器 / 我的常点 / 老客召回(#118 #119 #117)。

三条都是「用户已经知道自己想要什么」时的路径,守住的是:
筛选真的筛得掉(不是摆设)、常点只列点得了的、
商家看得到召回规模但看不到是谁。
"""
from .util import CUSTOMER, MERCHANT, call, login

DEMO_LAT, DEMO_LNG = 30.66, 104.08


def _ids(rows):
    return {m["id"] for m in rows}


def _rating_ok(m, floor):
    r = m.get("rating_avg")
    return r is None or float(r) >= floor


def _dist_m(m, lat, lng):
    """粗略球面距离(米),只为验证半径筛选,不需要测地线精度。"""
    import math
    dlat = math.radians(m["lat"] - lat)
    dlng = math.radians(m["lng"] - lng)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(lat)) * math.cos(math.radians(m["lat"]))
         * math.sin(dlng / 2) ** 2)
    return 6371000 * 2 * math.asin(math.sqrt(a))


def main() -> None:
    base = f"/merchants?lat={DEMO_LAT}&lng={DEMO_LNG}&sort=distance"
    everyone = call("GET", base)
    assert everyone, "演示城市附近一家商家都没有,先跑 seed"
    print(f"✓ 不加筛选 {len(everyone)} 家")

    # 断言一律逐条复核筛选谓词,不用「筛选结果 ⊆ 不筛结果」:
    # 列表接口 LIMIT 50,商家一多不筛的那份本身就被截断了,子集关系不成立

    # --- #118 筛选器 ---
    # 评分下限:筛出来的每一家都得真的达标
    rated = call("GET", f"{base}&min_rating=4.5")
    for m in rated:
        assert _rating_ok(m, 4.5), f"{m['name']} 评分 {m.get('rating_avg')} 低于 4.5"
    print(f"✓ min_rating=4.5 → {len(rated)} 家,逐家复核评分达标")

    # 起送价上限
    cheap = call("GET", f"{base}&max_min_order_cents=1500")
    for m in cheap:
        assert m["min_order_cents"] <= 1500, m
    print(f"✓ 起送价 ≤¥15 → {len(cheap)} 家,逐家复核起送价")

    # 距离上限:逐家复核真实距离(留 100m 容差,服务端用 PostGIS 大地距离)
    near = call("GET", f"{base}&radius_m=1000")
    for m in near:
        d = _dist_m(m, DEMO_LAT, DEMO_LNG)
        assert d <= 1100, f"{m['name']} 距离 {d:.0f}m 超出 1km 筛选"
    print(f"✓ radius_m=1000 → {len(near)} 家,逐家复核距离")

    # 只看有优惠:必须真有满减或满赠规则
    promo = call("GET", f"{base}&has_promo=true")
    for m in promo:
        assert m["promo_rules"] or m["gift_rules"], f"{m['name']} 没有任何优惠规则"
    print(f"✓ has_promo → {len(promo)} 家,逐家复核确有满减/满赠")

    # 组合筛选必须同时生效(不能只认最后一个参数)
    combo = call("GET", f"{base}&min_rating=4.5&max_min_order_cents=1500")
    for m in combo:
        assert _rating_ok(m, 4.5) and m["min_order_cents"] <= 1500, m
    print(f"✓ 组合筛选两个条件同时生效 → {len(combo)} 家")

    # 无定位兜底也要认筛选,否则关掉定位筛选就静默失效
    no_pos_cheap = call("GET", "/merchants?max_min_order_cents=1500")
    for m in no_pos_cheap:
        assert m["min_order_cents"] <= 1500, m
    print(f"✓ 无定位时筛选同样生效({len(no_pos_cheap)} 家,逐家复核)")

    # 越界参数被挡住(422),不是静默忽略
    bad = call("GET", f"{base}&min_rating=9", expect_error=True)
    assert bad["_error"] == 422, bad
    print("✓ min_rating=9 被 422 挡住")

    # --- #119 我的常点 ---
    c_token = login(CUSTOMER)
    freq = call("GET", "/orders/frequent", token=c_token)["items"]
    assert isinstance(freq, list), freq
    assert len(freq) <= 5, freq
    times = [f["times"] for f in freq]
    assert times == sorted(times, reverse=True), f"常点未按次数倒序:{times}"
    for f in freq:
        assert f["times"] >= 1, f
        assert f["dish_name"] and f["merchant_name"], f
        # 列出来就得点得了:菜必须还在售(接口已按 is_on_sale/库存过滤)
        menu = call("GET", f"/merchants/{f['merchant_id']}/dishes")
        on_sale = {d["id"] for d in menu if d.get("is_on_sale", True)}
        assert f["dish_id"] in on_sale, f"{f['dish_name']} 已下架却出现在常点"
    print(f"✓ 我的常点 {len(freq)} 条,按次数倒序且逐条复核在售")

    limited = call("GET", "/orders/frequent?limit=2", token=c_token)["items"]
    assert len(limited) <= 2, limited
    print(f"✓ limit=2 生效({len(limited)} 条)")

    # --- #117 老客召回:只给计数,不给名单 ---
    m_token = login(MERCHANT)
    wb = call("GET", "/merchants/me/winback", token=m_token)
    for key in ("dormant_30d", "dormant_90d", "customers_180d"):
        assert isinstance(wb[key], int) and wb[key] >= 0, wb
    assert wb["dormant_90d"] <= wb["dormant_30d"], (
        "90 天没来的人不可能多于 30 天没来的", wb)
    print(f"✓ 召回概览:30 天沉睡 {wb['dormant_30d']} 人 / "
          f"90 天 {wb['dormant_90d']} 人 / 半年老客 {wb['customers_180d']} 人")

    # 关键:整个响应里不能出现任何顾客身份信息
    blob = str(wb)
    for leak in ("phone", "customer_id", "user_id", "nickname", "name\":\"1"):
        assert leak not in blob, f"召回概览泄露了顾客信息:{leak} in {blob}"
    # 按**手机号形态**判,不按"含不含 13"。
    # 原先写的是 `"13" not in blob`,任何含 13 的内容都会误报 ——
    # 实测被 `dormant_30d: 13`(沉睡用户数)打中,而那根本不是手机号。
    # 断言要守的东西是对的(概览不能带顾客身份),但判据太粗就会变成
    # "偶尔红一下、大家学会忽略它",那还不如没有
    import re as _re
    phones = _re.findall(r"1[3-9]\d{9}", blob)
    assert not phones, f"召回概览里出现手机号 {phones}:{blob}"
    print("✓ 响应只含计数,无任何顾客身份信息")

    # 顾客态拿不到商家的召回数据
    denied = call("GET", "/merchants/me/winback", token=c_token,
                  expect_error=True)
    assert denied["_error"] in (401, 403), denied
    print("✓ 顾客态访问召回概览被拒")

    print("\n全部通过:首页筛选 / 我的常点 / 老客召回")


if __name__ == "__main__":
    main()
