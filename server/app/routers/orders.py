import logging
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..db import get_db
from ..models import Dish, Merchant, MerchantStatus, Order, OrderEvent, User
from ..ratelimit import check_rate_limit
from ..redis_client import RIDER_LOC_KEY, get_redis
from ..schemas import (
    BoostTipIn,
    ChangeAddressIn,
    OrderCreateIn,
    OrderEventOut,
    OrderOut,
    PickupVerifyIn,
    RefundItemIn,
    RiderLocationOut,
    TransitionIn,
)
from ..security import get_current_user, require_role
from ..services.auto_flow import RESTOCK_FROM_STATUSES, restore_stock
from ..services.payment_core import mark_order_paid
from zoneinfo import ZoneInfo

from ..services.flags import in_hhmm_range, night_curfew_window, weather_surcharge_on
from ..services.pricing import delivery_fee_parts, haversine_m, in_delivery_range
from ..services.privacy_phone import dialable_phone, mask_phone
from ..services.push import notify_order_status, push_to_user
from ..services.settlement import settle_order
from ..services.wechat_pay import request_refund
from ..state_machine import STATUS_LABELS
from ..state_machine import OrderStatus, TransitionError, assert_transition
from ..ws import manager

logger = logging.getLogger("superz.orders")

router = APIRouter(prefix="/orders", tags=["订单"])


def resolve_options(dish_name: str, base_cents: int, groups: list,
                    chosen: list[str]) -> tuple[int, str]:
    """按菜品规格定义校验用户选择,返回 (单价, 展示名)。

    规则:必选组必须恰好选一项;单选组最多一项;多选组任意;
    选择必须能全部归属到某个组的某个选项,不允许凭空捏造。
    校验失败抛 ValueError(调用方转 422)。
    """
    remaining = list(chosen)
    total = base_cents
    picked_names: list[str] = []
    for group in groups:
        choices = {c["name"]: c.get("delta_cents", 0) for c in group.get("choices", [])}
        hits = [n for n in remaining if n in choices]
        if group.get("required") and len(hits) == 0:
            raise ValueError(f"「{dish_name}」请选择{group.get('name', '规格')}")
        if not group.get("multi") and len(hits) > 1:
            raise ValueError(f"「{dish_name}」的{group.get('name', '规格')}只能选一项")
        for n in hits:
            total += choices[n]
            picked_names.append(n)
            remaining.remove(n)
    if remaining:
        raise ValueError(f"「{dish_name}」不存在选项:{'、'.join(remaining)}")
    display = f"{dish_name}({'+'.join(picked_names)})" if picked_names else dish_name
    return total, display


def order_out(order: Order, merchant: Merchant | None,
              viewer: User | None = None) -> OrderOut:
    """订单 + 商家取餐点信息。骑手端地图/导航需要知道店在哪。

    电话脱敏:商家/骑手视角 contact_phone 一律打码,可拨号码走 privacy_phone
    (X 号 > 过渡期真号 > 严格模式空)。用户本人与管理后台看真号。
    """
    out = OrderOut.model_validate(order)
    out.no_rider_alerted = order.no_rider_alerted_at is not None
    if merchant is not None:
        out.merchant_name = merchant.name
        out.merchant_address = merchant.address
        out.merchant_lat = merchant.lat
        out.merchant_lng = merchant.lng
    if viewer is not None and viewer.role.value in ("merchant", "rider"):
        out.privacy_phone = dialable_phone(order)
        out.contact_phone = mask_phone(order.contact_phone)
        # 地址保护:未放行前只给粗地址(POI/小区),门牌详情不下发;
        # 收货人一律中性称呼。坐标保留(导航要用,门牌才是敏感面)
        if order.addr_protect and not order.addr_revealed:
            import re as _re
            out.address = (order.addr_public
                           or _re.sub(r"\d[\d\-室号门栋单元楼层a-zA-Z]*$",
                                      "***", order.address).strip() + " ***")
        if order.addr_protect:
            out.contact_name = order.salutation or "顾客"
        # 送达留证仅用户/平台可见
        out.delivery_photo_url = ""
    return out


async def orders_out(db: AsyncSession, orders: list[Order],
                     viewer: User | None = None) -> list[OrderOut]:
    ids = {o.merchant_id for o in orders}
    if not ids:
        return []
    merchants = {
        m.id: m
        for m in await db.scalars(select(Merchant).where(Merchant.id.in_(ids)))
    }
    return [order_out(o, merchants.get(o.merchant_id), viewer) for o in orders]


async def _record_event(db, order: Order, from_status: str, to_status: str,
                        user: User | None, note: str = ""):
    db.add(
        OrderEvent(
            order_id=order.id,
            from_status=from_status,
            to_status=to_status,
            actor_role=user.role.value if user else "system",
            actor_id=user.id if user else None,
            note=note,
        )
    )


async def _notify(order: Order):
    await manager.broadcast(
        f"order:{order.order_no}",
        {"type": "order_status", "order_no": order.order_no, "status": order.status.value},
    )


@router.post("", response_model=OrderOut)
async def create_order(
    payload: OrderCreateIn,
    user: User = Depends(require_role("customer")),
    db: AsyncSession = Depends(get_db),
):
    await check_rate_limit("order", str(user.id),
                           settings.rate_limit_order_per_minute)
    # 极端天气停运(管理后台一键):停接新单,已有订单尽力履约
    from ..services.flags import weather_shutdown_on
    if await weather_shutdown_on(db):
        raise HTTPException(
            409, "极端天气,平台临时停止接新单(已有订单会尽力送达);"
                 "天气好转后恢复,请稍后再来")
    # 平台深夜保护窗(管理后台开关):窗口内暂停接新单,已有订单正常履约
    curfew = await night_curfew_window(db)
    if curfew is not None:
        now_cn = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%H:%M")
        if in_hhmm_range(curfew, now_cn):
            raise HTTPException(
                409, f"深夜时段({curfew.replace('-', ' 至 ')})平台暂停接新单,"
                     f"已下的订单会正常配送,请稍后再来")
    merchant = await db.get(Merchant, payload.merchant_id)
    if (
        merchant is None
        or not merchant.is_open
        or merchant.status != MerchantStatus.approved
    ):
        raise HTTPException(409, "商家不存在或已打烊")

    # 拼单:校验拼单码并原子关车(只有发起人、锁单后);
    # 订单归发起人,起送价/满减按合车总额天然生效
    group_members = 0
    if payload.group_code:
        from .group_cart import consume_cart_for_order
        group_cart = await consume_cart_for_order(payload.group_code, user.id)
        if group_cart["merchant_id"] != merchant.id:
            raise HTTPException(422, "拼单车不是这家店的")
        group_members = len(group_cart["members"])

    # 酒类风控:购物车含酒 → 必须已实名且成年(#14);平台可配禁售时段。
    # 全部在扣库存之前拦截,不留副作用
    alcohol_in_cart = bool((await db.scalars(
        select(Dish.id).where(
            Dish.id.in_([i.dish_id for i in payload.items]),
            Dish.merchant_id == merchant.id,
            Dish.is_alcohol.is_(True)).limit(1))).first())
    if alcohol_in_cart:
        from ..models import UserIdentity
        from ..services.flags import alcohol_curfew_window
        from ..services.idcheck import is_adult

        window = await alcohol_curfew_window(db)
        if window is not None:
            now_cn = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%H:%M")
            if in_hhmm_range(window, now_cn):
                raise HTTPException(
                    409, f"按平台规定,{window.replace('-', ' 至 ')} 时段"
                         f"暂停销售酒类商品,请去掉酒类后下单")
        identity = await db.scalar(
            select(UserIdentity).where(UserIdentity.user_id == user.id))
        if identity is None:
            raise HTTPException(
                422, "购买酒类商品需先完成实名认证(我的 → 实名认证),只做一次全程有效")
        if not is_adult(identity.birth_date):
            raise HTTPException(422, "依法不向未成年人出售酒类商品")

    # 加菜 = 追加单:锚定原单(同人同店、商家出餐前),免配送费免起送价,
    # 地址/联系人/预约时间/骑手全部继承原单——它只是原单的"第二个袋子"
    parent = None
    if payload.append_to:
        parent = await db.scalar(
            select(Order).where(Order.order_no == payload.append_to))
        if (parent is None or parent.customer_id != user.id
                or parent.merchant_id != merchant.id):
            raise HTTPException(404, "原订单不存在")
        if parent.pickup:
            raise HTTPException(409, "自取单不支持加菜,直接再下一单即可(同样免配送费)")
        if parent.parent_order_no:
            raise HTTPException(409, "追加单不能再追加,请在原订单上加菜")
        if parent.status not in (OrderStatus.PAID, OrderStatus.ACCEPTED):
            raise HTTPException(409, "商家已出餐,来不及一起打包了;想加请重新下单")

    # 预约送达:至少提前 30 分钟,最多 48 小时(时间校验放在扣库存之前)
    scheduled_at = payload.scheduled_at
    if scheduled_at is not None:
        if scheduled_at.tzinfo is None:
            scheduled_at = scheduled_at.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        if scheduled_at < now + timedelta(minutes=30):
            raise HTTPException(422, "预约时间至少要在 30 分钟之后")
        if scheduled_at > now + timedelta(hours=48):
            raise HTTPException(422, "最多支持预约 48 小时内送达")

    # 扣库存用条件 UPDATE(stock >= quantity),天然防超卖:
    # 两个人同时买最后一份时,数据库保证只有一个 UPDATE 生效
    food_cents = 0
    items_snapshot = []
    for item in payload.items:
        result = await db.execute(
            update(Dish)
            .where(
                Dish.id == item.dish_id,
                Dish.merchant_id == merchant.id,
                Dish.is_on_sale.is_(True),
                Dish.stock >= item.quantity,
            )
            .values(stock=Dish.stock - item.quantity)
            .returning(Dish.name, Dish.price_cents, Dish.options,
                       Dish.flash_price_cents, Dish.flash_until,
                       Dish.is_alcohol)
        )
        row = result.first()
        if row is None:
            # 区分失败原因给准确文案:估清(今日售罄) / 下架 / 库存不够。
            # 先把要用的值全部读出来再 rollback(rollback 会使 ORM 对象过期)
            dish = await db.get(Dish, item.dish_id)
            if dish is None or dish.merchant_id != merchant.id:
                detail = f"菜品(id={item.dish_id})不存在"
            elif dish.sold_out_today:
                detail = f"「{dish.name}」今日已售罄,明天赶早"
            elif not dish.is_on_sale:
                detail = f"「{dish.name}」已下架"
            else:
                detail = f"「{dish.name}」库存不足(剩 {dish.stock} 份)"
            await db.rollback()
            raise HTTPException(409, detail)
        name, price_cents, option_groups, flash_price, flash_until, \
            dish_is_alcohol = row
        # 限时折扣生效则按折扣价成交(折扣价即成交价,佣金自动按折后实收计)
        if (flash_price is not None and flash_until is not None
                and flash_until > datetime.now(timezone.utc)):
            price_cents = flash_price
        # 规格/加料:按菜品定义校验选择并重算单价(不信客户端传价)
        try:
            unit_price, display_name = resolve_options(
                name, price_cents, option_groups or [], item.choices)
        except ValueError as exc:
            await db.rollback()
            raise HTTPException(422, str(exc))
        food_cents += unit_price * item.quantity
        snapshot_entry = {
            "dish_id": item.dish_id,
            # 展示名预合成「红烧牛肉面(大份+加蛋)」,三端所有现有展示直接生效
            "name": display_name,
            "options": item.choices,
            "price_cents": unit_price,
            "quantity": item.quantity,
        }
        if dish_is_alcohol:
            # 快照记酒类标记:小票与骑手端据此提示「查验收件人」
            snapshot_entry["is_alcohol"] = True
        items_snapshot.append(snapshot_entry)

    # 起送价:商家自设,但不低于平台下限(小单佣金连支付通道费都不够,商业上不可持续)。
    # 注意先把值取出来再 rollback —— rollback 会使 ORM 对象过期,
    # 之后再访问属性会触发同步惰性刷新,在 async 会话里直接炸 MissingGreenlet
    min_order = max(merchant.min_order_cents, settings.min_order_floor_cents)
    if parent is not None:
        min_order = 0  # 追加单免起送价:凑单场景就是为了补一瓶可乐
    if food_cents < min_order:
        await db.rollback()
        raise HTTPException(
            409, f"未达起送价 ¥{min_order / 100:.0f},请再加点菜")

    # 自取单不校验配送半径(人自己来,多远都行);配送单必须有收货地址
    if parent is not None:
        distance_m = 0.0  # 地址随原单,半径在原单已校验
    elif payload.pickup:
        distance_m = 0.0
    else:
        if not payload.address or payload.lat is None or payload.lng is None:
            await db.rollback()
            raise HTTPException(422, "请先选择收货地址")
        # 配送半径:超出不接单(与其靠封顶价让远单没人接,不如明确不做远单)
        distance_m = haversine_m(merchant.lat, merchant.lng, payload.lat, payload.lng)
        if not in_delivery_range(distance_m):
            await db.rollback()
            raise HTTPException(
                409, f"超出配送范围({settings.delivery_max_km:g}km),换家近点的店吧")

    packing = merchant.packing_fee_cents
    notes = []

    # 商家满减:取满足门槛的最大一档,成本商家承担(结算时从实收里扣)
    discount = 0
    for rule in sorted(merchant.promo_rules or [],
                       key=lambda r: r.get("threshold_cents", 0)):
        if food_cents >= rule.get("threshold_cents", 0) > 0:
            discount = min(rule.get("off_cents", 0), food_cents + packing)
    manjian_discount = discount  # 记住满减档,店铺券与它二选其一取最优

    # 平台首单立减:从没支付过订单的新用户,成本平台承担。
    # 反作弊软限制:limit/frozen 用户暂停平台补贴(下单照常,不拦)
    subsidy = 0
    if settings.first_order_discount_cents > 0 and user.risk_level == "":
        has_paid = await db.scalar(
            select(Order.id).where(
                Order.customer_id == user.id,
                Order.status.notin_(
                    [OrderStatus.PENDING_PAYMENT, OrderStatus.CANCELLED]),
            ).limit(1)
        )
        if has_paid is None:
            subsidy = min(settings.first_order_discount_cents,
                          food_cents + packing - discount)
            notes.append(f"首单立减-{subsidy / 100:g}元(平台)")

    # 优惠券抵扣:平台券走 subsidy(平台承担),店铺券走 discount(商家承担)
    coupon = None
    if payload.coupon_id:
        from ..models import Coupon
        coupon = await db.get(Coupon, payload.coupon_id, with_for_update=True)
        now_utc = datetime.now(timezone.utc)
        if coupon is None or coupon.user_id != user.id:
            await db.rollback()
            raise HTTPException(422, "优惠券不存在")
        if coupon.used_order_no:
            await db.rollback()
            raise HTTPException(409, "这张券已经用过了")
        expires = coupon.expires_at
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        if expires < now_utc:
            await db.rollback()
            raise HTTPException(409, "这张券已过期")
        if coupon.funder == "merchant":
            # 店铺券:只能在发券商家使用;门槛按 food+packing(与满减一致口径);
            # 与满减二选其一取最优,不叠加成负毛利
            if coupon.merchant_id != merchant.id:
                await db.rollback()
                raise HTTPException(409, "该店铺券只能在发券商家使用")
            if food_cents + packing < coupon.min_spend_cents:
                await db.rollback()
                raise HTTPException(
                    409, f"未达券的使用门槛 ¥{coupon.min_spend_cents / 100:g}")
            shop_off = min(coupon.amount_cents, food_cents + packing)
            if shop_off <= manjian_discount:
                await db.rollback()
                raise HTTPException(
                    409, f"本单满减(¥{manjian_discount / 100:g})已优于该店铺券,"
                         "无需使用")
            discount = shop_off  # 取代满减(取最优,商家承担)
            notes.append(f"店铺券-{shop_off / 100:g}元(商家)")
        else:
            if food_cents + packing - discount < coupon.min_spend_cents:
                await db.rollback()
                raise HTTPException(
                    409, f"未达券的使用门槛 ¥{coupon.min_spend_cents / 100:g}")
            coupon_off = min(coupon.amount_cents,
                             food_cents + packing - discount - subsidy)
            if coupon_off > 0:
                subsidy += coupon_off
                notes.append(f"平台券-{coupon_off / 100:g}元(平台)")

    # 满减备注:仅当最终折扣就是满减档(未被店铺券取代)时展示
    if discount and discount == manjian_discount:
        notes.append(f"满减-{discount / 100:g}元(商家)")

    # 资金安全:折扣(商家)+补贴(平台)合计不得超过 菜品+打包,
    # 否则用户实付会低于配送费+小费甚至为负(店铺券取代满减后重新钳制补贴)
    subsidy = min(subsidy, max(0, food_cents + packing - discount))

    # 商家满赠:取满足门槛的最高一档赠 1 份(与满减同时生效——满减动钱、满赠动货)。
    # 赠品以 0 元行进快照,food/total/佣金全不含赠品,资金口径零影响;
    # 扣库存用与正常菜同一条件 UPDATE 防超卖,没库存就降档尝试,绝不拦下单
    for rule in sorted(merchant.gift_rules or [],
                       key=lambda r: r.get("threshold_cents", 0), reverse=True):
        threshold = rule.get("threshold_cents", 0)
        if not (food_cents >= threshold > 0):
            continue
        gift_row = (await db.execute(
            update(Dish)
            .where(
                Dish.id == rule.get("dish_id"),
                Dish.merchant_id == merchant.id,
                Dish.is_on_sale.is_(True),
                Dish.stock >= 1,
            )
            .values(stock=Dish.stock - 1)
            .returning(Dish.name)
        )).first()
        if gift_row is None:
            notes.append(f"满{threshold / 100:g}赠品已送完")
            continue
        items_snapshot.append({
            "dish_id": rule["dish_id"],
            "name": f"[赠]{gift_row[0]}",
            "options": [],
            "price_cents": 0,
            "quantity": 1,
        })
        notes.append(f"满{threshold / 100:g}赠{gift_row[0]}(商家)")
        break

    # 配送费 = 距离阶梯 + 夜间/恶劣天气加价,每一分都归骑手(加价原因写进订单备注);
    # 自取单免配送费,取餐码随单生成、印在小票上
    if parent is not None:
        fee_cents = 0
        notes.append(f"追加到订单#{parent.order_no[-6:]},随原单配送免配送费")
    elif payload.pickup:
        fee_cents = 0
        notes.append("到店自取,免配送费")
    else:
        fee_parts = delivery_fee_parts(distance_m, weather_on=await weather_surcharge_on(db))
        fee_cents = sum(fee_parts.values())
        if fee_parts["night"]:
            notes.append(f"夜间配送+{fee_parts['night'] / 100:g}元(归骑手)")
        if fee_parts["weather"]:
            notes.append(f"恶劣天气+{fee_parts['weather'] / 100:g}元(归骑手)")

    if group_members > 1:
        notes.append(f"拼单×{group_members}人")
    # 地址精确度:该地址被骑手反馈过 ≥2 次「地址不准」,提示核对(不拦截)
    if not payload.pickup and payload.address:
        from ..models import AddressFeedback
        from sqlalchemy import func as sa_func
        fb = await db.scalar(
            select(sa_func.count(AddressFeedback.id)).where(
                AddressFeedback.customer_id == user.id,
                AddressFeedback.address == payload.address))
        if fb and fb >= 2:
            notes.append("骑手反馈过该地址不好找,请核对门牌或补充指引")
    # 自配送快照:下单时定格(商家之后改开关不影响已有订单);追加单随原单
    self_delivery = (parent.self_delivery if parent is not None
                     else (False if payload.pickup else merchant.self_delivery))
    if self_delivery:
        notes.append("商家自送")
    # 小费:100% 归骑手(结算行 = 配送费 + 小费),不计佣金基数、不参与满减门槛
    if payload.pickup and payload.tip_cents:
        await db.rollback()
        raise HTTPException(422, "自取单没有配送环节,无需小费")
    if self_delivery and payload.tip_cents:
        await db.rollback()
        raise HTTPException(422, "该店商家自送,无需小费(小费是给骑手的)")
    tip_cents = 0 if (payload.pickup or self_delivery) else payload.tip_cents
    if tip_cents:
        notes.append(f"小费{tip_cents / 100:g}元(100%归骑手)")
    order = Order(
        order_no=uuid.uuid4().hex[:20],
        customer_id=user.id,
        merchant_id=merchant.id,
        status=OrderStatus.PENDING_PAYMENT,
        items=items_snapshot,
        food_cents=food_cents,
        packing_fee_cents=packing,
        discount_cents=discount,
        subsidy_cents=subsidy,
        promo_note=";".join(notes),
        delivery_fee_cents=fee_cents,
        tip_cents=tip_cents,
        total_cents=(food_cents + packing - discount + fee_cents
                     + tip_cents - subsidy),
        address=(parent.address if parent is not None
                 else ("到店自取" if payload.pickup else payload.address)),
        lat=(parent.lat if parent is not None
             else (merchant.lat if payload.pickup else payload.lat)),
        lng=(parent.lng if parent is not None
             else (merchant.lng if payload.pickup else payload.lng)),
        contact_name=(parent.contact_name if parent is not None
                      else payload.contact_name),
        contact_phone=(parent.contact_phone if parent is not None
                       else payload.contact_phone),
        remark=(f"[追加到#{parent.order_no[-6:]}]{payload.remark}"
                if parent is not None else payload.remark),
        scheduled_at=(parent.scheduled_at if parent is not None
                      else scheduled_at),
        self_delivery=self_delivery,
        addr_protect=(False if payload.pickup else payload.addr_protect),
        addr_public=(payload.address_public.strip()[:200]
                     if payload.addr_protect else ""),
        salutation=payload.salutation.strip()[:12],
        pickup=payload.pickup,
        pickup_code=f"{secrets.randbelow(10000):04d}" if payload.pickup else "",
        parent_order_no=parent.order_no if parent is not None else "",
        rider_id=parent.rider_id if parent is not None else None,
    )
    db.add(order)
    await db.flush()
    if coupon is not None:
        coupon.used_order_no = order.order_no  # 锁定;全额退款/关单时释放
    await _record_event(db, order, "", OrderStatus.PENDING_PAYMENT.value, user)
    await db.commit()
    await db.refresh(order)
    # 风控异步评估(只标记不拦截,失败不影响下单)
    from ..services.risk import assess_order_async
    assess_order_async(order.id)
    return order_out(order, merchant, user)


@router.get("/coupons/mine")
async def my_coupons(
    user: User = Depends(require_role("customer")),
    db: AsyncSession = Depends(get_db),
):
    """我的券包:可用在前(未用未过期),近 30 张。"""
    from ..models import Coupon
    now = datetime.now(timezone.utc)
    rows = (await db.scalars(
        select(Coupon).where(Coupon.user_id == user.id)
        .order_by(Coupon.created_at.desc()).limit(30))).all()

    def usable(c: Coupon) -> bool:
        expires = (c.expires_at if c.expires_at.tzinfo
                   else c.expires_at.replace(tzinfo=timezone.utc))
        return not c.used_order_no and expires >= now

    return [{
        "id": c.id,
        "amount_cents": c.amount_cents,
        "min_spend_cents": c.min_spend_cents,
        "expires_at": c.expires_at.isoformat(),
        "usable": usable(c),
        "used": bool(c.used_order_no),
        "note": c.note,
        # 店铺券(funder=merchant)只能在 merchant_id 店使用;平台券不限店
        "funder": c.funder,
        "merchant_id": c.merchant_id,
    } for c in sorted(rows, key=lambda c: not usable(c))]


@router.post("/{order_no}/pay/mock", response_model=OrderOut)
async def mock_pay(
    order_no: str,
    user: User = Depends(require_role("customer")),
    db: AsyncSession = Depends(get_db),
):
    """模拟支付。接微信支付后,这段逻辑原样搬进支付回调,幂等结构不变。"""
    order = await db.scalar(
        select(Order).where(Order.order_no == order_no).with_for_update()
    )
    if order is None or order.customer_id != user.id:
        raise HTTPException(404, "订单不存在")
    merchant = await db.get(Merchant, order.merchant_id)
    # 幂等入账走统一入口(微信支付回调也是同一个函数)
    order = await mark_order_paid(
        db, order, merchant, actor_role="customer", actor_id=user.id
    )
    return order_out(order, merchant, user)


@router.post("/{order_no}/transition", response_model=OrderOut)
async def transition(
    order_no: str,
    payload: TransitionIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """统一状态流转入口:商家接单/出餐、骑手取餐/送达、用户确认/取消。"""
    order = await db.scalar(
        select(Order).where(Order.order_no == order_no).with_for_update()
    )
    if order is None:
        raise HTTPException(404, "订单不存在")

    # 归属校验:只能操作自己相关的订单
    role = user.role.value
    if role == "customer" and order.customer_id != user.id:
        raise HTTPException(403, "这不是你的订单")
    if role == "merchant":
        # 店主或店员都能接单/出餐(运营权限);敏感操作走各自端点仍限店主
        from ..services.staff import operable_shop
        shop, _ = await operable_shop(db, user)
        if shop is None or order.merchant_id != shop.id:
            raise HTTPException(403, "这不是你店里的订单")
    if role == "rider" and order.rider_id != user.id:
        raise HTTPException(403, "这不是你接的订单")

    # 自配送单:配送三态(取餐出发/送达)由商家操作,骑手环节不存在
    check_role = role
    if (order.self_delivery and role == "merchant"
            and payload.to_status in (OrderStatus.PICKED_UP,
                                      OrderStatus.DELIVERED)):
        check_role = "rider"
    try:
        assert_transition(order.status, payload.to_status, check_role)
    except TransitionError as e:
        raise HTTPException(403 if e.forbidden else 409, e.message)

    now = datetime.now(timezone.utc)
    # 用户取消分级:接单前随时;接单后 2 分钟反悔窗口;
    # 预约单放宽到预约时间 1 小时前(商家还没开始做);出餐后走售后
    if (payload.to_status == OrderStatus.CANCELLED and role == "customer"
            and order.status == OrderStatus.ACCEPTED):
        accepted_at = order.accepted_at
        if accepted_at is not None and accepted_at.tzinfo is None:
            accepted_at = accepted_at.replace(tzinfo=timezone.utc)
        scheduled_at = order.scheduled_at
        if scheduled_at is not None and scheduled_at.tzinfo is None:
            scheduled_at = scheduled_at.replace(tzinfo=timezone.utc)
        in_regret_window = (accepted_at is None
                            or now - accepted_at <= timedelta(minutes=2))
        scheduled_far = (scheduled_at is not None
                         and now < scheduled_at - timedelta(hours=1))
        if not (in_regret_window or scheduled_far):
            raise HTTPException(
                403, "商家已开始备餐,自助取消已关闭;可联系商家协商取消或送达后申请售后")

    # 商家拒单必须给用户一个说法
    if payload.to_status == OrderStatus.CANCELLED:
        if role == "merchant" and len(payload.reason.strip()) < 2:
            raise HTTPException(422, "拒单必须填写原因(会展示给用户)")
        order.cancel_reason = payload.reason.strip() or "用户取消"

    # 骑手取餐核验:小票印着单号尾号,输后 4 位防拿错单;
    # 连续输错仍可强制取餐(force),但写事件留痕供追溯。
    # 不传码 = 老客户端,不强制(核验是防错工具,不是新门槛)
    event_note = ""
    if (payload.to_status == OrderStatus.PICKED_UP and role == "rider"
            and not order.pickup):
        if payload.force:
            event_note = "强制取餐(未通过尾号核验)"
        elif payload.verify_code:
            if payload.verify_code.strip() != order.order_no[-4:]:
                redis = get_redis()
                err_key = f"pickup:verr:{order.order_no}"
                errs = await redis.incr(err_key)
                await redis.expire(err_key, 3600)
                hint = (";如确认拿的是本单,可选择强制取餐(会留痕)"
                        if errs >= 3 else "")
                raise HTTPException(
                    422, f"取餐码不符,请核对小票上的单号尾号(已输错 {errs} 次{hint})")
            event_note = "取餐核验通过"

    from_status = order.status
    order.status = payload.to_status
    # 接单时刻落库:出餐超时判定与用户反悔窗口的共同基准
    if payload.to_status == OrderStatus.ACCEPTED:
        order.accepted_at = now
    # 出餐瞬间定格是否超时(承诺时长口径;预约单以预约前推为基准)
    if payload.to_status == OrderStatus.READY and order.accepted_at is not None:
        shop_for_promise = (shop if role == "merchant"
                            else await db.get(Merchant, order.merchant_id))
        accepted_at = order.accepted_at
        if accepted_at.tzinfo is None:
            accepted_at = accepted_at.replace(tzinfo=timezone.utc)
        promise = timedelta(minutes=shop_for_promise.promise_ready_minutes)
        # 「or」保持粘性:骑手上报「到店未出餐」已标过延误的,不因补出餐而清掉
        if order.scheduled_at is not None:
            scheduled_at = order.scheduled_at
            if scheduled_at.tzinfo is None:
                scheduled_at = scheduled_at.replace(tzinfo=timezone.utc)
            order.ready_late = order.ready_late or now > scheduled_at
        else:
            order.ready_late = order.ready_late or (now - accepted_at > promise)
    # 制作开始前取消的订单,库存还回去
    if (
        payload.to_status == OrderStatus.CANCELLED
        and from_status in RESTOCK_FROM_STATUSES
    ):
        await restore_stock(db, order)
    # 已支付订单取消(用户取消/商家拒单)= 全额退款。
    # 缺货部分退款已同步扣减 total_cents,此处余额即用户净付金额;
    # 必须先发起退款再累计 refund_cents:微信通道按 total+已退 反推原始支付总额
    if (
        payload.to_status == OrderStatus.CANCELLED
        and from_status != OrderStatus.PENDING_PAYMENT
        and order.total_cents > 0
    ):
        refund_amount = order.total_cents
        note = f"取消退款:{order.cancel_reason}"
        await request_refund(db, order, refund_amount, note)
        order.refund_cents += refund_amount
        order.refund_note = (
            f"{order.refund_note};{note}" if order.refund_note else note
        )
    # 取消(含未支付关单)把抵扣的券放回券包,未过期可再用
    if payload.to_status == OrderStatus.CANCELLED:
        from ..services.eta import release_coupon
        await release_coupon(db, order.order_no)
    # 出餐了就把「到店未出餐」的催单工单自动销掉(不占用同单一张 open 工单的名额)
    if payload.to_status == OrderStatus.READY:
        from ..models import DeliveryIssue
        await db.execute(
            update(DeliveryIssue)
            .where(DeliveryIssue.order_id == order.id,
                   DeliveryIssue.kind == "not_ready",
                   DeliveryIssue.status == "open")
            .values(status="resolved", resolution="continue_delivery",
                    resolve_note="商家已出餐,自动销单", resolved_at=now)
        )
    # 送达拍照留证(放门口场景,仅用户/平台可见):
    # 深夜(北京 21-06)的地址保护单强制,其余可选
    if payload.to_status == OrderStatus.DELIVERED and not order.pickup:
        if payload.photo_url.strip():
            order.delivery_photo_url = payload.photo_url.strip()[:300]
        elif order.addr_protect:
            hour = datetime.now(ZoneInfo("Asia/Shanghai")).hour
            if hour >= 21 or hour < 6:
                raise HTTPException(
                    422, "深夜时段的保护订单送达需拍照留证(放门口拍一张即可)")
    # 订单完成 = 结算点:骑手配送费、商家净收入分别入账
    if payload.to_status == OrderStatus.COMPLETED:
        await settle_order(db, order)
    # 取餐节点:按骑手实时位置重估 ETA(只剩配送段,更准)
    if payload.to_status == OrderStatus.PICKED_UP and order.rider_id:
        try:
            from ..services.eta import recompute_eta
            from ..routers.riders import _rider_pos
            merchant = await db.get(Merchant, order.merchant_id)
            await recompute_eta(db, order, merchant,
                                rider_pos=await _rider_pos(order.rider_id))
        except Exception:
            logger.exception("取餐 ETA 刷新失败 %s", order.order_no)
    await _record_event(db, order, from_status.value, payload.to_status.value,
                        user, note=event_note)
    await db.commit()
    await db.refresh(order)
    # 送达超时判赔(平台承担,独立事务,失败不影响送达)
    if payload.to_status == OrderStatus.DELIVERED:
        try:
            from ..services.eta import compensate_if_late
            await compensate_if_late(db, order)
        except Exception:
            logger.exception("超时赔付检查失败 %s", order.order_no)
    await _notify(order)
    # 离线推送给用户(自己操作的除外);分账在完成时触发
    if user.id != order.customer_id:
        await notify_order_status(
            order.customer_id, order.order_no, STATUS_LABELS[order.status]
        )
    return order_out(order, await db.get(Merchant, order.merchant_id), user)


@router.post("/{order_no}/change-address", response_model=OrderOut)
async def change_address(
    order_no: str,
    payload: ChangeAddressIn,
    user: User = Depends(require_role("customer")),
    db: AsyncSession = Depends(get_db),
):
    """骑手取餐前改地址(每单一次,限同商家配送半径)。

    配送费按距离差重算(保留原单的夜间/天气加价):变便宜自动退差价;
    补差价支付未接入前不允许改到更贵的地址(改远请取消重下)。
    取餐后地址在骑手手上,自助通道关闭——电话联系骑手或让骑手上报地址异常仲裁。
    """
    order = await db.scalar(
        select(Order).where(Order.order_no == order_no).with_for_update())
    if order is None or order.customer_id != user.id:
        raise HTTPException(404, "订单不存在")
    if order.pickup:
        raise HTTPException(409, "自取单没有配送地址;想改配送请取消后重新下单")
    if order.status == OrderStatus.PICKED_UP:
        raise HTTPException(
            409, "骑手已取餐,请电话联系骑手协商;送错可申请售后")
    if order.status not in (OrderStatus.PAID, OrderStatus.ACCEPTED,
                            OrderStatus.READY):
        raise HTTPException(409, "当前状态不能修改地址")
    changed_before = await db.scalar(
        select(OrderEvent.id).where(
            OrderEvent.order_id == order.id,
            OrderEvent.to_status == "address_changed").limit(1))
    if changed_before:
        raise HTTPException(409, "每单只能改一次地址;再有变动请联系商家或客服")

    merchant = await db.get(Merchant, order.merchant_id)
    new_distance = haversine_m(merchant.lat, merchant.lng,
                               payload.lat, payload.lng)
    if not in_delivery_range(new_distance):
        raise HTTPException(
            409, f"新地址超出配送范围({settings.delivery_max_km:g}km)")

    # 距离差重算基础费,保留原单的夜间/天气加价部分
    old_distance = haversine_m(merchant.lat, merchant.lng, order.lat, order.lng)
    old_base = delivery_fee_parts(old_distance)["base"]
    new_base = delivery_fee_parts(new_distance)["base"]
    delta = new_base - old_base
    if delta > 0:
        raise HTTPException(
            409, f"新地址配送费需增加 ¥{delta / 100:.2f},补差价支付暂未开通;"
                 f"改远地址请取消订单后重新下单(接单 2 分钟内可免费取消)")

    order.address = payload.address.strip()
    order.lat, order.lng = payload.lat, payload.lng
    if payload.contact_name.strip():
        order.contact_name = payload.contact_name.strip()
    if payload.contact_phone.strip():
        order.contact_phone = payload.contact_phone.strip()
    refunded = 0
    if delta < 0:
        refunded = -delta
        order.delivery_fee_cents += delta
        order.total_cents += delta
        note = f"改地址退配送费差价 ¥{refunded / 100:.2f}"
        order.refund_cents += refunded
        order.refund_note = (f"{order.refund_note};{note}"
                             if order.refund_note else note)
        await request_refund(db, order, refunded, "改地址,配送费差价退还")
    await _record_event(db, order, order.status.value, "address_changed", user)
    await db.commit()
    await db.refresh(order)

    tail = order.order_no[-6:]
    await push_to_user(merchant.owner_id, "订单地址已变更",
                       f"订单#{tail} 用户改了配送地址,已重新打印小票请留意",
                       {"type": "order", "order_no": order.order_no})
    if order.rider_id is not None:
        await push_to_user(order.rider_id, "配送地址已变更",
                           f"订单#{tail} 新地址:{order.address},请以最新地址为准",
                           {"type": "order", "order_no": order.order_no})
    # 地址变了小票就旧了:云打印自动补打(失败只记日志)
    try:
        from ..services.cloud_print import print_order_async
        print_order_async(order, merchant)
    except Exception:
        pass
    return order_out(order, merchant, user)


@router.post("/{order_no}/boost-tip", response_model=OrderOut)
async def boost_tip(
    order_no: str,
    payload: BoostTipIn,
    user: User = Depends(require_role("customer")),
    db: AsyncSession = Depends(get_db),
):
    """加急小费:无人接单时用户追加小费,更快有人接。

    资金:小费 100% 归骑手、不计佣金基数(结算已按此分账);追加=一次补收款,
    微信补收未接入前走 mock 幂等入账(参照 mock_pay),补收成功才把 tip/total 抬上去。
    只在「无人接单告警」窗口开放(no_rider_alerted_at 已置、尚无骑手),
    避免正常单被无谓加价;取消时 tip 随 total 一起退(现有退款链覆盖)。
    """
    order = await db.scalar(
        select(Order).where(Order.order_no == order_no).with_for_update())
    if order is None or order.customer_id != user.id:
        raise HTTPException(404, "订单不存在")
    if order.pickup or order.self_delivery:
        raise HTTPException(409, "该订单没有骑手配送环节,无需加急小费")
    if order.rider_id is not None:
        raise HTTPException(409, "已有骑手接单,无需加急")
    if order.no_rider_alerted_at is None or order.status not in (
            OrderStatus.ACCEPTED, OrderStatus.READY):
        raise HTTPException(409, "当前无需加急(暂未进入无人接单状态)")
    if order.tip_cents + payload.add_cents > 10000:
        raise HTTPException(422, "小费累计不超过 100 元")

    # 补收款:接入微信支付后这里创建补收单,回调成功再入账;
    # 当前 mock 模式直接视为已收(与 mock_pay 语义一致)
    order.tip_cents += payload.add_cents
    order.total_cents += payload.add_cents
    order.promo_note = (
        f"{order.promo_note};加急小费+{payload.add_cents / 100:g}元(100%归骑手)"
        if order.promo_note else
        f"加急小费+{payload.add_cents / 100:g}元(100%归骑手)")
    await _record_event(db, order, order.status.value, "tip_boosted", user)
    await db.commit()
    await db.refresh(order)

    # 通知在线骑手:加急单值钱了,快来抢(抢单池排序也会把它往前提)
    from ..models import UserRole
    online_riders = (await db.scalars(
        select(User.id).where(User.role == UserRole.rider,
                              User.is_online.is_(True)).limit(100))).all()
    for rid in online_riders:
        await push_to_user(
            rid, "有加急小费订单",
            f"一单加了小费 ¥{order.tip_cents / 100:g}(全归你),顺路就去抢",
            {"type": "order", "order_no": order.order_no})
    merchant = await db.get(Merchant, order.merchant_id)
    return order_out(order, merchant, user)


async def _self_refund_reason(db: AsyncSession, order: Order) -> str | None:
    """自助退款是否符合规则,返回原因文案;不符合返回 None(转人工)。

    规则明确、无争议才自助:①未接单(PAID)②商家超时未出餐(ACCEPTED 且
    已超承诺出餐时长 1.5 倍)。已出餐/配送中/已完成一律转人工(涉及餐损/判责)。
    """
    if order.status == OrderStatus.PAID:
        return "商家尚未接单,可自助全额退款"
    if order.status == OrderStatus.ACCEPTED and order.accepted_at is not None:
        shop = await db.get(Merchant, order.merchant_id)
        accepted = order.accepted_at
        if accepted.tzinfo is None:
            accepted = accepted.replace(tzinfo=timezone.utc)
        promise = timedelta(minutes=shop.promise_ready_minutes) * 1.5
        if datetime.now(timezone.utc) - accepted > promise:
            return "商家超时未出餐,可自助全额退款"
    return None


@router.get("/{order_no}/self-refund/check")
async def self_refund_check(
    order_no: str,
    user: User = Depends(require_role("customer")),
    db: AsyncSession = Depends(get_db),
):
    """自助退款前置判断:能否自助、原因,或需转人工(带工单上下文)。"""
    order = await db.scalar(select(Order).where(Order.order_no == order_no))
    if order is None or order.customer_id != user.id:
        raise HTTPException(404, "订单不存在")
    reason = await _self_refund_reason(db, order)
    if reason is not None:
        return {"eligible": True, "reason": reason,
                "refund_cents": order.total_cents}
    return {"eligible": False,
            "reason": "该订单已出餐或在配送中,自助退款不适用",
            "suggest_ticket": True,
            "ticket_context": f"订单#{order.order_no[-6:]} 申请退款(状态:"
                              f"{STATUS_LABELS.get(order.status, order.status.value)})"}


@router.post("/{order_no}/self-refund", response_model=OrderOut)
async def self_refund(
    order_no: str,
    user: User = Depends(require_role("customer")),
    db: AsyncSession = Depends(get_db),
):
    """自助退款:规则明确的场景直接按取消退款处理,不生成人工工单。"""
    order = await db.scalar(
        select(Order).where(Order.order_no == order_no).with_for_update())
    if order is None or order.customer_id != user.id:
        raise HTTPException(404, "订单不存在")
    reason = await _self_refund_reason(db, order)
    if reason is None:
        raise HTTPException(
            409, "该订单不符合自助退款条件,请提交客服工单人工处理")
    from_status = order.status
    # 与 transition 取消口径一致:回补库存(仅制作前)+ 全额退款 + 释放券
    if from_status in RESTOCK_FROM_STATUSES:
        await restore_stock(db, order)
    if order.total_cents > 0:
        note = f"自助退款:{reason}"
        await request_refund(db, order, order.total_cents, note)
        order.refund_cents += order.total_cents
        order.refund_note = (f"{order.refund_note};{note}"
                             if order.refund_note else note)
    order.status = OrderStatus.CANCELLED
    order.cancel_reason = reason
    from ..services.eta import release_coupon
    await release_coupon(db, order.order_no)
    await _record_event(db, order, from_status.value,
                        OrderStatus.CANCELLED.value, user)
    await db.commit()
    await db.refresh(order)
    await _notify(order)
    # 通知商家(已接单的单被自助退)
    merchant = await db.get(Merchant, order.merchant_id)
    if from_status == OrderStatus.ACCEPTED:
        await push_to_user(merchant.owner_id, "订单已自助退款",
                           f"订单#{order.order_no[-6:]} 因出餐超时被用户自助退款",
                           {"type": "order", "order_no": order.order_no})
    return order_out(order, merchant, user)


URGE_MAX_TIMES = 3          # 每单最多催 3 次
URGE_COOLDOWN_SECONDS = 180  # 两次催单间隔 ≥3 分钟


@router.post("/{order_no}/urge")
async def urge_order(
    order_no: str,
    user: User = Depends(require_role("customer")),
    db: AsyncSession = Depends(get_db),
):
    """用户催单:按订单状态自动判定催谁——未出餐催商家,配送中催骑手。

    每单最多 3 次、间隔 3 分钟(Redis 控频);催单写 OrderEvent(to_status='urged',
    事件型记录,不改订单状态,客户端时间轴对未知事件天然忽略)。
    """
    order = await db.scalar(select(Order).where(Order.order_no == order_no))
    if order is None or order.customer_id != user.id:
        raise HTTPException(404, "订单不存在")
    urgeable = {OrderStatus.PAID, OrderStatus.ACCEPTED,
                OrderStatus.READY, OrderStatus.PICKED_UP}
    if order.status not in urgeable:
        raise HTTPException(409, "当前状态不需要催单")
    if order.pickup and order.status == OrderStatus.READY:
        raise HTTPException(409, "餐已备好,凭取餐码到店取餐即可")

    # 控频:间隔 + 次数(Redis 不可用时放行,催单不能变成单点故障)
    redis = get_redis()
    try:
        if not await redis.set(f"urge:cd:{order_no}", 1,
                               ex=URGE_COOLDOWN_SECONDS, nx=True):
            raise HTTPException(429, "刚催过了,3 分钟后可以再催")
        times = await redis.incr(f"urge:count:{order_no}")
        if times == 1:
            await redis.expire(f"urge:count:{order_no}", 86400)
        if times > URGE_MAX_TIMES:
            raise HTTPException(429, "每单最多催 3 次;着急的话可以电话联系商家或骑手")
    except HTTPException:
        raise
    except Exception:
        times = 1

    # 催单对象:未出餐 → 商家;已取餐 → 骑手;
    # READY 有骑手 → 骑手(快去取餐),没骑手 → 商家知悉(等骑手接单)
    if order.status == OrderStatus.PICKED_UP or (
            order.status == OrderStatus.READY and order.rider_id is not None):
        target = "rider"
    else:
        target = "merchant"

    await _record_event(db, order, order.status.value, "urged", user)
    await db.commit()

    tail = order.order_no[-6:]
    if target == "rider" and order.rider_id is not None:
        await push_to_user(order.rider_id, "用户催单",
                           f"订单#{tail} 用户在催了,辛苦快一点,注意安全",
                           {"type": "order", "order_no": order.order_no})
    else:
        shop = await db.get(Merchant, order.merchant_id)
        if shop:
            await push_to_user(shop.owner_id, "用户催单",
                               f"订单#{tail} 用户催单了,可一键回复安抚",
                               {"type": "order", "order_no": order.order_no})
        # 商家端前台:WS 横幅 + 语音(与新单同通道)
        await manager.broadcast(
            f"merchant:{order.merchant_id}",
            {"type": "urge", "order_no": order.order_no,
             "summary": "、".join(f"{i['name']}×{i['quantity']}"
                                  for i in order.items)})
    return {"target": target, "times_used": min(times, URGE_MAX_TIMES),
            "times_left": max(0, URGE_MAX_TIMES - times)}


@router.post("/{order_no}/urge-reply", response_model=OrderOut)
async def urge_reply(
    order_no: str,
    payload: dict,
    user: User = Depends(require_role("merchant")),
    db: AsyncSession = Depends(get_db),
):
    """商家一键回复催单(马上好/高峰期稍等等预设话术),推送给用户。"""
    text_reply = (payload.get("text") or "").strip()
    if not (1 <= len(text_reply) <= 50):
        raise HTTPException(422, "回复内容 1-50 字")
    order = await db.scalar(select(Order).where(Order.order_no == order_no))
    if order is None:
        raise HTTPException(404, "订单不存在")
    shop = await db.scalar(select(Merchant).where(Merchant.owner_id == user.id))
    if shop is None or order.merchant_id != shop.id:
        raise HTTPException(403, "这不是你店里的订单")
    urged = await db.scalar(
        select(OrderEvent.id).where(OrderEvent.order_id == order.id,
                                    OrderEvent.to_status == "urged").limit(1))
    if urged is None:
        raise HTTPException(409, "该订单没有催单记录")
    await _record_event(db, order, order.status.value, "urge_reply", user)
    await db.commit()
    await push_to_user(order.customer_id, f"商家回复:{text_reply}",
                       f"「{shop.name}」回复了你的催单",
                       {"type": "order", "order_no": order.order_no})
    return order_out(order, shop, user)


@router.post("/{order_no}/pickup-verify", response_model=OrderOut)
async def pickup_verify(
    order_no: str,
    payload: PickupVerifyIn,
    user: User = Depends(require_role("merchant")),
    db: AsyncSession = Depends(get_db),
):
    """自取单核销:商家核对用户报的取餐码 → 订单完成并结算。

    只有出餐后(READY)才能核销——防止手滑把还没做的单直接完成。
    """
    order = await db.scalar(
        select(Order).where(Order.order_no == order_no).with_for_update())
    if order is None:
        raise HTTPException(404, "订单不存在")
    merchant = await db.scalar(
        select(Merchant).where(Merchant.id == order.merchant_id))
    if merchant is None or merchant.owner_id != user.id:
        raise HTTPException(403, "这不是你店里的订单")
    if not order.pickup:
        raise HTTPException(409, "这不是自取单")
    if order.status != OrderStatus.READY:
        raise HTTPException(409, "先出餐(状态改为待取餐)再核销取餐码")
    if payload.code.strip() != order.pickup_code:
        raise HTTPException(422, "取餐码不对,请让顾客出示订单页的取餐码")

    from_status = order.status
    order.status = OrderStatus.COMPLETED
    await settle_order(db, order)
    await _record_event(db, order, from_status.value,
                        OrderStatus.COMPLETED.value, user)
    await db.commit()
    await db.refresh(order)
    await _notify(order)
    await notify_order_status(
        order.customer_id, order.order_no, STATUS_LABELS[order.status])
    return order_out(order, merchant, user)


@router.post("/{order_no}/refund-item", response_model=OrderOut)
async def refund_item(
    order_no: str,
    payload: RefundItemIn,
    user: User = Depends(require_role("merchant")),
    db: AsyncSession = Depends(get_db),
):
    """缺货部分退款:商家对某个菜品退指定份数,不用整单拒。

    只允许在「待接单/制作中」阶段操作(出餐后缺货说不过去);
    退光所有菜品 = 整单取消,配送费一并退。
    """
    shop = await db.scalar(select(Merchant).where(Merchant.owner_id == user.id))
    order = await db.scalar(
        select(Order).where(Order.order_no == order_no).with_for_update()
    )
    if shop is None or order is None or order.merchant_id != shop.id:
        raise HTTPException(404, "订单不存在")
    if order.status not in (OrderStatus.PAID, OrderStatus.ACCEPTED):
        raise HTTPException(409, "只有待接单/制作中的订单可以缺货退款")

    # 在快照里找到这个菜(跳过 0 元赠品行:无款可退,也不该被当缺货退)
    items = [dict(i) for i in order.items]  # 拷贝重建,JSONB 才能检测到变更
    target = next((i for i in items
                   if i["dish_id"] == payload.dish_id
                   and i.get("price_cents", 0) > 0), None)
    if target is None:
        if any(i["dish_id"] == payload.dish_id for i in items):
            raise HTTPException(422, "赠品行不支持退款(0 元无款可退);赠品缺货请联系顾客说明")
        raise HTTPException(404, "订单里没有这个菜品")
    if payload.quantity > target["quantity"]:
        raise HTTPException(422, f"最多可退 {target['quantity']} 份")

    refund_amount = target["price_cents"] * payload.quantity
    note_piece = f"{target['name']}×{payload.quantity}"

    # 库存回补
    await db.execute(
        update(Dish)
        .where(Dish.id == payload.dish_id)
        .values(stock=Dish.stock + payload.quantity)
    )

    target["quantity"] -= payload.quantity
    items = [i for i in items if i["quantity"] > 0]

    # 付费菜全退光 = 整单取消(只剩赠品行不算"还有菜"——赠品库存一并回补)
    if not any(i.get("price_cents", 0) > 0 for i in items):
        for gift in items:
            await db.execute(
                update(Dish)
                .where(Dish.id == gift["dish_id"])
                .values(stock=Dish.stock + gift["quantity"])
            )
        # 全退光:整单取消,退掉用户实付的剩余全部(打包/配送/扣除过的优惠都按实付口径)
        refund_amount = order.total_cents
        order.items = []
        order.food_cents = 0
        order.packing_fee_cents = 0
        order.discount_cents = 0
        order.subsidy_cents = 0
        order.total_cents = 0
        order.commission_cents = 0
        order.refund_cents += refund_amount
        order.refund_note = (
            f"{order.refund_note};{note_piece}" if order.refund_note else note_piece
        )
        from_status = order.status
        order.status = OrderStatus.CANCELLED
        order.cancel_reason = "商家缺货,整单退款"
        from ..services.eta import release_coupon
        await release_coupon(db, order.order_no)
        await _record_event(db, order, from_status.value, OrderStatus.CANCELLED.value, user)
    else:
        order.items = items
        order.food_cents -= refund_amount
        order.total_cents -= refund_amount
        # 满减/首单立减不回收(对用户友好,成本各自认);佣金按新的实收口径重算
        gross = max(order.food_cents + order.packing_fee_cents - order.discount_cents, 0)
        order.commission_cents = int(Decimal(gross) * shop.commission_rate)
        order.refund_cents += refund_amount
        order.refund_note = (
            f"{order.refund_note};{note_piece}" if order.refund_note else note_piece
        )
        await _record_event(db, order, order.status.value, "partial_refund", user)

    await request_refund(db, order, refund_amount, f"缺货退款:{note_piece}")
    await db.commit()
    await db.refresh(order)
    await _notify(order)
    await notify_order_status(
        order.customer_id, order.order_no,
        f"缺货退款 ¥{refund_amount / 100:.2f}{note_piece}",
    )
    return order_out(order, shop, user)


@router.get("/delivery-fee")
async def preview_delivery_fee(
    merchant_id: int,
    lat: float,
    lng: float,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """下单前预览配送费(点单页选完地址就能展示)。

    返回组成明细:base 距离阶梯 / night 夜间加价 / weather 恶劣天气加价,
    全部归骑手;in_range=false 表示超出配送半径,下单会被拒。
    """
    merchant = await db.get(Merchant, merchant_id)
    if merchant is None:
        raise HTTPException(404, "商家不存在")
    distance = haversine_m(merchant.lat, merchant.lng, lat, lng)
    parts = delivery_fee_parts(distance, weather_on=await weather_surcharge_on(db))
    return {
        "distance_m": round(distance),
        "fee_cents": sum(parts.values()),
        "parts": parts,
        "in_range": in_delivery_range(distance),
    }


@router.get("", response_model=list[OrderOut])
async def my_orders(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """按角色返回各自视角的订单列表。"""
    query = select(Order).order_by(Order.created_at.desc()).limit(50)
    role = user.role.value
    if role == "customer":
        query = query.where(Order.customer_id == user.id)
    elif role == "rider":
        query = query.where(Order.rider_id == user.id)
    else:
        # 店主或店员都能看本店订单(店员据此听单)
        from ..services.staff import operable_shop
        shop, _ = await operable_shop(db, user)
        if shop is None:
            return []
        query = query.where(Order.merchant_id == shop.id)
    result = await db.scalars(query)
    return await orders_out(db, list(result), user)


@router.get("/{order_no}", response_model=OrderOut)
async def get_order(
    order_no: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    order = await db.scalar(select(Order).where(Order.order_no == order_no))
    if order is None:
        raise HTTPException(404, "订单不存在")
    merchant = await db.get(Merchant, order.merchant_id)
    out = order_out(order, merchant, user)
    # 详情页专属:联系电话(用户联系骑手/商家,一键拨号)
    if order.rider_id:
        rider = await db.get(User, order.rider_id)
        if rider:
            out.rider_name = rider.name
            out.rider_phone = rider.phone
    if merchant:
        owner = await db.get(User, merchant.owner_id)
        if owner:
            out.merchant_phone = owner.phone
    return out


@router.get("/{order_no}/events", response_model=list[OrderEventOut])
async def order_events(
    order_no: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """订单状态时间轴(几点几分接单/取餐/送达),订单追踪页用。"""
    order = await db.scalar(select(Order).where(Order.order_no == order_no))
    if order is None:
        raise HTTPException(404, "订单不存在")
    result = await db.scalars(
        select(OrderEvent)
        .where(OrderEvent.order_id == order.id)
        .order_by(OrderEvent.created_at)
    )
    return list(result)


@router.get("/{order_no}/refunds")
async def order_refunds(
    order_no: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """本单退款流水(退款进度可视化):每笔退款的金额/通道/状态/时间。

    mock 通道即时到账;微信通道受理后 1-3 个工作日原路退回,
    客户端据 status 画时间轴,用户不用反复问"钱呢"。
    """
    from ..models import Refund

    order = await db.scalar(select(Order).where(Order.order_no == order_no))
    if order is None or (user.role.value == "customer"
                         and order.customer_id != user.id):
        raise HTTPException(404, "订单不存在")
    rows = await db.scalars(
        select(Refund).where(Refund.order_id == order.id)
        .order_by(Refund.created_at))
    return [{"amount_cents": r.amount_cents, "reason": r.reason,
             "channel": r.channel, "status": r.status.value,
             "created_at": r.created_at} for r in rows]


@router.get("/{order_no}/rider-location", response_model=RiderLocationOut)
async def rider_location(
    order_no: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    order = await db.scalar(select(Order).where(Order.order_no == order_no))
    if order is None or order.rider_id is None:
        raise HTTPException(404, "订单不存在或还没有骑手接单")
    # 归属校验:只有下单用户本人、该单骑手、管理员能看骑手位置
    if user.id not in (order.customer_id, order.rider_id) \
            and user.role.value != "admin":
        raise HTTPException(403, "无权查看该订单")
    # 隐私最小化:订单终结后不再暴露骑手实时位置
    if order.status in (OrderStatus.COMPLETED, OrderStatus.CANCELLED):
        return RiderLocationOut(rider_id=order.rider_id, lat=None, lng=None,
                                updated_at=None)
    redis = get_redis()
    loc = await redis.hgetall(RIDER_LOC_KEY.format(rider_id=order.rider_id))
    return RiderLocationOut(
        rider_id=order.rider_id,
        lat=float(loc["lat"]) if loc.get("lat") else None,
        lng=float(loc["lng"]) if loc.get("lng") else None,
        updated_at=float(loc["ts"]) if loc.get("ts") else None,
    )


# ---------- 订单内聊天(用户↔骑手 / 用户↔商家) ----------

_CHAT_READONLY_HOURS = 2   # 订单终结后只读
_CHAT_HIDE_DAYS = 7        # 之后当事人不可见(留档供仲裁)
_TERMINAL = (OrderStatus.COMPLETED, OrderStatus.CANCELLED)


async def _chat_context(db, order_no: str, user: User):
    """校验当事人身份,返回 (order, my_role, 可聊的对端集合)。"""
    order = await db.scalar(select(Order).where(Order.order_no == order_no))
    if order is None:
        raise HTTPException(404, "订单不存在")
    role = user.role.value
    if role == "customer":
        if order.customer_id != user.id:
            raise HTTPException(403, "这不是你的订单")
        peers = {"merchant"} | ({"rider"} if order.rider_id else set())
    elif role == "rider":
        if order.rider_id != user.id:
            raise HTTPException(403, "这不是你接的订单")
        peers = {"customer"}
    elif role == "merchant":
        shop = await db.scalar(
            select(Merchant).where(Merchant.owner_id == user.id))
        if shop is None or order.merchant_id != shop.id:
            raise HTTPException(403, "这不是你店里的订单")
        peers = {"customer"}
    else:
        raise HTTPException(403, "客服查看请走管理后台")
    return order, role, peers


def _chat_age_hours(order: Order) -> float | None:
    """订单终结后经过的小时数;未终结返回 None。"""
    if order.status not in _TERMINAL:
        return None
    updated = order.updated_at or order.created_at
    if updated.tzinfo is None:
        updated = updated.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - updated).total_seconds() / 3600


@router.post("/{order_no}/messages")
async def send_message(
    order_no: str,
    payload: dict,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """发消息。text 过敏感词;quick 为预设快捷语;image 传图片 URL。"""
    from ..models import Message

    order, role, peers = await _chat_context(db, order_no, user)
    to = str(payload.get("to", "")) or next(iter(peers))
    if to not in peers:
        raise HTTPException(422, "只能给这单的商家/骑手/顾客发消息")
    if order.status == OrderStatus.PENDING_PAYMENT:
        raise HTTPException(409, "订单支付后才能发起聊天")
    age = _chat_age_hours(order)
    if age is not None and age >= _CHAT_READONLY_HOURS:
        raise HTTPException(
            409, "订单已结束,会话已转只读;有问题请走售后或客服工单")
    kind = str(payload.get("kind", "text"))
    if kind not in ("text", "image", "quick"):
        raise HTTPException(422, "kind 只支持 text / image / quick")
    content = str(payload.get("content", "")).strip()[:500]
    if not content:
        raise HTTPException(422, "消息不能为空")
    if kind in ("text", "quick"):
        from ..services.moderation import guard_text
        await guard_text(db, content, "聊天消息")

    msg = Message(order_id=order.id, sender_id=user.id, sender_role=role,
                  receiver_role=to, kind=kind, content=content)
    db.add(msg)
    await db.commit()
    await db.refresh(msg)

    # 未读数(Redis)+ WS 即达 + 离线推送
    receiver_id = (order.customer_id if to == "customer"
                   else order.rider_id if to == "rider" else None)
    if to == "merchant":
        shop = await db.get(Merchant, order.merchant_id)
        receiver_id = shop.owner_id if shop else None
    redis = get_redis()
    if receiver_id:
        await redis.incr(f"chat:unread:{order.id}:{receiver_id}")
        await redis.expire(f"chat:unread:{order.id}:{receiver_id}", 604800)
    await manager.broadcast(f"chat:{order.order_no}", {
        "type": "chat", "order_no": order.order_no, "id": msg.id,
        "from": role, "to": to, "kind": kind, "content": content,
    })
    if receiver_id:
        try:
            preview = "[图片]" if kind == "image" else content[:40]
            await push_to_user(receiver_id, "订单消息",
                               f"订单#{order.order_no[-6:]}:{preview}",
                               {"type": "chat", "order_no": order.order_no})
        except Exception:
            pass
    return {"id": msg.id, "created_at": msg.created_at.isoformat()}


@router.get("/{order_no}/messages")
async def list_messages(
    order_no: str,
    peer: str = "",
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """拉会话(轮询兜底)。读取即清零自己的未读数。"""
    from ..models import Message

    order, role, peers = await _chat_context(db, order_no, user)
    age = _chat_age_hours(order)
    if age is not None and age >= _CHAT_HIDE_DAYS * 24:
        raise HTTPException(403, "会话已归档(超过 7 天);如需调取请联系客服")
    peer = peer or next(iter(peers))
    if peer not in peers:
        raise HTTPException(422, "没有这条会话")
    pair = {role, peer}
    rows = (await db.scalars(
        select(Message).where(Message.order_id == order.id)
        .order_by(Message.created_at).limit(200))).all()
    await get_redis().delete(f"chat:unread:{order.id}:{user.id}")
    return {
        "readonly": age is not None and age >= _CHAT_READONLY_HOURS,
        "messages": [{
            "id": m.id, "from": m.sender_role, "kind": m.kind,
            "content": m.content, "mine": m.sender_id == user.id,
            "created_at": m.created_at.isoformat(),
        } for m in rows
            if {m.sender_role, m.receiver_role} == pair],
    }


@router.get("/{order_no}/unread")
async def unread_count(
    order_no: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    order, _, _ = await _chat_context(db, order_no, user)
    n = await get_redis().get(f"chat:unread:{order.id}:{user.id}")
    return {"unread": int(n or 0)}


# ---------- 地址保护:临时放行 / 地址反馈 ----------

@router.post("/{order_no}/reveal-address", response_model=OrderOut)
async def reveal_address(
    order_no: str,
    user: User = Depends(require_role("customer")),
    db: AsyncSession = Depends(get_db),
):
    """临时放行完整门牌(骑手到楼下后,用户不想下楼取时点)。只对本单生效。"""
    order = await db.scalar(
        select(Order).where(Order.order_no == order_no).with_for_update())
    if order is None or order.customer_id != user.id:
        raise HTTPException(404, "订单不存在")
    if not order.addr_protect:
        raise HTTPException(409, "该订单未开启地址保护,无需放行")
    if order.addr_revealed:
        return order_out(order, await db.get(Merchant, order.merchant_id), user)
    order.addr_revealed = True
    await _record_event(db, order, order.status.value, "addr_revealed", user,
                        note="用户临时放行完整门牌")
    await db.commit()
    await db.refresh(order)
    if order.rider_id:
        await push_to_user(order.rider_id, "地址已放行",
                           f"订单#{order.order_no[-6:]} 顾客放行了完整门牌,"
                           "刷新订单可见", {"type": "order"})
    await manager.broadcast(f"order:{order.order_no}", {
        "type": "addr_revealed", "order_no": order.order_no})
    return order_out(order, await db.get(Merchant, order.merchant_id), user)


@router.post("/{order_no}/address-feedback")
async def address_feedback(
    order_no: str,
    payload: dict,
    user: User = Depends(require_role("rider")),
    db: AsyncSession = Depends(get_db),
):
    """骑手反馈「地址不准」(每单一条):只沉淀不追责,
    同一地址攒 2 条后用户下次下单会收到核对提示。"""
    from ..models import AddressFeedback
    order = await db.scalar(select(Order).where(Order.order_no == order_no))
    if order is None or order.rider_id != user.id:
        raise HTTPException(403, "这不是你接的订单")
    existing = await db.scalar(select(AddressFeedback.id).where(
        AddressFeedback.order_no == order_no))
    if existing:
        raise HTTPException(409, "这单已经反馈过了")
    db.add(AddressFeedback(
        customer_id=order.customer_id, address=order.address,
        order_no=order_no, rider_id=user.id,
        note=str(payload.get("note", "")).strip()[:200]))
    await db.commit()
    return {"ok": True}
