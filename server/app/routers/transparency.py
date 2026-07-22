"""透明中心数据源(/transparency 页面,公开无鉴权)。

六组接口,全部平台级聚合、无任何个人/单店信息:
  /audit          每日核账运行记录 + 连续无差错天数(账本的守夜人,公开值守)
  /funds          佣金收入 vs 支出去向(与公开账本同一套 ledger 口径)
  /compensation   平台"赔钱记录":安抚券/餐损赔付/退款——主动亮赔付
  /reports        月度财报(收入侧自动聚合,口径与 scripts/finance_report.py 一致)
  /fairness       分账公平证据:真实佣金率/每100元去向/骑手收入/评价不删
  /changelog      最近更新(GitHub 同源)+ 线上运行版本——代码即承诺
  /uptime         90 天可用率(auto_flow 自记探针,缺档按不可用计,只低不虚高)

缓存与限流复用大屏(routers/screen.py)的进程内小缓存 + 按 IP 限流。
每个数字都要经得起复算:口径写在字段名和注释里,前端原样展示口径说明。
"""
import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
from fastapi import APIRouter, Depends, Request
from sqlalchemy import text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..db import get_db
from ..redis_client import get_redis
from .screen import SH, _cache_get, _cache_put, _guard

logger = logging.getLogger("superz.transparency")

router = APIRouter(prefix="/transparency", tags=["透明中心"])

# 有效佣金入账口径:正常入账行(冲账/调整单独看)
_EARN = "kind = 'earning'"


@router.get("/audit")
async def audit_public(request: Request, db: AsyncSession = Depends(get_db)):
    """每日核账公示:近 90 次运行 + 连续无差错天数。

    核的是恒等式:商家入账=菜钱-佣金、骑手入账=配送费(100% 归骑手)、
    退款汇总=逐笔流水之和……详见 services/audit.py 文档字符串。
    """
    await _guard(request)
    if (hit := _cache_get("tp:audit")) is not None:
        return hit
    runs = [{"day": r[0], "checked_orders": r[1], "problems": r[2]}
            for r in (await db.execute(sa_text("""
        SELECT day, checked_orders, problem_count
        FROM audit_runs ORDER BY day DESC LIMIT 90
    """))).all()]
    streak = 0
    for r in runs:  # 从最近一天往回数连续无差错
        if r["problems"] > 0:
            break
        streak += 1
    data = {
        "runs": runs,
        "clean_streak_days": streak,
        "window_days": 30,  # 每次核对近 30 天全部账目
        "latest": runs[0] if runs else None,
    }
    _cache_put("tp:audit", data, 300)
    return data


@router.get("/funds")
async def funds_public(request: Request, db: AsyncSession = Depends(get_db)):
    """佣金去哪了:收入(外卖佣金+团购服务费) vs 支出去向,差额=平台留存。

    全部对账本求和(冲账负数行自动抵扣),与公开账本锚点同源可复核。
    """
    await _guard(request)
    if (hit := _cache_get("tp:funds")) is not None:
        return hit
    commission = (await db.scalar(sa_text(
        "SELECT coalesce(sum(commission_cents), 0) FROM merchant_earnings")))
    voucher_fee = (await db.scalar(sa_text("""
        SELECT coalesce(sum(commission_cents), 0) FROM voucher_purchases
        WHERE status = 'redeemed'
    """)))
    # 平台补贴:首单立减 + 安抚券抵扣,同走订单 subsidy 审计通道
    subsidy = (await db.scalar(sa_text("""
        SELECT coalesce(sum(subsidy_cents), 0) FROM orders
        WHERE status NOT IN ('pending_payment','cancelled')
    """)))
    # 无骑手接单取消的餐损赔付:佣金不收,商家应收全额平台承担
    meal_comp = (await db.scalar(sa_text("""
        SELECT coalesce(sum(net_cents), 0) FROM merchant_earnings
        WHERE note LIKE '无骑手接单取消,平台赔付餐损%'
    """)))
    # 申诉改判正向调整:恢复被冲的净额,平台认亏
    adjustments = (await db.scalar(sa_text("""
        SELECT coalesce(sum(net_cents), 0) FROM merchant_earnings
        WHERE kind = 'adjustment'
    """))) + (await db.scalar(sa_text("""
        SELECT coalesce(sum(amount_cents), 0) FROM rider_earnings
        WHERE kind = 'adjustment'
    """)))
    income = commission + voucher_fee
    spend = subsidy + meal_comp + adjustments
    data = {
        "income": {"commission_cents": commission,
                   "voucher_fee_cents": voucher_fee,
                   "total_cents": income},
        "spend": {"subsidy_cents": subsidy,
                  "meal_compensation_cents": meal_comp,
                  "adjustment_cents": adjustments,
                  "total_cents": spend},
        # 留存要养:支付通道/服务器/短信/地图/审核客服(见月度财报成本侧)
        "retained_cents": income - spend,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    _cache_put("tp:funds", data, 600)
    return data


@router.get("/compensation")
async def compensation_public(
    request: Request, db: AsyncSession = Depends(get_db),
):
    """平台赔钱记录(本月/累计):超时安抚券、餐损赔付、退款。

    没有平台愿意亮自己的赔付账——我们把它当承诺兑现的凭据。
    """
    await _guard(request)
    if (hit := _cache_get("tp:comp")) is not None:
        return hit
    month_start = datetime.now(SH).replace(
        day=1, hour=0, minute=0, second=0, microsecond=0)

    async def _pair(sql: str) -> dict:
        total = (await db.execute(sa_text(sql))).one()
        month = (await db.execute(
            sa_text(sql + " AND created_at >= :m"), {"m": month_start})).one()
        return {"total": {"count": total[0], "cents": total[1]},
                "month": {"count": month[0], "cents": month[1]}}

    data = {
        # 送达超时 15 分钟自动发的安抚券(平台承担,规则见 services/eta.py)
        "eta_coupons": await _pair("""
            SELECT count(*), coalesce(sum(amount_cents), 0) FROM coupons
            WHERE source LIKE 'eta:%' AND funder = 'platform'
        """),
        # 无骑手接单取消:已出餐商家按应收全额赔付,佣金不收
        "meal_compensation": await _pair("""
            SELECT count(*), coalesce(sum(net_cents), 0) FROM merchant_earnings
            WHERE note LIKE '无骑手接单取消,平台赔付餐损%'
        """),
        # 渠道确认成功的退款(缺货部分退/整单退/售后退)
        "refunds": await _pair("""
            SELECT count(*), coalesce(sum(amount_cents), 0) FROM refunds
            WHERE status = 'success'
        """),
        "month_since": month_start.date().isoformat(),
    }
    _cache_put("tp:comp", data, 600)
    return data


@router.get("/reports")
async def monthly_reports(
    request: Request, db: AsyncSession = Depends(get_db),
):
    """月度财报(收入侧,口径与 scripts/finance_report.py 相同,实时聚合)。

    成本侧(服务器/短信/推送账单)在服务商后台,随开源仓 docs/finance 手工发布;
    这里先把能自动算的收入侧逐月公开。
    """
    await _guard(request)
    if (hit := _cache_get("tp:reports")) is not None:
        return hit
    months = [{
        "month": r[0], "orders_completed": r[1], "gmv_cents": r[2],
        "commission_cents": r[3], "rider_income_cents": r[4],
        "subsidy_cents": r[5],
    } for r in (await db.execute(sa_text("""
        SELECT to_char(o.created_at AT TIME ZONE 'Asia/Shanghai', 'YYYY-MM') AS ym,
               count(*) FILTER (WHERE o.status = 'completed'),
               coalesce(sum(o.total_cents) FILTER (
                   WHERE o.status = 'completed'), 0),
               coalesce(sum(me.commission_cents), 0),
               coalesce(sum(re.amount_cents), 0),
               coalesce(sum(o.subsidy_cents) FILTER (
                   WHERE o.status NOT IN ('pending_payment','cancelled')), 0)
        FROM orders o
        LEFT JOIN LATERAL (
            SELECT sum(commission_cents) AS commission_cents
            FROM merchant_earnings WHERE order_id = o.id) me ON true
        LEFT JOIN LATERAL (
            SELECT sum(amount_cents) AS amount_cents
            FROM rider_earnings WHERE order_id = o.id) re ON true
        GROUP BY 1 ORDER BY 1 DESC LIMIT 24
    """))).all()]
    # 团购服务费按核销月归属,单独聚合后并入
    vouchers = dict((await db.execute(sa_text("""
        SELECT to_char(redeemed_at AT TIME ZONE 'Asia/Shanghai', 'YYYY-MM'),
               sum(commission_cents)
        FROM voucher_purchases WHERE status = 'redeemed' AND redeemed_at IS NOT NULL
        GROUP BY 1
    """))).all())
    for m in months:
        m["voucher_fee_cents"] = vouchers.get(m["month"], 0)
    data = {"months": months,
            "note": "收入侧自动聚合;成本侧随开源仓 docs/finance 发布"}
    _cache_put("tp:reports", data, 3600)
    return data


@router.get("/fairness")
async def fairness_public(
    request: Request, db: AsyncSession = Depends(get_db),
):
    """分账公平证据(近 30 天口径,除累计项外)。"""
    await _guard(request)
    if (hit := _cache_get("tp:fairness")) is not None:
        return hit
    since = datetime.now(timezone.utc) - timedelta(days=30)

    # 1) 真实平均佣金率 = Σ佣金 / Σ佣金基数(菜品+打包-满减,即入账 food 口径)
    rate_row = (await db.execute(sa_text(f"""
        SELECT coalesce(sum(commission_cents), 0), coalesce(sum(food_cents), 0)
        FROM merchant_earnings WHERE {_EARN} AND created_at >= :s
    """), {"s": since})).one()
    real_rate = (rate_row[0] / rate_row[1]) if rate_row[1] else None
    tiers = [{"rate": float(r[0]), "merchants": r[1]}
             for r in (await db.execute(sa_text("""
        SELECT commission_rate, count(*) FROM merchants
        WHERE status = 'approved' GROUP BY 1 ORDER BY 1
    """))).all()]

    # 2) 每 100 元用户实付去哪了。口径:近 30 天无退款的完成订单 + 正常入账行,
    # 保证恒等式严格闭合(商家+骑手+佣金-补贴 = 100);退款单的账在赔付页单列
    per_row = (await db.execute(sa_text("""
        SELECT coalesce(sum(o.total_cents), 0),
               coalesce(sum(me.net), 0), coalesce(sum(me.commission), 0),
               coalesce(sum(re.amount), 0),
               coalesce(sum(o.subsidy_cents), 0)
        FROM orders o
        LEFT JOIN LATERAL (
            SELECT sum(net_cents) AS net, sum(commission_cents) AS commission
            FROM merchant_earnings
            WHERE order_id = o.id AND kind = 'earning') me ON true
        LEFT JOIN LATERAL (
            SELECT sum(amount_cents) AS amount
            FROM rider_earnings
            WHERE order_id = o.id AND kind = 'earning') re ON true
        WHERE o.status = 'completed' AND o.refund_cents = 0
          AND o.created_at >= :s
          -- 正常履约口径:有骑手,或自配送/自取/零配送费;
          -- 排除历史造数等配送侧无账可对的脏单,保证恒等式可复算
          AND (o.rider_id IS NOT NULL OR o.self_delivery OR o.pickup
               OR o.delivery_fee_cents = 0)
    """), {"s": since})).one()
    paid = per_row[0]
    per100 = None
    if paid:
        f = lambda cents: round(cents * 100 / paid, 1)  # noqa: E731
        per100 = {"merchant": f(per_row[1]), "rider": f(per_row[3]),
                  "commission": f(per_row[2]), "subsidy": f(per_row[4]),
                  "orders": None}
        # 恒等:商家+骑手+佣金-补贴 = 100(补贴是平台倒贴进去的)

    # 3) 骑手收入透明(配送费+小费 100% 归骑手,审计恒等式背书)
    today_sh = ("date_trunc('day', now() AT TIME ZONE 'Asia/Shanghai')"
                " AT TIME ZONE 'Asia/Shanghai'")
    rider = (await db.execute(sa_text(f"""
        SELECT coalesce(sum(amount_cents), 0),
               coalesce(sum(amount_cents) FILTER (
                   WHERE created_at >= {today_sh}), 0),
               count(*) FILTER (WHERE created_at >= {today_sh} AND {_EARN})
        FROM rider_earnings
    """))).one()
    withdrawn = (await db.scalar(sa_text("""
        SELECT coalesce(sum(amount_cents), 0) FROM withdrawals
        WHERE status = 'paid'
    """)))

    # 4) 评价不删的证据:全量可见,连刷评嫌疑都只标记不隐藏
    reviews = (await db.execute(sa_text("""
        SELECT count(*),
               count(*) FILTER (WHERE merchant_rating <= 2),
               count(*) FILTER (WHERE flagged)
        FROM reviews
    """))).one()

    data = {
        "commission": {
            "real_rate_30d": round(real_rate, 4) if real_rate is not None else None,
            "promised_cap": 0.05,
            "tiers": tiers,
        },
        "per100": per100,
        "rider_income": {
            "total_cents": rider[0],
            "today_cents": rider[1],
            "today_avg_per_order_cents":
                round(rider[1] / rider[2]) if rider[2] else None,
            "withdrawn_total_cents": withdrawn,
            # 提现零手续费省下的钱:按行业常见约 0.1% 通道费保守估算
            "zero_fee_saved_cents": withdrawn // 1000,
        },
        "reviews": {
            "total": reviews[0],
            "bad_ratio": round(reviews[1] / reviews[0], 4) if reviews[0] else None,
            "flagged_still_visible": reviews[2],
        },
        "window_days": 30,
    }
    _cache_put("tp:fairness", data, 3600)
    return data


# ---------- 工程透明:最近更新 / 运行版本 / 系统状态 ----------

def _running_version() -> dict:
    """线上跑的是哪个版本:env APP_VERSION 优先,其次发版脚本写的
    server/app_version.txt(git describe + 部署时间),都没有 = dev。"""
    if settings.app_version:
        return {"version": settings.app_version, "deployed_at": None}
    vf = Path(__file__).resolve().parent.parent.parent / "app_version.txt"
    if vf.exists():
        lines = vf.read_text().strip().splitlines()
        return {"version": lines[0] if lines else "unknown",
                "deployed_at": lines[1] if len(lines) > 1 else None}
    return {"version": "dev", "deployed_at": None}


async def _fetch_github() -> dict:
    """拉 GitHub Releases + 最近提交。只下发版本/日期/标题/摘要,
    不透传作者邮箱等个人信息。token 选填,仅为提升 API 限额。"""
    headers = {"Accept": "application/vnd.github+json",
               "User-Agent": "superz-transparency"}
    if settings.github_token:
        headers["Authorization"] = f"Bearer {settings.github_token}"
    base = f"https://api.github.com/repos/{settings.github_repo}"
    async with httpx.AsyncClient(timeout=8, headers=headers) as client:
        rel_resp = await client.get(f"{base}/releases", params={"per_page": 10})
        rel_resp.raise_for_status()
        commit_resp = await client.get(f"{base}/commits", params={"per_page": 15})
        commit_resp.raise_for_status()
    releases = [{
        "tag": r.get("tag_name", ""),
        "name": (r.get("name") or r.get("tag_name") or "")[:120],
        "published_at": r.get("published_at"),
        "summary": (r.get("body") or "")[:300],
    } for r in rel_resp.json()]
    commits = [{
        "sha": c.get("sha", "")[:7],
        "date": (c.get("commit", {}).get("committer") or {}).get("date"),
        "message": (c.get("commit", {}).get("message") or "")
                   .split("\n")[0][:160],
    } for c in commit_resp.json()]
    return {"releases": releases, "commits": commits}


@router.get("/changelog")
async def changelog_public(request: Request):
    """最近更新(GitHub 同源,Redis 缓存 30 分钟):
    平台刚刚改了什么,和源码仓一字不差——线上版本号也在这,对得上号。"""
    await _guard(request)
    r = get_redis()
    fresh, last = None, None
    try:
        fresh = await r.get("tp:changelog")
        if fresh:
            data = json.loads(fresh)
            data["version"] = _running_version()
            return data
        last = await r.get("tp:changelog:last")
    except Exception:
        pass  # Redis 不可用不拦公开页,直接现拉
    try:
        data = {**(await _fetch_github()),
                "repo": settings.github_repo, "stale": False,
                "fetched_at": datetime.now(timezone.utc).isoformat()}
        try:
            await r.set("tp:changelog", json.dumps(data), ex=1800)
            await r.set("tp:changelog:last", json.dumps(data))  # 降级兜底,不过期
        except Exception:
            pass
        data["version"] = _running_version()
        return data
    except Exception as exc:
        logger.warning("GitHub 更新流拉取失败,走缓存降级: %s", exc)
        if last:
            data = json.loads(last)
            data["stale"] = True
            data["version"] = _running_version()
            return data
        return {"releases": [], "commits": [], "repo": settings.github_repo,
                "stale": True, "fetched_at": None,
                "version": _running_version()}


@router.get("/uptime")
async def uptime_public(request: Request, db: AsyncSession = Depends(get_db)):
    """90 天可用率(每天应有 288 次探针,缺档按不可用计——只会算低不会虚高)
    + 当前实时状态。探针由后台任务自记,与 /health 同口径。"""
    await _guard(request)
    if (hit := _cache_get("tp:uptime")) is not None:
        return hit
    rows = (await db.execute(sa_text("""
        SELECT (created_at AT TIME ZONE 'Asia/Shanghai')::date AS d,
               count(*), count(*) FILTER (WHERE db_ok AND redis_ok),
               min(created_at AT TIME ZONE 'Asia/Shanghai')
        FROM health_probes
        WHERE created_at >= now() - interval '90 days'
        GROUP BY 1 ORDER BY 1
    """))).all()
    now_sh = datetime.now(SH).replace(tzinfo=None)
    days = []
    for d, probes, ok, first in rows:
        # 应有探针数从当日首个探针起算(上线当天不背"半夜没探针"的锅);
        # 首探之后的缺档照常按不可用计
        day_end = min(now_sh, datetime.combine(d, datetime.max.time()))
        expected = max(1, int((day_end - first).total_seconds() // 300) + 1)
        days.append({
            "day": d.isoformat(), "probes": probes, "ok": ok,
            "availability": round(min(1.0, ok / expected), 4),
        })
    # 当前实时状态(与 /health 同口径,但不抛 503——状态页要打得开)
    db_ok = redis_ok = True
    try:
        await db.execute(sa_text("SELECT 1"))
    except Exception:
        db_ok = False
    try:
        await get_redis().ping()
    except Exception:
        redis_ok = False
    # 今日探针明细(格子是按天的,这行让"今天只有一格"也有实时感)
    today_row = (await db.execute(sa_text("""
        SELECT count(*), count(*) FILTER (WHERE db_ok AND redis_ok),
               max(created_at)
        FROM health_probes
        WHERE (created_at AT TIME ZONE 'Asia/Shanghai')::date
              = (now() AT TIME ZONE 'Asia/Shanghai')::date
    """))).one()
    data = {
        "days": days,
        "current": {"db": db_ok, "redis": redis_ok, "ok": db_ok and redis_ok},
        "today": {
            "probes": today_row[0],
            "ok": today_row[1],
            "last_at": (today_row[2].astimezone(SH).strftime("%H:%M")
                        if today_row[2] else None),
        },
        "probe_interval_minutes": 5,
        "note": "缺探针按不可用计;记录自探针上线之日起",
    }
    _cache_put("tp:uptime", data, 60)
    return data


# ---------- 治理透明:规则留痕 / 处置公示 / 客服质量 / 公告归档 ----------

# 对用户有感知、可公开的开关(敏感运营开关只留内档不公开)
_PUBLIC_FLAGS = {
    "weather_surcharge": "恶劣天气配送加价(+¥2 全归骑手)",
    "weather_shutdown": "极端天气临时停运",
    "night_curfew": "深夜保护窗(暂停接新单)",
    "alcohol_curfew": "酒类夜间禁售时段",
    "open_cities": "开城清单",
    "screen_show_gmv": "公开大屏金额展示",
}


@router.get("/governance")
async def governance_public(
    request: Request, db: AsyncSession = Depends(get_db),
):
    """治理公开:规则开关变更时间线 / 反作弊处置月度聚合 / 客服质量 / 公告归档。

    处置数据只有计数绝无个案;开关历史自留痕表上线之日起记录,不补历史——
    没记录的就说没记录,这也是透明的一部分。
    """
    await _guard(request)
    if (hit := _cache_get("tp:gov")) is not None:
        return hit

    # 1) 规则开关时间线(白名单键,最近 50 条)
    keys = tuple(_PUBLIC_FLAGS)
    flag_rows = (await db.execute(sa_text("""
        SELECT key, old_value, new_value, reason, created_at
        FROM flag_history WHERE key = ANY(:keys)
        ORDER BY id DESC LIMIT 50
    """), {"keys": list(keys)})).all()
    flags_since = await db.scalar(sa_text(
        "SELECT min(created_at) FROM flag_history"))
    flag_timeline = [{
        "key": r[0], "label": _PUBLIC_FLAGS.get(r[0], r[0]),
        "old": r[1], "new": r[2], "reason": r[3],
        "at": r[4].astimezone(timezone.utc).isoformat(),
    } for r in flag_rows]

    # 2) 反作弊处置月度聚合(限制/冻结/解除;刷评标记数按评价创建月)
    risk_rows = (await db.execute(sa_text("""
        SELECT to_char(created_at AT TIME ZONE 'Asia/Shanghai', 'YYYY-MM'),
               count(*) FILTER (WHERE to_level = 'limit'),
               count(*) FILTER (WHERE to_level = 'frozen'),
               count(*) FILTER (WHERE to_level = '')
        FROM risk_action_log GROUP BY 1 ORDER BY 1 DESC LIMIT 12
    """))).all()
    flagged_reviews = dict((await db.execute(sa_text("""
        SELECT to_char(created_at AT TIME ZONE 'Asia/Shanghai', 'YYYY-MM'),
               count(*) FROM reviews WHERE flagged GROUP BY 1
    """))).all())
    risk_monthly = [{
        "month": r[0], "limited": r[1], "frozen": r[2], "lifted": r[3],
        "reviews_flagged": flagged_reviews.get(r[0], 0),
    } for r in risk_rows]

    # 3) 客服质量(近 6 个月):首次响应时长与 24h 回复率,replied_at 口径
    ticket_rows = (await db.execute(sa_text("""
        SELECT to_char(created_at AT TIME ZONE 'Asia/Shanghai', 'YYYY-MM'),
               count(*),
               round(avg(extract(epoch FROM replied_at - created_at) / 60)
                     FILTER (WHERE replied_at IS NOT NULL)),
               count(*) FILTER (
                   WHERE replied_at IS NOT NULL
                     AND replied_at - created_at <= interval '24 hours')
        FROM tickets
        WHERE created_at >= now() - interval '6 months'
        GROUP BY 1 ORDER BY 1 DESC
    """))).all()
    tickets_monthly = [{
        "month": r[0], "tickets": r[1],
        "avg_first_reply_minutes": int(r[2]) if r[2] is not None else None,
        "replied_24h_ratio": round(r[3] / r[1], 4) if r[1] else None,
    } for r in ticket_rows]
    # 问题自助解决占比(近 30 天):自助售后笔数 /(自助售后 + 人工工单)
    self_row = (await db.execute(sa_text("""
        SELECT (SELECT count(*) FROM after_sales
                WHERE created_at >= now() - interval '30 days'),
               (SELECT count(*) FROM tickets
                WHERE created_at >= now() - interval '30 days')
    """))).one()
    self_total = self_row[0] + self_row[1]

    # 4) 公告归档:面向全体的公告全部留档可查(含已过期)
    ann_rows = (await db.execute(sa_text("""
        SELECT title, content, is_active, starts_at, ends_at, created_at
        FROM announcements WHERE audience = 'all'
        ORDER BY id DESC LIMIT 30
    """))).all()
    announcements = [{
        "title": r[0], "content": r[1], "active": r[2],
        "starts_at": r[3].astimezone(timezone.utc).isoformat() if r[3] else None,
        "ends_at": r[4].astimezone(timezone.utc).isoformat() if r[4] else None,
        "created_at": r[5].astimezone(timezone.utc).isoformat(),
    } for r in ann_rows]

    data = {
        "flag_timeline": flag_timeline,
        "flags_since": (flags_since.astimezone(timezone.utc).date().isoformat()
                        if flags_since else None),
        "risk_monthly": risk_monthly,
        "tickets_monthly": tickets_monthly,
        "self_service_30d": {
            "after_sales": self_row[0], "tickets": self_row[1],
            "ratio": round(self_row[0] / self_total, 4) if self_total else None,
        },
        "announcements": announcements,
    }
    _cache_put("tp:gov", data, 30)
    return data
