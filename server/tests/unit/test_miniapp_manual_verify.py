"""个人开发者实名:核验服务没接入时转人工审核,而不是把人挡在 503 后面。

用户的场景:生产上 `idcheck_*` 从未配置,开发者在 /dev/account 点「提交核验」,
得到 503「实名核验服务未配置,请稍后再试」—— 机器核验没接,连人工审核的入口
都没有。这里钉三件事:

1. **未配置**(`IdcheckNotConfigured`)→ 进 pending 人工审核,管理后台能看到;
   真名 / 证号照旧只存密文,接口只回尾号;
2. **服务故障**(`IdcheckUnavailable`)→ 仍然 503 不放行。那是临时故障,等一会
   重试即可,和「平台还没接核验服务」不是一回事 —— 两者混成一个,运维就分不清
   该去配服务还是该去看上游;
3. 姓名与证号不一致 → 422,状态不动。

还钉住管理端「查看实名信息」那一条:理由必填,且审计里只记尾号与理由,
不记明文 —— 留痕不能变成第二个泄露点。
"""
import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

import app.routers.admin_miniapps as adminmod
import app.routers.dev_miniapps as devmod
from app.models import Developer
from app.schemas_miniapp import DeveloperIdentityRevealIn, DevVerifyIndividualIn
from app.services import idcheck
from app.services.crypto import decrypt, encrypt


def _id_number(prefix17: str = "11010119900307001") -> str:
    """拼一个校验位正确的身份证号(测试用,非真实号码)。"""
    from app.services.idcheck import _CHECK_CHARS, _WEIGHTS
    return prefix17 + _CHECK_CHARS[
        sum(int(d) * w for d, w in zip(prefix17, _WEIGHTS)) % 11]


GOOD = _id_number()


class _Dev:
    """Developer 的替身:只带实名接口会碰到的字段(默认值和库里的列一致,都是 "")。"""

    def __init__(self, status: str = "unverified"):
        self.id = 7
        self.status = status
        self.kind = "individual"
        self.real_name_enc = ""
        self.id_no_enc = ""
        self.id_no_tail = ""
        self.submitted_at = None
        self.reject_reason = ""


class _User:
    def __init__(self):
        self.id = 42
        self.phone = "13900000000"


class _DB:
    """只够实名接口用的假会话:add 收审核记录 / 审计事件,commit 记一笔。"""

    def __init__(self, dev: _Dev | None = None):
        self.dev = dev
        self.added = []
        self.commits = 0

    def add(self, row):
        self.added.append(row)

    async def commit(self):
        self.commits += 1

    async def get(self, model, key, **_):
        assert model is Developer and key == self.dev.id
        return self.dev


async def _fake_me(db, c):
    return {"id": c.dev.id, "status": c.dev.status, "kind": c.dev.kind,
            "real_name_masked": "张**" if c.dev.real_name_enc else "",
            "id_no_tail": c.dev.id_no_tail}


def _submit(monkeypatch, *, status: str = "unverified", verify):
    """直接调实名路由函数(不经过 HTTP):verify 是 verify_two_elements 的替身。"""
    dev, db = _Dev(status), _DB()
    c = SimpleNamespace(user=_User(), dev=dev)

    async def no_rate_limit(*args, **kwargs):
        return None

    monkeypatch.setattr(devmod, "check_rate_limit", no_rate_limit)
    monkeypatch.setattr(devmod, "_me", _fake_me)
    monkeypatch.setattr(idcheck, "verify_two_elements", verify)
    body = DevVerifyIndividualIn(real_name="张三", id_no=GOOD)
    try:
        out = asyncio.run(devmod.verify_individual(body, c, db))
        return SimpleNamespace(result=out, error=None, dev=dev, db=db)
    except HTTPException as exc:
        return SimpleNamespace(result=None, error=exc, dev=dev, db=db)


async def _not_configured(*args, **kwargs):
    raise idcheck.IdcheckNotConfigured("实名核验服务未配置")


async def _unavailable(*args, **kwargs):
    raise idcheck.IdcheckUnavailable("实名核验服务暂时不可用")


async def _mismatch(*args, **kwargs):
    return False


class Test核验服务没接入时转人工审核:
    def test_进pending而不是503(self, monkeypatch):
        r = _submit(monkeypatch, verify=_not_configured)
        assert r.error is None, f"未配置不该把人挡在 {r.error} 后面"
        assert r.result["status"] == "pending", "要进待审核队列"

    def test_落库的还是密文_接口只回尾号(self, monkeypatch):
        r = _submit(monkeypatch, verify=_not_configured)
        assert decrypt(r.dev.real_name_enc) == "张三"
        assert decrypt(r.dev.id_no_enc) == GOOD
        assert "张三" not in r.dev.real_name_enc and GOOD not in r.dev.id_no_enc, \
            "真名、证号必须只存密文 —— 转人工审核不是降低加密标准的理由"
        assert r.dev.id_no_tail == GOOD[-4:]
        assert r.dev.kind == "individual"
        assert r.dev.submitted_at is not None and r.dev.reject_reason == ""

    def test_审核记录里写明是转人工(self, monkeypatch):
        r = _submit(monkeypatch, verify=_not_configured)
        decisions = [x for x in r.db.added if getattr(x, "action", "") == "verify_submit"]
        assert decisions, "没写审核记录,后台和透明中心都对不上"
        d = decisions[0]
        assert d.target_type == "developer" and d.developer_id == r.dev.id
        assert "未配置" in d.note_internal and "人工" in d.note_internal

    def test_驳回后可以重新提交转人工(self, monkeypatch):
        r = _submit(monkeypatch, status="rejected", verify=_not_configured)
        assert r.error is None and r.result["status"] == "pending"
        assert r.db.commits == 1

    def test_待审核时不能重复提交(self, monkeypatch):
        r = _submit(monkeypatch, status="pending", verify=_not_configured)
        assert r.error is not None and r.error.status_code == 409
        assert r.db.commits == 0


class Test机器核验的另两种结果不跟着变:
    def test_服务故障仍然503不放行(self, monkeypatch):
        r = _submit(monkeypatch, verify=_unavailable)
        assert r.error is not None and r.error.status_code == 503
        assert "请稍后再试" in r.error.detail
        assert r.dev.status == "unverified" and r.db.commits == 0, \
            "临时故障不该自动转 pending,更不该放行"

    def test_姓名证号不一致仍然422(self, monkeypatch):
        r = _submit(monkeypatch, verify=_mismatch)
        assert r.error is not None and r.error.status_code == 422
        assert "不一致" in r.error.detail
        assert r.dev.status == "unverified" and r.db.commits == 0


class Test核验服务本身把两种失败分开:
    def _prod_unconfigured(self, monkeypatch):
        monkeypatch.setattr(idcheck.settings, "app_env", "prod")
        monkeypatch.setattr(idcheck.settings, "idcheck_api_url", "")
        monkeypatch.setattr(idcheck.settings, "idcheck_app_code", "")

    def test_生产未配置抛NotConfigured(self, monkeypatch):
        self._prod_unconfigured(monkeypatch)
        with pytest.raises(idcheck.IdcheckNotConfigured):
            asyncio.run(idcheck.verify_two_elements("张三", GOOD))

    def test_开发环境未配置仍然按桩放行(self, monkeypatch):
        monkeypatch.setattr(idcheck.settings, "app_env", "dev")
        monkeypatch.setattr(idcheck.settings, "idcheck_api_url", "")
        monkeypatch.setattr(idcheck.settings, "idcheck_app_code", "")
        assert asyncio.run(idcheck.verify_two_elements("张三", GOOD)) is True


class Test人工审核查看实名信息:
    def _call(self, monkeypatch, dev: _Dev, reason: str):
        db = _DB(dev)
        admin = SimpleNamespace(id=9, phone="13800000009")
        return asyncio.run(adminmod.reveal_developer_identity(
            dev.id, DeveloperIdentityRevealIn(reason=reason), admin, db)), db

    def test_理由必填(self):
        for bad in ("", "看"):
            with pytest.raises(ValidationError):
                DeveloperIdentityRevealIn(reason=bad)
        assert DeveloperIdentityRevealIn(reason="人工核验").reason == "人工核验"

    def test_返回完整信息但审计里只有尾号(self):
        dev = _Dev()
        dev.real_name_enc, dev.id_no_enc = encrypt("张三"), encrypt(GOOD)
        dev.id_no_tail = GOOD[-4:]
        out, db = self._call(None, dev, "个人实名转人工审核")
        assert out["real_name"] == "张三" and out["id_no"] == GOOD and out["audited"] is True
        events = [x for x in db.added if getattr(x, "event", "") == "developer_identity_reveal"]
        assert events, "查看实名信息必须留痕"
        props = str(events[0].props)
        assert "张三" not in props and GOOD not in props, "留痕不能成为第二份明文"
        assert events[0].props["id_no_tail"] == GOOD[-4:]
        assert events[0].props["reason"] == "个人实名转人工审核"

    def test_没有实名信息时404(self):
        dev = _Dev()
        with pytest.raises(HTTPException) as e:
            self._call(None, dev, "人工核验")
        assert e.value.status_code == 404
