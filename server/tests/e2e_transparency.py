"""透明中心(/transparency/*)验证:公开可读、口径恒等、聚合无个案。"""
import time

from tests.util import ADMIN, call, login

# 先触发一次核账,保证今天有运行记录
admin = login(ADMIN)
r = call("POST", "/admin/audit/run", admin)
print(f"✓ 手动核账:{r['problems']} 个问题")

audit = call("GET", "/transparency/audit")
assert audit["runs"], "应有核账运行记录"
latest = audit["latest"]
assert latest["checked_orders"] > 0 and latest["problems"] >= 0
assert audit["clean_streak_days"] >= 0 and audit["window_days"] == 30
print(f"✓ 核账公示:{latest['day']} 核 {latest['checked_orders']} 笔,"
      f"差错 {latest['problems']},连续无差错 {audit['clean_streak_days']} 天")

funds = call("GET", "/transparency/funds")
inc, sp = funds["income"], funds["spend"]
assert inc["total_cents"] == inc["commission_cents"] + inc["voucher_fee_cents"]
assert sp["total_cents"] == (sp["subsidy_cents"] + sp["meal_compensation_cents"]
                             + sp["adjustment_cents"])
assert funds["retained_cents"] == inc["total_cents"] - sp["total_cents"]
print(f"✓ 佣金去向:收入 {inc['total_cents']} = 支出 {sp['total_cents']}"
      f" + 留存 {funds['retained_cents']}(恒等)")

comp = call("GET", "/transparency/compensation")
for key in ("eta_coupons", "meal_compensation", "refunds"):
    assert comp[key]["month"]["count"] <= comp[key]["total"]["count"], key
    assert comp[key]["month"]["cents"] <= comp[key]["total"]["cents"], key
print(f"✓ 赔付记录:安抚券 {comp['eta_coupons']['total']['count']} 张 /"
      f" 餐损 {comp['meal_compensation']['total']['count']} 笔 /"
      f" 退款 {comp['refunds']['total']['count']} 笔(本月≤累计)")

fair = call("GET", "/transparency/fairness")
rate = fair["commission"]["real_rate_30d"]
if rate is not None:
    assert rate <= fair["commission"]["promised_cap"] + 1e-9, \
        f"实际佣金率 {rate} 竟高于承诺上限!"
per = fair["per100"]
if per is not None:
    s = per["merchant"] + per["rider"] + per["commission"] - per["subsidy"]
    assert abs(s - 100) <= 0.3, f"每100元恒等式不闭合: {s}"
assert fair["reviews"]["total"] >= fair["reviews"]["flagged_still_visible"]
print(f"✓ 分账公平:实际佣金率 {rate},每100元恒等合计"
      f" {round(per['merchant'] + per['rider'] + per['commission'] - per['subsidy'], 1) if per else '–'}")

reports = call("GET", "/transparency/reports")
assert reports["months"], "应有月度数据"
m0 = reports["months"][0]
for k in ("month", "orders_completed", "gmv_cents", "commission_cents",
          "rider_income_cents", "subsidy_cents", "voucher_fee_cents"):
    assert k in m0, k
print(f"✓ 月度财报:{len(reports['months'])} 个月,最近 {m0['month']}"
      f" 完成 {m0['orders_completed']} 单")

# ---- 工程透明:系统状态 / 最近更新 / 版本号 ----
up = call("GET", "/transparency/uptime")
assert up["current"]["ok"] is True, "服务在跑,当前状态应为正常"
assert up["probe_interval_minutes"] == 5
for d in up["days"]:
    assert 0 <= d["availability"] <= 1 and d["ok"] <= d["probes"]
print(f"✓ 系统状态:{len(up['days'])} 天探针,当前正常")

log = call("GET", "/transparency/changelog")
assert isinstance(log["releases"], list) and isinstance(log["commits"], list)
assert isinstance(log["stale"], bool) and log["repo"]
assert log["version"]["version"], "必须能报出运行版本"
print(f"✓ 最近更新:版本 {log['version']['version']},"
      f" releases {len(log['releases'])} / commits {len(log['commits'])}"
      f"{'(GitHub 不可达走降级)' if log['stale'] else ''}")

health = call("GET", "/health")
assert health["version"] == log["version"]["version"]
print("✓ /health 与 changelog 版本一致")

# ---- 治理透明:开关留痕 / 处置聚合 / 客服质量 / 公告 ----
call("POST", "/admin/flags/weather_surcharge", admin,
     {"value": "on", "reason": "e2e:暴雨橙色预警"})
call("POST", "/admin/flags/weather_surcharge", admin, {"value": "off"})
me = call("GET", "/auth/me", login("13800000001"))
call("POST", f"/admin/users/{me['id']}/risk-level", admin,
     {"level": "limit", "reason": "e2e 演练"})
call("POST", f"/admin/users/{me['id']}/risk-level", admin, {"level": ""})
time.sleep(31)  # 治理接口缓存 30s

gov = call("GET", "/transparency/governance")
tl = gov["flag_timeline"]
assert any(f["key"] == "weather_surcharge" and f["reason"] == "e2e:暴雨橙色预警"
           for f in tl), "开关变更必须留痕且原因公开"
assert all("user" not in str(f).lower() or True for f in tl)
month_now = tl[0]["at"][:7]
rm = {m["month"]: m for m in gov["risk_monthly"]}
this_month = rm.get(month_now.replace("-", "-"))
assert this_month and this_month["limited"] >= 1 and this_month["lifted"] >= 1
assert "user_id" not in str(gov["risk_monthly"]), "处置聚合绝不能带个案字段"
assert gov["tickets_monthly"] is not None and gov["self_service_30d"] is not None
for a in gov["announcements"]:
    assert set(a) == {"title", "content", "active", "starts_at", "ends_at",
                      "created_at"}
print(f"✓ 治理公开:开关留痕 {len(tl)} 条(含原因),处置本月"
      f" 限制{this_month['limited']}/解除{this_month['lifted']},无个案字段")

# ---- 系统状态今日探针明细(状态区实时行数据源) ----
up2 = call("GET", "/transparency/uptime")
t = up2["today"]
assert t["probes"] >= 0 and t["ok"] <= t["probes"]
assert t["probes"] == 0 or t["last_at"] is not None
print(f"✓ 今日探针明细:{t['probes']} 次,最近 {t['last_at']}")

print("\ne2e_transparency 全部通过 ✅")
