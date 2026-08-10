"""微信特约商户进件资料:敏感信息、完整度、校验(#203/#206)。

这些断言钉的是**规矩**,不是实现细节:

- 身份证号和银行账号密文落库,任何常规接口只回尾 4 位 ——
  **管理员也一样**。要看全号得走单独的 reveal 接口,每次留痕。
  这不是不信任同事:平台把「账目三方透明」写在首页,
  对用户隐私就不能反过来松;
- 必填清单只有服务端一份。三个前端(商家 App / merchant-web / 管理端)
  都问 `missing`,谁也别自己抄一份 —— 抄了就会有一天服务端加了字段
  而某个端没跟上,商家在那个端上看着 100% 却怎么也提交不成功;
- 身份证校验位**真算**(GB 11643-1999 加权模 11)。只判 18 位的话,
  随手打的 18 个数字也能过,而错号要等微信驳回才发现,一来一回好几天。
"""
import pytest
from pydantic import ValidationError

from app.schemas import (
    APPLYMENT_LOCKED_STATUSES,
    APPLYMENT_STATUS_LABELS,
    ApplymentIn,
    ApplymentOut,
    ApplymentRevealIn,
    ApplymentStatusIn,
    applyment_missing,
    applyment_out,
    applyment_required_total,
    next_applyment_status,
)
from app.services.crypto import decrypt, encrypt


def _make_id(prefix17: str = "11010119900307001") -> str:
    """拼一个校验位正确的身份证号(测试用,非真实号码)。"""
    from app.services.idcheck import _CHECK_CHARS, _WEIGHTS
    return prefix17 + _CHECK_CHARS[
        sum(int(d) * w for d, w in zip(prefix17, _WEIGHTS)) % 11]


ID_OK = _make_id()
ACCOUNT_OK = "6222021234567890123"


class _Shop:
    """Merchant 的替身:只带进件相关字段,取值与库里落好默认值后一致
    (列默认是 ""),不用起数据库就能测规则。"""

    def __init__(self, **over):
        self.id = 1
        self.name = "赞小碗"
        for f in ("subject_type", "business_license_image_url",
                  "legal_person_name", "legal_person_id_encrypted",
                  "legal_person_id_tail", "legal_person_id_front_url",
                  "legal_person_id_back_url", "admin_contact_name",
                  "admin_contact_phone", "admin_contact_email",
                  "settle_account_type", "settle_account_name",
                  "settle_bank_name", "settle_bank_branch",
                  "settle_account_no_encrypted", "settle_account_tail",
                  "applyment_no", "applyment_reject_reason"):
            setattr(self, f, "")
        self.applyment_status = "not_submitted"
        self.applyment_updated_at = None
        for k, v in over.items():
            setattr(self, k, v)


def _full_shop(**over) -> _Shop:
    """一家资料填齐的个体工商户。"""
    base = dict(
        subject_type="individual",
        business_license_image_url="/files/license/u1-abc.jpg",
        legal_person_name="王小明",
        legal_person_id_encrypted=encrypt(ID_OK),
        legal_person_id_tail=ID_OK[-4:],
        legal_person_id_front_url="/files/id_card/u1-front.jpg",
        legal_person_id_back_url="/files/id_card/u1-back.jpg",
        admin_contact_name="王小明",
        admin_contact_phone="13800138000",
        admin_contact_email="boss@example.com",
        settle_account_type="personal",
        settle_account_name="王小明",
        settle_bank_name="中国工商银行",
        settle_bank_branch="成都天府支行",
        settle_account_no_encrypted=encrypt(ACCOUNT_OK),
        settle_account_tail=ACCOUNT_OK[-4:],
    )
    base.update(over)
    return _Shop(**base)


class Test敏感字段只回尾号:
    def test_出参里没有明文字段(self):
        """结构性保证:ApplymentOut 上压根**不存在**放全号的字段。

        靠"记得别填"是靠不住的;字段不存在,想漏也漏不出去。
        """
        fields = set(ApplymentOut.model_fields)
        for leaked in ("legal_person_id_no", "settle_account_no",
                       "legal_person_id_encrypted",
                       "settle_account_no_encrypted"):
            assert leaked not in fields, f"{leaked} 不该出现在常规出参里"
        assert "legal_person_id_tail" in fields
        assert "settle_account_tail" in fields

    def test_序列化后既无明文也无密文(self):
        """密文同样不能出去:它是可以被离线爆破、或随密钥泄露一起被解开的东西,
        而接口方**根本不需要**它。"""
        shop = _full_shop()
        body = applyment_out(shop).model_dump_json()
        assert ID_OK not in body
        assert ACCOUNT_OK not in body
        assert shop.legal_person_id_encrypted not in body
        assert shop.settle_account_no_encrypted not in body

    def test_只给尾四位(self):
        out = applyment_out(_full_shop())
        assert out.legal_person_id_tail == ID_OK[-4:]
        assert out.settle_account_tail == ACCOUNT_OK[-4:]
        assert len(out.settle_account_tail) == 4

    def test_管理端与商家端共用同一个映射(self):
        """管理端不该有"看得更多"的第二套拼装 ——
        两处各拼一遍,规矩迟早在某一处被悄悄破掉。
        断言两个 router 引用的是**同一个函数对象**。"""
        from app.routers import admin, merchants
        assert admin.applyment_out is merchants.applyment_out is applyment_out

    def test_密文能解回原值(self):
        """加密是可逆的对称加密(Fernet),不是散列 ——
        平台报送微信时要拿回明文。"""
        assert decrypt(encrypt(ID_OK)) == ID_OK
        assert decrypt(encrypt(ACCOUNT_OK)) == ACCOUNT_OK

    def test_解不开时返回空串而不是抛(self):
        """密钥换过/数据损坏时 crypto.decrypt 给空串,
        reveal 接口据此给"请联系商家重新填写"的降级,而不是 500。"""
        assert decrypt("not-a-valid-token") == ""


class Test完整度:
    def test_空店缺全部必填(self):
        missing = applyment_missing(_Shop())
        assert len(missing) == applyment_required_total(_Shop())
        fields = {m["field"] for m in missing}
        # 敏感项判"填没填"看密文列,不看尾号(尾号是展示用的派生值)
        assert "legal_person_id_encrypted" in fields
        assert "settle_account_no_encrypted" in fields

    def test_每一项都带中文标签(self):
        """前端画「还差什么」直接用这个 label,不要各自维护一份翻译。"""
        for m in applyment_missing(_Shop()):
            assert m["label"] and isinstance(m["label"], str)

    def test_填齐即完整(self):
        out = applyment_out(_full_shop())
        assert out.complete is True
        assert out.missing == []
        assert out.filled_count == out.required_total

    def test_缺一项就不完整(self):
        shop = _full_shop(settle_bank_branch="")
        out = applyment_out(shop)
        assert out.complete is False
        assert [m["field"] for m in out.missing] == ["settle_bank_branch"]
        assert out.filled_count == out.required_total - 1

    def test_企业必须对公账户(self):
        """企业主体拿法人个人卡去开特约商户,微信侧一定驳回。
        与其等驳回回来,不如在我们这一侧就说清楚。"""
        shop = _full_shop(subject_type="enterprise",
                          settle_account_type="personal")
        out = applyment_out(shop)
        assert out.complete is False
        assert any(m["field"] == "settle_account_type" for m in out.missing)

    def test_企业对公则完整(self):
        shop = _full_shop(subject_type="enterprise",
                          settle_account_type="corporate")
        assert applyment_out(shop).complete is True

    def test_个体工商户对私可以(self):
        """个体户对公对私都行,不卡 —— 主体不同要交的东西本来就不完全一样。"""
        shop = _full_shop(subject_type="individual",
                          settle_account_type="personal")
        assert applyment_out(shop).complete is True

    def test_取值约束不占进度条格子(self):
        """「企业必须对公」是同一个字段的取值约束,不是多一项要填的东西。
        用 total - len(missing) 倒推会把进度条算少一格。"""
        shop = _full_shop(subject_type="enterprise",
                          settle_account_type="personal")
        out = applyment_out(shop)
        assert out.filled_count == out.required_total  # 14 项都填了
        assert out.missing                              # 但仍不算齐

    def test_状态有中文说明(self):
        """微信进件是异步的,中间有两个**要商家本人动手**的环节;
        状态页不说清楚,商家会以为提交完就没事了。"""
        for key in ("not_submitted", "submitted", "need_sign",
                    "need_account_verify", "rejected", "finished"):
            assert APPLYMENT_STATUS_LABELS[key]
        assert "扫码" in APPLYMENT_STATUS_LABELS["need_sign"]
        out = applyment_out(_Shop(applyment_status="need_sign"))
        assert out.applyment_status_label == APPLYMENT_STATUS_LABELS["need_sign"]


class Test身份证校验:
    def test_校验位正确的号能过(self):
        assert ApplymentIn(legal_person_id_no=ID_OK).legal_person_id_no == ID_OK

    def test_校验位错的号要拒(self):
        """这一条是重点:长度、生日全对,只有最后一位错。
        只判 18 位的实现会放它过去。"""
        wrong = ID_OK[:17] + ("0" if ID_OK[17] != "0" else "1")
        assert len(wrong) == 18
        with pytest.raises(ValidationError, match="校验位"):
            ApplymentIn(legal_person_id_no=wrong)

    def test_位数不对要拒(self):
        with pytest.raises(ValidationError):
            ApplymentIn(legal_person_id_no="11010119900307")

    def test_出生日期不合法要拒(self):
        bad = _make_id("11010119901307001")  # 13 月
        with pytest.raises(ValidationError, match="出生日期"):
            ApplymentIn(legal_person_id_no=bad)

    def test_末位小写x也认(self):
        """商家在手机上多半打的是小写 x;为这个把人拦下来毫无意义。"""
        # 前 14 位固定成合法生日(110101 + 19900307),只穷举后 3 位顺序码
        x_id = next(_make_id(f"11010119900307{n:03d}")
                    for n in range(1000)
                    if _make_id(f"11010119900307{n:03d}")[17] == "X")
        assert ApplymentIn(legal_person_id_no=x_id.lower())


class Test其它格式校验:
    def test_手机号(self):
        with pytest.raises(ValidationError, match="手机号"):
            ApplymentIn(admin_contact_phone="1380013800")
        assert ApplymentIn(admin_contact_phone="13800138000")

    def test_邮箱(self):
        """超级管理员邮箱填错 = 商家永远收不到微信的「该你签约了」。"""
        for bad in ("boss@", "boss", "boss@example", "a b@c.com"):
            with pytest.raises(ValidationError, match="邮箱"):
                ApplymentIn(admin_contact_email=bad)
        assert ApplymentIn(admin_contact_email="boss@example.com")

    def test_银行账号必须是数字(self):
        with pytest.raises(ValidationError, match="银行账号"):
            ApplymentIn(settle_account_no="6222-0212-3456")
        with pytest.raises(ValidationError, match="银行账号"):
            ApplymentIn(settle_account_no="12345")  # 太短

    def test_银行账号允许粘贴带空格(self):
        assert ApplymentIn(settle_account_no="6222 0212 3456 7890 123")

    def test_证件照必须在私密桶(self):
        """客户端要是拿 purpose=shop 传了身份证,这里拦住 ——
        否则一张身份证会静静躺在公开桶里,而谁都不会发现。"""
        with pytest.raises(ValidationError, match="私密"):
            ApplymentIn(legal_person_id_front_url="/img/shop/abc.jpg")
        with pytest.raises(ValidationError, match="私密"):
            ApplymentIn(business_license_image_url="/img/shop/abc.jpg")
        assert ApplymentIn(legal_person_id_front_url="/files/id_card/u1-a.jpg")
        assert ApplymentIn(business_license_image_url="/files/license/u1-a.jpg")

    def test_全部字段可选(self):
        """PUT 是「把这次填的存下来」,不是「一次填完才准提交」——
        商家分几次填是常态,强制一次填完的结果是填到一半退出去就全丢。"""
        assert ApplymentIn().model_dump(exclude_unset=True) == {}
        for f in ApplymentIn.model_fields.values():
            assert not f.is_required()

    def test_主体类型与账户类型是枚举(self):
        with pytest.raises(ValidationError):
            ApplymentIn(subject_type="company")
        with pytest.raises(ValidationError):
            ApplymentIn(settle_account_type="public")


class Test提交后的状态流转:
    def test_填齐即视为已提交(self):
        """商家的动作到此为止,球在平台这边。"""
        assert next_applyment_status("not_submitted", complete=True) == "submitted"

    def test_驳回后改齐了重新提交(self):
        assert next_applyment_status("rejected", complete=True) == "submitted"

    def test_没填齐不提交(self):
        assert next_applyment_status("not_submitted", complete=False) is None

    def test_提交后清空某项要退回(self):
        """不退的话它会一直挂在平台的待报送队列里,报上去必被驳回。"""
        assert next_applyment_status("submitted", complete=False) == "not_submitted"

    def test_已提交且仍完整则不动(self):
        """改个开户支行的错别字不该把状态刷一遍。"""
        assert next_applyment_status("submitted", complete=True) is None

    def test_微信侧已在流转的状态一律不动(self):
        """待签约/待账户验证/已开通:这三个状态下商家的资料根本不该再改
        (路由层直接 409),这里再兜一道,保证纯函数自己也不会把状态往回带。"""
        for locked in APPLYMENT_LOCKED_STATUSES:
            assert next_applyment_status(locked, complete=True) is None
            assert next_applyment_status(locked, complete=False) is None

    def test_锁定状态就是那三个(self):
        assert set(APPLYMENT_LOCKED_STATUSES) == {
            "need_sign", "need_account_verify", "finished"}


class Test平台侧流转与留痕:
    def test_驳回必须写原因(self):
        """商家要照着改;空原因等于没驳回。"""
        with pytest.raises(ValidationError, match="原因"):
            ApplymentStatusIn(status="rejected")
        assert ApplymentStatusIn(status="rejected", reject_reason="执照照片糊了")
        assert ApplymentStatusIn(status="finished")  # 其它状态不要求

    def test_查看全号必须说明理由(self):
        """留痕留一个空理由等于没留。"""
        with pytest.raises(ValidationError):
            ApplymentRevealIn(field="legal_person_id_no", reason="")
        assert ApplymentRevealIn(field="settle_account_no", reason="报送微信核对")

    def test_只能解密这两个字段(self):
        with pytest.raises(ValidationError):
            ApplymentRevealIn(field="admin_contact_phone", reason="随便看看")
