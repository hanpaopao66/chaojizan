"""音乐人中心全流程 e2e(DEV-PROMPTS-41 #378,§5.3、M1–M4)。

开通音乐人(不要求实名)→ 上传音频(整块 / 分片,wav / flac)→ 建作品、挂封面、加歌 →
转码出 std / hq 两档 → 提交审核 → 过审上线;
没歌 / 没封面 / 没勾声明不让提交;已发布的作品不能改;撤回提交;下架后再交;
太短的音频转码失败并写原因;开关关着一律 503;艺名唯一、保留词、长度。

跑法:SUPERZ_API=http://127.0.0.1:8110 DATABASE_URL=… REDIS_URL=… python -m tests.e2e_music_studio
"""
from tests.music_util import (add_track, admin_token, approve, artist, call, chunked_audio,
                              new_release, person, rand_name, raw, set_flag, studio_release,
                              tone, upload_audio, upload_cover, wait_ready)


def main():
    # ---- 开通音乐人:不要求实名(M2、§3.2),一个账号一个身份 ----
    p = person()
    assert p.get("/music/v1/studio/me")["artist"] is None
    name = rand_name("音乐人")
    _, a = artist(p, name)
    assert a["name"] == name and len(a["aid"]) == 12
    print(f"  ✓ 开通音乐人 {a['aid']}(全程没实名)")

    dup = p.post("/music/v1/studio/artist", {"name": rand_name("再来一个")}, expect_error=True)
    assert dup.get("_error") == 409, dup
    other = person()
    same = other.post("/music/v1/studio/artist", {"name": name}, expect_error=True)
    assert same.get("_error") == 409, f"艺名要全站唯一:{same}"
    spaced = other.post("/music/v1/studio/artist", {"name": " ".join(name)}, expect_error=True)
    assert spaced.get("_error") == 409, f"加空格也是同一个名字:{spaced}"
    for bad, why in ((" 超级赞官方 ", "保留词"), ("a", "太短"), ("超" * 31, "太长")):
        r = other.post("/music/v1/studio/artist", {"name": bad}, expect_error=True)
        assert r.get("_error") == 422, f"{why} 应该 422:{r}"
    print("  ✓ 艺名唯一、保留词、长度都拦住了")

    # ---- 上传:整块 wav、分片 flac(sniff 认 fLaC) ----
    src_a = upload_audio(p, tone(hz=440), "a.wav")
    assert src_a["kind"] == "audio_source" and src_a["status"] == "ready", src_a
    src_b = chunked_audio(p, tone(hz=660, fmt="flac"), "b.flac")
    assert src_b["kind"] == "audio_source", f"FLAC 要被认出来:{src_b}"
    outsider = person()
    assert raw(outsider.token, src_a["url"].split("?")[0])[0] == 404, \
        "原始音频只有作者和审核员能下"
    print("  ✓ 整块 wav、分片 flac 都收下了,别人下不到原文件")

    # ---- 建作品、加歌 ----
    cover = upload_cover(p)
    r = new_release(p, title=rand_name("首张专辑"), kind="ep", genre="folk",
                    language="mandarin")
    rid = r["rid"]
    assert rid.startswith("mr") and r["status"] == "draft", r
    no_cover = p.post(f"/music/v1/studio/releases/{rid}/submit", expect_error=True)
    assert no_cover.get("_error") == 422 and "歌" in no_cover["detail"], no_cover
    t1 = add_track(p, rid, src_a["id"], title="第一首", lyrics="[00:01.00]第一句\n[00:05.00]第二句",
                   credits={"lyricist": ["词人"], "composer": ["曲人"]})
    assert t1["tracks"][0]["lyrics_kind"] == "lrc", f"带时间轴的要认成 LRC:{t1['tracks'][0]}"
    add_track(p, rid, src_b["id"], title="第二首", lyrics="没有时间轴的纯文本")
    again = p.post(f"/music/v1/studio/releases/{rid}/tracks",
                   {"title": "重复", "media_id": src_a["id"], "declaration": "original"},
                   expect_error=True)
    assert again.get("_error") == 409, f"同一个音频不能挂两首歌:{again}"
    nodecl = p.post(f"/music/v1/studio/releases/{rid}/tracks",
                    {"title": "没勾声明", "media_id": upload_audio(p)["id"]}, expect_error=True)
    assert nodecl.get("_error") == 422, f"必须勾原创 / 授权声明(M1):{nodecl}"

    # ---- 转码:两档 m4a、时长对得上 ----
    done = wait_ready(p, rid)
    assert [t["transcode_status"] for t in done["tracks"]] == ["ready", "ready"], done["tracks"]
    assert all(5000 <= t["duration_ms"] <= 8000 for t in done["tracks"]), done["tracks"]
    print("  ✓ 两首歌都转好了")

    # ---- 提交前还缺封面 ----
    no_cover = p.post(f"/music/v1/studio/releases/{rid}/submit", expect_error=True)
    assert no_cover.get("_error") == 422 and "封面" in no_cover["detail"], no_cover
    p.patch(f"/music/v1/studio/releases/{rid}", {"cover_media_id": cover["id"]})

    # ---- 提交 → 撤回 → 再提交 ----
    sub = p.post(f"/music/v1/studio/releases/{rid}/submit")
    assert sub["status"] == "reviewing", sub
    locked = p.patch(f"/music/v1/studio/releases/{rid}", {"title": "审核中改名"},
                     expect_error=True)
    assert locked.get("_error") == 409, f"审核中不能改:{locked}"
    back = p.post(f"/music/v1/studio/releases/{rid}/cancel")
    assert back["status"] == "draft", back
    p.patch(f"/music/v1/studio/releases/{rid}", {"title": "改完再交"})
    p.post(f"/music/v1/studio/releases/{rid}/submit")

    # ---- 过审:上线、封面进公开桶、曲序对 ----
    approve(rid)
    live = studio_release(p, rid)
    assert live["status"] == "published" and live["cover"].startswith("/img/"), live
    assert [t["track_no"] for t in live["tracks"]] == [1, 2]
    pub = p.get(f"/music/v1/releases/{rid}")
    assert pub["track_count"] == 2 and pub["tracks"][0]["cover"] == live["cover"], pub
    assert pub["tracks"][0]["release"]["kind"] == "ep"
    print(f"  ✓ 作品 {rid} 上线,封面在公开桶")

    # ---- 已发布的不能改、不能删、不能改曲序 ----
    for req, why in (
            (lambda: p.patch(f"/music/v1/studio/releases/{rid}", {"title": "上线后改名"},
                             expect_error=True), "改信息"),
            (lambda: p.post(f"/music/v1/studio/releases/{rid}/tracks",
                            {"title": "加一首", "media_id": upload_audio(p)["id"],
                             "declaration": "original"}, expect_error=True), "加歌"),
            (lambda: p.delete(f"/music/v1/studio/releases/{rid}", expect_error=True), "删除"),
            (lambda: p.put(f"/music/v1/studio/releases/{rid}/order",
                           {"tids": [t["tid"] for t in reversed(live["tracks"])]},
                           expect_error=True), "改曲序")):
        out = req()
        assert out.get("_error") == 409, f"已发布的作品不能{why}:{out}"
    print("  ✓ 过审后不能改,要改先下架(M3)")

    # ---- 音乐人自己下架 → 改 → 再交 ----
    w = p.post(f"/music/v1/studio/releases/{rid}/withdraw")
    assert w["status"] == "withdrawn", w
    assert outsider.get(f"/music/v1/releases/{rid}", expect_error=True).get("_error") == 404, \
        "下架后外人看不到"
    assert p.get(f"/music/v1/releases/{rid}")["rid"] == rid, "作者自己还看得到"
    order = [t["tid"] for t in reversed(live["tracks"])]
    reordered = p.put(f"/music/v1/studio/releases/{rid}/order", {"tids": order})
    assert [t["tid"] for t in reordered["tracks"]] == order, reordered["tracks"]
    p.post(f"/music/v1/studio/releases/{rid}/submit")
    approve(rid)
    assert p.get(f"/music/v1/releases/{rid}")["rid"] == rid
    print("  ✓ 下架 → 改曲序 → 再交 → 再上线")

    # ---- 删歌、删草稿 ----
    draft = new_release(p, title=rand_name("草稿"))
    src_c = upload_audio(p)
    added = add_track(p, draft["rid"], src_c["id"])
    tid = added["tracks"][0]["tid"]
    left = p.delete(f"/music/v1/studio/tracks/{tid}")
    assert left["tracks"] == [], left
    assert p.delete(f"/music/v1/studio/releases/{draft['rid']}")["ok"] is True
    assert draft["rid"] not in [x["rid"] for x in p.get("/music/v1/studio/releases")["items"]]
    print("  ✓ 删歌、删草稿")

    # ---- 太短的音频:转码失败并写原因(M4 5 秒–20 分钟)----
    short = new_release(p, title=rand_name("太短"))
    bad_src = upload_audio(p, tone(seconds=2), "short.wav")
    add_track(p, short["rid"], bad_src["id"], title="只有两秒")
    failed = wait_ready(p, short["rid"])
    assert failed["tracks"][0]["transcode_status"] == "failed", failed["tracks"]
    assert "秒" in failed["tracks"][0]["fail_reason"], failed["tracks"][0]
    blocked = p.post(f"/music/v1/studio/releases/{short['rid']}/submit", expect_error=True)
    assert blocked.get("_error") == 422 and "转码失败" in blocked["detail"], blocked
    print("  ✓ 太短的歌转码失败、带原因,而且提交不了")

    # ---- 数据 ----
    stats = p.get("/music/v1/studio/stats?days=30")
    assert set(stats) >= {"plays", "listeners", "likes", "fans", "per_day", "top_tracks"}, stats

    # ---- 开关:投稿关了 503,整个音乐关了 503 ----
    try:
        set_flag("music_upload_enabled", "off")
        off = p.post("/music/v1/studio/releases", {"title": "关着的时候"}, expect_error=True)
        assert off.get("_error") == 503 and off["detail"] == "音乐投稿暂未开放", off
        up_off = upload_audio(p, expect_error=True)
        assert up_off.get("_error") == 503, f"投稿关着连音频都不让传:{up_off}"
        assert p.get(f"/music/v1/releases/{rid}")["rid"] == rid, "只关投稿,听歌照常"
        set_flag("music_enabled", "off")
        all_off = p.get(f"/music/v1/releases/{rid}", expect_error=True)
        assert all_off.get("_error") == 503 and all_off["detail"] == "音乐暂未开放", all_off
    finally:
        set_flag("music_upload_enabled", None)
        set_flag("music_enabled", None)
    print("  ✓ 两道开关都是急停闸")

    # ---- 后台看得到这位音乐人 ----
    from urllib.parse import quote
    admins = call("GET", f"/admin/music/artists?q={quote(a['name'])}", admin_token())["items"]
    assert any(x["aid"] == a["aid"] for x in admins), admins
    print("PASS e2e_music_studio")


if __name__ == "__main__":
    main()
