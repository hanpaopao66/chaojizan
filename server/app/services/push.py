"""极光推送(JPush)服务端直推。

未配置 Key 时静默跳过(返回 False),所有调用点都不感知。
客户端集成(setAlias 绑定 u{user_id})见 docs/INTEGRATIONS.md。

## 关于扇出(推给一批人)

单发走 `push_to_user`,扇出走 `fanout`。**不要自己写 for 循环串行 await**:
每次 `push_to_user` 是一次 HTTPS 往返,JPush 超时 5 秒 ——
500 个骑手串起来最坏能堵 2500 秒,而这条链子曾经就挂在支付回调里
(微信回调超时会重试最多 15 次,于是一次超时变成十五次雪崩)。
`fanout` 负责三件事:分批并发、共用连接、push_logs 一次性写。
"""
import asyncio
import logging

import httpx

from ..config import settings

logger = logging.getLogger("superz.push")

JPUSH_URL = "https://api.jpush.cn/v3/push"

# 进程级共享的 HTTP 客户端。**原先是每推一条 new 一个 AsyncClient**,
# 等于每条推送都重做一次 TCP 握手 + TLS 握手,连接一次都没复用上。
# 扇出的时候这个开销是乘以人数的。
# 懒创建:AsyncClient 的连接池要绑事件循环,在 import 时建会绑错循环
_client: httpx.AsyncClient | None = None
_client_lock = asyncio.Lock()

# 后台推送任务的强引用池。create_task 的返回值不留引用会被 GC 提前回收 ——
# 表现是"推送有时候莫名其妙就没发",而且完全不报错。见 spawn()
_background: set[asyncio.Task] = set()


async def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        async with _client_lock:
            if _client is None or _client.is_closed:
                _client = httpx.AsyncClient(
                    timeout=5,
                    # 池子够扇出并发用即可;JPush 是单一 host,不需要开太大
                    limits=httpx.Limits(max_connections=32,
                                        max_keepalive_connections=16),
                )
    return _client


async def aclose_push_client() -> None:
    """进程退出时收掉连接池(main.py 的 lifespan 调)。"""
    global _client
    if _client is not None and not _client.is_closed:
        await _client.aclose()
    _client = None


async def _record_many(rows: list[tuple[int, str, str, bool, str]]) -> None:
    """批量写 push_logs:**一个 session、一次 commit**。

    原先是每推一条就 `SessionLocal()` 开一个新 session 写一行再 commit,
    扇出 500 人就是 500 个 session、500 次 commit —— 而连接池总共才 10+20,
    推送自己就能把池子占满,把正常请求挤到等待队列里去。

    记录失败不能反过来影响推送主流程,所以整个吞掉异常。
    """
    if not rows:
        return
    from ..db import SessionLocal
    from ..models import PushLog

    try:
        async with SessionLocal() as db:
            db.add_all([
                PushLog(user_id=uid, title=title, content=content[:200],
                        ok=ok, error=error[:300])
                for uid, title, content, ok, error in rows
            ])
            await db.commit()
    except Exception:
        logger.exception("push_logs 批量写入失败(%s 条)", len(rows))


async def _record(user_id: int, title: str, content: str, ok: bool, error: str) -> None:
    """写 push_logs;记录失败不能反过来影响推送主流程。"""
    await _record_many([(user_id, title, content, ok, error)])


async def push_to_user(user_id: int, title: str, content: str,
                       extras: dict | None = None,
                       record_skip: bool = False) -> bool:
    """按别名推给单个用户(客户端登录后 setAlias('u{user_id}'))。

    record_skip:未配置 JPush 时是否仍写 push_logs(error=未配置)。
    订单状态类高频推送保持静默跳过;回复/收藏/召回等触达类传 True——
    低频、值得留痕,配好 Key 前就能验证触发链路,配好后无缝变真实发送。
    """
    if not settings.jpush_configured:
        logger.debug("jpush 未配置,跳过推送: u%s %s", user_id, title)
        if record_skip:
            await _record(user_id, title, content, False, "jpush 未配置(仅记录意图)")
        return False
    ok, error = await _send(_payload_for(user_id, title, content, extras))
    await _record(user_id, title, content, ok, error)
    return ok


async def _send(payload: dict) -> tuple[bool, str]:
    """真正发一条,返回 (成功?, 失败原因)。不写库 —— 写库由调用方决定批不批。"""
    try:
        client = await _get_client()
        resp = await client.post(
            JPUSH_URL,
            json=payload,
            auth=(settings.jpush_app_key, settings.jpush_master_secret),
        )
        if resp.status_code == 200:
            return True, ""
        error = f"HTTP {resp.status_code}: {resp.text[:200]}"
        logger.warning("jpush 推送失败 %s", error)
        return False, error
    except httpx.HTTPError as exc:
        logger.warning("jpush 请求异常: %s", exc)
        return False, f"{type(exc).__name__}: {exc}"


def _payload_for(user_id: int, title: str, content: str,
                 extras: dict | None) -> dict:
    return {
        "platform": "all",
        "audience": {"alias": [f"u{user_id}"]},
        "notification": {
            "android": {"alert": content, "title": title, "extras": extras or {}},
            "ios": {"alert": {"title": title, "body": content},
                    "sound": "default", "extras": extras or {}},
        },
        "options": {"apns_production": True, "time_to_live": 3600},
    }


async def fanout(targets: list[tuple[int, str, str, dict | None]],
                 *, record_skip: bool = False) -> int:
    """推给一批人:分批并发 + 共用连接 + push_logs 一次写完。返回条数。

    targets: [(user_id, title, content, extras), ...]

    ## 为什么不是 for 循环 await

    串行的话总耗时 = 人数 × 单次往返;JPush 超时 5 秒时 500 人能堵 2500 秒,
    整个进程的事件循环被一条推送链占着。分批并发之后上界变成
    (人数 ÷ 并发数) × 超时,而且连接是复用的,正常情况下是秒级。

    ## 为什么分批而不是一次性 gather 全部

    一次性 gather 500 个 = 瞬间 500 个并发 HTTPS 出去,既打爆自己的连接池,
    也容易被对面限流。批大小见 config.push_fanout_concurrency。

    未配置 JPush 时不发网络请求,只按 record_skip 决定留不留痕 ——
    与 push_to_user 的口径保持一致,调用方不需要知道有没有配 Key。
    """
    if not targets:
        return 0
    cap = settings.push_fanout_max_targets
    if len(targets) > cap:
        # 截断而不是照单全发。真到这个量级说明推送策略该改了,
        # 而不是让一次扇出把进程占死。留一条 warning 让人看得见
        logger.warning("推送扇出人数 %s 超过上限 %s,已截断", len(targets), cap)
        targets = targets[:cap]

    if not settings.jpush_configured:
        logger.debug("jpush 未配置,跳过扇出 %s 条", len(targets))
        if record_skip:
            await _record_many([
                (uid, title, content, False, "jpush 未配置(仅记录意图)")
                for uid, title, content, _extras in targets])
        return len(targets)

    rows: list[tuple[int, str, str, bool, str]] = []
    size = max(1, settings.push_fanout_concurrency)
    for start in range(0, len(targets), size):
        chunk = targets[start:start + size]
        results = await asyncio.gather(*[
            _send(_payload_for(uid, title, content, extras))
            for uid, title, content, extras in chunk
        ], return_exceptions=True)
        for (uid, title, content, _extras), res in zip(chunk, results):
            if isinstance(res, BaseException):
                rows.append((uid, title, content, False,
                             f"{type(res).__name__}: {res}"))
            else:
                rows.append((uid, title, content, res[0], res[1]))
    await _record_many(rows)
    return len(targets)


def spawn(coro, *, what: str = "推送") -> None:
    """把一段推送丢到后台跑,不占请求路径。

    用在**调用方不需要知道结果**的地方(典型:支付回调里的骑手扇出 ——
    微信回调超时会重试最多 15 次,绝不能让推送把回调拖超时)。

    两个坑都在这儿处理掉了:
      1. `asyncio.create_task` 的返回值不留引用会被 GC 提前回收,
         任务无声消失 —— 所以存进 _background 集合里;
      2. 后台任务里的异常没人 await 就只会在解释器退出时打一行
         "Task exception was never retrieved" —— 所以自己包一层记日志。
    """
    async def _guarded():
        try:
            await coro
        except Exception:
            logger.exception("后台%s失败(不影响主流程)", what)

    task = asyncio.create_task(_guarded())
    _background.add(task)
    task.add_done_callback(_background.discard)


async def notify_order_status(customer_id: int, order_no: str, status_label: str) -> None:
    """订单状态变更推给用户。推送失败不影响主流程。"""
    await push_to_user(
        customer_id,
        "订单状态更新",
        f"你的订单{status_label}",
        {"order_no": order_no},
    )


async def notify_new_order(merchant_owner_id: int, order_no: str, summary: str) -> None:
    """新订单推给商家老板(离线也能听到,替代只在前台有效的 WebSocket)。"""
    await push_to_user(
        merchant_owner_id,
        "新订单来了",
        summary,
        {"order_no": order_no, "type": "new_order"},
    )


async def notify_riders_new_grab(db, order, shop_name: str) -> int:
    """新单进抢单池 → 推给附近在线的骑手(#114),返回触达人数。

    抢单模式最怕的不是没人抢,是没人知道有单可抢:骑手端只能靠轮询,
    锁屏了就彻底静默 —— 于是出现「单子挂在池里 30 分钟无人接,
    平台按无人接单兜底赔付商家餐损」的局面,骑手也白等一场。

    只推给在线骑手,且按各自的抢单半径过滤(骑手自己设的,不是平台派的):
    抢单仍是广播制,这里只是把广播送到耳边,不改成强制派单。
    同一单每人只推一次(Redis nx),不做「催抢单」的二次轰炸 ——
    真正的兜底催单在 no_rider_alert_minutes 那条线上,各司其职。

    ## 性能上的三处改法(行为不变,只是不再串行)

    位置查询原先是每个骑手一次 `hgetall` 往返,500 个骑手 = 500 次串行 Redis;
    现在用 pipeline 一次要回来。推送原先是逐个 await 的 HTTPS;
    现在交给 `fanout` 分批并发 + 复用连接 + push_logs 一次写完。
    筛选口径(城市 / 半径 / 每人每单只推一次)一个字都没动。
    """
    from sqlalchemy import select

    from ..models import Merchant, User, UserRole
    from ..redis_client import RIDER_LOC_KEY, get_redis
    from ..services.pricing import haversine_m

    try:
        merchant = await db.get(Merchant, order.merchant_id)
        if merchant is None:
            return 0
        if merchant.lat is None or merchant.lng is None:
            return 0
        riders = (await db.scalars(select(User).where(
            User.role == UserRole.rider,
            User.is_online.is_(True))
            # 安全阀。原先无上限:在线骑手有多少就循环多少次,
            # 而这个函数曾经挂在支付回调里
            .limit(settings.push_fanout_max_targets))).all()
        # 多城市隔离:骑手标了城市就只推本城的单(商家没标城市的不隔离)
        riders = [r for r in riders
                  if not (r.city and merchant.city and r.city != merchant.city)]
        if not riders:
            return 0

        redis = get_redis()
        # 一次 pipeline 把所有人的位置要回来,而不是 N 次往返
        pipe = redis.pipeline()
        for rider in riders:
            pipe.hgetall(RIDER_LOC_KEY.format(rider_id=rider.id))
        locations = await pipe.execute()

        nearby: list = []
        for rider, loc in zip(riders, locations):
            # 骑手位置取不到(没上报/已过期)就不推:宁可漏推,
            # 也不把 20 公里外的单推到人脸上
            try:
                rider_lat = float(loc["lat"])
                rider_lng = float(loc["lng"])
            except (KeyError, TypeError, ValueError):
                continue
            distance = haversine_m(rider_lat, rider_lng,
                                   merchant.lat, merchant.lng)
            radius_m = (rider.grab_radius_km or 0) * 1000
            if radius_m and distance > radius_m:
                continue
            nearby.append((rider, distance))
        if not nearby:
            return 0

        # 同一单每人只推一次的幂等键,同样批量下发。
        # 注意 SET NX 的语义要求逐个判断结果,所以还是一人一条命令,
        # 只是不再一条一条等往返
        pipe = redis.pipeline()
        for rider, _distance in nearby:
            pipe.set(f"grab_push:{order.order_no}:{rider.id}", 1, ex=3600, nx=True)
        claimed = await pipe.execute()

        # record_skip:留痕。骑手是最可能事后追问"我怎么没收到这单"的一方,
        # push_logs 让这件事可查而不是各执一词;也让 JPush Key 落地前
        # 就能验证触发链路
        targets = [
            (rider.id, "有新单可抢",
             f"{shop_name} · 距你 {round(distance / 1000, 1)}km · "
             f"配送费 {order.delivery_fee_cents / 100:g} 元(全额归你)",
             {"type": "new_grab", "order_no": order.order_no})
            for (rider, distance), got in zip(nearby, claimed) if got
        ]
        return await fanout(targets, record_skip=True)
    except Exception:
        logger.exception("骑手新单推送失败(不影响主流程): order=%s",
                         getattr(order, "order_no", "?"))
        return 0


async def notify_riders_new_grab_detached(order_no: str, merchant_id: int,
                                          delivery_fee_cents: int,
                                          shop_name: str) -> int:
    """同上,但**自带 session**,可以脱离请求生命周期在后台跑。

    为什么需要单独一个:`notify_riders_new_grab` 收的是调用方的 db session
    和一个 ORM 对象。丢进 `create_task` 之后请求早就返回了、session 也关了,
    再去 `db.get(Merchant, ...)` 只会炸。所以后台版只收基本类型,
    自己开一个 session。
    """
    from ..db import SessionLocal

    class _OrderView:  # 只需要这三个字段,不值得为它去把整行读回来
        __slots__ = ("order_no", "merchant_id", "delivery_fee_cents")

        def __init__(self):
            self.order_no = order_no
            self.merchant_id = merchant_id
            self.delivery_fee_cents = delivery_fee_cents

    async with SessionLocal() as db:
        return await notify_riders_new_grab(db, _OrderView(), shop_name)


async def notify_bad_review(merchant_owner_id: int, rating: int,
                            summary: str) -> None:
    """来了差评(≤3 星)→ 推给店主。差评响应越快挽回余地越大,
    等商家自己翻到店铺页最底下再发现,黄花菜都凉了。"""
    await push_to_user(
        merchant_owner_id,
        f"收到一条 {rating} 星评价",
        summary or "(未留言)",
        {"type": "bad_review"},
        record_skip=True,
    )


async def notify_review_reply(customer_id: int, shop_name: str, reply: str) -> None:
    """商家回复了评价 → 推给写评价的用户(回复不触达 = 白写)。"""
    await push_to_user(
        customer_id,
        f"「{shop_name}」回复了你的评价",
        reply[:80],
        {"type": "review_reply"},
        record_skip=True,
    )


async def notify_favorites(db, merchant_id: int, shop_name: str,
                           title: str, content: str) -> int:
    """收藏触达:收藏了该店的用户逐个推送,返回触达人数。

    防打扰:每店每天最多一条(Redis nx 键),商家连发三张券用户只收到第一条。
    调用方失败不感知——触达是锦上添花,绝不能影响发券/改菜主流程。
    """
    from sqlalchemy import select

    from ..models import Favorite
    from ..redis_client import get_redis

    try:
        if not await get_redis().set(f"fav_push:{merchant_id}", 1,
                                     ex=86400, nx=True):
            return 0
        user_ids = (await db.scalars(
            select(Favorite.user_id)
            .where(Favorite.merchant_id == merchant_id).limit(500))).all()
        # 分批并发,不再逐个 await:500 个收藏用户串行推最坏要 2500 秒,
        # 而这是挂在商家「发券/上新」的请求路径上的
        return await fanout(
            [(uid, title, content,
              {"type": "favorite", "merchant_id": merchant_id})
             for uid in user_ids],
            record_skip=True)
    except Exception:
        logger.exception("收藏触达失败(不影响主流程): merchant=%s", merchant_id)
        return 0


#: 每个状态变更该通知谁,以及对各方说什么(#302)。
#:
#: ## 为什么要这张表
#:
#: 在此之前状态变更**只推给顾客**。三个关键点击的按钮都早就有了
#: (商家「出餐完成」、骑手「已取餐」「已送达」),但信号只走到一端:
#:
#: - 商家点了「出餐完成」→ 骑手收不到,只能靠 15 秒轮询,
#:   他就站在店门口等着,而餐已经好了;
#: - 骑手点了「已取餐」「已送达」→ 商家收不到,看板要自己刷。
#:
#: WebSocket 只有 `order:{order_no}`(要开着那一单的详情页)和
#: `merchant:{id}`(只在新单和支付时广播),都接不住这几下。
#:
#: ## 措辞要说下一步动作,不是复述状态
#:
#: 「订单状态更新:待取餐」对骑手没有意义 —— 他要的是「餐好了,可以取了」。
#: 通知的价值在于**接下来该干什么**,不在于告诉你系统里那个字段变成了啥。
#:
#: ## 不推给动作的发起人
#:
#: 谁点的谁知道,再推一遍是骚扰。调用处按 actor 过滤。
_STATUS_FANOUT: dict[str, dict[str, tuple[str, str]]] = {
    # 状态: {角色: (标题, 正文)}
    "accepted": {
        "customer": ("商家已接单", "商家开始做了,做好会有骑手来取"),
    },
    "ready": {
        # 这一条是这次改动的重点:骑手在楼下等,餐好了他得马上知道
        "rider": ("餐好了,可以取了", "商家已出餐,去取餐吧"),
        "customer": ("商家已出餐", "等骑手取走就出发了"),
    },
    "picked_up": {
        "customer": ("骑手已取餐", "正在送来的路上"),
        "merchant": ("骑手已取餐", "这一单已经出门了"),
    },
    "delivered": {
        "customer": ("餐到了", "请查收;有问题可以在订单里申请售后"),
        "merchant": ("已送达", "这一单送到了"),
    },
    "completed": {
        # 完成 = 结算点,骑手的配送费这一刻才真的进账。
        # 在此之前他跑完一单没有任何回音,要自己去钱包页看 ——
        # **钱到账是最该主动说一声的事**
        "rider": ("这一单结清了", "配送费已入账,可以在钱包里查"),
        "merchant": ("订单已完成", "货款已结算入账"),
    },
    "cancelled": {
        "customer": ("订单已取消", "退款会原路返回"),
        "merchant": ("订单已取消", "不用做了"),
        "rider": ("订单已取消", "这一单不用送了"),
    },
}


async def fanout_order_status(
    status_value: str,
    *,
    customer_id: int,
    merchant_owner_id: int | None,
    rider_id: int | None,
    order_no: str,
    actor_id: int | None,
) -> None:
    """把状态变更推给这一单的**每一个**相关方(#302)。

    `actor_id` 是点这一下的人,不推给他自己。
    推送失败不影响主流程 —— 这是通知,不是业务。
    """
    plan = _STATUS_FANOUT.get(status_value)
    if not plan:
        return
    targets = {
        "customer": customer_id,
        "merchant": merchant_owner_id,
        "rider": rider_id,
    }
    for role, (title, body) in plan.items():
        uid = targets.get(role)
        if uid is None or uid == actor_id:
            continue
        await push_to_user(uid, title, body,
                           {"order_no": order_no, "type": "order_status"})
