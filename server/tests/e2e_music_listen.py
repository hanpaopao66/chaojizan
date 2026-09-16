"""听歌 e2e(DEV-PROMPTS-41 §5.5、M5、M6)。

签播放地址 → Range 拿到字节 → 没登录也能听 → 收听计数的门槛和 30 分钟去重 →
最近播放 upsert、清空 → 换个音质 → 地址过期 / 签名被改一律 404 →
作品下架之后旧地址立刻失效 → 榜单和曲风页把它算进去。

跑法:SUPERZ_API=http://127.0.0.1:8110 DATABASE_URL=… REDIS_URL=… python -m tests.e2e_music_listen
"""
import time

from tests.music_util import (TRACK_SECONDS, add_track, artist, clear_rate_limits, new_release,
                              person, publish_release, raw, sql, studio_release, tone,
                              upload_audio, upload_cover, wait_ready)


def _submit_only(p):
    """建一个提交了但**没过审**的作品(两首歌,测「没过审谁也拿不到」那几条)。"""
    cover = upload_cover(p)
    r = new_release(p, cover_media_id=cover["id"], kind="ep")
    for hz in (520, 580):
        add_track(p, r["rid"], upload_audio(p, tone(hz=hz))["id"])
    wait_ready(p, r["rid"])
    p.post(f"/music/v1/studio/releases/{r['rid']}/submit")
    return studio_release(p, r["rid"])


def _clear_dedup(user_id: int) -> None:
    """清掉收听去重的坑(§5.5 的 30 分钟),不然一条用例里只能算一次。"""
    import redis

    from app.config import settings
    r = redis.Redis.from_url(settings.redis_url)
    try:
        for k in r.scan_iter(match=f"music:play:u{user_id}:*"):
            r.delete(k)
    finally:
        r.close()


def main():
    a, _ = artist()
    rel = publish_release(a, tracks=2)
    tid = rel["tracks"][0]["tid"]
    listener = person()
    print(f"  作品 {rel['rid']},第一首 {tid}")

    # ---- 详情里带播放地址(两档:wav 源码率高,std + hq 都出)----
    detail = listener.get(f"/music/v1/tracks/{tid}")
    stream = detail["stream"]
    assert stream["std"] and stream["hq"], f"wav 源应该出两档:{stream}"
    assert stream["expires_at"], stream
    assert detail["lyrics_kind"] in ("none", "plain", "lrc") and "declaration" in detail

    # ---- Range 拿字节 ----
    code, headers, body = raw(None, stream["std"])
    assert code == 200 and len(body) > 1000, (code, len(body))
    assert headers.get("accept-ranges") == "bytes", headers
    total = len(body)
    code, headers, part = raw(None, stream["std"], headers={"Range": "bytes=0-99"})
    assert code == 206 and len(part) == 100, (code, len(part))
    assert headers.get("content-range") == f"bytes 0-99/{total}", headers
    code, _, hq = raw(listener.token, stream["hq"])
    assert code == 200 and len(hq) > len(body) * 1.2, "hq 该比 std 大不少"
    print("  ✓ 不登录也能听(M5),Range 和两档音质都对")

    other_tid = rel["tracks"][1]["tid"]
    assert raw(None, f"/music/v1/stream/{tid}/lossless.m4a")[0] == 404, "没有这个音质"
    # 已发布的作品本来就不要签名也能听(M5),所以签名坏了只是退回「没登录的人」,照样能听。
    # 签名真正管用的是**没过审的作品**:下面那一段
    assert raw(None, stream["std"].replace("s=", "s=ff"))[0] == 200, \
        "已发布的歌不带签名也能听(M5),签名坏了只是当没登录"

    # ---- 没过审的作品:只有作者和审核员拿得到地址,签名改一个字就 404 ----
    b, _ = artist()
    draft_rel = _submit_only(b)
    draft_tid = draft_rel["tracks"][0]["tid"]
    mine = b.get(f"/music/v1/tracks/{draft_tid}")["stream"]["std"]
    assert raw(None, mine)[0] == 200, "作者自己的签名地址能放"
    assert raw(None, mine.replace("s=", "s=ff"))[0] == 404, "没过审的歌,签名改了就 404"
    bad_exp = mine.split("&e=")[0] + "&e=1&s=" + mine.split("&s=")[1]
    assert raw(None, bad_exp)[0] == 404, "过期的地址不认"
    assert raw(None, mine.replace(draft_tid, draft_rel["tracks"][1]["tid"]))[0] == 404, \
        "签名绑着歌,同一个作品里换一首也用不了"
    assert raw(listener.token, f"/music/v1/stream/{draft_tid}/std.m4a")[0] == 404, \
        "别人不带签名更不行"
    assert listener.get(f"/music/v1/tracks/{draft_tid}", expect_error=True).get("_error") == 404
    print("  ✓ 签名绑歌、绑用户、绑到期;没过审的一律 404")

    # ---- 收听计数:门槛 min(30 秒, 时长一半)----
    half = TRACK_SECONDS * 1000 // 2
    before = listener.get(f"/music/v1/tracks/{tid}")["plays"]
    short = listener.post(f"/music/v1/tracks/{tid}/play", {"ms_listened": half - 500})
    assert short["counted"] is False, f"没听够不算:{short}"
    assert short["threshold_ms"] == half, short
    ok = listener.post(f"/music/v1/tracks/{tid}/play", {"ms_listened": half})
    assert ok["counted"] is True and ok["plays"] == before + 1, ok
    again = listener.post(f"/music/v1/tracks/{tid}/play", {"ms_listened": 999_999})
    assert again["counted"] is False and again.get("deduped") is True, \
        f"30 分钟内同一个人同一首只算一次:{again}"
    assert listener.get(f"/music/v1/tracks/{tid}")["plays"] == before + 1
    print("  ✓ 收听门槛 + 30 分钟去重")

    # ---- 没登录按设备去重 ----
    from tests.music_util import call
    dev = "e2e-device-" + str(int(time.time()))
    anon1 = call("POST", f"/music/v1/tracks/{tid}/play", None,
                 {"ms_listened": half, "device_id": dev})
    assert anon1["counted"] is True, anon1
    anon2 = call("POST", f"/music/v1/tracks/{tid}/play", None,
                 {"ms_listened": half, "device_id": dev})
    assert anon2["counted"] is False, f"同一台设备 30 分钟内只算一次:{anon2}"
    anon3 = call("POST", f"/music/v1/tracks/{tid}/play", None,
                 {"ms_listened": half, "device_id": dev + "-b"})
    assert anon3["counted"] is True, "换台设备算新的一个人"
    print("  ✓ 没登录按设备去重")

    # ---- 最近播放:听过就在里面,清空能清掉 ----
    hist = listener.get("/music/v1/me/history")
    assert [x["tid"] for x in hist["items"]][:1] == [tid], hist
    assert hist["max"] == 300
    listener.post(f"/music/v1/tracks/{other_tid}/play", {"ms_listened": 100})
    assert [x["tid"] for x in listener.get("/music/v1/me/history")["items"]][0] == other_tid, \
        "没听够也进最近播放(是「我放过什么」,不是「算不算收听」)"
    assert listener.delete("/music/v1/me/history")["ok"] is True
    assert listener.get("/music/v1/me/history")["items"] == []
    print("  ✓ 最近播放 upsert + 清空")

    # ---- 榜单:热歌榜把这次收听算进去,带中间量 ----
    _clear_dedup(listener.id)
    clear_rate_limits("music_play", listener.id)
    for extra in range(4):     # 凑够飙升榜的 5 个人
        p = person()
        p.post(f"/music/v1/tracks/{tid}/play", {"ms_listened": half})
    hot = listener.get("/music/v1/charts/hot")
    hit = next((x for x in hot["items"] if x["track"]["tid"] == tid), None)
    assert hit is not None, f"听过的歌该在热歌榜上:{[x['track']['tid'] for x in hot['items']]}"
    assert hit["rank"]["parts"]["listeners_7d"] >= 5, hit["rank"]
    assert "人收听" in hit["rank"]["why"], hit["rank"]
    assert hit["rank_no"] == 1 or hit["rank"]["score"] > 0
    rising = listener.get("/music/v1/charts/rising")
    assert any(x["track"]["tid"] == tid for x in rising["items"]), "5 个人听过就该上飙升榜"
    print("  ✓ 榜单算进去了,每项带中间量")

    # ---- 曲风页、发现页、公式 ----
    genre = listener.get("/music/v1/genres/pop/tracks")
    assert any(x["tid"] == tid for x in genre["items"]), genre
    home = listener.get("/music/v1/home")
    assert {"daily", "playlists", "new_tracks", "charts", "genres"} <= set(home), list(home)
    assert len(home["charts"]) == 3 and all(len(c["top"]) <= 3 for c in home["charts"])
    formula = listener.get("/music/v1/rank/formula")
    assert "热歌榜分数" in formula["formula"] and formula["params"]["like_weight"] == 3, formula
    print("  ✓ 曲风页、发现页、公开公式")

    # ---- 个性化开关 ----
    assert listener.get("/music/v1/me/settings")["personalize"] is True
    assert listener.put("/music/v1/me/settings", {"personalize": False})["personalize"] is False
    daily = listener.get("/music/v1/daily")
    assert daily["personalized"] is False, daily
    listener.put("/music/v1/me/settings", {"personalize": True})

    # ---- 下架:旧地址立刻失效 ----
    a.post(f"/music/v1/studio/releases/{rel['rid']}/withdraw")
    assert raw(None, stream["std"])[0] == 404, "下架之后旧的播放地址立刻失效"
    assert listener.get(f"/music/v1/tracks/{tid}", expect_error=True).get("_error") == 404
    gone = listener.post(f"/music/v1/tracks/{tid}/play", {"ms_listened": half},
                         expect_error=True)
    assert gone.get("_error") == 404, gone
    # 数字不许倒退:下架不清收听明细(那是平台的数据,不是展示)
    row = sql("SELECT count(*) FROM music_plays WHERE track_id = (SELECT id FROM music_tracks "
              "WHERE tid = :t)", {"t": tid}, fetch="scalar")
    assert row >= 5, row
    print("PASS e2e_music_listen")


if __name__ == "__main__":
    main()
