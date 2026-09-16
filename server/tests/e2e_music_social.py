"""音乐的互动 e2e(DEV-PROMPTS-41 §5.8、§5.10、§8.2)。

喜欢 / 取消 → 我喜欢的音乐;歌单增删改查、去重、排序、收藏别人的公开歌单、私密歌单外人看不到;
收藏专辑;评论、楼中楼、热评、赞、@ 超级赞号;互动消息里带 track / release;
关注音乐人走 /social/v1(全站一张表),音乐人主页的 fans 跟着变;搜索;举报(版权投诉要联系方式);
限流(评论 5 秒一条)。

跑法:SUPERZ_API=http://127.0.0.1:8110 DATABASE_URL=… REDIS_URL=… python -m tests.e2e_music_social
"""
from tests.chat_util import set_username
from tests.music_util import (admin_token, artist, call, clear_rate_limits, person,
                              publish_release, rand_name)


def main():
    a, art = artist()
    rel = publish_release(a, tracks=3, genre="rock")
    tids = [t["tid"] for t in rel["tracks"]]
    tid = tids[0]
    u, v = person(), person()
    print(f"  作品 {rel['rid']},歌 {tids}")

    # ---- 喜欢 ----
    liked = u.post(f"/music/v1/tracks/{tid}/like")
    assert liked == {"liked": True, "likes": 1}, liked
    assert u.post(f"/music/v1/tracks/{tid}/like")["likes"] == 1, "重复点赞不重复计数"
    assert u.get(f"/music/v1/tracks/{tid}")["liked"] is True
    mine = u.get("/music/v1/me/likes")
    assert [x["tid"] for x in mine["items"]] == [tid], mine
    assert u.delete(f"/music/v1/tracks/{tid}/like") == {"liked": False, "likes": 0}
    assert u.get("/music/v1/me/likes")["items"] == []
    u.post(f"/music/v1/tracks/{tid}/like")
    print("  ✓ 喜欢 / 取消 / 我喜欢的音乐")

    # ---- 歌单 ----
    # 上面连着点了好几次赞:「每人每秒 5 次」(§5.10)的桶还满着,清掉再往下走 ——
    # 这条用例测的不是限流,专测限流的在下面评论那一段
    clear_rate_limits("music_act", u.id)
    pl = u.post("/music/v1/playlists", {"title": rand_name("我的歌单"), "description": "e2e",
                                        "tags": ["华语", "华语"], "is_public": True})
    pid = pl["pid"]
    assert pid.startswith("mp") and pl["tags"] == ["华语"], pl
    add = u.post(f"/music/v1/playlists/{pid}/tracks", {"tids": tids + [tids[0]]})
    assert add == {"added": 3, "track_count": 3}, f"加歌要去重:{add}"
    assert u.post(f"/music/v1/playlists/{pid}/tracks", {"tids": [tids[0]]})["added"] == 0
    detail = u.get(f"/music/v1/playlists/{pid}")
    assert [x["tid"] for x in detail["tracks"]] == tids, detail
    order = list(reversed(tids))
    assert u.put(f"/music/v1/playlists/{pid}/order", {"tids": order})["ok"] is True
    assert [x["tid"] for x in u.get(f"/music/v1/playlists/{pid}")["tracks"]] == order
    bad = u.put(f"/music/v1/playlists/{pid}/order", {"tids": order[:2]}, expect_error=True)
    assert bad.get("_error") == 422, f"新顺序必须是全部歌曲:{bad}"
    rm = u.delete(f"/music/v1/playlists/{pid}/tracks/{tids[1]}")
    assert rm["track_count"] == 2, rm
    u.patch(f"/music/v1/playlists/{pid}", {"title": "改过的歌单"})
    assert u.get(f"/music/v1/playlists/{pid}")["title"] == "改过的歌单"
    print("  ✓ 歌单增删改、去重、排序")

    # ---- 收藏别人的歌单;私密的外人看不到 ----
    clear_rate_limits("music_act", u.id)
    col = v.post(f"/music/v1/playlists/{pid}/collect")
    assert col == {"collected": True, "collects": 1}, col
    assert any(x["pid"] == pid for x in v.get("/music/v1/me/playlists")["collected"])
    own = u.post(f"/music/v1/playlists/{pid}/collect", expect_error=True)
    assert own.get("_error") == 422, f"自己的歌单不用收藏:{own}"
    u.patch(f"/music/v1/playlists/{pid}", {"is_public": False})
    assert v.get(f"/music/v1/playlists/{pid}", expect_error=True).get("_error") == 404, \
        "私密歌单外人看不到"
    assert u.get(f"/music/v1/playlists/{pid}")["pid"] == pid, "主人自己看得到"
    u.patch(f"/music/v1/playlists/{pid}", {"is_public": True})
    assert v.delete(f"/music/v1/playlists/{pid}/collect")["collects"] == 0
    print("  ✓ 收藏歌单、私密歌单只有主人看得到")

    # ---- 收藏专辑 ----
    clear_rate_limits("music_act", v.id)
    c = v.post(f"/music/v1/releases/{rel['rid']}/collect")
    assert c == {"collected": True, "collects": 1}, c
    assert v.get(f"/music/v1/releases/{rel['rid']}")["collected"] is True
    assert any(x["rid"] == rel["rid"]
               for x in v.get("/music/v1/me/playlists")["collected_releases"])
    assert v.delete(f"/music/v1/releases/{rel['rid']}/collect")["collects"] == 0

    # ---- 评论:一级、楼中楼、热评、赞 ----
    clear_rate_limits("music_act", v.id)
    name = set_username(v, "musicfan")
    c1 = u.post(f"/music/v1/tracks/{tid}/comments", {"text": "这首好听"})
    assert c1["text"] == "这首好听" and c1["mine"] is True, c1
    clear_rate_limits("music_comment", u.id)
    c2 = u.post(f"/music/v1/tracks/{tid}/comments",
                {"text": f"@{name} 你听听这首", "parent_id": c1["id"]})
    assert [m["username"] for m in c2["mentions"]] == [name.lower()], c2
    lst = v.get(f"/music/v1/tracks/{tid}/comments")
    assert lst["total"] == 2 and lst["items"][0]["reply_count"] == 1, lst
    assert [x["id"] for x in lst["items"][0]["replies"]] == [c2["id"]], lst["items"][0]
    assert lst["hot"] == [], "一条赞都没有的不算热评"
    liked = v.post(f"/music/v1/comments/{c1['id']}/like")
    assert liked == {"liked": True, "likes": 1}, liked
    assert [x["id"] for x in v.get(f"/music/v1/tracks/{tid}/comments")["hot"]] == [c1["id"]]
    assert v.delete(f"/music/v1/comments/{c1['id']}/like")["likes"] == 0
    reps = v.get(f"/music/v1/comments/{c1['id']}/replies")
    assert [x["id"] for x in reps["items"]] == [c2["id"]], reps
    print("  ✓ 评论、楼中楼、热评、赞、@")

    # ---- 互动消息:@ 到的人和歌的作者都收到,带 track ----
    at = v.get("/social/v1/notifications?kind=at")
    hit = next((x for x in at["items"] if x.get("track") and x["track"]["tid"] == tid), None)
    assert hit is not None, f"@ 我的要带这首歌:{at['items'][:2]}"
    assert "歌曲评论里 @" in hit["title"], hit["title"]
    reply = a.get("/social/v1/notifications?kind=reply")
    hit2 = next((x for x in reply["items"] if x.get("track") and x["track"]["tid"] == tid), None)
    assert hit2 is not None and "评论了你的歌" in hit2["title"], reply["items"][:2]
    assert hit2["track"]["cover"].startswith("/img/"), hit2["track"]
    sys_msgs = a.get("/social/v1/notifications?kind=system")
    hit3 = next((x for x in sys_msgs["items"]
                 if x.get("release") and x["release"]["rid"] == rel["rid"]), None)
    assert hit3 is not None and "审核通过" in hit3["title"], sys_msgs["items"][:2]
    print("  ✓ 互动消息带歌、带作品(§5.8)")

    # ---- 删评论:作者本人、歌的作者 ----
    other = person()
    c3 = other.post(f"/music/v1/tracks/{tid}/comments", {"text": "路过留个言"})
    nope = u.delete(f"/music/v1/comments/{c3['id']}", expect_error=True)
    assert nope.get("_error") == 403, f"别人的评论删不了:{nope}"
    assert a.delete(f"/music/v1/comments/{c3['id']}")["ok"] is True, "歌的作者能删自己歌下的"
    assert all(x["id"] != c3["id"] for x in v.get(f"/music/v1/tracks/{tid}/comments")["items"])
    clear_rate_limits("music_comment", other.id)
    c4 = other.post(f"/music/v1/tracks/{tid}/comments", {"text": "再来一条"})
    assert other.delete(f"/music/v1/comments/{c4['id']}")["ok"] is True

    # ---- 评论限流:5 秒一条 ----
    clear_rate_limits("music_comment", u.id)
    u.post(f"/music/v1/tracks/{tid}/comments", {"text": "第一条"}, retry_429=False)
    fast = u.post(f"/music/v1/tracks/{tid}/comments", {"text": "紧接着第二条"},
                  expect_error=True, retry_429=False)
    assert fast.get("_error") == 429, f"5 秒一条(§5.10):{fast}"
    print("  ✓ 删评论的权限、评论限流")

    # ---- 关注音乐人:走全站的 /social/v1(#377),主页 fans 跟着变 ----
    before = v.get(f"/music/v1/artists/{art['aid']}")
    assert before["followed"] is False, before
    f = v.post(f"/social/v1/users/{art['user_id']}/follow")
    assert f["followed"] is True, f
    after = v.get(f"/music/v1/artists/{art['aid']}")
    assert after["followed"] is True and after["fans"] == before["fans"] + 1, after
    assert after["track_count"] == 3 and len(after["hot_tracks"]) == 3, after
    assert any(x["rid"] == rel["rid"] for x in after["releases"]), after
    page = v.get(f"/music/v1/artists/{art['aid']}/tracks")
    assert len(page["items"]) == 3 and page["has_more"] is False, page
    print("  ✓ 关注全站一张表,音乐人主页读得到")

    # ---- 搜索 ----
    from urllib.parse import quote
    q = quote(rel["tracks"][0]["title"][:6])
    found = v.get(f"/music/v1/search?q={q}&type=track")
    assert any(x["tid"] == tid for x in found["items"]), found
    arts = v.get(f"/music/v1/search?q={quote(art['name'][:6])}&type=artist")
    assert any(x["aid"] == art["aid"] for x in arts["items"]), arts
    rels = v.get(f"/music/v1/search?q={quote(rel['title'][:6])}&type=release")
    assert any(x["rid"] == rel["rid"] for x in rels["items"]), rels
    pls = v.get(f"/music/v1/search?q={quote('改过的歌单')}&type=playlist")
    assert any(x["pid"] == pid for x in pls["items"]), pls
    print("  ✓ 四种搜索")

    # ---- 举报:版权投诉必须留联系方式(M1)----
    no_contact = v.post("/music/v1/reports", {"target_type": "track", "target_id": tid,
                                              "reason_code": "M301", "note": "这是我的歌"},
                        expect_error=True)
    assert no_contact.get("_error") == 422 and "联系方式" in no_contact["detail"], no_contact
    ok = v.post("/music/v1/reports", {"target_type": "track", "target_id": tid,
                                      "reason_code": "M301", "note": "这是我的歌",
                                      "contact": "copyright@example.com"})
    assert ok["ok"] is True, ok
    dup = v.post("/music/v1/reports", {"target_type": "track", "target_id": tid,
                                       "reason_code": "M301", "contact": "copyright@example.com"})
    assert dup["id"] == ok["id"], "同一个人同一个对象 7 天内只记一次"
    admin_view = call("GET", "/admin/music/reports?status=open", admin_token())["items"]
    row = next((x for x in admin_view if x["id"] == ok["id"]), None)
    assert row is not None and row["contact"] == "copyright@example.com", row
    assert row["is_copyright"] is True and "reporter_id" not in row, "举报人对被举报方永远匿名"
    print("PASS e2e_music_social")


if __name__ == "__main__":
    main()
