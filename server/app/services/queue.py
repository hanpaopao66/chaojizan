"""到店排队:取号、叫号、过号、入座。

## 这个功能解决什么

团购券解决的是「钱先付了」,排队解决的是「位怎么排」。两件事**故意不绑在一起**
—— 见下面「平台规则」里的第一条。

## 平台规则(不给商家配,也不给平台自己留后门)

调研美团那套排队时,最值得学的是商家侧的配置经验(桌型分队、放号上限、
两段式提醒),最值得躲开的是它生态里已经出现的东西:黑猫上有商家
「引导办卡可以免排队」—— 那就是把插队权卖了。

所以这三条写死在代码里:

1. **买券不能插队。** 取号免费开放,和买没买券、买了几张、是不是会员
   统统无关。券只代表钱先付了,跟谁先到店没有关系。
2. **没有任何接口能把号往前挪。** `sort_key` 只有三种改法:取号排到队尾、
   过号往后挪、以及不改。往前挪的代码不存在 —— 「平台不卖插队权」
   这句话要能被证伪,首先它得在代码里真的做不到。
3. **叫号后 [CALL_GRACE_SECONDS] 秒内不许标过号。** 这条是对称性:
   用户过号有代价(顺延、两次转待恢复),那商家叫完号立刻点过号
   也不能是零成本。秒过号在代码层面就不允许。

## 为什么过号用「顺延 N 桌」而不是「保留 X 分钟」

美团的教程明说这两种二选一、别混。选顺延是因为它对「路上堵了十分钟」
的人不至于一刀作废,而且规则和队列位置挂钩、可留痕、可申诉;
保留 X 分钟的口径受商家叫号快慢影响,同样等十分钟,商家叫号慢的店就没事、
叫号快的店就作废,解释不清。

顺延两次还没到才转 `pending_restore` —— 到店找商家恢复,不是作废。
"""
from __future__ import annotations

import math
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import (QUEUE_LIVE_STATUSES, Merchant, QueueEvent, QueueSetting,
                      QueueTableType, QueueTicket, QueueTicketStatus)

# ---------- 平台规则:商家配不了,平台也没给自己留后门 ----------

#: 叫号后至少这么久才允许标过号的**默认值**。见模块注释第 3 条。
#: 实际生效值走 grace_seconds() —— 自部署者可以改,但改了公示上就是改后的数。
CALL_GRACE_SECONDS = 120


def grace_seconds() -> int:
    """实际生效的叫号宽限期。

    **商家改不了**(不在 QueueSetting 里),平台部署方可以改,
    而改了之后 /transparency/queue 报的就是改后的值 —— 藏不住。
    """
    from ..config import settings
    return max(0, int(settings.queue_call_grace_seconds))

#: 顺延几次之后转「待恢复」。第 1 次过号顺延,第 2 次转待恢复。
MAX_DEFERS = 2

#: 商家可配项的取值范围(超出范围直接拒绝,不静默夹紧 ——
#: 夹紧的话商家以为自己设成了 20,实际是 8,而用户看到的是 8)
CAP_MULTIPLIER_RANGE = (1, 10)
DEFER_TABLES_RANGE = (1, 8)
NOTIFY_AHEAD_RANGE = (1, 10)
TURN_MINUTES_RANGE = (5, 240)

#: 公示与接口里都用这一句,别两处各写各的
WAIT_BASIS = ("按「(前方桌数+1) ÷ 本档桌数,向上取整,再乘每桌预计用餐时长」估的上限,"
              "实际通常更快。桌数和时长由商家填,公示里能查到。")


def beijing_today() -> date:
    """按北京时间切日。

    **不能用 date.today()** —— 开发机在 PDT 时本地日期比北京晚一天,
    号码会在下午整体串一天(账本那边已经踩过这个坑)。
    """
    from zoneinfo import ZoneInfo
    return datetime.now(ZoneInfo("Asia/Shanghai")).date()


# ---------- 纯函数:不碰库,单测直接打 ----------


def pick_table_type(types: list[QueueTableType], party_size: int):
    """按人数挑桌型:**能坐下的里面最小的那档**。

    确定性地挑,不让用户自己选大桌 —— 否则 2 个人挑包间排队,
    包间那条队被占着,真正 8 个人的桌反而排不上,这本身就是一种插队。

    挑不到(人数超过最大桌)返回 None,由调用方给一句人话。
    """
    fit = [t for t in types
           if t.is_active and t.seats_min <= party_size <= t.seats_max]
    if not fit:
        return None
    return min(fit, key=lambda t: (t.seats_max, t.id))


def wait_upper_minutes(ahead: int, table_count: int, turn_minutes: int) -> int:
    """预计等待的**上限**,分钟。

    模型:本档 table_count 张桌都坐满,每 turn_minutes 翻一次台。
    排在你前面还有 ahead 桌,那你是第 ahead+1 位,要等
    ceil((ahead+1) / table_count) 轮。

    **故意报上限而不是期望值**:报低了用户白等一肚子气,报高了实际更快
    是惊喜。口径公示在 WAIT_BASIS 里,谁都能自己复算。
    """
    if table_count <= 0:
        return 0
    return math.ceil((ahead + 1) / table_count) * max(0, turn_minutes)


def issue_cap(table_count: int, cap_multiplier: int) -> int:
    """放号上限 = 桌数 × 倍数。

    不封顶的话队尾那些人等两小时也坐不上 —— 取了号反而比不让取更生气。
    美团教程给的经验值是 ×3。
    """
    return max(0, table_count) * max(1, cap_multiplier)


def deferred_sort_key(other_keys: list[Decimal], defer_tables: int) -> Decimal:
    """过号顺延之后的新排序键:排到「前面再走掉 defer_tables 桌」的位置。

    other_keys 是同一条队里**其余等待中**号的 sort_key,升序。

    - 前面不足 defer_tables 桌:直接去队尾(最大值 +1)。
      这是顺延的自然结果,不是惩罚加码。
    - 否则取第 defer_tables 个和第 defer_tables+1 个的中点。

    取中点而不是重排全队,是因为重排会动到别人的键 —— 而「别人的位置
    不因为你过号而改变」本身就是要守的东西。
    """
    keys = sorted(other_keys)
    n = max(1, defer_tables)
    if not keys:
        return Decimal(1)
    if len(keys) <= n:
        return keys[-1] + Decimal(1)
    return (keys[n - 1] + keys[n]) / Decimal(2)


def ticket_code(table_type_id: int, seq: int) -> str:
    """对外的号码:桌型字母 + 三位序号,如 A012。

    字母按桌型轮转(A-Z),让同一家店的不同队列一眼能分开 ——
    喊「A12 号」比喊「12 号」少一半的走错队。
    """
    return f"{chr(ord('A') + table_type_id % 26)}{seq:03d}"


def can_pass(called_at: datetime | None, now: datetime | None = None) -> bool:
    """现在能不能标过号。见模块注释第 3 条(对称性)。"""
    if called_at is None:
        return False
    now = now or datetime.now(timezone.utc)
    if called_at.tzinfo is None:
        called_at = called_at.replace(tzinfo=timezone.utc)
    return (now - called_at) >= timedelta(seconds=grace_seconds())


# ---------- 碰库的部分 ----------


async def get_setting(db: AsyncSession, merchant_id: int) -> QueueSetting:
    s = await db.get(QueueSetting, merchant_id)
    if s is None:
        s = QueueSetting(merchant_id=merchant_id)
        db.add(s)
        await db.flush()
    return s


async def _log(db: AsyncSession, ticket: QueueTicket, action: str,
               actor_role: str, actor_id: int | None, detail: str = "") -> None:
    db.add(QueueEvent(ticket_id=ticket.id, merchant_id=ticket.merchant_id,
                      action=action, actor_role=actor_role,
                      actor_id=actor_id, detail=detail))


async def waiting_keys(db: AsyncSession, table_type_id: int, day: date,
                       *, exclude_id: int | None = None) -> list[Decimal]:
    """同一条队里还在等的号的排序键(升序)。"""
    q = select(QueueTicket.sort_key).where(
        QueueTicket.table_type_id == table_type_id,
        QueueTicket.day == day,
        QueueTicket.status == QueueTicketStatus.waiting,
    )
    if exclude_id is not None:
        q = q.where(QueueTicket.id != exclude_id)
    return sorted((await db.scalars(q.order_by(QueueTicket.sort_key))).all())


async def live_count(db: AsyncSession, table_type_id: int, day: date) -> int:
    """占着放号名额的号数:等待中 + 已叫号 + 待恢复。"""
    return int(await db.scalar(
        select(func.count()).select_from(QueueTicket).where(
            QueueTicket.table_type_id == table_type_id,
            QueueTicket.day == day,
            QueueTicket.status.in_(QUEUE_LIVE_STATUSES),
        )) or 0)


async def ahead_of(db: AsyncSession, ticket: QueueTicket) -> int:
    """前方还有几桌(只数等待中的;已叫号的那桌已经在往里走了)。"""
    return int(await db.scalar(
        select(func.count()).select_from(QueueTicket).where(
            QueueTicket.table_type_id == ticket.table_type_id,
            QueueTicket.day == ticket.day,
            QueueTicket.status == QueueTicketStatus.waiting,
            QueueTicket.sort_key < ticket.sort_key,
        )) or 0)


async def active_ticket_of(db: AsyncSession, merchant_id: int,
                           customer_id: int) -> QueueTicket | None:
    """这个人在这家店还没走完的号。

    一人一店同时只能有一个 —— 取号免费,不设这道闸门的话
    一个人可以把整条队占满,而代价是零。
    """
    return await db.scalar(
        select(QueueTicket).where(
            QueueTicket.merchant_id == merchant_id,
            QueueTicket.customer_id == customer_id,
            QueueTicket.day == beijing_today(),
            QueueTicket.status.in_(QUEUE_LIVE_STATUSES),
        ).order_by(QueueTicket.id.desc()))


# ---------- 状态流转。每一步都留痕,因为公示承诺了可核查 ----------


class QueueError(Exception):
    """业务上说不通的操作。路由把它翻成 409 + 这句人话。"""


async def take_ticket(db: AsyncSession, shop: Merchant, customer_id: int,
                      party_size: int) -> QueueTicket:
    """取号。

    **和买没买券无关** —— 这是整个功能里最要紧的一条,见模块注释。
    """
    setting = await get_setting(db, shop.id)
    if not setting.enabled:
        raise QueueError("这家店没有开排队")

    dup = await active_ticket_of(db, shop.id, customer_id)
    if dup is not None:
        raise QueueError(f"你在这家店已经有号了({dup.ticket_no}),"
                         f"取消之后才能重新取")

    types = (await db.scalars(select(QueueTableType).where(
        QueueTableType.merchant_id == shop.id,
        QueueTableType.is_active.is_(True),
    ))).all()
    tt = pick_table_type(list(types), party_size)
    if tt is None:
        biggest = max((t.seats_max for t in types), default=0)
        raise QueueError(
            f"{party_size} 位坐不下 —— 这家店最大的桌是 {biggest} 位"
            if biggest else "这家店还没设桌型")

    # **行锁锁在店上,不是桌型上。** 序号按「店 + 当天」发(见下),
    # 所以要串起来的是同一家店的所有取号,不是同一条队的。
    # 锁桌型的话,两条队同时取号会各自算出同一个序号。
    await db.execute(select(QueueSetting.merchant_id).where(
        QueueSetting.merchant_id == shop.id).with_for_update())

    day = beijing_today()
    cap = issue_cap(tt.table_count, setting.cap_multiplier)
    if await live_count(db, tt.id, day) >= cap:
        raise QueueError(
            f"{tt.name}的号发完了(今天最多 {cap} 个)—— "
            f"再放号也是白等,晚点再来看看")

    # **序号按「店 + 当天」递增,不按桌型。**
    #
    # 按桌型发的话号码会撞:号码是「店-月日-字母+序号」,字母取 桌型id % 26,
    # 而序号又从 1 重新起 —— 桌型 id 相差 26 的两条队(比如 12 和 38 都是 M)
    # 各自的第一个号都是 M001,`ticket_no` 的唯一约束当场炸,取号返回 500。
    # 桌型 id 是全局递增的,一家店先后建的两个桌型差 26 很正常,
    # 生产上会真踩到。(全套 e2e 跑出来的,单跑两条用例都不会撞。)
    #
    # 代价是同一条队的号不连号(A001、B002、A003)。可接受 ——
    # 反而少了「两条队都有 001 号」那种叫号时的歧义。
    seq = int(await db.scalar(select(func.coalesce(func.max(QueueTicket.seq), 0))
                              .where(QueueTicket.merchant_id == shop.id,
                                     QueueTicket.day == day)) or 0) + 1
    top = await db.scalar(select(func.coalesce(func.max(QueueTicket.sort_key), 0))
                          .where(QueueTicket.table_type_id == tt.id,
                                 QueueTicket.day == day))
    ticket = QueueTicket(
        ticket_no=f"{shop.id}-{day:%m%d}-{ticket_code(tt.id, seq)}",
        merchant_id=shop.id, table_type_id=tt.id, customer_id=customer_id,
        party_size=party_size, day=day, seq=seq,
        sort_key=Decimal(top or 0) + Decimal(1),
        status=QueueTicketStatus.waiting,
    )
    db.add(ticket)
    await db.flush()
    await _log(db, ticket, "take", "customer", customer_id,
               f"{party_size}位 → {tt.name}")
    return ticket


async def call_ticket(db: AsyncSession, ticket: QueueTicket,
                      actor_id: int) -> None:
    """叫号。"""
    if ticket.status != QueueTicketStatus.waiting:
        raise QueueError("这个号现在不能叫(只有排队中的号可以)")
    ticket.status = QueueTicketStatus.called
    ticket.called_at = datetime.now(timezone.utc)
    await _log(db, ticket, "call", "merchant", actor_id)
    await _notify(ticket.customer_id, "到号了",
                  f"{ticket.ticket_no} 到号,请到店内前台。"
                  f"没赶上会顺延,不会直接作废")


async def pass_ticket(db: AsyncSession, ticket: QueueTicket,
                      actor_id: int) -> str:
    """标过号。返回一句给商家看的结果说明。

    **叫号后不足 CALL_GRACE_SECONDS 秒不许过号** —— 用户过号有代价,
    商家秒过号也不能零成本。这是对称性,不是给商家添麻烦。
    """
    if ticket.status != QueueTicketStatus.called:
        raise QueueError("只有已叫号的号可以标过号")
    if not can_pass(ticket.called_at):
        left = grace_seconds() - int(
            (datetime.now(timezone.utc) - ticket.called_at.replace(
                tzinfo=ticket.called_at.tzinfo or timezone.utc)).total_seconds())
        raise QueueError(
            f"叫号还不到 {grace_seconds()} 秒,再等 {max(1, left)} 秒。"
            f"客人可能正在往里走")

    setting = await get_setting(db, ticket.merchant_id)
    ticket.passed_count += 1
    ticket.called_at = None
    if ticket.passed_count >= MAX_DEFERS:
        if ticket.pre_pass_sort_key is None:
            ticket.pre_pass_sort_key = ticket.sort_key
        ticket.status = QueueTicketStatus.pending_restore
        await _log(db, ticket, "pass", "merchant", actor_id,
                   f"第{ticket.passed_count}次过号 → 待恢复")
        await _notify(ticket.customer_id, "号已转待恢复",
                      f"{ticket.ticket_no} 两次叫号都没到,已转「待恢复」。"
                      f"到店找商家可以恢复,不用重新取号")
        return "已转待恢复(到店可恢复)"

    keys = await waiting_keys(db, ticket.table_type_id, ticket.day,
                              exclude_id=ticket.id)
    # 记下过号前的位置:申诉判这次过号不成立时,要能还原回来。
    # 只在第一次过号时记 —— 连着两次过号的话,该还原的是最初那个位置
    if ticket.pre_pass_sort_key is None:
        ticket.pre_pass_sort_key = ticket.sort_key
    ticket.sort_key = deferred_sort_key(keys, setting.defer_tables)
    ticket.status = QueueTicketStatus.waiting
    ticket.notified_ahead_at = None      # 重新排队,临近提醒要能再响一次
    await _log(db, ticket, "pass", "merchant", actor_id,
               f"第{ticket.passed_count}次过号,顺延{setting.defer_tables}桌")
    await _notify(ticket.customer_id, "已为你顺延",
                  f"{ticket.ticket_no} 没赶上,已顺延 {setting.defer_tables} 桌,"
                  f"号还在。再过一次号会转待恢复")
    return f"已顺延 {setting.defer_tables} 桌"


async def restore_ticket(db: AsyncSession, ticket: QueueTicket,
                         actor_id: int) -> None:
    """把待恢复的号放回队列。

    放回的位置和过号顺延是**同一条规则**(顺延 defer_tables 桌),
    不是排到队尾也不是插回原位 —— 两种特殊待遇都解释不清。
    """
    if ticket.status != QueueTicketStatus.pending_restore:
        raise QueueError("只有待恢复的号需要恢复")
    setting = await get_setting(db, ticket.merchant_id)
    keys = await waiting_keys(db, ticket.table_type_id, ticket.day,
                              exclude_id=ticket.id)
    ticket.sort_key = deferred_sort_key(keys, setting.defer_tables)
    ticket.status = QueueTicketStatus.waiting
    ticket.notified_ahead_at = None
    await _log(db, ticket, "restore", "merchant", actor_id,
               f"恢复,按顺延{setting.defer_tables}桌重排")
    await _notify(ticket.customer_id, "号已恢复",
                  f"{ticket.ticket_no} 已恢复排队,按顺延 "
                  f"{setting.defer_tables} 桌重新排")


async def seat_ticket(db: AsyncSession, ticket: QueueTicket,
                      actor_id: int) -> None:
    """入座。队列往前走一格,这里顺带触发临近提醒。"""
    if ticket.status not in (QueueTicketStatus.called,
                             QueueTicketStatus.waiting):
        raise QueueError("这个号现在不能入座")
    ticket.status = QueueTicketStatus.seated
    ticket.seated_at = datetime.now(timezone.utc)
    await _log(db, ticket, "seat", "merchant", actor_id)


async def cancel_ticket(db: AsyncSession, ticket: QueueTicket,
                        actor_role: str, actor_id: int) -> None:
    """取消。用户自己不等了,或者商家打烊清场。"""
    if ticket.status not in QUEUE_LIVE_STATUSES:
        raise QueueError("这个号已经结束了")
    ticket.status = QueueTicketStatus.cancelled
    ticket.closed_at = datetime.now(timezone.utc)
    await _log(db, ticket, "cancel", actor_role, actor_id)


async def notify_near(db: AsyncSession, table_type_id: int,
                      day: date) -> int:
    """两段式提醒的前一段:前方还剩 notify_ahead 桌时推一次。

    只推一次(notified_ahead_at 记着)—— 队列每次入座都会重算,
    不记的话同一个人会被反复轰炸。
    """
    tt = await db.get(QueueTableType, table_type_id)
    if tt is None:
        return 0
    setting = await get_setting(db, tt.merchant_id)
    rows = (await db.scalars(select(QueueTicket).where(
        QueueTicket.table_type_id == table_type_id,
        QueueTicket.day == day,
        QueueTicket.status == QueueTicketStatus.waiting,
        QueueTicket.notified_ahead_at.is_(None),
    ).order_by(QueueTicket.sort_key).limit(setting.notify_ahead + 1))).all()
    sent = 0
    for i, t in enumerate(rows):
        if i >= setting.notify_ahead:
            break
        t.notified_ahead_at = datetime.now(timezone.utc)
        await _notify(t.customer_id, "快到你了",
                      f"{t.ticket_no} 前方还有 {i} 桌,"
                      f"该往店里走了 —— 叫号后 "
                      f"{grace_seconds()} 秒内没到会顺延")
        sent += 1
    return sent


async def _notify(user_id: int, title: str, content: str) -> None:
    """排队推送一律留痕(record_skip=True)。

    低频、且用户会拿它当证据(「我根本没收到到号提醒」),
    没配 JPush 的部署也要能看出触发链路走到了哪一步。
    """
    from . import push
    await push.push_to_user(user_id, title, content,
                            {"type": "queue"}, record_skip=True)


def public_spec() -> dict:
    """排队规则的公示口径。**数字从上面的常量直接读,不另抄一份** ——
    抄一份就会有一天代码改了公示没改,而公示是拿来被人对着查的。
    """
    return {
        "no_priority": {
            "claim": "取号免费,买券、会员、任何付费都不能插队。",
            "why": ("排队排的是先来后到。一旦能用钱买位置,先到的人就白等了 ——"
                    "而平台从中什么也没多创造出来,只是把别人的等待卖了一次。"),
            "how_to_check": ("每个号的完整流水对当事人开放:"
                             "GET /queue/tickets/{号}/events。"
                             "谁在什么时候动了这个号、动成什么样,一条不落。"),
        },
        "pass_rule": {
            "text": ("叫到号没到:顺延若干桌,号还在;"
                     f"累计 {MAX_DEFERS} 次转「待恢复」,到店找商家恢复,不作废。"),
            "max_defers": MAX_DEFERS,
            "why_not_timeout": ("另一种常见做法是「保留 X 分钟,超时作废」。"
                                "没采用是因为同样等十分钟,商家叫号慢的店没事、"
                                "叫号快的店就作废 —— 口径受商家节奏影响,说不清。"),
            "restore_position": "恢复后按和顺延同一条规则重排,不排队尾也不插回原位。",
        },
        "merchant_limits": {
            "call_grace_seconds": grace_seconds(),
            "text": (f"商家叫号后不足 {grace_seconds()} 秒不能标你过号。"
                     "这条是平台规则,商家改不了。"),
            "why": ("用户过号有代价,那商家叫完号立刻点过号也不能零成本 —— "
                    "否则「过号」就成了一个随手清队列的按钮。"),
        },
        "wait_estimate": {
            "basis": WAIT_BASIS,
            "stance": ("报的是上限,不是期望值。报低了用户白等一肚子气,"
                       "实际更快是惊喜。"),
        },
        "issue_cap": {
            "text": "放号上限 = 本档桌数 × 商家设的倍数(1–10,默认 3)。",
            "why": "不封顶的话队尾的人等两小时也坐不上,取了号比不让取更生气。",
        },
        "platform_take": {
            "text": "排队本身平台不收钱。",
            "why": "它不产生交易。平台只在团购券核销时收 2% 服务费。",
        },
        "appeal": {
            "target_type": "queue_pass",
            "text": "认为自己被不公平地过号或跳过,可以申诉,平台查这个号的完整流水。",
        },
    }


async def undo_pass(db: AsyncSession, ticket: QueueTicket,
                    actor_id: int) -> bool:
    """撤销一次不当过号:还原到过号前的位置。**只有申诉判成立才走这里。**

    这是 `sort_key` 唯一一条会变小的路径,而且它做不到"挪到任意位置" ——
    只能还原到 `pre_pass_sort_key` 里记着的那个值,那个值是过号当时写下的。
    平台自己也没有把谁往前插的能力,这一点和商家一样。

    队已经散了(号不在队列里、或者已经是隔天)就还原不了 —— 返回 False,
    由调用方如实告诉用户「位置补不回来,但这次过号已判给你」。
    位置补不回来是事实,不该拿一句含糊话盖过去。
    """
    if ticket.status != QueueTicketStatus.waiting:
        return False
    if ticket.day != beijing_today() or ticket.pre_pass_sort_key is None:
        return False
    back_to = ticket.pre_pass_sort_key
    ticket.sort_key = back_to
    ticket.pre_pass_sort_key = None
    ticket.passed_count = max(0, ticket.passed_count - 1)
    await _log(db, ticket, "undo_pass", "admin", actor_id,
               f"申诉成立,还原到 {back_to}")
    await _notify(ticket.customer_id, "过号已撤销",
                  f"{ticket.ticket_no} 的那次过号经复核不成立,"
                  f"位置已还原。")
    return True


#: 一个号最多活多久(小时)。超过就清场,置为 expired。
#:
#: **判据是「取号之后过了多久」,不是日历天,也不是营业时间。**
#:
#: 按日历天切是错的:开到凌晨两点的店,23:50 取的号在 00:00 就"隔天"了 ——
#: 而那个人还在门口站着。跨零点营业的店按日历天清,清的是活人。
#:
#: 按营业结束时间切在语义上最准,但要串营业时间 + 节假日计划 + 临时歇业
#: 三样,每一样都是一处能算错的地方;而算错的后果是把还在排队的人清掉。
#: 「没有哪个餐厅的队要排 6 小时」这个判据简单得多,而且跨零点也对。
QUEUE_TICKET_MAX_HOURS = 6


def is_stale(created_at: datetime, now: datetime | None = None) -> bool:
    """这个号是不是该清场了。"""
    now = now or datetime.now(timezone.utc)
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    return (now - created_at) >= timedelta(hours=QUEUE_TICKET_MAX_HOURS)


async def sweep_stale_tickets(db: AsyncSession, now: datetime) -> int:
    """清场:把挂着没走完的号置为 expired。返回清掉几个。

    ## 为什么必须有终态

    不清的话,一个号会永远停在 waiting。**它最后到底是坐上了、自己走了、
    还是店打烊了没轮到,查不出来** —— 而公示里的 seated/taken 正是靠这个
    区分「排到了」和「排了半天没排上」。没有终态,这两件事在数字上长得一样。

    对用户端和商家端没有可见影响(两边的列表都按当天过滤),所以这不是
    一个能从界面上看出来的毛病 —— 只会在数据里慢慢攒。

    单轮最多 500 个,剩下的下一轮接着清(清扫每 30 秒跑一次,不会积压)。
    """
    stale = (await db.scalars(
        select(QueueTicket).where(
            QueueTicket.status.in_(QUEUE_LIVE_STATUSES),
            QueueTicket.created_at
            < now - timedelta(hours=QUEUE_TICKET_MAX_HOURS),
        ).with_for_update(skip_locked=True).limit(500))).all()
    for t in stale:
        was = t.status.value
        t.status = QueueTicketStatus.expired
        t.closed_at = now
        await _log(db, t, "expire", "system", None,
                   f"超过 {QUEUE_TICKET_MAX_HOURS} 小时未走完(清场前状态:{was})")
    return len(stale)
