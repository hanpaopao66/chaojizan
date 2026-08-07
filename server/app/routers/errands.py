"""跑腿:帮送(A 点取、B 点送)。

## 为什么不塞进 create_order

`create_order` 那四百行全是外卖:商家营业校验、菜品与库存、起送价、
满减与券、打包费、佣金基数。跑腿一样都用不上,塞进去只会让两条路
互相污染 —— 而它们唯一共享的是"配送"这一段,那一段本来就在
pricing / dispatch / settlement 里,已经复用了。

## 状态流

    待支付 → (支付) → 待取餐 → 已取件 → 已送达 → 已完成

**没有商家接单/出餐这两步**。支付成功后直接落 READY 进抢单池
(见 services/payment_core)。

## 钱

    用户付 = 跑腿费(距离 + 时段 + 天气 + 上门难度,复用外卖那套费率)
    骑手拿 = 跑腿费 × 98%
    平台收 = 跑腿费 × 2%(与团购券同口径)

⚠️ 和外卖**不是同一个口径**:外卖的配送费一分不抽,平台收入来自商家佣金;
跑腿没有商家,这 2% 是平台在这条业务上唯一的收入。
下单页与账单上都要写出来,不能藏在总价里 ——
不写清楚就会变成"你不是说配送费不抽吗"。
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..security import require_role
from ..db import get_db
from ..models import Merchant, Order, User
from ..schemas import (
    ErrandBuyCreateIn,
    ErrandBuyQuoteOut,
    ErrandCreateIn,
    ErrandQuoteOut,
    OrderOut,
)
from ..services.errand import (
    KIND_ERRAND_BUY,
    KIND_ERRAND_SEND,
    forbidden_reason,
    raise_limit_cents,
    service_fee_cents,
    service_merchant,
    settle_goods,
    unavailable_fee_cents,
)
from ..state_machine import OrderStatus

router = APIRouter(prefix="/errands", tags=["errands"])


async def _quote(db: AsyncSession, payload: ErrandCreateIn) -> dict:
    """跑腿费 = 取件点 → 送达点 的配送定价。**复用外卖那套费率**,
    不另起一套 —— 另起一套的下场是两份费率迟早分叉,
    而配送费透明是我们的立身之本。"""
    from ..services.pricing import delivery_fee_parts, haversine_m
    from ..services.flags import weather_surcharge_on

    distance = haversine_m(payload.pickup_lat, payload.pickup_lng,
                           payload.lat, payload.lng)
    parts = delivery_fee_parts(
        distance,
        weather_on=await weather_surcharge_on(
            db, payload.pickup_lat, payload.pickup_lng),
        floor=payload.floor,
        has_elevator=payload.has_elevator,
        to_door=payload.to_door,
    )
    fee = sum(parts.values())
    return {"distance_m": int(distance), "parts": parts, "fee_cents": fee,
            "service_fee_cents": service_fee_cents(fee)}


@router.post("/quote", response_model=ErrandQuoteOut)
async def quote(
    payload: ErrandCreateIn,
    user: User = Depends(require_role("customer")),
    db: AsyncSession = Depends(get_db),
):
    """下单前算钱。**平台服务费单独一行给出来** ——
    藏在总价里就等于没说,而我们对外讲的是"账目公开"。"""
    from ..routers.orders import FEE_PART_LABELS

    q = await _quote(db, payload)
    labels = {k: FEE_PART_LABELS[k] for k in q["parts"]
              if k in FEE_PART_LABELS}
    return ErrandQuoteOut(
        distance_m=q["distance_m"],
        fee_cents=q["fee_cents"],
        parts=q["parts"],
        labels=labels,
        service_fee_cents=q["service_fee_cents"],
        total_cents=q["fee_cents"],
        note=("跑腿费按取件点到送达点的距离算,和外卖同一套费率。"
              f"平台从中收 {q['service_fee_cents'] / 100:.2f} 元服务费"
              "(2%),其余全归骑手 —— "
              "外卖的配送费我们一分不抽,那边平台收入来自商家佣金;"
              "跑腿没有商家,这 2% 是这条业务上唯一的收入。"),
    )


@router.post("", response_model=OrderOut)
async def create_errand(
    payload: ErrandCreateIn,
    user: User = Depends(require_role("customer")),
    db: AsyncSession = Depends(get_db),
):
    """下一单帮送。东西是用户自己的,平台只提供"把它从 A 送到 B"。"""
    import uuid

    from ..config import settings
    from ..ratelimit import check_rate_limit
    from ..routers.orders import order_out
    from ..services.flags import weather_shutdown_on

    await check_rate_limit("order", str(user.id),
                           settings.rate_limit_order_per_minute)
    if await weather_shutdown_on(db):
        raise HTTPException(
            409, "极端天气,平台临时停止接新单(已有订单会尽力送达)")

    # 禁运:**硬编码拦截,不是只写在协议里**。写在协议里等于没写 ——
    # 没人看,出了事平台也脱不了责任
    hit = forbidden_reason(payload.errand_note)
    if hit:
        raise HTTPException(
            422, f"这类物品不能通过跑腿寄送({hit})。"
                 "涉及安全与法规,平台一律不承运,请理解")
    if not payload.no_forbidden:
        raise HTTPException(422, "请先确认寄送物品不含违禁品")
    if len(payload.errand_note.strip()) < 2:
        raise HTTPException(422, "写一下寄的是什么,骑手取件时要核对")

    q = await _quote(db, payload)
    if q["distance_m"] > settings.delivery_max_km * 1000:
        raise HTTPException(
            409, f"这一单要跑 {q['distance_m'] / 1000:.1f} 公里,"
                 f"超出 {settings.delivery_max_km:g} 公里配送范围")

    shop = await service_merchant(db, user.city)
    order = Order(
        order_no=uuid.uuid4().hex[:20],
        customer_id=user.id,
        merchant_id=shop.id,
        order_kind=KIND_ERRAND_SEND,
        status=OrderStatus.PENDING_PAYMENT,
        items=[],
        food_cents=0, packing_fee_cents=0, discount_cents=0,
        delivery_fee_cents=q["fee_cents"],
        fee_parts=q["parts"],
        to_door=payload.to_door,
        tip_cents=0,
        total_cents=q["fee_cents"],
        commission_cents=0,        # 支付成功时按 2% 落定(payment_core)
        # 送达点
        address=payload.address, lat=payload.lat, lng=payload.lng,
        floor=payload.floor, has_elevator=payload.has_elevator,
        contact_name=payload.contact_name,
        contact_phone=payload.contact_phone,
        # 取件点(跑腿单的取件点在订单自己身上,不在商家上)
        pickup_address=payload.pickup_address,
        pickup_lat=payload.pickup_lat, pickup_lng=payload.pickup_lng,
        pickup_contact_name=payload.pickup_contact_name,
        pickup_contact_phone=payload.pickup_contact_phone,
        errand_note=payload.errand_note.strip()[:300],
        remark=payload.remark,
        promo_note=(f"跑腿费 {q['fee_cents'] / 100:.2f} 元,"
                    f"平台服务费 {q['service_fee_cents'] / 100:.2f} 元(2%)"),
    )
    db.add(order)
    await db.commit()
    await db.refresh(order)
    return order_out(order, shop, viewer=user)


@router.post("/{order_no}/picked-photo", response_model=OrderOut)
async def upload_pickup_photo(
    order_no: str,
    payload: dict,
    user: User = Depends(require_role("rider")),
    db: AsyncSession = Depends(get_db),
):
    """取件拍照。**这是丢件纠纷时唯一的事实来源** ——
    东西是用户的,平台既不知道原样也不承担保价,
    只有这张照片能说明"骑手拿到手时是什么样"。

    不强制:骑手在楼道里手忙脚乱,卡住照片就等于卡住取件。
    但界面上要说清楚没拍的后果 —— 出了纠纷双方都只能各执一词。
    """
    from ..routers.orders import order_out

    url = str(payload.get("photo_url") or "").strip()
    if not url:
        raise HTTPException(422, "缺少照片")
    order = await db.scalar(select(Order).where(Order.order_no == order_no))
    if order is None or order.rider_id != user.id:
        raise HTTPException(404, "订单不存在")
    if order.status not in (OrderStatus.ACCEPTED, OrderStatus.READY):
        raise HTTPException(409, "只有待取件的单能上传取件照")
    order.pickup_photo_url = url[:300]
    await db.commit()
    await db.refresh(order)
    merchant = await db.get(Merchant, order.merchant_id)
    return order_out(order, merchant, viewer=user)


# ---------- 帮买 ----------

#: 帮买**只做包装商品与商超日用,不做即食餐饮**。
#:
#: 代购即食食品需要食品经营许可 —— 让骑手去一个没证的摊子买一份小笼包,
#: 就是给无证经营导流,而我们外卖那边卡证卡得很严,两套标准会自己打架。
#: 想吃现做的,走我们自己的外卖(那边的商家有证)。
_BUY_BANNED = (
    ("即食餐饮", ("小笼包", "炒菜", "盒饭", "现做", "熟食", "麻辣烫",
                "火锅", "米线", "快餐", "早餐", "外卖")),
    ("烟草", ("烟", "香烟", "卷烟")),
    ("酒类", ("酒", "白酒", "啤酒", "红酒")),
)


def _buy_banned(text: str) -> str | None:
    lowered = (text or "").lower()
    for label, words in _BUY_BANNED:
        if any(w in lowered for w in words):
            return label
    return None


@router.post("/buy/quote", response_model=ErrandBuyQuoteOut)
async def buy_quote(
    payload: ErrandBuyCreateIn,
    user: User = Depends(require_role("customer")),
    db: AsyncSession = Depends(get_db),
):
    """帮买报价。**商品款和跑腿费分开列** ——
    用户付的是两笔钱,合成一个总数他就不知道自己在为什么付费。"""
    from ..routers.orders import FEE_PART_LABELS

    q = await _quote(db, payload)
    labels = {k: FEE_PART_LABELS[k] for k in q["parts"]
              if k in FEE_PART_LABELS}
    limit = raise_limit_cents(payload.goods_budget_cents)
    return ErrandBuyQuoteOut(
        distance_m=q["distance_m"],
        fee_cents=q["fee_cents"],
        parts=q["parts"],
        labels=labels,
        service_fee_cents=q["service_fee_cents"],
        goods_budget_cents=payload.goods_budget_cents,
        total_cents=q["fee_cents"] + payload.goods_budget_cents,
        raise_limit_cents=limit,
        note=(f"你先付商品款 {payload.goods_budget_cents / 100:.2f} 元 + "
              f"跑腿费 {q['fee_cents'] / 100:.2f} 元。"
              "**商品款平台一分不抽**,按小票实付结给骑手:"
              "买少了差额原路退你,"
              f"买多了在 {limit / 100:.2f} 元以内我们先垫、再向你补收;"
              "超过这个数骑手会先问你同不同意,你不同意就不买。"
              "买不到的话商品款全额退,跑腿费只收到店那一段的距离费。"),
    )


@router.post("/buy", response_model=OrderOut)
async def create_errand_buy(
    payload: ErrandBuyCreateIn,
    user: User = Depends(require_role("customer")),
    db: AsyncSession = Depends(get_db),
):
    """下一单帮买。用户预付商品款给平台,骑手不垫自己的钱。"""
    import uuid

    from ..config import settings
    from ..ratelimit import check_rate_limit
    from ..routers.orders import order_out
    from ..services.flags import weather_shutdown_on

    await check_rate_limit("order", str(user.id),
                           settings.rate_limit_order_per_minute)
    if await weather_shutdown_on(db):
        raise HTTPException(409, "极端天气,平台临时停止接新单")

    hit = forbidden_reason(payload.errand_note) or _buy_banned(
        payload.errand_note)
    if hit:
        raise HTTPException(
            422, f"帮买不支持这一类({hit})。"
                 "帮买只做包装商品与商超日用 —— "
                 "代购即食食品需要食品经营许可,我们不给无证经营导流;"
                 "想吃现做的可以走外卖,那边的商家都有证")
    if not payload.no_forbidden:
        raise HTTPException(422, "请先确认所买物品不在不支持的范围内")

    q = await _quote(db, payload)
    if q["distance_m"] > settings.delivery_max_km * 1000:
        raise HTTPException(
            409, f"这一单要跑 {q['distance_m'] / 1000:.1f} 公里,超出配送范围")

    shop = await service_merchant(db, user.city)
    total = q["fee_cents"] + payload.goods_budget_cents
    order = Order(
        order_no=uuid.uuid4().hex[:20],
        customer_id=user.id,
        merchant_id=shop.id,
        order_kind=KIND_ERRAND_BUY,
        status=OrderStatus.PENDING_PAYMENT,
        items=[],
        # 商品款走 food_cents:它是"用户付的、不属于配送费"的那部分,
        # 订单金额自洽校验(total == food + 配送 + …)才对得上。
        # 但**结算时不进商家入账** —— 跑腿单根本不生成商家入账行
        food_cents=payload.goods_budget_cents,
        packing_fee_cents=0, discount_cents=0,
        delivery_fee_cents=q["fee_cents"],
        fee_parts=q["parts"],
        to_door=payload.to_door,
        tip_cents=0,
        total_cents=total,
        commission_cents=0,
        goods_budget_cents=payload.goods_budget_cents,
        address=payload.address, lat=payload.lat, lng=payload.lng,
        floor=payload.floor, has_elevator=payload.has_elevator,
        contact_name=payload.contact_name,
        contact_phone=payload.contact_phone,
        pickup_address=payload.pickup_address,
        pickup_lat=payload.pickup_lat, pickup_lng=payload.pickup_lng,
        pickup_contact_name=payload.pickup_contact_name,
        pickup_contact_phone=payload.pickup_contact_phone,
        errand_note=payload.errand_note.strip()[:300],
        remark=payload.remark,
        promo_note=(f"商品款 {payload.goods_budget_cents / 100:.2f} 元(预付)"
                    f" + 跑腿费 {q['fee_cents'] / 100:.2f} 元"),
    )
    db.add(order)
    await db.commit()
    await db.refresh(order)
    return order_out(order, shop, viewer=user)


@router.post("/{order_no}/receipt", response_model=OrderOut)
async def submit_receipt(
    order_no: str,
    payload: dict,
    user: User = Depends(require_role("rider")),
    db: AsyncSession = Depends(get_db),
):
    """骑手买完,填实付金额 + 传小票。

    **小票是唯一对账依据**,而且用户看得到 —— 代买最容易起的纠纷就是
    "你是不是多报了",把小票摊开,这个纠纷根本不会发生。

    超出浮动上限的部分不能自己做主:骑手不该被迫做"超了一点点先垫上"
    这个判断题,那是把平台的规则缺失转嫁给收入最低的那个人。
    """
    from ..routers.orders import order_out

    actual = payload.get("actual_cents")
    url = str(payload.get("receipt_url") or "").strip()
    if not isinstance(actual, int) or actual < 0:
        raise HTTPException(422, "填一下小票上的实付金额")
    if not url:
        raise HTTPException(422, "小票必须拍 —— 它是这一单唯一的对账依据")
    order = await db.scalar(select(Order).where(Order.order_no == order_no))
    if order is None or order.rider_id != user.id:
        raise HTTPException(404, "订单不存在")
    if order.order_kind != KIND_ERRAND_BUY:
        raise HTTPException(409, "只有帮买单需要填小票")

    limit = raise_limit_cents(order.goods_budget_cents)
    over = actual - order.goods_budget_cents
    if over > limit and order.goods_raise_status != "approved":
        raise HTTPException(
            409, f"比预估多了 {over / 100:.2f} 元,超出可自行垫付的 "
                 f"{limit / 100:.2f} 元。先点「要多花钱」问一下顾客,"
                 "他同意了再买 —— 别自己垫")
    # 差额当场结清 —— 光算不执行的话,骑手按小票实付拿钱、用户还按预估付钱,
    # 中间那个差额就是平台的窟窿(审计的跑腿恒等式当场把它抓出来了)
    from ..services.wechat_pay import request_refund

    diff = settle_goods(order.goods_budget_cents, actual)
    order.goods_actual_cents = actual
    order.goods_receipt_url = url[:300]
    if diff["refund_cents"]:
        # 买少了:差额原路退,用户实付随之下降
        await request_refund(db, order, diff["refund_cents"], diff["note"])
        order.refund_cents += diff["refund_cents"]
        order.refund_note = (f"{order.refund_note};{diff['note']}"
                             if order.refund_note else diff["note"])
    elif diff["extra_charge_cents"]:
        # 买多了:用户实付上调(预付 + 补收)。
        #
        # ⚠️ **补收目前只落账不真的收钱** —— 微信支付商户号还没下来,
        # 没有可用的补收通道。上线前必须接上,否则这笔钱是平台垫的。
        # 这里如实把金额记进订单,而不是假装没这回事:
        # 账面上看得见,才不会上线后才发现在漏钱
        extra = diff["extra_charge_cents"]
        order.food_cents += extra
        order.total_cents += extra
        order.promo_note = (f"{order.promo_note};"
                            f"按小票补收 {extra / 100:.2f} 元")[:100]
    await db.commit()
    await db.refresh(order)
    merchant = await db.get(Merchant, order.merchant_id)
    return order_out(order, merchant, viewer=user)


@router.post("/{order_no}/raise", response_model=OrderOut)
async def request_raise(
    order_no: str,
    payload: dict,
    user: User = Depends(require_role("rider")),
    db: AsyncSession = Depends(get_db),
):
    """骑手发起「要多花钱」确认。用户同意才买。"""
    from ..routers.orders import order_out
    from ..services.push import push_to_user

    want = payload.get("actual_cents")
    if not isinstance(want, int) or want <= 0:
        raise HTTPException(422, "填一下实际要多少钱")
    order = await db.scalar(select(Order).where(Order.order_no == order_no))
    if order is None or order.rider_id != user.id:
        raise HTTPException(404, "订单不存在")
    if order.order_kind != KIND_ERRAND_BUY:
        raise HTTPException(409, "只有帮买单需要加价确认")
    order.goods_raise_cents = want
    order.goods_raise_status = "pending"
    await db.commit()
    await db.refresh(order)
    await push_to_user(
        order.customer_id, "骑手问你:要多花点钱吗",
        f"你预估 {order.goods_budget_cents / 100:.2f} 元,"
        f"实际要 {want / 100:.2f} 元。同意的话骑手才买",
        {"type": "errand_raise", "order_no": order.order_no})
    merchant = await db.get(Merchant, order.merchant_id)
    return order_out(order, merchant, viewer=user)


@router.post("/{order_no}/raise/decide", response_model=OrderOut)
async def decide_raise(
    order_no: str,
    payload: dict,
    user: User = Depends(require_role("customer")),
    db: AsyncSession = Depends(get_db),
):
    """用户回应加价:同意就买,不同意骑手按「买不到」处理。"""
    from ..routers.orders import order_out
    from ..services.push import push_to_user

    agree = bool(payload.get("agree"))
    order = await db.scalar(select(Order).where(Order.order_no == order_no))
    if order is None or order.customer_id != user.id:
        raise HTTPException(404, "订单不存在")
    if order.goods_raise_status != "pending":
        raise HTTPException(409, "没有待确认的加价")
    order.goods_raise_status = "approved" if agree else "rejected"
    await db.commit()
    await db.refresh(order)
    if order.rider_id:
        await push_to_user(
            order.rider_id,
            "顾客已回应加价" if agree else "顾客不同意加价",
            "可以按新价格买了" if agree
            else "按买不到处理即可,商品款会全额退给顾客",
            {"type": "errand_raise", "order_no": order.order_no},
            record_skip=True)
    merchant = await db.get(Merchant, order.merchant_id)
    return order_out(order, merchant, viewer=user)


@router.post("/{order_no}/unavailable", response_model=OrderOut)
async def mark_unavailable(
    order_no: str,
    payload: dict | None = None,
    user: User = Depends(require_role("rider")),
    db: AsyncSession = Depends(get_db),
):
    """骑手到店发现没货。

    商品款**全额退用户**;跑腿费只收到店那一段的距离费 ——
    骑手确实跑了这一趟不该白跑,用户也确实没拿到东西。
    这条折中的前提是**在下单页提前说清楚**,提前说了就不叫坑。
    """
    from ..models import OrderEvent
    from ..routers.orders import order_out
    from ..services.wechat_pay import request_refund

    order = await db.scalar(
        select(Order).where(Order.order_no == order_no).with_for_update())
    if order is None or order.rider_id != user.id:
        raise HTTPException(404, "订单不存在")
    if order.order_kind != KIND_ERRAND_BUY:
        raise HTTPException(409, "只有帮买单能标记买不到")
    if order.status in (OrderStatus.CANCELLED, OrderStatus.COMPLETED):
        raise HTTPException(409, "这一单已经结束了")

    # 商品款全额退,跑腿费只留到店那一段的距离费
    keep = unavailable_fee_cents(order.fee_parts)
    refund = max(0, order.total_cents - keep)
    note = f"帮买:商品买不到,退商品款与上门段费用,保留到店距离费 {keep} 分"
    if refund:
        await request_refund(db, order, refund, note)
        order.refund_cents += refund
        order.refund_note = (f"{order.refund_note};{note}"
                             if order.refund_note else note)
    from_status = order.status
    order.goods_actual_cents = 0
    order.errand_note = (order.errand_note +
                         f"|买不到:{(payload or {}).get('note', '')}")[:300]
    order.status = OrderStatus.CANCELLED
    order.cancel_reason = "帮买:商品买不到"
    db.add(OrderEvent(
        order_id=order.id, from_status=from_status.value,
        to_status=OrderStatus.CANCELLED.value,
        actor_role="rider", actor_id=user.id, note=note))
    await db.commit()
    await db.refresh(order)
    merchant = await db.get(Merchant, order.merchant_id)
    return order_out(order, merchant, viewer=user)
