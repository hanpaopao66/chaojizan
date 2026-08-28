"""往拼进 SQL 的那几个参数里灌注入载荷,看能不能打穿。

## 为什么要有

仓库里有十几处用 f-string / .format() 拼 SQL(首页排序、搜索、住宿列表、
大屏、透明中心)。审计逐处核过:插进去的要么是模块常量、要么是**白名单
查表**的结果、要么是字面量拼的条件,取值一律走 `:named` 绑定参数。

但"现在是对的"和"以后一直对"是两件事 —— 有人给 `sort` 加一个取值忘了
进白名单、或者图省事把某个筛选值拼进条件串,静态上看不出来,
而这是**开源**平台,注入点一旦出现,读代码的人第一个知道。

所以这条不去断言实现长什么样,直接**打**:排序、筛选、搜索词、分页
各灌一批载荷,要么被 422 挡住,要么当普通字符串处理 —— 不许 500,
更不许把库打出别的行为来。

    SUPERZ_API=http://127.0.0.1:8010 python -m tests.e2e_injection_probe
"""
from urllib.parse import quote

from tests.util import call, login

customer = login("13800000001")

# 经典载荷:闭合引号、注释掉后半段、UNION、堆叠语句、布尔恒真
PAYLOADS = [
    "'",
    "''",
    "1' OR '1'='1",
    "'; DROP TABLE orders; --",
    "' UNION SELECT NULL,NULL,NULL --",
    "distance; SELECT pg_sleep(5)",
    "distance'--",
    ") OR 1=1 --",
    "%27%20OR%201=1",
    "\\'",
]

POS = "lat=30.6612&lng=104.0823"
# 固定查询词也要编码:urllib 用 ascii 编请求行,裸中文直接抛
Q = quote("面", safe="")


def probe(label, url_tmpl, ok_codes=(200, 422)):
    """打一个参数,断言服务端要么正常处理要么明确拒绝 —— 不许 5xx。"""
    bad = []
    for p in PAYLOADS:
        url = url_tmpl.format(v=quote(p, safe=""))
        r = call("GET", url, customer, expect_error=True)
        code = r.get("_error", 200) if isinstance(r, dict) else 200
        if code not in ok_codes:
            bad.append((p, code, str(r)[:120]))
    assert not bad, f"{label} 有载荷打出了意外响应:{bad}"
    print(f"✓ {label}:{len(PAYLOADS)} 个载荷全部被挡住或按普通字符串处理")


def main() -> None:
    # 1) 首页排序 —— 拼进 SQL 的 _SORTS[sort],必须白名单查表
    probe("首页 sort", "/merchants?" + POS + "&sort={v}")
    # 2) 搜索排序 —— _SEARCH_SORTS[sort]
    probe("搜索 sort", "/merchants/search?q=" + Q + "&" + POS + "&sort={v}")
    # 3) 搜索词 —— 走 :pattern 绑定参数
    probe("搜索词 q", "/merchants/search?q={v}&" + POS)
    # 4) 品类筛选 —— 拼的是固定串,取值走 :category
    probe("品类 category", "/merchants?" + POS + "&category={v}")
    # 5) 住宿排序与筛选 —— _HOTEL_SORTS[sort] 与 :tier
    probe("住宿 sort", "/stays/hotels?" + POS + "&sort={v}")
    probe("住宿 tier", "/stays/hotels?" + POS + "&tier={v}")
    # 6) 分页游标 —— 订单列表按 created_at 解析
    probe("订单游标 before", "/orders?limit=5&before={v}")

    # 白名单本身要真的在挡:一个不存在但"看着正常"的排序值必须 422,
    # 不能被静默降级成默认排序(那样注入点就藏在降级逻辑里了)
    r = call("GET", "/merchants?" + POS + "&sort=created_at",
             customer, expect_error=True)
    assert r.get("_error") == 422, f"未知排序没有被拒:{r}"
    r = call("GET", "/merchants/search?q=" + Q + "&" + POS + "&sort=price",
             customer, expect_error=True)
    assert r.get("_error") == 422, f"搜索未知排序没有被拒:{r}"
    print("✓ 白名单确实在挡:未知排序值一律 422,不静默降级")

    # 库还活着(上面要是真打穿了,这一条会挂)
    n = len(call("GET", "/merchants?" + POS + "&limit=1", customer))
    assert n >= 0
    print("✓ 打完之后库和接口都正常")

    print("\ne2e_injection_probe 全部通过 ✅")


if __name__ == "__main__":
    main()
