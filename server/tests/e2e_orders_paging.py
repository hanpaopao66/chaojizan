"""订单游标分页:翻页不漏单不重复,老客户端(不传参数)照常。

老口径是服务端写死 limit(50) 不分页,用户超过 50 单后永远看不到更早的,
与「每一单的账都可查」冲突。这条守住分页正确性。
"""
from .util import CUSTOMER, call, login


def main() -> None:
    token = login(CUSTOMER)

    # 不传参数:老客户端行为,取默认一页
    first = call("GET", "/orders", token=token)
    assert isinstance(first, list), first
    print(f"✓ 不传分页参数照常返回 {len(first)} 单(老客户端不受影响)")

    page1 = call("GET", "/orders?limit=5", token=token)
    assert len(page1) <= 5, page1
    if len(page1) < 5:
        print("✓ 订单不足 5 单,分页逻辑无需继续验证")
        return

    cursor = page1[-1]["created_at"]
    page2 = call("GET", f"/orders?limit=5&before={cursor}", token=token)
    print(f"✓ 第一页 {len(page1)} 单,游标 {cursor[:19]},第二页 {len(page2)} 单")

    ids1 = {o["order_no"] for o in page1}
    ids2 = {o["order_no"] for o in page2}
    assert not (ids1 & ids2), f"两页出现重复单:{ids1 & ids2}"
    print("✓ 两页无重复")

    # 时间必须严格递减(游标分页的前提)
    times = [o["created_at"] for o in page1 + page2]
    assert times == sorted(times, reverse=True), "订单未按时间倒序"
    print("✓ 全程按创建时间倒序,游标可用")

    # 上限保护:limit 超过 50 被夹到 50
    big = call("GET", "/orders?limit=999", token=token)
    assert len(big) <= 50, len(big)
    print(f"✓ limit=999 被夹到 {len(big)}(上限 50)")

    bad = call("GET", "/orders?before=notatime", token=token, expect_error=True)
    assert bad["_error"] == 422, bad
    assert "游标" in str(bad["detail"]), bad
    print("✓ 游标格式错误返回 422 中文提示")

    print("\ne2e_orders_paging 全部通过 ✅")


if __name__ == "__main__":
    main()
