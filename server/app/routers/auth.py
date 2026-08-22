import logging
import secrets

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func as sa_func
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..db import get_db
from ..models import (
    EarningKind,
    Merchant,
    Order,
    RiderEarning,
    User,
    UserRole,
    Withdrawal,
    WithdrawalStatus,
)
from ..ratelimit import check_rate_limit, client_ip
from ..redis_client import get_redis
from ..state_machine import OrderStatus
from ..schemas import (
    IdentityIn,
    IdentityOut,
    LoginIn,
    MeOut,
    MePatch,
    RegisterIn,
    SmsCodeIn,
    SmsLoginIn,
    TokenOut,
)
from ..security import create_token, get_current_user, hash_password, verify_password
from ..services.sms import send_verification_code

logger = logging.getLogger("superz.auth")

router = APIRouter(prefix="/auth", tags=["认证"])

#: 同一手机号验证码连错的次数(见 sms_login)。按手机号而不是按角色计,
#: role 是请求方指定的,分桶等于白送攻击者几倍的额度
SMS_FAIL_KEY = "sms:fail:{phone}"


@router.post("/register", response_model=TokenOut)
async def register(payload: RegisterIn, db: AsyncSession = Depends(get_db)):
    # 账号按 (手机号, 角色) 区分:同一手机号可分别注册用户/商家/骑手
    existing = await db.scalar(select(User).where(
        User.phone == payload.phone, User.role == UserRole(payload.role)))
    if existing:
        raise HTTPException(409, "该手机号已注册过此角色的账号")
    user = User(
        phone=payload.phone,
        password_hash=hash_password(payload.password),
        name=payload.name or payload.phone[-4:],
        role=UserRole(payload.role),
    )
    db.add(user)
    # 这个号上次注销时带着风控标记的话,贴回来(注销不是洗白按钮)
    await apply_risk_carryover(db, user)
    await db.commit()
    if user.role == UserRole.customer:
        from ..services.coupons import issue_newcomer
        await issue_newcomer(db, user)  # 新客券,失败不影响注册
    await db.refresh(user)
    return TokenOut(token=create_token(user), user_id=user.id, role=user.role.value, name=user.name)


@router.post("/login", response_model=TokenOut)
async def login(payload: LoginIn, db: AsyncSession = Depends(get_db)):
    await check_rate_limit("login", payload.phone,
                           settings.rate_limit_login_per_minute)
    stmt = select(User).where(User.phone == payload.phone)
    if payload.role:
        stmt = stmt.where(User.role == UserRole(payload.role))
    candidates = (await db.scalars(stmt)).all()
    # 同一手机号可能有多角色账号(未传 role 时逐个验密,密码不同则无歧义)
    user = next((u for u in candidates
                 if verify_password(payload.password, u.password_hash)), None)
    if user is None:
        raise HTTPException(401, "手机号或密码错误")
    if user.role == UserRole.admin and not settings.admin_password_login:
        raise HTTPException(403, "管理员请使用手机验证码登录")
    if payload.device_id and user.device_id != payload.device_id:
        user.device_id = payload.device_id  # 风控:记录最近登录设备
        await db.commit()
    return TokenOut(token=create_token(user), user_id=user.id, role=user.role.value, name=user.name)


@router.post("/refresh", response_model=TokenOut)
async def refresh(user: User = Depends(get_current_user)):
    """滑动续期:持有效 token 即可换新 token(过期时间重新计算)。

    商家端接单机长期挂机,客户端在 token 过半龄时静默调用本接口,
    既允许把过期时间收紧到 7 天,又不会让挂机设备掉线。
    """
    return TokenOut(token=create_token(user), user_id=user.id,
                    role=user.role.value, name=user.name)


# ---------- 短信验证码登录(用户端主登录方式) ----------
# 取真实来源 IP 的逻辑提到了 ratelimit.client_ip:screen/transparency 那边
# 原先自己读 request.client.host(拿到的是 nginx 容器地址),
# 与其在那儿抄第二份,不如让两边共用同一个 —— 抄第二份的下场就是
# 其中一份修好了另一份还错着,而且没人知道有两份
_client_ip = client_ip


@router.get("/slider")
async def slider_challenge():
    """滑块验证挑战:返回一次性票据与目标位置(0-100)。

    同号当日第 3 条短信起要求过滑块——轻量减速带,不引第三方。
    """
    ticket = secrets.token_hex(16)
    target = 20 + secrets.randbelow(61)  # 20-80,避开两端
    await get_redis().set(f"slider:{ticket}", target, ex=120)
    return {"ticket": ticket, "target": target}


@router.post("/sms-code")
async def send_sms_code(payload: SmsCodeIn, request: Request):
    """发验证码。60 秒防重发,验证码 5 分钟有效。

    防滥发(登录成功即清计数,长登录态本身就是最大的省短信手段):
    同号每日 8 条、同 IP 每日 20 条;同号第 3 条起要求滑块(409 captcha_required)。
    短信服务未配置时进入开发模式:验证码直接随响应返回(dev_code)。
    """
    await check_rate_limit("sms", payload.phone,
                           settings.rate_limit_sms_per_minute)

    # 应用商店审核白名单:不真发短信、不占频控;固定码在 sms-login 校验。
    # 响应与正常发送一致,不向外泄露白名单存在
    if settings.sms_review_code(payload.phone) is not None:
        logger.info("审核白名单账号请求验证码: %s", payload.phone)
        return {"sent": True}

    redis = get_redis()

    day_phone = f"sms:day:p:{payload.phone}"
    day_ip = f"sms:day:ip:{_client_ip(request)}"
    phone_count = int(await redis.get(day_phone) or 0)
    ip_count = int(await redis.get(day_ip) or 0)
    if phone_count >= 8:
        raise HTTPException(429, "该手机号今日验证码已达上限,请明天再试")
    if ip_count >= settings.sms_daily_ip_limit:
        raise HTTPException(429, "当前网络今日验证码请求过多,请明天再试")
    if phone_count >= 2:  # 第 3 条起要求滑块
        stored = await redis.get(f"slider:{payload.ticket}") if payload.ticket else None
        if stored is None or payload.slide is None \
                or abs(int(stored) - payload.slide) > 4:
            raise HTTPException(409, "captcha_required")
        await redis.delete(f"slider:{payload.ticket}")  # 一次性

    if not await redis.set(f"sms:cd:{payload.phone}", 1, ex=60, nx=True):
        raise HTTPException(429, "发送太频繁,请 60 秒后再试")
    # 计数在冷却检查后再加,连点不重复计
    for key in (day_phone, day_ip):
        if await redis.incr(key) == 1:
            await redis.expire(key, 86400)
    code = f"{secrets.randbelow(1000000):06d}"
    await redis.set(f"sms:code:{payload.phone}", code, ex=300)
    # 新码 = 新的错码预算。不清的话,上一串码试错到锁定的人重新发码后
    # 再手滑一次就又被锁死;而"多发一条码"本身有 60 秒冷却 + 每日 8 条
    # + 第 3 条起滑块顶着,不构成绕过
    await redis.delete(SMS_FAIL_KEY.format(phone=payload.phone))

    if await send_verification_code(payload.phone, code):
        return {"sent": True}
    logger.warning("短信服务未配置,开发模式返回验证码 %s -> %s", payload.phone, code)
    return {"sent": False, "dev_code": code}


def review_code_ok(phone: str, code: str, role: str) -> bool:
    """应用商店审核白名单的固定码是否成立(只豁免验证码,其余流程完全一致)。

    **admin 一律不适用。** 这个分支只看手机号和固定码,而 role 是请求方
    随便填的 —— 一个写死在配置里、永不过期的六位码配上一个已经存在的
    管理员账号,就是一条直通管理后台的路。审核账号只需要三端能进,
    把 admin 排除掉成本为零。
    """
    if role == "admin":
        return False
    expected = settings.sms_review_code(phone)
    return expected is not None and secrets.compare_digest(code, expected)


@router.post("/sms-login", response_model=TokenOut)
async def sms_login(payload: SmsLoginIn, db: AsyncSession = Depends(get_db)):
    """验证码登录;新手机号自动注册为用户(customer)。

    ## 频控:限速 + 作废,两条一起才挡得住爆破

    密码登录(/login)和发码(/sms-code)都有 check_rate_limit,这里原先
    一条都没有 —— 实测连打 25 次错误验证码,25 次全是 401。6 位码、
    TTL 300 秒,一个人守着一个手机号慢慢试就能进,而 role 由请求方指定,
    受害者是商家号还是已存在的 admin 都由攻击者挑。

    所以两条一起上:同号每分钟 N 次(与密码登录同一口径),
    **外加同一串码连错 M 次直接作废它** —— 只限速的话 300 秒的有效期里
    还剩几十次机会,而正常人手滑不会超过两三次。
    锁定按**手机号**算不按角色分桶:换个 role 接着打是同一个洞。
    """
    await check_rate_limit("sms_login", payload.phone,
                           settings.rate_limit_sms_login_per_minute)
    if review_code_ok(payload.phone, payload.code, payload.role):
        logger.info("审核白名单账号登录: %s role=%s", payload.phone, payload.role)
    else:
        redis = get_redis()
        fail_key = SMS_FAIL_KEY.format(phone=payload.phone)
        stored = await redis.get(f"sms:code:{payload.phone}")
        if stored is None or stored != payload.code:
            wrong = await redis.incr(fail_key)
            if wrong == 1:
                await redis.expire(fail_key, 300)  # 与验证码同寿命
            if wrong >= settings.sms_login_max_wrong:
                # 作废这一串码:光 429 的话等窗口翻转就能接着试同一个码
                await redis.delete(f"sms:code:{payload.phone}")
                logger.warning("验证码连错 %d 次,已作废该号当前验证码: %s",
                               wrong, payload.phone)
                raise HTTPException(429, "验证码错误次数过多,请重新获取验证码")
            raise HTTPException(401, "验证码错误或已过期")
        await redis.delete(f"sms:code:{payload.phone}")
        await redis.delete(fail_key)
        await redis.delete(f"sms:day:p:{payload.phone}")  # 登录成功,清当日频控

    # 按 (手机号, 角色) 找账号:同一手机号在三端各有独立账号,首登该端自动注册
    role = UserRole(payload.role)
    user = await db.scalar(select(User).where(
        User.phone == payload.phone, User.role == role))
    if user is None and role == UserRole.admin:
        # 管理员绝不自动注册:验证码对了也不行,得先有管理员账号
        raise HTTPException(403, "该手机号不是管理员")
    if user is None:
        prefix = {"customer": "用户", "merchant": "商家", "rider": "骑手"}[payload.role]
        user = User(
            phone=payload.phone,
            name=f"{prefix}{payload.phone[-4:]}",
            role=role,
            device_id=payload.device_id,
            # 验证码登录的账号没有密码,置为随机串(不可能被密码登录命中)
            password_hash=hash_password(secrets.token_hex(16)),
        )
        db.add(user)
        # 与 /register 同一条口径:注销前的风控标记跟着手机号回来
        await apply_risk_carryover(db, user)
        await db.commit()
        await db.refresh(user)
        from ..services.coupons import issue_newcomer
        await issue_newcomer(db, user)  # 新客券,失败不影响注册
    elif payload.device_id and user.device_id != payload.device_id:
        user.device_id = payload.device_id
        await db.commit()
    return TokenOut(token=create_token(user), user_id=user.id, role=user.role.value, name=user.name)


_ACTIVE_STATUSES = (
    OrderStatus.PENDING_PAYMENT, OrderStatus.PAID, OrderStatus.ACCEPTED,
    OrderStatus.READY, OrderStatus.PICKED_UP, OrderStatus.DELIVERED,
)


@router.delete("/me")
async def delete_account(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """账号注销(应用商店上架硬性要求)。

    软删除:手机号/昵称/头像匿名化,交易与账务记录按法律要求保留。
    有未完结事项(在途订单/店铺/未提余额)时拒绝,引导先处理——
    防止注销被用来逃避在途责任。
    """
    active = await db.scalar(
        select(sa_func.count(Order.id)).where(
            (Order.customer_id == user.id) | (Order.rider_id == user.id),
            Order.status.in_(_ACTIVE_STATUSES),
        )
    )
    if active:
        raise HTTPException(409, f"还有 {active} 笔进行中的订单,完结后才能注销")
    if user.role == UserRole.merchant:
        shop = await db.scalar(select(Merchant).where(Merchant.owner_id == user.id))
        if shop is not None:
            raise HTTPException(409, "商家账号注销涉及店铺资质与结算,请通过客服工单办理")
    if user.role == UserRole.rider:
        earned = await db.scalar(
            select(sa_func.coalesce(sa_func.sum(RiderEarning.amount_cents), 0))
            .where(RiderEarning.rider_id == user.id,
                   RiderEarning.kind == EarningKind.earning)
        )
        out = await db.scalar(
            select(sa_func.coalesce(sa_func.sum(Withdrawal.amount_cents), 0))
            .where(Withdrawal.user_id == user.id,
                   Withdrawal.role == "rider",
                   Withdrawal.status.notin_(
                       [WithdrawalStatus.rejected, WithdrawalStatus.failed]))
        )
        if earned - out > 0:
            raise HTTPException(409, f"钱包还有 ¥{(earned - out) / 100:.2f} 未提现,提现到账后才能注销")

    # 未核销的团购券:**自动全额退款**,不是作废(#33 第 5 节,已拍板)。
    #
    # 注销页此前写着「团购券将全部作废」,而代码一张没动 —— 两头都不对:
    # 已付款未核销的券**是用户的钱**(券款在核销前不属于商家,平台也没收
    # 服务费),作废等于注销一次没收一次;而文案说了作废、代码又没作废,
    # 用户看到的和发生的也不是一回事。
    #
    # 走和用户自己点退款完全相同的那条路(request_voucher_refund + 落
    # refunds 流水 + 回补库存):**只改状态不推钱**的写法在模拟支付期
    # 歪打正着地自洽,真开微信那天就变成「收了钱、标记已退款、钱没退」。
    refunded_vouchers = 0
    if user.role == UserRole.customer:
        from ..models import Voucher, VoucherPurchase, VoucherPurchaseStatus
        from ..services.wechat_pay import request_voucher_refund

        unused = (await db.scalars(
            select(VoucherPurchase)
            .where(VoucherPurchase.customer_id == user.id,
                   VoucherPurchase.status == VoucherPurchaseStatus.paid)
            .with_for_update())).all()
        for pur in unused:
            note = "账号注销,未核销券全额退款"
            await request_voucher_refund(db, pur, pur.sell_price_cents, note)
            pur.status = VoucherPurchaseStatus.refunded
            pur.refund_note = note
            # 自检规则 14 的时间窗按"钱落定那一刻"取,退掉的券没有 redeemed_at
            pur.refunded_at = sa_func.now()
            await db.execute(
                update(Voucher).where(Voucher.id == pur.voucher_id)
                .values(total_count=Voucher.total_count + 1,
                        sold_count=Voucher.sold_count - 1))
            refunded_vouchers += 1

    # 隐私政策承诺"使用行为记录注销即删",这里兑现;实名数据一并删除
    from sqlalchemy import delete as sa_delete

    from ..models import Address, AppEvent, MerchantStaff, RiderProfile, UserIdentity

    await db.execute(sa_delete(AppEvent).where(AppEvent.user_id == user.id))
    await db.execute(
        sa_delete(UserIdentity).where(UserIdentity.user_id == user.id))
    # 骑手实名:注销页原话是"实名信息一并删除",而在此之前
    # rider_profiles 的 real_name / id_no_encrypted / 紧急联系人
    # **一个字都没删** —— 用户侧(UserIdentity)删了,骑手侧没删,
    # 同一句承诺两套做法。整行删掉,与 UserIdentity 对齐:
    # 这张表除了 users.id 没有别的外键指过来,删掉不牵连任何账务。
    await db.execute(
        sa_delete(RiderProfile).where(RiderProfile.rider_id == user.id))
    # 地址簿:联系人姓名 + 电话 + 门牌 + 经纬度,是全库最贴身的一张表。
    # 订单自带地址快照(orders.address / contact_phone),删地址簿不影响
    # 任何历史订单的可读性与对账。
    await db.execute(sa_delete(Address).where(Address.user_id == user.id))
    # 店员名单:人都注销了还挂在名单上,店主看到的是 `del****9af0`。
    # 店主本人有店时上面已经 409 拒了,能走到这里的必然是店员或普通账号。
    await db.execute(
        sa_delete(MerchantStaff).where(MerchantStaff.user_id == user.id))

    # 风控标记跟着「手机号+角色」的假名走,不跟着这一行走。
    # 手机号马上就要被释放,标记留在旧行上等于自助洗白,见 RiskCarryover。
    await _park_risk_marks(db, user)

    user.deleted_at = sa_func.now()      # ← 唯一的墓碑判据
    user.phone = f"del{user.id}_{secrets.token_hex(3)}"  # 释放手机号,可重新注册
    user.name = "已注销用户"
    user.avatar_url = ""
    user.password_hash = hash_password(secrets.token_hex(16))
    # 下面这几列不清的话,墓碑行会继续参与业务:
    user.ref_code = None          # 邀请码还能被解析出来,继续给已注销账号发券
    user.is_online = False        # 8 处在线骑手查询会把它算进去(含派单广播)
    user.birthday = ""            # 生日券任务按 birthday 扫全表,与推送开关无关
    user.marketing_push = False
    user.go_home_lat = None       # 收工方向 = 街道级的住处,属于"使用行为记录"
    user.go_home_lng = None
    user.go_home_on = False
    # device_id **保留**:它不是账号资料,是这台设备的风控指纹。
    # 清掉等于让"注销→再注册"绕过同设备多账号判定(见 services/coupons.py
    # 的 _device_has_other_account 与 services/risk.py 的 multi_account_device)。
    await db.commit()
    logger.info("账号已注销并匿名化: user_id=%s 退券=%s",
                user.id, refunded_vouchers)
    return {"deleted": True, "refunded_vouchers": refunded_vouchers}


async def _park_risk_marks(db: AsyncSession, user: User) -> None:
    """把风控标记寄存到 risk_carryovers,按 HMAC(手机号+角色) 索引。

    没有标记的账号一行都不写 —— 这张表里有一行本身就是个结论。
    """
    if not (user.after_sale_banned or user.risk_level):
        return
    from ..models import RiskCarryover
    from ..services.crypto import pseudonym

    key = pseudonym(user.phone, user.role.value)
    row = await db.scalar(
        select(RiskCarryover).where(RiskCarryover.phone_key == key))
    if row is None:
        row = RiskCarryover(phone_key=key)
        db.add(row)
    row.after_sale_banned = user.after_sale_banned
    row.risk_level = user.risk_level
    row.risk_note = user.risk_note
    logger.info("风控标记已寄存(注销): user_id=%s banned=%s level=%s",
                user.id, user.after_sale_banned, user.risk_level or "-")
    # 寄存完就从墓碑行上抹掉,让不变式干净:
    # **墓碑行不带任何活的风控状态**,状态只在 risk_carryovers 里。
    #
    # 这不是为了好看 —— 数据修复脚本靠"墓碑行还带着标记"来报
    # 「这个人可能已经洗白过了,请人工核对」。新注销的行如果也留着标记,
    # 那份名单每天都在长,几轮之后就没人看了,而它本来是要人看的。
    # 处置的审计留痕在 risk_action_log,那张表一个字不动。
    user.after_sale_banned = False
    user.risk_level = ""
    user.risk_note = ""


async def apply_risk_carryover(db: AsyncSession, user: User) -> None:
    """注册钩子:这个手机号+角色上次注销时带着风控标记,贴回来。

    不 commit,随调用方的事务走。命中即消费掉那一行(标记已经落到
    新账号上,再留着就会在下一次注销时被重复读)。
    """
    from ..models import RiskCarryover
    from ..services.crypto import pseudonym

    key = pseudonym(user.phone, user.role.value)
    row = await db.scalar(
        select(RiskCarryover).where(RiskCarryover.phone_key == key))
    if row is None:
        return
    user.after_sale_banned = row.after_sale_banned
    user.risk_level = row.risk_level
    # note 跟着 level 走(与 admin 那边 `reason if level else ""` 同一条不变式)。
    # 有 level 就必须有可见的原因:用户可见、可申诉是 risk_level 的既定口径,
    # 不能让人看到一个凭空出现的"限制"
    user.risk_note = (
        f"{(row.risk_note or '')[:180]}(注销前的处置,可申诉)"[:200]
        if row.risk_level else "")
    await db.delete(row)
    logger.info("风控标记已跟随到新账号: user_id=%s banned=%s level=%s",
                user.id, user.after_sale_banned, user.risk_level or "-")


# ---------- 用户实名认证(按需触发,不是注册门槛) ----------

def _mask_name(name: str) -> str:
    """姓名打码:留姓,其余打星(王小明 → 王**)。"""
    return name[0] + "*" * (len(name) - 1) if name else ""


@router.post("/verify-identity", response_model=IdentityOut)
async def verify_identity(
    payload: IdentityIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """实名认证:姓名+身份证号。只有购买受限品类(酒类)时才要求做,
    做一次全程有效。证号 Fernet 加密落库,明文不入库、不出任何接口。
    """
    from ..models import UserIdentity
    from ..services.crypto import encrypt
    from ..services.idcheck import is_adult, validate_id_no, verify_two_elements

    existing = await db.scalar(
        select(UserIdentity).where(UserIdentity.user_id == user.id))
    if existing:
        raise HTTPException(409, "已完成实名认证,如需修改请联系平台客服")
    real_name = payload.real_name.strip()
    birth, err = validate_id_no(payload.id_no)
    if err:
        raise HTTPException(422, err)
    try:
        matched = await verify_two_elements(real_name, payload.id_no.strip().upper())
    except RuntimeError:
        raise HTTPException(503, "实名核验服务暂时不可用,请稍后再试")
    if not matched:
        raise HTTPException(422, "姓名与身份证号不一致,请核对后重试")
    db.add(UserIdentity(
        user_id=user.id,
        real_name=real_name,
        id_no_encrypted=encrypt(payload.id_no.strip().upper()),
        birth_date=birth,
    ))
    await db.commit()
    logger.info("用户实名认证完成: user_id=%s", user.id)
    return IdentityOut(verified=True, is_adult=is_adult(birth),
                       real_name=_mask_name(real_name))


@router.get("/identity-status", response_model=IdentityOut)
async def identity_status(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from ..models import UserIdentity
    from ..services.idcheck import is_adult

    identity = await db.scalar(
        select(UserIdentity).where(UserIdentity.user_id == user.id))
    if identity is None:
        return IdentityOut(verified=False)
    return IdentityOut(verified=True, is_adult=is_adult(identity.birth_date),
                       real_name=_mask_name(identity.real_name))


# ---------- 个人资料 ----------
@router.get("/me", response_model=MeOut)
async def me(user: User = Depends(get_current_user)):
    return MeOut(id=user.id, phone=user.phone, name=user.name,
                 role=user.role.value, avatar_url=user.avatar_url,
                 birthday=user.birthday, marketing_push=user.marketing_push,
                 risk_level=user.risk_level, risk_note=user.risk_note)


@router.patch("/me", response_model=MeOut)
async def update_me(
    payload: MePatch,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """改昵称/头像(手机号和角色不可自改)。"""
    from ..services.moderation import guard_text, submit_images
    if payload.name is not None:
        await guard_text(db, payload.name, "昵称")
        user.name = payload.name.strip()
    if payload.avatar_url is not None:
        if payload.avatar_url and payload.avatar_url != user.avatar_url:
            await submit_images(db, "avatar", user.id, [payload.avatar_url])
        user.avatar_url = payload.avatar_url
    if payload.birthday is not None:
        user.birthday = payload.birthday
    if payload.marketing_push is not None:
        user.marketing_push = payload.marketing_push
    await db.commit()
    await db.refresh(user)
    return MeOut(id=user.id, phone=user.phone, name=user.name,
                 role=user.role.value, avatar_url=user.avatar_url,
                 birthday=user.birthday, marketing_push=user.marketing_push)
