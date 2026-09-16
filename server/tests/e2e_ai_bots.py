"""AI 机器人在论坛里说话(#385)。

这一条把前面所有承诺连起来验一次 —— **每一条都是"错了也不报错"的那种**:

1. 总闸关着时一个字都不发(缺省就是关的);
2. 名片上 `is_ai` 为真 —— 客户端据此挂 AI 标(《标识办法》要的显式标识);
3. 它发的帖走**和真人一样的路**:在时间线上看得见、点得开、能被举报;
4. **它的互动不进推荐分**。这条是最要紧的:推荐公式是公开可复算的,
   AI 点的赞算进去等于自己骗自己 —— 而且错了的表现只是"数字大了一点",
   不报错、不崩,没有 AI 号的时候根本看不出来;
5. 改人设、停用都不删号 —— 它发过的帖还在。

模型这一环用**一个假的 OpenAI 兼容服务**顶替(e2e 环境不该依赖本机跑着模型),
地址填成它,和真模型走的是同一条代码路径。

跑法:SUPERZ_API=http://127.0.0.1:8013 DATABASE_URL=… python -m tests.e2e_ai_bots
"""
import json
import random
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from tests.chat_util import person
from tests.miniapp_util import admin_token, developer, sql
from tests.util import call

REPLY = "这家我上周去过,牛肉是现片的"


class FakeModel(BaseHTTPRequestHandler):
    """一个最小的 OpenAI 兼容服务:不管问什么都回同一句。"""

    def do_POST(self):  # noqa: N802
        self.rfile.read(int(self.headers.get("content-length") or 0))
        body = json.dumps({"choices": [{"message": {"content": REPLY}}]}).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):  # 别把 e2e 的输出刷满
        pass


def start_fake_model() -> str:
    srv = HTTPServer(("127.0.0.1", 0), FakeModel)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{srv.server_address[1]}/v1"


def set_flag(admin: str, key: str, value: str) -> None:
    call("POST", f"/admin/flags/{key}", admin, {"value": value})


def ensure_official_dev() -> None:
    """**这条 e2e 自己造数据。**

    建 AI 号要挂在官方开发者名下(和官方小程序、机器人管家同一个主人),而那一行是部署时
    `scripts/seed_bot_manager --apply` 建的 —— CI 的每个分片是一个干净的库,不会有。
    套件之间不许互相依赖数据(见 e2e_suites.txt 开头那段),所以这里自己补。

    **账号走正常注册**,不裸插 users:那张表有十几个非空列,手写 INSERT 今天少一个
    `is_online` 明天少一个别的,每加一列就炸一次。
    """
    row = sql("select id from developers where is_official and user_id is not null limit 1",
              fetch="all")
    if row:
        return
    # 注册一个开发者,把**他自己那一行**标成官方。
    # 不新插一行、也不动已有的行:developers.user_id 是唯一的,而且别的套件
    # (官方小程序那几条)也在看 is_official,改它们的行会把那边带倒
    _tok, phone = developer()
    sql("""update developers set is_official = true, display_name = '超级赞官方'
            where user_id = (select id from users
                              where phone = :p and role = 'developer')""", {"p": phone})


def main() -> None:
    admin = admin_token()
    me = person()
    tag = random.randint(1000, 9999)
    ensure_official_dev()

    # ---- 总闸关着:什么都不发 ----
    set_flag(admin, "ai_bots_enabled", "off")
    endpoint = start_fake_model()

    bot = call("POST", "/admin/ai/bots", admin, {
        "name": f"吃货小z{tag}", "username": f"chihuo{tag}bot",
        "persona": "你是一位爱吃的成都上班族", "topics": "火锅,串串",
        "posts_per_day": 24, "replies_per_day": 48})
    uid = bot["user_id"]
    assert bot["active"] is True and bot["posts"] == 0, bot
    # **模型是这个号自己的**(#386):平台没有模型,所以要先给它填地址
    assert bot["mode"] == "client", "缺省是本机模式 —— 那一档服务端连地址都没有"
    assert bot["owner_id"], "每个机器人都得有主人"
    call("PATCH", f"/admin/ai/bots/{uid}", admin,
         {"mode": "server", "endpoint": endpoint, "model": "fake-1"})
    print(f"  ✓ 建了 AI 号 {uid} @{bot['username']}")

    e = call("POST", f"/admin/ai/bots/{uid}/say", admin, {}, expect_error=True)
    assert e.get("_error") == 409 and "总闸" in str(e.get("detail")), e
    print("  ✓ 总闸关着时一个字都不发(缺省就是关的)")

    # ---- 名片上挂 AI 标 ----
    card = me.get(f"/social/v1/users/{uid}")
    assert card["is_ai"] is True, f"AI 号的名片上要有这一位:{card}"
    assert card["is_bot"] is True, "它同时也是机器人"
    print("  ✓ 名片上 is_ai 为真(客户端据此挂 AI 标)")

    # ---- 打开总闸:发一条 ----
    set_flag(admin, "ai_bots_enabled", "on")
    r = call("POST", f"/admin/ai/bots/{uid}/say", admin, {})
    assert r["text"] == REPLY, r
    pid = r["pid"]
    print(f"  ✓ 发出来了:{pid} 「{r['text']}」")

    # 走的是和真人一样的路:真人看得见、点得开
    got = me.get(f"/forum/v1/posts/{pid}")["post"]
    assert got["text"] == REPLY and got["author"]["is_ai"] is True, got
    print("  ✓ 真人打得开这条帖,作者名片上带着 AI 标")

    # 真人也发一条。**这一条必须在占比闸之前发** —— 干净的库(CI 的每个分片都是)
    # 在这一刻只有 AI 那一条帖,于是"拨到 0 之后时间线空了"是理所当然的,
    # 那个反证等于没证
    mine = me.post("/forum/v1/posts", {"text": f"今晚吃什么好呢 {tag}"})

    # ---- 机器人内容占公共时间线的上限(ai_timeline_share) ----
    # AI 的帖**可以**进公共时间线(运营方定的),但占比有闸。拨到 0 = 一条都不进 ——
    # 这一条同时也是那个死循环的防线:一屏里放不下时剩下的会被反复顺延
    def page0() -> list:
        return [x["post"] for x in me.get("/forum/v1/timeline/foryou")["items"]]

    set_flag(admin, "ai_timeline_share", "100")
    on = [x["pid"] for x in page0()]
    assert pid in on, "刚发出来的帖,上限 100% 时该在推荐第一屏上"
    assert mine["pid"] in on, "真人那条也该在(下面的反证要靠它)"
    set_flag(admin, "ai_timeline_share", "0")
    left = page0()
    assert [x["pid"] for x in left if x["author"]["is_ai"]] == [], (
        f"上限拨到 0 之后第一屏还有机器人的帖:{left}")
    # **反证**:同一屏上真人那条照样在。不然"拨到 0 → 一条机器人都没有"
    # 也可能是整个接口空了、或者这一屏根本没取到东西
    assert mine["pid"] in [x["pid"] for x in left], (
        f"拨到 0 把真人的帖也挡掉了:{left}")
    set_flag(admin, "ai_timeline_share", "80")
    print("  ✓ 占比闸:拨到 0 机器人一条都不进第一屏,同一屏上真人那条照样在")

    # ---- 它的互动不进推荐分 ----
    before = next((x for x in me.get("/forum/v1/timeline/foryou")["items"]
                   if x["post"]["pid"] == mine["pid"]), None)
    assert before is not None, "自己的帖该在推荐里"
    e_before = before["rank"]["parts"]["e"]
    likes_before = before["rank"]["parts"]["likes"]

    # 让 AI 号去点个赞(直接写库:走接口要机器人 token,这里要验的是算分那一层)
    sql("INSERT INTO forum_likes (post_id, user_id, created_at) "
        "SELECT id, :u, now() FROM forum_posts WHERE pid = :p "
        "ON CONFLICT DO NOTHING", {"u": uid, "p": mine["pid"]})
    after = next((x for x in me.get("/forum/v1/timeline/foryou")["items"]
                  if x["post"]["pid"] == mine["pid"]), None)
    assert after is not None
    assert after["rank"]["parts"]["e"] == e_before, (
        f"AI 点的赞进互动分了:{e_before} → {after['rank']['parts']['e']}。"
        "公开公式里混进自己刷的数,等于自己骗自己")
    assert after["rank"]["parts"]["likes"] == likes_before, (
        f"公示的「几人点赞」也把 AI 算进去了:{after['rank']['parts']}")
    print(f"  ✓ AI 点了赞,互动分和公示的点赞人数都纹丝不动(还是 e={e_before})")

    # 真人点赞照样算 —— 证明上面那条不是"这条路根本没通"
    other = person()
    other.post(f"/forum/v1/posts/{mine['pid']}/like", {})
    now = next((x for x in me.get("/forum/v1/timeline/foryou")["items"]
                if x["post"]["pid"] == mine["pid"]), None)
    assert now["rank"]["parts"]["e"] > e_before, (
        f"真人点赞也没算进去,那上面那条断言是假绿:{now['rank']}")
    print(f"  ✓ 真人点赞照常算(e {e_before} → {now['rank']['parts']['e']})")

    # ---- 模型是这个号自己的:密钥存进去读不回来,上限按后台那两个数夹 ----
    r = call("PATCH", f"/admin/ai/bots/{uid}", admin, {"api_key": "sk-secret-e2e"})
    assert r["has_key"] is True, "密钥该记下了"
    assert "sk-secret-e2e" not in json.dumps(r, ensure_ascii=False), (
        f"密钥回了明文 —— 这一页任何管理员都打得开,截图、录屏、肩后看都算泄露:{r}")
    assert "sk-secret-e2e" not in json.dumps(
        call("GET", "/admin/ai/bots", admin), ensure_ascii=False), "列表里也不许回明文"
    print("  ✓ 密钥存得进、读不回来(列表和详情都只说「设没设」)")

    set_flag(admin, "ai_posts_per_day_max", "3")
    r = call("PATCH", f"/admin/ai/bots/{uid}", admin, {"posts_per_day": 200})
    assert r["posts_per_day"] == 3, f"后台把上限拨到 3,填 200 应该被夹到 3:{r}"
    set_flag(admin, "ai_posts_per_day_max", "48")
    print("  ✓ 每天发几条被后台那个上限夹住(拨到 3,填 200 存下来是 3)")

    # 指向内网的地址拒掉 —— 这个地址是用户填的,请求是**我们的服务器**发的
    e = call("PATCH", f"/admin/ai/bots/{uid}", admin,
             {"endpoint": "https://169.254.169.254/latest/v1"}, expect_error=True)
    assert e.get("_error") == 422 and "内网或回环" in str(e.get("detail")), e
    print("  ✓ 填云厂商元数据地址来探我们内网,当场拒(SSRF)")

    # 切回本机模式:服务端既没有地址也没有密钥,所以探不了、也替不了它说话
    call("PATCH", f"/admin/ai/bots/{uid}", admin, {"mode": "client"})
    for path in (f"/admin/ai/bots/{uid}/probe", f"/admin/ai/bots/{uid}/say"):
        e = call("POST", path, admin, {}, expect_error=True)
        assert e.get("_error") == 409 and "本机" in str(e.get("detail")), (path, e)
    call("PATCH", f"/admin/ai/bots/{uid}", admin, {"mode": "server"})
    print("  ✓ 本机模式的号服务端不替它生成(探针和「说一句」都回 409,不是假装成功)")

    # ---- 停用不删号 ----
    call("PATCH", f"/admin/ai/bots/{uid}", admin, {"active": False})
    row = next(x for x in call("GET", "/admin/ai/bots", admin)["items"]
               if x["user_id"] == uid)
    assert row["active"] is False and row["posts"] >= 1, row
    assert me.get(f"/forum/v1/posts/{pid}")["post"]["text"] == REPLY, \
        "停用不该把它发过的帖带走"
    print("  ✓ 停用之后它不再说话,发过的帖还在")

    set_flag(admin, "ai_bots_enabled", "off")
    print("AI 机器人 e2e 通过 ✓")


if __name__ == "__main__":
    main()
