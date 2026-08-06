"""连锁店群(第八/九批):品牌、跨店权限、门店选择。

这套用例的重点是**权限**,不是功能。连锁把"一号一店"这个贯穿全库
80 多处调用点的假设拆了,拆错的后果不是页面不好看,是 A 店的区域经理
能改 B 店的价、能看 B 店的钱。所以每条正向断言后面都跟一条越权断言。

另外守两条业务红线:
- 同品牌新门店的证照**不能复用**(食品经营许可证按门店核发,复用即违法);
- 新店不抄库存(抄了等于一开门就超卖)。
"""
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from .util import call  # noqa: E402


def new_merchant(name: str):
    """注册一个全新的商家账号,返回 (token, phone)。"""
    phone = f"1{random.choice('3589')}{random.randrange(10**8, 10**9)}"
    token = call("POST", "/auth/register", body={
        "phone": phone, "password": "123456", "name": name,
        "role": "merchant"})["token"]
    return token, phone


def main():
    boss, boss_phone = new_merchant("连锁老板")
    shop1 = call("POST", "/merchants", boss, {
        "name": "赞小碗-总店", "description": "e2e 连锁",
        "address": "连锁路 1 号", "lat": 30.66, "lng": 104.08,
        "license_no": f"JYCHAIN{random.randrange(10**9)}",
        "license_image_url": "/uploads/license-demo.jpg"})
    print(f"✓ 开出第一家店 #{shop1['id']}")
    call("POST", "/merchants/me/dishes", boss, {
        "name": "招牌小碗", "price_cents": 1200, "stock": 50,
        "category": "主食"})

    # ---- 单店商家零感知:没建品牌时 brand=null,但 shops 照给 ----
    # (门店选择器用同一份数据,单店商家拿到一个元素的列表,不用分支)
    r = call("GET", "/brands/me", boss)
    assert r["brand"] is None and len(r["shops"]) == 1, r
    print("✓ 未建品牌时 brand=null、shops 仍有一家(选择器数据源统一)")

    # 品牌名与新门店名都是新增的用户自由文本,必须过敏感词闸门
    bad = call("POST", "/brands/me", boss,
               {"name": "加微信转账便宜点", "shop_id": shop1["id"]},
               expect_error=True)
    assert bad["_error"] == 422, f"品牌名要过敏感词:{bad}"
    print("✓ 品牌名过敏感词闸门")

    brand = call("POST", "/brands/me", boss,
                 {"name": f"赞小碗{random.randrange(10**4)}",
                  "shop_id": shop1["id"]})
    print(f"✓ 建品牌「{brand['name']}」并把首店并入")

    # ---- 红线一:新门店证照不能复用 ----
    bad = call("POST", "/brands/me/shops", boss, {
        "copy_from": shop1["id"], "name": "赞小碗-二店",
        "address": "连锁路 2 号", "lat": 30.67, "lng": 104.09,
    }, expect_error=True)
    assert bad["_error"] == 422 and "证照" in bad["detail"], bad
    print("✓ 新门店不交证照被拒(许可证按门店核发,不能复用总部的)")

    dirty = call("POST", "/brands/me/shops", boss, {
        "copy_from": shop1["id"], "name": "加微信转账便宜点",
        "address": "连锁路 2 号", "lat": 30.67, "lng": 104.09,
        "license_no": "JYX1", "license_image_url": "/uploads/x.jpg",
    }, expect_error=True)
    assert dirty["_error"] == 422, f"新门店名要过敏感词:{dirty}"
    print("✓ 新门店名过敏感词闸门")

    shop2 = call("POST", "/brands/me/shops", boss, {
        "copy_from": shop1["id"], "name": "赞小碗-二店",
        "address": "连锁路 2 号", "lat": 30.67, "lng": 104.09,
        "license_no": f"JYCHAIN{random.randrange(10**9)}",
        "license_image_url": "/uploads/license-demo-2.jpg"})
    assert shop2["status"] == "pending", \
        f"新店必须照走审核,不能因为是连锁就免审:{shop2}"
    print(f"✓ 二店 #{shop2['id']} 建成,状态 pending(照走人工核验)")

    h1 = {"X-Shop-Id": shop1["id"]}
    h2 = {"X-Shop-Id": shop2["id"]}

    # ---- 红线二:抄菜单不抄库存 ----
    got = call("GET", f"/merchants/{shop2['id']}/dishes", boss)
    items = got if isinstance(got, list) else got.get("items", [])
    assert items, "二店应当抄到总店的菜单"
    assert all(d.get("stock", 0) == 0 for d in items), \
        f"新店抄了库存 = 一开门就超卖:{items[:2]}"
    assert any(d["name"] == "招牌小碗" for d in items), items
    print(f"✓ 二店抄到 {len(items)} 个菜品,库存全为 0(不抄库存)")

    # ---- 切店之后改的必须是选中的那家 ----
    # 这条守的是一个静默数据损坏:老写法 db.scalar(...owner_id==我)
    # 不带 ORDER BY,连锁老板名下两家店时返回哪家由数据库决定 ——
    # 表现是"切到二店改了价,保存成功,总店的价变了"。
    mine2 = call("GET", "/merchants/me/dishes", boss, headers=h2)
    d2 = [d for d in mine2 if d["name"] == "招牌小碗"][0]
    call("PATCH", f"/merchants/me/dishes/{d2['id']}", boss,
         {"price_cents": 1900}, headers=h2)
    mine1 = call("GET", "/merchants/me/dishes", boss, headers=h1)
    d1 = [d for d in mine1 if d["name"] == "招牌小碗"][0]
    assert d1["price_cents"] == 1200, \
        f"改的是二店的价,总店不该跟着变(选中门店没生效):{d1}"
    after2 = call("GET", "/merchants/me/dishes", boss, headers=h2)
    assert [d for d in after2 if d["id"] == d2["id"]][0]["price_cents"] == 1900
    print("✓ 切店后改价只落在选中的门店(总店不受影响)")

    # ---- 门店选择:X-Shop-Id 头切店 ----
    a = call("GET", "/merchants/me", boss, headers=h1)
    b = call("GET", "/merchants/me", boss, headers=h2)
    assert a["id"] == shop1["id"] and b["id"] == shop2["id"], (a, b)
    print("✓ X-Shop-Id 切店生效(同一个端点、同一个账号,拿到不同门店)")

    shops = call("GET", "/brands/me/overview", boss)
    assert shops["total"]["shops"] == 2, shops
    print(f"✓ 总部概览:{shops['total']['shops']} 家店")

    # ---- 越权:伪造别人家的 X-Shop-Id 拿不到东西 ----
    outsider, outsider_phone = new_merchant("路人商家")
    other = call("POST", "/merchants", outsider, {
        "name": "路人小店", "address": "别处 9 号", "lat": 31.2, "lng": 121.4,
        "license_no": f"JYOTHER{random.randrange(10**9)}",
        "license_image_url": "/uploads/license-demo.jpg"})
    stolen = call("GET", "/merchants/me", boss,
                  headers={"X-Shop-Id": other["id"]}, expect_error=True)
    assert stolen.get("_error") in (403, 404), \
        f"X-Shop-Id 只是「选哪家」不是「有权限」,伪造别家 id 必须拿不到:{stolen}"
    print("✓ 伪造他人门店 id 被拒(头是选择,权限另判)")

    # ---- 区域经理:只能管授权范围内的店 ----
    mgr, mgr_phone = new_merchant("区域经理")
    nobody = call("POST", "/brands/me/members", boss,
                  {"phone": "19900000000", "shop_ids": [shop1["id"]]},
                  expect_error=True)
    assert nobody["_error"] == 404, nobody
    print("✓ 未注册的手机号不能加成员(不替人开账号)")

    cross = call("POST", "/brands/me/members", boss,
                 {"phone": mgr_phone, "shop_ids": [other["id"]]},
                 expect_error=True)
    assert cross["_error"] == 422, f"不能把别家的店授权出去:{cross}"
    print("✓ 授权门店必须是本品牌的店")

    call("POST", "/brands/me/members", boss,
         {"phone": mgr_phone, "shop_ids": [shop2["id"]]})
    members = call("GET", "/brands/me/members", boss)
    assert len(members) == 1 and members[0]["shop_ids"] == [shop2["id"]]
    assert "****" in members[0]["phone"], f"成员手机号要打码:{members[0]}"
    print("✓ 区域经理已授权,仅管二店;列表里手机号打码")

    ok = call("GET", "/merchants/me", mgr, headers=h2)
    assert ok["id"] == shop2["id"], ok
    print("✓ 区域经理能操作授权范围内的二店")

    denied = call("GET", "/merchants/me", mgr, headers=h1, expect_error=True)
    assert denied.get("_error") in (403, 404), \
        f"授权范围只有二店,总店必须拒:{denied}"
    print("✓ 区域经理访问未授权的总店被拒")

    # 不带头时不猜:连锁下"我的店"有歧义,必须让客户端显式选
    ambiguous = call("GET", "/merchants/me", mgr, expect_error=True)
    assert ambiguous.get("_error") in (403, 404), \
        f"品牌成员不指定门店时不该猜一家给他:{ambiguous}"
    print("✓ 品牌成员不选店时不猜(强制走门店选择器)")

    # ---- 钱只走店主本人:区域经理碰不到钱包和提现 ----
    #
    # 这是连锁里最贵的一条边界。钱包余额按 merchant_id 算(整店营收),
    # 已提现按 user_id 减 —— 两个 id 不是同一个人的话同时出两个洞:
    # 经理能把整店余额提到自己的收款账户,而且店主已提走的部分不计入
    # 经理的可提额度,两个人各提一次全额。
    for path in ("/merchants/me/wallet", "/merchants/me/withdrawals"):
        r = call("GET", path, mgr, headers=h2, expect_error=True)
        assert r.get("_error") == 403, f"{path} 不该对区域经理开放:{r}"
    r = call("POST", "/merchants/me/withdrawals", mgr,
             {"amount_cents": 10000}, headers=h2, expect_error=True)
    assert r.get("_error") == 403, f"区域经理不能提现:{r}"
    print("✓ 区域经理拿不到钱包/提现(运营授权 ≠ 能动钱)")

    # 店主本人照常(这条防"修狠了把店主也拦了")
    w = call("GET", "/merchants/me/wallet", boss, headers=h2)
    assert "withdrawable_cents" in w, w
    print("✓ 店主本人的钱包照常可见")

    # ---- 成员看不到成员列表(组织信息只对品牌所有者) ----
    peek = call("GET", "/brands/me/members", mgr, expect_error=True)
    assert peek["_error"] == 403, peek
    print("✓ 区域经理看不到成员列表")

    # ---- 移除后立即失权 ----
    call("DELETE", f"/brands/me/members/{members[0]['id']}", boss)
    after = call("GET", "/merchants/me", mgr, headers=h2, expect_error=True)
    assert after.get("_error") in (403, 404), \
        f"移出品牌后必须立即失去门店权限:{after}"
    print("✓ 移出品牌后立即失权")

    # ---- 外人不能借品牌接口伸手 ----
    steal = call("POST", "/brands/me/shops", outsider, {
        "copy_from": shop1["id"], "name": "蹭牌店",
        "address": "别处 9 号", "lat": 31.2, "lng": 121.4,
        "license_no": "JY000", "license_image_url": "/uploads/x.jpg"},
        expect_error=True)
    assert steal.get("_error") in (403, 422), steal
    print("✓ 外部商家不能往别人品牌下开店")

    # ================= AA:总部统一下发营销 =================
    #
    # 红线:券的成本 funder=merchant、由**发券的那家门店**全额承担。
    # 所以各店各建批次、各出各的 —— 建一个"品牌级批次"让几家店共用预算,
    # 就变成"我店的钱被别店花了",门店对不上自己那份账。
    call("PATCH", "/merchants/me", boss,
         {"promo_rules": [{"threshold_cents": 3000, "off_cents": 500}]},
         headers=h1)
    r = call("POST", "/brands/me/promo-sync", boss,
             {"from_shop": shop1["id"], "to_shops": [shop2["id"]]})
    assert r["rules"] == 1 and len(r["shops"]) == 1, r
    got = call("GET", "/merchants/me", boss, headers=h2)
    assert got["promo_rules"] == [
        {"threshold_cents": 3000, "off_cents": 500}], got["promo_rules"]
    print("✓ 满减下发到目标门店")

    # 下发之后门店仍可自己改 —— 满减的钱是门店出的,最终决定权在他们
    call("PATCH", "/merchants/me", boss,
         {"promo_rules": [{"threshold_cents": 5000, "off_cents": 300}]},
         headers=h2)
    still = call("GET", "/merchants/me", boss, headers=h1)
    assert still["promo_rules"][0]["threshold_cents"] == 3000, \
        f"门店改自己的不该反向影响源门店:{still['promo_rules']}"
    print("✓ 下发后门店可自行调整,不回写源门店")

    cross = call("POST", "/brands/me/promo-sync", boss,
                 {"from_shop": shop1["id"], "to_shops": [other["id"]]},
                 expect_error=True)
    assert cross["_error"] == 422, f"不能下发到别人家的店:{cross}"
    print("✓ 下发目标必须是本品牌的店")

    bad = call("POST", "/brands/me/coupon-sync", boss, {
        "name": "加微信转账便宜点", "to_shops": [shop1["id"]],
        "threshold_cents": 3000, "off_cents": 500, "total": 100},
        expect_error=True)
    assert bad["_error"] == 422, f"券名要过敏感词:{bad}"
    bad = call("POST", "/brands/me/coupon-sync", boss, {
        "name": "开业券", "to_shops": [shop1["id"]],
        "threshold_cents": 500, "off_cents": 500, "total": 100},
        expect_error=True)
    assert bad["_error"] == 422, f"面额不小于门槛该拦(倒贴):{bad}"

    cs = call("POST", "/brands/me/coupon-sync", boss, {
        "name": f"开业券{random.randrange(10**4)}",
        "to_shops": [shop1["id"], shop2["id"]],
        "threshold_cents": 3000, "off_cents": 500,
        "total": 100, "valid_days": 14})
    assert len(cs["shops"]) == 2 and cs["total_per_shop"] == 100, cs
    assert "各自承担成本" in cs["note"], cs
    b1 = call("GET", "/merchants/me/coupon-batches", boss, headers=h1)
    b2 = call("GET", "/merchants/me/coupon-batches", boss, headers=h2)
    n1 = [b for b in b1 if b["name"].startswith("开业券")][0]
    n2 = [b for b in b2 if b["name"].startswith("开业券")][0]
    assert n1["id"] != n2["id"], "必须是两个独立批次,不是共用一个"
    assert n1["total"] == 100 and n2["total"] == 100, \
        "每家各 100 张,不是两家分 100 张"
    print("✓ 券下发:各店各建独立批次、各发 100 张各自承担成本")

    # ================= AB:多门店合并对账 =================
    fin = call("GET", "/brands/me/finance?days=30", boss)
    assert len(fin["shops"]) == 2, fin
    assert "资金仍按门店结算" in fin["note"], fin["note"]
    assert set(fin["total"]) == {"orders", "gross_cents",
                                "commission_cents", "net_cents"}, fin["total"]
    print(f"✓ 跨店对账汇总:{len(fin['shops'])} 家门店并排(只读,不做品牌钱包)")

    # 区域经理碰不到钱 —— 与 money_shop 同一条边界
    call("POST", "/brands/me/members", boss,
         {"phone": mgr_phone, "shop_ids": [shop2["id"]]})
    denied = call("GET", "/brands/me/finance", mgr, expect_error=True)
    assert denied["_error"] == 403, f"跨店对账只对品牌所有者:{denied}"
    print("✓ 区域经理看不到跨店对账(与提现/钱包同一条边界)")

    steal = call("GET", "/brands/me/finance", outsider, expect_error=True)
    assert steal.get("_error") in (403, 404), steal
    print("✓ 外部商家拿不到本品牌对账")

    print("\ne2e_chain_stores 全部通过 ✅")


if __name__ == "__main__":
    main()
