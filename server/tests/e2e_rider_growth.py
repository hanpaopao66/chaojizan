"""骑手周报 / 新手保护期 / 意见反馈(AS·AU·AW)。

## 这一批守的三条

1. **周报只统计不考核。** 返回体里不许出现评分、等级、排名 ——
   一旦出现,它就从"我这周跑得怎么样"变成平台的另一根鞭子;
2. **新手保护只放宽软阈值,不动派单。** 派单公平性是公开承诺过的,
   为谁开一个口子整个承诺都打折;
3. **反馈必须有回音。** 不回复的通道等于没有,而且比没有更糟 ——
   提过一次没人理,以后连提都懒得提。所以回复要推送 + 进消息中心。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from .util import ADMIN, RIDER, call, login  # noqa: E402

rider = login(RIDER)
admin = login(ADMIN)

#: 周报里**一个都不能出现**的字段名。这不是洁癖:
#: 这些字段一旦有了,界面上迟早会显示,显示了就成了考核
FORBIDDEN = ("score", "rank", "level", "grade", "percentile",
             "badge", "tier", "star")


def main():
    # ---- 周报 ----
    r = call("GET", "/riders/me/weekly-report", rider)
    assert len(r["days"]) == 7, r["days"]
    assert set(r["days"][0]) == {"orders", "earned_cents", "minutes"}
    assert r["orders"] == sum(d["orders"] for d in r["days"])
    assert r["earned_cents"] == sum(d["earned_cents"] for d in r["days"])
    assert r["online_minutes"] == sum(d["minutes"] for d in r["days"])
    print(f"✓ 周报逐日切分,合计与逐日相加对得上"
          f"({r['orders']} 单 / ¥{r['earned_cents'] / 100:g})")

    # 查**键名**而不是整个返回体的字符串:"week_start" 里就含 "star",
    # 子串匹配会一直误报,然后这条断言被人放宽掉 —— 那才是真的失去意义
    def keys(node):
        if isinstance(node, dict):
            for k, v in node.items():
                yield str(k).lower()
                yield from keys(v)
        elif isinstance(node, list):
            for v in node:
                yield from keys(v)

    for key in keys(r):
        # 按下划线切段后**整段相等**才算命中:week_start 里含 "star",
        # 子串匹配会一直误报,然后这条断言迟早被人放宽掉 —— 那才是
        # 真的失去意义。要拦的是 service_score / rider_level 这种
        bad = set(key.split("_")) & set(FORBIDDEN)
        assert not bad, f"周报里出现了字段 {key} —— 这是考核不是统计"
    assert "只统计" in r["note"], r["note"]
    print("✓ 周报里没有评分/等级/排名字段,口径写在返回体里")

    # 时薪:在线不足 1 小时不给。分母太小算出来是个荒唐数字,
    # 而骑手会拿这个数去判断"今天值不值得跑"
    if r["online_minutes"] < 60:
        assert r["cents_per_hour"] is None, r["cents_per_hour"]
        print("✓ 在线不足 1 小时不给时薪(分母太小的数会误导人)")
    else:
        assert r["cents_per_hour"] > 0
        print(f"✓ 时薪 ¥{r['cents_per_hour'] / 100:.1f}/小时")

    # 收入构成读的是订单快照,键必须带得出中文名
    for k in r["fee_parts"]:
        assert k in r["fee_part_labels"], f"{k} 没有中文名"
    print(f"✓ 收入构成 {len(r['fee_parts'])} 项,每项都有中文名")

    last = call("GET", "/riders/me/weekly-report?week_offset=1", rider)
    assert last["week_start"] < r["week_start"], (last["week_start"],
                                                  r["week_start"])
    print("✓ 可以往前翻周(上周的起点比本周早)")

    # ---- 新手保护期:只放宽阈值,不改派单 ----
    from app.config import settings
    assert settings.rider_novice_extra_transfers > 0
    # 演示骑手早就跑满了,所以他**不该**在新手期 ——
    # 这一条反过来验证判定不是永远返回 true
    import asyncio

    async def check():
        from app.db import SessionLocal, engine
        from app.routers.riders import _novice_window
        async with SessionLocal() as db:
            me = call("GET", "/auth/me", rider)["id"]
            got = await _novice_window(db, me)
        await engine.dispose()
        return got

    assert asyncio.run(check()) is False, \
        "跑了几百单的老骑手不该还在新手期 —— 判定失效了"
    print("✓ 新手期判定:注册 7 天内**且**不足 20 单,老骑手不误判")

    # ---- 意见反馈:提交 → 平台回复 → 骑手看得到 ----
    err = call("POST", "/riders/feedback", rider, {"content": "太差"},
               expect_error=True)
    assert err["_error"] == 422, err
    err = call("POST", "/riders/feedback", rider,
               {"kind": "抱怨", "content": "抢单页太慢了"}, expect_error=True)
    assert err["_error"] == 422, err
    print("✓ 内容过短、分类非法一律 422")

    fb = call("POST", "/riders/feedback", rider,
              {"kind": "bug", "content": "抢单页刷新一次要五六秒,高峰期根本抢不到"})
    assert fb["status"] == "open", fb
    mine = call("GET", "/riders/me/feedback", rider)
    row = next(i for i in mine["items"] if i["id"] == fb["id"])
    assert row["status"] == "open" and not row["reply"]
    print("✓ 提交后进队列,骑手自己查得到")

    queue = call("GET", "/admin/rider-feedback?status=open", admin)
    assert any(i["id"] == fb["id"] for i in queue), "平台队列里应当有这条"
    # 最老的排最前:按新到旧排的话,积压的老意见永远沉底
    ids = [i["id"] for i in queue]
    assert ids == sorted(ids), ids
    print("✓ 平台队列存在,且最老的排最前(不让老意见沉底)")

    empty = call("POST", f"/admin/rider-feedback/{fb['id']}/reply", admin,
                 {"reply": ""}, expect_error=True)
    assert empty["_error"] == 422, empty
    print("✓ 空回复被拒 —— 空回复比不回复更伤人")

    call("POST", f"/admin/rider-feedback/{fb['id']}/reply", admin,
         {"reply": "已排进下个版本:抢单页改成增量刷新。谢谢你specifics"
                   .replace("specifics", "说得这么具体")})
    after = call("GET", "/riders/me/feedback", rider)
    row = next(i for i in after["items"] if i["id"] == fb["id"])
    assert row["status"] == "replied" and "增量刷新" in row["reply"], row
    print("✓ 平台回复后骑手侧立刻可见")

    # 回音要进消息中心 —— 这是这个功能的全部意义。
    # 骑手在马路上,推送那一下没看到就找不回来了
    msgs = call("GET", "/riders/me/messages?category=feedback", rider)
    assert any("意见" in m["title"] for m in msgs["messages"]), \
        [m["title"] for m in msgs["messages"]]
    print("✓ 回复进了消息中心的「我的意见」分类,不只是一条会消失的推送")

    print("\ne2e_rider_growth 全部通过 ✅")


if __name__ == "__main__":
    main()
