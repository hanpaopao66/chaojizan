"""实发一条推送,验一条通道(#384)。

## 为什么必须有这个

各家厂商的推送接口**只回一句笼统的错误**:签名算错、时间戳单位错、消息类别标错、
包名填错,回来的都是「鉴权失败」「参数错误」这种。不实发一条根本看不出来配没配对,
而"推送没到"这件事用户不会来报 bug —— 等发现时已经过去几周了。

所以每配好一家,**当场用这个命令实发一条到自己手机上**。收到了才算接通。

## 怎么用

先在手机上装好对应的 App、登录一次(客户端会把 token 报给服务端),然后在部署机上:

    # 看看这个人名下都有哪些设备
    docker exec superz-api python -m scripts.push_probe --user 42 --list

    # 往其中一台实发一条
    docker exec superz-api python -m scripts.push_probe --user 42 --channel hms

    # 或者直接给 token(还没登录过、手动从日志里抄的)
    docker exec superz-api python -m scripts.push_probe --channel xiaomi --token abc123

**它绕过前台判断、免打扰、通知偏好**:那些是业务规则,这里要验的是通道本身通不通。
"""
import argparse
import asyncio
import sys

from sqlalchemy import select

from app.db import SessionLocal
from app.models import PushDevice
from app.services.push_channels import apns, hms, oppo, vivo, xiaomi

MODS = {"apns": apns, "hms": hms, "xiaomi": xiaomi, "oppo": oppo, "vivo": vivo}


async def list_devices(user_id: int) -> int:
    async with SessionLocal() as db:
        rows = list(await db.scalars(select(PushDevice)
                                     .where(PushDevice.user_id == user_id)
                                     .order_by(PushDevice.id)))
    if not rows:
        print(f"用户 {user_id} 名下一台设备都没有 —— 先在手机上登录一次")
        return 1
    print(f"用户 {user_id} 名下 {len(rows)} 台设备:")
    for r in rows:
        state = "在用" if r.disabled_at is None else f"已下线({r.disabled_at:%m-%d %H:%M})"
        print(f"  #{r.id} {r.channel:7} {r.app:9} "
              f"{'沙箱' if r.sandbox else '生产'} {state}  token={r.token[:16]}…")
    return 0


async def probe(channel: str, token: str, app: str, sandbox: bool,
                title: str, content: str) -> int:
    mod = MODS.get(channel)
    if mod is None:
        print(f"✗ 不认识的通道:{channel};认得的是 {'、'.join(MODS)}")
        return 2
    if not mod.configured():
        print(f"✗ {channel} 没配齐 —— 看 docs/INTEGRATIONS.md 第 2 节,把 .env.prod 填完")
        return 2
    print(f"→ {channel} 发一条到 {token[:16]}…({app}{'、沙箱' if sandbox else ''})")
    r = await mod.send(token, title, content, {"type": "probe"},
                       app=app, sandbox=sandbox, collapse_id="probe")
    if r.ok:
        print("✓ 对方收下了。**去手机上看一眼通知栏** —— "
              "接口成功只说明请求对了,弹没弹出来是另一回事(通知权限、渠道被关都会吞掉它)")
        return 0
    print(f"✗ 没发出去:{r.error}")
    if r.gone:
        print("  (这个 token 被判成永久失效:多半是沙箱/生产发反了,或者 App 已经卸载)")
    return 1


def main() -> int:
    ap = argparse.ArgumentParser(description="实发一条推送验通道")
    ap.add_argument("--user", type=int, help="按用户找设备")
    ap.add_argument("--list", action="store_true", help="只列出这个人的设备,不发")
    ap.add_argument("--channel", help="apns / hms / xiaomi / oppo / vivo")
    ap.add_argument("--token", help="直接给设备 token(不给就从 --user 名下找)")
    ap.add_argument("--app", default="user", choices=("user", "merchant", "rider"))
    ap.add_argument("--sandbox", action="store_true", help="APNs 沙箱(Xcode / TestFlight 装的包)")
    ap.add_argument("--title", default="超级赞")
    ap.add_argument("--content", default="这是一条测试推送,收到说明通道通了")
    a = ap.parse_args()

    if a.list:
        if not a.user:
            print("--list 要配 --user")
            return 2
        return asyncio.run(list_devices(a.user))

    token, app, sandbox = a.token, a.app, a.sandbox
    channel = a.channel
    if not token:
        if not a.user or not channel:
            print("要么给 --token,要么给 --user 和 --channel")
            return 2

        async def pick() -> PushDevice | None:
            async with SessionLocal() as db:
                return await db.scalar(select(PushDevice).where(
                    PushDevice.user_id == a.user, PushDevice.channel == channel,
                    PushDevice.disabled_at.is_(None)).order_by(PushDevice.id.desc()))

        d = asyncio.run(pick())
        if d is None:
            print(f"✗ 用户 {a.user} 名下没有在用的 {channel} 设备")
            return 1
        token, app, sandbox = d.token, d.app, d.sandbox
    if not channel:
        print("要给 --channel")
        return 2
    return asyncio.run(probe(channel, token, app, sandbox, a.title, a.content))


if __name__ == "__main__":
    sys.exit(main())
