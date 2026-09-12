"""目录与发现(#326)。

- 未登录能看目录和详情(想用的人得先看得见有什么);
- 排序:精选在前,其余按首次上架时间从新到旧;**发新版本不会往前挪**(I3);
- 搜索按名称精确 > 前缀 > 包含;分类、kind 过滤;
- 收藏、最近使用存在服务端,两台设备(两个 token)看到的一样;
- 老版本 App 的 v1 清单只含外部地址条目。
"""
import time
import uuid
from urllib.parse import quote

from tests.miniapp_util import (HELLO, customer, developer, make_zip, new_app, publish, sms_login)
from tests.util import call

dev, _ = developer()
tag = uuid.uuid4().hex[:4]
older = new_app(dev, name=f"目录甲{tag}")["app"]["appid"]
publish(dev, older)
time.sleep(1.1)
newer = new_app(dev, name=f"目录乙{tag}", kind="game")["app"]["appid"]
call("PUT", f"/dev/v1/apps/{newer}", dev, {"category": "casual"})
publish(dev, newer, make_zip(HELLO, kind="game"), kind="game")

cat = call("GET", "/mini-apps/catalog")
ids = [x["appid"] for x in cat["items"] if not x["curated"]]
assert ids.index(newer) < ids.index(older), "后上架的排前面"
assert "没有竞价" in cat["sort_rule"] and cat["categories"]
print("✓ 未登录能看目录;按首次上架时间从新到旧,规则写在应答里")

# 给老的发个新版本:不许往前挪
publish(dev, older, make_zip({**HELLO, "app.js": "console.log('v2')"}), version="1.1.0")
ids = [x["appid"] for x in call("GET", "/mini-apps/catalog")["items"] if not x["curated"]]
assert ids.index(newer) < ids.index(older), "发新版本不能刷到前面去(I3)"
print("✓ 发新版本不会往前挪")

s = call("GET", f"/mini-apps/catalog?q={quote('目录甲' + tag)}")["items"]
assert [x["appid"] for x in s][:1] == [older], "名称精确命中排第一"
s = call("GET", f"/mini-apps/catalog?q={tag}")["items"]
assert {x["appid"] for x in s} >= {older, newer}
games = call("GET", "/mini-apps/catalog?kind=game")["items"]
assert newer in {x["appid"] for x in games} and older not in {x["appid"] for x in games}
casual = call("GET", "/mini-apps/catalog?category=casual")["items"]
assert all(x["category"] == "casual" for x in casual) and newer in {x["appid"] for x in casual}
page = call("GET", "/mini-apps/catalog?limit=1")
assert len(page["items"]) == 1 and page["next_cursor"] == 1
print("✓ 搜索、kind、分类过滤、分页")

d = call("GET", f"/mini-apps/{older}")
assert d["available"] and d["version"]["version"] == "1.1.0" and len(d["version"]["sha256"]) == 64
assert d["developer"]["label"] == "个人开发者 · 已实名" and "测试开发者" not in str(d), \
    "个人开发者的真名不公开"
assert d["privacy_policy"] and "initData" in d["capabilities"] and d["me"] is None
assert d["link"].endswith(f"/m/{older}")
print("✓ 详情:版本、SHA-256、能力、隐私政策、开发者认证类型;真名不公开")

token, phone = customer()
call("POST", f"/mini-apps/{older}/launch", token, {})
call("POST", f"/mini-apps/{newer}/launch", token, {})
call("POST", f"/mini-apps/{older}/star", token)
other_device = sms_login(phone)["token"]
me = call("GET", "/mini-apps/me", other_device)
assert [x["appid"] for x in me["recent"]][:2] == [newer, older], "最近使用按打开时间倒序"
assert [x["appid"] for x in me["starred"]] == [older]
assert call("GET", f"/mini-apps/{older}", other_device)["me"]["starred"] is True
call("DELETE", f"/mini-apps/{older}/star", other_device)
assert call("GET", "/mini-apps/me", token)["starred"] == []
print("✓ 收藏、最近使用存在服务端,换设备看到的一样")

v1 = call("GET", "/mini-apps", token)
assert older not in str(v1) and newer not in str(v1), "托管应用不许出现在老 App 的清单里"
print("✓ v1 清单只含外部地址条目")

call("POST", f"/dev/v1/apps/{older}/offline", dev)
assert older not in {x["appid"] for x in call("GET", "/mini-apps/catalog")["items"]}
assert older not in {x["appid"] for x in call("GET", "/mini-apps/me", token)["recent"]}
d = call("GET", f"/mini-apps/{older}")
assert d["available"] is False and d["status"] == "offline"
call("POST", f"/dev/v1/apps/{older}/online", dev)
print("✓ 开发者下架后从目录和最近使用里消失,详情页写明已下架")

print("\n目录与发现验证通过 🎉")
