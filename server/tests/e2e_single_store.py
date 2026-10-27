"""单门店版显示哪家店:后台「平台开关」的 single_store_merchant_id → /config 的 single_store.merchant_id。

应用商店里的用户端是单门店版(packages/shared/lib/src/edition.dart),打开就是这家店的点菜页。
- 没配是 null(客户端说「门店信息加载失败」,不猜一家顶上);
- 填的不是数字、店不存在,当场 422 —— 填错的后果是审核员打开商店包看到加载失败;
- 填一家审核通过的外卖店,/config 照原样下发;清空回到 null;
- 只有管理员能改;
- 顾客的订单列表、订单计数能按店过滤(单门店版只列这一家的单),不传就是原样。

    SUPERZ_API=http://127.0.0.1:8013 python -m tests.e2e_single_store
"""
from tests.util import ADMIN, DEMO_SHOP_ID, call, login


def main() -> None:
    admin = login(ADMIN)
    before = call("GET", "/admin/flags", admin).get("single_store_merchant_id", "")
    try:
        call("POST", "/admin/flags/single_store_merchant_id", admin, {"value": ""})
        assert call("GET", "/config")["single_store"] == {"merchant_id": None}
        print("✓ 没配时下发 null")

        for bad, why in (("张记面馆", "填商家 id"), ("99999999", "没有 id 为")):
            r = call("POST", "/admin/flags/single_store_merchant_id", admin, {"value": bad},
                     expect_error=True)
            assert r["_error"] == 422 and why in str(r), r
        assert call("GET", "/config")["single_store"]["merchant_id"] is None
        print("✓ 不是数字、店不存在:当场 422,配置不变")

        call("POST", "/admin/flags/single_store_merchant_id", admin,
             {"value": f" {DEMO_SHOP_ID} ", "reason": "e2e 测试"})
        assert call("GET", "/config")["single_store"]["merchant_id"] == DEMO_SHOP_ID
        assert call("GET", "/admin/flags", admin)["single_store_merchant_id"] == str(DEMO_SHOP_ID)
        print("✓ 填一家审核通过的外卖店:/config 照原样下发")

        customer = login("13800000001")
        r = call("POST", "/admin/flags/single_store_merchant_id", customer, {"value": ""},
                 expect_error=True)
        assert r["_error"] == 403, r
        assert call("GET", "/config")["single_store"]["merchant_id"] == DEMO_SHOP_ID
        print("✓ 只有管理员能改")

        mine = call("GET", f"/orders?limit=50&merchant_id={DEMO_SHOP_ID}", customer)
        assert all(o["merchant_id"] == DEMO_SHOP_ID for o in mine), mine[:3]
        assert call("GET", "/orders?merchant_id=99999999", customer) == []
        assert len(call("GET", "/orders?limit=50", customer)) >= len(mine)
        counts = call("GET", "/orders/counts?merchant_id=99999999", customer)
        assert counts["food"] == [] and counts["stay"]["total"] == 0, counts
        whole = call("GET", "/orders/counts", customer)
        assert "stay" in whole and isinstance(whole["food"], list)
        print("✓ 订单列表、订单计数按店过滤;不传照旧是全部")
    finally:
        call("POST", "/admin/flags/single_store_merchant_id", admin,
             {"value": before, "reason": "e2e 复原"})
    print("e2e_single_store 全部通过 ✅")


if __name__ == "__main__":
    main()
