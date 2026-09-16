"""小米推送直连(#384 第二步)。

小米这条不用先换令牌 —— 请求头上直接带 `Authorization: key=<AppSecret>`,
是几家里最简单的一条。

## 两个国家/地区的接入点不一样

国内是 `api.xmpush.xiaomi.com`。海外另有接入点,我们只做国内 —— 海外安卓有 FCM,
不需要厂商通道(而 FCM 在国内不通,这正是要接厂商通道的原因)。

## 表单,不是 JSON

小米收的是 `application/x-www-form-urlencoded`。自定义字段走 `payload` 一个字段,
所以 extras 序列化成 JSON 串塞进去。

## 「这个 token 没用了」怎么判

小米回 200 + `{"result":"ok","code":0}` 算成功。失效的 regid 在
`data.reason` / `description` 里说明。**判得很窄**:只有明确说这个 regid 不合法时
才算 gone,别的(参数错、限流、包名不对)都是我们自己的问题 ——
把设备下线只会把问题藏起来,而用户从此收不到推送不会来报 bug。
"""
import json
import logging

from ...config import settings
from .base import NOT_CONFIGURED, Result, client

logger = logging.getLogger("superz.push.xiaomi")

SEND_URL = "https://api.xmpush.xiaomi.com/v3/message/regid"

#: 小米在这几种说法里表示「这个 regid 不存在 / 不合法」
GONE_HINTS = ("invalid registration_id", "registrationid is not valid",
              "not_registered", "invalid regid")


def configured() -> bool:
    return bool(settings.xiaomi_app_secret)


def package_for(app: str) -> str:
    """推给哪个包。小米按 `restricted_package_name` 限定,填错就推到别的 App 上去了。"""
    return {
        "user": settings.xiaomi_package_user,
        "merchant": settings.xiaomi_package_merchant,
        "rider": settings.xiaomi_package_rider,
    }.get(app, settings.xiaomi_package_user)


def form(token: str, title: str, content: str, extras: dict | None, *,
         app: str = "user") -> dict:
    """表单字段。

    - `pass_through=0`:由系统弹通知栏。传 1 是透传给 App,而 App 被杀掉时
      透传是收不到的 —— 那就失去了接厂商通道的意义;
    - `notify_type=-1`:铃声、震动、呼吸灯都按系统设置来,不替用户做主。
    """
    out = {
        "registration_id": token,
        "title": title,
        "description": content,
        "pass_through": 0,
        "notify_type": -1,
        "payload": json.dumps(extras or {}, ensure_ascii=False),
    }
    pkg = package_for(app)
    if pkg:
        out["restricted_package_name"] = pkg
    return out


def _gone(text: str) -> bool:
    low = text.lower()
    return any(h in low for h in GONE_HINTS)


async def send(token: str, title: str, content: str, extras: dict | None = None, *,
               app: str = "user", **_ignored) -> Result:
    if not configured():
        return NOT_CONFIGURED
    try:
        c = await client("xiaomi")
        r = await c.post(SEND_URL,
                         data=form(token, title, content, extras, app=app),
                         headers={"authorization": f"key={settings.xiaomi_app_secret}"})
    except Exception as e:
        logger.warning("小米推送异常 token=%s…: %s", token[:8], e)
        return Result(False, f"xiaomi {type(e).__name__}")
    try:
        data = r.json()
    except Exception:
        return Result(False, f"xiaomi {r.status_code} {r.text[:100]}")
    if r.status_code == 200 and str(data.get("code")) == "0" and data.get("result") == "ok":
        return Result(True)
    detail = f"{data.get('reason') or ''} {data.get('description') or ''}".strip()
    logger.warning("小米推送失败 code=%s %s", data.get("code"), detail[:200])
    return Result(False, f"xiaomi {data.get('code')} {detail[:80]}".strip(),
                  gone=_gone(detail))
