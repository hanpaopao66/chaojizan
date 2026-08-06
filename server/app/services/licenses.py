"""证照有效期:一个地方决定"这张证现在处在哪一档"。

## 为什么要有这个模块

美团《入网餐饮服务提供者审查登记规范》把「营业执照和行业资质提交审核时
过期或**合作期间未能保持持续有效**」列为违规。我们此前完全没管:
库里只有证号和照片,没有到期日。食品经营许可证一般 5 年,到期是
**静默失效** —— 商家不会自己记得,平台也不知道,直到监管上门。

## 取舍:过期不立即停业,给 7 天宽限

食品经营许可证过期继续经营是违法的,平台放任有连带责任 —— 这是必须管的。
但一到期就停业会误伤两类人:证已经续上了只是忘了在平台更新的,
和证在审批流程里卡着的(续证本身要时间)。这两类占绝大多数,
而真正无证经营的是极少数。

所以分四档,前三档只提醒不拦:
- **30 天**:第一次提醒。续证要跑流程,提前一个月是能来得及的最短提前量。
- **7 天**:第二次,措辞加重。
- **1 天**:最后一次。
- **过期**:进入 7 天宽限期 —— 商家端顶部常驻横幅、合规档案标红、
  admin 待处理列表可见。**仍然可以正常接单。**
- **宽限期满**:才置 food_safety_hold(与食安停业同一个闸门,
  商家自己开不回来,必须人工核验新证)。

这个梯度是"平台该管"和"别误伤"之间的取舍点。要更严或更松,
改 GRACE_DAYS 和 NOTIFY_DAYS 即可,判定逻辑不用动。

## 不猜

`license_expires_at` 为空 = 未登记,**一律不触发任何提醒和拦截**。
存量商家都是这个状态,等他们下次编辑资质时补录。
给存量数据瞎猜一个日期,猜错就是把正常营业的店误判成过期。
"""
from datetime import date, timedelta

# 到期前哪几档发提醒(天)。降序,取第一个命中的档。
NOTIFY_DAYS = (30, 7, 1)
# 过期后的宽限天数:期间照常接单,只是提醒升级为常驻横幅
GRACE_DAYS = 7


def stage(expires_at: date | None, today: date | None = None) -> str:
    """这张证现在处在哪一档。

    返回 unknown(未登记)/ ok / soon(≤30天)/ urgent(≤7天)/ last(≤1天)
    / expired(已过期,宽限期内)/ overdue(宽限期满,该停了)。
    """
    if expires_at is None:
        return "unknown"
    today = today or date.today()
    left = (expires_at - today).days
    if left < -GRACE_DAYS:
        return "overdue"
    if left < 0:
        return "expired"
    if left <= 1:
        return "last"
    if left <= 7:
        return "urgent"
    if left <= 30:
        return "soon"
    return "ok"


def days_left(expires_at: date | None, today: date | None = None) -> int | None:
    if expires_at is None:
        return None
    return (expires_at - (today or date.today())).days


def notice(shop_name: str, expires_at: date,
           today: date | None = None) -> tuple[str, str] | None:
    """给商家的提醒文案。不需要提醒时返回 None。

    文案里一律带上**到期日原文和还剩几天** —— 只说"即将到期"的通知,
    商家看完还得自己去翻证件。
    """
    st = stage(expires_at, today)
    left = days_left(expires_at, today)
    day = expires_at.isoformat()
    if st == "soon":
        return (f"食品经营许可证还有 {left} 天到期",
                f"「{shop_name}」的食品经营许可证有效期至 {day},还剩 {left} 天。"
                f"续证要跑审批流程,建议现在就去办;拿到新证后在商家端更新即可。")
    if st == "urgent":
        return (f"食品经营许可证 {left} 天后到期",
                f"「{shop_name}」的食品经营许可证 {day} 到期,还剩 {left} 天。"
                f"过期后仍可营业 {GRACE_DAYS} 天,之后需人工核验新证才能恢复接单。")
    if st == "last":
        return ("食品经营许可证明天到期",
                f"「{shop_name}」的食品经营许可证 {day} 到期。"
                f"过期后有 {GRACE_DAYS} 天宽限期,请尽快上传新证。")
    if st == "expired":
        return ("食品经营许可证已过期",
                f"「{shop_name}」的食品经营许可证已于 {day} 过期。"
                f"目前仍可正常接单,但 {GRACE_DAYS} 天宽限期结束后将暂停营业,"
                f"需上传新证并经人工核验才能恢复。")
    if st == "overdue":
        return ("已暂停营业:食品经营许可证过期",
                f"「{shop_name}」的食品经营许可证 {day} 过期且已超过 "
                f"{GRACE_DAYS} 天宽限期,店铺已暂停接单。"
                f"上传新证后由平台人工核验恢复 —— 无证经营是违法的,"
                f"这一步我们不能替你跳过。")
    return None


def notify_key(expires_at: date, today: date | None = None) -> str | None:
    """本档提醒的去重键。写进 Merchant.license_notified,
    清扫任务每小时跑一次也只会就每一档各发一次。

    键里带上到期日:商家换了新证(到期日变了),旧的水位自然失效,
    新证到期时会重新走一遍完整的四档提醒。
    """
    st = stage(expires_at, today)
    if st in ("unknown", "ok"):
        return None
    return f"{expires_at.isoformat()}:{st}"


async def sweep_license_expiry(now_beijing) -> dict[str, int]:
    """每天 09:00 扫一遍到期证照:发提醒、宽限期满置 hold。

    ## 为什么固定 09:00 而不是随清扫循环每分钟跑

    这是一天一次的通知,不是实时业务。挑上午九点是因为**商家这时候在**
    (备午市),而不是凌晨三点手机震一下第二天就被划掉了。
    Redis 按日防重,多副本部署也只发一次。

    ## 为什么去重要两层

    Redis 那层保证"今天这个任务只跑一次"(多副本/重启);
    Merchant.license_notified 那层保证"每一档只发一次"(30/7/1/expired
    各一条,而不是从第 30 天起每天发一条)。少了任何一层都会轰炸商家。
    """
    from sqlalchemy import select

    from ..db import SessionLocal
    from ..models import Merchant, MerchantStatus
    from ..redis_client import get_redis
    from .auto_flow import _in_window
    from .push import push_to_user

    if not _in_window("09:00", now_beijing, window_seconds=300):
        return {}
    redis = get_redis()
    if not await redis.set(f"license_expiry:{now_beijing.date()}", 1,
                           ex=86400, nx=True):
        return {}

    today = now_beijing.date()
    notified = held = 0
    async with SessionLocal() as db:
        # 只捞"到期日在 30 天内或已过期"的,不全表扫
        rows = (await db.scalars(
            select(Merchant).where(
                Merchant.license_expires_at.is_not(None),
                Merchant.license_expires_at <= today + timedelta(days=30),
                Merchant.status == MerchantStatus.approved,
            ))).all()
        for shop in rows:
            key = notify_key(shop.license_expires_at, today)
            if key is None:
                continue
            st = stage(shop.license_expires_at, today)

            # 宽限期满:与食安停业同一个闸门,商家自己开不回来。
            # **先置 hold 再发通知** —— 反过来的话通知说"已暂停营业"
            # 而实际还在接单,商家看到的和事实对不上
            if st == "overdue" and not shop.food_safety_hold:
                shop.food_safety_hold = True
                shop.hold_reason = "license_expired"
                shop.is_open = False
                held += 1

            if key in (shop.license_notified or []):
                continue
            text = notice(shop.name, shop.license_expires_at, today)
            if text is None:
                continue
            title, content = text
            await push_to_user(shop.owner_id, title, content,
                               extras={"type": "license_expiry"},
                               record_skip=True)
            # 列表整个换掉而不是 append:JSONB 的原地 mutate SQLAlchemy 看不见
            shop.license_notified = list(shop.license_notified or []) + [key]
            notified += 1
        await db.commit()
    return {"notified": notified, "held": held}
