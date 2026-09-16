"""每个人接自己的 AI 机器人(#386):本机模型那一档从头走一遍。

## 这一条要证的是什么

**平台不做大模型级别的机器人,所有接入都是用户级别的,平台只负责搭建平台。**
落到协议上就是:服务端派活儿、你的设备生成、再交回来。所以要验:

1. 建号、改配置、删号,**只能管自己的** —— 别人的一律 404(不是 403:
   别人有没有这个号,也不该从这里探出来);
2. **服务端说了算的那几条**:该不该说、回谁、节奏。设备拿到的只有提示词;
3. **一件活儿只能交一次** —— 网络重试、两台设备同时在线,同一条不能发两遍;
4. 交回来的话走**和真人一样的发帖路径**;
5. 本机模式下**服务端没有它的地址和密钥**:探针回 409,不假装成功;
6. 每人几个是后台可调的,建满了说得清楚;
7. **不占开发者配额** —— 所有 AI 号在 FK 上都挂在官方开发者名下,
   那一层的 20 个配额要是把它们算进去,第 21 个用户会撞上一句和他毫无关系的话。

跑法:SUPERZ_API=http://127.0.0.1:8100 python -m tests.e2e_ai_my_bots
"""
import json
import random

from tests.chat_util import person
from tests.e2e_ai_bots import ensure_official_dev, set_flag, start_fake_model
from tests.miniapp_util import admin_token
from tests.util import call


def main() -> None:
    admin = admin_token()
    ensure_official_dev()
    set_flag(admin, "ai_bots_enabled", "on")
    me = person()
    tag = random.randint(10000, 99999)

    def mk(**kw):
        body = {"name": f"我的小z{tag}", "username": f"wode{tag}bot",
                "persona": "你是一位爱做饭的成都上班族,说话简短", "topics": "做饭,夜宵",
                "posts_per_day": 24, "replies_per_day": 48}
        body.update(kw)
        return me.post("/ai/v1/bots", body)

    lim = me.get("/ai/v1/limits")
    assert lim["enabled"] is True and lim["mine"] == 0 and lim["per_user"] >= 1, lim
    print(f"  ✓ 先告诉他规矩:每人最多 {lim['per_user']} 个,现在有 {lim['mine']} 个")

    bot = mk()
    uid = bot["user_id"]
    assert bot["mode"] == "client", "缺省是本机模型 —— 那一档我们连地址都不持有"
    assert bot["has_key"] is False and bot["endpoint"] == "", bot
    print(f"  ✓ 建了自己的号 {uid} @{bot['username']}(缺省本机模型)")

    # ---- 只能管自己的 ----
    other = person()
    assert not [x for x in other.get("/ai/v1/bots")["items"] if x["user_id"] == uid], \
        "别人的号不该出现在我的列表里"
    for method, path in (("PATCH", f"/ai/v1/bots/{uid}"), ("GET", f"/ai/v1/bots/{uid}/task"),
                         ("DELETE", f"/ai/v1/bots/{uid}")):
        e = call(method, path, other.token, {"active": False}, expect_error=True)
        assert e.get("_error") == 404, (
            f"{method} {path} 回的是 {e.get('_error')} —— 别人的号要 404 不是 403:"
            "回 403 等于承认「这个号存在」")
    print("  ✓ 别人的号一律 404(不是 403:存不存在也不该从这里探出来)")

    # ---- 服务端派活儿,设备只生成 ----
    t = me.get(f"/ai/v1/bots/{uid}/task")["task"]
    assert t and t["prompt"], f"刚建好、还没说过话,该派一件活儿:{t}"
    # 派哪一件看库里有没有近期的真人帖(回帖优先于发帖)。两种都要能接住 ——
    # 写死成 "post" 的话,这条在跑过别的套件的库上会假红
    assert t["kind"] in ("post", "reply"), t
    if t["kind"] == "reply":
        assert t["reply_to"], "回帖的活儿要说清楚回哪一条"
        assert "只回一句" in t["prompt"], t
    else:
        assert t["reply_to"] is None, t
        assert ("做饭" in t["prompt"] or "夜宵" in t["prompt"]
                or "身边的小事" in t["prompt"]), "发帖从他填的话题里挑由头"
    # **提示词里不许夹带模型配置** —— 本机那一档我们本来就没有,交出去更是荒唐
    assert "api_key" not in json.dumps(t) and "endpoint" not in json.dumps(t), t
    assert t["system"] == "你是一位爱做饭的成都上班族,说话简短", "人设原样交给设备当 system"
    assert t["max_chars"] and t["expires_in"], t
    print(f"  ✓ 领到一件活儿({t['kind']}),提示词和人设都给了设备")

    # 领了就有节流:紧接着再领拿不到第二件(**不然一台设备能把一天的量一口气领完**)
    assert me.get(f"/ai/v1/bots/{uid}/task")["task"] is None, \
        "刚领过就又派一件的话,设备转一圈就能把节奏绕开"
    print("  ✓ 刚领过不再派第二件")

    # ---- 交差:走和真人一样的路 ----
    said = "今晚拿剩的米饭炒了个蛋炒饭,比外卖香"
    r = me.post(f"/ai/v1/bots/{uid}/task/{t['task_id']}", {"text": f"「{said}」"})
    assert r["text"] == said, f"首尾的引号该收拾掉:{r}"
    pid = r["pid"]
    got = person().get(f"/forum/v1/posts/{pid}")["post"]
    assert got["text"] == said and got["author"]["is_ai"] is True, (
        f"真人看得见这条帖,而且作者名片上带着 AI 标:{got}")
    if t["kind"] == "reply":
        assert (got.get("reply_to") or {}).get("pid") == t["reply_to"], (
            f"回帖要挂在服务端指定的那一条下面,不是设备自己挑的:{got}")
        assert got["reply_to"]["author"]["is_ai"] is False, (
            "只回真人的帖 —— AI 之间互相回会滚成一片没人看的对话")
    print(f"  ✓ 交回来的话发出去了:{pid}「{said}」,名片上带 AI 标")

    # ---- 一件活儿只能交一次 ----
    e = call("POST", f"/ai/v1/bots/{uid}/task/{t['task_id']}", me.token,
             {"text": "再发一遍"}, expect_error=True)
    assert e.get("_error") == 409, (
        f"同一件活儿交了两次都成功 —— 网络重试、两台设备同时在线时会发重:{e}")
    e = call("POST", f"/ai/v1/bots/{uid}/task/aaaaaaaaaaaa", me.token,
             {"text": "我自己编一个活儿号"}, expect_error=True)
    assert e.get("_error") == 409, "编一个活儿号就能发帖的话,前面那几条限制全是摆设"
    print("  ✓ 一件活儿只能交一次,编的活儿号交不进来")

    # ---- 本机模式:服务端没有它的地址和密钥 ----
    e = call("POST", f"/ai/v1/bots/{uid}/probe", me.token, {}, expect_error=True)
    assert e.get("_error") == 409 and "设备" in str(e.get("detail")), e
    print("  ✓ 本机模式探不了(模型在他自己的设备上),回 409 不假装成功")

    # ---- 换成公网地址:地址要过内网守卫 ----
    e = call("PATCH", f"/ai/v1/bots/{uid}", me.token,
             {"mode": "server", "endpoint": "https://169.254.169.254/latest/v1"},
             expect_error=True)
    assert e.get("_error") == 422 and "内网或回环" in str(e.get("detail")), (
        f"填云厂商元数据地址来探我们内网,必须当场拒:{e}")
    endpoint = start_fake_model()
    r = me.patch(f"/ai/v1/bots/{uid}", {"mode": "server", "endpoint": endpoint,
                                        "model": "fake-1", "api_key": "sk-mine"})
    assert r["has_key"] is True and "sk-mine" not in json.dumps(r, ensure_ascii=False), \
        f"密钥读不回来:{r}"
    probe = me.post(f"/ai/v1/bots/{uid}/probe", {})
    assert probe["ok"] is True and probe["reply"], probe
    assert "sk-mine" not in json.dumps(probe, ensure_ascii=False), "探针也不许回明文密钥"
    print("  ✓ 换成公网地址:元数据地址被拒、密钥存得进读不回来、探针答上来了")

    # 公网模式不收设备交回来的东西 —— 两条路不能混着走
    e = call("GET", f"/ai/v1/bots/{uid}/task", me.token, expect_error=True)
    assert e.get("_error") == 409, e
    print("  ✓ 公网模式不派活儿给设备(平台自己按节奏调)")

    # ---- 每天几条被后台那个上限夹住 ----
    set_flag(admin, "ai_posts_per_day_max", "3")
    r = me.patch(f"/ai/v1/bots/{uid}", {"posts_per_day": 200})
    assert r["posts_per_day"] == 3, f"后台拨到 3,填 200 该被夹到 3:{r}"
    set_flag(admin, "ai_posts_per_day_max", "48")
    print("  ✓ 每天发几条被后台的上限夹住")

    # ---- 每人几个:拨到 1 就建不了第二个 ----
    set_flag(admin, "ai_bots_per_user", "1")
    e = call("POST", "/ai/v1/bots", me.token,
             {"name": f"第二个{tag}", "username": f"dier{tag}bot",
              "persona": "你是一位夜跑的人"}, expect_error=True)
    assert e.get("_error") == 409 and "最多 1 个" in str(e.get("detail")), e
    set_flag(admin, "ai_bots_per_user", "20")
    print("  ✓ 名额用完了说得清楚(拨到 1 就建不了第二个)")

    # ---- 不占开发者那 20 个配额 ----
    # 所有 AI 号在 FK 上都挂在**同一个**官方开发者名下。那一层的配额要是把它们
    # 算进去,第 21 个用户建第一个号时会撞上「每个开发者最多 20 个机器人」——
    # 一句和他毫无关系的话。这里用两个不同的人各建一个来证明配额是按人算的
    them = person()
    theirs = call("POST", "/ai/v1/bots", them.token,
                  {"name": f"他的小z{tag}", "username": f"tade{tag}bot",
                   "persona": "你是一位爱看球的人"})
    assert theirs["user_id"] != uid, theirs
    assert them.get("/ai/v1/limits")["mine"] == 1, "名额是按人算的,不是全平台共用一份"
    print("  ✓ 名额按人算(排除开发者配额那一条由单测守查询形状)")

    # ---- 删号:发过的帖还在 ----
    me.delete(f"/ai/v1/bots/{uid}")
    assert not [x for x in me.get("/ai/v1/bots")["items"] if x["user_id"] == uid], "该没了"
    still = person().get(f"/forum/v1/posts/{pid}")["post"]
    assert still["text"] == said, "删号不该把它发过的帖带走 —— 别人回过的串会断掉"
    assert me.get("/ai/v1/limits")["mine"] == 0, "删掉之后名额要还回来"
    print("  ✓ 删掉了,发过的帖还在,名额还回来了")

    set_flag(admin, "ai_bots_enabled", "off")
    print("\n用户级 AI 机器人 e2e 通过 ✓")


if __name__ == "__main__":
    main()
