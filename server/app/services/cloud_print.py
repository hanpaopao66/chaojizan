"""飞鹅云打印:商家听单小票,服务端直推。

为什么走云打印:打印机自带流量卡/WiFi 直连厂商云端,支付成功后服务端调 API
出票——不依赖商家手机在线、不怕 App 被杀后台,可靠性与大平台小票机对齐。
蓝牙直连是商家端 App 里的另一条兜底路(见 apps/merchant_app/printer_service.dart)。

打印失败绝不影响订单流程:所有异常只记日志,商家端有"补打"按钮兜底。
"""
import asyncio
import hashlib
import logging
import time
from datetime import datetime, timedelta, timezone

import httpx

from ..config import settings
from ..models import Merchant, Order
from .privacy_phone import mask_phone

logger = logging.getLogger("superz.print")

FEIE_URL = "https://api.feieyun.cn/Api/Open/"
_CST = timezone(timedelta(hours=8))


async def _call(apiname: str, **params) -> dict:
    """飞鹅开放平台调用。签名 = sha1(USER + UKEY + STIME)。"""
    stime = str(int(time.time()))
    sig = hashlib.sha1(
        (settings.feie_user + settings.feie_ukey + stime).encode()).hexdigest()
    data = {"user": settings.feie_user, "stime": stime, "sig": sig,
            "apiname": apiname, **params}
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(FEIE_URL, data=data)
        resp.raise_for_status()
        return resp.json()


async def bind_printer(sn: str, key: str, remark: str = "") -> None:
    """绑定打印机到开发者账号。失败抛 ValueError(中文原因,直接给商家看)。"""
    body = await _call("Open_printerAddlist",
                       printerContent=f"{sn}#{key}#{remark or 'SuperZ'}")
    if body.get("ret") != 0:
        raise ValueError(f"云打印服务返回错误:{body.get('msg', '未知错误')}")
    no = (body.get("data") or {}).get("no") or []
    if no:
        # 形如 "SN#KEY#备注 (错误:识别码不正确)"
        raise ValueError(f"打印机绑定失败:{no[0]}")


async def unbind_printer(sn: str) -> None:
    """解绑。打印机不存在等错误不抛出——解绑要的是幂等,不是较真。"""
    try:
        await _call("Open_printerDelList", snlist=sn)
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("解绑云打印机 %s 失败(忽略): %s", sn, exc)


def _yuan(cents: int) -> str:
    return f"{cents / 100:.2f}"


def build_ticket(order: Order, shop_name: str, *, purpose: str = "front",
                 options: dict | None = None) -> str:
    """58mm 小票排版(飞鹅标签:<CB>居中放大 <B>放大 <C>居中 <BR>换行)。

    [purpose] 决定这张单印什么:
    - **front(前厅)**:全量 —— 骑手来取要核对收件人与地址;
    - **kitchen(后厨)**:菜品、备注、取餐码,**不印顾客手机号和地址**。
      后厨不需要这两项,而备餐单会被随手丢在操作台上、下班扫进垃圾桶,
      一张纸就是一条个人信息泄露。金额也不印 —— 后厨看单价没有用。
    - **label(标签)**:一句话贴袋子上,只要店名和取餐码/单号后六位。

    [options] 是几个开关(不做自由排版编辑器,维护成本远超收益):
    show_price / show_remark / big_pickup_code。
    """
    opt = options or {}
    if purpose == "label":
        return _build_label(order, shop_name)
    kitchen = purpose == "kitchen"
    show_price = opt.get("show_price", not kitchen)
    show_remark = opt.get("show_remark", True)
    created = order.created_at
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    ts = created.astimezone(_CST).strftime("%m-%d %H:%M")
    tail = order.order_no[-6:]

    lines: list[str] = []
    lines.append(f"<CB>超级赞 #{tail}</CB>")
    lines.append(f"<C>{shop_name}</C>")
    if order.pickup:
        lines.append(f"<CB>自取单 取餐码 {order.pickup_code}</CB>")
    if order.parent_order_no:
        lines.append(f"<CB>追加单 随#{order.parent_order_no[-6:]}一起出</CB>")
    lines.append("--------------------------------")
    lines.append(f"单号 {order.order_no}")
    lines.append(f"下单 {ts}")
    if order.scheduled_at is not None:
        sched = order.scheduled_at
        if sched.tzinfo is None:
            sched = sched.replace(tzinfo=timezone.utc)
        lines.append(f"<B>预约 {sched.astimezone(_CST).strftime('%m-%d %H:%M')} 送达</B>")
    if order.remark and show_remark:
        lines.append(f"<B>备注:{order.remark}</B>")
    if any(item.get("is_alcohol") for item in order.items):
        lines.append("<B>含酒精饮品 请查验收件人年龄</B>")
    lines.append("--------------------------------")
    for item in order.items:
        amt = _yuan(item["price_cents"] * item["quantity"])
        lines.append(f"<B>{item['name']} x{item['quantity']}</B>"
                     + (f"  {amt}" if show_price else ""))
    if not show_price:
        # 后厨单到此为止:金额、收件人、地址都不印
        lines.append("--------------------------------")
        lines.append("<C>备餐单</C>")
        return "<BR>".join(lines)
    lines.append("--------------------------------")
    lines.append(f"菜品 {_yuan(order.food_cents)}"
                 + (f"  打包费 {_yuan(order.packing_fee_cents)}"
                    if order.packing_fee_cents else ""))
    if order.discount_cents:
        lines.append(f"满减 -{_yuan(order.discount_cents)}")
    if order.pickup:
        lines.append("到店自取 免配送费")
    else:
        lines.append(f"配送费 {_yuan(order.delivery_fee_cents)}(全归骑手)")
        # 配送费构成印在票上:顾客当面问"怎么这么贵"时,商家能直接指给他看。
        # 这笔钱商家一分不拿却总要替我们解释,印出来比让他背话术实在。
        # 与蓝牙小票、四端展示同一份拆分快照,不另算一遍
        from ..routers.orders import FEE_PART_LABELS
        parts = [(k, v) for k, v in (order.fee_parts or {}).items() if v]
        if len(parts) > 1:
            lines.append("  " + " ".join(
                f"{FEE_PART_LABELS.get(k, k)}{v / 100:.1f}" for k, v in parts))
        # 只在**明确选了楼下**时印。用 `not order.to_door` 的话,
        # 字段为 None(未入库的对象/老数据)会被当成"选了楼下"印出来 ——
        # 而那是在替顾客做一个他没做过的选择
        if order.to_door is False:
            lines.append("  顾客选了送到楼下,骑手不上楼")
    lines.append(f"<B>用户实付 {_yuan(order.total_cents)}</B>")
    lines.append("--------------------------------")
    # 电话脱敏:小票只印中间号(X 号)或打码号,真号永不落纸
    shown_phone = order.privacy_phone or mask_phone(order.contact_phone)
    if order.pickup:
        lines.append(f"<B>顾客到店自取,核对取餐码 {order.pickup_code}</B>")
        if order.contact_phone:
            lines.append(f"{order.contact_name} {shown_phone}")
    else:
        lines.append(f"<B>{order.contact_name} {shown_phone}</B>")
        lines.append(f"<B>{order.address}</B>")
    lines.append("--------------------------------")
    lines.append("<C>平台只抽5% 账目公开可查</C>")
    return "<BR>".join(lines)


def _build_label(order: Order, shop_name: str) -> str:
    """标签机:贴在打包袋上的一小张。只要认得出是哪一单就够了。"""
    tail = order.order_no[-6:]
    lines = [f"<CB>{shop_name}</CB>"]
    if order.pickup:
        lines.append(f"<CB>取餐码 {order.pickup_code}</CB>")
    lines.append(f"<CB>#{tail}</CB>")
    lines.append(f"<C>{sum(i['quantity'] for i in order.items)} 件</C>")
    return "<BR>".join(lines)


async def print_content(sn: str, content: str) -> None:
    """推送打印。失败抛 ValueError(给补打接口回显)。"""
    body = await _call("Open_printMsg", sn=sn, content=content, times="1")
    if body.get("ret") != 0:
        raise ValueError(f"打印失败:{body.get('msg', '未知错误')}")


def print_order_async(order: Order, merchant: Merchant,
                      printers: list | None = None) -> None:
    """支付成功后的自动出票:后台任务,任何失败只记日志,绝不阻塞订单流程。

    多台打印机时**按用途各出各的**:前厅一张全量、后厨一张不带
    顾客手机号和地址、标签机一小张。每台独立成任务 ——
    后厨那台离线不该让前厅也没单。
    """
    if not settings.feie_configured:
        return
    order_no = order.order_no
    # 在这里就把内容排好:任务是异步跑的,而 order/merchant 是 ORM 对象,
    # 外层 session 一关就过期,到任务里再读属性会炸 DetachedInstanceError
    jobs = [(p["sn"], build_ticket(order, merchant.name,
                                   purpose=p["purpose"],
                                   options=p.get("options") or {}))
            for p in _auto_printers(merchant, printers)]
    if not jobs:
        return

    async def _one(sn: str, content: str) -> None:
        try:
            await print_content(sn, content)
            logger.info("云打印出票 %s -> %s", order_no, sn)
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("云打印失败 %s -> %s: %s", order_no, sn, exc)

    loop = asyncio.get_running_loop()
    for sn, content in jobs:
        loop.create_task(_one(sn, content))


def _auto_printers(merchant: Merchant, printers: list | None) -> list[dict]:
    """这家店要自动出票的打印机。

    **优先用调用方查好的 merchant_printers**;没有时退回老的
    Merchant.printer_sn 单字段 —— 迁移已经把存量搬过去了,这条是兜底
    (迁移之后、商家还没在新界面上动过的那段时间,以及任何忘了传的调用点)。

    打印机由调用方查好传进来而不是在这里查:这个函数被支付回调调用,
    那里的 session 生命周期不归我们管,在这里另起一个查询容易踩到
    "外层事务还没提交、查出来的是旧数据"。
    """
    if printers:
        return [{"sn": p.sn, "purpose": p.purpose, "options": p.options}
                for p in printers if p.auto and p.sn]
    if merchant.printer_sn and merchant.printer_auto:
        return [{"sn": merchant.printer_sn, "purpose": "front",
                 "options": {}}]
    return []
