"""验证码什么时候能随响应回去:**判据是这个部署配没配短信,不是这次发没发出去。**

## 这条守什么

`/auth/sms-code` 原来的写法是:

    if await send_verification_code(phone, code):
        return {"sent": True}
    return {"sent": False, "dev_code": code}     # ← 只要没发成就把码给出去

而 `send_verification_code` 返回 False 有**三种**情况,只有第一种是"开发环境":

1. `not settings.sms_configured` —— 没配短信,开发/测试环境;
2. 阿里云返回非 OK —— 配额用尽、签名被禁、模板停用、余额不足;
3. `httpx.HTTPError / ValueError / KeyError` —— 网络抖动、超时、响应不是 JSON。

也就是说**生产上把短信配好了也没用**:短信商任何一次抖动,
攻击者 POST 一次 `/auth/sms-code` 就能拿到**任意手机号**的验证码,
再 POST 一次 `/auth/sms-login` 就登进去了。而 `sms-login` 的 role 由请求方指定
(见该函数注释:「受害者是商家号还是已存在的 admin 都由攻击者挑」),
所以这是**任意账号接管,包括管理员**。

而且攻击者可以主动制造条件 2:先用别的号把短信配额打满,再打目标。

## 判据改成什么

「这个部署**配没配**短信」。配了 = 真实部署,任何情况都不许把码给出去,
发送失败就如实报 503;没配 = 开发/测试,保留原来的 dev_code 便利。

这是**开源平台**,代码里每一个"不配就放行"的默认值,攻击者都读得到。
"""
import pytest

from app.config import settings
from app.routers import auth


class Test判据是配没配而不是发没发成:
    """回码要**两个条件同时成立**:这是开发环境,且没配短信。

    第一版这两条只 patch 了 `sms_configured`,把 `is_dev` 那一半交给进程环境 ——
    本地 `.env` 有 `APP_ENV=dev` 所以是绿的,CI 的单测 job 没有这一行
    (按生产处理)当场就红。**单元测试只断言代码的性质,不断言当前进程配了什么。**
    """

    @staticmethod
    def _部署(monkeypatch, *, 开发: bool, 配了短信: bool) -> None:
        """把两个判据都钉死 —— 少钉一个,这条测试就变成在测本机的 .env。"""
        monkeypatch.setattr(type(settings), "is_dev",
                            property(lambda self: 开发))
        monkeypatch.setattr(type(settings), "sms_configured",
                            property(lambda self: 配了短信))

    def test_开发环境且没配短信才回码(self, monkeypatch):
        self._部署(monkeypatch, 开发=True, 配了短信=False)
        assert auth.dev_code_visible() is True

    def test_配了短信一律不许回码(self, monkeypatch):
        """这一条是整个洞的要害:配了短信 = 真实部署。"""
        self._部署(monkeypatch, 开发=True, 配了短信=True)
        assert auth.dev_code_visible() is False, (
            "配了短信还把验证码随响应返回 —— 短信商一抖动就是任意账号接管")

    def test_生产上没配短信也不回码(self, monkeypatch):
        """`is_dev` 那一半以前没有任何守卫 —— 删掉它,上面两条照样绿。

        而这一半正是自部署者最容易踩的:拿着开源代码起一套、短信还没接,
        `/auth/sms-code` 就把任意手机号的验证码交出去了。
        """
        self._部署(monkeypatch, 开发=False, 配了短信=False)
        assert auth.dev_code_visible() is False, (
            "生产上没配短信就把验证码交出去 —— 自部署者接短信之前的那段时间,"
            "任何人都能登进任何账号")

    def test_判据里不许出现发送结果(self):
        """`dev_code_visible` 不接受参数 —— 结构上就不可能拿"这次发成没有"
        当判据。签名一旦被改成 `dev_code_visible(sent)`,这条就红。"""
        import inspect
        params = list(inspect.signature(auth.dev_code_visible).parameters)
        assert params == [], (
            f"判据函数收了参数 {params} —— 判据只能看部署配置,"
            f"不能看这一次的发送结果")


class Test路由用的是这个判据:
    def test_回码那一行必须在判据守卫之后(self):
        """钉的是**顺序**,不是有没有出现某个字符串。

        `if await send_verification_code(...)` 本身没问题(那是成功分支);
        有问题的是"发送失败 → 直接把 code 返回"。所以要求源码里
        `dev_code_visible()` 出现在返回 dev_code 之前 ——
        有人把守卫删掉或挪到后面,这条就红。
        """
        import inspect
        src = inspect.getsource(auth.send_sms_code)
        assert "dev_code_visible()" in src, "路由没走统一判据"
        guard = src.index("dev_code_visible()")
        leak = src.index('"dev_code"')
        assert guard < leak, (
            "返回 dev_code 的那一行没有被 dev_code_visible() 守住 —— "
            "配了短信的部署一旦发送失败就会把验证码交出去")

    def test_发送失败要报错而不是把码给出去(self):
        src = inspect.getsource(auth.send_sms_code)
        assert "503" in src, (
            "配了短信却发送失败时,应当如实返回 503,"
            "而不是静默降级成把验证码交给调用方")


import inspect  # noqa: E402  (上面那条测试要用)
