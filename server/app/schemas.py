from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .models import (
    AfterSaleStatus,
    MerchantStatus,
    TicketStatus,
    VerifyStatus,
    WithdrawalStatus,
)
from .state_machine import STATUS_LABELS, OrderStatus


# ---------- 认证 ----------
class RegisterIn(BaseModel):
    phone: str = Field(pattern=r"^1\d{10}$")
    password: str = Field(min_length=6, max_length=64)
    name: str = ""
    role: str = Field(pattern="^(customer|merchant|rider)$")


class LoginIn(BaseModel):
    phone: str
    password: str
    device_id: str = Field(default="", max_length=64)  # 风控用轻量设备指纹


class SmsCodeIn(BaseModel):
    phone: str = Field(pattern=r"^1\d{10}$")
    # 滑块验证(同号当日第 3 条起要求):/auth/slider 领票,滑到位后随发码提交
    ticket: str = Field(default="", max_length=64)
    slide: int | None = Field(default=None, ge=0, le=100)


class SmsLoginIn(BaseModel):
    phone: str = Field(pattern=r"^1\d{10}$")
    code: str = Field(pattern=r"^\d{6}$")
    device_id: str = Field(default="", max_length=64)
    # 新手机号自动注册时的角色(三端各传各的;已有账号忽略此参数保原角色)
    role: str = Field(default="customer", pattern="^(customer|merchant|rider)$")


class TokenOut(BaseModel):
    token: str
    user_id: int
    role: str
    name: str


class MeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    phone: str
    name: str
    role: str
    avatar_url: str
    birthday: str = ""
    marketing_push: bool = True
    # 反作弊处置(非空即对用户可见,客户端据此显示提示+申诉入口)
    risk_level: str = ""
    risk_note: str = ""


class MePatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=50)
    avatar_url: str | None = Field(default=None, max_length=300)
    # 生日 MM-DD(生日当天发券;传空串清除);营销推送开关
    birthday: str | None = Field(
        default=None, pattern=r"^(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])$|^$")
    marketing_push: bool | None = None


class IdentityIn(BaseModel):
    """实名认证提交:姓名 + 身份证号。证号加密落库,明文不出接口。"""

    real_name: str = Field(min_length=2, max_length=50)
    id_no: str = Field(min_length=18, max_length=18)


class IdentityOut(BaseModel):
    verified: bool
    is_adult: bool = False
    real_name: str = ""  # 打码姓名(如 王*),仅供界面展示


# ---------- 商家 / 菜品 ----------
class MerchantIn(BaseModel):
    name: str
    description: str = ""
    address: str = ""
    lat: float
    lng: float
    license_no: str = ""
    license_image_url: str = ""  # 证照照片(新申请必传,老库存量允许为空)
    # 外卖品类(白名单校验在路由,清单见 categories.py)
    category: str = "fast_food"


class MerchantOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: str
    address: str
    lat: float
    lng: float
    city: str = ""  # 所在城市(入驻时逆地理解析;开城清单外不可营业)
    category: str = "fast_food"  # 外卖品类(清单见 categories.py)
    is_open: bool
    commission_rate: Decimal
    status: MerchantStatus = MerchantStatus.approved
    reject_reason: str = ""
    rating_avg: float | None = None
    rating_count: int = 0
    announcement: str = ""
    logo_url: str = ""
    min_order_cents: int = 0
    packing_fee_cents: int = 0
    promo_rules: list = []
    gift_rules: list = []  # 满赠 [{threshold_cents, dish_id, name}]
    holiday_plans: list = []  # 节假日计划 [{from,to,closed,open,close}]
    closed_until: datetime | None = None  # 临时歇业到此刻,到点自动恢复
    photo_urls: list = []  # 门店相册
    open_time: str = ""
    close_time: str = ""
    promise_ready_minutes: int = 15  # 承诺出餐时长(分钟)
    self_delivery: bool = False  # 商家自配送(开启后订单不进抢单池)
    monthly_sales: int = 0  # 近 30 天完成单数,仅店铺详情接口计算
    # 招牌菜(名/价/图,最多 3 个):列表页给足"这家卖什么"的决策信息
    top_dishes: list = []
    # 当前查看者是否为店员(仅 GET /merchants/me 填充,客户端据此隐藏提现/改价入口)
    viewer_is_staff: bool = False


class AdminMerchantOut(MerchantOut):
    """审核后台视角:多了证照和店主联系方式。"""

    license_no: str = ""
    license_image_url: str = ""
    owner_name: str = ""
    owner_phone: str = ""
    # 分账(二清收口):特约商户号+就绪标记(就绪后新订单货款走分账)
    sub_mchid: str = ""
    ps_ready: bool = False
    created_at: datetime | None = None
    # 经营质量(近 30 天,列表页聚合填充)
    rejects_30d: int = 0
    ready_late_30d: int = 0


class RejectIn(BaseModel):
    reason: str = Field(min_length=2, max_length=200)


class PaidNoteIn(BaseModel):
    note: str = Field(default="", max_length=200)  # 打款凭证/批次号


class BatchPaidIn(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=200)
    note: str = Field(default="", max_length=200)


class PromoRule(BaseModel):
    threshold_cents: int = Field(gt=0, le=100_000)  # 满 X
    off_cents: int = Field(gt=0, le=100_000)        # 减 Y

    @model_validator(mode="after")
    def off_less_than_threshold(self):
        if self.off_cents >= self.threshold_cents:
            raise ValueError("减的金额必须小于门槛(不能倒贴)")
        return self


class RestIn(BaseModel):
    """临时歇业:歇业 N 小时或到今天打烊,二选一。到点自动恢复营业。"""

    hours: int | None = Field(default=None, ge=1, le=72)
    until_close: bool = False

    @model_validator(mode="after")
    def one_of(self):
        if (self.hours is None) == (not self.until_close):
            raise ValueError("请选择歇业时长或「歇业到今天打烊」")
        return self


_HHMM = r"^([01]\d|2[0-3]):[0-5]\d$"
_DATE = r"^\d{4}-\d{2}-\d{2}$"


class HolidayPlan(BaseModel):
    """节假日计划一条:日期区间歇业,或特殊营业时段。"""

    from_date: str = Field(alias="from", pattern=_DATE)
    to_date: str = Field(default="", alias="to", pattern=f"{_DATE}|^$")
    closed: bool = True
    open: str = Field(default="", pattern=f"{_HHMM}|^$")
    close: str = Field(default="", pattern=f"{_HHMM}|^$")

    @model_validator(mode="after")
    def sane(self):
        if not self.to_date:
            self.to_date = self.from_date
        if self.to_date < self.from_date:
            raise ValueError("结束日期不能早于开始日期")
        if not self.closed and not (self.open and self.close):
            raise ValueError("特殊营业时段需要填开始和结束时间")
        return self


class GiftRule(BaseModel):
    """满赠:满 threshold 赠 dish_id 一份。name 存快照,展示不用再查菜。"""

    threshold_cents: int = Field(gt=0, le=100_000)
    dish_id: int = Field(gt=0)
    name: str = Field(default="", max_length=60)


class MerchantPatch(BaseModel):
    is_open: bool | None = None
    name: str | None = None
    # 品类不是资质项:随时可改即时生效,管理员可纠错
    category: str | None = None
    description: str | None = None
    address: str | None = None
    license_no: str | None = None
    license_image_url: str | None = None
    announcement: str | None = None
    logo_url: str | None = None
    # "HH:MM" 或空串(清除设置)
    open_time: str | None = Field(default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$|^$")
    close_time: str | None = Field(default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$|^$")
    # 运营三件套
    min_order_cents: int | None = Field(default=None, ge=0, le=100_000)
    packing_fee_cents: int | None = Field(default=None, ge=0, le=10_000)
    promo_rules: list[PromoRule] | None = Field(default=None, max_length=3)
    gift_rules: list[GiftRule] | None = Field(default=None, max_length=2)
    holiday_plans: list[HolidayPlan] | None = Field(default=None, max_length=20)
    photo_urls: list[str] | None = Field(default=None, max_length=9)  # 门店相册
    promise_ready_minutes: int | None = Field(default=None, ge=5, le=60)
    self_delivery: bool | None = None  # 自配送开关(只影响之后的新订单)


class PrinterOut(BaseModel):
    """云打印机状态。enabled=平台是否配置了打印服务商(未配置时前端隐藏绑定入口)。"""

    enabled: bool
    sn: str = ""
    auto: bool = True


class PrinterBindIn(BaseModel):
    sn: str = Field(min_length=4, max_length=32)
    key: str = Field(min_length=4, max_length=32)
    remark: str = Field(default="", max_length=30)


class PrinterPatch(BaseModel):
    auto: bool


class OptionChoice(BaseModel):
    name: str = Field(min_length=1, max_length=20)
    delta_cents: int = Field(default=0, ge=0, le=100_000)  # 加价,不允许负(改价请改基础价)


class OptionGroup(BaseModel):
    name: str = Field(min_length=1, max_length=20)   # 如「份量」「加料」
    required: bool = False                            # 必选(如份量必须二选一)
    multi: bool = False                               # 可多选(如加料)
    choices: list[OptionChoice] = Field(min_length=1, max_length=10)

    @model_validator(mode="after")
    def names_unique(self):
        names = [c.name for c in self.choices]
        if len(names) != len(set(names)):
            raise ValueError("同一规格组内选项名不能重复")
        return self


class DishIn(BaseModel):
    name: str
    category: str = ""
    price_cents: int = Field(gt=0)
    stock: int = Field(default=100, ge=0)
    daily_stock: int | None = Field(default=None, ge=0, le=100_000)
    is_alcohol: bool = False  # 酒类:购买需实名且成年,商家上架自助勾选
    image_url: str = ""
    options: list[OptionGroup] = Field(default=[], max_length=5)


class DishPatch(BaseModel):
    name: str | None = None
    category: str | None = None
    price_cents: int | None = Field(default=None, gt=0)
    stock: int | None = Field(default=None, ge=0)
    # 每日回满目标(传 null 关闭)。与其他字段不同,None 是有效值,
    # 用 model_fields_set 判断是否显式传了本字段
    daily_stock: int | None = Field(default=None, ge=0, le=100_000)
    is_on_sale: bool | None = None
    is_alcohol: bool | None = None
    image_url: str | None = None
    options: list[OptionGroup] | None = Field(default=None, max_length=5)
    # 限时折扣:两者同传开启,同传 null 关闭(折扣价必须低于现价,服务端校验)
    flash_price_cents: int | None = Field(default=None, gt=0)
    flash_until: datetime | None = None


class DishOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    merchant_id: int
    name: str
    category: str
    price_cents: int
    stock: int
    daily_stock: int | None = None
    sold_out_today: bool = False  # 估清(今日售罄):用户端灰态徽标,区别于下架
    is_on_sale: bool
    is_alcohol: bool = False  # 酒类:「酒」角标 + 未成年人禁止购买提示
    image_url: str
    options: list = []
    flash_price_cents: int | None = None
    flash_until: datetime | None = None
    monthly_sales: int = 0  # 近 30 天售出份数,菜单接口填充


# ---------- 平台:公告 / 埋点 ----------
class AnnouncementIn(BaseModel):
    audience: str = Field(pattern="^(user|merchant|rider|all)$")
    title: str = Field(min_length=2, max_length=50)
    content: str = Field(min_length=2, max_length=500)
    starts_at: datetime | None = None
    ends_at: datetime | None = None


class AnnouncementPatch(BaseModel):
    is_active: bool | None = None
    title: str | None = Field(default=None, min_length=2, max_length=50)
    content: str | None = Field(default=None, min_length=2, max_length=500)
    ends_at: datetime | None = None


class SplashIn(BaseModel):
    audience: str = Field(default="all", pattern="^(user|merchant|rider|all)$")
    title: str = Field(default="", max_length=50)
    subtitle: str = Field(default="", max_length=100)
    image_url: str = Field(min_length=1, max_length=300)
    countdown_seconds: int = Field(default=3, ge=2, le=8)
    starts_at: datetime | None = None
    ends_at: datetime | None = None


class SplashOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    audience: str
    title: str
    subtitle: str
    image_url: str
    countdown_seconds: int
    is_active: bool
    starts_at: datetime | None
    ends_at: datetime | None
    created_at: datetime


class AnnouncementOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    audience: str
    title: str
    content: str
    is_active: bool
    starts_at: datetime | None
    ends_at: datetime | None
    created_at: datetime


class EventIn(BaseModel):
    name: str = Field(min_length=1, max_length=50)
    props: dict = Field(default={})


class EventsIn(BaseModel):
    events: list[EventIn] = Field(min_length=1, max_length=50)


# ---------- 团购券 ----------
class VoucherIn(BaseModel):
    title: str = Field(min_length=2, max_length=80)
    description: str = Field(default="", max_length=200)
    sell_price_cents: int = Field(gt=0, le=1_000_000)
    face_value_cents: int = Field(gt=0, le=1_000_000)
    total_count: int = Field(gt=0, le=100_000)
    per_user_limit: int = Field(default=5, gt=0, le=50)
    valid_days: int = Field(default=90, gt=0, le=365)


class VoucherPatch(BaseModel):
    is_active: bool | None = None
    total_count: int | None = Field(default=None, ge=0, le=100_000)
    description: str | None = Field(default=None, max_length=200)


class VoucherOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    merchant_id: int
    title: str
    description: str
    sell_price_cents: int
    face_value_cents: int
    total_count: int
    sold_count: int
    per_user_limit: int
    valid_days: int
    is_active: bool
    merchant_name: str = ""  # 路由层填充
    merchant_logo: str = ""


class VoucherPurchaseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    purchase_no: str
    voucher_id: int
    merchant_id: int
    sell_price_cents: int
    face_value_cents: int
    commission_cents: int
    net_cents: int
    code: str
    status: str
    expires_at: datetime | None
    refund_note: str = ""
    created_at: datetime
    redeemed_at: datetime | None = None
    title: str = ""          # 路由层填充
    merchant_name: str = ""
    merchant_address: str = ""   # 到店导航用
    merchant_lat: float | None = None
    merchant_lng: float | None = None
    expired: bool = False    # 视图状态:paid 但已过有效期


class VoucherRedeemIn(BaseModel):
    code: str = Field(min_length=6, max_length=16)


# ---------- 订单 ----------
class OrderItemIn(BaseModel):
    dish_id: int
    quantity: int = Field(gt=0, le=99)
    # 选中的规格/加料名(跨组扁平,如 ["大份","加蛋"])。
    # 价格由服务端按菜品 options 重算,客户端传价无效
    choices: list[str] = Field(default=[], max_length=20)


class FoodSafetyIn(BaseModel):
    """食安投诉提交:强制拍照,医疗凭证选传。"""

    order_no: str
    kind: Literal["foreign_object", "spoiled", "sick"]
    description: str = Field(min_length=4, max_length=500)
    images: list[str] = Field(min_length=1, max_length=6)
    medical_urls: list[str] = Field(default=[], max_length=6)


class FoodSafetyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    order_no: str
    kind: str
    description: str
    images: list
    medical_urls: list
    status: str
    actions: list = []
    created_at: datetime
    resolved_at: datetime | None = None


class AdminFoodSafetyOut(FoodSafetyOut):
    customer_id: int
    merchant_id: int
    merchant_name: str = ""
    customer_phone: str = ""
    order_total_cents: int = 0
    order_items: list = []       # 供后台选择下架涉事菜品
    merchant_is_open: bool = True


class FoodSafetyActionIn(BaseModel):
    note: str = Field(default="", max_length=300)
    dish_id: int | None = None   # take-down-dish 用


class TransferIn(BaseModel):
    """骑手转单:已抢未取餐的单退回抢单池。原因只留痕不判责。"""

    reason: Literal["vehicle_broken", "unwell", "route_conflict", "other"]


class TransferOut(BaseModel):
    today_count: int      # 今日已转单次数(含本次)
    free_times: int       # 每日免责次数(超出仍可转,计入考核参考)
    suspend_threshold: int = 0  # 非免责转单达此数,当日暂停抢单(次日恢复)


class DeliveryIssueIn(BaseModel):
    order_no: str
    # 途中异常:cannot_contact 联系不上 / wrong_address 地址错 / food_damaged 餐损
    # 交接异常:not_ready 到店未出餐(催商家) / items_missing 餐不齐(平台仲裁)
    kind: Literal["cannot_contact", "wrong_address", "food_damaged",
                  "not_ready", "items_missing", "other"]
    note: str = Field(default="", max_length=300)
    photo_url: str = Field(default="", max_length=300)  # 餐损/餐不齐必传,路由校验


class DeliveryIssueOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    order_no: str
    rider_id: int
    kind: str
    note: str
    photo_url: str
    status: str
    resolution: str
    resolve_note: str
    created_at: datetime
    resolved_at: datetime | None
    # 管理后台仲裁需要的现场信息(路由层填充)
    rider_name: str = ""
    rider_phone: str = ""
    contact_phone: str = ""
    address: str = ""
    total_cents: int = 0
    order_status: str = ""


class DeliveryIssueResolveIn(BaseModel):
    action: Literal["continue_delivery", "mark_delivered", "refund"]
    note: str = Field(default="", max_length=300)


class ChangeAddressIn(BaseModel):
    address: str = Field(min_length=4, max_length=200)
    lat: float
    lng: float
    contact_name: str = Field(default="", max_length=50)
    contact_phone: str = Field(default="", max_length=20)


class PickupVerifyIn(BaseModel):
    code: str = Field(min_length=1, max_length=8)


class BoostTipIn(BaseModel):
    """加急小费:在无人接单时追加的小费(分),累加到现有小费上。"""

    add_cents: int = Field(gt=0, le=5000)  # 单次追加 0.01–50 元


class ShopCouponBatchIn(BaseModel):
    """商家自建店铺券:满 threshold 减 off,限量、每人限领、有效期。成本商家承担。"""

    name: str = Field(min_length=2, max_length=50)
    threshold_cents: int = Field(ge=0, le=100_000)   # 满 X(0=无门槛)
    off_cents: int = Field(gt=0, le=50_000)          # 减 Y
    total: int = Field(gt=0, le=100_000)             # 发行总量(预算封顶)
    per_user_limit: int = Field(default=1, ge=1, le=10)
    valid_days: int = Field(default=7, ge=1, le=90)

    @model_validator(mode="after")
    def off_lt_threshold(self):
        if self.threshold_cents and self.off_cents >= self.threshold_cents:
            raise ValueError("减的金额必须小于门槛(不能倒贴)")
        return self


class ShopCouponBatchOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    threshold_cents: int = 0   # = min_spend_cents
    off_cents: int = 0         # = amount_cents
    total: int
    issued: int
    per_user_limit: int
    valid_days: int
    active: bool


class ClaimableCouponOut(BaseModel):
    """用户在某店可领/已领的券。"""
    batch_id: int
    name: str
    threshold_cents: int
    off_cents: int
    remaining: int          # 该批剩余可发数
    claimed_by_me: int      # 我已领数
    can_claim: bool


class CartIn(BaseModel):
    """整份覆盖保存云端购物车。空 items 表示清空该店购物车。"""

    items: list[OrderItemIn] = Field(default=[], max_length=50)


class CartOut(BaseModel):
    merchant_id: int
    items: list = []


class OrderCreateIn(BaseModel):
    merchant_id: int
    items: list[OrderItemIn] = Field(min_length=1)
    # 加菜:传原单号则创建追加单(免配送费/免起送价,地址与骑手随原单)
    append_to: str = ""
    # 到店自取:免配送费、不走骑手,地址三件套可不传(服务端落商家坐标)
    pickup: bool = False
    address: str = ""
    lat: float | None = None
    lng: float | None = None
    contact_name: str = ""
    contact_phone: str = ""
    remark: str = ""
    scheduled_at: datetime | None = None  # 预约送达/预约自取(空 = 尽快)
    # 小费(分):100% 归骑手,平台不抽不计佣;自取单不收
    tip_cents: int = Field(default=0, ge=0, le=5000)
    # 平台券抵扣(超时安抚券等):平台承担,走 subsidy 口径
    coupon_id: int | None = None
    # 拼单码:发起人锁单后用它下单,服务端校验并原子关车
    group_code: str = ""
    # 地址保护(随所选地址):开启则骑手只见粗地址(address_public)与中性称呼
    addr_protect: bool = False
    address_public: str = Field(default="", max_length=200)
    salutation: str = Field(default="", max_length=12)


class OrderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    order_no: str
    customer_id: int
    merchant_id: int
    rider_id: int | None
    status: OrderStatus
    items: list
    food_cents: int
    packing_fee_cents: int = 0
    discount_cents: int = 0
    subsidy_cents: int = 0
    promo_note: str = ""
    delivery_fee_cents: int
    tip_cents: int = 0  # 小费,100% 归骑手
    total_cents: int
    commission_cents: int
    scheduled_at: datetime | None = None
    # 预计送达时间(支付时生成;超过 15 分钟自动发安抚券,平台承担)
    eta_at: datetime | None = None
    address: str
    lat: float
    lng: float
    contact_name: str = ""
    contact_phone: str = ""
    # 商家/骑手视角的可拨号码:AXB X 号 > 过渡期真号 > 严格模式空(隐藏拨打)。
    # contact_phone 对商家/骑手一律打码,拨打一律走本字段
    privacy_phone: str = ""
    remark: str
    cancel_reason: str = ""
    refund_cents: int = 0
    refund_note: str = ""
    # 商家自配送:不走骑手,商家自己送(用户端明示"商家自送")
    self_delivery: bool = False
    # 无人接单告警:置位后用户端出现「加急小费」入口(no_rider_alerted_at 非空)
    no_rider_alerted: bool = False
    # 出餐管理(商家端 KDS):接单时刻用于备餐计时,ready_late=出餐超时定格
    accepted_at: datetime | None = None
    ready_late: bool = False
    # 地址保护:骑手/商家视角 address=粗地址、contact_name=中性称呼;
    # 用户可临时放行完整门牌(addr_revealed)
    addr_protect: bool = False
    addr_revealed: bool = False
    delivery_photo_url: str = ""  # 送达拍照留证(仅用户/平台可见)
    # 到店自取:取餐码印在小票上,商家核对用户报的码后完成订单
    pickup: bool = False
    pickup_code: str = ""
    parent_order_no: str = ""  # 非空 = 追加单,随原单一起配送
    created_at: datetime
    # 商家信息(取餐点),由路由层填充,骑手端地图/导航用
    merchant_name: str = ""
    merchant_address: str = ""
    merchant_lat: float | None = None
    merchant_lng: float | None = None
    # 骑手抢单池视角(仅 available-orders 填充):
    # 到商家的直线距离(骑手最近上报位置,无定位为空)与顺路标记
    distance_m: int | None = None
    same_shop: bool = False   # 与手头某单同商家(顺路取)
    same_way: bool = False    # 与手头某单收货点相近(顺路送)
    # 联系方式,仅订单详情接口填充(列表不查,避免 N+1)
    rider_name: str = ""
    rider_phone: str = ""
    merchant_phone: str = ""


class OrderEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    to_status: str
    actor_role: str
    created_at: datetime

    @property
    def status_label(self) -> str:  # 方便调试,客户端用自己的映射
        return STATUS_LABELS[self.status]


class TransitionIn(BaseModel):
    to_status: OrderStatus
    reason: str = Field(default="", max_length=200)  # 取消/拒单时填写
    # 骑手取餐核验(READY→PICKED_UP):输入小票单号尾号后 4 位防拿错单;
    # 连续输错可强制取餐(force=true,写事件留痕)。不传 = 老客户端,不核验
    verify_code: str = Field(default="", max_length=8)
    force: bool = False
    # 送达拍照留证(放门口场景):深夜(21-06)的地址保护单强制,其余可选
    photo_url: str = Field(default="", max_length=300)


class RefundItemIn(BaseModel):
    dish_id: int
    quantity: int = Field(gt=0, le=99)


# ---------- 商家对账 ----------
class DayStatOut(BaseModel):
    day: date
    order_count: int
    food_cents: int        # 菜品流水
    commission_cents: int  # 平台佣金
    net_cents: int         # 净收入


class FinanceOrderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    order_no: str
    food_cents: int
    commission_cents: int
    net_cents: int
    created_at: datetime


# ---------- 售后 ----------
class AfterSaleIn(BaseModel):
    reason: str = Field(min_length=4, max_length=500)
    # 举证照片必传(1-6 张):有图才能判责,恶意售后无所遁形。
    # 默认空列表而非 min_length=1:旧版 App 不带此字段,由路由层给出
    # 中文提示(pydantic 422 对用户不友好),规则本身不放松
    images: list[str] = Field(default=[], max_length=6)


class AfterSaleReplyIn(BaseModel):
    reply: str = Field(min_length=2, max_length=300)


class AfterSaleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    reason: str
    images: list[str] = []
    fault: str = ""          # ""=未判 / merchant=商家责任 / rider=骑手责任(平台先行赔付)
    status: AfterSaleStatus
    reply: str
    created_at: datetime
    processed_at: datetime | None


class MerchantAfterSaleOut(AfterSaleOut):
    """商家处理视角:带订单摘要,不用来回翻订单。"""

    order_no: str = ""
    order_summary: str = ""
    total_cents: int = 0


# ---------- 评价 ----------
# 评价一键标签白名单(只做正向/中性,负面反馈用文字说清楚更公平)
REVIEW_TAGS = ["味道好", "分量足", "包装好", "配送快", "干净卫生", "回头客"]


class ReviewIn(BaseModel):
    is_anonymous: bool = False  # 真匿名:商家侧完全不可反查
    merchant_rating: int = Field(ge=1, le=5)
    rider_rating: int | None = Field(default=None, ge=1, le=5)
    comment: str = Field(default="", max_length=500)
    image_urls: list[str] = Field(default=[], max_length=6)  # 图片评价
    tags: list[str] = Field(default=[], max_length=4)        # 一键标签

    @model_validator(mode="after")
    def tags_in_whitelist(self):
        bad = [t for t in self.tags if t not in REVIEW_TAGS]
        if bad:
            raise ValueError(f"不支持的标签:{'、'.join(bad)}")
        return self


class ReviewOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    merchant_rating: int
    rider_rating: int | None
    comment: str
    image_urls: list = []
    tags: list = []
    reply: str = ""  # 商家回复
    is_anonymous: bool = False
    # 追评(带"追评"标展示在首评下方)
    append_content: str = ""
    append_images: list = []
    append_at: datetime | None = None
    append_reply: str = ""
    hidden: bool = False  # 申诉改判后隐藏(商家自查可见状态,公开列表不出现)
    created_at: datetime
    customer_name: str = ""  # 已脱敏;匿名评价固定"匿名用户"


class ReplyIn(BaseModel):
    reply: str = Field(min_length=1, max_length=300)


# ---------- 收货地址 ----------
class AddressIn(BaseModel):
    contact_name: str = Field(min_length=1, max_length=50)
    contact_phone: str = Field(pattern=r"^1\d{10}$")
    address: str = Field(min_length=2, max_length=200)
    detail: str = Field(default="", max_length=100)
    lat: float
    lng: float
    is_default: bool = False
    # 保护模式:骑手只见粗地址;中性称呼替代真实姓名(空=「顾客」)
    protect: bool = False
    salutation: str = Field(default="", max_length=12)


class AddressPatch(BaseModel):
    protect: bool | None = None
    salutation: str | None = Field(default=None, max_length=12)
    contact_name: str | None = None
    contact_phone: str | None = Field(default=None, pattern=r"^1\d{10}$")
    address: str | None = None
    detail: str | None = None
    lat: float | None = None
    lng: float | None = None
    is_default: bool | None = None


class AddressOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    contact_name: str
    contact_phone: str
    address: str
    detail: str
    lat: float
    lng: float
    is_default: bool
    protect: bool = False
    salutation: str = ""


class PoiTipOut(BaseModel):
    name: str
    district: str
    lat: float
    lng: float


# ---------- 骑手实名认证 ----------
class RiderProfileIn(BaseModel):
    real_name: str = Field(min_length=2, max_length=50)
    id_card_no: str = Field(pattern=r"^\d{17}[\dXx]$")
    id_card_photo_url: str = Field(min_length=1)
    health_cert_photo_url: str = Field(min_length=1)


class RiderProfileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    real_name: str
    id_card_no: str
    id_card_photo_url: str
    health_cert_photo_url: str
    status: VerifyStatus
    reject_reason: str


class AdminRiderProfileOut(RiderProfileOut):
    rider_id: int
    rider_phone: str = ""
    created_at: datetime | None = None
    transfer_count_30d: int = 0  # 近30天转单次数(考核参考,免责线之外的部分重点看)
    online_7d_minutes: int = 0   # 近7天在线时长(分钟,运力规划参考)
    # 上岗考试:考过=最高分那次通过;字段全空 = 未参加
    exam_passed: bool = False
    exam_best_score: int | None = None
    exam_at: datetime | None = None  # 最近一次考试时间


# ---------- 骑手钱包 ----------
class WalletOut(BaseModel):
    balance_cents: int             # 账面余额(含保证金留存)
    total_earned_cents: int        # 累计收入
    pending_withdrawal_cents: int  # 提现中(冻结)
    withdrawn_cents: int           # 已提现
    # 保证金(仅商家;骑手恒为 0,可提=余额):从营收自动留存,不强制预缴
    deposit_required_cents: int = 0   # 应留
    deposit_held_cents: int = 0       # 已留存 = min(余额, 应留)
    withdrawable_cents: int = 0       # 可提现 = max(0, 余额 - 应留)


class EarningOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    order_no: str
    amount_cents: int
    created_at: datetime


class PayoutAccountIn(BaseModel):
    """收款账户登记。银行类必填开户行;微信/支付宝填收款账号(手机号/账号)。"""

    kind: Literal["bank_corporate", "bank_personal", "wechat", "alipay"]
    holder_name: str = Field(min_length=2, max_length=50)
    account_no: str = Field(min_length=4, max_length=64)
    bank_name: str = Field(default="", max_length=100)

    @model_validator(mode="after")
    def bank_requires_bank_name(self):
        if self.kind.startswith("bank") and not self.bank_name.strip():
            raise ValueError("银行账户必须填写开户行")
        return self


class PayoutAccountOut(BaseModel):
    """普通角色视角:永远只回尾 4 位,完整账号只存在于密文与管理端打款界面。"""

    configured: bool
    kind: str = ""
    holder_name: str = ""
    bank_name: str = ""
    account_tail: str = ""
    updated_at: datetime | None = None
    recently_changed: bool = False  # 24h 内改过,提现会被人工加核


class WithdrawalIn(BaseModel):
    amount_cents: int = Field(gt=0)


class WithdrawalOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    amount_cents: int
    status: WithdrawalStatus
    reject_reason: str
    paid_note: str = ""  # 打款凭证/批次号,骑手端也可见(透明)
    created_at: datetime
    processed_at: datetime | None


class AdminWithdrawalOut(WithdrawalOut):
    role: str = "rider"   # rider / merchant,后台展示打款对象类型
    name: str = ""
    phone: str = ""
    # 收款账户快照(申请时冻结);account_no 解密后的完整账号,仅管理端可见
    account_kind: str = ""
    account_holder: str = ""
    account_bank: str = ""
    account_no: str = ""
    account_recently_changed: bool = False


# ---------- 骑手 ----------
class LocationIn(BaseModel):
    lat: float
    lng: float


class OnlineIn(BaseModel):
    is_online: bool


class RiderLocationOut(BaseModel):
    rider_id: int
    lat: float | None
    lng: float | None
    updated_at: float | None


# ---------- 客服工单 ----------
class TicketIn(BaseModel):
    content: str = Field(min_length=4, max_length=500)
    contact: str = Field(default="", max_length=50)


class TicketOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    role: str
    contact: str
    content: str
    status: TicketStatus
    reply: str
    created_at: datetime
    replied_at: datetime | None


class AdminTicketOut(TicketOut):
    user_phone: str = ""


class TicketReplyIn(BaseModel):
    reply: str = Field(min_length=1, max_length=500)
