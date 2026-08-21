"""应用商店审核白名单的固定码:admin 一律不适用。

白名单分支在角色判断**之前**,而且它只看手机号和固定码 —— role 是请求方
随便填的。于是一个写死在配置里、永不过期的六位码,配上一个已经存在的
管理员账号,就是一条直通管理后台的路。审核用的账号本来只需要三端能进,
把 admin 排除掉成本为零。

放在单元层是因为这是纯判断:e2e 要验它得让服务端带着
SMS_REVIEW_ACCOUNTS 重启一次,而那条环境一旦忘了撤,后面所有用例
都跑在一个开着后门的实例上。
"""
import pytest

from app.config import settings
from app.routers.auth import review_code_ok

PHONE = "13800000000"
CODE = "246810"


@pytest.fixture
def whitelisted(monkeypatch):
    monkeypatch.setattr(settings, "sms_review_accounts", f"{PHONE}:{CODE}")


def test_三端照常放行(whitelisted):
    for role in ("customer", "merchant", "rider"):
        assert review_code_ok(PHONE, CODE, role), role


def test_admin不适用(whitelisted):
    assert not review_code_ok(PHONE, CODE, "admin"), \
        "固定码能登管理后台:白名单分支排在角色判断之前"


def test_码不对不放行(whitelisted):
    assert not review_code_ok(PHONE, "000000", "customer")


def test_不在白名单不放行(whitelisted):
    assert not review_code_ok("13900000000", CODE, "customer")


def test_未配置白名单时谁都不放行():
    assert settings.sms_review_accounts == "", "本机不该配着审核白名单"
    assert not review_code_ok(PHONE, CODE, "customer")
