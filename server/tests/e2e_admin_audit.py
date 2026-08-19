"""管理员写操作留痕(#286)。

## 这个用例防的是什么

平台后台碰的是**钱和资格**:批不批一家店营业、放不放一笔提现、
极端天气停不停运。这些接口一直都拿到了 `admin: User`,却一个都没记
谁操作的 —— 只能 curl 的时候缺口还小(操作少、门槛高),
一旦做成后台点两下就能批,它就是个真问题。

留痕是**各 handler 显式调 log_admin_action** 的(中间件记不到业务含义,
「驳回,理由:执照过期」比「POST /admin/merchants/12/reject」有用得多)。
显式的代价是可能漏记 —— 这个用例就是盯这一点:
**每个覆盖到的写操作,做完必须能在 /admin/action-logs 里查到。**
"""
from tests.util import ADMIN, call, login

admin = login(ADMIN)


def logs(**q):
    qs = "&".join(f"{k}={v}" for k, v in q.items() if v is not None)
    return call("GET", f"/admin/action-logs?{qs}", admin)


def newest(action):
    rows = logs(action=action, limit=1)
    return rows[0] if rows else None


# ---- 平台开关 ----
before = newest("flag.set")
call("POST", "/admin/flags/weather_shutdown", admin,
     {"value": "off", "reason": "e2e 留痕自测"})
row = newest("flag.set")
assert row is not None and row != before, "改平台开关没有留痕"
assert row["target_type"] == "flag" and row["target_id"] == "weather_shutdown"
assert row["detail"]["reason"] == "e2e 留痕自测"
assert row["detail"]["to"] == "off"
print("✓ 平台开关:改完能查到,带上了改动前后的值和原因")

# 手机号必须打码。留痕列表是运营日常看的,不需要完整号码;
# 要精确到人有 admin_id
assert "****" in row["admin_phone"], f"管理员手机号没打码:{row['admin_phone']}"
assert row["admin_id"], "没记 admin_id,只有打码号就查不到具体是谁"
print("✓ 手机号打码,但 admin_id 留着(能查到人)")

# ---- 商家审核 ----
# 演示库里的待审商家不一定有,所以用「操作后能不能查到」而不是「必须有待审的」
pending = [m for m in call("GET", "/admin/merchants?status=pending", admin)
           if m.get("id")]
if pending:
    mid = pending[0]["id"]
    before = newest("merchant.reject")
    call("POST", f"/admin/merchants/{mid}/reject", admin,
         {"reason": "e2e 留痕自测"})
    row = newest("merchant.reject")
    assert row is not None and row != before, "驳回商家没有留痕"
    assert row["target_type"] == "merchant" and row["target_id"] == str(mid)
    assert row["detail"]["reason"] == "e2e 留痕自测"
    print(f"✓ 商家驳回:留痕带上了店 id 和理由(店 {mid})")

    before = newest("merchant.approve")
    call("POST", f"/admin/merchants/{mid}/approve", admin)
    row = newest("merchant.approve")
    assert row is not None and row != before, "通过商家没有留痕"
    assert row["target_id"] == str(mid)
    print("✓ 商家通过:留痕")
else:
    print("· 演示库里没有待审商家,跳过商家审核留痕(开关那条已覆盖同一条路径)")

# ---- 按对象查历史 ----
if pending:
    mine = logs(target_type="merchant", target_id=pending[0]["id"])
    assert len(mine) >= 2, "按对象查不到这家店的操作历史"
    assert {r["action"] for r in mine} >= {"merchant.reject", "merchant.approve"}
    print("✓ 按对象能查出「这家店被谁动过」")

# ---- 留痕不许被删 ----
# 能删的留痕等于没有留痕。这里断言接口不存在(405/404 都算)
call("DELETE", "/admin/action-logs/1", admin, expect_error=True)
print("✓ 没有删除接口")

# ---- detail 不许放敏感字段 ----
from app.services.admin_audit import _clean

for bad in ({"id_card": "x"}, {"bank_account": "x"}, {"Password": "x"},
            {"api_key": "x"}):
    try:
        _clean(bad)
        raise AssertionError(f"{list(bad)[0]} 没被拦下")
    except ValueError:
        pass
assert _clean({"reason": "执照过期", "amount_cents": 100})
print("✓ detail 挡掉身份证/银行卡/口令/密钥,正常字段放行")

print("\n✓ e2e_admin_audit 全过")
