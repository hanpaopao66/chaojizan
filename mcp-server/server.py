#!/usr/bin/env python3
"""超级赞 MCP 服务:让 AI 助手找店、比价、下单、查进度。

## 它做不到什么(这一点写在最前面)

**付不了款。** 助手能把单创建到「待支付」为止,付款那一下在用户自己的
App 里由人按。即使令牌泄露,对方能替你创建一张 15 分钟后自动关闭的
待付单,**但花不掉一分钱**。

这不是没做完 —— 「点单」意味着一个自动化程序能花用户的钱,
而判断权应该留给人。服务端那一侧也不是靠自觉:助手令牌的能力范围
在 `server/app/security.py` 的 AGENT_ALLOWED 里收口,**默认拒绝**,
支付路径根本不在白名单里。所以这里少写一个工具不是"漏了",
是**就算写了也调不通**。

## 为什么不用 MCP SDK

这是开源项目,少一个依赖少一份供应链风险 —— 而 MCP 在 stdio 上就是
一行一个 JSON-RPC 消息,标准库够了。

## 干跑

    SUPERZ_API=... SUPERZ_AGENT_TOKEN=... python3 server.py --selftest

不进 stdio 循环,直接把每个工具打一遍,让人在接进客户端**之前**
就知道通不通。
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

PROTOCOL_VERSION = "2024-11-05"
SERVER_INFO = {"name": "superz", "version": "1.0.0"}

API = os.environ.get("SUPERZ_API", "http://127.0.0.1:8010").rstrip("/")
TOKEN = os.environ.get("SUPERZ_AGENT_TOKEN", "")
TIMEOUT = float(os.environ.get("SUPERZ_TIMEOUT", "20"))


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

class ApiError(Exception):
    """服务端的业务错误。**原样把中文说明带回给模型** ——
    它比任何我在这里编的英文短语都准确,而且是给人看过的话。"""

    def __init__(self, status: int, detail: str):
        super().__init__(f"[{status}] {detail}")
        self.status = status
        self.detail = detail


def api(method: str, path: str, *, query: dict | None = None,
        body: dict | None = None):
    url = API + path
    if query:
        clean = {k: v for k, v in query.items() if v is not None}
        if clean:
            url += "?" + urllib.parse.urlencode(clean)
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if TOKEN:
        req.add_header("Authorization", f"Bearer {TOKEN}")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            raw = resp.read()
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            detail = json.loads(raw).get("detail")
        except Exception:
            detail = raw[:200].decode("utf-8", "replace")
        if e.code == 403:
            # 助手令牌撞到能力边界。**把边界说清楚**,否则模型会一直重试
            detail = (f"{detail} —— 这是 AI 助手令牌的能力边界,"
                      f"不是临时故障,重试没有用。")
        raise ApiError(e.code, str(detail))
    except urllib.error.URLError as e:
        raise ApiError(0, f"连不上 {API}:{e.reason}")


# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------

def t_search_merchants(q: str, lat: float, lng: float,
                       sort: str = "comprehensive"):
    return api("GET", "/merchants/search",
               query={"q": q, "lat": lat, "lng": lng, "sort": sort})


def t_get_menu(merchant_id: int):
    return api("GET", f"/merchants/{merchant_id}/dishes")


def t_quote_order(merchant_id: int, lat: float, lng: float,
                  items: list | None = None, to_door: bool = True):
    """算价,**不下单**。

    助手最常做的事是比价,所以这一步单独拆出来 ——
    让它能算清楚再决定,而不是先下一串单再取消。
    """
    fee = api("GET", "/orders/delivery-fee",
              query={"merchant_id": merchant_id, "lat": lat, "lng": lng,
                     "to_door": str(to_door).lower()})
    out = {"delivery": fee}
    if items:
        menu = {d["id"]: d for d in (t_get_menu(merchant_id) or [])}
        food = 0
        missing = []
        for it in items:
            d = menu.get(it.get("dish_id"))
            if d is None:
                missing.append(it.get("dish_id"))
                continue
            food += int(d.get("price_cents", 0)) * int(it.get("quantity", 1))
        out["food_cents"] = food
        if missing:
            out["missing_dish_ids"] = missing
        out["note"] = ("餐费按菜单原价估算,**不含满减/优惠券** —— "
                       "真实应付以创建订单后返回的 total_cents 为准。")
    return out


def t_create_pending_order(merchant_id: int, items: list, address: str,
                           lat: float, lng: float, remark: str = "",
                           contact_phone: str = ""):
    """创建**待支付**订单。到此为止 —— 付款要用户在 App 里自己点。"""
    order = api("POST", "/orders", body={
        "merchant_id": merchant_id, "items": items, "address": address,
        "lat": lat, "lng": lng, "remark": remark,
        "contact_phone": contact_phone,
    })
    return {
        "order": order,
        "next_step": ("订单已创建,**还没付钱**。请让用户打开超级赞 App "
                      "的「我的订单」确认并支付 —— 助手没有支付能力。"
                      "15 分钟内不付款会自动关闭,不扣任何费用。"),
    }


def t_get_order_status(order_no: str):
    return api("GET", f"/orders/{order_no}")


def t_list_my_orders(limit: int = 10):
    return api("GET", "/orders", query={"limit": limit})


def t_get_transparency(topic: str = "liability"):
    """平台的公开口径。topic: liability 判责分摊 / dispatch 派单算法 /
    queue 排队规则 / fairness 分账公平 / funds 资金流向。"""
    return api("GET", f"/transparency/{topic}")


TOOLS = [
    {
        "name": "search_merchants",
        "description": "按位置和关键词找外卖商家。返回评分、距离、起送价。"
                       "排序只用真实评分/销量/距离——平台不做竞价排名。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "q": {"type": "string", "description": "店名或菜名关键词"},
                "lat": {"type": "number", "description": "用户纬度"},
                "lng": {"type": "number", "description": "用户经度"},
                "sort": {"type": "string",
                         "enum": ["comprehensive", "distance", "rating", "sales"]},
            },
            "required": ["q", "lat", "lng"],
        },
        "fn": t_search_merchants,
    },
    {
        "name": "get_menu",
        "description": "看一家店的菜单:价格、规格、库存、是否已估清。",
        "inputSchema": {
            "type": "object",
            "properties": {"merchant_id": {"type": "integer"}},
            "required": ["merchant_id"],
        },
        "fn": t_get_menu,
    },
    {
        "name": "quote_order",
        "description": "算价,**不下单**。返回配送费明细(距离/夜间/天气/上门难度)"
                       "和餐费估算。比价用这个,不要靠反复下单取消。"
                       "注意:餐费按原价估,不含满减和优惠券。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "merchant_id": {"type": "integer"},
                "lat": {"type": "number"},
                "lng": {"type": "number"},
                "items": {"type": "array", "description":
                          "[{dish_id, quantity}];不传则只算配送费",
                          "items": {"type": "object"}},
                "to_door": {"type": "boolean", "description":
                            "送上门(true)还是送到楼下(false)"},
            },
            "required": ["merchant_id", "lat", "lng"],
        },
        "fn": t_quote_order,
    },
    {
        "name": "create_pending_order",
        "description": "创建一张**待支付**订单。"
                       "⚠️ 这个工具**不会付款**,也付不了 —— 助手令牌没有支付能力。"
                       "创建完要让用户在超级赞 App 里自己确认支付;"
                       "15 分钟内不付会自动关闭,不扣费。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "merchant_id": {"type": "integer"},
                "items": {"type": "array", "description": "[{dish_id, quantity}]",
                          "items": {"type": "object"}},
                "address": {"type": "string", "description": "收货地址"},
                "lat": {"type": "number"},
                "lng": {"type": "number"},
                "remark": {"type": "string", "description": "备注,如忌口"},
                "contact_phone": {"type": "string",
                                  "description": "联系电话;不传用账号手机号"},
            },
            "required": ["merchant_id", "items", "address", "lat", "lng"],
        },
        "fn": t_create_pending_order,
    },
    {
        "name": "get_order_status",
        "description": "查一单到哪一步了:待支付/待接单/制作中/待取餐/配送中/"
                       "已送达/已完成,以及预计送达时间。",
        "inputSchema": {
            "type": "object",
            "properties": {"order_no": {"type": "string"}},
            "required": ["order_no"],
        },
        "fn": t_get_order_status,
    },
    {
        "name": "list_my_orders",
        "description": "我最近的订单。",
        "inputSchema": {
            "type": "object",
            "properties": {"limit": {"type": "integer", "description": "默认 10"}},
        },
        "fn": t_list_my_orders,
    },
    {
        "name": "get_transparency",
        "description": "平台的公开口径:判责分摊怎么算、派单算法的权重、"
                       "排队规则、分账去向。这些是对所有人公开的承诺,"
                       "用户问「为什么这么收费」时查它。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "topic": {"type": "string",
                          "enum": ["liability", "dispatch", "queue",
                                   "fairness", "funds"]},
            },
        },
        "fn": t_get_transparency,
    },
]

BY_NAME = {t["name"]: t for t in TOOLS}


# ---------------------------------------------------------------------------
# JSON-RPC over stdio
# ---------------------------------------------------------------------------

def handle(msg: dict) -> dict | None:
    """处理一条请求。返回 None 表示这是通知(notification),不该回。"""
    method = msg.get("method")
    mid = msg.get("id")

    if method == "initialize":
        return ok(mid, {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": SERVER_INFO,
        })
    if method in ("notifications/initialized", "initialized"):
        return None
    if method == "ping":
        return ok(mid, {})
    if method == "tools/list":
        return ok(mid, {"tools": [
            {k: t[k] for k in ("name", "description", "inputSchema")}
            for t in TOOLS
        ]})
    if method == "tools/call":
        params = msg.get("params") or {}
        name = params.get("name")
        tool = BY_NAME.get(name)
        if tool is None:
            return err(mid, -32602, f"没有这个工具:{name}")
        try:
            result = tool["fn"](**(params.get("arguments") or {}))
        except ApiError as e:
            # 业务错误走 isError 而不是协议错误 —— 模型要看到那句中文,
            # 才知道是「余额不够」还是「这家店打烊了」
            return ok(mid, {"isError": True, "content": [
                {"type": "text", "text": e.detail}]})
        except TypeError as e:
            return ok(mid, {"isError": True, "content": [
                {"type": "text", "text": f"参数不对:{e}"}]})
        return ok(mid, {"content": [
            {"type": "text",
             "text": json.dumps(result, ensure_ascii=False, indent=2)}]})

    return err(mid, -32601, f"不支持的方法:{method}")


def ok(mid, result) -> dict:
    return {"jsonrpc": "2.0", "id": mid, "result": result}


def err(mid, code, message) -> dict:
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": code,
                                                   "message": message}}


def serve(stdin=sys.stdin, stdout=sys.stdout) -> None:
    """一行一条 JSON。**读到坏行不能退出** —— 一个格式错的消息
    不该让整个助手连接断掉,那表现是「用着用着突然没反应了」。"""
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        try:
            resp = handle(msg)
        except Exception as e:                      # noqa: BLE001
            resp = err(msg.get("id"), -32603, f"内部错误:{e}")
        if resp is not None:
            stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
            stdout.flush()


def selftest() -> int:
    """干跑:每个只读工具打一遍。**不创建订单** —— 自检不该产生真实的单。"""
    print(f"API   = {API}")
    print(f"TOKEN = {'已设置' if TOKEN else '(空,只读接口可能 401)'}")
    print()
    checks = [
        ("get_transparency", lambda: t_get_transparency("liability")),
        ("list_my_orders", lambda: t_list_my_orders(3)),
        ("search_merchants", lambda: t_search_merchants("饭", 30.66, 104.08)),
    ]
    bad = 0
    for name, fn in checks:
        try:
            r = fn()
            n = len(r) if isinstance(r, (list, dict)) else 0
            print(f"  ✓ {name:20} 通(返回 {n} 项)")
        except ApiError as e:
            print(f"  ✗ {name:20} {e}")
            bad += 1
    print()
    print("  · create_pending_order 不在自检里:它会产生真实的待支付订单。")
    print("  · 付款工具不存在 —— 助手令牌没有支付能力,这是有意的。")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(selftest() if "--selftest" in sys.argv else (serve() or 0))
