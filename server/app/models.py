import enum
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Enum as SAEnum,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    literal,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base
from .state_machine import OrderStatus, StayOrderStatus


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
    # 手机号按角色分账号:同一手机号可分别注册 用户/商家/骑手,互不影响
    __table_args__ = (UniqueConstraint("phone", "role", name="uq_users_phone_role"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    phone: Mapped[str] = mapped_column(String(20), index=True)
    password_hash: Mapped[str] = mapped_column(String(100))
    name: Mapped[str] = mapped_column(String(50), default="")
    role: Mapped[UserRole] = mapped_column(_enum_column(UserRole, "user_role"))
    is_online: Mapped[bool] = mapped_column(Boolean, default=False)  # 仅骑手用
    # 轻量设备指纹(客户端登录上报,风控用:同设备多账号/商家关联下单识别)
    device_id: Mapped[str] = mapped_column(String(64), default="")
    # 骑手接单半径偏好(km,空=不限;顺路单豁免半径)
    grab_radius_km: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # 骑手接单偏好(0/False 一律表示"不限",没有"未设置"这档)。
    # 三个都**只影响他自己看到什么** —— 订单照样存在、照样派给别人。
    # 正因如此,抢单池必须回报"被你的偏好挡掉了几单"(见 riders.py):
    # 悄悄过滤会变成"今天怎么没单",他不会想到是自己设过一个开关
    grab_min_fee_cents: Mapped[int] = mapped_column(Integer, default=0)
    grab_same_way_only: Mapped[bool] = mapped_column(Boolean, default=False)
    grab_avoid_alcohol: Mapped[bool] = mapped_column(Boolean, default=False)
    # 骑手自设的同时接单上限(空 = 用平台默认 rider_max_active_orders)。
    #
    # **只能往下调,不能往上**:平台常数留作硬上限。理由不是不信任他 ——
    # 同时 8 单必然有人超时,而超时的赔付平台出、差评他背。
    # 但 3 单对新手会超时、对老手嫌少,这个数只影响他自己,
    # 没道理由平台替他定死一个。
    rider_max_active: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # 骑手有没有自己碰过接单半径。
    #
    # 用来区分「没设过」和「设成了不限」—— 两者的 grab_radius_km 都是
    # null,但含义相反:前者是新手还没接触过这个设置,后者是他明确要
    # 看全城。新手首次上线自动设 3 公里只对前者做,而且只做一次。
    grab_radius_touched: Mapped[bool] = mapped_column(Boolean, default=False)
    # 收工方向(#264):开着的时候,顺路的参照点从「手上单的送达点」
    # 换成这里,骑手就只看往这个方向的单。
    #
    # ⚠️ **只存到街道级**(小数点后 2 位,约 1km):对「往这个方向」
    # 这个用途足够,而更精确就等于存了骑手住哪 —— 连着看几天能推出来的
    # 东西,不该进我们的库。写入时由 round_coarse() 截断,不信任客户端。
    #
    # 开关和坐标分开:关掉之后坐标留着,下次收工不用重设。
    go_home_lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    go_home_lng: Mapped[float | None] = mapped_column(Float, nullable=True)
    go_home_on: Mapped[bool] = mapped_column(Boolean, default=False)
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
    #: 注销时刻。**非空 = 这是一行墓碑**,不是活着的账号。
    #:
    #: 在此之前,"已注销"这件事是靠 `phone` 被改成 `del{id}_{hex}` 来表达的 ——
    #: 一个标记塞在业务列里,全库只有 security.py 一处认得。于是:
    #: 邀请码还能被解析出来、`is_online` 还是 true 被算进在线骑手、
    #: 员工名单里渲染成 `del****9af0`、订单详情把它当电话号下发给对端拨号。
    #: 每一处都是"没人想到还有这种行"而不是"决定这么做"。
    #:
    #: 有了这一列,判据就只有一个:`deleted_at IS NOT NULL`。
    #: 手机号前缀那条在 security.py 里留着兜存量(修复脚本跑完即可摘)。
    #:
    #: 行本身不删:40 张表的外键指向 users.id 且**一条 ON DELETE 都没有**,
    #: 硬删会直接违反外键;而订单/账务本来就要按法律留存。
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    @property
    def is_deleted(self) -> bool:
        """已注销。手机号前缀是存量兜底,见 deleted_at 的注释。

        ⚠️ 这是 Python 侧的判断,**不能用在 where 子句里** ——
        查询要写 `User.deleted_at.is_(None)`。
        """
        return self.deleted_at is not None or self.phone.startswith("del")

    @property
    def dial_phone(self) -> str:
        """可拨的号码。已注销返回空串。

        墓碑行的 `phone` 是 `del{id}_{hex}` 哨兵,不是号码 ——
        原样下发给对端"一键拨号"的话,拨出去的是一串字母。
        """
        return "" if self.is_deleted else self.phone


class RiskCarryover(Base):
    """注销后仍要跟随的风控标记(按 手机号+角色 的不可逆假名索引)。

    ## 为什么需要它

    注销把手机号释放掉了("释放手机号,可重新注册"),而
    `after_sale_banned` / `risk_level` 留在旧行上。于是
    **注销再注册 = 风控标记清零** —— 一个自助的、零成本的、
    没有冷却时间的洗白按钮,就摆在"我的-设置"里。
    `after_sale_banned` 是"恶意售后"黑名单,这个洞直接对着钱。

    ## 为什么不是"有标记就不让注销"

    注销是应用商店上架的硬性要求(苹果 5.1.1(v)),也是个人信息保护法
    的删除权。现有的三条拒绝理由(在途订单 / 店铺资质 / 未提余额)
    都是**用户自己的未了义务或资产**,站得住;
    "平台给你打了个标记所以你不许注销"不是同一回事 ——
    尤其 frozen 的语义是"待人工复核",可能是误伤
    (风控那边的原话是"误伤优先放行"),
    把一个可能误伤的标记变成永久不能注销,比这个洞更糟。

    ## 为什么存假名不存手机号

    存明文就等于"注销了但我们还留着你的手机号",和注销页答应的
    "账号将被匿名化删除"直接冲突。存 HMAC 假名:命中判定照样做得了,
    库里没有可读的号码。裸 sha256 不行 —— 手机号空间太小,见 crypto.pseudonym。

    ## 只给带标记的账号写

    干净账号注销后**一条痕迹都不留**。这张表里有一行,
    本身就等于"这个号被处置过",所以它只该装真的被处置过的人。
    """

    __tablename__ = "risk_carryovers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    #: HMAC(手机号 + 角色),见 services/crypto.pseudonym。唯一:重复注销覆盖同一行
    phone_key: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    after_sale_banned: Mapped[bool] = mapped_column(Boolean, default=False)
    risk_level: Mapped[str] = mapped_column(String(10), default="")
    risk_note: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())


class Brand(Base):
    """品牌(连锁总部)。

    单店商家**没有**品牌 —— `Merchant.brand_id` 为空时所有既有逻辑
    走原路径,零感知。品牌层只在"一个人要管多家店"时才出现。

    刻意不做的:品牌级钱包。资金仍按门店结算,
    与「每一笔分账可查可申诉」的承诺保持一致 ——
    钱一旦在总部合并,门店就说不清自己那份对不对。
    """

    __tablename__ = "brands"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(50))
    logo_url: Mapped[str] = mapped_column(String(300), default="")
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())


class BrandMember(Base):
    """品牌成员与授权范围。

    role:
    - owner   品牌所有者:全部门店的全部权限
    - manager 区域经理:只管 shop_ids 里的店(空 = 全部门店)

    店员仍走 merchant_staff(按单店授权),不进品牌层 ——
    店员是门店雇的,不是品牌雇的。
    """

    __tablename__ = "brand_members"
    __table_args__ = (UniqueConstraint("brand_id", "user_id",
                                       name="uq_brand_member"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    brand_id: Mapped[int] = mapped_column(ForeignKey("brands.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    role: Mapped[str] = mapped_column(String(12), default="manager")
    # 授权门店范围(空列表 = 全部门店);manager 用,owner 忽略
    shop_ids: Mapped[list] = mapped_column(
        JSONB, default=list, server_default="[]")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())


class Merchant(Base):
    __tablename__ = "merchants"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # **不再 unique**:连锁品牌下一个老板名下有多家店。
    # "一个账号一家店"改由应用层守(POST /merchants 仍拒第二家) ——
    # 开分店走 /brands/me/shops,那条路径要求品牌所有者身份 + 独立证照
    owner_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    # 店铺专属短码(6 位):海报二维码与短链 /s/{code} 用。
    # 懒生成(第一次要用时才建),不暴露内部 id 规律
    short_code: Mapped[str] = mapped_column(String(8), default="", index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    address: Mapped[str] = mapped_column(String(200), default="")
    lat: Mapped[float] = mapped_column(Float)
    lng: Mapped[float] = mapped_column(Float)
    # 所在城市(入驻时逆地理解析,失败留空人工填;管理后台可改)。
    # 开城清单(platform_flags.open_cities)外的城市可入驻待审但不可营业
    city: Mapped[str] = mapped_column(String(20), default="", index=True)
    # 业态:food=餐饮外卖(默认) / hotel=酒店住宿。经营主体(钱包/提现/分账/
    # 发票/税务)按 Merchant 复用,业务数据走各自竖井(菜品 vs 房型)
    biz_type: Mapped[str] = mapped_column(
        String(10), default="food", index=True)
    # 外卖品类(白名单见 categories.py):展示归类不是资质项,商家随时可改。
    # 仅 biz_type=food 有意义;酒店档次在 hotel_profiles.tier
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
    # 自动接单:支付成功即进入制作,高峰期不用守着屏幕点(仅营业中生效)
    auto_accept: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false")

    # 食安封签:商家自述使用一次性封签(拆封即留痕)。**是自述不是认证** ——
    # 平台不上门查,所以用户端的文案也只能写"商家声明",不能写"平台认证"
    food_seal: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false")

    # 所属品牌(连锁)。**为空 = 单店商家,一切照旧** ——
    # 品牌层是加法不是改造,单店的路径一行都不用动
    brand_id: Mapped[int | None] = mapped_column(
        ForeignKey("brands.id"), nullable=True, index=True)

    # 食安停业闸门:30 天内多起食安投诉成立时置位,**商家自己开不回来**。
    # 此前自动停业只置 is_open=False,而 status 仍是 approved ——
    # 商家在店铺页把开关拨回去就继续接单,"暂停营业待人工复核"形同虚设
    food_safety_hold: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false")
    # **闸门是谁落的**:food_safety(食安投诉成立) / license_expired(证过期)。
    # 不记原因的话就会出现"因食安被停业的店,交一张新证就解封了" ——
    # 续证核验通过时我们要解的只是自己落的那道闸,不是别人的。
    hold_reason: Mapped[str] = mapped_column(
        String(20), default="", server_default="")

    # 忙碌模式:高峰压单的中间态 —— 不闭店,但把预期先说清楚。
    # busy_until 之前 ETA/出餐超时判定放宽 busy_extra_minutes,
    # 用户端展示「出餐较慢」标;到点自动失效(读取时判断,无需清扫任务)
    busy_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    busy_extra_minutes: Mapped[int] = mapped_column(
        Integer, default=10, server_default="10")

    @property
    def busy_active(self) -> bool:
        until = self.busy_until
        if until is None:
            return False
        if until.tzinfo is None:
            until = until.replace(tzinfo=timezone.utc)
        return until > datetime.now(timezone.utc)

    # 云打印机(飞鹅):绑定 SN 后支付成功自动出小票;printer_auto 商家可关
    printer_sn: Mapped[str] = mapped_column(String(32), default="")
    printer_auto: Mapped[bool] = mapped_column(Boolean, default=True)
    license_no: Mapped[str] = mapped_column(String(50), default="")  # 食品经营许可证号,入驻审核必填
    license_image_url: Mapped[str] = mapped_column(String(300), default="")  # 证照照片,监管要求留存影像

    # 证照有效期与主体一致性(#连锁调研)。
    #
    # 美团《入网餐饮服务提供者审查登记规范》把三件事列为违规:
    # 「营业执照和行业资质**主体名称不一致**」
    # 「实际经营地址与资质证照中营业地址不一致」
    # 「提交审核时过期或**合作期间未能保持持续有效**」
    #
    # 第三条是我们此前完全没管的:库里只有证号和照片,**没有到期日**。
    # 食品经营许可证一般 5 年,到期是「静默失效」—— 商家绝不会自己记得,
    # 而过期继续经营是违法的,平台放任有连带责任。
    # 第一条也是我们审核时看不到的:审核员只看到一张图,
    # 对不上"这张证是不是这家店的"。
    license_expires_at: Mapped[date | None] = mapped_column(
        Date, nullable=True)
    # 营业执照统一社会信用代码 / 注册号
    business_license_no: Mapped[str] = mapped_column(String(50), default="")
    # 证照上的主体名称(公司/个体工商户全称)。与店铺名往往不同 ——
    # 店招叫「赞小碗」,证上是「成都赞小碗餐饮管理有限公司」,
    # 这很正常;要审的是**营业执照与行业资质两张证的主体一致**
    license_subject: Mapped[str] = mapped_column(String(100), default="")
    # 到期提醒的发送水位:记已经就哪一档(30/7/1/expired)提醒过,
    # 避免清扫任务每小时跑一次就给商家轰 24 条消息
    license_notified: Mapped[list] = mapped_column(
        JSONB, default=list, server_default="[]")

    # ---- 微信特约商户进件资料(#203)----
    #
    # 进件的 API 形状取决于服务商类目(普通服务商 applyment4sub /
    # 电商平台 ecommerce/applyments),但**要商家交的材料两套是一样的**,
    # 所以数据模型先落地,不等类目答案。
    #
    # 为什么不复用 PayoutAccount:那是「平台打款给谁」(按 user 一人一户),
    # 这里是「微信把钱结给谁」(按门店,连锁每店可以不同)。两件事,
    # 而且分账上线后前者对商家就没用了。同一个银行账号存两张表迟早分叉。
    subject_type: Mapped[str] = mapped_column(
        String(12), default="")          # individual 个体工商户 / enterprise 企业
    # 营业执照照片。此前库里只有证号没有图,而进件必须传图
    business_license_image_url: Mapped[str] = mapped_column(
        String(300), default="")
    legal_person_name: Mapped[str] = mapped_column(String(50), default="")
    # 身份证号与银行账号是敏感个人信息,**一律密文落库**(services/crypto.py),
    # 接口只回尾 4 位。平台把「账目三方透明」写在首页,
    # 对用户隐私就不能反过来松
    legal_person_id_encrypted: Mapped[str] = mapped_column(
        String(300), default="")
    legal_person_id_tail: Mapped[str] = mapped_column(String(4), default="")
    legal_person_id_front_url: Mapped[str] = mapped_column(
        String(300), default="")         # 人像面,私密桶 purpose=id_card
    legal_person_id_back_url: Mapped[str] = mapped_column(
        String(300), default="")         # 国徽面
    # 超级管理员:微信给他发进件通知,签约也是他扫码。
    # 填错了商家永远收不到"该你签约了",而进件会一直卡在待签约
    admin_contact_name: Mapped[str] = mapped_column(String(50), default="")
    admin_contact_phone: Mapped[str] = mapped_column(String(20), default="")
    admin_contact_email: Mapped[str] = mapped_column(String(100), default="")
    settle_account_type: Mapped[str] = mapped_column(
        String(12), default="")          # corporate 对公 / personal 对私
    settle_account_name: Mapped[str] = mapped_column(String(80), default="")
    settle_bank_name: Mapped[str] = mapped_column(String(80), default="")
    # 开户支行:微信进件必填,而 PayoutAccount 里没有这一项
    settle_bank_branch: Mapped[str] = mapped_column(String(120), default="")
    settle_account_no_encrypted: Mapped[str] = mapped_column(
        String(300), default="")
    settle_account_tail: Mapped[str] = mapped_column(String(4), default="")
    # 进件状态。微信侧是异步的,中间有「待账户验证」「待签约」两个
    # **要商家本人操作**的环节 —— 不把状态显式画出来,
    # 商家会以为提交完就没事了,然后一直开不了通
    applyment_status: Mapped[str] = mapped_column(
        String(24), default="not_submitted", index=True)
    applyment_no: Mapped[str] = mapped_column(String(64), default="")
    applyment_reject_reason: Mapped[str] = mapped_column(String(500), default="")
    applyment_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)

    # 明厨亮灶(#155)。**不塞 JSONB** —— 列表页要按 status 展示「有/无」标识,
    # 那是法规第十三条的硬要求,得能索引能筛
    #
    # none 没装 / pending 待首帧人工核验 / active 在线 / degraded 装了但当前不可用。
    # **列表页只把 active 显示成「有明厨亮灶」** —— 看不到就是没有
    kitchen_cam_status: Mapped[str] = mapped_column(
        String(10), default="none", index=True)
    kitchen_cam_url: Mapped[str] = mapped_column(String(300), default="")
    kitchen_cam_vendor: Mapped[str] = mapped_column(String(20), default="")
    #: 商家自己拍的画面截图,首帧人工核验用(顺便查有没有拍到不该拍的,#157)
    kitchen_cam_shot_url: Mapped[str] = mapped_column(String(300), default="")
    #: 商家确认已告知后厨员工该区域对外直播(#157,个保法第二十六条的精神)
    kitchen_cam_notified: Mapped[bool] = mapped_column(Boolean, default=False)
    kitchen_cam_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    kitchen_cam_checked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    #: 降级原因(机器可读)与给商家看的人话
    kitchen_cam_reason: Mapped[str] = mapped_column(String(20), default="")
    kitchen_cam_note: Mapped[str] = mapped_column(String(200), default="")
    #: 连续失败/成功次数 —— 降级要迟钝、恢复要灵敏,见 kitchen_cam.next_status
    kitchen_cam_fail_streak: Mapped[int] = mapped_column(Integer, default=0)
    kitchen_cam_ok_streak: Mapped[int] = mapped_column(Integer, default=0)
    #: HLS media sequence,用于判断"能连上但画面停了"
    kitchen_cam_sequence: Mapped[int | None] = mapped_column(
        Integer, nullable=True)

    @property
    def kitchen_cam(self) -> bool:
        """列表页的「有/无明厨亮灶」。

        **放在模型上而不是逐个端点填** —— 法规第十三条要求的是商家列表页,
        而商家列表不止一个(首页、搜索、收藏、附近……)。逐个端点填一定会漏,
        漏掉的那个列表就是个合规缺口。挂在模型上,MerchantOut 的
        from_attributes 会自动带出去,新加的列表也天然带上。

        只认 active:pending(待核验)、degraded(掉线)都算「无」。
        """
        return self.kitchen_cam_status == "active"

    @property
    def kitchen_cam_label(self) -> str:
        return "有明厨亮灶" if self.kitchen_cam else "无明厨亮灶"

    # 堂食标识(总局令第 123 号第十二条,2026-06-01 施行):
    # 列表页和商家主页都要展示。三态 unknown 未填报 / yes 有堂食 / no 无堂食。
    #
    # **默认 unknown,不默认「有堂食」**。这是法定公示项,平台替商家猜一个
    # 填上去,就是拿平台的信用给一条没人核实过的信息背书 —— 填错比不填更糟,
    # 而"未填报"至少是句真话,用户看得出这里还没数据。
    # 不塞 JSONB 的理由同 kitchen_cam_status:列表页要按它展示,得能索引
    dine_in_status: Mapped[str] = mapped_column(
        String(10), default="unknown", server_default="unknown", index=True)

    @property
    def dine_in_label(self) -> str:
        """列表页/详情页的堂食标识文案。挂模型上的理由同 kitchen_cam:
        商家列表不止一个,逐个端点填一定会漏,漏掉的那个就是合规缺口。"""
        return {"yes": "有堂食", "no": "无堂食"}.get(
            self.dine_in_status, "未填报")

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
    # 菜单排序:小的在前(默认 0,同值按 id)。招牌放最前、饮品小食垫后
    # 是商家最常做的"装修"动作,此前只能靠改分类名硬凑
    sort: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    # 菜品描述:用户点之前想知道"这菜里有什么"。此前只有店铺介绍,
    # 单菜一个字都没有 —— 有忌口的人只能靠猜或者备注里写一长串
    description: Mapped[str] = mapped_column(
        String(200), default="", server_default="")
    # 菜品标签(白名单见 schemas.DISH_BADGES):新品/招牌/辣度等,
    # 用户端角标。**不含"平台推荐"这类** —— 那会变成竞价位
    badges: Mapped[list] = mapped_column(
        JSONB, default=list, server_default="[]")
    # 酒类标记:商家上架自助勾选(法律义务在商家,平台提供工具与拦截)。
    # 含酒订单要求用户已实名且成年(#14),小票/骑手端提示查验收件人
    is_alcohol: Mapped[bool] = mapped_column(Boolean, default=False)

    # 成本(分/份)。**只商家自己可见**:不进任何对外接口、不进开放 API、
    # 不进公开的菜单接口 —— 成本泄露出去,商家在供应商和同行面前都被动。
    # 0 = 没录过(不是"成本为零"),毛利一律不算不显示 ——
    # 猜一个成本算出来的毛利,比不显示更糟。
    cost_cents: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0")

    # 菜品级打包费(分)。None = 用店铺的 packing_fee_cents。
    # 店铺级一刀切在真实场景里两头不讨好:汤类打包盒三块、饮料根本不要盒,
    # 收一样的钱要么商家亏,要么顾客觉得被宰。
    packing_fee_cents: Mapped[int | None] = mapped_column(
        Integer, nullable=True)
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

    # 套餐:[{"dish_id":1,"quantity":2},...]。非空 = 这道"菜"是套餐,
    # 自身 price_cents 就是套餐价(天然低于单点合计,不用负价 delta ——
    # 那会打破"改价就改基础价"的既有约定)。下单时逐个子项扣库存,
    # 任一缺货整单回滚;账目上仍是一行,口径零影响
    combo_items: Mapped[list] = mapped_column(
        JSONB, default=list, server_default="[]")

    # 供应时段 "06:00-10:30"(空=全天供应,支持跨天如 22:00-02:00)。
    # 非供应时段**不从菜单里消失**,只置灰 —— 消失会让用户以为没这道菜
    serve_window: Mapped[str] = mapped_column(
        String(11), default="", server_default="")


class Order(Base):
    __tablename__ = "orders"
    # 「某个人的单,按时间倒序取前 N 条」是三端最常跑的形状。
    # 光有单列索引的话,库要把这个人的全部历史单捞出来再整个排序 ——
    # 单越多越慢,而且慢得很平滑,不盯着看发现不了。
    # **必须和 alembic/versions/0106_hot_path_indexes.py 里的一致**:
    # 那边用 CONCURRENTLY 真正建库上的索引(不锁表),这边只是让
    # autogenerate 知道它们该存在 —— 少了这几行,下次 autogenerate
    # 会兴高采烈地生成 DROP INDEX
    __table_args__ = (
        Index("ix_orders_rider_created", "rider_id",
              text("created_at DESC")),
        Index("ix_orders_merchant_created", "merchant_id",
              text("created_at DESC")),
        Index("ix_orders_customer_created", "customer_id",
              text("created_at DESC")),
    )

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
    # 配送费的构成快照 {base, night, weather, door}(分)。
    #
    # **存快照而不是事后重算**:费率会调、天气开关会关,重算出来的数
    # 和当时真正收的对不上 —— 那就不叫透明了,叫"我们现在觉得应该是多少"。
    #
    # 这份拆分给四端看:顾客(我这 8 块钱花在哪)、骑手(**接单前**就知道
    # 这单为什么值 8 块)、商家(顾客问起配送费贵时能解释)、小票。
    # 此前它只在预览接口里露过一次,下单之后就没人看得到了。
    fee_parts: Mapped[dict] = mapped_column(
        JSONB, default=dict, server_default="{}")
    #: 算这笔配送费时**用的**距离(米)与来源(#300)。
    #:
    #: 配送费一分不少全归骑手,所以这个数直接是他的收入。
    #: 算过一次就锁在订单里 —— 不能因为缓存过期、接口换了答案就变,
    #: 骑手事后要查得到「这 8 块钱按 3.4 公里算的」。
    #:
    #: source: route=腾讯骑行路网 / straight=接口不可用时的直线兜底。
    #: 两者差 19%(实测成都样本),不标出来事后无从分辨。
    bill_distance_m: Mapped[int | None] = mapped_column(
        Integer, nullable=True)
    bill_distance_source: Mapped[str] = mapped_column(
        String(10), default="", server_default="")
    #: 下单时这个地址**已知的**难度,一句话(#301)。
    #:
    #: 骑手抢单列表要在**接单前**看到「无电梯 6 楼」——
    #: 不能骑到楼下才发现。存快照而不是现查:一屏几十单,
    #: 每单查一次共识就是几十次往返(#289 踩过同一个坑)。
    hardship_note: Mapped[str] = mapped_column(
        String(200), default="", server_default="")
    # 送上门 / 送到楼下。**顾客自己选**:选了楼下就不收上门难度费,
    # 骑手也没有义务上楼(这一点写进骑手端与规则页,否则那笔钱是白收的)
    to_door: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true")
    # 小费:100% 归骑手,不计佣金基数;骑手结算行 = 配送费 + 小费
    tip_cents: Mapped[int] = mapped_column(Integer, default=0)
    # total = food + packing - discount + delivery + tip - subsidy(用户实付)
    total_cents: Mapped[int] = mapped_column(Integer)
    # 支付成功时按商家费率计算,基数是商家实收口径(food+packing-discount)
    commission_cents: Mapped[int] = mapped_column(Integer, default=0)
    address: Mapped[str] = mapped_column(String(200))
    # 楼层快照(下单当时的地址信息)。null = 顾客没填,不加时 ——
    # 猜一个出来会让 ETA 变成假承诺
    floor: Mapped[int | None] = mapped_column(Integer, nullable=True)
    has_elevator: Mapped[bool | None] = mapped_column(
        Boolean, nullable=True)
    lat: Mapped[float] = mapped_column(Float)
    lng: Mapped[float] = mapped_column(Float)
    contact_name: Mapped[str] = mapped_column(String(50), default="")
    contact_phone: Mapped[str] = mapped_column(String(20), default="")
    remark: Mapped[str] = mapped_column(String(200), default="")
    # 订单类型:food 外卖(默认)/ errand_send 帮送 / errand_buy 帮买。
    # 跑腿单**没有商家**,但 merchant_id 是 NOT NULL 且有上百处代码依赖 ——
    # 所以跑腿单挂到本城一个 biz_type='errand' 的服务主体上,
    # 取件点放在订单自己身上(外卖的取件点是那家店、固定;
    # 跑腿的是用户当场填的、每单不同)。读取件点统一走 services/errand
    order_kind: Mapped[str] = mapped_column(
        String(16), default="food", server_default="food", index=True)
    pickup_address: Mapped[str] = mapped_column(String(200), default="")
    pickup_lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    pickup_lng: Mapped[float | None] = mapped_column(Float, nullable=True)
    pickup_contact_name: Mapped[str] = mapped_column(String(50), default="")
    pickup_contact_phone: Mapped[str] = mapped_column(String(20), default="")
    #: 物品描述(帮送)/ 要买什么(帮买)
    errand_note: Mapped[str] = mapped_column(String(300), default="")
    #: 取件时拍的物品照。**丢件纠纷时唯一的事实来源** ——
    #: 东西是用户的,平台既不知道原样也不承担保价
    pickup_photo_url: Mapped[str] = mapped_column(String(300), default="")
    # 帮买:垫资由**用户预付给平台**,骑手不垫自己的钱 ——
    # 让收入最低的那个人先掏钱,是把平台的资金风险转嫁给他。
    # 实付以小票为准,小票是唯一对账依据且用户看得到
    # (代买最容易起的纠纷就是"你是不是多报了")
    goods_budget_cents: Mapped[int] = mapped_column(Integer, default=0)
    goods_actual_cents: Mapped[int | None] = mapped_column(
        Integer, nullable=True)
    goods_receipt_url: Mapped[str] = mapped_column(String(300), default="")
    #: 超出浮动上限时骑手发起的加价确认(pending/approved/rejected)
    goods_raise_status: Mapped[str] = mapped_column(String(12), default="")
    goods_raise_cents: Mapped[int | None] = mapped_column(
        Integer, nullable=True)
    # 送达段:骑手点「我到了」的时刻,以及到送达之间的停留时长。
    # 这几分钟花在找门、等门禁、等电梯、爬楼上 —— 是"场景难度"
    # 唯一可测量的部分。到店等餐时长早就在记了,送达这段一直是空白。
    # **只记录,不判罚**:一个点位慢是这个点位的事,
    # 不是那天送这一单的骑手的事
    arrived_drop_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    drop_minutes: Mapped[float | None] = mapped_column(Float, nullable=True)
    #: 聚合键快照(网格+楼层段,见 services/drop_time)。**存下来不重算** ——
    #: 网格算法一改,历史数据就全对不上了
    drop_key: Mapped[str | None] = mapped_column(
        String(40), nullable=True, index=True)
    # 追加单(加菜):关联原单,免配送费,骑手/配送随原单;原单取消则级联取消
    parent_order_no: Mapped[str] = mapped_column(String(32), default="", index=True)
    # 商家自配送(下单快照):不进抢单池、无骑手,商家操作配送三态;
    # 配送费归商家(入账行并入 food 口径),平台照常只抽餐费佣金
    self_delivery: Mapped[bool] = mapped_column(Boolean, default=False)
    # 结算口径(支付时快照):platform=平台代收代付(过渡期);
    # profit_sharing=微信服务商分账,货款直达商家账户,平台不沉淀
    settle_mode: Mapped[str] = mapped_column(String(16), default="platform")
    # 微信侧交易号(支付回调落库)。**分账接口的必传入参**,
    # 此前只有 StayOrder 有这个字段,外卖单收到回调直接把它丢了。
    #
    # 注意存量:这个字段是分账的硬前提,而补不回来 ——
    # 加字段之前已支付的订单永远分不了账。不是 bug,是迁移的既成事实
    wx_transaction_id: Mapped[str] = mapped_column(String(64), default="")
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
    # 骑手到店时刻。等餐时长 = picked_up_at − arrived_shop_at。
    #
    # **这个时间戳只记录、不判罚**。有了它之后很容易顺手加一条
    # 「等餐超 X 分钟扣商家分」—— 不做,与「不做违规积分」一致。
    # 它的作用是**让争议有据可查**:骑手申诉超时时不用自己举证,
    # 商家看自己的出餐表现时有真数,ETA 也能拿它修正。
    arrived_shop_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    # 骑手取餐时刻(此前只有状态流转事件,没有单独字段 ——
    # 从 order_events 里捞是能捞,但那张表是给审计用的,
    # 每次算等餐时长都去 join 它,索引和口径都不合适)
    picked_up_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    accepted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    # 送达/完成时刻。**这两个是法定要记录的字段,不是产品数据。**
    #
    # 《网络餐饮服务经营者落实食品安全主体责任监督管理规定》(总局令第 123 号)
    # 第十五条:平台应当如实记录并保存订单信息 —— 含食品名称、下单时间、
    # **送餐人员、送达时间**、收货地址,保存时间自交易完成之日起**不少于三年**。
    #
    # 此前只有 order_events 里的状态流转事件能推出送达时间,那不够:
    # 事件表是流水,查一单的送达时间要 join + 过滤,而且直接落库的订单
    # (清扫任务自动完成、历史数据迁移)根本没有对应事件。
    # 法定要记录的字段就该有自己的列。
    delivered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(
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
    # 楼层与电梯。**null = 没填**,不是 0 也不是"有" —— 没填时不加时,
    # 猜一个出来会让 ETA 变成假承诺。
    #
    # 爬 6 楼和 1 楼临街是两种活,用同一个 ETA 对骑手不公平,
    # 对顾客也是个不准的承诺。填了之后 ETA 会诚实一点。
    floor: Mapped[int | None] = mapped_column(Integer, nullable=True)
    has_elevator: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    # 保护模式:骑手只看到粗地址(POI/小区),门牌详情送达前不下发;
    # 深夜独居场景的安全开关(下单页 21:00-06:00 主动提示可开)
    protect: Mapped[bool] = mapped_column(Boolean, default=False)
    # 中性称呼(如"顾客"/"李女士"),骑手/商家侧替代真实姓名;空=「顾客」
    salutation: Mapped[str] = mapped_column(String(12), default="")
    #: 标签:家 / 公司 / 学校(或自定义,最多 8 字)。空 = 没打标签。
    #: 用处是让地址簿一眼可辨 —— 三个"XX路XX号"排在一起,
    #: 用户得逐字读才知道哪个是家
    tag: Mapped[str] = mapped_column(String(8), default="")
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
    """骑手实名认证。未认证不得上线接单。

    ## 门槛只有两样:姓名 + 身份证号

    逐条核过法规之后确认的口径:

    - **健康证不是法定要求。** 《网络餐饮服务食品安全监督管理办法》要求餐食封装、
      避免送餐人员直接接触食品 —— 送餐员因此不属于"直接接触入口食品的人员",
      不在预防性健康检查范围内。四川已明确取消。所以这里是**选填**,
      只在地方另有要求的城市才卡(见 riders.py 的城市判断);
    - **人脸认证不做。** 《人脸识别技术应用安全管理办法》(网信办+公安部,
      2025-06-01 施行)明写:存在其他非人脸方式能达到同等业务要求的,
      **不得将人脸识别作为唯一验证方式**;并鼓励优先用国家人口基础信息库。
      二要素核验正是那个"其他方式";
    - **身份证照片不收。** 二要素核验(姓名+证号查人口库)不需要照片,
      而照片是敏感个人影像 —— 不收就没有泄露面。字段保留只为兼容历史数据。

    ## 证号加密落库

    照 UserIdentity 的口径:Fernet 加密,明文不入库、不出任何接口。
    此前骑手侧是**明文存 18 位并直接出接口**,而用户侧早就加密了 ——
    同一个项目两套标准,这里对齐到严的那个。
    """

    __tablename__ = "rider_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    rider_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True, index=True)
    real_name: Mapped[str] = mapped_column(String(50), default="")
    #: Fernet 加密的身份证号。明文不入库不出接口
    id_no_encrypted: Mapped[str] = mapped_column(String(500), default="")
    #: 出生日期(从证号解析,用于年龄核验;比留着证号安全)
    birth_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    #: 二要素核验通过的时刻。空 = 走的是历史人工审核路径
    id_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    #: 历史字段,新流程不再写入(旧数据迁移时保留照片 URL 以备追溯)
    id_card_photo_url: Mapped[str] = mapped_column(String(300), default="")
    #: 健康证:**选填**。仅地方另有要求的城市才卡
    health_cert_photo_url: Mapped[str] = mapped_column(String(300), default="")
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


#: 退款流水的业务线。**这三个字面量只在这里定义一次** ——
#: 写入(services/wechat_pay)和核对(services/audit)各写各的字符串的话,
#: 改一处就会让另一处静默查不到数,而"查不到数"的表现是**自检全绿**。
REFUND_BIZ_FOOD = "food"        # 外卖 / 跑腿:order_id 指向 orders
REFUND_BIZ_VOUCHER = "voucher"  # 团购券:biz_id 指向 voucher_purchases
REFUND_BIZ_STAY = "stay"        # 住宿:biz_id 指向 stay_orders


class Refund(Base):
    """退款流水:每次退款(缺货部分退/整单退/售后退)一条,金额对账的凭据。
    业务表上的 refund_cents 是汇总视图,本表是逐笔明细,审计核对两者恒等。

    ## 三条业务线共用一张表

    `biz_type` + `biz_id` 是**唯一的**业务归属判据,三条线都填。
    `order_id` / `order_no` 只有外卖/跑腿行有(券和住宿是 NULL):
    留着它们不是冗余,而是因为规则 6 的冲账判据(_reversal_due_ids)
    要 join 回 orders,而外键约束也只有真外键给得了。
    副作用刚好是所有现存的 `Refund.order_id == order.id` 查询原样正确。

    分表(voucher_refunds / stay_refunds)的代价见迁移 0107 的抬头:
    Σ 恒等式、requested 挂账的全表聚合、微信 REFUND.* 回调反查,
    每加一条业务线都要再复制一遍。
    """

    __tablename__ = "refunds"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    biz_type: Mapped[str] = mapped_column(String(10))  # 见 REFUND_BIZ_*
    biz_id: Mapped[int] = mapped_column(Integer)
    order_id: Mapped[int | None] = mapped_column(
        ForeignKey("orders.id"), index=True, nullable=True)
    order_no: Mapped[str | None] = mapped_column(String(32), nullable=True)
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

    __table_args__ = (Index("ix_refunds_biz", "biz_type", "biz_id"),)


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


class AdminActionLog(Base):
    """管理员写操作留痕。

    ## 为什么必须有

    这些接口碰的是**钱和资格**:批不批一家店营业、放不放一笔提现、
    极端天气停不停运。原先每个 handler 都拿到了 `admin: User`,
    却一个都没记 —— 谁批的、什么时候批的、为什么批,事后查不到。

    只能 curl 的时候这个缺口还小(操作少、门槛高、有人盯着);
    一旦做成后台点两下就能批,它就变成一个真问题。**界面和留痕要一起上。**

    ## 为什么快照管理员手机号

    `admin_id` 是外键,但人是会离职的、账号是会改手机号的。
    留痕的意义在于**事后能还原当时发生了什么**,所以把当时的手机号
    抄一份存下来 —— 外键给你"是谁",快照给你"当时他是谁"。

    ## 为什么不做成通用中间件

    试过在中间件里拦所有 POST /admin/*,但那样只能记到路径和 body,
    记不到**业务含义**(「驳回,理由:执照过期」比
    「POST /admin/merchants/12/reject {"reason":"执照过期"}」有用得多),
    也记不到操作前的状态。所以是各 handler 显式调 `log_admin_action`。
    显式的代价是可能漏记 —— `tests/e2e_admin_audit.py` 盯着这一点。
    """

    __tablename__ = "admin_action_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    admin_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)

    #: 操作当时的管理员手机号快照。人会离职、号会变,外键答"是谁",
    #: 快照答"当时他是谁"
    admin_phone: Mapped[str] = mapped_column(String(20), default="")

    #: 动作标识,如 merchant.approve / withdrawal.paid / flag.set。
    #: 用点分而不是自由文本 —— 将来要按动作聚合(这个月批了多少家)
    action: Mapped[str] = mapped_column(String(50), index=True)

    #: 操作对象类型与主键,如 ("merchant", 12)。
    #: 分开存是为了能按对象查历史("这家店被谁动过")
    target_type: Mapped[str] = mapped_column(String(30), default="", index=True)
    target_id: Mapped[str] = mapped_column(String(40), default="", index=True)

    #: 业务细节:驳回理由、改动前后的值、批量操作的条数。
    #: **不许往里塞身份证号、银行卡号这类东西** —— 留痕是给运营复盘的,
    #: 不是第二份敏感数据副本
    detail: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
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
    tags: Mapped[list] = mapped_column(JSONB, default=list)  # 商家维度标签(白名单见 schemas)
    # 配送维度标签:只随 rider_rating,**不进商家维度** ——
    # 配送是平台的事,配送差评从结构上就不该落到商家头上
    rider_tags: Mapped[list] = mapped_column(
        JSONB, default=list, server_default="[]")
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
    # 退款时刻。**自检的时间窗要取"钱落定的那一刻"**(规则 8/9 刚为此
    # 从 created_at 改成 redeemed_at / completed_at),而退掉的券根本没核销过,
    # redeemed_at 永远是 NULL —— 没有这一列,券的有效期最长 365 天,
    # 第 31 天以后退的券一生都不会被自检看到
    refunded_at: Mapped[datetime | None] = mapped_column(
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


#: 「不是追加单」= `parent_order_no = ''`。
#:
#: **`''` 必须渲染成字面量,不能走绑定参数。** 这不是风格问题,是性能悬崖:
#:
#: `parent_order_no` 上有普通索引,而全库 99.8% 的单这一列都是 `''`
#: (追加单才有值)。写成绑定参数时,PostgreSQL 的预备语句在**第 6 次执行**
#: 起会切「通用计划」—— 通用计划按 n_distinct 估选择度,于是认定
#: `parent_order_no = $n` 很挑,一头扎进 `ix_orders_parent_order_no`,
#: 然后把整张表当过滤条件扫一遍。
#:
#: 开发库 134728 单上实测:同一条抢单池查询,前 5 次 0.32~0.61ms,
#: **第 6 次起 22~27ms**(Rows Removed by Filter: 134427)。而骑手端
#: 每 5 秒打一次这个接口 —— 连接上的预备语句一旦切过去就一直是慢的,
#: 且随订单表增长线性变差。
#:
#: 写成字面量后 Postgres 拿得到 `''` 的真实 MCV 统计,知道它命中几乎全表,
#: 转而走 `ix_orders_status`:稳定 0.31~0.65ms,不再有第 6 次的悬崖。
#: (试过加部分索引 —— 谓词里带绑定参数时 Postgres 证不出蕴含,建了也用不上;
#: 改成字面量之后规划器又更愿意走 status 索引,那个索引是多余的。)
NOT_APPEND_ORDER = Order.parent_order_no == literal("", literal_execute=True)


class OrderEvent(Base):
    """状态流转审计日志:每次变更一条,纠纷仲裁全靠它。

    **这张表永远不清理。**《网络餐饮服务食品安全监督管理办法》第十五条
    要求订单信息(含送餐人员、送达时间)自交易完成起保存不少于三年,
    见 docs/DEV-PROMPTS-20.md。auto_flow 的日志清扫刻意绕开它。
    """

    __tablename__ = "order_events"
    # 运营侧「今天有多少单到了某状态」的统计走这条(见 0106 迁移)
    __table_args__ = (
        Index("ix_order_events_status_created", "to_status", "created_at"),
    )

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


class PlatformCopy(Base):
    """可下发的说明性文案:改一句话不用发一次三端版(#122)。

    只放**说明性**文案 —— FAQ、空状态、引导语、入口标题。
    承诺类数字(「总负担 5% 封顶」「配送费 100% 归骑手」)不在这里:
    那些由服务端按真实费率配置算出来后下发,后台看得到但改不了。
    一旦承诺变成后台可填的自由文本,任何人都能把它改成「3% 封顶」
    而实际照抽 5%,承诺就退化成广告词了。
    """

    __tablename__ = "platform_copy"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # 点位 key,如 home.vacancy / faq.1.q;客户端按 key 取,取不到用本地默认值
    key: Mapped[str] = mapped_column(String(60), unique=True, index=True)
    text: Mapped[str] = mapped_column(String(1000))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class PlatformFaq(Base):
    """帮助中心问答:同上,内容可下发,客户端保留完整本地默认值兜底。"""

    __tablename__ = "platform_faq"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    audience: Mapped[str] = mapped_column(String(12), default="user", index=True)
    question: Mapped[str] = mapped_column(String(120))
    answer: Mapped[str] = mapped_column(String(1000))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


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
    """骑手食品安全培训记录。**这是法定记录,不是产品功能。**

    《网络餐饮服务经营者落实食品安全主体责任监督管理规定》(总局令第 123 号,
    2026-06-01 施行):

    > 第二十九条 网络餐饮服务经营者委托开展配送业务的……**受托方应当对配送
    > 人员进行食品安全培训、管理,培训记录保存期限不得少于二年。**

    商家把配送委托给平台,平台就是"受托方" —— 对骑手做食安培训、
    留存记录 ≥2 年是我们的法定义务(罚则见第四十四条)。

    所以:
    - **这张表的记录不随账号注销删除。** 个保法第四十七条把"法律、行政法规
      规定的保存期限未届满"列为删除义务的例外,法定保存优先;
    - `content_version` 必须记 —— 法规要的是"培训记录",
      光有分数证明不了培训了什么。内容改版后旧记录仍能说明当时培训的是哪一版。
    """

    __tablename__ = "rider_exams"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    rider_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    score: Mapped[int] = mapped_column(Integer)
    passed: Mapped[bool] = mapped_column(Boolean)
    answers: Mapped[dict] = mapped_column(JSONB, default=dict)
    #: 培训内容版本。法规要的是"培训记录",得能说明当时培训的是什么
    content_version: Mapped[str] = mapped_column(String(20), default="")
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


class MerchantApiKey(Base):
    """POS/收银系统对接的开放接口凭证(只读)。

    稍大的餐厅都用收银系统,没有拉单接口他们就要两套系统抄单。
    明文 key 只在创建那一刻返回一次,库里只存 sha256 —— 泄库不泄 key;
    prefix 存明文前几位,列表页里让商家认得出是哪把。"""

    __tablename__ = "merchant_api_keys"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    merchant_id: Mapped[int] = mapped_column(
        ForeignKey("merchants.id"), index=True)
    name: Mapped[str] = mapped_column(String(30), default="")  # 备注(如"收银台1")
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    prefix: Mapped[str] = mapped_column(String(12), default="")
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


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

class LedgerEpoch(Base):
    """账本纪元:每一次「链被重新起头」的**永久公开记录**(#2)。

    ## 为什么需要它

    见证节点的第一道防线是「我见过的锚点必须一字不差,消失也算篡改」。
    这条防线是对的,但它分不出两件事:

    - 平台偷偷改了账;
    - 平台公开地重置了链(比如清演示数据),并说明了原因。

    `LEDGER-SPEC` §4 原话是「由人来判断是公告过的重置还是真的在毁账」——
    **机器没有任何判断依据**。2026-07-28 那次重置就卡在这儿:
    节点从那天报警报到今天 9000 多次,而这一个月里没有人做过那个判断。
    结果是最坏的一种告警疲劳:唯一那个该响的警报,正因为别的原因一直响着。

    ## 它不是赦免

    有了这张表,平台**仍然改不了历史** —— 只是把「重置」从一个无法解释的
    异常,变成一条**必须署名、永久留档、节点也会盯着**的记录:

    - 每条纪元记录一旦写下就不再改动,节点各自留存;
      记录本身被改或消失,那才是真的篡改,防线照常触发;
    - `prev_tip_hash` 冻结上一纪元的链尾哈希 —— 旧链的每日锚点可以没了,
      但它最后长什么样必须留下来,任何保存过旧锚点的人都能对。
      **2026-07-28 那次没留**,所以第 1 纪元这一栏是空的;
      这条记录存在的意义,一半就是让这种事不再发生第二次。
    """

    __tablename__ = "ledger_epochs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    #: 第几纪元,从 1 开始
    epoch: Mapped[int] = mapped_column(Integer, unique=True)
    #: 本纪元第一个锚点的日子(北京时间 yyyy-MM-dd)
    started_day: Mapped[str] = mapped_column(String(10))
    #: 为什么重置。给人看的一句话,会原样展示在 /nodes 与透明中心
    reason: Mapped[str] = mapped_column(String(300), default="")
    #: 上一纪元的链尾 chain_hash;第 1 纪元或未留存时为空串
    prev_tip_hash: Mapped[str] = mapped_column(String(64), default="")
    #: 上一纪元覆盖的日期范围(留档用,便于对照"消失的是哪几天")
    prev_first_day: Mapped[str] = mapped_column(String(10), default="")
    prev_last_day: Mapped[str] = mapped_column(String(10), default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())


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


class RiderHardship(Base):
    """骑手对**这一单实际有多难送**的现场反馈(#301)。

    ## 为什么需要它

    配送费里的上门难度费取决于 `floor` / `has_elevator`,而这两个字段是
    **用户在地址簿里自己填的**:大多数人不填(那就是 0,骑手爬六层白爬),
    填了也没人核实。「要走进小区 300 米」「车进不去只能推行」
    「门禁要等保安」这些情况**根本没有字段**。

    平台不可能知道每栋楼的情况。**跑过的人知道。**

    ## 一条反馈做两件事

    1. **这一单当场补钱**,平台承担 —— 不向用户追收(会让顾客觉得被坑,
       更要命的是会让骑手不敢反馈),也不向商家追收(与商家无关);
    2. **按地址沉淀**,攒够一致反馈后转正,后来的单在下单时就按真实
       难度计价 —— 用户下单前看得到并可以改选送到楼下,
       骑手接单前也看得到,不用骑到楼下才发现是六楼没电梯。

    ## 这张表里没有的东西

    **不存对骑手的评价、不存信用分。** 沉淀的是地址的属性,不是人的行为。
    防刷靠 `(rider_id, addr_key)` 唯一约束和补贴金额上限,不靠给人打分 ——
    一旦反馈有代价,骑手就不说了,机制立刻死掉。
    """

    __tablename__ = "rider_hardships"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"))
    order_no: Mapped[str] = mapped_column(String(32), unique=True)
    rider_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    #: 地址规整键:收货点 111m 网格 + 楼层。
    #: 同一栋楼的地址写法千奇百怪,按原文攒永远攒不够
    addr_key: Mapped[str] = mapped_column(String(64), index=True)
    #: no_elevator / walk_in / no_vehicle / gate_hard / other
    kinds: Mapped[list] = mapped_column(JSONB, default=list)
    floors: Mapped[int | None] = mapped_column(Integer, nullable=True)
    walk_m: Mapped[int | None] = mapped_column(Integer, nullable=True)
    note: Mapped[str] = mapped_column(String(200), default="")
    #: 这一单实际补给骑手多少(分)
    comp_cents: Mapped[int] = mapped_column(Integer, default=0)
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


# ---------- 酒店住宿垂类(平行竖井,经营主体复用 Merchant) ----------

# 酒店档次白名单(展示归类,不自称"星级"避免虚假宣传)
HOTEL_TIERS = {
    "economy": "经济型",
    "comfort": "舒适型",
    "premium": "高档型",
    "luxury": "豪华型",
}


class CancelPolicy(str, enum.Enum):
    """取消政策(房型级,下单时快照进订单)。"""

    limited_free = "limited_free"  # 入住日 X 点前免费取消,之后扣首晚
    first_night = "first_night"    # 任何时候取消扣首晚(未支付除外)
    strict = "strict"              # 支付后不可退(可走售后协商)


class HotelProfile(Base):
    """酒店专属资料:与 Merchant 一对一,不污染餐饮字段。

    资质:Merchant.license_no/license_image_url 在 biz_type=hotel 时
    存「营业执照」;特种行业许可证(旅馆业,公安核发)在本表。
    """

    __tablename__ = "hotel_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    merchant_id: Mapped[int] = mapped_column(
        ForeignKey("merchants.id"), unique=True, index=True)
    tier: Mapped[str] = mapped_column(String(10), default="economy")  # 档次白名单 HOTEL_TIERS
    front_desk_phone: Mapped[str] = mapped_column(String(20), default="")
    checkin_from: Mapped[str] = mapped_column(String(5), default="14:00")   # 最早入住时刻
    checkout_until: Mapped[str] = mapped_column(String(5), default="12:00")  # 最晚退房时刻
    facilities: Mapped[list] = mapped_column(JSONB, default=list)  # 设施标签 ["wifi","parking",...]
    special_license_no: Mapped[str] = mapped_column(String(50), default="")     # 特种行业许可证号,入驻必填
    special_license_image_url: Mapped[str] = mapped_column(String(300), default="")
    hygiene_image_url: Mapped[str] = mapped_column(String(300), default="")  # 卫生许可证照片(选填)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())


class RoomType(Base):
    """房型:酒店的"商品"。价格与库存不在这里——在 room_calendar 按日管理。"""

    __tablename__ = "room_types"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    merchant_id: Mapped[int] = mapped_column(ForeignKey("merchants.id"), index=True)
    name: Mapped[str] = mapped_column(String(60))            # 如「高级大床房」
    bed_type: Mapped[str] = mapped_column(String(30), default="")  # 如「1.8m 大床」
    area_m2: Mapped[int] = mapped_column(Integer, default=0)       # 面积(㎡),0=未填
    max_guests: Mapped[int] = mapped_column(Integer, default=2)
    image_urls: Mapped[list] = mapped_column(JSONB, default=list)
    facilities: Mapped[list] = mapped_column(JSONB, default=list)
    cancel_policy: Mapped[CancelPolicy] = mapped_column(
        _enum_column(CancelPolicy, "cancel_policy"),
        default=CancelPolicy.limited_free)
    # limited_free 档的免费取消截止时刻(入住日当天 HH:MM);其余档忽略
    free_cancel_until: Mapped[str] = mapped_column(String(5), default="18:00")
    is_on_sale: Mapped[bool] = mapped_column(Boolean, default=True)  # 下架不删,历史订单还引用
    sort: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())


class RoomCalendar(Base):
    """房价房态日历:每晚一行是刻意设计——连住 = 区间内逐行原子扣减。

    无记录的日期视为不可售(商家未开放)。
    """

    __tablename__ = "room_calendar"
    __table_args__ = (
        UniqueConstraint("room_type_id", "date", name="uq_room_calendar_day"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    room_type_id: Mapped[int] = mapped_column(
        ForeignKey("room_types.id"), index=True)
    date: Mapped[date] = mapped_column(Date, index=True)
    price_cents: Mapped[int] = mapped_column(Integer)
    total_qty: Mapped[int] = mapped_column(Integer, default=0)
    sold_qty: Mapped[int] = mapped_column(Integer, default=0)
    closed: Mapped[bool] = mapped_column(Boolean, default=False)  # 关房:暂停售卖当晚


class StayOrder(Base):
    """住宿订单(单号前缀 S)。佣金 5% 只在离店(completed)时产生;
    取消扣款/noshow 首晚归商家且佣金为 0——"离店才收,取消分文不收"。
    """

    __tablename__ = "stay_orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_no: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    merchant_id: Mapped[int] = mapped_column(ForeignKey("merchants.id"), index=True)
    room_type_id: Mapped[int] = mapped_column(ForeignKey("room_types.id"), index=True)
    checkin_date: Mapped[date] = mapped_column(Date, index=True)
    checkout_date: Mapped[date] = mapped_column(Date, index=True)
    nights: Mapped[int] = mapped_column(Integer)
    rooms_qty: Mapped[int] = mapped_column(Integer, default=1)
    guest_name: Mapped[str] = mapped_column(String(50))
    guest_phone: Mapped[str] = mapped_column(String(20))
    arrival_note: Mapped[str] = mapped_column(String(100), default="")  # 预计到店时间段等
    # 快照:房型名与逐晚单价 [{"date":"2026-08-01","price_cents":15800},...]
    room_type_name: Mapped[str] = mapped_column(String(60), default="")
    nightly_prices: Mapped[list] = mapped_column(JSONB, default=list)
    total_cents: Mapped[int] = mapped_column(Integer)  # = sum(每晚价) × 间数
    # 佣金与商家净额:completed 时按 5% 落定;取消扣款/noshow 时 fee=0
    fee_cents: Mapped[int] = mapped_column(Integer, default=0)
    net_cents: Mapped[int] = mapped_column(Integer, default=0)
    # 取消政策快照(档位 + limited_free 的截止时刻)
    cancel_policy: Mapped[CancelPolicy] = mapped_column(
        _enum_column(CancelPolicy, "cancel_policy"))
    free_cancel_until: Mapped[str] = mapped_column(String(5), default="18:00")
    status: Mapped[StayOrderStatus] = mapped_column(
        _enum_column(StayOrderStatus, "stay_order_status"),
        default=StayOrderStatus.CREATED,
        index=True,
    )
    reject_reason: Mapped[str] = mapped_column(String(100), default="")
    # 退款金额(取消/拒单/noshow 时落定,原路退回)
    refund_cents: Mapped[int] = mapped_column(Integer, default=0)
    refund_note: Mapped[str] = mapped_column(String(200), default="")
    wx_transaction_id: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())
    paid_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    checked_in_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)


# 住宿点评一键标签白名单(客户端与校验共用)
STAY_REVIEW_TAGS = [
    "干净卫生", "位置方便", "隔音好", "性价比高", "服务热情",
    "设施陈旧", "隔音差", "卫生一般",
]


class StayReview(Base):
    """住宿点评:一单一评,只有已离店的订单能评(离店后 15 天内)。

    酒店评分 = 近 180 天点评滚动均分,点评数 <3 不出分——
    防一条差评定生死,也防刷高分。不做酒店间排名对比。
    """

    __tablename__ = "stay_reviews"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    stay_order_id: Mapped[int] = mapped_column(
        ForeignKey("stay_orders.id"), unique=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    merchant_id: Mapped[int] = mapped_column(
        ForeignKey("merchants.id"), index=True)
    rating: Mapped[int] = mapped_column(Integer)  # 1-5
    comment: Mapped[str] = mapped_column(String(500), default="")
    image_urls: Mapped[list] = mapped_column(JSONB, default=list)  # 最多 6 张
    tags: Mapped[list] = mapped_column(JSONB, default=list)  # 白名单 STAY_REVIEW_TAGS
    reply: Mapped[str] = mapped_column(String(300), default="")  # 酒店回复
    # 真匿名:展示"匿名住客",商家侧不可反查;平台后台仍可见
    is_anonymous: Mapped[bool] = mapped_column(Boolean, default=False)
    # 追评(首评后 7 天内一次;匿名评价的追评继承匿名)
    append_content: Mapped[str] = mapped_column(String(500), default="")
    append_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    append_reply: Mapped[str] = mapped_column(String(300), default="")
    hidden: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())


class StayAfterSaleKind(str, enum.Enum):
    no_room = "no_room"          # 到店无房(最恶性违约:全额退+商家违约金 30% 首晚)
    nego_refund = "nego_refund"  # 协商退(strict 档,商家同意才动钱,平台只留证)


class StayAfterSaleStatus(str, enum.Enum):
    pending = "pending"
    accepted = "accepted"
    rejected = "rejected"
    auto_accepted = "auto_accepted"  # 商家 2 小时未响应,系统按成立处理


class StayAfterSale(Base):
    """住宿售后。资金规则(⚖️ 2026-07-27 拍板,可推翻):

    到店无房成立 = 用户收 全额房费+首晚30%违约金(随退款原路退;微信联调后
    违约金部分改走转账到零钱),商家余额扣违约金(net=-penalty),平台分文不取
    也不出钱——赔付是商家违约成本,符合无补贴原则。
    协商退 = 商家填多少退多少(0~全额),不同意维持原政策。
    设施不符/卫生问题走现有客服工单;商家对判罚有异议走工单人工复核。
    """

    __tablename__ = "stay_after_sales"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    stay_order_id: Mapped[int] = mapped_column(
        ForeignKey("stay_orders.id"), index=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    merchant_id: Mapped[int] = mapped_column(
        ForeignKey("merchants.id"), index=True)
    kind: Mapped[StayAfterSaleKind] = mapped_column(
        _enum_column(StayAfterSaleKind, "stay_after_sale_kind"))
    status: Mapped[StayAfterSaleStatus] = mapped_column(
        _enum_column(StayAfterSaleStatus, "stay_after_sale_status"),
        default=StayAfterSaleStatus.pending, index=True)
    note: Mapped[str] = mapped_column(String(300), default="")           # 用户说明
    merchant_note: Mapped[str] = mapped_column(String(300), default="")  # 商家回应
    refund_cents: Mapped[int] = mapped_column(Integer, default=0)   # 成立后退款总额
    penalty_cents: Mapped[int] = mapped_column(Integer, default=0)  # 其中违约金部分
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)


class LicenseRenewal(Base):
    """续证复审:过审后的资质变更走这条通道,不走 PATCH。

    ## 为什么不让商家直接改

    通过审核的店随手改证号不重审,等于让「亮照公示」页给假证号背书;
    到期日更甚 —— 能随手改成 2099 的话,整个到期闸门就是摆设。
    所以资质字段过审后一律锁死,续证提交到这张表,人工核验后才写回。

    ## 为什么不复用"打回 pending 重审"

    打回 pending 会让店在审核期间下架。**续证的店绝大多数是正常经营的**,
    只是证到期了要换一张新的 —— 为了换证停业几天,惩罚的是守规矩的人。
    所以单开一条通道:提交期间照常营业,核验通过才替换。
    """

    __tablename__ = "license_renewals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    merchant_id: Mapped[int] = mapped_column(
        ForeignKey("merchants.id"), index=True)
    submitted_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    license_no: Mapped[str] = mapped_column(String(50), default="")
    license_image_url: Mapped[str] = mapped_column(String(300), default="")
    license_expires_at: Mapped[date | None] = mapped_column(
        Date, nullable=True)
    business_license_no: Mapped[str] = mapped_column(String(50), default="")
    license_subject: Mapped[str] = mapped_column(String(100), default="")
    # pending / approved / rejected
    status: Mapped[str] = mapped_column(
        String(10), default="pending", server_default="pending", index=True)
    reject_reason: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)


class StaffHealthCert(Base):
    """从业人员健康证台账。

    《食品安全法》第四十五条:从事接触直接入口食品工作的从业人员应当
    每年进行健康检查、取得健康证明后方可上岗。**证一年一换、到期是静默
    失效** —— 和食品经营许可证同一个毛病,只是人更多、更没人记得。

    ## 为什么记在平台而不是让商家自己管

    监管检查要看的是**记录**。商家把健康证塞在抽屉里,查的时候翻不出来
    就是没有。做成台账之后,到期前平台替他记着,检查时一屏可查。

    ## 这是别人的个人信息,不是商家的资料

    姓名 + 证件号 + 照片,主体是**员工本人**,不是商家。所以:
    - 照片走私密桶(storage.PURPOSES['health_cert'] = True);
    - 列表里证件号打码,只有编辑时本人那条才回全;
    - **绝不进「亮照公示」那个无鉴权的对外出口** —— 那个页面是给顾客看
      店铺资质的,不是公示员工个人信息的。

    ## 到期不停业

    健康证是**按人**的,一个员工的证过期,停整家店不成比例。
    所以只提醒 + 进合规档案 + admin 可见,不落闸 ——
    与「不做违规积分」的立场一致。
    """

    __tablename__ = "staff_health_certs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    merchant_id: Mapped[int] = mapped_column(
        ForeignKey("merchants.id"), index=True)
    name: Mapped[str] = mapped_column(String(30))
    # 岗位:后厨/配菜/传菜/前厅…… 自由填,不做枚举
    # (各家叫法不同,枚举只会逼商家往"其他"里塞)
    role: Mapped[str] = mapped_column(String(20), default="")
    cert_no: Mapped[str] = mapped_column(String(40), default="")
    photo_url: Mapped[str] = mapped_column(String(300), default="")
    issued_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    expires_at: Mapped[date | None] = mapped_column(
        Date, nullable=True, index=True)
    # 离职的不删除、只归档:监管查的是"当时在岗的人有没有证",
    # 删掉等于把当时的合规记录也一起删了
    archived: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())


class PurchaseRecord(Base):
    """进货查验台账(食品溯源)。

    《食品安全法》第五十三条:食品经营者采购食品应当查验供货者的许可证和
    合格证明;食品经营企业应当建立进货查验记录制度,如实记录**食品名称、
    规格、数量、生产日期或生产批号、保质期、进货日期以及供货者名称、地址、
    联系方式**,并保存相关凭证。

    保存期限(第五十条第二款):不少于产品**保质期满后六个月**;
    没有明确保质期的,不少于**二年**。

    ## 为什么值得做

    这是餐饮小商家普遍不做的一件事,而出事时它是**唯一能自证清白的东西**
    —— "这批肉是谁供的、什么时候进的、票在哪",答不上来就只能自己扛。
    做成"拍一张进货单 + 填几个字"之后,平台替他算留存到期日、
    出事时按食材名一秒反查。

    ## 平台不替商家删记录

    keep_until 只是**最短留存期**,到了只代表"法律上可以删了",
    不代表该删。所以它是算出来给人看的,没有任何自动清理任务 ——
    自动删掉商家的合规证据,风险全在他身上而收益是我们省几行存储。
    """

    __tablename__ = "purchase_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    merchant_id: Mapped[int] = mapped_column(
        ForeignKey("merchants.id"), index=True)
    # 法定必记项
    name: Mapped[str] = mapped_column(String(60), index=True)   # 食品名称
    spec: Mapped[str] = mapped_column(String(40), default="")   # 规格
    qty: Mapped[str] = mapped_column(String(30), default="")    # 数量(带单位)
    # 生产日期**或**生产批号(法条是"或者",有一个即可)
    produced_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    batch_no: Mapped[str] = mapped_column(String(40), default="")
    # 保质期:存"保质期至"而不是天数 —— 天数还要商家自己算,而且算错了
    # 留存期限也跟着错
    shelf_life_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    purchased_on: Mapped[date] = mapped_column(Date, index=True)  # 进货日期
    # 供货者三项
    supplier_name: Mapped[str] = mapped_column(String(60), default="")
    supplier_address: Mapped[str] = mapped_column(String(120), default="")
    supplier_phone: Mapped[str] = mapped_column(String(20), default="")
    # 凭证:供货者许可证 + 进货票据。都走私密桶(别人的营业执照/票据)
    supplier_license_url: Mapped[str] = mapped_column(String(300), default="")
    receipt_url: Mapped[str] = mapped_column(String(300), default="")
    note: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())


class MerchantPrinter(Base):
    """商家绑定的云打印机(飞鹅)。一家店可以挂多台。

    ## 为什么要多台

    前厅一台出顾客小票、后厨一台出备餐单,是餐饮的标配。原先只有
    Merchant.printer_sn 一个字段,后厨想要单子就只能跟前厅共用一台,
    出餐的人得跑到前台去拿。飞鹅本身一个账号就支持挂多台设备。

    ## 用途决定印什么

    **后厨那张不该印顾客的手机号和地址** —— 后厨不需要,而单子会被
    随手丢在操作台上。前厅那张要印(骑手来取要核对)。所以 purpose
    不只是个标签,它决定 build_ticket 隐藏哪几行。
    """

    __tablename__ = "merchant_printers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    merchant_id: Mapped[int] = mapped_column(
        ForeignKey("merchants.id"), index=True)
    sn: Mapped[str] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(30), default="")
    # front 前厅小票 / kitchen 后厨备餐单 / label 标签机
    purpose: Mapped[str] = mapped_column(
        String(10), default="front", server_default="front")
    # 支付成功自动出票;关掉的话只能手动补打
    auto: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true")
    # 小票开关(不做自由排版编辑器 —— 维护成本远超收益):
    # {"show_price": bool, "show_remark": bool, "big_pickup_code": bool}
    options: Mapped[dict] = mapped_column(
        JSONB, default=dict, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())


class MerchantWebhook(Base):
    """商家系统回调(收银/ERP 主动收单)。

    此前开放接口只有两个 GET,商家的收银系统只能轮询 —— 要么慢(轮询
    间隔就是延迟),要么把我们的接口打爆(为了快就 1 秒一次)。回调是
    "来单就推过去"。

    ## secret 只在创建时给一次明文

    库里存哈希。签名用的是明文,所以商家丢了只能重置 ——
    这和 API Key 是同一套做法,理由也一样:库被拖走时,
    拿到的哈希签不出有效请求。
    """

    __tablename__ = "merchant_webhooks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    merchant_id: Mapped[int] = mapped_column(
        ForeignKey("merchants.id"), index=True)
    url: Mapped[str] = mapped_column(String(300))
    secret_hash: Mapped[str] = mapped_column(String(64))
    # 订阅的事件:order.paid / order.cancelled / order.delivered ……
    events: Mapped[list] = mapped_column(JSONB, default=list)
    active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true")
    # 连续失败计数:到阈值自动停用并提示商家(一直推一个死地址,
    # 既浪费我们的连接,也让商家以为还在收单)
    fail_streak: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0")
    last_error: Mapped[str] = mapped_column(String(200), default="")
    last_ok_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())


class WebhookDelivery(Base):
    """回调投递记录(死信队列 + 商家自查"我到底收到没有")。

    只留最近一段时间的:这张表写入量和订单量同阶,不清理会变成最大的表。
    """

    __tablename__ = "webhook_deliveries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    webhook_id: Mapped[int] = mapped_column(
        ForeignKey("merchant_webhooks.id"), index=True)
    event: Mapped[str] = mapped_column(String(30))
    # 幂等 id:商家侧据此去重(我们会重试,同一件事可能到两次)
    delivery_id: Mapped[str] = mapped_column(String(36), index=True)
    order_no: Mapped[str] = mapped_column(String(32), default="")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    # pending / ok / failed(重试用尽)
    status: Mapped[str] = mapped_column(
        String(10), default="pending", server_default="pending", index=True)
    last_status_code: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str] = mapped_column(String(200), default="")
    next_retry_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True)
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())


class DishSchedule(Base):
    """菜品定时动作(一次性)。

    与 Dish.serve_window 的区别要分清:
    - **serve_window 是每天重复的供应时段**,只把菜灰掉、不改价;
    - 这张表是**一次性的定时动作**:夜宵档提价、午市套餐限时降价、
      某天到点自动上架。

    ## 过期未执行的不补跑

    服务重启或清扫任务停了一阵之后,把三天前该降的价降下来,
    商家会莫名其妙亏一笔 —— 而他早就忘了自己设过这个。
    超过 grace 还没跑的直接标 skipped 并告知,不猜他现在还想不想要。
    """

    __tablename__ = "dish_schedules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    merchant_id: Mapped[int] = mapped_column(
        ForeignKey("merchants.id"), index=True)
    dish_id: Mapped[int] = mapped_column(ForeignKey("dishes.id"), index=True)
    # price 改价 / on 上架 / off 下架
    action: Mapped[str] = mapped_column(String(10))
    price_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    run_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), index=True)
    # pending / done / skipped(过期太久没跑) / cancelled
    status: Mapped[str] = mapped_column(
        String(10), default="pending", server_default="pending", index=True)
    note: Mapped[str] = mapped_column(String(100), default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())


class CustomerNote(Base):
    """商家给顾客记的备注与口味标签。

    "302 那位不要香菜" —— 老客维护靠这个,现在只能靠记性。

    ## 只对本店可见

    这是**顾客的个人信息**,商家能记是因为他在服务这个人,不是因为他
    拥有这份数据。所以:不跨店、不进任何对外接口、不进开放 API、
    顾客换一家店就是干净的。
    """

    __tablename__ = "customer_notes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    merchant_id: Mapped[int] = mapped_column(
        ForeignKey("merchants.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    note: Mapped[str] = mapped_column(String(200), default="")
    tags: Mapped[list] = mapped_column(JSONB, default=list)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
        onupdate=func.now())


class OrderFlag(Base):
    """商家标记的异常订单(疑似职业索赔 / 恶意差评)。

    ## 只上报,不给商家拉黑顾客的权力

    这是拍板定下的口径。理由:给了拉黑权,它会变成报复工具
    (差评了就拉黑);而真正的职业索赔是**跨店行为**,只有平台看得到
    全局 —— 一个人在十家店用同样的话术要退款,单店老板永远发现不了。

    代价是商家标记完**不会立刻发生任何事**,体感是"我说了没用"。
    所以界面上必须诚实说明平台会怎么处理、多久有回音,否则不如不做。
    """

    __tablename__ = "order_flags"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    merchant_id: Mapped[int] = mapped_column(
        ForeignKey("merchants.id"), index=True)
    order_no: Mapped[str] = mapped_column(String(32), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    # claim 疑似职业索赔 / review 疑似恶意差评 / other
    kind: Mapped[str] = mapped_column(String(10), default="other")
    reason: Mapped[str] = mapped_column(String(300), default="")
    # pending 待核查 / reviewed 已核查 / dismissed 不成立
    status: Mapped[str] = mapped_column(
        String(10), default="pending", server_default="pending", index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())


class RiderAppeal(Base):
    """骑手申诉(超时/差评非我责任)。

    ## 为什么必须有

    商家早就能对差评申诉,骑手不能 —— 被判超时、收到差评时**完全没有
    说话的地方**。而超时的成因里,商家出餐慢、地址填错、顾客不接电话
    占了相当一部分,这些都不是骑手能控制的。

    ## 申诉成立之后发生什么

    **只把这一单标注为「非骑手责任」,不加回任何分数** —— 因为平台本来
    就没有骑手评分体系(不做服务分、不做违规积分)。所以申诉的价值是
    "这条记录上写着不怪我",不是换钱。界面上必须说清楚,
    否则骑手会以为申诉能拿到补偿。

    ## 证据由系统自动附上

    骑手不用自己举证:等餐时长、天气豁免、订单实际距离这些平台都有,
    提交时一并快照进 evidence。让一个在马路上跑车的人去截图收集材料,
    这个通道就等于不存在。
    """

    __tablename__ = "rider_appeals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    rider_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    order_no: Mapped[str] = mapped_column(String(32), index=True)
    # late 超时非我责任 / review 差评非我责任 / other
    kind: Mapped[str] = mapped_column(String(10), default="late")
    reason: Mapped[str] = mapped_column(String(300), default="")
    photo_url: Mapped[str] = mapped_column(String(300), default="")
    # 提交时的系统证据快照(等餐时长/天气/距离……)。**存快照不存引用**:
    # 事后重算的话,天气开关早就关了、ETA 也重估过,证据会自己变
    evidence: Mapped[dict] = mapped_column(JSONB, default=dict)
    # pending 待核 / accepted 成立(非骑手责任) / rejected 不成立
    status: Mapped[str] = mapped_column(
        String(10), default="pending", server_default="pending", index=True)
    verdict_note: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)


class RiderFeedback(Base):
    """骑手意见反馈:针对**平台本身**,不是针对某一单。

    申诉(RiderAppeal)解决的是"这一单不怪我"。但骑手对平台的意见没有
    任何出口 —— 抢单页太卡、某条提示看不懂、某条规则不合理,这些他只能
    在群里骂,平台永远听不到。

    ## 一条硬要求:必须有回音

    不回复的反馈通道等于没有,而且比没有更糟 —— 提过一次没人理,
    以后连提都懒得提了。所以平台回复时走推送 + 骑手消息中心,
    而不是让他自己回来翻。

    ## 没有"已关闭"这个状态

    关闭是平台单方面宣布这件事结束。骑手要的是回复,不是一个状态位。
    """

    __tablename__ = "rider_feedbacks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    rider_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    # bug 故障 / rule 规则不合理 / feature 想要的功能 / other
    kind: Mapped[str] = mapped_column(String(12), default="other")
    content: Mapped[str] = mapped_column(String(1000), default="")
    # open 待处理 / replied 已回复
    status: Mapped[str] = mapped_column(
        String(12), default="open", server_default="open", index=True)
    reply: Mapped[str] = mapped_column(String(1000), default="")
    replied_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())


class MiniApp(Base):
    """小程序清单:用户端下拉面板里的那排图标(#277)。

    走 Telegram Mini Apps 模式:小程序就是网页,跑在 WebView 里,
    能力靠 JS 桥给,身份靠 HMAC 签名的 initData 传(services/mini_app.py)。
    不自研 DSL 渲染引擎,不引商业容器 —— 理由在 docs/DEV-PROMPTS-31.md。

    ## allowed_origins 是安全边界,不是展示字段

    JS 桥只对这里列出的 origin 注入/应答;容器每次导航都校验,
    白名单外的链接甩给系统浏览器。改这个字段等于给页面发能力,
    第三方入驻(以后的事)审核审的就是它。

    ## sort 人工定,不做推荐算法

    面板顺序就是运营拍的顺序。不做"猜你想用",将来有第三方了
    也不做竞价位 —— 这条写在 DEV-PROMPTS-31 的"明确不做"里。
    """

    __tablename__ = "mini_apps"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(30))
    # 图标:emoji 字面量或 https 图片地址,客户端按内容渲染
    icon: Mapped[str] = mapped_column(String(200), default="")
    # 一句话副标题,面板宫格下方灰字
    tagline: Mapped[str] = mapped_column(String(60), default="")
    entry_url: Mapped[str] = mapped_column(String(500))
    # JS 桥生效的 origin 白名单,如 ["https://chaojizan.cc"]
    allowed_origins: Mapped[list] = mapped_column(JSONB, default=list)
    # 允许调用的桥能力,如 ["initData"];支付/定位/扫码等以后按需加
    perms: Mapped[list] = mapped_column(JSONB, default=list)
    # on 上架 / off 下架(表结构为第三方入驻留位,这批清单只有自家条目)
    status: Mapped[str] = mapped_column(
        String(10), default="on", server_default="on", index=True)
    sort: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


# ---------- 到店排队(团购券的配套:券解决"钱",排队解决"位") ----------


class QueueTicketStatus(str, enum.Enum):
    waiting = "waiting"                  # 排队中
    called = "called"                    # 已叫号,等人到店
    pending_restore = "pending_restore"  # 两次没到,转待恢复(到店找商家恢复)
    seated = "seated"                    # 已入座
    cancelled = "cancelled"              # 用户自己取消
    expired = "expired"                  # 当日打烊清场


# 还在队列里、占着放号名额的状态
QUEUE_LIVE_STATUSES = (
    QueueTicketStatus.waiting,
    QueueTicketStatus.called,
    QueueTicketStatus.pending_restore,
)


class QueueTableType(Base):
    """桌型:2人/4人/6人/包间**各自一条队**。

    调研美团那套时,商家侧的第一条经验就是别用「大小桌」糊弄:
    4 人桌翻台 45 分钟、6 人桌 60 分钟,混成一条队,预估等待必然是错的
    —— 而用户就是照着这个数字决定要不要等。估错了等于骗人。
    """

    __tablename__ = "queue_table_types"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    merchant_id: Mapped[int] = mapped_column(
        ForeignKey("merchants.id"), index=True)
    name: Mapped[str] = mapped_column(String(20))          # 如「4人桌」「包间」
    seats_min: Mapped[int] = mapped_column(Integer)        # 容纳人数下限
    seats_max: Mapped[int] = mapped_column(Integer)        # 容纳人数上限
    table_count: Mapped[int] = mapped_column(Integer)      # 这一档有几张桌
    turn_minutes: Mapped[int] = mapped_column(Integer, default=45)  # 预计用餐时长
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class QueueSetting(Base):
    """商家的排队设置。**注意哪些不在这里** —— 见 services/queue.py。

    叫号后多久才允许标过号、平台收不收排队的钱、买券能不能插队,
    这三样是平台规则,不给商家配。给商家配的开关只有节奏和容量。
    """

    __tablename__ = "queue_settings"

    merchant_id: Mapped[int] = mapped_column(
        ForeignKey("merchants.id"), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    # 放号上限 = 桌数 × 这个倍数。美团教程给的经验值是 3:
    # 不封顶的话队尾那些人等两小时也坐不上,取了号反而更生气
    cap_multiplier: Mapped[int] = mapped_column(Integer, default=3)
    defer_tables: Mapped[int] = mapped_column(Integer, default=3)   # 过号顺延几桌
    notify_ahead: Mapped[int] = mapped_column(Integer, default=3)   # 前方剩几桌提醒
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class QueueTicket(Base):
    """一个号。

    `sort_key` 是队列里的位置,**只有三件事能改它**:取号(排到队尾)、
    过号顺延(往后挪 N 桌)、以及什么都不改。没有任何接口能把号往前挪 ——
    「平台不卖插队权」这句话要能被证伪,首先它得在代码里真的做不到。
    """

    __tablename__ = "queue_tickets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ticket_no: Mapped[str] = mapped_column(String(24), unique=True, index=True)
    merchant_id: Mapped[int] = mapped_column(
        ForeignKey("merchants.id"), index=True)
    table_type_id: Mapped[int] = mapped_column(
        ForeignKey("queue_table_types.id"), index=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    party_size: Mapped[int] = mapped_column(Integer)
    # 按**北京时间**切日。开发机在 PDT 时本地日期比北京晚一天,
    # 用 date.today() 会让号码在下午 5 点整体串一天(账本那边踩过)
    day: Mapped[date] = mapped_column(Date, index=True)
    seq: Mapped[int] = mapped_column(Integer)          # 当日该桌型的第几号
    sort_key: Mapped[Decimal] = mapped_column(Numeric(18, 6))
    # 过号前的位置。申诉判「这次过号不成立」时还原到它。
    # **这是 sort_key 唯一一条会变小的路径,而且只能还原到这里记着的值** ——
    # 不是"平台可以把谁挪到任意位置",是"平台可以撤销一次留了痕的过号"
    pre_pass_sort_key: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 6), nullable=True)
    status: Mapped[QueueTicketStatus] = mapped_column(
        _enum_column(QueueTicketStatus, "queue_ticket_status"),
        default=QueueTicketStatus.waiting,
        index=True,
    )
    passed_count: Mapped[int] = mapped_column(Integer, default=0)
    called_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    seated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)      # 取消/清场的时刻
    # 提醒只发一次:重算队列是每次入座都在跑的,不记这个就会反复推送
    notified_ahead_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class QueueEvent(Base):
    """队列的每一次变化都留痕。

    公示上写着「平台不卖插队权、商家不能随手把谁往前挪」,这句话
    **必须能被证伪** —— 所以要有一份谁在什么时候被移到哪、谁动的手的完整记录。
    用户申诉「我被莫名其妙过号了」时,查的也是这张表。
    """

    __tablename__ = "queue_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ticket_id: Mapped[int] = mapped_column(
        ForeignKey("queue_tickets.id"), index=True)
    merchant_id: Mapped[int] = mapped_column(
        ForeignKey("merchants.id"), index=True)
    action: Mapped[str] = mapped_column(String(24))     # take/call/pass/restore/seat/cancel/expire
    actor_role: Mapped[str] = mapped_column(String(12))  # customer/merchant/system
    actor_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    detail: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )


class AgentToken(Base):
    """给 AI 助手用的**受限令牌**(MCP 接入)。

    ## 为什么不复用登录 token

    「点单」意味着一个 agent 能花用户的钱。登录 token 什么都能干 ——
    支付、退款、改地址、提现 —— 把它交给一个自动化程序,泄露的后果是
    钱直接没了。

    这个令牌**只能做只读的事,加上「创建一张待支付订单」**。付款那一下
    永远在用户自己的 App 里,由人按。所以即使它泄露:
    对方能看到你的订单、能替你创建一张待付的单(15 分钟不付自动关闭),
    **但花不掉你一分钱**。

    能力范围写在 security.AGENT_ALLOWED 里,**默认拒绝** ——
    以后新加的接口自动不对 agent 开放,不需要谁记得去加限制。

    ## 为什么要落库而不是只签 JWT

    JWT 自己吊销不了。落一行是为了两件事:用户能在设置里看到「有哪些
    助手连着我的账号」,以及能**当场吊销**其中一个。
    """

    __tablename__ = "agent_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    #: JWT 的 jti。校验时按它查这张表,查不到或已吊销一律 401
    jti: Mapped[str] = mapped_column(String(43), unique=True, index=True)
    #: 用户自己起的名字(「我的 Claude」),用来分辨吊销哪一个
    name: Mapped[str] = mapped_column(String(40), default="")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())


class ApiCall(Base):
    """开放接口的调用记录 —— 给开发者排查用。

    ## 只记「发生了什么」,不记「内容是什么」

    **没有请求体,没有响应体。** 里面是收货地址、手机号、备注里的忌口 ——
    为了让开发者好排查而把这些多存一份,是拿用户的隐私补贴开发体验。
    方法、路径、状态码、耗时,足够回答「我的集成为什么失败」这个问题;
    答不了的那部分,让开发者复现一次,比长期存着划算。

    ## 两种调用方都记

    `kind='key'` 是商家的 POS/ERP,`kind='agent'` 是用户的 AI 助手。
    记 agent 那一类不只是为了排查:用户有权知道**自己的助手做过什么** ——
    一个能替你下单的东西,你得看得见它在干嘛。

    ## 会长,所以要清

    和 push_logs 一样进 sweep_log_retention 的清理计划。
    只写不删的表迟早把备份撑爆,而这张表的价值随时间掉得很快 ——
    上个月的 429 对今天的排查没有意义。
    """

    __tablename__ = "api_calls"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    #: key = 商家 API Key;agent = 用户的 AI 助手令牌
    kind: Mapped[str] = mapped_column(String(8), index=True)
    merchant_id: Mapped[int | None] = mapped_column(Integer, nullable=True,
                                                    index=True)
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True,
                                                index=True)
    method: Mapped[str] = mapped_column(String(8))
    path: Mapped[str] = mapped_column(String(200))
    status: Mapped[int] = mapped_column(Integer, index=True)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
