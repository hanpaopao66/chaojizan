import logging
import secrets

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func as sa_func
from sqlalchemy import select
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
from ..ratelimit import check_rate_limit
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


@router.post("/register", response_model=TokenOut)
async def register(payload: RegisterIn, db: AsyncSession = Depends(get_db)):
    existing = await db.scalar(select(User).where(User.phone == payload.phone))
    if existing:
        raise HTTPException(409, "手机号已注册")
    user = User(
        phone=payload.phone,
        password_hash=hash_password(payload.password),
        name=payload.name or payload.phone[-4:],
        role=UserRole(payload.role),
    )
    db.add(user)
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
    user = await db.scalar(select(User).where(User.phone == payload.phone))
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(401, "手机号或密码错误")
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
@router.post("/sms-code")
async def send_sms_code(payload: SmsCodeIn):
    """发验证码。60 秒防重发,验证码 5 分钟有效。

    短信服务未配置时进入开发模式:验证码直接随响应返回(dev_code),
    客户端自动填入 —— 上线前配好腾讯云短信后此字段自动消失。
    """
    await check_rate_limit("sms", payload.phone,
                           settings.rate_limit_sms_per_minute)
    redis = get_redis()
    if not await redis.set(f"sms:cd:{payload.phone}", 1, ex=60, nx=True):
        raise HTTPException(429, "发送太频繁,请 60 秒后再试")
    code = f"{secrets.randbelow(1000000):06d}"
    await redis.set(f"sms:code:{payload.phone}", code, ex=300)

    if await send_verification_code(payload.phone, code):
        return {"sent": True}
    logger.warning("短信服务未配置,开发模式返回验证码 %s -> %s", payload.phone, code)
    return {"sent": False, "dev_code": code}


@router.post("/sms-login", response_model=TokenOut)
async def sms_login(payload: SmsLoginIn, db: AsyncSession = Depends(get_db)):
    """验证码登录;新手机号自动注册为用户(customer)。"""
    redis = get_redis()
    stored = await redis.get(f"sms:code:{payload.phone}")
    if stored is None or stored != payload.code:
        raise HTTPException(401, "验证码错误或已过期")
    await redis.delete(f"sms:code:{payload.phone}")

    user = await db.scalar(select(User).where(User.phone == payload.phone))
    if user is None:
        user = User(
            phone=payload.phone,
            name=f"用户{payload.phone[-4:]}",
            role=UserRole.customer,
            device_id=payload.device_id,
            # 验证码登录的账号没有密码,置为随机串(不可能被密码登录命中)
            password_hash=hash_password(secrets.token_hex(16)),
        )
        db.add(user)
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

    # 隐私政策承诺"使用行为记录注销即删",这里兑现;实名数据一并删除
    from sqlalchemy import delete as sa_delete

    from ..models import AppEvent, UserIdentity

    await db.execute(sa_delete(AppEvent).where(AppEvent.user_id == user.id))
    await db.execute(
        sa_delete(UserIdentity).where(UserIdentity.user_id == user.id))
    user.phone = f"del{user.id}_{secrets.token_hex(3)}"  # 释放手机号,可重新注册
    user.name = "已注销用户"
    user.avatar_url = ""
    user.password_hash = hash_password(secrets.token_hex(16))
    await db.commit()
    logger.info("账号已注销并匿名化: user_id=%s", user.id)
    return {"deleted": True}


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
