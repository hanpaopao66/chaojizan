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
    # 同一手机号可有多角色账号;不传则逐账号验密取首个命中(兼容旧调用方)
    role: str = Field(default="", pattern="^(customer|merchant|rider|admin)?$")


class SmsCodeIn(BaseModel):
    phone: str = Field(pattern=r"^1\d{10}$")
    # 滑块验证(同号当日第 3 条起要求):/auth/slider 领票,滑到位后随发码提交
    ticket: str = Field(default="", max_length=64)
    slide: int | None = Field(default=None, ge=0, le=100)


class SmsLoginIn(BaseModel):
    phone: str = Field(pattern=r"^1\d{10}$")
    code: str = Field(pattern=r"^\d{6}$")
    device_id: str = Field(default="", max_length=64)
    # 新手机号自动注册时的角色(三端各传各的;已有账号忽略此参数保原角色)。
    # admin 仅允许已存在的管理员账号登录,绝不自动注册(见 sms_login)
    role: str = Field(default="customer",
                      pattern="^(customer|merchant|rider|admin)$")


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
class HotelApplyIn(BaseModel):
    """酒店入驻专属资料(biz_type=hotel 时必传)。"""

    tier: str = Field(default="economy", pattern="^(economy|comfort|premium|luxury)$")
    front_desk_phone: str = Field(default="", max_length=20)
    checkin_from: str = Field(default="14:00", pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    checkout_until: str = Field(default="12:00", pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    facilities: list[str] = []
    special_license_no: str = Field(default="", max_length=50)      # 特种行业许可证号
    special_license_image_url: str = Field(default="", max_length=300)
    hygiene_image_url: str = Field(default="", max_length=300)      # 卫生许可证(选填)


class MerchantIn(BaseModel):
    name: str
    description: str = ""
    address: str = ""
    lat: float
    lng: float
    # biz_type=food 时为食品经营许可证;hotel 时为营业执照
    license_no: str = ""
    license_image_url: str = ""  # 证照照片(新申请必传,老库存量允许为空)
    # 有效期与主体名称。**选填而不是必填**:存量商家没有这两项,
    # 改成必填会把所有老商家的"驳回后回填重提"表单卡死。
    # 填了就纳入到期提醒,不填只是不提醒 —— 不猜、不拦。
    license_expires_at: date | None = None
    business_license_no: str = Field(default="", max_length=50)
    license_subject: str = Field(default="", max_length=100)
    # 堂食标识(#187):入驻时就问一句,免得开业后列表上挂着「未填报」。
    # 默认 unknown 而不是 yes —— 不填只是不填,不该被平台猜成有堂食
    dine_in_status: str = Field(default="unknown",
                                pattern="^(unknown|yes|no)$")
    # 外卖品类(白名单校验在路由,清单见 categories.py;酒店忽略此字段)
    category: str = "fast_food"
    # 业态:food 餐饮外卖(默认) / hotel 酒店住宿
    biz_type: str = Field(default="food", pattern="^(food|hotel)$")
    hotel: HotelApplyIn | None = None  # 酒店专属资料,biz_type=hotel 必传


class MerchantOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: str
    address: str
    lat: float
    lng: float
    city: str = ""  # 所在城市(入驻时逆地理解析;开城清单外不可营业)
    biz_type: str = "food"  # 业态:food 餐饮 / hotel 酒店(三端按此分叉界面)
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
    # 当前查看者是否是这家店登记的经营者本人(仅 GET /merchants/me 填充)。
    # **和 not viewer_is_staff 不是一回事**:连锁的区域经理不是店员
    # (能改价、能改设置),但也不是经营者本人 —— 资金动作服务端一律 403。
    # 客户端据此隐藏对账/提现入口,别把人领到一堵墙前面再报错。
    viewer_is_owner: bool = True

    # 明厨亮灶(#155)。**这两个字段是法定要求,不是可选的展示项**:
    # 总局令第 123 号第十三条要求平台"根据商家是否实施,在商家列表页展示
    # 「无明厨亮灶」「有明厨亮灶」标识" —— 注意要标的是**两种**,
    # 所以每一个商家都带这个字段,不是给装了的加徽章。
    #
    # 口径只认 active:pending(待核验)和 degraded(掉线)一律算「无」。
    # 看不到就是没有 —— 标识和实际能不能看必须是同一件事
    kitchen_cam: bool = False
    kitchen_cam_label: str = "无明厨亮灶"

    # 堂食标识(#187,总局令第 123 号第十二条)。同样是**法定公示项**,
    # 列表页和商家主页都要展示,所以每家店都带,不是给有堂食的加徽章。
    # unknown 未填报 / yes 有堂食 / no 无堂食 —— 未填报如实标"未填报",
    # 不默认成「有堂食」:替商家猜一个,就是用平台信用给未经核实的信息背书
    dine_in_status: str = "unknown"
    dine_in_label: str = "未填报"

    # 忙碌模式(高峰压单):生效期 ETA/出餐超时判定放宽 busy_extra_minutes,
    # 用户端亮「出餐较慢」标。busy_active 读 ORM 的 property,到点自动变 False
    busy_active: bool = False
    busy_until: datetime | None = None
    busy_extra_minutes: int = 10

    # 食安封签(商家自述,非平台认证):用户端展示"商家声明使用封签"
    food_seal: bool = False
    # 食安停业闸门:置位时商家自己开不回营业(整改复核由平台解除)
    food_safety_hold: bool = False


class MerchantMeOut(MerchantOut):
    """店主自查视角(仅 GET /merchants/me):多了本店证照,驳回后回填表单用。
    店员拿到的是空串 —— 资质材料不是接单要用的东西。"""

    license_no: str = ""
    license_image_url: str = ""
    license_expires_at: date | None = None
    business_license_no: str = ""
    license_subject: str = ""
    # 证照状态:unknown 未登记 / ok / soon / urgent / last / expired / overdue
    # (判定见 services/licenses.stage;客户端据此决定横幅的轻重)
    license_stage: str = "unknown"
    license_days_left: int | None = None
    special_license_no: str = ""
    special_license_image_url: str = ""
    hygiene_image_url: str = ""
    auto_accept: bool = False  # 自动接单开关(店铺 tab 展示/切换)


class AdminMerchantOut(MerchantOut):
    """审核后台视角:多了证照和店主联系方式。"""

    license_no: str = ""
    license_image_url: str = ""
    # 酒店业态的第二证照(特种行业许可证)与卫生许可证,列表页聚合填充
    special_license_no: str = ""
    special_license_image_url: str = ""
    hygiene_image_url: str = ""
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
    # 文字地址可改(补门牌、改错别字),**但 lat/lng 不在这里** ——
    # 坐标决定谁能搜到这家店、配送费怎么算,自助改等于绕过审核把自己
    # 挪到人流密集区。要迁址走客服重审(客户端 onboarding.dart 也是这个口径)。
    #
    # ⚠️ 别顺手往下面加 lat/lng —— 那一行加上去,距离推荐就可以被商家自己刷。
    address: str | None = None
    license_no: str | None = None
    license_image_url: str | None = None
    # 换新证时一起改:到期日变了,services/licenses.notify_key 里的水位
    # 自然失效,新证到期时会重新走一遍完整的四档提醒
    license_expires_at: date | None = None
    business_license_no: str | None = Field(default=None, max_length=50)
    license_subject: str | None = Field(default=None, max_length=100)
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
    auto_accept: bool | None = None    # 自动接单(支付成功即进入制作)
    food_seal: bool | None = None      # 食安封签(商家自述)
    # 堂食标识(#187):unknown 未填报 / yes 有堂食 / no 无堂食。
    # **不是资质项**,不走驳回重提那道闸 —— 它是商家对现状的陈述,
    # 店里加了几张桌子就该能当天改过来;真实性靠公示 + 用户举报兜
    dine_in_status: str | None = Field(default=None,
                                       pattern="^(unknown|yes|no)$")
    # 酒店第二证照:仅**被驳回后重新提交**时可带(平时资质变更走客服人工核验)
    special_license_no: str | None = Field(default=None, max_length=50)
    special_license_image_url: str | None = Field(default=None, max_length=300)
    hygiene_image_url: str | None = Field(default=None, max_length=300)


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


# 菜品标签白名单。只收**商家自述的客观项**:新品/招牌是事实,辣度是口味,
# 忌口提示关乎安全。**故意不含「平台推荐」「热销第一」这类** ——
# 那种标签一旦存在,迟早会变成可以买的位置,与"没有竞价排名"直接冲突
DISH_BADGES = [
    "新品", "招牌", "微辣", "中辣", "特辣", "不辣",
    "含花生", "含香菜", "素食", "儿童友好",
]

# 供应时段 "06:00-10:30";空串=全天供应(与 open_time 同款正则口径)
SERVE_WINDOW_RE = r"^([01]\d|2[0-3]):[0-5]\d-([01]\d|2[0-3]):[0-5]\d$|^$"


def _validate_serve_window(window: str) -> None:
    """起止相同的时段(如 10:00-10:00)在 in_hhmm_range 下恒为 False ——
    这道菜会永远点不了,而商家以为自己设了"整点供应"。"""
    if window and window.split("-")[0] == window.split("-")[1]:
        raise ValueError("供应时段的开始和结束不能相同;全天供应请留空")


class ComboItem(BaseModel):
    """套餐子项:哪道菜、几份。套餐价是套餐自身的 price_cents,
    子项只用来扣库存和给后厨看,不参与计价。"""

    dish_id: int
    quantity: int = Field(default=1, ge=1, le=20)
# 互斥组:同一道菜挂"不辣"又挂"特辣",用户不知道该信哪个
_BADGE_EXCLUSIVE = [{"微辣", "中辣", "特辣", "不辣"}]


def _validate_badges(badges: list[str]) -> None:
    bad = [b for b in badges if b not in DISH_BADGES]
    if bad:
        raise ValueError(f"不支持的标签:{'、'.join(bad)}")
    if len(set(badges)) != len(badges):
        raise ValueError("标签不能重复")
    for group in _BADGE_EXCLUSIVE:
        hit = group & set(badges)
        if len(hit) > 1:
            raise ValueError(f"辣度只能选一个,现在选了:{'、'.join(sorted(hit))}")


class DishIn(BaseModel):
    name: str
    category: str = ""
    price_cents: int = Field(gt=0)
    # 成本(分/份),0 = 没录过。只商家自己可见,不进任何对外接口
    cost_cents: int = Field(default=0, ge=0, le=1_000_000)
    # 额外打包费(分/份);None = 不单独设,只走店铺的每单打包费
    packing_fee_cents: int | None = Field(default=None, ge=0, le=2000)
    stock: int = Field(default=100, ge=0)
    daily_stock: int | None = Field(default=None, ge=0, le=100_000)
    is_alcohol: bool = False  # 酒类:购买需实名且成年,商家上架自助勾选
    image_url: str = ""
    description: str = Field(default="", max_length=200)
    badges: list[str] = Field(default=[], max_length=4)
    options: list[OptionGroup] = Field(default=[], max_length=5)
    combo_items: list[ComboItem] = Field(default=[], max_length=8)
    serve_window: str = Field(default="", pattern=SERVE_WINDOW_RE)

    @model_validator(mode="after")
    def badges_in_whitelist(self):
        _validate_badges(self.badges)
        _validate_serve_window(self.serve_window)
        return self


class DishPatch(BaseModel):
    name: str | None = None
    category: str | None = None
    price_cents: int | None = Field(default=None, gt=0)
    cost_cents: int | None = Field(default=None, ge=0, le=1_000_000)
    packing_fee_cents: int | None = Field(default=None, ge=0, le=2000)
    stock: int | None = Field(default=None, ge=0)
    # 每日回满目标(传 null 关闭)。与其他字段不同,None 是有效值,
    # 用 model_fields_set 判断是否显式传了本字段
    daily_stock: int | None = Field(default=None, ge=0, le=100_000)
    is_on_sale: bool | None = None
    is_alcohol: bool | None = None
    image_url: str | None = None
    sort: int | None = Field(default=None, ge=-9999, le=9999)  # 菜单顺序,小的在前
    description: str | None = Field(default=None, max_length=200)
    badges: list[str] | None = Field(default=None, max_length=4)
    options: list[OptionGroup] | None = Field(default=None, max_length=5)
    combo_items: list[ComboItem] | None = Field(default=None, max_length=8)
    serve_window: str | None = Field(default=None, pattern=SERVE_WINDOW_RE)

    @model_validator(mode="after")
    def badges_in_whitelist(self):
        _validate_badges(self.badges or [])
        _validate_serve_window(self.serve_window or "")
        return self
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
    sort: int = 0  # 菜单顺序(小的在前),商家排的顺序用户端照着看
    description: str = ""  # 菜品描述(用户点之前想知道这菜里有什么)
    badges: list = []      # 标签角标(白名单 DISH_BADGES)
    combo_items: list = []         # 套餐子项(非空 = 这是个套餐)
    combo_dishes: list = []        # 子项明细 [{name, quantity}],菜单接口填充
    combo_original_cents: int = 0  # 子项单点合计,前端划线显示"省 X 元"
    serve_window: str = ""         # 供应时段(空=全天)
    servable_now: bool = True      # 此刻是否在供应时段内(下方自动算)
    options: list = []
    # 菜品额外打包费(分/份);None = 这道菜没单独设,只走店铺的每单打包费。
    # **对用户端公开**:它是实付价的一部分,用户有权在点之前就看到
    packing_fee_cents: int | None = None
    flash_price_cents: int | None = None
    flash_until: datetime | None = None
    monthly_sales: int = 0  # 近 30 天售出份数,菜单接口填充

    @model_validator(mode="after")
    def _compute_servable(self):
        """**在 schema 层算,不靠各个路由记得填**。
        菜单和商家列表之外还有 frequent-dishes / 建菜 / 改菜 / 估清 等
        六七个出口都返回 DishOut,漏一个,非供应时段的菜就在那里显示可点
        (「我常买」里点早餐,一路点到结算才吃 409)。"""
        if self.serve_window:
            from zoneinfo import ZoneInfo

            from .services.flags import in_hhmm_range
            now = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%H:%M")
            self.servable_now = in_hhmm_range(self.serve_window, now)
        return self


# ---------- 平台:公告 / 埋点 ----------
class MerchantDishOut(DishOut):
    """商家自查视角的菜品(仅 /merchants/me/dishes 与建菜/改菜返回)。

    **cost_cents 只能出现在这里**:DishOut 同时是用户端菜单、我常买、
    店铺详情的出口,成本挂上去就等于把商家的进价公开给同行和供应商。
    分一个子类而不是"记得在公开出口里 pop 掉" —— 后者漏一个就泄露,
    而出口有六七个。
    """

    cost_cents: int = 0



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


class AppealVerdictIn(BaseModel):
    """骑手申诉核定。

    accept 单独一个字段而不是复用 FoodSafetyActionIn —— 后者没有这一项,
    复用的话"驳回"这条路径根本走不到(每条都会判成立)。
    """

    accept: bool
    note: str = Field(min_length=2, max_length=200)


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
    """商家自建券:满 threshold 减 off,限量、每人限领、有效期。成本商家承担。

    trigger 决定什么时候发到用户手里:
    - shop      顾客在店铺页主动领(默认,老行为)
    - referral  有人通过邀请码带来的新客在本店完成首单,双方各得一张(#115)
    - birthday  本店老客生日当天
    - winback   本店 30 天没来的老客

    后三种是平台原先掏钱做的营销,现在归位给商家——平台只提供触达机制。
    """

    name: str = Field(min_length=2, max_length=50)
    trigger: str = Field(
        default="shop",
        pattern="^(shop|referral|birthday|winback|favorite)$")
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
    # 发放方式:shop 顾客主动领 / referral 新客推荐 / birthday 生日 / winback 复购。
    # 商家列表里要能看出这一批是干什么的,否则四种批次混在一起分不清
    trigger: str = "shop"
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


class ErrandCreateIn(BaseModel):
    """帮送下单入参。取件点与送达点都是用户填的。"""
    # 取件点(东西现在在哪)
    pickup_address: str = Field(min_length=2, max_length=200)
    pickup_lat: float
    pickup_lng: float
    pickup_contact_name: str = Field(default="", max_length=50)
    pickup_contact_phone: str = Field(default="", max_length=20)
    # 送达点
    address: str = Field(min_length=2, max_length=200)
    lat: float
    lng: float
    contact_name: str = Field(default="", max_length=50)
    contact_phone: str = Field(default="", max_length=20)
    floor: int | None = None
    has_elevator: bool | None = None
    to_door: bool = True
    # 寄什么。**必填**:骑手取件时要核对,而且禁运筛查靠它
    errand_note: str = Field(min_length=2, max_length=300)
    remark: str = Field(default="", max_length=200)
    #: 用户勾选「不含违禁品」。不勾不让下单 ——
    #: 这不是免责话术,是让他在按下单之前真的想一遍
    no_forbidden: bool = False


class ErrandBuyCreateIn(ErrandCreateIn):
    """帮买:去哪买(pickup_*)、买什么(errand_note)、预计花多少。

    **只做包装商品与商超日用,不做即食餐饮** —— 代购即食食品需要食品经营
    许可,让骑手去一个没证的摊子买一份小笼包就是给无证经营导流,
    而我们外卖那边卡证卡得很严,两套标准会自己打架。
    """
    #: 用户预估这些东西要花多少钱。**先付给平台**,骑手不垫自己的钱
    goods_budget_cents: int = Field(ge=100, le=200000)


class ErrandBuyQuoteOut(BaseModel):
    distance_m: int
    fee_cents: int
    parts: dict
    labels: dict
    service_fee_cents: int
    #: 预付的商品款(原样回显,让用户在付款前看清自己付的是哪两笔)
    goods_budget_cents: int
    total_cents: int
    #: 骑手可自行超支的上限;超出要他先发起确认、用户同意才买
    raise_limit_cents: int
    note: str


class ErrandQuoteOut(BaseModel):
    distance_m: int
    fee_cents: int
    parts: dict
    labels: dict
    #: 平台服务费**单独给**,不藏在总价里
    service_fee_cents: int
    total_cents: int
    note: str


class OrderCreateIn(BaseModel):
    merchant_id: int
    items: list[OrderItemIn] = Field(min_length=1)
    # 加菜:传原单号则创建追加单(免配送费/免起送价,地址与骑手随原单)
    append_to: str = ""
    # 到店自取:免配送费、不走骑手,地址三件套可不传(服务端落商家坐标)
    pickup: bool = False
    address: str = ""
    # 楼层与电梯:客户端从所选地址带过来。填了 ETA 会诚实一点 ——
    # 爬 6 楼和 1 楼临街是两种活
    floor: int | None = Field(default=None, ge=-5, le=200)
    has_elevator: bool | None = None
    # 送上门 / 送到楼下。**顾客自己选** —— 选楼下就不收上门难度费,
    # 骑手也没有义务上楼。默认 true 与此前行为一致
    to_door: bool = True
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
    # 骑手到店时刻:骑手端据此决定还要不要显示「我到店了」按钮
    arrived_shop_at: datetime | None = None
    # 骑手到达收货点的时刻(同上,决定「我到了」按钮显不显示)
    arrived_drop_at: datetime | None = None
    # 跑腿:订单类型与取件点。外卖单这几个是默认值/空串。
    # 骑手端据此把「取餐」改成「取件」、把商家名改成取件点
    order_kind: str = "food"
    errand_note: str = ""
    pickup_address: str = ""
    pickup_contact_name: str = ""
    pickup_photo_url: str = ""
    # 帮买:预付商品款 / 小票实付 / 小票照片 / 加价确认状态。
    # **小票对用户可见** —— 代买最容易起的纠纷就是"你是不是多报了",
    # 把小票摊开这个纠纷根本不会发生
    goods_budget_cents: int = 0
    goods_actual_cents: int | None = None
    goods_receipt_url: str = ""
    goods_raise_status: str = ""
    goods_raise_cents: int | None = None
    # 这一单实际的送达段停留时长(分钟)。null = 骑手没点过「我到了」,
    # **不猜** —— 凑出来的数会污染分位数,而分位数将来要给别人补时
    drop_minutes: float | None = None
    # 这个收货点的历史送达段耗时(分钟)与样本数。
    # **样本不足时 p75 为 null 而不是给个凑合的数** ——
    # 调用方必须能区分"这里确实快"和"我们还不知道"
    drop_p75_minutes: float | None = None
    drop_sample: int = 0
    # 配送费构成 {base, night, weather, door}(分)+ 中文名。
    # **四端都给**:顾客要知道这 8 块钱花在哪、骑手要在接单前就知道
    # 这单为什么值 8 块、商家被问起配送费贵时能解释
    fee_parts: dict = {}
    fee_part_labels: dict = {}
    to_door: bool = True
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
    distance_m: int | None = None          # 骑手 → 取餐点
    trip_m: int | None = None              # 取餐点 → 送达点(整单划不划算要看它)
    # 距离来源:route=腾讯骑行路径规划,straight=回退直线×1.2。
    # **必须透传给骑手** —— 距离准不准,他有权知道,而不是时准时不准却不知为何
    distance_source: str = "straight"
    same_shop: bool = False   # 与手头某单同商家(同店多取一单,取餐几乎零成本)
    same_way: bool = False    # 顺路(向后兼容:strong/weak 都为 true)
    # 顺路等级:strong / weak / none。按**绕路增量**判,不按两点距离
    same_way_level: str = "none"
    detour_m: int | None = None            # 绕路增量:接这单要比只送手头单多跑多远
    # 整单经济性(#142):骑手判断「值不值得接」要的是这三个,不是"到店多远"
    est_minutes: float | None = None       # 预计总耗时(到店 + 等餐 + 送达)
    est_wait_minutes: float | None = None  # 其中在店等餐(按该店实测出餐分位数)
    # 配送费构成 + 中文名。**接单前就给** —— 骑手要知道这单 8 块里
    # 有 3 块是因为要爬 6 楼,才判断得了值不值。
    # (美团官方只说"接单前能看到价格",看不到明细;这一步我们做了)
    fee_parts: dict = {}
    fee_part_labels: dict = {}
    # 等餐预期来源:measured=该店实测 P80,declared=商家自报(样本不足)。
    # **必须透传** —— 「等 22 分钟」和「大概 15 分钟(样本还少)」,
    # 骑手的决策是不一样的
    wait_source: str = "declared"
    cents_per_minute: float | None = None  # 每分钟收入估算(横向比较用)
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

    #: 分页游标要用:排序是 (created_at, id) 两列,
    #: 只拿 created_at 翻页会把同一秒的行整组跳过(实测漏过一条冲账)
    id: int
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
# 评价一键标签白名单。**按责任方分组**:配送是平台的事,配送问题的标签
# 只随骑手评分落库,从结构上就进不了商家维度 —— 锅不该商家背。
REVIEW_TAGS = ["味道好", "分量足", "包装好", "配送快", "干净卫生", "回头客"]
# 商家侧负向(归因到菜品/包装/出餐,商家能改的事)
MERCHANT_NEG_TAGS = ["太咸了", "分量不足", "包装洒漏", "出餐慢", "和图不符"]
# 骑手/配送侧(正负都有;只挂 rider_rating)
RIDER_REVIEW_TAGS = ["送得快", "服务周到", "送得慢", "态度不好", "餐洒了"]

_MERCHANT_TAG_WHITELIST = set(REVIEW_TAGS) | set(MERCHANT_NEG_TAGS)


class ReviewIn(BaseModel):
    is_anonymous: bool = False  # 真匿名:商家侧完全不可反查
    merchant_rating: int = Field(ge=1, le=5)
    rider_rating: int | None = Field(default=None, ge=1, le=5)
    comment: str = Field(default="", max_length=500)
    image_urls: list[str] = Field(default=[], max_length=6)  # 图片评价
    tags: list[str] = Field(default=[], max_length=4)        # 商家维度标签
    rider_tags: list[str] = Field(default=[], max_length=3)  # 配送维度标签

    @model_validator(mode="after")
    def tags_in_whitelist(self):
        bad = [t for t in self.tags if t not in _MERCHANT_TAG_WHITELIST]
        if bad:
            raise ValueError(f"不支持的标签:{'、'.join(bad)}")
        bad_rider = [t for t in self.rider_tags if t not in RIDER_REVIEW_TAGS]
        if bad_rider:
            raise ValueError(f"不支持的配送标签:{'、'.join(bad_rider)}")
        return self


class ReviewOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    merchant_rating: int
    rider_rating: int | None
    comment: str
    image_urls: list = []
    tags: list = []
    rider_tags: list = []  # 配送维度标签(不进商家维度)
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
    #: 楼层与电梯(选填)。填了 ETA 会诚实一点 —— 爬 6 楼和 1 楼临街
    #: 是两种活。**不填就是不填**,我们不猜(猜错就是个假承诺)
    floor: int | None = Field(default=None, ge=-5, le=200)
    has_elevator: bool | None = None
    # 保护模式:骑手只见粗地址;中性称呼替代真实姓名(空=「顾客」)
    protect: bool = False
    salutation: str = Field(default="", max_length=12)
    #: 标签:家 / 公司 / 学校(或自定义)。地址簿里三个"XX路XX号"排在一起时,
    #: 用户得逐字读才知道哪个是家
    tag: str = Field(default="", max_length=8)


class AddressPatch(BaseModel):
    # floor 的 null 是**有语义的**(清掉重填),所以路由用 exclude_unset
    # 区分"没传"和"显式传 null" —— 与菜品的额外打包费同一个处理
    floor: int | None = Field(default=None, ge=-5, le=200)
    has_elevator: bool | None = None
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
    floor: int | None = None
    has_elevator: bool | None = None
    protect: bool = False
    salutation: str = ""
    tag: str = ""


class PoiTipOut(BaseModel):
    name: str
    district: str
    lat: float
    lng: float


# ---------- 骑手实名认证 ----------
class RiderProfileIn(BaseModel):
    """骑手实名:只要姓名 + 身份证号。

    **不收身份证照片** —— 二要素核验(查国家人口基础信息库)不需要它,
    而它是敏感个人影像,不收就没有泄露面。

    健康证选填:国家层面不要求送餐员持健康证(不属于"直接接触入口食品的人员"),
    四川已明确取消;只有地方另有要求的城市才会卡。
    """

    real_name: str = Field(min_length=2, max_length=50)
    id_card_no: str = Field(pattern=r"^\d{17}[\dXx]$")
    health_cert_photo_url: str = Field(default="", max_length=300)


class RiderProfileOut(BaseModel):
    """**不回证号,姓名打码** —— 和用户侧 UserIdentity 一个口径。"""

    real_name: str          # 打码后的
    health_cert_photo_url: str = ""
    status: VerifyStatus
    reject_reason: str = ""
    #: 是否经过二要素核验(区别于历史的人工审核路径)
    id_verified: bool = False
    #: **本市**是否要求健康证。国家层面不要求(送餐员不属于"直接接触
    #: 入口食品的人员",四川已取消),只有查证过本地有规章的城市才为 true
    health_cert_required: bool = False
    #: 骑手所在城市(首次上线按定位解析);空 = 还没上线过
    city: str = ""


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


# ---------- 住宿(酒店垂类,方案见 docs/HOTEL_PLAN.md) ----------

_HHMM_RE = r"^([01]\d|2[0-3]):[0-5]\d$"
_POLICY_RE = "^(limited_free|first_night|strict)$"


class RoomTypeIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    bed_type: str = Field(default="", max_length=30)
    area_m2: int = Field(default=0, ge=0, le=500)
    max_guests: int = Field(default=2, ge=1, le=10)
    image_urls: list[str] = Field(default=[], max_length=9)
    facilities: list[str] = Field(default=[], max_length=20)
    cancel_policy: str = Field(default="limited_free", pattern=_POLICY_RE)
    free_cancel_until: str = Field(default="18:00", pattern=_HHMM_RE)
    sort: int = Field(default=0, ge=0, le=999)


class RoomTypePatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=60)
    bed_type: str | None = Field(default=None, max_length=30)
    area_m2: int | None = Field(default=None, ge=0, le=500)
    max_guests: int | None = Field(default=None, ge=1, le=10)
    image_urls: list[str] | None = Field(default=None, max_length=9)
    facilities: list[str] | None = Field(default=None, max_length=20)
    # 政策改动只影响新订单(已有订单按下单时快照执行)
    cancel_policy: str | None = Field(default=None, pattern=_POLICY_RE)
    free_cancel_until: str | None = Field(default=None, pattern=_HHMM_RE)
    is_on_sale: bool | None = None
    sort: int | None = Field(default=None, ge=0, le=999)


class RoomTypeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    merchant_id: int
    name: str
    bed_type: str = ""
    area_m2: int = 0
    max_guests: int = 2
    image_urls: list = []
    facilities: list = []
    cancel_policy: str = "limited_free"
    free_cancel_until: str = "18:00"
    is_on_sale: bool = True
    sort: int = 0


class RoomCalendarSetIn(BaseModel):
    """日历批量设置:日期区间 × 多房型,统一改价/改总量/开关房(至少一项)。"""

    room_type_ids: list[int] = Field(min_length=1, max_length=50)
    from_date: date
    to_date: date
    price_cents: int | None = Field(default=None, gt=0, le=10_000_000)
    total_qty: int | None = Field(default=None, ge=0, le=999)
    closed: bool | None = None

    @model_validator(mode="after")
    def sane(self):
        if self.to_date < self.from_date:
            raise ValueError("结束日期不能早于开始日期")
        if (self.to_date - self.from_date).days > 120:
            raise ValueError("一次最多设置 120 天")
        if self.price_cents is None and self.total_qty is None \
                and self.closed is None:
            raise ValueError("请至少设置价格、间数或开关房中的一项")
        return self


class RoomDayOut(BaseModel):
    date: date
    price_cents: int
    total_qty: int
    sold_qty: int
    closed: bool


class RoomCalendarRowOut(BaseModel):
    room_type_id: int
    room_type_name: str
    days: list[RoomDayOut] = []


class HotelCardOut(BaseModel):
    """酒店列表卡片:带日期区间的起价与满房标记。"""

    id: int
    name: str
    tier: str = "economy"
    address: str = ""
    lat: float = 0
    lng: float = 0
    logo_url: str = ""
    photo_urls: list = []
    rating_avg: float | None = None
    rating_count: int = 0
    distance_m: int | None = None
    # 区间内可订房型的最低"每晚均价"(分);None = 区间内满房/未开放
    min_night_price_cents: int | None = None
    full: bool = False  # 区间内所有房型都订不了


class RoomQuoteOut(BaseModel):
    """房型报价(按查询的入住区间聚合)。"""

    room_type: RoomTypeOut
    total_cents: int | None = None      # 区间总价(一间);None = 不可订
    nightly: list[RoomDayOut] = []      # 每晚明细(价格/余量)
    bookable: bool = False
    # 剩余间数:>3 不透具体数(防试探),≤3 返回真实数供"仅剩 X 间"
    left_qty: int | None = None
    cancel_policy_text: str = ""


class HotelDetailOut(BaseModel):
    id: int
    name: str
    description: str = ""
    tier: str = "economy"
    address: str = ""
    lat: float = 0
    lng: float = 0
    front_desk_phone: str = ""
    checkin_from: str = "14:00"
    checkout_until: str = "12:00"
    facilities: list = []
    logo_url: str = ""
    photo_urls: list = []
    rating_avg: float | None = None
    rating_count: int = 0
    checkin_date: date | None = None
    checkout_date: date | None = None
    rooms: list[RoomQuoteOut] = []


class StayOrderIn(BaseModel):
    """住宿下单:房型 + 入住区间 + 间数 + 入住人。"""

    room_type_id: int = Field(gt=0)
    checkin_date: date
    checkout_date: date
    rooms_qty: int = Field(default=1, ge=1, le=5)
    guest_name: str = Field(min_length=1, max_length=50)
    guest_phone: str = Field(pattern=r"^1\d{10}$")
    arrival_note: str = Field(default="", max_length=100)


class StayOrderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    order_no: str
    merchant_id: int
    room_type_id: int
    checkin_date: date
    checkout_date: date
    nights: int
    rooms_qty: int
    guest_name: str
    guest_phone: str
    arrival_note: str = ""
    room_type_name: str = ""
    nightly_prices: list = []
    total_cents: int
    fee_cents: int = 0
    net_cents: int = 0
    cancel_policy: str
    free_cancel_until: str = "18:00"
    status: str
    status_label: str = ""       # 中文状态(后端统一,三端一致)
    cancel_policy_text: str = ""
    reject_reason: str = ""
    refund_cents: int = 0
    refund_note: str = ""
    created_at: datetime | None = None
    paid_at: datetime | None = None
    confirmed_at: datetime | None = None
    checked_in_at: datetime | None = None
    completed_at: datetime | None = None
    cancelled_at: datetime | None = None
    # 列表/详情回填
    hotel_name: str = ""
    hotel_address: str = ""
    hotel_phone: str = ""


class StayCancelPreviewOut(BaseModel):
    """取消试算:确认弹层展示,无副作用。"""

    refund_cents: int
    penalty_cents: int  # 扣款(=总额-退款,归商家,平台不抽佣)
    note: str


class StayReviewIn(BaseModel):
    rating: int = Field(ge=1, le=5)
    comment: str = Field(default="", max_length=500)
    image_urls: list[str] = Field(default=[], max_length=6)
    tags: list[str] = Field(default=[], max_length=6)
    is_anonymous: bool = False


class StayReviewOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    rating: int
    comment: str = ""
    image_urls: list = []
    tags: list = []
    reply: str = ""
    is_anonymous: bool = False
    append_content: str = ""
    append_reply: str = ""
    created_at: datetime | None = None
    reviewer_name: str = ""  # 匿名时为「匿名住客」,列表页聚合填充
    order_no: str = ""       # 仅本人/商家视角回填


class StayAfterSaleIn(BaseModel):
    kind: str = Field(pattern="^(no_room|nego_refund)$")
    note: str = Field(default="", max_length=300)


class StayAfterSaleRespondIn(BaseModel):
    accept: bool
    note: str = Field(default="", max_length=300)
    # 协商退:同意时商家填退款金额(分,0~全额);到店无房忽略此字段
    refund_cents: int | None = Field(default=None, ge=0)


class StayAfterSaleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    stay_order_id: int
    kind: str
    status: str
    note: str = ""
    merchant_note: str = ""
    refund_cents: int = 0
    penalty_cents: int = 0
    created_at: datetime | None = None
    resolved_at: datetime | None = None
    order_no: str = ""       # 列表回填
    guest_name: str = ""
    total_cents: int = 0


# ---------- 微信特约商户进件资料(#203/#206) ----------
#
# 这一节除了 Pydantic 模型,还放了**必填清单与完整度判定**。
# 放在 schemas 而不是某个 router 里,是因为它是「契约」的一部分:
# 商家端(Flutter)、merchant-web、管理端队列三处都要问"还差什么",
# 三处各硬编码一份必填清单,加一个字段就得改四个地方 ——
# 而漏改的那一处会让商家看着 100% 却永远提交不成功。
#
# 结算账户虽然也是"银行账号 + 户名",但**不复用 PayoutAccount**:
# 那是「平台打款给谁」(按 user 一人一户),这里是「微信把钱结给谁」
# (按门店,连锁每店可以不同)。同一个账号存两张表迟早分叉。

#: 进件状态机(平台侧流转;接了微信之后由回调驱动)
APPLYMENT_STATUS_LABELS: dict[str, str] = {
    "not_submitted": "未提交",
    "submitted": "已提交,待平台报送",
    # 下面两个是微信侧**要商家本人动手**的环节。不把它们显式画出来,
    # 商家会以为提交完就没事了,然后一直开不了通
    "need_sign": "待超级管理员签约(微信会发通知,需本人扫码)",
    "need_account_verify": "待账户验证(需在微信侧回填打款金额)",
    "rejected": "已驳回,请按原因修改后重新提交",
    "finished": "已开通",
}

#: 两种主体都要交的。顺序即前端进度条的展示顺序
_APPLYMENT_REQUIRED_COMMON: tuple[tuple[str, str], ...] = (
    ("subject_type", "主体类型"),
    ("business_license_image_url", "营业执照照片"),
    ("legal_person_name", "法人姓名"),
    # 敏感字段判"填没填"看密文列,不看尾号 —— 尾号是展示用的派生值
    ("legal_person_id_encrypted", "法人身份证号"),
    ("legal_person_id_front_url", "身份证人像面"),
    ("legal_person_id_back_url", "身份证国徽面"),
    ("admin_contact_name", "超级管理员姓名"),
    ("admin_contact_phone", "超级管理员手机号"),
    # 邮箱不是可选项:微信的开户/签约通知邮件发到这里,
    # 填错等于商家永远收不到"该你签约了"
    ("admin_contact_email", "超级管理员邮箱"),
    ("settle_account_type", "结算账户类型"),
    ("settle_account_name", "结算账户开户名"),
    ("settle_bank_name", "开户银行"),
    # 开户支行:微信进件必填,而 PayoutAccount 里压根没有这一项 ——
    # 这也是"两张表不能合并"的一个具体例子
    ("settle_bank_branch", "开户支行"),
    ("settle_account_no_encrypted", "结算银行账号"),
)


def applyment_missing(shop) -> list[dict]:
    """还缺哪些资料。返回 [{field, label}],空列表 = 齐了。

    个体工商户与企业交的东西**不完全一样**:企业主体的结算账户必须对公,
    拿法人个人卡去开企业特约商户,微信侧一定驳回 —— 与其等驳回回来,
    不如在我们这一侧就说清楚。个体工商户对公对私都行,不卡。

    `subject_type` 没填时只报它一个吗?不 —— 那样进度条会从 1/1 直接
    跳到 1/14,看着像出了 bug。所以按公共清单照常算,主体相关的额外规则
    等主体类型填了再叠加。
    """
    missing = [{"field": f, "label": label}
               for f, label in _APPLYMENT_REQUIRED_COMMON
               if not (getattr(shop, f, "") or "")]
    if (shop.subject_type == "enterprise"
            and shop.settle_account_type
            and shop.settle_account_type != "corporate"):
        missing.append({"field": "settle_account_type",
                        "label": "企业主体的结算账户必须是对公账户"})
    return missing


def applyment_required_total(shop) -> int:
    """必填项总数(给前端画 x/y 进度)。企业的对公约束不额外计数 ——
    它是同一个字段的取值约束,不是多一项要填的东西。"""
    return len(_APPLYMENT_REQUIRED_COMMON)


class ApplymentIn(BaseModel):
    """进件资料提交/更新。**所有字段可选** —— 这是有意的。

    商家不可能一次填完:营业执照在抽屉里、银行账号要翻网银、身份证要拍两张。
    强制一次性提交的结果是每次都从头填一遍,填到一半退出去就全丢。
    所以 PUT 是「把这次填的存下来」,只写传了的字段;
    齐没齐由 `applyment_missing` 判,不由必填校验判。

    身份证号与银行账号**明文只在这个入参里存在**:落库前就换成密文 + 尾号,
    此后任何常规接口都只能拿到尾 4 位。
    """

    subject_type: Literal["individual", "enterprise"] | None = None
    business_license_image_url: str | None = Field(default=None, max_length=300)
    legal_person_name: str | None = Field(default=None, max_length=50)
    #: 明文身份证号;校验位真算(见 validate_id_no),不是只判 18 位
    legal_person_id_no: str | None = Field(default=None, max_length=18)
    legal_person_id_front_url: str | None = Field(default=None, max_length=300)
    legal_person_id_back_url: str | None = Field(default=None, max_length=300)
    admin_contact_name: str | None = Field(default=None, max_length=50)
    admin_contact_phone: str | None = Field(default=None, max_length=20)
    admin_contact_email: str | None = Field(default=None, max_length=100)
    settle_account_type: Literal["corporate", "personal"] | None = None
    settle_account_name: str | None = Field(default=None, max_length=80)
    settle_bank_name: str | None = Field(default=None, max_length=80)
    settle_bank_branch: str | None = Field(default=None, max_length=120)
    #: 明文银行账号
    settle_account_no: str | None = Field(default=None, max_length=32)

    @model_validator(mode="after")
    def check_formats(self):
        """格式校验集中在这里,三个前端共用同一套规则(#205 明确要求)。

        每个字段都允许传空串 —— 那是「清空这一项」,不是「格式不对」。
        """
        import re

        from .services.idcheck import validate_id_no

        if self.legal_person_id_no:
            # 身份证校验位真算:GB 11643-1999 加权模 11。
            # 只判 18 位的话,随手打的 18 个数字也能过,
            # 而错号要等微信驳回才发现,一来一回是好几天
            _, err = validate_id_no(self.legal_person_id_no)
            if err:
                raise ValueError(err)
        if self.admin_contact_phone and not re.fullmatch(
                r"1\d{10}", self.admin_contact_phone.strip()):
            raise ValueError("超级管理员手机号格式不正确")
        if self.admin_contact_email and not re.fullmatch(
                r"[^@\s]+@[^@\s.]+(\.[^@\s.]+)+", self.admin_contact_email.strip()):
            raise ValueError("超级管理员邮箱格式不正确")
        if self.settle_account_no:
            # 银行卡号纯数字;国内对公/对私账号 8~32 位都有,不卡死具体长度。
            # 常见的粘贴带空格,这里先去空格再判
            no = self.settle_account_no.replace(" ", "")
            if not re.fullmatch(r"\d{8,32}", no):
                raise ValueError("银行账号须为 8~32 位数字")
        # 证件照必须在**私密桶**里。storage.url_for 给私密文件的地址是
        # /files/{purpose}/...,公开桶是 /img/...。
        # 客户端要是拿 purpose=shop 传了身份证,这里就能拦住 ——
        # 否则一张身份证会静静躺在公开桶里,而谁都不会发现
        for field, purpose in (("legal_person_id_front_url", "id_card"),
                               ("legal_person_id_back_url", "id_card"),
                               ("business_license_image_url", "license")):
            url = getattr(self, field)
            if url and not url.startswith(f"/files/{purpose}/"):
                raise ValueError(
                    f"{field} 必须是 purpose={purpose} 的私密上传地址;"
                    "证件照不能进公开桶")
        return self


class ApplymentOut(BaseModel):
    """进件资料回显。**敏感字段只有尾 4 位** —— 商家、管理员一视同仁。

    管理员要看完整号码得走 /admin/merchants/{id}/applyment/reveal,
    那个接口每调一次写一条审计。把「查看」做成一个要留痕的显式动作,
    而不是列表接口顺手带出来的副产品:
    一个后台列表不该批量吐出几百个身份证号(骑手实名那边也是这么定的)。
    """

    merchant_id: int
    merchant_name: str = ""
    subject_type: str = ""
    business_license_image_url: str = ""
    legal_person_name: str = ""
    legal_person_id_tail: str = ""      # 只有尾 4 位
    legal_person_id_front_url: str = ""
    legal_person_id_back_url: str = ""
    admin_contact_name: str = ""
    admin_contact_phone: str = ""
    admin_contact_email: str = ""
    settle_account_type: str = ""
    settle_account_name: str = ""
    settle_bank_name: str = ""
    settle_bank_branch: str = ""
    settle_account_tail: str = ""       # 只有尾 4 位
    applyment_status: str = "not_submitted"
    applyment_status_label: str = ""
    applyment_no: str = ""
    applyment_reject_reason: str = ""
    applyment_updated_at: datetime | None = None
    # 完整度:前端照着画进度条和「还差什么」,不要各自硬编码必填清单
    complete: bool = False
    missing: list[dict] = []
    required_total: int = 0
    filled_count: int = 0


#: 微信侧已经在处理、商家不能再自行改资料的状态。
#: 改了库里也报不上去(报送的是当时那一版),只会让商家以为"我已经改好了"
APPLYMENT_LOCKED_STATUSES = ("need_sign", "need_account_verify", "finished")


def next_applyment_status(current: str, complete: bool) -> str | None:
    """商家保存资料后进件状态该变成什么。None = 不变。

    规则只有两条,但两条都不能少:

    1. **资料齐了就置 `submitted`** —— 商家的动作到此为止,球在平台这边;
       只从 `not_submitted`/`rejected` 起跳,已经在微信侧流转的状态不回退;
    2. **提交后又清空了某项就退回 `not_submitted`** —— 不退的话它会一直
       挂在平台的待报送队列里,报上去必被驳回,而平台侧看不出是商家动过。
    """
    if current in APPLYMENT_LOCKED_STATUSES:
        return None
    if complete and current in ("not_submitted", "rejected"):
        return "submitted"
    if not complete and current == "submitted":
        return "not_submitted"
    return None


def applyment_out(shop, merchant_name: str = "") -> "ApplymentOut":
    """Merchant → ApplymentOut。商家侧和管理端**共用这一个映射**。

    共用是要紧的:哪天有人在管理端顺手加一行 `out.legal_person_id_no = ...`,
    也只会在这一个函数里发生,review 时看得见。
    两处各拼一遍的话,"管理员也只看尾号"这条规矩迟早在某一处被悄悄破掉。
    """
    missing = applyment_missing(shop)
    total = applyment_required_total(shop)
    return ApplymentOut(
        merchant_id=shop.id,
        merchant_name=merchant_name or shop.name,
        subject_type=shop.subject_type,
        business_license_image_url=shop.business_license_image_url,
        legal_person_name=shop.legal_person_name,
        legal_person_id_tail=shop.legal_person_id_tail,
        legal_person_id_front_url=shop.legal_person_id_front_url,
        legal_person_id_back_url=shop.legal_person_id_back_url,
        admin_contact_name=shop.admin_contact_name,
        admin_contact_phone=shop.admin_contact_phone,
        admin_contact_email=shop.admin_contact_email,
        settle_account_type=shop.settle_account_type,
        settle_account_name=shop.settle_account_name,
        settle_bank_name=shop.settle_bank_name,
        settle_bank_branch=shop.settle_bank_branch,
        settle_account_tail=shop.settle_account_tail,
        applyment_status=shop.applyment_status,
        applyment_status_label=APPLYMENT_STATUS_LABELS.get(
            shop.applyment_status, shop.applyment_status),
        applyment_no=shop.applyment_no,
        applyment_reject_reason=shop.applyment_reject_reason,
        applyment_updated_at=shop.applyment_updated_at,
        complete=not missing,
        missing=missing,
        required_total=total,
        # 直接数填了几项,不用 total - len(missing) 去倒推:
        # missing 里可能有「企业必须对公」这种**取值约束**,它不是多一项要填的,
        # 倒推会把进度条算少一格
        filled_count=sum(1 for f, _ in _APPLYMENT_REQUIRED_COMMON
                         if getattr(shop, f, "")),
    )


class ApplymentStatusIn(BaseModel):
    """平台侧流转进件状态。

    这一版微信还没接(类目答案没下来,普通服务商与电商平台两套 API 不通用),
    所以状态由平台报送人员手动推进;接上之后这里换成回调驱动,契约不变。
    """

    status: Literal["not_submitted", "submitted", "need_sign",
                    "need_account_verify", "rejected", "finished"]
    #: 驳回原因;status=rejected 时必填,商家端原样展示
    reject_reason: str = Field(default="", max_length=500)
    #: 微信侧申请单号,报送成功后回填
    applyment_no: str = Field(default="", max_length=64)

    @model_validator(mode="after")
    def rejected_needs_reason(self):
        if self.status == "rejected" and not self.reject_reason.strip():
            raise ValueError("驳回必须写明原因 —— 商家要照着改")
        return self


class ApplymentRevealIn(BaseModel):
    """解密查看敏感字段。**必须说明理由** —— 留痕留一个空理由等于没留。"""

    field: Literal["legal_person_id_no", "settle_account_no"]
    reason: str = Field(min_length=2, max_length=200)
