"""论坛:两条时间线、公开公式、个性化开关、拉黑与屏蔽词过滤、热门话题、话题页、搜索
(DEV-PROMPTS-41 §5.7、§8.3,#380)。

这组守的是:
- 推荐每条带 `rank`(score + parts + why),**拿计算器能复算**;
- **关掉个性化后,推荐结果和没登录的人逐条相等**(§5.7「两个方括号都按 0 算」);
- 每屏 20 条、同一作者最多 2 条;
- 关注时间线含转发,按事件时间倒序、cursor 翻页;
- 双向拉黑、屏蔽词从时间线 / 话题页 / 搜索里滤掉;
- 热门话题按**人数**算(一个人自己刷不出来),运营隐藏的不上榜但话题页照样能打开。

    . "$(bash scripts/e2e_iso.sh env 2)" && cd server && python -m tests.e2e_forum_timeline
"""
import math
import urllib.parse

from tests.forum_util import (admin_token, age_post, call, clear_rate_limits, person, post,
                              set_flag, timeline_pids)


def foryou_item(who, pid: str, pages: int = 8) -> dict | None:
    """在推荐里翻几页找这一条,找不到给 None。

    库里帖子越积越多(全量回归时前面的套件也在发帖),要找的那条不一定落在第一屏 ——
    断言「它在第一屏」等于断言「库是空的」,那个用例迟早会因为别人加了帖子而红。
    反过来「不在第一屏」也不等于「过滤掉了」,所以正反两种断言都走这里翻页。
    """
    for page in range(pages):
        out = (who.get(f"/forum/v1/timeline/foryou?page={page}") if who is not None
               else call("GET", f"/forum/v1/timeline/foryou?page={page}"))
        for it in out["items"]:
            if it["post"]["pid"] == pid:
                return it
        if not out["has_more"]:
            break
    return None


def find_in_foryou(who, pid: str, pages: int = 8) -> dict:
    it = foryou_item(who, pid, pages)
    assert it is not None, f"推荐里翻了 {pages} 页也没找到 {pid}"
    return it


def main() -> None:
    a, b, c, d = person("137"), person("137"), person("137"), person("137")

    # ---------- 公式公开 ----------
    f = call("GET", "/forum/v1/rank/formula")
    assert "推荐分 = (E + 1) ÷ (发帖后小时数 + 2)^1.5" in f["formula"], f["formula"]
    assert f["params"]["window_hours"] == 72 and f["params"]["decay_power"] == 1.5, f["params"]
    assert f["params"]["reply_weight"] == 3 and f["params"]["follow_bonus"] == 1
    print("✓ /rank/formula 把公式和全部参数原样下发")

    # ---------- 推荐:每条带中间量,能手算复核 ----------
    p1 = post(a, "第一条 #天气")
    p2 = post(a, "第二条")
    p3 = post(b, "别人的一条")
    age_post(p1["pid"], 7)                       # 发帖 7 小时前
    # **点赞的人不能是等会儿要看推荐的那个** —— 点过赞的话题会给他 topic 加权,基准就不干净了
    liker = person("137")
    for who in (b, c, liker):
        clear_rate_limits("forum_act", who.id)
        who.post(f"/forum/v1/posts/{p1['pid']}/like")
    c.post(f"/forum/v1/posts/{p1['pid']}/repost")

    item = find_in_foryou(d, p1["pid"])
    parts = item["rank"]["parts"]
    assert parts["likes"] == 3 and parts["reposts"] == 1, parts
    assert parts["e"] == 3 + 2 * 1 == 5, parts
    assert 6.9 <= parts["hours"] <= 7.2, parts
    # 推荐分 = (E + 1) ÷ (小时数 + 2)^1.5,没关注、没共同话题时两个方括号都是 0
    want = (parts["e"] + 1) / (parts["hours"] + 2) ** 1.5
    assert math.isclose(item["rank"]["score"], want, rel_tol=1e-9), (item["rank"], want)
    assert "互动分 5" in item["rank"]["why"], item["rank"]["why"]
    print("✓ 推荐每条带 rank.parts 和 why,分数拿计算器能复算")

    # ---------- 关注 + 话题的两个加权 ----------
    d.post(f"/social/v1/users/{a.id}/follow")
    post(d, "我也聊 #天气")                        # 我近 30 天用过「天气」这个话题
    item = find_in_foryou(d, p1["pid"])
    assert item["rank"]["parts"]["following"] is True, item["rank"]
    assert item["rank"]["parts"]["topic"] is True, item["rank"]
    assert math.isclose(item["rank"]["score"], want * 2 * 1.5, rel_tol=1e-9), item["rank"]
    assert "你关注了作者" in item["rank"]["why"], item["rank"]["why"]
    print("✓ 关注了作者 × 2、有我用过的话题 × 1.5,why 里写明白")

    # ---------- 关掉个性化:和没登录的人逐条相等 ----------
    assert d.put("/forum/v1/me/settings", {"personalize": False}) == {"personalize": False}
    off = d.get("/forum/v1/timeline/foryou")
    anon = call("GET", "/forum/v1/timeline/foryou")
    assert off["personalized"] is False and anon["personalized"] is False
    assert timeline_pids(off) == timeline_pids(anon), "关掉个性化后和没登录看到的不一样"
    item = find_in_foryou(d, p1["pid"])
    assert math.isclose(item["rank"]["score"], want, rel_tol=1e-9), \
        "关掉个性化后两个方括号没按 0 算"
    d.put("/forum/v1/me/settings", {"personalize": True})
    print("✓ 关掉个性化后推荐和没登录的人逐条相等,两个加权都按 0 算")

    # ---------- 一屏 20 条、同一作者最多 2 条 ----------
    for i in range(6):
        post(c, f"刷屏 {i}")
    screen = call("GET", "/forum/v1/timeline/foryou")
    assert len(screen["items"]) <= 20, len(screen["items"])
    authors = [it["post"]["author"]["id"] for it in screen["items"]]
    assert authors.count(c.id) <= 2, f"同一作者一屏超过 2 条:{authors}"
    print("✓ 一屏 20 条、同一作者最多 2 条")

    # ---------- 关注时间线:含转发,按事件时间倒序 ----------
    follower = person("137")
    follower.post(f"/social/v1/users/{a.id}/follow")
    tl = follower.get("/forum/v1/timeline/following")
    assert p2["pid"] in timeline_pids(tl) and p1["pid"] in timeline_pids(tl), tl
    clear_rate_limits("forum_act", a.id)
    a.post(f"/forum/v1/posts/{p3['pid']}/repost")     # 我关注的 a 转发了 b 的帖子
    tl = follower.get("/forum/v1/timeline/following")
    repost_item = next(it for it in tl["items"] if it["type"] == "repost")
    assert repost_item["by"]["id"] == a.id and repost_item["post"]["pid"] == p3["pid"], repost_item
    assert repost_item["at"], repost_item
    assert tl["items"][0] is repost_item or tl["items"][0]["post"]["pid"] == p3["pid"], \
        "刚转的应该在最前面"
    # 谁也没关注的人:空时间线
    assert person("137").get("/forum/v1/timeline/following")["items"] == []
    print("✓ 关注时间线:自己发的和转发的都在,按事件时间倒序")

    # cursor 翻页
    page1 = follower.get("/forum/v1/timeline/following?cursor=")
    if page1["next_cursor"]:
        page2 = follower.get(
            f"/forum/v1/timeline/following?cursor={urllib.parse.quote(page1['next_cursor'])}")
        assert not (set(timeline_pids(page1)) & set(timeline_pids(page2))), "翻页翻出重复的"
    print("✓ 关注时间线按 cursor 翻页,前后两页不重复")

    # ---------- 双向拉黑 ----------
    hater = person("137")
    hated = post(hater, "拉黑测试的帖子")
    assert foryou_item(hater, hated["pid"]) is not None, "自己发的帖子自己都看不到?"
    a.post("/social/v1/blocks", {"user_id": hater.id})
    assert foryou_item(a, hated["pid"]) is None, "拉黑的人还在我的推荐里"
    r = a.get(f"/forum/v1/posts/{hated['pid']}", expect_error=True)
    assert r.get("_error") == 404, r
    # 反过来也看不到:我拉黑了他,他也看不到我的
    mine = post(a, "拉黑之后发的")
    assert foryou_item(hater, mine["pid"]) is None, "被我拉黑的人还看得到我的帖子"
    print("✓ 拉黑是双向的:推荐里没有,直接点开 404")

    # ---------- 屏蔽词 ----------
    noisy = post(b, "有人在聊球赛结果")
    reader = person("137")
    assert reader.post("/forum/v1/me/mute-words", {"word": "球赛"}) == ["球赛"]
    assert foryou_item(reader, noisy["pid"]) is None, "屏蔽词没把帖子滤掉"
    assert foryou_item(None, noisy["pid"]) is not None, "屏蔽词只该对我自己生效"
    assert reader.delete(f"/forum/v1/me/mute-words?word={urllib.parse.quote('球赛')}") == []
    assert foryou_item(reader, noisy["pid"]) is not None, "删掉屏蔽词还看不到"
    print("✓ 屏蔽词只对我生效,删掉就又看得到")

    # ---------- 热门话题:按人数算 ----------
    tag = f"话题{a.id}"
    post(a, f"#{tag} 一")
    post(a, f"#{tag} 二")                             # 同一个人发两条,还是 1 个人
    trending = call("GET", "/forum/v1/tags/trending")["items"]
    assert not [t for t in trending if t["tag"] == tag], "一个人自己就把话题刷上榜了"
    post(b, f"#{tag} 三")
    trending = call("GET", "/forum/v1/tags/trending")["items"]
    hot = next(t for t in trending if t["tag"] == tag)
    assert hot["authors_24h"] == 2 and hot["authors_3h"] == 2, hot
    assert hot["score"] == 2 + 2 * 2 == 6, hot
    assert len(trending) <= 20
    print("✓ 热门话题按人数算:同一个人发两条还是 1 个人,分数 = 24h + 2 × 3h")

    # 运营隐藏:不上榜,但话题页照样能打开
    call("POST", f"/admin/forum/tags/{urllib.parse.quote(tag)}/hide", admin_token(),
         {"reason_code": "F402", "note": "蹭无关话题"})
    assert not [t for t in call("GET", "/forum/v1/tags/trending")["items"] if t["tag"] == tag], \
        "隐藏了还在热门榜上"
    page = call("GET", f"/forum/v1/tags/{urllib.parse.quote(tag)}/posts")
    assert page["hidden"] is True and len(page["items"]) == 3, page
    call("POST", f"/admin/forum/tags/{urllib.parse.quote(tag)}/unhide", admin_token())
    assert [t for t in call("GET", "/forum/v1/tags/trending")["items"] if t["tag"] == tag]
    print("✓ 运营隐藏的话题不上热门榜,但话题页照样能打开、帖子照样在")

    # ---------- 话题页两种排序 ----------
    top = call("GET", f"/forum/v1/tags/{urllib.parse.quote(tag)}/posts?sort=top")["items"]
    new = call("GET", f"/forum/v1/tags/{urllib.parse.quote(tag)}/posts?sort=new")["items"]
    assert len(top) == len(new) == 3
    assert [x["created_at"] for x in new] == sorted([x["created_at"] for x in new], reverse=True)
    print("✓ 话题页按赞 / 按时间两种排序")

    # ---------- 搜索 ----------
    needle = f"独一无二的词{a.id}"
    found = post(a, f"这里有{needle}")
    res = call("GET", f"/forum/v1/search?q={urllib.parse.quote(needle)}")
    assert [x["pid"] for x in res["items"]] == [found["pid"]], res
    users = call("GET", f"/forum/v1/search?q={urllib.parse.quote(a.name)}&type=users")
    assert any(x["id"] == a.id for x in users["items"]), users
    tags = call("GET", f"/forum/v1/search?q={urllib.parse.quote(tag)}&type=tags")
    assert any(t["tag"] == tag for t in tags["items"]), tags
    assert call("GET", "/forum/v1/search?q=")["items"] == []
    print("✓ 搜索:帖子 / 用户 / 话题三种,空关键词不返回全站")

    # ---------- 开关:关了全部 503,发帖闸只停写 ----------
    set_flag("forum_post_enabled", "off")
    try:
        r = post(a, "发帖闸关着", expect_error=True)
        assert r.get("_error") == 503 and "论坛发帖暂停中" in str(r.get("detail")), r
        assert call("GET", "/forum/v1/timeline/foryou")["items"] is not None, "只停笔,看还能看"
    finally:
        set_flag("forum_post_enabled", None)
    set_flag("forum_enabled", "off")
    try:
        r = call("GET", "/forum/v1/timeline/foryou", expect_error=True)
        assert r.get("_error") == 503 and "论坛暂未开放" in str(r.get("detail")), r
        r = call("GET", "/forum/v1/rank/formula", expect_error=True)
        assert r.get("_error") == 503, "公式接口也该跟着停"
    finally:
        set_flag("forum_enabled", None)
    assert call("GET", "/forum/v1/rank/formula")["params"]
    print("✓ 两道闸:forum_enabled 关了全部 503,forum_post_enabled 只停发帖")

    print("\ne2e_forum_timeline 全部通过 ✅")


if __name__ == "__main__":
    main()
