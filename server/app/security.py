import time

import bcrypt
import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import settings
from .db import get_db
from .models import User

bearer = HTTPBearer(auto_error=False)


def hash_password(raw: str) -> str:
    return bcrypt.hashpw(raw.encode(), bcrypt.gensalt()).decode()


def verify_password(raw: str, hashed: str) -> bool:
    return bcrypt.checkpw(raw.encode(), hashed.encode())


def create_token(user: User, *, login_device_id: int | None = None) -> str:
    """登录 token。

    [login_device_id]:扫码 / 一键登录签给网页版、桌面版的 token 带上那台设备
    (login_devices.id,写在 `ld` 里)。带了它的 token 每次请求都回库看那台设备还在不在 ——
    用户在手机上「移除」之后下一次请求就 401(见 get_current_user)。手机上登录的 token 不带。
    """
    payload = {
        "sub": str(user.id),
        "role": user.role.value,
        "exp": int(time.time()) + settings.jwt_expire_minutes * 60,
    }
    if login_device_id is not None:
        payload["ld"] = int(login_device_id)
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


async def login_device_alive(db: AsyncSession, payload: dict) -> bool:
    """token 里带的那台网页 / 电脑(`ld`)还在不在:没被移除、而且是这个人的。

    JWT 自己吊销不了。扫码登录的会话要做到「手机上一移除,那边立刻退出」,
    就只能像助手令牌一样每次回库查一行 —— 代价是一次主键查询,只有带 `ld` 的会话付。
    实时网关(realtime/gateway.py)连上来时也走这里。
    """
    from .models import LoginDevice

    try:
        device_id = int(payload.get("ld"))
        user_id = int(payload.get("sub") or 0)
    except (TypeError, ValueError):
        return False
    row = await db.get(LoginDevice, device_id)
    return row is not None and row.revoked_at is None and row.user_id == user_id


async def socket_user(db: AsyncSession, token: str) -> User | None:
    """实时通道(WebSocket)的登录校验:**和 get_current_user 同一套判据**,外加助手令牌一律不许连。

    WebSocket 挂不上 `Depends(get_current_user)`,以前每条通道自己 `jwt.decode`:
    手机上「移除」了那台电脑、账号注销了,HTTP 请求当场 401,老的订单 / 商家通道却照连不误,
    一直连到令牌 30 天后过期。判据只写这一处,三条通道(ws.py 两条、realtime/gateway.py)都调它,
    单测 test_socket_auth 钉住没有别处再自己解登录令牌。

    - 签名、有效期;
    - 助手令牌(scope=agent)不许连:它能碰什么是按 HTTP 接口逐条放的白名单,实时通道不在里面;
    - 扫码登录的网页 / 电脑(`ld`):那台设备还在(login_device_alive);
    - 账号还在、没注销(和 get_current_user 一样,deleted_at 和手机号前缀两条都判)。

    角色和归属由各条通道自己判。返回的 User 属于传进来的 db。
    """
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
        user_id = int(payload.get("sub") or 0)
    except (jwt.PyJWTError, TypeError, ValueError):
        return None
    if payload.get("scope") == "agent":
        return None
    if payload.get("ld") is not None and not await login_device_alive(db, payload):
        return None
    user = await db.get(User, user_id)
    if user is None or user.deleted_at is not None or user.phone.startswith("del"):
        return None
    return user


#: AI 助手令牌能碰的接口。(方法, 路径正则) —— **全匹配**,**按权限分开**。
#:
#: ## 为什么是白名单,而且是全匹配的正则
#:
#: 黑名单要求每加一个新接口就有人记得去禁它,忘一次就是一条没人看守的路。
#: 白名单反过来:新接口默认不开放,要开是一个显式动作。
#:
#: 而白名单本身也不能用前缀匹配 —— 第一版写的是「GET /merchants 前缀下
#: 子路径一律放行」,单测当场抓出 `GET /merchants/me/order-flags` 被放行:
#: `/merchants/me/*` 是**商家自己的经营数据**(还包括 finance/statement.csv),
#: 一个用来点外卖的助手不该能读它。前缀一松,松掉的地方自己长出来。
#:
#: ## 为什么分权限
#:
#: 一个令牌能做哪几件事,签发时由人勾选(agent_tokens.scopes)。只勾了「点餐」的
#: 令牌泄露了,对方发不了视频;只给开发者后台发包用的,下不了单。
#: 能做的事越少,令牌丢了损失越小 —— 所以每项权限单列一张表,不合成一张大的。
#:
#: ## 每项权限里都没有的
#:
#: **付款**(点餐只到「创建一张待支付订单」,付款那一下永远在用户自己的 App 里
#: 由人按 —— 令牌泄露也花不掉一分钱)、退款、改地址、申诉、地址簿、钱包与提现、
#: 删稿、改小程序的密钥和域名、实名认证、签协议 —— 这些要么动钱、要么动身份、
#: 要么删了回不来,留给人自己在 App 或开发者后台里做。

#: 每项权限都能用的:我是谁、这个令牌能做哪几件事(MCP 据此只列出能用的工具)
AGENT_COMMON: tuple[tuple[str, str], ...] = (
    ("GET", r"/auth/me"),
    ("GET", r"/auth/agent-tokens/current"),
)

#: 点餐:找店、看菜、算配送费、看自己的订单,加上「创建一张待支付订单」
AGENT_ORDER: tuple[tuple[str, str], ...] = (
    ("GET", r"/merchants"),                  # 附近的店
    ("GET", r"/merchants/search"),
    ("GET", r"/merchants/\d+"),              # 店铺详情(只认数字 id)
    ("GET", r"/merchants/\d+/dishes"),       # 菜单
    ("GET", r"/orders"),                     # 我的订单
    ("GET", r"/orders/delivery-fee"),        # 算配送费(不下单)
    ("GET", r"/orders/[0-9a-f]{8,40}"),      # 订单详情(订单号是十六进制串)
    ("GET", r"/transparency/[a-z-]+"),       # 公开口径,本来也不需要登录
    ("POST", r"/orders"),                    # ← 只到「创建待支付订单」为止
)

_VID = r"sv[1-9A-HJ-NP-Za-km-z]{10}"         # services/video.py 的 VID_RE
_UPLOAD = r"[0-9a-f]{32}"                    # 分片上传的 id

#: 发视频:建稿件、传原片和封面、挂分 P、改标题简介、提交审核、看自己稿件的进度。
#: **提交之后是「审核中」,由平台的人审** —— 助手能替你投稿,不能替你过审。
#: 没有:删稿、删分 P、申诉、放弃改动,以及点赞投币评论弹幕这些「以你的名义对别人做事」的
AGENT_VIDEO: tuple[tuple[str, str], ...] = (
    ("GET", r"/video/v1/zones"),                          # 分区(选分区用)
    ("POST", r"/video/v1/uploads/videos"),                # 建稿件(草稿)
    ("PATCH", rf"/video/v1/videos/{_VID}"),               # 改标题、简介、标签、封面
    ("POST", rf"/video/v1/videos/{_VID}/parts"),          # 挂上传好的原片(开始转码)
    ("POST", rf"/video/v1/videos/{_VID}/submit"),         # 提交审核
    ("GET", r"/video/v1/creator/videos"),                 # 我的稿件
    ("GET", rf"/video/v1/creator/videos/{_VID}"),         # 一个稿件的进度与驳回原因
    ("POST", r"/media/v1/uploads"),                       # 建分片上传(原片)
    ("GET", rf"/media/v1/uploads/{_UPLOAD}"),             # 断点续传:看收到了哪几片
    ("PUT", rf"/media/v1/uploads/{_UPLOAD}/chunks/\d+"),
    ("POST", rf"/media/v1/uploads/{_UPLOAD}/complete"),
    ("POST", r"/media/v1/upload"),                        # 整块上传(封面图)
)

_APPID = r"sz[0-9a-f]{16}"                   # services/miniapp_platform.py 的 APPID_PATTERN

#: 发布小程序和小游戏(开发者账号):建应用、改基本信息、传包、设体验版、提交审核、撤回、
#: **审核通过的版本**发布上线、回滚、看审核结论和数据。
#: **审核仍由平台的人做** —— 没过审的版本发布不了,这一点在 miniapp_publish 里,不在这里。
#: 没有:下架与删除应用、密钥、域名、能力申请、体验者、实名认证、签协议、申诉
AGENT_MINIAPP: tuple[tuple[str, str], ...] = (
    ("GET", r"/dev/v1/me"),                               # 开发者账号(认证、协议的状态)
    ("GET", r"/dev/v1/messages"),                         # 平台通知
    ("GET", r"/dev/v1/apps"),
    ("POST", r"/dev/v1/apps"),                            # 建应用 / 小游戏
    ("GET", rf"/dev/v1/apps/{_APPID}"),
    ("PUT", rf"/dev/v1/apps/{_APPID}"),                   # 名称、简介、图标、分类
    ("POST", rf"/dev/v1/apps/{_APPID}/versions"),         # 传包(平台逐条校验)
    ("GET", rf"/dev/v1/apps/{_APPID}/versions"),
    ("GET", rf"/dev/v1/apps/{_APPID}/versions/\d+"),
    ("POST", rf"/dev/v1/apps/{_APPID}/versions/\d+/trial"),     # 设为体验版
    ("POST", rf"/dev/v1/apps/{_APPID}/versions/\d+/submit"),    # 提交审核
    ("POST", rf"/dev/v1/apps/{_APPID}/versions/\d+/withdraw"),  # 撤回审核
    ("POST", rf"/dev/v1/apps/{_APPID}/versions/\d+/release"),   # 审核通过的版本发布上线
    ("POST", rf"/dev/v1/apps/{_APPID}/rollback"),                # 回到之前的线上版本
    ("GET", rf"/dev/v1/apps/{_APPID}/decisions"),         # 审核结论(驳回原因)
    ("GET", rf"/dev/v1/apps/{_APPID}/stats"),
)

#: 权限名 → 放行的接口。签发时勾的就是这几个键
AGENT_SCOPES: dict[str, tuple[tuple[str, str], ...]] = {
    "order": AGENT_ORDER,
    "video": AGENT_VIDEO,
    "miniapp": AGENT_MINIAPP,
}
#: 给人看的名字(签发页、拒绝的话里用)
AGENT_SCOPE_LABELS = {"order": "点餐", "video": "发视频", "miniapp": "发布小程序和小游戏"}
#: 哪种账号能勾哪几项:点餐、发视频是用户端账号的事,发布小程序是开发者账号的事。
#: 商家、骑手、平台账号不签助手令牌(商家的开放接口走 API Key,另一套)
AGENT_SCOPES_BY_ROLE: dict[str, tuple[str, ...]] = {
    "customer": ("order", "video"),
    "developer": ("miniapp",),
}


def agent_can(method: str, path: str, scopes=("order",)) -> bool:
    """这个方法+路径是否在(这几项权限的)助手令牌能力范围内。**默认拒绝。**

    **全匹配**,不是前缀匹配:`POST /orders` 放行而 `POST /orders/x/pay/mock`
    不放行,靠的就是全匹配 —— 前缀匹配的话后者也会被放进来。
    不认识的权限名什么都不放行。
    """
    import re

    p = path.rstrip("/") or "/"
    rules = AGENT_COMMON + tuple(r for s in scopes for r in AGENT_SCOPES.get(s, ()))
    return any(m == method and re.fullmatch(pat, p) for m, pat in rules)


def agent_denied(scopes) -> str:
    """撞到能力边界时的那句话:说清这个令牌能做什么、这件事该去哪做,模型才不会一直重试"""
    can = "、".join(AGENT_SCOPE_LABELS.get(s, s) for s in scopes) or "(没有)"
    return (f"AI 助手令牌不能做这件事(这个令牌能做:{can})。"
            "付款、退款、改地址、删稿、改密钥和域名、实名认证这些只能自己在 App 或开发者后台里操作;"
            "要让助手做别的,在 App「设置 → AI 助手」(开发者在开发者后台「账号」)签一个勾了那一项的令牌。")


async def _check_agent_token(db: AsyncSession, payload: dict) -> dict:
    """助手令牌还有效吗 —— 吊销、过期、不存在一律 401。有效的话返回它的 id、名字和权限。

    JWT 自己吊销不了,所以每次都回库查一行。代价是一次主键查询,
    换来的是「用户在设置里点吊销,下一秒就真的不能用了」。
    权限也以库里这一行为准,不看 JWT 里写了什么。
    """
    from datetime import datetime, timezone

    from .models import AgentToken

    jti = payload.get("jti") or ""
    row = await db.scalar(select(AgentToken).where(AgentToken.jti == jti))
    if row is None or row.revoked_at is not None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED,
                            "这个助手令牌已被吊销")
    now = datetime.now(timezone.utc)
    exp = row.expires_at
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    if exp <= now:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "这个助手令牌已过期")
    info = {"id": row.id, "name": row.name, "scopes": list(row.scopes or ["order"]),
            "expires_at": exp.isoformat()}
    row.last_used_at = now          # 让用户看得出哪个还在用、哪个可以清掉
    await db.commit()
    return info


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: AsyncSession = Depends(get_db),
) -> User:
    if credentials is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "未登录")
    try:
        payload = jwt.decode(credentials.credentials, settings.jwt_secret, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "登录已过期,请重新登录")
    # AI 助手令牌:能力范围在这里收口。
    #
    # 放在 get_current_user 而不是各个路由上,是因为**这里是唯一入口** ——
    # 所有需要登录的接口都经过它,漏不掉;而逐个路由加限制,
    # 漏一个就是一条没人看守的路。
    if payload.get("scope") == "agent":
        agent = await _check_agent_token(db, payload)
        # 打个标,记录交给中间件 —— 只有那儿同时拿得到状态码和耗时
        request.state.api_client = ("agent", None, int(payload["sub"]))
        request.state.agent_token = agent
        if not agent_can(request.method, request.url.path, agent["scopes"]):
            raise HTTPException(status.HTTP_403_FORBIDDEN, agent_denied(agent["scopes"]))
    # 扫码登录的网页版 / 桌面版会话:那台设备在手机上被移除了,这里就 401。
    # 放在唯一入口里,和上面助手令牌同一个理由 —— 逐个路由加,漏一个就是一台移除不掉的电脑
    if payload.get("ld") is not None:
        if not await login_device_alive(db, payload):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED,
                                "这台设备已在手机上退出登录,请重新扫码登录")
        # /auth/refresh 续期时要原样带上;扫码 / 确认接口据此认出「这是网页、电脑上的会话」
        request.state.login_device_id = int(payload["ld"])
    user = await db.get(User, int(payload["sub"]))
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "用户不存在")
    # 已注销:旧 token 立即失效。
    #
    # 判据是 `deleted_at`,不再是手机号长什么样。前缀那条留着兜两种情况:
    # ① 存量行还没跑过数据修复脚本;② 迁移被回滚(0108 downgrade 会
    # 删掉这一列)。少认一行墓碑的后果是旧 token 还能用,所以宁可两条都判。
    if user.deleted_at is not None or user.phone.startswith("del"):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "账号已注销")
    return user


async def get_current_user_optional(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: AsyncSession = Depends(get_db),
) -> User | None:
    """未登录返回 None 而不是 401。

    只给「同一个路径既服务公开内容也服务私密内容」的地方用
    (目前是 /uploads 老 URL 兼容):公开文件不该因为没带 token 就 401,
    私密文件再由调用方自己判 None 并抛 401。
    """
    if credentials is None:
        return None
    try:
        # **按关键字传,不按位置。**
        #
        # 原来是 `get_current_user(credentials, db)` —— 位置传参。
        # 给 get_current_user 加了 `request` 作第一个参数之后,
        # credentials 落到了 request 位、db 落到了 credentials 位,
        # 于是 `AsyncSession object has no attribute 'credentials'`,500。
        #
        # 而这条路径只有「登录用户访问私密的老 /uploads URL」才走到,
        # 单测和大部分 e2e 都碰不到 —— 全套跑到第 51 个套件才炸出来。
        return await get_current_user(
            request=request, credentials=credentials, db=db)
    except HTTPException:
        return None


def require_role(*roles: str):
    async def checker(user: User = Depends(get_current_user)) -> User:
        if user.role.value not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "当前角色无权访问")
        return user

    return checker
