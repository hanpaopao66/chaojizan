import time

import bcrypt
import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import settings
from .db import get_db
from .models import User

bearer = HTTPBearer(auto_error=False)


def hash_password(raw: str) -> str:
    return bcrypt.hashpw(raw.encode(), bcrypt.gensalt()).decode()


def verify_password(raw: str, hashed: str) -> bool:
    return bcrypt.checkpw(raw.encode(), hashed.encode())


def create_token(user: User) -> str:
    payload = {
        "sub": str(user.id),
        "role": user.role.value,
        "exp": int(time.time()) + settings.jwt_expire_minutes * 60,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


#: AI 助手令牌**唯一**能碰的接口。(方法, 路径正则) —— **全匹配**。
#:
#: ## 为什么是白名单,而且是全匹配的正则
#:
#: 黑名单要求每加一个新接口就有人记得去禁它,忘一次就是一条没人看守的路。
#: 白名单反过来:新接口默认不开放,要开是一个显式动作。
#:
#: 而白名单本身也不能用前缀匹配 —— 第一版写的是「GET /merchants 前缀下
#: 子路径一律放行」,单测当场抓出 `GET /merchants/me/order-flags` 被放行:
#: `/merchants/me/*` 是**商家自己的经营数据**(还包括 finance/statement.csv),
#: 一个用来点外卖的助手不该能读它。前缀一松,松掉的地方自己长出来。
#:
#: ## 为什么没有支付
#:
#: 「点单」意味着 agent 能花用户的钱。这里给到「创建一张待支付订单」为止,
#: 付款那一下永远在用户自己的 App 里由人按 —— 即使令牌泄露,
#: 对方能替你创建一张 15 分钟后自动关闭的待付单,**但花不掉一分钱**。
#:
#: 同理没有:退款、改地址、申诉、地址簿写入、钱包与提现。
AGENT_ALLOWED: tuple[tuple[str, str], ...] = (
    ("GET", r"/auth/me"),
    ("GET", r"/merchants"),                  # 附近的店
    ("GET", r"/merchants/search"),
    ("GET", r"/merchants/\d+"),              # 店铺详情(只认数字 id)
    ("GET", r"/merchants/\d+/dishes"),       # 菜单
    ("GET", r"/orders"),                     # 我的订单
    ("GET", r"/orders/delivery-fee"),        # 算配送费(不下单)
    ("GET", r"/orders/[0-9a-f]{8,40}"),      # 订单详情(订单号是十六进制串)
    ("GET", r"/transparency/[a-z-]+"),       # 公开口径,本来也不需要登录
    ("POST", r"/orders"),                    # ← 只到「创建待支付订单」为止
)


def agent_can(method: str, path: str) -> bool:
    """这个方法+路径是否在助手令牌的能力范围内。**默认拒绝。**

    **全匹配**,不是前缀匹配:`POST /orders` 放行而 `POST /orders/x/pay/mock`
    不放行,靠的就是全匹配 —— 前缀匹配的话后者也会被放进来。
    """
    import re

    return any(m == method and re.fullmatch(pat, path.rstrip("/") or "/")
               for m, pat in AGENT_ALLOWED)


async def _check_agent_token(db: AsyncSession, payload: dict) -> None:
    """助手令牌还有效吗 —— 吊销、过期、不存在一律 401。

    JWT 自己吊销不了,所以每次都回库查一行。代价是一次主键查询,
    换来的是「用户在设置里点吊销,下一秒就真的不能用了」。
    """
    from datetime import datetime, timezone

    from .models import AgentToken

    jti = payload.get("jti") or ""
    row = await db.scalar(select(AgentToken).where(AgentToken.jti == jti))
    if row is None or row.revoked_at is not None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED,
                            "这个助手令牌已被吊销")
    now = datetime.now(timezone.utc)
    exp = row.expires_at
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    if exp <= now:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "这个助手令牌已过期")
    row.last_used_at = now          # 让用户看得出哪个还在用、哪个可以清掉
    await db.commit()


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: AsyncSession = Depends(get_db),
) -> User:
    if credentials is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "未登录")
    try:
        payload = jwt.decode(credentials.credentials, settings.jwt_secret, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "登录已过期,请重新登录")
    # AI 助手令牌:能力范围在这里收口。
    #
    # 放在 get_current_user 而不是各个路由上,是因为**这里是唯一入口** ——
    # 所有需要登录的接口都经过它,漏不掉;而逐个路由加限制,
    # 漏一个就是一条没人看守的路。
    if payload.get("scope") == "agent":
        await _check_agent_token(db, payload)
        # 打个标,记录交给中间件 —— 只有那儿同时拿得到状态码和耗时
        request.state.api_client = ("agent", None, int(payload["sub"]))
        if not agent_can(request.method, request.url.path):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "AI 助手令牌不能做这件事。它只能查询和创建待支付订单 —— "
                "付款、退款、改地址请在 App 里自己操作。")
    user = await db.get(User, int(payload["sub"]))
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "用户不存在")
    # 已注销:旧 token 立即失效。
    #
    # 判据是 `deleted_at`,不再是手机号长什么样。前缀那条留着兜两种情况:
    # ① 存量行还没跑过数据修复脚本;② 迁移被回滚(0108 downgrade 会
    # 删掉这一列)。少认一行墓碑的后果是旧 token 还能用,所以宁可两条都判。
    if user.deleted_at is not None or user.phone.startswith("del"):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "账号已注销")
    return user


async def get_current_user_optional(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: AsyncSession = Depends(get_db),
) -> User | None:
    """未登录返回 None 而不是 401。

    只给「同一个路径既服务公开内容也服务私密内容」的地方用
    (目前是 /uploads 老 URL 兼容):公开文件不该因为没带 token 就 401,
    私密文件再由调用方自己判 None 并抛 401。
    """
    if credentials is None:
        return None
    try:
        return await get_current_user(credentials, db)
    except HTTPException:
        return None


def require_role(*roles: str):
    async def checker(user: User = Depends(get_current_user)) -> User:
        if user.role.value not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "当前角色无权访问")
        return user

    return checker
