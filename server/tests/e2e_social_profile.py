"""社交身份 e2e(DEV-PROMPTS-40 #340):用户名、找人、联系人、隐私、拉黑,以及 S2(手机号不外露)。

跑法:SUPERZ_API=http://127.0.0.1:8013 DATABASE_URL=… python -m tests.e2e_social_profile
"""
import json
import random

from tests.chat_util import person, sql
from tests.miniapp_util import sms_login
from tests.util import call, fresh_phone


def main():
    a, b = person(), person()
    print(f"  两个账号:A={a.id} B={b.id}")

    me = a.get("/social/v1/me")
    assert me["username"] is None and me["public_id"], me
    assert me["privacy"]["last_seen"] == "everyone", me["privacy"]
    assert me["link"].endswith(f"/u/{me['public_id']}"), me["link"]

    # ---- 用户名规则 ----
    bad = {"ab": "至少 5 位", "_abcde": "字母开头", "abcde_": "下划线结尾", "ab__cde": "连续两个",
           "admin": "保留", "superzfan": "保留", "helloBot": "bot 结尾", "中文名字啊": "字母、数字"}
    for name, needle in bad.items():
        r = a.put("/social/v1/me/username", {"username": name}, expect_error=True)
        assert r.get("_error") in (409, 422) and needle in str(r["detail"]), (name, r)
    name = f"Alice{random.randint(10000, 99999)}"
    out = a.put("/social/v1/me/username", {"username": name})
    assert out["username"] == name and out["link"].endswith(f"/@{name}"), out
    r = b.put("/social/v1/me/username", {"username": name.lower()}, expect_error=True)
    assert r.get("_error") == 409 and "占用" in r["detail"], r
    chk = b.get(f"/social/v1/username-check?u={name.upper()}")
    assert chk["ok"] is False and "占用" in chk["reason"], chk
    # 改名:旧名字立即释放
    new_name = name + "x"
    a.put("/social/v1/me/username", {"username": new_name})
    assert b.get(f"/social/v1/username-check?u={name}")["ok"] is True
    print("  ✓ 用户名:8 种不合规各有明确的话,大小写不敏感唯一,改名后旧名释放")

    # ---- 找人 ----
    card = b.get(f"/social/v1/resolve/{new_name}")
    assert card["type"] == "user" and card["user"]["id"] == a.id, card
    card2 = b.get(f"/social/v1/resolve-id/{me['public_id']}")
    assert card2["user"]["id"] == a.id
    found = b.post("/social/v1/find-by-phone", {"phone": a.phone})
    assert found["id"] == a.id, found
    a.patch("/social/v1/me", {"privacy": {"phone_search": "nobody"}})
    r = b.post("/social/v1/find-by-phone", {"phone": a.phone}, expect_error=True)
    missing = b.post("/social/v1/find-by-phone", {"phone": fresh_phone("186")}, expect_error=True)
    assert r.get("_error") == 404 and missing.get("_error") == 404, (r, missing)
    assert r["detail"] == missing["detail"], "关了查找和没注册必须回同一句话,否则等于告诉你这个号注册过"
    a.patch("/social/v1/me", {"privacy": {"phone_search": "everyone"}})
    print("  ✓ 找人:@用户名、名片编号、完整手机号;关掉查找后和「没注册」回同一句话")

    # ---- 隐私:最后上线 ----
    sql("UPDATE social_profiles SET last_seen_at = now() - interval '1 hour' WHERE user_id = :u",
        {"u": a.id})
    seen = b.get(f"/social/v1/users/{a.id}")["last_seen"]
    assert seen["at"] and seen["approx"] is None, seen
    a.patch("/social/v1/me", {"privacy": {"last_seen": "contacts"}})
    seen = b.get(f"/social/v1/users/{a.id}")["last_seen"]
    assert seen == {"online": False, "at": None, "approx": "recently"}, seen
    a.post("/social/v1/contacts", {"user_id": b.id, "alias": "老B"})
    seen = b.get(f"/social/v1/users/{a.id}")["last_seen"]
    assert seen["at"], "A 把 B 加成联系人之后,B 应该看得到 A 的精确时间"
    # 互惠:B 自己隐藏了最后上线,就看不到别人的精确时间
    b.patch("/social/v1/me", {"privacy": {"last_seen": "nobody"}})
    assert b.get(f"/social/v1/users/{a.id}")["last_seen"]["at"] is None
    b.patch("/social/v1/me", {"privacy": {"last_seen": "everyone"}})
    print("  ✓ 最后上线:所有人 / 联系人 / 互惠,隐藏时只给「最近」")

    # ---- 联系人 ----
    cs = a.get("/social/v1/contacts")["items"]
    assert [c["id"] for c in cs] == [b.id] and cs[0]["contact_alias"] == "老B", cs
    assert a.get(f"/social/v1/users/{b.id}")["is_contact"] is True
    assert b.get(f"/social/v1/users/{a.id}")["is_contact"] is False, "联系人是单向的"
    print("  ✓ 联系人:备注名、单向")

    # ---- 拉黑(S7)----
    sql("UPDATE users SET avatar_url = '/img/avatar/e2e.png' WHERE id = :u", {"u": a.id})
    assert b.get(f"/social/v1/users/{a.id}")["avatar"] == "/img/avatar/e2e.png"
    chat = b.private_with(a)
    a.post("/social/v1/blocks", {"user_id": b.id})
    view = b.get(f"/social/v1/users/{a.id}")
    assert view["avatar"] == "" and view["last_seen"]["at"] is None, view
    assert [x["id"] for x in a.get("/social/v1/blocks")["items"]] == [b.id]
    r = b.send(chat["id"], "在吗", expect_error=True)
    assert r.get("_error") == 403 and "拉黑" in r["detail"], r
    r = a.send(chat["id"], "我拉黑了你但还想说一句", expect_error=True)
    assert r.get("_error") == 403, "拉黑是双向隔离:拉黑的一方也不能发"
    a.delete(f"/social/v1/blocks/{b.id}")
    b.send(chat["id"], "解除了")
    print("  ✓ 拉黑:头像和在线状态对他隐藏、私信双向不通;解除后恢复")

    # ---- 角色:商家账号不能用 ----
    mt = sms_login(fresh_phone("135"), role="merchant")["token"]
    r = call("GET", "/social/v1/me", mt, expect_error=True)
    assert r.get("_error") == 403 and "用户端" in r["detail"], r
    print("  ✓ 商家账号调社交接口 403(D1)")

    # ---- S2:别人的手机号不出现在任何社交响应里 ----
    probe = a.phone
    own = call("GET", "/auth/me", a.token)
    assert probe in json.dumps(own, ensure_ascii=False), "探测器自检:A 自己的 /auth/me 里应该有手机号"
    seen_by_b = [
        b.get(f"/social/v1/users/{a.id}"), b.get(f"/social/v1/resolve/{new_name}"),
        b.post("/social/v1/find-by-phone", {"phone": a.phone}),
        b.get("/chat/v1/dialogs"), b.get(f"/chat/v1/chats/{chat['id']}"),
        b.get(f"/chat/v1/chats/{chat['id']}/messages"),
        b.get(f"/chat/v1/search?q={new_name[:4]}"),
    ]
    for body in seen_by_b:
        blob = json.dumps(body, ensure_ascii=False)
        assert probe not in blob and probe[-8:] not in blob, f"S2:响应里有 A 的手机号:{blob[:300]}"
    print(f"  ✓ S2:B 看到的 {len(seen_by_b)} 个响应里都没有 A 的手机号(探测器先认出了 A 自己的号)")

    # ---- 按手机号找人每天 20 次 ----
    c = person()
    codes = [c.post("/social/v1/find-by-phone", {"phone": fresh_phone("186")},
                    expect_error=True, retry_429=False).get("_error") for _ in range(21)]
    assert codes[:20] == [404] * 20 and codes[20] == 429, codes
    print("  ✓ 按手机号找人:第 21 次 429")

    print("e2e_social_profile 全部通过 ✅")


if __name__ == "__main__":
    main()
