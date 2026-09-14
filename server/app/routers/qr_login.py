"""扫码登录、一键登录,和「已登录的网页和电脑」(用户端网页版、桌面版)。

流程,以及安全上每条规矩对着哪种攻击,见 services/qr_login.py 的模块说明。这里是接口:

    POST   /auth/qr/sessions                网页 / 电脑建会话(不用登录;带 device_key 就是一键登录)
    GET    /auth/qr/sessions/{sid}          网页 / 电脑长轮询(不用登录,要请求头 X-QR-Secret)
    POST   /auth/qr/sessions/{sid}/scan     手机扫到码
    POST   /auth/qr/sessions/{sid}/confirm  手机上点「登录」
    POST   /auth/qr/sessions/{sid}/cancel   手机上点「取消」
    GET    /auth/qr/pending                 手机上查有没有待确认的一键登录
    GET    /auth/login-devices              已登录的网页和电脑
    DELETE /auth/login-devices/{id}         移除:那台设备立刻退出,也不能再一键登录
    GET    /l/{sid}                         二维码被别的扫码工具打开时看到的说明页

后面这几个要登录的接口都不在 AI 助手令牌的白名单里(security.AGENT_SCOPES),助手令牌调是 403 ——
**别往白名单里加**,理由见 services/qr_login.py 第 6 条。
"""
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..db import SessionLocal, get_db
from ..models import LoginDevice, User, UserRole
from ..ratelimit import check_daily_limit, check_rate_limit, client_ip
from ..security import create_token, get_current_user
from ..services import push
from ..services import qr_login as qr
from ..services.rt_events import append_user_event

logger = logging.getLogger("superz.qr_login")

router = APIRouter(prefix="/auth", tags=["认证"])
#: 不带 /auth 前缀的那一页(二维码里的链接)
page_router = APIRouter()

QR_PAGE = Path(__file__).resolve().parent.parent.parent / "static" / "qr-login.html"


class QrSessionIn(BaseModel):
    #: web = 网页版;desktop = 桌面版(macOS / Windows / Linux)
    client: Literal["web", "desktop"] = "web"
    #: 桌面版报自己的系统(macos / windows / linux);网页版不用报,看 UA
    platform: str = Field(default="", max_length=16)
    #: 上次扫码登录时拿到的 device_key。带了就是一键登录
    device_key: str = Field(default="", max_length=128)
    #: 扫码登录时,这台设备手里原来那把 device_key(比如点了「切换账号」)。
    #: 扫码的还是同一个人的话沿用那一行设备记录,「已登录的网页和电脑」里不会多出一台重复的
    prev_device_key: str = Field(default="", max_length=128)


def _phone_app(request: Request, user: User) -> None:
    """扫码、确认、取消、查待确认:只认**手机 App 上**登录的用户端账号。

    - 商家、骑手账号扫到了也不行:用户端的网页版登录的是用户端账号;
    - 网页版、电脑版自己的会话(token 里带 `ld`)不行:不然偷到一个网页会话的人,
      可以拿它给自己批一台又一台新电脑。批准新设备这一下必须在手机上。
    AI 助手令牌走不到这里:get_current_user 已经按白名单 403 了。
    """
    if user.role != UserRole.customer:
        raise HTTPException(403, "请用超级赞用户端 App 扫码登录")
    if getattr(request.state, "login_device_id", None) is not None:
        raise HTTPException(403, "网页版、电脑版不能批准别的设备登录,请在手机 App 上操作")


@router.post("/qr/sessions")
async def create_qr_session(payload: QrSessionIn, request: Request,
                            db: AsyncSession = Depends(get_db)):
    """网页版 / 桌面版建一个登录会话。**不用登录。**

    返回 sid(二维码里的就是它)、secret(只给这个网页,轮询时放请求头 X-QR-Secret,
    **不进二维码、不进 URL**)、二维码内容 qr、expires_at。会话 120 秒过期。

    记下请求方的设备描述、IP 和客户端类型 —— 手机的确认页要把它们摆出来,
    那是被人骗扫的时候唯一能帮你认出「这不是我那台电脑」的东西。

    带 device_key 就是一键登录:这台设备上次扫码登录过,会话直接绑到那个人身上,
    给他的手机 App 发确认请求(App 在前台:用户事件,当场弹确认页;不在前台:推送)。
    device_key 自己登不了录,手机上点了确认才签 token。

    限流:按 IP 建会话;一键登录再按人限,每天有上限(它会往手机上弹框)。
    """
    ip = client_ip(request)
    await check_rate_limit("qr_create", ip, settings.rate_limit_qr_create_per_minute)
    device = qr.describe_device(request.headers.get("user-agent", ""), payload.client,
                                payload.platform)
    now = time.time()
    sid, secret = qr.new_sid(), qr.new_secret()
    sess = {
        "status": "pending", "mode": "qr", "client": payload.client, "device": device,
        "ip": ip, "secret": qr.hash_key(secret),
        "created_at": now, "expires_at": now + qr.SESSION_TTL,
        "user_id": None, "device_id": None, "prev": None, "who": None,
    }
    user = row = None
    if payload.device_key:
        row = await qr.live_device_by_key(db, payload.device_key)
        user = await db.get(User, row.user_id) if row is not None else None
        if row is None or not qr.usable_user(user):
            # 被移除了、太久没用、换过 key(用过一次就换)、账号没了 —— 一律同一句话,
            # 不告诉对方是哪一种
            raise HTTPException(403, "这台设备的一键登录已经失效,请扫码登录")
        await check_rate_limit("qr_oneclick", str(user.id),
                               settings.rate_limit_qr_oneclick_per_minute)
        await check_daily_limit("qr_oneclick", str(user.id), settings.qr_oneclick_daily_limit,
                                "今天一键登录的次数用完了,请扫码登录")
        sess.update(status="scanned", mode="oneclick", user_id=user.id, device_id=row.id,
                    scanned_at=now, who=qr.who(user))
    elif payload.prev_device_key:
        sess["prev"] = qr.hash_key(payload.prev_device_key)
    if not await qr.put_new(sid, sess):
        raise HTTPException(503, "请重试")          # sid 撞了:192 位随机数,不会真的发生

    if user is not None:
        stale = await qr.remember_pending(user.id, sid, row.id)
        if stale and stale != sid:
            # 同一台设备又点了一次「一键登录」:旧的那条作废,手机上只留一条
            await qr.cancel_quietly(stale)
        await append_user_event(db, user.id, "qr_login", {
            "sid": sid, "device": device, "client": payload.client,
            "expires_at": qr.iso(sess["expires_at"])})
        await db.commit()
        if not qr.app_in_foreground(user.id):
            # 推送里不带 sid:推送经第三方(极光)转一道,App 打开后自己来 /auth/qr/pending 取
            push.spawn(push.push_to_user(
                user.id, "登录确认", f"{device} 正在请求登录你的超级赞账号,打开 App 确认",
                {"type": "qr_login"}, record_skip=True), what="一键登录推送")
        logger.info("一键登录请求: user_id=%s device_id=%s", user.id, row.id)

    return {
        "sid": sid,
        "secret": secret,
        "qr": qr.qr_url(sid) if user is None else "",
        "mode": sess["mode"],
        "status": sess["status"],
        "expires_at": qr.iso(sess["expires_at"]),
        "ttl": qr.SESSION_TTL,
    }


@router.get("/qr/sessions/{sid}")
async def poll_qr_session(
    sid: str,
    request: Request,
    state: str = Query(default="", max_length=16),
    wait: int = Query(default=qr.WAIT_MAX, ge=0, le=qr.WAIT_MAX),
    x_qr_secret: str = Header(default="", max_length=128),
):
    """网页 / 电脑长轮询。**不用登录**,但要请求头 X-QR-Secret(建会话时拿到的)。

    [state] 传上一次看到的状态:没变就挂着等,最多 [wait] 秒(≤ 25);变了立刻返回。

    - pending:还没人扫;
    - scanned:扫了 / 一键登录已发到手机,等手机上点确认。带打过码的昵称和头像;
    - confirmed:**只返回这一次**。token、device_key(下次一键登录用)、device_id;
      返回前这个会话已经从 Redis 里删掉,之后再来就是 expired;
    - cancelled:手机上点了取消;
    - expired:过期了,或者根本没有这个会话。

    **这个接口不在等之前查库**(见 qr_login.wait_change):挂着的请求不占数据库连接。
    """
    await check_rate_limit("qr_poll", client_ip(request), settings.rate_limit_qr_poll_per_minute)
    raw, sess = await qr.load(sid)
    if sess is None:
        return {"status": "expired"}
    if not qr.secret_ok(sess, x_qr_secret):
        # 只有 sid(二维码被人拍走、链接进了日志)的人走到这里:状态也不给看
        raise HTTPException(403, "这不是你发起的登录")
    if wait > 0 and qr.status_of(sess) == state:
        raw, sess = await qr.wait_change(sid, state, wait)
        if sess is None:
            return {"status": "expired"}
    status = qr.status_of(sess)
    if status == "confirmed":
        return await _hand_over(sid, raw, sess)
    if status == "scanned":
        return {"status": "scanned", "mode": sess.get("mode", "qr"), "user": sess.get("who")}
    if status == "pending":
        return {"status": "pending", "expires_at": qr.iso(sess["expires_at"])}
    return {"status": status}


async def _hand_over(sid: str, raw: str, sess: dict) -> dict:
    """手机上确认过了:领走会话、签 token、建 / 刷新这台设备的记录。

    **先删会话再签 token**:删(比对原文)成功的那一个请求才签,两个轮询同时来只有一个拿得到。
    删了之后签发失败(库挂了)的话,这次登录就丢了、要重新扫 —— 宁可让人重扫一次,也不让 token 交付两次。
    """
    if not await qr.swap(sid, raw, None):
        return {"status": "expired"}                     # 另一个轮询先领走了
    await qr.forget_pending(int(sess["user_id"]), sid)
    async with SessionLocal() as db:
        user = await db.get(User, int(sess["user_id"]))
        if not qr.usable_user(user):
            return {"status": "cancelled"}
        now = datetime.now(timezone.utc)
        row = None
        if sess.get("device_id"):
            # 一键登录:沿用那台设备。确认之后、领走之前被移除了的,不算数
            row = await db.scalar(
                select(LoginDevice).where(LoginDevice.id == int(sess["device_id"]))
                .with_for_update().execution_options(populate_existing=True))
            if row is None or row.revoked_at is not None or row.user_id != user.id:
                return {"status": "cancelled"}
        elif sess.get("prev"):
            row = await db.scalar(
                select(LoginDevice).where(LoginDevice.key_hash == sess["prev"],
                                          LoginDevice.user_id == user.id,
                                          LoginDevice.revoked_at.is_(None))
                .with_for_update().execution_options(populate_existing=True))
        device_key = qr.new_device_key()
        if row is None:
            await qr.make_room(db, user.id)
            row = LoginDevice(user_id=user.id, key_hash=qr.hash_key(device_key),
                              client=sess.get("client", "web"), device=sess.get("device", "")[:64],
                              ip_masked=qr.mask_ip(sess.get("ip", "")), last_used_at=now)
            db.add(row)
            await db.flush()
        else:
            # 每用一次换一把新 key:被偷走的旧 key 一用,真主人手里那把就失效了
            row.key_hash = qr.hash_key(device_key)
            row.client = sess.get("client", row.client)
            row.device = sess.get("device", row.device)[:64]
            row.ip_masked = qr.mask_ip(sess.get("ip", ""))
            row.last_used_at = now
        token = create_token(user, login_device_id=row.id)
        await db.commit()
        # 只记谁、哪台设备、哪种方式。token、device_key、secret 一个字都不进日志
        logger.info("扫码登录完成: user_id=%s device_id=%s mode=%s",
                    user.id, row.id, sess.get("mode"))
        return {
            "status": "confirmed",
            "token": token,
            "user_id": user.id,
            "role": user.role.value,
            "name": user.name,
            "avatar_url": user.avatar_url or "",
            "device_key": device_key,
            "device_id": row.id,
        }


async def _live_session(sid: str) -> tuple[str, dict]:
    """读出会话,并确认它还有效。过期 / 没有这个会话 → 404"""
    raw, sess = await qr.load(sid)
    if sess is None or qr.status_of(sess) == "expired":
        raise HTTPException(404, "二维码已过期,请在电脑上刷新后重新扫码")
    return raw, sess


@router.post("/qr/sessions/{sid}/scan")
async def scan_qr_session(sid: str, request: Request,
                          user: User = Depends(get_current_user)):
    """手机扫到了登录码:把会话绑给扫码的人,返回确认页要摆出来的东西。

    返回请求方的设备描述、**打过码的 IP**、和这台手机是不是同一个网络、什么时候发起的。
    确认页上必须有它们(见 services/qr_login.py 第 4 条)。

    同一个人重复扫是幂等的;已经被别人扫过的码 409 —— 一张码只能属于一个人。
    """
    _phone_app(request, user)
    await check_rate_limit("qr_scan", str(user.id), settings.rate_limit_qr_scan_per_minute)
    viewer = client_ip(request)
    for _ in range(3):
        raw, sess = await _live_session(sid)
        owner = sess.get("user_id")
        if owner is not None and owner != user.id:
            raise HTTPException(409, "这个二维码已经被别人扫过了,请在电脑上刷新二维码")
        status = sess.get("status")
        if status == "cancelled":
            raise HTTPException(409, "这次登录已经取消了,请在电脑上刷新二维码")
        if status == "confirmed":
            raise HTTPException(409, "这个二维码已经用过了")
        if status == "scanned":
            return qr.request_view(sid, sess, viewer)
        new = {**sess, "status": "scanned", "user_id": user.id,
               "scanned_at": time.time(), "who": qr.who(user)}
        if await qr.swap(sid, raw, new):
            return qr.request_view(sid, new, viewer)
    raise HTTPException(409, "二维码刚刚有变化,请再扫一次")


@router.post("/qr/sessions/{sid}/confirm")
async def confirm_qr_session(sid: str, request: Request,
                             user: User = Depends(get_current_user)):
    """手机上点「登录」。**只能是扫码的那个人**(一键登录:只能是那台设备的主人)。

    这一步只把会话标成已确认;token 等网页带着 secret 来领的时候才签(见 _hand_over),
    所以 token 从头到尾不在 Redis 里放着。
    """
    _phone_app(request, user)
    await check_rate_limit("qr_scan", str(user.id), settings.rate_limit_qr_scan_per_minute)
    for _ in range(3):
        raw, sess = await _live_session(sid)
        if sess.get("user_id") != user.id:
            raise HTTPException(403, "只有扫码的人才能确认这次登录")
        status = sess.get("status")
        if status == "confirmed":
            return {"ok": True}
        if status != "scanned":
            raise HTTPException(409, "这次登录已经取消了,请在电脑上刷新二维码")
        if await qr.swap(sid, raw, {**sess, "status": "confirmed", "confirmed_at": time.time()}):
            await qr.forget_pending(user.id, sid)
            logger.info("扫码登录已确认: user_id=%s mode=%s", user.id, sess.get("mode"))
            return {"ok": True}
    raise HTTPException(409, "刚刚有变化,请再试一次")


@router.post("/qr/sessions/{sid}/cancel")
async def cancel_qr_session(sid: str, request: Request,
                            user: User = Depends(get_current_user)):
    """手机上点「取消」(或者关掉了确认页)。只有扫码的那个人能取消;已经过期的算取消成功。"""
    _phone_app(request, user)
    await check_rate_limit("qr_scan", str(user.id), settings.rate_limit_qr_scan_per_minute)
    for _ in range(3):
        raw, sess = await qr.load(sid)
        if sess is None or qr.status_of(sess) in ("expired", "cancelled"):
            return {"ok": True}
        if sess.get("user_id") != user.id:
            raise HTTPException(403, "只有扫码的人才能取消这次登录")
        if sess.get("status") == "confirmed":
            raise HTTPException(409, "已经登录了。要让那台设备退出,到「设置 → 已登录的网页和电脑」里移除")
        if await qr.swap(sid, raw, {**sess, "status": "cancelled"}):
            await qr.forget_pending(user.id, sid)
            return {"ok": True}
    raise HTTPException(409, "刚刚有变化,请再试一次")


@router.get("/qr/pending")
async def pending_qr_logins(request: Request, user: User = Depends(get_current_user)):
    """我有没有待确认的一键登录(App 从推送点进来、或者回到前台时查一次)。

    每一条带着确认页要摆出来的东西(设备、打过码的 IP、时间),和扫码返回的是同一个样子。
    """
    _phone_app(request, user)
    await check_rate_limit("qr_pending", str(user.id), settings.rate_limit_qr_poll_per_minute)
    viewer = client_ip(request)
    items = []
    for sid in await qr.pending_sids(user.id):
        _, sess = await qr.load(sid)
        if (sess is None or sess.get("user_id") != user.id or sess.get("mode") != "oneclick"
                or qr.status_of(sess) != "scanned"):
            await qr.forget_pending(user.id, sid)
            continue
        items.append(qr.request_view(sid, sess, viewer))
    items.sort(key=lambda x: x["created_at"], reverse=True)
    return {"items": items}


def _customer(user: User) -> None:
    if user.role != UserRole.customer:
        raise HTTPException(403, "只有用户端账号有扫码登录的设备")


@router.get("/login-devices")
async def list_login_devices(request: Request, user: User = Depends(get_current_user),
                             db: AsyncSession = Depends(get_db)):
    """已登录的网页和电脑:扫码登录过、还能一键登录的那几台。

    打过码的 IP、最近使用时间。current 标出「就是现在这台」(网页、电脑上打开这一页时)。
    """
    _customer(user)
    current = getattr(request.state, "login_device_id", None)
    rows = await qr.live_devices(db, user.id)
    return {
        "items": [{
            "id": r.id,
            "client": r.client,
            "device": r.device,
            "ip": r.ip_masked,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "last_used_at": r.last_used_at.isoformat() if r.last_used_at else None,
            "current": r.id == current,
        } for r in rows],
        "idle_days": qr.DEVICE_IDLE_DAYS,
    }


@router.delete("/login-devices/{device_id}")
async def remove_login_device(device_id: int, user: User = Depends(get_current_user),
                              db: AsyncSession = Depends(get_db)):
    """移除一台网页 / 电脑:它的登录**下一次请求就失效**(token 里带着这台设备,每次都回库查),
    也不能再一键登录。开着实时通道的话,那边收到用户事件当场退出。"""
    _customer(user)
    row = await db.get(LoginDevice, device_id)
    if row is None or row.user_id != user.id:
        raise HTTPException(404, "没有这台设备")
    if row.revoked_at is None:
        row.revoked_at = datetime.now(timezone.utc)
        await append_user_event(db, user.id, "login_device", {"id": row.id, "revoked": True})
        await db.commit()
        logger.info("已移除扫码登录的设备: user_id=%s device_id=%s", user.id, row.id)
    return {"ok": True}


@page_router.get("/l/{sid}", include_in_schema=False)
async def qr_login_page(sid: str):
    """二维码被别的扫码工具(微信、系统相机)打开时看到的页面:「请用超级赞 App 扫一扫登录」+ 下载。

    **一个字的会话信息都不给**:不查这个 sid 在不在、是谁建的、从哪台电脑来 —— 这是一份静态文件,
    任何 sid 打开都一样。不然拿到这个链接的人都能打听到对面是哪台电脑、有没有人扫过。
    不缓存、不带 Referer 出去(链接里有 sid),不让搜索引擎收。
    """
    return FileResponse(QR_PAGE, media_type="text/html", headers={
        "Cache-Control": "no-store",
        "Referrer-Policy": "no-referrer",
        "X-Robots-Tag": "noindex",
    })
