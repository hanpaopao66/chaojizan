"""骑手人脸核验:实名之后再加一道,在线期间定时复核,防代送。

## 为什么实名了还要人脸

二要素(姓名+证号查公安人口库)只证明"这个身份真实存在且匹配",
**证明不了拿手机跑单的人就是他**。账号出租、一个号几个人轮着跑,
二要素拦不住 —— 顾客把餐交给了一个平台不认识的人。

所以:

- **首次(enroll)**:实名之后做一次活体 + 与公安库照片比对,确认是本人;
- **复核(periodic)**:在线期间每隔几个小时(默认 4 小时,
  `RIDER_FACE_CHECK_INTERVAL_HOURS`)再做一次活体 + 与首次核验比对。
  到点没复核 → 不能接新单,**手上的单照常送完**(餐在路上,不能为了核验扔下);

## 合规口径(《人脸识别技术应用安全管理办法》,2025-06-01 施行)

- 人脸**不是唯一**验证方式:身份仍以二要素为准,人脸只回答"是不是本人在跑";
- **单独同意**:第一次核验前要骑手明确勾选同意(RiderProfile.face_consent_at);
- **服务端不存人脸图像**:图像在骑手手机和服务商之间传,我们只存结果和
  服务商的核验编号。复核的比对源用首次核验在服务商那边的编号,不用我们存的图。

## 服务商

接口照「三方服务桩」的模式做成可替换的:`FaceProvider` 两个方法,
`start` 拿到一次核验的编号和客户端要用的东西(H5 地址或 SDK 令牌),
`result` 查这次核验的结果。**结果一律以服务端向服务商查询为准**,
客户端说自己过了不算 —— 不然改一下客户端就能绕过。

服务商还没定(`FACE_PROVIDER` 留空):开发环境走 `FakeFaceProvider`,
生产环境直接报"未配置",**不放行**(和 idcheck 二要素同一条纪律)。
"""
from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Protocol

from ..config import settings

PURPOSE_ENROLL = "enroll"
PURPOSE_PERIODIC = "periodic"

#: 一次核验从发起到查结果的最长时间。超过就作废,要重新发起 ——
#: 防止拿一个很久以前过了的编号来顶
SESSION_TTL = timedelta(minutes=15)

#: 每个骑手每天最多发起几次。每次都要花钱(首次约 1 元,复核约 0.15 元),
#: 正常一天两三次复核,失败重试几次也够;再多就是客户端出了问题或者有人在刷
DAILY_START_LIMIT = 12


@dataclass(frozen=True)
class FaceSession:
    #: 服务商这边的核验编号(阿里云叫 CertifyId,腾讯云叫 BizToken)
    ref: str
    #: H5 方案:客户端打开这个地址做活体。空 = 不走 H5
    verify_url: str = ""
    #: SDK 方案:客户端拿这个去调服务商 SDK。空 = 不走 SDK
    client_token: str = ""


@dataclass(frozen=True)
class FaceResult:
    passed: bool
    #: 没过时给骑手看的原因,要说人话("光线太暗"而不是错误码)
    reason: str = ""


class FaceProvider(Protocol):
    name: str

    async def start(self, *, purpose: str, rider_id: int, real_name: str,
                    id_no: str, enroll_ref: str) -> FaceSession:
        """发起一次核验。

        purpose=enroll 时和公安库比对(用 real_name + id_no);
        purpose=periodic 时和首次核验比对(用 enroll_ref)。
        服务异常抛 RuntimeError。
        """
        ...

    async def result(self, ref: str) -> FaceResult:
        """查这次核验的结果。还没做完也算没过。服务异常抛 RuntimeError。"""
        ...


class FakeFaceProvider:
    """开发环境用的假实现:不做真核验,发起后查结果就算通过。

    想测"没过"的路径:发起时 dev_outcome="fail",编号里带上标记,
    查结果时据此返回失败。**只在开发环境出现**(get_provider 卡着)。
    """

    name = "fake"

    def __init__(self, outcome: str = "pass"):
        self.outcome = outcome

    async def start(self, *, purpose: str, rider_id: int, real_name: str,
                    id_no: str, enroll_ref: str) -> FaceSession:
        tag = "fail" if self.outcome == "fail" else "pass"
        return FaceSession(ref=f"fake-{tag}-{secrets.token_hex(8)}")

    async def result(self, ref: str) -> FaceResult:
        if ref.startswith("fake-fail-"):
            return FaceResult(False, "没有检测到本人(开发环境模拟的失败)")
        return FaceResult(True)


def get_provider(dev_outcome: str = "") -> FaceProvider:
    """按配置挑服务商。没配:开发环境给假的,生产抛 RuntimeError(调用方回 503)。"""
    name = settings.face_provider.strip().lower()
    if not name:
        if not settings.is_dev:
            raise RuntimeError("人脸核验服务未配置")
        return FakeFaceProvider(dev_outcome or "pass")
    # 选定服务商后在这里接上真实现(阿里云金融级实人认证 / 腾讯云慧眼)
    raise RuntimeError(f"人脸核验服务商 {name} 还没有接入")


def interval() -> timedelta:
    return timedelta(hours=settings.rider_face_check_interval_hours)


def expires_at(verified_at: datetime | None) -> datetime | None:
    if verified_at is None:
        return None
    if verified_at.tzinfo is None:
        verified_at = verified_at.replace(tzinfo=timezone.utc)
    return verified_at + interval()


def needs_check(verified_at: datetime | None,
                now: datetime | None = None) -> str:
    """要不要先做人脸核验。返回空串 = 不用;否则是原因:enroll(从没做过)/
    expired(过了有效期)。开关关着一律不用。"""
    if not settings.rider_face_check_required:
        return ""
    if verified_at is None:
        return PURPOSE_ENROLL
    now = now or datetime.now(timezone.utc)
    return "expired" if now >= expires_at(verified_at) else ""
