"""骑手入驻门槛:该有的和不该有的(#165-#167)。

这些断言钉的是**法规口径**,不是实现细节。逐条的依据:

- 门槛只有姓名 + 身份证号:《人脸识别技术应用安全管理办法》(2025-06-01 施行)
  明写"存在其他非人脸方式能达到同等业务要求的,不得将人脸识别作为唯一验证
  方式",并鼓励优先用国家人口基础信息库 —— 二要素正是那个方式;
- 健康证不是法定要求:送餐员不属于"直接接触入口食品的人员";
- **食品安全培训是法定要求**:总局令第 123 号第二十九条,受托方应当对配送
  人员进行培训并留存记录 ≥2 年,罚则见第四十四条。这一条**不能被优化掉**。
"""
import json
from datetime import date
from pathlib import Path

from app.schemas import RiderProfileIn, RiderProfileOut
from app.services.idcheck import is_adult, validate_id_no

_DATA = Path(__file__).resolve().parents[2] / "app" / "data"


def _make_id(prefix17: str) -> str:
    """拼一个校验位正确的身份证号(测试用,非真实号码)。"""
    from app.services.idcheck import _CHECK_CHARS, _WEIGHTS
    return prefix17 + _CHECK_CHARS[
        sum(int(d) * w for d, w in zip(prefix17, _WEIGHTS)) % 11]


class Test门槛只有姓名和证号:
    def test_不收身份证照片(self):
        """二要素核验查的是人口库,不需要照片;
        而照片是敏感个人影像 —— 不收就没有泄露面。"""
        assert "id_card_photo_url" not in RiderProfileIn.model_fields

    def test_健康证选填(self):
        """国家层面不要求送餐员持健康证(不属于直接接触入口食品的人员),
        四川已明确取消。只有地方另有要求的城市才卡。"""
        f = RiderProfileIn.model_fields["health_cert_photo_url"]
        assert not f.is_required(), "健康证不能是必填 —— 法规没这个要求"

    def test_姓名和证号是必填(self):
        for name in ("real_name", "id_card_no"):
            assert RiderProfileIn.model_fields[name].is_required()

    def test_没有人脸相关字段(self):
        """有其他方式能达到同等目的时,不得把人脸作为唯一验证方式。
        入驻这条路上压根不该出现人脸。"""
        blob = " ".join(RiderProfileIn.model_fields).lower()
        for word in ("face", "liveness", "renlian", "人脸", "活体"):
            assert word not in blob


class Test证号不出接口:
    def test_返回体里没有证号(self):
        """骑手侧此前明文存 18 位**并直接出接口**,而用户侧早就加密了 ——
        同一个项目两套标准,这里对齐到严的那个。"""
        for bad in ("id_card_no", "id_no", "id_no_encrypted"):
            assert bad not in RiderProfileOut.model_fields, \
                f"{bad} 不该出现在对外返回体里"

    def test_姓名打码(self):
        """和用户侧 IdentityOut 一个口径:只回打码姓名。"""
        assert "real_name" in RiderProfileOut.model_fields


class Test年龄:
    def test_未成年不能接单(self):
        birth, err = validate_id_no(_make_id("11010120150307001"))
        assert err == "", err
        assert not is_adult(birth), "2015 年出生的显然未成年"

    def test_成年可以(self):
        birth, err = validate_id_no(_make_id("11010119900307001"))
        assert err == "" and is_adult(birth)

    def test_校验位不对要拦住(self):
        good = _make_id("11010119900307001")
        wrong = good[:17] + ("0" if good[17] != "0" else "1")
        _, err = validate_id_no(wrong)
        assert err, "校验位错误必须拦下,否则等于没有实名"


class Test食安培训是法定要求:
    """总局令第 123 号第二十九条。**这一条不能被"降门槛"优化掉。**"""

    def test_培训内容存在且标了法规依据(self):
        c = json.loads((_DATA / "rider_training.json").read_text("utf-8"))
        assert c["sections"], "培训内容不能是空的 —— 空的等于没培训"
        # 要让骑手知道这是法律要求平台做的,不是平台给他加的规矩
        assert "123" in c["why"] and "食品安全" in c["why"]

    def test_有内容版本(self):
        """法规要的是「培训记录」,光有分数证明不了培训了什么。
        内容改版后,旧记录仍要能说明当时培训的是哪一版。"""
        c = json.loads((_DATA / "rider_training.json").read_text("utf-8"))
        assert c.get("version"), "培训内容必须有版本号"

    def test_覆盖食安要点(self):
        """第三十条:配送人员应保持个人卫生、使用安全无害的配送容器、
        保持清洁并定期清洗消毒。这些要真的讲到。"""
        c = json.loads((_DATA / "rider_training.json").read_text("utf-8"))
        blob = json.dumps(c, ensure_ascii=False)
        for topic in ("封签", "清洗消毒", "餐箱"):
            assert topic in blob, f"培训内容里应当讲到「{topic}」"

    def test_三分钟能做完(self):
        """法规要培训到位,没要求它是一场考试。
        压到三分钟是为了让人真去做,而不是绕过它。"""
        c = json.loads((_DATA / "rider_training.json").read_text("utf-8"))
        assert 1 <= c["minutes"] <= 10

    def test_题库覆盖食安类(self):
        bank = json.loads((_DATA / "rider_quiz.json").read_text("utf-8"))
        cats = {q["cat"] for q in bank["questions"]}
        assert any("食" in c for c in cats), f"题库缺食安类:{cats}"


class Test培训记录留存:
    def test_记录表带内容版本字段(self):
        from app.models import RiderExam
        assert hasattr(RiderExam, "content_version")

    def test_记录不随注销删除(self):
        """个保法第四十七条把"法律、行政法规规定的保存期限未届满"
        列为删除义务的例外 —— 食安培训记录要留 2 年,法定保存优先。

        这里从文档层面钉住这个决定,防止后来有人"顺手"把它加进注销清理。
        """
        from app.models import RiderExam
        doc = RiderExam.__doc__ or ""
        assert "二年" in doc or "2 年" in doc
        assert "注销" in doc, "这个例外要写在模型文档里,否则迟早被误删"
