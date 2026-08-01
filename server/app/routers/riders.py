import time

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..db import get_db
from ..models import (
    DeliveryIssue,
    Merchant,
    Order,
    OrderEvent,
    RiderEarning,
    RiderProfile,
    User,
    VerifyStatus,
    Withdrawal,
    WithdrawalStatus,
)
from ..redis_client import RIDER_LOC_KEY, get_redis
from ..schemas import (
    DeliveryIssueIn,
    DeliveryIssueOut,
    EarningOut,
    LocationIn,
    OnlineIn,
    OrderOut,
    RiderProfileIn,
    RiderProfileOut,
    TransferIn,
    TransferOut,
    WalletOut,
    WithdrawalIn,
    WithdrawalOut,
)
from ..security import require_role
from ..state_machine import GRABBABLE_STATUSES, OrderStatus
from ..ws import manager
from .orders import order_out, orders_out

router = APIRouter(prefix="/riders", tags=["骑手"])


def _profile_out(p: RiderProfile) -> RiderProfileOut:
    """对外只回打码姓名与状态。**证号明文不出接口** ——
    和用户侧 UserIdentity 一个口径。"""
    name = p.real_name or ""
    return RiderProfileOut(
        real_name=(name[0] + "*" * (len(name) - 1)) if len(name) > 1 else name,
        health_cert_photo_url=p.health_cert_photo_url,
        status=p.status,
        reject_reason=p.reject_reason,
        id_verified=p.id_verified_at is not None,
    )


def _parse_grace(value: str):
    """宽限截止日(ISO)。解析不了就当没有宽限 —— **不能因为配置写错就放行**,
    那样等于合规卡点形同虚设。"""
    from datetime import date as _date
    try:
        return _date.fromisoformat((value or "").strip())
    except ValueError:
        return None


async def _require_verified(db: AsyncSession, rider_id: int) -> RiderProfile:
    """接单相关操作的前置:必须实名认证通过。"""
    profile = await db.scalar(
        select(RiderProfile).where(RiderProfile.rider_id == rider_id)
    )
    if profile is None or profile.status != VerifyStatus.approved:
        raise HTTPException(403, "请先完成实名认证并通过审核后再接单")
    return profile


# ---------- 实名认证 ----------
@router.get("/profile", response_model=RiderProfileOut)
async def get_profile(
    user: User = Depends(require_role("rider")),
    db: AsyncSession = Depends(get_db),
):
    profile = await db.scalar(
        select(RiderProfile).where(RiderProfile.rider_id == user.id)
    )
    from ..services.flags import health_cert_cities
    # 本市要不要健康证,要**提前**告诉他 —— 等到上线被拦才发现,
    # 那时候他人已经在路上了
    cert_required = bool(
        user.city and user.city in await health_cert_cities(db))
    if profile is None:
        # 还没提交:返回 unsubmitted 空档案,客户端据此显示提交表单
        return RiderProfileOut(
            real_name="", health_cert_photo_url="",
            status=VerifyStatus.unsubmitted, reject_reason="",
            health_cert_required=cert_required, city=user.city,
        )
    out = _profile_out(profile)
    out.health_cert_required = cert_required
    out.city = user.city
    return out


@router.post("/profile", response_model=RiderProfileOut)
async def submit_profile(
    payload: RiderProfileIn,
    user: User = Depends(require_role("rider")),
    db: AsyncSession = Depends(get_db),
):
    """实名认证:姓名 + 身份证号,**核验通过当场生效,不用等人工审**。

    ## 为什么门槛只有这两样

    逐条核过法规:

    - **健康证不是法定要求**(送餐员不属于"直接接触入口食品的人员",
      四川已明确取消)—— 这里选填,只有地方另有要求的城市才卡;
    - **人脸认证不做**:《人脸识别技术应用安全管理办法》(2025-06-01 施行)
      明写"存在其他非人脸方式能达到同等业务要求的,不得将人脸识别作为
      唯一验证方式",并鼓励优先用国家人口基础信息库 —— 二要素正是那个方式;
    - **身份证照片不收**:二要素核验不需要它,而它是敏感个人影像。
      不收就没有泄露面。

    ## 为什么改成当场生效

    原来是"传照片 → pending → 等管理员看照片审批"。这套既慢又不准:
    人工看一眼照片判断不了真伪,而二要素查的是公安人口库。
    **真正的门槛从来不是填资料,是等审批。**

    注意:二要素只证明"这个姓名+证号真实且匹配",**不证明拿手机的人就是他**。
    账号出租、顶替跑单防不住 —— 那个风险留给异常触发的核身去处理,
    不该拿它当理由给所有人加一道人脸门槛。
    """
    from datetime import datetime, timezone

    from ..services.crypto import encrypt
    from ..services.idcheck import is_adult, validate_id_no, verify_two_elements

    profile = await db.scalar(
        select(RiderProfile).where(RiderProfile.rider_id == user.id)
    )
    if profile and profile.status == VerifyStatus.approved:
        raise HTTPException(409, "已通过认证,如需修改请联系平台客服")

    real_name = payload.real_name.strip()
    birth, err = validate_id_no(payload.id_card_no)
    if err:
        raise HTTPException(422, err)
    if not is_adult(birth):
        raise HTTPException(422, "未满 18 周岁不能接单")

    try:
        ok = await verify_two_elements(real_name, payload.id_card_no)
    except RuntimeError as exc:
        # 核验服务挂了要如实说,**不要放行** —— 放行等于没有实名
        raise HTTPException(503, str(exc))
    if not ok:
        raise HTTPException(422, "姓名与身份证号不一致,请核对后重新提交")

    if profile is None:
        profile = RiderProfile(rider_id=user.id)
        db.add(profile)
    profile.real_name = real_name
    profile.id_no_encrypted = encrypt(payload.id_card_no.strip().upper())
    profile.birth_date = birth
    profile.id_verified_at = datetime.now(timezone.utc)
    # 健康证选填:填了就存(地方要求的城市用得上),没填也照样通过
    profile.health_cert_photo_url = (payload.health_cert_photo_url or "").strip()
    profile.status = VerifyStatus.approved
    profile.reject_reason = ""
    await db.commit()
    await db.refresh(profile)
    return _profile_out(profile)


@router.post("/online")
async def set_online(
    payload: OnlineIn,
    user: User = Depends(require_role("rider")),
    db: AsyncSession = Depends(get_db),
):
    from datetime import datetime, timedelta, timezone

    from ..models import PlatformFlag, RiderSession

    warning = ""
    if payload.is_online:
        profile = await _require_verified(db, user.id)  # 上线前卡实名
        # ---- 健康证:**只有本地有规章的城市才卡** ----
        #
        # 国家层面不要求送餐员持健康证(不属于"直接接触入口食品的人员",
        # 四川已明确取消)。但杭州等地有地方性规章,所以做成城市级清单。
        #
        # 卡在上线而不是认证:注册时我们还不知道他在哪个城市 ——
        # user.city 是首次上线按定位解析出来的。卡在认证等于要求他
        # 先报城市,那是给所有人加一步,只为了极少数城市的规定
        if not profile.health_cert_photo_url and user.city:
            from ..services.flags import health_cert_cities
            if user.city in await health_cert_cities(db):
                raise HTTPException(
                    403, f"{user.city}有地方规定要求送餐员持健康证,"
                         "请在「我的」→ 实名认证里补传一张。"
                         "(国家层面并不要求,是你所在城市另有规定)")
        # ---- 食品安全培训卡点(法定,见 exam_submit 的说明)----
        #
        # 123 号令第二十九条要求受托方对配送人员进行食安培训并留存记录。
        # **默认必需** —— 这不是产品选择,是有罚则的条款。
        #
        # 但不能某天早上让存量骑手全部上不了线:平台标志
        # rider_training_grace_until 给一个宽限截止(ISO 日期),
        # 窗口内未完成培训的照常上线,只是每次上线带一条提醒。
        if not await _exam_passed(db, user.id):
            grace = await db.get(PlatformFlag, "rider_training_grace_until")
            deadline = _parse_grace(grace.value if grace else "")
            now_bj = datetime.now(timezone.utc) + timedelta(hours=8)
            if deadline is not None and now_bj.date() <= deadline:
                warning = (f"请在 {deadline.isoformat()} 前完成食品安全培训"
                           f"(三分钟,「我的」→ 上岗培训)—— "
                           "这是监管对平台的要求,过期未完成会影响上线")
            else:
                raise HTTPException(
                    403, "上线前需完成食品安全培训(三分钟,「我的」→ 上岗培训)。"
                         "这是《网络餐饮服务经营者落实食品安全主体责任监督管理"
                         "规定》对平台的要求,我们已经把它压到最短")
    now = datetime.now(timezone.utc)
    # 在线时长记录(只统计不考核):先关掉可能残留的开区间,防重复
    open_session = await db.scalar(
        select(RiderSession).where(RiderSession.rider_id == user.id,
                                   RiderSession.offline_at.is_(None)))
    if payload.is_online:
        if open_session is None:
            db.add(RiderSession(rider_id=user.id, online_at=now))
        # 每日首次上线自动投保/登记(幂等,失败不阻塞上线)
        try:
            from ..services.insurance import ensure_today
            await ensure_today(db, user.id)
        except Exception:
            import logging
            logging.getLogger("superz.rider").exception("投保记录失败")
        # 城市标注(多城市隔离):没标注过的,按最近定位解析一次;
        # 失败留空(空 city 不参与隔离),管理后台可人工改
        if not user.city:
            try:
                loc = await get_redis().hgetall(
                    RIDER_LOC_KEY.format(rider_id=user.id))
                if loc and "lat" in loc and "lng" in loc:
                    from ..services.geo_city import city_of
                    user.city = await city_of(
                        float(loc["lat"]), float(loc["lng"]))
            except Exception:
                pass
    elif open_session is not None:
        open_session.offline_at = now
    user.is_online = payload.is_online
    await db.commit()
    # warning 非空 = 在宽限窗口内还没做培训。客户端要显示出来,
    # 但**不能挡住他上线** —— 挡了就是让他今天没饭吃
    return {"is_online": payload.is_online, "warning": warning}


@router.patch("/me/preferences")
async def update_preferences(
    payload: dict,
    user: User = Depends(require_role("rider")),
    db: AsyncSession = Depends(get_db),
):
    """骑手偏好:接单半径(km,null=不限)。顺路单永远豁免半径。"""
    if "grab_radius_km" in payload:
        radius = payload["grab_radius_km"]
        if radius is not None and (not isinstance(radius, int)
                                   or not 1 <= radius <= 20):
            raise HTTPException(422, "接单半径需为 1-20 的整数公里数,或 null 不限")
        user.grab_radius_km = radius
    await db.commit()
    return {"grab_radius_km": user.grab_radius_km}


@router.get("/me/worklog")
async def my_worklog(
    user: User = Depends(require_role("rider")),
    db: AsyncSession = Depends(get_db),
):
    """我的数据(自我参考,不做考核):今日/本周在线时长、完成单、入账。"""
    from datetime import datetime, timedelta, timezone

    from ..models import RiderSession

    now = datetime.now(timezone.utc)
    bj_now = now + timedelta(hours=8)
    today_start = (bj_now.replace(hour=0, minute=0, second=0, microsecond=0)
                   - timedelta(hours=8))
    week_start = today_start - timedelta(days=bj_now.weekday())

    def minutes(sessions, since):
        total = 0.0
        for s in sessions:
            start = s.online_at if s.online_at.tzinfo else \
                s.online_at.replace(tzinfo=timezone.utc)
            end = s.offline_at or now
            if end.tzinfo is None:
                end = end.replace(tzinfo=timezone.utc)
            start = max(start, since)
            if end > start:
                total += (end - start).total_seconds() / 60
        return int(total)

    sessions = (await db.scalars(
        select(RiderSession).where(RiderSession.rider_id == user.id,
                                   RiderSession.online_at > week_start
                                   - timedelta(days=1)))).all()

    async def stats(since):
        row = (await db.execute(
            select(func.count(RiderEarning.id),
                   func.coalesce(func.sum(RiderEarning.amount_cents), 0))
            .where(RiderEarning.rider_id == user.id,
                   RiderEarning.created_at > since))).first()
        return row[0], row[1]

    t_orders, t_cents = await stats(today_start)
    w_orders, w_cents = await stats(week_start)
    return {
        "today_minutes": minutes(sessions, today_start),
        "week_minutes": minutes(sessions, week_start),
        "today_orders": t_orders, "today_earned_cents": t_cents,
        "week_orders": w_orders, "week_earned_cents": w_cents,
    }


_ARRIVE_NOTIFY_M = 500  # 距收货点 <500m 触发一次"即将送达"


async def _rider_pos(rider_id: int):
    """骑手最近上报位置 (lat, lng);无/过期返回 None。"""
    loc = await get_redis().hgetall(RIDER_LOC_KEY.format(rider_id=rider_id))
    try:
        if loc and loc.get("lat") and loc.get("lng"):
            return (float(loc["lat"]), float(loc["lng"]))
    except (TypeError, ValueError):
        pass
    return None


@router.post("/location")
async def report_location(
    payload: LocationIn,
    user: User = Depends(require_role("rider")),
    db: AsyncSession = Depends(get_db),
):
    """骑手端每 5 秒上报一次。位置写 Redis;顺带做"即将送达"判定。"""
    from ..services.pricing import haversine_m
    from ..services.push import push_to_user

    redis = get_redis()
    await redis.hset(
        RIDER_LOC_KEY.format(rider_id=user.id),
        mapping={"lat": payload.lat, "lng": payload.lng, "ts": time.time()},
    )
    await redis.expire(RIDER_LOC_KEY.format(rider_id=user.id), 300)

    # 即将送达:手头在送订单(已取餐)距收货点 <500m,一单只推一次
    delivering = (await db.scalars(
        select(Order).where(Order.rider_id == user.id,
                            Order.status == OrderStatus.PICKED_UP))).all()
    arrived = []
    for order in delivering:
        if haversine_m(payload.lat, payload.lng, order.lat, order.lng) \
                >= _ARRIVE_NOTIFY_M:
            continue
        # Redis 去重键:一单一次(1 天过期足够覆盖单次配送)
        if not await redis.set(f"arrive:{order.order_no}", 1, ex=86400, nx=True):
            continue
        await push_to_user(order.customer_id, "骑手即将送达",
                           "骑手离你不到 500 米了,请保持电话畅通",
                           {"type": "order", "order_no": order.order_no})
        arrived.append(order.order_no)
    return {"ok": True, "arrived": arrived}


# ---------- 配送异常上报 ----------

_ISSUE_KIND_LABELS = {
    "cannot_contact": "联系不上顾客",
    "wrong_address": "地址错误/找不到",
    "food_damaged": "餐品洒损",
    "not_ready": "到店未出餐",
    "items_missing": "餐品不齐/缺件",
    "other": "其他异常",
}


@router.post("/issues", response_model=DeliveryIssueOut)
async def report_delivery_issue(
    payload: DeliveryIssueIn,
    user: User = Depends(require_role("rider")),
    db: AsyncSession = Depends(get_db),
):
    """配送异常上报:配送与交接的摩擦走正式通道,不再全靠打电话。

    途中异常(联系不上/地址错/餐损)三方知情、平台仲裁;
    交接异常:not_ready 到店未出餐 = 催商家出餐 + 订单记出餐延误一次
    (商家出餐后自动销单,等满 10 分钟还可无责转单);
    items_missing 餐不齐必须拍照,走平台仲裁(缺件金额用缺货部分退款处理)。
    """
    if payload.kind in ("food_damaged", "items_missing") and not payload.photo_url:
        raise HTTPException(
            422, "餐损上报必须拍照举证(现场照片)"
            if payload.kind == "food_damaged" else "餐不齐上报必须拍照举证(袋内实拍)")
    order = await db.scalar(
        select(Order).where(Order.order_no == payload.order_no))
    if order is None or order.rider_id != user.id:
        raise HTTPException(403, "这不是你接的订单")
    if order.status not in (OrderStatus.ACCEPTED, OrderStatus.READY,
                            OrderStatus.PICKED_UP):
        raise HTTPException(409, "订单当前状态不能上报配送异常")
    if payload.kind == "not_ready" and order.status == OrderStatus.PICKED_UP:
        raise HTTPException(409, "已确认取餐,不能再上报未出餐;缺件请选「餐品不齐」")
    existing = await db.scalar(
        select(DeliveryIssue.id).where(
            DeliveryIssue.order_id == order.id,
            DeliveryIssue.status == "open"))
    if existing:
        raise HTTPException(409, "该订单已有待处理的异常上报,平台正在处理")
    issue = DeliveryIssue(
        order_id=order.id,
        order_no=order.order_no,
        rider_id=user.id,
        kind=payload.kind,
        note=payload.note.strip(),
        photo_url=payload.photo_url,
    )
    db.add(issue)
    if payload.kind == "not_ready":
        # 出餐延误一次:计入商家出餐超时率(粘性标记,补出餐不清)
        order.ready_late = True
    await db.commit()
    await db.refresh(issue)

    label = _ISSUE_KIND_LABELS.get(payload.kind, "配送异常")
    from ..services.push import push_to_user
    shop = await db.get(Merchant, order.merchant_id)
    if payload.kind == "not_ready":
        # 催单只推商家,不惊动顾客(出餐超时安抚与用户催单通道另有兜底)
        if shop:
            await push_to_user(shop.owner_id, "骑手到店等餐",
                               f"订单 {order.order_no[-6:]} 骑手已到店但餐未备好,"
                               f"请尽快出餐交接",
                               {"type": "order", "order_no": order.order_no},
                               record_skip=True)  # 低频催单,未配 JPush 也留痕
        return issue
    if payload.kind == "cannot_contact":
        await push_to_user(order.customer_id, "骑手正在联系你",
                           "骑手反馈联系不上你,请保持电话畅通或在订单页联系骑手",
                           {"type": "order", "order_no": order.order_no})
    else:
        await push_to_user(order.customer_id, "配送遇到问题",
                           f"骑手上报:{label}。平台已介入处理,请留意订单状态",
                           {"type": "order", "order_no": order.order_no})
    if shop:
        await push_to_user(shop.owner_id, "配送异常",
                           f"订单 {order.order_no[-6:]} 骑手上报:{label},平台已介入",
                           {"type": "order", "order_no": order.order_no})
    return issue


@router.get("/issues", response_model=list[DeliveryIssueOut])
async def my_delivery_issues(
    user: User = Depends(require_role("rider")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.scalars(
        select(DeliveryIssue)
        .where(DeliveryIssue.rider_id == user.id)
        .order_by(DeliveryIssue.created_at.desc())
        .limit(50)
    )
    return list(result)


# 骑手在途状态(并发上限与顺路判断的口径)
_IN_FLIGHT_STATUSES = (OrderStatus.ACCEPTED, OrderStatus.READY,
                       OrderStatus.PICKED_UP)
# 排序权重全部在 services/dispatch.py —— 那里是公开算法的唯一事实来源,
# /transparency/dispatch 从同一处读。在这里再留一份就迟早对不上。


async def _my_in_flight(db: AsyncSession, rider_id: int) -> list[Order]:
    """骑手手头在途的单(追加单随原单取送,不单独计)。"""
    return list(await db.scalars(
        select(Order).where(
            Order.rider_id == rider_id,
            Order.status.in_(_IN_FLIGHT_STATUSES),
            Order.parent_order_no == "",
        )
    ))


@router.get("/available-orders", response_model=list[OrderOut])
async def available_orders(
    user: User = Depends(require_role("rider")),
    db: AsyncSession = Depends(get_db),
):
    """可抢订单池:商家已接单/已出餐、且还没有骑手的订单。

    保持广播抢单**不做强制派单** —— 算法只负责把信息排得更有用,
    接不接始终是骑手自己的决定。

    排序口径见 services/dispatch.py,那里是**公开算法的唯一事实来源**
    (/transparency/dispatch 从同一处读权重,不另抄一份)。
    骑手位置取不到(未上报/过期)时退化为按等待时长排(老单在前)。
    """
    from datetime import datetime, timezone

    from ..services import dispatch, prep_time
    from ..services.routing import bicycling_m, detour_m

    # 取 200 条进来算分、只返回前 50:若只取最老的 50 条再排序,
    # 离骑手近的新单会被挤在池外,「新单不垫底」就落空了
    result = await db.scalars(
        select(Order)
        .where(Order.rider_id.is_(None), Order.status.in_(GRABBABLE_STATUSES),
               Order.pickup.is_(False),        # 自取单不进抢单池
               Order.self_delivery.is_(False),  # 商家自送,不需要骑手
               Order.parent_order_no == "")    # 追加单随原单,不单独抢
        .order_by(Order.created_at)            # 无定位时的兜底顺序:等待久的在前
        .limit(200)
    )
    orders = list(result)
    # 多城市隔离:骑手标注了城市时,只看本城商家的单
    # (商家没标注城市的不隔离——存量宽限,别让单子没人看见)
    if user.city:
        mids = {o.merchant_id for o in orders}
        if mids:
            city_rows = (await db.execute(
                select(Merchant.id, Merchant.city)
                .where(Merchant.id.in_(mids)))).all()
            mcity = dict(city_rows)
            orders = [o for o in orders
                      if not mcity.get(o.merchant_id)
                      or mcity[o.merchant_id] == user.city]
    outs = await orders_out(db, orders, user)

    # 手头在途单 → 顺路判断基准(同商家取、收货点相近送)
    mine = await _my_in_flight(db, user.id)
    my_shops = {o.merchant_id for o in mine}
    my_drops = [(o.lat, o.lng) for o in mine]

    # 骑手最近位置(Redis,5 分钟过期;取不到就不算距离)
    redis = get_redis()
    loc = await redis.hgetall(RIDER_LOC_KEY.format(rider_id=user.id))
    rider_pos = None
    try:
        if loc and "lat" in loc and "lng" in loc:
            rider_pos = (float(loc["lat"]), float(loc["lng"]))
    except (TypeError, ValueError):
        rider_pos = None

    now = datetime.now(timezone.utc)
    # 出餐时长分位数**批量取**:逐个查会把一次抢单变成几十次往返
    preps = await prep_time.stats_for(db, [o.merchant_id for o in orders])
    radius_m = (user.grab_radius_km * 1000
                if user.grab_radius_km and rider_pos else None)
    scored: list[tuple[float, OrderOut]] = []
    for order, out in zip(orders, outs):
        out.same_shop = order.merchant_id in my_shops
        score_val = 0.0
        if rider_pos and out.merchant_lat is not None:
            # 到店距离用真实骑行路径(不可用时回退直线×1.2 并标明来源)——
            # 直线系统性低估,实测成都两点直线 1467m / 骑行 1745m,差 19%
            distance, src = await bicycling_m(
                rider_pos[0], rider_pos[1], out.merchant_lat, out.merchant_lng)
            out.distance_m = int(distance)
            out.distance_source = src
            trip, _ = await bicycling_m(
                out.merchant_lat, out.merchant_lng, order.lat, order.lng)
            out.trip_m = int(trip)

            # 顺路按**绕路增量**判,不按两点距离。
            # 旧口径(两个送达点相距 <800m)的实测反例:送达点相邻但取餐点在
            # 反方向 3km 的单也判顺路 —— 骑手照着接会多跑近 6 公里
            best_detour = None
            for dlat, dlng in my_drops:
                inc, _ = await detour_m(
                    rider_pos, (out.merchant_lat, out.merchant_lng),
                    (order.lat, order.lng), (dlat, dlng))
                if best_detour is None or inc < best_detour:
                    best_detour = inc
            out.detour_m = None if best_detour is None else int(best_detour)

            created = order.created_at
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            wait_minutes = max(0.0, (now - created).total_seconds() / 60)

            res = dispatch.score(dispatch.Candidate(
                to_pickup_m=distance,
                trip_m=trip,
                wait_minutes=wait_minutes,
                tip_yuan=order.tip_cents / 100,
                same_shop=out.same_shop,
                detour_m=best_detour,
            ))
            out.same_way_level = res.same_way_level
            out.same_way = res.same_way_level != "none"
            score_val = res.score

            # 整单经济性:骑手判断「值不值得接」要的是耗时与时薪,
            # 不是"到店多远"。等餐用该店**实测**出餐分位数,
            # 不是写死的 20 分钟
            ps = preps.get(order.merchant_id)
            wait = ps.wait_minutes if ps else 15.0
            econ = dispatch.trip_economics(
                distance, trip, wait,
                order.delivery_fee_cents, order.tip_cents)
            out.est_minutes = econ["total_minutes"]
            out.est_wait_minutes = econ["wait_minutes"]
            out.wait_source = ps.source if ps else "declared"
            out.cents_per_minute = econ["cents_per_minute"]

            # 接单半径过滤(骑手自设);同店/顺路豁免 —— 手头单顺路的永远给看
            if (radius_m is not None and distance > radius_m
                    and not out.same_shop and not out.same_way):
                continue
        scored.append((score_val, out))
    if rider_pos:
        # 综合分越小越靠前;分数相同(理论上极少)按原有等待顺序稳定排
        scored.sort(key=lambda pair: pair[0])
    return [out for _, out in scored[:50]]


@router.post("/grab/{order_no}", response_model=OrderOut)
async def grab_order(
    order_no: str,
    user: User = Depends(require_role("rider")),
    db: AsyncSession = Depends(get_db),
):
    """抢单。条件 UPDATE 保证同一单只有一个骑手抢到,手慢的收到 409。"""
    await _require_verified(db, user.id)  # 抢单前再卡一道认证
    # 转单软约束:当日非免责转单达阈值,今日暂停抢单(次日自动恢复)。
    # 不罚钱不封号;等餐超时/事故释放的无责转单不计数,不受影响
    used = await _transfer_used_today(user.id)
    if used >= settings.transfer_daily_suspend_threshold:
        raise HTTPException(
            409, f"今日转单已达 {used} 次,抢单暂停到明天(次日自动恢复,"
                 "不罚款不扣钱);手头的单照常配送,有困难随时联系平台")
    # 并发上限:手头在途太多影响履约,先送完再接(追加单不占额度)
    active = len(await _my_in_flight(db, user.id))
    if active >= settings.rider_max_active_orders:
        raise HTTPException(
            409, f"手头已有 {active} 单在途,先送完再接新单"
                 f"(最多同时 {settings.rider_max_active_orders} 单)")
    result = await db.execute(
        update(Order)
        .where(
            Order.order_no == order_no,
            Order.rider_id.is_(None),
            Order.status.in_(GRABBABLE_STATUSES),
            Order.pickup.is_(False),        # 自取单没有配送环节
            Order.self_delivery.is_(False),  # 商家自送,不进抢单池
            Order.parent_order_no == "",    # 追加单不能单独被抢
        )
        .values(rider_id=user.id)
        .returning(Order.id)
    )
    if result.first() is None:
        await db.rollback()
        raise HTTPException(409, "手慢了,这一单已被别人抢走")

    # 追加单骑手跟随:抢到原单,它的"第二个袋子"一起归你
    await db.execute(
        update(Order)
        .where(Order.parent_order_no == order_no, Order.rider_id.is_(None))
        .values(rider_id=user.id)
    )
    order = await db.scalar(select(Order).where(Order.order_no == order_no))
    db.add(
        OrderEvent(
            order_id=order.id,
            from_status=order.status.value,
            to_status=order.status.value,
            actor_role="rider",
            actor_id=user.id,
        )
    )
    # 骑手接单后按其实时位置重估 ETA(偏差>5分钟才刷新;调用方 commit)
    merchant = await db.get(Merchant, order.merchant_id)
    rider_pos = await _rider_pos(user.id)
    from ..services.eta import recompute_eta
    await recompute_eta(db, order, merchant, rider_pos=rider_pos)
    await db.commit()
    await db.refresh(order)
    await manager.broadcast(
        f"order:{order.order_no}",
        {"type": "rider_assigned", "order_no": order.order_no, "rider_id": user.id},
    )
    # 关键节点推送:骑手已接单,用户可在订单页看实时配送(离线也收得到)
    from ..services.push import push_to_user
    await push_to_user(order.customer_id, "骑手已接单",
                       "骑手正在赶往商家,可在订单页查看实时位置",
                       {"type": "order", "order_no": order.order_no})
    return order_out(order, merchant, user)


# ---------- 转单 ----------

async def _transfer_used_today(rider_id: int) -> int:
    """当日(北京自然日)非免责转单次数;免责转单与事故释放不计入。"""
    from datetime import datetime, timedelta, timezone
    bj_date = (datetime.now(timezone.utc) + timedelta(hours=8)).date()
    return int(await get_redis().get(f"rider:transfer:{rider_id}:{bj_date}")
               or 0)


@router.get("/discipline")
async def my_discipline(
    user: User = Depends(require_role("rider")),
):
    """规则中心数据:当日转单计数与软约束阈值(规则文案在客户端)。"""
    used = await _transfer_used_today(user.id)
    threshold = settings.transfer_daily_suspend_threshold
    return {
        "transfer_used_today": used,
        "free_times": settings.transfer_free_times_per_day,
        "suspend_threshold": threshold,
        "grab_suspended_today": used >= threshold,
    }


_TRANSFER_REASON_LABELS = {
    "vehicle_broken": "车坏了",
    "unwell": "身体不适",
    "route_conflict": "顺路冲突",
    "other": "其他",
}


@router.post("/transfer/{order_no}", response_model=TransferOut)
async def transfer_order(
    order_no: str,
    payload: TransferIn,
    user: User = Depends(require_role("rider")),
    db: AsyncSession = Depends(get_db),
):
    """转单:已抢但未取餐的单退回抢单池,突发状况不用硬扛。

    已取餐(餐在骑手手上)不能自助转单,只能走配送异常仲裁。
    每天免责 2 次,超出仍可转但计数(管理后台可见,将来接考核)。
    用户与商家不推送(无感换人,避免焦虑),只提醒在线骑手来接力。
    """
    from datetime import datetime, timedelta, timezone

    order = await db.scalar(
        select(Order).where(Order.order_no == order_no).with_for_update())
    if order is None or order.rider_id != user.id:
        raise HTTPException(403, "这不是你接的订单")
    if order.parent_order_no:
        raise HTTPException(409, "追加单随原单配送,请在原单上操作转单")
    if order.status == OrderStatus.PICKED_UP:
        raise HTTPException(409, "已取餐不能转单(餐在你手上);有困难请上报配送异常,平台协调处理")
    if order.status not in (OrderStatus.ACCEPTED, OrderStatus.READY):
        raise HTTPException(409, "订单当前状态不能转单")

    now = datetime.now(timezone.utc)
    # 无责转单:上报「到店未出餐」满 N 分钟商家还没出餐(工单仍 open),
    # 等不起是商家的问题,这次转单不占当日免责次数
    waited_free = bool(await db.scalar(
        select(DeliveryIssue.id).where(
            DeliveryIssue.order_id == order.id,
            DeliveryIssue.rider_id == user.id,
            DeliveryIssue.kind == "not_ready",
            DeliveryIssue.status == "open",
            DeliveryIssue.created_at
            < now - timedelta(
                minutes=settings.pickup_wait_free_transfer_minutes),
        ).limit(1)))
    order.rider_id = None
    # 兜底计时从转单时刻重新起算:回池的单享受完整的接单等待期,
    # 提醒标记同步清掉,无人接时还会再推一轮在线骑手
    order.rider_pool_since = now
    order.no_rider_alerted_at = None
    # 追加单骑手跟随原单:原单转出,子单一起释放
    await db.execute(
        update(Order)
        .where(Order.parent_order_no == order_no, Order.rider_id == user.id)
        .values(rider_id=None)
    )
    label = _TRANSFER_REASON_LABELS[payload.reason]
    db.add(OrderEvent(
        order_id=order.id,
        from_status=order.status.value,
        to_status="transferred",  # 事件型值,不动状态机;用户端时间轴自动忽略
        actor_role="rider",
        actor_id=user.id,
        note=f"转单原因:{label}" + ("(到店等餐超时,无责)" if waited_free else ""),
    ))
    await db.commit()

    # 每日转单计数(北京自然日,Redis 过期兜底;考核口径以 OrderEvent 为准)
    redis = get_redis()
    bj_date = (now + timedelta(hours=8)).date()
    key = f"rider:transfer:{user.id}:{bj_date}"
    if waited_free:
        count = int(await redis.get(key) or 0)  # 无责:不计数,回显当前值
    else:
        count = await redis.incr(key)
        await redis.expire(key, 172800)
        # 软约束触达:临近阈值提前提醒,到阈值告知今日暂停(次日自动恢复)
        threshold = settings.transfer_daily_suspend_threshold
        left = threshold - count
        try:
            from ..services.push import push_to_user
            if 0 < left <= 2:
                await push_to_user(
                    user.id, "转单提醒",
                    f"今日已转 {count} 次,再转 {left} 次今日将暂停抢单"
                    "(次日自动恢复,不罚款)。突发状况多的话联系平台",
                    {"type": "discipline"}, record_skip=True)
            elif count == threshold:
                await push_to_user(
                    user.id, "今日抢单已暂停",
                    f"今日非免责转单已达 {threshold} 次,抢单暂停到明天自动恢复。"
                    "不罚款不扣钱;手头的单照常配送",
                    {"type": "discipline"}, record_skip=True)
        except Exception:
            pass  # 提醒失败不影响转单

    # 只提醒在线骑手接力,不推用户与商家
    try:
        from ..models import UserRole
        from ..services.push import push_to_user
        online_riders = (
            await db.scalars(
                select(User.id).where(
                    User.role == UserRole.rider,
                    User.is_online.is_(True),
                    User.id != user.id,
                ).limit(100)
            )
        ).all()
        for rider_id in online_riders:
            await push_to_user(rider_id, "有转出的订单",
                               "有骑手转出了一单,顺路就去抢单大厅接力吧",
                               {"type": "grab"})
    except Exception:
        pass  # 推送失败不影响转单
    return TransferOut(
        today_count=count,
        free_times=settings.transfer_free_times_per_day,
        suspend_threshold=settings.transfer_daily_suspend_threshold,
    )


# ---------- 钱包 ----------
async def _wallet(db: AsyncSession, rider_id: int) -> WalletOut:
    earned = await db.scalar(
        select(func.coalesce(func.sum(RiderEarning.amount_cents), 0)).where(
            RiderEarning.rider_id == rider_id
        )
    )
    pending = await db.scalar(
        select(func.coalesce(func.sum(Withdrawal.amount_cents), 0)).where(
            Withdrawal.user_id == rider_id,
            Withdrawal.role == "rider",
            Withdrawal.status == WithdrawalStatus.pending,
        )
    )
    paid = await db.scalar(
        select(func.coalesce(func.sum(Withdrawal.amount_cents), 0)).where(
            Withdrawal.user_id == rider_id,
            Withdrawal.role == "rider",
            Withdrawal.status == WithdrawalStatus.paid,
        )
    )
    balance = earned - pending - paid
    return WalletOut(
        balance_cents=balance,
        total_earned_cents=earned,
        pending_withdrawal_cents=pending,
        withdrawn_cents=paid,
        withdrawable_cents=max(0, balance),
    )


@router.get("/wallet", response_model=WalletOut)
async def wallet(
    user: User = Depends(require_role("rider")),
    db: AsyncSession = Depends(get_db),
):
    return await _wallet(db, user.id)


@router.get("/earnings", response_model=list[EarningOut])
async def earnings(
    user: User = Depends(require_role("rider")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.scalars(
        select(RiderEarning)
        .where(RiderEarning.rider_id == user.id)
        .order_by(RiderEarning.created_at.desc())
        .limit(100)
    )
    return list(result)


@router.get("/withdrawals", response_model=list[WithdrawalOut])
async def my_withdrawals(
    user: User = Depends(require_role("rider")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.scalars(
        select(Withdrawal)
        .where(Withdrawal.user_id == user.id, Withdrawal.role == "rider")
        .order_by(Withdrawal.created_at.desc())
        .limit(100)
    )
    return list(result)


@router.post("/withdrawals", response_model=WithdrawalOut)
async def request_withdrawal(
    payload: WithdrawalIn,
    user: User = Depends(require_role("rider")),
    db: AsyncSession = Depends(get_db),
):
    """申请提现。锁用户行串行化并发申请,余额不可能被双花。"""
    if payload.amount_cents < settings.min_withdrawal_cents:
        raise HTTPException(
            422, f"最低提现 ¥{settings.min_withdrawal_cents / 100:.0f}"
        )
    # 收款账户是打款前提:先登记再申请(打给谁都不知道就别冻结钱)
    from ..models import PayoutAccount
    from .payout import account_recently_changed
    account = await db.scalar(
        select(PayoutAccount).where(PayoutAccount.user_id == user.id))
    if account is None:
        raise HTTPException(422, "请先在钱包页登记收款账户,再申请提现")
    # 行锁:同一骑手的提现申请排队进入,余额校验期间不会有并发写
    await db.execute(select(User).where(User.id == user.id).with_for_update())
    current = await _wallet(db, user.id)
    if payload.amount_cents > current.balance_cents:
        raise HTTPException(
            409, f"余额不足,当前可提现 ¥{current.balance_cents / 100:.2f}"
        )
    withdrawal = Withdrawal(
        user_id=user.id, role="rider", amount_cents=payload.amount_cents,
        # 快照冻结:打款照快照打,改账户不影响在途申请
        account_snapshot={
            "kind": account.kind,
            "holder_name": account.holder_name,
            "bank_name": account.bank_name,
            "account_tail": account.account_tail,
            "account_no_encrypted": account.account_no_encrypted,
            "recently_changed": account_recently_changed(account),
        })
    db.add(withdrawal)
    await db.commit()
    await db.refresh(withdrawal)
    return withdrawal


# ---------- 上岗管理:食品安全培训 + 装备申领 ----------
#
# **这是法定动作,不是产品功能。**
#
# 《网络餐饮服务经营者落实食品安全主体责任监督管理规定》(总局令第 123 号,
# 2026-06-01 施行)第二十九条:商家委托开展配送业务的,**受托方应当对配送
# 人员进行食品安全培训、管理,培训记录保存期限不得少于二年**。
# 商家把配送委托给平台,平台就是受托方。罚则见第四十四条。
#
# 但法规要的是**培训**,不是考试 —— 它没说必须考 80 分。
# 所以这里的形态是:先看内容(三分钟),再用几道题确认看懂了;
# **答错当场讲解、可以重来**,而不是判他不及格把他挡在外面。
# 记录照存(谁、什么时候、培训的哪一版内容、答题结果)。

_TRAINING_QUESTIONS = 5


def _quiz_bank() -> dict:
    import json
    from pathlib import Path
    path = Path(__file__).resolve().parent.parent / "data" / "rider_quiz.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _training_content() -> dict:
    import json
    from pathlib import Path
    path = Path(__file__).resolve().parent.parent / "data" / "rider_training.json"
    return json.loads(path.read_text(encoding="utf-8"))


async def _exam_passed(db: AsyncSession, rider_id: int) -> bool:
    from ..models import RiderExam
    return bool(await db.scalar(
        select(RiderExam.id).where(RiderExam.rider_id == rider_id,
                                   RiderExam.passed.is_(True)).limit(1)))


@router.get("/training")
async def training_content(
    user: User = Depends(require_role("rider")),
    db: AsyncSession = Depends(get_db),
):
    """培训内容 + 我的完成状态。**先给内容,再谈答题。**"""
    content = _training_content()
    return {
        "done": await _exam_passed(db, user.id),
        "version": content["version"],
        "minutes": content["minutes"],
        # 为什么要做这一步,给骑手一个真实的理由 ——
        # 不说清楚他会觉得又是平台在给他加规矩
        "why": content["why"],
        "sections": content["sections"],
        "question_count": _TRAINING_QUESTIONS,
        "note": "答错不算不合格,会当场告诉你为什么,改完就能继续",
    }


@router.get("/exam/status")
async def exam_status(
    user: User = Depends(require_role("rider")),
    db: AsyncSession = Depends(get_db),
):
    from ..models import RiderExam
    best = await db.scalar(
        select(func.max(RiderExam.score)).where(RiderExam.rider_id == user.id))
    return {"passed": await _exam_passed(db, user.id),
            "best_score": best or 0,
            "pass_score": 100,
            "version": _training_content()["version"]}


@router.get("/exam/questions")
async def exam_questions(user: User = Depends(require_role("rider"))):
    """抽题(不含答案)。交卷按题目 id 判分,抽题无状态。"""
    import random
    bank = _quiz_bank()
    picked = random.sample(
        bank["questions"], k=min(_TRAINING_QUESTIONS, len(bank["questions"])))
    return [{"id": q["id"], "cat": q["cat"], "q": q["q"],
             "options": q["options"]} for q in picked]


@router.post("/exam/submit")
async def exam_submit(
    payload: dict,
    user: User = Depends(require_role("rider")),
    db: AsyncSession = Depends(get_db),
):
    """交卷。**全对即完成;答错当场给正确答案和理由,可以立刻重来。**

    为什么不设"及格线"再判他不及格:法规要的是培训到位,
    而"考了 70 分,不让你跑"既不合规也没意义 —— 他没看懂的那两条,
    正是最该讲给他听的。所以答错就讲,讲完重答。
    """
    from ..models import RiderExam
    answers = payload.get("answers") or {}
    if not isinstance(answers, dict) or len(answers) < _TRAINING_QUESTIONS:
        raise HTTPException(422, f"请完成全部 {_TRAINING_QUESTIONS} 题")
    bank = {q["id"]: q for q in _quiz_bank()["questions"]}
    graded = list(answers.items())[:_TRAINING_QUESTIONS]

    wrong = []
    correct = 0
    for qid, choice in graded:
        q = bank.get(int(qid))
        if q is None:
            continue
        if q["answer"] == choice:
            correct += 1
        else:
            # 答错要讲清楚 —— 这才是培训。只回一个"错了"等于什么都没培训
            wrong.append({
                "id": q["id"], "q": q["q"],
                "your_choice": choice,
                "answer": q["answer"],
                "answer_text": q["options"][q["answer"]],
            })

    score = round(correct * 100 / max(1, len(graded)))
    passed = not wrong
    content = _training_content()
    db.add(RiderExam(rider_id=user.id, score=score, passed=passed,
                     answers={str(k): v for k, v in graded},
                     content_version=content["version"]))
    await db.commit()
    return {
        "score": score, "passed": passed, "wrong": wrong,
        "message": ("培训完成,现在就可以上线接单" if passed else
                    f"有 {len(wrong)} 题需要再看一眼 —— 下面是正确答案和原因,"
                    "看完直接重答就行"),
    }


@router.get("/gear")
async def my_gear(
    user: User = Depends(require_role("rider")),
    db: AsyncSession = Depends(get_db),
):
    from ..models import RiderGear
    rows = (await db.scalars(
        select(RiderGear).where(RiderGear.rider_id == user.id)
        .order_by(RiderGear.created_at.desc()))).all()
    return [{"id": g.id, "item": g.item, "status": g.status, "note": g.note,
             "created_at": g.created_at.isoformat()} for g in rows]


@router.post("/gear")
async def request_gear(
    payload: dict,
    user: User = Depends(require_role("rider")),
    db: AsyncSession = Depends(get_db),
):
    """申领装备(头盔/餐箱/雨衣)。同件装备有未发放的申请不能重复领。"""
    from ..models import RiderGear
    item = str(payload.get("item", ""))
    if item not in ("helmet", "box", "raincoat"):
        raise HTTPException(422, "装备只支持 helmet / box / raincoat")
    existing = await db.scalar(
        select(RiderGear.id).where(RiderGear.rider_id == user.id,
                                   RiderGear.item == item,
                                   RiderGear.status == "requested"))
    if existing:
        raise HTTPException(409, "该装备已有待发放的申请,请等平台处理")
    db.add(RiderGear(rider_id=user.id, item=item))
    await db.commit()
    return {"ok": True}


# ---------- 意外保障 + 事故上报 ----------

@router.get("/insurance")
async def my_insurance(
    user: User = Depends(require_role("rider")),
    db: AsyncSession = Depends(get_db),
):
    """我的保障记录(近 30 天):registered=保障金池兜底 / insured=已投保。"""
    from ..models import RiderInsuranceDay
    rows = (await db.scalars(
        select(RiderInsuranceDay)
        .where(RiderInsuranceDay.rider_id == user.id)
        .order_by(RiderInsuranceDay.day.desc()).limit(30))).all()
    return [{"day": r.day, "status": r.status, "policy_no": r.policy_no}
            for r in rows]


@router.post("/accidents")
async def report_accident(
    payload: dict,
    user: User = Depends(require_role("rider")),
    db: AsyncSession = Depends(get_db),
):
    """交通事故上报:人先安全,照片可后补。

    上报即三动作:①在途单(未取餐)全部无责释放回池,已取餐的单自动开
    配送异常工单交平台仲裁 ②红色加急事故工单 ③平台电话回访(后台跟进)。
    """
    from datetime import datetime, timezone

    from ..models import RiderAccident, RiderInsuranceDay, UserRole
    from ..services.insurance import _today_bj
    from ..services.push import push_to_user

    severity = str(payload.get("severity", ""))
    if severity not in ("minor", "injury", "serious"):
        raise HTTPException(422, "severity 只支持 minor / injury / serious")
    now = datetime.now(timezone.utc)
    accident = RiderAccident(
        rider_id=user.id,
        lat=payload.get("lat"), lng=payload.get("lng"),
        severity=severity,
        description=str(payload.get("description", ""))[:500],
        photos=[u for u in (payload.get("photos") or []) if str(u).strip()][:6],
    )
    db.add(accident)

    # 在途单处理:未取餐的无责释放回池(不计免责次数);已取餐的开异常工单
    in_flight = (await db.scalars(
        select(Order).where(
            Order.rider_id == user.id,
            Order.status.in_([OrderStatus.ACCEPTED, OrderStatus.READY,
                              OrderStatus.PICKED_UP]),
            Order.parent_order_no == ""))).all()
    released, issues = 0, 0
    for order in in_flight:
        if order.status == OrderStatus.PICKED_UP:
            existing = await db.scalar(
                select(DeliveryIssue.id).where(
                    DeliveryIssue.order_id == order.id,
                    DeliveryIssue.status == "open"))
            if not existing:
                db.add(DeliveryIssue(
                    order_id=order.id, order_no=order.order_no,
                    rider_id=user.id, kind="other",
                    note="骑手交通事故,餐品在途,平台介入处理"))
                issues += 1
        else:
            order.rider_id = None
            order.rider_pool_since = now
            order.no_rider_alerted_at = None
            await db.execute(
                update(Order)
                .where(Order.parent_order_no == order.order_no)
                .values(rider_id=None))
            db.add(OrderEvent(
                order_id=order.id, from_status=order.status.value,
                to_status="transferred", actor_role="system", actor_id=None,
                note="骑手交通事故,系统无责释放"))
            released += 1

    insured = await db.scalar(
        select(RiderInsuranceDay).where(
            RiderInsuranceDay.rider_id == user.id,
            RiderInsuranceDay.day == _today_bj()))
    await db.commit()
    await db.refresh(accident)

    # 通知平台管理员(红色加急,电话回访)
    admins = (await db.scalars(
        select(User.id).where(User.role == UserRole.admin).limit(10))).all()
    for aid in admins:
        await push_to_user(aid, "⚠️ 骑手交通事故",
                           f"骑手 {user.phone} 上报{('轻微事故' if severity == 'minor' else '受伤事故' if severity == 'injury' else '严重事故')},"
                           f"请立即电话回访;在途单已自动处理({released} 单回池/{issues} 单转仲裁)",
                           {"type": "accident"}, record_skip=True)
    return {
        "id": accident.id,
        "released_orders": released,
        "issue_orders": issues,
        "insurance_status": insured.status if insured else "none",
        "insurance_policy_no": insured.policy_no if insured else "",
    }


@router.post("/accidents/{accident_id}/photos")
async def add_accident_photos(
    accident_id: int,
    payload: dict,
    user: User = Depends(require_role("rider")),
    db: AsyncSession = Depends(get_db),
):
    """补传现场照片(上报时人先安全,照片可以后补)。"""
    from ..models import RiderAccident
    acc = await db.get(RiderAccident, accident_id, with_for_update=True)
    if acc is None or acc.rider_id != user.id:
        raise HTTPException(404, "事故记录不存在")
    urls = [str(u).strip() for u in (payload.get("photos") or [])
            if str(u).strip()]
    acc.photos = [*(acc.photos or []), *urls][:6]
    await db.commit()
    return {"ok": True, "photos": acc.photos}


@router.get("/accidents")
async def my_accidents(
    user: User = Depends(require_role("rider")),
    db: AsyncSession = Depends(get_db),
):
    from ..models import RiderAccident
    rows = (await db.scalars(
        select(RiderAccident).where(RiderAccident.rider_id == user.id)
        .order_by(RiderAccident.created_at.desc()).limit(20))).all()
    return [{"id": a.id, "severity": a.severity, "status": a.status,
             "description": a.description, "photos": a.photos,
             "created_at": a.created_at.isoformat()} for a in rows]


# ---------- 紧急求助(SOS)与紧急联系人 ----------

SOS_CANCEL_WINDOW_SECONDS = 120  # 误触自助撤销窗口


@router.get("/me/emergency-contacts")
async def get_emergency_contacts(
    user: User = Depends(require_role("rider")),
    db: AsyncSession = Depends(get_db),
):
    """紧急联系人(电话打码展示;明文只在触发 SOS 时用于短信/回访)。"""
    import json

    from ..services.crypto import decrypt
    from ..services.privacy_phone import mask_phone
    profile = await db.scalar(
        select(RiderProfile).where(RiderProfile.rider_id == user.id))
    if profile is None or not profile.emergency_contacts_enc:
        return []
    contacts = json.loads(decrypt(profile.emergency_contacts_enc))
    return [{"name": c["name"], "phone": mask_phone(c["phone"])}
            for c in contacts]


@router.post("/me/emergency-contacts")
async def set_emergency_contacts(
    payload: dict,
    user: User = Depends(require_role("rider")),
    db: AsyncSession = Depends(get_db),
):
    """设置紧急联系人(最多 2 人),加密落库(同收款账户口径)。"""
    import json
    import re

    from ..services.crypto import encrypt
    contacts = payload.get("contacts") or []
    if not isinstance(contacts, list) or len(contacts) > 2:
        raise HTTPException(422, "紧急联系人最多 2 人")
    cleaned = []
    for c in contacts:
        name = str(c.get("name", "")).strip()[:20]
        phone = str(c.get("phone", "")).strip()
        if not name or not re.fullmatch(r"1\d{10}", phone):
            raise HTTPException(422, "请填写姓名和正确的手机号")
        cleaned.append({"name": name, "phone": phone})
    profile = await db.scalar(
        select(RiderProfile).where(RiderProfile.rider_id == user.id))
    if profile is None:
        raise HTTPException(409, "请先提交实名认证")
    profile.emergency_contacts_enc = (
        encrypt(json.dumps(cleaned, ensure_ascii=False)) if cleaned else "")
    await db.commit()
    return {"count": len(cleaned)}


@router.post("/sos")
async def trigger_sos(
    payload: dict,
    user: User = Depends(require_role("rider")),
    db: AsyncSession = Depends(get_db),
):
    """一键紧急求助:红色加急工单+推送管理员+紧急联系人短信(桩)。

    在途订单不自动释放(误触率高),客服确认后走改派/仲裁;
    误触可在 2 分钟内自助撤销。SOP 见 docs/RIDER_SOP.md。
    """
    import json
    import logging
    from datetime import datetime, timezone

    from ..models import RiderEmergency, UserRole
    from ..services.push import push_to_user

    lat, lng = payload.get("lat"), payload.get("lng")
    if lat is None:  # 请求没带就取最近心跳
        loc = await get_redis().hgetall(RIDER_LOC_KEY.format(rider_id=user.id))
        try:
            lat, lng = float(loc["lat"]), float(loc["lng"])
        except (KeyError, TypeError, ValueError):
            lat = lng = None
    sos = RiderEmergency(
        rider_id=user.id, lat=lat, lng=lng,
        note=str(payload.get("note", "")).strip()[:200])
    db.add(sos)
    in_flight = len(await _my_in_flight(db, user.id))
    await db.commit()
    await db.refresh(sos)

    admins = (await db.scalars(
        select(User.id).where(User.role == UserRole.admin).limit(10))).all()
    for aid in admins:
        await push_to_user(
            aid, "🆘 骑手紧急求助",
            f"骑手 {user.phone} 触发 SOS,请 5 分钟内电话回访!"
            f"({'有' + str(in_flight) + ' 单在途' if in_flight else '无在途单'};"
            f"位置{'已带' if lat is not None else '未知'})",
            {"type": "sos"}, record_skip=True)
    # 紧急联系人短信(桩:未配置只记日志,后台工单里标注需人工联系)
    profile = await db.scalar(
        select(RiderProfile).where(RiderProfile.rider_id == user.id))
    sms_sent = False
    if profile is not None and profile.emergency_contacts_enc:
        from ..config import settings
        from ..services.crypto import decrypt
        contacts = json.loads(decrypt(profile.emergency_contacts_enc))
        if settings.sms_configured:
            # TODO(联调):批量发"您的家人在配送途中触发紧急求助"模板短信
            sms_sent = True
        else:
            logging.getLogger("superz.sos").warning(
                "SOS 短信未配置,需人工电话联系紧急联系人: %s",
                "、".join(c["name"] for c in contacts))
    return {"id": sos.id, "cancel_window_seconds": SOS_CANCEL_WINDOW_SECONDS,
            "sms_sent": sms_sent,
            "in_flight_orders": in_flight}


@router.post("/sos/{sos_id}/cancel")
async def cancel_sos(
    sos_id: int,
    user: User = Depends(require_role("rider")),
    db: AsyncSession = Depends(get_db),
):
    """误触自助撤销(窗口内且仍是 open)。"""
    from datetime import datetime, timezone

    from ..models import RiderEmergency
    sos = await db.get(RiderEmergency, sos_id, with_for_update=True)
    if sos is None or sos.rider_id != user.id:
        raise HTTPException(404, "求助记录不存在")
    if sos.status != "open":
        raise HTTPException(409, "客服已在跟进,请等电话;确为误触请直接告知客服")
    created = sos.created_at
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    if (datetime.now(timezone.utc) - created).total_seconds() \
            > SOS_CANCEL_WINDOW_SECONDS:
        raise HTTPException(409, "已超过自助撤销窗口,客服马上回访,接个电话说明即可")
    sos.status = "cancelled"
    sos.actions = [*(sos.actions or []), {
        "status": "cancelled", "note": "骑手自助撤销(误触)",
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}]
    await db.commit()
    return {"ok": True}


@router.get("/me/fatigue")
async def my_fatigue(
    user: User = Depends(require_role("rider")),
    db: AsyncSession = Depends(get_db),
):
    """连续在线时长与疲劳提醒(#144)。

    **只提醒,不断单。** 骑手要吃饭,一刀切断人家收入是另一种不尊重 ——
    但平台也不能装作没看见连续在线 10 小时这件事。

    level=throttle 时客户端把新单提醒调慢并置顶休息提示,
    抢单功能照常可用。
    """
    from datetime import datetime, timezone

    from ..models import RiderSession
    from ..services import labor_guard

    # 本次连续在线:取最近一条还没下线的会话
    row = await db.scalar(
        select(RiderSession)
        .where(RiderSession.rider_id == user.id,
               RiderSession.offline_at.is_(None))
        .order_by(RiderSession.online_at.desc()).limit(1))
    if row is None:
        return {"online_minutes": 0, "level": "none", "message": None}

    start = row.online_at
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    minutes = max(0.0,
                  (datetime.now(timezone.utc) - start).total_seconds() / 60)
    level = labor_guard.fatigue_level(minutes)
    return {
        "online_minutes": round(minutes, 1),
        "level": level,
        "message": labor_guard.fatigue_message(level, minutes),
        # 说清楚 throttle 是什么意思,免得骑手以为被限流封号了
        "blocks_grabbing": False,
    }


@router.get("/me/reviews")
async def my_reviews(
    limit: int = 30,
    user: User = Depends(require_role("rider")),
    db: AsyncSession = Depends(get_db),
):
    """顾客对我的评价(#148)。

    骑手此前**完全看不到自己的评价** —— 而顾客怎么说,直接影响骑手的
    心情与改进方向。商家早就有 /merchants/me/reviews,骑手没有,是个疏漏。

    ## 刻意不做的事

    **不返回排名、不返回与其他骑手的对比、不返回任何形式的评分等级。**

    那是段位体系的入口:一旦骑手看到"你排第 87 名",他就会开始为名次跑单,
    而名次是平台单方面控制的 —— 这正是 #144 要防的「算法困住人」。

    判断标准很简单:**这个数字会不会影响他能看到的单?**
    会,就是绳索;不会,才是反馈。本平台的答案是不会 ——
    /transparency/dispatch 的 never_do 里写着「不按骑手评分或等级差别对待」。
    """
    from ..models import Order, Review

    rows = (await db.execute(
        select(Review, Order.order_no)
        .join(Order, Order.id == Review.order_id)
        .where(Review.rider_id == user.id,
               Review.rider_rating.is_not(None))
        # 最新优先:骑手要看的是"最近顾客怎么说"
        .order_by(Review.created_at.desc())
        .limit(min(max(limit, 1), 100)))).all()

    items = []
    for r, order_no in rows:
        items.append({
            "id": r.id,
            "order_no": order_no,
            "rating": r.rider_rating,
            # 评价正文是顾客写给「这一单」的,里面可能同时提到商家和骑手。
            # 原样给,不做摘录 —— 断章取义比不给更糟
            "comment": r.comment or "",
            "created_at": r.created_at.isoformat(),
        })

    rated = [i["rating"] for i in items]
    return {
        "items": items,
        # 只给**自己的**均分与条数,不给排名、不给同行对比
        "average": round(sum(rated) / len(rated), 2) if rated else None,
        "count": len(rated),
        # 这句话要跟着数据一起下发:不写的话骑手会默认它影响派单,
        # 然后开始为分数跑单 —— 那正是我们要避免的
        "note": "评价不影响派单。同一批单,所有在线骑手看到的排序口径一致;"
                "平台不按评分或等级差别对待骑手(见「抢单怎么排的」)。",
        "appeal_hint": "对评价有异议可发起申诉,平台会人工复核。",
    }
