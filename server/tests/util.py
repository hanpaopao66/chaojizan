"""e2e 测试公共工具。测试跑在真实 HTTP 接口上,需要先起服务:
    SUPERZ_API=http://127.0.0.1:8010 python -m tests.e2e_orders
"""
import json
import os
import time
import urllib.error
import urllib.request

BASE = os.environ.get("SUPERZ_API", "http://127.0.0.1:8010")


def call(method, path, token=None, body=None, expect_error=False, _retried=False):
    req = urllib.request.Request(BASE + path, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    data = json.dumps(body).encode() if body is not None else None
    try:
        with urllib.request.urlopen(req, data) as resp:
            raw = resp.read()
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        detail = json.loads(e.read()).get("detail")
        if expect_error:
            return {"_error": e.code, "detail": detail}
        if e.code == 429 and not _retried:
            # 全套 e2e 共用演示账号,可能撞上自家限流(按分钟固定窗口):
            # 等窗口翻转再试一次,不为测试放宽生产阈值
            wait = 61 - int(time.time()) % 60
            print(f"  (限流 429,等 {wait}s 窗口翻转后重试)")
            time.sleep(wait)
            return call(method, path, token, body, expect_error, _retried=True)
        raise SystemExit(f"FAIL {method} {path}: {e.code} {detail}")


def login(phone, password="123456"):
    return call("POST", "/auth/login", body={"phone": phone, "password": password})["token"]


# seed.py 里的演示账号
CUSTOMER, MERCHANT, RIDER, ADMIN = (
    "13800000001",
    "13800000002",
    "13800000003",
    "13800000000",
)


def _clear_demo_rider_backlog():
    """清掉演示骑手手头残留的在途单,给抢单测试腾额度。

    历次 e2e 半途撂下的单会顶满「同时在途 3 单」上限(清单#10),
    全套测试共用的演示骑手就再也抢不了单。全走公开接口打扫:
    未取餐的转单回池(最终由无人接单兜底取消,资金口径合法),
    已取餐的直接送达(随后自动确认收货正常结算)。best-effort,
    个别清不掉(如状态并发变化)不阻塞测试启动。
    """
    try:
        token = login(RIDER)
    except SystemExit:
        return  # 演示号不存在(非 seed 库),没有积压可清
    for _ in range(5):  # 列表每页 50 条,转掉一批老单会浮上来,多扫几轮
        stuck = [o for o in call("GET", "/orders", token)
                 if o["status"] in ("accepted", "ready", "picked_up")
                 and not o.get("parent_order_no")]  # 追加单随原单,不占额度
        if not stuck:
            return
        for o in stuck:
            if o["status"] == "picked_up":
                call("POST", f"/orders/{o['order_no']}/transition", token,
                     {"to_status": "delivered"}, expect_error=True)
            else:
                call("POST", f"/riders/transfer/{o['order_no']}", token,
                     {"reason": "other"}, expect_error=True)


def _reset_demo_rider_transfer_count():
    """清零演示骑手的当日转单计数(Redis)。

    转单软约束(清单#33)会把历次测试累计的当日计数算到共用的
    演示骑手头上,达到阈值后抢单 409,拖垮全套回归;上面的积压
    清扫本身也靠转单回池,会再加一截计数。best-effort。
    """
    try:
        from datetime import datetime, timedelta, timezone

        import redis as _redis

        from app.config import settings as _settings
        rider_id = call("GET", "/auth/me", login(RIDER))["id"]
        bj_date = (datetime.now(timezone.utc) + timedelta(hours=8)).date()
        r = _redis.Redis.from_url(_settings.redis_url)
        r.delete(f"rider:transfer:{rider_id}:{bj_date}")
        r.close()
    except Exception:
        pass


_clear_demo_rider_backlog()
_reset_demo_rider_transfer_count()


def orderable_dish(dishes, min_cents=1500):
    """挑一道单价满足平台起送价下限的菜。

    公共演示店的菜单会被历史测试残留污染,dishes[0] 可能是低价菜,
    盲取会撞上起送价 409 —— 所有下单测试统一走这里。
    """
    return next(d for d in dishes if d["price_cents"] >= min_cents)


async def drain_order_pool():
    """清空抢单池:历次测试撂下的无骑手订单做旧到取消线,
    交给无人接单兜底正规取消(全额退款/已出餐赔付,审计口径合法)。

    池子接口只返回前 50 条,残留一多,新下的测试单会被挤出去,
    membership 断言随机翻车——有池子断言的测试开头先调这个清场。
    """
    from sqlalchemy import text

    from app.db import SessionLocal
    from app.services.auto_flow import sweep_once

    for _ in range(3):  # 兜底取消每轮最多 100 单,多扫几轮直到清完
        async with SessionLocal() as db:
            remaining = await db.scalar(text(
                "SELECT count(*) FROM orders WHERE rider_id IS NULL "
                "AND status IN ('accepted', 'ready') AND pickup = false "
                "AND parent_order_no = '' AND scheduled_at IS NULL"))
            if not remaining:
                return
            await db.execute(text(
                "UPDATE orders SET rider_pool_since = "
                "now() - interval '31 minutes' WHERE rider_id IS NULL "
                "AND status IN ('accepted', 'ready') AND pickup = false "
                "AND parent_order_no = '' AND scheduled_at IS NULL"))
            await db.commit()
        await sweep_once()


async def register_fresh_rider(name="测试骑手"):
    """注册新账号并直连 DB 提为已认证骑手,返回 token。

    演示库只有一个骑手号,「他人可抢」、每日转单计数、在途上限
    这类从零起算的断言都需要独立骑手。
    """
    import random

    from sqlalchemy import text

    from app.db import SessionLocal

    phone = f"1{random.choice('3589')}{random.randrange(10**8, 10**9)}"
    code = call("POST", "/auth/sms-code", body={"phone": phone})["dev_code"]
    token = call("POST", "/auth/sms-login",
                 body={"phone": phone, "code": code})["token"]
    async with SessionLocal() as db:
        uid = await db.scalar(
            text("SELECT id FROM users WHERE phone = :p"), {"p": phone})
        await db.execute(
            text("UPDATE users SET role = 'rider' WHERE id = :id"),
            {"id": uid})
        await db.execute(
            text("INSERT INTO rider_profiles (rider_id, real_name, "
                 "id_card_no, id_card_photo_url, health_cert_photo_url, "
                 "status, reject_reason) VALUES (:id, :name, '', "
                 "'', '', 'approved', '')"), {"id": uid, "name": name})
        await db.commit()
    # require_role 每次请求都从 DB 读角色,原 token 直接可用
    return token


def register_fresh_customer(tag=None):
    """注册一个全新用户并返回 token(验证码登录,开发模式 dev_code 直返)。

    售后风控按用户 30 天累计,复用演示账号会被自己刷爆 —— 售后类测试
    必须用新账号,每次运行从零开始。
    """
    import random
    phone = f"1{random.choice('3589')}{random.randrange(10**8, 10**9)}"
    code = call("POST", "/auth/sms-code", body={"phone": phone})["dev_code"]
    return call("POST", "/auth/sms-login", body={"phone": phone, "code": code})["token"]
