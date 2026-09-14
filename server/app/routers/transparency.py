"""透明中心数据源(/transparency 页面,公开无鉴权)。

各组接口全部平台级聚合、无任何个人/单店信息:
  /audit          每日核账运行记录 + 连续无差错天数(账本的守夜人,公开值守)
  /funds          佣金收入 vs 支出去向(与公开账本同一套 ledger 口径)
  /compensation   平台"赔钱记录":安抚券(停发之前的)/超时致歉/餐损赔付/退款/保障金池——主动亮赔付
  /reports        月度财报(收入侧自动聚合,口径与 scripts/finance_report.py 一致)
  /fairness       分账公平证据:真实佣金率/每100元去向/骑手收入/评价不删
  /changelog      最近更新(GitHub 同源)+ 线上运行版本——代码即承诺
  /dispatch       派单算法:完整公式、每个权重的取值与理由、承诺不做的事
  /liability      判责与分摊:一单出问题钱怎么分、平台承担哪些、三方怎么申诉
  /credit         顾客信用分:公式、权重、时间窗、谁能看到、不能用来做什么、怎么申诉
  /uptime         90 天可用率(auto_flow 自记探针,缺档按不可用计,只低不虚高)
  /community      社区:视频审核量与时长、处置记录(不带人)、推荐公式、管理员查看私聊次数(S8)

缓存与限流复用大屏(routers/screen.py)的进程内小缓存 + 按 IP 限流。
每个数字都要经得起复算:口径写在字段名和注释里,前端原样展示口径说明。
"""
import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
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


def clean_streak_days(runs: list[dict]) -> int:
    """从最近一天往回数,连续多少天核账零差错。runs 按 day 倒序。

    **必须判日期连不连续。** 以前这里只遍历"已存在的行"、只在 problems > 0
    时 break,缺失的天直接跨过去接着数 —— 而自检挂掉的那天恰恰**不写行**
    (services/auto_flow.maybe_run_daily_audit:防重键先占后跑,炸了就没有
    这一天的记录)。于是"那天没跑成"和"那天零差错"在公示上完全一样,
    连续天数照涨。

    这个平台把账目透明当立身之本,公示一个虚高的无差错天数,
    性质和普通 bug 不一样:它是拿**没结论**冒充**没问题**。
    """
    from datetime import date as _date

    streak, prev_day = 0, None
    for r in runs:
        day = _date.fromisoformat(r["day"])
        if prev_day is not None and (prev_day - day).days != 1:
            break  # 中间断档:那些天没有结论,连续性到此为止
        if r["problems"] > 0:
            break
        streak += 1
        prev_day = day
    return streak


def missing_run_days(runs: list[dict], today) -> list[str]:
    """有记录的最早一天到昨天之间,自检没留下结论的日子。

    今天不算:定时任务北京时间 04:00 才跑,今天的行本来就可能还没写 ——
    把它算成缺失会天天误报,而误报久了就没人看这个数了。
    """
    from datetime import date as _date

    if not runs:
        return []
    have = {r["day"] for r in runs}
    missing, cursor = [], _date.fromisoformat(runs[-1]["day"])
    while cursor < today:
        if cursor.isoformat() not in have:
            missing.append(cursor.isoformat())
        cursor += timedelta(days=1)
    return missing


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
    # 连续无差错天数 + 缺失天数都是纯函数,单元测试直接盯(tests/unit)
    missing = missing_run_days(runs, datetime.now(SH).date())
    data = {
        "runs": runs,
        "clean_streak_days": clean_streak_days(runs),
        "window_days": 30,  # 每次核对近 30 天全部账目
        "latest": runs[0] if runs else None,
        # 有记录的最早一天到昨天之间,自检没跑成/没留下结论的日子
        "missing_days": len(missing),
        "missing_recent": missing[-10:],
        "last_run_day": runs[0]["day"] if runs else None,
    }
    _cache_put("tp:audit", data, 300)
    return data


# ---------- 今日逐单(透明中心首屏) ----------

_CH_LABEL = {
    "food": "点外卖", "retail": "买菜买水果", "errand_send": "帮我送",
    "errand_buy": "帮我买", "voucher": "团购核销", "stay": "住宿离店",
}
_TODAY_SH = ("date_trunc('day', now() AT TIME ZONE 'Asia/Shanghai')"
             " AT TIME ZONE 'Asia/Shanghai'")


def split_order_row(r: dict) -> dict:
    """一笔外卖/零售/跑腿单按**支付时的口径**拆成商家 / 骑手 / 平台三份。

    三份加起来**恒等于用户实付** —— 平台补贴(首单立减)算平台自己掏的钱,
    所以平台那一份是「佣金 − 补贴」,可以是负数(平台倒贴)。
    骑手那一份用「实付 − 商家 − 平台」求出来,而不是另拼一遍配送费 + 小费 ——
    上门费、夜间费这些都在 delivery_fee 里,另拼一遍迟早漏一项,
    而求差保证这一行永远对得上。

    - 跑腿单没有商家(那个服务主体不入账,见 settlement.credit_merchant_for_order);
    - 到店自取没有骑手;
    - 商家自送,配送费归商家。

    和结算(services/settlement)是同一个分法,只是提前到支付那一刻看:
    在途的单还没入账,但它**会**这么分。(等餐补偿 2026-09-14 起停发;之前那几单是平台另付给
    骑手的钱,不是用户付的,这里本来就不含。)
    """
    paid = r["total_cents"]
    platform = r["commission_cents"] - r["subsidy_cents"]
    if r["order_kind"] in ("errand_send", "errand_buy"):
        merchant = 0
    else:
        merchant = max(r["food_cents"] + r["packing_fee_cents"]
                       - r["discount_cents"], 0) - r["commission_cents"]
        if r["self_delivery"]:
            # 自送单的配送费(和小费)归商家;骑手那份是 0
            merchant = paid - platform
    rider = 0 if (r["pickup"] or r["self_delivery"]) else paid - merchant - platform
    if r["pickup"] and not r["self_delivery"]:
        merchant = paid - platform
    return {"paid": paid, "merchant": merchant, "rider": rider,
            "platform": platform}


async def _today_rows(db: AsyncSession) -> list[dict]:
    """今天(北京时间)的全部成交,逐笔。三张表:外卖/零售/跑腿按下单时刻、
    团购按核销时刻、住宿按离店时刻 —— 各自是「钱在这一刻被分掉」的时刻,
    和公开账本(services/ledger.build_day_payload)取的是同一组时间列。

    **单号只给指纹**:sha256(单号) 前 24 位,和公开账本同一个算法 ——
    知道自己单号的人能在这里、也能在明天的账本锚点里认出自己那一单,
    别人反推不出单号。零个人信息,也不带店名和地址。
    """
    from ..services.ledger import hash_no

    rows = []
    for r in (await db.execute(sa_text(f"""
        SELECT o.order_no, o.created_at, m.biz_type, o.order_kind,
               o.total_cents, o.food_cents, o.packing_fee_cents,
               o.discount_cents, o.subsidy_cents, o.commission_cents,
               coalesce(o.self_delivery, false), coalesce(o.pickup, false)
        FROM orders o JOIN merchants m ON m.id = o.merchant_id
        WHERE o.created_at >= {_TODAY_SH}
          AND o.status NOT IN ('pending_payment', 'cancelled')
    """))).all():
        kind = r[3] if r[3] in ("errand_send", "errand_buy") else (
            "retail" if r[2] == "retail" else "food")
        split = split_order_row({
            "total_cents": r[4], "food_cents": r[5], "packing_fee_cents": r[6],
            "discount_cents": r[7], "subsidy_cents": r[8],
            "commission_cents": r[9], "self_delivery": r[10], "pickup": r[11],
            "order_kind": r[3],
        })
        rows.append({"at": r[1], "ch": kind, "hash": hash_no(r[0]), **split})
    for r in (await db.execute(sa_text(f"""
        SELECT purchase_no, redeemed_at, sell_price_cents, commission_cents,
               net_cents
        FROM voucher_purchases
        WHERE status = 'redeemed' AND redeemed_at >= {_TODAY_SH}
    """))).all():
        rows.append({"at": r[1], "ch": "voucher", "hash": hash_no(r[0]),
                     "paid": r[2], "merchant": r[4], "rider": 0,
                     "platform": r[3]})
    for r in (await db.execute(sa_text(f"""
        SELECT order_no, completed_at, total_cents, fee_cents, net_cents
        FROM stay_orders
        WHERE status = 'completed' AND completed_at >= {_TODAY_SH}
    """))).all():
        rows.append({"at": r[1], "ch": "stay", "hash": hash_no(r[0]),
                     "paid": r[2], "merchant": r[4], "rider": 0,
                     "platform": r[3]})
    rows.sort(key=lambda x: x["at"], reverse=True)
    return rows


def _today_totals(rows: list[dict]) -> dict:
    return {k: sum(r[k] for r in rows)
            for k in ("paid", "merchant", "rider", "platform")}


@router.get("/today")
async def today_public(request: Request, db: AsyncSession = Depends(get_db)):
    """今日逐单:每一笔的钱分给了谁。公开,不需要登录。

    列表只回最近 200 笔(页面放不下更多);**合计按今天全部**算,
    全量逐笔走 /transparency/today.csv。
    """
    await _guard(request)
    if (hit := _cache_get("tp:today")) is not None:
        return hit
    rows = await _today_rows(db)
    data = {
        "day": datetime.now(SH).date().isoformat(),
        "count": len(rows),
        "totals": _today_totals(rows),
        "items": [{
            "t": r["at"].astimezone(SH).strftime("%H:%M"),
            "ch": r["ch"], "label": _CH_LABEL[r["ch"]],
            # 页面上只放前 6 位;CSV 里是完整的 24 位,能和账本锚点对上
            "id": r["hash"][:6],
            "paid": r["paid"], "merchant": r["merchant"],
            "rider": r["rider"], "platform": r["platform"],
        } for r in rows[:200]],
    }
    _cache_put("tp:today", data, 30)
    return data


@router.get("/today.csv")
async def today_csv(request: Request, db: AsyncSession = Depends(get_db)):
    """今日逐单全量 CSV。谁都能下,不需要登录。"""
    from fastapi.responses import Response

    await _guard(request)
    rows = await _today_rows(db)
    day = datetime.now(SH).date().isoformat()

    def y(c: int) -> str:
        return f"{c / 100:.2f}"

    lines = ["时间,频道,单号指纹(sha256 前 24 位),用户付,商家,骑手,平台"]
    for r in rows[:5000]:
        lines.append(",".join([
            r["at"].astimezone(SH).strftime("%H:%M:%S"), _CH_LABEL[r["ch"]],
            r["hash"], y(r["paid"]), y(r["merchant"]), y(r["rider"]),
            y(r["platform"])]))
    t = _today_totals(rows)
    lines.append(",".join(["合计", f"{len(rows)} 笔", "", y(t["paid"]),
                           y(t["merchant"]), y(t["rider"]), y(t["platform"])]))
    # BOM:Excel 双击打开不乱码
    body = "﻿" + "\n".join(lines) + "\n"
    return Response(
        body, media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition":
                 f'attachment; filename="chaojizan-{day}.csv"'})


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
    # 平台补贴:首单立减(现在是 0)+ 停发之前发出去的安抚券被抵扣,同走订单 subsidy 审计通道
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
    # 骑手保障金池:按公开账本算的计提、支出(判骑手责任时垫商家那份餐钱)、回池(申诉改判)、余额。
    # 池子是从佣金里计提的专项钱,单列一栏 —— 支出一笔一笔都在公开账本的 rider_fund.rows 里
    from ..services.rider_fault import fund_balance
    fund = await fund_balance(db)
    # 骑手责任申诉改判成立时退回骑手的钱(fault_refund):那一单的错判由平台认。
    # **算进申诉改判那一项,不单列成 spend 的新一项** —— 已经发版的 App 在客户端按
    # 「补贴 + 餐损 + 改判 == 支出合计」把这组数再核一遍(user_app transparency_page),
    # spend 里多一项它就报「收支明细与合计对不上」。明细放在 spend_detail 里另给
    fault_back = await db.scalar(sa_text(
        "SELECT coalesce(sum(amount_cents), 0) FROM rider_earnings "
        "WHERE kind = 'fault_refund'"))
    adjustments += fault_back
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
        # 上面几项里的「其中」,不另算进合计
        "spend_detail": {"rider_fault_refund_cents": fault_back},
        "rider_fund": fund,
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
    """赔付记录(本月/累计):超时安抚券(停发之前的)和停发之后的超时致歉次数、
    餐损赔付、退款,以及判骑手责任时保障金池垫的、骑手另出的商家那份餐钱。

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
        # 送达超时 15 分钟自动发的安抚券 —— 2026-09-14 起停发(平台不出这笔钱),
        # 这里只剩停发之前发出去的;已经发出去、没用的照旧能用(services/eta.py)
        "eta_coupons": await _pair("""
            SELECT count(*), coalesce(sum(amount_cents), 0) FROM coupons
            WHERE source LIKE 'eta:%' AND funder = 'platform'
        """),
        # 停发之后:送达超时 15 分钟以上只推一条致歉,一分钱不出。只有笔数
        "eta_apologies": await _pair("""
            SELECT count(*), 0 FROM order_events
            WHERE to_status = 'eta_late_apology'
        """),
        # 无骑手接单取消:已出餐商家按应收全额赔付,佣金不收
        "meal_compensation": await _pair("""
            SELECT count(*), coalesce(sum(net_cents), 0) FROM merchant_earnings
            WHERE note LIKE '无骑手接单取消,平台赔付餐损%'
        """),
        # 渠道确认成功的退款(缺货部分退/整单退/售后退)。
        # 不带 biz_type 过滤 —— 外卖/团购券/住宿三条线的退款都算数,
        # 公示的是"平台一共退回去多少钱",按业务线切分是另一回事
        "refunds": await _pair("""
            SELECT count(*), coalesce(sum(amount_cents), 0) FROM refunds
            WHERE status = 'success'
        """),
        # 判骑手责任时,商家那份餐钱:保障金池出的(payout),和池子不够、骑手另出的
        # (fault_charge,记正数)。平台自己这一单一分不出(services/rider_fault)
        "rider_fund_payouts": await _pair("""
            SELECT count(*), coalesce(sum(amount_cents), 0) FROM rider_fund_movements
            WHERE kind = 'payout'
        """),
        "rider_fault_charges": await _pair("""
            SELECT count(*), coalesce(-sum(amount_cents), 0) FROM rider_earnings
            WHERE kind = 'fault_charge'
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
    # 跑腿服务主体(biz_type='errand')是平台给跑腿单建的占位,不是商家,不进档位
    tiers = [{"rate": float(r[0]), "merchants": r[1]}
             for r in (await db.execute(sa_text("""
        SELECT commission_rate, count(*) FROM merchants
        WHERE status = 'approved' AND biz_type <> 'errand' GROUP BY 1 ORDER BY 1
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

    # 4) 评价的可见性。
    #
    # **必须把隐藏数一起报出来。** 这里原本只 `count(*)`,不带 hidden 过滤 ——
    # 而店铺页是 `WHERE hidden IS FALSE`。于是「删了一成」和「一条没删」
    # 在这份公示上长得一模一样:证据按不可能证伪的方式算,那就不是证据。
    #
    # 和 clean_streak_days 那次是同一个形状(「自检没跑成」和「零差错」
    # 在公示上分不出来),那次的结论是:拿没结论冒充没问题,
    # 性质和普通 bug 不一样。
    #
    # 隐藏只有一条路径:商家就某条差评申诉、平台复核认定成立。
    # 平台自己不删任何评价,刷评嫌疑也只标记不隐藏。
    # 而且作者会被通知、可以再申诉,恢复了就重新计入评分。
    reviews = (await db.execute(sa_text("""
        SELECT count(*),
               count(*) FILTER (WHERE merchant_rating <= 2),
               count(*) FILTER (WHERE flagged AND NOT hidden),
               count(*) FILTER (WHERE hidden),
               count(*) FILTER (WHERE hidden AND merchant_rating <= 2)
        FROM reviews
    """))).one()

    # 住宿真实费率(近 30 天离店结算口径):承诺 5%,离店才收,取消/未入住分文不收
    stay_row = (await db.execute(sa_text("""
        SELECT coalesce(sum(fee_cents), 0), coalesce(sum(total_cents), 0)
        FROM stay_orders WHERE status = 'completed' AND completed_at >= :s
    """), {"s": since})).one()
    stay_real = (stay_row[0] / stay_row[1]) if stay_row[1] else None

    data = {
        "commission": {
            "real_rate_30d": round(real_rate, 4) if real_rate is not None else None,
            "promised_cap": 0.05,
            "tiers": tiers,
        },
        # 三场景费率一句话:外卖 5% 封顶 / 团购核销 2% / 住宿 5% 离店才收
        "stay_commission": {
            "real_rate_30d": round(stay_real, 4) if stay_real is not None else None,
            "promised_cap": 0.05,
            "note": "离店才计佣;取消/拒单/未入住,平台分文不取",
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
            # 隐藏的数字**主动亮出来**,不藏在总数里
            "hidden": reviews[3],
            "hidden_bad": reviews[4],
            "hidden_ratio": (round(reviews[3] / reviews[0], 4)
                             if reviews[0] else None),
            "visible": reviews[0] - reviews[3],
            "hidden_rule": "平台自己不删任何评价;刷评嫌疑只标记不隐藏。"
                           "唯一会被隐藏的情况是:商家就某条评价提出申诉、"
                           "平台复核认定成立。",
            "hidden_recourse": "评价被隐藏时作者会收到通知,并且可以在 72 小时内"
                               "申诉;复核改判则恢复显示、重新计入评分。",
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
    "miniapp_hosted": "托管小程序",
    "miniapp_catalog": "小程序目录(第三方应用)",
    "miniapp_profile": "小程序读取昵称头像",
}


@router.get("/dispatch")
async def dispatch_spec():
    """派单算法公开(#141)。

    为什么要公开:**派单算法对骑手的意义,等同于账目对商家的意义** ——
    它决定骑手今天挣多少。资本平台的算法是黑箱,骑手只能猜"为什么好单不给我"。

    这里返回的权重**从 services/dispatch.py 的常量直接读**,不另抄一份 ——
    抄的那份迟早和真实算法对不上,那时公开的就是假的,比不公开更坏。
    有测试钉着这件事(tests/unit/test_dispatch.py)。
    """
    from ..services import dispatch as d

    return d.public_spec()


@router.get("/liability")
async def liability_spec():
    """订单出问题时钱怎么分(公开无鉴权)。

    为什么要公开:**这是三方都会被它扣钱的规则**。用户想取消、商家做了餐、
    骑手跑了路,一单出岔子,总有人要承担 —— 那这个"谁承担"的口径就不能
    只存在客服的话术里。资本平台的做法是规则写在几十页协议里、实际由客服
    临场判,同一种情况两个人问出两个答案。

    这里返回的每个数字**从 services/liability.py 的常量直接读**,不另抄一份;
    连"平台承担的那部分为什么不算补贴"这种解释也放在代码里,
    改代码就等于改公示。有测试钉着(tests/unit/test_liability.py)。

    三方都能对判责结果申诉,窗口和处理方式一并公开。
    """
    from ..services import liability as lb

    return lb.public_spec()


@router.get("/credit")
async def credit_spec(role: str = "customer"):
    """信用分怎么算(公开无鉴权):公式、每项权重、看多少天、谁能看到、
    不能用来做什么、怎么申诉。`role` 是 customer(默认)/ merchant / rider ——
    三种角色同一套机制,只有「什么算扣分」「什么不扣分」「谁看得到」按角色不同。

    每个数字**从 services/credit.py 的常量直接读**,不另抄一份 ——
    本人明细页、规则页、算分用的都是那几个常量(tests/unit/test_credit.py 钉着)。
    """
    from ..services import credit

    if role not in credit.ROLES:
        raise HTTPException(422, "role 只能是 customer / merchant / rider")
    return credit.public_spec(role)


@router.get("/queue")
async def queue_spec(db: AsyncSession = Depends(get_db)):
    """到店排队的规则与现状(公开无鉴权)。

    为什么要公开:排队分配的是**稀缺且没法补发的东西** —— 一个晚上的位子。
    分错了不像退款那样能补回来,所以规则必须摆在明处,而且要能被对着查。

    最要紧的一句是「买券不能插队」。调研同类产品时看到的乱象正是这个:
    有商家引导办卡免排队,等于把先到者的等待卖了一次。我们把「做不到」
    写进代码(services/queue.py 里没有任何往前挪位置的路径),
    再把「怎么自己查」写进这里。

    三项现状指标是行业通用的那三个:取号数、平均等位、过号率 ——
    **只给聚合数,绝无个案**。
    """
    if (hit := _cache_get("tp:queue")) is not None:
        return hit
    from ..services import queue as q

    spec = q.public_spec()
    # **比例的分母只算已经走完的号。** 还在排队的那些结局未定,
    # 把它们算进分母,过号率会被稀释得越接近饭点越好看 —— 那不叫公示。
    row = (await db.execute(sa_text("""
        SELECT count(*) AS taken,
               count(*) FILTER (WHERE status NOT IN
                     ('waiting', 'called', 'pending_restore')) AS finished,
               count(*) FILTER (WHERE status = 'waiting'
                     OR status = 'called'
                     OR status = 'pending_restore') AS still_live,
               count(*) FILTER (WHERE status = 'seated') AS seated,
               count(*) FILTER (WHERE status = 'cancelled') AS gave_up,
               count(*) FILTER (WHERE status = 'expired') AS never_seated,
               count(*) FILTER (WHERE passed_count > 0) AS passed,
               round(avg(extract(epoch FROM (seated_at - created_at)) / 60.0)
                     FILTER (WHERE seated_at IS NOT NULL)::numeric, 1) AS avg_wait
        FROM queue_tickets
        WHERE created_at >= now() - interval '30 days'
    """))).first()
    taken = int(row.taken or 0)
    finished = int(row.finished or 0)
    spec["current"] = {
        "days": 30,
        "taken": taken,
        "still_waiting": int(row.still_live or 0),
        "finished": finished,
        "seated": int(row.seated or 0),
        "gave_up": int(row.gave_up or 0),
        # 排到打烊也没坐上。**这个数单列出来** —— 它和「自己不等了」
        # 是两回事:前者是放号放多了,后者是客人改主意
        "never_seated": int(row.never_seated or 0),
        "passed": int(row.passed or 0),
        # 过号率:行业里 20% 是该去看看店里发生了什么的线
        "pass_ratio": round((row.passed or 0) / finished, 3) if finished else 0.0,
        "seated_ratio": round((row.seated or 0) / finished, 3) if finished else 0.0,
        "avg_wait_minutes": float(row.avg_wait or 0),
        "note": ("取号数 / 平均等位 / 过号率 —— 这三项是行业通用口径。"
                 "过号率偏高通常不是用户的问题,是叫号节奏或放号上限没配对。"
                 "**比例的分母只算已经走完的号**(还在排的结局未定,"
                 "算进去会让饭点的数字凭空好看)。"),
    }
    _cache_put("tp:queue", spec, 600)
    return spec


@router.get("/kitchen-cam")
async def kitchen_cam_spec(db: AsyncSession = Depends(get_db)):
    """明厨亮灶的规则与现状(#155-#157,公开)。

    为什么要公开:平台在列表页给商家标「有明厨亮灶」,用户据此下单 ——
    那这个标识是**怎么发的、怎么验的、什么情况下会撤**,用户有权知道。

    行业里「标着明厨亮灶却黑屏、镜头对着天花板」的乱象,根子就在于
    标识只是个开关、发了没人管。我们把校验规则摆出来,是为了让人能对着查。

    数值全部从 services/kitchen_cam.py 的常量读,**不另抄一份**。
    """
    from ..services import kitchen_cam as kc

    spec = kc.public_spec()
    # 带上真实的接入现状 —— 只给计数,绝无个案
    counts = dict((await db.execute(sa_text("""
        SELECT kitchen_cam_status, count(*) FROM merchants
        WHERE status = 'approved' AND biz_type <> 'errand' GROUP BY 1
    """))).all())
    spec["current"] = {
        "active": counts.get("active", 0),
        "degraded": counts.get("degraded", 0),
        "pending": counts.get("pending", 0),
        "none": counts.get("none", 0),
        "note": "degraded 是装了但当前连不上的 —— 这些店在列表页显示的是"
                "「无明厨亮灶」。我们把这个数也公开,是因为藏起来就等于"
                "默认可以挂着不管",
    }
    spec["changelog"] = kc.CHANGELOG
    return spec


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


@router.get("/miniapps")
async def miniapps_public(request: Request, db: AsyncSession = Depends(get_db)):
    """小程序栏(#334):开发者与应用数、审核统计、下架记录、精选及变动理由、排序规则。

    全部从审核记录投影(services/miniapp_transparency.py);个人开发者真名、
    举报人身份、内部审核备注一概不读。
    """
    await _guard(request)
    if (hit := _cache_get("tp:miniapps")) is not None:
        return hit
    from ..services.miniapp_transparency import public_section

    data = await public_section(db)
    _cache_put("tp:miniapps", data, 300)
    return data


@router.get("/community")
async def community_public(request: Request, db: AsyncSession = Depends(get_db)):
    """社区栏(#371):视频审核量 / 驳回率 / 审核中位时长(近 30 天 + 按月)、处置记录
    (对象类型 + 原因代码 + 申诉结果)、推荐与热门的公式原文、管理员查看私聊的次数(按月,S8)。

    **不含任何个人信息、会话名、消息内容**:处罚说明、内部备注、被处罚的是谁、谁处理的一概不读
    (services/community_stats.py);e2e 把手机号、用户名、会话标题、消息正文喂进去再扫这份响应。
    """
    await _guard(request)
    if (hit := _cache_get("tp:community")) is not None:
        return hit
    from ..services.community_stats import public_section as community_section

    data = await community_section(db)
    _cache_put("tp:community", data, 300)
    return data
