"""安全审计里四条中低危的守卫。

四条的共同点还是那个:**判据用错了,或者失败时倒向了不安全那一侧。**

1. **上传的文件名回退**:`_sniff_ext` 按魔数认不出时,回退到**攻击者可控的
   文件名后缀**。而白名单只有 jpg/png/webp,三种都嗅得出来 ——
   这条回退只可能放进非图片,纯负收益。
2. **退款的 mock 通道**:微信未配置时把退款**直接置 success**。
   账上写着已退、钱没动,而审计规则 5 比的是「refund_cents == Σ流水」,
   两边都假,查不出来。判据该是"是不是开发环境",不是"配没配微信"。
3. **`/ws/orders/{no}` 无鉴权**:商家那条听单通道验 JWT + 店铺归属,
   订单这条谁都能连。
4. **`/register` 在生产上就不该存在**:三端都走短信登录,没有任何客户端
   调它;而它不验手机号(可以拿别人的号注册)、还是"这个号注册过没"的
   枚举口子。
"""
import inspect
import re

import pytest

from app.config import Settings


def code_of(fn) -> str:
    """函数源码,**去掉注释和文档字符串**。

    第一版直接 grep 整段源码,结果被我自己写的那句
    「原来这里是 `ext = Path(file.filename)...`」命中了 —— 解释性注释里
    出现旧写法是正常的,源码检查类的断言必须只看真正会执行的那部分。
    """
    src = inspect.getsource(fn)
    src = re.sub(r'"""(?:.|\n)*?"""', "", src)      # 文档字符串
    return "\n".join(l.split("#", 1)[0] for l in src.splitlines())


def _bare(**kw) -> Settings:
    return Settings(_env_file=None, **kw)


class Test上传认不出格式就该拒绝:
    def test_源码里没有回退到文件名后缀(self):
        from app.routers import uploads
        src = code_of(uploads.upload_image)
        assert "file.filename" not in src, (
            "认不出魔数时回退到了文件名后缀 —— 白名单那三种格式都嗅得出来,"
            "这条回退只可能放进非图片")

    def test_嗅探认不出时抛错(self):
        from app.routers import uploads
        src = code_of(uploads.upload_image)
        assert "_sniff_ext" in src
        # 认不出必须是一条明确的拒绝路径,不是静默兜底
        assert "ext is None" in src and "raise" in src

    @pytest.mark.parametrize("data", [
        b"<html><script>alert(1)</script></html>",
        b"<svg xmlns='http://www.w3.org/2000/svg'><script/></svg>",
        b"PK\x03\x04zipfile",
        b"",
        b"GIF89a",          # 真 GIF 也不在白名单里
    ])
    def test_这些内容一律认不出(self, data):
        from app.routers.uploads import _sniff_ext
        assert _sniff_ext(data) is None, f"{data[:20]!r} 被当成了图片"


class Test退款的mock通道只在开发环境:
    def test_判据是环境不是配没配微信(self):
        from app.services import wechat_pay
        src = code_of(wechat_pay._dispatch_refund)
        assert "is_dev" in src, (
            "退款走 mock 直接置 success 的判据仍然是「配没配微信」—— "
            "生产上没配的话,账上写已退、钱没动,而审计比的是"
            "「refund_cents == Σ流水」,两边都假")


class Test注册在生产上关闭:
    def test_默认关(self):
        from app.routers import auth
        assert not auth.password_register_allowed(_bare()), (
            "生产默认能用密码注册 —— 它不验手机号,任何人可以拿别人的号注册,"
            "而且是「这个号注册过没」的枚举口子")

    def test_开发环境自动开(self):
        """45 个 e2e 套件用它,而 e2e 跑在 APP_ENV=dev 下 —— 不能让它们全炸。"""
        from app.routers import auth
        assert auth.password_register_allowed(_bare(app_env="dev"))

    def test_自部署者可以显式打开(self):
        """开源项目要给部署者留选择,但默认必须是关的。"""
        from app.routers import auth
        assert auth.password_register_allowed(
            _bare(password_register_enabled=True))

    def test_路由真的判了(self):
        from app.routers import auth
        src = code_of(auth.register)
        assert "password_register_allowed()" in src


class Test订单WS要鉴权:
    def test_订单通道验了身份(self):
        from app import ws
        src = code_of(ws.order_ws)
        assert "token" in src, (
            "/ws/orders/{no} 谁都能连 —— 商家那条听单通道验了 JWT + 店铺归属,"
            "订单这条不能是敞开的")

    def test_三种当事人都连得上(self):
        """顾客、这单的骑手、这单的商家都该连得上 —— 只挡无关的人。
        判据写在源码里,这条钉住它没被收窄成「只有顾客」。"""
        from app import ws
        src = code_of(ws.order_ws)
        for who in ("customer_id", "rider_id", "merchant_id"):
            assert who in src, f"订单 WS 的鉴权漏了 {who} 这一方"
