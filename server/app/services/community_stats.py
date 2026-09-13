"""社区的数:后台「数据」页(#370)和透明中心「社区」栏(#371)。

两边用同一套 SQL 口径,只是透明中心**只出聚合数和不带人的处置记录**:
- 不读 note / note_internal / appeal_text(可能写着人名、群名、消息原文);
- 不读被处罚的是谁(target_id)、哪个会话(chat_id)、谁处理的(admin_id);
- 管理员查看私聊只出按月的次数。
tests/e2e_social_moderation.py 把手机号、用户名、会话标题、消息正文喂进去再扫响应,一个都不许出现。

时间一律按北京时间分天、分月。审核时长 = 结论时间 − 这次结论对应的那次提交(video_decisions.submitted_at,
0130 之前的结论没有这一列,不参与计算 —— 没有数据就说没有,不编)。
"""
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from . import sanctions
from .video import REASON_CODES

_BJ = timezone(timedelta(hours=8))
REVIEW_ACTIONS = ("approve", "reject", "approve_changes", "reject_changes")
#: 透明中心列多少条处置记录
RECORDS_MAX = 100
MONTHS = 12
RANK_SOURCE = "server/app/services/video_rank.py"

#: 透明中心处置记录**只有**这几个字段(文档 COMMUNITY-GOVERNANCE.md §7 同一张表,单测对着比)
RECORD_KEYS = ("date", "target_type", "action", "action_label", "reason_code", "reason_label",
               "duration", "appeal", "appeal_label", "revoked")

#: 透明中心不公开的东西(页面原样列出来,和小程序栏同一个写法)
NOT_PUBLIC = ["被处罚的是谁(账号、昵称、用户名、手机号)", "会话名称和成员", "消息、评论、弹幕的内容",
              "举报人是谁", "处罚说明和内部备注", "处理人是谁"]


def today_bj() -> date:
    return datetime.now(_BJ).date()


def bj_midnight(d: date) -> datetime:
    return datetime(d.year, d.month, d.day, tzinfo=_BJ)


def _rate(num: int, den: int) -> float | None:
    return round(num / den, 4) if den else None


def _hours(v) -> float | None:
    return round(float(v), 2) if v is not None else None


# ---------------- 后台「数据」 ----------------

async def daily(db: AsyncSession, days: int) -> dict:
    """近 N 天每天:消息数、活跃会话数、投稿量、审核结论数、审核中位时长、举报量、处置量。"""
    days = max(1, min(int(days), 90))
    first = today_bj() - timedelta(days=days - 1)
    since = bj_midnight(first)
    p = {"since": since}
    day = "(created_at AT TIME ZONE 'Asia/Shanghai')::date"

    msgs = {r[0]: (int(r[1]), int(r[2])) for r in (await db.execute(text(f"""
        SELECT {day}, count(*), count(DISTINCT chat_id) FROM chat_messages
         WHERE created_at >= :since AND kind <> 'service' GROUP BY 1"""), p)).all()}
    subs = {r[0]: int(r[1]) for r in (await db.execute(text("""
        SELECT (submitted_at AT TIME ZONE 'Asia/Shanghai')::date, count(*) FROM videos
         WHERE submitted_at >= :since GROUP BY 1"""), p)).all()}
    reviews = {r[0]: (int(r[1]), _hours(r[2])) for r in (await db.execute(text(f"""
        SELECT {day}, count(*),
               percentile_cont(0.5) WITHIN GROUP (
                   ORDER BY extract(epoch FROM created_at - submitted_at) / 3600.0)
                   FILTER (WHERE submitted_at IS NOT NULL AND submitted_at <= created_at)
          FROM video_decisions
         WHERE created_at >= :since AND action = ANY(:acts) GROUP BY 1"""),
        {**p, "acts": list(REVIEW_ACTIONS)})).all()}
    reports = {r[0]: int(r[1]) for r in (await db.execute(text(f"""
        SELECT d, sum(n) FROM (
            SELECT {day} AS d, count(*) AS n FROM chat_reports WHERE created_at >= :since GROUP BY 1
            UNION ALL
            SELECT {day} AS d, count(*) AS n FROM video_reports WHERE created_at >= :since GROUP BY 1
        ) x GROUP BY d"""), p)).all()}
    punish = {r[0]: int(r[1]) for r in (await db.execute(text(f"""
        SELECT d, sum(n) FROM (
            SELECT {day} AS d, count(*) AS n FROM social_sanctions
             WHERE created_at >= :since GROUP BY 1
            UNION ALL
            SELECT {day} AS d, count(*) AS n FROM video_decisions
             WHERE created_at >= :since AND action = 'remove' GROUP BY 1
        ) x GROUP BY d"""), p)).all()}
    items = []
    for i in range(days):
        d = first + timedelta(days=i)
        m, c = msgs.get(d, (0, 0))
        rv, med = reviews.get(d, (0, None))
        items.append({"day": d.isoformat(), "messages": m, "active_chats": c,
                      "video_submissions": subs.get(d, 0), "review_decisions": rv,
                      "review_median_hours": med, "reports": reports.get(d, 0),
                      "sanctions": punish.get(d, 0)})
    tot = (await db.execute(text("""
        SELECT (SELECT count(DISTINCT chat_id) FROM chat_messages
                 WHERE created_at >= :since AND kind <> 'service'),
               (SELECT percentile_cont(0.5) WITHIN GROUP (
                        ORDER BY extract(epoch FROM created_at - submitted_at) / 3600.0)
                  FROM video_decisions
                 WHERE created_at >= :since AND action = ANY(:acts)
                   AND submitted_at IS NOT NULL AND submitted_at <= created_at)"""),
        {**p, "acts": list(REVIEW_ACTIONS)})).one()
    open_ = (await db.execute(text("""
        SELECT (SELECT count(*) FROM chat_reports WHERE status IN ('open', 'escalated')),
               (SELECT count(*) FROM video_reports WHERE status IN ('open', 'escalated')),
               (SELECT count(*) FROM social_sanctions WHERE appeal_status = 'open'),
               (SELECT count(*) FROM videos WHERE status = 'reviewing' AND deleted_at IS NULL)
    """))).one()
    return {
        "days": days, "since": first.isoformat(), "items": items,
        "totals": {"messages": sum(x["messages"] for x in items),
                   "active_chats": int(tot[0] or 0),
                   "video_submissions": sum(x["video_submissions"] for x in items),
                   "review_decisions": sum(x["review_decisions"] for x in items),
                   "review_median_hours": _hours(tot[1]),
                   "reports": sum(x["reports"] for x in items),
                   "sanctions": sum(x["sanctions"] for x in items)},
        "open": {"chat_reports": int(open_[0]), "video_reports": int(open_[1]),
                 "social_appeals": int(open_[2]), "review_queue": int(open_[3])},
        "notes": {"video_submissions": "按稿件最近一次提交审核的时间计;同一个稿件改了重交,只算最后那一次",
                  "review_median_hours": "提交到结论(含转码时间);统计从有提交时间记录的结论开始",
                  "sanctions": "对人和会话的处罚(删消息、禁言、封群、封号、警告)+ 视频下架"},
    }


# ---------------- 透明中心「社区」 ----------------

async def _review_block(db: AsyncSession, since: datetime) -> dict:
    row = (await db.execute(text("""
        SELECT count(*),
               count(*) FILTER (WHERE action IN ('approve', 'approve_changes')),
               count(*) FILTER (WHERE action IN ('reject', 'reject_changes')),
               percentile_cont(0.5) WITHIN GROUP (
                   ORDER BY extract(epoch FROM created_at - submitted_at) / 3600.0)
                   FILTER (WHERE submitted_at IS NOT NULL AND submitted_at <= created_at)
          FROM video_decisions WHERE created_at >= :since AND action = ANY(:acts)"""),
        {"since": since, "acts": list(REVIEW_ACTIONS)})).one()
    return {"reviewed": int(row[0]), "approved": int(row[1]), "rejected": int(row[2]),
            "reject_rate": _rate(int(row[2]), int(row[0])), "median_review_hours": _hours(row[3])}


async def public_section(db: AsyncSession) -> dict:
    now = datetime.now(timezone.utc)
    since30 = now - timedelta(days=30)
    month0 = today_bj().replace(day=1)
    for _ in range(MONTHS - 1):
        month0 = (month0 - timedelta(days=1)).replace(day=1)
    since_m = bj_midnight(month0)
    mon = "to_char(created_at AT TIME ZONE 'Asia/Shanghai', 'YYYY-MM')"

    # ---- 视频审核 ----
    review_monthly = [{
        "month": r[0], "reviewed": int(r[1]), "approved": int(r[2]), "rejected": int(r[3]),
        "reject_rate": _rate(int(r[3]), int(r[1])), "median_review_hours": _hours(r[4]),
    } for r in (await db.execute(text(f"""
        SELECT {mon}, count(*),
               count(*) FILTER (WHERE action IN ('approve', 'approve_changes')),
               count(*) FILTER (WHERE action IN ('reject', 'reject_changes')),
               percentile_cont(0.5) WITHIN GROUP (
                   ORDER BY extract(epoch FROM created_at - submitted_at) / 3600.0)
                   FILTER (WHERE submitted_at IS NOT NULL AND submitted_at <= created_at)
          FROM video_decisions WHERE created_at >= :since AND action = ANY(:acts)
         GROUP BY 1 ORDER BY 1 DESC"""), {"since": since_m, "acts": list(REVIEW_ACTIONS)})).all()]

    # ---- 处置:对人和会话的处罚 + 视频下架。只读类型、代码、时间、申诉结果 ----
    srows = (await db.execute(text("""
        SELECT target_type, action, reason_code, until, created_at, revoked_at, appeal_status
          FROM social_sanctions ORDER BY id DESC LIMIT :n"""), {"n": RECORDS_MAX})).all()
    vrows = (await db.execute(text("""
        SELECT d.id, d.reason_code, d.created_at,
               (SELECT r.action FROM video_decisions a JOIN video_decisions r ON r.appeal_of = a.id
                 WHERE a.appeal_of = d.id AND a.action = 'appeal'
                   AND r.action IN ('appeal_upheld', 'appeal_overturned')
                 ORDER BY r.id DESC LIMIT 1) AS result,
               EXISTS (SELECT 1 FROM video_decisions a
                        WHERE a.appeal_of = d.id AND a.action = 'appeal') AS appealed
          FROM video_decisions d WHERE d.action = 'remove'
         ORDER BY d.id DESC LIMIT :n"""), {"n": RECORDS_MAX})).all()
    records = []
    for r in srows:
        appeal = r.appeal_status or ""
        records.append({
            "date": r.created_at.astimezone(_BJ).date().isoformat(),
            "at": r.created_at, "target_type": r.target_type, "action": r.action,
            "action_label": sanctions.ACTION_LABELS.get(r.action, r.action),
            "reason_code": r.reason_code, "reason_label": REASON_CODES.get(r.reason_code, ""),
            "duration": sanctions.duration_of(r.action, r.until, r.created_at), "appeal": appeal,
            "appeal_label": sanctions.APPEAL_LABELS.get(appeal, ""),
            "revoked": r.revoked_at is not None})
    for r in vrows:
        appeal = ("overturned" if r.result == "appeal_overturned" else
                  "upheld" if r.result == "appeal_upheld" else "open" if r.appealed else "")
        records.append({
            "date": r.created_at.astimezone(_BJ).date().isoformat(),
            "at": r.created_at, "target_type": "video", "action": "remove_video",
            "action_label": "下架视频", "reason_code": r.reason_code,
            "reason_label": REASON_CODES.get(r.reason_code, ""), "duration": "",
            "appeal": appeal, "appeal_label": sanctions.APPEAL_LABELS.get(appeal, ""),
            "revoked": appeal == "overturned"})
    records.sort(key=lambda x: x["at"], reverse=True)
    # 只留白名单里的字段:以后有人往上面加了一列,也出不了这个门
    records = [{k: x[k] for k in RECORD_KEYS} for x in records[:RECORDS_MAX]]

    by_action = {r[0]: int(r[1]) for r in (await db.execute(text("""
        SELECT action, count(*) FROM social_sanctions WHERE created_at >= :since GROUP BY 1"""),
        {"since": since30})).all()}
    removed30 = int(await db.scalar(text(
        "SELECT count(*) FROM video_decisions WHERE action = 'remove' AND created_at >= :since"),
        {"since": since30}) or 0)
    sanction_monthly = {}
    for m, action, n in (await db.execute(text(f"""
        SELECT {mon}, action, count(*) FROM social_sanctions WHERE created_at >= :since
         GROUP BY 1, 2"""), {"since": since_m})).all():
        sanction_monthly.setdefault(m, {})[action] = int(n)
    for m, n in (await db.execute(text(f"""
        SELECT {mon}, count(*) FROM video_decisions
         WHERE action = 'remove' AND created_at >= :since GROUP BY 1"""),
        {"since": since_m})).all():
        sanction_monthly.setdefault(m, {})["remove_video"] = int(n)
    appeals30 = (await db.execute(text("""
        SELECT count(*) FILTER (WHERE appealed_at >= :since),
               count(*) FILTER (WHERE appeal_resolved_at >= :since AND appeal_status = 'upheld'),
               count(*) FILTER (WHERE appeal_resolved_at >= :since
                                  AND appeal_status = 'overturned'),
               count(*) FILTER (WHERE appeal_status = 'open')
          FROM social_sanctions"""), {"since": since30})).one()

    # ---- 管理员查看私聊(S8):只有按月的次数 ----
    views_monthly = [{"month": r[0], "views": int(r[1])} for r in (await db.execute(text(f"""
        SELECT {mon}, count(*) FROM admin_chat_views WHERE created_at >= :since
         GROUP BY 1 ORDER BY 1 DESC"""), {"since": since_m})).all()]
    views30 = int(await db.scalar(text(
        "SELECT count(*) FROM admin_chat_views WHERE created_at >= :since"),
        {"since": since30}) or 0)
    views_total = int(await db.scalar(text("SELECT count(*) FROM admin_chat_views")) or 0)

    from . import video_rank as rank
    return {
        "window_days": 30,
        "video_review": {"last_30d": await _review_block(db, since30),
                         "monthly": review_monthly},
        "sanctions": {
            "last_30d": {"total": sum(by_action.values()) + removed30,
                         "by_action": [{"action": a, "label": sanctions.ACTION_LABELS[a],
                                        "count": by_action.get(a, 0)}
                                       for a in sanctions.ACTION_LABELS]
                         + [{"action": "remove_video", "label": "下架视频", "count": removed30}]},
            "monthly": [{"month": m, "total": sum(v.values()), "by_action": v}
                        for m, v in sorted(sanction_monthly.items(), reverse=True)],
            "records": records,
        },
        "appeals": {"last_30d": {"filed": int(appeals30[0]), "upheld": int(appeals30[1]),
                                 "overturned": int(appeals30[2])},
                    "open": int(appeals30[3]),
                    "rule": "每个处罚都能申诉一次,由另一名审核员复核;申诉成立即撤销处罚、解除限制"},
        "admin_chat_views": {
            "last_30d": views30, "total": views_total, "monthly": views_monthly,
            "rule": ("平台技术上能读到消息(服务端存储,不做端到端加密)。管理员只能在处理举报时查看"
                     "举报单里的那几条和前后各 5 条,不带举报单号的查看一律拒绝;每次查看都留痕,"
                     "次数按月公示在这里"),
        },
        "formula": {"text": rank.FORMULA, "source": RANK_SOURCE,
                    "source_url": f"https://github.com/{settings.github_repo}/blob/main/"
                                  f"{RANK_SOURCE}"},
        "not_public": NOT_PUBLIC,
    }
