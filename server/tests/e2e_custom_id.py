"""超级赞号(相当于微信号)与加联系人 e2e(迁移 0133)。

- 改名:第一次随时能设;一年内再改被拒,告诉下次能改的日期;只改大小写不算修改;清空随时能清,
  清空之后再设算一次修改;满一年(改时间戳)能改;存量号(username_set_at 为空)下一次不用等;
- 冷冻:换掉 / 清空 / 注销释放的旧号,冷冻期内别人注册不了(超级赞号、频道的公开链接都不行),
  原主人不受冷冻限制(一年的名额照样要等);到期(改时间戳)别人能注册,冷冻记录跟着删掉;
- 找人:按超级赞号、名片编号、手机号找到名片,直接加联系人(不用对方同意,只加在自己这边);
- 「按超级赞号找到我」关掉:别人按号找 404(和没有这个号同一句话),全局搜索、视频里搜人都不出;
  名片链接换成 /u/<public_id>,照样打得开;按手机号找照旧;开关只有开 / 关两档。

**自己造账号,不用演示号**:CI 分组并行,演示号会和同组别的套件互相干扰。
跑法:SUPERZ_API=http://127.0.0.1:8031 DATABASE_URL=… REDIS_URL=… python -m tests.e2e_custom_id
"""
import random
import re
from datetime import datetime, time, timedelta, timezone

from tests.chat_util import person, sql
from tests.util import call
from tests.video_util import realname

BJ = timezone(timedelta(hours=8))
DATE = re.compile(r"\d{4}-\d{1,2}-\d{1,2}")


def uname(base: str) -> str:
    return f"{base}{random.randint(100000, 999999)}"


def err(r: dict, code: int) -> dict:
    assert r.get("_error") == code, r
    return r


def holds(name: str) -> int:
    return sql("SELECT count(*) FROM username_holds WHERE username_lc = :n", {"n": name.lower()},
               fetch="scalar")


def a_year_passed(p) -> None:
    """把上一次设置 / 修改挪到 366 天前(真等一年等不起)。"""
    sql("UPDATE social_profiles SET username_set_at = now() - interval '366 days' "
        "WHERE user_id = :u", {"u": p.id})


def ids(items) -> list[int]:
    return [x["id"] for x in items]


def main():
    a, b, c, d = person(), person(), person(), person()
    print(f"  账号:A={a.id} B={b.id} C={c.id} D={d.id}")

    # ---- 1. 第一次设置随时能设,设完开始算一年(按北京时间的日期) ----
    me = a.get("/social/v1/me")
    assert me["username"] is None and me["username_next_change_at"] is None, me
    n1 = uname("Cida")
    out = a.put("/social/v1/me/username", {"username": n1})
    nxt = out["username_next_change_at"]
    expect = datetime.combine(datetime.now(BJ).date() + timedelta(days=365), time.min, tzinfo=BJ)
    assert out["username"] == n1 and datetime.fromisoformat(nxt) == expect, (out, expect)
    assert out["link"].endswith(f"/@{n1}"), out["link"]
    print(f"  ✓ 第一次设置随时能设;下次可修改 {expect:%Y-%m-%d}(北京时间 365 天后那天零点)")

    # ---- 2. 一年内再改:被拒,告诉下次能改的时间;只改大小写不算修改 ----
    n2 = uname("Cidb")
    det = err(a.put("/social/v1/me/username", {"username": n2}, expect_error=True), 409)["detail"]
    assert det["error"] == "username_cooldown" and det["next_change_at"] == nxt, det
    assert f"下次可修改:{expect:%Y-%m-%d}" in det["message"], det
    assert a.get("/social/v1/me")["username"] == n1, "被拒的修改什么都没动"
    out = a.put("/social/v1/me/username", {"username": n1.upper()})
    assert out["username"] == n1.upper() and out["username_next_change_at"] == nxt, out
    assert holds(n1) == 0, "只改大小写:号还是这个号,不冷冻"
    print("  ✓ 一年内再改被拒(409,detail 带下次可修改的日期);只改大小写照改、不计次")

    # ---- 3. 满一年能改;换下来的旧号冷冻,别人注册不了,也解析不到任何人 ----
    a_year_passed(a)
    assert a.get("/social/v1/me")["username_next_change_at"] is None
    out = a.put("/social/v1/me/username", {"username": n2})
    assert out["username"] == n2 and out["username_next_change_at"], "改完重新算一年"
    assert holds(n1) == 1
    r = err(b.put("/social/v1/me/username", {"username": n1.lower()}, expect_error=True), 409)
    assert "冷冻" in r["detail"] and not DATE.search(r["detail"]), \
        f"说清是冷冻,但不说解冻日期(能倒推出原主人哪天换的号):{r}"
    chk = b.get(f"/social/v1/username-check?u={n1}")
    assert chk["ok"] is False and "冷冻" in chk["reason"], chk
    err(b.get(f"/social/v1/resolve/{n1}", expect_error=True), 404)
    assert b.get(f"/social/v1/resolve/{n2}")["user"]["id"] == a.id
    print("  ✓ 满一年能改;旧号冷冻:别人注册被拒(大小写不敏感)、实时检查说冷冻、解析不到任何人")

    # ---- 4. 频道的公开链接也拿不走冷冻中的号(共用一个命名空间) ----
    realname(b, "测试频道主")
    ch = b.post("/chat/v1/chats", {"type": "channel", "title": "超级赞号测试频道"})
    r = err(b.patch(f"/chat/v1/chats/{ch['id']}", {"username": n1}, expect_error=True), 409)
    assert "冷冻" in r["detail"], r
    print("  ✓ 频道公开链接也用不了冷冻中的超级赞号")

    # ---- 5. 原主人:清空随时能清;冷冻挡不住他,一年的名额照样要等 ----
    out = a.put("/social/v1/me/username", {"username": ""})
    assert out["username"] is None and out["username_next_change_at"], \
        "清空不看一年的名额,也不重新计时:下次能改的时间还在"
    assert out["link"].endswith(f"/u/{out['public_id']}"), out["link"]
    assert holds(n2) == 1
    det = err(a.put("/social/v1/me/username", {"username": n2}, expect_error=True), 409)["detail"]
    assert det["error"] == "username_cooldown", f"清空之后再设算一次修改:{det}"
    err(c.put("/social/v1/me/username", {"username": n2}, expect_error=True), 409)
    a_year_passed(a)
    chk = a.get(f"/social/v1/username-check?u={n2}")
    assert chk["ok"] is True, f"冷冻挡不住原主人:{chk}"
    out = a.put("/social/v1/me/username", {"username": n2})
    assert out["username"] == n2 and holds(n2) == 0, "原主人拿回来,冷冻记录删掉"
    print("  ✓ 原主人:清空随时能清;拿回来不受冷冻限制,但要等一年一次的名额")

    # ---- 6. 冷冻到期(改时间戳)别人就能注册,冷冻记录跟着删 ----
    sql("UPDATE username_holds SET frozen_until = now() - interval '1 second' "
        "WHERE username_lc = :n", {"n": n1.lower()})
    assert b.get(f"/social/v1/username-check?u={n1}")["ok"] is True
    out = b.put("/social/v1/me/username", {"username": n1})
    assert out["username"] == n1 and holds(n1) == 0, out
    assert d.get(f"/social/v1/resolve/{n1}")["user"]["id"] == b.id, "到期后这个号归了 B"
    print("  ✓ 冷冻到期后别人能注册,冷冻记录删掉")

    # ---- 7. 存量号(0133 之前设的,username_set_at 为空):下一次不用等,改完才开始算一年 ----
    n3, n4, n5 = uname("Cidc"), uname("Cidd"), uname("Cide")
    c.put("/social/v1/me/username", {"username": n3})
    sql("UPDATE social_profiles SET username_set_at = NULL WHERE user_id = :u", {"u": c.id})
    assert c.get("/social/v1/me")["username_next_change_at"] is None
    assert c.put("/social/v1/me/username", {"username": n4})["username_next_change_at"]
    det = err(c.put("/social/v1/me/username", {"username": n5}, expect_error=True), 409)["detail"]
    assert det["error"] == "username_cooldown", det
    print("  ✓ 存量号改一次不用等,改完开始算一年")

    # ---- 8. 注销账号:号和换号一样冷冻 ----
    e = person()
    n6 = uname("Cidf")
    e.put("/social/v1/me/username", {"username": n6})
    call("DELETE", "/auth/me", e.token)
    r = err(d.put("/social/v1/me/username", {"username": n6}, expect_error=True), 409)
    assert "冷冻" in r["detail"], r
    err(d.get(f"/social/v1/resolve/{n6}", expect_error=True), 404)
    print("  ✓ 注销账号释放的号也冷冻")

    # ---- 9. 按超级赞号 / 名片编号找人,直接加联系人(不用对方同意,只加在自己这边) ----
    card = d.get(f"/social/v1/resolve/{n2}")
    u = card["user"]
    assert card["type"] == "user" and u["id"] == a.id and u["username"] == n2, card
    assert {"name", "avatar"} <= set(u) and "phone" not in u, u
    added = d.post("/social/v1/contacts", {"user_id": a.id})
    assert added["is_contact"] is True, added
    assert a.id in ids(d.get("/social/v1/contacts")["items"])
    assert d.id not in ids(a.get("/social/v1/contacts")["items"]), "联系人是单向的"
    pid = a.get("/social/v1/me")["public_id"]
    assert d.get(f"/social/v1/resolve-id/{pid}")["user"]["id"] == a.id
    # 开关打开时,全局搜索、视频里搜人都能按号搜到(下面关掉之后要搜不到 —— 先确认搜得到,断言才有意义)
    assert a.id in ids(d.get(f"/chat/v1/search?q={n2}")["users"])
    assert a.id in ids(d.get(f"/video/v1/search/users?q={n2}")["items"])
    print("  ✓ 按超级赞号 / 名片编号找到名片,直接加进联系人(单向,不用对方同意)")

    # ---- 10. 关掉「按超级赞号找到我」 ----
    out = a.patch("/social/v1/me", {"privacy": {"username_search": "nobody"}})
    assert out["privacy"]["username_search"] == "nobody"
    assert out["link"].endswith(f"/u/{pid}"), f"名片码改用随机编号:{out['link']}"
    off = err(d.get(f"/social/v1/resolve/{n2}", expect_error=True), 404)
    none = err(d.get(f"/social/v1/resolve/{uname('Nobody')}", expect_error=True), 404)
    assert off["detail"] == none["detail"], "关了开关和没有这个号必须是同一句话"
    assert a.get(f"/social/v1/resolve/{n2}")["user"]["id"] == a.id, "自己找自己不受影响"
    assert d.get(f"/social/v1/resolve-id/{pid}")["user"]["id"] == a.id, "本人给出去的名片码照样能打开"
    assert a.id not in ids(d.get(f"/chat/v1/search?q={n2}")["users"]), "全局搜索也按号搜不到"
    assert a.id not in ids(d.get(f"/video/v1/search/users?q={n2}")["items"]), "视频里搜人也按号搜不到"
    # 按手机号找照旧(两个开关互不相干),关了按手机号找才找不到
    assert d.post("/social/v1/find-by-phone", {"phone": a.phone})["id"] == a.id
    a.patch("/social/v1/me", {"privacy": {"phone_search": "nobody"}})
    err(d.post("/social/v1/find-by-phone", {"phone": a.phone}, expect_error=True), 404)
    a.patch("/social/v1/me", {"privacy": {"phone_search": "everyone"}})
    # 开关只有开 / 关两档
    r = err(a.patch("/social/v1/me", {"privacy": {"username_search": "contacts"}},
                    expect_error=True), 422)
    assert "只能开或关" in r["detail"], r
    out = a.patch("/social/v1/me", {"privacy": {"username_search": "everyone"}})
    assert out["link"].endswith(f"/@{n2}"), out["link"]
    assert d.get(f"/social/v1/resolve/{n2}")["user"]["id"] == a.id
    print("  ✓ 关掉「按超级赞号找到我」:按号找 404(和没有这个号同一句话)、全局搜索和视频搜人不出、"
          "名片码换随机编号照样打得开、按手机号找照旧;打开后恢复")

    print("e2e_custom_id 全部通过 ✅")


if __name__ == "__main__":
    main()
