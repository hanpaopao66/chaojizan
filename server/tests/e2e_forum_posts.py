"""论坛:发帖、实体、图片、卡片、回复成串、引用、编辑、删除、投票、赞 / 转发 / 书签、浏览、置顶
(DEV-PROMPTS-41 §5.6、§8.1、§8.3,#380)。

这组守的是:
- **实体只由服务端解析** —— 客户端自己报 entities 不算数;
- 图片只能是本人上传的 `/img/forum/u<我>-…`,最多 4 张;
- 回复成串(root 记整串第一条)、谁能回复、引用不套娃、被引用的删了照样占位;
- 编辑 30 分钟内最多 5 次、留历史;删除是软删,下面的回复保留;
- **投票前看不到票数**(§8.1),每人一票不能改;
- 浏览按人按天去重。

    . "$(bash scripts/e2e_iso.sh env 2)" && cd server && python -m tests.e2e_forum_posts
"""
from tests.chat_util import set_username
from tests.forum_util import (act, age_poll, age_post, clear_rate_limits, person, post,
                              run_sweep, upload_forum_image)


def main() -> None:
    a, b, c = person("137"), person("137"), person("137")
    a_name, b_name = set_username(a, "fa"), set_username(b, "fb")

    # ---------- 发帖:实体只由服务端解析 ----------
    p = post(a, f"周末去 #成都# 玩 @{b_name},看 https://chaojizan.cc/x",
             entities={"tags": [{"tag": "假的", "display": "假的"}]})
    assert p["pid"].startswith("fp") and len(p["pid"]) == 12, p["pid"]
    ent = p["entities"]
    assert ent["tags"] == [{"tag": "成都", "display": "成都"}], ent
    assert [m["username"] for m in ent["mentions"]] == [b_name], ent
    assert ent["links"] == ["https://chaojizan.cc/x"], ent
    assert p["counts"] == {"replies": 0, "reposts": 0, "quotes": 0, "likes": 0,
                           "bookmarks": 0, "views": 0}, p["counts"]
    assert p["viewer"] == {"liked": False, "reposted": False, "bookmarked": False}
    assert p["edited"] is False and p["pinned"] is False and p["reply_policy"] == "all"
    print("✓ 发帖:话题、@、链接由服务端解析,客户端自己报的 entities 不算数")

    # 被 @ 到的人收到「@我的」
    at = b.get("/social/v1/notifications?kind=at")["items"]
    assert at and at[0]["post"]["pid"] == p["pid"], at
    assert at[0]["title"] == f"{a.name} 在帖子里 @ 了你", at[0]["title"]
    print("✓ @ 到的人收到互动消息,带 post: {pid, text}")

    # ---------- 正文上限、空帖 ----------
    r = post(a, "字" * 501, expect_error=True)
    assert r.get("_error") == 422, r
    r = post(a, "   ", expect_error=True)
    assert r.get("_error") == 422, f"空帖不该发得出去:{r}"
    print("✓ 正文 500 字上限;什么都没有的帖子发不出去")

    # ---------- 图片:只能是本人上传的、最多 4 张 ----------
    url_a = upload_forum_image(a)
    assert url_a.startswith(f"/img/forum/u{a.id}-"), url_a
    withimg = post(a, "配图", media=[{"url": url_a, "w": 320, "h": 240}])
    assert withimg["media"] == [{"url": url_a, "w": 320, "h": 240}], withimg["media"]
    r = post(a, "偷图", media=[{"url": upload_forum_image(b)}], expect_error=True)
    assert r.get("_error") == 422, f"用了别人上传的图还能发:{r}"
    r = post(a, "五张", media=[{"url": url_a} for _ in range(5)], expect_error=True)
    assert r.get("_error") == 422, r
    # 只有图、没有正文是可以的
    only_img = post(a, "", media=[{"url": url_a}])
    assert only_img["text"] == "" and only_img["media"]
    print("✓ 图片只能用自己刚传的、最多 4 张;只有图没有字也能发")

    # ---------- 卡片:现查,不存快照 ----------
    card_post = post(b, "看这条", card={"type": "post", "id": p["pid"]})
    assert card_post["card"]["type"] == "post" and card_post["card"]["id"] == p["pid"]
    assert card_post["card"]["url"].endswith(f"/forum/p/{p['pid']}"), card_post["card"]
    r = post(b, "假卡片", card={"type": "post", "id": "fpZZZZZZZZZZ"}, expect_error=True)
    assert r.get("_error") == 422, r
    r = post(b, "没这种", card={"type": "track", "id": "mt1"}, expect_error=True)
    assert r.get("_error") == 422, f"音乐还没合并进来,歌曲卡片不该能发:{r}"
    print("✓ 卡片只存 {type,id},发的时候要能查得到;不认识的类型 422")

    # ---------- 回复成串 ----------
    r1 = post(b, "第一层回复", reply_to_pid=p["pid"])
    r2 = post(c, "第二层回复", reply_to_pid=r1["pid"])
    assert r1["root_pid"] == p["pid"] and r2["root_pid"] == p["pid"], (r1, r2)
    assert r2["reply_to"]["pid"] == r1["pid"] and r2["reply_to"]["author"]["id"] == b.id
    detail = c.get(f"/forum/v1/posts/{r2['pid']}")
    assert [x["pid"] for x in detail["ancestors"]] == [p["pid"], r1["pid"]], detail["ancestors"]
    assert a.get(f"/forum/v1/posts/{p['pid']}")["post"]["counts"]["replies"] == 1
    print("✓ 回复成串:root 记整串第一条,详情带上文")

    # 作者收到「回复我的」
    replies_n = a.get("/social/v1/notifications?kind=reply")["items"]
    assert replies_n and replies_n[0]["post"]["pid"] == r1["pid"], replies_n
    assert replies_n[0]["title"] == f"{b.name} 回复了你的帖子", replies_n[0]["title"]

    # ---------- 谁能回复 ----------
    only_mentioned = post(a, f"只有我提到的人能回 @{b_name}", reply_policy="mentioned")
    assert post(b, "我被提到了", reply_to_pid=only_mentioned["pid"])["pid"]
    r = post(c, "我没被提到", reply_to_pid=only_mentioned["pid"], expect_error=True)
    assert r.get("_error") == 403, f"没被提到的人还能回:{r}"
    only_following = post(a, "只有我关注的人能回", reply_policy="following")
    r = post(c, "你没关注我", reply_to_pid=only_following["pid"], expect_error=True)
    assert r.get("_error") == 403, r
    a.post(f"/social/v1/users/{c.id}/follow")
    assert post(c, "现在关注我了", reply_to_pid=only_following["pid"])["pid"]
    print("✓ 谁能回复:所有人 / 我关注的人 / 我提到的人,三档都挡得住")

    # ---------- 引用 ----------
    q = post(c, "说得好", quote_pid=p["pid"])
    assert q["quote"]["pid"] == p["pid"] and q["quote"]["text"].startswith("周末去")
    assert q["quote"].get("quote") is None, "引用不套娃"
    assert a.get(f"/forum/v1/posts/{p['pid']}")["post"]["counts"]["quotes"] == 1
    quotes = a.get(f"/forum/v1/posts/{p['pid']}/quotes")["items"]
    assert [x["pid"] for x in quotes] == [q["pid"]], quotes
    qn = a.get("/social/v1/notifications?kind=quote")["items"]
    assert qn and qn[0]["title"] == f"{c.name} 引用了你的帖子", qn
    print("✓ 引用:被引用的展开一层、计数和「引用的人」都对,作者收到 quote 消息")

    # ---------- 编辑 ----------
    edited = a.patch(f"/forum/v1/posts/{p['pid']}", {"text": "改成 #天气 了"})
    assert edited["edited"] is True and edited["edited_at"], edited
    assert edited["entities"]["tags"] == [{"tag": "天气", "display": "天气"}], edited["entities"]
    hist = c.get(f"/forum/v1/posts/{p['pid']}/edits")
    assert len(hist) == 1 and hist[0]["text"].startswith("周末去"), hist
    r = b.patch(f"/forum/v1/posts/{p['pid']}", {"text": "我改你的"}, expect_error=True)
    assert r.get("_error") == 403, r
    old = post(a, "很久以前发的")
    age_post(old["pid"], 1)
    r = a.patch(f"/forum/v1/posts/{old['pid']}", {"text": "现在改"}, expect_error=True)
    assert r.get("_error") == 409, f"发出 30 分钟以后还能改:{r}"
    many = post(a, "改五次")
    for i in range(5):
        a.patch(f"/forum/v1/posts/{many['pid']}", {"text": f"第 {i} 次"})
    r = a.patch(f"/forum/v1/posts/{many['pid']}", {"text": "第六次"}, expect_error=True)
    assert r.get("_error") == 409, f"编辑超过 5 次还放行:{r}"
    print("✓ 编辑:本人、30 分钟内、最多 5 次,留历史,话题跟着正文改")

    # ---------- 赞、转发、书签 ----------
    # 都走 act():每人每秒 5 次(§5.10),这一段连着点十几下,每次先清桶 —— 这里测的不是限流
    like = f"/forum/v1/posts/{p['pid']}/like"
    out = act(b, "POST", like)
    assert out == {"liked": True, "likes": 1}, out
    assert act(b, "POST", like) == {"liked": True, "likes": 1}, "重复赞不加"
    likers = a.get(f"/forum/v1/posts/{p['pid']}/likers")["items"]
    assert [x["id"] for x in likers] == [b.id], likers
    likes_n = a.get("/social/v1/notifications?kind=like")["items"]
    post_likes = [n for n in likes_n if n.get("post")]
    assert post_likes and post_likes[0]["title"] == f"{b.name} 赞了你的帖子", post_likes
    act(c, "POST", like)
    merged = [n for n in a.get("/social/v1/notifications?kind=like")["items"] if n.get("post")]
    assert merged[0]["count"] == 2 and merged[0]["title"] == f"{c.name}等 2 人赞了你的帖子", merged
    assert len(merged) == 1, "赞按帖子合并成一行"
    assert act(b, "DELETE", like) == {"liked": False, "likes": 1}

    rp = f"/forum/v1/posts/{p['pid']}/repost"
    assert act(b, "POST", rp) == {"reposted": True, "reposts": 1}
    rn = [n for n in a.get("/social/v1/notifications?kind=repost")["items"] if n.get("post")]
    assert rn and rn[0]["title"] == f"{b.name} 转发了你的帖子", rn
    assert act(b, "DELETE", rp) == {"reposted": False, "reposts": 0}

    bm = f"/forum/v1/posts/{p['pid']}/bookmark"
    assert act(b, "POST", bm) == {"bookmarked": True}
    marks = b.get("/forum/v1/me/bookmarks")["items"]
    assert [x["pid"] for x in marks] == [p["pid"]], marks
    assert a.get(f"/forum/v1/posts/{p['pid']}")["post"]["counts"]["bookmarks"] == 1
    assert act(b, "DELETE", bm) == {"bookmarked": False}
    print("✓ 赞 / 转发 / 书签:计数、互动消息合并、点赞的人、书签列表都对")

    # ---------- 投票:投票前看不到票数 ----------
    poll = post(a, "中午吃什么", poll={"options": ["火锅", "串串", "冒菜"], "minutes": 60})
    assert poll["poll"]["total"] == 0, f"作者自己看得到票数:{poll['poll']}"
    seen_by_b = b.get(f"/forum/v1/posts/{poll['pid']}")["post"]["poll"]
    assert seen_by_b["total"] is None and all(o["votes"] is None for o in seen_by_b["options"]), \
        f"没投票就看到票数了:{seen_by_b}"
    assert seen_by_b["voted"] is None and seen_by_b["closed"] is False
    vote_path = f"/forum/v1/posts/{poll['pid']}/vote"
    after = act(b, "POST", vote_path, {"option": 1})
    assert after["voted"] == 1 and after["total"] == 1, after
    assert [o["votes"] for o in after["options"]] == [0, 1, 0], after
    r = act(b, "POST", vote_path, {"option": 0}, expect_error=True)
    assert r.get("_error") == 409, f"投过票还能改:{r}"
    r = act(c, "POST", vote_path, {"option": 9}, expect_error=True)
    assert r.get("_error") == 422, r
    r = post(a, "一个选项", poll={"options": ["甲"], "minutes": 60}, expect_error=True)
    assert r.get("_error") == 422, r
    print("✓ 投票:投票前看不到票数,每人一票不能改,选项数和时长都校验")

    # 投票结束:作者和投过票的人各收到一条 system,清扫跑两遍也只发一次
    age_poll(poll["pid"], 1)
    assert run_sweep()["polls_closed"] >= 1
    for who in (a, b):
        msgs = [n for n in who.get("/social/v1/notifications?kind=system")["items"]
                if (n["data"] or {}).get("action") == "poll_closed"
                and (n["data"] or {}).get("pid") == poll["pid"]]
        assert len(msgs) == 1, f"投票结束的通知不是一条:{msgs}"
    run_sweep()
    again = [n for n in a.get("/social/v1/notifications?kind=system")["items"]
             if (n["data"] or {}).get("pid") == poll["pid"]]
    assert len(again) == 1, "清扫跑第二遍又发了一条"
    ended = b.get(f"/forum/v1/posts/{poll['pid']}")["post"]["poll"]
    assert ended["closed"] is True and ended["total"] == 1, ended
    没投过的人 = c.get(f"/forum/v1/posts/{poll['pid']}")["post"]["poll"]
    assert 没投过的人["total"] == 1, "结束之后谁都看得到票数"
    print("✓ 投票结束:作者和投过票的人各一条 system,清扫幂等;结束后票数对所有人可见")

    # ---------- 浏览:按人按天去重 ----------
    clear_rate_limits("forum_views", b.id)
    assert b.post("/forum/v1/posts/views", {"pids": [p["pid"], q["pid"]]})["counted"] == 2
    assert b.post("/forum/v1/posts/views", {"pids": [p["pid"]]})["counted"] == 0, "同一天不重复算"
    assert c.post("/forum/v1/posts/views", {"pids": [p["pid"]]})["counted"] == 1
    assert a.get(f"/forum/v1/posts/{p['pid']}")["post"]["counts"]["views"] == 2
    print("✓ 浏览:按人按天去重,刷新一次不涨一次")

    # ---------- 置顶 ----------
    a.post(f"/forum/v1/posts/{p['pid']}/pin")
    prof = b.get(f"/forum/v1/users/{a.id}/profile")
    assert prof["pinned"]["pid"] == p["pid"] and prof["pinned"]["pinned"] is True, prof["pinned"]
    r = b.post(f"/forum/v1/posts/{p['pid']}/pin", expect_error=True)
    assert r.get("_error") == 403, r
    a.delete("/forum/v1/pin")
    assert b.get(f"/forum/v1/users/{a.id}/profile")["pinned"] is None
    print("✓ 置顶:只能置顶自己的,取消后主页上没有")

    # ---------- 删除:软删,下面的回复保留 ----------
    a.delete(f"/forum/v1/posts/{p['pid']}")
    r = b.get(f"/forum/v1/posts/{p['pid']}", expect_error=True)
    assert r.get("_error") == 404, r
    串 = c.get(f"/forum/v1/posts/{r2['pid']}")
    assert 串["ancestors"][0] == {"pid": p["pid"], "unavailable": True, "reason": "deleted"}, \
        串["ancestors"]
    assert 串["post"]["text"] == "第二层回复", "别人的回复不跟着消失"
    quoting = c.get(f"/forum/v1/posts/{q['pid']}")["post"]
    assert quoting["quote"] == {"pid": p["pid"], "unavailable": True, "reason": "deleted"}, \
        quoting["quote"]
    print("✓ 删除是软删:串里占位、引用里占位,别人的回复留着")

    # ---------- 个人主页各页签 ----------
    mine = a.get(f"/forum/v1/users/{a.id}/posts?tab=posts")["items"]
    assert all(it["type"] in ("post", "repost") for it in mine), mine[:1]
    media_tab = a.get(f"/forum/v1/users/{a.id}/posts?tab=media")["items"]
    assert all(x["media"] for x in media_tab), media_tab[:1]
    likes_tab = b.get(f"/forum/v1/users/{b.id}/posts?tab=likes")
    assert isinstance(likes_tab["items"], list)
    r = a.get(f"/forum/v1/users/{b.id}/posts?tab=likes", expect_error=True)
    assert r.get("_error") == 403, f"别人喜欢过什么不该给我看:{r}"
    print("✓ 主页页签:posts 含转发、media 只给带图的、likes 只有本人看得见")

    print("\ne2e_forum_posts 全部通过 ✅")


if __name__ == "__main__":
    main()
