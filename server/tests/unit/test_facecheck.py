"""骑手人脸核验:有效期判定和服务商选择(防代送)。

## 这组测试守什么

- **到点就得复核**:有效期边界按「到点即过期」算,时间带不带时区都一样;
- **开关关掉就一律不拦** —— 服务商没配好之前,运营要能先关掉,而不是让全城骑手上不了线;
- **生产没配服务商不放行**:和二要素同一条纪律。开发环境给假实现,生产给 RuntimeError;
- 假实现能模拟"没过",开发环境才测得到失败路径。
"""
import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from app.config import settings
from app.services import facecheck


@pytest.fixture
def four_hours(monkeypatch):
    monkeypatch.setattr(settings, "rider_face_check_required", True)
    monkeypatch.setattr(settings, "rider_face_check_interval_hours", 4.0)


class Test有效期:
    def test_从没做过要做首次(self, four_hours):
        assert facecheck.needs_check(None) == facecheck.PURPOSE_ENROLL

    def test_有效期内不用做(self, four_hours):
        now = datetime.now(timezone.utc)
        assert facecheck.needs_check(now - timedelta(hours=3, minutes=59),
                                     now) == ""

    def test_到点就过期(self, four_hours):
        now = datetime.now(timezone.utc)
        assert facecheck.needs_check(now - timedelta(hours=4), now) == "expired"

    def test_不带时区的当成UTC(self, four_hours):
        now = datetime.now(timezone.utc)
        naive = (now - timedelta(hours=5)).replace(tzinfo=None)
        assert facecheck.needs_check(naive, now) == "expired"
        assert facecheck.expires_at(naive).tzinfo is not None

    def test_间隔可配置(self, monkeypatch):
        monkeypatch.setattr(settings, "rider_face_check_required", True)
        monkeypatch.setattr(settings, "rider_face_check_interval_hours", 2.0)
        now = datetime.now(timezone.utc)
        assert facecheck.needs_check(now - timedelta(hours=3), now) == "expired"

    def test_开关关掉一律不拦(self, monkeypatch):
        monkeypatch.setattr(settings, "rider_face_check_required", False)
        assert facecheck.needs_check(None) == ""


class Test服务商:
    def test_生产没配不放行(self, monkeypatch):
        monkeypatch.setattr(settings, "face_provider", "")
        monkeypatch.setattr(settings, "app_env", "prod")
        with pytest.raises(RuntimeError, match="未配置"):
            facecheck.get_provider()

    def test_开发环境给假实现(self, monkeypatch):
        monkeypatch.setattr(settings, "face_provider", "")
        monkeypatch.setattr(settings, "app_env", "dev")
        assert facecheck.get_provider().name == "fake"

    def test_没接入的服务商不放行(self, monkeypatch):
        # 配了个名字但代码里还没实现:不能悄悄退回假实现
        monkeypatch.setattr(settings, "face_provider", "aliyun")
        monkeypatch.setattr(settings, "app_env", "dev")
        with pytest.raises(RuntimeError):
            facecheck.get_provider()

    def test_假实现能模拟成功和失败(self):
        async def go(outcome):
            p = facecheck.FakeFaceProvider(outcome)
            s = await p.start(purpose="enroll", rider_id=1, real_name="王小明",
                              id_no="", enroll_ref="")
            return await p.result(s.ref)
        assert asyncio.run(go("pass")).passed is True
        failed = asyncio.run(go("fail"))
        assert failed.passed is False and failed.reason
