"""视频「我的」与治理 e2e(DEV-PROMPTS-40 #366 #368,不变量 S2 S6)。

UP 主空间、关注 / 粉丝列表、收藏夹(默认 + 自建、公开 / 私密、移动、删除,收藏数按人算)、稍后再看、
历史(暂停记录、删单条、清空)、硬币流水、个性化开关;已发布稿件改分 P(删一 P 待审、线上不变)、放弃改动;
举报视频 / 评论 / 弹幕(7 天内 3 个不同的人 → 进复审)和审核员处置;S2:视频接口的响应里没有手机号。

跑法:SUPERZ_API=http://127.0.0.1:8013 DATABASE_URL=… REDIS_URL=… python -m tests.e2e_video_me
"""
import json

from tests.util import call
from tests.video_util import admin_token, clear_rate_limits, fixture_video, person, sql, uploader


def act(p):
    clear_rate_limits("video_act", p.id)
    return p


def main():
    adm = admin_token()
    up, fan, other = uploader(), person(), person()
    vids = [fixture_video(up.id, title=f"空间视频 {i}", zone="life", hours_ago=10 - i)
            for i in range(3)]
    for v in vids:
        sql("UPDATE videos SET views = :n WHERE id = :i", {"n": 10 * (v["id"] % 7), "i": v["id"]})

    # ---- 关注、空间、关注 / 粉丝列表 ----
    act(fan).post(f"/video/v1/users/{up.id}/follow", {"follow": True})
    act(other).post(f"/video/v1/users/{up.id}/follow", {"follow": True})
    r = act(fan).post(f"/video/v1/users/{fan.id}/follow", {"follow": True}, expect_error=True)
    assert r.get("_error") == 422, "不能关注自己"
    sp = call("GET", f"/video/v1/users/{up.id}/space", fan.token)
    assert sp["user"]["id"] == up.id and sp["followed"] is True and sp["can_follow"] is True
    assert sp["stats"]["fans"] == 2 and sp["stats"]["videos"] == 3, sp["stats"]
    assert [x["vid"] for x in sp["videos"]["items"]] == [v["vid"] for v in reversed(vids)], \
        "空间的投稿按最新"
    by_views = call("GET", f"/video/v1/users/{up.id}/videos?order=views")["items"]
    assert [x["views"] for x in by_views] == sorted((x["views"] for x in by_views), reverse=True)
    fans = call("GET", f"/video/v1/users/{up.id}/fans", fan.token)["items"]
    assert [x["id"] for x in fans] == [other.id, fan.id], "新关注的在前"
    following = fan.get("/video/v1/me/following")["items"]
    assert [x["id"] for x in following] == [up.id] and following[0]["followed"] is True
    act(other).post(f"/video/v1/users/{up.id}/follow", {"follow": False})
    assert call("GET", f"/video/v1/users/{up.id}/space")["stats"]["fans"] == 1
    up.post("/social/v1/blocks", {"user_id": other.id})
    r = act(other).post(f"/video/v1/users/{up.id}/follow", {"follow": True}, expect_error=True)
    assert r.get("_error") == 403, "拉黑了不能关注"
    assert call("GET", f"/video/v1/users/{up.id}/space", other.token)["can_follow"] is False
    up.delete(f"/social/v1/blocks/{other.id}")
    print("  ✓ 关注:空间(粉丝 / 投稿数 / 最新 / 最多播放)、粉丝列表新的在前、我的关注;取关;拉黑不能关注")

    # ---- 收藏夹 ----
    folders = fan.get("/video/v1/me/favorites")["items"]
    assert len(folders) == 1 and folders[0]["is_default"] and folders[0]["public"] is False
    default_id = folders[0]["id"]
    mine = fan.post("/video/v1/me/favorites", {"title": "想学的", "public": True})
    assert mine["public"] is True and mine["count"] == 0
    act(fan).post(f"/video/v1/videos/{vids[0]['vid']}/favorite")               # 默认收藏夹
    out = act(fan).post(f"/video/v1/videos/{vids[1]['vid']}/favorite",
                        {"folder_ids": [default_id, mine["id"]]})             # 两个收藏夹
    assert out["favorited"] and out["favorites"] == 1, "放进两个收藏夹也只算一个人收藏"
    got = {f["id"]: f for f in fan.get("/video/v1/me/favorites")["items"]}
    assert got[default_id]["count"] == 2 and got[mine["id"]]["count"] == 1
    assert got[mine["id"]]["cover"] == "" or got[mine["id"]]["cover"].startswith("/img/")
    items = fan.get(f"/video/v1/me/favorites/{default_id}")["items"]
    assert [x["video"]["vid"] for x in items] == [vids[1]["vid"], vids[0]["vid"]], "新收的在前"
    assert call("GET", f"/video/v1/favorites/{default_id}", other.token,
                expect_error=True).get("_error") == 404, "私密收藏夹别人看不到"
    pub = call("GET", f"/video/v1/favorites/{mine['id']}")
    assert [x["video"]["vid"] for x in pub["items"]] == [vids[1]["vid"]], "公开收藏夹谁都能看"
    sp = call("GET", f"/video/v1/users/{fan.id}/space")
    assert [f["id"] for f in sp["folders"]] == [mine["id"]], "空间只列公开收藏夹"
    fan.post(f"/video/v1/me/favorites/{default_id}/move", {"vids": [vids[0]["vid"]],
                                                            "to": mine["id"]})
    got = {f["id"]: f for f in fan.get("/video/v1/me/favorites")["items"]}
    assert got[default_id]["count"] == 1 and got[mine["id"]]["count"] == 2
    assert call("GET", f"/video/v1/videos/{vids[0]['vid']}")["favorites"] == 1, "挪来挪去计数不变"
    fan.patch(f"/video/v1/me/favorites/{mine['id']}", {"title": "改名了", "public": False})
    assert call("GET", f"/video/v1/favorites/{mine['id']}", expect_error=True).get("_error") == 404
    r = fan.delete(f"/video/v1/me/favorites/{default_id}", expect_error=True)
    assert r.get("_error") == 422, "默认收藏夹不能删"
    fan.delete(f"/video/v1/me/favorites/{mine['id']}")
    assert call("GET", f"/video/v1/videos/{vids[0]['vid']}")["favorites"] == 0, \
        "删了收藏夹,只在里面的视频收藏数跟着减"
    assert call("GET", f"/video/v1/videos/{vids[1]['vid']}")["favorites"] == 1
    out = act(fan).post(f"/video/v1/videos/{vids[1]['vid']}/favorite", {"folder_ids": []})
    assert out["favorited"] is False and out["favorites"] == 0, "空列表 = 取消收藏"
    r = fan.post("/video/v1/me/favorites", {"title": "", "public": False}, expect_error=True)
    assert r.get("_error") == 422
    print("  ✓ 收藏夹:默认(私密)+ 自建(公开可见于空间);两个收藏夹只算一次收藏;移动、改名、改私密;"
          "默认的不能删;删自建的计数回落;空列表取消")

    # ---- 稍后再看 ----
    fan.post("/video/v1/me/watch-later", {"vid": vids[0]["vid"]})
    wl = fan.post("/video/v1/me/watch-later", {"vid": vids[2]["vid"]})
    assert [x["video"]["vid"] for x in wl["items"]] == [vids[2]["vid"], vids[0]["vid"]]
    assert fan.get(f"/video/v1/videos/{vids[0]['vid']}")["me"]["watch_later"] is True
    fan.delete(f"/video/v1/me/watch-later/{vids[0]['vid']}")
    assert [x["video"]["vid"] for x in fan.get("/video/v1/me/watch-later")["items"]] == \
        [vids[2]["vid"]]
    print("  ✓ 稍后再看:加、列、删,详情页 me.watch_later 跟着变")

    # ---- 历史:记录、暂停、删单条、清空 ----
    for v in vids[:2]:
        fan.post(f"/video/v1/videos/{v['vid']}/view", {"part_id": v["part_id"],
                                                       "position_ms": 12_000, "played_ms": 6000})
    h = fan.get("/video/v1/me/history")
    assert [x["video"]["vid"] for x in h["items"]] == [vids[1]["vid"], vids[0]["vid"]]
    assert h["items"][0]["position_ms"] == 12_000 and h["paused"] is False
    assert fan.get(f"/video/v1/videos/{vids[0]['vid']}")["me"]["progress"]["position_ms"] == 12_000
    fan.patch("/video/v1/me/settings", {"history_paused": True})
    fan.post(f"/video/v1/videos/{vids[2]['vid']}/view", {"part_id": vids[2]["part_id"],
                                                          "position_ms": 1000, "played_ms": 6000})
    h = fan.get("/video/v1/me/history")
    assert h["paused"] is True and vids[2]["vid"] not in [x["video"]["vid"] for x in h["items"]], \
        "暂停记录后看的不进历史"
    assert call("GET", f"/video/v1/videos/{vids[2]['vid']}")["views"] >= 1, "暂停记录不影响播放计数"
    fan.patch("/video/v1/me/settings", {"history_paused": False})
    fan.delete(f"/video/v1/me/history/{vids[1]['vid']}")
    assert [x["video"]["vid"] for x in fan.get("/video/v1/me/history")["items"]] == \
        [vids[0]["vid"]]
    fan.delete("/video/v1/me/history")
    assert fan.get("/video/v1/me/history")["items"] == []
    st = fan.get("/video/v1/me/settings")
    assert st == {"personalize": True, "history_paused": False}, st
    print("  ✓ 历史:记最后看到哪、详情页续播进度;暂停记录后不进历史(播放照算);删单条、清空")

    # ---- 硬币流水 ----
    fan.post("/video/v1/me/coins/daily")
    coins = fan.get("/video/v1/me/coins")
    assert coins["coins"] == 1 and coins["today_claimed"] is True
    assert coins["items"][0]["reason"] == "daily" and coins["items"][0]["delta"] == 1 and \
        coins["items"][0]["balance"] == 1, coins["items"]
    r = act(fan).post(f"/video/v1/videos/{vids[0]['vid']}/coin", {"amount": 2}, expect_error=True)
    assert r.get("_error") == 422 and "不够" in r["detail"], "余额 1 投 2 枚:整笔回滚"
    assert fan.get("/video/v1/me/coins")["coins"] == 1
    assert sql("SELECT count(*) FROM video_coins WHERE user_id = :u", {"u": fan.id},
               fetch="scalar") == 0, "余额不够时投币记录也不留"
    print("  ✓ 硬币:每日 +1 进流水(带余额);余额不够整笔回滚,不留投币记录")

    # ---- 已发布稿件删一 P:待审期间线上不变;放弃改动 ----
    two = fixture_video(up.id, title="两 P 的视频")
    p2 = sql("INSERT INTO video_parts (video_id, idx, title, status, duration_ms, w, h, live) "
             "VALUES (:v, 1, 'P2', 'ready', 30000, 1280, 720, true) RETURNING id",
             {"v": two["id"]}, fetch="scalar")
    cd = up.delete(f"/video/v1/videos/{two['vid']}/parts/{p2}")
    assert cd["pending"]["state"] == "editing" and [x["id"] for x in cd["pending"]["parts"]] == \
        [two["part_id"]], cd["pending"]
    assert len(call("GET", f"/video/v1/videos/{two['vid']}")["parts"]) == 2, "没审之前线上还是两 P"
    r = up.delete(f"/video/v1/videos/{two['vid']}/parts/{two['part_id']}", expect_error=True)
    assert r.get("_error") == 422, "至少留 1 P"
    up.post(f"/video/v1/videos/{two['vid']}/submit")
    assert up.get(f"/video/v1/creator/videos/{two['vid']}")["pending"]["state"] == "reviewing", \
        "没有新分 P 要转码,直接进审核"
    r = up.delete(f"/video/v1/videos/{two['vid']}/changes", expect_error=True)
    assert r.get("_error") == 409, "审核中的改动不能撤回"
    call("POST", f"/admin/social/videos/{two['vid']}/decide", adm, {"approve": True})
    assert [x["id"] for x in call("GET", f"/video/v1/videos/{two['vid']}")["parts"]] == \
        [two["part_id"]]
    assert sql("SELECT count(*) FROM video_parts WHERE id = :p", {"p": p2}, fetch="scalar") == 0
    up.patch(f"/video/v1/videos/{two['vid']}", {"title": "想改又不改了"})
    up.delete(f"/video/v1/videos/{two['vid']}/changes")
    c = up.get(f"/video/v1/creator/videos/{two['vid']}")
    assert c["pending"] is None and c["title"] == "两 P 的视频"
    up.patch(f"/video/v1/videos/{two['vid']}", {"title": "两 P 的视频"})
    assert up.get(f"/video/v1/creator/videos/{two['vid']}")["pending"] is None, "改回原样 = 没有改动"
    lst = up.get("/video/v1/creator/videos?status=published")["items"]
    assert two["vid"] in {x["vid"] for x in lst} and all(x["status"] in ("published", "scheduled")
                                                          for x in lst)
    print("  ✓ 改分 P:删一 P 进待审(线上还是两 P)、至少留 1 P、审核中不能撤回、通过后才删;放弃改动;改回原样不算改动")

    # ---- 举报与处置(7 天内 3 个不同的人 → 进复审)----
    reporters = [person() for _ in range(3)]
    cm = act(fan).post(f"/video/v1/videos/{vids[0]['vid']}/comments", {"text": "广告:加我领红包"})
    dm = fan.post(f"/video/v1/parts/{vids[0]['part_id']}/danmaku", {"time_ms": 1000, "text": "引流"})
    r = reporters[0].post("/video/v1/reports", {"target_type": "comment", "target_id": cm["id"],
                                                "reason_code": "X999", "note": "短"},
                          expect_error=True)
    assert r.get("_error") == 422, "选其他要写明原因"
    for i, rp in enumerate(reporters):
        out = rp.post("/video/v1/reports", {"target_type": "comment", "target_id": cm["id"],
                                            "reason_code": "C102", "note": "引流"})
        assert out["status"] == ("escalated" if i == 2 else "open"), (i, out)
    again = reporters[0].post("/video/v1/reports", {"target_type": "comment",
                                                    "target_id": cm["id"], "reason_code": "C102"})
    assert again["id"] != 0
    reporters[0].post("/video/v1/reports", {"target_type": "danmaku", "target_id": dm["id"],
                                            "reason_code": "C102"})
    reporters[1].post("/video/v1/reports", {"target_type": "video", "vid": vids[2]["vid"],
                                            "reason_code": "V201", "note": "搬运的"})
    rep = call("GET", "/admin/social/video-reports", adm)["items"]
    first = next(x for x in rep if x["target_type"] == "comment" and x["target_id"] == cm["id"])
    assert first["status"] == "escalated", first
    states = [x["status"] for x in rep]
    assert states == sorted(states, key=lambda s: s != "escalated"), "3 人举报的(escalated)排最前"
    assert "reporter_id" not in json.dumps(rep), "后台列表里也不带举报人"
    r = call("POST", f"/admin/social/video-reports/{first['id']}/handle", adm,
             {"action": "delete"}, expect_error=True)
    assert r.get("_error") == 422, "处置要带原因代码(S6)"
    call("POST", f"/admin/social/video-reports/{first['id']}/handle", adm,
         {"action": "delete", "reason_code": "C102", "note": "引流广告"})
    assert cm["id"] not in [x["id"] for x in call("GET", f"/video/v1/videos/{vids[0]['vid']}/comments")["items"]]
    left = [x for x in call("GET", "/admin/social/video-reports", adm)["items"]
            if x["target_type"] == "comment" and x["target_id"] == cm["id"]]
    assert left == [], "同一个对象的举报一起结案"
    dr = next(x for x in call("GET", "/admin/social/video-reports", adm)["items"]
              if x["target_type"] == "danmaku" and x["target_id"] == dm["id"])
    call("POST", f"/admin/social/video-reports/{dr['id']}/handle", adm,
         {"action": "delete", "reason_code": "C102", "note": "引流"})
    seg = call("GET", f"/video/v1/parts/{vids[0]['part_id']}/danmaku?segment=0")["items"]
    assert dm["id"] not in [x["id"] for x in seg]
    vr = next(x for x in call("GET", "/admin/social/video-reports", adm)["items"]
              if x["target_type"] == "video" and x["target_id"] == vids[2]["id"])
    call("POST", f"/admin/social/video-reports/{vr['id']}/handle", adm,
         {"action": "remove", "reason_code": "V201", "note": "未经授权搬运"})
    assert call("GET", f"/video/v1/videos/{vids[2]['vid']}", expect_error=True).get("_error") == 404
    sysn = up.get("/social/v1/notifications?kind=system")["items"]
    assert any("下架" in x["title"] and x["data"]["reason_code"] == "V201" for x in sysn), sysn
    print("  ✓ 举报:X999 要写原因;3 个不同的人举报 → escalated 排最前;处置要原因代码;删评论 / 删弹幕 / 下架视频,"
          "同一对象的举报一起结案,UP 主收到带原因的通知")

    # ---- S2:视频接口的响应里没有别人的手机号 ----
    blobs = [
        call("GET", f"/video/v1/users/{up.id}/space", fan.token),
        call("GET", f"/video/v1/videos/{vids[0]['vid']}", fan.token),
        call("GET", f"/video/v1/videos/{vids[0]['vid']}/comments", fan.token),
        call("GET", f"/video/v1/users/{up.id}/fans", other.token),
        call("GET", "/video/v1/feed/recommend", fan.token),
        up.get("/social/v1/notifications?kind=reply"),
        call("GET", "/admin/social/video-reports?status=all", adm),
    ]
    raw = json.dumps(blobs, ensure_ascii=False)
    assert up.phone not in raw and fan.phone not in raw and other.phone not in raw, \
        "S2:视频相关的响应里不能出现手机号"
    assert fan.phone in json.dumps(call("GET", "/auth/me", fan.token)), "探测器认得出手机号"
    print("  ✓ S2:空间、详情、评论、粉丝、推荐、互动消息、后台举报列表里都没有手机号(探测器先对自己的号验过)")
    print("e2e_video_me 全部通过 ✅")


if __name__ == "__main__":
    main()
