"""菜单批量导入 / 定时改价 / 顾客备注 / 异常订单标记(第十二批 AC·AD·AJ·AK)。

四块各有一条不能破的线:
- 导入:**预览与写入分两步**。一次错误的表格能把 80 道菜的价格全改掉,
  而商家发现时已经卖了半天;
- 定时:**过期太久的不补跑**。把三天前该降的价降下来,商家会莫名其妙亏一笔;
- 备注:**只对本店可见**,而且只能给真在本店下过单的人记 ——
  否则这就是个可以给任意 user_id 写字的接口;
- 标记:**只上报不处置**。不给商家拉黑顾客的权力(那会变成报复工具),
  所以接口必须把"标记之后不会发生什么"说清楚。
"""
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from .util import ADMIN, CUSTOMER, call, login  # noqa: E402

admin = login(ADMIN)


def new_shop(name: str):
    phone = f"1{random.choice('3589')}{random.randrange(10**8, 10**9)}"
    tok = call("POST", "/auth/register", body={
        "phone": phone, "password": "123456", "name": name,
        "role": "merchant"})["token"]
    shop = call("POST", "/merchants", tok, {
        "name": name, "address": "运营路 1 号", "lat": 30.6612, "lng": 104.0823,
        "license_no": f"JYOPS{random.randrange(10**9)}",
        "license_image_url": "/uploads/license-demo.jpg"})
    call("POST", f"/admin/merchants/{shop['id']}/approve", admin)
    call("PATCH", "/merchants/me", tok, {"is_open": True})
    return tok, shop


def main():
    tok, shop = new_shop(f"运营店{random.randrange(10**4)}")

    # ================= AC:菜单批量导入 =================
    rows = [
        {"名称": "招牌牛腩饭", "分类": "主食", "价格(元)": "28",
         "成本(元)": "12", "库存": "50", "描述": "十二小时慢炖",
         "标签": "招牌|微辣", "额外打包费(元)": "1"},
        {"名称": "酸梅汤", "分类": "饮品", "价格(元)": "6",
         "成本(元)": "1.5", "库存": "100"},
        {"名称": "", "价格(元)": "10"},                    # 缺名称
        {"名称": "坏行", "价格(元)": "abc"},                # 价格不是数字
        {"名称": "标签错", "价格(元)": "9", "标签": "超好吃"},  # 标签不在白名单
        {"名称": "酸梅汤", "价格(元)": "7"},                # 表格内重复
    ]
    pre = call("POST", "/merchants/me/dishes/import-preview", tok,
               {"rows": rows})
    assert pre["create"] == 2 and pre["problem"] == 4, pre
    by_name = {i["name"]: i for i in pre["items"]}
    assert "缺名称" in by_name[""]["problems"]
    assert "价格(元)不是数字" in by_name["坏行"]["problems"]
    assert any("白名单" in p for p in by_name["标签错"]["problems"])
    assert by_name["招牌牛腩饭"]["row"] == 2, "行号要能对上表格里看到的"
    print(f"✓ 导入预览:{pre['create']} 新增 / {pre['problem']} 有问题,"
          "逐行标出且不落库")

    mine_before = call("GET", "/merchants/me/dishes", tok)
    assert mine_before == [], "预览阶段绝不能写库"
    print("✓ 预览不写库(一次错表格能把整店价格改掉,必须两步)")

    res = call("POST", "/merchants/me/dishes/import", tok,
               {"items": pre["items"]})
    assert res["created"] == 2, res
    mine = call("GET", "/merchants/me/dishes", tok)
    assert len(mine) == 2, mine
    d = [x for x in mine if x["name"] == "招牌牛腩饭"][0]
    assert d["price_cents"] == 2800 and d["cost_cents"] == 1200
    assert d["packing_fee_cents"] == 100 and d["stock"] == 50
    assert set(d["badges"]) == {"招牌", "微辣"}
    # 导入的新菜默认下架:几十道菜没核对就出现在顾客面前,事后一个个下架更麻烦
    assert d["is_on_sale"] is False, "导入的新菜该默认下架等商家核对"
    assert "下架" in res["note"], res["note"]
    print("✓ 确认导入:成本/打包费/标签/库存都进去了,且**默认下架**")

    # 再导一次同名的 = 更新,不是重复建
    pre2 = call("POST", "/merchants/me/dishes/import-preview", tok,
                {"rows": [{"名称": "酸梅汤", "价格(元)": "8"}]})
    assert pre2["update"] == 1 and pre2["items"][0]["old_price_cents"] == 600
    call("POST", "/merchants/me/dishes/import", tok, {"items": pre2["items"]})
    mine = call("GET", "/merchants/me/dishes", tok)
    assert len(mine) == 2, "同名该更新而不是新增"
    assert [x for x in mine if x["name"] == "酸梅汤"][0]["price_cents"] == 800
    print("✓ 同名再导 = 更新(预览里带旧价,商家改之前看得见)")

    # ================= AD:定时改价 / 上下架 =================
    dish_id = d["id"]
    soon = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
    past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()

    bad = call("POST", "/merchants/me/dish-schedules", tok,
               {"dish_id": dish_id, "action": "price", "run_at": soon},
               expect_error=True)
    assert bad["_error"] == 422, f"改价要填新价:{bad}"
    bad = call("POST", "/merchants/me/dish-schedules", tok,
               {"dish_id": dish_id, "action": "price", "price_cents": 3200,
                "run_at": past}, expect_error=True)
    assert bad["_error"] == 422, f"过去的时间该拒(不猜他要的是明天):{bad}"
    bad = call("POST", "/merchants/me/dish-schedules", tok,
               {"dish_id": dish_id, "action": "涨价", "run_at": soon},
               expect_error=True)
    assert bad["_error"] == 422, f"动作白名单:{bad}"
    print("✓ 定时任务:改价必填新价、过去时间被拒、动作白名单")

    s1 = call("POST", "/merchants/me/dish-schedules", tok,
              {"dish_id": dish_id, "action": "price", "price_cents": 3200,
               "run_at": soon, "note": "夜宵档提价"})
    lst = call("GET", "/merchants/me/dish-schedules", tok)
    assert len(lst["items"]) == 1 and lst["items"][0]["status"] == "pending"
    assert lst["items"][0]["dish_name"] == "招牌牛腩饭"
    assert "不会补跑" in lst["note"] and "供应时段" in lst["note"], lst["note"]
    print("✓ 定时任务已排期,列表带菜名与口径说明(和供应时段区分开)")

    call("DELETE", f"/merchants/me/dish-schedules/{s1['id']}", tok)
    again = call("DELETE", f"/merchants/me/dish-schedules/{s1['id']}", tok,
                 expect_error=True)
    assert again["_error"] == 409, f"已取消的不能再取消:{again}"
    print("✓ 定时任务可取消,重复取消被拒")

    other_tok, _ = new_shop(f"路人运营店{random.randrange(10**4)}")
    steal = call("POST", "/merchants/me/dish-schedules", other_tok,
                 {"dish_id": dish_id, "action": "off", "run_at": soon},
                 expect_error=True)
    assert steal["_error"] == 404, f"不能给别人家的菜排期:{steal}"
    print("✓ 跨店排期被拒")

    # ================= AJ:顾客备注 =================
    customer = login(CUSTOMER)
    me = call("GET", "/auth/me", customer)
    ghost = call("PUT", f"/merchants/me/customers/{me['id']}/note", tok,
                 {"note": "还没下过单"}, expect_error=True)
    assert ghost["_error"] == 404, \
        f"没在本店下过单就不能记备注(否则是个任意 id 写字接口):{ghost}"
    print("✓ 只能给真在本店下过单的顾客记备注")

    # 造一单
    call("PATCH", f"/merchants/me/dishes/{dish_id}", tok,
         {"is_on_sale": True, "stock": 10})
    order = call("POST", "/orders", customer, {
        "merchant_id": shop["id"],
        "items": [{"dish_id": dish_id, "quantity": 1}],
        "address": "备注测试地址", "lat": 30.6612, "lng": 104.0823})

    bad = call("PUT", f"/merchants/me/customers/{me['id']}/note", tok,
               {"note": "加微信转账便宜点"}, expect_error=True)
    assert bad["_error"] == 422, f"备注要过敏感词:{bad}"

    call("PUT", f"/merchants/me/customers/{me['id']}/note", tok,
         {"note": "不要香菜,喜欢多辣", "tags": ["忌香菜", "重辣"]})
    got = call("GET", f"/merchants/me/customers/{me['id']}/note", tok)
    assert got["note"].startswith("不要香菜") and "忌香菜" in got["tags"]
    print("✓ 备注可记可读,过敏感词闸门")

    # **只对本店可见**:换一家店读不到
    cross = call("GET", f"/merchants/me/customers/{me['id']}/note", other_tok)
    assert cross["note"] == "" and cross["tags"] == [], \
        f"备注不跨店 —— 这是顾客的个人信息,不是商家的资产:{cross}"
    print("✓ 备注不跨店(换一家店就是干净的)")

    # ================= AK:异常订单标记(只上报,不给拉黑权) =================
    no = order["order_no"]
    bad = call("POST", f"/merchants/me/orders/{no}/flag", tok,
               {"kind": "claim", "reason": "怪"}, expect_error=True)
    assert bad["_error"] == 422, f"说明太短该拒(平台要靠它核查):{bad}"
    bad = call("POST", f"/merchants/me/orders/{no}/flag", tok,
               {"kind": "拉黑", "reason": "这个人反复索赔"}, expect_error=True)
    assert bad["_error"] == 422, f"类型白名单:{bad}"

    r = call("POST", f"/merchants/me/orders/{no}/flag", tok,
             {"kind": "claim", "reason": "同一话术在多店要求全额退款"})
    # 口径必须写在返回体里 —— 商家按下去之后不会发生任何事,
    # 不说清楚他会以为已经解决了
    assert "不会自动对这位顾客做任何处置" in r["note"], r["note"]
    assert "拉黑" in r["note"], r["note"]
    print("✓ 标记成功,且返回体明说「不会自动处置、不给拉黑权」")

    dup = call("POST", f"/merchants/me/orders/{no}/flag", tok,
               {"kind": "claim", "reason": "再标一次试试"}, expect_error=True)
    assert dup["_error"] == 409, f"同一单只能标一次:{dup}"
    print("✓ 同一单不能重复标记(重复标不会让它更成立,只会灌满队列)")

    flags = call("GET", "/merchants/me/order-flags", tok)
    assert len(flags["items"]) == 1 and flags["items"][0]["status"] == "pending"
    assert "不会自动处置" in flags["note"], flags["note"]
    print("✓ 标记列表可查进度,口径一致")

    cross = call("POST", f"/merchants/me/orders/{no}/flag", other_tok,
                 {"kind": "claim", "reason": "标别人家的单"}, expect_error=True)
    assert cross["_error"] == 404, f"不能标别人家的单:{cross}"
    print("✓ 跨店标记被拒")

    call("POST", f"/orders/{no}/transition", customer,
         {"to_status": "cancelled"})
    print("\ne2e_merchant_ops 全部通过 ✅")


if __name__ == "__main__":
    main()
