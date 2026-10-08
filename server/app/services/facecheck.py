"""骑手人脸核验:实名之后再加一道,在线期间定时复核,防代送。

## 为什么实名了还要人脸

二要素(姓名+证号查公安人口库)只证明"这个身份真实存在且匹配",
**证明不了拿手机跑单的人就是他**。账号出租、一个号几个人轮着跑,
二要素拦不住 —— 顾客把餐交给了一个平台不认识的人。

所以:

- **首次(enroll)**:实名之后做一次活体 + 与公安库照片比对,确认是本人;
- **复核(periodic)**:在线期间每隔几个小时(默认 4 小时,
  `RIDER_FACE_CHECK_INTERVAL_HOURS`)再刷一次脸,和**首次核验留存的照片**比对
  (阿里云活体人脸验证,约 0.15 元/次;每次都查公安库要约 1 元/次)。
  到点没复核 → 不能接新单,**手上的单照常送完**(餐在路上,不能为了核验扔下);

## 合规口径(《人脸识别技术应用安全管理办法》,2025-06-01 施行)

- 人脸**不是唯一**验证方式:身份仍以二要素为准,人脸只回答"是不是本人在跑";
- **单独同意**:第一次核验前要骑手明确勾选同意(RiderProfile.face_consent_at);
- **照片只留首次那一张,而且不在我们的服务器上**:2026-10-08 运营方定了
  "存照片换便宜的复核"。照片由阿里云直接写进平台自己的阿里云 OSS
  (实人认证控制台开「留存认证资料」+ OSS 授权),我们只记它在哪个桶、
  哪个对象(对象名加密存),复核时把这个位置交给阿里云去比对。
  同意文案要写明这件事;**注销账号时把这张照片删掉**(delete_photo);
- 存了人脸信息的人数到 10 万要向省级网信部门备案(办法第十五条),运营上记着。

## 服务商

接口照「三方服务桩」的模式做成可替换的:`FaceProvider` 两个方法,
`start` 拿到一次核验的编号和客户端要用的东西(H5 地址或 SDK 令牌),
`result` 查这次核验的结果。**结果一律以服务端向服务商查询为准**,
客户端说自己过了不算 —— 不然改一下客户端就能绕过。

`FACE_PROVIDER=aliyun` 走阿里云金融级实人认证(`AliyunFaceProvider`)。
留空:开发环境走 `FakeFaceProvider`,生产环境直接报"未配置",**不放行**
(和 idcheck 二要素同一条纪律)。
"""
from __future__ import annotations

import logging
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Protocol

from ..config import settings

logger = logging.getLogger("superz.facecheck")

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
    #: 首次核验留存的照片在 OSS 的位置 (bucket, object)。复核拿它当比对源。
    #: 服务商没返回(场景没开留存 / 假实现)时为空,复核就退回和公安库比对
    photo: tuple[str, str] | None = None


class FaceProvider(Protocol):
    name: str

    async def start(self, *, purpose: str, rider_id: int, real_name: str,
                    id_no: str, enroll_ref: str) -> FaceSession:
        """发起一次核验。

        purpose=enroll 时和公安库比对(用 real_name + id_no);
        purpose=periodic 时是定时复核;enroll_ref 是首次核验的编号,
        留给"复核和首次比对"的方案用(阿里云这一版没用到)。
        服务异常抛 RuntimeError。
        """
        ...

    async def result(self, ref: str, *, compare: bool = False) -> FaceResult:
        """查这次核验的结果。还没做完也算没过。服务异常抛 RuntimeError。

        compare=True 表示这次是和留存照片比对的复核(有的服务商要换场景去查)。
        """
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

    async def result(self, ref: str, *, compare: bool = False) -> FaceResult:
        if ref.startswith("fake-fail-"):
            return FaceResult(False, "没有检测到本人(开发环境模拟的失败)")
        return FaceResult(True)


#: H5 接入时,一次核验在拿到服务商编号之前的占位编号前缀。
#: 后面跟的随机串同时是中转页地址里的凭证(见 AliyunFaceProvider)
PENDING_PREFIX = "pending-"

#: 阿里云 DescribeFaceVerify 的 SubCode → 给骑手看的话。没列到的统一说"没有通过"
_ALIYUN_SUBCODES = {
    "201": "姓名和身份证号不一致,请联系客服核对实名信息",
    "202": "查询不到你的身份信息,请联系客服",
    "203": "查询不到你的证件照片,请联系客服",
    "204": "刷脸和证件照片不是同一个人",
    "205": "活体检测没通过,请本人对着镜头、在光线充足的地方重试",
    "206": "核验次数过多被暂时限制,请稍后再试",
    "207": "刷脸和证件照片比对没通过,请在光线充足的地方重试",
    "209": "公安比对服务暂时异常,请稍后再试",
}


class AliyunFaceProvider:
    """阿里云金融级实人认证(ProductCode=ID_PRO,活体 + 与公安库照片比对),H5 接入。

    ## 为什么要一个中转页

    阿里云发起核验(InitFaceVerify)必须带 MetaInfo —— 那是**刷脸的那个浏览器**
    跑阿里云的 JS 现取的环境参数,App 拿不到也不能造。所以:

    1. App 调 /riders/face/start:我们记一条 pending 核验,给 App 一个中转页地址
       (/riders/face/h5/<随机凭证>),**这时候还没调阿里云**;
    2. App 在应用内浏览器打开中转页:页面取 MetaInfo,回传给我们,
       我们才调 InitFaceVerify 拿到阿里云的刷脸页地址,页面跳过去;
    3. 刷完阿里云跳回中转页的「做完了」,骑手回 App 点「查看结果」,
       我们调 DescribeFaceVerify 查结果 —— **以服务端查到的为准**。

    凭证只能换一次阿里云地址(换完编号就变成阿里云的 CertifyId),
    阿里云那边的 CertifyId 和刷脸页也都是 30 分钟内一次有效。

    ## 首次和复核用的不是一个方案

    - 首次:ID_PRO(活体 + 公安库照片比对,约 0.8-1 元/次)。场景开了
      「留存认证资料」+ OSS 授权的话,结果里带着这次刷脸照片在 OSS 的位置;
    - 复核:PV_FV(活体人脸验证,约 0.15 元/次),比对源就是上面那张照片
      (OssBucketName + OssObjectName)。照片不经过我们的服务器;
    - 首次那次没拿到照片位置(场景没开留存、老数据),复核退回 ID_PRO,贵但能用。

    两个方案在阿里云控制台是**两个场景**,场景 ID 分开配。
    """

    name = "aliyun"
    VERSION = "2019-03-07"

    async def start(self, *, purpose: str, rider_id: int, real_name: str,
                    id_no: str, enroll_ref: str) -> FaceSession:
        token = secrets.token_hex(16)
        base = settings.public_base_url.rstrip("/")
        return FaceSession(ref=PENDING_PREFIX + token,
                           verify_url=f"{base}/riders/face/h5/{token}")

    async def _call(self, action: str, params: dict) -> dict:
        import uuid
        from datetime import datetime, timezone

        import httpx

        from .sms import rpc_sign

        body = {
            "AccessKeyId": settings.face_aliyun_access_key_id,
            "Action": action,
            "Format": "JSON",
            "SignatureMethod": "HMAC-SHA1",
            "SignatureNonce": uuid.uuid4().hex,
            "SignatureVersion": "1.0",
            "Timestamp": datetime.now(timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%SZ"),
            "Version": self.VERSION,
            "SceneId": settings.face_aliyun_scene_id,
            **params,
        }
        body["Signature"] = rpc_sign(
            body, settings.face_aliyun_access_key_secret)
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    settings.face_aliyun_endpoint, data=body,
                    headers={"Content-Type":
                             "application/x-www-form-urlencoded"})
            data = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("阿里云人脸核验 %s 异常: %s", action, exc)
            raise RuntimeError("人脸核验服务暂时不可用,请稍后再试") from exc
        if str(data.get("Code")) != "200":
            # 签名错、场景 ID 错、欠费都在这里。日志里留原文,骑手只看到"暂时不可用"
            logger.warning("阿里云人脸核验 %s 失败: %s", action, data)
            raise RuntimeError("人脸核验服务暂时不可用,请稍后再试")
        return data.get("ResultObject") or {}

    async def init_h5(self, *, outer_order_no: str, rider_id: int,
                      real_name: str, id_no: str, meta_info: str,
                      return_url: str,
                      photo: tuple[str, str] | None = None) -> tuple[str, str]:
        """中转页拿到 MetaInfo 之后调。返回 (CertifyId, 阿里云刷脸页地址)。

        photo 有值 = 复核,和这张留存照片比对(PV_FV);没有 = 和公安库比对(ID_PRO)。
        """
        common = {
            "OuterOrderNo": outer_order_no,
            "Model": settings.face_aliyun_model,
            "CertType": "IDENTITY_CARD",
            "MetaInfo": meta_info,
            "ReturnUrl": return_url,
            "CertifyUrlType": "H5",
            "UserId": str(rider_id),
        }
        if photo and settings.face_aliyun_compare_scene_id:
            obj = await self._call("InitFaceVerify", {
                **common, "ProductCode": "PV_FV",
                "SceneId": settings.face_aliyun_compare_scene_id,
                "OssBucketName": photo[0], "OssObjectName": photo[1],
            })
        else:
            obj = await self._call("InitFaceVerify", {
                **common, "ProductCode": "ID_PRO",
                "CertName": real_name, "CertNo": id_no,
            })
        certify_id = str(obj.get("CertifyId") or "")
        certify_url = str(obj.get("CertifyUrl") or "")
        if not certify_id or not certify_url:
            raise RuntimeError("人脸核验服务暂时不可用,请稍后再试")
        return certify_id, certify_url

    async def result(self, ref: str, *, compare: bool = False) -> FaceResult:
        """compare=True:这次是 PV_FV 复核,要用复核那个场景 ID 去查。"""
        extra = ({"SceneId": settings.face_aliyun_compare_scene_id}
                 if compare and settings.face_aliyun_compare_scene_id else {})
        obj = await self._call("DescribeFaceVerify", {"CertifyId": ref, **extra})
        # 官方口径:以 Passed 为准(T 过,F 没过,中途放弃也是 F)
        if obj.get("Passed") == "T":
            return FaceResult(True, photo=_photo_of(obj.get("MaterialInfo")))
        code = str(obj.get("SubCode") or "")
        return FaceResult(False, _ALIYUN_SUBCODES.get(
            code, f"没有通过,请本人在光线充足的地方重试(代码 {code or '无'})"))


def _photo_of(material) -> tuple[str, str] | None:
    """从 DescribeFaceVerify 的 MaterialInfo 里取刷脸照片在 OSS 的位置。

    MaterialInfo 是一段 JSON **字符串**;照片在 facialPictureFront 下。
    场景没开留存或 OSS 没授权时这几个字段不返回 —— 取不到就是 None,不报错。
    """
    import json
    try:
        info = json.loads(material) if isinstance(material, str) else material
        front = (info or {}).get("facialPictureFront") or {}
        bucket = str(front.get("ossBucketName") or "")
        obj = str(front.get("ossObjectName") or "")
    except (ValueError, AttributeError):
        return None
    return (bucket, obj) if bucket and obj else None


async def delete_photo(bucket: str, obj: str) -> bool:
    """删掉 OSS 里留存的那张刷脸照片(注销账号时调)。成功 / 本来就没有 = True。

    走 OSS 的 REST DeleteObject(V1 签名,纯 httpx,不引 SDK)。
    RAM 子账号要有这个桶的 oss:DeleteObject 权限。
    """
    import base64
    import hashlib
    import hmac
    import urllib.parse
    from email.utils import formatdate

    import httpx

    if not (bucket and obj and settings.face_aliyun_access_key_id):
        return False
    date = formatdate(usegmt=True)
    resource = f"/{bucket}/{obj}"
    to_sign = f"DELETE\n\n\n{date}\n{resource}"
    sig = base64.b64encode(hmac.new(
        settings.face_aliyun_access_key_secret.encode(), to_sign.encode(),
        hashlib.sha1).digest()).decode()
    url = (f"https://{bucket}.{settings.face_aliyun_oss_endpoint}/"
           f"{urllib.parse.quote(obj)}")
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.delete(url, headers={
                "Date": date,
                "Authorization":
                    f"OSS {settings.face_aliyun_access_key_id}:{sig}"})
    except httpx.HTTPError as exc:
        logger.warning("删除留存人脸照片失败 %s: %s", resource, exc)
        return False
    # 204 删掉了;404 本来就没有。别的都算没删掉,留日志人工补
    if resp.status_code in (204, 404):
        return True
    logger.warning("删除留存人脸照片失败 %s: %s %s", resource,
                   resp.status_code, resp.text[:200])
    return False


def get_provider(dev_outcome: str = "") -> FaceProvider:
    """按配置挑服务商。没配:开发环境给假的,生产抛 RuntimeError(调用方回 503)。"""
    name = settings.face_provider.strip().lower()
    if not name:
        if not settings.is_dev:
            raise RuntimeError("人脸核验服务未配置")
        return FakeFaceProvider(dev_outcome or "pass")
    if name == "aliyun":
        if not settings.face_aliyun_configured:
            raise RuntimeError("人脸核验服务未配置")
        return AliyunFaceProvider()
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
