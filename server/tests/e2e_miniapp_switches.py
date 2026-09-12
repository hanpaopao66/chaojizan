"""小程序急停闸(DEV-PROMPTS-39 #337「任何一步出问题先关开关」)。

- 托管小程序关:启动回 4009、状态轮询 blocked(开着的宿主一分钟内关掉)、托管文件 404、
  目录和「最近使用」里都没有、详情 available=false;开回来全部恢复,内容没变;
- 小程序目录关:公开目录只剩官方的;用户自己的「最近使用」照常;
- 昵称头像关:能力清单里没有 profile,requestProfile 回 4001;开回来恢复;
- 每次拉闸都进 flag_history(透明中心治理时间线的数据源),带原因。

跑完(包括中途失败)一定把三个闸放回「开」—— 这是共享的开发库。
"""
import urllib.parse

from tests.miniapp_util import admin_token, customer, developer, new_app, publish, raw_get, sql
from tests.util import call

SWITCHES = ("miniapp_hosted", "miniapp_catalog", "miniapp_profile")
REASON = "e2e:急停闸演练"


def flag(key: str, value: str) -> None:
    call("POST", f"/admin/flags/{key}", admin_token(), {"value": value, "reason": REASON})


dev, _ = developer()
created = new_app(dev)
appid, name = created["app"]["appid"], created["app"]["name"]
publish(dev, appid)
cap = call("POST", f"/dev/v1/apps/{appid}/capabilities", dev,
           {"capability": "profile", "justification": "在记录旁边显示用户的昵称"})
call("POST", f"/admin/mini-apps/capabilities/{cap['id']}/decide", admin_token(),
     {"approve": True, "note": "急停闸演练"})
user, _ = customer()
launch = call("POST", f"/mini-apps/{appid}/launch", user, {"platform": "web"})
path = urllib.parse.urlsplit(launch["url"]).path
status, _, body = raw_get(path)
assert status == 200


def catalog_ids(q: str = "") -> list[str]:
    items = call("GET", f"/mini-apps/catalog?limit=100&q={urllib.parse.quote(q)}")["items"]
    return [i["appid"] for i in items]


def recent_ids() -> list[str]:
    return [a["appid"] for a in call("GET", "/mini-apps/me", user)["recent"]]


assert appid in catalog_ids(name) and appid in recent_ids()
# 开跑前三个闸都得是开的(没写过 = 开)
for k, v in call("GET", "/admin/flags", admin_token()).items():
    if k in SWITCHES:
        assert v == "on", f"{k} 开跑前就是 {v}"

try:
    # ---- 托管小程序 ----
    flag("miniapp_hosted", "off")
    r = call("POST", f"/mini-apps/{appid}/launch", user, {"platform": "web"}, expect_error=True)
    assert r["_error"] == 503 and r["detail"]["code"] == 4009, r
    assert call("GET", f"/mini-apps/{appid}/status", user)["blocked"] is True
    assert raw_get(path)[0] == 404, "拉闸后托管文件必须立刻 404"
    assert all(i["hosting"] == "external"
               for i in call("GET", "/mini-apps/catalog?limit=100")["items"]), "目录里还有托管应用"
    assert appid not in recent_ids()
    assert call("GET", f"/mini-apps/{appid}")["available"] is False
    flag("miniapp_hosted", "on")
    assert call("POST", f"/mini-apps/{appid}/launch", user, {"platform": "web"})["url"]
    assert call("GET", f"/mini-apps/{appid}/status", user)["blocked"] is False
    s2, _, body2 = raw_get(path)
    assert s2 == 200 and body2 == body, "开回来之后内容要和原来一样"
    print("✓ 托管小程序闸:启动 4009、轮询 blocked、文件 404、目录与最近使用消失;开回来全部恢复")

    # ---- 小程序目录 ----
    flag("miniapp_catalog", "off")
    items = call("GET", "/mini-apps/catalog?limit=100")["items"]
    assert all(i["is_official"] for i in items) and appid not in catalog_ids(name)
    assert appid in recent_ids(), "用户自己的「最近使用」不受目录闸影响"
    assert call("POST", f"/mini-apps/{appid}/launch", user, {"platform": "web"})["url"], "直达链接照常能开"
    flag("miniapp_catalog", "on")
    assert appid in catalog_ids(name)
    print("✓ 小程序目录闸:目录只剩官方的;最近使用、直达链接照常;开回来恢复")

    # ---- 昵称头像 ----
    assert "profile" in call("GET", f"/mini-apps/{appid}")["capabilities"]
    flag("miniapp_profile", "off")
    assert "profile" not in call("GET", f"/mini-apps/{appid}")["capabilities"]
    r = call("POST", f"/mini-apps/{appid}/profile", user, expect_error=True)
    assert r["_error"] == 403 and r["detail"]["code"] == 4001, r
    flag("miniapp_profile", "on")
    assert call("POST", f"/mini-apps/{appid}/profile", user)["init_data"]
    print("✓ 昵称头像闸:能力当场收回、requestProfile 回 4001;开回来恢复")

    # ---- 公示 ----
    rows = sql("SELECT key, new_value FROM flag_history WHERE reason = :r AND key = ANY(:k) "
               "ORDER BY id DESC LIMIT 6", {"r": REASON, "k": list(SWITCHES)}, fetch="all")
    assert {(k, v) for k, v in rows} == {(k, v) for k in SWITCHES for v in ("on", "off")}, rows
    print("✓ 每次拉闸都带原因记进 flag_history(透明中心治理时间线)")
finally:
    # 只动没放回去的:每改一次都会进公开时间线,不留一串没意义的「开 → 开」
    for k, v in call("GET", "/admin/flags", admin_token()).items():
        if k in SWITCHES and v != "on":
            flag(k, "on")
