import logging
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import false, func, or_, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..db import get_db
from ..models import (Dish, Merchant, MerchantStatus, Order, OrderEvent,
                      Review, User)
from ..ratelimit import check_rate_limit
from ..redis_client import RIDER_LOC_KEY, get_redis
from ..schemas import (
    BoostTipIn,
    CancelSplitIn,
    ChangeAddressIn,
    HardshipIn,
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
from ..services.pricing import (delivery_fee_parts, haversine_m,
                                in_delivery_range)

# 配送费拆分项的中文名。**放服务端,四端共用一份** ——
# 三个客户端各写一遍,迟早写得不一样,而这是要给顾客看的账
FEE_PART_LABELS = {
    "base": "基础配送费",
    "night": "夜间配送",
    "weather": "恶劣天气",
    "door": "上门难度(无电梯高楼层)",
    # 骑手实地反馈过的难度(#301)。名字里带"骑手反馈"是刻意的:
    # 顾客要知道这不是平台拍脑袋加的,是跑过这个地址的人说的
    "hardship": "骑手反馈的实地难度",
    "wait": "等餐补偿",
}
from ..services.privacy_phone import dialable_phone, mask_phone
from ..services.push import (fanout_order_status,
                             notify_order_status, push_to_user)
from ..services.routing import billing_distance_m
from ..services.settlement import settle_order
from ..services.wechat_pay import request_refund
from ..state_machine import STATUS_LABELS
from ..state_machine import OrderStatus, TransitionError, assert_transition
from ..ws import manager
from ..services.staff import owned_shop

logger = logging.getLogger("superz.orders")


def _coupon_label(source: str) -> str:
    """给用户看的券名。按发放来源认,不是按资金方认。

    资金方(platform/merchant)是记账用的分类,对用户没有意义 ——
    他记得的是"平台赔我的那张"、"收藏店铺送的那张"。
    认不出来的券名会让减免看着像凭空冒出来的,反而不放心。
    """
    for prefix, label in (
        ("eta:", "超时安抚券"),
        ("favorite:", "收藏有礼券"),
        ("batch:", "平台活动券"),
        ("shop:", "店铺券"),
    ):
        if source.startswith(prefix):
            return label
    return "平台券"

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


def coarse_address(order: Order) -> str:
    """粗地址:登记了 POI/小区就用它,否则把结尾那段门牌替换掉。

    坐标不动 —— 骑手要导航,能定位到楼下不等于知道住哪个门。
    """
    import re as _re
    return (order.addr_public
            or _re.sub(r"\d[\d\-室号门栋单元楼层a-zA-Z]*$",
                       "***", order.address).strip() + " ***")


def short_name(order: Order) -> str:
    """中性称呼:下单时填的称谓 > 只留姓 > 「顾客」。"""
    if order.salutation:
        return order.salutation
    if order.addr_protect:
        return "顾客"
    name = (order.contact_name or "").strip()
    return f"{name[0]}**" if name else "顾客"


def order_out(order: Order, merchant: Merchant | None,
              viewer: User | None = None, *,
              as_role: str | None = None,
              has_review: bool = False,
              urge_count: int = 0) -> OrderOut:
    """订单 + 商家取餐点信息。骑手端地图/导航需要知道店在哪。

    电话脱敏:商家/骑手视角 contact_phone 一律打码,可拨号码走 privacy_phone
    (X 号 > 过渡期真号 > 严格模式空)。用户本人与管理后台看真号。

    [as_role] 给**没有 User 对象但视角明确**的调用方用(如 POS 开放接口:
    认证走 API Key,没有登录用户)。不给它就等于走"用户本人"的全量口径 ——
    脱敏是一整块,漏传一次就是门牌和真名一起下发出去。
    """
    out = OrderOut.model_validate(order)
    out.has_review = has_review
    out.urge_count = urge_count
    # 拆分项的中文名跟着数一起给 —— 客户端不用各写一份映射
    if out.fee_parts:
        out.fee_part_labels = {k: FEE_PART_LABELS[k]
                               for k in out.fee_parts
                               if k in FEE_PART_LABELS}
    out.no_rider_alerted = order.no_rider_alerted_at is not None
    # 取件点统一走访问器:外卖是那家店,跑腿是订单自带的地址。
    # 各处自己读 merchant.lat/lng 的话,跑腿单会把骑手导到那个
    # 虚拟服务主体的坐标去(见 services/errand)
    from ..services.errand import pickup_point
    point = pickup_point(order, merchant)
    if point.lat is not None or point.name:
        out.merchant_name = point.name
        out.merchant_address = point.address
        out.merchant_lat = point.lat
        out.merchant_lng = point.lng
    role = as_role or (viewer.role.value if viewer is not None else None)
    if role in ("merchant", "rider"):
        # 骑手侧再分一层:**这一单的骑手**才拿得到联系方式和门牌。
        #
        # 抢单池里的单 rider_id 是空的 —— 谁都不是它的骑手。原先这里只看
        # role 就下发 dialable_phone,于是骑手只要轮询 /available-orders、
        # 一单都不接,就能拿到全城顾客的完整手机号 + 完整门牌 + 真名。
        # 而没接单的人本来就不需要联系顾客:抢到之后再给全,业务上也是对的。
        assigned = role != "rider" or (
            viewer is not None and order.rider_id == viewer.id)
        out.privacy_phone = dialable_phone(order) if assigned else ""
        out.contact_phone = mask_phone(order.contact_phone)
        # 地址保护:未放行前只给粗地址(POI/小区),门牌详情不下发;
        # 收货人一律中性称呼。坐标保留(导航要用,门牌才是敏感面)
        if not assigned or (order.addr_protect and not order.addr_revealed):
            out.address = coarse_address(order)
        if not assigned or order.addr_protect:
            out.contact_name = short_name(order)
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
    # 一次查完再进循环。写成 `o.id in await _reviewed_ids(...)` 的话
    # 每个订单各发一条 SQL —— 那正是这个字段要消灭的东西
    reviewed = await _reviewed_ids(db, orders)
    urges = await _urge_counts(db, orders)
    return [
        order_out(o, merchants.get(o.merchant_id), viewer,
                  has_review=o.id in reviewed,
                  urge_count=urges.get(o.id, 0))
        for o in orders
    ]


async def _urge_counts(db: AsyncSession,
                       orders: list[Order]) -> dict[int, int]:
    """这批单里各被催了几次。**一次查完,不是一单一查。**

    只查进行中的单:历史单显示"曾被催过"没有任何动作可接,
    白扫一遍事件表。一单进行中的都没有就连查询都不发。
    """
    live = [o.id for o in orders if o.status in URGEABLE]
    if not live:
        return {}
    rows = await db.execute(
        select(OrderEvent.order_id, func.count())
        .where(OrderEvent.order_id.in_(live),
               OrderEvent.to_status == "urged")
        .group_by(OrderEvent.order_id))
    return dict(rows.all())


async def _reviewed_ids(db: AsyncSession, orders: list[Order]) -> set[int]:
    """这批单里哪些已经评过。**一次查完,不是一单一查。**

    只查已完成的单:别的状态本来就不能评(见 reviews.py 的 409),
    把它们也塞进 IN 里只是让索引白扫一遍。
    一单都没完成时直接返回空集,连查询都不发。
    """
    done = [o.id for o in orders if o.status == OrderStatus.COMPLETED]
    if not done:
        return set()
    return set(await db.scalars(
        select(Review.order_id).where(Review.order_id.in_(done))))


async def may_view_order(db: AsyncSession, order: Order, user: User) -> bool:
    """这个人是不是这一单的当事人。四种角色各有各的范围:

    - 顾客:本人下的单;
    - 商家:该单所属门店(含店员、含品牌里被授权到这家店的成员);
    - 骑手:接了这一单的那个骑手;
    - admin:全部(客服要查)。

    口径与 self_refund_check / urge_order / rider_location 一致 ——
    那几个从一开始就写对了,这里只是把同一条判断收敛成一个函数,
    免得下一个只读端点又忘一次。
    """
    role = user.role.value
    if role == "admin":
        return True
    if role == "customer":
        return order.customer_id == user.id
    if role == "rider":
        return order.rider_id == user.id
    if role == "merchant":
        from ..services.staff import operable_shop
        # 显式传本单的 merchant_id:不传的话走 X-Shop-Id / "我唯一的那家店",
        # 连锁老板没选门店时会把自己家的单判成看不了
        shop, _ = await operable_shop(db, user, order.merchant_id)
        return shop is not None and shop.id == order.merchant_id
    return False


async def visible_order_or_404(db: AsyncSession, order_no: str,
                               user: User) -> Order:
    """按归属取单;不是当事人就当它不存在。

    **404 而不是 403**:订单号是可枚举的(20 位 hex 不算,但历史短号在),
    403 等于确认"这个单号存在",而这里没有任何理由把这件事告诉外人。
    """
    order = await db.scalar(select(Order).where(Order.order_no == order_no))
    if order is None or not await may_view_order(db, order, user):
        raise HTTPException(404, "订单不存在")
    return order


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
    # 菜品级打包费的累计额(在店铺每单打包费之外另加)
    extra_packing = 0
    for item in payload.items:
        result = await db.execute(
            update(Dish)
            .where(
                Dish.id == item.dish_id,
                Dish.merchant_id == merchant.id,
                Dish.is_on_sale.is_(True),
                # 估清(今日售罄)是**下单闸门**,不是"库存刚好是 0"的同义词。
                # 少了这个条件,任何一条回补库存的路径(缺货退款、取消回补)
                # 都会让估清的菜在商家不知情的情况下复活 —— 下面那段
                # 三分文案里专门有一支报「今日已售罄」,说明闸门本来就该看它。
                # 解除估清只有商家点「撤销估清」和次日 04:00 自动恢复两条路
                Dish.sold_out_today.is_(False),
                Dish.stock >= item.quantity,
            )
            .values(stock=Dish.stock - item.quantity)
            .returning(Dish.name, Dish.price_cents, Dish.options,
                       Dish.flash_price_cents, Dish.flash_until,
                       Dish.is_alcohol, Dish.serve_window, Dish.combo_items,
                       Dish.packing_fee_cents)
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
            dish_is_alcohol, serve_window, combo_items, \
            dish_packing = row
        # 菜品级打包费:**在店铺「每单打包费」之外另加**,按份数累计。
        #
        # 为什么是"另加"而不是"替代":店铺那个是每单一次的费用,
        # 改成按份数算会让**所有没设过菜品打包费的商家**在一夜之间
        # 涨价(3 份菜就收 3 倍) —— 这种静默涨价谁都受不了。
        # None = 没单独设过,不加钱;0 是合法取值,意思是"这道菜不额外收"。
        if dish_packing:
            extra_packing += dish_packing * item.quantity
        # 分时段供应:菜单里非供应时段是灰态可见的(不消失,免得用户以为没这道菜),
        # 真正的闸门在这里 —— 前端灰态挡不住直接调接口
        # in_hhmm_range 已在模块顶部导入 —— **不能在这里再 import 一次**:
        # 函数体内的 import 会让这个名字变成整个函数的局部变量,
        # 把函数开头(宵禁/酒类禁售)那两处早于此行的调用打成 UnboundLocalError
        if serve_window:
            now_bj = (datetime.now(timezone.utc)
                      + timedelta(hours=8)).strftime("%H:%M")
            if not in_hhmm_range(serve_window, now_bj):
                await db.rollback()
                raise HTTPException(
                    409, f"「{name}」仅 {serve_window} 供应")
        # 套餐:逐个子项扣库存(复用同一条条件 UPDATE 的形状)。
        # 任一子项不够就整单回滚 —— 套餐少一样东西送出去,顾客的体验
        # 比缺货退款更差
        if combo_items:
            # **按 dish_id 排序后再逐个上锁**:两个套餐共用食材但
            # combo_items 的顺序相反时(P=[X,Y]、Q=[Y,X]),并发下单
            # 会两两互等成死锁 —— 实测 18 单挂 3 单,顾客直接吃 500。
            # 顺序由商家配菜时的点选顺序决定,用户根本无从规避
            for sub in sorted(combo_items,
                              key=lambda s: s.get("dish_id") or 0):
                sub_qty = int(sub.get("quantity", 1)) * item.quantity
                sub_result = await db.execute(
                    update(Dish)
                    .where(
                        Dish.id == sub.get("dish_id"),
                        Dish.merchant_id == merchant.id,
                        Dish.is_on_sale.is_(True),
                        Dish.sold_out_today.is_(False),   # 同主项:估清即闸门
                        Dish.stock >= sub_qty,
                    )
                    .values(stock=Dish.stock - sub_qty)
                    .returning(Dish.name)
                )
                sub_row = sub_result.first()
                if sub_row is None:
                    # 与主项同款的精确三分文案:说"不够了"但其实是下架,
                    # 商家照着补货补半天也不管用
                    sub_dish = await db.get(Dish, sub.get("dish_id"))
                    if sub_dish is None:
                        why = "已不存在"
                    elif sub_dish.sold_out_today:
                        why = "今日已售罄"
                    elif not sub_dish.is_on_sale:
                        why = "已下架"
                    else:
                        why = f"库存不足(剩 {sub_dish.stock} 份)"
                    sub_name = sub_dish.name if sub_dish else "套餐内菜品"
                    await db.rollback()
                    raise HTTPException(
                        409, f"「{name}」里的「{sub_name}」{why},换一个吧")
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
        if combo_items:
            # 套餐仍是**一行**(账目口径零影响),但带上子项明细 ——
            # 后厨看的是"要做哪几样",不是套餐名。
            # **dish_id 必须存**:取消/退款回补库存只认快照,
            # 没有 id 就只能补套餐自己,子项库存会凭空蒸发
            names = {
                r[0]: r[1] for r in (await db.execute(
                    select(Dish.id, Dish.name).where(
                        Dish.id.in_([s.get("dish_id") for s in combo_items]),
                        # 纵深防御:子项写入时已钉死在本店,读时再钉一次
                        Dish.merchant_id == merchant.id))).all()
            }
            snapshot_entry["combo"] = [
                {"dish_id": s.get("dish_id"),
                 "name": names.get(s.get("dish_id"), ""),
                 "quantity": int(s.get("quantity", 1))}
                for s in combo_items]
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
    distance_source = ""
    hardship_note = ""
    if parent is not None:
        distance_m = 0.0  # 地址随原单,半径在原单已校验
    elif payload.pickup:
        distance_m = 0.0
    else:
        if not payload.address or payload.lat is None or payload.lng is None:
            await db.rollback()
            raise HTTPException(422, "请先选择收货地址")
        # 计价距离走**腾讯骑行路网**,不是直线(#300)。
        #
        # 配送费一分不少全归骑手,所以这个数直接就是他的收入。
        # 直线永远 ≤ 实际要骑的路(几何决定的,不是估算误差),实测成都
        # 样本差 19% —— 而计价按整公里分档,19% 在 2–4km 区间经常正好
        # 差一整档,每单少 1 块钱,一天 30 单就是 30 块。单边的少付。
        #
        # ⚠️ **配送半径仍按直线判**,只有计价用路网。
        #
        # 一度改成两边都用路网,理由是"直线 3.9km 在范围内、实际骑行
        # 4.6km 已经超了,骑手垫了中间那段"。这个理由**是错的**:
        # 配送费封顶 ¥10,要骑到 9 公里才碰得到 —— 计价换成路网之后,
        # 4.6km 的单本来就按 4.6km 付钱,骑手没有垫任何东西。
        #
        # 而路网判范围有个真实代价:附近商家列表的半径是 PostGIS
        # **球面直线**(merchants.py 的 _radius_cap),算不了路网。
        # 两边尺子不一样,用户就会看见一家店、点进去、下单被拒 ——
        # 「看得见点不了」比「看不见」更伤人,而且他不知道为什么。
        #
        # 所以:钱按实际骑的路算(骑手的收入不能少),
        # 范围按看得见的那把尺子算(用户看到的和能点的一致)。
        straight_m = haversine_m(merchant.lat, merchant.lng,
                                 payload.lat, payload.lng)
        if not in_delivery_range(straight_m):
            await db.rollback()
            raise HTTPException(
                409, f"超出配送范围({settings.delivery_max_km:g}km),换家近点的店吧")
        # 计价距离走**腾讯骑行路网**(#300)。配送费一分不少全归骑手,
        # 所以这个数直接就是他的收入。直线永远 ≤ 实际要骑的路
        # (几何决定的,不是估算误差),实测成都样本差 19–42% ——
        # 而计价按整公里分档,经常正好差一整档,每单少 1 块钱。
        distance_m, distance_source = await billing_distance_m(
            merchant.lat, merchant.lng, payload.lat, payload.lng)

    # 店铺「每单打包费」+ 各菜品自己的额外打包费(按份数)。
    # 没有任何菜品设过额外打包费时,这里与加这个功能之前一字不差
    packing = merchant.packing_fee_cents + extra_packing
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
    # 券是否真的抵到了钱。平台券在 coupon_off 被钳成 0 时(前面的立减/满减
    # 已经把可抵金额吃光)一分没减,那种情况下不能把券烧掉
    coupon_applied = False
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
            coupon_applied = True
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
                coupon_applied = True
                # 券名要说清是**哪一张**(#296)。
                #
                # 原来一律写「平台券-3元」:用户被超时赔付时收到的通知
                # 说的是「安抚券」,订单上却写「平台券」—— 他认不出这
                # 就是平台答应赔他的那张,只会觉得凭空多了个没头没尾的减免。
                # 名字对不上号的补偿,等于没补偿。
                notes.append(
                    f"{_coupon_label(coupon.source)}-{coupon_off / 100:g}元(平台)")

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
    # 三条分支都要给 fee_parts 赋值 —— 只在配送分支里赋,
    # 追加单和自取单走到下面引用时就是 UnboundLocalError(整条下单路径 500)
    fee_parts: dict[str, int] = {}
    if parent is not None:
        fee_cents = 0
        notes.append(f"追加到订单#{parent.order_no[-6:]},随原单配送免配送费")
    elif payload.pickup:
        fee_cents = 0
        notes.append("到店自取,免配送费")
    else:
        # 天气按**商家坐标**判(骑手在那一带跑),不再是全局开关 ——
        # 成都下暴雨北京也加价、北京下雪没人开开关骑手白挨冻,都是全局开关的锅
        # 这个地址骑手反馈过什么(#301)。攒够共识才算数,
        # 而且**只加不减**:没有任何一条路径让这笔钱变负
        from ..services import hardship as _hs
        _cons = await _hs.address_consensus(
            db, payload.lat, payload.lng, payload.floor)
        fee_parts = delivery_fee_parts(
            distance_m,
            weather_on=await weather_surcharge_on(
                db, merchant.lat, merchant.lng),
            floor=payload.floor, has_elevator=payload.has_elevator,
            to_door=payload.to_door,
            hardship_cents=_hs.comp_cents(
                _cons["kinds"], _cons["floors"], _cons["walk_m"]))
        # 骑手接单前要看到的是**什么难**,不只是多了几块钱。
        # 只说金额,他还是要骑到楼下才知道是六楼没电梯
        hardship_note = "；".join(
            _hs.HARDSHIP_LABELS[k][0]
            + (f"{_cons['floors']}楼"
               if k == "no_elevator" and _cons["floors"] else "")
            + (f"约{_cons['walk_m']}米"
               if k == "walk_in" and _cons["walk_m"] else "")
            for k in _cons["kinds"])[:200]
        fee_cents = sum(fee_parts.values())
        if fee_parts["night"]:
            notes.append(f"夜间配送+{fee_parts['night'] / 100:g}元(归骑手)")
        if fee_parts["weather"]:
            notes.append(f"恶劣天气+{fee_parts['weather'] / 100:g}元(归骑手)")
        if fee_parts["door"]:
            notes.append(
                f"{payload.floor}楼无电梯送上门+"
                f"{fee_parts['door'] / 100:g}元(归骑手)")
        if fee_parts["hardship"]:
            # 说清是**谁**说的:不是平台拍脑袋加的,是跑过这里的骑手
            notes.append(
                f"骑手反馈这里不好送+{fee_parts['hardship'] / 100:g}元(归骑手)")

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
        # 楼层快照:自取没有爬楼,追加单跟父单一致
        floor=(parent.floor if parent is not None
               else (None if payload.pickup else payload.floor)),
        # 配送费构成快照:此前这份拆分只在预览里露一次,下单后就没人看得到
        # 追加单/自取单没有配送费,拆分自然是空的
        fee_parts=fee_parts,
        # 算这笔钱**用的**距离和来源,锁进订单(#300)。
        # 配送费全归骑手,他事后要查得到「8 块钱按 3.4 公里算的,
        # 数据来自路网」—— 说不清来历的钱,给多少都不叫透明
        bill_distance_m=round(distance_m) if distance_m else None,
        bill_distance_source=distance_source,
        hardship_note=hardship_note,
        to_door=payload.to_door,
        has_elevator=(parent.has_elevator if parent is not None
                      else (None if payload.pickup
                            else payload.has_elevator)),
        lat=(parent.lat if parent is not None
             else (merchant.lat if payload.pickup else payload.lat)),
        lng=(parent.lng if parent is not None
             else (merchant.lng if payload.pickup else payload.lng)),
        contact_name=(parent.contact_name if parent is not None
                      else payload.contact_name),
        # **空了就回落到下单人的账号手机号。**
        # 骑手拨的就是这个号(privacy_phone 非严格模式直接给它),
        # 存一个空串意味着这一单一出岔子就没法收场 —— 骑手到了楼下,
        # 找不到门牌、也打不通人。而账号手机号服务端本来就有,
        # 注册时验过,回落它比要求客户端再传一遍可靠。
        contact_phone=(parent.contact_phone if parent is not None
                       else (payload.contact_phone or user.phone)),
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
    if coupon is not None and coupon_applied:
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


def mock_pay_allowed(cfg=None) -> bool:
    """模拟支付能不能用。**环境是必要条件,开关是充分条件,两个都要。**

    只看 `MOCK_PAY_ENABLED` 的话,安全性就依赖"记得在生产把它设成 false" ——
    而忘了设的后果是**任何用户白嫖下单**。默认 prod 之后,忘配的后果变成
    "本地 e2e 跑不了",那是能当场发现的。
    """
    cfg = cfg or settings
    return bool(cfg.mock_pay_enabled and cfg.is_dev)


@router.post("/{order_no}/pay/mock", response_model=OrderOut)
async def mock_pay(
    order_no: str,
    user: User = Depends(require_role("customer")),
    db: AsyncSession = Depends(get_db),
):
    """模拟支付。接微信支付后,这段逻辑原样搬进支付回调,幂等结构不变。

    生产 MOCK_PAY_ENABLED=false 封死:真实收款上线后这个口子等于白送订单。
    """
    if not mock_pay_allowed():
        # 文案要能自解释:本地/CI 撞上这条,九成是漏了 APP_ENV=dev,
        # 而不是真的要用微信支付。让人当场知道去看哪,别去翻源码
        raise HTTPException(
            403, "模拟支付已关闭,请使用微信支付"
                 "(本地或 CI 撞到这条:检查 APP_ENV=dev 与 MOCK_PAY_ENABLED)")
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
    # 送达/完成时刻落库。**法定记录**(123 号令第十五条要求如实记录送达时间,
    # 且订单信息自交易完成之日起保存不少于三年)—— 不能只靠 order_events 推
    if payload.to_status == OrderStatus.DELIVERED:
        order.delivered_at = now
        # 送达段停留时长:到收货点 → 点送达。这几分钟花在找门、等门禁、
        # 等电梯、爬楼上,是"场景难度"唯一可测量的部分。
        # 骑手没点过「我到了」就不算 —— **不猜**,猜出来的数会污染分位数,
        # 而分位数将来要拿去给别人补时
        if order.arrived_drop_at is not None:
            from ..services.drop_time import drop_key
            arrived = order.arrived_drop_at
            if arrived.tzinfo is None:
                arrived = arrived.replace(tzinfo=timezone.utc)
            order.drop_minutes = round(
                max(0.0, (now - arrived).total_seconds() / 60), 1)
            # 聚合键存快照不重算:网格算法一改,历史数据就全对不上了
            order.drop_key = drop_key(order.lat, order.lng, order.floor)
    if payload.to_status == OrderStatus.COMPLETED:
        order.completed_at = now
        if order.delivered_at is None:
            order.delivered_at = now   # 自取单没有"送达"这一步
    # 出餐瞬间定格是否超时(承诺时长口径;预约单以预约前推为基准)
    if payload.to_status == OrderStatus.READY and order.accepted_at is not None:
        shop_for_promise = (shop if role == "merchant"
                            else await db.get(Merchant, order.merchant_id))
        accepted_at = order.accepted_at
        if accepted_at.tzinfo is None:
            accepted_at = accepted_at.replace(tzinfo=timezone.utc)
        # 忙碌模式生效期出餐超时判定同步放宽(按判定时刻的忙碌状态,
        # 接单后忙碌恰好结束的边界单按常规口径,不做更细的追溯)
        promise_minutes = shop_for_promise.promise_ready_minutes + (
            shop_for_promise.busy_extra_minutes
            if shop_for_promise.busy_active else 0)
        promise = timedelta(minutes=promise_minutes)
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
    # 缺货部分退款已同步扣减 total_cents,此处余额即用户净付金额。
    # refund_cents 由 request_refund 自己累计(渠道拒绝则不累计)
    if (
        payload.to_status == OrderStatus.CANCELLED
        and from_status != OrderStatus.PENDING_PAYMENT
        and order.total_cents > 0
    ):
        refund_amount = order.total_cents
        note = f"取消退款:{order.cancel_reason}"
        await request_refund(db, order, refund_amount, note)
        order.refund_note = (
            f"{order.refund_note};{note}" if order.refund_note else note
        )
    # 取消(含未支付关单)把抵扣的券放回券包,未过期可再用
    if payload.to_status == OrderStatus.CANCELLED:
        from ..services.eta import release_coupon
        await release_coupon(db, order.order_no)
    # 出餐了就把「到店未出餐」的催单工单自动销掉(不占用同单一张 open 工单的名额)
    if payload.to_status == OrderStatus.READY:
        # 发货照:**零售必须拍,餐饮不要求**。
        #
        # 零售的纠纷是"少给了/给错了/坏的",那正是一张照片能定的事;
        # 而外卖的纠纷是"味道不对""洒了",照片帮不上,凭空多一步只是
        # 让每个快餐店每天多按几十次快门。
        #
        # ⚠️ 和跑腿的取件照(errands.upload_pickup_photo)是**有意相反**的
        # 决定。那里不强制,理由写着「骑手在楼道里手忙脚乱,卡住照片就等于
        # 卡住取件」—— 商家发货的处境不同:在自己柜台前、有平板、
        # 是每天重复几十遍的动作。两个处境,两个判断,不是其中一个漏了。
        #
        # 卡住了会怎样:订单停在 accepted。骑手照样抢得到、到得了店
        # (抢单池收 accepted 和 ready 两种),所以**不会卡死**,
        # 只是商家得把照片补上才走得到下一步。
        shop_ = (shop if role == "merchant"
                 else await db.get(Merchant, order.merchant_id))
        if shop_ is not None and shop_.biz_type == "retail":
            url = payload.photo_url.strip()
            if url:
                order.handover_photo_url = url[:300]
            if not order.handover_photo_url:
                raise HTTPException(
                    422, "发货前请拍一张商品照 —— "
                         "顾客说少给了或者拿错了的时候,这张照片替你说话")
        elif payload.photo_url.strip():
            # 餐饮商家愿意拍就存着,不拦
            order.handover_photo_url = payload.photo_url.strip()[:300]

        from ..models import DeliveryIssue
        await db.execute(
            update(DeliveryIssue)
            .where(DeliveryIssue.order_id == order.id,
                   DeliveryIssue.kind == "not_ready",
                   DeliveryIssue.status == "open")
            .values(status="resolved", resolution="continue_delivery",
                    resolve_note="商家已出餐,自动销单", resolved_at=now)
        )
    # 送达拍照留证:判据是**交付方式**,不是地址是否保护(#303)。
    #
    # 原来只有「地址保护单 + 深夜」才强制,这个判据用错了维度:
    #
    # - **当面交给顾客**:有人接了就是证据,拍照多余,而且尴尬 ——
    #   举着手机拍一个正在接餐的人,谁都不舒服;
    # - **放门口/前台/柜子**:没有人证,**照片是骑手唯一的自保**。
    #   顾客三天后说"我没收到",没有照片就是各执一词,
    #   而这种事的结果通常由平台判,判给谁都有人吃亏。
    #
    # 所以强制的对象从"保护单"改成"没当面交给人的单",
    # 深夜与否不再是判据 —— 白天放门口一样说不清。
    #
    # **这是为骑手做的,不是为平台的留证率做的。**
    # 所以当面交付一律不拦:那是在他赶时间的时候多加一道手续,
    # 收益只有一张没人会看的照片。
    if payload.to_status == OrderStatus.DELIVERED and not order.pickup:
        if payload.photo_url.strip():
            order.delivery_photo_url = payload.photo_url.strip()[:300]
        elif payload.handoff == "leave":
            raise HTTPException(
                422, "放在门口的单需要拍一张照片 —— "
                     "万一顾客说没收到,这张照片替你说话")
    # 订单完成 = 结算点:骑手配送费、商家净收入分别入账
    if payload.to_status == OrderStatus.COMPLETED:
        await settle_order(db, order)
    # 取餐时刻落库:等餐时长 = 它 − arrived_shop_at,骑手申诉时的证据
    if payload.to_status == OrderStatus.PICKED_UP and order.picked_up_at is None:
        order.picked_up_at = datetime.now(timezone.utc)
        # 没点过「我到店了」就按取餐时刻兜底 —— 等餐时长记为 0 而不是 null,
        # 免得下游到处判空;真实为 0 和"没记录"的区别由 arrived_shop_at
        # 是否等于 picked_up_at 体现
        if order.arrived_shop_at is None:
            order.arrived_shop_at = order.picked_up_at
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
    # 商家接单 = 这单进抢单池,推给附近在线骑手(#114)。
    # 只在 ACCEPTED 这一次推:READY 时单子早就在池里了,再推一遍是骚扰。
    # 自取/商家自送/追加单不进池,自然也不推
    if (payload.to_status == OrderStatus.ACCEPTED
            and order.rider_id is None
            and not order.pickup
            and not order.self_delivery
            and not order.parent_order_no):
        from ..services.push import notify_riders_new_grab
        merchant_for_push = await db.get(Merchant, order.merchant_id)
        await notify_riders_new_grab(
            db, order, merchant_for_push.name if merchant_for_push else "商家")
    # 状态变更推给这一单的**每一个**相关方,不只是顾客(#302)。
    #
    # 原来这里写死 `notify_order_status(order.customer_id, ...)`:
    # 商家点了「出餐完成」,在楼下等餐的骑手收不到,只能靠 15 秒轮询;
    # 骑手点了「已取餐」「已送达」,商家看板要自己刷。
    # 三个按钮早就有了,信号却只走到一端。
    #
    # 谁点的不推给谁 —— 他知道自己刚点了什么,再推一遍是骚扰。
    shop_for_push = await db.get(Merchant, order.merchant_id)
    await fanout_order_status(
        order.status.value,
        customer_id=order.customer_id,
        merchant_owner_id=shop_for_push.owner_id if shop_for_push else None,
        rider_id=order.rider_id,
        order_no=order.order_no,
        actor_id=user.id,
    )
    return order_out(order, shop_for_push, user)


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
    # 范围按直线判(和下单一致,理由见 create_order),计价用路网
    if not in_delivery_range(haversine_m(merchant.lat, merchant.lng,
                                         payload.lat, payload.lng)):
        raise HTTPException(
            409, f"新地址超出配送范围({settings.delivery_max_km:g}km)")
    new_distance, _new_src = await billing_distance_m(
        merchant.lat, merchant.lng, payload.lat, payload.lng)

    # 距离差重算基础费,保留原单的夜间/天气加价部分。
    #
    # 旧距离**优先用下单时锁在订单里的那个**(#300):现算一遍的话,
    # 万一这期间缓存过期、路网换了答案,差值就凭空冒出来了 ——
    # 而顾客只是改了个地址,他没做错任何事。老订单没有这个字段
    # (0109 之前的)才退回现算。
    old_distance = float(order.bill_distance_m) \
        if order.bill_distance_m else \
        (await billing_distance_m(merchant.lat, merchant.lng,
                                  order.lat, order.lng))[0]
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
        note = f"改地址退配送费差价 ¥{refunded / 100:.2f}"
        # **先发起退款,再下调 total_cents**:微信通道按「当前 total + 已退」
        # 反推原始支付总额,先扣了 total 反推出来的就少一截(见 wechat_pay)
        await request_refund(db, order, refunded, "改地址,配送费差价退还")
        order.delivery_fee_cents += delta
        order.total_cents += delta
        order.refund_note = (f"{order.refund_note};{note}"
                             if order.refund_note else note)
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
        from ..models import MerchantPrinter
        from ..services.cloud_print import print_order_async
        printers = list(await db.scalars(
            select(MerchantPrinter).where(
                MerchantPrinter.merchant_id == merchant.id)))
        print_order_async(order, merchant, printers)
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


# ---------- 出餐之后的取消:按判责口径分摊 ----------

def _cancel_stage(order: Order) -> str:
    """这一单现在处在哪个分摊阶段。判据只有平台看得见的事实。"""
    from ..services import liability as lb
    return lb.stage_of(order.status.value,
                       rider_arrived=order.arrived_shop_at is not None)


def _cancel_split(order: Order):
    from ..services import liability as lb
    return lb.split_for_cancel(
        _cancel_stage(order),
        food_cents=order.food_cents,
        packing_fee_cents=order.packing_fee_cents,
        discount_cents=order.discount_cents,
        delivery_fee_cents=order.delivery_fee_cents,
        tip_cents=order.tip_cents,
        # 自配送的运力是商家出的,配送费归他;而且这种单没有骑手 ——
        # 不传的话那笔钱会被算给一个不存在的人,直接从账上蒸发
        self_delivery=order.self_delivery,
    )


def _quote_body(order: Order, split) -> dict:
    from ..services import liability as lb
    return {
        "order_no": order.order_no,
        "stage": split.stage,
        "stage_label": lb.STAGE_LABELS[split.stage],
        "refund_cents": split.refund_cents,
        "lines": [{"name": l.name, "cents": l.cents, "to": l.to, "why": l.why}
                  for l in split.lines],
        "food_to": split.food_to,
        # 口径是公开的,界面上要能点进去看,否则"透明"只是自称
        "spec_url": "/transparency/liability",
        "appeal_hint": "对这个结果有异议,可以在取消后 72 小时内申诉,"
                       "平台复核。",
    }


@router.get("/{order_no}/cancel-quote")
async def cancel_quote(
    order_no: str,
    user: User = Depends(require_role("customer")),
    db: AsyncSession = Depends(get_db),
):
    """出餐之后想取消,先看账:能退多少、剩下的钱去哪了、为什么。

    ## 为什么要有这个东西

    老口径是出餐后一律禁止取消,理由站得住(餐已经做了,成本真实发生),
    但手段太粗:**没有出口的结果不是用户不取消,是他去微信支付投诉或者
    银行拒付** —— 那对三方都更糟。

    所以把「不许取消」换成「取消要承担什么」。用户永远有出口,
    只是账单按责任分,而且每一分钱都写明去向。口径见
    services/liability.py,对外公开在 /transparency/liability。

    出餐**之前**不走这里 —— 那套(未接单随时退、2 分钟反悔窗口、
    商家超时可全退)已经在跑,走 /self-refund。
    """
    order = await db.scalar(select(Order).where(Order.order_no == order_no))
    if order is None or order.customer_id != user.id:
        raise HTTPException(404, "订单不存在")
    try:
        split = _cancel_split(order)
    except ValueError as exc:
        raise HTTPException(409, str(exc))
    return _quote_body(order, split)


@router.post("/{order_no}/cancel-with-split", response_model=OrderOut)
async def cancel_with_split(
    order_no: str,
    payload: CancelSplitIn,
    user: User = Depends(require_role("customer")),
    db: AsyncSession = Depends(get_db),
):
    """按上一步看到的那份账取消。

    ## 必须带上用户同意的是哪一份账

    账单会变:用户盯着「退配送费 5 元」那一屏犹豫的时候,骑手正好把餐取走了,
    真实账单就变成「退 0」。这时候直接按当前口径扣款,等于**用户同意的是
    A,系统执行的是 B** —— 在钱的路径上这是不能接受的。

    所以提交要带 `agreed_stage` 和 `agreed_refund_cents`,对不上直接 409,
    让客户端重新取一次账再让用户确认。

    ## 库存不回补、佣金归零、商家和骑手照口径入账

    见 settlement.settle_cancelled_with_split。
    """
    order = await db.scalar(
        select(Order).where(Order.order_no == order_no).with_for_update())
    if order is None or order.customer_id != user.id:
        raise HTTPException(404, "订单不存在")
    try:
        split = _cancel_split(order)
    except ValueError as exc:
        raise HTTPException(409, str(exc))

    if (payload.agreed_stage != split.stage
            or payload.agreed_refund_cents != split.refund_cents):
        raise HTTPException(409, {
            "message": "这一单的情况刚刚变了,账单跟着变了,请重新确认",
            "quote": _quote_body(order, split),
        })

    from ..services.settlement import settle_cancelled_with_split
    from_status = order.status
    if split.refund_cents > 0:
        await request_refund(db, order, split.refund_cents,
                             f"用户取消({_quote_label(split)})")
    await settle_cancelled_with_split(db, order, split)
    order.status = OrderStatus.CANCELLED
    order.cancel_reason = f"用户取消 · {_quote_label(split)}"
    from ..services.eta import release_coupon
    await release_coupon(db, order.order_no)
    await _record_event(db, order, from_status.value,
                        OrderStatus.CANCELLED.value, user)
    await db.commit()
    await db.refresh(order)
    await _notify(order)

    merchant = await db.get(Merchant, order.merchant_id)
    # 三方都要被告知,尤其骑手 —— 他正拿着一份餐在路上
    await push_to_user(
        merchant.owner_id, "用户取消了订单",
        f"订单#{order.order_no[-6:]} 用户取消,餐费照常入账、平台不收佣金",
        {"type": "order", "order_no": order.order_no})
    if order.rider_id is not None and split.rider_cents > 0:
        await push_to_user(
            order.rider_id, "订单已取消,这一趟的钱照付",
            f"订单#{order.order_no[-6:]} 用户取消。"
            f"{'这份餐归你处置。' if split.food_to else ''}"
            f"配送这部分 ¥{split.rider_cents / 100:.2f} 照常入账",
            {"type": "order", "order_no": order.order_no})
    return order_out(order, merchant, user)


def _quote_label(split) -> str:
    from ..services import liability as lb
    return lb.STAGE_LABELS[split.stage]


URGE_MAX_TIMES = 3          # 每单最多催 3 次
# 事件附言对用户可见的白名单(见 order_events)
EVENT_NOTE_PUBLIC = frozenset({"urge_reply"})
URGE_COOLDOWN_SECONDS = 180  # 两次催单间隔 ≥3 分钟
# 可催 = 进行中:这个集合同时决定「能不能催」和「列表里带不带催单数」,
# 两处必须是同一份 —— 不然会出现"催得动却看不见"的状态
URGEABLE = frozenset({OrderStatus.PAID, OrderStatus.ACCEPTED,
                      OrderStatus.READY, OrderStatus.PICKED_UP})


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
    if order.status not in URGEABLE:
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
                           {"type": "order", "order_no": order.order_no},
                           record_skip=True)
    else:
        shop = await db.get(Merchant, order.merchant_id)
        if shop:
            await push_to_user(shop.owner_id, "用户催单",
                               f"订单#{tail} 用户催单了,可一键回复安抚",
                               {"type": "order", "order_no": order.order_no},
                               record_skip=True)
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
    shop = await owned_shop(db, user)
    if shop is None or order.merchant_id != shop.id:
        raise HTTPException(403, "这不是你店里的订单")
    urged = await db.scalar(
        select(OrderEvent.id).where(OrderEvent.order_id == order.id,
                                    OrderEvent.to_status == "urged").limit(1))
    if urged is None:
        raise HTTPException(409, "该订单没有催单记录")
    # 回复文本必须落库:推送只是提醒,没配 JPush 的部署里推送是空操作,
    # 文本只进推送的话商家这 50 个字就直接消失了 —— 用户端时间轴
    # 从 events 的 note 里读它
    await _record_event(db, order, order.status.value, "urge_reply", user,
                        note=text_reply)
    await db.commit()
    await push_to_user(order.customer_id, f"商家回复:{text_reply}",
                       f"「{shop.name}」回复了你的催单",
                       {"type": "order", "order_no": order.order_no},
                       record_skip=True)
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
    # 完成也走 fanout(#302):骑手跑完一单、钱这一刻进账,
    # 在此之前他没有任何回音,要自己翻钱包页去看
    await fanout_order_status(
        order.status.value,
        customer_id=order.customer_id,
        merchant_owner_id=merchant.owner_id if merchant else None,
        rider_id=order.rider_id,
        order_no=order.order_no,
        actor_id=user.id,
    )
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
    shop = await owned_shop(db, user)
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

    list_price = target["price_cents"] * payload.quantity
    note_piece = f"{target['name']}×{payload.quantity}"

    # 库存回补(套餐要连子项一起还 —— 真正扣的是子项)
    await db.execute(
        update(Dish)
        .where(Dish.id == payload.dish_id)
        .values(stock=Dish.stock + payload.quantity)
    )
    for sub in (target.get("combo") or []):
        if sub.get("dish_id") is None:
            continue  # 老单没存子项 id
        await db.execute(
            update(Dish)
            .where(Dish.id == sub["dish_id"])
            .values(stock=Dish.stock
                    + int(sub.get("quantity", 1)) * payload.quantity)
        )

    target["quantity"] -= payload.quantity
    items = [i for i in items if i["quantity"] > 0]

    # 付费菜全退光 = 整单取消(只剩赠品行不算"还有菜")
    full_cancel = not any(i.get("price_cents", 0) > 0 for i in items)

    if full_cancel:
        # 全退光:退掉用户实付的剩余全部(打包/配送/扣除过的优惠都按实付口径)
        refund_amount = max(order.total_cents, 0)
        disc_share, sub_share = order.discount_cents, order.subsidy_cents
    else:
        # **退款按用户实付口径,不是菜单原价。**
        #
        # 满减/首单立减/平台券是**整单**优惠,用户从来没按原价付过这道菜。
        # 按 price×qty 退,退出去的钱里就有一截是他没付过的:
        # 餐费 5300 满减 2000 配送 300 → 实付 3600,退掉 4500 的那道菜
        # 就退了 4500,total_cents 被扣成 -900,平台净流出 900 分
        # (审计规则 5b 抓的就是这个负数),商家净额跟着变负、钱包被倒扣。
        #
        # 口径:按该菜在**当前**餐品总额中的占比分摊整单优惠。
        # 这**不是**"整单回收满减" —— 用户留下的部分继续享受同样的折扣率,
        # 不会因为退了一道菜就跌破门槛要补差价;分摊掉的那部分优惠
        # 各自退回给出资方(满减→商家,补贴→平台),谁出的钱谁收回。
        # 向下取整,不足一分的零头算用户的。
        #
        # 这样订单自洽式 total = 菜品+打包-满减+配送+小费-补贴 天然守恒
        # (审计规则 3),而 Σ退款 ≤ 用户实付 是它的推论。
        food_before = order.food_cents
        if food_before > 0:
            disc_share = min(order.discount_cents * list_price // food_before,
                             order.discount_cents)
            sub_share = min(order.subsidy_cents * list_price // food_before,
                            order.subsidy_cents)
        else:
            disc_share = sub_share = 0
        refund_amount = max(list_price - disc_share - sub_share, 0)
        if refund_amount > order.total_cents:
            # 上面的分摊保证了退款 ≤ 剩余应付,走到这儿说明哪条口径漏了。
            # 宁可少退也不能退超(退超 = 平台净流出,而且用户倒欠钱)
            logger.error(
                "缺货退款封顶:订单 %s 算出 %s 分 > 剩余应付 %s 分",
                order.order_no, refund_amount, order.total_cents)
            refund_amount = max(order.total_cents, 0)

    # **先发起退款,再改订单金额**:微信通道按「当前 total + 已退」反推
    # 原始支付总额,先扣了 total 反推出来的就少一截(见 wechat_pay)。
    # refund_cents 也由 request_refund 自己累计(渠道拒绝则不累计)
    if refund_amount > 0:
        await request_refund(db, order, refund_amount, f"缺货退款:{note_piece}")

    if full_cancel:
        for gift in items:      # 只剩的赠品行,库存一并回补
            await db.execute(
                update(Dish)
                .where(Dish.id == gift["dish_id"])
                .values(stock=Dish.stock + gift["quantity"])
            )
        order.items = []
        order.food_cents = 0
        order.packing_fee_cents = 0
        order.discount_cents = 0
        order.subsidy_cents = 0
        # **配送费和小费也要清零。** 这两项和上面几项一样,已经随
        # refund_amount(= 当时的 total_cents)整额退给用户了 ——
        # 而这是取餐前的取消,骑手一分没拿。
        #
        # 漏掉它们的后果不是少退钱(钱退对了),是**订单不再自洽**:
        # total(0) ≠ 0+0-0+配送费+小费-0。而审计规则 3 又把已取消单
        # 整个排除在外,所以这类脏数据一直没人看见 —— 库里攒了 254 单。
        # 现在两边一起改:这里清干净,规则 3 不再跳过已取消单。
        order.delivery_fee_cents = 0
        order.tip_cents = 0
        order.fee_parts = {}
        order.total_cents = 0
        order.commission_cents = 0
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
        order.food_cents = max(order.food_cents - list_price, 0)
        order.discount_cents -= disc_share      # 分摊掉的那部分优惠随菜退场
        order.subsidy_cents -= sub_share
        order.total_cents = max(order.total_cents - refund_amount, 0)
        # 佣金按新的实收口径重算(商家仍只承担留下来的那部分满减)
        gross = max(order.food_cents + order.packing_fee_cents - order.discount_cents, 0)
        order.commission_cents = int(Decimal(gross) * shop.commission_rate)
        order.refund_note = (
            f"{order.refund_note};{note_piece}" if order.refund_note else note_piece
        )
        await _record_event(db, order, order.status.value, "partial_refund", user)

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
    floor: int | None = None,
    has_elevator: bool | None = None,
    to_door: bool = True,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """下单前预览配送费(点单页选完地址就能展示)。

    返回组成明细:base 距离阶梯 / night 夜间加价 / weather 恶劣天气加价
    / door 上门难度(无电梯高楼层),**全部归骑手**;
    in_range=false 表示超出配送半径,下单会被拒。

    door_fee_cents 单独给一份:让顾客在选「送上门 / 送到楼下」**之前**
    就看到差价,而不是选完才发现多收了钱。
    """
    merchant = await db.get(Merchant, merchant_id)
    if merchant is None:
        raise HTTPException(404, "商家不存在")
    # 和下单时**同一个函数**(#300)。预览用直线、下单用路网的话,
    # 结算页显示 ¥5 付款变 ¥6 —— 和 #295 的 ETA 是同一种病:
    # 同一件事在同一分钟内给出两个答案
    distance, distance_source = await billing_distance_m(
        merchant.lat, merchant.lng, lat, lng)
    # 按**商家坐标**判天气:骑手是在那一带跑的。
    # 用收货点也行,但一单里两点最远 4km,同一片天气,取商家侧即可
    # 骑手反馈过的实地难度(#301):预览就要带上,否则预览 ¥5 付款变 ¥7。
    # 顺带 —— 顾客在这里就能看到"这地方骑手说不好送",
    # 他可以改选送到楼下省掉一部分,这个选择权本来就该给他
    from ..services import hardship as _hs
    _cons = await _hs.address_consensus(db, lat, lng, floor)
    _hard = _hs.comp_cents(_cons["kinds"], _cons["floors"], _cons["walk_m"])
    parts = delivery_fee_parts(
        distance,
        weather_on=await weather_surcharge_on(db, merchant.lat, merchant.lng),
        floor=floor, has_elevator=has_elevator, to_door=to_door,
        hardship_cents=_hard)
    # 送到楼下时能省多少:让顾客在选之前就看到差价,而不是选完才发现
    door_saving = delivery_fee_parts(
        distance, weather_on=False, floor=floor,
        has_elevator=has_elevator, to_door=True)["door"]
    # 预计送达:走**和下单后完全同一条路径**(compute_eta_async),
    # 而不是让客户端拿直线距离自己换算。
    #
    # 结算页原来自己算 `etaMinutes(直线距离)`,付完款订单详情显示的却是
    # 服务端算的数 —— 同一件事在同一分钟内给出两个答案。新用户不会想到
    # 这是两套算法,他只会记住这个 App 说话不算数。(#295)
    #
    # ⚠️ 这里**故意不传 prep_minutes**:payment_core 下单时也没传。
    # 传了商家实测分位数看着"更准",却会和真实下单结果差开 ——
    # 这个接口要的是**一致**,不是更准。
    #
    # 搭在配送费预览里而不是新开一个接口:结算页选完地址本来就调这个,
    # 多开一个就是多一次往返、多一处可能只成功一半的地方。
    eta_minutes: int | None = None
    try:
        from types import SimpleNamespace

        from ..services.eta import compute_eta_async

        # compute_eta 只读这几个字段;为了预估去造一条真订单是本末倒置
        probe = SimpleNamespace(
            pickup=False, parent_order_no="", scheduled_at=None,
            lat=lat, lng=lng, floor=floor, has_elevator=has_elevator)
        eta_at = await compute_eta_async(probe, merchant)
        if eta_at is not None:
            eta_minutes = max(1, round(
                (eta_at - datetime.now(timezone.utc)).total_seconds() / 60))
    except Exception:
        # 估不出就回 None,客户端**不显示** —— 而不是退回直线自己编一个。
        # 「大概 30 分钟」和「不知道」的区别新手分不出来,但他会记住你说错了
        logger.warning("结算页预估送达失败,不显示", exc_info=True)

    return {
        "distance_m": round(distance),
        "fee_cents": sum(parts.values()),
        "parts": parts,
        "labels": FEE_PART_LABELS,
        "door_fee_cents": door_saving,
        # in_range 按**直线**判,和下单时同一把尺子(见 create_order 里的
        # 长注释)。这里若用路网,预览说"超范围"下单却过得去,
        # 或者反过来 —— 又是同一件事两个答案
        "in_range": in_delivery_range(
            haversine_m(merchant.lat, merchant.lng, lat, lng)),
        # 这个距离是怎么来的:route=腾讯骑行路网 / straight=接口不可用
        # 时的直线兜底。两者差 19%,顾客和骑手都该知道看的是哪个
        "distance_source": distance_source,
        # 骑手实地反馈的原文说明,一项一行 —— 顾客要看得懂
        # 自己为什么多付这两块钱。说不清来历的钱,收多少都不叫透明
        "hardship_lines": _hs.explain(
            _cons["kinds"], _cons["floors"], _cons["walk_m"]),
        "hardship_samples": _cons["samples"],
        "eta_minutes": eta_minutes,
    }


@router.get("", response_model=list[OrderOut])
async def my_orders(
    before: str | None = None,
    limit: int = 20,
    status: str | None = None,
    q: str | None = None,  # 商家搜单:订单号片段/取餐码/顾客手机尾号
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """按角色返回各自视角的订单列表(游标分页)。

    before 传上一页最后一单的 created_at(ISO),不传则取最新一页。
    用游标不用 offset:订单在翻页期间还在新增,offset 会漏单或重复。
    老口径是写死 limit(50) 不分页——用户超过 50 单后就永远看不到更早的,
    与「每一单的账都可查」的承诺直接冲突。
    """
    limit = max(1, min(limit, 50))
    query = select(Order).order_by(Order.created_at.desc()).limit(limit)
    if before:
        try:
            cursor = datetime.fromisoformat(before)
        except ValueError:
            raise HTTPException(422, "分页游标格式不对")
        query = query.where(Order.created_at < cursor)
    if status:
        try:
            query = query.where(Order.status == OrderStatus(status))
        except ValueError:
            raise HTTPException(422, "未知的订单状态")
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
        # 搜索(仅商家视角):顾客打电话来查单,翻列表翻不到才有这个框。
        # 匹配在服务端做,响应字段口径不变 —— 不为搜索多下发一位手机号。
        # like '%q%' 走不了索引,但先按本店过滤后基数很小,不值得建索引
        if q:
            if len(q) < 3:
                raise HTTPException(422, "搜索至少输入 3 个字符")
            pattern = f"%{q}%"
            phone_match = select(User.id).where(
                User.id == Order.customer_id, User.phone.like(f"%{q}"))
            query = query.where(or_(
                Order.order_no.ilike(pattern),
                Order.pickup_code == q,
                phone_match.exists() if q.isdigit() else false(),
            ))
    result = await db.scalars(query)
    return await orders_out(db, list(result), user)


@router.get("/frequent")
async def my_frequent_dishes(
    days: int = Query(default=90, ge=7, le=365),
    limit: int = Query(default=5, ge=1, le=20),
    user: User = Depends(require_role("customer")),
    db: AsyncSession = Depends(get_db),
):
    """我的常点:近 N 天点得最多的「店+菜」组合。

    外卖的真实需求大半是复购,可老口径只有「再来一单」——那是整单重下,
    改一个菜就得重新翻菜单。这里按单品聚合,用户想点哪个点哪个。

    只统计已完成的单(取消/退款的不算数),菜必须还在售且没估清,
    否则列出来点不了比不列还糟。全程只读自己的订单,不涉及他人数据。
    """
    rows = await db.execute(text("""
        SELECT d.id, d.name, d.price_cents, d.image_url,
               m.id AS merchant_id, m.name AS merchant_name, m.is_open,
               count(*) AS times, max(o.created_at) AS last_at
        FROM orders o, jsonb_array_elements(o.items) it
        JOIN dishes d ON d.id = (it->>'dish_id')::int
        JOIN merchants m ON m.id = d.merchant_id
        WHERE o.customer_id = :uid
          AND o.status = 'completed'
          AND o.created_at >= now() - make_interval(days => :days)
          AND d.is_on_sale
          AND d.stock > 0
          AND m.status = 'approved'
        GROUP BY d.id, d.name, d.price_cents, d.image_url,
                 m.id, m.name, m.is_open
        ORDER BY times DESC, last_at DESC
        LIMIT :limit
    """), {"uid": user.id, "days": days, "limit": limit})
    return {"items": [
        {"dish_id": r[0], "dish_name": r[1], "price_cents": r[2],
         "image_url": r[3] or "", "merchant_id": r[4], "merchant_name": r[5],
         # 店没开也照常列出来,只是点不了 —— 藏起来用户会以为常点丢了
         "merchant_open": bool(r[6]), "times": r[7],
         "last_at": r[8].isoformat() if r[8] else None}
        for r in rows
    ]}


# ⚠️ 这条必须排在 `/{order_no}` **之前**:FastAPI 按注册顺序匹配,
# 放在后面的话 "hardship-rules" 会被当成一个订单号,回「订单不存在」
@router.get("/hardship-rules")
async def hardship_rules(user: User = Depends(get_current_user)):
    """难度补贴的**完整口径**:每一项是什么、加多少钱、几条转正。

    公开这个接口是这套机制成立的前提。**不给出金额的补贴等于施舍** ——
    骑手不知道勾一项能拿多少,就无从判断值不值得花那十秒钟填;
    顾客不知道那两块钱怎么来的,只会觉得平台在乱收费。

    写死在代码里,不做后台可调 —— 可调就意味着某天可以悄悄调低。
    """
    from ..services import hardship as hs

    return {
        "items": [
            {"kind": k, "name": n, "desc": d,
             "cents": {
                 "no_elevator": None,   # 按层算,见 rule
                 "walk_in": None,       # 按米算
                 "no_vehicle": hs.NO_VEHICLE_CENTS,
                 "gate_hard": hs.GATE_HARD_CENTS,
                 "other": hs.OTHER_CENTS,
             }[k],
             "rule": {
                 "no_elevator": f"超出 {hs.NO_ELEVATOR_FREE_FLOOR} 楼的部分,"
                                f"每层 ¥{hs.NO_ELEVATOR_PER_FLOOR_CENTS / 100:g},"
                                f"封顶 ¥{hs.NO_ELEVATOR_MAX_CENTS / 100:g}",
                 "walk_in": f"超出 {hs.WALK_IN_FREE_M} 米的部分,"
                            f"每 100 米 ¥{hs.WALK_IN_PER_100M_CENTS / 100:g},"
                            f"封顶 ¥{hs.WALK_IN_MAX_CENTS / 100:g}",
                 "no_vehicle": f"固定 ¥{hs.NO_VEHICLE_CENTS / 100:g}",
                 "gate_hard": f"固定 ¥{hs.GATE_HARD_CENTS / 100:g}",
                 "other": "不自动给钱,平台人工看",
             }[k]}
            for k, (n, d) in hs.HARDSHIP_LABELS.items()
        ],
        "max_cents": hs.MAX_COMP_CENTS,
        "consensus_min": hs.CONSENSUS_MIN,
        "funder": "platform",
        "notes": [
            "这笔钱由平台出,不向顾客或商家追收",
            "反馈不影响你的评分、派单和接单资格",
            f"同一个地址攒够 {hs.CONSENSUS_MIN} 条一致反馈后,"
            "后来的单在下单时就按真实难度算,顾客也看得到",
            "同一个地址你只需要反馈一次",
        ],
    }


@router.get("/{order_no}", response_model=OrderOut)
async def get_order(
    order_no: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    order = await visible_order_or_404(db, order_no, user)
    merchant = await db.get(Merchant, order.merchant_id)
    # 详情也填 has_review:同一个字段在列表里是真的、在详情里恒为 false,
    # 那它就是个陷阱 —— 下一个人照着详情写逻辑,错得毫无征兆
    out = order_out(order, merchant, user,
                    has_review=order.id in await _reviewed_ids(db, [order]),
                    urge_count=(await _urge_counts(db, [order])).get(
                        order.id, 0))
    # 详情页专属:联系电话(用户联系骑手/商家,一键拨号)。
    # dial_phone 而不是 phone:已注销账号的 phone 是 `del{id}_{hex}` 哨兵,
    # 原样下发的话客户端会拿一串字母去拨号
    if order.rider_id:
        rider = await db.get(User, order.rider_id)
        if rider:
            out.rider_name = rider.name
            out.rider_phone = rider.dial_phone
    if merchant:
        owner = await db.get(User, merchant.owner_id)
        if owner:
            out.merchant_phone = owner.dial_phone
    return out


@router.get("/{order_no}/events", response_model=list[OrderEventOut])
async def order_events(
    order_no: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """订单状态时间轴(几点几分接单/取餐/送达),订单追踪页用。"""
    order = await visible_order_or_404(db, order_no, user)
    result = await db.scalars(
        select(OrderEvent)
        .where(OrderEvent.order_id == order.id)
        .order_by(OrderEvent.created_at)
    )
    # note 白名单:只有明确"写给用户看"的事件才带附言下发。
    # 商家回复催单的那句话就存在 note 里 —— 不下发的话,
    # 没配推送的部署里商家点了「回复安抚」用户什么都看不到,
    # 商家以为安抚了,用户以为没人理
    out = []
    for e in result:
        row = OrderEventOut.model_validate(e)
        if e.to_status not in EVENT_NOTE_PUBLIC:
            row.note = ""
        out.append(row)
    return out


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

    # 原先只拦了顾客(customer_id != 我 → 404),商家/骑手角色拿到的是 200:
    # 随便一个骑手号就能翻别人单子的退款流水。四种角色统一走归属校验
    order = await visible_order_or_404(db, order_no, user)
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
    # 归属校验:下单用户本人、该单骑手、管理员,以及**本店商家**(含店员)。
    # 商家看骑手位置的正当性:顾客催单先打给店家,店家不能两眼一抹黑
    allowed = (user.id in (order.customer_id, order.rider_id)
               or user.role.value == "admin")
    if not allowed and user.role.value == "merchant":
        from ..services.staff import operable_shop
        shop, _ = await operable_shop(db, user)
        allowed = shop is not None and shop.id == order.merchant_id
        # 商家侧只看**履约中**的位置:送达后到自动确认最长 24 小时,
        # 期间骑手早在送别的单 —— 店家没有继续追踪的正当理由
        if allowed and order.status not in (
                OrderStatus.ACCEPTED, OrderStatus.READY,
                OrderStatus.PICKED_UP):
            return RiderLocationOut(rider_id=order.rider_id, lat=None,
                                    lng=None, updated_at=None)
    if not allowed:
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
        shop = await owned_shop(db, user)
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


@router.post("/{order_no}/hardship")
async def report_hardship(
    order_no: str,
    payload: HardshipIn,
    user: User = Depends(require_role("rider")),
    db: AsyncSession = Depends(get_db),
):
    """骑手反馈这一单实际有多难送 —— 当场补钱 + 按地址沉淀(#301)。

    ## 为什么在送达之后才能提

    送达前弹这个是在他赶时间的时候加手续。**先把餐送到,再说钱的事。**

    ## 这笔钱由平台出

    不向顾客追收(顾客会觉得被坑,更要命的是会让骑手不敢反馈 ——
    他知道这钱是从顾客身上要的),也不向商家追收(与商家无关)。
    走 `adjustment` 入账,和申诉改判同一条通道:平台认亏。

    ## 沉淀怎么用

    同一地址攒够 `CONSENSUS_MIN` 条一致反馈后,后续订单在**下单时**
    就按真实难度计价 —— 用户下单前看得到(可以改选送到楼下省这笔钱),
    骑手接单前也看得到,不用骑到楼下才发现是六楼没电梯。
    """
    from ..models import RiderHardship
    from ..services import hardship as hs

    order = await db.scalar(select(Order).where(Order.order_no == order_no))
    if order is None or order.rider_id != user.id:
        raise HTTPException(403, "这不是你接的订单")
    if order.status not in (OrderStatus.DELIVERED, OrderStatus.COMPLETED):
        raise HTTPException(409, "送到之后再来说这一单难不难 —— 先别耽误送餐")

    kinds = [k for k in payload.kinds if k in hs.HARDSHIP_LABELS]
    if not kinds:
        raise HTTPException(422, "至少勾一项")

    if await db.scalar(select(RiderHardship.id).where(
            RiderHardship.order_no == order_no)):
        raise HTTPException(409, "这单已经反馈过了")

    key = hs.addr_key(order.lat, order.lng, order.floor)
    # 同一骑手同一地址只计一次 —— 防刷靠这个,不靠给人打分。
    # **不是拒绝他反馈**,是这一次不再重复补钱:同一个地方的同一件事,
    # 说一次就够了,再说三次也不会变得更难
    dup = await db.scalar(select(RiderHardship.id).where(
        RiderHardship.rider_id == user.id, RiderHardship.addr_key == key))
    comp = 0 if dup else hs.comp_cents(kinds, payload.floors, payload.walk_m)

    row = RiderHardship(
        order_id=order.id, order_no=order_no, rider_id=user.id,
        addr_key=key, kinds=kinds, floors=payload.floors,
        walk_m=payload.walk_m, note=payload.note.strip()[:200],
        comp_cents=comp,
    )
    db.add(row)
    if comp:
        from ..models import EarningKind, RiderEarning
        db.add(RiderEarning(
            rider_id=user.id, order_id=order.id, order_no=order_no,
            kind=EarningKind.adjustment, amount_cents=comp,
        ))
    await db.commit()

    lines = hs.explain(kinds, payload.floors, payload.walk_m)
    return {
        "comp_cents": comp,
        "lines": lines,
        "duplicate": bool(dup),
        "message": (
            f"谢谢,已补 ¥{comp / 100:.2f} 到你的收入"
            if comp else
            ("这个地址你反馈过了,已经记下 —— 不重复补钱,但会算进共识"
             if dup else "已记下;这几项不自动补钱,平台会人工看")),
    }
