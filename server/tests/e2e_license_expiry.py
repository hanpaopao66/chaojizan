"""证照有效期台账(第十批 V)。

证过期是**静默失效**:商家不会自己记得,平台不提醒就没人知道,
直到监管上门。而无证经营违法、平台有连带责任。

本用例守的是那个取舍点 —— **过期不立即停业,给 7 天宽限**:
一到期就停会误伤"证已续上只是忘了在平台更新"和"续证还卡在审批里"
这两类(绝大多数),真正无证经营的是极少数。所以:
提醒要发够(30/7/1 各一次、不重复轰炸),宽限期内照常接单,
期满才落闸,而落下的闸商家自己开不回来。
"""
import asyncio
import random
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text  # noqa: E402

from app.db import SessionLocal  # noqa: E402

from .util import ADMIN, call, login  # noqa: E402

admin = login(ADMIN)


def new_shop(name: str):
    phone = f"1{random.choice('3589')}{random.randrange(10**8, 10**9)}"
    tok = call("POST", "/auth/register", body={
        "phone": phone, "password": "123456", "name": name,
        "role": "merchant"})["token"]
    shop = call("POST", "/merchants", tok, {
        "name": name, "address": "证照路 1 号", "lat": 30.66, "lng": 104.08,
        "license_no": f"JYLIC{random.randrange(10**9)}",
        "license_image_url": "/uploads/license-demo.jpg"})
    call("POST", f"/admin/merchants/{shop['id']}/approve", admin)
    return tok, shop


def stage_of(tok):
    return call("GET", "/merchants/me", tok)["license_stage"]


async def set_expiry(shop_id: int, day):
    """直接改库里的到期日。

    走接口是改不动的 —— 过审后资质字段一律锁死(见下面的越权断言),
    而用例要造出"还剩 5 天""已过期 30 天"这些时点。生产上这些状态
    由时间自然到达,这里只是把时钟拨过去。
    """
    async with SessionLocal() as db:
        await db.execute(
            text("UPDATE merchants SET license_expires_at = :d, "
                 "license_notified = '[]' WHERE id = :i"),
            {"d": day, "i": shop_id})
        await db.commit()


async def set_hold(shop_id: int, reason: str):
    """直接造出停业闸门与它的原因。"""
    async with SessionLocal() as db:
        await db.execute(
            text("UPDATE merchants SET food_safety_hold = true, "
                 "hold_reason = :r, is_open = false WHERE id = :i"),
            {"r": reason, "i": shop_id})
        await db.commit()


async def main():
    tok, shop = new_shop(f"证照店{random.randrange(10**4)}")

    # ---- 未登记有效期:不提醒、不拦、不猜 ----
    me = call("GET", "/merchants/me", tok)
    assert me["license_stage"] == "unknown", me
    assert me["license_expires_at"] is None
    comp = call("GET", "/merchants/me/compliance", tok)
    assert comp["license"]["stage"] == "unknown", comp["license"]
    assert "提醒" in comp["license"]["hint"], comp["license"]
    print("✓ 未登记有效期:stage=unknown,不触发任何提醒与拦截")

    # 存量商家就是这个状态,必须还能正常接单
    assert call("GET", "/merchants/me", tok)["status"] == "approved"
    print("✓ 未登记不影响营业(存量商家不能被误伤)")

    # ---- 各档判定 ----
    today = date.today()
    cases = [
        (today + timedelta(days=200), "ok"),
        (today + timedelta(days=20), "soon"),
        (today + timedelta(days=5), "urgent"),
        (today + timedelta(days=1), "last"),
        (today - timedelta(days=2), "expired"),
        (today - timedelta(days=30), "overdue"),
    ]
    for day, want in cases:
        await set_expiry(shop["id"], day)
        got = stage_of(tok)
        assert got == want, f"{day} 应是 {want},实际 {got}"
    print("✓ 六档判定正确(ok/soon/urgent/last/expired/overdue)")

    # ---- 过审后资质一律锁死:到期日尤其不能自助改 ----
    # 能随手改成 2099 的话,整个到期闸门就是摆设
    for field, value in (("license_expires_at", "2099-01-01"),
                         ("license_no", "JYFAKE001"),
                         ("license_subject", "随便写的公司"),
                         ("business_license_no", "9151000000")):
        err = call("PATCH", "/merchants/me", tok, {field: value},
                   expect_error=True)
        assert err["_error"] == 403, f"{field} 不该能自助改:{err}"
    print("✓ 过审后资质字段全部锁死(含有效期,不能自己改成 2099)")

    # ---- 宽限期内照常接单:这是整个取舍的核心 ----
    await set_expiry(shop["id"], today - timedelta(days=2))
    me = call("GET", "/merchants/me", tok)
    assert me["license_stage"] == "expired"
    call("PATCH", "/merchants/me", tok, {"is_open": True})
    assert call("GET", "/merchants/me", tok)["is_open"] is True, \
        "过期但在宽限期内必须还能开门 —— 一到期就停会误伤忘记更新的商家"
    print("✓ 过期后 7 天宽限期内照常营业")

    # ---- 待办里单列一档,不混进角标数 ----
    todos = call("GET", "/merchants/me/todos", tok)
    assert todos["license_stage"] == "expired", todos
    print("✓ 待办单列 license_stage(不混进「有几单待接」的数字里)")

    # ---- 续证通道:提交 → 人工核验 → 自动替换 ----
    bad = call("POST", "/merchants/me/license-renewal", tok,
               {"license_no": "JY1", "license_image_url": "/uploads/a.jpg",
                "license_expires_at": (today - timedelta(days=1)).isoformat()},
               expect_error=True)
    assert bad["_error"] == 422, f"交一张已经过期的证该当场拦:{bad}"

    bad = call("POST", "/merchants/me/license-renewal", tok,
               {"license_no": "JY1", "license_image_url": "/uploads/a.jpg",
                "license_expires_at": (today + timedelta(days=900)).isoformat(),
                "license_subject": "加微信转账便宜点"}, expect_error=True)
    assert bad["_error"] == 422, f"主体名称要过敏感词:{bad}"

    new_no = f"JYNEW{random.randrange(10**9)}"
    new_exp = today + timedelta(days=900)
    call("POST", "/merchants/me/license-renewal", tok, {
        "license_no": new_no, "license_image_url": "/uploads/new.jpg",
        "license_expires_at": new_exp.isoformat(),
        "license_subject": "成都赞小碗餐饮管理有限公司",
        "business_license_no": f"91510{random.randrange(10**12)}"})
    again = call("POST", "/merchants/me/license-renewal", tok, {
        "license_no": new_no, "license_image_url": "/uploads/new.jpg",
        "license_expires_at": new_exp.isoformat()}, expect_error=True)
    assert again["_error"] == 409, f"同时只能有一份在审:{again}"
    prog = call("GET", "/merchants/me/license-renewal", tok)
    assert prog["renewal"]["status"] == "pending", prog
    # 核验期间照常营业 —— 为换证停业几天,惩罚的是守规矩的人
    assert call("GET", "/merchants/me", tok)["license_stage"] == "expired"
    print("✓ 续证提交:过期证当场拦、主体过敏感词、一份在审、期间照常营业")

    queue = call("GET", "/admin/license-renewals", admin)
    mine = [r for r in queue if r["merchant_id"] == shop["id"]][0]
    assert mine["new"]["license_no"] == new_no
    assert mine["current"]["license_no"] != new_no, "要能并排比对新旧两张证"
    rid = mine["id"]
    call("POST", f"/admin/license-renewals/{rid}/approve", admin)
    me = call("GET", "/merchants/me", tok)
    assert me["license_no"] == new_no, me
    assert me["license_expires_at"] == new_exp.isoformat(), me
    assert me["license_stage"] == "ok", me
    comp = call("GET", "/merchants/me/compliance", tok)
    assert comp["license"]["license_subject"].startswith("成都"), comp
    print("✓ 核验通过:资质替换、档位回到 ok、主体名称落库")

    rej = call("POST", f"/admin/license-renewals/{rid}/approve", admin,
               expect_error=True)
    assert rej["_error"] == 404, f"同一条不能重复核验:{rej}"
    print("✓ 已处理的续证不能重复核验")

    # ---- admin 队列:按紧急程度排序,已停业的排最前 ----
    tok2, shop2 = new_shop(f"过期店{random.randrange(10**4)}")
    await set_expiry(shop2["id"], today - timedelta(days=40))
    alerts = call("GET", "/admin/merchants/license-alerts", admin)
    ids = [i["id"] for i in alerts["items"]]
    assert shop2["id"] in ids, alerts
    # 刚续完证的那家必须**离开**队列 —— 队列是"今天该跟进谁",
    # 已经处理完的还挂在上面,审核员每天都要重新分辨一遍哪些是旧的
    assert shop["id"] not in ids, f"续证通过后应离开待处理队列:{alerts}"
    stages = [i["stage"] for i in alerts["items"]]
    order = {"overdue": 0, "expired": 1, "last": 2, "urgent": 3, "soon": 4}
    assert stages == sorted(stages, key=lambda x: order.get(x, 9)), \
        f"该按紧急程度排(已停业的最该先处理):{stages}"
    assert alerts["grace_days"] == 7, alerts
    mine = [i for i in alerts["items"] if i["id"] == shop2["id"]][0]
    assert mine["stage"] == "overdue" and mine["days_left"] == -40, mine
    print(f"✓ admin 证照队列 {len(ids)} 家,按紧急程度倒序,含主体/执照号供核对")

    # ---- 续证不能解开「食安停业」那道闸 ----
    #
    # 两道闸都写在同一个 food_safety_hold 上,不记原因的话就会出现
    # "因食安被停业的店,交一张新证就解封了"。食安整改和换证没有关系。
    tok4, shop4 = new_shop(f"食安停业店{random.randrange(10**4)}")
    # 直接造出"因食安被停业"的状态(走完整投诉流程要先造一单+投诉+成立,
    # 而这里要验的只是「续证解闸时看不看原因」这一句)
    await set_hold(shop4["id"], "food_safety")
    assert call("GET", "/merchants/me", tok4)["is_open"] is False
    call("POST", "/merchants/me/license-renewal", tok4, {
        "license_no": f"JYX{random.randrange(10**9)}",
        "license_image_url": "/uploads/x.jpg",
        "license_expires_at": (today + timedelta(days=900)).isoformat()})
    q = call("GET", "/admin/license-renewals", admin)
    rid4 = [r for r in q if r["merchant_id"] == shop4["id"]][0]["id"]
    res = call("POST", f"/admin/license-renewals/{rid4}/approve", admin)
    assert res["unheld"] is False, \
        f"食安停业不该被换证解开(两件事没有关系):{res}"
    me4 = call("GET", "/merchants/me", tok4)
    reopen = call("PATCH", "/merchants/me", tok4, {"is_open": True},
                  expect_error=True)
    assert reopen.get("_error") in (403, 409), \
        f"食安闸门仍应生效,商家自己开不回来:{reopen} / {me4}"
    print("✓ 续证只解自己落的闸,食安停业不受影响")

    # ---- 未登记有效期的店不该出现在队列里(不猜) ----
    tok3, shop3 = new_shop(f"未登记店{random.randrange(10**4)}")
    alerts = call("GET", "/admin/merchants/license-alerts", admin)
    assert shop3["id"] not in [i["id"] for i in alerts["items"]], \
        "没登记有效期的店不该进待处理队列 —— 不猜就是不猜"
    print("✓ 未登记有效期的店不进 admin 队列")

    print("\ne2e_license_expiry 全部通过 ✅")


if __name__ == "__main__":
    asyncio.run(main())
