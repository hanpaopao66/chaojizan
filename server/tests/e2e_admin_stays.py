"""平台后台住宿能力:售后监控接口、看板住宿待办计数。

    SUPERZ_API=http://127.0.0.1:8010 python -m tests.e2e_admin_stays
"""
from tests.util import ADMIN, call, login

admin_token = login(ADMIN)

# 1) 售后监控列表(此前 e2e_stays_aftersale 造过数据)
rows = call("GET", "/admin/stay-aftersales", token=admin_token)
assert isinstance(rows, list) and len(rows) > 0
sample = rows[0]
for key in ("kind", "status", "order_no", "hotel", "total_cents",
            "refund_cents", "penalty_cents"):
    assert key in sample, f"缺字段 {key}"
accepted = [r for r in rows if r["status"] in ("accepted", "auto_accepted")
            and r["kind"] == "no_room"]
assert any(r["penalty_cents"] > 0 for r in accepted), "成立的无房赔付应带违约金"
# 状态筛选
rej = call("GET", "/admin/stay-aftersales?status=rejected", token=admin_token)
assert all(r["status"] == "rejected" for r in rej)
print(f"OK 售后监控列表 {len(rows)} 条,筛选正常")

# 2) 看板住宿待办计数存在
dash = call("GET", "/admin/dashboard", token=admin_token)
assert "stay_orders" in dash["pending"] and "stay_aftersales" in dash["pending"]
print("OK 看板住宿待办:", dash["pending"]["stay_orders"],
      dash["pending"]["stay_aftersales"])

print("PASS e2e_admin_stays")
