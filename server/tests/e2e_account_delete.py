"""账号注销验证(M4 上架合规硬性要求)。

  1. 新注册用户可直接注销:手机号匿名化、旧 token 失效、原手机号可重新注册
  2. 有进行中订单的用户被拒(409),完结后可注销
  3. 商家账号有店铺 → 引导走客服工单(409)
  4. **实名信息真的删了**:注销页写着"实名信息一并删除",这条钉住它
  5. 墓碑行不再参与业务:ref_code / is_online 清零
  6. 风控标记跟着手机号走:注销再注册不等于洗白
在 server/ 目录下运行:python -m tests.e2e_account_delete
"""
import asyncio
import time

from tests.util import demo_shop, call, login, orderable_dish

tag = str(int(time.time()))
phone = "138" + tag[-8:]

# ---- 1. 干净账号直接注销 ----
token = call("POST", "/auth/register",
             body={"phone": phone, "password": "123456", "name": "过客", "role": "customer"})["token"]
call("DELETE", "/auth/me", token)
print("✓ 新用户注销成功")

err = call("GET", "/auth/me", token, expect_error=True)
assert err["_error"] == 401, "注销后旧 token 应失效"
print("✓ 注销后旧 token 立即失效(401)")

err = call("POST", "/auth/login", body={"phone": phone, "password": "123456"}, expect_error=True)
assert err["_error"] == 401, "注销后原手机号不能再登录旧账号"
token2 = call("POST", "/auth/register",
              body={"phone": phone, "password": "654321", "name": "重来", "role": "customer"})["token"]
print("✓ 手机号已释放,可重新注册全新账号")

# ---- 2. 有在途订单时拒绝 ----
shops = call("GET", "/merchants?lat=30.6612&lng=104.0823")
sid = demo_shop()["id"]
dishes = call("GET", f"/merchants/{sid}/dishes")
dish = orderable_dish(dishes)  # 统一走公共挑菜:跳过酒类(要实名)与估清的菜
order = call("POST", "/orders", token2, {
    "merchant_id": sid,
    "items": [{"dish_id": dish["id"], "quantity": 1}],
    "address": "注销测试地址", "lat": 30.6612, "lng": 104.0823,
})
err = call("DELETE", "/auth/me", token2, expect_error=True)
assert err["_error"] == 409 and "进行中" in err["detail"]
print(f"✓ 有在途订单被拒:{err['detail']}")

call("POST", f"/orders/{order['order_no']}/transition", token2, {"to_status": "cancelled"})
call("DELETE", "/auth/me", token2)
print("✓ 订单完结后注销成功")

# ---- 3. 商家有店铺时引导客服 ----
merchant = login("13800000002")
err = call("DELETE", "/auth/me", merchant, expect_error=True)
assert err["_error"] == 409 and "客服" in err["detail"]
print(f"✓ 商家有店铺被引导走客服:{err['detail']}")

# ---- 4/5. 骑手注销:实名信息真删,墓碑行不再参与业务 ----
#
# 注销页的原话是「实名信息一并删除」。用户侧(user_identities)一直是
# 删的,骑手侧(rider_profiles 的 real_name / id_no_encrypted / 紧急联系人)
# 在 0108 之前**一个字都没删** —— 说的和做的不是一回事。这段钉住它。
#
# 断言必须查库:接口层看不见 rider_profiles 还在不在,
# 而"接口不返回"和"数据已删除"是两码事,承诺说的是后者。
def _user_state(uid):
    """直接查库。接口层看不见 rider_profiles / 墓碑列还在不在,
    而"接口不返回"和"数据已删除"是两码事,承诺说的是后者。"""
    async def _go():
        from sqlalchemy import text as _text

        from app.db import SessionLocal as _S
        from app.db import engine as _e
        async with _S() as db:
            row = (await db.execute(_text(
                "SELECT deleted_at, ref_code, is_online, birthday FROM users"
                " WHERE id = :i"), {"i": uid})).first()
            counts = {}
            for table, col in (("rider_profiles", "rider_id"),
                               ("addresses", "user_id"),
                               ("user_identities", "user_id")):
                counts[table] = (await db.execute(_text(
                    f"SELECT count(*) FROM {table} WHERE {col} = :i"),
                    {"i": uid})).scalar()
        await _e.dispose()  # 多次 asyncio.run:释放连接池防事件循环串台
        return row, counts
    return asyncio.run(_go())


rphone = "139" + tag[-8:]
rider_tok = call("POST", "/auth/register", body={
    "phone": rphone, "password": "123456", "name": "注销骑手",
    "role": "rider"})["token"]
rider_id = call("GET", "/auth/me", rider_tok)["id"]
call("POST", "/riders/profile", rider_tok,
     {"real_name": "测试骑手", "id_card_no": "110101199003072316"})
assert call("GET", "/riders/profile", rider_tok)["real_name"], \
    "实名信息应先存在,否则下面的删除断言是空转"
call("POST", "/riders/online", rider_tok, {"is_online": True},
     expect_error=True)  # 城市/认证等原因可能拒,下面按实际值判

before, before_n = _user_state(rider_id)
assert before_n["rider_profiles"] == 1, \
    f"注销前实名行应存在,实得 {before_n['rider_profiles']}(断言会空转)"

call("DELETE", "/auth/me", rider_tok)
after, after_n = _user_state(rider_id)
assert after_n["rider_profiles"] == 0, (
    f"注销页承诺「实名信息一并删除」,rider_profiles 仍有 "
    f"{after_n['rider_profiles']} 行")
print("✓ 骑手实名信息(姓名/证号/紧急联系人)随注销真的删掉了")
assert after.deleted_at is not None, "deleted_at 应被写上(墓碑判据)"
assert after.is_online is False, "is_online 未重置,会被算进在线骑手/派单广播"
print("✓ 骑手墓碑行:deleted_at 已写、is_online 已归零")

# 用户侧:邀请码 / 地址簿 / 生日。邀请码是懒生成的,先让它真的生成出来,
# 否则"注销后 ref_code 为空"那条断言测的是"它本来就是空"
cphone = "136" + tag[-8:]
cust_tok = call("POST", "/auth/register", body={
    "phone": cphone, "password": "123456", "name": "注销用户",
    "role": "customer"})["token"]
cust_id = call("GET", "/auth/me", cust_tok)["id"]
code = call("GET", "/referrals/me", cust_tok)["code"]
assert code and len(code) == 6, f"邀请码没生成出来:{code!r}"
call("PATCH", "/auth/me", cust_tok, {"birthday": "01-02"})
call("POST", "/addresses", cust_tok, {
    "contact_name": "注销用户", "contact_phone": cphone,
    "address": "注销测试地址", "detail": "1 单元", "lat": 30.6612,
    "lng": 104.0823})
cbefore, cbefore_n = _user_state(cust_id)
assert cbefore.ref_code == code and cbefore_n["addresses"] >= 1, \
    f"前置数据没建起来:ref_code={cbefore.ref_code!r} {cbefore_n}"

call("DELETE", "/auth/me", cust_tok)
cafter, cafter_n = _user_state(cust_id)
assert cafter.ref_code is None, f"邀请码未清空:{cafter.ref_code!r}"
assert cafter.birthday == "", f"生日未清空:{cafter.birthday!r}"
assert cafter_n["addresses"] == 0, f"地址簿仍有 {cafter_n['addresses']} 行"
print("✓ 用户墓碑行:ref_code / 生日 / 地址簿都清干净了")
# 墓碑上的邀请码不能还被解析出来。两个坑都得躲开:
#   ① 拿注销掉的号去填只会撞 401 —— 那是在测别的东西,所以另开活账号;
#   ② 营销总开关默认是关的,关着的时候 claim 一律 409「活动暂未开启」,
#      根本走不到查 ref_code 那一步 —— 断言会永远绿。所以先开、断言、再还原。
admin = login("13800000000")
_orig_marketing = call("GET", "/admin/flags", admin).get("marketing", "off")
call("POST", "/admin/flags/marketing", admin, {"value": "on"})
try:
    newbie = call("POST", "/auth/register", body={
        "phone": "135" + tag[-8:], "password": "123456", "name": "新人",
        "role": "customer"})["token"]
    err = call("POST", "/referrals/claim", newbie, {"code": code},
               expect_error=True)
    assert err["_error"] == 404 and "不存在" in err.get("detail", ""), (
        f"已注销账号的邀请码仍被解析:{err}")
finally:
    call("POST", "/admin/flags/marketing", admin, {"value": _orig_marketing})
print(f"✓ 已注销账号的邀请码不再被解析(404 {err['detail']})")

# ---- 6. 风控标记跟着手机号走:注销 ≠ 洗白 ----
#
# 注销把手机号释放掉("可重新注册"),标记留在旧行上的话,
# 「注销 → 再注册」就是一个自助的、零成本的洗白按钮,而
# after_sale_banned 是"恶意售后"黑名单,这个洞直接对着钱。
wphone = "137" + tag[-8:]
wash_tok = call("POST", "/auth/register", body={
    "phone": wphone, "password": "123456", "name": "洗白测试",
    "role": "customer"})["token"]
wash_id = call("GET", "/auth/me", wash_tok)["id"]
call("POST", f"/admin/users/{wash_id}/risk-level", admin,
     {"level": "limit", "reason": "刷单嫌疑"})
call("POST", f"/admin/users/{wash_id}/after-sale-ban", admin, {"banned": True})
call("DELETE", "/auth/me", wash_tok)
again = call("POST", "/auth/register", body={
    "phone": wphone, "password": "123456", "name": "洗白测试2",
    "role": "customer"})
me2 = call("GET", "/auth/me", again["token"])
assert me2["risk_level"] == "limit", (
    f"注销再注册把风控分级洗掉了:{me2['risk_level']!r}")
assert me2["risk_note"], "风控标记必须带可见的原因(口径:可见且可申诉)"
print(f"✓ 风控标记跟随手机号:重新注册后仍为 {me2['risk_level']}"
      f"({me2['risk_note']})")
# after_sale_banned 同样跟随。用一个不存在的单号就够 —— 禁令是这个
# 端点的**第一道**检查,在查订单之前,所以 403 只可能来自黑名单;
# 没跟随的话会是 404「订单不存在」,两者分得开
banned = call("POST", "/orders/NOPE-NOT-EXIST/after-sale", again["token"],
              {"reason": "餐品洒了要退款", "kind": "refund",
               "images": ["http://x/1.jpg"]}, expect_error=True)
assert banned["_error"] == 403, (
    f"售后黑名单被注销洗掉了(期望 403 受限,实得 {banned})")
print(f"✓ 售后黑名单同样跟随:{banned['detail']}")

# 同一手机号换个角色不该被殃及:假名带了 role
other_role = call("POST", "/auth/register", body={
    "phone": wphone, "password": "123456", "name": "换角色", "role": "rider"})
assert call("GET", "/auth/me", other_role["token"])["risk_level"] == "", \
    "假名带了 role,别的角色不该被同一手机号的标记殃及"
print("✓ 标记按 (手机号, 角色) 生效,不误伤同号的其他角色账号")

print("\n账号注销全流程验证通过 🎉")
