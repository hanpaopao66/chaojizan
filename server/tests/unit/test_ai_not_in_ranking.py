"""AI 的互动不进公开排序(#385)。

这是引入 AI 机器人时**唯一不能松的那条**:推荐和榜单的公式是公开的、
任何人可以照着复算的(论坛 §5.7、视频 §5.9、音乐 §5.4)。AI 号点的赞、
转的帖、加的歌单如果算进去,那份"可复算"就成了自己骗自己 ——
而且是从内部骗起:运营看到的热度里有一部分是自己刷的。

这里测的是**取数那一层的 SQL 里有没有那道闸**。三个模块各有各的写法
(论坛和视频是裸 SQL,音乐是 ORM),所以分别查。真正跑通数据的断言在
e2e_ai_bots 里 —— 那边造一个 AI 号去点赞,看榜单动没动。

为什么用"读源码"这种笨办法:这道闸漏掉的表现是**数字偏大一点点**,
不报错、不崩,而且只有在有 AI 号之后才看得出来。等有人发现时,
公开的榜单已经错了很久了。
"""
import re
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "app" / "services"


def source(name: str) -> str:
    return (SRC / name).read_text(encoding="utf-8")


def test_论坛四种互动全都排掉了_AI():
    from app.services.forum_feed import _WINDOW_SQL

    # 四条 union:点赞、转发、引用、回复
    assert _WINDOW_SQL.count("UNION ALL") == 3
    assert _WINDOW_SQL.count("is_ai") == 4, (
        "四种互动每种都要挂那道闸,漏一种就能从那一种刷热度:\n" + _WINDOW_SQL)


def test_视频六种带账号的互动排掉了_AI():
    from app.services.video_feed import _WINDOW_SQL

    # 七条里有一条是浏览(按 viewer_key 去重,可能是没登录的人,没有 user_id 可判)
    assert _WINDOW_SQL.count("UNION ALL") == 6
    assert _WINDOW_SQL.count("is_ai") == 6, (
        "除了浏览,其余六种都要挂:\n" + _WINDOW_SQL)


def test_视频的浏览那条是按设备去重_所以不挂那道闸():
    """不是漏了:浏览按 viewer_key 去重,没登录的人也算,那里没有 user_id 可判。

    AI 也不会去"看"视频 —— 它没有播放器。
    """
    from app.services.video_feed import _WINDOW_SQL

    views = _WINDOW_SQL.split("UNION ALL")[0]
    assert "viewer_key" in views and "is_ai" not in views


def test_热门话题不把_AI_算进人头():
    s = source("forum_feed.py")
    trending = s[s.index("async def trending"):]
    trending = trending[:trending.index("\n\n\n")] if "\n\n\n" in trending else trending
    assert "User.is_ai.is_(False)" in trending, (
        "热门话题是「多少人在聊」,不是「我们生成了多少」")


def test_音乐的喜欢和加歌单不把_AI_算进人头():
    s = source("music_rank.py")
    for fn in ("_likers", "_playlisters"):
        body = s[s.index(f"async def {fn}"):]
        body = body[:body.index("\n\n\n")] if "\n\n\n" in body else body
        assert "User.is_ai.is_(False)" in body, f"{fn} 里没挂那道闸"


def test_收听人数那条按设备去重_不挂闸():
    """和视频的浏览同理:listener_key 可能是没登录的设备,没有 user_id 可判。"""
    s = source("music_rank.py")
    body = s[s.index("async def _listeners"):]
    body = body[:body.index("\n\n\n")]
    assert "listener_key" in body and "is_ai" not in body


def test_判据是_is_ai_不是_role_bot():
    """机器人管家那种脚本机器人是真的在替人干活,它的互动算数。

    要排掉的是**模型生成的**。这两件事混成一个判据的话,
    要么把管家的正常互动误伤掉,要么将来模型驱动一个普通账号时漏掉。
    """
    for name in ("forum_feed.py", "video_feed.py", "music_rank.py"):
        s = source(name)
        for m in re.finditer(r"[^\n]*is_ai[^\n]*", s):
            line = m.group(0)
            assert "role" not in line or "is_ai" in line, line


def test_名片上带_is_ai_显式标识():
    """客户端据此挂 AI 标 —— 这是《标识办法》要的显式标识那一半。"""
    s = source("social.py")
    assert '"is_ai": bool(u.is_ai)' in s
    assert '"is_bot"' in s, "两个标是分开的:是机器人 ≠ 是 AI"
