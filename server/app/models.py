import enum
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Enum as SAEnum,
    Float,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base
from .state_machine import OrderStatus


class UserRole(str, enum.Enum):
    customer = "customer"
    merchant = "merchant"
    rider = "rider"
    admin = "admin"  # 平台管理员,只能由 seed/运维创建,不开放注册


class MerchantStatus(str, enum.Enum):
    pending = "pending"    # 已提交,待审核
    approved = "approved"  # 审核通过,可营业
    rejected = "rejected"  # 已驳回(可修改后重新提交)


class WithdrawalStatus(str, enum.Enum):
    pending = "pending"    # 已申请,冻结余额,等平台打款
    paid = "paid"          # 已打款
    rejected = "rejected"  # 已驳回,余额退回
    failed = "failed"      # 打款被退回(收款信息有误等),余额退回,可重新申请


class VerifyStatus(str, enum.Enum):
    unsubmitted = "unsubmitted"  # 还没提交(骑手默认状态)
    pending = "pending"          # 已提交,待审核
    approved = "approved"        # 审核通过,可接单
    rejected = "rejected"        # 已驳回(可修改重新提交)


class AfterSaleStatus(str, enum.Enum):
    pending = "pending"    # 用户已申请,等商家处理
    accepted = "accepted"  # 商家同意,全额退款
    rejected = "rejected"  # 商家拒绝(需说明理由)


class TicketStatus(str, enum.Enum):
    open = "open"        # 待平台回复
    replied = "replied"  # 平台已回复
    closed = "closed"    # 已关闭


def _enum_column(enum_cls, name: str):
    return SAEnum(
        enum_cls,
        name=name,
        native_enum=False,
        length=24,
        values_callable=lambda e: [m.value for m in e],
    )


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    phone: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(100))
    name: Mapped[str] = mapped_column(String(50), default="")
    role: Mapped[UserRole] = mapped_column(_enum_column(UserRole, "user_role"))
    is_online: Mapped[bool] = mapped_column(Boolean, default=False)  # 仅骑手用
    # 轻量设备指纹(客户端登录上报,风控用:同设备多账号/商家关联下单识别)
    device_id: Mapped[str] = mapped_column(String(64), default="")
    # 骑手接单半径偏好(km,空=不限;顺路单豁免半径)
    grab_radius_km: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # 骑手所在城市(上线时按定位逆地理解析一次,管理后台可改)。
    # 只看/只抢本城订单;空 = 未标注,不参与隔离(存量宽限)
    city: Mapped[str] = mapped_column(String(20), default="")
    # 邀请码(6 位,懒生成):邀请有礼用,奖励挂被邀请人完成首单
    ref_code: Mapped[str | None] = mapped_column(
        String(6), nullable=True, unique=True)
    # 生日 MM-DD(选填,年不收集——最小化原则):生日当天发券
    birthday: Mapped[str] = mapped_column(String(5), default="")
    # 营销推送开关(生日/复购/上新等;订单状态类推送不受影响)
    marketing_push: Mapped[bool] = mapped_column(Boolean, default=True)
    avatar_url: Mapped[str] = mapped_column(String(300), default="")
    # 售后黑名单:恶意售后(客服判定)后禁止自助售后,只能走工单;公平不纵容任意一方作恶
    after_sale_banned: Mapped[bool] = mapped_column(Boolean, default=False)
    # 反作弊分级处置:""=正常(仅观察标记)/ limit=限制(暂停领券与平台补贴,下单不拦)
    # / frozen=冻结(待人工复核)。任何非空级别都对用户可见并可申诉;误伤优先放行
    risk_level: Mapped[str] = mapped_column(String(10), default="")
    risk_note: Mapped[str] = mapped_column(String(200), default="")  # 处置原因(用户可见)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Merchant(Base):
    __tablename__ = "merchants"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True)
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(Text, default="")
    address: Mapped[str] = mapped_column(String(200), default="")
    lat: Mapped[float] = mapped_column(Float)
    lng: Mapped[float] = mapped_column(Float)
    # 所在城市(入驻时逆地理解析,失败留空人工填;管理后台可改)。
    # 开城清单(platform_flags.open_cities)外的城市可入驻待审但不可营业
    city: Mapped[str] = mapped_column(String(20), default="", index=True)
    # 外卖品类(白名单见 categories.py):展示归类不是资质项,商家随时可改
    category: Mapped[str] = mapped_column(
        String(20), default="fast_food", index=True)
    is_open: Mapped[bool] = mapped_column(Boolean, default=False)
    announcement: Mapped[str] = mapped_column(String(200), default="")  # 店铺公告横幅
    logo_url: Mapped[str] = mapped_column(String(300), default="")  # 门头照/头像
    photo_urls: Mapped[list] = mapped_column(JSONB, default=list)  # 门店相册,最多 9 张
    # 营业时间 "HH:MM",两者都设置后到点自动开店/打烊;留空 = 纯手动
    open_time: Mapped[str] = mapped_column(String(5), default="")
    close_time: Mapped[str] = mapped_column(String(5), default="")
    # 平台抽成比例。5% 就是我们对抗高抽成平台的武器
    commission_rate: Mapped[Decimal] = mapped_column(Numeric(4, 3), default=Decimal("0.050"))
    # 运营三件套(商家自主设置,平台不强制):
    min_order_cents: Mapped[int] = mapped_column(Integer, default=0)    # 起送价,0=不限
    packing_fee_cents: Mapped[int] = mapped_column(Integer, default=0)  # 每单打包费
    # 满减规则 [{"threshold_cents": 3000, "off_cents": 500}, ...],成本商家承担
    promo_rules: Mapped[list] = mapped_column(JSONB, default=list)
    # 满赠规则 [{"threshold_cents": 3000, "dish_id": 1, "name": "可乐"}, ...](最多 2 档):
    # 满减动钱、满赠动货——赠品以 0 元行进订单快照,金额/佣金口径零影响
    gift_rules: Mapped[list] = mapped_column(JSONB, default=list)
    # 承诺出餐时长(分钟):接单后超过它未出餐会被催,统计超时率
    promise_ready_minutes: Mapped[int] = mapped_column(Integer, default=15)
    # 商家自配送:开启后新订单不进抢单池,商家自己送(配送费归商家)
    self_delivery: Mapped[bool] = mapped_column(Boolean, default=False)
    # 微信特约商户号(服务商模式进件后回填)+ 可分账标记(接收方绑定完成)。
    # 都就绪后新订单 settle_mode=profit_sharing:货款分账直达商家,不经平台
    sub_mchid: Mapped[str] = mapped_column(String(32), default="")
    ps_ready: Mapped[bool] = mapped_column(Boolean, default=False)
    # 临时歇业到某时刻:到点自动恢复营业(区别于手动关店忘了开);手动/自动开店时清空
    closed_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    # 节假日营业计划(最多20条,过期自动清理):
    # 歇业 {"from":"2026-02-05","to":"2026-02-12","closed":true}
    # 特殊时段 {"from":"2026-02-04","to":"2026-02-04","closed":false,"open":"10:00","close":"15:00"}
    # 优先级:计划 > 每日 open/close > 手动开关
    holiday_plans: Mapped[list] = mapped_column(JSONB, default=list)
    # 发票抬头(首次申请开票时填写,可改;申请单上存快照)
    invoice_title: Mapped[str] = mapped_column(String(100), default="")
    invoice_tax_no: Mapped[str] = mapped_column(String(30), default="")
    invoice_email: Mapped[str] = mapped_column(String(100), default="")
    # 保证金:从营收自动留存(不强制预缴)——可提余额 = 余额 - 应留保证金。
    # 用途:售后冲账余额为负时的兜底;退店无纠纷全额退还(走客服)。平台可按店调
    deposit_required_cents: Mapped[int] = mapped_column(Integer, default=50000)
    # 云打印机(飞鹅):绑定 SN 后支付成功自动出小票;printer_auto 商家可关
    printer_sn: Mapped[str] = mapped_column(String(32), default="")
    printer_auto: Mapped[bool] = mapped_column(Boolean, default=True)
    license_no: Mapped[str] = mapped_column(String(50), default="")  # 食品经营许可证号,入驻审核必填
    license_image_url: Mapped[str] = mapped_column(String(300), default="")  # 证照照片,监管要求留存影像
    status: Mapped[MerchantStatus] = mapped_column(
        _enum_column(MerchantStatus, "merchant_status"),
        default=MerchantStatus.pending,
        index=True,
    )
    reject_reason: Mapped[str] = mapped_column(String(200), default="")
    # 评分聚合(反规范化,评价创建时累加,免得列表页每次聚合查询)
    rating_sum: Mapped[int] = mapped_column(Integer, default=0)
    rating_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    @property
    def rating_avg(self) -> float | None:
        if self.rating_count == 0:
            return None
        return round(self.rating_sum / self.rating_count, 1)


class Dish(Base):
    __tablename__ = "dishes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    merchant_id: Mapped[int] = mapped_column(ForeignKey("merchants.id"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    category: Mapped[str] = mapped_column(String(50), default="")  # 点单页左侧分类栏
    price_cents: Mapped[int] = mapped_column(Integer)  # 金钱一律用「分」存整数,杜绝浮点误差
    stock: Mapped[int] = mapped_column(Integer, default=100)
    # 每日回满:非空则每天北京时间 04:00 stock 重置为该值(空=不启用,沿用手动库存)
    daily_stock: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # 估清(今日售罄):区别于下架的临时态,次日 04:00 自动恢复
    sold_out_today: Mapped[bool] = mapped_column(Boolean, default=False)
    # 估清前的库存(未启用每日回满的菜,恢复时回到这个值)
    stock_before_soldout: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_on_sale: Mapped[bool] = mapped_column(Boolean, default=True)
    # 酒类标记:商家上架自助勾选(法律义务在商家,平台提供工具与拦截)。
    # 含酒订单要求用户已实名且成年(#14),小票/骑手端提示查验收件人
    is_alcohol: Mapped[bool] = mapped_column(Boolean, default=False)
    image_url: Mapped[str] = mapped_column(String(300), default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())
    # 规格/加料组:[{"name":"份量","required":true,"multi":false,
    #   "choices":[{"name":"小份","delta_cents":0},{"name":"大份","delta_cents":300}]}]
    # 单价 = price_cents + Σ选中项 delta;下单时服务端按本字段重算,不信客户端
    options: Mapped[list] = mapped_column(JSONB, default=list)
    # 限时折扣:折扣价 + 截止时间,两者齐且未过期才生效。
    # 资金口径:折扣价就是成交价(商家自降价),佣金自动按折后实收计,无需补贴字段
    flash_price_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    flash_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_no: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    merchant_id: Mapped[int] = mapped_column(ForeignKey("merchants.id"), index=True)
    rider_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    status: Mapped[OrderStatus] = mapped_column(
        _enum_column(OrderStatus, "order_status"),
        default=OrderStatus.PENDING_PAYMENT,
        index=True,
    )
    # 下单时的菜品快照 [{dish_id, name, price_cents, quantity}]
    # 商家后来改价/删菜不影响已有订单
    items: Mapped[list] = mapped_column(JSONB)
    food_cents: Mapped[int] = mapped_column(Integer)            # 菜品合计(折前)
    packing_fee_cents: Mapped[int] = mapped_column(Integer, default=0)   # 打包费(归商家)
    discount_cents: Mapped[int] = mapped_column(Integer, default=0)      # 商家满减,商家承担
    subsidy_cents: Mapped[int] = mapped_column(Integer, default=0)       # 平台补贴(首单立减),平台承担
    promo_note: Mapped[str] = mapped_column(String(100), default="")     # 如「满30减5;首单立减3」
    delivery_fee_cents: Mapped[int] = mapped_column(Integer)
    # 小费:100% 归骑手,不计佣金基数;骑手结算行 = 配送费 + 小费
    tip_cents: Mapped[int] = mapped_column(Integer, default=0)
    # total = food + packing - discount + delivery + tip - subsidy(用户实付)
    total_cents: Mapped[int] = mapped_column(Integer)
    # 支付成功时按商家费率计算,基数是商家实收口径(food+packing-discount)
    commission_cents: Mapped[int] = mapped_column(Integer, default=0)
    address: Mapped[str] = mapped_column(String(200))
    lat: Mapped[float] = mapped_column(Float)
    lng: Mapped[float] = mapped_column(Float)
    contact_name: Mapped[str] = mapped_column(String(50), default="")
    contact_phone: Mapped[str] = mapped_column(String(20), default="")
    remark: Mapped[str] = mapped_column(String(200), default="")
    # 追加单(加菜):关联原单,免配送费,骑手/配送随原单;原单取消则级联取消
    parent_order_no: Mapped[str] = mapped_column(String(32), default="", index=True)
    # 商家自配送(下单快照):不进抢单池、无骑手,商家操作配送三态;
    # 配送费归商家(入账行并入 food 口径),平台照常只抽餐费佣金
    self_delivery: Mapped[bool] = mapped_column(Boolean, default=False)
    # 结算口径(支付时快照):platform=平台代收代付(过渡期);
    # profit_sharing=微信服务商分账,货款直达商家账户,平台不沉淀
    settle_mode: Mapped[str] = mapped_column(String(16), default="platform")
    # 地址保护(下单快照):骑手/商家视角只见 addr_public(粗地址)与中性称呼;
    # 用户可临时放行(addr_revealed)完整门牌;深夜保护单送达强制拍照留证
    addr_protect: Mapped[bool] = mapped_column(Boolean, default=False)
    addr_public: Mapped[str] = mapped_column(String(200), default="")
    addr_revealed: Mapped[bool] = mapped_column(Boolean, default=False)
    salutation: Mapped[str] = mapped_column(String(12), default="")
    delivery_photo_url: Mapped[str] = mapped_column(String(300), default="")
    # 到店自取:免配送费、不走骑手;用户凭取餐码到店,商家核对后完成订单
    pickup: Mapped[bool] = mapped_column(Boolean, default=False)
    pickup_code: Mapped[str] = mapped_column(String(8), default="")
    # 预约送达时间(空 = 尽快送)。商家接单超时豁免至预约前 1 小时
    scheduled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    # 预计送达时间(支付时按距离朴素公式生成;预约单=预约时间)。
    # 实际送达超过它 15 分钟自动发安抚券(平台承担,见 services/eta.py)
    eta_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    cancel_reason: Mapped[str] = mapped_column(String(200), default="")  # 取消/拒单原因
    # 无骑手接单提醒已发(清扫任务用,每单只提醒一次)
    no_rider_alerted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    # 进入无骑手状态的时刻:支付成功、骑手转单时刷新。
    # 无人接单兜底的即时单计时基准(转出的单从转单时刻重新起算)
    rider_pool_since: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    # 接单时刻:出餐超时判定与用户 2 分钟反悔窗口的共同基准
    accepted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    ready_alert_stage: Mapped[int] = mapped_column(Integer, default=0)  # 出餐催单档位 0/1/2
    ready_late: Mapped[bool] = mapped_column(Boolean, default=False)    # 出餐超时(定格)
    # AXB 隐私中间号(X 号):绑定后商家/骑手看到与拨打的都是它,订单终结后解绑清空
    privacy_phone: Mapped[str] = mapped_column(String(20), default="")
    # 风控标记(只标记不拦截):{"hits": ["addr_freq", ...], "status": ""|"confirmed"|"cleared"}
    # confirmed 的单从月售/销量排行剔除;资金结算不受影响(钱是真付的)
    risk_flags: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # 缺货部分退款:累计退款金额 + 明细(如「酸辣粉×1」)
    refund_cents: Mapped[int] = mapped_column(Integer, default=0)
    refund_note: Mapped[str] = mapped_column(String(300), default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Address(Base):
    """用户收货地址簿。address 存 POI 名+区划,detail 存门牌/单元。"""

    __tablename__ = "addresses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    contact_name: Mapped[str] = mapped_column(String(50))
    contact_phone: Mapped[str] = mapped_column(String(20))
    address: Mapped[str] = mapped_column(String(200))
    detail: Mapped[str] = mapped_column(String(100), default="")
    lat: Mapped[float] = mapped_column(Float)
    lng: Mapped[float] = mapped_column(Float)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    # 保护模式:骑手只看到粗地址(POI/小区),门牌详情送达前不下发;
    # 深夜独居场景的安全开关(下单页 21:00-06:00 主动提示可开)
    protect: Mapped[bool] = mapped_column(Boolean, default=False)
    # 中性称呼(如"顾客"/"李女士"),骑手/商家侧替代真实姓名;空=「顾客」
    salutation: Mapped[str] = mapped_column(String(12), default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class UserIdentity(Base):
    """用户实名认证(按需触发,不是注册门槛):酒类等受限品类的年龄核验。

    身份证号 Fernet 加密落库,明文不入库不出接口;接口只回
    verified/is_adult 与打码姓名。注销账号时本表记录一并删除。
    """

    __tablename__ = "user_identities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), unique=True, index=True)
    real_name: Mapped[str] = mapped_column(String(50))
    id_no_encrypted: Mapped[str] = mapped_column(String(500))
    birth_date: Mapped[date] = mapped_column(Date)
    verified_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class RiderProfile(Base):
    """骑手实名认证 + 健康证。未认证(非 approved)不得上线接单——合规硬要求。"""

    __tablename__ = "rider_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    rider_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True, index=True)
    real_name: Mapped[str] = mapped_column(String(50), default="")
    id_card_no: Mapped[str] = mapped_column(String(18), default="")
    id_card_photo_url: Mapped[str] = mapped_column(String(300), default="")   # 身份证人像面
    health_cert_photo_url: Mapped[str] = mapped_column(String(300), default="")  # 健康证
    # 紧急联系人(最多2人,JSON 加密串,同收款账户口径;明文不出接口)
    emergency_contacts_enc: Mapped[str] = mapped_column(String(800), default="")
    status: Mapped[VerifyStatus] = mapped_column(
        _enum_column(VerifyStatus, "verify_status"),
        default=VerifyStatus.pending,
        index=True,
    )
    reject_reason: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class EarningKind(str, enum.Enum):
    earning = "earning"        # 正常入账
    reversal = "reversal"      # 售后冲账(负数行,与入账行相加归零)
    adjustment = "adjustment"  # 申诉改判等正向调整(恢复被冲的净额,平台认亏)


class RiderEarning(Base):
    """骑手收入流水:订单完成时入账,一单一种类型一条。
    只追加、不修改、不删除——账本的铁律;冲账也是追加一条负数行。"""

    __tablename__ = "rider_earnings"
    __table_args__ = (UniqueConstraint("order_id", "kind"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    rider_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"))
    order_no: Mapped[str] = mapped_column(String(32))
    amount_cents: Mapped[int] = mapped_column(Integer)
    kind: Mapped[EarningKind] = mapped_column(
        _enum_column(EarningKind, "earning_kind"), default=EarningKind.earning
    )
    note: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class MerchantEarning(Base):
    """商家收入流水:订单完成时入账,净额 = 菜品金额 - 平台佣金。
    与骑手账本同构:一单一种类型一条、只追加;售后冲账 = 追加负数行。
    (微信分账模式下货款直达商家,这张表是对账依据,不是资金池)"""

    __tablename__ = "merchant_earnings"
    __table_args__ = (UniqueConstraint("order_id", "kind"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    merchant_id: Mapped[int] = mapped_column(ForeignKey("merchants.id"), index=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"))
    order_no: Mapped[str] = mapped_column(String(32))
    food_cents: Mapped[int] = mapped_column(Integer)
    commission_cents: Mapped[int] = mapped_column(Integer)
    net_cents: Mapped[int] = mapped_column(Integer)
    # 结算口径(随订单快照):profit_sharing 行的钱已直达商家微信商户号,
    # 不计入平台侧可提现余额(钱包/审计 4b 按此过滤,防双发)
    settle_mode: Mapped[str] = mapped_column(String(16), default="platform")
    kind: Mapped[EarningKind] = mapped_column(
        _enum_column(EarningKind, "earning_kind"), default=EarningKind.earning
    )
    note: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class RefundStatus(str, enum.Enum):
    requested = "requested"  # 已向支付渠道发起,等回调确认
    success = "success"      # 渠道确认退款成功(模拟通道即时成功)
    failed = "failed"        # 渠道拒绝/失败,需人工介入


class Refund(Base):
    """退款流水:每次退款(缺货部分退/整单退/售后退)一条,金额对账的凭据。
    订单上的 refund_cents 是汇总视图,本表是逐笔明细,审计核对两者恒等。"""

    __tablename__ = "refunds"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True)
    order_no: Mapped[str] = mapped_column(String(32))
    out_refund_no: Mapped[str] = mapped_column(String(64), unique=True)
    amount_cents: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(String(200))
    channel: Mapped[str] = mapped_column(String(12))  # mock / wechat
    status: Mapped[RefundStatus] = mapped_column(
        _enum_column(RefundStatus, "refund_status"),
        default=RefundStatus.requested, index=True,
    )
    error: Mapped[str] = mapped_column(String(300), default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Withdrawal(Base):
    """提现申请。pending 即冻结对应余额;驳回退回,打款终结。
    骑手和商家(店主账号)共用一张表、同一套 T+1 打款流程,role 区分。"""

    __tablename__ = "withdrawals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    role: Mapped[str] = mapped_column(String(10), default="rider")  # rider / merchant
    amount_cents: Mapped[int] = mapped_column(Integer)
    status: Mapped[WithdrawalStatus] = mapped_column(
        _enum_column(WithdrawalStatus, "withdrawal_status"),
        default=WithdrawalStatus.pending,
        index=True,
    )
    reject_reason: Mapped[str] = mapped_column(String(200), default="")  # 驳回/退票原因
    paid_note: Mapped[str] = mapped_column(String(200), default="")  # 打款凭证/批次号
    # 打款通道:manual 人工线下 / wechat 商家转账 API(接入后由回调驱动状态)
    channel: Mapped[str] = mapped_column(String(10), default="manual")
    channel_ref: Mapped[str] = mapped_column(String(64), default="")  # 渠道转账单号
    # 申请时的收款账户快照(含密文账号):打款照快照打,改账户不影响在途申请
    account_snapshot: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    processed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class InvoiceRequest(Base):
    """平台服务费发票申请:商家按自然月索取(佣金+团购服务费),
    金额系统聚合不让商家填;管理员线下开电子普票后回填文件链接。"""

    __tablename__ = "invoice_requests"
    __table_args__ = (UniqueConstraint("merchant_id", "period"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    merchant_id: Mapped[int] = mapped_column(ForeignKey("merchants.id"), index=True)
    period: Mapped[str] = mapped_column(String(7))  # 如 2026-07
    amount_cents: Mapped[int] = mapped_column(Integer)  # 申请时系统聚合快照
    title: Mapped[str] = mapped_column(String(100))     # 抬头快照
    tax_no: Mapped[str] = mapped_column(String(30))
    email: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(12), default="pending", index=True)
    # pending 待开票 / issued 已开票 / rejected 已驳回
    file_url: Mapped[str] = mapped_column(String(300), default="")  # 电子发票 PDF
    note: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    processed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class PayoutAccount(Base):
    """收款账户:骑手/商家提现的打款目标(店主账号维度,一人一户,更换即覆盖)。
    账号密文落库(services/crypto.py),普通接口只回尾 4 位;
    提现申请时快照冻结到 withdrawals.account_snapshot,改账户不影响在途申请。"""

    __tablename__ = "payout_accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True)
    role: Mapped[str] = mapped_column(String(10))  # rider / merchant
    # bank_corporate 对公 / bank_personal 对私 / wechat 微信 / alipay 支付宝
    kind: Mapped[str] = mapped_column(String(16))
    holder_name: Mapped[str] = mapped_column(String(50))
    account_no_encrypted: Mapped[str] = mapped_column(String(300))
    account_tail: Mapped[str] = mapped_column(String(4))   # 展示用尾号
    bank_name: Mapped[str] = mapped_column(String(100), default="")  # 银行类必填
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Ticket(Base):
    """客服工单:三端任何角色都能找到平台真人。
    产品里所有「联系平台客服」的承诺,落点都在这里。"""

    __tablename__ = "tickets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    role: Mapped[str] = mapped_column(String(20))       # 提交时的角色快照
    contact: Mapped[str] = mapped_column(String(50))    # 联系方式(默认手机号)
    content: Mapped[str] = mapped_column(String(500))
    status: Mapped[TicketStatus] = mapped_column(
        _enum_column(TicketStatus, "ticket_status"),
        default=TicketStatus.open,
        index=True,
    )
    reply: Mapped[str] = mapped_column(String(500), default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    replied_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class AuditAlert(Base):
    """账务自检告警:恒等式不平时写一条,管理后台首页显眼展示。"""

    __tablename__ = "audit_alerts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    check_name: Mapped[str] = mapped_column(String(50))
    detail: Mapped[str] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class AuditRun(Base):
    """每日账务自检运行记录:干净的运行也留痕——透明中心公示
    "昨日核账 N 笔,差错 0 笔"与连续无差错天数,靠这张表说话。"""

    __tablename__ = "audit_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    day: Mapped[str] = mapped_column(String(10), unique=True)  # 北京时间 YYYY-MM-DD
    checked_orders: Mapped[int] = mapped_column(Integer, default=0)
    problem_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class FlagHistory(Base):
    """平台开关变更留痕:改了什么、何时、为什么。

    白名单内对用户有感知的开关(天气加价/停运/深夜保护等)在透明中心
    时间线公开展示;敏感运营开关只留内档不公开。自本表上线起记录,不补历史。"""

    __tablename__ = "flag_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(40), index=True)
    old_value: Mapped[str] = mapped_column(String(200), default="")
    new_value: Mapped[str] = mapped_column(String(200), default="")
    reason: Mapped[str] = mapped_column(String(200), default="")  # 选填,公开展示
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class RiskActionLog(Base):
    """反作弊处置留痕:透明中心按月聚合公示(限制/冻结/解除各多少)。
    公开侧绝不下发 user_id——只有计数,没有个案。"""

    __tablename__ = "risk_action_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    from_level: Mapped[str] = mapped_column(String(10), default="")
    to_level: Mapped[str] = mapped_column(String(10), default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class HealthProbe(Base):
    """系统状态自记探针(auto_flow 每 5 分钟一次):/status 可用率数据源。

    数据库不可用时这一行根本写不进来——缺的探针按不可用计,
    所以可用率只会算低不会虚高。保留 90 天。"""

    __tablename__ = "health_probes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    db_ok: Mapped[bool] = mapped_column(Boolean, default=True)
    redis_ok: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )


class Favorite(Base):
    """收藏店铺:一人一店一条。"""

    __tablename__ = "favorites"
    __table_args__ = (UniqueConstraint("user_id", "merchant_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    merchant_id: Mapped[int] = mapped_column(ForeignKey("merchants.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class AfterSale(Base):
    """售后申请:一单一次,已送达/已完成 7 天内可发起。
    商业平台的售后有多官僚,我们就要做多顺畅——这是信任闭环的一部分。"""

    __tablename__ = "after_sales"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), unique=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    merchant_id: Mapped[int] = mapped_column(ForeignKey("merchants.id"), index=True)
    reason: Mapped[str] = mapped_column(String(500))
    # 举证照片(必传):完成单售后要有图,客服/商家看图判断,恶意售后无所遁形
    images: Mapped[list] = mapped_column(JSONB, default=list)
    # 判责方:merchant=商家责任(商家承担) / rider=骑手责任(平台先行赔付,保障金覆盖)
    fault: Mapped[str] = mapped_column(String(12), default="")
    status: Mapped[AfterSaleStatus] = mapped_column(
        _enum_column(AfterSaleStatus, "after_sale_status"),
        default=AfterSaleStatus.pending,
        index=True,
    )
    reply: Mapped[str] = mapped_column(String(300), default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    processed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class DeliveryIssue(Base):
    """配送异常工单:骑手在配送途中上报(联系不上/地址错误/餐损/其他),
    平台仲裁三选一:协调后继续送 / 用户责任按送达处理 / 骑手责任平台先行赔付。
    kind/resolution 用 varchar 存枚举值,取值见 schemas 的 Literal。"""

    __tablename__ = "delivery_issues"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True)
    order_no: Mapped[str] = mapped_column(String(32))
    rider_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    # cannot_contact 联系不上顾客 / wrong_address 地址错误 / food_damaged 餐损 / other
    kind: Mapped[str] = mapped_column(String(20))
    note: Mapped[str] = mapped_column(String(300), default="")
    photo_url: Mapped[str] = mapped_column(String(300), default="")  # 餐损必传
    status: Mapped[str] = mapped_column(String(12), default="open", index=True)
    # continue_delivery 协调继续送 / mark_delivered 按送达处理 / refund 平台先行赔付
    resolution: Mapped[str] = mapped_column(String(20), default="")
    resolve_note: Mapped[str] = mapped_column(String(300), default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class Review(Base):
    """订单评价:一单一评,只有完成的订单能评。"""

    __tablename__ = "reviews"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), unique=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    merchant_id: Mapped[int] = mapped_column(ForeignKey("merchants.id"), index=True)
    rider_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    merchant_rating: Mapped[int] = mapped_column(Integer)  # 1-5
    rider_rating: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 1-5
    comment: Mapped[str] = mapped_column(String(500), default="")
    image_urls: Mapped[list] = mapped_column(JSONB, default=list)  # 图片评价,最多 6 张
    tags: Mapped[list] = mapped_column(JSONB, default=list)  # 一键标签(白名单见 schemas)
    reply: Mapped[str] = mapped_column(String(300), default="")  # 商家回复
    # 真匿名:展示"匿名用户",商家侧完全不可反查;平台后台仍可见(处理恶意评价)
    is_anonymous: Mapped[bool] = mapped_column(Boolean, default=False)
    # 追评(首评后 7 天内一次;匿名评价的追评继承匿名)
    append_content: Mapped[str] = mapped_column(String(500), default="")
    append_images: Mapped[list] = mapped_column(JSONB, default=list)
    append_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    append_reply: Mapped[str] = mapped_column(String(300), default="")
    # 申诉改判后隐藏:不在任何列表展示,不参与评分(评分聚合同步扣减)
    hidden: Mapped[bool] = mapped_column(Boolean, default=False)
    # 刷评识别:命中疑似规则(同店高频/下单到评价间隔异常)标记待复核,不自动删/隐藏
    flagged: Mapped[bool] = mapped_column(Boolean, default=False)
    flag_reason: Mapped[str] = mapped_column(String(100), default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Appeal(Base):
    """判责申诉:骑手/商家对平台单方裁决(售后判责/配送异常裁决/差评)的复核通道。
    72 小时内、每个目标一次;改判动作平台认亏,不追用户款(见 routers/appeals.py)。"""

    __tablename__ = "appeals"
    __table_args__ = (UniqueConstraint("target_type", "target_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    role: Mapped[str] = mapped_column(String(10))  # rider / merchant
    # after_sale / delivery_issue / review
    target_type: Mapped[str] = mapped_column(String(20))
    target_id: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(String(500))
    images: Mapped[list] = mapped_column(JSONB, default=list)
    status: Mapped[str] = mapped_column(String(12), default="open", index=True)
    # upheld 维持原判 / overturned 改判
    resolve_note: Mapped[str] = mapped_column(String(300), default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class VoucherPurchaseStatus(str, enum.Enum):
    pending_payment = "pending_payment"  # 待支付(15 分钟超时关闭)
    paid = "paid"                        # 已购未使用(可退款)
    redeemed = "redeemed"                # 已核销(商家入账,不可退)
    refunded = "refunded"                # 已退款
    cancelled = "cancelled"              # 支付超时关闭


class Voucher(Base):
    """团购券(商家发布的代金券):花 sell 元买 face 元额度,到店核销。

    平台只在核销时收 2% 服务费——券没被使用,平台一分不赚。
    """

    __tablename__ = "vouchers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    merchant_id: Mapped[int] = mapped_column(ForeignKey("merchants.id"), index=True)
    title: Mapped[str] = mapped_column(String(80))          # 如「50元代金券」
    description: Mapped[str] = mapped_column(String(200), default="")
    sell_price_cents: Mapped[int] = mapped_column(Integer)  # 售价
    face_value_cents: Mapped[int] = mapped_column(Integer)  # 面值(到店抵扣额)
    total_count: Mapped[int] = mapped_column(Integer)       # 剩余可售(卖一减一)
    sold_count: Mapped[int] = mapped_column(Integer, default=0)
    per_user_limit: Mapped[int] = mapped_column(Integer, default=5)
    valid_days: Mapped[int] = mapped_column(Integer, default=90)  # 购买后有效期
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class VoucherPurchase(Base):
    """券实例:一次购买一张,券码唯一。资金字段在核销时落定(commission/net)。"""

    __tablename__ = "voucher_purchases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    purchase_no: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    voucher_id: Mapped[int] = mapped_column(ForeignKey("vouchers.id"), index=True)
    merchant_id: Mapped[int] = mapped_column(ForeignKey("merchants.id"), index=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    sell_price_cents: Mapped[int] = mapped_column(Integer)   # 快照,商家改价不影响已购券
    face_value_cents: Mapped[int] = mapped_column(Integer)
    commission_cents: Mapped[int] = mapped_column(Integer, default=0)  # 核销时 = 售价×2%
    net_cents: Mapped[int] = mapped_column(Integer, default=0)         # 核销时 = 售价-服务费
    code: Mapped[str] = mapped_column(String(16), unique=True, index=True)  # 核销码
    status: Mapped[VoucherPurchaseStatus] = mapped_column(
        _enum_column(VoucherPurchaseStatus, "voucher_purchase_status"),
        default=VoucherPurchaseStatus.pending_payment,
        index=True,
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)  # 支付时 = now + valid_days
    refund_note: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    paid_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    redeemed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)


class FoodSafetyReport(Base):
    """食品安全投诉(红线通道):异物/变质/食用后不适。

    不经商家、直达平台(管理后台标红加急);处置动作(先行退款/下架菜品/
    暂停营业)全部留痕在 actions,监管检查可导出。同一商家 30 天内
    ≥3 起成立自动停业待人工审核。
    """

    __tablename__ = "food_safety_reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True)
    order_no: Mapped[str] = mapped_column(String(32))
    customer_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    merchant_id: Mapped[int] = mapped_column(
        ForeignKey("merchants.id"), index=True)
    # foreign_object 异物 / spoiled 变质 / sick 食用后不适
    kind: Mapped[str] = mapped_column(String(20))
    description: Mapped[str] = mapped_column(String(500))
    images: Mapped[list] = mapped_column(JSONB, default=list)        # 必传
    medical_urls: Mapped[list] = mapped_column(JSONB, default=list)  # 医疗凭证,选传
    status: Mapped[str] = mapped_column(String(12), default="open", index=True)
    # 处置留痕:[{action, note, admin_id, at}](confirmed/dismissed/dish_off/suspend/auto_suspend)
    actions: Mapped[list] = mapped_column(JSONB, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)


class OrderEvent(Base):
    """状态流转审计日志:每次变更一条,纠纷仲裁全靠它。"""

    __tablename__ = "order_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True)
    from_status: Mapped[str] = mapped_column(String(24))
    to_status: Mapped[str] = mapped_column(String(24))
    actor_role: Mapped[str] = mapped_column(String(24))
    actor_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    note: Mapped[str] = mapped_column(String(120), default="")  # 事件备注(转单原因等)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Announcement(Base):
    """平台公告:发通知不用发版。按端(audience)定向,时间窗内生效。"""

    __tablename__ = "announcements"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    audience: Mapped[str] = mapped_column(String(12), index=True)  # user/merchant/rider/all
    title: Mapped[str] = mapped_column(String(50))
    content: Mapped[str] = mapped_column(String(500))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    starts_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)  # 空 = 立即
    ends_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)  # 空 = 长期
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class SplashConfig(Base):
    """开屏运营位:三端 App 冷启动的可配置图文开屏(自营内容,不是广告位)。

    端定向 + 时间窗 + 倒计时秒数;没配置/过期时客户端回落品牌开屏。
    客户端拉到后缓存本地下次启动用,永不阻塞冷启动。"""

    __tablename__ = "splash_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    audience: Mapped[str] = mapped_column(String(12), default="all", index=True)
    title: Mapped[str] = mapped_column(String(50), default="")
    subtitle: Mapped[str] = mapped_column(String(100), default="")
    image_url: Mapped[str] = mapped_column(String(300))  # 建议 1080×1920 竖图
    countdown_seconds: Mapped[int] = mapped_column(Integer, default=3)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    starts_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)  # 空 = 立即
    ends_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)  # 空 = 长期
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class AppEvent(Base):
    """自建埋点:只收登录用户的产品行为(浏览/搜索/分享),不收设备指纹。

    服务端已有的交易数据(下单/支付)不重复埋。收集范围已写入隐私政策。
    """

    __tablename__ = "app_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    role: Mapped[str] = mapped_column(String(12))
    event: Mapped[str] = mapped_column(String(50), index=True)
    props: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class RiderInsuranceDay(Base):
    """骑手意外险每日记录:上线自动投保(桩未配置时为登记模式,
    保障金池兜底先行赔付);费用从保障金池支出。"""

    __tablename__ = "rider_insurance_days"
    __table_args__ = (UniqueConstraint("rider_id", "day"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    rider_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    day: Mapped[str] = mapped_column(String(10))  # 北京日 YYYY-MM-DD
    policy_no: Mapped[str] = mapped_column(String(64), default="")
    premium_cents: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(12), default="registered")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class RiderAccident(Base):
    """交通事故上报(红线通道):上报即在途单无责释放+红色加急工单;
    处置留痕 actions,SOP 见 docs/RIDER_SOP.md。"""

    __tablename__ = "rider_accidents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    rider_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    lng: Mapped[float | None] = mapped_column(Float, nullable=True)
    severity: Mapped[str] = mapped_column(String(12))  # minor/injury/serious
    description: Mapped[str] = mapped_column(String(500), default="")
    photos: Mapped[list] = mapped_column(JSONB, default=list)
    status: Mapped[str] = mapped_column(String(12), default="open", index=True)
    actions: Mapped[list] = mapped_column(JSONB, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class RiderExam(Base):
    """骑手上岗培训考试记录:题库 20 题抽 10,80 分过;
    强制开关走 platform_flags(存量骑手宽限)。"""

    __tablename__ = "rider_exams"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    rider_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    score: Mapped[int] = mapped_column(Integer)
    passed: Mapped[bool] = mapped_column(Boolean)
    answers: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class RiderGear(Base):
    """装备申领登记(头盔/餐箱/雨衣):申领→发放留痕,不做佩戴监控。"""

    __tablename__ = "rider_gear"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    rider_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    item: Mapped[str] = mapped_column(String(20))  # helmet/box/raincoat
    status: Mapped[str] = mapped_column(String(12), default="requested")
    note: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    issued_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)


class RiderSession(Base):
    """骑手在线时长记录(只统计不考核):上线开区间、下线闭区间;
    位置心跳断档超 5 分钟由清扫任务补写下线。"""

    __tablename__ = "rider_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    rider_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    online_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    offline_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)


class ModerationWord(Base):
    """敏感词库:文本内容(评价/公告/昵称/菜名/工单)写入前同步拦截。

    种子只放少量示例词,完整词库由运营在管理后台维护——
    开源仓库里不放敏感词表。
    """

    __tablename__ = "moderation_words"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    word: Mapped[str] = mapped_column(String(50), unique=True)
    category: Mapped[str] = mapped_column(String(20), default="other")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class ContentReview(Base):
    """图片审核队列(先发后审):评价图/菜品图/头像先上线、后机审或人工抽查,
    驳回则隐藏并通知。kind: review(评价图)/dish(菜品图)/avatar(头像)。"""

    __tablename__ = "content_reviews"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(20))
    ref_id: Mapped[int] = mapped_column(Integer)
    url: Mapped[str] = mapped_column(String(300))
    status: Mapped[str] = mapped_column(String(12), default="pending", index=True)
    note: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)


class PushLog(Base):
    """离线推送结果记录:排查"商家说没收到新单提醒"时的第一现场。

    订单状态类只记真实尝试(未配置时静默跳过,避免开发期刷屏);
    回复/收藏/召回等触达类低频推送即使未配置也记一条"意图"
    (push_to_user record_skip=True),配好 Key 前就能验证触发链路。
    """

    __tablename__ = "push_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)  # 目标用户(别名 u{id})
    title: Mapped[str] = mapped_column(String(50))
    content: Mapped[str] = mapped_column(String(200))
    ok: Mapped[bool] = mapped_column(Boolean)
    error: Mapped[str] = mapped_column(String(300), default="")  # 失败时的原因摘要
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

class LedgerAnchor(Base):
    """公开账本锚点:一天一条,哈希链防篡改(见证节点体系的地基)。

    payload = 当日全部账务流水的匿名化导出(订单号哈希,无任何个人信息),
    chain_hash = sha256(前一天 chain_hash + 当日 payload_hash) —— 改历史任何
    一条流水,之后所有锚点全部对不上。锚点只为已关账的日子生成,永不重算。
    社区见证节点各自留存见过的 chain_hash,平台自己也改不了历史。
    """

    __tablename__ = "ledger_anchors"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    day: Mapped[str] = mapped_column(String(10), unique=True)  # 北京时间 yyyy-MM-dd
    payload: Mapped[str] = mapped_column(Text)                 # 规范化 JSON 全文
    payload_hash: Mapped[str] = mapped_column(String(64))
    chain_hash: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class WitnessNode(Base):
    """社区见证节点注册表:心跳即注册,不收集运行者任何身份信息。

    divergent=True 表示该节点报告其本地留存的历史锚点与平台当前不一致——
    这是整套体系要抓的事(平台改账),必须在 /nodes 页面公开示警。
    """

    __tablename__ = "witness_nodes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    node_id: Mapped[str] = mapped_column(String(64), unique=True)  # 节点自生成 UUID
    name: Mapped[str] = mapped_column(String(30), default="")      # 自愿展示的名字
    region: Mapped[str] = mapped_column(String(30), default="")    # 自愿展示的地区
    # 自愿上报的时区(IANA 名或 UTC±HH:MM),/nodes 世界地图据此粗定位;可为空
    tz: Mapped[str] = mapped_column(String(40), default="")
    version: Mapped[str] = mapped_column(String(20), default="")
    verified_day: Mapped[str] = mapped_column(String(10), default="")  # 校验到哪天
    ok: Mapped[bool] = mapped_column(Boolean, default=True)       # 最近一次校验结论
    divergent: Mapped[bool] = mapped_column(Boolean, default=False)
    message: Mapped[str] = mapped_column(String(200), default="")
    heartbeats: Mapped[int] = mapped_column(Integer, default=0)
    first_seen: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_seen: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class PlatformFlag(Base):
    """平台运行时开关(极简 KV):管理员改,立即生效,不用发版。

    目前唯一的键:weather_surcharge = "on"/"off" —— 恶劣天气配送加价开关。
    """

    __tablename__ = "platform_flags"

    key: Mapped[str] = mapped_column(String(40), primary_key=True)
    value: Mapped[str] = mapped_column(String(200), default="")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Coupon(Base):
    """最小平台券:目前只有超时赔付安抚券(无门槛,平台承担)。

    下单抵扣走 subsidy_cents 口径(与首单立减同一条审计通道);
    source 唯一约束保证同一来源(如 eta:订单号)最多发一张。
    订单全额退款/关单时释放回券包(used_order_no 清空),未过期可再用。
    """
    __tablename__ = "coupons"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    amount_cents: Mapped[int] = mapped_column(Integer)
    min_spend_cents: Mapped[int] = mapped_column(Integer, default=0)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_order_no: Mapped[str] = mapped_column(String(32), default="")
    source: Mapped[str] = mapped_column(String(64), unique=True)
    # 资金方:platform=平台承担(走 subsidy)/ merchant=商家承担(走 discount)。
    # 商家店铺券只能在发券商家使用(merchant_id 限定)
    funder: Mapped[str] = mapped_column(String(10), default="platform")
    merchant_id: Mapped[int | None] = mapped_column(
        ForeignKey("merchants.id"), nullable=True)
    # 发放批次(超时安抚券等系统券为空)
    batch_id: Mapped[int | None] = mapped_column(
        ForeignKey("coupon_batches.id"), nullable=True, index=True)
    note: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Message(Base):
    """订单内聊天(用户↔骑手 / 用户↔商家)。

    支付后开启,订单终结 2 小时后只读,7 天后当事人不可见
    (留档供仲裁);文本过敏感词;电话(隐私号)仍是兜底。
    """
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True)
    sender_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    sender_role: Mapped[str] = mapped_column(String(12))
    receiver_role: Mapped[str] = mapped_column(String(12))
    kind: Mapped[str] = mapped_column(String(8), default="text")
    content: Mapped[str] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class MerchantStaff(Base):
    """商家子账号:店主给店员开的操作账号,能接单/出餐/估清,不能提现改价改设置。

    敏感端点本就按 Merchant.owner_id 鉴权(店员非店主自然被拒),这里只授予
    运营类操作权限;店员账号 role=merchant 但自己不拥有店铺。
    """
    __tablename__ = "merchant_staff"
    __table_args__ = (UniqueConstraint("merchant_id", "user_id",
                                       name="uq_staff_merchant_user"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    merchant_id: Mapped[int] = mapped_column(
        ForeignKey("merchants.id"), index=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(50), default="")  # 备注名
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())


class Cart(Base):
    """云端购物车:按 用户×商家 存一份未提交购物车,跨设备续用。

    items 是 [{"dish_id","choices","quantity"}] 快照(与下单入参同构);
    展示价/校验一律以进店时的当前菜单为准,这里只存"选了什么"。
    """
    __tablename__ = "carts"
    __table_args__ = (UniqueConstraint("user_id", "merchant_id",
                                       name="uq_cart_user_merchant"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    merchant_id: Mapped[int] = mapped_column(ForeignKey("merchants.id"))
    items: Mapped[list] = mapped_column(JSONB, default=list)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ProfitSharingRecord(Base):
    """分账请求台账:完成单发起分账的幂等记录(一单一条)。

    pending=待发起/待重试(清扫任务兜底),success=分账完成,
    failed=超过重试上限(人工介入),returned=全额退款已回退。
    渠道侧真金白银的流向以微信账单为准,这张表是本地对账依据。
    """
    __tablename__ = "profit_sharing_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), unique=True)
    order_no: Mapped[str] = mapped_column(String(32), index=True)
    merchant_id: Mapped[int] = mapped_column(
        ForeignKey("merchants.id"), index=True)
    sub_mchid: Mapped[str] = mapped_column(String(32))
    net_cents: Mapped[int] = mapped_column(Integer)
    commission_cents: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(
        String(12), default="pending", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    note: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
        onupdate=func.now())


class RiderEmergency(Base):
    """骑手一键紧急求助(SOS):进行中的危险,区别于事后的事故上报。

    触发即红色加急工单+推送管理员;误触可在短窗口内自助撤销;
    在途订单不自动动(误触率高),由客服确认后走改派/仲裁。
    """
    __tablename__ = "rider_emergencies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    rider_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    lng: Mapped[float | None] = mapped_column(Float, nullable=True)
    note: Mapped[str] = mapped_column(String(200), default="")
    status: Mapped[str] = mapped_column(String(12), default="open", index=True)
    actions: Mapped[list] = mapped_column(JSONB, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())


class AddressFeedback(Base):
    """骑手「地址不准」反馈(每单一条):同一用户同一地址攒 2 条后,
    下次下单提示核对——地址不准是配送效率第一杀手,但只提示不拦截。"""
    __tablename__ = "address_feedback"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    customer_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), index=True)
    address: Mapped[str] = mapped_column(String(200))
    order_no: Mapped[str] = mapped_column(String(32), unique=True)
    rider_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    note: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())


class CouponBatch(Base):
    """券批次:面额/门槛/有效期/总量(预算封顶)/触发方式。

    trigger:newcomer=注册自动发(风控命中的不发)/ manual=定向补偿发 /
    birthday=生日券 / winback=复购提醒(#51)。发放用条件 UPDATE 扣
    issued 防超发;每人每批次一张(coupons.source 唯一兜底)。
    """
    __tablename__ = "coupon_batches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(50))
    trigger: Mapped[str] = mapped_column(
        String(12), default="manual", index=True)
    amount_cents: Mapped[int] = mapped_column(Integer)
    min_spend_cents: Mapped[int] = mapped_column(Integer, default=0)
    valid_days: Mapped[int] = mapped_column(Integer, default=7)
    total: Mapped[int] = mapped_column(Integer)
    issued: Mapped[int] = mapped_column(Integer, default=0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    # 店铺券:非空 = 商家自建券(成本商家承担),trigger="shop";每人限领
    merchant_id: Mapped[int | None] = mapped_column(
        ForeignKey("merchants.id"), nullable=True, index=True)
    per_user_limit: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())


class Referral(Base):
    """邀请关系:被邀请人 24 小时内填码建立;完成首单后双方发券。

    防刷:同设备不建立、邀请人月上限、风控命中的完成单不触发(留待
    下一笔干净的单)。invitee 唯一——一个新用户只能被邀请一次。
    """
    __tablename__ = "referrals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    inviter_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), index=True)
    invitee_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True)
    status: Mapped[str] = mapped_column(
        String(12), default="pending", index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())
    rewarded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
