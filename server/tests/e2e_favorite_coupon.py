"""收藏有礼 + 差评时效 + 回复模板(第七批)。

这条发券路径的攻击成本是全平台最低的 —— 注册一个号 + 一次 POST,
不用下单、不用花一分钱。而券是 funder=merchant、商家全额承担。
所以本用例的重点不是"能发出来",而是**该拦的都拦住了**:
营销总开关、风控账号、同设备多账号、跨批次重复领。
"""
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from .util import ADMIN, MERCHANT, call, login  # noqa: E402
from .util import DEMO_SHOP_ID  # noqa: E402

merchant = login(MERCHANT)
admin = login(ADMIN)


def new_customer(device_id: str = ""):
    phone = f"1{random.choice('3589')}{random.randrange(10**8, 10**9)}"
    code = call("POST", "/auth/sms-code", body={"phone": phone})["dev_code"]
    body = {"phone": phone, "code": code}
    if device_id:
        body["device_id"] = device_id
    return call("POST", "/auth/sms-login", body=body)["token"], phone


def set_marketing(value: str):
    call("POST", "/admin/flags/marketing", admin, {"value": value})


def main():
    orig_flag = None
    flags = call("GET", "/admin/flags", admin)
    for f in (flags if isinstance(flags, list) else []):
        if f.get("key") == "marketing":
            orig_flag = f.get("value")

    batch = call("POST", "/merchants/me/coupon-batches", merchant, {
        "name": "收藏有礼-e2e", "trigger": "favorite",
        "threshold_cents": 2000, "off_cents": 300,
        "total": 20, "valid_days": 7, "per_user_limit": 1})
    assert batch["trigger"] == "favorite", batch
    print("✓ 商家可建 trigger=favorite 的券批次")

    # ---- 营销总开关关闭时一张不发(平台唯一的应急刹车) ----
    set_marketing("off")
    c_off, _ = new_customer()
    res = call("POST", f"/favorites/{DEMO_SHOP_ID}", c_off)
    assert res["favorited"] is True and "coupon" not in res, res
    print("✓ 营销总开关关闭:收藏成功但不发券(与其余自动发券路径同口径)")

    # ---- 开关打开后正常发 ----
    set_marketing("on")
    c1, _ = new_customer()
    res = call("POST", f"/favorites/{DEMO_SHOP_ID}", c1)
    assert res.get("coupon", {}).get("amount_cents") == 300, res
    print(f"✓ 收藏即发券 ¥{res['coupon']['amount_cents'] / 100:g}")

    # ---- 取关再收藏不再发 ----
    call("DELETE", f"/favorites/{DEMO_SHOP_ID}", c1)
    again = call("POST", f"/favorites/{DEMO_SHOP_ID}", c1)
    assert "coupon" not in again, f"取关再收藏不该再发:{again}"
    print("✓ 取关再收藏不重复发")

    # ---- 换一批券也不再发(去重键是「店+人」不是批次) ----
    call("POST", f"/merchants/me/coupon-batches/{batch['id']}/toggle",
         merchant)
    batch2 = call("POST", "/merchants/me/coupon-batches", merchant, {
        "name": "收藏有礼-e2e-2", "trigger": "favorite",
        "threshold_cents": 2000, "off_cents": 900,
        "total": 20, "valid_days": 7, "per_user_limit": 1})
    call("DELETE", f"/favorites/{DEMO_SHOP_ID}", c1)
    cross = call("POST", f"/favorites/{DEMO_SHOP_ID}", c1)
    assert "coupon" not in cross, \
        f"换批次也不该再发(否则奖励反复取关的人):{cross}"
    print("✓ 商家换新批次:老用户取关再收藏依然不再发")

    # ---- 风控账号拿不到(主动领券已拒,这里不能是后门) ----
    c_risk, _ = new_customer()
    uid = call("GET", "/auth/me", c_risk)["id"]
    call("POST", f"/admin/users/{uid}/risk-level", admin,
         {"level": "limit", "reason": "e2e 风控测试"})
    res = call("POST", f"/favorites/{DEMO_SHOP_ID}", c_risk)
    assert "coupon" not in res, f"风控账号不该拿到券:{res}"
    print("✓ 风控账号(limit)收藏不发券")
    call("POST", f"/admin/users/{uid}/risk-level", admin,
         {"level": "", "reason": "e2e 收尾"})

    # ---- 同设备多账号只有第一个拿得到 ----
    dev = f"e2e-dev-{random.randrange(10**6)}"
    ca, _ = new_customer(dev)
    cb, _ = new_customer(dev)
    ra = call("POST", f"/favorites/{DEMO_SHOP_ID}", ca)
    rb = call("POST", f"/favorites/{DEMO_SHOP_ID}", cb)
    assert not ("coupon" in ra and "coupon" in rb), \
        "同设备两个号都拿到券,防薅失效"
    print("✓ 同设备多账号防薅生效")

    # ---- 差评时效与回复模板 ----
    todos = call("GET", "/merchants/me/todos", merchant)
    assert "bad_reviews_overdue" in todos, todos
    assert todos["bad_reviews_overdue"] <= todos["bad_reviews_unreplied"], \
        "超时数不可能大于未回复总数"
    print(f"✓ 差评时效:待回复 {todos['bad_reviews_unreplied']}、"
          f"超 24 小时 {todos['bad_reviews_overdue']}")

    tpl = call("GET", "/merchants/me/reply-templates", merchant)
    assert len(tpl["templates"]["bad"]) >= 4, tpl
    print(f"✓ 回复模板:差评 {len(tpl['templates']['bad'])} 套")

    # 收尾:停用测试批次,还原营销开关
    call("POST", f"/merchants/me/coupon-batches/{batch2['id']}/toggle",
         merchant)
    if orig_flag is not None and orig_flag != "on":
        set_marketing(orig_flag)

    print("\ne2e_favorite_coupon 全部通过 ✅")


if __name__ == "__main__":
    main()
