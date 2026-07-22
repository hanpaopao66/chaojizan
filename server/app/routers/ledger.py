"""公开账本 + 社区见证节点。

全部接口公开无鉴权:账本是匿名化聚合数据,见证节点注册不收集身份信息。
体系说明见 witness/README.md;/nodes 网页由 main.py 提供。
"""
import re
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func as sa_func
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..models import LedgerAnchor, WitnessNode
from ..ratelimit import check_rate_limit
from .transparency import _running_version as _tp_version

router = APIRouter(tags=["公开账本与见证节点"])

_NODE_ID = re.compile(r"^[A-Za-z0-9-]{8,64}$")
MAX_NODES = 5000
ONLINE_WINDOW_MIN = 15  # 心跳间隔 5 分钟,15 分钟没心跳算离线


# ---------- 公开账本 ----------
@router.get("/ledger/anchors")
async def ledger_anchors(
    after: str = "",
    db: AsyncSession = Depends(get_db),
):
    """锚点链(轻量,不含流水全文)。见证节点每轮全量拉取比对历史。"""
    q = select(LedgerAnchor).order_by(LedgerAnchor.day)
    if after:
        q = q.where(LedgerAnchor.day > after)
    rows = await db.scalars(q.limit(400))
    return [{"day": r.day, "payload_hash": r.payload_hash,
             "chain_hash": r.chain_hash} for r in rows]


@router.get("/ledger/days/{day}")
async def ledger_day(day: str, db: AsyncSession = Depends(get_db)):
    """某天流水全文(匿名化)。见证节点据此复算 payload_hash 与 chain_hash。"""
    import json

    anchor = await db.scalar(
        select(LedgerAnchor).where(LedgerAnchor.day == day))
    if anchor is None:
        raise HTTPException(404, "该日锚点不存在(未到关账时间或早于账本起点)")
    return {"day": anchor.day, "payload": json.loads(anchor.payload),
            "payload_hash": anchor.payload_hash, "chain_hash": anchor.chain_hash}


# ---------- 见证节点 ----------
class HeartbeatIn(BaseModel):
    node_id: str = Field(min_length=8, max_length=64)
    name: str = Field(default="", max_length=30)
    region: str = Field(default="", max_length=30)
    tz: str = Field(default="", max_length=40)  # 自愿:IANA 时区名或 UTC±HH:MM,地图粗定位
    version: str = Field(default="", max_length=20)
    verified_day: str = Field(default="", max_length=10)  # 校验到哪天
    chain_hash: str = Field(default="", max_length=64)    # 该天的链哈希(节点复算值)
    ok: bool = True
    message: str = Field(default="", max_length=200)


@router.post("/nodes/heartbeat")
async def node_heartbeat(payload: HeartbeatIn, db: AsyncSession = Depends(get_db)):
    """见证节点心跳:即到即注册,不收集任何身份信息。

    节点上报其复算的链哈希;与平台记录不一致 → 标记 divergent 并在
    /nodes 页公开示警——「有节点认为账本被改过」正是这套体系要抓的事。
    """
    if not _NODE_ID.match(payload.node_id):
        raise HTTPException(422, "node_id 只能是字母数字与连字符(8-64 位)")
    await check_rate_limit("witness", payload.node_id, 6)

    node = await db.scalar(
        select(WitnessNode).where(WitnessNode.node_id == payload.node_id))
    if node is None:
        total = await db.scalar(select(sa_func.count(WitnessNode.id)))
        if total >= MAX_NODES:
            raise HTTPException(429, "节点注册已达上限")
        node = WitnessNode(node_id=payload.node_id)
        db.add(node)

    divergent = False
    if payload.verified_day and payload.chain_hash:
        anchor = await db.scalar(select(LedgerAnchor)
                                 .where(LedgerAnchor.day == payload.verified_day))
        divergent = anchor is not None and anchor.chain_hash != payload.chain_hash

    node.name = payload.name
    node.region = payload.region
    node.tz = payload.tz
    node.version = payload.version
    node.verified_day = payload.verified_day
    node.ok = payload.ok
    node.divergent = divergent or not payload.ok
    node.message = payload.message
    node.heartbeats = (node.heartbeats or 0) + 1  # 新建对象 flush 前默认值未生效
    node.last_seen = datetime.now(timezone.utc)
    await db.commit()
    return {"registered": True, "divergent": node.divergent}


@router.get("/stats/overview")
async def stats_overview(db: AsyncSession = Depends(get_db)):
    """公开运营总览(大屏 /screen、官网、App 账目透明页共用)。

    历史 30 天来自公开账本锚点(与见证节点看到的是同一份数据),
    当日为实时聚合。全部是平台级汇总,无任何个人/单店信息——
    口径与"财报开源"一致:我们的经营数字本来就是公开的。
    """
    import json as _json

    from sqlalchemy import text as sa_text

    anchors = (await db.scalars(
        select(LedgerAnchor).order_by(LedgerAnchor.day.desc()).limit(30))).all()
    trend = []
    for a in reversed(anchors):
        p = _json.loads(a.payload)
        t = p.get("totals", {})
        trend.append({
            "day": a.day,
            "orders": sum(1 for r in p.get("merchant_rows", [])
                          if r.get("kind") == "earning"),
            "merchant_net": t.get("merchant_net", 0),
            "rider_amount": t.get("rider_amount", 0),
            "commission": t.get("platform_commission", 0),
            "voucher_fee": t.get("voucher_fee", 0),
        })

    today = (await db.execute(sa_text("""
        SELECT count(*) FILTER (WHERE status NOT IN ('pending_payment','cancelled')),
               coalesce(sum(total_cents) FILTER (
                   WHERE status NOT IN ('pending_payment','cancelled')), 0),
               coalesce(sum(delivery_fee_cents) FILTER (
                   WHERE status NOT IN ('pending_payment','cancelled')), 0)
        FROM orders
        WHERE created_at >= date_trunc('day', now() AT TIME ZONE 'Asia/Shanghai')
                            AT TIME ZONE 'Asia/Shanghai'
    """))).one()
    hourly = [{"hour": int(r[0]), "orders": r[1]} for r in (await db.execute(sa_text("""
        SELECT extract(hour FROM created_at AT TIME ZONE 'Asia/Shanghai')::int AS h,
               count(*)
        FROM orders
        WHERE created_at >= date_trunc('day', now() AT TIME ZONE 'Asia/Shanghai')
                            AT TIME ZONE 'Asia/Shanghai'
          AND status NOT IN ('pending_payment','cancelled')
        GROUP BY 1 ORDER BY 1
    """))).all()]

    now = datetime.now(timezone.utc)
    node_online = await db.scalar(
        select(sa_func.count(WitnessNode.id)).where(
            WitnessNode.last_seen >= now - timedelta(minutes=ONLINE_WINDOW_MIN)))
    node_total = await db.scalar(select(sa_func.count(WitnessNode.id)))
    latest = anchors[0] if anchors else None
    anchor_count = await db.scalar(select(sa_func.count(LedgerAnchor.id)))

    return {
        "today": {"orders": today[0], "gmv_cents": today[1],
                  "rider_cents": today[2]},
        "hourly": hourly,
        "trend": trend,
        "principles": {"commission_rate": 0.05, "delivery_to_rider": 1.0,
                       "voucher_rate": 0.02},
        "chain": {"anchors": anchor_count,
                  "latest_day": latest.day if latest else None,
                  "latest_hash": latest.chain_hash if latest else None},
        "nodes": {"online": node_online, "total": node_total},
        # 线上运行版本(官网页脚展示,与开源仓 tag 对得上号——代码即承诺)
        "version": _tp_version(),
    }


@router.get("/nodes/summary")
async def nodes_summary(db: AsyncSession = Depends(get_db)):
    """节点网络概览(/nodes 页面数据源)。"""
    now = datetime.now(timezone.utc)
    online_after = now - timedelta(minutes=ONLINE_WINDOW_MIN)
    nodes = (await db.scalars(
        select(WitnessNode).order_by(WitnessNode.last_seen.desc()).limit(200))).all()
    latest = await db.scalar(
        select(LedgerAnchor).order_by(LedgerAnchor.day.desc()).limit(1))

    online = [n for n in nodes if n.last_seen >= online_after]
    return {
        "online": len(online),
        "total": len(nodes),
        "verified_ok": sum(1 for n in online if n.ok and not n.divergent),
        "divergent": sum(1 for n in nodes if n.divergent),
        "latest_anchor": {"day": latest.day, "chain_hash": latest.chain_hash}
        if latest else None,
        "nodes": [{
            "name": n.name or f"节点 {n.node_id[:8]}",
            "region": n.region,
            "tz": n.tz,
            "verified_day": n.verified_day,
            "ok": n.ok and not n.divergent,
            "online": n.last_seen >= online_after,
            "last_seen": n.last_seen,
            "heartbeats": n.heartbeats,
        } for n in nodes],
    }
