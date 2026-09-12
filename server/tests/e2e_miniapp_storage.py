"""小程序云存储(#325,§5.5)。

- set/get/remove/keys/usage 五个操作;键、值格式不对回 4004;
- rev 乐观并发:ifRev 不符回 4007,ifRev=0 表示「必须还不存在」;
- 配额:键数恰好到 1024 成功、多一个 4006;字节恰好到 5 MB 成功、多 1 字节 4006;
- A 应用读不到 B 应用;同一应用里,用户甲读不到用户乙;
- 限流:每分钟 120 次,超了 4005;
- 用户能看用量、导出、清空;注销账号后数据为空。
"""
import os

from tests.miniapp_util import customer, developer, new_app, publish, sql
from tests.util import call

MAX_KEYS, MAX_BYTES, MAX_VALUE = 1024, 5 * 1024 * 1024, 65536

dev, _ = developer()
app_a = new_app(dev)["app"]["appid"]
app_b = new_app(dev)["app"]["appid"]
publish(dev, app_a)
publish(dev, app_b)
alice, _ = customer()
bob, _ = customer()


def kv(token, appid, op, body=None, expect_error=False):
    return call("POST", f"/mini-apps/{appid}/storage/{op}", token, body or {},
                expect_error=expect_error, retry_429=False)


def code_of(r):
    assert "_error" in r, f"应该失败:{r}"
    return r["detail"]["code"]


r = kv(alice, app_a, "set", {"key": "n:1", "value": "你好"})
assert r == {"key": "n:1", "rev": 1}, r
assert kv(alice, app_a, "get", {"keys": ["n:1", "missing"]})["items"] == \
    {"n:1": {"value": "你好", "rev": 1}, "missing": None}
r = kv(alice, app_a, "set", {"key": "n:1", "value": "改了", "if_rev": 1})
assert r["rev"] == 2
assert code_of(kv(alice, app_a, "set", {"key": "n:1", "value": "旧版本覆盖", "if_rev": 1},
                  expect_error=True)) == 4007, "rev 不符必须 4007"
assert code_of(kv(alice, app_a, "set", {"key": "n:1", "value": "x", "if_rev": 0},
                  expect_error=True)) == 4007, "ifRev=0 表示必须不存在"
assert kv(alice, app_a, "set", {"key": "n:2", "value": "新的", "if_rev": 0})["rev"] == 1
assert kv(alice, app_a, "get", {"keys": ["n:1"]})["items"]["n:1"]["value"] == "改了", \
    "冲突的写入不许落库"
print("✓ set/get 与 rev 乐观并发(4007、ifRev=0)")

for bad in ({"key": "有中文", "value": "x"}, {"key": "a" * 129, "value": "x"},
            {"key": "k", "value": "x" * (MAX_VALUE + 1)}, {"key": "k"}):
    assert code_of(kv(alice, app_a, "set", bad, expect_error=True)) == 4004, bad
assert code_of(kv(alice, app_a, "get", {"keys": [f"k{i}" for i in range(101)]},
                  expect_error=True)) == 4004, "一次最多 100 个键"
assert kv(alice, app_a, "set", {"key": "big", "value": "字" * (MAX_VALUE // 3)})["rev"] == 1, \
    "值按 UTF-8 字节算,恰好在上限内要成功"
print("✓ 键、值、批量大小不合法回 4004;值按 UTF-8 字节计")

assert kv(bob, app_a, "get", {"keys": ["n:1"]})["items"]["n:1"] is None, "别的用户读不到"
assert kv(alice, app_b, "get", {"keys": ["n:1"]})["items"]["n:1"] is None, "别的应用读不到"
kv(alice, app_b, "set", {"key": "n:1", "value": "B 应用的"})
assert kv(alice, app_a, "get", {"keys": ["n:1"]})["items"]["n:1"]["value"] == "改了"
print("✓ (应用, 用户)隔离:A 应用读不到 B 应用,甲读不到乙")

keys = kv(alice, app_a, "keys", {"prefix": "n:"})
assert keys["keys"] == ["n:1", "n:2"] and keys["next_cursor"] is None
page = kv(alice, app_a, "keys", {"limit": 1})
assert len(page["keys"]) == 1 and page["next_cursor"]
assert kv(alice, app_a, "remove", {"keys": ["n:2", "nope"]}) == {"removed": 1}
print("✓ getKeys 前缀与分页、removeItems")

# ---- 配额边界:直接把用量行调到边上(一个一个写 1024 个键会先撞限流)----


def set_usage(appid: str, token: str, keys: int, nbytes: int):
    uid = call("GET", "/auth/me", token)["id"]
    sql("UPDATE mini_app_kv_usage SET keys = :k, bytes = :b WHERE user_id = :u "
        "AND app_id = (SELECT id FROM mini_apps WHERE appid = :a)",
        {"k": keys, "b": nbytes, "a": appid, "u": uid})


usage = kv(alice, app_a, "usage")
base_keys, base_bytes = usage["keys"], usage["bytes"]
set_usage(app_a, alice, MAX_KEYS - 1, base_bytes)
assert kv(alice, app_a, "set", {"key": "last", "value": "1"})["rev"] == 1, "第 1024 个键要成功"
assert code_of(kv(alice, app_a, "set", {"key": "one_more", "value": "1"},
                  expect_error=True)) == 4006, "第 1025 个键必须 4006"
assert kv(alice, app_a, "set", {"key": "last", "value": "2"})["rev"] == 2, "改已有的键不占新额度"
set_usage(app_a, alice, 10, MAX_BYTES - len("edge") - 5)
assert kv(alice, app_a, "set", {"key": "edge", "value": "12345"})["rev"] == 1, "恰好 5 MB 要成功"
assert code_of(kv(alice, app_a, "set", {"key": "edge2", "value": ""},
                  expect_error=True)) == 4006, "多 1 个字节(键名本身)也要 4006"
set_usage(app_a, alice, base_keys, base_bytes)
print("✓ 配额:1024 个键与 5 MB 都是恰好成功、多一点就 4006")

# ---- 用户的数据权利(I8)----
data = call("GET", f"/mini-apps/{app_a}/data?export=true", alice)
assert data["items"]["n:1"] == "改了" and "exported_at" in data
listing = call("GET", "/mini-apps/me/data", alice)["items"]
assert {x["appid"] for x in listing} >= {app_a, app_b}
assert call("DELETE", f"/mini-apps/{app_b}/data", alice)["removed_keys"] == 1
assert kv(alice, app_b, "get", {"keys": ["n:1"]})["items"]["n:1"] is None
assert kv(alice, app_b, "usage")["keys"] == 0
print("✓ 用户能看用量、导出 JSON、清空")

# ---- 限流 4005 ----
if os.environ.get("SKIP_RATE", "") != "1":
    hit = None
    for i in range(130):
        r = kv(bob, app_b, "usage", expect_error=True)
        if isinstance(r, dict) and r.get("_error"):
            hit = r
            break
    assert hit and hit["_error"] == 429 and hit["detail"]["code"] == 4005, hit
    print(f"✓ 限流:第 {i + 1} 次调用回 4005")

# ---- 注销级联删除 ----
carol, _ = customer()
kv(carol, app_a, "set", {"key": "secret", "value": "注销后必须消失"})
uid = call("GET", "/auth/me", carol)["id"]
call("DELETE", "/auth/me", carol)


def leftover(user_id: int) -> int:
    return sum(sql(f"SELECT count(*) FROM {t} WHERE user_id = :u", {"u": user_id}, fetch="scalar")
               for t in ("mini_app_kv", "mini_app_kv_usage", "mini_app_user_prefs",
                         "mini_app_openids", "mini_app_grants", "mini_app_daily_users"))


assert leftover(uid) == 0, "注销后小程序相关数据要全部删除"
print("✓ 注销账号后云存储、授权、最近使用、open_id 映射全部删除")

print("\n云存储验证通过 🎉")
