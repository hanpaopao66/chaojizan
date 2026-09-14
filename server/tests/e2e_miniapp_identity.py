"""小程序身份协议 v2(#321):登录 → launch → 用公钥和密钥各验一次。

- initData 两种验法都过:持 AppSecret 验 hash、拿平台公钥验 signature;
- 启动地址带 §5.2 的片段,片段里就是同一份 initData;**全程没有登录 token**(I1);
- 同一个用户在两个应用里 open_id 不同,且和 user_id 没有关系(I2);
- 篡改任一字段、换 app_id,两种验法都失败;
- 两步轮换:生成待生效密钥后照旧用旧的签;切换后新的能验、旧的不能。
"""
import json
import re
import urllib.parse

from tests.miniapp_util import (customer, developer, new_app, parse_init, publish,
                                verify_hash, verify_signature)
from tests.util import call

dev, _ = developer()
a = new_app(dev)
b = new_app(dev)
appid_a, secret_a = a["app"]["appid"], a["app_secret"]
appid_b, secret_b = b["app"]["appid"], b["app_secret"]
assert re.fullmatch(r"sz[0-9a-f]{16}", appid_a), appid_a
assert re.fullmatch(r"[A-Za-z0-9_-]{43}", secret_a), "AppSecret 是 43 位 base64url"
detail = call("GET", f"/dev/v1/apps/{appid_a}", dev)
assert secret_a not in str(detail), "AppSecret 只在创建时显示一次,之后任何接口都不许再回"
publish(dev, appid_a)
publish(dev, appid_b)
print("✓ 两个应用建好、过审、发布")

keys = call("GET", "/.well-known/superz-webapp-keys.json")["keys"]
assert keys and keys[0]["alg"] == "Ed25519" and len(keys[0]["kid"]) == 8, keys
pub = keys[0]["public_key"]

user_token, _ = customer()
me = call("GET", "/auth/me", user_token)
r = call("POST", f"/mini-apps/{appid_a}/launch", user_token,
         {"platform": "android", "start_param": "note_42", "theme": {"bg_color": "#F0EEE6"}})
init = r["init_data"]
fields = parse_init(init)
assert set(fields) == {"app_id", "auth_date", "launch_id", "user", "start_param", "sig_kid",
                       "hash", "signature"}, fields.keys()
assert fields["app_id"] == appid_a and fields["start_param"] == "note_42"
assert fields["sig_kid"] == keys[0]["kid"]
assert "env" not in fields, "真机启动不带 env(只有模拟器是 sim)"
assert verify_hash(init, secret_a), "持 AppSecret 验 hash 应该通过"
assert verify_signature(init, pub, appid_a), "拿平台公钥验 signature 应该通过"
print("✓ initData v2:hash 与 signature 两种验法都过")

frag = urllib.parse.urlsplit(r["url"]).fragment
fp = dict(urllib.parse.parse_qsl(frag))
assert fp["szWebAppData"] == init and fp["szWebAppVersion"] == "2.0"
assert fp["szWebAppPlatform"] == "android" and fp["szWebAppStartParam"] == "note_42"
assert f"/v/{r['version']['id']}/index.html" in r["url"]
blob = str(r)
assert user_token not in blob and "Bearer" not in blob, "启动应答里不许有登录 token(I1)"
assert re.search(r"eyJ[\w-]+\.[\w-]+\.[\w-]+", blob) is None, "应答里出现了 JWT 形状的串"
print("✓ 启动地址带 §5.2 片段,应答里没有任何登录凭据")

user_a = json.loads(fields["user"])
rb = call("POST", f"/mini-apps/{appid_b}/launch", user_token, {"platform": "web"})
user_b = json.loads(parse_init(rb["init_data"])["user"])
assert re.fullmatch(r"o_[a-z2-7]{26}", user_a["open_id"]), user_a
assert user_a["open_id"] != user_b["open_id"], "同一个人在两个应用里 open_id 必须不同(I2)"
# open_id 是随机生成再存对应表的(mini_app_v2.new_open_id,单测守着),不是从用户 id 算出来的。
# 这条子串比对只在 id 够长时才有意义:干净库上 id 只有一两位,26 位随机串里碰巧含一个 "5"
# 的概率过半(CI 分组并行后在干净库上撞见过)
if len(str(me["id"])) >= 4:
    assert str(me["id"]) not in user_a["open_id"]
assert set(user_a) == {"open_id", "language_code"}, "没授权 profile 时只有 open_id 和语言"
again = call("POST", f"/mini-apps/{appid_a}/launch", user_token, {})
assert json.loads(parse_init(again["init_data"])["user"])["open_id"] == user_a["open_id"]
assert parse_init(again["init_data"])["launch_id"] != fields["launch_id"], "每次启动 launch_id 不同"
print("✓ open_id 按应用隔离、同应用稳定;launch_id 每次不同")

# 篡改:改 user、换 app_id、改 auth_date —— 两种验法都失败

def tampered(k, v):
    f = parse_init(init)
    f[k] = v
    return urllib.parse.urlencode(f, quote_via=urllib.parse.quote)


for k, v in (("user", fields["user"].replace(user_a["open_id"], user_b["open_id"])),
             ("app_id", appid_b), ("auth_date", str(int(fields["auth_date"]) + 1)),
             ("start_param", "admin")):
    bad = tampered(k, v)
    assert not verify_hash(bad, secret_a), f"改了 {k} 之后 hash 还能验过"
    assert not verify_signature(bad, pub, appid_a), f"改了 {k} 之后 signature 还能验过"
assert not verify_hash(init, secret_b), "别的应用的密钥验不过"
assert not verify_signature(init, pub, appid_b), "拿到别的应用的包,按自己的 app_id 验必须失败"
assert not verify_hash(init, secret_a, max_age=-1), "过期的包验不过"
print("✓ 篡改任一字段、换 app_id、过期,验签全部失败")

# 两步轮换
pending = call("POST", f"/dev/v1/apps/{appid_a}/secret/rotate", dev)["app_secret_pending"]
assert pending != secret_a
mid = call("POST", f"/mini-apps/{appid_a}/launch", user_token, {})["init_data"]
assert verify_hash(mid, secret_a) and not verify_hash(mid, pending), "切换前应继续用旧密钥签"
call("POST", f"/dev/v1/apps/{appid_a}/secret/activate", dev)
after = call("POST", f"/mini-apps/{appid_a}/launch", user_token, {})["init_data"]
assert verify_hash(after, pending), "切换后用新密钥签"
assert not verify_hash(after, secret_a), "切换后旧密钥验不过"
assert verify_signature(after, pub, appid_a), "公钥验法不受 AppSecret 轮换影响"
r = call("POST", f"/dev/v1/apps/{appid_a}/secret/activate", dev, expect_error=True)
assert r["_error"] == 409, "没有待生效的密钥时切换应 409"
print("✓ 两步轮换:切换前旧密钥签、切换后新密钥签")

# 模拟器:env=sim,开发者自己的身份
vid = call("GET", f"/dev/v1/apps/{appid_a}", dev)["current_version"]["id"]
sim = call("POST", f"/dev/v1/apps/{appid_a}/sim/launch?version_id={vid}", dev, {})
sf = parse_init(sim["init_data"])
assert sf["env"] == "sim" and verify_hash(sim["init_data"], pending)
assert json.loads(sf["user"])["open_id"] != user_a["open_id"]
print("✓ 模拟器的 initData 带 env=sim,是开发者自己的 open_id")

# v1 协议一个字不动:老接口仍然给外部地址条目签 v1 包
v1 = call("GET", "/mini-apps", user_token)
assert all(x["id"] for x in v1)
assert appid_a not in str(v1), "托管应用不许出现在 v1 清单里(老 App 打不开)"
if v1:
    pack = call("POST", f"/mini-apps/{v1[0]['id']}/init-data", user_token)
    assert set(pack) == {"payload", "sign"}
print("✓ v1 清单只含外部地址条目,v1 签名接口照旧")

print("\n身份协议 v2 验证通过 🎉")
