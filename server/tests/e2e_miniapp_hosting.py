"""小程序托管(#322):上传 → 启动 → 取 index.html 验返回头 → 隔离 → 404。

- 恶意包(zip slip、符号链接、解压总量超限、缺清单、超限、禁用扩展名)全部被拒,报告可读;
- 托管出口的返回头逐条对 §5.6:CSP(含声明的服务器域名、report-uri)、
  Permissions-Policy、nosniff、入口 HTML 不缓存、其余文件永久缓存;
- 别的应用的版本号、不存在的文件一律 404;
- 紧急隔离后同一个地址**立即** 404,解除后恢复;对象从未被覆盖(SHA-256 不变)。
"""
import hashlib
import json
import stat
import urllib.parse
import zipfile

from tests.miniapp_util import (HELLO, admin_token, customer, developer, make_zip, new_app,
                                publish, raw_get, upload)
from tests.util import call

dev, _ = developer()
app = new_app(dev)
appid = app["app"]["appid"]


def rejected(data: bytes, needle: str):
    r = upload(dev, appid, data, expect_error=True)
    assert r.get("_error") == 422, f"应被拒:{needle} → {r}"
    report = r["detail"]["report"]
    assert not report["ok"] and report["errors"], report
    text = " ".join(report["errors"])
    assert needle in text, f"报告里要说清楚「{needle}」:{text}"
    return report


# 断言具体的那句话:「..」开头的段也会被「隐藏文件」那条拦下,只看报告里有没有「..」分不清是哪条在守
for name in ("../evil.js", "a/../../evil.js"):
    rejected(make_zip(HELLO, raw_entries=[(zipfile.ZipInfo(name), "x")]), "不能有 .. 或 .")
link = zipfile.ZipInfo("link.js")
link.external_attr = (stat.S_IFLNK | 0o777) << 16
rejected(make_zip(HELLO, raw_entries=[(link, "/etc/passwd")]), "符号链接")
rejected(make_zip({"app.js": "1"}), "index.html")
rejected(make_zip(HELLO, superz=False), "superz.json")
rejected(make_zip({**HELLO, "run.exe": "MZ"}), "exe")
# 真炸弹的形状:压缩后很小,解压出一百来 MB。**判据是绝对上限,不是压缩比** ——
# 「不超过压缩量 3 倍」那条 2026-09-16 去掉了,它拒的全是正常包
# (重复度高的文本压缩比本来就有几十上百倍)
bomb = make_zip({**HELLO, **{f"big{i}.txt": b"0" * (5 * 1024 * 1024) for i in range(19)}})
rejected(bomb, "超过 90 MB 上限")
rejected(make_zip(HELLO, superz={"kind": "game"}), "kind")
print("✓ zip slip / 符号链接 / 缺入口 / 缺清单 / 禁用扩展名 / zip 炸弹 / kind 不符,全部被拒且报告可读")

ok = upload(dev, appid, make_zip({**HELLO, "notes.txt": "外部脚本测试",
                                  "ext.html": "<script src='https://evil.example/x.js'></script>"}))
assert ok["report"]["ok"] and any("外部" in w for w in ok["report"]["warnings"]), \
    f"引用外部脚本要给警告:{ok['report']}"
print("✓ 引用外部脚本的包能传,但报告里有警告")

call("PUT", f"/dev/v1/apps/{appid}/domains", dev,
     {"request_domains": ["https://api.example.com"]})
for bad in (["http://api.example.com"], ["https://127.0.0.1"], ["https://localhost"],
            ["https://api.example.com/"]):
    r = call("PUT", f"/dev/v1/apps/{appid}/domains", dev, {"request_domains": bad},
             expect_error=True)
    assert r["_error"] == 422, f"{bad} 应被拒:{r}"
print("✓ 服务器域名只收 https origin,拒 http / IP / localhost / 带路径")

v = publish(dev, appid)
user, _ = customer()
# 宿主(协议 2.1)下发 16 个主题色:Telegram 的 15 个 + line_color
THEME16 = {k: "#F0EEE6" for k in (
    "bg_color", "text_color", "hint_color", "link_color", "button_color", "button_text_color",
    "secondary_bg_color", "header_bg_color", "bottom_bar_bg_color", "accent_text_color",
    "section_bg_color", "section_header_text_color", "section_separator_color",
    "subtitle_text_color", "destructive_text_color", "line_color")}
launch = call("POST", f"/mini-apps/{appid}/launch", user, {"platform": "web", "theme": THEME16})
caps = launch["app"]["capabilities"]
assert {"fullscreen", "orientation"} <= set(caps), f"全屏和锁方向所有应用都有(不只小游戏):{caps}"
frag = urllib.parse.parse_qs(launch["url"].split("#", 1)[1])
assert json.loads(frag["szWebAppThemeParams"][0]) == THEME16, "16 个主题色原样进启动片段"
print("✓ 普通应用也有全屏、锁方向;宿主下发的 16 个主题色原样进启动片段")
url = launch["url"].split("#", 1)[0]
path = urllib.parse.urlsplit(url).path
assert path.endswith(f"/v/{v['id']}/index.html"), path

status, h, body = raw_get(path)
assert status == 200, (status, body[:200])
assert h["content-type"].startswith("text/html")
csp = h["content-security-policy"]
for part in ("default-src 'self'", "script-src 'self' 'wasm-unsafe-eval'", "object-src 'none'",
             "frame-src 'none'", "form-action 'none'", "connect-src 'self' https://api.example.com",
             "img-src 'self' data: blob: https://api.example.com", "report-uri ",
             "/mini-apps/csp-report", "frame-ancestors "):
    assert part in csp, f"CSP 缺 {part!r}:{csp}"
assert "unsafe-eval'" not in csp.replace("wasm-unsafe-eval", ""), "不许 unsafe-eval"
assert "geolocation=()" in h["permissions-policy"] and "camera=()" in h["permissions-policy"]
assert h["x-content-type-options"] == "nosniff"
assert h["referrer-policy"] == "strict-origin-when-cross-origin"
assert h["cache-control"] == "no-cache", "入口 HTML 要每次回源 —— 隔离后才能立刻打不开"
etag = h["etag"]
s2, h2, _ = raw_get(path, {"If-None-Match": etag})
assert s2 == 304, "ETag 命中应 304"
s3, h3, js = raw_get(path.replace("index.html", "app.js"))
assert s3 == 200 and h3["cache-control"] == "public, max-age=31536000, immutable"
assert h3["content-type"].startswith("text/javascript")
assert js.decode() == HELLO["app.js"], "托管出去的字节就是上传的那份"
print("✓ 返回头:CSP(含声明域名与上报地址)、Permissions-Policy、nosniff、缓存策略全部对上")

s, _, _ = raw_get(path.replace("index.html", "nope.js"))
assert s == 404
s, _, _ = raw_get(path.replace("index.html", "../superz.json"))
assert s in (400, 404)
other = new_app(dev)["app"]["appid"]
s, _, _ = raw_get(path.replace(appid, other))
assert s == 404, "别的应用的路径下不许出这个版本"
s, _, _ = raw_get(f"/_mini-host/SZ{appid[2:]}/v/{v['id']}/index.html")
assert s == 404, "appid 大小写变体要拒"
print("✓ 不存在的文件、别的应用、大小写变体一律 404")

detail = call("GET", f"/mini-apps/{appid}")
assert detail["version"]["sha256"] == v["sha256"] and len(v["sha256"]) == 64
print("✓ 详情页公示当前版本 SHA-256")

adm = admin_token()
r = call("POST", f"/admin/mini-apps/versions/{v['id']}/quarantine", adm,
         {"reason_code": "R502", "note_public": "发现挖矿脚本"}, expect_error=True)
assert "_error" not in r, r
s, _, _ = raw_get(path)
assert s == 404, "隔离后同一个地址必须立即 404"
s, _, _ = raw_get(path.replace("index.html", "app.js"))
assert s == 404
r = call("POST", f"/mini-apps/{appid}/launch", user, {}, expect_error=True)
assert r["_error"] == 423 and r["detail"]["code"] == 4009, r
st = call("GET", f"/mini-apps/{appid}/status", user)
assert st["blocked"] is True, "宿主轮询状态要能看到被隔离了"
r = call("POST", f"/mini-apps/{appid}/storage/usage", user, {}, expect_error=True)
assert r["_error"] == 423 and r["detail"]["code"] == 4009, "隔离后桥调用回 4009"
assert appid not in str(call("GET", "/mini-apps/catalog")), "隔离的应用不该出现在目录里"
print("✓ 紧急隔离:文件立即 404、启动与云存储回 4009、目录里消失")

r = call("POST", f"/admin/mini-apps/versions/{v['id']}/unquarantine", adm, {"note": "复核后误报"})
s, _, again = raw_get(path)
files = {f["path"]: f for f in call("GET", f"/dev/v1/apps/{appid}/versions/{v['id']}", dev)["files"]}
assert s == 200 and hashlib.sha256(again).hexdigest() == files["index.html"]["sha256"]
print("✓ 解除隔离后恢复,内容没变")

s, h, body = raw_get("/_mini-host/_sdk/2/sz-webapp.js")
if s == 200:
    assert "javascript" in h["content-type"]
    print("✓ 托管 origin 下有 SDK(/_sdk/2/sz-webapp.js)")
else:
    print("… SDK 还没构建(packages/miniapp-sdk → server/static/sdk),跳过")

print("\n小程序托管验证通过 🎉")
