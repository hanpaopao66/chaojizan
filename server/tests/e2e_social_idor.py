"""越权 / IDOR 的补漏(DEV-PROMPTS-40 #373):别人的草稿、分片上传、媒体状态、投稿、私密收藏夹。

S1(消息、事件、媒体、已读名单)在 e2e_chat_private / e2e_media 里已经逐项断言;这里补的是那几个
「拿着别人的编号直接调接口」的口子,每一条都应该是 403 / 404,而且响应里不能透出对方的东西。

跑法:SUPERZ_API=http://127.0.0.1:8013 DATABASE_URL=… python -m tests.e2e_social_idor
"""
from tests.chat_util import person
from tests.e2e_media import png_bytes, raw, upload
from tests.video_util import new_video, realname


def code(r) -> int | None:
    return r.get("_error") if isinstance(r, dict) else None


def main():
    a, b, c = person(), person(), person()
    print(f"  账号:A={a.id} B={b.id} C={c.id}")

    # ---- 草稿:别人会话的「我的会话设置」改不了 ----
    cid = a.private_with(b)["id"]
    r = c.patch(f"/chat/v1/dialogs/{cid}", {"draft": {"text": "偷偷写一句"}}, expect_error=True)
    assert code(r) in (403, 404), f"不在会话里的人改草稿:{r}"
    a.patch(f"/chat/v1/dialogs/{cid}", {"draft": {"text": "A 的草稿"}})
    card_b = b.get(f"/chat/v1/chats/{cid}")
    assert "A 的草稿" not in str(card_b), "草稿是各人自己的,对方看不到"
    print("  ✓ 草稿:会话外的人改不了;同一个会话里对方也看不到我的草稿")

    # ---- 分片上传:拿着别人的上传编号 ----
    up = a.post("/media/v1/uploads", {"size": 3 * 1024 * 1024, "name": "a.bin", "kind": "file"})
    for path, method in ((f"/media/v1/uploads/{up['id']}", "GET"),
                         (f"/media/v1/uploads/{up['id']}/chunks/0", "PUT")):
        st, _, _ = raw(c, path, method=method, data=b"x" * 16 if method == "PUT" else None)
        assert st == 404, f"{method} 别人的上传:{st}"
    r = c.post(f"/media/v1/uploads/{up['id']}/complete", {"kind": "file"}, expect_error=True)
    assert code(r) == 404, r
    print("  ✓ 分片上传:别人的上传编号查不到、传不进片、完成不了")

    # ---- 媒体状态:别人还没发出去的文件 ----
    ph = upload(a, png_bytes(200, 120), "私密.png", "photo")
    r = c.get(f"/media/v1/media/{ph['id']}", expect_error=True)
    assert code(r) == 404, r
    print("  ✓ 媒体状态:别人没发出来的文件,编号猜中了也是 404")

    # ---- 投稿:别人的稿件改不了、提交不了、删不了、看不到草稿 ----
    realname(a)
    v = new_video(a, title="A 的草稿稿件")
    vid = v["vid"]
    for method, path, body in (("PATCH", f"/video/v1/videos/{vid}", {"title": "被改了"}),
                               ("POST", f"/video/v1/videos/{vid}/submit", {}),
                               ("POST", f"/video/v1/videos/{vid}/parts", {"media_id": ph["id"]}),
                               ("GET", f"/video/v1/creator/videos/{vid}", None),
                               ("DELETE", f"/video/v1/videos/{vid}", None)):
        fn = {"PATCH": c.patch, "POST": c.post, "GET": c.get, "DELETE": c.delete}[method]
        r = fn(path, body, expect_error=True) if body is not None else fn(path, expect_error=True)
        assert code(r) in (403, 404), f"{method} {path}:{r}"
    assert b.get(f"/video/v1/videos/{vid}", expect_error=True).get("_error") == 404, "草稿别人看不到"
    assert a.get(f"/video/v1/creator/videos/{vid}")["title"] == "A 的草稿稿件", "没被改动"
    print("  ✓ 投稿:别人的稿件改、提交、加分 P、看创作中心详情、删除一律 403 / 404;草稿别人看不到")

    # ---- 私密收藏夹 ----
    folders = a.get("/video/v1/me/favorites")
    items = folders["items"] if isinstance(folders, dict) else folders
    private = next(f for f in items if not f.get("public", f.get("is_public", False)))
    for who in (b, None):
        st, _, body = raw(who, f"/video/v1/favorites/{private['id']}")
        assert st == 404, f"私密收藏夹被看到了:{st} {body[:80]!r}"
    r = b.get(f"/video/v1/me/favorites/{private['id']}", expect_error=True)
    assert code(r) == 404, r
    r = b.patch(f"/video/v1/me/favorites/{private['id']}", {"title": "改名"}, expect_error=True)
    assert code(r) == 404, r
    print("  ✓ 收藏夹:私密的别人和没登录的都看不到;别人的收藏夹改不了")


if __name__ == "__main__":
    main()
    print("e2e_social_idor 通过")
