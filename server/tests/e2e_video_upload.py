"""视频投稿全流程 e2e(DEV-PROMPTS-40 #358 #360–#362 #366–#368,不变量 S4 S5 S6、决定 D10 D11 D13)。

现场用 ffmpeg 生成横屏(1280×720)和竖屏(720×1280)各一段 4 秒的测试片 →
分片 / 整块上传 → 建稿、挂分 P、提交 → 转码(档位、雪碧图、封面三帧)→ 审核通过 →
推荐 / 竖屏流里出现 → 另一个账号播放(Range 拿到字节)、发弹幕、评论、三连、关注、分享 →
UP 主收到互动消息(实时 notify 事件)→ 创作中心数据变化;
驳回重交;编辑已发布稿件(改标题、加一 P)期间线上仍是旧版;下架 → 申诉 → 原审核员 403、换人改判;
设成私密后旧的播放地址立即失效;删除;开关;最后注销账号,所有视频地址不可访问(S5)。

跑法:SUPERZ_API=http://127.0.0.1:8013 DATABASE_URL=… REDIS_URL=… python -m tests.e2e_video_upload
"""
import asyncio
import time
from datetime import datetime, timedelta, timezone

from tests.chat_util import WS
from tests.util import call
from tests.video_util import (add_part, admin2_token, admin_token, chunked_upload, clear_rate_limits,
                              creator, ffmpeg_clip, media_upload, new_video, person, raw,
                              realname, set_coins, set_flag, sql, wait_video)


def gone(url: str, timeout: float = 5) -> bool:
    """对象存储里的文件是提交之后才删的(后台任务),等它一下。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if raw(None, url)[0] == 404:
            return True
        time.sleep(0.2)
    return False


def find_in_feed(path: str, vid: str, token: str | None = None, pages: int = 60) -> dict | None:
    for page in range(pages):
        out = call("GET", f"{path}?page={page}", token)
        hit = next((x for x in out["items"] if x["vid"] == vid), None)
        if hit is not None:
            return hit
        if not out["has_more"]:
            return None
    return None


def main():
    adm = admin_token()
    a, b = person(), person()   # a = UP 主,b = 观众
    print(f"  UP 主 A={a.id},观众 B={b.id}")

    # ---- 实名门槛(D11)----
    r = a.post("/video/v1/uploads/videos", {"title": "没实名"}, expect_error=True)
    assert r.get("_error") == 403 and "实名" in r["detail"], r
    realname(a)
    print("  ✓ D11:没实名不能投稿,实名之后可以")

    # ---- 上传原片:横屏走分片,竖屏整块 ----
    horiz, vert = ffmpeg_clip(1280, 720, 4), ffmpeg_clip(720, 1280, 4)
    src_h = chunked_upload(a, horiz, "横屏.mp4")
    src_v = media_upload(a, vert, "竖屏.mp4", "video_source")
    assert src_h["kind"] == "video_source" and src_h["status"] == "ready", src_h
    code, _, _ = raw(b.token, src_h["url"].split("?")[0])
    assert code == 404, "原片只有上传者自己(和审核员)能下"

    vh = new_video(a, title="横屏测试视频", zone="tech", tags=["测试", "横屏"],
                   description="一段 e2e 生成的横屏测试片", copyright="original")
    vid_h = vh["vid"]
    assert vid_h.startswith("sv") and len(vid_h) == 12 and vh["status"] == "draft", vh
    add_part(a, vid_h, src_h["id"], "第一 P")
    r = a.post(f"/video/v1/videos/{vid_h}/parts", {"media_id": src_h["id"]}, expect_error=True)
    assert r.get("_error") == 409, "同一个原片不能挂两次"
    vv = new_video(a, title="竖屏测试视频", zone="life", tags=["竖屏"], copyright="repost",
                   source_url="https://example.com/origin")
    vid_v = vv["vid"]
    add_part(a, vid_v, src_v["id"])

    wa = WS(a.token)
    wa.wait_for(lambda f: f.get("t") == "ready")
    for vid in (vid_h, vid_v):
        a.post(f"/video/v1/videos/{vid}/submit")
    h = wait_video(a, vid_h, lambda x: x["status"] == "reviewing", what="reviewing")
    v = wait_video(a, vid_v, lambda x: x["status"] == "reviewing", what="reviewing")
    wa.wait_for(lambda f: f.get("t") == "uev" and f.get("type") == "video"
                and f["data"]["vid"] in (vid_h, vid_v), timeout=30)

    # ---- 转码产物:档位不超过原片、宽高比例对、雪碧图、封面三帧 ----
    ph = h["parts"][0]
    assert [(x["q"], x["w"], x["h"]) for x in ph["renditions"]] == \
        [(720, 1280, 720), (480, 852, 480), (360, 640, 360)], ph["renditions"]
    pv = v["parts"][0]
    assert [(x["q"], x["w"], x["h"]) for x in pv["renditions"]] == \
        [(720, 720, 1280), (480, 480, 852), (360, 360, 640)], pv["renditions"]
    assert h["is_vertical"] is False and v["is_vertical"] is True
    assert 3900 <= ph["duration_ms"] <= 4200 and h["duration_ms"] == ph["duration_ms"], ph
    sp = ph["sprite"]
    assert sp["cols"] == 10 and sp["rows"] == 10 and sp["w"] == 160 and sp["h"] == 90, sp
    assert sp["interval_ms"] == 1000 and sp["count"] == 4 and len(sp["urls"]) == 1, sp
    assert len(ph["cover_candidates"]) == 3, ph["cover_candidates"]
    assert h["cover_media_id"] == ph["cover_candidates"][0]["media_id"], "没选封面时用第一帧"
    code, hdr, _ = raw(None, h["cover_preview"])
    assert code == 200 and hdr["content-type"].startswith("image/"), "UP 主看得到自己审核中的封面"
    print("  ✓ 转码:横屏 720/480/360、竖屏按宽算档位;雪碧图 10×10、160×90、1 秒一格;封面三帧,默认第一帧")

    # ---- 审核中:别人看不到(D10)----
    assert b.get(f"/video/v1/videos/{vid_h}", expect_error=True).get("_error") == 404
    assert call("GET", f"/video/v1/videos/{vid_h}", expect_error=True).get("_error") == 404
    code, _, _ = raw(b.token, ph["renditions"][0]["url"].split("?")[0])
    assert code == 404, "审核中的播放地址别人拿不到"
    assert raw(None, ph["renditions"][0]["url"], headers={"Range": "bytes=0-9"})[0] == 206, \
        "UP 主自己的签名地址能播"
    queue = call("GET", "/admin/social/videos/review", adm)["items"]
    assert {vid_h, vid_v} <= {x["vid"] for x in queue}, "两个稿件都在审核队列里"
    adm_view = call("GET", f"/admin/social/videos/{vid_h}", adm)
    assert raw(None, adm_view["parts"][0]["renditions"][-1]["url"])[0] in (200, 206), "审核员能看"
    print("  ✓ D10:审核中只有 UP 主和审核员能看;别人、没登录的一律 404")

    # ---- 审核:驳回要原因代码,X999 要写说明(S6)----
    r = call("POST", f"/admin/social/videos/{vid_h}/decide", adm, {"approve": False},
             expect_error=True)
    assert r.get("_error") == 422 and "原因代码" in r["detail"], r
    r = call("POST", f"/admin/social/videos/{vid_h}/decide", adm,
             {"approve": False, "reason_code": "X999", "note": "不行"}, expect_error=True)
    assert r.get("_error") == 422 and "X999" in r["detail"], r
    for vid in (vid_h, vid_v):
        out = call("POST", f"/admin/social/videos/{vid}/decide", adm, {"approve": True})
        assert out["status"] == "published", out
    r = call("POST", f"/admin/social/videos/{vid_h}/decide", adm, {"approve": True},
             expect_error=True)
    assert r.get("_error") == 409, "已经发布的不能再审一次"
    print("  ✓ 审核:驳回不带原因 422、X999 不写说明 422;通过后 published")

    # ---- 过审硬币(D13)、系统通知 ----
    coins = a.get("/video/v1/me/coins")
    approved = [x for x in coins["items"] if x["reason"] == "video_approved"]
    assert len(approved) == 2 and all(x["delta"] == 2 for x in approved), coins
    sysn = a.get("/social/v1/notifications?kind=system")["items"]
    assert any("审核通过" in x["title"] and x["video"]["vid"] == vid_h for x in sysn), sysn
    print(f"  ✓ D13:两个稿件过审各 +2 硬币(余额 {coins['coins']});审核结果进「系统通知」")

    # ---- 推荐 / 竖屏流 ----
    assert find_in_feed("/video/v1/feed/recommend", vid_h) is not None
    assert find_in_feed("/video/v1/feed/recommend", vid_v) is not None
    assert find_in_feed("/video/v1/feed/vertical", vid_v) is not None
    assert find_in_feed("/video/v1/feed/vertical", vid_h) is None, "竖屏流只有竖屏视频"
    card = find_in_feed("/video/v1/feed/recommend", vid_h)
    assert card["cover"].startswith("/img/video_cover/"), card["cover"]
    code, hdr, _ = raw(None, card["cover"])
    assert code == 200 and hdr["content-type"].startswith("image/"), "过审后封面在公开桶"
    print("  ✓ 推荐里有两个视频,竖屏流只有竖屏那个;封面过审后进公开桶")

    # ---- 另一个账号播放:Range ----
    d = b.get(f"/video/v1/videos/{vid_h}")
    assert d["title"] == "横屏测试视频" and d["uploader"]["id"] == a.id and d["me"]["liked"] is False
    url = d["parts"][0]["renditions"][0]["url"]
    assert f"u={b.id}" in url, "播放地址按看的人签名"
    code, hdr, body = raw(None, url, headers={"Range": "bytes=0-99"})
    assert code == 206 and len(body) == 100 and hdr["content-range"].startswith("bytes 0-99/"), \
        (code, hdr)
    assert body[4:8] == b"ftyp", "拿到的是 MP4 的文件头"
    total = int(hdr["content-range"].split("/")[1])
    code, hdr, body = raw(None, url, headers={"Range": f"bytes={total - 10}-"})
    assert code == 206 and len(body) == 10, (code, hdr)
    plain = url.split("?")[0]
    code, _, _ = raw(None, plain, headers={"Range": "bytes=0-9"})
    assert code == 206, "公开稿件没登录、不带签名也能看"
    code, hdr, _ = raw(None, d["parts"][0]["sprite"]["urls"][0])
    assert code == 200 and hdr["content-type"] == "image/jpeg", "进度条缩略图"
    print(f"  ✓ 播放:签名地址 Range 206、MP4 文件头对、尾部 10 字节;公开稿件匿名可播;雪碧图可取(全长 {total} 字节)")

    # ---- 弹幕、评论、三连、关注、分享、播放计数 ----
    set_coins(b.id, 5)
    daily = b.post("/video/v1/me/coins/daily")
    assert daily["granted"] is True and daily["coins"] == 6, daily
    assert b.post("/video/v1/me/coins/daily")["granted"] is False, "每日硬币一天只领一次"
    dm = b.post(f"/video/v1/parts/{d['parts'][0]['id']}/danmaku",
                {"time_ms": 1500, "text": "前排", "mode": 1, "color": 16777215, "size": 25})
    assert dm["mine"] is True and len(dm["user_hash"]) == 8, dm
    cm = b.post(f"/video/v1/videos/{vid_h}/comments", {"text": "拍得不错"})
    assert cm["user"]["id"] == b.id and cm["is_up"] is False, cm
    tri = b.post(f"/video/v1/videos/{vid_h}/triple")
    assert tri["liked"] and tri["coins_given"] == 2 and tri["favorited"], tri
    assert tri["me"]["coins"] == 2 and tri["me"]["coin_balance"] == 4, tri["me"]
    r = b.post(f"/video/v1/videos/{vid_h}/coin", {"amount": 1}, expect_error=True)
    assert r.get("_error") == 409 and "投满" in r["detail"], "自制视频每人最多 2 枚"
    r = b.post(f"/video/v1/videos/{vid_v}/coin", {"amount": 2}, expect_error=True)
    assert r.get("_error") == 422 and "转载" in r["detail"], "转载视频最多 1 枚"
    b.post(f"/video/v1/videos/{vid_v}/coin", {"amount": 1})
    r = a.post(f"/video/v1/videos/{vid_h}/coin", {"amount": 1}, expect_error=True)
    assert r.get("_error") == 422, "不能给自己投币"
    # 点赞 / 投币 / 收藏 / 分享 / 关注共用「每人每秒 5 次」的桶(§5.7):上面连着点了一串,清一下再往下走
    clear_rate_limits("video_act", b.id)
    b.post(f"/video/v1/users/{a.id}/follow", {"follow": True})
    sh = b.post(f"/video/v1/videos/{vid_h}/share", {"channel": "chat"})
    assert sh["shares"] == 1 and sh["link"].endswith(f"/v/{vid_h}"), sh
    b.post(f"/video/v1/videos/{vid_h}/share", {"channel": "link"})
    v1 = b.post(f"/video/v1/videos/{vid_h}/view", {"part_id": d["parts"][0]["id"],
                                                    "position_ms": 3000, "played_ms": 3000})
    assert v1["counted"] is True, "4 秒的片子看了 3 秒(> 30%)算一次播放"
    v2 = b.post(f"/video/v1/videos/{vid_h}/view", {"part_id": d["parts"][0]["id"],
                                                    "position_ms": 4000, "played_ms": 4000})
    assert v2["counted"] is False and v2["views"] == 1, "同一个人同一天只算一次"
    anon = call("POST", f"/video/v1/videos/{vid_h}/view",
                body={"played_ms": 800, "device_id": "dev-e2e-1"})
    assert anon["counted"] is False, "没看满 5 秒也没到 30%,不算"
    anon = call("POST", f"/video/v1/videos/{vid_h}/view",
                body={"played_ms": 6000, "device_id": "dev-e2e-1"})
    assert anon["counted"] is True and anon["views"] == 2, "没登录按设备算"
    d2 = b.get(f"/video/v1/videos/{vid_h}")
    assert (d2["likes"], d2["coins"], d2["favorites"], d2["shares"], d2["danmaku_count"],
            d2["comment_count"], d2["views"]) == (1, 2, 1, 1, 1, 1, 2), d2
    assert d2["me"]["liked"] and d2["me"]["favorited"] and d2["uploader"]["followed"], d2["me"]
    hist = b.get("/video/v1/me/history")["items"]
    assert hist[0]["video"]["vid"] == vid_h and hist[0]["position_ms"] == 4000, hist[:1]
    print("  ✓ 弹幕、评论、三连(赞 + 2 币 + 默认收藏夹)、投币上限(自制 2 / 转载 1 / 不能投自己)、"
          "关注、分享(一人只算一次)、播放计数(5 秒或 30%、每人每天一次、没登录按设备)、历史")

    # ---- 互动消息(实时)----
    ev = wa.wait_for(lambda f: f.get("t") == "uev" and f.get("type") == "notify"
                     and f["data"]["kind"] == "reply", timeout=10)
    assert ev["data"]["unread"]["reply"] >= 1, ev
    replies = a.get("/social/v1/notifications?kind=reply")["items"]
    assert replies[0]["text"] == "拍得不错" and replies[0]["actor"]["id"] == b.id, replies[0]
    assert replies[0]["title"].endswith("评论了你的视频"), replies[0]["title"]
    likes = a.get("/social/v1/notifications?kind=like")["items"]
    assert any(x["video"] and x["video"]["vid"] == vid_h and "赞了你的视频" in x["title"]
               for x in likes), likes
    unread = a.get("/social/v1/notifications/unread")
    assert unread["reply"] >= 1 and unread["like"] >= 1 and unread["system"] >= 2, unread
    after = a.post("/social/v1/notifications/read", {"kind": "reply"})["unread"]
    assert after["reply"] == 0 and after["like"] == unread["like"], after
    wa.wait_for(lambda f: f.get("t") == "uev" and f.get("type") == "notify"
                and f["data"]["unread"]["reply"] == 0, timeout=10)
    print("  ✓ 互动消息:评论进「回复我的」、赞进「收到的赞」、审核进「系统通知」;notify 事件实时推,已读后角标跟着变")

    # ---- 创作中心 ----
    st = a.get(f"/video/v1/creator/videos/{vid_h}/stats")
    assert st["totals"] == {"views": 2, "likes": 1, "coins": 2, "favorites": 1, "comments": 1,
                            "danmaku": 1, "shares": 1}, st["totals"]
    today = st["days"][-1]
    assert (today["views"], today["likes"], today["coins"], today["danmaku"]) == (2, 1, 2, 1), today
    ov = a.get("/video/v1/creator/overview")
    assert ov["fans"] == 1 and ov["videos"]["published"] == 2 and ov["totals"]["coins"] == 3, ov
    received = [x for x in a.get("/video/v1/me/coins")["items"] if x["reason"] == "coin_receive"]
    assert sum(x["delta"] for x in received) == 3, "投出的硬币归 UP 主"
    print("  ✓ 创作中心:单稿累计 + 今天的增量、总览(粉丝、稿件数、硬币);投币进 UP 主的硬币流水")

    # ---- 编辑已发布稿件:审核期间线上仍是旧版(§5.8)----
    ed = a.patch(f"/video/v1/videos/{vid_h}", {"title": "改过的新标题", "allow_comments": True})
    assert ed["status"] == "published" and ed["pending"]["state"] == "editing", ed["pending"]
    assert ed["pending"]["fields"] == {"title": "改过的新标题"}, ed["pending"]
    src_h2 = media_upload(a, ffmpeg_clip(640, 360, 3), "第二P.mp4", "video_source")
    add_part(a, vid_h, src_h2["id"], "第二 P")
    assert b.get(f"/video/v1/videos/{vid_h}")["title"] == "横屏测试视频", "改动没审之前线上不变"
    a.post(f"/video/v1/videos/{vid_h}/submit")
    wait_video(a, vid_h, lambda x: (x["pending"] or {}).get("state") == "reviewing",
               what="改动进审核")
    pub = b.get(f"/video/v1/videos/{vid_h}")
    assert pub["title"] == "横屏测试视频" and len(pub["parts"]) == 1, "改动审核期间线上仍是旧版"
    assert raw(None, pub["parts"][0]["renditions"][0]["url"], headers={"Range": "bytes=0-9"})[0] \
        == 206, "旧版照常能播"
    q = call("GET", "/admin/social/videos/review", adm)["items"]
    assert any(x["vid"] == vid_h and x["review"] == "changes" for x in q), "改动也进审核队列"
    r = a.patch(f"/video/v1/videos/{vid_h}", {"title": "审核中再改"}, expect_error=True)
    assert r.get("_error") == 409, "改动审核中不能再改"
    call("POST", f"/admin/social/videos/{vid_h}/decide", adm, {"approve": True})
    pub = b.get(f"/video/v1/videos/{vid_h}")
    assert pub["title"] == "改过的新标题" and [p["title"] for p in pub["parts"]] == \
        ["第一 P", "第二 P"], pub["parts"]
    assert pub["duration_ms"] > 6500, "时长是各 P 之和"
    print("  ✓ 编辑已发布稿件:改标题 + 加一 P → 待审;审核期间线上仍是旧标题、旧的 1 P 照常播;通过后才换")

    # ---- 驳回重交 ----
    src3 = media_upload(a, ffmpeg_clip(640, 360, 2, audio=False), "无声.mp4", "video_source")
    v3 = new_video(a, title="标题和内容不符", zone="funny")
    vid3 = v3["vid"]
    add_part(a, vid3, src3["id"])
    a.post(f"/video/v1/videos/{vid3}/submit")
    wait_video(a, vid3, lambda x: x["status"] == "reviewing", what="reviewing")
    call("POST", f"/admin/social/videos/{vid3}/decide", adm,
         {"approve": False, "reason_code": "V202", "note": "标题说的内容视频里没有"})
    c3 = creator(a, vid3)
    assert c3["status"] == "rejected" and c3["reject_code"] == "V202" and \
        c3["reject_label"].startswith("标题"), c3
    assert any(d["action"] == "reject" and d["can_appeal"] for d in c3["decisions"]), c3["decisions"]
    sysn = a.get("/social/v1/notifications?kind=system")["items"]
    assert any("未通过" in x["title"] and x["data"]["reason_code"] == "V202" for x in sysn), sysn
    r = a.post(f"/video/v1/videos/{vid3}/submit")    # 不改直接重交也行(先回草稿再提交)
    ed = a.patch(f"/video/v1/videos/{vid3}", {"title": "无声的测试片"}, expect_error=True)
    assert ed.get("_error") == 409, "重新提交之后在审核中,不能改"
    wait_video(a, vid3, lambda x: x["status"] == "reviewing", what="重交后 reviewing")
    call("POST", f"/admin/social/videos/{vid3}/decide", adm, {"approve": True})
    assert creator(a, vid3)["status"] == "published"
    print("  ✓ 驳回重交:V202 + 说明 → rejected(可申诉)、系统通知带原因;重新提交 → 审核 → 通过")

    # ---- 下架 → 申诉 → 换人复核(S6)----
    call("POST", f"/admin/social/videos/{vid_v}/remove", adm,
         {"reason_code": "C104", "note": "画面低俗(测试)"})
    assert b.get(f"/video/v1/videos/{vid_v}", expect_error=True).get("_error") == 404
    assert raw(None, card["cover"])[0] == 200  # 横屏的封面还在
    ap = a.post(f"/video/v1/videos/{vid_v}/appeal", {"text": "这是测试片,没有低俗内容"})
    r = a.post(f"/video/v1/videos/{vid_v}/appeal", {"text": "再申诉一次试试"}, expect_error=True)
    assert r.get("_error") == 409, "每个结论只能申诉一次"
    lst = call("GET", "/admin/social/appeals", adm)["items"]
    mine = next(x for x in lst if x["appeal"]["id"] == ap["id"])
    assert mine["you_decided_original"] is True
    r = call("POST", f"/admin/social/appeals/{ap['id']}/resolve", adm,
             {"overturn": True, "note": "自己改判自己"}, expect_error=True)
    assert r.get("_error") == 403 and "另一名审核员" in r["detail"], r
    adm2 = admin2_token()
    out = call("POST", f"/admin/social/appeals/{ap['id']}/resolve", adm2,
               {"overturn": True, "note": "复核后没有低俗内容,撤销下架"})
    assert out["status"] == "published", out
    assert b.get(f"/video/v1/videos/{vid_v}")["vid"] == vid_v, "改判后恢复上线"
    r = call("POST", f"/admin/social/appeals/{ap['id']}/resolve", adm2,
             {"overturn": False, "note": "重复处理"}, expect_error=True)
    assert r.get("_error") == 409
    print("  ✓ S6:下架带原因;申诉一次;原审核员处理 403;另一名审核员改判后恢复上线")

    # ---- 设成私密:旧的播放地址立即失效 ----
    old_url = b.get(f"/video/v1/videos/{vid_h}")["parts"][0]["renditions"][0]["url"]
    a.patch(f"/video/v1/videos/{vid_h}", {"visibility": "private"})
    assert raw(None, old_url, headers={"Range": "bytes=0-9"})[0] == 404, "签名绑人,播放时重新判权"
    assert b.get(f"/video/v1/videos/{vid_h}", expect_error=True).get("_error") == 404
    mine_url = a.get(f"/video/v1/videos/{vid_h}")["parts"][0]["renditions"][0]["url"]
    assert raw(None, mine_url, headers={"Range": "bytes=0-9"})[0] == 206, "私密视频自己能看"
    forged = mine_url.replace(f"u={a.id}", f"u={b.id}")
    assert raw(None, forged, headers={"Range": "bytes=0-9"})[0] == 404, "把签名里的人换成别人不行"
    a.patch(f"/video/v1/videos/{vid_h}", {"visibility": "public"})
    print("  ✓ 私密:别人的旧签名地址立刻 404,自己能看,改签名里的用户不行")

    # ---- 定时发布:过审后到点才公开,由清扫任务推进 ----
    src4 = media_upload(a, ffmpeg_clip(360, 640, 2), "定时.mp4", "video_source")
    at = (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat()
    v4 = new_video(a, title="定时发布的视频", zone="life", scheduled_at=at)
    vid4 = v4["vid"]
    r = a.post("/video/v1/uploads/videos", {"title": "太近", "scheduled_at":
               (datetime.now(timezone.utc) + timedelta(minutes=1)).isoformat()}, expect_error=True)
    assert r.get("_error") == 422 and "5 分钟" in r["detail"], r
    add_part(a, vid4, src4["id"])
    a.post(f"/video/v1/videos/{vid4}/submit")
    wait_video(a, vid4, lambda x: x["status"] == "reviewing", what="reviewing")
    out = call("POST", f"/admin/social/videos/{vid4}/decide", adm, {"approve": True})
    assert out["status"] == "scheduled", out
    assert b.get(f"/video/v1/videos/{vid4}", expect_error=True).get("_error") == 404, \
        "过审了但没到点,别人还看不到"
    sql("UPDATE videos SET scheduled_at = now() - interval '1 minute' WHERE vid = :v", {"v": vid4})
    from app.services.video import sweep_videos
    swept = asyncio.run(sweep_videos())
    assert swept["published"] >= 1, swept
    assert b.get(f"/video/v1/videos/{vid4}")["status"] == "published", "到点由清扫任务公开"
    assert any("已经公开" in x["text"] for x in
               a.get("/social/v1/notifications?kind=system")["items"])
    print("  ✓ 定时发布:5 分钟之内的时间拒绝;过审 → scheduled(别人看不到)→ 清扫到点 → published,并通知 UP 主")

    # ---- 删除 ----
    url3 = a.get(f"/video/v1/videos/{vid3}")["parts"][0]["renditions"][0]["url"]
    a.delete(f"/video/v1/videos/{vid3}")
    assert raw(None, url3, headers={"Range": "bytes=0-9"})[0] == 404
    assert b.get(f"/video/v1/videos/{vid3}", expect_error=True).get("_error") == 404
    print("  ✓ 删除:详情和播放地址立即 404")

    # ---- 开关(#375)----
    try:
        set_flag("video_upload_enabled", "off")
        r = a.post("/video/v1/uploads/videos", {"title": "关着"}, expect_error=True)
        assert r.get("_error") == 503 and r["detail"] == "视频投稿暂未开放", r
        r = media_upload(a, vert, "x.mp4", "video_source", expect_error=True)
        assert r.get("_error") == 503, "投稿关着的时候原片也传不了"
        assert call("GET", "/video/v1/feed/hot")["items"] is not None, "只关投稿,浏览照常"
        set_flag("video_enabled", "off")
        r = call("GET", "/video/v1/feed/recommend", expect_error=True)
        assert r.get("_error") == 503 and r["detail"] == "视频功能暂未开放", r
    finally:
        set_flag("video_enabled", None)
        set_flag("video_upload_enabled", None)
    assert call("GET", "/video/v1/feed/hot")["page"] == 0
    flags = call("GET", "/admin/flags", adm)
    assert flags["video_enabled"] == "on" and flags["video_upload_enabled"] == "on", \
        "开发环境缺省开(生产缺省关,见 test_video_flags)"
    print("  ✓ 开关:关投稿 → 建稿、传原片 503;关视频 → 全部 503;都有明确的中文提示")

    # ---- S5:注销账号,原来的视频地址全部不可访问 ----
    d = b.get(f"/video/v1/videos/{vid_h}")
    urls = [d["parts"][0]["renditions"][0]["url"], d["parts"][0]["sprite"]["urls"][0],
            d["parts"][0]["renditions"][0]["url"].split("?")[0]]
    cover = d["cover"]
    assert all(raw(None, u, headers={"Range": "bytes=0-9"})[0] in (200, 206) for u in urls)
    clear_rate_limits("video_comment", a.id)
    a.post(f"/video/v1/videos/{vid_h}/comments", {"text": "UP 主自己的评论"})
    call("DELETE", "/auth/me", a.token)
    for u in urls:
        assert raw(None, u, headers={"Range": "bytes=0-9"})[0] == 404, f"注销后还能访问:{u}"
    assert gone(cover), "公开桶里的封面也删了"
    assert b.get(f"/video/v1/videos/{vid_h}", expect_error=True).get("_error") == 404
    assert b.get(f"/video/v1/videos/{vid_v}", expect_error=True).get("_error") == 404
    left = sql("SELECT count(*) FROM video_comments WHERE user_id = :u AND text <> ''",
               {"u": a.id}, fetch="scalar")
    assert left == 0, "注销的人说过的话清空了"
    assert sql("SELECT count(*) FROM media_files WHERE owner_id = :u AND purpose = 'video'",
               {"u": a.id}, fetch="scalar") == 0, "原片、封面的媒体行都删了"
    assert sql("SELECT count(*) FROM follows WHERE followee_id = :u", {"u": a.id},
               fetch="scalar") == 0
    print("  ✓ S5:注销后播放地址、雪碧图、公开封面、详情全部 404;评论正文、媒体、关注关系清掉")

    wa.close()
    print("e2e_video_upload 全部通过 ✅")


if __name__ == "__main__":
    main()
