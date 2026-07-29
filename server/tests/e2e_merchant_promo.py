"""商家专属码与海报物料(#116)。

零补贴模式下商家自己带客是唯一能规模化的获客渠道,这条守住三件事:
短码稳定(重复调用不换号,换了就是一批废海报)、
短码能反查回本店、
海报上印的费率是这家店的真实费率(阶梯佣金降档后海报要跟着变)。
"""
from .util import CUSTOMER, MERCHANT, call, login


def main() -> None:
    m_token = login(MERCHANT)

    promo = call("GET", "/merchants/me/promo", token=m_token)
    code = promo["short_code"]
    assert len(code) == 6, promo
    assert not set(code) & set("IO01"), f"短码含易混字符:{code}"
    assert promo["url"].endswith(f"/s/{code}"), promo["url"]
    print(f"✓ 生成店铺短码 {code} → {promo['url']}")

    # 幂等:海报已经印出来贴墙上了,再调一次绝不能换号
    again = call("GET", "/merchants/me/promo", token=m_token)
    assert again["short_code"] == code, f"短码被重新生成:{code} → {again['short_code']}"
    print("✓ 重复调用短码不变(已印出的海报不会作废)")

    # 费率取这家店真实值,不是写死的 5%
    shop = call("GET", "/merchants/me", token=m_token)
    assert abs(promo["commission_rate"] - float(shop["commission_rate"])) < 1e-9, (
        promo["commission_rate"], shop["commission_rate"])
    assert promo["commission_rate"] <= 0.05 + 1e-9, "费率超过 5% 承诺上限"
    assert promo["shop_name"] == shop["name"], promo
    print(f"✓ 海报费率 {promo['commission_rate']:.3f} 与本店真实费率一致")

    # 短码反查:不需要登录,落地页直接用
    found = call("GET", f"/merchants/by-code/{code}")
    assert found["id"] == shop["id"], (found, shop["id"])
    assert found["name"] == shop["name"], found
    print(f"✓ 短码反查回本店:{found['name']}(id={found['id']})")

    # 大小写不敏感:顾客手打短码不该因为大小写失败
    lower = call("GET", f"/merchants/by-code/{code.lower()}")
    assert lower["id"] == shop["id"], lower
    print("✓ 小写短码同样解析成功")

    # 不存在的码给 404,不能漏成 500 或者串到别家店
    bad = call("GET", "/merchants/by-code/ZZZZZZ", expect_error=True)
    assert bad["_error"] == 404, bad
    print("✓ 不存在的短码返回 404")

    # 落地页本身:短码不存在也返回页面而不是裸 404(扫码的人看到的是人话)
    # 这里只验接口层,页面渲染在前端

    # 顾客态不该能拿到别人的推广物料
    c_token = login(CUSTOMER)
    denied = call("GET", "/merchants/me/promo", token=c_token, expect_error=True)
    assert denied["_error"] in (401, 403), denied
    print("✓ 顾客态访问商家物料被拒")

    print("\n全部通过:商家专属码与海报物料")


if __name__ == "__main__":
    main()
