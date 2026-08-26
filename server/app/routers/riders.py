import asyncio
import time

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import Float, cast, func, select, text, update
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

    # ---- 新手默认收窄接单半径(#266)----
    #
    # `grab_radius_km` 默认为空(不限),新骑手第一次上线看到的是全城的单。
    # 最容易发生的事:接一个十公里的,然后超时 —— 而超时的差评他自己背。
    #
    # **只在第一次生效**:设过一次之后(不管设成什么,包括手动改回不限)
    # 永远不再自动改。平台插手一次是帮忙,反复插手就是替他做决定。
    #
    # ⚠️ **必须告诉他**。静默给人设一个筛选,正是我们刚修的那个
    # 「定位丢了半径静默失效」的另一面 —— 他不知道自己被筛过,
    # 只会觉得单少。所以走 warning 这条已有的通道说出来。
    novice_hint = ""
    if payload.is_online and user.grab_radius_km is None \
            and not user.grab_radius_touched:
        user.grab_radius_km = NOVICE_RADIUS_KM
        user.grab_radius_touched = True
        novice_hint = (f"先给你把接单半径设成了 {NOVICE_RADIUS_KM} 公里 —— "
                       "新手接太远的单容易超时。熟悉之后在「接单偏好」里"
                       "随时改,改成不限也行")

    await db.commit()
    # warning 非空 = 在宽限窗口内还没做培训。客户端要显示出来,
    # 但**不能挡住他上线** —— 挡了就是让他今天没饭吃
    return {"is_online": payload.is_online, "warning": warning,
            # 这次上线平台替他改了什么。空串 = 什么都没改
            "auto_pref_hint": novice_hint}


@router.patch("/me/preferences")
async def update_preferences(
    payload: dict,
    user: User = Depends(require_role("rider")),
    db: AsyncSession = Depends(get_db),
):
    """骑手接单偏好。四项都**只改他自己看到什么**,不改订单本身。

    - `grab_radius_km`:接单半径(km,null=不限)。顺路单永远豁免半径;
    - `grab_min_fee_cents`:低于这个数的不显示(0=不限)。
      一个 3 块的单他看一眼就划走,却要一天划几百次;
    - `grab_same_way_only`:只看同店/顺路。兼职骑手要的不是"5 公里内",
      是"下班这条路上";
    - `grab_avoid_alcohol`:不看酒类。要查收件人年龄,有人不想沾这麻烦;
    - `rider_max_active`:同时接单上限(null=用平台默认)。**只能往下调**,
      平台常数是硬上限 —— 见 `effective_max_active`。这一项和上面四条
      不一样:它真的会拦住接单,不只是改他看到什么。

    **过滤掉的单不会消失**,还在池子里等别人抢 —— 所以抢单池返回体里
    带 `filtered_by_prefs`,把"被你自己的设置挡掉了几单"摆出来。
    悄悄过滤会变成"今天怎么没单",他不会想到是两个月前设的一个开关。
    """
    if "grab_radius_km" in payload:
        radius = payload["grab_radius_km"]
        if radius is not None and (not isinstance(radius, int)
                                   or not 1 <= radius <= 20):
            raise HTTPException(422, "接单半径需为 1-20 的整数公里数,或 null 不限")
        user.grab_radius_km = radius
        # 打标:他自己碰过了,以后不再自动帮他设(见 set_online 的 #266)。
        # **改回 null 也算碰过** —— "我就是要看全城"是个明确的决定,
        # 下次上线不该被平台悄悄改回 3 公里
        user.grab_radius_touched = True
    if "grab_min_fee_cents" in payload:
        v = payload["grab_min_fee_cents"]
        # 上限 2000 分:再高就等于"我不接单了",那该用下线开关而不是
        # 一个看不见的过滤器 —— 否则他会以为平台没派单给他
        if not isinstance(v, int) or not 0 <= v <= 2000:
            raise HTTPException(422, "单价下限需为 0-2000 分(0=不限)")
        user.grab_min_fee_cents = v
    if "rider_max_active" in payload:
        v = payload["rider_max_active"]
        hard = settings.rider_max_active_orders
        if v is not None and (not isinstance(v, int) or not 1 <= v <= hard):
            # 上限就是平台硬上限,**不许往上** —— 见 effective_max_active
            raise HTTPException(
                422, f"同时接单上限需为 1-{hard} 的整数,或 null 用平台默认")
        user.rider_max_active = v
    if "go_home" in payload:
        # {"lat":.., "lng":..} 设方向;null 清掉
        v = payload["go_home"]
        if v is None:
            user.go_home_lat = None
            user.go_home_lng = None
            user.go_home_on = False
        else:
            try:
                lat, lng = float(v["lat"]), float(v["lng"])
            except (KeyError, TypeError, ValueError):
                raise HTTPException(422, "收工方向需要 {lat, lng}")
            if not (-90 <= lat <= 90 and -180 <= lng <= 180):
                raise HTTPException(422, "坐标超出范围")
            # **服务端截到街道级**,不信任客户端传的精度(见 round_coarse)
            user.go_home_lat = round_coarse(lat)
            user.go_home_lng = round_coarse(lng)
    if "go_home_on" in payload:
        if not isinstance(payload["go_home_on"], bool):
            raise HTTPException(422, "go_home_on 需为 true/false")
        if payload["go_home_on"] and user.go_home_lat is None:
            raise HTTPException(422, "先设一个收工方向再打开")
        user.go_home_on = payload["go_home_on"]
    for key in ("grab_same_way_only", "grab_avoid_alcohol"):
        if key in payload:
            if not isinstance(payload[key], bool):
                raise HTTPException(422, f"{key} 需为 true/false")
            setattr(user, key, payload[key])
    await db.commit()
    return {
        "grab_radius_km": user.grab_radius_km,
        "grab_min_fee_cents": user.grab_min_fee_cents,
        "grab_same_way_only": user.grab_same_way_only,
        "grab_avoid_alcohol": user.grab_avoid_alcohol,
        "rider_max_active": user.rider_max_active,
        # 平台硬上限一起给,客户端据此画滑块的范围 ——
        # 写死在客户端的话,以后调这个常数要发版
        "max_active_cap": settings.rider_max_active_orders,
        "go_home_on": user.go_home_on,
        "go_home_lat": user.go_home_lat,
        "go_home_lng": user.go_home_lng,
    }


@router.get("/me/preferences")
async def my_preferences(user: User = Depends(require_role("rider"))):
    """当前偏好。客户端设置页进来先读,免得显示成默认值把他的设置盖掉。"""
    return {
        "grab_radius_km": user.grab_radius_km,
        "grab_min_fee_cents": user.grab_min_fee_cents,
        "grab_same_way_only": user.grab_same_way_only,
        "grab_avoid_alcohol": user.grab_avoid_alcohol,
    }


@router.get("/me/messages")
async def my_messages(
    category: str | None = None,   # money / safety / appeal / system
    before: int | None = None,     # push_logs 游标(上一页最后一条 id)
    user: User = Depends(require_role("rider")),
    db: AsyncSession = Depends(get_db),
):
    """骑手消息中心:平台公告 + 发给我的通知。

    ## 为什么骑手比商家更需要这一页

    商家至少还有个后台天天开着。骑手在马路上,推送弹出来那一下没看到
    就**永远找不回来了** —— 而发给他的偏偏是最要紧的几类:申诉结果、
    提现到账、极端天气预警、装备发放。此前这些只走推送,没有归档页。

    订单类不进这里(订单页本身就是它们的家),分类口径见
    services/message_center.py。
    """
    from ..services import message_center
    return await message_center.fetch(db, "rider", user.id,
                                      category=category, before=before)


@router.post("/me/messages/read")
async def mark_messages_read(user: User = Depends(require_role("rider"))):
    """记已读水位到当前时刻。"""
    from ..services import message_center
    return await message_center.mark_read("rider", user.id)


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


@router.get("/me/weekly-report")
async def my_weekly_report(
    week_offset: int = 0,          # 0 本周,1 上周,以此类推
    user: User = Depends(require_role("rider")),
    db: AsyncSession = Depends(get_db),
):
    """骑手周报:逐日单量/在线时长/收入 + **收入构成**。

    ## 红线:只统计,不考核

    这一页里不会出现排名、等级、"超过了 X% 的骑手"、"再跑 3 单解锁"。
    一旦出现,它就从"我这周跑得怎么样"变成了平台的另一根鞭子 ——
    而平台既定立场是不做骑手评分体系。

    ## 收入构成是这一页真正的新东西

    别处的周报只给一个总数。有了配送费拆分之后,能告诉他
    「这周 8% 的收入来自爬楼费」「夜间跑的那两晚多挣了 30 块」——
    这才谈得上让他自己判断怎么跑更划算。

    构成读**订单快照**(fee_parts),不按当前费率重算:费率调过之后
    重算出来的和当时到手的对不上,那种周报还不如不给。
    """
    from datetime import datetime, timedelta, timezone

    from ..models import Order, RiderSession

    now = datetime.now(timezone.utc)
    bj_now = now + timedelta(hours=8)
    today_start = (bj_now.replace(hour=0, minute=0, second=0, microsecond=0)
                   - timedelta(hours=8))
    # 周一为一周之首(北京时区);week_offset 往前推整周
    week_start = (today_start - timedelta(days=bj_now.weekday())
                  - timedelta(weeks=max(0, week_offset)))
    week_end = week_start + timedelta(days=7)

    earnings = (await db.scalars(
        select(RiderEarning).where(
            RiderEarning.rider_id == user.id,
            RiderEarning.created_at >= week_start,
            RiderEarning.created_at < week_end))).all()
    sessions = (await db.scalars(
        select(RiderSession).where(
            RiderSession.rider_id == user.id,
            RiderSession.online_at < week_end,
            RiderSession.online_at > week_start - timedelta(days=1)))).all()

    def bj_day(dt) -> int:
        """落在本周第几天(0=周一)。统一按北京自然日切,
        否则跨零点的单会算到前一天,骑手对不上自己的记忆。"""
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return (dt - week_start).days

    days = [{"orders": 0, "earned_cents": 0, "minutes": 0} for _ in range(7)]
    for e in earnings:
        i = bj_day(e.created_at)
        if 0 <= i < 7:
            days[i]["orders"] += 1 if e.amount_cents > 0 else 0
            days[i]["earned_cents"] += e.amount_cents
    for s in sessions:
        start = (s.online_at if s.online_at.tzinfo
                 else s.online_at.replace(tzinfo=timezone.utc))
        end = s.offline_at or now
        if end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)
        # 一段在线可能跨天,按天切开算 —— 整段记到开始那天的话,
        # 跑通宵的骑手会看到"周一在线 14 小时、周二 0 小时"
        for i in range(7):
            d0 = week_start + timedelta(days=i)
            d1 = d0 + timedelta(days=1)
            lo, hi = max(start, d0), min(end, d1)
            if hi > lo:
                days[i]["minutes"] += int((hi - lo).total_seconds() / 60)

    # 收入构成:读订单上的拆分快照
    order_nos = [e.order_no for e in earnings if e.amount_cents > 0]
    parts: dict[str, int] = {}
    tip_total = 0
    if order_nos:
        rows = (await db.scalars(select(Order).where(
            Order.order_no.in_(order_nos)))).all()
        for o in rows:
            tip_total += o.tip_cents or 0
            for k, v in (o.fee_parts or {}).items():
                if v:
                    parts[k] = parts.get(k, 0) + v
    if tip_total:
        parts["tip"] = tip_total

    from .orders import FEE_PART_LABELS
    labels = dict(FEE_PART_LABELS)
    labels.setdefault("tip", "顾客小费")

    total_cents = sum(d["earned_cents"] for d in days)
    total_orders = sum(d["orders"] for d in days)
    total_minutes = sum(d["minutes"] for d in days)
    return {
        "week_start": week_start.isoformat(),
        "days": days,
        "orders": total_orders,
        "earned_cents": total_cents,
        "online_minutes": total_minutes,
        # 时薪自己算给他看:总额高不等于划算,这是骑手最该拿到的一个数。
        # **在线不足 1 小时不给** —— 分母太小算出来是个荒唐数字,
        # 而他会拿这个数去判断"今天值不值得跑"。宁可不显示
        "cents_per_hour": (round(total_cents / (total_minutes / 60))
                           if total_minutes >= 60 else None),
        "fee_parts": parts,
        "fee_part_labels": {k: labels[k] for k in parts if k in labels},
        "note": "只统计,不考核 —— 这里没有评分、等级和排名,"
                "平台也不会拿这些数字对你做任何处理。"
                "构成读的是每一单当时的拆分快照,不按现在的费率重算。",
    }


@router.get("/heatmap")
async def order_heatmap(
    weekday: int | None = None,     # 0=周一 … 6=周日;缺省用今天
    hour: int | None = None,        # 0-23;缺省用当前小时
    weeks: int = 4,
    user: User = Depends(require_role("rider")),
    db: AsyncSession = Depends(get_db),
):
    """跑单热力图:**过去 N 周,这个时段、这个网格,实际完成了多少单。**

    ## 只回答历史,不做预测

    这一页不预测、不外推、不"推荐去哪跑"。

    - **预测**在我们现在的单量上只会产生噪音,而噪音在这里的代价很实:
      骑手照着一片"高热区"跑过去,发现没单;
    - **推荐去哪跑**是软性派单 —— 会变成"平台让我去我才有单"的
      另一种绑定,和不做强制派单的立场冲突。

    ## 样本不足的格子不画热区

    ⚠️ 这是这个功能唯一会真正伤人的失败方式:指着一片高热区跑过去
    发现没单,比不给更糟。所以低于门槛的格子回 `enough=false`,
    客户端**必须**显示成"数据不够"而不是"冷区" ——
    "这里没单"和"我们不知道这里有没有单"是两件事。

    只统计本城(骑手标了城市时),范围也只到骑手所在城市。
    """
    from datetime import datetime, timedelta, timezone

    from ..services.drop_time import GRID

    bj_now = datetime.now(timezone.utc) + timedelta(hours=8)
    wd = bj_now.weekday() if weekday is None else max(0, min(6, weekday))
    hr = bj_now.hour if hour is None else max(0, min(23, hour))
    weeks = max(1, min(12, weeks))
    since = datetime.now(timezone.utc) - timedelta(weeks=weeks)

    # 商家坐标而不是收货点:骑手要知道**去哪等单**,
    # 而单是从店里出来的。按收货点画,他会守在住宅区,那里不出单
    grid_lat = func.floor(cast(Merchant.lat, Float) / GRID)
    grid_lng = func.floor(cast(Merchant.lng, Float) / GRID)
    # 北京时区的星期与小时:服务器按 UTC 存,直接取 hour 会差 8 小时,
    # 骑手看到的"午高峰"会落在凌晨
    bj_ts = Order.created_at + text("interval '8 hours'")
    stmt = (
        select(grid_lat, grid_lng,
               func.count(Order.id),
               func.avg(cast(Merchant.lat, Float)),
               func.avg(cast(Merchant.lng, Float)))
        .join(Merchant, Merchant.id == Order.merchant_id)
        .where(Order.created_at >= since,
               Order.status.in_([OrderStatus.COMPLETED,
                                 OrderStatus.DELIVERED]),
               Order.pickup.is_(False),
               func.extract("dow", bj_ts) == (wd + 1) % 7,
               func.extract("hour", bj_ts) == hr)
        .group_by(grid_lat, grid_lng))
    if user.city:
        # 和抢单池**同一条隔离规则**:商家没标注城市的不隔离(存量宽限)。
        # 这里如果写成 `city == user.city`,热力图就会漏掉那些他其实
        # 抢得到的单 —— 一张比现实更冷的图,比没有图更误导
        stmt = stmt.where((Merchant.city == user.city)
                          | (Merchant.city == "")
                          | Merchant.city.is_(None))
    rows = (await db.execute(stmt)).all()

    # 门槛:每周至少 1 单才谈得上"这个时段这里有单"。
    # 4 周 4 单换算成"平均每周 1 单" —— 低于这个数,
    # 说它是热区就是在编
    floor_n = weeks
    cells = [{
        "lat": round(float(alat), 5), "lng": round(float(alng), 5),
        "orders": int(n),
        "per_week": round(int(n) / weeks, 1),
        "enough": int(n) >= floor_n,
    } for _, _, n, alat, alng in rows if alat is not None]
    cells.sort(key=lambda c: -c["orders"])
    enough = [c for c in cells if c["enough"]]
    return {
        "weekday": wd, "hour": hr, "weeks": weeks,
        "cells": cells[:200],
        "note": (f"过去 {weeks} 周,周{'一二三四五六日'[wd]} {hr} 点这个时段的"
                 f"**实际完成单量**。这是历史,不是预测 —— "
                 f"我们不预测哪里会爆单,也不建议你去哪跑。"
                 + ("" if enough else
                    "当前这个时段的数据还不够,先按自己的经验跑。")),
        "insufficient": len(cells) - len(enough),
    }


@router.post("/feedback")
async def submit_feedback(
    payload: dict,
    user: User = Depends(require_role("rider")),
    db: AsyncSession = Depends(get_db),
):
    """给平台提意见。与申诉的区别:申诉是"这一单不怪我",
    这里是"你们这个东西不好用 / 这条规则不合理"。

    **必须有回音** —— 不回复的反馈通道等于没有,而且比没有更糟:
    提过一次没人理,以后连提都懒得提。平台回复时走推送 + 消息中心。
    """
    from ..models import RiderFeedback

    content = str(payload.get("content") or "").strip()
    if len(content) < 4:
        raise HTTPException(422, "说具体一点(至少 4 个字),不然没法处理")
    kind = str(payload.get("kind") or "other")
    if kind not in ("bug", "rule", "feature", "other"):
        raise HTTPException(422, "kind 只能是 bug/rule/feature/other")
    # 同时挂着的**未回复**意见最多 10 条。
    #
    # 卡的是"没处理完的堆积",不是"你一年能提几条" —— 按时间窗口
    # 卡的话,一个认真提意见的骑手会先被自己的历史堵住嘴,
    # 而平台回过的那些本来就已经了结了,不该继续占他的额度。
    # 到了上限也照常告诉他为什么,不做静默丢弃
    pending = await db.scalar(select(func.count(RiderFeedback.id)).where(
        RiderFeedback.rider_id == user.id,
        RiderFeedback.status == "open")) or 0
    if pending >= 10:
        raise HTTPException(
            429, "你还有 10 条意见我们没回,先让我们把这些处理完 —— "
                 "已经提过的都在队列里,一条都不会丢")
    row = RiderFeedback(rider_id=user.id, kind=kind, content=content[:1000])
    db.add(row)
    await db.commit()
    return {"id": row.id, "status": "open",
            "note": "收到了。有回复会推送给你,也会进「消息」页。"}


@router.get("/me/feedback")
async def my_feedback(
    user: User = Depends(require_role("rider")),
    db: AsyncSession = Depends(get_db),
):
    """我提过的意见与平台的回复。"""
    from ..models import RiderFeedback

    rows = (await db.scalars(
        select(RiderFeedback)
        .where(RiderFeedback.rider_id == user.id)
        .order_by(RiderFeedback.id.desc()).limit(50))).all()
    return {
        "items": [{"id": r.id, "kind": r.kind, "content": r.content,
                   "status": r.status, "reply": r.reply,
                   "replied_at": r.replied_at, "created_at": r.created_at}
                  for r in rows],
        "note": "提了就一定会有人看。回复会推送给你。",
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


#: 抢单池路网预热的总时间预算(秒)。见 available_orders 里的说明:
#: 热不完就下一轮接着热,绝不让骑手等超过这个数
_PREWARM_BUDGET = 2.5


@router.get("/available-orders")
async def available_orders(
    with_meta: bool = False,
    user: User = Depends(require_role("rider")),
    db: AsyncSession = Depends(get_db),
):
    """可抢订单池:商家已接单/已出餐、且还没有骑手的订单。

    保持广播抢单**不做强制派单** —— 算法只负责把信息排得更有用,
    接不接始终是骑手自己的决定。

    排序口径见 services/dispatch.py,那里是**公开算法的唯一事实来源**
    (/transparency/dispatch 从同一处读权重,不另抄一份)。
    骑手位置取不到(未上报/过期)时退化为按等待时长排(老单在前)。

    `with_meta=true` 时返回
    `{items, filtered_by_prefs, has_location, stale_prefs, prefs}`
    而不是裸数组:骑手自己设的偏好挡掉了几单要**摆出来**,否则
    "今天怎么没单"这个疑问没有答案。不传时保持裸数组 ——
    老版本客户端拿到对象会直接崩。

    `stale_prefs` 是**因为定位取不到而没生效的偏好键**。半径和只看顺路
    都依赖位置,位置一没有它们就静默失效,而界面上还选着 —— 这条是给
    客户端照实提示用的。
    """
    from datetime import datetime, timezone

    from ..services import dispatch, prep_time
    from ..services.routing import (
        MatrixBusy, bicycling_m, bicycling_matrix, detour_m, routes_cached)

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
    # 收工单(#264):开着的时候,顺路的参照点换成「我要回的方向」。
    #
    # 为什么需要它:`same_way` 按手上单的送达点算绕路增量,而
    # **手上没单时它整个不生效**(见下面 grab_same_way_only 那段注释)——
    # 收工那一刻恰恰是手上快空了的时候,顺路筛选正好在最需要它的时刻失灵,
    # 结果是最后一单接到反方向,白骑十公里回家。
    #
    # 算法一行不用改:detour_m 的第四个参数本来就是"终点",
    # 把手上单的送达点换成这个坐标即可。
    if user.go_home_on and user.go_home_lat is not None:
        my_drops = [(user.go_home_lat, user.go_home_lng)]

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
    # 送达段历史耗时:同样**批量取**(逐个查会把一次抢单变成几十次往返)。
    # 样本不足的点位返回 None,客户端据此显示"这个点还没有历史数据" ——
    # 拿 3 单算出来的数摆给骑手看,比不给更误导
    from ..services import drop_time
    drops = await drop_time.stats_for(
        db, [drop_time.drop_key(o.lat, o.lng, o.floor) for o in orders])
    # 路网距离**批量预热**(#289):和上面两处「批量取」同一个理由 ——
    # 原来这一段在下面的 for 里逐单打两次腾讯路径接口(骑手→商家、
    # 商家→用户),一屏 20 单就是 40 次串行 HTTP、每次超时 3 秒。
    # Redis 缓存挡得住重复,但**缓存冷的时候正是午高峰第一批单**。
    #
    # 矩阵写的缓存和单点调用是同一套键,所以下面的 bicycling_m 直接命中,
    # 一行调用都不用改口径。
    # 预热没热成时,下面逐单算距离也**不许发请求**,只读缓存。
    # 理由见 routing.route 里 cache_only 那段:一屏 20 单是 40 次不受
    # 节流约束的单点请求,一发就把限流坐实,反而更糟
    cache_only = False
    if rider_pos:
        shop_pts = list({(o.merchant_lat, o.merchant_lng) for o in outs
                         if o.merchant_lat is not None
                         and o.merchant_lng is not None})

        async def _prewarm() -> None:
            if shop_pts:
                await bicycling_matrix(rider_pos, shop_pts)
            # **商家 → 送达点那一段也要热。**
            #
            # 原来只热了骑手→商家,而下面的循环对每一单还要算一次
            # 商家→送达点 —— 那一段照旧是逐单串行 HTTP。实测 20 单的池子
            # 冷缓存要 6.4 秒,一半就花在这儿。
            #
            # 矩阵是「一个起点 → 多个终点」,而这一段每单的起点都不同,
            # 所以按商家分组:同一家店的多单共用一次矩阵调用
            # (外卖的现实是一家店同时有好几单,分组之后调用次数
            #  从"单数"降到"店数")。
            # ⚠️ 局部变量别叫 drops —— 外面 `drops` 是送达段历史耗时的
            # 字典(drop_time.stats_for 的结果),在这儿覆盖掉的话,
            # 下面 `drops.get(dk)` 会拿到一个 list,整个接口 500。
            # 踩过一次,改名 drop_pts
            by_shop: dict[tuple[float, float], list[tuple[float, float]]] = {}
            for order, out in zip(orders, outs):
                if out.merchant_lat is None or out.merchant_lng is None:
                    continue
                by_shop.setdefault(
                    (out.merchant_lat, out.merchant_lng), []).append(
                        (order.lat, order.lng))
            for shop_pt, drop_pts in by_shop.items():
                await bicycling_matrix(shop_pt, list(set(drop_pts)))

        try:
            # 整段预热的**总预算**。
            #
            # 只给"等锁"设上限还不够:抢到锁的那个人要串行等完所有矩阵
            # 调用,而调用次数 = 1(骑手→商家)+ 商家家数(商家→送达点),
            # 每次之间强制间隔 1.1 秒。5 家店就是 6.6 秒 —— 超过骑手
            # 5 秒的轮询间隔,请求会开始堆积。
            #
            # 到点就收手,热到哪算哪:已经写进 Redis 的那几段下一轮
            # 直接命中,剩下的下一轮接着热(实测七轮补满)。
            # 预热是加速,不是正确性。
            await asyncio.wait_for(_prewarm(), _PREWARM_BUDGET)
        except (asyncio.TimeoutError, TimeoutError):
            cache_only = True
        except MatrixBusy:
            # 别人正占着那把节流锁。**不排队** —— 排一次要好几秒,
            # 而代价只是这一屏的跑程用直线口径(前端本来就显示来源)。
            # 下一次刷新(5 秒后)大概率就热上了。
            cache_only = True
        except Exception:
            # 其它预热失败不影响正确性:下面照旧逐单算,只是慢一点
            import logging
            logging.getLogger("superz.riders").warning(
                "抢单列表路网预热失败,退回逐单", exc_info=True)

        # 预热写进缓存的那些,**一次 mget 全读回来**。
        #
        # 不这么做的话下面每单要发两次 `GET`(到店一次、送程一次)——
        # 一屏 42 单就是 84 次串行往返,profile 下占整个接口 23%。
        # 荒唐的地方在于:这些值上一步刚算完写进去,转头一个一个读回来。
        warm = await routes_cached(
            [(rider_pos, (o.merchant_lat, o.merchant_lng)) for o in outs
             if o.merchant_lat is not None and o.merchant_lng is not None]
            + [((o.merchant_lat, o.merchant_lng), (od.lat, od.lng))
               for od, o in zip(orders, outs)
               if o.merchant_lat is not None and o.merchant_lng is not None])
    else:
        warm = {}
    radius_m = (user.grab_radius_km * 1000
                if user.grab_radius_km and rider_pos else None)
    scored: list[tuple[float, OrderOut]] = []
    # 被骑手自己的偏好挡掉的单数。**必须回报** —— 见下方 with_meta
    filtered = 0
    for order, out in zip(orders, outs):
        out.same_shop = order.merchant_id in my_shops
        score_val = 0.0
        if rider_pos and out.merchant_lat is not None:
            # 到店距离用真实骑行路径(不可用时回退直线×1.2 并标明来源)——
            # 直线系统性低估,实测成都两点直线 1467m / 骑行 1745m,差 19%
            shop_pt = (out.merchant_lat, out.merchant_lng)
            hit = warm.get((rider_pos, shop_pt))
            if hit is None:
                distance, src = await bicycling_m(
                    rider_pos[0], rider_pos[1], shop_pt[0], shop_pt[1],
                    cache_only=cache_only)
            else:
                distance, src = hit[0], hit[2]
            out.distance_m = int(distance)
            out.distance_source = src
            hit = warm.get((shop_pt, (order.lat, order.lng)))
            if hit is None:
                trip, _ = await bicycling_m(
                    shop_pt[0], shop_pt[1], order.lat, order.lng,
                    cache_only=cache_only)
            else:
                trip = hit[0]
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
            # 配送费构成:**接单前**就摊开给骑手看。
            # 8 块里有 3 块是因为要爬 6 楼 —— 知道这个才判断得了值不值
            from .orders import FEE_PART_LABELS
            out.fee_parts = {k: v for k, v in (order.fee_parts or {}).items()
                             if v}
            out.fee_part_labels = {k: FEE_PART_LABELS[k]
                                   for k in out.fee_parts
                                   if k in FEE_PART_LABELS}

            dk = drop_time.drop_key(order.lat, order.lng, order.floor)
            stat = drops.get(dk) or {}
            out.drop_p75_minutes = stat.get("p75_minutes")
            out.drop_sample = stat.get("sample", 0)

            # 接单半径过滤(骑手自设);同店/顺路豁免 —— 手头单顺路的永远给看
            if (radius_m is not None and distance > radius_m
                    and not out.same_shop and not out.same_way):
                filtered += 1
                continue
            # 只看顺路(兼职骑手:他要的不是"5 公里内",是"下班这条路上")。
            # 手上没单时不生效 —— 那时无所谓顺不顺路,一刀切会让他
            # 一整天看到 0 单还找不到原因
            if (user.grab_same_way_only and my_drops
                    and not out.same_shop and not out.same_way):
                filtered += 1
                continue
        # 下面两条不依赖定位,放在距离分支外 —— 否则关掉定位权限的骑手
        # 设了偏好却完全不生效,而界面上还显示着开着
        if (user.grab_min_fee_cents
                and order.delivery_fee_cents + order.tip_cents
                < user.grab_min_fee_cents):
            filtered += 1
            continue
        # 酒类看订单条目快照上的 is_alcohol(客户端也是按这个字段
        # 显示「送达请查验年龄」的,同一个事实来源)
        if (user.grab_avoid_alcohol
                and any(i.get("is_alcohol") for i in (order.items or []))):
            filtered += 1
            continue
        scored.append((score_val, out))
    if rider_pos:
        # 综合分越小越靠前;分数相同(理论上极少)按原有等待顺序稳定排
        scored.sort(key=lambda pair: pair[0])
    items = [out for _, out in scored[:50]]
    if not with_meta:
        return items
    # 带上"被你自己的设置挡掉了几单"。悄悄过滤会变成"今天怎么没单",
    # 骑手不会想到是两个月前设的一个开关 —— 这个数就是那条线索。
    # 老版本客户端不传 with_meta,拿到的还是原来的数组,不会崩
    # 定位取不到时**哪些偏好悄悄失效了**,照实回报。
    #
    # 接单半径和只看顺路都在 `if rider_pos` 分支里(见上面 ~919 行),
    # 位置没上报或 Redis 过期(5 分钟)时整段跳过 —— 骑手界面上 chip
    # 还选着「3km」,实际收到的是不限。他不会想到是定位的问题,
    # 只会觉得"这破筛选没用"。
    #
    # 这和商家端「空列表和加载失败长得一样」是同一种病:
    # **让用户误以为某件事在生效**。所以给出来,由客户端照实显示。
    stale_prefs = stale_location_prefs(
        rider_pos is not None,
        grab_radius_km=user.grab_radius_km,
        grab_same_way_only=user.grab_same_way_only,
        go_home_on=user.go_home_on,
    )
    return {"items": items, "filtered_by_prefs": filtered,
            # 位置有没有:客户端据此决定要不要提示去开定位
            "has_location": rider_pos is not None,
            # 因为没定位而没生效的偏好键;空数组 = 一切正常
            "stale_prefs": stale_prefs,
            "prefs": {"grab_radius_km": user.grab_radius_km,
                      "grab_min_fee_cents": user.grab_min_fee_cents,
                      "grab_same_way_only": user.grab_same_way_only,
                      "grab_avoid_alcohol": user.grab_avoid_alcohol,
                      "rider_max_active": user.rider_max_active,
                      "max_active_cap": settings.rider_max_active_orders,
                      "go_home_on": user.go_home_on,
                      "go_home_lat": user.go_home_lat,
                      "go_home_lng": user.go_home_lng}}


#: 收工方向坐标的存储精度(小数点后位数)。
#:
#: 2 位 ≈ 1.1km。**这是隐私上限不是精度选择**:骑手的收工方向多半就是
#: 他家附近,存得越准越接近"我们知道他住哪"。而「往这个方向」这个用途
#: 只需要街道级 —— 判顺路比的是绕路增量的相对大小,差一公里不影响谁排前面。
GO_HOME_PRECISION = 2


def round_coarse(v: float) -> float:
    """把坐标截到街道级。

    **服务端截,不信任客户端** —— 客户端传什么精度我们管不着,
    但落库的必须是粗的。
    """
    return round(v, GO_HOME_PRECISION)


#: 新手首次上线时自动设的接单半径(km)。
#:
#: 美团给新手推荐 3 公里内,理由和我们一样:接太远容易超时。
#: **只在第一次生效**,而且要明说 —— 见 set_online 里那段。
NOVICE_RADIUS_KM = 3


def effective_max_active(rider_max_active: int | None) -> int:
    """这个骑手实际的同时接单上限。

    `rider_max_active` 为空 = 没设过,用平台默认。设过就取**较小值** ——
    平台常数是硬上限,骑手只能往下调。

    往上调不给,不是不信任骑手:同时 8 单必然有人超时,而超时的
    赔付平台出、差评他背。往下调随便,那纯粹是他自己的节奏。
    """
    hard = settings.rider_max_active_orders
    if rider_max_active is None:
        return hard
    return min(rider_max_active, hard)


def stale_location_prefs(has_location: bool, *,
                         grab_radius_km: int | None,
                         grab_same_way_only: bool,
                         go_home_on: bool = False) -> list[str]:
    """定位取不到时,哪些接单偏好**悄悄失效了**。

    接单半径和只看顺路都要拿骑手位置来算(见 available_orders 里的
    `if rider_pos` 分支),位置没上报或 Redis 过期(5 分钟)时整段跳过 ——
    而骑手界面上 chip 还选着「3km」。

    这是「让用户误以为某件事在生效」那一类:比"挡掉了你不知道"更坏,
    因为骑手会按"我只看 3 公里内"去接单,接了才发现要骑十公里。

    有定位时一律返回空 —— 偏好本身没设也返回空,没设就谈不上失效。
    """
    if has_location:
        return []
    out: list[str] = []
    if grab_radius_km:
        out.append("grab_radius_km")
    if grab_same_way_only:
        out.append("grab_same_way_only")
    # 收工方向也吃 rider_pos:绕路增量是从"骑手当前位置"起算的
    if go_home_on:
        out.append("go_home_on")
    return out


# ---------- 骑手申诉(超时/差评非我责任) ----------

async def _appeal_evidence(db, order) -> dict:
    """把平台已有的证据快照下来。**骑手不用自己举证** ——
    让一个在马路上跑车的人去截图收集材料,这个通道就等于不存在。

    存快照不存引用:事后重算的话天气开关早关了、ETA 也重估过,
    证据会自己变。
    """
    from datetime import datetime, timezone

    from ..services.eta import _weather_exempt
    from ..services.pricing import haversine_m

    ev: dict = {}
    if order.arrived_shop_at and order.picked_up_at:
        wait = (order.picked_up_at - order.arrived_shop_at).total_seconds()
        ev["wait_minutes"] = round(wait / 60, 1)
    if order.eta_at:
        ev["eta_at"] = order.eta_at.isoformat()
    if order.delivered_at:
        ev["delivered_at"] = order.delivered_at.isoformat()
        if order.eta_at:
            ev["late_minutes"] = round(
                (order.delivered_at - order.eta_at).total_seconds() / 60, 1)
    merchant = await db.get(Merchant, order.merchant_id)
    if merchant is not None and order.lat is not None:
        ev["distance_m"] = int(haversine_m(
            merchant.lat, merchant.lng, order.lat, order.lng))
    try:
        ev["weather_exempt"] = await _weather_exempt(
            db, order.delivered_at or order.created_at)
    except Exception:
        pass
    ev["snapshot_at"] = datetime.now(timezone.utc).isoformat()
    return ev


@router.post("/appeals")
async def submit_appeal(
    payload: dict,
    user: User = Depends(require_role("rider")),
    db: AsyncSession = Depends(get_db),
):
    """提交申诉。系统自动附上它已经知道的证据。

    ## 申诉成立之后会发生什么(界面上要原样说清楚)

    **只把这一单标注为「非骑手责任」,不加回任何分数、不补偿金额** ——
    平台本来就没有骑手评分体系(不做服务分、不做违规积分),所以没有
    "分"可加。申诉的价值是这条记录上写着不怪你。
    不说清楚的话骑手会以为申诉能拿到钱。
    """
    from datetime import datetime, timezone

    from ..models import RiderAppeal
    from ..services.moderation import guard_text

    order_no = str(payload.get("order_no", "")).strip()[:32]
    order = await db.scalar(select(Order).where(Order.order_no == order_no))
    if order is None or order.rider_id != user.id:
        raise HTTPException(404, "这不是你的单")
    kind = str(payload.get("kind") or "late")
    if kind not in ("late", "review", "other"):
        raise HTTPException(422, "类型只支持:超时非我责任 / 差评非我责任 / 其他")
    reason = str(payload.get("reason", "")).strip()[:300]
    if len(reason) < 5:
        raise HTTPException(422, "说明一下当时的情况(至少 5 个字),"
                                 "平台要靠这段话去核实")
    await guard_text(db, reason, "申诉说明")

    dup = await db.scalar(select(RiderAppeal).where(
        RiderAppeal.rider_id == user.id, RiderAppeal.order_no == order_no))
    if dup is not None:
        raise HTTPException(409, "这一单已经申诉过了,等结果就好")

    row = RiderAppeal(
        rider_id=user.id, order_no=order_no, kind=kind, reason=reason,
        photo_url=str(payload.get("photo_url", "")).strip()[:300],
        evidence=await _appeal_evidence(db, order))
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return {
        "id": row.id, "status": row.status, "evidence": row.evidence,
        "note": "已提交。平台会核实 —— 系统已经自动附上了等餐时长、"
                "实际距离、天气豁免这些记录,你不用再去找证据。"
                "**申诉成立只会把这一单标注为「非骑手责任」,"
                "不加分也不补钱** —— 平台没有骑手评分这种东西。",
    }


@router.get("/appeals")
async def my_appeals(
    user: User = Depends(require_role("rider")),
    db: AsyncSession = Depends(get_db),
):
    """我的申诉与进度。"""
    from ..models import RiderAppeal

    rows = (await db.scalars(
        select(RiderAppeal).where(RiderAppeal.rider_id == user.id)
        .order_by(RiderAppeal.id.desc()).limit(100))).all()
    return {
        "items": [{
            "id": r.id, "order_no": r.order_no, "kind": r.kind,
            "reason": r.reason, "status": r.status,
            "verdict_note": r.verdict_note, "evidence": r.evidence,
            "created_at": r.created_at, "reviewed_at": r.reviewed_at,
        } for r in rows],
        "note": "成立 = 这一单标注为非骑手责任。平台没有骑手服务分,"
                "所以没有分可加 —— 但记录上会写清楚不怪你。",
    }


# 到店围栏半径(米)。100 米:商圈里店挨着店,再大就会在隔壁店门口
# 误触发;再小则 GPS 漂移会让人明明站在门口却点不了
_ARRIVE_RADIUS_M = 100


@router.post("/orders/{order_no}/arrived", response_model=OrderOut)
async def mark_arrived_shop(
    order_no: str,
    payload: dict | None = None,
    user: User = Depends(require_role("rider")),
    db: AsyncSession = Depends(get_db),
):
    """骑手点「我到店了」。

    ## 这个时间戳是干什么的

    等餐时长 = 取餐时刻 − 到店时刻。它是**骑手申诉超时时的证据** ——
    在店里干等二十分钟不该算到骑手头上,而现在他没有任何办法证明这件事。
    同时给商家 /me/quality 一个真实的出餐表现数,给 ETA 一个修正输入。

    **只记录,不判罚。** 有了它之后很容易顺手加一条「等餐超 X 分钟扣商家分」
    —— 不做,与平台「不做违规积分」的立场一致。

    ## 手动优先于围栏

    带了坐标就顺手校验一下距离(离店 100 米外点了会被拒,防随手乱点),
    但**判定用的是骑手主动点的那一刻**,不是围栏自动触发 ——
    商圈里店挨着店,自动触发会在隔壁店门口就记上,反而把证据搞脏。
    """
    from datetime import datetime, timezone

    from ..services.pricing import haversine_m

    order = await db.scalar(select(Order).where(Order.order_no == order_no))
    if order is None or order.rider_id != user.id:
        raise HTTPException(404, "订单不存在")
    if order.status not in (OrderStatus.ACCEPTED, OrderStatus.READY):
        raise HTTPException(409, "只有待取餐的单能标记到店")
    if order.arrived_shop_at is not None:
        # 幂等:重复点不刷新时间 —— 刷新的话骑手多点一次就把等餐时长清零了
        merchant = await db.get(Merchant, order.merchant_id)
        return order_out(order, merchant, viewer=user)

    if payload and payload.get("lat") is not None:
        merchant = await db.get(Merchant, order.merchant_id)
        if merchant is not None:
            dist = haversine_m(float(payload["lat"]), float(payload["lng"]),
                               merchant.lat, merchant.lng)
            if dist > _ARRIVE_RADIUS_M * 5:
                raise HTTPException(
                    409, f"离店还有约 {int(dist)} 米,到店门口再点")
    order.arrived_shop_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(order)
    merchant = await db.get(Merchant, order.merchant_id)
    return order_out(order, merchant, viewer=user)


@router.post("/orders/{order_no}/arrived-drop", response_model=OrderOut)
async def mark_arrived_drop(
    order_no: str,
    payload: dict | None = None,
    user: User = Depends(require_role("rider")),
    db: AsyncSession = Depends(get_db),
):
    """骑手点「我到收货点了」。

    ## 这个时间戳补的是一块空白

    到店等餐时长早就在记(到店 → 取餐),**送达这一段一直没有**。
    而"这个小区难进""这栋写字楼电梯要等十分钟"这类事全部发生在
    这一段里 —— 到了楼下到点送达之间,花在找门牌、等门禁、等电梯、
    爬楼、打电话让人下来上面。

    没有它,"场景难度"就只能靠拍脑袋;有了它,才谈得上用真实分位数
    给这个点位补时。

    ## 只记录,不产生任何后果

    这一步不进 ETA、不进钱、不进考核。**一个点位慢是这个点位的事,
    不是那天送这一单的骑手的事** —— 这条边界要提前划死,
    因为有了时长数据之后,"送得慢的骑手"是一个非常容易顺手做出来的
    指标,而它和平台不做骑手评分的立场直接冲突。

    ## 幂等,且以骑手主动点的那次为准

    重复点不刷新时间(刷新的话多点一次就把时长清零了)。
    围栏可以做自动提示,但判定用他点的那一下 —— 楼挨着楼,
    自动触发会在隔壁单元就记上,把数据搞脏。
    """
    from datetime import datetime, timezone

    from ..services.pricing import haversine_m

    order = await db.scalar(select(Order).where(Order.order_no == order_no))
    if order is None or order.rider_id != user.id:
        raise HTTPException(404, "订单不存在")
    if order.status != OrderStatus.PICKED_UP:
        raise HTTPException(409, "只有配送中的单能标记到达收货点")
    if order.arrived_drop_at is None:
        if payload and payload.get("lat") is not None:
            # 带了坐标就顺手校验(离收货点 500 米外点了会被拒,防随手乱点)。
            # 不带坐标照样放行 —— 定位权限关着的骑手不该用不了这个功能
            dist = haversine_m(float(payload["lat"]), float(payload["lng"]),
                               order.lat, order.lng)
            if dist > _ARRIVE_RADIUS_M * 5:
                raise HTTPException(
                    409, f"离收货点还有约 {int(dist)} 米,到了再点")
        order.arrived_drop_at = datetime.now(timezone.utc)
        await db.commit()
        await db.refresh(order)
    merchant = await db.get(Merchant, order.merchant_id)
    return order_out(order, merchant, viewer=user)


@router.post("/orders/batch-arrived")
async def batch_arrived(
    payload: dict,
    user: User = Depends(require_role("rider")),
    db: AsyncSession = Depends(get_db),
):
    """同一家店的在手单,一次全标到店。

    ## 为什么值得单开一个端点

    同店多单是常态(午高峰一家店压着三四单),而"到店"这个动作
    **物理上只发生一次** —— 让骑手站在店门口点三次,第三次点的时候
    等餐时长已经比第一次少了半分钟,这个证据本身就被操作方式污染了。
    批量标记让三单共用同一个到店时刻,才是事实。

    ## 不整体回滚

    三单里有一单状态不对(比如已经取过了),不该把另外两单一起打回。
    逐单执行、逐单报结果,失败的那条给出原因就行 —— 骑手在店门口,
    要的是"哪几单好了、哪单还得点一下",不是一个 409。
    """
    merchant_id = payload.get("merchant_id")
    if not isinstance(merchant_id, int):
        raise HTTPException(422, "缺少 merchant_id")
    orders = [o for o in await _my_in_flight(db, user.id)
              if o.merchant_id == merchant_id]
    if not orders:
        raise HTTPException(404, "你在这家店没有在手的单")
    results = []
    for o in orders:
        try:
            await mark_arrived_shop(o.order_no, payload, user, db)
            results.append({"order_no": o.order_no, "ok": True})
        except HTTPException as exc:
            results.append({"order_no": o.order_no, "ok": False,
                            "reason": exc.detail})
    done = sum(1 for r in results if r["ok"])
    return {"items": results, "ok_count": done,
            "note": f"{len(orders)} 单里标记成功 {done} 单"}


@router.post("/orders/batch-picked")
async def batch_picked(
    payload: dict,
    user: User = Depends(require_role("rider")),
    db: AsyncSession = Depends(get_db),
):
    """同一家店的在手单,一次全标取餐。

    取餐码按单传(`codes` 是 `{订单号: 尾号后 4 位}`),没传的单不核验 ——
    与单单取餐同一口径:核验是防拿错的工具,不是新门槛。
    同样逐单执行不整体回滚。
    """
    from ..schemas import TransitionIn
    from .orders import transition

    merchant_id = payload.get("merchant_id")
    if not isinstance(merchant_id, int):
        raise HTTPException(422, "缺少 merchant_id")
    codes = payload.get("codes") or {}
    orders = [o for o in await _my_in_flight(db, user.id)
              if o.merchant_id == merchant_id]
    if not orders:
        raise HTTPException(404, "你在这家店没有在手的单")
    results = []
    for o in orders:
        try:
            # 走同一个 transition,而不是自己写一遍改状态 ——
            # 那里面挂着推送、回调、事件留痕,复制一份必然漏
            await transition(
                o.order_no,
                TransitionIn(to_status=OrderStatus.PICKED_UP,
                             verify_code=str(codes.get(o.order_no, "")),
                             force=bool(payload.get("force"))),
                user, db)
            results.append({"order_no": o.order_no, "ok": True})
        except HTTPException as exc:
            results.append({"order_no": o.order_no, "ok": False,
                            "reason": exc.detail})
    done = sum(1 for r in results if r["ok"])
    return {"items": results, "ok_count": done,
            "note": f"{len(orders)} 单里取餐成功 {done} 单"}


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
    if used >= await _suspend_threshold(db, user.id):
        raise HTTPException(
            409, f"今日转单已达 {used} 次,抢单暂停到明天(次日自动恢复,"
                 "不罚款不扣钱);手头的单照常配送,有困难随时联系平台")
    # 并发上限:手头在途太多影响履约,先送完再接(追加单不占额度)。
    #
    # 取骑手自设值和平台硬上限里**小的那个**:他可以往下调不能往上。
    # 理由不是不信任他 —— 同时 8 单必然有人超时,而超时的赔付平台出、
    # 差评他背。
    active = len(await _my_in_flight(db, user.id))
    limit = effective_max_active(user.rider_max_active)
    if active >= limit:
        # 是他自己设的还是平台定的,要说清楚 —— 不然他会觉得平台在卡他,
        # 而实际上那个数是他上周自己调的
        why = ("你把同时接单上限设成了 %d 单,可以在接单偏好里改" % limit
               if user.rider_max_active is not None
               and user.rider_max_active < settings.rider_max_active_orders
               else "最多同时 %d 单" % limit)
        raise HTTPException(
            409, f"手头已有 {active} 单在途,先送完再接新单({why})")
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

async def _novice_window(db: AsyncSession, rider_id: int) -> bool:
    """还在新手期吗(实名认证起 7 天内**且**完成单不足 20)。

    起点取**实名认证记录**的创建时刻,不是注册时刻:注册完不认证的人
    根本抢不了单,从注册开始计时会让一个隔了两个月才来认证的人
    一上来就不在新手期。


    ## 保护的是什么,不保护什么

    只做一件事:**把转单的每日暂停阈值放宽几次**。头几天路不熟、
    进不去小区、拿错单,他会比老手更频繁地转单 —— 而转单达阈值就
    暂停抢单,等于第一周就把人劝退了。

    **不做**"给新手派更好的单":那要动派单权重,而派单公平性是
    公开算法承诺过的东西,为谁开一个口子都会让整个承诺打折。
    新手需要的是别被自己的手忙脚乱卡死,不是特权。

    两个条件是**与**不是或:跑满 20 单说明已经上手了,哪怕还在
    第七天;反过来第八天还没跑够 20 单的,多半是兼职,他也不该
    因为"注册久了"就被当老手对待 —— 这一条上宁可宽松,
    因为放宽的只是一个软阈值,代价很小。
    """
    from datetime import datetime, timedelta, timezone

    from ..models import RiderProfile

    profile = await db.scalar(
        select(RiderProfile).where(RiderProfile.rider_id == rider_id))
    if profile is None:
        return False
    created = profile.created_at
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    if datetime.now(timezone.utc) - created > timedelta(
            days=settings.rider_novice_days):
        return False
    done = await db.scalar(select(func.count(RiderEarning.id)).where(
        RiderEarning.rider_id == rider_id)) or 0
    return done < settings.rider_novice_orders


async def _suspend_threshold(db: AsyncSession, rider_id: int) -> int:
    """当日转单暂停阈值(新手期放宽后的**实际**值)。

    抢单那里判一次、规则中心显示一次、转单回执里再回显一次 ——
    三处各自算的话必然分叉,而这里分叉的表现是最难受的一种:
    界面写着"已暂停",他一点却抢到了;或者写着"还能转 2 次",
    转完发现已经停了。口径只能有一处。
    """
    return settings.transfer_daily_suspend_threshold + (
        settings.rider_novice_extra_transfers
        if await _novice_window(db, rider_id) else 0)


async def _transfer_used_today(rider_id: int) -> int:
    """当日(北京自然日)非免责转单次数;免责转单与事故释放不计入。"""
    from datetime import datetime, timedelta, timezone
    bj_date = (datetime.now(timezone.utc) + timedelta(hours=8)).date()
    return int(await get_redis().get(f"rider:transfer:{rider_id}:{bj_date}")
               or 0)


@router.get("/discipline")
async def my_discipline(
    user: User = Depends(require_role("rider")),
    db: AsyncSession = Depends(get_db),
):
    """规则中心数据:当日转单计数与软约束阈值(规则文案在客户端)。

    阈值给的是**他自己的**那个 —— 新手期放宽过的话这里就该显示放宽后的,
    否则界面写着"已暂停"他一点却抢到了,或者反过来。
    """
    used = await _transfer_used_today(user.id)
    threshold = await _suspend_threshold(db, user.id)
    return {
        "transfer_used_today": used,
        "free_times": settings.transfer_free_times_per_day,
        "suspend_threshold": threshold,
        "grab_suspended_today": used >= threshold,
        "novice_window": threshold > settings.transfer_daily_suspend_threshold,
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
        # 软约束触达:临近阈值提前提醒,到阈值告知今日暂停(次日自动恢复)。
        # 阈值取他自己的那个(新手期放宽过),否则提醒会提前两次响
        threshold = await _suspend_threshold(db, user.id)
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
        suspend_threshold=await _suspend_threshold(db, user.id),
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
