"""分享卡片消息(DEV-PROMPTS-41 §5.9):把歌、歌单、动态、视频分享进聊天。

这组守的是**「标题和封面由服务端查、不信客户端」**:

- 客户端只发 `{type, id}`,服务端查出来存快照 —— 不然谁都能发一张「超级赞官方」的假卡片;
- 看不到的东西分享不出去:没过审的作品、私密歌单、删了的帖子一律 422;
- 转发带着卡片走(快照已经在消息里,不用重查);
- 会话列表那一行写得出分享的是什么(`[歌曲] 晚风`)。

    SUPERZ_API=http://127.0.0.1:8010 python -m tests.e2e_chat_card
"""
from tests.chat_util import Person, person
from tests.music_util import artist, publish_release, tone, upload_audio, new_release, add_track
from tests.util import call


def send_card(p: Person, chat_id: int, type_: str, id_: str, *, expect_error: bool = False):
    return p.send(chat_id, kind="card", card={"type": type_, "id": id_}, expect_error=expect_error)


def main() -> None:
    a, b = person("137"), person("137")
    chat = a.private_with(b)["id"]

    # ---------- 歌:公开的能分享,快照是服务端查的 ----------
    musician, _ = artist()
    rel = publish_release(musician, title="分享测试专辑")
    tid = rel["tracks"][0]["tid"]
    song = musician.get(f"/music/v1/tracks/{tid}")["title"]
    m = send_card(a, chat, "track", tid)
    card = m["card"]
    assert card["type"] == "track" and card["id"] == tid, card
    assert card["title"] == song, f"标题不是服务端查出来的:{card}"
    assert card["url"].endswith(f"/music/t/{tid}"), card
    print("✓ 分享一首歌:服务端把标题、封面、链接查出来存进消息")

    # 客户端自己编的标题不作数:发的时候只认 {type, id}
    m2 = a.send(chat, kind="card",
                card={"type": "track", "id": tid, "title": "超级赞官方公告", "cover": "http://evil/x.jpg"})
    assert m2["card"]["title"] == song and "evil" not in str(m2["card"]), m2["card"]
    print("✓ 客户端塞的标题和封面被忽略,假卡片发不出来")

    # ---------- 会话列表那一行 ----------
    rows = b.get("/chat/v1/dialogs")["items"]
    row = next(c for c in rows if c["id"] == chat)
    assert row["last_message"]["card"]["title"] == song, row["last_message"]
    print("✓ 收件人看到的是同一份快照")

    # ---------- 动态 ----------
    post = a.post("/forum/v1/posts", {"text": "今天的面很好吃"})
    mp = send_card(a, chat, "post", post["pid"])
    assert mp["card"]["title"].startswith("今天的面"), mp["card"]
    print("✓ 分享一条动态")

    # ---------- 分享不出去的:没过审、不存在、不认识的类型 ----------
    from tests.music_util import wait_ready
    draft_rid = new_release(musician, title="没过审的")["rid"]
    src = upload_audio(musician, tone(hz=520), "draft.wav")
    add_track(musician, draft_rid, src["id"], title="草稿")
    draft = wait_ready(musician, draft_rid)
    r = send_card(a, chat, "track", draft["tracks"][0]["tid"], expect_error=True)
    assert r.get("_error") == 422, f"没过审的歌居然分享出去了:{r}"
    r = send_card(a, chat, "track", "mt0000000000", expect_error=True)
    assert r.get("_error") == 422, r
    r = send_card(a, chat, "merchant", "1", expect_error=True)
    assert r.get("_error") == 422, f"不认识的类型也收了:{r}"
    print("✓ 没过审的、不存在的、不认识的类型:422")

    # ---------- 删了的动态:已经发出去的消息还在,新的分享不出去 ----------
    a.delete(f"/forum/v1/posts/{post['pid']}")
    r = send_card(a, chat, "post", post["pid"], expect_error=True)
    assert r.get("_error") == 422, r
    print("✓ 帖子删了之后再分享:422")

    # ---------- 转发:卡片跟着走 ----------
    c = person("137")
    chat2 = a.private_with(c)["id"]
    a.post(f"/chat/v1/chats/{chat}/messages/forward",
           {"seqs": [m["seq"]], "to_chat_ids": [chat2]})
    msgs = c.get(f"/chat/v1/chats/{chat2}/messages")["messages"]
    got = [x for x in msgs if x["kind"] == "card"]
    assert got and got[0]["card"]["title"] == song, got
    print("✓ 转发带着卡片走")

    print("\ne2e_chat_card 全部通过 ✅")


if __name__ == "__main__":
    main()
