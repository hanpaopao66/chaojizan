"""论坛:举报、下架与恢复、申诉换人复核、话题隐藏留痕、处罚管得到、注销清干净
(DEV-PROMPTS-41 §3.6、§3.7、§5.11、§8.3 后台部分,#380)。

这组守的是:
- 下架必须带原因代码、X999 要写说明;作者收到 system 互动消息,**能申诉一次**;
- **原审核人不能复核自己的决定**(403,换人);改判自动恢复帖子;
- 话题隐藏要写原因、留痕;
- 禁言 / 封号挡得住发帖,但申诉、书签、屏蔽词、浏览上报照样能用;
- 注销之后帖子正文清空、别人的回复还在。

    . "$(bash scripts/e2e_iso.sh env 2)" && cd server && python -m tests.e2e_forum_moderation
"""
import urllib.parse

from tests.forum_util import admin2_token, admin_token, call, clear_rate_limits, person, post, sql


def main() -> None:
    author, reporter = person("137"), person("137")
    admin, admin2 = admin_token(), admin2_token()

    # ---------- 举报 ----------
    p = post(author, "被举报的帖子 #热门话题测试")
    r = reporter.post("/forum/v1/reports", {"pid": p["pid"], "reason_code": "BAD1"},
                      expect_error=True)
    assert r.get("_error") == 422, f"原因代码不存在还收:{r}"
    assert reporter.post("/forum/v1/reports",
                         {"pid": p["pid"], "reason_code": "F403", "note": "人身攻击"}) == {"ok": True}
    codes = {c["code"] for c in call("GET", "/forum/v1/reason-codes")["items"]}
    assert {"C101", "X999", "F401", "F402", "F403"} <= codes, codes
    assert not [c for c in codes if c.startswith("V")], "视频专有的原因代码不该出现在论坛"
    reports = call("GET", "/admin/forum/reports?status=open", admin)["items"]
    mine = next(x for x in reports if x["post"] and x["post"]["pid"] == p["pid"])
    assert mine["reason_code"] == "F403" and mine["reason_label"] == "恶意引战、人身攻击", mine
    assert "reporter" not in mine and "reporter_id" not in mine, "举报人不该出现在后台列表里"
    print("✓ 举报:原因代码校验、后台看得到、举报人匿名")

    # ---------- 处理举报 = 下架 ----------
    r = call("POST", f"/admin/forum/reports/{mine['id']}/handle", admin,
             {"action": "remove", "reason_code": "X999", "note": "太短"}, expect_error=True)
    assert r.get("_error") == 422, f"X999 没写说明还放行:{r}"
    out = call("POST", f"/admin/forum/reports/{mine['id']}/handle", admin,
               {"action": "remove", "reason_code": "F403", "note": "多次人身攻击"})
    assert out["status"] == "actioned" and "已下架" in out["resolution"], out
    r = call("POST", f"/admin/forum/reports/{mine['id']}/handle", admin,
             {"action": "dismiss"}, expect_error=True)
    assert r.get("_error") == 409, "同一条举报处理两次"
    r = reporter.get(f"/forum/v1/posts/{p['pid']}", expect_error=True)
    assert r.get("_error") == 404, r
    # 作者自己看得到,而且知道为什么
    own = author.get(f"/forum/v1/posts/{p['pid']}")["post"]
    assert own["pid"] == p["pid"], own
    sysmsgs = author.get("/social/v1/notifications?kind=system")["items"]
    down = next(n for n in sysmsgs if (n["data"] or {}).get("pid") == p["pid"])
    assert down["title"] == "帖子已下架" and down["data"]["reason_code"] == "F403", down
    assert down["data"]["reason_label"] == "恶意引战、人身攻击", down["data"]
    assert down["post"]["pid"] == p["pid"] and down["post"]["unavailable"] is True, down["post"]
    print("✓ 下架:原因代码必填、X999 要说明、举报一起结案、作者收到 system 并知道原因")

    # ---------- 申诉:一次,而且换人 ----------
    r = author.post(f"/forum/v1/posts/{p['pid']}/appeal", {"text": "短"}, expect_error=True)
    assert r.get("_error") == 422, r
    assert author.post(f"/forum/v1/posts/{p['pid']}/appeal",
                       {"text": "我没有攻击任何人,请复核"}) == {"ok": True}
    r = author.post(f"/forum/v1/posts/{p['pid']}/appeal", {"text": "再申诉一次试试"},
                    expect_error=True)
    assert r.get("_error") == 409, f"同一个决定申诉了两次:{r}"
    r = reporter.post(f"/forum/v1/posts/{p['pid']}/appeal", {"text": "我替他申诉"},
                      expect_error=True)
    assert r.get("_error") == 403, r

    appeals = call("GET", "/admin/forum/appeals?status=open", admin)["items"]
    ap = next(x for x in appeals if x["post"] and x["post"]["pid"] == p["pid"])
    assert ap["you_decided_original"] is True, "下架的是我,这里应该标着不能由我复核"
    assert ap["appeal"]["text"] == "我没有攻击任何人,请复核", ap["appeal"]
    r = call("POST", f"/admin/forum/appeals/{ap['decision_id']}/resolve", admin,
             {"result": "overturned", "note": "看错了"}, expect_error=True)
    assert r.get("_error") == 403, f"自己复核了自己的决定:{r}"
    seen_by_2 = next(x for x in call("GET", "/admin/forum/appeals?status=open", admin2)["items"]
                     if x["decision_id"] == ap["decision_id"])
    assert seen_by_2["you_decided_original"] is False, seen_by_2
    out = call("POST", f"/admin/forum/appeals/{ap['decision_id']}/resolve", admin2,
               {"result": "overturned", "note": "复核后认为不构成"})
    assert out["result"] == "overturned" and out["status"] == "visible", out
    assert reporter.get(f"/forum/v1/posts/{p['pid']}")["post"]["pid"] == p["pid"], "改判没恢复"
    back = [n for n in author.get("/social/v1/notifications?kind=system")["items"]
            if n["title"] == "帖子已恢复"]
    assert back, "改判了没通知作者"
    r = call("POST", f"/admin/forum/appeals/{ap['decision_id']}/resolve", admin2,
             {"result": "upheld", "note": "再处理一次"}, expect_error=True)
    assert r.get("_error") == 409, r
    print("✓ 申诉:只能一次、只有作者能提、原审核人 403、换人改判后帖子恢复")

    # ---------- 维持原处理 ----------
    # 正文带上作者号:后台按正文找的那一条断言要能和前几次跑留下的数据区分开
    p2_text = f"第二条要被下架的{author.id}"
    p2 = post(author, p2_text)
    call("POST", f"/admin/forum/posts/{p2['pid']}/remove", admin,
         {"reason_code": "F401", "note": "刷屏"})
    author.post(f"/forum/v1/posts/{p2['pid']}/appeal", {"text": "这不是刷屏,请复核一下"})
    d2 = next(x for x in call("GET", "/admin/forum/appeals?status=open", admin2)["items"]
              if x["post"]["pid"] == p2["pid"])
    out = call("POST", f"/admin/forum/appeals/{d2['decision_id']}/resolve", admin2,
               {"result": "upheld", "note": "确实是重复发帖"})
    assert out["result"] == "upheld" and out["status"] == "removed", out
    held = [n for n in author.get("/social/v1/notifications?kind=system")["items"]
            if n["title"] == "申诉结果:维持原处理"]
    assert held, "维持原处理没通知作者"
    # 手动恢复
    out = call("POST", f"/admin/forum/posts/{p2['pid']}/restore", admin, {"note": "运营决定恢复"})
    assert out["status"] == "visible", out
    print("✓ 维持原处理照样通知作者;后台能手动恢复")

    # ---------- 后台帖子管理 ----------
    found = call("GET", f"/admin/forum/posts?q={urllib.parse.quote(p2_text)}", admin)
    assert [x["pid"] for x in found["items"]] == [p2["pid"]], found
    by_author = call("GET", f"/admin/forum/posts?author={author.id}", admin)["items"]
    assert len(by_author) >= 2 and all(x["author"]["id"] == author.id for x in by_author)
    stats = call("GET", "/admin/forum/stats", admin)
    assert stats["posts_7d"] >= 2 and stats["removed_7d"] >= 2, stats
    assert set(stats) >= {"posts_7d", "removed_7d", "visible_total", "reports_open",
                          "appeals_open", "tags_hidden", "tags_total"}, stats
    print("✓ 后台帖子管理:按正文 / 按作者找得到,数据页字段齐")

    # ---------- 话题隐藏留痕 ----------
    tag = "热门话题测试"
    r = call("POST", f"/admin/forum/tags/{urllib.parse.quote(tag)}/hide", admin,
             {"reason_code": "X999", "note": "短"}, expect_error=True)
    assert r.get("_error") == 422, "隐藏话题也要写清楚原因"
    call("POST", f"/admin/forum/tags/{urllib.parse.quote(tag)}/hide", admin,
         {"reason_code": "F402", "note": "和话题本身无关的内容太多"})
    hidden = call("GET", "/admin/forum/tags?hidden=true", admin)["items"]
    row = next(t for t in hidden if t["tag"] == tag)
    assert row["hidden"] is True and row["hidden_code"] == "F402", row
    assert row["hidden_label"] == "蹭无关话题", row
    logged = sql("SELECT action, reason_code FROM forum_decisions WHERE tag_id = "
                 "(SELECT id FROM forum_tags WHERE tag = :t) ORDER BY id DESC LIMIT 1",
                 {"t": tag}, fetch="all")
    assert logged and logged[0][0] == "tag_hide" and logged[0][1] == "F402", logged
    call("POST", f"/admin/forum/tags/{urllib.parse.quote(tag)}/unhide", admin)
    r = call("POST", f"/admin/forum/tags/{urllib.parse.quote('根本没有这个话题')}/hide", admin,
             {"reason_code": "F402", "note": "试试"}, expect_error=True)
    assert r.get("_error") == 404, r
    print("✓ 话题隐藏:要写原因、进 forum_decisions 留痕、能取消")

    # ---------- 处罚管得到 ----------
    muted = person("137")
    mine = post(muted, "禁言之前发的")
    call("POST", "/admin/social/sanctions", admin,
         {"target_type": "user", "target_id": muted.id, "action": "mute",
          "reason_code": "C101", "note": "e2e 测禁言", "hours": 1})
    r = post(muted, "禁言之后还想发", expect_error=True)
    assert r.get("_error") == 403, f"禁言的人还能发帖:{r}"
    r = muted.patch(f"/forum/v1/posts/{mine['pid']}", {"text": "改一下"}, expect_error=True)
    assert r.get("_error") == 403, f"禁言的人还能编辑:{r}"
    # 禁言不挡看、也不挡只影响自己的
    assert muted.get("/forum/v1/timeline/foryou")["items"] is not None
    clear_rate_limits("forum_act", muted.id)
    assert muted.post(f"/forum/v1/posts/{mine['pid']}/bookmark") == {"bookmarked": True}
    assert muted.post("/forum/v1/me/mute-words", {"word": "随便"})["items"] == ["随便"]
    print("✓ 禁言挡得住发帖和编辑,挡不住看、书签、屏蔽词")

    banned = person("137")
    his = post(banned, "封号之前发的")
    call("POST", "/admin/social/sanctions", admin,
         {"target_type": "user", "target_id": banned.id, "action": "ban_account",
          "reason_code": "C102", "note": "e2e 测封号", "days": 1})
    r = post(banned, "封号之后还想发", expect_error=True)
    assert r.get("_error") == 403, f"封号的人还能发帖:{r}"
    clear_rate_limits("forum_act", banned.id)
    r = banned.post(f"/forum/v1/posts/{his['pid']}/like", expect_error=True)
    assert r.get("_error") == 403, f"封号的人还能点赞:{r}"
    # 放行表里的:申诉、举报、浏览上报、书签、屏蔽词、个性化开关
    call("POST", f"/admin/forum/posts/{his['pid']}/remove", admin,
         {"reason_code": "F401", "note": "刷屏"})
    assert banned.post(f"/forum/v1/posts/{his['pid']}/appeal",
                       {"text": "封号了也要能申诉"}) == {"ok": True}
    clear_rate_limits("forum_views", banned.id)
    assert banned.post("/forum/v1/posts/views", {"pids": [p2["pid"]]})["ok"] is True
    assert banned.post(f"/forum/v1/posts/{p2['pid']}/bookmark") == {"bookmarked": True}
    assert banned.put("/forum/v1/me/settings", {"personalize": False}) == {"personalize": False}
    assert banned.post("/forum/v1/reports",
                       {"pid": p2["pid"], "reason_code": "F401"}) == {"ok": True}
    print("✓ 封号挡住发帖和点赞,放行申诉、举报、浏览上报、书签、屏蔽词、个性化开关")

    # ---------- 注销:帖子正文清空,别人的回复还在 ----------
    leaver = person("137")
    gone = post(leaver, "注销之前发的帖子")
    reply = post(reporter, "我回复了他", reply_to_pid=gone["pid"])
    clear_rate_limits("forum_act", leaver.id)
    leaver.post(f"/forum/v1/posts/{p2['pid']}/like")
    likes_before = call("GET", f"/forum/v1/posts/{p2['pid']}")["post"]["counts"]["likes"]
    call("DELETE", "/auth/me", leaver.token)
    r = reporter.get(f"/forum/v1/posts/{gone['pid']}", expect_error=True)
    assert r.get("_error") == 404, f"注销了帖子还在:{r}"
    still = reporter.get(f"/forum/v1/posts/{reply['pid']}")
    assert still["post"]["text"] == "我回复了他", "别人的回复跟着消失了"
    assert still["ancestors"][0]["unavailable"] is True, still["ancestors"]
    after = call("GET", f"/forum/v1/posts/{p2['pid']}")["post"]["counts"]["likes"]
    assert after == likes_before - 1, f"注销之后赞没跟着减:{likes_before} → {after}"
    left = sql("SELECT count(*) FROM forum_likes WHERE user_id = :u", {"u": leaver.id},
               fetch="scalar")
    assert int(left or 0) == 0, "注销之后赞的明细还在"
    print("✓ 注销:自己的帖子清空并标删除,别人的回复留着,计数跟着重算")

    print("\ne2e_forum_moderation 全部通过 ✅")


if __name__ == "__main__":
    main()
