"""外部依赖体检(#131)。

这条守的是「降级要可见」:JPush、隐私号、身份证核验这些集成早就写好且
能优雅降级 —— 问题是降级了没人知道。骑手新单推送做完验收全绿,
而生产上 JPUSH 没配、一条都发不出去,就是这么发生的。
"""
from .util import ADMIN, CUSTOMER, MERCHANT, call, login


def main() -> None:
    a = login(ADMIN)
    r = call("GET", "/admin/readiness", token=a)

    assert r["total"] >= 10, r
    assert r["configured"] + r["missing"] == r["total"], r
    print(f"✓ 体检 {r['total']} 项:已配置 {r['configured']} / 未配置 {r['missing']}")

    keys = {i["key"] for i in r["items"]}
    for must in ("payment_wechat", "mock_pay_disabled", "jpush",
                 "privacy_phone", "idcheck", "storage_minio"):
        assert must in keys, f"体检漏了 {must}"
    print("✓ 关键项齐全(支付/模拟支付/推送/隐私号/实名/存储)")

    # 每一项都得说清降级成什么、影响谁 —— 只报 true/false 没有意义
    for it in r["items"]:
        assert it["degraded_behavior"].strip(), it
        assert it["affects"].strip(), it
    print("✓ 每项都写明了降级行为与影响范围")

    # 体检本身包含配置状态,不能对外
    for token, who in ((None, "匿名"), (login(CUSTOMER), "顾客"),
                       (login(MERCHANT), "商家")):
        e = call("GET", "/admin/readiness", token=token, expect_error=True)
        assert e["_error"] in (401, 403), (who, e)
    print("✓ 匿名/顾客/商家访问体检接口均被拒")

    print("\n全部通过:外部依赖体检")


if __name__ == "__main__":
    main()
