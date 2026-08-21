"""越权与隐私泄露回归(六条实测复现的洞)。

这套用例是**判权专用**的:每一条都对应一次实测能拿到不该拿的数据,
所以断言全部写成"该看不到的人真的看不到",而不是"功能能用"。

写这套的直接教训:e2e_privacy_phone 里有一行注释写着「抢单池也不给真号」,
断言的却是兄弟字段 contact_phone(那个确实打码了),而真号在
privacy_phone 上 —— 那一行从来没被断言过,于是绿了很久。
**断言必须钉在真正会泄露的那个字段上**,注释说的和 assert 写的不是一回事时,
以 assert 为准,而 assert 写错了没人看得出来。

六条:
1. /auth/sms-login 没有任何频控 —— 6 位码、300 秒有效,连打 25 次全 401;
2. /orders/{no} 与 /events /refunds 没有归属校验 —— 第三方账号读到门牌+真名+明文手机号;
3. 抢单池下发顾客真号 —— 骑手只轮询、一单不接就拿到完整 11 位号码与门牌;
4. 品牌区域经理拿得到门店资金明细 —— 与 money_shop 的边界对不上;
5. 酒店店员能改房价 —— 住宿侧漏了餐饮侧那道 owned_shop 闸门;
6. /files 判权里的「上传者本人」是裸子串匹配 —— 判权形同虚设,
   而且它先于按归属查库命中,让「送达留证只给该单顾客」失效。

    SUPERZ_API=http://127.0.0.1:8010 python -m tests.e2e_authz_regression
"""
import asyncio
import json
import random
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from .util import (  # noqa: E402
    ADMIN,
    BASE,
    CUSTOMER,
    MERCHANT,
    RIDER,
    call,
    demo_shop,
    drain_order_pool,
    login,
    register_fresh_customer,
)

# 与 app/routers/auth.py 的阈值对齐。写死是有意的:阈值放宽了这条要跟着改,
# 而不是让用例跟着代码自动"正确"
MAX_WRONG_CODES = 5

JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01" + b"\x00" * 256


# ---------------- 小工具 ----------------

def fresh_phone() -> str:
    return f"1{random.choice('3589')}{random.randrange(10**8, 10**9)}"


def sms_login(phone: str, role: str = "customer") -> str:
    """验证码登录。**必须传 role** —— 不传默认注册成顾客。"""
    code = call("POST", "/auth/sms-code", body={"phone": phone})["dev_code"]
    return call("POST", "/auth/sms-login",
                body={"phone": phone, "code": code, "role": role})["token"]


def upload(token: str, purpose: str, name: str = "t.jpg"):
    """multipart 上传(util.call 只发 JSON,这里手搓一份)。"""
    boundary = "----superz-authz"
    body = b"".join([
        f'--{boundary}\r\nContent-Disposition: form-data; name="purpose"'
        f'\r\n\r\n{purpose}\r\n'.encode(),
        f'--{boundary}\r\nContent-Disposition: form-data; name="file";'
        f' filename="{name}"\r\nContent-Type: image/jpeg\r\n\r\n'.encode()
        + JPEG + b"\r\n",
        f"--{boundary}--\r\n".encode(),
    ])
    req = urllib.request.Request(BASE + "/upload", data=body, method="POST")
    req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def err_code(r):
    """call(expect_error=True) 的返回归一化:成功时它给的是响应体本身
    (可能是 dict 也可能是 list),失败时才是 {"_error": ...}。
    直接 r["_error"] 会在"越权成功"这条路上抛 KeyError/AttributeError,
    把一次真实的越权显示成一个看不懂的类型错误。"""
    return r.get("_error") if isinstance(r, dict) else None


def fetch_code(path: str, token: str | None = None) -> int:
    req = urllib.request.Request(BASE + path)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code


def new_merchant_account(name: str) -> tuple[str, str]:
    phone = fresh_phone()
    token = call("POST", "/auth/register", body={
        "phone": phone, "password": "123456", "name": name,
        "role": "merchant"})["token"]
    return token, phone


def make_paid_order(customer: str, merchant: str, *, contact_phone: str,
                    contact_name: str = "张三",
                    address: str = "测试地址1号") -> tuple[str, dict]:
    """下一单并付掉,返回 (order_no, dish)。"""
    shop = demo_shop()
    dish = call("POST", "/merchants/me/dishes", merchant,
                {"name": f"判权测试菜-{int(time.time()*1000)%10**7}",
                 "price_cents": 2000, "stock": 50})
    order = call("POST", "/orders", customer, {
        "merchant_id": shop["id"],
        "items": [{"dish_id": dish["id"], "quantity": 1}],
        "address": address, "lat": 30.6612, "lng": 104.0823,
        "contact_name": contact_name, "contact_phone": contact_phone,
    })
    call("POST", f"/orders/{order['order_no']}/pay/mock", customer)
    return order["order_no"], dish


def retire(merchant: str, dish: dict) -> None:
    call("PATCH", f"/merchants/me/dishes/{dish['id']}", merchant,
         {"is_on_sale": False}, expect_error=True)


# ---------------- 1. 验证码爆破 ----------------

def t1_sms_code_bruteforce():
    print("\n== 1. 验证码频控 ==")
    phone = fresh_phone()
    real = call("POST", "/auth/sms-code", body={"phone": phone})["dev_code"]
    wrong = "000000" if real != "000000" else "111111"

    codes = []
    for _ in range(25):
        r = call("POST", "/auth/sms-login", expect_error=True,
                 retry_429=False,
                 body={"phone": phone, "code": wrong, "role": "customer"})
        codes.append(err_code(r))
        if err_code(r) != 401:
            break
    assert codes[-1] != 401, (
        f"连打 {len(codes)} 次错码全是 401 —— 6 位码、TTL 300 秒,"
        f"这就是可爆破:{codes}")
    assert len(codes) <= MAX_WRONG_CODES + 1, (
        f"第 {len(codes)} 次才拦住,阈值太松:{codes}")
    print(f"✓ 第 {len(codes)} 次错码不再是 401(得到 {codes[-1]})")

    # 光限速不够:失败到上限就该让这一串码作废,不然等窗口翻转接着打
    r = call("POST", "/auth/sms-login", expect_error=True, retry_429=False,
             body={"phone": phone, "code": real, "role": "customer"})
    assert "token" not in r, "连续错码后真码仍能登录 —— 锁定没让验证码失效"
    print("✓ 触发锁定后真码同样不放行(码已作废,得重新获取)")

    # role 由请求方指定:锁定必须按手机号算,换个 role 接着打是同一个洞
    r = call("POST", "/auth/sms-login", expect_error=True, retry_429=False,
             body={"phone": phone, "code": wrong, "role": "merchant"})
    assert err_code(r) != 401, f"换 role 就能接着爆破:{r}"
    print("✓ 锁定按手机号算,换 role 绕不过去")

    # 反向:别修狠了。手滑几次之后,正确的码仍然要能登进去
    phone2 = fresh_phone()
    real2 = call("POST", "/auth/sms-code", body={"phone": phone2})["dev_code"]
    wrong2 = "000000" if real2 != "000000" else "111111"
    for _ in range(MAX_WRONG_CODES - 1):
        call("POST", "/auth/sms-login", expect_error=True, retry_429=False,
             body={"phone": phone2, "code": wrong2, "role": "customer"})
    ok = call("POST", "/auth/sms-login",
              body={"phone": phone2, "code": real2, "role": "customer"})
    assert ok.get("token"), f"手滑 {MAX_WRONG_CODES - 1} 次后正确码被误伤:{ok}"
    print(f"✓ 手滑 {MAX_WRONG_CODES - 1} 次后正确的码照常放行(没修狠)")


# ---------------- 2. 订单归属校验 ----------------

def t2_order_ownership():
    print("\n== 2. 订单接口归属校验 ==")
    customer, merchant = login(CUSTOMER), login(MERCHANT)
    rider, admin = login(RIDER), login(ADMIN)
    no, dish = make_paid_order(customer, merchant,
                               contact_phone="13911110001",
                               contact_name="王越权",
                               address="越权路7号2栋301室")

    third = register_fresh_customer()
    outsider_rider = sms_login(fresh_phone(), "rider")
    outsider_merchant = sms_login(fresh_phone(), "merchant")

    for who, tok in (("第三方顾客", third), ("无关骑手", outsider_rider),
                     ("无关商家", outsider_merchant)):
        for suffix in ("", "/events", "/refunds"):
            r = call("GET", f"/orders/{no}{suffix}", tok, expect_error=True)
            assert err_code(r) == 404, (
                f"{who} 读到了 /orders/{{no}}{suffix} —— "
                f"门牌/真名/明文手机号一起下发:{r}")
    print("✓ 第三方顾客 / 无关骑手 / 无关商家读 详情+事件+退款流水 全部 404")

    # 正向:四种角色各自的合法范围一个都不能误伤
    assert call("GET", f"/orders/{no}", customer)["order_no"] == no
    assert call("GET", f"/orders/{no}", merchant)["order_no"] == no
    assert call("GET", f"/orders/{no}", admin)["order_no"] == no
    for tok in (customer, merchant, admin):
        call("GET", f"/orders/{no}/events", tok)
        call("GET", f"/orders/{no}/refunds", tok)
    print("✓ 顾客本人 / 该单商家 / admin 三个接口照常 200")

    # 该单商家的店员也在合法范围内(接单机就是店员在用)
    staff_phone = fresh_phone()
    staff = sms_login(staff_phone, "merchant")
    added = call("POST", "/merchants/me/staff", merchant,
                 {"phone": staff_phone, "name": "判权测试店员"})
    try:
        staff = call("POST", "/auth/refresh", staff)["token"]
        assert call("GET", f"/orders/{no}", staff)["order_no"] == no, \
            "本店店员读不到本店订单 —— 修狠了,接单机会瞎"
        call("GET", f"/orders/{no}/events", staff)
        print("✓ 该单商家的店员照常可读(合法范围含店员)")
    finally:
        call("DELETE", f"/merchants/me/staff/{added['user_id']}", merchant,
             expect_error=True)

    # 该单骑手:抢单之后进入合法范围
    call("POST", f"/orders/{no}/transition", merchant, {"to_status": "accepted"})
    call("POST", f"/riders/grab/{no}", rider)
    assert call("GET", f"/orders/{no}", rider)["order_no"] == no
    call("GET", f"/orders/{no}/events", rider)
    print("✓ 该单骑手抢单后照常可读")

    call("POST", f"/orders/{no}/transition", merchant,
         {"to_status": "cancelled", "reason": "判权测试收尾"})
    retire(merchant, dish)


# ---------------- 3. 抢单池不下发真号/门牌/真名 ----------------

REAL_POOL_PHONE = "13912340001"
MASKED_POOL_PHONE = "139****0001"


def t3_grab_pool_privacy():
    print("\n== 3. 抢单池隐私 ==")
    customer, merchant, rider = login(CUSTOMER), login(MERCHANT), login(RIDER)
    no, dish = make_paid_order(customer, merchant,
                               contact_phone=REAL_POOL_PHONE,
                               contact_name="赵四海",
                               address="赞测路88号3栋502室")
    call("POST", f"/orders/{no}/transition", merchant, {"to_status": "accepted"})

    # 池子只回前 50 条,残留一多新单就被挤出去。**先看看在不在**,
    # 不在才清场 —— drain 会把池里所有无骑手的单按无人接单兜底取消掉,
    # 无条件调用等于每跑一次就误伤一批别人正在用的单
    pool = call("GET", "/riders/available-orders", rider)
    row = next((o for o in pool if o["order_no"] == no), None)
    if row is None:
        asyncio.run(drain_order_pool())
        pool = call("GET", "/riders/available-orders", rider)
        row = next(o for o in pool if o["order_no"] == no)

    # **断言 privacy_phone 这个字段** —— 兄弟字段 contact_phone 一直是打码的,
    # 真号在这一个上,原来那条注释说的和 assert 写的不是一回事
    dial = row.get("privacy_phone") or ""
    assert not re.fullmatch(r"\d{11}", dial), (
        f"骑手只轮询、一单没接就拿到完整 11 位真号:privacy_phone={dial}")
    assert REAL_POOL_PHONE not in json.dumps(row, ensure_ascii=False), \
        f"抢单池整行里出现了真号:{row}"
    assert row["contact_phone"] == MASKED_POOL_PHONE, row["contact_phone"]
    assert "502" not in row["address"], \
        f"抢单池给了完整门牌:{row['address']}"
    assert row["contact_name"] != "赵四海" and "四海" not in row["contact_name"], \
        f"抢单池给了真名:{row['contact_name']}"
    print(f"✓ 未接单:无可拨号码({dial!r})、地址粗化({row['address']!r})、"
          f"姓名只留姓({row['contact_name']!r})")

    # 抢到之后再给全 —— 没接单的人本来就不需要联系顾客,接了就需要
    grabbed = call("POST", f"/riders/grab/{no}", rider)
    assert grabbed["privacy_phone"] == REAL_POOL_PHONE, \
        f"抢到之后拿不到可拨号码,骑手打不通电话:{grabbed['privacy_phone']!r}"
    assert "502" in grabbed["address"] and grabbed["contact_name"] == "赵四海"
    detail = call("GET", f"/orders/{no}", rider)
    assert detail["privacy_phone"] == REAL_POOL_PHONE
    assert detail["contact_phone"] == MASKED_POOL_PHONE, "真号只走 privacy_phone"
    print("✓ 抢到之后:可拨号码/门牌/真名照常下发,contact_phone 仍打码")

    call("POST", f"/orders/{no}/transition", merchant,
         {"to_status": "cancelled", "reason": "判权测试收尾"})
    retire(merchant, dish)


# ---------------- 4. 区域经理碰不到门店资金明细 ----------------

def t4_brand_manager_finance():
    print("\n== 4. 区域经理 vs 门店资金明细 ==")
    boss, _ = new_merchant_account("判权连锁老板")
    shop1 = call("POST", "/merchants", boss, {
        "name": f"判权总店{random.randrange(10**4)}", "description": "e2e",
        "address": "判权路 1 号", "lat": 30.66, "lng": 104.08,
        "license_no": f"JYAUTHZ{random.randrange(10**9)}",
        "license_image_url": "/uploads/license-demo.jpg"})
    call("POST", "/brands/me", boss,
         {"name": f"判权牌{random.randrange(10**4)}", "shop_id": shop1["id"]})
    shop2 = call("POST", "/brands/me/shops", boss, {
        "copy_from": shop1["id"], "name": f"判权二店{random.randrange(10**4)}",
        "address": "判权路 2 号", "lat": 30.67, "lng": 104.09,
        "license_no": f"JYAUTHZ{random.randrange(10**9)}",
        "license_image_url": "/uploads/license-demo-2.jpg"})

    mgr, mgr_phone = new_merchant_account("判权区域经理")
    call("POST", "/brands/me/members", boss,
         {"phone": mgr_phone, "shop_ids": [shop2["id"]]})
    h2 = {"X-Shop-Id": shop2["id"]}
    today = date.today().isoformat()

    # 经理确实管得着这家店(否则下面的 403 可能只是"店都找不到")
    assert call("GET", "/merchants/me", mgr, headers=h2)["id"] == shop2["id"]

    paths = ("/merchants/me/finance/daily",
             f"/merchants/me/finance/orders?day={today}",
             "/merchants/me/finance/statement.csv")
    for path in paths:
        r = call("GET", path, mgr, headers=h2, expect_error=True)
        assert err_code(r) == 403, (
            f"{path} 对区域经理开放了 —— 与 money_shop 同一条边界:"
            f"改价改设置可以,碰钱不行。实际 {r}")
    print("✓ 区域经理拿 403:日对账 / 入账明细 / 对账单 CSV")

    # 反向:店主本人照常(这条防"修狠了把店主也拦了")
    call("GET", "/merchants/me/finance/daily", boss, headers=h2)
    call("GET", f"/merchants/me/finance/orders?day={today}", boss, headers=h2)
    print("✓ 店主本人照常 200")


# ---------------- 5. 酒店店员改不了房价 ----------------

def t5_hotel_staff_price():
    print("\n== 5. 酒店店员 vs 改房价 ==")
    admin = login(ADMIN)
    owner, _ = new_merchant_account("判权酒店老板")
    hotel = call("POST", "/merchants", owner, {
        "name": f"判权客栈{random.randrange(10**4)}", "description": "e2e",
        "address": "判权路 3 号", "lat": 30.66, "lng": 104.06,
        "biz_type": "hotel",
        "license_no": f"91510100MA6AUTHZ{random.randrange(10**4)}",
        "license_image_url": "https://example.com/biz-license.jpg",
        "hotel": {
            "tier": "comfort", "front_desk_phone": "02888888888",
            "checkin_from": "14:00", "checkout_until": "12:00",
            "facilities": ["wifi"],
            "special_license_no": "川公治安 2026-999",
            "special_license_image_url": "https://example.com/special.jpg",
        }})
    call("POST", f"/admin/merchants/{hotel['id']}/approve", admin)
    rt = call("POST", "/stays/me/room-types", owner,
              {"name": "判权大床房", "bed_type": "大床", "max_guests": 2})

    staff_phone = fresh_phone()
    staff = sms_login(staff_phone, "merchant")
    call("POST", "/merchants/me/staff", owner,
         {"phone": staff_phone, "name": "前台"})
    staff = call("POST", "/auth/refresh", staff)["token"]

    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    calendar_body = {"room_type_ids": [rt["id"]], "from_date": tomorrow,
                     "to_date": tomorrow, "price_cents": 9900}

    denied = [
        ("PUT", "/stays/me/calendar", calendar_body),
        ("PATCH", f"/stays/me/room-types/{rt['id']}", {"name": "店员改的"}),
        ("POST", "/stays/me/room-types", {"name": "店员新建的房型"}),
        ("PATCH", "/stays/me/profile", {"front_desk_phone": "02866666666"}),
    ]
    for method, path, body in denied:
        r = call(method, path, staff, body, expect_error=True)
        assert err_code(r) == 403, (
            f"{method} {path} 店员做成了 —— services/staff.py 定的规矩是"
            f"敏感端点(提现/改价/改设置)店员一律拒,餐饮侧照做了,"
            f"住宿侧没有。实际 {r}")
    print("✓ 店员改房价/改房型/建房型/改酒店资料 全部 403")

    # 反向:店员的运营视野照旧,店主照常能改
    assert any(x["id"] == rt["id"]
               for x in call("GET", "/stays/me/room-types", staff))
    call("GET", "/stays/me/calendar", staff)
    print("✓ 店员照常看房型/看房态(运营端点不受影响)")
    r = call("PUT", "/stays/me/calendar", owner, calendar_body)
    assert r.get("created", 0) + r.get("updated", 0) >= 1, r
    call("PATCH", "/stays/me/profile", owner,
         {"front_desk_phone": "02877777777"})
    print("✓ 店主本人改房价/改资料照常成功")


# ---------------- 6. /files 判权:owner 段 + 送达留证 ----------------

def _owner_segment_check(attacker_id: int, victim_id: int) -> bool:
    """在进程内直接问判权函数:裸子串放行的那条路还在不在。

    这一条**在 HTTP 上打不出来**:存储层要求 key 精确匹配,拼出来的路径
    读不到对象,于是表现成 404 而不是 200。但判权函数本身已经放行了 ——
    换一个宽松点的后端(或者哪天加了个按 basename 兜底的读法)就是真泄露。
    所以钉在函数上,不钉在响应码上。
    """
    async def _run() -> bool:
        from sqlalchemy import select
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

        from app.config import settings
        from app.models import User
        from app.routers.uploads import _may_read_private

        # 每次现开一个引擎再销毁:asyncio.run 每调一次换一个事件循环,
        # 复用 app.db 的全局引擎会撞上"连接属于另一个 loop"
        engine = create_async_engine(settings.database_url)
        try:
            async with async_sessionmaker(engine)() as db:
                attacker = await db.scalar(
                    select(User).where(User.id == attacker_id))
                crafted = (f"u{attacker.id}-/id_card/"
                           f"u{victim_id}-{'a' * 32}.jpg")
                return await _may_read_private(crafted, attacker, db)
        finally:
            await engine.dispose()

    return asyncio.run(_run())


def t6a_owner_segment():
    """(a) 裸子串:`/u{id}-` 出现在路径**任意位置**就短路放行。"""
    print("\n== 6a. 私密文件判权:上传者本人只认首个 owner 段 ==")
    customer = login(CUSTOMER)
    me = call("GET", "/auth/me", customer)

    leaked = _owner_segment_check(me["id"], me["id"] + 100000)
    assert not leaked, (
        "判权里的「上传者本人」是裸子串匹配:路径里任意位置出现 "
        f"/u{me['id']}- 就返回 True,下面按归属查库的分支一条都不执行")
    print("✓ 「上传者本人」只认 key 的首个 owner 段,拼路径绕不过去")

    crafted = f"/files/u{me['id']}-/id_card/u{me['id'] + 100000}-{'a' * 32}.jpg"
    assert fetch_code(crafted, customer) == 403, \
        "拼出来的路径应当直接判权不足(403),而不是靠存储层读不到兜底"
    print("✓ 同一条路径在 HTTP 上也是 403(不再靠存储层兜底)")


def t6b_delivery_proof():
    """(b) 送达留证:只给该单顾客。骑手拍完就不该再看得到 ——
    那是别人家门口的照片,拍摄者没有持续查看的正当理由。"""
    print("\n== 6b. 私密文件判权:送达留证只给该单顾客 ==")
    customer, merchant, rider = login(CUSTOMER), login(MERCHANT), login(RIDER)
    no, dish = make_paid_order(customer, merchant,
                               contact_phone="13911110002",
                               address="留证路5号1单元802室")
    call("POST", f"/orders/{no}/transition", merchant, {"to_status": "accepted"})
    call("POST", f"/orders/{no}/transition", merchant, {"to_status": "ready"})
    call("POST", f"/riders/grab/{no}", rider)
    call("POST", f"/orders/{no}/transition", rider, {"to_status": "picked_up"})
    proof = upload(rider, "delivery_proof")
    assert proof["url"].startswith("/files/"), proof
    call("POST", f"/orders/{no}/transition", rider,
         {"to_status": "delivered", "photo_url": proof["url"]})

    assert fetch_code(proof["url"], customer) == 200, \
        "该单顾客读不到自己家门口的留证照 —— 修狠了"
    assert fetch_code(proof["url"], rider) == 403, (
        "骑手能长期回看别人家门口的照片:「上传者本人」那条先于"
        "按归属查库命中,把「留证只给该单顾客」整条架空了")
    assert fetch_code(proof["url"], register_fresh_customer()) == 403
    print("✓ 送达留证:该单顾客 200 / 拍照的骑手 403 / 第三方 403")

    call("POST", f"/orders/{no}/transition", customer, {"to_status": "completed"},
         expect_error=True)
    retire(merchant, dish)


def main() -> None:
    t1_sms_code_bruteforce()
    t2_order_ownership()
    t3_grab_pool_privacy()
    t4_brand_manager_finance()
    t5_hotel_staff_price()
    t6a_owner_segment()
    t6b_delivery_proof()
    print("\n越权与隐私泄露回归全部通过 🎉")


if __name__ == "__main__":
    only = sys.argv[1] if len(sys.argv) > 1 else ""
    if only:
        globals()[next(k for k in globals() if k.startswith(only))]()
    else:
        main()
