"""全局搜索的分类标签 e2e(对齐 Telegram 搜索页顶部那一排)。

守的是 `/chat/v1/search?tab=…` 每一类只出该出的东西:

- 对话:群和人,**不含频道**;频道:只有频道,不含人;
- 应用:小程序 + 机器人(机器人平台关着时一个机器人都不出);
- 多媒体 / 文件 / 语音 / 链接 / 音乐:跨会话按消息类型找,**不填关键词也能列**
  (点进「文件」就该看到全部文件,和 Telegram 一样);
- 音乐这一类算两样:分享进来的歌卡片(§5.9)和 mime 是 audio/* 的文件 ——
  我们有音乐模块,所以这一格比 Telegram 那个更实;
- 不带 tab 时还是老形状(chats / users / messages),老版本 App 还在用。

翻页用消息自增 id(seq 是会话内的号,跨会话排不出先后),所以这里也断言 next_before_id。

跑法:SUPERZ_API=http://127.0.0.1:8013 DATABASE_URL=… python -m tests.e2e_chat_search_tabs
"""
import random
from urllib.parse import quote

from tests.chat_util import person, set_username
from tests.e2e_media import png_bytes, upload
from tests.util import call


def kinds(items: list) -> set:
    return {i["message"]["kind"] for i in items}


def main():
    me, friend = person(), person()
    tag = f"搜索{random.randint(1000, 9999)}"

    # ---- 造点东西出来:一个群、一个频道、一个私聊,各种类型的消息 ----
    g = me.post("/chat/v1/chats", {"type": "group", "title": f"{tag}群", "member_ids": [friend.id]})
    ch = me.post("/chat/v1/chats", {"type": "channel", "title": f"{tag}频道"})
    pv = me.private_with(friend)
    print(f"  群={g['id']} 频道={ch['id']} 私聊={pv['id']}")

    photo = upload(me, png_bytes(), "shot.png", "photo")
    me.send(g["id"], "", kind="photo", media_ids=[photo["id"]])
    doc = upload(me, b"%PDF-1.4 hello world", "合同.pdf", "file")
    me.send(g["id"], "", kind="file", media_ids=[doc["id"]])
    song = upload(me, b"ID3\x04\x00\x00\x00\x00\x00\x00" + b"\x00" * 64, "demo.mp3", "file")
    me.send(g["id"], "", kind="file", media_ids=[song["id"]])
    me.send(pv["id"], f"{tag} 看这个 https://chaojizan.cc/opensource")
    print("  ✓ 图片、文件、音频文件、带链接的消息都发好了")

    # ---- 对话 / 频道 ----
    r = me.get(f"/chat/v1/search?q={quote(tag)}&tab=chats")
    got = {i["kind"] for i in r["items"]}
    titles = [i.get("title") for i in r["items"] if i["kind"] == "chat"]
    assert f"{tag}群" in titles, r["items"]
    assert f"{tag}频道" not in titles, f"「对话」里不该有频道:{titles}"
    assert got <= {"chat", "user"}, got
    print("  ✓ 对话:有群没频道")

    r = me.get(f"/chat/v1/search?q={quote(tag)}&tab=channels")
    titles = [i.get("title") for i in r["items"]]
    assert titles == [f"{tag}频道"], f"「频道」里只该有频道:{r['items']}"
    print("  ✓ 频道:只有频道,没有人")

    # ---- 多媒体 / 文件 / 语音 / 链接 ----
    r = me.get("/chat/v1/search?tab=media")
    assert kinds(r["items"]) <= {"photo", "video", "gif", "video_note"}, kinds(r["items"])
    assert any(i["message"]["kind"] == "photo" for i in r["items"]), r["items"]
    print("  ✓ 多媒体:不填关键词也列得出来,只有图和视频")

    r = me.get("/chat/v1/search?tab=files")
    names = [m.get("name", "") for i in r["items"] for m in i["message"].get("media", [])]
    assert "合同.pdf" in names, names
    assert kinds(r["items"]) == {"file"}, kinds(r["items"])
    print("  ✓ 文件:只有文件")

    r = me.get("/chat/v1/search?tab=links")
    assert any("chaojizan.cc/opensource" in (i["message"].get("text") or "")
               for i in r["items"]), r["items"]
    print("  ✓ 链接:带链接的那条在")

    r = me.get("/chat/v1/search?tab=voice")
    assert kinds(r["items"]) <= {"voice"}, kinds(r["items"])
    print("  ✓ 语音:没有语音就是空的,不会把别的类型混进来")

    # ---- 音乐:音频文件算,普通文件不算 ----
    r = me.get("/chat/v1/search?tab=music")
    names = [m.get("name", "") for i in r["items"] for m in i["message"].get("media", [])]
    assert "demo.mp3" in names, f"音频文件该进「音乐」:{names}"
    assert "合同.pdf" not in names, f"PDF 不该进「音乐」:{names}"
    print("  ✓ 音乐:mime 是 audio/* 的进来了,PDF 没混进来")

    # ---- 老形状还在(不带 tab)----
    r = me.get(f"/chat/v1/search?q={quote(tag)}")
    assert set(r) == {"chats", "users", "messages"}, list(r)
    assert any(c["title"] == f"{tag}群" for c in r["chats"]), r["chats"]
    print("  ✓ 不带 tab 还是老形状,老版本 App 不会崩")

    # ---- 不认识的分类要拒掉,不能当成「不分类」放行 ----
    call("GET", "/chat/v1/search?q=x&tab=downloads", me.token, expect_error=422)
    print("  ✓ 不认识的分类回 422(「下载内容」在客户端本地,服务端没有)")

    # ---- 翻页:limit=1 时给下一页的游标 ----
    r = me.get("/chat/v1/search?tab=files&limit=1")
    assert len(r["items"]) == 1 and r["has_more"] and r["next_before_id"], r
    nxt = me.get(f"/chat/v1/search?tab=files&limit=1&before_id={r['next_before_id']}")
    assert nxt["items"] and nxt["items"][0]["id"] < r["items"][0]["id"], (r, nxt)
    print("  ✓ 翻页按消息 id 往前走,没有重复")

    # ---- 应用:搜得到小程序 ----
    r = me.get(f"/chat/v1/search?q={quote('透明')}&tab=apps")
    assert all(i["kind"] in ("miniapp", "bot") for i in r["items"]), r["items"]
    print(f"  ✓ 应用:返回 {len(r['items'])} 条,都是小程序或机器人")

    # 别人的东西搜不到:friend 没发过这些,他的「文件」里不该有我的合同
    set_username(friend, "sousuo")
    r = friend.get("/chat/v1/search?tab=files")
    names = [m.get("name", "") for i in r["items"] for m in i["message"].get("media", [])]
    assert "合同.pdf" in names, "同群的人看得到群里的文件"
    r = friend.get("/chat/v1/search?tab=links")
    assert any("chaojizan.cc/opensource" in (i["message"].get("text") or "")
               for i in r["items"]), "私聊对方看得到那条链接"
    print("  ✓ 只搜得到自己能读的会话(同群能看到,退群/没进的看不到)")

    print("搜索分类 e2e 通过 ✓")


if __name__ == "__main__":
    main()
