"""P1 平台运营基建验证:公告配置化 / 自建埋点 / 门店相册。

在 server/ 目录下运行:python -m tests.e2e_p2_platform
"""
import time

from tests.util import ADMIN, CUSTOMER, MERCHANT, call, login

customer = login(CUSTOMER)
merchant = login(MERCHANT)
admin = login(ADMIN)

tag = str(int(time.time()))

# ---- 公告:权限 → 定向 → 时间窗 → 下线 ----
err = call("POST", "/admin/announcements", customer,
           {"audience": "user", "title": "x", "content": "y"},
           expect_error=True)
assert err["_error"] == 403
print("✓ 非管理员发公告被拒")

ann_user = call("POST", "/admin/announcements", admin, {
    "audience": "user", "title": f"用户公告-{tag}", "content": "只有用户端能看到"})
ann_all = call("POST", "/admin/announcements", admin, {
    "audience": "all", "title": f"全端公告-{tag}", "content": "三端都能看到"})
ann_future = call("POST", "/admin/announcements", admin, {
    "audience": "user", "title": f"未来公告-{tag}", "content": "还没到时间",
    "starts_at": "2099-01-01T00:00:00Z"})

seen_user = [a["title"] for a in call("GET", "/announcements?audience=user")]
assert ann_user["title"] in seen_user, "用户端应看到 user 公告"
assert ann_all["title"] in seen_user, "用户端应看到 all 公告"
assert ann_future["title"] not in seen_user, "未开始的公告不应出现"
print("✓ 公告端定向 + 时间窗生效(user 看到 user/all,看不到未来公告)")

seen_merchant = [a["title"] for a in call("GET", "/announcements?audience=merchant")]
assert ann_user["title"] not in seen_merchant, "商家端不应看到 user 公告"
assert ann_all["title"] in seen_merchant
print("✓ 商家端只看到 merchant/all 公告")

call("PATCH", f"/admin/announcements/{ann_all['id']}", admin,
     {"is_active": False})
seen_after = [a["title"] for a in call("GET", "/announcements?audience=user")]
assert ann_all["title"] not in seen_after, "下线的公告不应再出现"
print("✓ 公告一键下线立即生效(发通知/撤通知都不用发版)")

# 清理:全部下线,不污染后续测试与真机演示
call("PATCH", f"/admin/announcements/{ann_user['id']}", admin,
     {"is_active": False})
call("PATCH", f"/admin/announcements/{ann_future['id']}", admin,
     {"is_active": False})

# ---- 埋点:登录才收 → 批量入库 → 管理端汇总可见 ----
err = call("POST", "/events/batch", None,
           {"events": [{"name": "view_menu"}]}, expect_error=True)
assert err["_error"] == 401
print("✓ 未登录上报被拒(只收登录用户,与隐私政策一致)")

event_name = f"e2e_event_{tag}"
resp = call("POST", "/events/batch", customer, {"events": [
    {"name": event_name, "props": {"merchant_id": 1}},
    {"name": event_name, "props": {"q": "面"}},
]})
assert resp["accepted"] == 2
summary = call("GET", "/admin/events/summary", admin)["events"]
row = next(e for e in summary if e["event"] == event_name)
assert row["count"] == 2 and row["users"] == 1
print("✓ 埋点批量入库,管理端 7 天汇总正确(2 次 / 1 独立用户)")

err = call("GET", "/admin/events/summary", customer, expect_error=True)
assert err["_error"] == 403
print("✓ 事件汇总仅管理员可见")

# ---- 门店相册:保存 → 用户可见 → 上限 9 张 ----
photos = [f"/uploads/e2e_{tag}_{i}.jpg" for i in range(3)]
shop = call("PATCH", "/merchants/me", merchant, {"photo_urls": photos})
assert shop["photo_urls"] == photos

detail = call("GET", f"/merchants/{shop['id']}")
assert detail["photo_urls"] == photos, "用户侧店铺详情应带相册"
print("✓ 门店相册保存成功,用户侧详情可见(3 张)")

err = call("PATCH", "/merchants/me", merchant,
           {"photo_urls": [f"/x{i}.jpg" for i in range(10)]},
           expect_error=True)
assert err["_error"] == 422
print("✓ 超过 9 张被拒")

call("PATCH", "/merchants/me", merchant, {"photo_urls": []})
assert call("GET", f"/merchants/{shop['id']}")["photo_urls"] == []
print("✓ 相册可清空(传空列表)")

print("\n全部通过:公告配置化 / 自建埋点 / 门店相册 ✓")
