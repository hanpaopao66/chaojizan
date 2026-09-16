"""聊天离线推送 e2e(DEV-PROMPTS-40 #353;群上限提到 20 万之后的分批扇出)。

守的是 chat_push.notify_message 那四条规则,以及**它们在分批扫成员的前提下仍然成立**:

- 群里发一条,除了发送人,每个该收到的成员都记一条 push_log;
- 发送人自己不推;
- 免打扰的会话不推,**除非回复了他 / @ 了他**;
- 在「通知」里关掉了「群」这一类的人不推。

为什么要单独有这一条:群上限从 1,000 提到 20 万(D7)之后,推送不能再「把成员
全查出来再逐个推」,改成按 user_id 分批扫。分批最容易出的错是**静默漏人** ——
少扫一批不会报错、不会崩,只是有些人收不到消息提醒,而这件事没人会来报 bug。
e2e 环境把 `CHAT_PUSH_CHUNK` 设成 2(scripts/e2e_iso.sh、CI),所以下面这个
四个人的群横跨三批:漏一批,断言立刻红。

push_logs 在推送服务没配时也照记(record_skip=True),所以本地和 CI 都能断言。

跑法:SUPERZ_API=http://127.0.0.1:8013 DATABASE_URL=… python -m tests.e2e_chat_push
"""
import time

from tests.chat_util import person
from tests.miniapp_util import sql


def pushes(user_id: int) -> list[tuple]:
    """这个人收到的推送(标题, 正文),新的在前。

    push_logs 里没有会话 id,所以按人过滤 —— 这几个号都是这条 e2e 现开的,
    他们名下的推送只可能来自这里。
    """
    rows = sql("select title, content from push_logs where user_id = :u order by id desc",
               {"u": user_id}, fetch="all")
    return [tuple(r) for r in rows]


def wait_pushes(user_id: int, n: int, *, seconds: float = 8.0) -> list[tuple]:
    """推送是发完消息之后在后台做的(after_commit),等它落库 —— 不等的话断言在和调度赛跑。"""
    deadline = time.time() + seconds
    rows: list[tuple] = []
    while time.time() < deadline:
        rows = pushes(user_id)
        if len(rows) >= n:
            return rows
        time.sleep(0.3)
    return rows


def main():
    owner, a, b, c = person(), person(), person(), person()
    print(f"  账号:群主={owner.id} 正常={a.id} 免打扰={b.id} 关了群通知={c.id}")

    g = owner.post("/chat/v1/chats", {"type": "group", "title": "大群分批测试",
                                      "member_ids": [a.id, b.id, c.id]})
    gid = g["id"]
    assert g["member_count"] == 4, g

    # b 把这个会话设成免打扰;c 在「通知」里关掉「群」这一类
    b.patch(f"/chat/v1/dialogs/{gid}", {"muted_until": "forever"})
    c.patch("/social/v1/me", {"notify": {"group": False}})

    # ---- 一条普通消息:只有 a 该收到 ----
    owner.send(gid, "晚上七点老地方")
    got = wait_pushes(a.id, 1)
    assert len(got) == 1, f"正常成员没收到推送:{got}"
    assert "晚上七点老地方" in got[0][1], got
    print("  ✓ 普通成员收到了,正文带预览")

    # 这三个人一个都不该有。发送人自己不推;免打扰和关了群通知的也不推。
    # (四个人 + CHAT_PUSH_CHUNK=2 → 横跨三批,漏扫一批这里就会多出或少掉)
    for who, why in ((owner, "发送人自己"), (b, "免打扰"), (c, "关了群通知")):
        assert pushes(who.id) == [], f"{why}不该收到推送:{pushes(who.id)}"
    print("  ✓ 发送人自己、免打扰的、关了群通知的都没推")

    # ---- 回复免打扰的人:他照样收到(规则里那个「除非」)----
    mine = b.send(gid, "我在")
    owner.send(gid, "说你呢", reply_to_seq=mine["seq"])
    got = wait_pushes(b.id, 1)
    assert len(got) == 1, f"免打扰的人被回复了还是该收到:{got}"
    print("  ✓ 免打扰的人被回复了照样收到")

    # 关了群通知的那位,这一轮依然没有(回复的不是他)
    assert pushes(c.id) == [], pushes(c.id)

    # ---- 一路下来 a 该收到 3 条:群主两条 + b 那条「我在」。少一条就是某一批被漏扫了 ----
    got = wait_pushes(a.id, 3)
    assert len(got) == 3, f"a 应该收到 3 条(群主 2 条 + b 1 条):{got}"
    print("  ✓ 每条各推各的,没有互相顶掉")

    print("聊天推送 e2e 通过 ✓")


if __name__ == "__main__":
    main()
