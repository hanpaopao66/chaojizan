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

from app.security import AGENT_ALLOWED, agent_can


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
        assert not agent_can("POST", path), (
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
        assert not agent_can(method, path), f"{method} {path} 不该对助手开放"


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
        assert not agent_can(method, path)

    def test_白名单本身很短(self):
        """短是刻意的。每加一条都要能说出「为什么助手需要它」。"""
        assert len(AGENT_ALLOWED) <= 12, (
            f"助手白名单涨到了 {len(AGENT_ALLOWED)} 条 —— "
            f"每一条都是一个自动化程序能碰的地方,加之前先问为什么")

    def test_写操作只有一条(self):
        writes = [(m, p) for m, p in AGENT_ALLOWED if m != "GET"]
        assert writes == [("POST", "/orders")], (
            f"助手的写操作不止「创建订单」一条:{writes} —— "
            f"每多一条,「付款在人手里」这句话就松一分")


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
