"""明厨亮灶接入与可用性探测(#155/#156/#157)。

## 这不是产品选择,是法定义务

《网络餐饮服务经营者落实食品安全主体责任监督管理规定》
(国家市场监督管理总局令第 123 号,2026-01-27 公布,**2026-06-01 施行**)

**第十三条(平台义务)**:

> 平台提供者应当要求实施"互联网+明厨亮灶"的入网餐饮服务提供者在其主页面
> 显著位置设置"明厨亮灶"的链接标识,并根据入网餐饮服务提供者是否实施
> "互联网+明厨亮灶",在入网餐饮服务提供者列表页面展示"无明厨亮灶"、
> "有明厨亮灶"标识……为入网餐饮服务提供者实施"互联网+明厨亮灶"提供技术支持。
> 相关视频信息应当至少保存十四日。

**第二十五条**对商家是"倡导"(可以不装);**第十三条对平台是"应当"** ——
只要有一家商家装了,平台的三项义务立刻生效。罚则(第三十五条)一万至十万元。

注意列表页要标的是「有」**和「无」两种**,不是给装了的商家加个徽章。

## 为什么必须能自动降级(#156)

记者对现有平台的调查发现的乱象:**标着「明厨亮灶」却黑屏、
摄像头对准天花板、对着墙。** 因为对平台来说标识只是个开关 ——
商家申请、平台点开、从此挂着,设备坏了没人管。

这对我们不只是体验问题:平台在列表页标「有」、用户因此下单、吃坏了,
平台给的就是**虚假标识**。《食品安全法》第一百三十一条:网络食品交易
第三方平台提供者未履行审查义务、使消费者合法权益受损的,与入网食品
经营者**承担连带责任**。

**一个挂着不管的开关,就是在给自己挂责任。**

## 探测分两层,而且不假装

第一层(纯 Python,永远可用)已经覆盖了现实里最常见的两种失效:

1. **拉不到流** —— 断电、断网、地址失效;
2. **拉得到但流停了** —— HLS 的 media sequence 不再推进。
   这一种最阴险:播放器还转圈,监控页面还"在线",实际画面早停了。

第二层(抽帧分析黑屏/静止)需要 ffmpeg。**没有 ffmpeg 就如实说没有** ——
`capabilities()` 会把当前实际能做哪几项报出来,商家端和公开说明都照实显示。
宁可写"当前只检测掉线,不检测黑屏",也不能让人以为我们全都验了。

## 平台不自建视频存储(成本账)

1 路 720p H.264 约 1 Mbps → 一天约 10.8 GB → **14 天约 151 GB/店**。
100 家店 15 TB,还不算带宽。平台无补贴预算,这笔钱出不起,也不该出 ——
摄像头是商家的经营设备,和后厨的灶台一样。

所以视频存储走商家自己的摄像头云服务,平台只存**播放地址 + 探测记录**。
平台的"技术支持"体现在**接入不挑品牌**:通用 RTSP/HLS/FLV 都能接,
不绑定某一家硬件商 —— 绑定等于变相收费。

## 后厨也是劳动者的工作场所(#157)

覆盖范围严格照法规原文:只拍「餐饮食品加工制作的**关键环节**」。
休息区、更衣区、卫生间、员工用餐处一律不拍,首帧人工核验时要一并看。

**不做 AI 行为识别打分**(未戴帽/玩手机自动记违规)。理由和不给骑手
服务分是同一个:误判会落到具体的帮工身上;而一旦记分影响商家生意,
商家就会把压力全部转嫁给这条链上最没有议价能力的人。

我们做的是把画面如实给出去让人看,判断交给看的人和监管部门。
"""
from __future__ import annotations

import asyncio
import logging
import re
import shutil
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx

logger = logging.getLogger("superz.kitchen_cam")

# ---------------------------------------------------------------- 常量即文档
#
# 下面这些数值会原样出现在 /transparency/kitchen-cam 的公开说明里,
# **不另抄一份** —— 抄一份就迟早对不上(dispatch.py 的教训)。

#: 探测间隔(分钟)。30 分钟是个平衡:再密对商家的摄像头云服务是无谓压力,
#: 再疏则一家店可能挂着「有明厨亮灶」半小时以上而实际黑屏
PROBE_INTERVAL_MINUTES = 30

#: 连续失败多少次才降级。**不是一次失败就降** ——
#: 家用宽带抖一下、云服务重启一次都很常见,一次就降会让商家疲于奔命,
#: 最后的结果是没人愿意装
FAIL_STREAK_TO_DEGRADE = 2

#: 恢复需要连续成功多少次。比降级门槛低一点:修好了要让他快点回来
OK_STREAK_TO_RECOVER = 1

#: 单次探测超时(秒)。摄像头云服务慢是常态,给宽一点;
#: 但不能无限等 —— 探测任务要在间隔内跑完全部商家
PROBE_TIMEOUT_SECONDS = 8.0

#: HLS 播放列表两次拉取之间,media sequence 至少要推进才算"流是活的"。
#: 这一项是纯 Python 能做的最有价值的检测:它抓的是
#: 「服务器还在、播放器还转圈、但画面早就停了」这种最难发现的失效
SEQUENCE_STALL_MINUTES = 6

#: 黑屏判据:抽帧后的平均亮度低于这个值(0-255)。
#: 20 是保守的 —— 夜间打烊后的厨房本来就暗,不该误判成"遮挡"
DARK_LUMA_MAX = 20.0

#: 静止判据:连续抽帧之间的平均像素差低于这个值,视为画面没动
#: (镜头前贴了张照片、或者视频源卡在一帧)
STILL_DIFF_MAX = 1.5

#: 抽几帧做黑屏/静止判断
SAMPLE_FRAMES = 3

#: 允许的播放协议。**不绑定品牌** —— 萤石、海康、大华、通用 NVR 都能接
ALLOWED_SCHEMES = ("https", "http", "rtsp", "rtmp")

#: 不该出现在明厨亮灶画面里的区域(首帧人工核验的清单,#157)。
#: 法规要求覆盖的是「加工制作的关键环节」,不是整个店
MUST_NOT_COVER = [
    "员工休息区", "更衣区", "卫生间", "员工用餐处", "办公区",
    "收银台(会拍到顾客付款)", "任何能持续拍到顾客面部的角度",
]

#: 应当覆盖的关键环节
SHOULD_COVER = ["操作台", "灶台", "备餐区", "洗消区"]

#: 平台明确不做的(进公开说明,和骑手端那份承诺一个性质)
NEVER_DO = [
    "不做 AI 行为识别打分 —— 不给后厨员工记违规、不自动扣分。"
    "误判会落到具体的人身上,而压力最终会被转嫁给最没有议价能力的那个人",
    "不给「有明厨亮灶」加权排序、不做流量倾斜 —— "
    "一旦标识能换流量,就会有人对着天花板装一个来骗标识",
    "不向普通用户开放历史录像回看 —— 只能看实时画面。"
    "开这个口子等于任何人可以回看任何一家后厨的任何时刻,那不是透明,是监控外包",
    "不卖摄像头硬件、不绑定单一品牌 —— 绑定等于变相收费",
]

#: 状态机
STATUS_NONE = "none"          # 没装(法规里的「无明厨亮灶」)
STATUS_PENDING = "pending"    # 已提交,等首帧人工核验
STATUS_ACTIVE = "active"      # 在线可看(法规里的「有明厨亮灶」)
STATUS_DEGRADED = "degraded"  # 装了但当前不可用

#: **列表页只认 active。** pending 和 degraded 一律显示「无明厨亮灶」——
#: 法规要的是如实标识,不是"他有这个意愿"。看不到就是没有
LISTED_AS_HAS = (STATUS_ACTIVE,)


@dataclass(frozen=True)
class ProbeResult:
    ok: bool
    #: 机器可读的失败原因;ok 时为空
    reason: str
    #: 给商家看的人话
    message: str
    #: 这次实际做了哪几项检查(诚实起见,前端会显示出来)
    checks: tuple[str, ...]
    #: HLS media sequence,用于下次比对是否推进
    sequence: int | None = None


def capabilities() -> dict:
    """当前这套部署实际能检测哪几项。

    **不假装。** ffmpeg 不在镜像里时,黑屏/静止检测就是做不了,
    那就照实说「当前只检测掉线与流停滞」,而不是让商家和用户
    以为我们把画面也验了。
    """
    has_ffmpeg = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))
    return {
        "reachability": True,       # 拉不拉得到流
        "stream_alive": True,       # 流是不是还在推进
        "dark_frame": has_ffmpeg,   # 黑屏
        "still_frame": has_ffmpeg,  # 画面静止(镜头前贴了张照片)
        "note": ("完整检测:掉线、流停滞、黑屏、画面静止" if has_ffmpeg else
                 "当前只检测掉线与流停滞。黑屏与画面静止需要 ffmpeg,"
                 "这套部署没装 —— 与其含糊,不如照实说"),
    }


def normalize_url(url: str) -> str:
    """校验并规范播放地址。不合法就抛 ValueError(调用方转 422)。"""
    url = (url or "").strip()
    if not url:
        raise ValueError("请填写摄像头播放地址")
    if len(url) > 300:
        raise ValueError("地址过长")
    parsed = urlparse(url)
    if parsed.scheme not in ALLOWED_SCHEMES:
        raise ValueError(
            f"只支持 {'/'.join(ALLOWED_SCHEMES)} 开头的地址;"
            "萤石云、海康、大华的取址方法见接入说明")
    if not parsed.netloc:
        raise ValueError("地址不完整")
    # 内网地址挡掉:一来公网播不了,二来防止拿平台当内网探测器
    host = parsed.hostname or ""
    if (host in ("localhost", "127.0.0.1", "0.0.0.0", "::1")
            or host.startswith(("192.168.", "10.", "169.254."))
            or re.match(r"^172\.(1[6-9]|2\d|3[01])\.", host)):
        raise ValueError("这是内网地址,顾客在外面播不了。请填公网可访问的地址")
    return url


_SEQ_RE = re.compile(r"#EXT-X-MEDIA-SEQUENCE:\s*(\d+)")


async def probe(url: str, *, last_sequence: int | None = None) -> ProbeResult:
    """探一次。**任何异常都返回 ProbeResult,不往外抛** ——
    探测失败不该让整个定时任务挂掉。
    """
    try:
        return await _probe_inner(url, last_sequence)
    except Exception as exc:  # noqa: BLE001 —— 见上
        logger.warning("明厨亮灶探测异常 url=%s err=%s", url[:60], exc)
        return ProbeResult(
            ok=False, reason="probe_error",
            message="探测时出错,稍后会再试一次",
            checks=("reachability",))


async def _probe_inner(url: str, last_sequence: int | None) -> ProbeResult:
    checks: list[str] = ["reachability"]
    scheme = urlparse(url).scheme

    # RTSP/RTMP 没法用 HTTP 探。没有 ffmpeg 时**只能承认探不了** ——
    # 装作探过并判 ok,等于把「有明厨亮灶」发给了一个我们根本没看过的流
    if scheme in ("rtsp", "rtmp"):
        if not capabilities()["dark_frame"]:
            return ProbeResult(
                ok=False, reason="unprobeable",
                message="这套部署暂时探测不了 rtsp/rtmp 地址,"
                        "请改用 HLS(.m3u8)地址,或联系平台",
                checks=("reachability",))
        return await _probe_with_ffmpeg(url, checks)

    async with httpx.AsyncClient(
            timeout=PROBE_TIMEOUT_SECONDS, follow_redirects=True) as client:
        try:
            resp = await client.get(url)
        except httpx.HTTPError:
            return ProbeResult(
                ok=False, reason="unreachable",
                message="连不上摄像头 —— 多半是断电、断网,或者地址变了",
                checks=tuple(checks))
    if resp.status_code >= 400:
        return ProbeResult(
            ok=False, reason=f"http_{resp.status_code}",
            message=f"摄像头服务返回 {resp.status_code},地址可能已失效",
            checks=tuple(checks))

    body = resp.text[:20000] if "mpegurl" in (
        resp.headers.get("content-type", "").lower()) or url.endswith(
            ".m3u8") else ""

    sequence = None
    if body:
        checks.append("stream_alive")
        m = _SEQ_RE.search(body)
        sequence = int(m.group(1)) if m else None
        # **流停滞**:序号没推进 = 服务器还在但没有新画面了。
        # 这一种最阴险,播放器还转圈,人以为在线
        if (sequence is not None and last_sequence is not None
                and sequence <= last_sequence):
            return ProbeResult(
                ok=False, reason="stalled",
                message="能连上,但画面已经停了(没有新的视频片段)—— "
                        "摄像头可能死机了,重启一下试试",
                checks=tuple(checks), sequence=sequence)

    if capabilities()["dark_frame"]:
        frame_result = await _probe_with_ffmpeg(url, checks)
        if not frame_result.ok:
            return ProbeResult(
                ok=False, reason=frame_result.reason,
                message=frame_result.message,
                checks=frame_result.checks, sequence=sequence)
        checks = list(frame_result.checks)

    return ProbeResult(ok=True, reason="", message="画面正常",
                       checks=tuple(checks), sequence=sequence)


async def _probe_with_ffmpeg(url: str, checks: list[str]) -> ProbeResult:
    """抽帧看黑屏与静止。需要 ffmpeg;没有就不会被调用。

    用 signalstats 的 YAVG(平均亮度)与相邻帧差,不引 numpy/opencv ——
    为一个半小时跑一次的探测拉进来几百 MB 的依赖不划算。
    """
    checks = list(checks) + ["dark_frame", "still_frame"]
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error",
        "-rw_timeout", str(int(PROBE_TIMEOUT_SECONDS * 1_000_000)),
        "-i", url,
        "-vf", f"select='lt(n\\,{SAMPLE_FRAMES * 10})',"
               f"signalstats,metadata=print:key=lavfi.signalstats.YAVG",
        "-frames:v", str(SAMPLE_FRAMES), "-f", "null", "-",
    ]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE)
        _, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=PROBE_TIMEOUT_SECONDS * 2)
    except (asyncio.TimeoutError, FileNotFoundError, OSError):
        return ProbeResult(
            ok=False, reason="unreachable",
            message="拉不到画面 —— 多半是断电、断网,或者地址变了",
            checks=tuple(checks))

    text = stderr.decode("utf-8", "ignore")
    lumas = [float(v) for v in re.findall(
        r"lavfi\.signalstats\.YAVG=([\d.]+)", text)]
    if not lumas:
        return ProbeResult(
            ok=False, reason="no_frames",
            message="连上了但取不到画面,摄像头可能没在推流",
            checks=tuple(checks))

    if max(lumas) < DARK_LUMA_MAX:
        return ProbeResult(
            ok=False, reason="dark",
            message="画面是黑的 —— 镜头被挡住了,或者后厨没开灯",
            checks=tuple(checks))

    # 亮度完全不变 = 很可能是一张静止图。这是个弱信号,
    # 只在样本足够时才用,且阈值给得保守 —— 宁可漏判不可错判
    if len(lumas) >= SAMPLE_FRAMES and (max(lumas) - min(lumas)) < STILL_DIFF_MAX:
        return ProbeResult(
            ok=False, reason="still",
            message="画面一直没有变化 —— 请确认镜头前没有遮挡物,"
                    "并且拍的是正在使用的操作区",
            checks=tuple(checks))

    return ProbeResult(ok=True, reason="", message="画面正常",
                       checks=tuple(checks))


def next_status(current: str, *, ok: bool, fail_streak: int,
                ok_streak: int) -> str:
    """探测结果 → 新状态。**降级要迟钝,恢复要灵敏。**

    降级迟钝:家用宽带抖一下、云服务重启一次都很常见,一次失败就降级
    会让商家疲于奔命,最后没人愿意装 —— 而我们要的是更多人装。

    恢复灵敏:他刚修好,不该让他再等半小时。
    """
    if current == STATUS_NONE:
        return STATUS_NONE          # 没装的不参与
    if current == STATUS_PENDING:
        return STATUS_PENDING       # 等人工核验,探测结果不改它的状态
    if ok:
        return (STATUS_ACTIVE if ok_streak >= OK_STREAK_TO_RECOVER
                else current)
    return (STATUS_DEGRADED if fail_streak >= FAIL_STREAK_TO_DEGRADE
            else current)


def listed_label(status: str) -> str:
    """列表页标识。法规第十三条要求的是「有明厨亮灶」/「无明厨亮灶」两种,
    所以**每一个商家**都有标识,不是给装了的加徽章。
    """
    return "有明厨亮灶" if status in LISTED_AS_HAS else "无明厨亮灶"


def public_spec() -> dict:
    """公开说明。数值全部从上面的常量读,**不另抄一份**。"""
    return {
        "legal_basis": {
            "regulation": "网络餐饮服务经营者落实食品安全主体责任监督管理规定",
            "issuer": "国家市场监督管理总局令第 123 号",
            "published": "2026-01-27",
            "effective": "2026-06-01",
            "platform_duty": "第十三条:平台应当要求实施「互联网+明厨亮灶」的商家"
                             "在主页面显著位置设置链接标识,并在商家列表页展示"
                             "「有明厨亮灶」「无明厨亮灶」标识,同时为商家提供技术支持",
            "merchant_duty": "第二十五条:倡导商家实施;实施的应当设置链接标识"
                             "并保证设备正常运转",
            "retention": "相关视频信息应当至少保存十四日",
        },
        "how_we_verify": {
            "interval_minutes": PROBE_INTERVAL_MINUTES,
            "fail_streak_to_degrade": FAIL_STREAK_TO_DEGRADE,
            "ok_streak_to_recover": OK_STREAK_TO_RECOVER,
            "capabilities": capabilities(),
            "note": "探测失败会让标识**自动变回「无明厨亮灶」** —— "
                    "不是加个小字提示,是标识本身变掉。"
                    "你看到的标识和实际能不能看,必须是同一件事",
        },
        "coverage": {
            "should_cover": SHOULD_COVER,
            "must_not_cover": MUST_NOT_COVER,
            "why": "法规要求覆盖的是「加工制作的关键环节」,不是整个店。"
                   "后厨里站着的也是劳动者 —— 休息区、更衣区、卫生间一律不拍,"
                   "首次接入时人工核验会一并检查",
        },
        "storage": {
            "platform_stores": "只存播放地址与探测记录,不存视频",
            "why": "1 路 720p 存 14 天约 151 GB。平台无补贴预算,这笔钱出不起,"
                   "也不该出 —— 摄像头是商家的经营设备。"
                   "视频存储走商家自己的摄像头云服务",
            "vendor_lock": "接入不挑品牌,通用 RTSP/HLS/FLV 都能接。"
                           "绑定单一品牌等于变相收费",
        },
        "never_do": NEVER_DO,
    }


#: 规则可以改,但不能悄悄改
CHANGELOG = [
    {
        "date": "2026-07-31",
        "change": "上线明厨亮灶接入与自动降级",
        "why": "123 号令 2026-06-01 已施行,平台侧标识与技术支持是法定义务;"
               "自动降级是为了不给虚假标识背书 —— "
               "行业里「标着明厨亮灶却黑屏、镜头对着天花板」的乱象很普遍,"
               "而平台标了「有」、用户因此下单出了事,是要负连带责任的",
    },
]


# ---------------------------------------------------------------------------
# 定时探测(#156):标识必须能自动降级
# ---------------------------------------------------------------------------


async def sweep(db, *, limit: int = 200) -> list[dict]:
    """探一轮所有已接入的商家,按结果升降状态。

    返回状态发生变化的清单 [{merchant_id, owner_id, name, old, new, note}],
    供调用方推送商家 —— 掉线了要让他知道,否则他不会去修。

    **只探 active/degraded。** pending 在等人工核验,探测结果不改它的状态;
    none 压根没装。
    """
    from sqlalchemy import select

    from ..models import Merchant

    shops = (await db.scalars(
        select(Merchant)
        .where(Merchant.kitchen_cam_status.in_(
            (STATUS_ACTIVE, STATUS_DEGRADED)))
        .order_by(Merchant.kitchen_cam_checked_at.asc().nullsfirst())
        .limit(limit))).all()

    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    changes: list[dict] = []

    for shop in shops:
        result = await probe(shop.kitchen_cam_url,
                             last_sequence=shop.kitchen_cam_sequence)
        old = shop.kitchen_cam_status
        if result.ok:
            shop.kitchen_cam_ok_streak += 1
            shop.kitchen_cam_fail_streak = 0
        else:
            shop.kitchen_cam_fail_streak += 1
            shop.kitchen_cam_ok_streak = 0

        new = next_status(old, ok=result.ok,
                          fail_streak=shop.kitchen_cam_fail_streak,
                          ok_streak=shop.kitchen_cam_ok_streak)
        shop.kitchen_cam_status = new
        shop.kitchen_cam_checked_at = now
        shop.kitchen_cam_reason = result.reason
        shop.kitchen_cam_note = result.message[:200]
        if result.sequence is not None:
            shop.kitchen_cam_sequence = result.sequence

        if new != old:
            changes.append({
                "merchant_id": shop.id, "owner_id": shop.owner_id,
                "name": shop.name, "old": old, "new": new,
                "note": result.message,
            })

    await db.commit()
    return changes


async def maybe_sweep(now=None) -> int:
    """每 PROBE_INTERVAL_MINUTES 探一轮。Redis 锁防多实例重复跑。

    掉线的商家会收到推送 —— 话术是「你的设备可能出问题了」而**不是
    「你违规了」**。绝大多数掉线是断电或断网,不是故意遮挡;
    把商家当贼防,他下次就懒得装了,而我们要的是更多人装。
    """
    from datetime import datetime, timezone

    from ..db import SessionLocal
    from ..redis_client import get_redis

    now = now or datetime.now(timezone.utc)
    slot = now.strftime("%Y%m%d%H") + str(
        now.minute // PROBE_INTERVAL_MINUTES)
    redis = get_redis()
    if not await redis.set(f"kitchencam:sweep:{slot}", 1,
                           ex=PROBE_INTERVAL_MINUTES * 60, nx=True):
        return 0

    async with SessionLocal() as db:
        changes = await sweep(db)

    if changes:
        from .push import push_to_user
        for c in changes:
            if c["new"] == STATUS_DEGRADED:
                await push_to_user(
                    c["owner_id"], "明厨亮灶掉线了",
                    f"{c['note']};顾客现在看到的是「无明厨亮灶」,"
                    "恢复后会自动改回来",
                    {"type": "kitchen_cam"})
            elif c["new"] == STATUS_ACTIVE:
                await push_to_user(
                    c["owner_id"], "明厨亮灶已恢复",
                    "画面正常了,顾客又能看到「有明厨亮灶」",
                    {"type": "kitchen_cam"})
    return len(changes)
