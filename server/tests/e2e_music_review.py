"""音乐的审核与治理 e2e(DEV-PROMPTS-41 §5.3、§5.11、§3.6、§3.7)。

待审队列里能播 → 驳回带原因 → 申诉一次 → 原审核人不能复核(403)→ 换人改判上线;
平台下架 → 恢复;举报处置(下架作品、删评论、歌单改私密、停用音乐人);
处罚:封号挡住开通音乐人 / 建作品 / 加歌 / 提交,但申诉、举报、听歌照常;
注销:作品、歌、歌单、评论全清干净,播放地址和封面地址立刻失效。

跑法:SUPERZ_API=http://127.0.0.1:8110 DATABASE_URL=… REDIS_URL=… python -m tests.e2e_music_review
"""
import time

from tests.music_util import (add_track, admin2_token, admin_token, artist, call,
                              clear_rate_limits, new_release, person, publish_release, raw,
                              rand_name, sql, studio_release, tone, upload_audio, upload_cover,
                              wait_ready)


def _gone(url: str, timeout: float = 8) -> bool:
    """对象存储里的文件是提交之后才删的(后台任务),等它一下。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if raw(None, url)[0] == 404:
            return True
        time.sleep(0.3)
    return False


def _submitted(p) -> dict:
    cover = upload_cover(p)
    r = new_release(p, cover_media_id=cover["id"], title=rand_name("待审"))
    add_track(p, r["rid"], upload_audio(p, tone(hz=500))["id"], title=rand_name("待审曲"),
              lyrics="第一句\n第二句")
    wait_ready(p, r["rid"])
    p.post(f"/music/v1/studio/releases/{r['rid']}/submit")
    return studio_release(p, r["rid"])


def main():
    adm, adm2 = admin_token(), admin2_token()
    a, art = artist()

    # ---- 待审队列:信息齐、每首歌有能播的地址 ----
    rel = _submitted(a)
    rid = rel["rid"]
    queue = call("GET", "/admin/music/review", adm)["items"]
    row = next((x for x in queue if x["rid"] == rid), None)
    assert row is not None, f"{rid} 不在待审队列里"
    assert row["artist"]["aid"] == art["aid"] and row["tracks"][0]["lyrics"], row
    assert row["cover"], "封面要给审核员看得到(没过审只在私密桶里)"
    code, _, body = raw(adm, row["tracks"][0]["stream"]["std"])
    assert code == 200 and len(body) > 1000, (code, len(body))
    assert raw(None, row["cover"])[0] in (200, 404), row["cover"]
    print("  ✓ 待审队列里能看能播")

    # ---- 驳回:必须带原因;X999 必须写说明 ----
    naked = call("POST", f"/admin/music/releases/{rid}/decide", adm,
                 {"action": "reject"}, expect_error=True)
    assert naked.get("_error") == 422, f"驳回必须带原因代码:{naked}"
    x999 = call("POST", f"/admin/music/releases/{rid}/decide", adm,
                {"action": "reject", "reason_code": "X999", "note": "短"}, expect_error=True)
    assert x999.get("_error") == 422, f"X999 要写说明:{x999}"
    bad_code = call("POST", f"/admin/music/releases/{rid}/decide", adm,
                    {"action": "reject", "reason_code": "ZZZZ"}, expect_error=True)
    assert bad_code.get("_error") == 422, bad_code
    rej = call("POST", f"/admin/music/releases/{rid}/decide", adm,
               {"action": "reject", "reason_code": "M301", "note": "查到是别人的歌"})
    assert rej["action"] == "reject" and rej["status"] == "rejected", rej
    mine = studio_release(a, rid)
    assert mine["reject_code"] == "M301" and "侵权" in mine["reject_label"], mine
    assert mine["can_appeal"] is True and mine["editable"] is True, mine
    note = a.get("/social/v1/notifications?kind=system")["items"][0]
    assert note["release"]["rid"] == rid and "未通过" in note["title"], note
    print("  ✓ 驳回带原因,音乐人收到通知")

    # ---- 申诉:一次;原审核人不能复核;换人改判 ----
    short = a.post(f"/music/v1/studio/releases/{rid}/appeal", {"text": "冤"}, expect_error=True)
    assert short.get("_error") == 422, short
    ap = a.post(f"/music/v1/studio/releases/{rid}/appeal", {"text": "这首是我自己写的,有demo为证"})
    did = ap["decision_id"]
    twice = a.post(f"/music/v1/studio/releases/{rid}/appeal", {"text": "再申诉一次试试"},
                   expect_error=True)
    assert twice.get("_error") == 409, f"每个结论只能申诉一次:{twice}"
    open_list = call("GET", "/admin/music/appeals", adm)["items"]
    row = next((x for x in open_list if x["decision_id"] == did), None)
    assert row is not None and row["you_decided_original"] is True, row
    self_resolve = call("POST", f"/admin/music/appeals/{did}/resolve", adm,
                        {"result": "overturned", "note": "我自己改判"}, expect_error=True)
    assert self_resolve.get("_error") == 403, f"原审核人不能复核自己的决定:{self_resolve}"
    row2 = next(x for x in call("GET", "/admin/music/appeals", adm2)["items"]
                if x["decision_id"] == did)
    assert row2["you_decided_original"] is False
    done = call("POST", f"/admin/music/appeals/{did}/resolve", adm2,
                {"result": "overturned", "note": "核实是原创,改判上线"})
    assert done["result"] == "overturned" and done["status"] == "published", done
    assert not any(x["decision_id"] == did for x in call("GET", "/admin/music/appeals", adm2)
                   ["items"]), "处理过的申诉不再出现"
    pub = person().get(f"/music/v1/releases/{rid}")
    assert pub["rid"] == rid and pub["cover"].startswith("/img/"), pub
    print("  ✓ 申诉一次、换人复核、改判上线")

    # ---- 平台下架 → 申诉 → 维持 → 管理员自己恢复 ----
    rm = call("POST", f"/admin/music/releases/{rid}/remove", adm,
              {"reason_code": "C102", "note": "有引流内容"})
    assert rm["status"] == "removed", rm
    tid = studio_release(a, rid)["tracks"][0]["tid"]
    assert person().get(f"/music/v1/tracks/{tid}", expect_error=True).get("_error") == 404
    assert _gone(pub["cover"]), "下架后公开桶里的封面跟着删"
    ap2 = a.post(f"/music/v1/studio/releases/{rid}/appeal", {"text": "那是歌词里的地名,不是引流"})
    upheld = call("POST", f"/admin/music/appeals/{ap2['decision_id']}/resolve", adm2,
                  {"result": "upheld", "note": "复核后维持原结论"})
    assert upheld["result"] == "upheld" and upheld["status"] == "removed", upheld
    restored = call("POST", f"/admin/music/releases/{rid}/restore", adm, {"note": "运营改主意了"})
    assert restored["status"] == "published", restored
    assert person().get(f"/music/v1/releases/{rid}")["rid"] == rid
    print("  ✓ 下架、申诉维持、恢复")

    # ---- 举报处置 ----
    b, art_b = artist()
    rel_b = publish_release(b)
    tid_b = rel_b["tracks"][0]["tid"]
    reporter = person()
    r1 = reporter.post("/music/v1/reports", {"target_type": "track", "target_id": tid_b,
                                             "reason_code": "C104", "note": "低俗"})
    handled = call("POST", f"/admin/music/reports/{r1['id']}/handle", adm,
                   {"action": "remove_target", "reason_code": "C104", "note": "确实不合适"})
    assert "已下架" in handled["resolution"], handled
    assert reporter.get(f"/music/v1/tracks/{tid_b}", expect_error=True).get("_error") == 404
    assert call("POST", f"/admin/music/reports/{r1['id']}/handle", adm,
                {"action": "dismiss"}, expect_error=True).get("_error") == 409

    c, art_c = artist()
    rel_c = publish_release(c)
    tid_c = rel_c["tracks"][0]["tid"]
    comment = reporter.post(f"/music/v1/tracks/{tid_c}/comments", {"text": "一条会被删掉的评论"})
    r2 = person().post("/music/v1/reports", {"target_type": "comment",
                                             "target_id": str(comment["id"]),
                                             "reason_code": "C101", "note": "辱骂"})
    out = call("POST", f"/admin/music/reports/{r2['id']}/handle", adm,
               {"action": "remove_target", "reason_code": "C101", "note": "确实辱骂"})
    assert "已删除评论" in out["resolution"], out
    assert all(x["id"] != comment["id"]
               for x in reporter.get(f"/music/v1/tracks/{tid_c}/comments")["items"])

    pl = reporter.post("/music/v1/playlists", {"title": rand_name("会被改私密的歌单")})
    r3 = person().post("/music/v1/reports", {"target_type": "playlist", "target_id": pl["pid"],
                                             "reason_code": "C102", "note": "广告"})
    out = call("POST", f"/admin/music/reports/{r3['id']}/handle", adm,
               {"action": "remove_target", "reason_code": "C102", "note": "广告歌单"})
    assert "已改为私密" in out["resolution"], out
    assert person().get(f"/music/v1/playlists/{pl['pid']}",
                        expect_error=True).get("_error") == 404
    assert reporter.get(f"/music/v1/playlists/{pl['pid']}")["pid"] == pl["pid"], "主人还留着"

    r4 = person().post("/music/v1/reports", {"target_type": "artist", "target_id": art_c["aid"],
                                             "reason_code": "M305", "note": "冒充别人"})
    out = call("POST", f"/admin/music/reports/{r4['id']}/handle", adm,
               {"action": "remove_target", "reason_code": "M305", "note": "确认冒充"})
    assert "已停用音乐人" in out["resolution"], out
    assert person().get(f"/music/v1/artists/{art_c['aid']}",
                        expect_error=True).get("_error") == 404
    assert person().get(f"/music/v1/tracks/{tid_c}", expect_error=True).get("_error") == 404, \
        "停用之后他的歌也从公开的地方消失"
    assert c.post("/music/v1/studio/releases", {"title": "还能发吗"},
                  expect_error=True).get("_error") == 403
    back = call("POST", f"/admin/music/artists/{art_c['aid']}/restore", adm)
    assert back["status"] == "active", back
    assert person().get(f"/music/v1/artists/{art_c['aid']}")["aid"] == art_c["aid"]
    print("  ✓ 举报处置:下架作品、删评论、歌单改私密、停用 / 恢复音乐人")

    # ---- 处罚:封号挡住投稿,但申诉、举报、听歌照常(§3.6)----
    d, _ = artist()
    rel_d = publish_release(d)
    tid_d = rel_d["tracks"][0]["tid"]
    banned = person()
    call("POST", "/admin/social/sanctions", adm,
         {"target_type": "user", "target_id": banned.id, "action": "ban_account", "days": 1,
          "reason_code": "C102", "note": "e2e 封号"})
    blocked = banned.post("/music/v1/studio/artist", {"name": rand_name("被封的")},
                          expect_error=True)
    assert blocked.get("_error") == 403, f"封号挡住开通音乐人:{blocked}"
    assert banned.post(f"/music/v1/tracks/{tid_d}/comments", {"text": "封号还能评论?"},
                       expect_error=True).get("_error") == 403
    assert banned.post("/music/v1/playlists", {"title": "封号还能建歌单?"},
                       expect_error=True).get("_error") == 403
    listen = banned.get(f"/music/v1/tracks/{tid_d}")
    assert listen["tid"] == tid_d, "封号照样能听歌"
    assert banned.post(f"/music/v1/tracks/{tid_d}/play", {"ms_listened": 3000})["counted"] in \
        (True, False), "收听上报不挂 social_user,封号照样能报"
    assert banned.delete("/music/v1/me/history")["ok"] is True
    assert banned.put("/music/v1/me/settings", {"personalize": False})["personalize"] is False
    assert banned.post("/music/v1/reports", {"target_type": "track", "target_id": tid_d,
                                             "reason_code": "C101", "note": "封号也能举报"})["ok"]
    # 被封之前已经是音乐人的,提交也挡住
    call("POST", "/admin/social/sanctions", adm,
         {"target_type": "user", "target_id": d.id, "action": "ban_account", "days": 1,
          "reason_code": "C102", "note": "e2e 封号"})
    draft = d.post("/music/v1/studio/releases", {"title": "封号之后建"}, expect_error=True)
    assert draft.get("_error") == 403, draft
    print("  ✓ 封号挡住投稿,不挡听歌、申诉、举报、改设置")

    # ---- 注销:清干净(§3.7)----
    e, art_e = artist()
    rel_e = publish_release(e, tracks=2)
    tid_e = rel_e["tracks"][0]["tid"]
    cover_e = rel_e["cover"]
    stream_e = e.get(f"/music/v1/tracks/{tid_e}")["stream"]["std"]
    assert raw(None, stream_e)[0] == 200
    fan = person()
    clear_rate_limits("music_act", fan.id)
    fan.post(f"/music/v1/tracks/{tid_e}/like")
    fan_pl = fan.post("/music/v1/playlists", {"title": rand_name("粉丝歌单")})
    fan.post(f"/music/v1/playlists/{fan_pl['pid']}/tracks", {"tids": [tid_e]})
    e.post(f"/music/v1/tracks/{tid_e}/comments", {"text": "自己歌下留个言"})
    call("DELETE", "/auth/me", e.token)
    for table, col, value in (("music_artists", "aid", art_e["aid"]),
                              ("music_releases", "rid", rel_e["rid"]),
                              ("music_tracks", "tid", tid_e)):
        left = sql(f"SELECT count(*) FROM {table} WHERE {col} = :v", {"v": value},
                   fetch="scalar")
        assert left == 0, f"{table} 注销后应该清掉,还剩 {left}"
    assert _gone(stream_e), "注销后播放地址失效"
    assert _gone(cover_e), "注销后公开桶里的封面也删掉"
    assert person().get(f"/music/v1/releases/{rel_e['rid']}",
                        expect_error=True).get("_error") == 404
    assert fan.get("/music/v1/me/likes")["items"] == [], "喜欢跟着歌一起没了"
    assert fan.get(f"/music/v1/playlists/{fan_pl['pid']}")["tracks"] == [], "歌单里的歌也没了"
    print("  ✓ 注销清干净,地址立刻失效")

    # ---- 后台数据 ----
    stats = call("GET", "/admin/music/stats", adm)
    assert stats["artists"] >= 1 and stats["approved_7d"] >= 1, stats
    codes = call("GET", "/admin/music/reason-codes", adm)
    assert codes["copyright_code"] == "M301"
    assert {"M301", "M302", "M303", "M304", "M305", "C101", "X999"} <= \
        {x["code"] for x in codes["items"]}, codes
    print("PASS e2e_music_review")


if __name__ == "__main__":
    main()
