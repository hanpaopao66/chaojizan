"""开发便利在默认配置下必须**全部关闭**。

## 为什么要有这一组

这是**开源**平台:攻击者读得到每一个默认值。而审计时发现的形状是同一个 ——
安全开关的默认值站在了不安全那一侧,安全性靠"记得在生产设 env":

    mock_pay_enabled: bool = True        # 忘了设 → 任何人白嫖下单
    admin_password_login: bool = True    # 忘了设 → 多一条爆破面
    verify_two_elements() 未配置 → True  # 忘了配 → 实名认证形同虚设
    /auth/sms-code 发送失败 → 回验证码    # 短信一抖 → 任意账号接管

前三条都是"忘了配 = 被打穿",第四条更糟(配对了也会被打穿,已单独修)。

## 判据反过来:默认 prod

`app_env` 默认 `prod`,本地开发与 CI 显式设 `APP_ENV=dev`。
**忘了配的后果是某个开发便利不可用,而不是某道校验被跳过。**

新加的开发便利只要挂在 `settings.is_dev` 上,就自动继承这个安全默认值 ——
这组测试守的就是"没有人绕过它"。
"""
import inspect

import pytest

from app.config import Settings


def _bare() -> Settings:
    """不读 .env 的 Settings —— 测的是**代码里的默认值**。

    直接 `Settings()` 会把本地 .env 读进来(那里有 APP_ENV=dev),
    于是"默认安全"这条永远是绿的,而真正要防的正是**部署上什么都没配**
    的那种情况。
    """
    return Settings(_env_file=None)


class Test环境判据本身:
    def test_默认是生产(self):
        """**这一条是整组的地基。** 默认 dev 的话,上面每一个开发便利
        在忘了配 env 的部署上都会自动打开。"""
        assert _bare().app_env == "prod"
        assert _bare().is_dev is False

    @pytest.mark.parametrize("v", ["dev", "DEV", " dev ", "development", "test"])
    def test_显式设了才算开发环境(self, v):
        assert Settings(_env_file=None, app_env=v).is_dev is True

    @pytest.mark.parametrize("v", ["prod", "production", "", "staging", "Dev1"])
    def test_其余取值一律按生产处理(self, v):
        """拼错、留空、写成 staging —— 一律按生产。
        猜不出来的时候站在安全那一侧。"""
        assert Settings(_env_file=None, app_env=v).is_dev is False


class Test每个开发便利都挂在环境判据上:
    """不是查"有没有这个字符串",是查**用它的地方真的判了环境**。"""

    def test_模拟支付(self):
        from app.routers import orders
        src = inspect.getsource(orders.mock_pay_allowed)
        assert "is_dev" in src, (
            "/orders/{no}/pay/mock 没有判环境 —— 只靠 MOCK_PAY_ENABLED 的话,"
            "忘了在生产设 false 就是任何人白嫖下单")

    def test_管理员密码登录(self):
        from app.routers import auth
        src = inspect.getsource(auth.admin_password_login_allowed)
        assert "is_dev" in src, (
            "管理员密码登录没有判环境 —— 生产上管理员只该走短信验证码")

    def test_短信验证码回显(self):
        from app.routers import auth
        src = inspect.getsource(auth.dev_code_visible)
        assert "is_dev" in src, "验证码回显没有判环境"

    def test_实名核验未配置时不许放行(self):
        from app.services import idcheck
        src = inspect.getsource(idcheck.verify_two_elements)
        assert "is_dev" in src, (
            "二要素未配置时直接 return True —— 生产上忘了配的话,"
            "任何人填任意姓名 + 任意格式合法的证号都算实名通过,"
            "而实名是骑手接单的前置,也是「提现户名必须与实名一致」那道闸的基准")


class Test生产默认下这些便利确实是关的:
    """上一组查的是"判了环境",这一组查"判出来的结果是关"。
    两组都要 —— 判了环境但判反了,前一组照样绿。"""

    def test_默认配置下模拟支付不可用(self):
        from app.routers import orders
        assert not orders.mock_pay_allowed(_bare())

    def test_默认配置下管理员密码登录不可用(self):
        from app.routers import auth
        assert not auth.admin_password_login_allowed(_bare())

    def test_开发环境下才打开(self):
        from app.routers import auth, orders
        dev = Settings(_env_file=None, app_env="dev")
        assert orders.mock_pay_allowed(dev)
        assert auth.admin_password_login_allowed(dev)

    def test_开关关掉时开发环境也不给(self):
        """环境是必要条件不是充分条件:显式关掉仍然要生效。"""
        from app.routers import orders
        assert not orders.mock_pay_allowed(
            Settings(_env_file=None, app_env="dev",
                     mock_pay_enabled=False))


class Test不管当前环境是什么这条性质都成立:
    """**这一组必须自洽。**

    第一版我在这里写了 `assert settings.is_dev` —— 那是拿"当前进程配没配
    APP_ENV"当断言,本地绿、CI 的单测 job 没有 env 块就红。
    今天早上刚因为同一个形状修过 test_matrix_backpressure(它依赖本地有
    腾讯 key),不能在同一天再犯一次。

    单元测试只断言**代码的性质**:非开发环境下这些便利一定是关的。
    至于"这台机器有没有配 APP_ENV",让 e2e 去撞 —— 那边撞了会给出
    带排查提示的 403,比一条红掉的单测更有用。
    """

    def test_非开发环境下模拟支付一定是关的(self):
        from app.routers import orders
        for env in ("prod", "production", "staging", ""):
            cfg = Settings(_env_file=None, app_env=env, mock_pay_enabled=True)
            assert not orders.mock_pay_allowed(cfg), f"{env!r} 下居然开着"

    def test_非开发环境下管理员密码登录一定是关的(self):
        from app.routers import auth
        for env in ("prod", "production", "staging", ""):
            cfg = Settings(_env_file=None, app_env=env,
                           admin_password_login=True)
            assert not auth.admin_password_login_allowed(cfg), f"{env!r} 下开着"
