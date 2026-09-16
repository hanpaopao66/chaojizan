"""设备推送地址的登记(#384)。

自己发推送就得自己存设备:苹果要 APNs 的 device token,安卓各厂商要各自的 regid。
以前这些都在极光那边,服务端只认 `u{user_id}` 一个别名。

三条规矩,都是踩着别人的坑写的:

1. **一个 token 只属于一台设备**,所以 `(channel, token)` 唯一。换人登录时把这一行
   **改挂**到新的人名下,不是新插一行 —— 不然上一个人退出登录之后,推送还继续发到这台手机;
2. **失效了下线但不删行**:留着才看得出"这台设备什么时候掉的";
3. **连续失败才下线**:一次网络抖动不算数,不然一次机房故障能把全站设备下线一遍。
"""
import logging
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import PushDevice

logger = logging.getLogger("superz.push.devices")

#: 认这几条通道。**不认识的一律拒**:打错一个字的后果是这台设备再也收不到推送,
#: 而注册接口会高高兴兴回 200 —— 这种错没人查得出来
CHANNELS = ("apns", "hms", "xiaomi", "oppo", "vivo", "honor", "jpush")

#: 连着失败几次就下线。偶发失败(对面抖一下、网络超时)不算
FAIL_LIMIT = 5


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


async def register(db: AsyncSession, user_id: int, *, channel: str, token: str,
                   app: str = "user", sandbox: bool = False) -> PushDevice:
    """登记 / 更新一台设备。客户端每次启动都可以调,幂等。"""
    row = await db.scalar(select(PushDevice).where(
        PushDevice.channel == channel, PushDevice.token == token))
    if row is None:
        row = PushDevice(user_id=user_id, channel=channel, token=token,
                         app=app, sandbox=sandbox)
        db.add(row)
        await db.flush()
        return row
    # 同一台设备换了人登录:改挂过去,并且把上一次的失败清零、重新上线
    row.user_id = user_id
    row.app = app
    row.sandbox = sandbox
    row.seen_at = now_utc()
    row.fail_count = 0
    row.disabled_at = None
    await db.flush()
    return row


async def unregister(db: AsyncSession, *, channel: str, token: str) -> None:
    """退出登录时下线这台设备。

    **不删行**:同一台设备下次登录还会用同一个 token 注册回来,
    留着这一行就能看出它的历史(什么时候归谁、掉过几次)。
    """
    await db.execute(update(PushDevice)
                     .where(PushDevice.channel == channel, PushDevice.token == token)
                     .values(disabled_at=now_utc()))


async def unregister_all(db: AsyncSession, user_id: int) -> None:
    """这个人名下所有设备下线(注销账号时用)。"""
    await db.execute(update(PushDevice)
                     .where(PushDevice.user_id == user_id,
                            PushDevice.disabled_at.is_(None))
                     .values(disabled_at=now_utc()))


async def active_for(db: AsyncSession, user_ids: list[int]) -> dict[int, list[PushDevice]]:
    """这些人各有哪些还活着的设备。一次查完,不按人一个个查。"""
    if not user_ids:
        return {}
    rows = list(await db.scalars(select(PushDevice).where(
        PushDevice.user_id.in_(user_ids), PushDevice.disabled_at.is_(None))))
    out: dict[int, list[PushDevice]] = {}
    for r in rows:
        out.setdefault(r.user_id, []).append(r)
    return out


async def mark_result(db: AsyncSession, device_id: int, *, ok: bool, gone: bool) -> None:
    """记一次发送结果:成功清零失败数;对面说 token 没了就直接下线;
    其余失败累加,连续到 [FAIL_LIMIT] 才下线。"""
    row = await db.get(PushDevice, device_id)
    if row is None:
        return
    if ok:
        row.fail_count = 0
        row.seen_at = now_utc()
        return
    if gone:
        row.disabled_at = now_utc()
        logger.info("设备 token 已失效,下线:device=%s channel=%s", row.id, row.channel)
        return
    row.fail_count += 1
    if row.fail_count >= FAIL_LIMIT:
        row.disabled_at = now_utc()
        logger.info("设备连续失败 %s 次,下线:device=%s channel=%s",
                    row.fail_count, row.id, row.channel)
