"""AI 助手令牌分权限(迁移 0131):点餐 / 发视频 / 发布小程序各一张白名单,真接口走一遍。

- 签发:账号类型决定能勾哪几项(用户端:点餐、发视频;开发者:发布小程序;商家签不了);
  GET /auth/agent-tokens/current 说清这个令牌能做什么(MCP 据此只列能用的工具);
- 发视频:建稿 → 分片传原片 → 挂分 P → 改简介 → 提审,**全程用助手令牌**,停在「审核中」;
  下单、点赞、删稿、读别的社交接口被拒;点餐令牌碰不了投稿;
- 发布小游戏:建应用 → 填上架信息 → 传包 → 提审 →(平台的人审过)→ 发布上线,**全程用助手令牌**;
  改密钥、删应用、下单被拒;没过审的版本发布不了。

    SUPERZ_API=http://127.0.0.1:8013 python -m tests.e2e_agent_scopes
"""
import time
import urllib.error
import urllib.request
import uuid

from tests.miniapp_util import (CHECKLIST_ALL, HELLO, LISTING, admin_token, developer, make_zip,
                                upload)
from tests.util import BASE, call, login
from tests.video_util import ffmpeg_clip, uploader


def denied(token: str, method: str, path: str, body=None) -> str:
    r = call(method, path, token, body if body is not None else ({} if method != "GET" else None),
             expect_error=True)
    assert r.get("_error") == 403, (method, path, r)
    return str(r.get("detail"))


def put_chunk(token: str, upload_id: str, n: int, data: bytes) -> None:
    req = urllib.request.Request(f"{BASE}/media/v1/uploads/{upload_id}/chunks/{n}", data=data,
                                 method="PUT")
    req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            assert r.status == 200
    except urllib.error.HTTPError as e:
        raise AssertionError(f"传第 {n} 片失败:{e.code} {e.read()[:200]}")


def main() -> None:
    # ---- 签发:账号类型决定能勾哪几项 ----
    up = uploader("139")                                   # 用户端账号,已实名
    t = call("POST", "/auth/agent-tokens", up.token, {"name": "投稿助手", "scopes": ["video"]})
    assert t["scopes"] == ["video"] and t["scope_labels"] == ["发视频"], t
    agent = t["token"]
    cur = call("GET", "/auth/agent-tokens/current", agent)
    assert cur["scopes"] == ["video"] and cur["name"] == "投稿助手" and cur["role"] == "customer", cur
    assert call("GET", "/auth/agent-tokens/current", up.token, expect_error=True)["_error"] == 404
    r = call("POST", "/auth/agent-tokens", up.token, {"scopes": ["miniapp"]}, expect_error=True)
    assert r["_error"] == 422, r
    both = call("POST", "/auth/agent-tokens", up.token, {"scopes": ["video", "order", "video"]})
    assert both["scopes"] == ["order", "video"], both    # 去重、按表里的顺序
    plain = call("POST", "/auth/agent-tokens", up.token, {"name": "只点餐"})
    assert plain["scopes"] == ["order"], plain           # 不勾 = 只点餐,和从前签的一样
    listed = {x["name"]: x for x in call("GET", "/auth/agent-tokens", up.token)}
    assert listed["投稿助手"]["scope_labels"] == ["发视频"], listed
    merchant = login("13800000002")
    assert call("POST", "/auth/agent-tokens", merchant, {}, expect_error=True)["_error"] == 403
    print("✓ 签发:用户端能勾点餐、发视频,开发者能勾发布小程序,商家签不了;current 说清能做什么")

    # ---- 发视频:全程用助手令牌 ----
    zones = call("GET", "/video/v1/zones", agent)
    assert zones, zones
    d = call("POST", "/video/v1/uploads/videos", agent,
             {"title": "助手投的第一条", "zone": "tech", "tags": ["AI 助手"],
              "description": "用 MCP 投的稿"})
    vid = d["vid"]
    clip = ffmpeg_clip(640, 360, 3)
    u = call("POST", "/media/v1/uploads", agent,
             {"size": len(clip), "name": "clip.mp4", "mime": "video/mp4", "purpose": "video",
              "kind": "video_source"})
    cs = u["chunk_size"]
    for n in range(u["chunks"]):
        put_chunk(agent, u["id"], n, clip[n * cs:(n + 1) * cs])
    got = call("GET", f"/media/v1/uploads/{u['id']}", agent)
    assert len(got["received"]) == u["chunks"], got
    m = call("POST", f"/media/v1/uploads/{u['id']}/complete", agent, {"kind": "video_source"})
    call("POST", f"/video/v1/videos/{vid}/parts", agent, {"media_id": m["id"], "title": "P1"})
    call("PATCH", f"/video/v1/videos/{vid}", agent, {"description": "助手改过的简介"})
    call("POST", f"/video/v1/videos/{vid}/submit", agent)
    deadline = time.time() + 240
    while True:
        v = call("GET", f"/video/v1/creator/videos/{vid}", agent)
        if v["status"] == "reviewing":
            break
        assert time.time() < deadline, f"四分钟没进审核:{v['status']}"
        time.sleep(1)
    assert v["description"] == "助手改过的简介", v
    mine = call("GET", "/video/v1/creator/videos", agent)
    assert any(x["vid"] == vid for x in mine["items"]), mine
    print("✓ 发视频:建稿 → 分片传片 → 挂分 P → 改简介 → 提审,停在「审核中」,全程助手令牌")

    msg = denied(agent, "POST", "/orders", {"merchant_id": 1, "items": [], "address": "x",
                                             "lat": 30.6, "lng": 104.0})
    assert "发视频" in msg and "付款" in msg, msg          # 说清这个令牌能做什么、什么只能自己做
    denied(agent, "POST", f"/video/v1/videos/{vid}/like")
    denied(agent, "DELETE", f"/video/v1/videos/{vid}")
    denied(agent, "GET", "/social/v1/me")
    denied(agent, "POST", "/auth/agent-tokens", {"scopes": ["video"]})   # 不能给自己再签
    denied(plain["token"], "POST", "/video/v1/uploads/videos", {"title": "点餐令牌来投稿"})
    print("✓ 发视频令牌下不了单、点不了赞、删不了稿;点餐令牌投不了稿;拒绝的话说清能做什么")

    # ---- 发布小游戏:开发者账号,全程用助手令牌 ----
    dev_token, _ = developer()
    t2 = call("POST", "/auth/agent-tokens", dev_token, {"name": "发布助手"})
    assert t2["scopes"] == ["miniapp"], t2                 # 开发者不勾 = 发布小程序
    assert call("POST", "/auth/agent-tokens", dev_token, {"scopes": ["order"]},
                expect_error=True)["_error"] == 422
    dagent = t2["token"]
    assert call("GET", "/auth/agent-tokens/current", dagent)["scope_labels"] == ["发布小程序和小游戏"]
    me = call("GET", "/dev/v1/me", dagent)
    assert me, me
    created = call("POST", "/dev/v1/apps", dagent,
                   {"name": f"助手小游戏{uuid.uuid4().hex[:4]}", "kind": "game", "category": "casual"})
    appid = created["app"]["appid"]
    call("PUT", f"/dev/v1/apps/{appid}", dagent, LISTING)
    ver = upload(dagent, appid, make_zip(HELLO, kind="game"), version="1.0.0",
                 changelog="助手传的第一版")["version"]
    listed_v = call("GET", f"/dev/v1/apps/{appid}/versions", dagent)["items"]
    assert any(x["id"] == ver["id"] for x in listed_v), listed_v
    r = call("POST", f"/dev/v1/apps/{appid}/versions/{ver['id']}/release", dagent,
             expect_error=True)
    assert r.get("_error") in (409, 422), f"没过审的版本发布上线了:{r}"
    call("POST", f"/dev/v1/apps/{appid}/versions/{ver['id']}/submit", dagent,
         {"review_note": "打开就是首页"})
    call("POST", f"/admin/mini-apps/reviews/{ver['id']}/decide", admin_token(),
         {"approve": True, "checklist": CHECKLIST_ALL})     # 审核是平台的人做的
    app = call("POST", f"/dev/v1/apps/{appid}/versions/{ver['id']}/release", dagent)
    assert (app.get("current_version") or {}).get("id") == ver["id"], app
    print("✓ 发布小游戏:建应用 → 传包 → 提审 → 平台审过 → 发布上线,全程助手令牌;没过审的发不了")

    denied(dagent, "POST", f"/dev/v1/apps/{appid}/secret/rotate")
    denied(dagent, "POST", f"/dev/v1/apps/{appid}/remove")
    denied(dagent, "PUT", f"/dev/v1/apps/{appid}/domains", {"domains": []})
    denied(dagent, "POST", "/dev/v1/me/agreement", {"revision": 1})
    denied(dagent, "GET", "/orders")
    print("✓ 发布助手改不了密钥和域名、删不了应用、签不了协议、看不了订单")

    # 清场:吊销这次签的令牌
    for tok in (up.token, dev_token):
        for x in call("GET", "/auth/agent-tokens", tok):
            if not x["revoked"]:
                call("DELETE", f"/auth/agent-tokens/{x['id']}", tok)
    assert call("GET", "/auth/agent-tokens/current", agent, expect_error=True)["_error"] == 401
    print("e2e_agent_scopes 全部通过 ✅")


if __name__ == "__main__":
    main()
