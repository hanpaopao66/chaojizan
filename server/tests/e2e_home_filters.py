"""首页筛选器 / 我的常点 / 老客召回(#118 #119 #117)。

三条都是「用户已经知道自己想要什么」时的路径,守住的是:
筛选真的筛得掉(不是摆设)、常点只列点得了的、
商家看得到召回规模但看不到是谁。

## 筛选那段为什么要自己造数据

演示库在演示坐标附近的 50 家店**每一家都长得一样**:
`min_order_cents` 全是 0、距离全是 0 米、`rating_avg` 全是 None。
在这样一份数据上,「筛出来的每一家都达标」这句话恒为真 ——
把服务端的筛选参数全部忽略掉,这一段照样全绿(实测)。

所以这里不用演示数据,自己在一片**空的坐标**上摆两家店:
一家样样达标、一家样样不达标,而且两家在不加筛选时都看得见。
断言分两头:达标的必须**在**结果里,不达标的必须**不在**。
少了后半句,筛选器就还是可以是个摆设。
"""
import random

from .util import ADMIN, CUSTOMER, MERCHANT, call, login

DEMO_LAT, DEMO_LNG = 30.66, 104.08


def _ids(rows):
    return {m["id"] for m in rows}


def _rating_ok(m, floor):
    r = m.get("rating_avg")
    return r is None or float(r) >= floor


#: 一个格子里最多容忍几家历史遗留的店。
#: 列表 LIMIT 50,而本次要断言的两家里有一家在 2km 外(排在同点位的后面),
#: 留够余量它才进得了这一页。
_SPOT_TOLERANCE = 20


def _empty_spot():
    """挑一块几乎没有商家的地方摆测试店。

    演示城市周边不行:那儿 50 家店挤在同一个点上,LIMIT 50 一截,
    自己刚建的店根本进不了列表。格间距 0.1°(~11km)远大于浏览半径
    (配送上限 4km),所以不同格子之间互不可见。

    **格子要给得足够多**:这条用例每跑一次就在格子里留下两家店,
    格子少了的话,跑上几十轮就会开始互相挤 —— 那种坏法是几个月后
    突然冒出来的、且看起来完全莫名其妙。14° × 20° 的框切 0.1°
    是 28000 格,再加上"少于 20 家也算数"的容忍,不会有那一天。
    """
    for _ in range(20):
        lat = round(20.0 + random.randrange(140) * 0.1, 1)
        lng = round(100.0 + random.randrange(200) * 0.1, 1)
        if len(call("GET", f"/merchants?lat={lat}&lng={lng}")) \
                <= _SPOT_TOLERANCE:
            return lat, lng
    raise AssertionError("连着 20 个格子都挤满了商家,该清一清测试数据了")


def _make_shop(admin, name, lat, lng, *, min_order, promo, rating):
    """建一家过审营业中的店,属性按参数摆好。评分只能写库 ——
    没有接口能凭空给一家新店打分,而用例要的是"评分 3.0 的店"这个状态。"""
    phone = f"1{random.choice('3589')}{random.randrange(10**8, 10**9)}"
    tok = call("POST", "/auth/register", body={
        "phone": phone, "password": "123456", "name": name,
        "role": "merchant"})["token"]
    shop = call("POST", "/merchants", tok, {
        "name": name, "address": "筛选测试路 1 号", "lat": lat, "lng": lng,
        "license_no": f"JYLIC{random.randrange(10**9)}",
        "license_image_url": "/uploads/license-demo.jpg"})
    call("POST", f"/admin/merchants/{shop['id']}/approve", admin)
    call("PATCH", "/merchants/me", tok, {
        "is_open": True, "min_order_cents": min_order,
        "promo_rules": ([{"threshold_cents": 3000, "off_cents": 500}]
                        if promo else [])})
    _set_rating(shop["id"], rating)
    return shop["id"]


def _set_rating(shop_id: int, avg: float):
    import asyncio

    async def _go():
        from sqlalchemy import text

        from app.db import SessionLocal, engine
        async with SessionLocal() as db:
            await db.execute(
                text("UPDATE merchants SET rating_sum = :s, rating_count = 10"
                     " WHERE id = :i"), {"s": int(avg * 10), "i": shop_id})
            await db.commit()
        await engine.dispose()  # 多次 asyncio.run:释放连接池防事件循环串台
    asyncio.run(_go())


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
    #
    # 在一片空坐标上摆两家店:
    #   good —— 评分 4.8 / 起送 ¥10 / 有满减 / 就在查询点上;
    #   poor —— 评分 3.0 / 起送 ¥30 / 无优惠 / 在 2km 外,
    #           默认浏览半径(配送上限 4km)之内,所以不加筛选时它必须看得见。
    # 每条筛选都断两头:good 在、poor 不在。
    # 只断"结果里的每一家都达标"是不够的 —— 演示数据上那句话恒为真。
    admin = login(ADMIN)
    flat, flng = _empty_spot()
    good = _make_shop(admin, f"筛选达标店{random.randrange(10**6)}",
                      flat, flng, min_order=1000, promo=True, rating=4.8)
    # 纬度 +0.018° ≈ 2km:超出 radius_m=1000,但在 4km 浏览半径内
    poor = _make_shop(admin, f"筛选不达标店{random.randrange(10**6)}",
                      flat + 0.018, flng, min_order=3000, promo=False,
                      rating=3.0)
    fbase = f"/merchants?lat={flat}&lng={flng}&sort=distance"
    both = _ids(call("GET", fbase))
    assert {good, poor} <= both, (
        f"前置就不成立:不加筛选时两家店都得在({good},{poor})→ {both}")
    print(f"✓ 测试坐标 ({flat:.2f},{flng:.2f}) 上摆好两家店,不筛时都可见")

    def check(param, label, *, keeps=good, drops=poor):
        rows = call("GET", f"{fbase}&{param}")
        ids = _ids(rows)
        assert keeps in ids, f"{label}:达标的店被筛掉了(id={keeps})"
        assert drops not in ids, f"{label}:不达标的店没被筛掉(id={drops})"
        return rows

    # 评分下限
    rated = check("min_rating=4.5", "min_rating=4.5")
    for m in rated:
        assert _rating_ok(m, 4.5), f"{m['name']} 评分 {m.get('rating_avg')} 低于 4.5"
    print("✓ min_rating=4.5:4.8 分的留下、3.0 分的被筛掉")

    # 起送价上限
    cheap = check("max_min_order_cents=1500", "起送价 ≤¥15")
    for m in cheap:
        assert m["min_order_cents"] <= 1500, m
    print("✓ 起送价 ≤¥15:¥10 的留下、¥30 的被筛掉")

    # 距离上限:逐家复核真实距离(留 100m 容差,服务端用 PostGIS 大地距离)
    near = check("radius_m=1000", "radius_m=1000")
    for m in near:
        d = _dist_m(m, flat, flng)
        assert d <= 1100, f"{m['name']} 距离 {d:.0f}m 超出 1km 筛选"
    print("✓ radius_m=1000:点上那家留下、2km 外那家被筛掉")

    # 只看有优惠:必须真有满减或满赠规则
    promo = check("has_promo=true", "has_promo")
    for m in promo:
        assert m["promo_rules"] or m["gift_rules"], f"{m['name']} 没有任何优惠规则"
    print("✓ has_promo:有满减的留下、没优惠的被筛掉")

    # 组合筛选必须同时生效(不能只认最后一个参数)
    combo = check("min_rating=4.5&max_min_order_cents=1500", "组合筛选")
    for m in combo:
        assert _rating_ok(m, 4.5) and m["min_order_cents"] <= 1500, m
    print("✓ 组合筛选两个条件同时生效")

    # 演示坐标那份也扫一遍:上面两家店在别的城市,这里保的是
    # 首页真实数据路径不因为筛选参数报错/串味
    for q in ("min_rating=4.5", "max_min_order_cents=1500", "radius_m=1000"):
        rows = call("GET", f"{base}&{q}")
        assert isinstance(rows, list), rows
    print("✓ 演示坐标上同样的筛选参数不报错")

    # 无定位兜底也要认筛选,否则关掉定位筛选就静默失效。
    # 这条在演示数据上是**有效**的:不筛的首页里就混着起送价 ¥20 的店,
    # 服务端忽略参数的话下面这个断言会直接红
    no_pos_all = call("GET", "/merchants?max_min_order_cents=100000")
    assert any(m["min_order_cents"] > 1500 for m in no_pos_all), (
        "无定位首页里没有起送价 >¥15 的店,下面那条断言会退化成恒真 —— "
        "换个门槛或先补数据")
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
