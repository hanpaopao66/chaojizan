"""S5「用户的数据用户说了算」(DEV-PROMPTS-40 §3):导出聊天记录 + 注销后级联删除。

- 导出:后台打包 zip,只有本人能下载;里面有会话 JSON、媒体文件、投稿清单;自己清空 / 隐藏的不在里面;
  24 小时内只能导一次;
- 注销:他发的消息正文和媒体对别人立刻消失(seq 占位)、下载地址 404;他是群主的群交给别人;
  @用户名释放;别人通讯录里的他没了;导出文件也跟着删。

在 server/ 目录下运行:SUPERZ_API=http://127.0.0.1:8013 python -m tests.e2e_chat_export
"""
import io
import json
import time
import zipfile

from tests.chat_util import person, set_username
from tests.e2e_media import png_bytes, raw, upload
from tests.util import call


def wait_export(p, timeout=90) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        st = p.get("/chat/v1/export")
        if st["state"] in ("ready", "failed"):
            return st
        time.sleep(1)
    raise AssertionError(f"导出 {timeout}s 还没做完:{st}")


def main():
    a, b, c = person(), person(), person()
    print(f"  账号:A={a.id} B={b.id} C={c.id}")
    name_a = set_username(a, "expo")

    # ---- 准备数据 ----
    cid = a.private_with(b)["id"]
    m1 = a.send(cid, "给你看张图")
    ph = upload(a, png_bytes(320, 200), "饭.png", "photo")
    m2 = a.send(cid, "", kind="photo", media_ids=[ph["id"]])
    b.send(cid, "好吃吗")
    hidden = a.send(cid, "这条我自己隐藏掉")
    a.post(f"/chat/v1/chats/{cid}/messages/delete", {"seqs": [hidden["seq"]], "revoke": False})
    g = a.post("/chat/v1/chats", {"type": "group", "title": "导出测试群", "member_ids": [b.id, c.id]})
    gid = g["id"]
    a.send(gid, "群里第一句")
    b.post("/social/v1/contacts", {"user_id": a.id})

    # ---- 导出 ----
    st = a.post("/chat/v1/export")
    assert st["state"] == "running", st
    st = wait_export(a)
    assert st["state"] == "ready", st
    code, headers, body = raw(None, st["url"])
    assert code == 200 and body[:2] == b"PK", f"签名地址能下到 zip:{code}"
    z = zipfile.ZipFile(io.BytesIO(body))
    names = z.namelist()
    assert "profile.json" in names and "videos.json" in names and "README.txt" in names, names
    prof = json.loads(z.read("profile.json"))
    assert prof["username"] == name_a, prof
    chat_files = [n for n in names if n.startswith(f"chats/{cid}_")]
    assert chat_files, names
    data = json.loads(z.read(chat_files[0]))
    seqs = [m["seq"] for m in data["messages"]]
    assert m1["seq"] in seqs and m2["seq"] in seqs, seqs
    assert hidden["seq"] not in seqs, "自己隐藏掉的消息不在导出里(导出不是绕过可见性的后门)"
    photo = next(m for m in data["messages"] if m["seq"] == m2["seq"])
    arc = photo["media"][0].get("file")
    assert arc and arc in names, photo
    from PIL import Image
    assert Image.open(io.BytesIO(z.read(arc))).size == (320, 200), "zip 里是那张图(发送时转过码,尺寸不变)"
    assert any(n.startswith(f"chats/{gid}_") for n in names), "群也导出来了"
    print(f"  ✓ 导出:zip 里有资料、{len(chat_files)} 个私聊文件、群、图片原文件;隐藏的消息不在里面")

    mid = st["media_id"]
    assert raw(b, f"/media/v1/files/{mid}")[0] == 404, "别人拿不到我的导出文件"
    forged = st["url"].replace(f"u={a.id}", f"u={b.id}")
    assert raw(None, forged)[0] == 404, "改签名地址里的用户:对不上"
    again = a.post("/chat/v1/export", expect_error=True, retry_429=False)
    assert again.get("_error") == 429 and "24 小时" in again["detail"], again
    print("  ✓ 导出文件只有本人能下;24 小时内再导出 429")

    # ---- 注销 ----
    b_url = next(x for x in b.get(f"/chat/v1/chats/{cid}/messages")["messages"]
                 if x["seq"] == m2["seq"])["media"][0]["url"]
    assert raw(None, b_url)[0] == 200
    call("DELETE", "/auth/me", a.token)

    msgs = b.get(f"/chat/v1/chats/{cid}/messages")["messages"]
    left = {m["seq"] for m in msgs}
    assert m1["seq"] not in left and m2["seq"] not in left, f"A 发的消息对 B 消失了:{left}"
    assert any(m["text"] == "好吃吗" for m in msgs), "B 自己发的还在"
    assert raw(b, f"/media/v1/files/{ph['id']}")[0] == 404, "A 的图片文件 404"
    assert raw(None, b_url)[0] == 404, "B 手里的签名地址也失效"
    card = b.get(f"/chat/v1/chats/{gid}")
    assert card["perms"]["is_owner"] is True, f"群主注销:群交给了 B(成员里最早进来的):{card['perms']}"
    gm = b.get(f"/chat/v1/chats/{gid}/messages")["messages"]
    assert not any(m["text"] == "群里第一句" for m in gm), "群里 A 说的话也清掉了"
    r = call("GET", f"/social/v1/resolve/{name_a}", b.token, expect_error=True)
    assert r.get("_error") == 404, f"@用户名释放了:{r}"
    contacts = b.get("/social/v1/contacts")
    items = contacts["items"] if isinstance(contacts, dict) else contacts
    assert all((x.get("user") or x).get("id") != a.id for x in items), "B 的通讯录里没有 A 了"
    assert raw(None, st["url"])[0] == 404, "导出文件也跟着删了"
    print("  ✓ 注销:A 的消息和图片对 B 立刻消失、地址 404;群交给 B;@用户名释放;通讯录里没了;导出文件删了")


if __name__ == "__main__":
    main()
    print("e2e_chat_export 通过")
