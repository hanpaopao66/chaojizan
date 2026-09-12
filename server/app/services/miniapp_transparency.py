"""透明中心「小程序」栏(#334):全部从 mini_app_decisions 等表**投影**,不另记一份数。

公开:已认证开发者数、在线应用数(应用/游戏)、本期提交/通过/驳回数、审核时长中位数、
下架记录(日期、应用名、原因类别、是否申诉及结果)、精选名单及每次变动的理由、排序规则。

**不公开**:个人开发者的真实姓名、举报人身份、内部审核备注(note_internal 根本不读)。
"""
from datetime import datetime, timedelta
from statistics import median

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import (Developer, MiniApp, MiniAppCuration, MiniAppDecision, MiniAppVersion)
from .miniapp_platform import REASON_CODES, now, today_bj

#: 原因代码的大类(公示按类别,不按单条代码 —— 类别已经足够说明是哪一类问题)
REASON_CATEGORY = {"1": "功能与描述", "2": "内容", "3": "隐私", "4": "资质", "5": "安全",
                   "6": "知识产权", "7": "其他"}


def reason_category(code: str) -> str:
    return REASON_CATEGORY.get(code[1:2], "其他") if code else ""


async def review_stats(db: AsyncSession, *, since: datetime) -> dict:
    subs = list((await db.execute(select(MiniAppDecision.target_id, MiniAppDecision.created_at)
                                  .where(MiniAppDecision.action == "submit",
                                         MiniAppDecision.created_at >= since))).all())
    results = list((await db.execute(select(MiniAppDecision).where(
        MiniAppDecision.action.in_(("approve", "reject")),
        MiniAppDecision.created_at >= since))).scalars())
    # 审核时长:同一个版本「最后一次提交」到「结论」
    submitted = {}
    for vid, at in (await db.execute(select(MiniAppDecision.target_id, MiniAppDecision.created_at)
                                     .where(MiniAppDecision.action == "submit")
                                     .order_by(MiniAppDecision.id))).all():
        submitted[vid] = at
    hours = [round((d.created_at - submitted[d.target_id]).total_seconds() / 3600, 2)
             for d in results if d.target_id in submitted
             and d.created_at >= submitted[d.target_id]]
    return {
        "since": since.isoformat(),
        "submitted": len(subs),
        "approved": sum(1 for d in results if d.action == "approve"),
        "rejected": sum(1 for d in results if d.action == "reject"),
        "median_review_hours": median(hours) if hours else None,
        "reject_by_category": _count_by(
            [reason_category(d.reason_code) for d in results if d.action == "reject"]),
    }


def _count_by(items: list[str]) -> dict:
    out: dict[str, int] = {}
    for x in items:
        out[x] = out.get(x, 0) + 1
    return out


async def public_section(db: AsyncSession) -> dict:
    month_start = today_bj().replace(day=1)
    since = datetime.combine(month_start, datetime.min.time()).replace(
        tzinfo=now().tzinfo) - timedelta(hours=8)
    verified = await db.scalar(select(func.count()).select_from(Developer).where(
        Developer.status == "verified"))
    online = dict((await db.execute(select(MiniApp.kind, func.count()).where(
        MiniApp.status == "online").group_by(MiniApp.kind))).all())

    # 下架记录:平台作出的暂停、移除、紧急隔离(开发者自己下架不算处罚,不列)
    punish = list((await db.execute(select(MiniAppDecision).where(
        MiniAppDecision.action.in_(("suspend", "remove", "quarantine")))
        .order_by(MiniAppDecision.id.desc()).limit(100))).scalars())
    names = {}
    if punish:
        names = dict((await db.execute(select(MiniApp.id, MiniApp.name).where(
            MiniApp.id.in_({d.app_id for d in punish if d.app_id})))).all())
    appeals = {}
    results = {}
    if punish:
        for a in (await db.execute(select(MiniAppDecision).where(
                MiniAppDecision.action == "appeal",
                MiniAppDecision.appeal_of.in_([d.id for d in punish])))).scalars():
            appeals[a.appeal_of] = a.id
        if appeals:
            for r in (await db.execute(select(MiniAppDecision).where(
                    MiniAppDecision.action.in_(("appeal_upheld", "appeal_overturned")),
                    MiniAppDecision.appeal_of.in_(list(appeals.values()))))).scalars():
                results[r.appeal_of] = r.action
    takedowns = []
    for d in punish:
        a_id = appeals.get(d.id)
        takedowns.append({
            "date": (d.created_at + timedelta(hours=8)).date().isoformat(),
            "app_name": names.get(d.app_id, ""),
            "action": {"suspend": "暂停", "remove": "移除", "quarantine": "紧急隔离"}[d.action],
            "reason_category": reason_category(d.reason_code),
            "reason_code": d.reason_code,
            "reason_label": REASON_CODES.get(d.reason_code, ""),
            "appealed": a_id is not None,
            "appeal_result": {"appeal_upheld": "维持", "appeal_overturned": "撤销"}.get(
                results.get(a_id), "处理中" if a_id else None),
        })

    curation = [{"name": a.name, "appid": a.appid, "position": c.position, "reason": c.reason}
                for c, a in (await db.execute(select(MiniAppCuration, MiniApp).join(
                    MiniApp, MiniApp.id == MiniAppCuration.app_id)
                    .order_by(MiniAppCuration.position))).all()]
    changes = list((await db.execute(select(MiniAppDecision).where(
        MiniAppDecision.action.in_(("curate", "uncurate")))
        .order_by(MiniAppDecision.id.desc()).limit(50))).scalars())
    cnames = {}
    if changes:
        cnames = dict((await db.execute(select(MiniApp.id, MiniApp.name).where(
            MiniApp.id.in_({d.app_id for d in changes if d.app_id})))).all())

    reviewing = await db.scalar(select(func.count()).select_from(MiniAppVersion).where(
        MiniAppVersion.status == "reviewing"))
    return {
        "verified_developers": verified,
        "online_apps": {"app": online.get("app", 0), "game": online.get("game", 0)},
        "month": {**(await review_stats(db, since=since)), "label": month_start.strftime("%Y-%m")},
        "reviewing_now": reviewing,
        "takedowns": takedowns,
        "curation": curation,
        "curation_changes": [
            {"date": (d.created_at + timedelta(hours=8)).date().isoformat(),
             "app_name": cnames.get(d.app_id, ""),
             "action": "进入精选" if d.action == "curate" else "移出精选",
             "reason": d.note_public} for d in changes],
        "sort_rule": {
            "text": "精选位在前(人工,理由见上);其余按首次上架时间从新到旧,发新版本不会往前挪;"
                    "没有竞价、没有付费位置",
            "code": "server/app/services/miniapp_catalog.py",
        },
        "not_public": ["个人开发者的真实姓名", "举报人身份", "内部审核备注"],
    }
