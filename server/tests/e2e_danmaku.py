"""弹幕 e2e(DEV-PROMPTS-40 §5.10、§5.7、#360,不变量 S7)。

分段(6 分钟一段,边界 359999 / 360000)、输入校验(≤ 100 字、单行、模式 / 颜色 / 字号、时间不超过视频长度)、
限流(每人每 3 秒 1 条、每天 1,000 条)、屏蔽词、user_hash(同一个人一样、不同的人不一样、看不出 id)、
UP 主删自己视频的弹幕、弹幕开关、拉黑双向隔离、高能进度条。

跑法:SUPERZ_API=http://127.0.0.1:8013 DATABASE_URL=… REDIS_URL=… python -m tests.e2e_danmaku
"""
import json
import time

from tests.util import call
from tests.video_util import clear_rate_limits, fixture_video, person, sql

SEG = 6 * 60 * 1000


def main():
    up, a, b = person(), person(), person()
    v = fixture_video(up.id, title="弹幕测试", duration_ms=10 * 60 * 1000)
    pid = v["part_id"]
    path = f"/video/v1/parts/{pid}/danmaku"

    def send(p, time_ms, text="好", expect_error=False, **kw):
        clear_rate_limits("danmaku", p.id)   # 限流单独测,别的用例不为它等 3 秒
        return p.post(path, {"time_ms": time_ms, "text": text, **kw}, expect_error=expect_error)

    # ---- 分段 ----
    d1 = send(a, 1000, "开头", color=16711680, mode=5, size=18)
    d2 = send(a, SEG - 1, "第一段最后一毫秒")
    d3 = send(a, SEG, "第二段第一毫秒")
    assert (d1["color"], d1["mode"], d1["size"]) == (16711680, 5, 18), d1
    s0 = call("GET", f"{path}?segment=0")
    s1 = call("GET", f"{path}?segment=1")
    assert s0["segment_ms"] == SEG and s0["segments"] == 2, s0
    assert [x["id"] for x in s0["items"]] == [d1["id"], d2["id"]], "第 0 段:[0, 360000),按时间排"
    assert [x["id"] for x in s1["items"]] == [d3["id"]], "第 1 段从 360000 开始"
    assert call("GET", f"{path}?segment=2")["items"] == []
    print("  ✓ 分段:6 分钟一段,359999 在第 0 段、360000 在第 1 段;共 2 段")

    # ---- user_hash:同一个人一样、不同的人不一样、不暴露 id ----
    hb = send(b, 2000, "我是 B")["user_hash"]
    assert d1["user_hash"] == d2["user_hash"] != hb and len(hb) == 8
    raw = json.dumps(call("GET", f"{path}?segment=0"))
    assert '"user_id"' not in raw and f'"{a.id}"' not in raw, "弹幕里不带发送人 id"
    assert all(x["mine"] is False for x in call("GET", f"{path}?segment=0")["items"])
    mine = [x for x in a.get(f"{path}?segment=0")["items"] if x["mine"]]
    assert {x["id"] for x in mine} == {d1["id"], d2["id"]}, "自己发的标 mine(客户端加边框)"
    print("  ✓ user_hash:8 位,同一个人相同、不同的人不同;响应里没有发送人 id;自己的标 mine")

    # ---- 输入校验 ----
    bad = [({"text": "长" * 101}, "100 字"), ({"text": "两\n行"}, "一行"),
           ({"text": "分\u2028隔"}, "一行"), ({"text": "   "}, "不能为空"),
           ({"mode": 2}, "模式"), ({"size": 20}, "字号"), ({"color": -1}, "颜色"),
           ({"color": 16777216}, "颜色"), ({"time_ms": 10 * 60 * 1000 + 1}, "长度")]
    for extra, needle in bad:
        body = {"time_ms": 1000, "text": "好", **extra}
        clear_rate_limits("danmaku", a.id)
        r = a.post(path, body, expect_error=True)
        assert r.get("_error") == 422 and needle in str(r["detail"]), (extra, r)
    ok = send(a, 3000, "长" * 100)
    assert len(ok["text"]) == 100
    r = send(a, 1000, "这里可以办证", expect_error=True)
    assert r.get("_error") == 422 and "不允许" in r["detail"], r
    print("  ✓ 校验:101 字、换行、U+2028、空白、模式 2、字号 20、颜色越界、时间超长都 422;100 字可以;屏蔽词拦住")

    # ---- 限流:每人每 3 秒 1 条、每天 1,000 条 ----
    clear_rate_limits("danmaku", b.id)
    b.post(path, {"time_ms": 5000, "text": "第一条"})
    r = call("POST", path, b.token, {"time_ms": 5001, "text": "第二条"}, expect_error=True,
             retry_429=False)
    assert r.get("_error") == 429 and "3 秒" in r["detail"], r
    time.sleep(3.1)
    b.post(path, {"time_ms": 5002, "text": "过了 3 秒可以"})
    import redis

    from app.config import settings
    rc = redis.Redis.from_url(settings.redis_url)
    day = time.strftime("%Y%m%d", time.gmtime(time.time() + 8 * 3600))
    rc.set(f"rld:danmaku:{b.id}:{day}", 1000)
    for k in rc.scan_iter(match=f"rls:danmaku:{b.id}:*"):
        rc.delete(k)
    r = call("POST", path, b.token, {"time_ms": 5003, "text": "第 1001 条"}, expect_error=True,
             retry_429=False)
    assert r.get("_error") == 429 and "1000" in r["detail"], r
    rc.delete(f"rld:danmaku:{b.id}:{day}")
    rc.close()
    print("  ✓ 限流:3 秒内第二条 429,过了 3 秒可以;一天第 1001 条 429")

    # ---- 删除:UP 主删别人的,别人删不了,发的人删自己的 ----
    r = b.delete(f"/video/v1/danmaku/{d1['id']}", expect_error=True)
    assert r.get("_error") == 403, "B 不能删 A 的弹幕"
    up.delete(f"/video/v1/danmaku/{d1['id']}")
    a.delete(f"/video/v1/danmaku/{d2['id']}")
    ids = {x["id"] for x in call("GET", f"{path}?segment=0")["items"]}
    assert d1["id"] not in ids and d2["id"] not in ids
    print("  ✓ 删除:UP 主能删自己视频下任何人的弹幕,发的人删自己的,别人 403")

    # ---- 高能进度条 ----
    den = call("GET", f"{path}/density")
    assert den["bucket_ms"] == 5000 and len(den["counts"]) == 120, den
    visible = [x for s in (0, 1) for x in call("GET", f"{path}?segment={s}")["items"]]
    assert sum(den["counts"]) == len(visible)
    assert den["counts"][SEG // 5000] == 1, "360000 那条落在第 72 桶"
    print("  ✓ 高能进度条:5 秒一桶,总数和能看到的弹幕一致")

    # ---- 拉黑双向隔离(S7)----
    hb_items = [x for x in call("GET", f"{path}?segment=0")["items"] if x["user_hash"] == hb]
    assert hb_items, "B 的弹幕大家都看得到"
    a.post("/social/v1/blocks", {"user_id": b.id})
    assert not [x for x in a.get(f"{path}?segment=0")["items"] if x["user_hash"] == hb], \
        "A 拉黑了 B:A 看不到 B 的弹幕"
    ha = d1["user_hash"]
    assert not [x for x in b.get(f"{path}?segment=0")["items"] if x["user_hash"] == ha], \
        "双向:B 也看不到 A 的弹幕"
    den_a = a.get(f"{path}/density")
    assert sum(den_a["counts"]) < sum(den["counts"]), "高能进度条也按拉黑过滤"
    up.post("/social/v1/blocks", {"user_id": b.id})
    r = send(b, 1000, "被 UP 主拉黑了", expect_error=True)
    assert r.get("_error") == 403 and "拉黑" in r["detail"], r
    a.delete(f"/social/v1/blocks/{b.id}")
    assert [x for x in a.get(f"{path}?segment=0")["items"] if x["user_hash"] == hb], "解除后恢复"
    print("  ✓ S7:A 拉黑 B 后双方互相看不到弹幕(高能进度条也过滤);被 UP 主拉黑的人不能在他视频下发弹幕")

    # ---- 弹幕开关、没公开的视频 ----
    sql("UPDATE videos SET allow_danmaku = false WHERE id = :v", {"v": v["id"]})
    r = send(a, 1000, "关了", expect_error=True)
    assert r.get("_error") == 403 and "关闭" in r["detail"], r
    assert call("GET", f"{path}?segment=0")["allow_danmaku"] is False
    sql("UPDATE videos SET allow_danmaku = true, status = 'reviewing' WHERE id = :v",
        {"v": v["id"]})
    assert call("GET", f"{path}?segment=0", expect_error=True).get("_error") == 404, \
        "审核中的视频弹幕别人拿不到"
    sql("UPDATE videos SET status = 'published' WHERE id = :v", {"v": v["id"]})
    cnt = sql("SELECT danmaku_count FROM videos WHERE id = :v", {"v": v["id"]}, fetch="scalar")
    alive = sql("SELECT count(*) FROM danmaku WHERE video_id = :v AND deleted_at IS NULL",
                {"v": v["id"]}, fetch="scalar")
    assert cnt == alive, (cnt, alive)
    print("  ✓ 弹幕开关关了 403;审核中的视频拿不到弹幕;视频上的弹幕数和明细一致")
    print("e2e_danmaku 全部通过 ✅")


if __name__ == "__main__":
    main()
