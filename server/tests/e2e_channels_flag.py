"""首页显示哪些业务:后台改,用户端立即拿到,不用发版。

## 这条守什么

「这次先只上外卖和团购」这种决定会反复变。编译期常量意味着每变一次
发一版 App、等审核三天 —— 所以做成后台开关。

而开关的意义全在**闭环**上:管理员在后台点一下,用户端下一次拉就变了。
中间任何一段没接上(白名单漏了这个键、公开接口没读它、校验把合法值拦了),
表现都是「我在后台点了,App 没反应」,而那从任何单侧都看不出来。

在 server/ 目录下运行:python -m tests.e2e_channels_flag
"""
from tests.util import ADMIN, call, login

admin = login(ADMIN)


def visible() -> list:
    """用户端看到的 —— **不带 token**,首页在登录前就要画出来。"""
    return call("GET", "/channels")["enabled"]


def set_channels(v: str):
    return call("POST", "/admin/flags/channels_enabled", admin,
                {"value": v, "reason": "e2e"})


def main() -> None:
    before = ",".join(call("GET", "/admin/flags", admin)["channels_enabled"]
                      .split(","))
    try:
        # ---------- 1) 公开可读,不需要登录 ----------
        got = visible()
        assert isinstance(got, list), f"/channels 返回的不是列表:{got}"
        print(f"✓ 不登录就能读到频道配置:{got}")

        # ---------- 2) 后台改,用户端立即变 ----------
        set_channels("food,voucher")
        assert visible() == ["food", "voucher"], visible()
        print("✓ 后台设成「外卖+团购」,用户端立刻只剩这两个")

        set_channels("food,stay,voucher,errand")
        assert visible() == ["food", "stay", "voucher", "errand"]
        print("✓ 全开也立刻生效")

        # ---------- 3) 「全关」和「没配过」是两件事 ----------
        #
        # 判据是「有没有这一行」,不是「值是不是空的」——
        # 否则管理员想全关的时候会拿到兜底那两个,而他以为自己关掉了。
        set_channels("")
        assert visible() == [], (
            f"设成空却返回 {visible()} —— 管理员想全关,系统给了兜底,"
            f"而他以为自己关掉了")
        print("✓ 全关就是全关(不回落到兜底)")

        # ---------- 4) 打错的 key 在入口就拦 ----------
        #
        # 不拦的话:那个频道从首页静默消失,而后台显示得好好的。
        err = call("POST", "/admin/flags/channels_enabled", admin,
                   {"value": "food,waimai", "reason": "e2e"},
                   expect_error=True)
        assert err["_error"] == 422 and "waimai" in err.get("detail", ""), (
            f"打错的频道名没被拦:{err}")
        print("✓ 不认识的频道名 422,并且指名道姓说是哪个错了")

        # 拦下来之后配置不能被改坏
        assert visible() == [], "校验失败却把配置改了"
        print("✓ 校验失败不落库")

        # ---------- 5) 顾客改不了 ----------
        customer = login("13800000001")
        err = call("POST", "/admin/flags/channels_enabled", customer,
                   {"value": "food", "reason": "试试"}, expect_error=True)
        assert err["_error"] == 403
        print("✓ 非管理员改不了(403)")
    finally:
        set_channels(before)
        print(f"✓ 已还原为 {before}")

    print("\ne2e_channels_flag 全部通过 ✅")


if __name__ == "__main__":
    main()
