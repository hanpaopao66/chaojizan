"""标签和勋章 e2e(services/badges.py、routers/badges.py)。

1. 设标签的校验:个数、字数、重复、屏蔽词、冒充平台标志;合规的规整后存下,别人在资料卡上看得到;
2. 每一枚勋章满足条件就有、不满足就没有。**门槛从透明中心的公示里读**,正好造到「门槛减一」(没有)
   和「门槛」(有),再把公示里写的「不算的」各造一条,确认它确实不算 —— 公示和判据是同一份;
3. 隐藏:整组标签、单枚勋章。隐藏后别人(登录的、没登录的、UP 主空间)看不到,和「没有」一样;
   自己看得到,标着已隐藏。「实名认证」默认就是隐藏的(公示里的 default_hidden),本人打开别人才看得到;
4. 封号期间改标签被挡、隐藏照常能用;注销之后标签清掉,资料卡上什么都没有。

全部自己造:顾客、商家(开店申请就行,不用过审)、第二名管理员(加屏蔽词、驳回评价图、封号),不碰演示账号。
订单用 settle_order 直接落「已完成 + 结算入账」(和 e2e_marketing 同一个做法,审计口径合法);
实名、写评价、售后退款、改标签、隐藏走真接口。

跑法:SUPERZ_API=http://127.0.0.1:8032 DATABASE_URL=… REDIS_URL=… python -m tests.e2e_badges
(直连库的助手读 DATABASE_URL,要和服务端指向同一个库)。服务端要以 PUBLIC_CACHE_MAX_SECONDS=0 起
(本地 .env、CI 都是):别人看到的勋章平时缓存 10 分钟,这里造完数据马上就看。缓存那一段在单测里
(tests/unit/test_badges.py 的假 Redis)。
"""
import asyncio
import random
import uuid
from datetime import datetime, timedelta, timezone

from tests.chat_util import person, sql
from tests.miniapp_util import sms_login
from tests.util import call, fresh_phone
from tests.video_util import admin2_token, fixture_video, realname

PHOTO = ["/uploads/e2e-badge-photo.jpg"]


def keys(card: dict) -> list[str]:
    return [b["key"] for b in card["badges"]]


def card_of(viewer, uid: int) -> dict:
    return viewer.get(f"/social/v1/users/{uid}")


def space_of(token: str | None, uid: int) -> dict:
    return call("GET", f"/video/v1/users/{uid}/space", token)["user"]


def new_shop() -> tuple[int, str]:
    """开一家店(提交申请就有 merchants 这一行,不用过审):返回 (店 id, 店主 token)。"""
    tok = sms_login(fresh_phone("135"), role="merchant")["token"]
    shop = call("POST", "/merchants", tok, {
        "name": f"勋章测试店{random.randint(10000, 99999)}", "address": "测试路 1 号",
        "lat": 30.66, "lng": 104.08, "license_no": f"JY{random.randint(10**13, 10**14 - 1)}",
        "license_image_url": "/uploads/license-demo.jpg"})
    return shop["id"], tok


async def _inject(customer_id: int, merchant_id: int, n: int, hours_ago: float,
                  parent: str, risk_status: str) -> list[str]:
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from sqlalchemy.pool import NullPool

    from app.config import settings
    from app.models import Order
    from app.services.settlement import settle_order
    from app.state_machine import OrderStatus

    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    nos = []
    try:
        async with AsyncSession(engine, expire_on_commit=False) as db:
            for _ in range(n):
                at = datetime.now(timezone.utc) - timedelta(hours=hours_ago)
                o = Order(
                    order_no=uuid.uuid4().hex[:20], customer_id=customer_id,
                    merchant_id=merchant_id, status=OrderStatus.COMPLETED,
                    items=[{"dish_id": 0, "name": "勋章测试菜", "options": [],
                            "price_cents": 2000, "quantity": 1}],
                    food_cents=2000, packing_fee_cents=0, discount_cents=0, subsidy_cents=0,
                    promo_note="", delivery_fee_cents=0, tip_cents=0, total_cents=2000,
                    commission_cents=100, address="到店自取", lat=30.66, lng=104.08,
                    pickup=True, pickup_code="0000", parent_order_no=parent,
                    risk_flags={"hits": ["addr_freq"], "status": risk_status} if risk_status else None)
                db.add(o)
                await db.flush()
                o.created_at = at
                o.completed_at = at + timedelta(minutes=20)
                await settle_order(db, o)
                nos.append(o.order_no)
            await db.commit()
    finally:
        await engine.dispose()
    return nos


def inject(customer_id: int, merchant_id: int, n: int = 1, *, hours_ago: float = 2,
           parent: str = "", risk_status: str = "") -> list[str]:
    """直接落 n 单「已完成」并结算入账。hours_ago:下单时间往前挪,写评价时不被「下单到评价不到 5 分钟」标成刷评。"""
    return asyncio.run(_inject(customer_id, merchant_id, n, hours_ago, parent, risk_status))


def review(p, order_no: str, *, photos: list[str] | None = None) -> dict:
    return call("POST", f"/orders/{order_no}/review", p.token,
                {"merchant_rating": 5, "comment": "勋章测试的评价", "image_urls": photos or []})


def main():
    spec = call("GET", "/transparency/badges")
    by = {b["key"]: b for b in spec["badges"]}
    assert list(by) == ["real_name", "early", "uploader", "photo_reviewer", "regular"], list(by)
    assert [k for k in by if by[k]["default_hidden"]] == ["real_name"], "默认不显示的只有实名认证"
    assert "「实名认证」这一枚默认不显示" in spec["visibility"], spec["visibility"]
    n_photo = by["photo_reviewer"]["min_count"]
    n_orders = by["regular"]["min_count"]
    early_before = datetime.fromisoformat(by["early"]["before"])
    tag_max, tag_len = spec["tags"]["max"], spec["tags"]["max_len"]
    print(f"  公示的门槛:带图评价 {n_photo} 条、完成 {n_orders} 单、{early_before.isoformat()} 以前注册;"
          f"标签最多 {tag_max} 个、每个 {tag_len} 个字")

    admin = admin2_token()
    a, b = person(), person()
    # A 挪到早期用户的截止时刻之后注册:后面数 A 的勋章时不掺「早期用户」,早期用户单独用 C 测边界
    sql("UPDATE users SET created_at = :t WHERE id = :u",
        {"t": early_before + timedelta(days=1), "u": a.id})

    # ------------------------------------------------------------------ 1. 标签校验
    mine = a.get("/social/v1/me/tags-badges")
    assert mine["tags"] == [] and mine["tags_hidden"] is False, mine
    assert (mine["tags_max"], mine["tag_max_len"]) == (tag_max, tag_len), mine
    assert [x["key"] for x in mine["badges"]] == list(by), "设置页列出全部勋章"
    assert not any(x["earned"] for x in mine["badges"]), mine["badges"]
    bad = [
        ([f"标签{i}" for i in range(tag_max + 1)], f"最多 {tag_max} 个"),
        (["长" * (tag_len + 1)], f"最多 {tag_len} 个字"),
        (["Python", "python"], "不能重复"),
        (["川菜", " 川菜 "], "不能重复"),
        (["  "], "不能是空的"),
        (["实名认证"], "平台发的标志"),
        (["官方推荐"], "平台发的标志"),
    ]
    for tags, needle in bad:
        r = a.patch("/social/v1/me/tags-badges", {"tags": tags}, expect_error=True)
        assert r.get("_error") == 422 and needle in str(r["detail"]), (tags, r)
    # 屏蔽词:第二名管理员加一个这次运行独有的词(过的是和签名、用户名同一个词库)。
    # 词 7 个字符,前面加一个字正好 8 个 —— 不能先撞上字数那条
    word = f"zq{random.randint(10000, 99999)}"
    call("POST", "/admin/moderation-words", admin, {"word": word, "category": "other"})
    wid = sql("SELECT id FROM moderation_words WHERE word = :w", {"w": word}, fetch="scalar")
    try:
        r = a.patch("/social/v1/me/tags-badges", {"tags": ["川菜", f"爱{word.upper()}"]},
                    expect_error=True)
        assert r.get("_error") == 422 and "第 2 个标签" in r["detail"], r
        assert word not in r["detail"].lower(), "不透出命中的词"
    finally:
        call("DELETE", f"/admin/moderation-words/{wid}", admin)
    assert a.get("/social/v1/me/tags-badges")["tags"] == [], "不合规的一个都没存进去"
    out = a.patch("/social/v1/me/tags-badges", {"tags": ["川菜", "  夜猫子 ", "Python", "长" * tag_len]})
    want = ["川菜", "夜猫子", "Python", "长" * tag_len]
    assert out["tags"] == want, out
    assert card_of(b, a.id)["tags"] == want, "别人在资料卡上看得到"
    assert space_of(b.token, a.id)["tags"] == want, "UP 主空间也看得到"
    assert space_of(None, a.id)["tags"] == want, "没登录的人也看得到(和昵称、签名同一级别)"
    a.post("/social/v1/blocks", {"user_id": b.id})
    assert card_of(b, a.id)["tags"] == want, "拉黑了照样看得到,和签名一个口径(看不到的是头像和在线)"
    a.delete(f"/social/v1/blocks/{b.id}")
    print("  ✓ 标签:个数、字数、重复(不分大小写、空白规整后比)、屏蔽词、冒充平台标志各有一句话;"
          "合规的规整后存下,资料卡、UP 主空间、没登录的人都看得到")

    # ------------------------------------------------------------------ 2. 勋章
    # 早期用户:截止时刻前一秒注册的有,那一刻注册的没有
    c = person()
    sql("UPDATE users SET created_at = :t WHERE id = :u",
        {"t": early_before - timedelta(seconds=1), "u": c.id})
    assert keys(card_of(b, c.id)) == ["early"], card_of(b, c.id)
    sql("UPDATE users SET created_at = :t WHERE id = :u", {"t": early_before, "u": c.id})
    assert keys(card_of(b, c.id)) == []
    print(f"  ✓ 早期用户:{early_before.isoformat()} 前一秒注册的有,那一刻注册的没有")

    # 实名认证:走真接口(开发环境没配二要素核验时,校验位对的证号算过)。
    # 这一枚默认不显示(公示里的 default_hidden):没选过的人,别人看到的和没有一样,
    # 自己看得到、标着已隐藏;本人打开之后别人才看得到
    assert keys(card_of(b, a.id)) == []
    realname(a)
    assert keys(card_of(b, a.id)) == [] and keys(space_of(None, a.id)) == [], "默认不显示"
    assert [(x["key"], x["hidden"]) for x in card_of(a, a.id)["badges"]] == [("real_name", True)], \
        "自己看得到,标着已隐藏"
    rn = next(x for x in a.get("/social/v1/me/tags-badges")["badges"] if x["key"] == "real_name")
    assert (rn["earned"], rn["hidden"], rn["default_hidden"]) == (True, True, True), rn
    a.patch("/social/v1/me/tags-badges", {"hidden_badges": {"real_name": False}})
    got = card_of(b, a.id)
    assert keys(got) == ["real_name"] and keys(space_of(None, a.id)) == ["real_name"], got
    assert got["badges"][0]["condition"] == by["real_name"]["condition"], "资料卡上的条件就是公示的那一句"
    assert sql("SELECT badges_shown @> '[\"real_name\"]'::jsonb FROM social_profiles WHERE user_id = :u",
               {"u": a.id}, fetch="scalar") is True, "打开这件事存下来了:以后按他选的"
    print("  ✓ 实名认证:核验通过就有;默认不显示(别人看不到,自己看得到标着已隐藏),本人打开之后别人看得到")

    # UP 主:已发布 + 公开 + 没删除,和 UP 主空间「投稿」数的是同一批
    vid = fixture_video(a.id)["id"]
    assert keys(card_of(b, a.id)) == ["real_name", "uploader"]
    assert call("GET", f"/video/v1/users/{a.id}/space", b.token)["stats"]["videos"] == 1
    for change in ("visibility = 'private'", "status = 'reviewing'", "status = 'removed'",
                   "deleted_at = now()"):
        sql(f"UPDATE videos SET {change} WHERE id = :v", {"v": vid})
        assert "uploader" not in keys(card_of(b, a.id)), change
        assert call("GET", f"/video/v1/users/{a.id}/space", b.token)["stats"]["videos"] == 0, change
        sql("UPDATE videos SET visibility = 'public', status = 'published', deleted_at = NULL "
            "WHERE id = :v", {"v": vid})
    assert keys(card_of(b, a.id)) == ["real_name", "uploader"]
    print("  ✓ UP 主:公开发布中的视频有 1 个就有;设私密、审核中、被下架、删除各试一次都没有,"
          "和空间里的投稿数同进同出")

    # 带图评价达人:每家店最多写 2 条(同店 30 天第 4 条起会被标刷评,这里不碰那条线)
    r_ = person()
    shops: list[int] = []

    def shop_for(i: int) -> int:
        while len(shops) <= i // 2:
            shops.append(new_shop()[0])
        return shops[i // 2]

    valid, slot = [], 0
    for _ in range(n_photo - 1):
        no = inject(r_.id, shop_for(slot))[0]
        slot += 1
        valid.append(review(r_, no, photos=PHOTO)["id"])
    assert "photo_reviewer" not in keys(card_of(b, r_.id)), f"{n_photo - 1} 条还不够"
    # 不算的:没带图的;下单不到 5 分钟就写的(被标刷评嫌疑)
    review(r_, inject(r_.id, shop_for(slot))[0])
    slot += 1
    quick = review(r_, inject(r_.id, shop_for(slot), hours_ago=0)[0], photos=PHOTO)["id"]
    slot += 1
    assert sql("SELECT flagged FROM reviews WHERE id = :i", {"i": quick}, fetch="scalar") is True
    assert "photo_reviewer" not in keys(card_of(b, r_.id)), "没图的、带刷评标记的不算"
    valid.append(review(r_, inject(r_.id, shop_for(slot))[0], photos=PHOTO)["id"])
    slot += 1
    assert "photo_reviewer" in keys(card_of(b, r_.id)), f"第 {n_photo} 条带图评价"
    sql("UPDATE reviews SET hidden = true WHERE id = :i", {"i": valid[0]})
    assert "photo_reviewer" not in keys(card_of(b, r_.id)), "被隐藏的评价(商家申诉成立)不算"
    sql("UPDATE reviews SET hidden = false WHERE id = :i", {"i": valid[0]})
    assert "photo_reviewer" in keys(card_of(b, r_.id))
    # 图被审核驳回:走后台真接口,驳回之后评价里就没这张图了
    cr = sql("SELECT id FROM content_reviews WHERE kind = 'review' AND ref_id = :i "
             "AND status = 'pending'", {"i": valid[1]}, fetch="scalar")
    call("POST", f"/admin/content-reviews/{cr}/reject", admin, {"note": "勋章测试驳回"})
    assert "photo_reviewer" not in keys(card_of(b, r_.id)), "图被审核移除的不算"
    print(f"  ✓ 带图评价达人:{n_photo - 1} 条没有、第 {n_photo} 条有;没带图的、刷评嫌疑的、"
          "被隐藏的、图被审核驳回的都不算")

    # 老顾客
    d = person()
    shop, boss = new_shop()
    first = inject(d.id, shop, n_orders - 1)
    assert "regular" not in keys(card_of(b, d.id)), f"{n_orders - 1} 单还不够"
    last = inject(d.id, shop)[0]
    assert "regular" in keys(card_of(b, d.id)), f"第 {n_orders} 单"
    # 钱全部退回的单不算:真走一遍售后(自取单没有配送费,商家同意就是整单退)
    call("POST", f"/orders/{last}/after-sale", d.token,
         {"reason": "勋章测试:餐不对", "images": ["/uploads/e2e-badge-as.jpg"]})
    asid = sql("SELECT a.id FROM after_sales a JOIN orders o ON o.id = a.order_id "
               "WHERE o.order_no = :n", {"n": last}, fetch="scalar")
    call("POST", f"/after-sales/{asid}/accept", boss, {"reply": "同意,全额退"})
    assert sql("SELECT refund_cents >= total_cents FROM orders WHERE order_no = :n",
               {"n": last}, fetch="scalar") is True
    assert "regular" not in keys(card_of(b, d.id)), "整单退了款的不算"
    inject(d.id, shop, parent=first[0])
    inject(d.id, shop, risk_status="confirmed")
    assert "regular" not in keys(card_of(b, d.id)), "加菜的追加单、被确认为刷单的不算"
    inject(d.id, shop)
    assert "regular" in keys(card_of(b, d.id))
    print(f"  ✓ 老顾客:{n_orders - 1} 单没有、第 {n_orders} 单有;整单退款(真走售后)、追加单、"
          "确认刷单的都不算")

    # ------------------------------------------------------------------ 3. 隐藏
    a.patch("/social/v1/me/tags-badges", {"tags_hidden": True, "hidden_badges": {"real_name": True}})
    others = card_of(b, a.id)
    assert others["tags"] == [] and others["tags_hidden"] is False, "别人看:和没有标签一样"
    assert keys(others) == ["uploader"], others
    for view in (space_of(b.token, a.id), space_of(None, a.id)):
        assert view["tags"] == [] and keys(view) == ["uploader"], view
    self_card = card_of(a, a.id)
    assert self_card["tags"] == want and self_card["tags_hidden"] is True, self_card
    assert [(x["key"], x["hidden"]) for x in self_card["badges"]] == [("real_name", True),
                                                                      ("uploader", False)]
    self_space = space_of(a.token, a.id)
    assert self_space["tags_hidden"] is True and [x["hidden"] for x in self_space["badges"]] == [True, False]
    mine = a.get("/social/v1/me/tags-badges")
    assert {x["key"]: (x["earned"], x["hidden"]) for x in mine["badges"]} == {
        "real_name": (True, True), "early": (False, False), "uploader": (True, False),
        "photo_reviewer": (False, False), "regular": (False, False)}, mine["badges"]
    # 还没拿到的也能先设成隐藏;不存在的勋章 422
    a.patch("/social/v1/me/tags-badges", {"hidden_badges": {"regular": True}})
    r = a.patch("/social/v1/me/tags-badges", {"hidden_badges": {"vip": True}}, expect_error=True)
    assert r.get("_error") == 422 and "没有这枚勋章" in r["detail"], r
    a.patch("/social/v1/me/tags-badges",
            {"tags_hidden": False, "hidden_badges": {"real_name": False, "regular": False}})
    back = card_of(b, a.id)
    assert back["tags"] == want and keys(back) == ["real_name", "uploader"], back
    print("  ✓ 隐藏:整组标签、单枚勋章隐藏后,别人(资料卡、UP 主空间、没登录)看到的和「没有」一样;"
          "自己看得到并标着已隐藏;没拿到的也能先隐藏")

    # ------------------------------------------------------------------ 4. 封号、注销
    s = call("POST", "/admin/social/sanctions", admin,
             {"target_type": "user", "target_id": a.id, "action": "ban_account", "days": 1,
              "reason_code": "C103", "note": "勋章 e2e"})
    try:
        r = a.patch("/social/v1/me/tags-badges", {"tags": ["新标签"]}, expect_error=True)
        assert r.get("_error") == 403 and r["detail"]["error"] == "sanctioned", r
        ok = a.patch("/social/v1/me/tags-badges", {"hidden_badges": {"uploader": True}})
        assert ok["tags"] == want and [x["hidden"] for x in ok["badges"] if x["key"] == "uploader"] == [True]
    finally:
        call("POST", f"/admin/social/sanctions/{s['id']}/revoke", admin, {"note": "测试完撤掉"})
    a.patch("/social/v1/me/tags-badges", {"hidden_badges": {"uploader": False}})
    e = person()
    # 还没实名就先把实名认证打开(没拿到的也能先设):实名之后别人马上看得到
    e.patch("/social/v1/me/tags-badges", {"tags": ["要注销了"], "hidden_badges": {"real_name": False}})
    realname(e)
    before = card_of(b, e.id)
    assert before["tags"] == ["要注销了"] and "real_name" in keys(before), before
    call("DELETE", "/auth/me", e.token)
    gone = card_of(b, e.id)
    assert gone["tags"] == [] and gone["badges"] == [], gone
    assert sql("SELECT jsonb_array_length(tags) + jsonb_array_length(badges_shown) "
               "FROM social_profiles WHERE user_id = :u", {"u": e.id}, fetch="scalar") == 0, \
        "注销时标签和显示设置从库里清掉,不只是不显示"
    print("  ✓ 封号期间改标签 403、隐藏照常能用;注销后标签和显示设置清掉,资料卡上什么都没有")

    # ------------------------------------------------------------------ 5. 公示
    for x in (card_of(b, a.id)["badges"] + card_of(b, d.id)["badges"]):
        assert x["condition"] == by[x["key"]]["condition"] and x["icon"] == by[x["key"]]["icon"], x
    assert all(x["condition"] and x["counts"] and x["excludes"] for x in spec["badges"])
    print("  ✓ 透明中心:门槛拿来造数据正好卡在分界上;资料卡上每一枚的条件、图标和公示一字不差")

    print("e2e_badges 全部通过 ✅")


if __name__ == "__main__":
    main()
