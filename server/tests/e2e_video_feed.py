"""推荐 / 热门 / 竖屏 / 分区 / 排行榜 / 相关 / 搜索 / 热搜 e2e(DEV-PROMPTS-40 §5.9、S3、S9、#363–#365)。

- §5.9 逐条复算:接口下发的每一条都带着算它的那几个数,这里**用文档里的系数**(不 import 服务端代码)
  重新算一遍互动分、热度、推荐分,必须一模一样;再检查顺序确实按分数排;
- 同一个 UP 主一屏(20 条)最多 2 个:第 3 个顺延到下一屏;
- S9:关掉个性化之后,「推荐」和没登录的人看到的**逐条相等**;开着时关注加 0.3、常看分区加 0.15、
  看过 >50% 的和「不感兴趣」的不再出现;
- 热门对谁都一样;竖屏流只有竖屏;排行榜按互动分;搜索四种排序和筛选;热搜要 24 小时内 ≥5 个不同的人。

视频直接放进库(tests/video_util.fixture_video),转码到发布的全流程在 e2e_video_upload。
跑法:SUPERZ_API=http://127.0.0.1:8013 DATABASE_URL=… REDIS_URL=… python -m tests.e2e_video_feed
"""
import math
import time
from datetime import datetime
from urllib.parse import quote

from tests.util import call
from tests.video_util import clear_rate_limits, fixture_video, person, rand_name, set_coins

# ---- §5.9 的系数,照文档抄(不从服务端 import:复算要独立于被测代码)----
W = {"views": 1, "likes": 5, "coins": 10, "favorites": 8, "comments": 6, "danmaku": 2, "shares": 10}
DECAY_OFFSET, DECAY_POWER = 2, 1.5
FOLLOW_BONUS, ZONE_BONUS = 0.3, 0.15
SCREEN, PER_UP = 20, 2


def recompute(item: dict, ranked_at: datetime) -> float:
    rk = item["rank"]
    inter = sum(rk["counts"][k] * w for k, w in W.items())
    assert inter == rk["interaction"], (item["vid"], rk)
    hours = max(0.0, (ranked_at - datetime.fromisoformat(item["published_at"])).total_seconds()
                / 3600)
    assert math.isclose(hours, rk["hours"], rel_tol=1e-12, abs_tol=1e-9), (hours, rk["hours"])
    hot = inter / (hours + DECAY_OFFSET) ** DECAY_POWER
    assert math.isclose(hot, rk["hot"], rel_tol=1e-12, abs_tol=1e-15), (hot, rk["hot"])
    rec = hot * (1 + FOLLOW_BONUS * rk["followed"] + ZONE_BONUS * rk["top_zone"])
    assert math.isclose(rec, rk["recommend"], rel_tol=1e-12, abs_tol=1e-15), (rec, rk)
    return rec


def check_page(out: dict, key: str) -> None:
    """一页里每条都能复算,而且按分数从高到低(同分按发布时间新的在前)。"""
    ranked_at = datetime.fromisoformat(out["ranked_at"])
    prev = None
    for it in out["items"]:
        rec = recompute(it, ranked_at)
        val = rec if key == "recommend" else it["rank"]["hot"]
        cur = (val, datetime.fromisoformat(it["published_at"]))
        if prev is not None:
            assert (cur[0] < prev[0] or math.isclose(cur[0], prev[0], rel_tol=1e-12)) and \
                (not math.isclose(cur[0], prev[0], rel_tol=1e-12) or cur[1] <= prev[1]), \
                f"顺序不对:{prev} → {cur}"
        prev = cur


def all_pages(path: str, token: str | None = None, max_pages: int = 10) -> list[dict]:
    out, page = [], 0
    while page < max_pages:
        r = call("GET", f"{path}{'&' if '?' in path else '?'}page={page}", token)
        out.append(r)
        if not r["has_more"]:
            break
        page += 1
    return out


def same_minute(fn):
    """两次请求落在同一分钟里(「现在」按分钟取整),跨分钟了就重来一次。"""
    for _ in range(3):
        a, b = fn()
        if a["ranked_at"] == b["ranked_at"]:
            return a, b
        time.sleep(1)
    raise AssertionError("连续三次跨分钟,取不到同一分钟的两份结果")


def interact(viewers, vid: str, part_id: int, *, likes=0, coins=0, favs=0, comments=0,
             danmaku=0, shares=0, views=0) -> None:
    for i, p in enumerate(viewers):
        clear_rate_limits("video_act", p.id)
        if i < likes:
            p.post(f"/video/v1/videos/{vid}/like", {"like": True})
        if i < coins:
            p.post(f"/video/v1/videos/{vid}/coin", {"amount": 1})
        if i < favs:
            p.post(f"/video/v1/videos/{vid}/favorite")
        if i < comments:
            clear_rate_limits("video_comment", p.id)
            p.post(f"/video/v1/videos/{vid}/comments", {"text": f"第 {i} 条评论"})
        if i < danmaku:
            clear_rate_limits("danmaku", p.id)
            p.post(f"/video/v1/parts/{part_id}/danmaku", {"time_ms": 1000 + i, "text": "弹幕"})
        if i < shares:
            p.post(f"/video/v1/videos/{vid}/share", {"channel": "link"})
        if i < views:
            p.post(f"/video/v1/videos/{vid}/view", {"part_id": part_id, "position_ms": 6000,
                                                     "played_ms": 6000})


def main():
    token = rand_name("tok")  # 这次运行独有的词,标题 / 标签里带着,搜索和热搜用
    u1, u2, u3, u4 = person(), person(), person(), person()
    viewers = [person() for _ in range(6)]
    for p in viewers:
        set_coins(p.id, 20)
    # U1:5 个视频,互动最多(不去重的话会霸占第一屏的前 5 名)
    v1 = [fixture_video(u1.id, title=f"{token} 甲{i}", zone="tech", hours_ago=1 + i * 0.1,
                        tags=["科技", token]) for i in range(5)]
    v2 = [fixture_video(u2.id, title=f"乙的视频 {i}", zone="life", hours_ago=2 + i,
                        description=f"简介里有 {token}") for i in range(3)]
    v3v = fixture_video(u3.id, title="竖屏的", zone="funny", vertical=True, hours_ago=3)
    v3h = fixture_video(u3.id, title="横屏的", zone="funny", vertical=False, hours_ago=3)
    v4 = [fixture_video(u4.id, title=f"游戏 {i}", zone="game", hours_ago=5,
                        duration_ms=15 * 60_000) for i in range(2)]
    for i, v in enumerate(v1):
        interact(viewers, v["vid"], v["part_id"], likes=6 - i, coins=3, favs=2, comments=2,
                 danmaku=2, shares=1, views=6)
    interact(viewers, v2[0]["vid"], v2[0]["part_id"], likes=2, views=3)
    interact(viewers, v3v["vid"], v3v["part_id"], likes=1, views=2)
    interact(viewers, v4[0]["vid"], v4[0]["part_id"], likes=1, danmaku=1, views=1)
    print(f"  造了 13 个视频(U1 有 5 个互动最多)、6 个观众的互动;本次的词:{token}")

    # ---- §5.9 逐条复算 + 顺序 ----
    pages = all_pages("/video/v1/feed/recommend")
    for out in pages:
        check_page(out, "recommend")
        assert out["personalized"] is False
    first = pages[0]["items"]
    got = next(x for x in first if x["vid"] == v1[0]["vid"])
    assert got["rank"]["counts"] == {"views": 6, "likes": 6, "coins": 3, "favorites": 2,
                                     "comments": 2, "danmaku": 2, "shares": 1}, got["rank"]
    assert got["rank"]["interaction"] == 6 + 30 + 30 + 16 + 12 + 4 + 10
    assert any("互动分" in w for w in got["why"]), got["why"]
    print(f"  ✓ §5.9:{sum(len(p['items']) for p in pages)} 条推荐逐条复算一致(互动分、热度、推荐分),"
          "顺序按分数;七种互动按人去重")

    # ---- 同一个 UP 主一屏最多 2 个 ----
    for out in pages:
        per = {}
        for it in out["items"]:
            per[it["uploader"]["id"]] = per.get(it["uploader"]["id"], 0) + 1
        assert max(per.values()) <= PER_UP, per
        assert len(out["items"]) <= SCREEN
    where = {x["vid"]: i for i, out in enumerate(pages) for x in out["items"]}
    assert [where[v["vid"]] for v in v1] == [0, 0, 1, 1, 2], \
        f"U1 的 5 个视频应该按 2 / 2 / 1 分到三屏:{[where.get(v['vid']) for v in v1]}"
    print("  ✓ 去重:同一个 UP 主一屏最多 2 个,U1 的 5 个按分数顺延成 2 / 2 / 1")

    # ---- S9:关掉个性化 = 和没登录一模一样 ----
    p = person()
    p.post(f"/video/v1/users/{u2.id}/follow")
    p.post(f"/video/v1/videos/{v4[1]['vid']}/view",
           {"part_id": v4[1]["part_id"], "position_ms": 60_000, "played_ms": 60_000})
    watched = v1[1]
    p.post(f"/video/v1/videos/{watched['vid']}/view",
           {"part_id": watched["part_id"], "position_ms": 45_000, "played_ms": 45_000})
    p.post(f"/video/v1/videos/{v2[1]['vid']}/not-interested")
    on_pages = all_pages("/video/v1/feed/recommend", p.token)
    on = [x for out in on_pages for x in out["items"]]
    assert on_pages[0]["personalized"] is True
    for out in on_pages:
        check_page(out, "recommend")
    on_by = {x["vid"]: x for x in on}
    assert watched["vid"] not in on_by, "看过 >50% 的 7 天内不再推"
    assert v2[1]["vid"] not in on_by, "不感兴趣的不再推"
    for v in v2:
        if v["vid"] in on_by:
            assert on_by[v["vid"]]["rank"]["followed"] is True
            assert any("关注" in w for w in on_by[v["vid"]]["why"])
    g = on_by[v4[0]["vid"]]
    assert g["rank"]["top_zone"] is True and any("常看" in w for w in g["why"]), g
    assert on_by[v1[0]["vid"]]["rank"]["followed"] is False
    print("  ✓ 个性化开着:关注的 UP 主 ×(1+0.3)、常看分区 +0.15、看过 >50% 的和不感兴趣的不出现,都能复算")

    p.patch("/video/v1/me/settings", {"personalize": False})
    assert p.get("/video/v1/me/settings")["personalize"] is False
    anon, off = same_minute(lambda: (call("GET", "/video/v1/feed/recommend"),
                                     call("GET", "/video/v1/feed/recommend", p.token)))
    assert off["personalized"] is False
    assert off["items"] == anon["items"], "S9:关掉个性化之后,推荐和没登录的人看到的必须逐条相等"
    assert [x["vid"] for x in off["items"]] == [x["vid"] for x in anon["items"]]
    assert watched["vid"] in {x["vid"] for out in all_pages("/video/v1/feed/recommend", p.token)
                              for x in out["items"]}, "关掉之后看过的也不再过滤(否则就不是一模一样)"
    for pg in range(1, len(pages)):
        a2, o2 = same_minute(lambda: (call("GET", f"/video/v1/feed/recommend?page={pg}"),
                                      call("GET", f"/video/v1/feed/recommend?page={pg}", p.token)))
        assert a2["items"] == o2["items"], f"第 {pg} 屏也要逐条相等"
    print(f"  ✓ S9:关掉个性化后 {len(pages)} 屏推荐和没登录的人逐条相等")

    # ---- 热门:谁看都一样;竖屏流只有竖屏 ----
    p.patch("/video/v1/me/settings", {"personalize": True})
    h_anon, h_p = same_minute(lambda: (call("GET", "/video/v1/feed/hot"),
                                       call("GET", "/video/v1/feed/hot", p.token)))
    assert h_anon["items"] == h_p["items"] and h_anon["sort"] == "hot"
    check_page(h_anon, "hot")
    vert = [x for out in all_pages("/video/v1/feed/vertical") for x in out["items"]]
    assert vert and all(x["is_vertical"] for x in vert), "竖屏流只取竖屏视频"
    assert v3v["vid"] in {x["vid"] for x in vert} and v3h["vid"] not in {x["vid"] for x in vert}
    print("  ✓ 热门不个性化(登录没登录一样)、按热度复算;竖屏流只有宽 < 高的")

    # ---- 分区、排行榜、相关 ----
    zones = {z["zone"]: z for z in call("GET", "/video/v1/zones")["items"]}
    assert zones["tech"]["count"] >= 5 and zones["tech"]["name"] == "科技"
    zt = call("GET", "/video/v1/zones/tech?order=new")
    assert zt["items"] and all(x["zone"] == "tech" for x in zt["items"])
    assert call("GET", "/video/v1/zones/nope", expect_error=True).get("_error") == 404
    lb = call("GET", "/video/v1/rank?days=1")
    scores = [x["rank"]["interaction"] for x in lb["items"]]
    assert scores == sorted(scores, reverse=True) and scores[0] > 0
    for x in lb["items"]:
        assert x["rank"]["interaction"] == sum(x["rank"]["counts"][k] * w for k, w in W.items())
    assert lb["items"][0]["vid"] == v1[0]["vid"], "U1 的第一个视频互动最多"
    assert [x["position"] for x in lb["items"]] == list(range(1, len(lb["items"]) + 1))
    lg = call("GET", "/video/v1/rank?zone=game&days=7")
    assert lg["items"] and all(x["zone"] == "game" for x in lg["items"])
    assert call("GET", "/video/v1/rank?days=2", expect_error=True).get("_error") == 422
    rel = call("GET", f"/video/v1/videos/{v1[0]['vid']}/related")
    rel_vids = {x["vid"] for x in rel["items"]}
    assert {v["vid"] for v in v1[1:]} <= rel_vids and v1[0]["vid"] not in rel_vids
    formula = call("GET", "/video/v1/rank/formula")
    assert formula["weights"] == W and "互动分 ÷ (发布后的小时数 + 2) ^ 1.5" in formula["formula"]
    print("  ✓ 分区(计数、只含本分区)、排行榜(互动分从高到低、名次、分区筛选、窗口只能 1/3/7)、相关(同 UP 主优先)、公式原文")

    # ---- 搜索:标题 / 标签 / 简介 / UP 主名;四种排序;时长、分区筛选 ----
    s = call("GET", f"/video/v1/search?q={token}")
    vids = [x["vid"] for x in s["items"]]
    assert {v["vid"] for v in v1} <= set(vids) and {v["vid"] for v in v2} <= set(vids), vids
    assert vids.index(v1[0]["vid"]) < vids.index(v2[0]["vid"]), "综合:标题命中排在简介命中前面"
    sv = call("GET", f"/video/v1/search?q={token}&order=views")["items"]
    assert [x["views"] for x in sv] == sorted([x["views"] for x in sv], reverse=True)
    sd = call("GET", f"/video/v1/search?q={token}&order=danmaku")["items"]
    assert [x["danmaku_count"] for x in sd] == sorted([x["danmaku_count"] for x in sd], reverse=True)
    sn = call("GET", f"/video/v1/search?q={token}&order=new")["items"]
    stamps = [x["published_at"] for x in sn]
    assert stamps == sorted(stamps, reverse=True)
    assert {x["vid"] for x in call("GET", f"/video/v1/search?q={token}&zone=life")["items"]} == \
        {v["vid"] for v in v2}
    assert call("GET", f"/video/v1/search?q={token}&duration=2")["items"] == [], "10–30 分钟的没有"
    long = call("GET", f"/video/v1/search?q={quote('游戏')}&duration=2")["items"]
    assert {v["vid"] for v in v4} <= {x["vid"] for x in long}, "15 分钟的在 10–30 分钟档"
    name = rand_name("搜我")
    u5 = person()
    call("PATCH", "/auth/me", u5.token, {"name": name})
    fixture_video(u5.id, title="普通标题", zone="life")
    su = call("GET", f"/video/v1/search?q={quote(name)}")["items"]
    assert su and su[0]["uploader"]["id"] == u5.id, "按 UP 主名搜得到"
    users = call("GET", f"/video/v1/search/users?q={quote(name)}")["items"]
    assert users and users[0]["id"] == u5.id and users[0]["videos"] == 1 and "phone" not in users[0]
    print("  ✓ 搜索:标题 / 标签 / 简介 / UP 主名都能搜到;综合、播放、最新、弹幕四种排序;分区和时长筛选;用户搜索")

    # ---- 热搜:24 小时内至少 5 个不同的人 ----
    hot_term, cold_term = rand_name("热词"), rand_name("冷词")
    for q in viewers[:5]:
        call("GET", f"/video/v1/search?q={quote(hot_term)}", q.token)
        call("GET", f"/video/v1/search?q={quote(hot_term)}", q.token)   # 同一个人搜两遍只算一次
    for q in viewers[:4]:
        call("GET", f"/video/v1/search?q={quote(cold_term)}", q.token)
    for _ in range(10):
        call("GET", f"/video/v1/search?q={quote(cold_term)}")   # 没登录的不算「不同的人」
    hot = call("GET", "/video/v1/search/hot")
    terms = {x["term"]: x["users"] for x in hot["items"]}
    assert terms.get(hot_term.lower()) == 5, terms
    assert cold_term.lower() not in terms, "4 个人不够上热搜(防刷)"
    print("  ✓ 热搜:5 个不同的人上榜(同一个人搜两遍算一个);4 个人、再加 10 次匿名搜索都不上榜")

    # ---- 关注流 ----
    fl = p.get("/video/v1/feed/following")["items"]
    assert fl and {x["uploader"]["id"] for x in fl} == {u2.id}
    stamps = [x["published_at"] for x in fl]
    assert stamps == sorted(stamps, reverse=True)
    print("  ✓ 关注流:只有关注的 UP 主,新发布的在前")
    print("e2e_video_feed 全部通过 ✅")


if __name__ == "__main__":
    main()
