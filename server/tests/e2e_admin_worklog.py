"""运力后台补全:骑手考试成绩可见(#27)+ 在线时长考勤明细(#28)+ 天气停运开关(#26)。"""
import asyncio
from datetime import datetime, timedelta, timezone

from tests.util import call, login

admin = login("13800000000")
customer = login("13800000001")
merchant = login("13800000002")
rider = login("13800000003")

# 骑手 user_id:从后台骑手列表拿(演示骑手小王已实名通过)
profiles = call("GET", "/admin/rider-profiles", admin)
wang = next(p for p in profiles if p["rider_id"])
RID = wang["rider_id"]


def seed():
    """直连 DB 造一条通过的考试 + 两天在线区间(避免依赖题库答案)。"""
    async def _run():
        from app.db import SessionLocal, engine
        from app.models import RiderExam, RiderSession
        now = datetime.now(timezone.utc)
        async with SessionLocal() as db:
            db.add(RiderExam(rider_id=RID, score=70, passed=False, answers={}))
            db.add(RiderExam(rider_id=RID, score=90, passed=True, answers={}))
            # 昨天在线 2 小时(闭区间)+ 今天在线中(开区间,1 小时前上线)
            db.add(RiderSession(rider_id=RID,
                                online_at=now - timedelta(days=1, hours=2),
                                offline_at=now - timedelta(days=1)))
            db.add(RiderSession(rider_id=RID,
                                online_at=now - timedelta(hours=1),
                                offline_at=None))
            await db.commit()
        await engine.dispose()
    asyncio.run(_run())


seed()

# ---- #27 考试成绩后台可见 ----
profiles = call("GET", "/admin/rider-profiles", admin)
me = next(p for p in profiles if p["rider_id"] == RID)
assert me["exam_passed"] is True, me
assert me["exam_best_score"] == 90, f"应取最高分,实际 {me['exam_best_score']}"
assert me["exam_at"] is not None
print(f"✓ #27 后台骑手视图:已通过,最高 {me['exam_best_score']} 分")

# ---- #28 考勤明细 ----
wl = call("GET", f"/admin/riders/{RID}/worklog?days=14", admin)
# 昨天 120 分钟 + 今天约 60 分钟(未闭合计到当前)
assert wl["total_minutes"] >= 175, f"总时长应≥175,实际 {wl['total_minutes']}"
assert wl["active_days"] == 2, f"活跃天数应为 2,实际 {wl['active_days']}"
assert len(wl["days"]) == 2
# 今天那条区间应显示"在线中"
today_segs = [s for d in wl["days"] for s in d["sessions"]]
assert any(s["offline_at"] == "在线中" for s in today_segs), "未闭合区间应标在线中"
print(f"✓ #28 考勤:总在线 {wl['total_minutes']} 分,活跃 {wl['active_days']} 天,"
      f"未闭合区间计到当前")

# 越权:非 admin 拿不到
err = call("GET", f"/admin/riders/{RID}/worklog", rider, expect_error=True)
assert err["_error"] == 403
print("✓ #28 非管理员访问考勤 403")

# ---- #26 天气停运开关 ----
dish = call("POST", "/merchants/me/dishes", merchant,
            {"name": f"停运测试菜-{int(datetime.now().timestamp())}",
             "price_cents": 2000, "stock": 50})
body = {"merchant_id": next(m["id"] for m in
                            call("GET", "/merchants?lat=30.6612&lng=104.0823")
                            if m["name"] == "张记面馆"),
        "items": [{"dish_id": dish["id"], "quantity": 1}],
        "address": "测试地址1号", "lat": 30.6612, "lng": 104.0823,
        "contact_name": "测试", "contact_phone": "13800000001"}
call("POST", "/admin/flags/weather_shutdown", admin, {"value": "on"})
err = call("POST", "/orders", customer, body, expect_error=True)
assert err["_error"] == 409, err
print(f"✓ #26 停运开启后下单被拒:{err['detail'][:30]}…")
call("POST", "/admin/flags/weather_shutdown", admin, {"value": "off"})
order = call("POST", "/orders", customer, body)
assert order["order_no"]
print("✓ #26 停运解除后恢复接单")

# 收尾:关订单退款、下架菜
call("POST", f"/orders/{order['order_no']}/pay/mock", customer)
call("POST", f"/orders/{order['order_no']}/transition", merchant,
     {"to_status": "cancelled", "reason": "测试收尾"})
call("PATCH", f"/merchants/me/dishes/{dish['id']}", merchant, {"is_on_sale": False})
print("\n运力后台补全(考试成绩+考勤明细+停运开关)验证通过 🎉")
