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
        monkeypatch.setattr(settings, "face_provider", "tencent")
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


class Test阿里云:
    """阿里云金融级实人认证(ID_PRO,H5)。打的是假的 HTTP,验请求长什么样、结果怎么判。"""

    @pytest.fixture
    def aliyun(self, monkeypatch):
        monkeypatch.setattr(settings, "face_provider", "aliyun")
        monkeypatch.setattr(settings, "face_aliyun_access_key_id", "ak")
        monkeypatch.setattr(settings, "face_aliyun_access_key_secret", "sk")
        monkeypatch.setattr(settings, "face_aliyun_scene_id", "1000001")
        monkeypatch.setattr(settings, "public_base_url", "https://x.test")
        sent = []
        import httpx
        real = httpx.AsyncClient  # 只取一次:装第二个回复时不能把上一个假的当成真的

        def install(reply: dict):
            def handler(request):
                from urllib.parse import parse_qsl
                sent.append(dict(parse_qsl(request.content.decode())))
                return httpx.Response(200, json=reply)

            monkeypatch.setattr(
                httpx, "AsyncClient",
                lambda **kw: real(transport=httpx.MockTransport(handler)))
        return install, sent

    def test_没配全不放行(self, monkeypatch):
        monkeypatch.setattr(settings, "face_provider", "aliyun")
        monkeypatch.setattr(settings, "face_aliyun_scene_id", "")
        with pytest.raises(RuntimeError, match="未配置"):
            facecheck.get_provider()

    def test_发起时不调阿里云_给中转页(self, aliyun):
        p = facecheck.get_provider()
        s = asyncio.run(p.start(purpose="enroll", rider_id=1, real_name="王",
                                id_no="", enroll_ref=""))
        assert s.ref.startswith(facecheck.PENDING_PREFIX)
        token = s.ref[len(facecheck.PENDING_PREFIX):]
        assert len(token) == 32
        assert s.verify_url == f"https://x.test/riders/face/h5/{token}"

    def test_中转页换刷脸地址_请求带签名和公安比对参数(self, aliyun):
        install, sent = aliyun
        install({"Code": "200", "ResultObject": {
            "CertifyId": "cid1", "CertifyUrl": "https://ali/x"}})
        cid, url = asyncio.run(facecheck.get_provider().init_h5(
            outer_order_no="rf" + "0" * 30, rider_id=9, real_name="王小明",
            id_no="110101199003072316", meta_info="{}",
            return_url="https://x.test/riders/face/h5-done"))
        assert (cid, url) == ("cid1", "https://ali/x")
        req = sent[0]
        assert req["Action"] == "InitFaceVerify"
        assert req["ProductCode"] == "ID_PRO" and req["SceneId"] == "1000001"
        assert req["CertName"] == "王小明" and req["MetaInfo"] == "{}"
        assert req["Signature"] and req["AccessKeyId"] == "ak"

    def test_过没过以Passed为准_没过给人话(self, aliyun):
        install, sent = aliyun
        install({"Code": "200", "ResultObject": {"Passed": "T"}})
        assert asyncio.run(facecheck.get_provider().result("cid1")).passed
        assert sent[0]["Action"] == "DescribeFaceVerify"
        assert sent[0]["CertifyId"] == "cid1"

        install({"Code": "200", "ResultObject": {"Passed": "F", "SubCode": "204"}})
        r = asyncio.run(facecheck.get_provider().result("cid1"))
        assert r.passed is False and "不是同一个人" in r.reason

    def test_接口报错不放行(self, aliyun):
        install, _ = aliyun
        install({"Code": "401", "Message": "签名错"})
        with pytest.raises(RuntimeError, match="暂时不可用"):
            asyncio.run(facecheck.get_provider().result("cid1"))


class Test留存照片复核:
    """2026-10-08 定了"存照片换便宜的复核":首次 ID_PRO 留照片,复核 PV_FV 拿它比对。"""

    @pytest.fixture
    def aliyun(self, monkeypatch):
        import httpx
        monkeypatch.setattr(settings, "face_provider", "aliyun")
        monkeypatch.setattr(settings, "face_aliyun_access_key_id", "ak")
        monkeypatch.setattr(settings, "face_aliyun_access_key_secret", "sk")
        monkeypatch.setattr(settings, "face_aliyun_scene_id", "111")
        monkeypatch.setattr(settings, "face_aliyun_compare_scene_id", "222")
        sent = []
        real = httpx.AsyncClient

        def install(status=200, reply=None):
            def handler(request):
                from urllib.parse import parse_qsl
                sent.append((request.method, str(request.url), request.headers,
                             dict(parse_qsl(request.content.decode()))))
                return httpx.Response(status, json=reply or {})
            monkeypatch.setattr(
                httpx, "AsyncClient",
                lambda **kw: real(transport=httpx.MockTransport(handler)))
        return install, sent

    def test_首次通过带回照片位置(self, aliyun):
        install, _ = aliyun
        import json
        material = json.dumps({"facialPictureFront": {
            "ossBucketName": "superz-face", "ossObjectName": "a/b.jpg"}})
        install(reply={"Code": "200", "ResultObject": {
            "Passed": "T", "MaterialInfo": material}})
        r = asyncio.run(facecheck.get_provider().result("cid"))
        assert r.photo == ("superz-face", "a/b.jpg")

    def test_场景没开留存_照片为空不报错(self, aliyun):
        install, _ = aliyun
        install(reply={"Code": "200", "ResultObject": {
            "Passed": "T", "MaterialInfo": "{}"}})
        assert asyncio.run(facecheck.get_provider().result("cid")).photo is None

    def test_复核用PV_FV和留存照片比对_不传证号(self, aliyun):
        install, sent = aliyun
        install(reply={"Code": "200", "ResultObject": {
            "CertifyId": "c2", "CertifyUrl": "https://ali/y"}})
        asyncio.run(facecheck.get_provider().init_h5(
            outer_order_no="rf" + "0" * 30, rider_id=9, real_name="王小明",
            id_no="110101199003072316", meta_info="{}", return_url="r",
            photo=("superz-face", "a/b.jpg")))
        req = sent[0][3]
        assert req["ProductCode"] == "PV_FV" and req["SceneId"] == "222"
        assert req["OssBucketName"] == "superz-face"
        assert req["OssObjectName"] == "a/b.jpg"
        assert "CertNo" not in req, "复核不需要证号,能不传就不传"

    def test_复核查结果用复核场景(self, aliyun):
        install, sent = aliyun
        install(reply={"Code": "200", "ResultObject": {"Passed": "T"}})
        asyncio.run(facecheck.get_provider().result("c2", compare=True))
        assert sent[0][3]["SceneId"] == "222"

    def test_没配复核场景_退回公安库比对(self, aliyun, monkeypatch):
        install, sent = aliyun
        monkeypatch.setattr(settings, "face_aliyun_compare_scene_id", "")
        install(reply={"Code": "200", "ResultObject": {
            "CertifyId": "c3", "CertifyUrl": "https://ali/z"}})
        asyncio.run(facecheck.get_provider().init_h5(
            outer_order_no="rf" + "0" * 30, rider_id=9, real_name="王小明",
            id_no="110101199003072316", meta_info="{}", return_url="r",
            photo=("superz-face", "a/b.jpg")))
        assert sent[0][3]["ProductCode"] == "ID_PRO"
        assert sent[0][3]["CertNo"] == "110101199003072316"

    def test_注销删照片_签名请求发到对应桶(self, aliyun):
        install, sent = aliyun
        install(status=204)
        assert asyncio.run(facecheck.delete_photo("superz-face", "a/b.jpg"))
        method, url, headers, _ = sent[0]
        assert method == "DELETE"
        assert url == "https://superz-face.oss-cn-shanghai.aliyuncs.com/a/b.jpg"
        assert headers["Authorization"].startswith("OSS ak:")

    def test_注销删照片_本来就没有也算删了_别的错如实报(self, aliyun):
        install, _ = aliyun
        install(status=404)
        assert asyncio.run(facecheck.delete_photo("b", "o"))
        install(status=403)
        assert not asyncio.run(facecheck.delete_photo("b", "o"))
