"""小程序开放平台的请求体(DEV-PROMPTS-39)。响应多是 dict,由 services/miniapp_platform.py 统一序列化。"""
import re

from pydantic import BaseModel, Field, field_validator, model_validator

_ORIGIN = r"^https://[A-Za-z0-9.-]+(:\d{1,5})?$"
#: 图标、截图只收平台自己的公开图片地址(/upload 的 miniapp_icon / miniapp_shot)——
#: 外链图片会让详情页替第三方的服务器统计访客
_IMAGE = r"^/img/miniapp_(icon|shot)/u\d+-[0-9a-f]{32}\.(jpg|jpeg|png|webp)$"


class LaunchIn(BaseModel):
    start_param: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{1,64}$")
    trial: bool = False
    platform: str = Field(default="unknown", pattern=r"^(android|ios|web|unknown)$")
    theme: dict | None = None


class ReportIn(BaseModel):
    reason_code: str = Field(pattern=r"^R\d{3}$")
    detail: str = Field(default="", max_length=500)
    evidence_keys: list[str] = Field(default_factory=list, max_length=3)


class StorageIn(BaseModel):
    keys: list[str] | None = None
    key: str | None = None
    value: str | None = None
    if_rev: int | None = None
    prefix: str = ""
    cursor: str = ""
    limit: int = 500


# ---------------- 开发者 ----------------

class DevProfileIn(BaseModel):
    display_name: str = Field(min_length=2, max_length=40)
    contact_email: str = Field(default="", max_length=120)


class DevVerifyIndividualIn(BaseModel):
    real_name: str = Field(min_length=2, max_length=20)
    id_no: str = Field(min_length=18, max_length=18)


class DevVerifyCompanyIn(BaseModel):
    company_name: str = Field(min_length=4, max_length=100)
    uscc: str = Field(pattern=r"^[0-9A-HJ-NPQRTUWXY]{18}$")
    license_key: str = Field(min_length=4, max_length=200)
    contact_name: str = Field(min_length=2, max_length=40)


class AgreementAcceptIn(BaseModel):
    revision: int = Field(ge=1)


class DevAppCreateIn(BaseModel):
    name: str = Field(min_length=2, max_length=20)
    kind: str = Field(pattern=r"^(app|game)$")
    category: str = Field(default="tools", max_length=16)
    tagline: str = Field(default="", max_length=30)


class DevAppUpdateIn(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=20)
    icon: str | None = Field(default=None, max_length=200)
    tagline: str | None = Field(default=None, max_length=30)
    description: str | None = Field(default=None, max_length=2000)
    category: str | None = Field(default=None, max_length=16)
    screenshots: list[str] | None = Field(default=None, max_length=6)
    privacy_policy: str | None = Field(default=None, max_length=8000)
    data_declaration: list[dict] | None = Field(default=None, max_length=20)

    @field_validator("icon")
    @classmethod
    def icon_one_char_or_image(cls, v):
        if v is None or v == "":
            return v
        if len(v) == 1 or re.match(_IMAGE, v):
            return v
        raise ValueError("图标写一个汉字,或者上传一张图片")

    @field_validator("screenshots")
    @classmethod
    def screenshots_are_images(cls, v):
        for s in v or []:
            if not isinstance(s, str) or not re.match(_IMAGE, s):
                raise ValueError("截图要先上传,填上传后返回的地址")
        return v

    @field_validator("data_declaration")
    @classmethod
    def declaration_shape(cls, v):
        for item in v or []:
            if not isinstance(item, dict) or not str(item.get("field") or "").strip() \
                    or not str(item.get("purpose") or "").strip():
                raise ValueError("数据声明每一项都要写 field(收集什么)和 purpose(为什么)")
        return v


class DomainsIn(BaseModel):
    request_domains: list[str] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def only_https_origins(self):
        import ipaddress
        import re
        for d in self.request_domains:
            if not re.match(_ORIGIN, d):
                raise ValueError(f"{d}:只能写 https 的 origin(协议 + 域名,结尾不带斜杠)")
            host = d[len("https://"):].split(":")[0].lower()
            if host in ("localhost",) or host.endswith(".localhost"):
                raise ValueError(f"{d}:不能是 localhost")
            try:
                ipaddress.ip_address(host)
                is_ip = True
            except ValueError:
                is_ip = False
            if is_ip or "." not in host:
                raise ValueError(f"{d}:不能是 IP 地址,要用备案过的域名")
        return self


class SubmitIn(BaseModel):
    review_note: str = Field(default="", max_length=1000)


class RollbackIn(BaseModel):
    version_id: int


class AutoReleaseIn(BaseModel):
    enabled: bool


class TesterIn(BaseModel):
    phone: str = Field(pattern=r"^1\d{10}$")


class CapabilityIn(BaseModel):
    capability: str = Field(max_length=24)
    justification: str = Field(min_length=10, max_length=300)


class AppealIn(BaseModel):
    text: str = Field(min_length=10, max_length=500)


# ---------------- 管理 ----------------

class VerifyDecisionIn(BaseModel):
    approve: bool
    reason: str = Field(default="", max_length=300)


class VersionDecisionIn(BaseModel):
    approve: bool
    reason_code: str = Field(default="", pattern=r"^(R\d{3})?$")
    note_public: str = Field(default="", max_length=500)
    note_internal: str = Field(default="", max_length=500)
    checklist: dict = Field(default_factory=dict)

    @model_validator(mode="after")
    def reject_needs_reason(self):
        if not self.approve and (not self.reason_code or not self.note_public.strip()):
            raise ValueError("驳回必须选原因代码,并写给开发者看的说明")
        return self


class PunishIn(BaseModel):
    reason_code: str = Field(pattern=r"^R\d{3}$")
    note_public: str = Field(min_length=4, max_length=500)
    note_internal: str = Field(default="", max_length=500)
    quarantine: bool = False


class CapabilityDecisionIn(BaseModel):
    approve: bool
    note: str = Field(default="", max_length=300)


class ReportHandleIn(BaseModel):
    resolution: str = Field(min_length=2, max_length=300)
    dismiss: bool = False


class AppealResolveIn(BaseModel):
    overturn: bool
    note_public: str = Field(min_length=4, max_length=500)
    note_internal: str = Field(default="", max_length=500)


class CurationIn(BaseModel):
    appid: str = Field(pattern=r"^sz[0-9a-f]{16}$")
    position: int = Field(ge=1, le=99)
    reason: str = Field(min_length=4, max_length=200)


class InviteIn(BaseModel):
    phone: str = Field(pattern=r"^1\d{10}$")
