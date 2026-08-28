"""注册接口:必须限流,而且必须记设备指纹。

## 这条守什么

审计时发现的链条:

1. `/register` **没有 check_rate_limit** —— 它是唯一一个没有的认证入口
   (login / sms-code / sms-login 三个都有);
2. `RegisterIn` **没有 device_id** —— 于是 `User.device_id` 一直是空;
3. 而新客券的防薅闸门 `_device_has_other_account` 第一句就是
   `if not user.device_id: return False`。

三条连起来:**防薅闸门对每一次密码注册都结构性失效**,而注册无限流、
不验手机号。攻击者可以在几秒内把一整个新客券批次薅空 ——
券的钱是商家出的,批次预算封顶只是把损失框住,并不阻止它发生,
而真正的新用户一张也拿不到。

这是开源平台,`_device_has_other_account` 的第一句谁都读得到。

## 判据

不是"有没有写某个字符串",是**三件事同时成立**:接口限流了、
请求体收 device_id、处理函数把它落到 User 上。少任何一件,闸门就还是虚的。
"""
import inspect

from app.routers import auth
from app.schemas import LoginIn, RegisterIn


class Test注册要限流:
    def test_register_调了限流(self):
        src = inspect.getsource(auth.register)
        assert "check_rate_limit" in src, (
            "/register 没有限流 —— 它是唯一一个没有的认证入口,"
            "而它每次都会发一张新客券")

    def test_三个认证入口都有限流(self):
        """一起断言,是为了让"新加一个入口忘了限流"也能被这条抓到。"""
        for fn in (auth.register, auth.login, auth.send_sms_code,
                   auth.sms_login):
            src = inspect.getsource(fn)
            assert "check_rate_limit" in src, f"{fn.__name__} 没有限流"


class Test注册要记设备指纹:
    def test_请求体收_device_id(self):
        assert "device_id" in RegisterIn.model_fields, (
            "RegisterIn 不收 device_id —— 那么 User.device_id 永远是空,"
            "而新客券防薅第一句就是 `if not user.device_id: return False`")

    def test_和登录用同一个口径(self):
        """长度上限对不上的话,同一台设备在两个入口会被算成两台。"""
        r = RegisterIn.model_fields["device_id"]
        l = LoginIn.model_fields["device_id"]
        assert r.default == l.default == ""
        assert str(r.metadata) == str(l.metadata), (
            f"注册与登录的 device_id 约束不一致:{r.metadata} vs {l.metadata}")

    def test_处理函数真的把它落到_User_上(self):
        """收了不存等于没收。"""
        src = inspect.getsource(auth.register)
        assert "device_id=payload.device_id" in src or (
            "device_id" in src and "user.device_id" in src), (
            "register 收了 device_id 却没写进 User —— 闸门还是虚的")


class Test防薅闸门本身:
    def test_没有设备指纹时闸门直接放行(self):
        """这不是 bug,是这条闸门的已知边界 —— 正因为如此,
        **上游必须保证 device_id 有值**,否则闸门等于不存在。
        这条测试把这个依赖关系写下来,免得以后有人删掉注册那一侧
        还以为闸门在守着。"""
        src = inspect.getsource(
            __import__("app.services.coupons", fromlist=["x"])
            ._device_has_other_account)
        assert "if not user.device_id" in src and "return False" in src
