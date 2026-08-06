"""多台云打印机 + 小票用途(第十二批 AE)。

前厅一台出顾客小票、后厨一台出备餐单,是餐饮的标配。原先只有
Merchant.printer_sn 一个字段,后厨想要单子只能跟前厅共用一台。

本用例的重点是那条**隐私边界**:后厨那张备餐单**不印顾客手机号和地址**。
后厨用不到这两项,而备餐单会被随手丢在操作台上、下班扫进垃圾桶 ——
一张纸就是一条个人信息泄露。

飞鹅未配置时(本地/CI 常态)绑定接口会 503,所以绑定相关的断言按
enabled 分支跳过;**小票内容的断言不依赖飞鹅**,直接对 build_ticket
下断言 —— 那才是隐私边界所在,不能因为环境没配就不测。
"""
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from .util import ADMIN, call, login  # noqa: E402

admin = login(ADMIN)


def new_shop(name: str):
    phone = f"1{random.choice('3589')}{random.randrange(10**8, 10**9)}"
    tok = call("POST", "/auth/register", body={
        "phone": phone, "password": "123456", "name": name,
        "role": "merchant"})["token"]
    shop = call("POST", "/merchants", tok, {
        "name": name, "address": "打印路 1 号", "lat": 30.66, "lng": 104.08,
        "license_no": f"JYPR{random.randrange(10**9)}",
        "license_image_url": "/uploads/license-demo.jpg"})
    call("POST", f"/admin/merchants/{shop['id']}/approve", admin)
    return tok, shop


def check_ticket_privacy():
    """小票用途决定印什么 —— 直接对排版函数下断言,不依赖飞鹅配置。"""
    from datetime import datetime, timezone
    from types import SimpleNamespace

    from app.services.cloud_print import build_ticket

    order = SimpleNamespace(
        order_no="SZ20260806000123", created_at=datetime.now(timezone.utc),
        pickup=False, pickup_code="", parent_order_no="", scheduled_at=None,
        remark="不要香菜", items=[{"name": "牛腩饭", "quantity": 2,
                                "price_cents": 2800, "is_alcohol": False}],
        food_cents=5600, packing_fee_cents=700, discount_cents=0,
        delivery_fee_cents=300, total_cents=6600,
        contact_name="张先生", contact_phone="13800001234",
        privacy_phone="", address="成都市高新区天府大道 1 号 3 栋 502")

    front = build_ticket(order, "赞小碗")
    assert "张先生" in front and "天府大道" in front, \
        "前厅那张要印收件人与地址(骑手来取要核对)"
    assert "6600" not in front or "66.00" in front
    print("✓ 前厅小票:含收件人、地址、金额")

    kitchen = build_ticket(order, "赞小碗", purpose="kitchen")
    assert "天府大道" not in kitchen, \
        "后厨备餐单不该印地址 —— 单子会被随手丢在操作台上"
    assert "张先生" not in kitchen, "后厨备餐单不该印收件人"
    assert "1234" not in kitchen and "138" not in kitchen, \
        "后厨备餐单不该印任何手机号(包括打码号)"
    assert "牛腩饭" in kitchen and "不要香菜" in kitchen, \
        "后厨要的是菜和备注"
    assert "66.00" not in kitchen, "后厨看金额没有用"
    print("✓ 后厨备餐单:有菜与备注,**无手机号、无地址、无金额**")

    label = build_ticket(order, "赞小碗", purpose="label")
    assert "000123" in label and "赞小碗" in label, label
    assert "天府大道" not in label and "138" not in label, \
        f"标签贴在袋子外面,更不能有地址电话:{label}"
    print("✓ 标签:只有店名与单号后六位(贴在袋子外面,信息最少)")

    # 自取单:后厨也要取餐码(顾客到店报码)
    order.pickup = True
    order.pickup_code = "8842"
    k2 = build_ticket(order, "赞小碗", purpose="kitchen")
    assert "8842" in k2, "自取单后厨要看到取餐码"
    print("✓ 自取单后厨单带取餐码")


def check_webhook_ssrf():
    """回调地址校验 —— **这是整块最该守的一条**。

    我们拿服务端的网络位置去访问一个**商家填的地址**。不拦的话:
    169.254.169.254 是云厂商的元数据服务(能读出实例的临时凭证),
    127.0.0.1 能借我们的身份打内网。
    """
    from app.services.webhooks import UnsafeUrl, validate_url

    must_block = [
        ("http://169.254.169.254/latest/meta-data/", "云厂商元数据服务"),
        ("http://127.0.0.1:8010/admin", "回环地址"),
        ("http://localhost/hook", "localhost"),
        ("http://10.0.0.5/hook", "内网 A 段"),
        ("http://192.168.1.10/hook", "内网 C 段"),
        ("https://example.com:8443/hook", "非默认端口"),
        ("ftp://example.com/hook", "非 http(s)"),
        ("not-a-url", "不是 URL"),
    ]
    for url, why in must_block:
        try:
            validate_url(url)
            raise AssertionError(f"必须拦住({why}):{url}")
        except UnsafeUrl:
            pass
    print(f"✓ 回调地址 SSRF 防护:{len(must_block)} 类全部拦住"
          "(含云元数据 169.254.169.254)")

    validate_url("https://example.com/hook")
    validate_url("http://example.com:80/hook")
    print("✓ 正常的公网地址放行")

    # 签名把时间戳纳进去:只签 body 的话录一个包就能无限重放
    from app.services.webhooks import sign
    a = sign("s3cret", b'{"a":1}', "1000")
    b = sign("s3cret", b'{"a":1}', "1001")
    assert a != b, "时间戳必须参与签名,否则录下来的请求能无限重放"
    assert sign("other", b'{"a":1}', "1000") != a, "换密钥签名必须变"
    print("✓ 签名含时间戳(防重放)、随密钥变化")


def check_webhook_payload_privacy():
    """推给商家系统的订单体**不含顾客真实手机号** ——
    与小票、开放接口同一个口径:顾客的号码不因为商家接了个系统就明文流出去。"""
    from datetime import datetime, timezone
    from types import SimpleNamespace

    from app.services.webhooks import build_payload

    order = SimpleNamespace(
        order_no="SZ20260806000999", created_at=datetime.now(timezone.utc),
        status="paid", merchant_id=1, pickup=False, pickup_code="",
        items=[{"name": "牛腩饭", "quantity": 1, "price_cents": 2800}],
        food_cents=2800, packing_fee_cents=100, discount_cents=0,
        delivery_fee_cents=300, total_cents=3200, remark="",
        contact_name="张先生", contact_phone="13800001234",
        privacy_phone="", address="天府大道 1 号")
    p = build_payload("order.paid", order, "did123")
    assert p["contact_phone"] != "13800001234",         f"真号不能出站:{p['contact_phone']}"
    assert "*" in p["contact_phone"], p["contact_phone"]
    print(f"✓ 回调订单体的手机号是打码号({p['contact_phone']}),真号不出站")

    order.privacy_phone = "17012345678,1234"
    p2 = build_payload("order.paid", order, "did124")
    assert p2["contact_phone"] == "17012345678,1234",         "有隐私号时优先给隐私号(商家能直接拨通)"
    print("✓ 有隐私号时优先给隐私号")


def check_webhook_api(tok):
    """回调配置接口:内网地址当场拒、事件白名单、密钥只给一次。"""
    lst = call("GET", "/merchants/me/webhooks", tok)
    assert lst["items"] == [], lst
    assert any(e["value"] == "order.paid" for e in lst["events"]), lst
    assert "去重" in lst["note"], lst["note"]

    bad = call("POST", "/merchants/me/webhooks", tok,
               {"url": "http://127.0.0.1/hook", "events": ["order.paid"]},
               expect_error=True)
    assert bad["_error"] == 422 and "内网" in bad["detail"], \
        f"内网地址要在配置时就拒掉,不能等到投递:{bad}"

    bad = call("POST", "/merchants/me/webhooks", tok,
               {"url": "https://example.com/hook", "events": ["瞎写的"]},
               expect_error=True)
    assert bad["_error"] == 422, f"事件白名单:{bad}"

    made = call("POST", "/merchants/me/webhooks", tok, {
        "url": "https://example.com/superz-hook",
        "events": ["order.paid", "order.cancelled"]})
    assert len(made["secret"]) > 20 and "唯一一次" in made["note"], made
    again = call("GET", "/merchants/me/webhooks", tok)
    assert len(again["items"]) == 1
    assert "secret" not in again["items"][0], "列表里不能回显密钥"
    print("✓ 回调配置:内网地址当场拒、事件白名单、密钥只在创建时给一次")

    call("DELETE", f"/merchants/me/webhooks/{made['id']}", tok)
    assert call("GET", "/merchants/me/webhooks", tok)["items"] == []
    print("✓ 回调可删除")


def main():
    check_ticket_privacy()
    check_webhook_ssrf()
    check_webhook_payload_privacy()

    tok, shop = new_shop(f"打印店{random.randrange(10**4)}")
    lst = call("GET", "/merchants/me/printers", tok)
    assert lst["items"] == [], lst
    assert {p["value"] for p in lst["purposes"]} == {
        "front", "kitchen", "label"}, lst["purposes"]
    assert "后厨" in lst["note"], lst["note"]
    print("✓ 打印机列表初始为空,三种用途可选,口径写在 note 里")

    bad = call("POST", "/merchants/me/printers", tok,
               {"sn": "", "key": ""}, expect_error=True)
    assert bad["_error"] in (422, 503), bad
    if not lst["enabled"]:
        print("✓ 飞鹅未配置:绑定接口 503(本地/CI 常态,跳过绑定相关断言)")
        # 回调与飞鹅无关,不能跟着一起跳过
        check_webhook_api(tok)
        print("\ne2e_printers 全部通过 ✅")
        return

    bad = call("POST", "/merchants/me/printers", tok,
               {"sn": "TESTSN01", "key": "k", "purpose": "厨房"},
               expect_error=True)
    assert bad["_error"] == 422, f"未知用途该拦:{bad}"
    print("✓ 用途白名单")

    other, _ = new_shop(f"路人打印店{random.randrange(10**4)}")
    steal = call("PATCH", "/merchants/me/printers/1", other,
                 {"name": "改别人的"}, expect_error=True)
    assert steal["_error"] == 404, f"不能改别人家的打印机:{steal}"
    print("✓ 跨店改打印机被拒")

    check_webhook_api(tok)
    print("\ne2e_printers 全部通过 ✅")


if __name__ == "__main__":
    main()
