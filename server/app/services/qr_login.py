"""扫码登录与一键登录(用户端网页版、桌面版):会话、设备描述、打码。

接口在 routers/qr_login.py;这里是不碰 HTTP 的部分,单测直接测。

## 两种登录,同一种会话

- **扫码登录**:网页 / 电脑上显示二维码,内容是 `{public_base_url}/l/{sid}`。已登录的手机 App
  「扫一扫」扫到它 → 手机上显示「在 Chrome · macOS 上登录超级赞?」→ 点「登录」→ 网页那边的长轮询
  拿到登录 token;
- **一键登录**:扫码登录成功时服务端给那台设备一把 device_key(login_devices 只存它的哈希)。
  下次登录过期或退出了,带着它来建会话:会话直接绑到那台设备的主人身上,给他的手机 App 发一条确认请求
  (用户事件 + 推送);手机上点确认,网页进去。

## 几条硬规矩,每条都对着一种具体的攻击

1. **二维码里只有 sid,领 token 还要一个 secret。** 二维码亮在屏幕上:旁边的人能拍走,
   用微信之类的工具扫一下它就进了访问日志(sid 在 URL 里,nginx、uvicorn 都会记路径)。
   所以建会话时另给网页一个 secret,只放在网页自己手里 —— 不进二维码、不进 URL,轮询时放在
   请求头 X-QR-Secret 里。只有 sid 的人能看到「已扫码」这类状态,拿不走 token。
2. **token 只交付一次,而且不预先存着。** 手机上点了确认只是把会话标成 confirmed;网页带着 secret
   来领的那一刻,先原子地把会话从 Redis 里删掉(比对原文,Lua 一步做完),删成功了才当场签 token。
   两个轮询同时来只有一个领得到,之后再来都是「已过期」。token 从头到尾没在 Redis 里放过。
3. **扫码的人和确认的人必须是同一个。** 扫码把会话绑给扫码的人;别人再扫是 409,别人来确认是 403。
   一键登录的会话建出来就绑在那台设备的主人身上,只有他能确认。
4. **确认页必须摆出请求方的设备和 IP。** 最常见的钓鱼是「扫别人伪造的码」:骗子在自己电脑上打开网页版,
   把二维码截图发给你(「扫码领券」),你一扫一点,他那台电脑就登上了你的账号。手机上能帮你认出来的
   只有「哪台设备、哪个 IP、什么时候」,所以一样不能少,确认页上还写着「如果不是你本人正在电脑前操作,
   请点取消」。设备描述只从固定的几个词里拼(见 describe_device),**不把 UA 原文放上去** ——
   放原文的话,骗子可以把 UA 写成「超级赞官方活动」,让确认页替他说话。
5. **设备记住的东西本身不能登录。** device_key 只能让服务端去问一次手机,手机上点了确认才签 token。
   网页的本地存储被人读走也一样:对方只能往你手机上弹确认框。所以一键登录按人限流(不能一直弹、
   等你点烦了手一滑),而且每用一次换一把新的 —— 被偷的旧 key 一用,真主人手里那把就失效了,能察觉。
6. **AI 助手令牌碰不了扫码、确认、取消。** 这几个接口要登录,而助手令牌的白名单(security.AGENT_SCOPES)
   里没有它们,默认拒绝,自动 403。**别往白名单里加**:一个能替你确认登录的助手,
   等于能把你的账号交给任何一台电脑。
7. **网页、电脑上的会话不能再批准别的设备。** 扫码、确认、取消、查待确认只认手机 App 上的登录
   (token 里没有 `ld`)。不然偷到一个网页会话的人,可以自己给自己批一台又一台新电脑。
8. **日志不记 token、device_key、secret。** 这三样任何一个进了日志,日志就成了登录凭据的备份。

## 存哪

会话在 Redis(`qr:s:{sid}`,建出来 120 秒过期,扫了码也不续);已登录的网页和电脑在 login_devices 表。
"""
import asyncio
import hashlib
import ipaddress
import json
import re
import secrets
import time
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..models import LoginDevice, User, UserRole
from ..redis_client import get_redis

#: 会话(一张二维码 / 一次一键登录请求)的有效期,秒。从建出来算,扫了码也不续
SESSION_TTL = 120
#: 长轮询最多挂多久,秒。要短于客户端的请求超时(ApiClient 轮询时给 30 秒)
WAIT_MAX = 25
#: 一键登录多久没用就失效,天。登录着的设备每天续期(/auth/refresh)时会刷新最近使用时间
DEVICE_IDLE_DAYS = 30
#: 一个人最多挂几台网页 / 电脑,再多就把最久没用的那台移除
MAX_DEVICES = 20

#: sid 的样子(secrets.token_urlsafe(24) 是 32 个字符)。不像的直接当不存在,不去碰 Redis
SID_RE = re.compile(r"^[A-Za-z0-9_-]{32,64}$")

_KEY = "qr:s:{sid}"
#: 这个人待确认的一键登录(sid 的集合),手机上 GET /auth/qr/pending 读它
_PENDING = "qr:u:{uid}"
#: 这台设备正在等确认的那条一键登录:同一台设备再点一次,旧的那条作废,手机上只留一条
_DEVICE_BUSY = "qr:d:{did}"

#: 网页版、桌面版连实时通道时报的 device(apps/user_app/lib/chat/realtime.dart)。
#: 只有这两种之外的前台连接才算「手机 App 在前台」—— 电脑上开着网页,不代表手机拿在手上
WEB_DEVICES = frozenset({"user-web", "user-desktop"})


def new_sid() -> str:
    return secrets.token_urlsafe(24)


def new_secret() -> str:
    return secrets.token_urlsafe(32)


def new_device_key() -> str:
    return secrets.token_urlsafe(32)


def hash_key(raw: str) -> str:
    """secret、device_key 落地前一律只存 SHA-256。它们是 32 字节随机数,不需要加盐或慢哈希"""
    return hashlib.sha256((raw or "").encode()).hexdigest()


def secret_ok(sess: dict, secret: str) -> bool:
    return bool(secret) and secrets.compare_digest(str(sess.get("secret") or ""), hash_key(secret))


def qr_url(sid: str) -> str:
    """二维码的内容:官方域名的链接。被别的扫码工具打开时是一张「请用超级赞 App 扫」的说明页"""
    return f"{settings.public_base_url.rstrip('/')}/l/{sid}"


def iso(ts: float) -> str:
    return datetime.fromtimestamp(float(ts), tz=timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# 设备描述与打码
# ---------------------------------------------------------------------------

_DESKTOP_OS = {"macos": "macOS", "windows": "Windows", "linux": "Linux"}

#: (UA 里的特征, 叫法)。**顺序有讲究**:Edge、Opera 和国产浏览器的 UA 里都带着 Chrome、Safari
#: 字样,所以越具体的越靠前,Chrome、Safari 垫底
_BROWSERS = (
    ("MicroMessenger", "微信内置浏览器"),
    ("QQBrowser", "QQ 浏览器"),
    ("UCBrowser", "UC 浏览器"),
    ("Quark/", "夸克"),
    ("360SE", "360 浏览器"),
    ("360EE", "360 浏览器"),
    ("MetaSr", "搜狗浏览器"),
    ("HuaweiBrowser", "华为浏览器"),
    ("MiuiBrowser", "小米浏览器"),
    ("Edg/", "Edge"),
    ("EdgA/", "Edge"),
    ("EdgiOS/", "Edge"),
    ("Edge/", "Edge"),
    ("OPR/", "Opera"),
    ("Firefox/", "Firefox"),
    ("FxiOS/", "Firefox"),
    ("CriOS/", "Chrome"),
    ("Chrome/", "Chrome"),
    ("Safari/", "Safari"),
)
#: 同上:iPhone 的 UA 里有 "like Mac OS X",安卓、鸿蒙的 UA 里有 "Linux",所以它们排在前面
_SYSTEMS = (
    ("Windows", "Windows"),
    ("iPhone", "iPhone"),
    ("iPad", "iPad"),
    ("HarmonyOS", "HarmonyOS"),
    ("OpenHarmony", "HarmonyOS"),
    ("Android", "Android"),
    ("CrOS", "ChromeOS"),
    ("Macintosh", "macOS"),
    ("Mac OS X", "macOS"),
    ("Linux", "Linux"),
)


def describe_device(user_agent: str, client: str = "web", platform: str = "") -> str:
    """给人看的设备描述:「Chrome · macOS」「超级赞电脑版 · Windows」。

    **只从上面固定的几个词里拼,不把 UA 原文放上去。** 这行字会出现在手机的确认页上,
    UA 是请求方随便写的 —— 原文照搬的话,骗子能让确认页显示「超级赞官方领券活动」。
    认不出来就老实写「浏览器」。

    桌面版的 HTTP 请求头是 Dart 默认的 UA,认不出系统,所以由客户端报 platform(白名单里的三个)。
    这一项和 UA 一样是请求方自己报的、能伪造 —— 确认页因此同时给 IP。
    """
    if client == "desktop":
        name = _DESKTOP_OS.get((platform or "").strip().lower())
        return f"超级赞电脑版 · {name}" if name else "超级赞电脑版"
    ua = user_agent or ""
    browser = next((name for mark, name in _BROWSERS if mark in ua), "浏览器")
    system = next((name for mark, name in _SYSTEMS if mark in ua), "")
    return f"{browser} · {system}" if system else browser


def _addr(ip: str):
    try:
        addr = ipaddress.ip_address((ip or "").strip())
    except ValueError:
        return None
    if addr.version == 6 and addr.ipv4_mapped is not None:  # ::ffff:1.2.3.4
        return addr.ipv4_mapped
    return addr


def mask_ip(ip: str) -> str:
    """IP 打码:IPv4 留前两段(123.45.*.*),IPv6 留前两组。

    手机上的确认页要靠它帮人认出「这是不是我那台电脑」,整段 IP 给出去又没有必要 ——
    请求方如果是骗子,这是他的 IP;如果是本人,这是本人的 IP,都犯不上在别处多存一份完整的。
    """
    addr = _addr(ip)
    if addr is None:
        return "未知"
    if addr.version == 4:
        a, b, _, _ = str(addr).split(".")
        return f"{a}.{b}.*.*"
    groups = addr.exploded.split(":")
    return f"{int(groups[0], 16):x}:{int(groups[1], 16):x}:*"


def same_network(a: str, b: str) -> bool:
    """两个出口 IP 是不是同一个网络:IPv4 要完全一样,IPv6 看前 64 位。

    手机和电脑连着同一个家里 / 公司的网,出口 IP 就是同一个 —— 这是确认页上最有用的一句提示。
    IPv4 不放宽到 /24:手机流量走运营商的大 NAT,同一个 /24 里是成千上万个陌生人。
    """
    x, y = _addr(a), _addr(b)
    if x is None or y is None or x.version != y.version:
        return False
    if x.version == 4:
        return x == y
    return ipaddress.ip_network(f"{x}/64", strict=False) == ipaddress.ip_network(f"{y}/64", strict=False)


def mask_name(name: str) -> str:
    """昵称打码(张** / 用****4):网页上「已扫码」时显示给请求方看。

    请求方如果是骗子,他在你点「登录」之前就能看到这一行,所以不给全名。
    """
    s = (name or "").strip()
    if not s:
        return ""
    if len(s) == 1:
        return "*"
    if len(s) == 2:
        return s[0] + "*"
    return s[0] + "*" * min(len(s) - 2, 4) + s[-1]


def who(user: User) -> dict:
    """「已扫码,请在手机上确认」那一屏上的人:打过码的昵称 + 头像"""
    return {"name": mask_name(user.name), "avatar_url": user.avatar_url or ""}


def usable_user(user: User | None) -> bool:
    """能用扫码 / 一键登录的账号:还在、没注销、是用户端账号"""
    return (user is not None and user.deleted_at is None
            and not (user.phone or "").startswith("del") and user.role == UserRole.customer)


def request_view(sid: str, sess: dict, viewer_ip: str) -> dict:
    """手机确认页上要摆出来的:哪台设备、打过码的 IP、和这台手机是不是同一个网络、什么时候"""
    return {
        "sid": sid,
        "mode": sess.get("mode", "qr"),
        "client": sess.get("client", "web"),
        "device": sess.get("device", ""),
        "ip": mask_ip(sess.get("ip", "")),
        "same_network": same_network(sess.get("ip", ""), viewer_ip),
        "created_at": iso(sess.get("created_at", 0)),
        "expires_at": iso(sess.get("expires_at", 0)),
    }


# ---------------------------------------------------------------------------
# 会话(Redis)
# ---------------------------------------------------------------------------

def status_of(sess: dict, at: float | None = None) -> str:
    """会话此刻的状态。过了有效期的一律算 expired —— 包括手机上确认了、网页还没领走的:
    领 token 也得在有效期里。cancelled 留着让网页知道是被取消的,不是过期的"""
    st = str(sess.get("status") or "")
    now = time.time() if at is None else at
    if st in ("pending", "scanned", "confirmed") and now >= float(sess.get("expires_at") or 0):
        return "expired"
    return st


def _dump(sess: dict) -> str:
    return json.dumps(sess, ensure_ascii=False, separators=(",", ":"))


async def put_new(sid: str, sess: dict) -> bool:
    return bool(await get_redis().set(_KEY.format(sid=sid), _dump(sess), ex=SESSION_TTL, nx=True))


async def load(sid: str) -> tuple[str | None, dict | None]:
    """读会话,返回 (原文, 内容)。不存在 / 过期 / sid 长得不对 → (None, None)"""
    if not SID_RE.match(sid or ""):
        return None, None
    raw = await get_redis().get(_KEY.format(sid=sid))
    if raw is None:
        return None, None
    raw = raw if isinstance(raw, str) else raw.decode()
    try:
        sess = json.loads(raw)
    except ValueError:
        return None, None
    return (raw, sess) if isinstance(sess, dict) else (None, None)


# 会话还是读出来的那一份才写(比对原文,一步做完),剩余有效期不变;ARGV[2] 为空是删掉(领走)。
# 不是那一份了返回 0:两个人同时扫、手机确认的同时网页在领,都靠这一步只让一个成立
_SWAP_LUA = """
local cur = redis.call('GET', KEYS[1])
if (not cur) or cur ~= ARGV[1] then return 0 end
if ARGV[2] == '' then
  redis.call('DEL', KEYS[1])
  return 1
end
local ttl = redis.call('PTTL', KEYS[1])
if ttl <= 0 then ttl = tonumber(ARGV[3]) end
redis.call('SET', KEYS[1], ARGV[2], 'PX', ttl)
return 1
"""


async def swap(sid: str, old_raw: str, new: dict | None) -> bool:
    """比对原文再写 / 删。成功了顺手叫醒本进程里在等这个会话的长轮询"""
    ok = bool(await get_redis().eval(_SWAP_LUA, 1, _KEY.format(sid=sid), old_raw,
                                     "" if new is None else _dump(new), SESSION_TTL * 1000))
    if ok:
        notify(sid)
    return ok


#: 本进程里在等某个会话变化的长轮询
_waiters: dict[str, set[asyncio.Event]] = {}


def notify(sid: str) -> None:
    for ev in list(_waiters.get(sid, ())):
        ev.set()


async def wait_change(sid: str, seen: str, timeout: float) -> tuple[str | None, dict | None]:
    """等会话的状态变得和 [seen] 不一样(或者等满 timeout 秒),返回最新的一份。

    本进程里改的当场叫醒;别的进程改的,最多晚 1 秒看到(每秒回 Redis 看一眼)。
    到了过期那一刻也会醒 —— 过期不会有人来叫。

    ⚠️ **等的时候不占数据库连接**:调用方别在等之前查库。一个会话一查库,连接就被这个请求攥着 25 秒,
    几十个人同时开着登录页就能把连接池(10 + 20)占满,别的接口全排队。
    """
    deadline = time.monotonic() + max(0.0, timeout)
    ev = asyncio.Event()
    _waiters.setdefault(sid, set()).add(ev)
    try:
        while True:
            ev.clear()
            raw, sess = await load(sid)
            if sess is None or status_of(sess) != seen:
                return raw, sess
            left = deadline - time.monotonic()
            if left <= 0:
                return raw, sess
            till_expiry = float(sess.get("expires_at") or 0) - time.time()
            try:
                await asyncio.wait_for(ev.wait(), timeout=min(1.0, left, max(0.05, till_expiry)))
            except asyncio.TimeoutError:
                pass
    finally:
        group = _waiters.get(sid)
        if group is not None:
            group.discard(ev)
            if not group:
                _waiters.pop(sid, None)


async def remember_pending(user_id: int, sid: str, device_id: int) -> str | None:
    """记下「这个人有一条待确认的一键登录」。返回这台设备上一条还没确认的 sid(要作废它)"""
    r = get_redis()
    busy = _DEVICE_BUSY.format(did=device_id)
    old = await r.get(busy)
    await r.set(busy, sid, ex=SESSION_TTL)
    key = _PENDING.format(uid=user_id)
    await r.sadd(key, sid)
    await r.expire(key, SESSION_TTL + 10)
    return old if isinstance(old, str) or old is None else old.decode()


async def pending_sids(user_id: int) -> list[str]:
    members = await get_redis().smembers(_PENDING.format(uid=user_id))
    return [m if isinstance(m, str) else m.decode() for m in members or ()]


async def forget_pending(user_id: int, sid: str) -> None:
    await get_redis().srem(_PENDING.format(uid=user_id), sid)


async def cancel_quietly(sid: str) -> None:
    """把一条还没确认的会话标成取消(同一台设备又点了一次一键登录,旧的那条作废)"""
    for _ in range(3):
        raw, sess = await load(sid)
        if sess is None or status_of(sess) not in ("pending", "scanned"):
            return
        if await swap(sid, raw, {**sess, "status": "cancelled"}):
            return


def app_in_foreground(user_id: int) -> bool:
    """这个人的手机 App 此刻开着、在前台(实时通道有前台连接,且不是网页版 / 桌面版那种)。

    在前台就只发用户事件(App 当场弹确认页),不在前台才推送。和聊天推送同一个判据(services/chat_push),
    只是把网页、电脑上的连接排除在外。"""
    from ..realtime.hub import hub

    return any(c.foreground and not c.closed and c.device not in WEB_DEVICES
               for c in hub.conns.get(user_id, ()))


# ---------------------------------------------------------------------------
# 已登录的网页和电脑(login_devices)
# ---------------------------------------------------------------------------

def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def device_idle(row: LoginDevice, at: datetime | None = None) -> bool:
    now = at or datetime.now(timezone.utc)
    return _aware(row.last_used_at) < now - timedelta(days=DEVICE_IDLE_DAYS)


async def live_device_by_key(db: AsyncSession, device_key: str) -> LoginDevice | None:
    """带着 device_key 来的一键登录:找到那一行,而且没被移除、没有太久没用"""
    if not device_key:
        return None
    row = await db.scalar(select(LoginDevice).where(LoginDevice.key_hash == hash_key(device_key)))
    if row is None or row.revoked_at is not None or device_idle(row):
        return None
    return row


async def live_devices(db: AsyncSession, user_id: int) -> list[LoginDevice]:
    since = datetime.now(timezone.utc) - timedelta(days=DEVICE_IDLE_DAYS)
    return list(await db.scalars(
        select(LoginDevice)
        .where(LoginDevice.user_id == user_id, LoginDevice.revoked_at.is_(None),
               LoginDevice.last_used_at >= since)
        .order_by(LoginDevice.last_used_at.desc(), LoginDevice.id.desc())))


async def make_room(db: AsyncSession, user_id: int) -> None:
    """要给这个人新建一台设备之前:清掉他早就不用的记录,活的超过上限就把最久没用的移除。

    不另起定时任务 —— 死记录只在这个人自己身上长,在他新登录一台设备的时候顺手清最合适;
    注销账号时整批删掉(routers/auth.delete_account)。
    """
    now = datetime.now(timezone.utc)
    await db.execute(delete(LoginDevice).where(
        LoginDevice.user_id == user_id,
        (LoginDevice.revoked_at < now - timedelta(days=30))
        | (LoginDevice.last_used_at < now - timedelta(days=DEVICE_IDLE_DAYS + 30))))
    live = await live_devices(db, user_id)
    for row in live[MAX_DEVICES - 1:]:
        row.revoked_at = now
