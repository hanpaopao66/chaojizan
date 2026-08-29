"""e2e 测试公共工具。测试跑在真实 HTTP 接口上,需要先起服务:
    SUPERZ_API=http://127.0.0.1:8010 python -m tests.e2e_orders
"""
import json
import os
import random
import re
import time
import urllib.error
import urllib.request

BASE = os.environ.get("SUPERZ_API", "http://127.0.0.1:8010")


def call(method, path, token=None, body=None, expect_error=False,
         _retried=False, headers=None, retry_429=True):
    """[retry_429] 撞上自家限流时等窗口翻转重试一次。**默认开**。

    全套 e2e 共用演示账号连着跑一百多个套件,很容易在末尾撞上下单/工单
    频控。不重试的话,expect_error 的调用会把 429 原样返回给断言,
    表现成"我等的是 409,来的是 429" —— 排查它和排查真 bug 一样费时,
    而它只是环境。

    默认开是因为**在这套用例里 429 几乎总是噪音**:真正在测限流的只有
    e2e_urge / e2e_support_audit / e2e_external_stubs 这几处,
    它们显式传 `retry_429=False` 关掉。默认关的话,每加一个新用例
    就要再踩一次同样的坑(已经踩过两次了)。
    """
    req = urllib.request.Request(BASE + path, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    for k, v in (headers or {}).items():
        req.add_header(k, str(v))
    data = json.dumps(body).encode() if body is not None else None
    try:
        with urllib.request.urlopen(req, data) as resp:
            raw = resp.read()
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        # 错误体**不一定是 JSON**:502/503 是代理给的纯文本,uvicorn 兜底的
        # 500 是 "Internal Server Error",连接被掐时干脆是空的。
        # 这里直接 json.loads 的话,真实状态码会被一个 JSONDecodeError 盖掉,
        # 排查的人看到的是 json/decoder.py 的栈,而不是「服务端 502 了」。
        raw = e.read()
        try:
            detail = json.loads(raw).get("detail")
        except (ValueError, AttributeError):
            detail = f"(非 JSON 响应体){raw[:200]!r}"
        if expect_error and not (e.code == 429 and retry_429):
            return {"_error": e.code, "detail": detail}
        if e.code == 429 and not _retried:
            # 全套 e2e 共用演示账号,可能撞上自家限流(按分钟固定窗口):
            # 等窗口翻转再试一次,不为测试放宽生产阈值
            wait = 61 - int(time.time()) % 60
            print(f"  (限流 429,等 {wait}s 窗口翻转后重试)")
            time.sleep(wait)
            return call(method, path, token, body, expect_error,
                        _retried=True, headers=headers, retry_429=retry_429)
        raise SystemExit(f"FAIL {method} {path}: {e.code} {detail}")


# 演示口令默认 123456,但 scripts/seed.py 在 STORAGE_BACKEND=minio 时会
# **随机生成**(它把这个当成"跑在生产上"的信号,不留人人可登的后门)。
# CI 恰恰要用 minio 跑生产的存储路径,于是撞上这条 —— 两边都对,只是没对齐。
# 解法是 CI 显式给 SEED_DEMO_PASSWORD,seed 和用例都读它,
# 而不是把 seed 那条生产保护放宽。
DEMO_PASSWORD = os.environ.get("SEED_DEMO_PASSWORD") or "123456"


def login(phone, password=None):
    return call("POST", "/auth/login",
                body={"phone": phone,
                      "password": password or DEMO_PASSWORD})["token"]


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


def fresh_phone(prefix: str = "137") -> str:
    """搓一个几乎不撞库的测试手机号。

    开发库里已经积累了一万五千多个测试账号 —— 手机号只有 8 位自由空间,
    **任何生成策略**单次撞上历史号的概率都在万分之一量级,而账号只增不减,
    这个概率单调上涨。所以别直接拿它去注册,用 register_user():
    撞了 409 换个号重试,这才是根治。
    """
    import random
    return prefix + "".join(str(random.randint(0, 9)) for _ in range(8))


def register_user(role: str, password: str = "123456", *,
                  name: str = "", prefix: str = "137",
                  attempts: int = 5) -> tuple[str, str]:
    """注册一个新账号,返回 (token, phone)。撞号自动换号重试。

    「该手机号已注册过此角色」不是本用例要测的东西 —— 它只说明
    随机号撞上了历史残留,换一个就好。别的 409(比如限流语义)照常抛。
    """
    last = None
    for _ in range(attempts):
        phone = fresh_phone(prefix)
        r = call("POST", "/auth/register",
                 body={"phone": phone, "password": password,
                       "name": name or f"测试{phone[-4:]}", "role": role},
                 expect_error=True)
        if isinstance(r, dict) and r.get("_error"):
            if r["_error"] == 409 and "已注册" in (r.get("detail") or ""):
                last = r
                continue
            raise SystemExit(f"FAIL 注册 {role}: {r['_error']} {r.get('detail')}")
        return r["token"], phone
    raise SystemExit(f"FAIL 注册 {role}: 连撞 {attempts} 次已注册号:{last}")


def orderable_dish(dishes, min_cents=1500, min_stock=1):
    """挑一道真能下单的菜:单价过起送价下限、在售、库存够、且不是酒类。

    公共演示店的菜单会被历史测试残留污染,dishes[0] 可能是低价菜,
    盲取会撞上起送价 409 —— 所有下单测试统一走这里。

    酒类必须排除:买酒要先实名认证(未成年人保护,#alcohol),
    普通用例的账号没实名,撞上就是一个跟本用例毫无关系的 422。
    库存也要看:菜单接口照常返回估清的菜,只有下单那一刻才报库存不足。

    需要下多单的用例用 min_stock 说明要几份,不要自己手搓筛选 ——
    手搓的版本十有八九会漏掉价格这一条,撞上起送价 409;而
    `stock` 为 None 表示不限量,手写的 `d.get("stock", 0) > 3` 会
    拿 None 跟数字比大小,直接 TypeError。
    """
    return next(d for d in dishes
                if d["price_cents"] >= min_cents
                and d.get("is_on_sale", True)
                and not d.get("is_alcohol")
                and (d.get("stock") is None or d["stock"] >= min_stock))


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
                 "id_no_encrypted, id_card_photo_url, health_cert_photo_url, "
                 "status, reject_reason) VALUES (:id, :name, '', "
                 "'', '', 'approved', '')"), {"id": uid, "name": name})
        # 食安培训记录:法定要求(123 号令第二十九条),没有它上不了线。
        # 这个助手造的是**完整入驻**的骑手,所以要带上 ——
        # 少了它,所有依赖骑手上线的用例都会挂在合规卡点上
        await db.execute(
            text("INSERT INTO rider_exams (rider_id, score, passed, answers, "
                 "content_version) VALUES (:id, 100, true, '{}'::jsonb, "
                 "'test')"), {"id": uid})
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


# 坐标工具搬到了 tests/geo.py:那个模块零副作用,单元测试可以直接 import。
# 本模块在 import 时会登录演示账号、清骑手积压,**import 它就需要起着服务** ——
# 让一条纯函数的单元测试连上网,CI 上炸过一次。这里 re-export 保持 e2e 的写法不变。
from .geo import unique_spot  # noqa: E402,F401  (给 e2e 继续用)


# 演示店固定是 seed 里的第一家(id=1)。**别再去扫 /merchants 列表找它** ——
# 那个接口有条数上限(LIMIT 50),演示库里商家一多,张记面馆就被挤出返回页,
# 表现为 `next(...)` 抛 StopIteration「店不见了」。61 处用例踩过同一个坑。
DEMO_SHOP_ID = 1


def demo_shop():
    """直接取演示店详情,不依赖任何会被截断的列表。"""
    return call("GET", f"/merchants/{DEMO_SHOP_ID}")


# ---------- 账务自检:按"本次运行新增了什么"断言 ----------
#
# **只按订单号过滤是漏的。** 聚合类检查(profit_sharing_stuck /
# profit_sharing_failed / global_identity_mismatch / refund_stuck /
# stay_paid_stuck …)的 detail 里根本没有订单号,一律被 `no in detail`
# 滤掉 —— 真出问题时用例照样打印"全绿 ✅"。实测过:本地库 51 条在响,
# 用例一条都没看见。
#
# 但也不能直接 `assert not run_audit()`:开发库是长期共享的,历史 e2e
# 残留(挂起的分账、退不掉的老单)会让每个用例长期红着,
# 而"长期红灯"的下场就是所有人习惯红了也没关系 —— 那比不查更糟。
#
# 所以口径是**增量**:跑场景前拍一次快照,跑完再拍一次,
# 只对"这一趟新增出来的问题"负责。历史脏数据不背,新破的必抓。


async def audit_snapshot():
    """跑一次账务自检,返回 {check_name: 条数} 快照。"""
    from collections import Counter

    from app.services.audit import run_audit
    return Counter(p["check"] for p in await run_audit())


async def audit_new_problems(before, *order_nos):
    """再跑一次自检,返回本次运行新增的问题。

    两类都算数:
      1. detail 里点名了本用例造的订单号 —— 逐单类检查;
      2. 某个 check 的条数比 `before` 多了 —— 聚合类检查唯一的抓法。
    """
    from collections import Counter

    from app.services.audit import run_audit
    problems = await run_audit()
    after = Counter(p["check"] for p in problems)
    mine = [p for p in problems
            if any(no and no in p.get("detail", "") for no in order_nos)]
    seen = {(p["check"], p["detail"]) for p in mine}
    for check in sorted(c for c, n in after.items() if n > before.get(c, 0)):
        # 聚合类检查只多出一条也要炸,但别把同类的几百条全倒出来
        sample = next(p["detail"] for p in problems if p["check"] == check)
        entry = {"check": check,
                 "detail": f"本次运行新增 {after[check] - before.get(check, 0)} 条"
                           f"(本轮共 {after[check]} 条),例:{sample[:200]}"}
        if (entry["check"], entry["detail"]) not in seen:
            mine.append(entry)
    return mine


def fake_order(**overrides):
    """小票渲染用的假订单。**三个用例共用这一份**。

    在这之前 e2e_printers / e2e_privacy_phone / e2e_alcohol 各手写了一份
    SimpleNamespace,给订单加一个字段(比如配送费拆分 fee_parts)就断掉
    没跟上的那几个 —— 而断的地方离真正的改动很远,排查起来全是噪音。

    默认值取一单"有拆分、送上门、非自取"的常规外卖,
    覆盖参数按需改。
    """
    from datetime import datetime, timezone
    from types import SimpleNamespace

    base = dict(
        order_no="SZ20260806000123",
        created_at=datetime.now(timezone.utc),
        pickup=False, pickup_code="", parent_order_no="", scheduled_at=None,
        remark="", privacy_phone="",
        items=[{"name": "牛腩饭", "quantity": 1, "price_cents": 2000,
                "is_alcohol": False}],
        food_cents=2000, packing_fee_cents=0, discount_cents=0,
        delivery_fee_cents=300, total_cents=2300,
        fee_parts={}, to_door=True,
        contact_name="张三", contact_phone="13800001234", address="某地址",
    )
    base.update(overrides)
    return SimpleNamespace(**base)


# ---------- 账务自检:怎么在长期共享的开发库上断言"没变坏" ----------
#
# 直接 `assert problems == 0` 在这个库上永远不成立,而且**清库也救不回来**:
# 自检里有一类不设时间窗的挂账检查(见 services/audit.py 规则 10/11/13),
# 核的不是"当期账对不对",是"有没有钱卡在半路没人管",注释写得很直白:
# 「挂着的钱不会因为过了 30 天就不欠了」。它们只增不减,要靠人把那些单
# 推完才降得下来 —— 开发库没有这个人,于是恒亮。
#
# 所以口径改成对基线取差:**本次运行不许把账弄坏**,存量原样带着。

_AUDIT_ORDER_NO = re.compile(r"[0-9a-f]{20}")

#: 纯粹靠时间推移就会从无到有的检查项:一笔退款挂满 6 小时、一单住宿挂满
#: 24 小时,它就冒出来了,跟"这次运行干了什么"毫无关系。拿它们当"本次新增"
#: 的判据,等于给主回归埋一颗按小时走的随机红灯(实测撞见过一次:
#: 一批 03:04 发起的退款正好在两次自检之间挂满 6 小时)
AUDIT_TIME_THRESHOLD = ("profit_sharing_stuck", "profit_sharing_failed",
                        "refund_stuck", "stay_paid_stuck")

#: 补账(/admin/audit/backfill)能修的三类。**它们必然不在基线里**,
#: 所以在种类级比较里是一颗保证会响的假红灯。
#:
#: e2e_support_audit 的做法是:开头先补账、断言这三类归零,**再取基线** ——
#: 于是基线里永远没有它们。而全套跑到这条用例时,前面十几个套件已经造了
#: 上百单(刚实测:一次补账清掉 180 条),其中任何一条历史单在基线和终检
#: 之间被推到 completed,这三类就冒出来一个,种类级差集当场变红。
#:
#: 实际撞到的那次:被点名的是一张 **24 小时前**的单,退款理由是别的用例的
#: (「退款顺序用例」),和本次运行毫无关系 —— 整轮全套(25 分钟)因此白跑。
#:
#: 排除它们不会放松任何东西:两个调用点都**另有**一条「本单不许被点名」的
#: 逐单断言(`[p for p in problems if no in p["detail"]]`),那条覆盖所有检查项。
#: 这里放掉的只是"别人的历史单"。
AUDIT_BACKFILLABLE = ("merchant_earning_missing", "rider_earning_missing",
                      "reversal_missing")


def audit_fingerprint(detail_rows) -> set:
    """一次自检结果的指纹:{(检查项, 被点名的订单号)}。

    不能拿 detail 原文当指纹:聚合类检查的文案带笔数和「最久的已挂 N 小时」,
    两次跑之间必然不同,比原文只会得到一堆假差异;而只比检查项名又看不出
    "是不是换了一单在报"。取(检查项,订单号)是这两者的折中。
    """
    return {(p["check"],
             m.group(0) if (m := _AUDIT_ORDER_NO.search(p["detail"])) else "")
            for p in detail_rows}


def audit_regressions(problems, baseline_checks) -> set:
    """相对基线**新冒出来**的检查项,已剔除随时间自然出现的那几类。

    本次运行真把账弄坏了,一定会以一个新的检查项出现(逐单类的还会带上
    订单号,调用方通常再单独断言一次自己那一单)。
    """
    return ({p["check"] for p in problems} - set(baseline_checks)
            - set(AUDIT_TIME_THRESHOLD) - set(AUDIT_BACKFILLABLE))
