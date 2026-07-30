"""平台运营基建:公告(发通知不用发版)+ 自建埋点。

埋点原则:只收登录用户的产品行为(浏览/搜索/分享),不收设备指纹;
服务端已有的交易数据不重复埋。收集范围写入隐私政策(legal.dart 第一.7 条)。
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func as sa_func
from sqlalchemy import or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..models import (Announcement, AppEvent, PlatformCopy, PlatformFaq,
                      SplashConfig, User)
from ..schemas import (
    AnnouncementIn,
    AnnouncementOut,
    AnnouncementPatch,
    EventsIn,
    SplashIn,
    SplashOut,
)
from ..security import get_current_user, require_role

router = APIRouter(tags=["平台"])


# ---------- 开屏运营位 ----------
@router.get("/splash")
async def active_splash(
    app: str = "user",
    db: AsyncSession = Depends(get_db),
):
    """当前生效的开屏运营位(端定向+时间窗,最新一条)。

    客户端拉到后缓存本地供下次启动展示(永不阻塞冷启动);
    返回 null = 没配置,客户端回落品牌开屏。自营内容,不是广告位。
    """
    now = datetime.now(timezone.utc)
    row = await db.scalar(
        select(SplashConfig)
        .where(
            SplashConfig.is_active.is_(True),
            SplashConfig.audience.in_([app, "all"]),
            or_(SplashConfig.starts_at.is_(None), SplashConfig.starts_at <= now),
            or_(SplashConfig.ends_at.is_(None), SplashConfig.ends_at >= now),
        )
        .order_by(SplashConfig.id.desc())
        .limit(1)
    )
    if row is None:
        return None
    return SplashOut.model_validate(row)


@router.post("/admin/splash", response_model=SplashOut)
async def create_splash(
    payload: SplashIn,
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    cfg = SplashConfig(**payload.model_dump())
    db.add(cfg)
    await db.commit()
    await db.refresh(cfg)
    return cfg


@router.get("/admin/splash", response_model=list[SplashOut])
async def list_splash(
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    rows = await db.scalars(
        select(SplashConfig).order_by(SplashConfig.id.desc()).limit(50))
    return list(rows)


@router.post("/admin/splash/{cfg_id}/toggle", response_model=SplashOut)
async def toggle_splash(
    cfg_id: int,
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    from fastapi import HTTPException

    cfg = await db.get(SplashConfig, cfg_id)
    if cfg is None:
        raise HTTPException(404, "配置不存在")
    cfg.is_active = not cfg.is_active
    await db.commit()
    await db.refresh(cfg)
    return cfg


# ---------- 公告 ----------
@router.get("/announcements", response_model=list[AnnouncementOut])
async def active_announcements(
    audience: str = "user",
    db: AsyncSession = Depends(get_db),
):
    """当前生效的公告(端定向 + 时间窗)。客户端启动/回前台拉取。"""
    now = datetime.now(timezone.utc)
    rows = await db.scalars(
        select(Announcement)
        .where(
            Announcement.is_active.is_(True),
            Announcement.audience.in_([audience, "all"]),
            or_(Announcement.starts_at.is_(None), Announcement.starts_at <= now),
            or_(Announcement.ends_at.is_(None), Announcement.ends_at >= now),
        )
        .order_by(Announcement.created_at.desc())
        .limit(3)
    )
    return list(rows)


@router.post("/admin/announcements", response_model=AnnouncementOut)
async def create_announcement(
    payload: AnnouncementIn,
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    ann = Announcement(**payload.model_dump())
    db.add(ann)
    await db.commit()
    await db.refresh(ann)
    return ann


@router.get("/admin/announcements", response_model=list[AnnouncementOut])
async def list_announcements(
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    rows = await db.scalars(
        select(Announcement).order_by(Announcement.created_at.desc()).limit(50))
    return list(rows)


@router.patch("/admin/announcements/{ann_id}", response_model=AnnouncementOut)
async def update_announcement(
    ann_id: int,
    payload: AnnouncementPatch,
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    from fastapi import HTTPException

    ann = await db.get(Announcement, ann_id)
    if ann is None:
        raise HTTPException(404, "公告不存在")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(ann, field, value)
    await db.commit()
    await db.refresh(ann)
    return ann


# ---------- 埋点 ----------
@router.post("/events/batch")
async def track_events(
    payload: EventsIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """批量上报(客户端攒够一批或退后台时发)。失败客户端直接丢弃,埋点不影响体验。"""
    for e in payload.events[:50]:
        db.add(AppEvent(user_id=user.id, role=user.role.value,
                        event=e.name[:50], props=e.props))
    await db.commit()
    return {"accepted": min(len(payload.events), 50)}


# ---------- 推送运营 ----------
@router.post("/admin/push/recall")
async def push_recall(
    payload: dict | None = None,
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """流失召回:最后一单在 [min_days, max_days] 天前的用户,推一条召回。

    人工触发而非定时任务——推送轰炸是黑心平台的做法,这里每次召回
    都由运营决策并留痕(push_logs)。dry_run(默认)只看人数不发送。
    """
    p = payload or {}
    min_days = int(p.get("min_days", 7))
    max_days = int(p.get("max_days", 30))
    dry_run = bool(p.get("dry_run", True))
    if not (0 < min_days < max_days <= 365):
        from fastapi import HTTPException

        raise HTTPException(422, "需满足 0 < min_days < max_days <= 365")

    rows = await db.execute(text("""
        SELECT o.customer_id
        FROM orders o
        JOIN users u ON u.id = o.customer_id
        WHERE u.role = 'customer'
        GROUP BY o.customer_id
        HAVING max(o.created_at) BETWEEN
              now() - make_interval(days => :max_days)
          AND now() - make_interval(days => :min_days)
    """), {"min_days": min_days, "max_days": max_days})
    user_ids = [r[0] for r in rows]
    pushed = 0
    if not dry_run:
        from ..services.push import push_to_user

        for uid in user_ids:
            if await push_to_user(
                    uid, "好久不见",
                    "附近的店最近上了新的团购券和限时折扣,回来看看?",
                    {"type": "recall"}, record_skip=True):
                pushed += 1
    return {"candidates": len(user_ids), "pushed": pushed, "dry_run": dry_run}


@router.get("/admin/push-logs")
async def push_logs(
    user_id: int | None = None,
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """推送流水(排查"没收到提醒"+ 验证触达链路)。最近 50 条。"""
    from ..models import PushLog

    q = select(PushLog).order_by(PushLog.id.desc()).limit(50)
    if user_id is not None:
        q = q.where(PushLog.user_id == user_id)
    rows = await db.scalars(q)
    return [{"id": r.id, "user_id": r.user_id, "title": r.title,
             "content": r.content, "ok": r.ok, "error": r.error,
             "created_at": r.created_at} for r in rows]


@router.get("/admin/events/summary")
async def events_summary(
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """近 7 天事件计数 + 独立用户数(产品决策的最小数据面)。"""
    rows = await db.execute(text("""
        SELECT event, count(*) AS n, count(DISTINCT user_id) AS users
        FROM app_events
        WHERE created_at >= now() - interval '7 days'
        GROUP BY event ORDER BY n DESC LIMIT 30
    """))
    _ = sa_func  # 保留引用
    return {"events": [
        {"event": r[0], "count": r[1], "users": r[2]} for r in rows]}


# 承诺类文案的 key 前缀:这些由服务端按真实费率算出来,后台改不了(#122)。
# 一旦承诺变成后台可填的自由文本,任何人都能把它改成「3% 封顶」而实际照抽 5%,
# 承诺就退化成广告词了 —— 整个透明叙事的地基就在这几句话上。
PLEDGE_PREFIX = "pledge."


def _pledge_copy() -> dict[str, str]:
    """按平台真实费率配置生成承诺文案。数字全部来自 settings,不手写。"""
    from ..config import settings

    tiers = settings.commission_tiers or [[0, "0.050"]]
    cap = max(float(rate) for _, rate in tiers)      # 承诺的是上限
    best = min(float(rate) for _, rate in tiers)     # 阶梯能降到的最低档

    def pct(x: float) -> str:
        v = x * 100
        return f"{v:.0f}%" if v == int(v) else f"{v:.1f}%"

    copy = {
        "pledge.commission": f"商家总负担 {pct(cap)} 封顶,配送费 100% 归骑手",
        "pledge.commission_short": f"{pct(cap)} 封顶",
        "pledge.rider": "配送费和小费 100% 归骑手,平台分文不取",
        "pledge.no_ranking": "不做竞价排名,钱买不到靠前的位置",
    }
    if best < cap:
        copy["pledge.tiers"] = (
            f"单量上去自动降档,最低 {pct(best)},降了不再上调")
    return copy


@router.get("/config")
async def public_config(db: AsyncSession = Depends(get_db)):
    """客户端启动配置(公开):开关 + 可下发文案 + 帮助中心问答(#122)。

    copy 只是"覆盖",不是"来源" —— 客户端必须自带一份完整的本地默认值,
    首次启动、断网、这个接口挂了,用户看到的仍应是完整内容而不是空白。

    rev 是内容版本号(内容哈希),客户端可据此跳过无变化时的重建。
    """
    import hashlib
    import json

    from ..services.flags import marketing_on

    rows = (await db.scalars(select(PlatformCopy))).all()
    copy = {r.key: r.text for r in rows if not r.key.startswith(PLEDGE_PREFIX)}
    copy.update(_pledge_copy())  # 承诺类永远以服务端计算值为准,覆盖任何存量脏数据

    faqs = (await db.scalars(
        select(PlatformFaq)
        .where(PlatformFaq.is_active.is_(True))
        .order_by(PlatformFaq.sort_order, PlatformFaq.id))).all()

    payload = {
        "marketing": await marketing_on(db),
        "copy": copy,
        "faq": [{"audience": f.audience, "q": f.question, "a": f.answer}
                for f in faqs],
    }
    payload["rev"] = hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()[:12]
    return payload


# ---------- 文案下发的后台维护 ----------
@router.get("/admin/copy")
async def list_copy(
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """后台看全部文案:承诺类也列出来(标 locked),但改不了。"""
    rows = (await db.scalars(select(PlatformCopy).order_by(PlatformCopy.key))).all()
    out = [{"key": r.key, "text": r.text, "locked": False,
            "updated_at": r.updated_at} for r in rows
           if not r.key.startswith(PLEDGE_PREFIX)]
    out += [{"key": k, "text": v, "locked": True, "updated_at": None}
            for k, v in sorted(_pledge_copy().items())]
    return out


@router.put("/admin/copy/{key}")
async def upsert_copy(
    key: str,
    payload: dict,
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """新增/修改一条文案。承诺类 key 一律拒绝,并说明原因。"""
    if key.startswith(PLEDGE_PREFIX):
        raise HTTPException(
            422, "承诺类文案由服务端按真实费率生成,不能手工改 —— "
                 "改费率请改平台配置,文案会自动跟着变")
    text_value = str(payload.get("text", "")).strip()
    if not text_value:
        raise HTTPException(422, "文案不能为空")
    if len(text_value) > 1000:
        raise HTTPException(422, "文案最长 1000 字")
    row = await db.scalar(select(PlatformCopy).where(PlatformCopy.key == key))
    if row is None:
        row = PlatformCopy(key=key[:60], text=text_value)
        db.add(row)
    else:
        row.text = text_value
    await db.commit()
    return {"key": key, "text": text_value}


@router.delete("/admin/copy/{key}")
async def delete_copy(
    key: str,
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """删掉一条下发文案 = 回退到客户端的本地默认值(不是变空白)。"""
    if key.startswith(PLEDGE_PREFIX):
        raise HTTPException(422, "承诺类文案不由后台维护,无从删起")
    row = await db.scalar(select(PlatformCopy).where(PlatformCopy.key == key))
    if row is None:
        raise HTTPException(404, "没有这条文案")
    await db.delete(row)
    await db.commit()
    return {"deleted": key}


@router.put("/admin/faq")
async def replace_faq(
    payload: dict,
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """整表替换帮助中心问答(全量提交,顺序即数组顺序)。

    整表替换而不是逐条增删:FAQ 是一篇要通读的东西,顺序和上下文比单条重要,
    逐条改很容易改出前后矛盾。
    """
    items = payload.get("items")
    if not isinstance(items, list):
        raise HTTPException(422, "items 必须是数组")
    if len(items) > 50:
        raise HTTPException(422, "帮助中心最多 50 条,再多用户读不完")
    rows = []
    for i, it in enumerate(items):
        q = str(it.get("q", "")).strip()
        a = str(it.get("a", "")).strip()
        if not q or not a:
            raise HTTPException(422, f"第 {i + 1} 条的问题或答案是空的")
        rows.append(PlatformFaq(
            audience=str(it.get("audience", "user"))[:12],
            question=q[:120], answer=a[:1000], sort_order=i, is_active=True))
    await db.execute(text("DELETE FROM platform_faq"))
    for r in rows:
        db.add(r)
    await db.commit()
    return {"count": len(rows)}
