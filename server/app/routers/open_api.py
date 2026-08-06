"""商家开放接口(POS/收银系统对接,#K)。

**为什么要有这层**:稍大的餐厅都在用收银系统(客如云/银豹等)。
没有拉单接口,他们就得盯着两块屏、手工把外卖单抄进收银台 ——
这是连锁商家问的第一个问题,也是他们不入驻的常见理由。

口径(第一版故意做窄,窄比全更容易保证不出事):
- **只读**。不开放接单/改价/退款 —— 写操作出错的代价由商家和顾客承担,
  等真实对接跑顺了再逐个开;
- 认证走独立的 API Key(`Authorization: Bearer sz_xxx`),
  不复用登录 token:POS 是长期挂机的机器,凭证泄露面和人不一样,
  要能单独吊销、能看到是哪把在用;
- 顾客隐私按商家视角脱敏(与商家 App 同一套 order_out 口径),
  不因为"是机器在读"就多给一位手机号。
"""
import hashlib
import secrets
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..models import Merchant, MerchantApiKey, MerchantStatus, Order
from ..ratelimit import check_rate_limit
from ..state_machine import OrderStatus
from .orders import order_out

router = APIRouter(prefix="/open/v1", tags=["开放接口"])

KEY_PREFIX = "sz_"


def hash_key(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def new_key() -> tuple[str, str, str]:
    """返回 (明文, 哈希, 展示前缀)。明文只在创建那一刻给一次。"""
    raw = KEY_PREFIX + secrets.token_urlsafe(32)
    return raw, hash_key(raw), raw[:10]


async def open_merchant(
    authorization: str = Header(default=""),
    db: AsyncSession = Depends(get_db),
) -> Merchant:
    """API Key → 商家。吊销过的、不存在的一律 401,不区分说法。"""
    token = ""
    if authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    if not token.startswith(KEY_PREFIX):
        raise HTTPException(401, "缺少或非法的 API Key")
    key = await db.scalar(
        select(MerchantApiKey).where(
            MerchantApiKey.token_hash == hash_key(token),
            MerchantApiKey.revoked_at.is_(None)))
    if key is None:
        raise HTTPException(401, "API Key 无效或已吊销")
    shop = await db.get(Merchant, key.merchant_id)
    # 店铺被驳回/下架后,已发出的 Key 也不该继续拉单
    if shop is None or shop.status != MerchantStatus.approved:
        raise HTTPException(401, "API Key 无效或已吊销")
    return shop


@router.get("/shop")
async def open_shop(shop: Merchant = Depends(open_merchant)):
    """本店基础信息:对接方用来核对连的是哪家店。"""
    # POS 是长期挂机的机器,轮询间隔配错(比如 100ms)就是一次自伤
    await check_rate_limit("open_api", str(shop.id), 120)
    return {
        "id": shop.id,
        "name": shop.name,
        "biz_type": shop.biz_type,
        "is_open": shop.is_open,
        "busy_active": shop.busy_active,
        "address": shop.address,
        "promise_ready_minutes": shop.promise_ready_minutes,
    }


@router.get("/orders")
async def open_orders(
    since: str | None = Query(default=None,
                              description="ISO 时间,只取此后创建的单"),
    status: str | None = Query(default=None, description="订单状态过滤"),
    limit: int = Query(default=50, ge=1, le=200),
    shop: Merchant = Depends(open_merchant),
    db: AsyncSession = Depends(get_db),
):
    """本店订单(只读)。

    增量拉取用 `since` 传上次拉到的最新 created_at ——
    **此时按时间正序返回**:`created_at > since` 是向前取,配倒序会变成
    "只给最新的 N 条",中间积压的单永远拉不到(POS 断网 40 分钟、
    期间来了 120 单,带 limit=50 拉一次就永久漏掉 70 单,而且没有补拉的入口)。
    不传 since 时按倒序给最新的一页,供首次接入/人工排查用。

    顾客手机号与门牌按商家视角脱敏,与商家 App 看到的完全一致。
    """
    await check_rate_limit("open_api", str(shop.id), 120)
    query = select(Order).where(Order.merchant_id == shop.id).limit(limit)
    if since:
        try:
            cursor = datetime.fromisoformat(since)
        except ValueError:
            raise HTTPException(422, "since 需要是 ISO 时间格式")
        if cursor.tzinfo is None:
            cursor = cursor.replace(tzinfo=timezone.utc)
        # 正序:从游标往后逐页推进,一单不漏
        query = query.where(Order.created_at > cursor).order_by(
            Order.created_at.asc())
    else:
        query = query.order_by(Order.created_at.desc())
    if status:
        try:
            query = query.where(Order.status == OrderStatus(status))
        except ValueError:
            raise HTTPException(422, "未知的订单状态")
    orders = list(await db.scalars(query))
    # **必须显式声明商家视角**:API Key 认证没有 User 对象,
    # 不传 as_role 就会退回"用户本人"的全量口径 —— 门牌、真名、
    # 送达留证一起下发。机器在读也不比人多看到一个字段
    items = [order_out(order, shop, as_role="merchant") for order in orders]
    return {"orders": items, "count": len(items)}
