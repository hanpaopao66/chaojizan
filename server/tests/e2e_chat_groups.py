"""群、频道、互动、贴纸、内容安全 e2e(DEV-PROMPTS-40 #349 #350 #351 #369)。

验证:建群时对「不许直接拉我进群」的人改发邀请、管理员只能授予自己有的权限、成员默认权限、
慢速模式(管理员不受限、一个相册算一条)、邀请链接要审批 → 同意、封禁后链接进不来也读不到、
已读回执(群卡片和会话列表带 peer_read_seq、已读名单)、匿名投票和测验的答案什么时候给、
频道只有管理员能发(帖子以频道名义)、浏览量按人去重、公开频道要实名 + 非成员能看、
贴纸包建 → 加图 → 发 → 别人看包、添加、移除、屏蔽词(消息 / 编辑 / 群名 / 用户名)、
同一段话群发 20 个以上私聊暂停 1 小时。

跑法:SUPERZ_API=http://127.0.0.1:8013 DATABASE_URL=… python -m tests.e2e_chat_groups
"""
import random
import time

from tests.chat_util import WS, person, sql, uev
from tests.e2e_media import png_bytes, upload
from tests.miniapp_util import admin_token, id_number
from tests.util import call


def ready(w: WS) -> WS:
    w.wait_for(lambda f: f.get("t") == "ready")
    return w


def main():
    owner, adm, mem, out, late = person(), person(), person(), person(), person()
    print(f"  账号:群主={owner.id} 管理员={adm.id} 成员={mem.id} 外人={out.id} 后来的={late.id}")

    # ---- 建群:不许直接拉进群的人改成发邀请 ----
    late.patch("/social/v1/me", {"privacy": {"group_invite": "nobody"}})
    g = owner.post("/chat/v1/chats", {"type": "group", "title": "周末饭搭子",
                                       "member_ids": [adm.id, mem.id, late.id]})
    gid = g["id"]
    assert g["skipped_user_ids"] == [late.id], g["skipped_user_ids"]
    assert g["member_count"] == 3 and g["perms"]["is_owner"], g
    print("  ✓ 建群:隐私设成「没有人」的人没被拉进来,接口告诉群主是谁")

    # ---- 管理员:只能授予自己有的权限 ----
    r = owner.patch(f"/chat/v1/chats/{gid}/members/{adm.id}", {
        "action": "promote", "title": "火锅队长",
        "rights": {"delete_messages": True, "ban_users": True, "pin_messages": True,
                   "invite_users": True, "add_admins": True, "change_info": False}})
    assert r["role"] == "admin" and r["title"] == "火锅队长", r
    r = adm.patch(f"/chat/v1/chats/{gid}/members/{mem.id}",
                  {"action": "promote", "rights": {"change_info": True, "ban_users": True}})
    assert r["rights"]["change_info"] is False and r["rights"]["ban_users"] is True, r["rights"]
    adm.patch(f"/chat/v1/chats/{gid}/members/{mem.id}", {"action": "demote"})
    e = adm.patch(f"/chat/v1/chats/{gid}", {"title": "改名"}, expect_error=True)
    assert e.get("_error") == 403, e
    print("  ✓ 管理员:头衔生效;授予的权限被压到自己有的范围内(改资料给不出去);不能改群资料")

    # ---- 成员默认权限:关掉发媒体 ----
    owner.patch(f"/chat/v1/chats/{gid}", {"settings": {"default_perms": {"send_media": False}}})
    assert mem.get(f"/chat/v1/chats/{gid}")["perms"]["send_media"] is False
    pic = upload(mem, png_bytes(), "a.png", "photo")
    e = mem.send(gid, "", kind="photo", media_ids=[pic["id"]], expect_error=True)
    assert e.get("_error") == 403, e
    apic = upload(adm, png_bytes(), "b.png", "photo")
    adm.send(gid, "", kind="photo", media_ids=[apic["id"]])
    owner.patch(f"/chat/v1/chats/{gid}", {"settings": {"default_perms": {"send_media": True}}})
    print("  ✓ 成员默认权限:关掉发媒体后成员发不了,管理员照发")

    # ---- 慢速模式 ----
    owner.patch(f"/chat/v1/chats/{gid}", {"settings": {"slow_mode": 10}})
    mem.send(gid, "第一条")
    e = mem.send(gid, "第二条", expect_error=True, retry_429=False)
    assert e.get("_error") == 429 and "慢速模式" in str(e.get("detail")), e
    time.sleep(1.1)   # 「同一群每人每秒 1 条」是另一条限流,别和它撞上
    adm.send(gid, "管理员不受慢速限制")
    time.sleep(1.2)
    adm.send(gid, "再来一条")
    time.sleep(10.5)
    gidx = str(random.getrandbits(62))
    for i in range(2):
        pm = upload(mem, png_bytes(320 + i, 240), f"p{i}.png", "photo")
        mem.send(gid, "相册" if i == 0 else "", kind="photo", media_ids=[pm["id"]], grouped_id=gidx)
    e = mem.send(gid, "相册之后再发一条", expect_error=True, retry_429=False)
    assert e.get("_error") == 429, e
    owner.patch(f"/chat/v1/chats/{gid}", {"settings": {"slow_mode": 0}})
    print("  ✓ 慢速模式:第二条 429;管理员不受限;同一相册的几张算一条,相册之后再发照样挡")

    # ---- 邀请链接:要审批 ----
    link = adm.post(f"/chat/v1/chats/{gid}/invites", {"title": "审批", "requires_approval": True})
    prev = out.get(f"/chat/v1/join/{link['code']}")
    assert prev["requires_approval"] and not prev["is_member"], prev
    wo, wout = ready(WS(owner.token)), ready(WS(out.token))
    r = out.post(f"/chat/v1/join/{link['code']}", {"about": "我是新来的"})
    assert r["status"] == "requested", r
    wo.wait_for(uev("join_request"))
    reqs = owner.get(f"/chat/v1/chats/{gid}/join-requests")["items"]
    assert reqs and reqs[0]["user"]["id"] == out.id and reqs[0]["about"] == "我是新来的", reqs
    owner.post(f"/chat/v1/chats/{gid}/join-requests/{out.id}", {"approve": True})
    wout.wait_for(uev("join_decided"))
    assert out.get(f"/chat/v1/chats/{gid}")["perms"]["in_chat"]
    print("  ✓ 邀请链接要审批:申请 → 群主实时收到 → 同意 → 申请人实时收到、进群")

    # ---- 封禁:主链接进不来,记录也读不到 ----
    adm.patch(f"/chat/v1/chats/{gid}/members/{out.id}", {"action": "ban"})
    primary = [i for i in owner.get(f"/chat/v1/chats/{gid}/invites")["items"] if i["is_primary"]][0]
    e = out.post(f"/chat/v1/join/{primary['code']}", {}, expect_error=True)
    assert e.get("_error") == 403, e
    e = out.get(f"/chat/v1/chats/{gid}/messages", expect_error=True)
    assert e.get("_error") == 403, e
    r = late.post(f"/chat/v1/join/{primary['code']}", {})
    assert r["status"] == "joined", r
    print("  ✓ 封禁:用主链接也进不来、读不到;没被直接拉进来的人用链接自己进")

    # ---- 已读回执 ----
    m = owner.send(gid, "大家看到了吗")
    mem.post(f"/chat/v1/dialogs/{gid}/read", {"seq": m["seq"]})
    card = owner.get(f"/chat/v1/chats/{gid}")
    assert card["peer_read_seq"] >= m["seq"], card.get("peer_read_seq")
    row = [d for d in owner.get("/chat/v1/dialogs")["items"] if d["id"] == gid][0]
    assert row["peer_read_seq"] >= m["seq"], row.get("peer_read_seq")
    rd = owner.get(f"/chat/v1/chats/{gid}/messages/{m['seq']}/readers")["items"]
    assert mem.id in [x["user"]["id"] for x in rd], rd
    print("  ✓ 已读:别人读了之后,群卡片和会话列表都带着 peer_read_seq(离线打开也是双勾);已读名单有他")

    # ---- 投票 ----
    pm = mem.send(gid, kind="poll", poll={"question": "吃什么", "options": ["火锅", "烧烤"]})
    assert all(o["votes"] is None for o in pm["poll"]["options"]), "没投之前不该看到票数"
    v = adm.post(f"/chat/v1/chats/{gid}/polls/{pm['seq']}/vote", {"options": [0]})
    assert v["poll"]["options"][0]["votes"] == 1 and v["poll"]["my_votes"] == [0], v["poll"]
    e = adm.get(f"/chat/v1/chats/{gid}/polls/{pm['seq']}/voters", expect_error=True)
    assert e.get("_error") == 403, "匿名投票不公开谁投了什么"
    time.sleep(1.1)
    qz = owner.send(gid, kind="poll", poll={"question": "1+1", "options": ["1", "2"], "quiz": True,
                                            "correct": 1, "explanation": "数学"})
    assert qz["poll"]["correct"] is None, "测验的答案投票前不能给"
    v = mem.post(f"/chat/v1/chats/{gid}/polls/{qz['seq']}/vote", {"options": [0]})
    assert v["poll"]["correct"] == 1 and v["poll"]["explanation"] == "数学", v["poll"]
    print("  ✓ 投票:投之前看不到票数;匿名投票不给名单;测验投完才揭晓答案")

    # ---- 频道 ----
    ch = owner.post("/chat/v1/chats", {"type": "channel", "title": "火锅资讯", "about": "每天一家"})
    cid = ch["id"]
    owner.post(f"/chat/v1/chats/{cid}/members", {"user_ids": [mem.id]})
    post = owner.send(cid, "今日推荐:小龙坎")
    assert post["as_chat"] and post["sender"] is None, post
    e = mem.send(cid, "我也想发", expect_error=True)
    assert e.get("_error") == 403, e
    v1 = mem.post(f"/chat/v1/chats/{cid}/views", {"seqs": [post["seq"]]})["views"]
    v2 = mem.post(f"/chat/v1/chats/{cid}/views", {"seqs": [post["seq"]]})["views"]
    assert v1[str(post["seq"])] == 1 and v2[str(post["seq"])] == 1, (v1, v2)
    e = out.get(f"/chat/v1/chats/{cid}/messages", expect_error=True)
    assert e.get("_error") == 403, "私有频道外人读不到"
    uname = f"hotpot{random.randint(10000, 99999)}"
    e = owner.patch(f"/chat/v1/chats/{cid}", {"username": uname}, expect_error=True)
    assert e.get("_error") == 403 and "实名" in str(e.get("detail")), e
    call("POST", "/auth/verify-identity", owner.token, {"real_name": "测试群主", "id_no": id_number()})
    owner.patch(f"/chat/v1/chats/{cid}", {"username": uname})
    page = out.get(f"/chat/v1/chats/{cid}/messages")
    assert any(x["seq"] == post["seq"] for x in page["messages"]), "公开频道不加入也能看"
    assert out.get(f"/chat/v1/chats/{cid}")["perms"]["in_chat"] is False
    r = out.post(f"/chat/v1/chats/{cid}/join")
    assert out.get(f"/chat/v1/chats/{cid}")["perms"]["in_chat"], r
    print("  ✓ 频道:帖子以频道名义发、订阅者不能发;浏览量按人去重;设公开要实名;公开后外人先看后订阅")

    # ---- 贴纸 ----
    s = mem.post("/chat/v1/stickers/sets", {"title": "我的表情"})
    sid = s["id"]
    assert s["is_mine"] and s["installed"] and s["count"] == 0, s
    st_media = upload(mem, png_bytes(600, 600), "s.png", "sticker", purpose="sticker")
    assert st_media["kind"] == "sticker" and st_media["public_url"], st_media
    st = mem.post(f"/chat/v1/stickers/sets/{sid}/stickers", {"media_id": st_media["id"], "emoji": "😀"})
    assert st["emoji"] == "😀" and st["media"]["url"].startswith("/img/"), st
    e = adm.post(f"/chat/v1/stickers/sets/{sid}/stickers", {"media_id": st_media["id"]},
                 expect_error=True)
    assert e.get("_error") == 403, "别人的贴纸包不能加图"
    photo = upload(mem, png_bytes(), "not-sticker.png", "photo")
    e = mem.post(f"/chat/v1/stickers/sets/{sid}/stickers", {"media_id": photo["id"]},
                 expect_error=True)
    assert e.get("_error") == 422, "普通图片不能直接当贴纸"
    sm = mem.send(gid, kind="sticker", sticker_id=st["id"])
    assert sm["sticker"]["set_id"] == sid and sm["media"], sm
    seen = adm.get(f"/chat/v1/stickers/sets/{sid}")
    assert not seen["installed"] and seen["count"] == 1, seen
    adm.post(f"/chat/v1/stickers/sets/{sid}/install")
    mine = adm.get("/chat/v1/stickers/sets")["installed"]
    assert any(x["id"] == sid and x["stickers"] for x in mine), mine
    adm.delete(f"/chat/v1/stickers/sets/{sid}/install")
    assert all(x["id"] != sid for x in adm.get("/chat/v1/stickers/sets")["installed"])
    by = adm.get(f"/chat/v1/stickers/sets/by-name/{s['short_name']}")
    assert by["id"] == sid, by
    print("  ✓ 贴纸:建包 → 加图(只能作者加、只能用贴纸类型的图)→ 发 → 别人看整包、添加、移除")

    # ---- 屏蔽词(#369)----
    word = f"zzban{random.randint(100000, 999999)}"
    call("POST", "/admin/moderation-words", admin_token(), {"word": word, "category": "test"})
    try:
        time.sleep(1.1)   # 上面刚发过贴纸:别撞上「同一群每人每秒 1 条」
        e = mem.send(gid, f"这里有{word}的内容", expect_error=True)
        assert e.get("_error") == 422 and "不允许" in str(e.get("detail")), e
        time.sleep(1.1)
        ok = mem.send(gid, "正常的一句话")
        e = mem.patch(f"/chat/v1/chats/{gid}/messages/{ok['seq']}", {"text": f"改成{word}"},
                      expect_error=True)
        assert e.get("_error") == 422, e
        e = owner.patch(f"/chat/v1/chats/{gid}", {"title": f"群{word}"}, expect_error=True)
        assert e.get("_error") == 422, e
        chk = mem.get(f"/social/v1/username-check?u=ab{word}")
        assert chk["ok"] is False and "不允许" in chk["reason"], chk
        e = mem.patch("/social/v1/me", {"bio": f"签名{word}"}, expect_error=True)
        assert e.get("_error") == 422, e
    finally:
        words = call("GET", "/admin/moderation-words", admin_token())
        for w in words:
            if w["word"] == word:
                call("DELETE", f"/admin/moderation-words/{w['id']}", admin_token())
    print("  ✓ 屏蔽词:消息、编辑、群名、签名命中就拒,用户名检查说不能用")

    # ---- 群发垃圾(#369):同一段话 24 小时内发给 20 个以上私聊 ----
    spammer = person()
    # 不是新账号(新账号每天只能主动发起 20 个私聊,那条先挡住,这里测的是另一条)
    sql("UPDATE users SET created_at = now() - interval '3 days' WHERE id = :id", {"id": spammer.id})
    targets = [person() for _ in range(21)]
    text = f"加我微信领红包 {random.randint(1000, 9999)} 号"
    blocked_at = None
    for i, t in enumerate(targets):
        c = spammer.private_with(t)
        r = spammer.send(c["id"], text, expect_error=True, retry_429=False)
        if r.get("_error") == 429:
            blocked_at = i
            break
        time.sleep(0.25)
    assert blocked_at == 20, f"应该在第 21 个私聊被停,实际 {blocked_at}"
    c0 = spammer.private_with(targets[0])
    e = spammer.send(c0["id"], "换一句话也不行", expect_error=True, retry_429=False)
    assert e.get("_error") == 429 and "分钟" in str(e.get("detail")), e
    print("  ✓ 群发:同一段话发到第 21 个私聊被停,之后 1 小时私聊都发不了(说明还剩几分钟)")

    for w in (wo, wout):
        w.close()
    print("e2e_chat_groups 全部通过 ✅")


if __name__ == "__main__":
    main()
