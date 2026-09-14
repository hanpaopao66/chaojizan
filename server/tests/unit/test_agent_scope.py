"""AI 助手令牌的能力范围:**默认拒绝**,而且付不了钱。

## 这一组守什么

「点单」意味着一个自动化程序能花用户的钱。整个设计押在一句话上:

    助手能创建待支付订单,但**付款那一下在人手里**。

这句话成立的前提是白名单严丝合缝。所以这里逐条钉住:
支付、退款、改地址、提现、申诉一个都进不去,而且**新加的接口默认进不去** ——
黑名单要求每加一个接口就有人记得去禁它,忘一次就是一条没人看守的路。

## 为什么大量测试写在路径这一层

范围检查在 `get_current_user` 里按 (方法, 路径) 判,不看路由函数。
所以判据本身就是路径 —— 在这一层测,和线上跑的是同一套逻辑。
"""
import pytest

from app.security import (AGENT_COMMON, AGENT_MINIAPP, AGENT_ORDER, AGENT_SCOPES,
                          AGENT_SCOPES_BY_ROLE, AGENT_VIDEO, agent_can)

#: 所有权限都勾上 —— 「付款进不去」这类要对**任何**令牌都成立
ALL = tuple(AGENT_SCOPES)
VID = "sv2BcDeFgHiJ"
APPID = "sz0123456789abcdef"
UP = "0" * 32


class Test付款一律进不去:
    """整个设计的支点。这几条红了,「令牌泄露也花不掉钱」就不成立。"""

    @pytest.mark.parametrize("path", [
        "/orders/abc123/pay/mock",
        "/orders/abc123/pay",
        "/orders/abc123/pay/wechat",
        "/payments/wechat/notify",
        "/vouchers/1/purchase",
        "/vouchers/purchases/abc/pay/mock",
    ])
    def test_支付类路径被拒(self, path):
        assert not agent_can("POST", path, ALL), (
            f"助手能调 {path} —— 它就能花用户的钱,"
            f"而这个令牌的全部意义就是「花不掉」")


class Test动钱和动身份的都进不去:
    @pytest.mark.parametrize("method,path", [
        ("POST", "/orders/abc/self-refund"),
        ("POST", "/orders/abc/refund-item"),
        ("POST", "/orders/abc/cancel-with-split"),
        ("POST", "/orders/abc/change-address"),
        ("POST", "/orders/abc/transition"),
        ("POST", "/appeals"),
        ("POST", "/addresses"),
        ("PATCH", "/addresses/1"),
        ("DELETE", "/addresses/1"),
        ("POST", "/payout/withdrawals"),
        ("POST", "/auth/agent-tokens"),      # 助手不能给自己再发一个令牌
        ("DELETE", "/auth/agent-tokens/1"),
        ("POST", "/reviews"),
        ("POST", "/tickets"),
        ("POST", "/queue/merchants/1/take"),
    ])
    def test_写操作一律被拒(self, method, path):
        assert not agent_can(method, path, ALL), f"{method} {path} 不该对助手开放"


class Test能做的那几件:
    @pytest.mark.parametrize("method,path", [
        ("GET", "/auth/me"),
        ("GET", "/merchants"),
        ("GET", "/merchants/search"),
        ("GET", "/merchants/1"),
        ("GET", "/merchants/1/dishes"),
        ("GET", "/orders"),
        ("GET", "/orders/cb765cbdc6a14181974b"),
        ("GET", "/orders/delivery-fee"),
        ("GET", "/transparency/liability"),
        ("POST", "/orders"),                 # ← 创建待支付订单,到此为止
    ])
    def test_放行(self, method, path):
        assert agent_can(method, path)


class Test默认拒绝:
    """白名单的意义:**新接口自动不开放**。"""

    @pytest.mark.parametrize("method,path", [
        ("GET", "/riders/available-orders"),
        ("GET", "/admin/dashboard"),
        ("GET", "/merchants/me/order-flags"),
        ("GET", "/payout/account"),
        ("POST", "/some/brand/new/endpoint"),
        ("PUT", "/orders"),                  # 方法不对也不行
        ("DELETE", "/orders"),
    ])
    def test_没列进白名单的一律拒(self, method, path):
        assert not agent_can(method, path, ALL)

    def test_不认识的权限什么都不放(self):
        assert not agent_can("POST", "/orders", ("admin",))
        assert not agent_can("GET", "/merchants", ())
        assert agent_can("GET", "/auth/me", ())   # 「我是谁」谁都能问

    @pytest.mark.parametrize("name,rules,cap", [
        ("order", AGENT_ORDER, 10), ("video", AGENT_VIDEO, 12), ("miniapp", AGENT_MINIAPP, 16),
        ("common", AGENT_COMMON, 2)])
    def test_白名单本身很短(self, name, rules, cap):
        """短是刻意的。每加一条都要能说出「为什么助手需要它」。"""
        assert len(rules) <= cap, (
            f"助手的「{name}」白名单涨到了 {len(rules)} 条 —— "
            f"每一条都是一个自动化程序能碰的地方,加之前先问为什么")

    def test_点餐的写操作只有一条(self):
        writes = [(m, p) for m, p in AGENT_ORDER + AGENT_COMMON if m != "GET"]
        assert writes == [("POST", "/orders")], (
            f"点餐助手的写操作不止「创建订单」一条:{writes} —— "
            f"每多一条,「付款在人手里」这句话就松一分")

    def test_发视频的写操作逐条钉住(self):
        """建稿、改稿、挂原片、提审,加上传文件的四步。没有删、没有申诉、没有对别人做事的"""
        writes = sorted((m, p) for m, p in AGENT_VIDEO if m != "GET")
        assert writes == sorted([
            ("POST", r"/video/v1/uploads/videos"),
            ("PATCH", r"/video/v1/videos/sv[1-9A-HJ-NP-Za-km-z]{10}"),
            ("POST", r"/video/v1/videos/sv[1-9A-HJ-NP-Za-km-z]{10}/parts"),
            ("POST", r"/video/v1/videos/sv[1-9A-HJ-NP-Za-km-z]{10}/submit"),
            ("POST", r"/media/v1/uploads"),
            ("PUT", r"/media/v1/uploads/[0-9a-f]{32}/chunks/\d+"),
            ("POST", r"/media/v1/uploads/[0-9a-f]{32}/complete"),
            ("POST", r"/media/v1/upload"),
        ]), f"发视频助手的写操作变了:{writes} —— 加之前先问:删了回不来吗?是在以用户的名义对别人做事吗?"

    def test_发布小程序的写操作逐条钉住(self):
        """建应用、改信息、传包、体验版、提审、撤回、发布、回滚。没有下架删除、密钥、域名、实名、协议"""
        writes = sorted((m, p) for m, p in AGENT_MINIAPP if m != "GET")
        base = r"/dev/v1/apps/sz[0-9a-f]{16}"
        assert writes == sorted([
            ("POST", r"/dev/v1/apps"),
            ("PUT", base),
            ("POST", base + "/versions"),
            ("POST", base + r"/versions/\d+/trial"),
            ("POST", base + r"/versions/\d+/submit"),
            ("POST", base + r"/versions/\d+/withdraw"),
            ("POST", base + r"/versions/\d+/release"),
            ("POST", base + "/rollback"),
        ]), f"发布小程序助手的写操作变了:{writes}"


class Test权限之间不串:
    """只勾了「发视频」的令牌泄露了,对方下不了单;反过来也一样。"""

    @pytest.mark.parametrize("method,path", [
        ("POST", "/orders"), ("GET", "/orders"), ("GET", "/merchants/search")])
    def test_发视频和发小程序的令牌碰不了点餐(self, method, path):
        assert not agent_can(method, path, ("video",))
        assert not agent_can(method, path, ("miniapp",))

    @pytest.mark.parametrize("method,path", [
        ("POST", "/video/v1/uploads/videos"), ("POST", "/media/v1/uploads"),
        ("POST", f"/video/v1/videos/{VID}/submit")])
    def test_点餐和发小程序的令牌碰不了投稿(self, method, path):
        assert not agent_can(method, path, ("order",))
        assert not agent_can(method, path, ("miniapp",))

    @pytest.mark.parametrize("method,path", [
        ("POST", "/dev/v1/apps"), ("POST", f"/dev/v1/apps/{APPID}/versions/3/release")])
    def test_点餐和发视频的令牌碰不了开发者后台(self, method, path):
        assert not agent_can(method, path, ("order", "video"))

    def test_账号类型决定能勾哪几项(self):
        assert AGENT_SCOPES_BY_ROLE == {"customer": ("order", "video"), "developer": ("miniapp",)}
        assert set(AGENT_SCOPES) == {"order", "video", "miniapp"}


class Test发视频能做的与不能做的:
    @pytest.mark.parametrize("method,path", [
        ("GET", "/video/v1/zones"),
        ("POST", "/video/v1/uploads/videos"),
        ("PATCH", f"/video/v1/videos/{VID}"),
        ("POST", f"/video/v1/videos/{VID}/parts"),
        ("POST", f"/video/v1/videos/{VID}/submit"),
        ("GET", "/video/v1/creator/videos"),
        ("GET", f"/video/v1/creator/videos/{VID}"),
        ("POST", "/media/v1/uploads"),
        ("GET", f"/media/v1/uploads/{UP}"),
        ("PUT", f"/media/v1/uploads/{UP}/chunks/0"),
        ("POST", f"/media/v1/uploads/{UP}/complete"),
        ("POST", "/media/v1/upload"),
    ])
    def test_放行(self, method, path):
        assert agent_can(method, path, ("video",))

    @pytest.mark.parametrize("method,path", [
        ("DELETE", f"/video/v1/videos/{VID}"),                 # 删稿:删了回不来
        ("DELETE", f"/video/v1/videos/{VID}/parts/1"),
        ("POST", f"/video/v1/videos/{VID}/appeal"),            # 申诉:判断留给人
        ("DELETE", f"/video/v1/videos/{VID}/changes"),
        ("POST", f"/video/v1/videos/{VID}/like"),              # 以你的名义对别人做事
        ("POST", f"/video/v1/videos/{VID}/coin"),
        ("POST", f"/video/v1/videos/{VID}/comments"),
        ("POST", "/video/v1/parts/1/danmaku"),
        ("POST", "/video/v1/users/2/follow"),
        ("POST", "/video/v1/reports"),
        ("PATCH", "/video/v1/me/settings"),
        ("GET", "/video/v1/me/history"),                      # 观看记录:和投稿无关的隐私
        ("GET", "/media/v1/files/1"),                         # 读别的媒体文件
        ("POST", "/chat/v1/chats/1/messages"),                # 发消息
        ("PATCH", "/video/v1/videos/sv2BcDeFgHiJ/../../me/settings"),
    ])
    def test_拒绝(self, method, path):
        assert not agent_can(method, path, ("video",))


class Test发布小程序能做的与不能做的:
    @pytest.mark.parametrize("method,path", [
        ("GET", "/dev/v1/me"),
        ("GET", "/dev/v1/apps"),
        ("POST", "/dev/v1/apps"),
        ("PUT", f"/dev/v1/apps/{APPID}"),
        ("POST", f"/dev/v1/apps/{APPID}/versions"),
        ("GET", f"/dev/v1/apps/{APPID}/versions/12"),
        ("POST", f"/dev/v1/apps/{APPID}/versions/12/trial"),
        ("POST", f"/dev/v1/apps/{APPID}/versions/12/submit"),
        ("POST", f"/dev/v1/apps/{APPID}/versions/12/withdraw"),
        ("POST", f"/dev/v1/apps/{APPID}/versions/12/release"),
        ("POST", f"/dev/v1/apps/{APPID}/rollback"),
        ("GET", f"/dev/v1/apps/{APPID}/decisions"),
    ])
    def test_放行(self, method, path):
        assert agent_can(method, path, ("miniapp",))

    @pytest.mark.parametrize("method,path", [
        ("POST", f"/dev/v1/apps/{APPID}/secret/rotate"),       # 密钥
        ("POST", f"/dev/v1/apps/{APPID}/secret/activate"),
        ("PUT", f"/dev/v1/apps/{APPID}/domains"),              # 域名
        ("POST", f"/dev/v1/apps/{APPID}/remove"),              # 删除应用
        ("POST", f"/dev/v1/apps/{APPID}/offline"),
        ("POST", f"/dev/v1/apps/{APPID}/capabilities"),
        ("POST", f"/dev/v1/apps/{APPID}/testers"),             # 体验者是别人的手机号
        ("PUT", f"/dev/v1/apps/{APPID}/auto-release"),
        ("POST", "/dev/v1/me/verify/individual"),              # 实名
        ("POST", "/dev/v1/me/agreement"),                      # 签协议
        ("PUT", "/dev/v1/me/profile"),
        ("POST", "/dev/v1/decisions/1/appeal"),
        ("POST", f"/dev/v1/apps/{APPID}/sim/launch"),
        ("POST", "/dev/v1/apps/SZ0123456789ABCDEF/versions"),  # appid 大小写都得是规定的样子
        ("POST", "/dev/v1/bots"),                              # 机器人是另一件事
    ])
    def test_拒绝(self, method, path):
        assert not agent_can(method, path, ("miniapp",))


class Test前缀匹配不能被绕过:
    """`POST /orders` 放行,而 `POST /orders/xxx/pay` 必须拒 ——
    两者都以 /orders 开头,靠的是「写操作只放行恰好这个路径」。"""

    def test_写操作不放行子路径(self):
        assert agent_can("POST", "/orders")
        assert agent_can("POST", "/orders/")
        assert not agent_can("POST", "/orders/x")
        assert not agent_can("POST", "/orders/cb765cbdc6a14181974b/pay/mock")

    def test_只读也是全匹配而不是想读什么都行(self):
        """第一版写的是「只读子路径一律放行」,单测当场抓出
        `GET /merchants/me/order-flags` 被放进来 —— 那是商家的经营数据。
        所以只读也逐条列,列进去的才通。"""
        assert agent_can("GET", "/merchants/1/dishes")
        assert agent_can("GET", "/orders/cb765cbdc6a14181974b")
        assert not agent_can("GET", "/orders/cb765cbdc6a14181974b/review")
        assert not agent_can("GET", "/merchants/me/order-flags")
        assert not agent_can("GET", "/merchants/me/finance/statement.csv")

    def test_前缀相近的别的路径不会被误放(self):
        """`/orders-export` 这种以 /orders 开头但不是它的路径。"""
        assert not agent_can("POST", "/orders-export")


class Test认证入口的签名不能被位置传参绑死:
    """`get_current_user` 加参数时,按位置调用它的地方会静默错位。

    实际发生过:给它加了 `request` 作第一个参数,而 `get_current_user_optional`
    是 `get_current_user(credentials, db)` 位置传参 —— credentials 落到
    request 位、db 落到 credentials 位,运行时
    `AsyncSession object has no attribute 'credentials'`,500。

    而这条路径只有「登录用户访问私密的老 /uploads URL」才走到:
    单测碰不到、大部分 e2e 碰不到,**全套跑到第 51 个套件才炸出来**。

    所以钉两件事:调用点用关键字传参;两个函数的参数名保持一致。
    """

    def test_optional_按关键字调用(self):
        import inspect
        import re
        from app import security
        src = inspect.getsource(security.get_current_user_optional)
        src = re.sub(r'"""(?:.|\n)*?"""', "", src)
        src = "\n".join(l.split("#", 1)[0] for l in src.splitlines())
        assert "get_current_user(" in src, "optional 不再委托给 get_current_user?"
        call = src[src.index("get_current_user("):]
        for kw in ("request=", "credentials=", "db="):
            assert kw in call, (
                f"委托调用没有用关键字传 {kw} —— "
                f"给 get_current_user 加参数时会静默错位,而错位只在冷门路径上炸")

    def test_两个入口的参数名一致(self):
        """名字不一致的话,关键字传参会 TypeError —— 那反而是好事(当场炸),
        但更好的是根本别不一致。"""
        import inspect
        from app import security
        a = list(inspect.signature(security.get_current_user).parameters)
        b = list(inspect.signature(security.get_current_user_optional).parameters)
        assert a == b, f"两个认证入口的参数不一致:{a} vs {b}"
