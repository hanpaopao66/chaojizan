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


def build_ticket(order: Order, shop_name: str) -> str:
    """58mm 小票排版(飞鹅标签:<CB>居中放大 <B>放大 <C>居中 <BR>换行)。

    给后厨和打包员看的单据:菜品和地址电话用大字,金额明细常规字号。
    """
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
    if order.remark:
        lines.append(f"<B>备注:{order.remark}</B>")
    if any(item.get("is_alcohol") for item in order.items):
        lines.append("<B>含酒精饮品 请查验收件人年龄</B>")
    lines.append("--------------------------------")
    for item in order.items:
        amt = _yuan(item["price_cents"] * item["quantity"])
        lines.append(f"<B>{item['name']} x{item['quantity']}</B>  {amt}")
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


async def print_content(sn: str, content: str) -> None:
    """推送打印。失败抛 ValueError(给补打接口回显)。"""
    body = await _call("Open_printMsg", sn=sn, content=content, times="1")
    if body.get("ret") != 0:
        raise ValueError(f"打印失败:{body.get('msg', '未知错误')}")


def print_order_async(order: Order, merchant: Merchant) -> None:
    """支付成功后的自动出票:后台任务,任何失败只记日志,绝不阻塞订单流程。"""
    if not (settings.feie_configured and merchant.printer_sn and merchant.printer_auto):
        return
    content = build_ticket(order, merchant.name)
    sn, order_no = merchant.printer_sn, order.order_no

    async def _task() -> None:
        try:
            await print_content(sn, content)
            logger.info("云打印出票 %s -> %s", order_no, sn)
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("云打印失败 %s -> %s: %s", order_no, sn, exc)

    asyncio.get_running_loop().create_task(_task())
