"""评论 e2e(DEV-PROMPTS-40 #362 #367,§5.7,不变量 S7)。

两级评论(一级 + 回复,回复的是回复时带「回复 @某人」)、赞 / 踩(点踩数不对外)、热度 / 时间排序和分页、
UP 主置顶一条、UP 主删自己视频下的评论、作者标记、@ 提及、评论开关、屏蔽词、长度、限流;
@ 跟着对方的「按超级赞号找到我」:关了就当普通文字、不通知,和 @ 没注册的号一样,关之前发的也不再给链接;
互动消息:被评论 / 被回复进「回复我的」、被 @ 进「@我的」、被赞按评论合并进「收到的赞」;
S7:拉黑的人的评论双向不可见,不能评论拉黑了你的 UP 主的视频,不能回复对方。

跑法:SUPERZ_API=http://127.0.0.1:8013 DATABASE_URL=… REDIS_URL=… python -m tests.e2e_video_comments
"""
import json

from tests.chat_util import set_username
from tests.util import call
from tests.video_util import clear_rate_limits, fixture_video, person, rand_name, sql


def main():
    up, a, b, c = person(), person(), person(), person()
    c_name = set_username(c, "Cmen")
    v = fixture_video(up.id, title="评论测试")
    vid = v["vid"]
    base = f"/video/v1/videos/{vid}/comments"

    def say(p, text, parent=None, expect_error=False):
        clear_rate_limits("video_comment", p.id)
        body = {"text": text} if parent is None else {"text": text, "parent_id": parent}
        return p.post(base, body, expect_error=expect_error)

    def act(p):
        clear_rate_limits("video_act", p.id)
        return p

    # ---- 两级评论、回复 @、作者标记、@ 提及 ----
    ra = say(a, f"第一条,@{c_name} 你也来看看")
    assert ra["root_id"] is None and ra["reply_to"] is None and ra["is_up"] is False, ra
    assert ra["mentions"] == [{"user_id": c.id, "username": c_name.lower()}], ra["mentions"]
    rb = say(b, "回复一级评论", parent=ra["id"])
    assert rb["root_id"] == ra["id"] and rb["parent_id"] == ra["id"] and rb["reply_to"] is None, \
        "直接回复一级评论不显示「回复 @」"
    rc = say(c, "回复 B 的回复", parent=rb["id"])
    assert rc["root_id"] == ra["id"] and rc["reply_to"] == {"id": b.id, "name": b.name}, rc
    rup = say(up, "UP 主来了")
    assert rup["is_up"] is True
    for i in range(3):
        say(b, f"B 的第 {i} 条回复", parent=ra["id"])
    lst = call("GET", f"{base}?sort=new")
    roots = {x["id"]: x for x in lst["items"]}
    assert set(roots) == {ra["id"], rup["id"]} and lst["count"] == 7, (list(roots), lst["count"])
    assert roots[ra["id"]]["reply_count"] == 5
    assert [x["id"] for x in roots[ra["id"]]["replies"]] == [rb["id"], rc["id"],
                                                             roots[ra["id"]]["replies"][2]["id"]]
    assert len(roots[ra["id"]]["replies"]) == 3, "一级评论带最早的 3 条回复"
    page1 = call("GET", f"/video/v1/comments/{ra['id']}/replies")
    assert page1["root"]["id"] == ra["id"] and len(page1["items"]) == 5
    assert [x["id"] for x in page1["items"]] == sorted(x["id"] for x in page1["items"])
    print("  ✓ 两级:一级评论 + 回复(回复的是回复才带「回复 @某人」),一级带 3 条预览;UP 主标记;@ 提及解析出人")

    # ---- 互动消息:回复我的 / @我的 ----
    n_up = up.get("/social/v1/notifications?kind=reply")["items"]
    assert any(x["actor"]["id"] == a.id and x["title"].endswith("评论了你的视频") for x in n_up)
    n_a = a.get("/social/v1/notifications?kind=reply")["items"]
    assert any(x["actor"]["id"] == b.id and x["title"].endswith("回复了你的评论") for x in n_a)
    n_b = b.get("/social/v1/notifications?kind=reply")["items"]
    assert any(x["actor"]["id"] == c.id for x in n_b), "回复的回复通知被回复的那个人"
    n_c = c.get("/social/v1/notifications?kind=at")["items"]
    assert n_c and n_c[0]["actor"]["id"] == a.id and "@ 了你" in n_c[0]["title"], n_c
    assert n_c[0]["comment"]["id"] == ra["id"] and n_c[0]["video"]["vid"] == vid, n_c[0]
    print("  ✓ 互动消息:评论视频 → UP 主「回复我的」;回复 → 被回复的人;@ → 被 @ 的人「@我的」,带跳转用的评论 id")

    # ---- @ 跟着「按超级赞号找到我」走:关了就当普通文字,和 @ 一个没注册的号一样 ----
    # 另开一个视频,不动上面这个视频的评论数和分页
    base2 = f"/video/v1/videos/{fixture_video(up.id, title='@ 开关测试')['vid']}/comments"

    def say2(p, text, parent=None):
        clear_rate_limits("video_comment", p.id)
        return p.post(base2, {"text": text} if parent is None else {"text": text, "parent_id": parent})

    def ats():
        return len(c.get("/social/v1/notifications?kind=at")["items"])

    def listed(viewer=None):
        items = (viewer.get if viewer else lambda path: call("GET", path))(f"{base2}?sort=new")["items"]
        return {x["id"]: x for x in items}

    me_c = [{"user_id": c.id, "username": c_name.lower()}]
    n0 = ats()
    old = say2(a, f"开关开着:@{c_name} 看这个")
    old_reply = say2(b, f"回复里也 @{c_name}", parent=old["id"])
    assert old["mentions"] == me_c and old_reply["mentions"] == me_c and ats() == n0 + 2, \
        "开着:有链接,有「@我的」"

    c.patch("/social/v1/me", {"privacy": {"username_search": "nobody"}})
    off = say2(a, f"关了开关:@{c_name} 看这个")
    ghost = say2(a, f"关了开关:@{rand_name('Ghostq')} 看这个")    # 从没注册过的号

    def same(x):
        return {k: x[k] for k in x if k not in ("id", "text", "created_at")}

    assert off["mentions"] == [] and same(off) == same(ghost), \
        f"关了开关的号和没注册的号,响应一模一样:{off} / {ghost}"
    assert ats() == n0 + 2, "关了开关:不发「@我的」"
    # 关之前发的:展示时也不再给链接 —— 一级评论、带的回复预览、回复列表;他自己看也一样(评论是公开的)
    for view in (listed(), listed(c)):
        assert view[old["id"]]["mentions"] == [] and view[old["id"]]["replies"][0]["mentions"] == []
    thread = call("GET", f"/video/v1/comments/{old['id']}/replies")
    assert thread["root"]["mentions"] == [] and thread["items"][0]["mentions"] == []

    c.patch("/social/v1/me", {"privacy": {"username_search": "everyone"}})
    view = listed()
    assert view[old["id"]]["mentions"] == me_c and view[old["id"]]["replies"][0]["mentions"] == me_c, \
        "重新打开:关之前发的评论,链接回来"
    assert view[off["id"]]["mentions"] == [] and ats() == n0 + 2, \
        "关着时发的那条当时就当文字存了:打开之后不补链接、不补「@我的」"
    assert say2(a, f"重新打开:@{c_name}")["mentions"] == me_c and ats() == n0 + 3
    print("  ✓ @ 跟着「按超级赞号找到我」:开着有链接有「@我的」;关了当普通文字、不通知,和 @ 没注册的号响应一样,"
          "关之前发的也不给链接(谁看都一样);重新打开旧链接回来,关着时发的不补")

    # ---- 赞 / 踩:点踩数不对外;赞按评论合并通知 ----
    act(b).post(f"/video/v1/comments/{ra['id']}/vote", {"vote": 1})
    r = act(c).post(f"/video/v1/comments/{ra['id']}/vote", {"vote": -1})
    assert r["likes"] == 1 and r["my_vote"] == -1 and "dislikes" not in r, r
    raw = json.dumps(call("GET", f"{base}?sort=hot"))
    assert "dislike" not in raw, "点踩数不能出现在任何响应里"
    act(c).post(f"/video/v1/comments/{ra['id']}/vote", {"vote": 1})
    act(up).post(f"/video/v1/comments/{ra['id']}/vote", {"vote": 1})
    likes = a.get("/social/v1/notifications?kind=like")["items"]
    mine = [x for x in likes if x["comment"] and x["comment"]["id"] == ra["id"]]
    assert len(mine) == 1 and mine[0]["count"] == 3 and "等 3 人赞了你的评论" in mine[0]["title"], mine
    assert mine[0]["actor"]["id"] == up.id and [x["id"] for x in mine[0]["actors"]] == \
        [up.id, c.id, b.id], mine[0]["actors"]
    assert sql("SELECT dislikes FROM video_comments WHERE id = :i", {"i": ra["id"]},
               fetch="scalar") == 0, "改成赞之后踩数也跟着减"
    act(b).post(f"/video/v1/comments/{ra['id']}/vote", {"vote": 0})
    me_a = a.get(f"{base}?sort=hot")["items"]
    assert next(x for x in me_a if x["id"] == ra["id"])["likes"] == 2
    r = act(b).post(f"/video/v1/comments/{ra['id']}/vote", {"vote": 5}, expect_error=True)
    assert r.get("_error") == 422
    print("  ✓ 赞踩:点踩数不对外;三个人赞 → 一行「小王等 3 人赞了你的评论」(新的在前);取消赞计数回落")

    # ---- 排序与置顶 ----
    for i in range(3):
        say(c, f"C 的第 {i} 条一级评论")
    hot = call("GET", f"{base}?sort=hot")["items"]
    assert hot[0]["id"] == ra["id"], "热度:赞 + 回复最多的在前"
    new = call("GET", f"{base}?sort=new")["items"]
    assert [x["id"] for x in new] == sorted((x["id"] for x in new), reverse=True), "时间倒序"
    r = act(a).post(f"/video/v1/comments/{rup['id']}/pin", {"pinned": True}, expect_error=True)
    assert r.get("_error") == 403, "只有 UP 主能置顶"
    r = up.post(f"/video/v1/comments/{rb['id']}/pin", {"pinned": True}, expect_error=True)
    assert r.get("_error") == 422, "只能置顶一级评论"
    last_c = new[0]
    up.post(f"/video/v1/comments/{last_c['id']}/pin", {"pinned": True})
    for sort in ("hot", "new"):
        items = call("GET", f"{base}?sort={sort}")["items"]
        assert items[0]["id"] == last_c["id"] and items[0]["pinned"], sort
    up.post(f"/video/v1/comments/{rup['id']}/pin", {"pinned": True})
    items = call("GET", f"{base}?sort=new")["items"]
    assert items[0]["id"] == rup["id"] and sum(1 for x in items if x["pinned"]) == 1, "只能置顶一条"
    print("  ✓ 排序:热度(赞 + 回复)/ 时间倒序;UP 主置顶一条(新的顶掉旧的),别人 403,回复 422")

    # ---- 分页 ----
    for i in range(20):
        say([a, b, c][i % 3], f"凑分页 {i}")
    p1 = call("GET", f"{base}?sort=new")
    p2 = call("GET", f"{base}?sort=new&cursor={p1['next_cursor']}")
    ids1, ids2 = [x["id"] for x in p1["items"]], [x["id"] for x in p2["items"]]
    assert len(ids1) == 20 and not set(ids1) & set(ids2) and ids1[0] == rup["id"], "置顶只在第一页"
    assert rup["id"] not in ids2
    h1 = call("GET", f"{base}?sort=hot")
    h2 = call("GET", f"{base}?sort=hot&cursor={h1['next_cursor']}")
    assert not {x["id"] for x in h1["items"]} & {x["id"] for x in h2["items"]}
    total_roots = len(ids1) + len(ids2)
    assert total_roots == 2 + 3 + 20, total_roots
    print("  ✓ 分页:时间序按 id 游标、热度按偏移,两页不重复;置顶只在第一页")

    # ---- 删除 ----
    r = a.delete(f"/video/v1/comments/{rc['id']}", expect_error=True)
    assert r.get("_error") == 403, "A 不能删 C 的回复"
    up.delete(f"/video/v1/comments/{rc['id']}")        # UP 主删自己视频下别人的
    b.delete(f"/video/v1/comments/{rb['id']}")          # 作者删自己的
    root = call("GET", f"/video/v1/comments/{ra['id']}/replies")
    assert rc["id"] not in [x["id"] for x in root["items"]] and root["root"]["reply_count"] == 3
    before = call("GET", f"/video/v1/videos/{vid}")["comment_count"]
    a.delete(f"/video/v1/comments/{ra['id']}")          # 删一级评论:楼里的回复一起不显示
    after = call("GET", f"/video/v1/videos/{vid}")["comment_count"]
    assert before - after == 1 + 3, (before, after)
    assert ra["id"] not in [x["id"] for x in call("GET", f"{base}?sort=new")["items"]]
    assert call("GET", f"/video/v1/comments/{ra['id']}/replies",
                expect_error=True).get("_error") == 404
    r = say(b, "回复已删的楼", parent=ra["id"], expect_error=True)
    assert r.get("_error") == 404
    print("  ✓ 删除:UP 主删别人的、作者删自己的、别人 403;删一级评论整楼不再显示,评论数一起减")

    # ---- 校验、屏蔽词、限流、评论开关 ----
    assert say(a, "   ", expect_error=True).get("_error") == 422
    assert say(a, "长" * 1001, expect_error=True).get("_error") == 422
    assert len(say(a, "长" * 1000)["text"]) == 1000
    r = say(a, "需要办证的找我", expect_error=True)
    assert r.get("_error") == 422 and "不允许" in r["detail"], r
    clear_rate_limits("video_comment", b.id)
    b.post(base, {"text": "限流第一条"})
    r = call("POST", base, b.token, {"text": "限流第二条"}, expect_error=True, retry_429=False)
    assert r.get("_error") == 429 and "5 秒" in r["detail"], r
    sql("UPDATE videos SET allow_comments = false WHERE id = :v", {"v": v["id"]})
    r = say(a, "关了还能评论吗", expect_error=True)
    assert r.get("_error") == 403 and "关闭" in r["detail"], r
    assert call("GET", base)["allow_comments"] is False
    sql("UPDATE videos SET allow_comments = true WHERE id = :v", {"v": v["id"]})
    print("  ✓ 校验:空、1001 字 422,1000 字可以;屏蔽词 422;5 秒内第二条 429;评论开关关了 403")

    # ---- S7:拉黑双向隔离 ----
    rb2 = say(b, "B 的一级评论")
    rr = say(b, "B 回复 C", parent=new[0]["id"])
    a.post("/social/v1/blocks", {"user_id": b.id})
    seen_a = [x for x in a.get(f"{base}?sort=new")["items"]] + \
        a.get(f"/video/v1/comments/{new[0]['id']}/replies")["items"]
    assert b.id not in {x["user"]["id"] for x in seen_a}, "A 拉黑 B:B 的评论和回复 A 都看不到"
    seen_b = b.get(f"{base}?sort=new")["items"]
    assert a.id not in {x["user"]["id"] for x in seen_b}, "双向:B 也看不到 A 的"
    assert rb2["id"] in {x["id"] for x in call("GET", f"{base}?sort=new")["items"]}, "别人照常看得到"
    mine_a = say(a, "A 的新评论")
    r = say(b, "回复拉黑了我的人", parent=mine_a["id"], expect_error=True)
    assert r.get("_error") == 403, "不能回复有拉黑关系的人"
    r = act(b).post(f"/video/v1/comments/{mine_a['id']}/vote", {"vote": 1}, expect_error=True)
    assert r.get("_error") == 404, "也不能给对方点赞"
    up.post("/social/v1/blocks", {"user_id": c.id})
    r = say(c, "UP 主拉黑了我", expect_error=True)
    assert r.get("_error") == 403 and "拉黑" in r["detail"], "被 UP 主拉黑的人不能评论他的视频"
    assert rr["id"] not in {x["id"] for x in seen_a}
    print("  ✓ S7:A 拉黑 B 后双方互相看不到评论和回复、不能互相回复和点赞,第三人照常;被 UP 主拉黑的人不能评论")

    # ---- 视频上的评论数和明细一致 ----
    cnt = sql("SELECT comment_count FROM videos WHERE id = :v", {"v": v["id"]}, fetch="scalar")
    alive = sql("SELECT count(*) FROM video_comments c LEFT JOIN video_comments r ON r.id = c.root_id "
                "WHERE c.video_id = :v AND c.deleted_at IS NULL "
                "AND (c.root_id IS NULL OR r.deleted_at IS NULL)", {"v": v["id"]}, fetch="scalar")
    assert cnt == alive, (cnt, alive)
    print("  ✓ 评论数和明细一致")
    print("e2e_video_comments 全部通过 ✅")


if __name__ == "__main__":
    main()
