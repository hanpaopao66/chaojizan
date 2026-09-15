"""全站统一关注(DEV-PROMPTS-41 #377):视频、论坛、音乐共用一张 follows 表,接口在 /social/v1。

这组守的是:
- **不挂模块开关** —— 以前关注挂在 /video/v1 下,视频一关连关注都 503;
- 被关注的人收到 `follow` 互动消息,**一天的新粉丝合并成一行**,重复点关注不重复记;
- 视频的老接口和新接口写的是同一个关系;
- 不能关注自己、有拉黑关系不能关注。

    SUPERZ_API=http://127.0.0.1:8010 python -m tests.e2e_social_follow
"""
from tests.chat_util import person
from tests.video_util import set_flag


def follows(p, uid: int) -> dict:
    return p.post(f"/social/v1/users/{uid}/follow")


def main() -> None:
    a, b, c, d = person("137"), person("137"), person("137"), person("137")

    # ---------- 视频开关关着也能关注 ----------
    set_flag("video_enabled", "off")
    try:
        out = follows(a, b.id)
        assert out == {"followed": True, "fans": 1}, out
    finally:
        set_flag("video_enabled", None)
    print("✓ 视频开关关着,/social/v1 照样能关注")

    # ---------- 互动消息:follow,一天合并成一行 ----------
    n1 = b.get("/social/v1/notifications?kind=follow")["items"]
    assert len(n1) == 1 and n1[0]["actor"]["id"] == a.id, n1
    assert n1[0]["title"] == f"{a.name} 关注了你", n1[0]["title"]
    assert b.get("/social/v1/notifications/unread")["follow"] == 1
    follows(a, b.id)  # 已经关注着再点一次:不重复记
    assert b.get("/social/v1/notifications?kind=follow")["items"][0]["count"] == 1
    follows(c, b.id)
    n2 = b.get("/social/v1/notifications?kind=follow")["items"]
    assert len(n2) == 1 and n2[0]["count"] == 2 and n2[0]["actor"]["id"] == c.id, n2
    assert n2[0]["title"] == f"{c.name}等 2 人关注了你", n2[0]["title"]
    print("✓ 被关注收到 follow 互动消息;同一天的新粉丝合并成一行,重复点不重复记")

    # ---------- 视频老接口写的是同一个关系 ----------
    b.post(f"/video/v1/users/{a.id}/follow", {"follow": True})
    st = a.get(f"/social/v1/users/{b.id}/follow-stats")
    assert st == {"fans": 2, "following": 1, "followed": True, "follows_you": True}, st
    fans = [x["id"] for x in call_list(d, f"/social/v1/users/{b.id}/followers")]
    assert set(fans) == {a.id, c.id}, fans
    following = [x["id"] for x in call_list(d, f"/social/v1/users/{b.id}/following")]
    assert following == [a.id], following
    print("✓ 视频老接口和新接口是同一张表:粉丝 / 关注列表、关注关系都对得上")

    # ---------- 不能关注自己;拉黑了不能关注 ----------
    r = a.post(f"/social/v1/users/{a.id}/follow", expect_error=True)
    assert r.get("_error") == 422, r
    b.post("/social/v1/blocks", {"user_id": d.id})
    r = d.post(f"/social/v1/users/{b.id}/follow", expect_error=True)
    assert r.get("_error") == 403, f"被拉黑了还能关注:{r}"
    r = a.post("/social/v1/users/999999999/follow", expect_error=True)
    assert r.get("_error") == 404, r
    print("✓ 关注自己 422、被拉黑 403、没有这个人 404")

    # ---------- 取消关注 ----------
    out = a.delete(f"/social/v1/users/{b.id}/follow")
    assert out == {"followed": False, "fans": 1}, out
    assert a.get(f"/social/v1/users/{b.id}/follow-stats")["followed"] is False
    print("✓ 取消关注:粉丝数跟着变")

    print("\ne2e_social_follow 全部通过 ✅")


def call_list(p, path: str) -> list[dict]:
    return p.get(path)["items"]


if __name__ == "__main__":
    main()
