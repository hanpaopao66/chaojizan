"""社区治理 e2e(DEV-PROMPTS-40 #368 聊天部分、#370、#371,不变量 S6、S8)。

验证:
1. 3 个不同的人举报同一个人 → 这几张举报单 escalated,排在更早提交的普通举报前面;
2. S8:不带举报单号看会话消息 403;带单只拿到举报单里那几条 ± 5 条(不越过举报人当时的可见下限),
   留痕表多一行、透明中心的查看次数 +1;举报单详情里不含任何消息内容;
3. 禁言:发消息、改消息、转发、评论、弹幕都 403,detail 带原因代码、中文标签、说明、到期时间、能申诉;
   禁言管不着的事(加联系人)照常;当事人收到系统通知;被举报的消息顺带删掉;
4. 封群:成员发言、外人加入(公开加入 / 邀请链接 / 预览)都拒,公开搜索、@链接、非成员预览里消失;
   成员照样能看历史;管理员撤销后全部恢复;
5. 封号:社交写操作全拒(发消息、建群、开新私聊、评论、弹幕、点赞、加联系人、改用户名、改签名、建稿、提交投稿、打电话),
   能看自己的处罚、能改隐私、能拉黑、能导出自己的数据、能申诉(只能申诉一次);
6. S6:作出处罚的管理员处理申诉 403;有待处理的申诉时不能绕过申诉直接撤销(409);
   另一个管理员撤销 → 限制立即解除、当事人收到「申诉结果」;维持 → 限制照旧;
7. 非管理员访问后台接口一律 403;
8. 透明中心「社区」栏:处置记录里有这次的处罚(类型 + 原因代码 + 申诉结果),
   但扫不到任何手机号、用户名、昵称、会话标题、消息正文、处罚说明、申诉理由(探测器先拿已知的串验过);
9. 注销再注册:还生效的封号跟到新账号上(注销不是洗白按钮);
10. 后台「数据」:每天一行,今天的消息数、举报量、处置量都数到了。

跑法:SUPERZ_API=http://127.0.0.1:8023 DATABASE_URL=… REDIS_URL=… python -m tests.e2e_social_moderation
(直连库 / Redis 的助手要和服务端指向同一个库)
"""
import json
import random
import secrets
import time

from tests.chat_util import WS, person
from tests.e2e_media import png_bytes, upload
from tests.miniapp_util import sms_login
from tests.video_util import (admin2_token, admin_token, clear_rate_limits, fixture_video, raw,
                              realname, sql)
from tests.util import call

TAG = f"mod{secrets.token_hex(3)}"


def err(r: dict, code: int = 403) -> dict:
    assert isinstance(r, dict) and r.get("_error") == code, f"期望 {code},实际 {r}"
    return r.get("detail")


def sanctioned(r: dict, action: str, *, point: str | None = None) -> dict:
    """被处罚挡住的 403:detail 是约定好的形状(COMMUNITY-GOVERNANCE.md §3)。"""
    d = err(r, 403)
    assert isinstance(d, dict) and d.get("error") == "sanctioned", f"不是处罚的 403:{d}"
    assert d["action"] == action, (d["action"], action)
    for k in ("message", "sanction_id", "reason_code", "reason_label", "note", "until",
              "permanent", "can_appeal", "appeal_path", "scope", "point", "action_label"):
        assert k in d, f"detail 缺 {k}:{d}"
    assert d["reason_label"], d
    if point:
        assert d["point"] == point, (d["point"], point)
    return d


def send(p, chat_id: int, text: str, **kw):
    clear_rate_limits("chat_send", p.id)
    clear_rate_limits("chat_send_min", p.id)
    return p.send(chat_id, text, **kw)


def uname(base: str) -> str:
    return f"{base}{random.randint(100000, 999999)}"


def views_count() -> int:
    return int(sql("SELECT count(*) FROM admin_chat_views", fetch="scalar"))


def tp() -> dict:
    return call("GET", "/transparency/community")


def main():
    adm, adm2 = admin_token(), admin2_token()
    adm_id = call("GET", "/auth/me", adm)["id"]
    bad, bad2, bad3 = person(), person(), person()
    r1, r2, r3, r4 = person(), person(), person(), person()
    owner, member, outsider, x1, x2 = person(), person(), person(), person(), person()
    print(f"  账号:骚扰者={bad.id} 骗子={bad2.id} 注销者={bad3.id} 举报人={r1.id},{r2.id},{r3.id},{r4.id} "
          f"群主={owner.id} 成员={member.id} 外人={outsider.id}")
    names = {p.id: p.put("/social/v1/me/username", {"username": uname(n)})["username"]
             for p, n in ((bad, "Bader"), (bad2, "Scamer"), (owner, "Owner"),
                          (member, "Member"), (r1, "Victim"))}

    # ------------------------------------------------------------------ 1. 举报排队
    # 先有一张普通举报(id 更小),后面三个人举报同一个人 —— 那三张要排到它前面
    cx = x2.private_with(x1)
    sx = send(x2, cx["id"], f"{TAG}-unrelated")["seq"]
    rx = x1.post("/chat/v1/reports", {"target_type": "message", "chat_id": cx["id"],
                                      "seqs": [sx], "reason_code": "C102"})
    assert rx["status"] == "open", rx

    ca = bad.private_with(r1)
    A = ca["id"]
    for i in range(1, 21):   # A 里 20 条,seq 1..20;偶数条是骚扰者发的
        who = r1 if i % 2 else bad
        m = send(who, A, f"{TAG}-A-{i}")
        assert m["seq"] == i, (m["seq"], i)
        time.sleep(0.05)
    rep1 = r1.post("/chat/v1/reports", {"target_type": "message", "chat_id": A, "seqs": [10],
                                        "reason_code": "C101", "note": f"{TAG}-举报说明"})
    assert rep1["status"] == "open", rep1

    cb = bad.private_with(r2)
    B = cb["id"]
    for i in range(1, 4):
        send(bad, B, f"{TAG}-B-{i}")
    r2.post(f"/chat/v1/dialogs/{B}/clear", {"revoke": False})   # r2 只为自己清空了 1..3
    s_b = send(bad, B, f"{TAG}-B-4")["seq"]
    assert s_b == 4
    rep2 = r2.post("/chat/v1/reports", {"target_type": "message", "chat_id": B,
                                        "seqs": [1, 2, s_b], "reason_code": "C101"})
    cc = bad.private_with(r3)
    send(bad, cc["id"], f"{TAG}-C-1")
    pic = upload(bad, png_bytes(64, 48), "p.png", "photo")
    send(bad, cc["id"], "", kind="photo", media_ids=[pic["id"]])
    rep3 = r3.post("/chat/v1/reports", {"target_type": "user", "user_id": bad.id,
                                        "chat_id": cc["id"], "seqs": [1, 2],
                                        "reason_code": "C101"})
    assert rep3["status"] == "escalated", f"第 3 个不同的人举报同一个人,应当 escalated:{rep3}"
    q = call("GET", "/admin/social/chat-reports?status=open&limit=500", adm)["items"]
    ids = [x["id"] for x in q]
    esc = [x["escalated"] for x in q]
    assert esc == sorted(esc, reverse=True), "escalated 的必须全部排在普通举报前面"
    for rid in (rep1["id"], rep2["id"], rep3["id"]):
        it = q[ids.index(rid)]
        assert it["status"] == "escalated" and it["subject"]["id"] == bad.id, it
        assert ids.index(rid) < ids.index(rx["id"]), "多人举报的排在更早提交的普通举报前面"
    assert q[ids.index(rep1["id"])]["reporters_7d"] >= 3
    assert "reporter_id" not in json.dumps(q), "队列里不能带举报人"
    print("  ✓ 3 个不同的人举报同一个人 → 三张单都 escalated,排在更早的普通举报前面;队列不带举报人")

    # ------------------------------------------------------------------ 2. S8
    for path in ("/admin/social/chat-messages", f"/admin/social/chat-messages?chat_id={A}",
                 f"/admin/social/chat-messages?chat_id={A}&seqs=1"):
        e = call("GET", path, adm, expect_error=True)
        assert e.get("_error") == 403 and "举报单" in str(e.get("detail")), (path, e)
    det = call("GET", f"/admin/social/chat-reports/{rep1['id']}", adm)
    assert f"{TAG}-A-" not in json.dumps(det, ensure_ascii=False), "举报单详情里不能有消息内容"
    assert det["can_view_messages"] and det["messages_path"].endswith(f"report_id={rep1['id']}")
    before_views, before_tp = views_count(), tp()["admin_chat_views"]
    v = call("GET", f"/admin/social/chat-messages?report_id={rep1['id']}", adm)
    assert v["seqs"] == list(range(5, 16)), f"只能是被举报的第 10 条 ± 5 条:{v['seqs']}"
    assert [m["text"] for m in v["messages"]] == [f"{TAG}-A-{i}" for i in range(5, 16)]
    assert [m["seq"] for m in v["messages"] if m["reported"]] == [10]
    dump = json.dumps(v, ensure_ascii=False)
    for i in (1, 2, 3, 4, 16, 17, 20):
        assert f"{TAG}-A-{i}\"" not in dump, f"范围外的第 {i} 条出现在了响应里"
    assert "已记录" in v["audit"]["notice"]
    assert views_count() == before_views + 1, "S8:每次查看都要留痕"
    row = sql("SELECT admin_id, report_id, chat_id, seqs FROM admin_chat_views "
              "ORDER BY id DESC LIMIT 1", fetch="all")[0]
    seqs = row[3] if isinstance(row[3], list) else json.loads(row[3])
    assert (row[0], row[1], row[2], seqs) == (adm_id, rep1["id"], A, list(range(5, 16))), row
    after_tp = tp()["admin_chat_views"]
    assert after_tp["total"] == before_tp["total"] + 1, (before_tp, after_tp)
    assert after_tp["last_30d"] == before_tp["last_30d"] + 1
    assert after_tp["monthly"][0]["views"] == (before_tp["monthly"][0]["views"]
                                               if before_tp["monthly"] else 0) + 1
    det2 = call("GET", f"/admin/social/chat-reports/{rep1['id']}", adm)
    assert len(det2["views"]) == len(det["views"]) + 1 and det2["views"][-1]["seqs"] == \
        list(range(5, 16))
    v2 = call("GET", f"/admin/social/chat-messages?report_id={rep2['id']}", adm)
    assert v2["seqs"] == [4], f"举报人清空过 1..3,上下文不能越过他当时的可见下限:{v2['seqs']}"
    assert f"{TAG}-B-3" not in json.dumps(v2, ensure_ascii=False)
    # 被举报的是图片:管理员拿到的是绑定这张举报单的地址,换一张单号就不认
    v3 = call("GET", f"/admin/social/chat-messages?report_id={rep3['id']}", adm)
    photo = next(m for m in v3["messages"] if m["kind"] == "photo")["media"][0]
    code_, _, body_ = raw(None, photo["url"])
    assert code_ == 200 and body_[:2] == b"\xff\xd8", (code_, photo["url"])  # 入库时转成了 JPEG
    assert photo["thumb"] and raw(None, photo["thumb"])[0] == 200
    forged = photo["url"].replace(f"r={rep3['id']}", f"r={rep1['id']}")
    assert raw(None, forged)[0] == 404, "签名绑定举报单:换单号不认"
    assert raw(None, f"/media/v1/files/{pic['id']}")[0] == 404
    assert raw(outsider.token, f"/media/v1/files/{pic['id']}")[0] == 404
    print("  ✓ S8:不带举报单号 403;带单只给第 10 条 ± 5 条;留痕 +1(谁、哪张单、哪个会话、哪些 seq);"
          "透明中心次数 +1;举报人清空过的部分不给看;图片地址绑定举报单,换单号 404")

    # ------------------------------------------------------------------ 3. 禁言
    h = call("POST", f"/admin/social/chat-reports/{rep1['id']}/handle", adm,
             {"action": "mute", "hours": 24, "reason_code": "C101", "note": f"{TAG}-多次辱骂他人",
              "also_delete": True})
    assert h["status"] == "actioned" and len(h["sanction_ids"]) == 2, h
    assert "禁言" in h["resolution"], h
    msgs = r1.get(f"/chat/v1/chats/{A}/messages?limit=50")["messages"]
    assert 10 not in [m["seq"] for m in msgs] and 9 in [m["seq"] for m in msgs], \
        "被举报的第 10 条要删掉,别的不动"
    d = sanctioned(send(bad, A, "还想说", expect_error=True), "mute", point="message")
    assert d["reason_code"] == "C101" and d["reason_label"] == "骚扰、辱骂", d
    assert d["note"] == f"{TAG}-多次辱骂他人" and d["until"] and not d["permanent"], d
    assert d["can_appeal"] and d["appeal_path"] == f"/social/v1/sanctions/{d['sanction_id']}/appeal"
    assert "禁言" in d["message"] and "申诉" in d["message"], d["message"]
    mute_id = d["sanction_id"]
    sanctioned(bad.patch(f"/chat/v1/chats/{A}/messages/8", {"text": "改一下"}, expect_error=True),
               "mute", point="message")
    sanctioned(bad.post(f"/chat/v1/chats/{A}/messages/forward",
                        {"seqs": [8], "to_chat_ids": [B]}, expect_error=True), "mute")
    up = person()
    vid = fixture_video(up.id, title=f"{TAG}-视频", duration_ms=120_000)
    clear_rate_limits("video_comment", bad.id)
    sanctioned(bad.post(f"/video/v1/videos/{vid['vid']}/comments", {"text": "评论一下"},
                        expect_error=True), "mute", point="comment")
    clear_rate_limits("danmaku", bad.id)
    sanctioned(bad.post(f"/video/v1/parts/{vid['part_id']}/danmaku",
                        {"time_ms": 1000, "text": "弹幕"}, expect_error=True),
               "mute", point="danmaku")
    bad.post("/social/v1/contacts", {"user_id": r4.id})   # 禁言管不着的事照常
    sys_items = bad.get("/social/v1/notifications?kind=system")["items"]
    assert any(x["title"] == "你被禁言了" and x["data"].get("sanction_id") == mute_id
               for x in sys_items), [x["title"] for x in sys_items]
    mine = bad.get("/social/v1/me/sanctions")
    act = {x["id"]: x for x in mine["active"]}
    assert mute_id in act and act[mute_id]["duration"] == "24 小时", mine
    assert any(x["action"] == "delete_messages" and x["seqs"] == [10] and x["status"] == "done"
               for x in mine["history"]), mine["history"]
    print("  ✓ 禁言:发 / 改 / 转发 / 评论 / 弹幕都 403,detail 带原因代码、标签、说明、到期、可申诉;"
          "加联系人照常;收到系统通知;被举报的那条删了")

    # ------------------------------------------------------------------ 4. 封群
    realname(owner, "测试群主")
    gtitle = f"{TAG}-周末群"
    g = owner.post("/chat/v1/chats", {"type": "group", "title": gtitle,
                                      "member_ids": [member.id]})
    G = g["id"]
    gname = uname("modgroup")
    owner.patch(f"/chat/v1/chats/{G}", {"username": gname})
    send(member, G, f"{TAG}-G-1")
    assert G in [c["id"] for c in outsider.get(f"/chat/v1/search?q={gname}")["chats"]]
    assert outsider.get(f"/social/v1/resolve/{gname}")["type"] == "chat"
    rg = r3.post("/chat/v1/reports", {"target_type": "chat", "chat_id": G,
                                      "reason_code": "C102", "note": "引流"})
    gd = call("GET", f"/admin/social/chat-reports/{rg['id']}", adm)
    assert gd["report"]["seq_count"] >= 1 and gd["candidates"]["chat"]["id"] == G, gd
    call("POST", f"/admin/social/chat-reports/{rg['id']}/handle", adm,
         {"action": "ban_chat", "permanent": True, "reason_code": "C102",
          "note": f"{TAG}-群内持续发引流广告"})
    d = sanctioned(send(member, G, "还能说吗", expect_error=True), "ban_chat", point="speak")
    assert d["scope"] == "chat" and d["can_appeal"] is False and d["appeal_path"] is None, d
    assert d["note"] == "" and d["permanent"], "普通成员不是当事人:不给他看写给群主的说明"
    d = sanctioned(send(owner, G, "群主说话", expect_error=True), "ban_chat")
    assert d["can_appeal"] is True and d["note"] == f"{TAG}-群内持续发引流广告", d
    sanctioned(outsider.post(f"/chat/v1/chats/{G}/join", {}, expect_error=True), "ban_chat",
               point="join")
    code = owner.get(f"/chat/v1/chats/{G}/invites")["items"][0]["code"]
    sanctioned(outsider.post(f"/chat/v1/join/{code}", {}, expect_error=True), "ban_chat",
               point="join")
    sanctioned(outsider.get(f"/chat/v1/join/{code}", expect_error=True), "ban_chat")
    assert G not in [c["id"] for c in outsider.get(f"/chat/v1/search?q={gname}")["chats"]], \
        "被封的群不能出现在公开搜索里"
    err(outsider.get(f"/social/v1/resolve/{gname}", expect_error=True), 404)
    err(outsider.get(f"/chat/v1/chats/{G}/messages", expect_error=True), 403)
    assert member.get(f"/chat/v1/chats/{G}/messages")["messages"], "成员照样能看历史"
    assert member.get(f"/chat/v1/chats/{G}")["platform_ban"]["permanent"] is True
    dl = {c["id"]: c for c in member.get("/chat/v1/dialogs")["items"]}
    assert dl[G]["platform_ban"] is not None
    ban_g = d["sanction_id"]
    print("  ✓ 封群:成员发言、公开加入、邀请链接、预览都拒;搜索、@链接、非成员预览里消失;"
          "成员能看历史;只有群主能申诉")

    # ------------------------------------------------------------------ 5. 封号
    ce = bad2.private_with(r4)
    E = ce["id"]
    send(bad2, E, f"{TAG}-E-我是客服,把验证码发我")
    draft = fixture_video(bad2.id, title=f"{TAG}-草稿")
    sql("UPDATE videos SET status = 'draft', published_at = NULL WHERE id = :id",
        {"id": draft["id"]})
    re_ = r4.post("/chat/v1/reports", {"target_type": "message", "chat_id": E, "seqs": [1],
                                       "reason_code": "C103"})
    call("POST", f"/admin/social/chat-reports/{re_['id']}/handle", adm,
         {"action": "ban_account", "days": 7, "reason_code": "C103",
          "note": f"{TAG}-冒充客服骗验证码"})
    # 封号在 social_user 统一挡(point = social_write),比写路径上的判定更早
    d = sanctioned(send(bad2, E, "再发一条", expect_error=True), "ban_account",
                   point="social_write")
    ban_id = d["sanction_id"]
    assert "注销" in d["message"] and "申诉" in d["message"], d["message"]
    writes = [
        ("POST", "/chat/v1/chats", {"type": "group", "title": "新群", "member_ids": [r4.id]}),
        ("POST", "/chat/v1/chats/private", {"user_id": outsider.id}),
        ("POST", f"/video/v1/videos/{vid['vid']}/comments", {"text": "评论"}),
        ("POST", f"/video/v1/parts/{vid['part_id']}/danmaku", {"time_ms": 1, "text": "弹幕"}),
        ("POST", f"/video/v1/videos/{vid['vid']}/like", {}),
        ("POST", "/social/v1/contacts", {"user_id": r1.id}),
        ("PUT", "/social/v1/me/username", {"username": uname("Another")}),
        ("PATCH", "/social/v1/me", {"bio": "新签名"}),
        ("POST", "/video/v1/uploads/videos", {"title": "新稿件", "zone": "tech"}),
        ("POST", f"/video/v1/videos/{draft['vid']}/submit", None),
        ("POST", f"/chat/v1/chats/{E}/messages/{1}/reactions", {"emoji": "👍"}),
        ("POST", f"/chat/v1/join/{code}", {}),
    ]
    for method, path, body in writes:
        r = call(method, path, bad2.token, body if body is not None else {}, expect_error=True)
        sanctioned(r, "ban_account")
    # 能做的:看自己的处罚、读消息、补齐、改隐私、拉黑
    mine = bad2.get("/social/v1/me/sanctions")
    b = next(x for x in mine["active"] if x["id"] == ban_id)
    assert b["action"] == "ban_account" and b["reason_code"] == "C103" and b["can_appeal"], b
    assert b["duration"] == "7 天" and b["until"], b
    assert bad2.get(f"/chat/v1/chats/{E}/messages")["messages"]
    bad2.post("/chat/v1/sync", {"user_pts": 0, "chats": {}})
    bad2.patch("/social/v1/me", {"privacy": {"last_seen": "contacts"}})
    bad2.post("/social/v1/blocks", {"user_id": outsider.id})
    assert bad2.post("/chat/v1/export")["state"] in ("running", "ready"), "封号期间照样能导出自己的数据"
    # 打电话(信令走 WebSocket):错误帧里是同一份说明
    w = WS(bad2.token)
    w.wait_for(lambda f: f.get("t") == "ready")
    cid = secrets.token_hex(8)
    w.send({"t": "call", "a": "invite", "call_id": cid, "to": r4.id, "video": False,
            "sdp": "v=0\r\no=- fake offer\r\n"})
    f = w.wait_for(lambda f: f.get("t") == "call" and f.get("call_id") == cid)
    w.close()
    assert f["a"] == "error" and f["reason"] == "sanctioned" and \
        f["sanction"]["action"] == "ban_account", f
    ap = bad2.post(f"/social/v1/sanctions/{ban_id}/appeal", {"text": f"{TAG}-我的号被盗了,不是我发的"})
    assert ap["appeal"]["status"] == "open", ap
    err(bad2.post(f"/social/v1/sanctions/{ban_id}/appeal", {"text": "再申诉一次试试"},
                  expect_error=True), 409)
    err(r4.post(f"/social/v1/sanctions/{ban_id}/appeal", {"text": "替别人申诉试试"},
                expect_error=True), 404)
    print(f"  ✓ 封号:{len(writes) + 2} 种社交写操作全 403(含打电话);能看自己的处罚、读消息、改隐私、拉黑、导出;"
          "能申诉且只能一次,别人替他申诉 404")

    # ------------------------------------------------------------------ 6. S6
    lst = call("GET", "/admin/social/social-appeals", adm)["items"]
    it = next(x for x in lst if x["appeal"]["id"] == ban_id)
    assert it["you_decided_original"] is True, it
    e = call("POST", f"/admin/social/social-appeals/{ban_id}/resolve", adm,
             {"overturn": True, "note": "我自己复核一下"}, expect_error=True)
    assert e.get("_error") == 403 and "另一名" in str(e.get("detail")), e
    e = call("POST", f"/admin/social/sanctions/{ban_id}/revoke", adm, {"note": "绕过申诉直接撤"},
             expect_error=True)
    assert e.get("_error") == 409, "有待处理的申诉时不能绕过申诉直接撤销"
    it2 = next(x for x in call("GET", "/admin/social/social-appeals", adm2)["items"]
               if x["appeal"]["id"] == ban_id)
    assert it2["you_decided_original"] is False
    out = call("POST", f"/admin/social/social-appeals/{ban_id}/resolve", adm2,
               {"overturn": True, "note": "复核:证据不足,撤销", "note_internal": "登录地异常,像被盗号"})
    assert out["appeal_status"] == "overturned" and out["sanction"]["status"] == "revoked", out
    m = send(bad2, E, "解封了")
    assert m["seq"] >= 2, m
    bad2.post("/social/v1/contacts", {"user_id": r1.id})
    sys2 = bad2.get("/social/v1/notifications?kind=system")["items"]
    assert any(x["title"] == "申诉结果" and "申诉成立" in (x["text"] or "") for x in sys2), \
        [(x["title"], x["text"]) for x in sys2]
    assert any(x["title"] == "账号被封禁" for x in sys2)
    mine = bad2.get("/social/v1/me/sanctions")
    hist = next(x for x in mine["history"] if x["id"] == ban_id)
    assert hist["status"] == "revoked" and hist["appeal"]["status"] == "overturned" \
        and hist["appeal"]["note"] == "复核:证据不足,撤销", hist
    assert "note_internal" not in json.dumps(mine) and "登录地异常" not in \
        json.dumps(mine, ensure_ascii=False), "内部备注不给当事人看"
    # 维持:禁言照旧
    bad.post(f"/social/v1/sanctions/{mute_id}/appeal", {"text": "我只是开玩笑"})
    call("POST", f"/admin/social/social-appeals/{mute_id}/resolve", adm2,
         {"overturn": False, "note": "复核:确属辱骂,维持"})
    sanctioned(send(bad, A, "维持之后", expect_error=True), "mute")
    assert any(x["title"] == "申诉结果" and "维持" in (x["text"] or "")
               for x in bad.get("/social/v1/notifications?kind=system")["items"])
    # 管理员撤销封群(没有申诉):立刻解封、回到搜索
    call("POST", f"/admin/social/sanctions/{ban_g}/revoke", adm, {"note": "群主已整改"})
    send(member, G, "解封后说话")
    assert G in [c["id"] for c in outsider.get(f"/chat/v1/search?q={gname}")["chats"]]
    assert member.get(f"/chat/v1/chats/{G}")["platform_ban"] is None
    print("  ✓ S6:原处罚人处理申诉 403、有申诉时直接撤销 409;另一名审核员撤销 → 立刻能发消息、收到申诉结果;"
          "维持 → 照旧禁言;撤销封群 → 回到搜索、能发言")

    # ------------------------------------------------------------------ 7. 非管理员
    for method, path, body in (
            ("GET", "/admin/social/chat-reports", None),
            ("GET", f"/admin/social/chat-reports/{rep1['id']}", None),
            ("GET", f"/admin/social/chat-messages?report_id={rep1['id']}", None),
            ("POST", f"/admin/social/chat-reports/{rx['id']}/handle", {"action": "dismiss"}),
            ("GET", "/admin/social/sanctions", None),
            ("POST", "/admin/social/sanctions", {"target_type": "user", "target_id": r1.id,
                                                 "action": "warn", "reason_code": "C101"}),
            ("POST", f"/admin/social/sanctions/{mute_id}/revoke", {"note": "试试"}),
            ("GET", "/admin/social/social-appeals", None),
            ("POST", f"/admin/social/social-appeals/{mute_id}/resolve",
             {"overturn": True, "note": "试试"}),
            ("GET", "/admin/social/community-stats", None)):
        for who in (bad, r1):
            r = call(method, path, who.token, body, expect_error=True)
            assert r.get("_error") == 403, (method, path, r)
    print("  ✓ 非管理员访问后台接口一律 403(10 个接口 × 2 个人)")

    # ------------------------------------------------------------------ 8. 透明中心
    pub = tp()
    rec = pub["sanctions"]["records"]
    assert {"mute", "ban_chat", "ban_account", "delete_messages"} <= {x["action"] for x in rec}
    assert any(x["action"] == "ban_account" and x["reason_code"] == "C103" and
               x["appeal"] == "overturned" and x["revoked"] for x in rec), rec[:5]
    assert any(x["action"] == "mute" and x["appeal"] == "upheld" and x["duration"] == "24 小时"
               for x in rec)
    assert set(rec[0]) == {"date", "target_type", "action", "action_label", "reason_code",
                           "reason_label", "duration", "appeal", "appeal_label", "revoked"}, rec[0]
    assert "services/video_rank.py" in pub["formula"]["source_url"] and pub["formula"]["text"]
    blob = json.dumps(pub, ensure_ascii=False)
    everyone = (bad, bad2, bad3, r1, r2, r3, r4, owner, member, outsider, x1, x2)
    probes = [p.phone for p in everyone] + [p.name for p in everyone] + list(names.values()) + [
        gtitle, gname, f"{TAG}-A-", f"{TAG}-B-", f"{TAG}-E-", f"{TAG}-G-", f"{TAG}-unrelated",
        f"{TAG}-多次辱骂他人", f"{TAG}-群内持续发引流广告", f"{TAG}-冒充客服骗验证码",
        f"{TAG}-我的号被盗了", f"{TAG}-举报说明", "登录地异常", "复核:证据不足"]
    # 探测器先认得出来才算数:把已知的串塞进一份响应里,必须扫得到
    canary = blob[:-1] + f', "canary": "{bad.phone} {names[bad.id]} {gtitle}"}}'
    assert all(x in canary for x in (bad.phone, names[bad.id], gtitle)), "探测器认不出已知的串"
    leaked = [x for x in probes if x and x in blob]
    assert not leaked, f"透明中心泄露了个人信息 / 会话名 / 内容:{leaked}"
    print(f"  ✓ 透明中心:处置记录里有这几次(类型 + 原因代码 + 申诉结果),扫了 {len(probes)} 个串"
          "(手机号、昵称、用户名、群名、消息、说明、申诉理由)一个都没有")

    # ------------------------------------------------------------------ 9. 注销再注册
    s3 = call("POST", "/admin/social/sanctions", adm,
              {"target_type": "user", "target_id": bad3.id, "action": "ban_account",
               "permanent": True, "reason_code": "C106", "note": "赌博引流"})
    assert s3["permanent"] and s3["status"] == "active", s3
    call("DELETE", "/auth/me", bad3.token)
    again = sms_login(bad3.phone)["token"]
    new_id = call("GET", "/auth/me", again)["id"]
    assert new_id != bad3.id
    mine3 = call("GET", "/social/v1/me/sanctions", again)
    assert any(x["id"] == s3["id"] and x["status"] == "active" for x in mine3["active"]), mine3
    r = call("POST", "/social/v1/contacts", again, {"user_id": r1.id}, expect_error=True)
    sanctioned(r, "ban_account", point="social_write")
    call("POST", f"/admin/social/sanctions/{s3['id']}/revoke", adm2, {"note": "测试完撤掉"})
    print("  ✓ 注销再注册:还生效的永久封号原样跟到新账号上(同一条处罚,不多一条)")

    # ------------------------------------------------------------------ 10. 数据
    st = call("GET", "/admin/social/community-stats?days=30", adm)
    assert len(st["items"]) == 30 and st["days"] == 30
    today = st["items"][-1]
    assert today["messages"] >= 25 and today["active_chats"] >= 5, today
    assert today["reports"] >= 6 and today["sanctions"] >= 5, today
    assert st["totals"]["messages"] >= today["messages"]
    active = call("GET", "/admin/social/sanctions?status=active&action=mute", adm)["items"]
    assert any(x["id"] == mute_id and x["appeal"]["status"] == "upheld" for x in active)
    print(f"  ✓ 后台数据:30 天一天一行,今天 {today['messages']} 条消息、{today['reports']} 张举报、"
          f"{today['sanctions']} 次处置;处置记录能按状态 / 种类筛")

    print("e2e_social_moderation 全部通过 ✅")


if __name__ == "__main__":
    main()
