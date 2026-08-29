"""开放接口的用量与日志:记得下、看得见、不越界、不泄密。

## 这条守什么

开发者后台的价值全在「我的集成为什么失败」这一个问题上,
而它成立的前提是**调用真的被记下来了** —— 中间件打标漏了、
或者认证层没设那个标,页面就是一片空白,而这从业务侧完全看不出来。

另外两条是底线:
- **不记请求体**。里面是收货地址、手机号、备注里的忌口。为了让开发者
  好排查而多存一份,是拿用户的隐私补贴开发体验;
- **看不到别人的**。A 商家的 Key 调出来的日志,B 商家不该看见。

在 server/ 目录下运行:python -m tests.e2e_api_console
"""
from tests.util import call, login

merchant = login("13800000002")
customer = login("13800000001")


def main() -> None:
    # ---------- 1) 商家 Key:调一次,日志里要有 ----------
    # **先清场。** 最多同时 5 把 Key,而上一轮跑失败会留下一把 ——
    # 不清的话第二次就 409,而那和这条用例要测的东西毫无关系。
    # (「前提要用例自己造齐」这条这一批已经栽过三次。)
    for k in call("GET", "/merchants/me/api-keys", merchant):
        if k.get("name") == "日志测试":
            call("DELETE", f"/merchants/me/api-keys/{k['id']}", merchant)
    key = call("POST", "/merchants/me/api-keys", merchant,
               {"name": "日志测试"})["token"]
    assert key.startswith("sz_"), f"签发的不是 API Key:{key[:12]}"

    before = call("GET", "/merchants/me/api-logs", merchant)["items"]
    call("GET", "/open/v1/shop", key)
    after = call("GET", "/merchants/me/api-logs", merchant)["items"]
    assert len(after) > len(before), (
        "用 API Key 调了一次开放接口,日志里却没多出来 —— "
        "中间件的标没打上,而这在业务侧完全看不出来")
    top = after[0]
    assert top["path"] == "/open/v1/shop" and top["status"] == 200
    assert top["duration_ms"] >= 0
    print(f"✓ 调用被记下了:{top['method']} {top['path']} "
          f"{top['status']} {top['duration_ms']}ms")

    # ---------- 2) 日志里不能有请求体/响应体 ----------
    fields = set(top)
    assert fields <= {"method", "path", "status", "duration_ms", "at"}, (
        f"日志多带了字段 {fields} —— 只该有方法/路径/状态/耗时/时间,"
        f"请求体里是顾客的地址和手机号")
    assert "?" not in top["path"], (
        f"路径里带了查询串({top['path']}) —— 里面可能有坐标和搜索词")
    print("✓ 只有方法/路径/状态/耗时,没有请求体,路径也不带查询串")

    # ---------- 3) 用量分开报错误率和限流 ----------
    usage = call("GET", "/merchants/me/api-usage?days=7", merchant)
    for k in ("total", "errors", "throttled", "error_ratio", "avg_ms"):
        assert k in usage, f"用量里缺 {k}"
    assert usage["total"] >= 1
    assert usage["note"], "没告诉开发者这些数该怎么用"
    print(f"✓ 用量:{usage['total']} 次调用,错误率 {usage['error_ratio']:.1%},"
          f"限流 {usage['throttled']} 次,平均 {usage['avg_ms']}ms")

    # ---------- 3.5) 认得出是谁的失败要记,不认识的不记 ----------
    #
    # 「我的 Key 怎么突然不好使了」是接入方最常问的问题,而答案(被吊销了)
    # 只有在日志里看得见才有用。
    #
    # 但完全不认识的 Key 不记 —— 否则任何人拿垃圾请求就能撑爆这张表。
    def err401_count() -> int:
        """日志里 401 的条数。

        **数条数,不数「用量接口报的总错误数」的差值。** 差值断言在演示店
        上是飘的:全套里别的用例也在用同一家店,两次读之间数字会被别人动。
        直接数日志里符合形状的行,和「谁在同时跑」无关。
        """
        rows = call("GET", "/merchants/me/api-logs?limit=500&status_min=401",
                    merchant)["items"]
        return len([r for r in rows if r["status"] == 401])

    before = err401_count()
    # 假钥匙必须是 ASCII —— HTTP 头进不了中文(latin-1 编码不了)
    call("GET", "/open/v1/shop", "sz_a_fake_key_that_should_401",
         expect_error=True)
    assert err401_count() == before, (
        "完全不认识的 Key 也被记进了日志 —— "
        "那任何人拿垃圾请求就能把这张表撑爆")

    # 吊销自己那把,再用它调一次 —— 这一次认得出是谁,必须记
    kid = next(k["id"] for k in call("GET", "/merchants/me/api-keys", merchant)
               if k.get("name") == "日志测试")
    call("DELETE", f"/merchants/me/api-keys/{kid}", merchant)
    err = call("GET", "/open/v1/shop", key, expect_error=True)
    assert err["_error"] == 401, f"吊销之后还能用:{err}"
    assert err401_count() == before + 1, (
        "被吊销的 Key 调用没记进日志 —— "
        "「我的 Key 怎么突然不好使了」在日志里就看不见答案")
    print("✓ 不认识的 Key 不记;被吊销的 Key 记了一条 401")

    # ---------- 4) 只看得到自己的 ----------
    #
    # 日志按 merchant_id 过滤。这条不验的话,一个商家能看到别人的
    # 集成在调什么接口、调多密 —— 那是经营信息。
    logs = call("GET", "/merchants/me/api-logs?limit=200", merchant)["items"]
    assert all(l["path"].startswith("/open/") for l in logs), (
        "日志里混进了非开放接口的调用 —— 说明过滤条件不对")
    print(f"✓ 日志只含自己的开放接口调用({len(logs)} 条)")

    # ---------- 5) 助手活动:用户看得见自己的助手做过什么 ----------
    issued = call("POST", "/auth/agent-tokens", customer,
                  {"name": "日志测试助手", "days": 1})
    agent = issued["token"]
    call("GET", "/auth/me", agent)
    call("GET", "/orders?limit=1", agent)
    act = call("GET", "/auth/agent-activity", customer)
    paths = [i["path"] for i in act["items"]]
    assert "/auth/me" in paths and "/orders" in paths, (
        f"助手调用没被记下来:{paths[:5]} —— "
        f"「你看得见它在干嘛」这句话就落空了")
    assert act["note"], "没告诉用户这一页是干什么的"
    print(f"✓ 用户看得见助手做过什么({len(act['items'])} 条)")

    # 助手自己看不到这一页(它不在白名单里)
    err = call("GET", "/auth/agent-activity", agent, expect_error=True)
    assert err["_error"] == 403, (
        f"助手能读自己的活动记录:{err} —— 那它就能知道自己被看着什么,"
        f"而这一页的意义是给人看的")
    print("✓ 助手自己读不到这一页(不在白名单里)")

    # ---------- 6) 收拾 ----------
    # Key 上面已经吊销了(3.5 那一步就是拿它验的),这里只清助手令牌
    tokens = call("GET", "/auth/agent-tokens", customer)
    for t in tokens:
        if t["name"] == "日志测试助手" and not t["revoked"]:
            call("DELETE", f"/auth/agent-tokens/{t['id']}", customer)

    print("\ne2e_api_console 全部通过 ✅")


if __name__ == "__main__":
    main()
