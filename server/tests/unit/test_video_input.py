"""弹幕 / 评论的输入校验和几个纯函数(DEV-PROMPTS-40 §5.10、#360 #362、§5.9 播放计数、雪碧图、播放签名)。"""
import pytest
from fastapi import HTTPException

from app.services import video as vsvc
from app.services import video_interact as act
from app.services import video_media as vmedia
from app.services import video_talk as talk

DUR = 10 * 60 * 1000


def ok(text="好", time_ms=1000, mode=1, color=16777215, size=25, duration=DUR):
    return talk.clean_danmaku(text, time_ms, mode, color, size, duration)


def bad(needle, **kw):
    with pytest.raises(HTTPException) as e:
        ok(**kw)
    assert e.value.status_code == 422 and needle in e.value.detail, e.value.detail


def test_danmaku_text_rules():
    assert ok("  前排  ") == "前排", "首尾空白去掉"
    assert ok("长" * 100) == "长" * 100
    bad("100 字", text="长" * 101)
    bad("不能为空", text="   ")
    bad("不能为空", text="")
    for ch in ("\n", "\r", "\t", "\v", "\f", "\u0085", "\u2028", "\u2029"):
        bad("一行", text=f"上{ch}下")
    assert ok("emoji 😀 也算一个字") == "emoji 😀 也算一个字"


def test_danmaku_mode_color_size_time():
    for m in (1, 4, 5):
        ok(mode=m)
    for m in (0, 2, 3, 6, 7):
        bad("模式", mode=m)
    for s in (18, 25):
        ok(size=s)
    bad("字号", size=20)
    ok(color=0)
    ok(color=0xFFFFFF)
    bad("颜色", color=-1)
    bad("颜色", color=0x1000000)
    bad("颜色", color=True)
    ok(time_ms=0)
    ok(time_ms=DUR)
    bad("长度", time_ms=DUR + 1)
    bad("长度", time_ms=-1)
    assert ok(time_ms=999_999, duration=0), "时长未知(0)时不按时长卡"


def test_comment_rules():
    assert talk.clean_comment("  多行\n评论也行  ") == "多行\n评论也行"
    assert talk.clean_comment("长" * 1000) == "长" * 1000
    for text, needle in (("", "不能为空"), ("   ", "不能为空"), ("长" * 1001, "1000 字")):
        with pytest.raises(HTTPException) as e:
            talk.clean_comment(text)
        assert e.value.status_code == 422 and needle in e.value.detail


def test_mentions_follow_username_rules():
    assert talk.parse_mentions("@Alice_1 和 @bob2x 还有 @alice_1") == ["alice_1", "bob2x"]
    assert talk.parse_mentions("邮箱 a@b.com 不算,@abc 太短,@1abcde 数字开头") == []
    assert talk.parse_mentions("@abcd_ 下划线结尾、@ab__cd 连续下划线") == []
    assert talk.parse_mentions("@hello_world,你好") == ["hello_world"]
    many = " ".join(f"@user{i:03d}x" for i in range(15))
    assert len(talk.parse_mentions(many)) == talk.MENTIONS_MAX == 10


# ---------------- 评论里的 @ 跟着「按超级赞号找到我」走(2026-09-14 拍板) ----------------

def _comment(mentions, text="@alice_z1 和 @bob_z22 来看"):
    from datetime import datetime, timezone

    from app.models import VideoComment
    return VideoComment(id=5, video_id=1, user_id=2, root_id=None, parent_id=None,
                        reply_to_user_id=None, text=text, mentions=mentions, likes=0,
                        reply_count=0, pinned=False,
                        created_at=datetime(2026, 9, 14, 12, tzinfo=timezone.utc))


def test_comment_out_drops_mentions_of_people_who_turned_the_switch_off():
    """展示时:@ 到的人现在关着开关,这条 mention 不下发(客户端当普通文字),和 @ 一个没注册的号
    长得一模一样;别人照旧。存的 mentions 不动 —— 他重新打开,链接就回来。"""
    from app.models import Video
    v = Video(vid="svAAAAAAAAAA", uploader_id=1)
    alice, bob = {"user_id": 7, "username": "alice_z1"}, {"user_id": 8, "username": "bob_z22"}
    c = _comment([alice, bob])
    assert talk.comment_out(c, v, {}, {}, mentions_hidden=set())["mentions"] == [alice, bob]
    off = talk.comment_out(c, v, {}, {}, mentions_hidden={7})
    assert off["mentions"] == [bob]
    never = talk.comment_out(_comment([bob]), v, {}, {}, mentions_hidden=set())
    assert off == never, "关了开关的号和从没注册过的号,出来的评论一模一样"
    assert c.mentions == [alice, bob], "只是不下发,库里存的不改"
    assert talk.comment_out(_comment(None), v, {}, {}, mentions_hidden={7})["mentions"] == []


def test_comment_out_must_be_told_who_is_hidden():
    """mentions_hidden 必传:哪天新加一个出评论的地方忘了查开关,当场报错,而不是静默地把号和人对上。"""
    from app.models import Video
    with pytest.raises(TypeError):
        talk.comment_out(_comment([]), Video(vid="svAAAAAAAAAA", uploader_id=1), {}, {})


def test_mentions_off_asks_once_about_everyone_on_the_page(monkeypatch):
    import asyncio
    from types import SimpleNamespace
    asked = []

    async def fake(db, ids):
        asked.append(sorted(ids))
        return {8}

    monkeypatch.setattr(talk, "username_search_off", fake)
    page = [SimpleNamespace(mentions=[{"user_id": 7, "username": "a"}, {"user_id": 8, "username": "b"}]),
            SimpleNamespace(mentions=None),
            SimpleNamespace(mentions=[{"user_id": 8, "username": "b"}, "坏数据", {"username": "c"}])]
    assert asyncio.run(talk.mentions_off(None, page)) == {8}
    assert asked == [[7, 8]], "一页一次,去重"


def test_posting_does_not_resolve_people_who_turned_the_switch_off():
    """发评论时解析 @ 的那条 SQL 带着开关条件:关了的人查不出来,也就不存 mentions、不发「@我的」。"""
    import asyncio

    from sqlalchemy.dialects import postgresql
    seen = []

    class _Rows:
        def all(self):
            return []

    class _DB:
        async def execute(self, stmt):
            seen.append(str(stmt.compile(dialect=postgresql.dialect(),
                                         compile_kwargs={"literal_binds": True})))
            return _Rows()

    assert asyncio.run(talk._resolve_mentions(_DB(), ["alice_z1"])) == []
    sql = seen[0]
    assert "social_profiles.privacy ->> 'username_search'" in sql and "'nobody'" in sql, sql
    assert "LEFT OUTER JOIN social_profiles" in sql, "没有资料行的人按缺省(能找到)算,不能被内连接丢掉"
    assert asyncio.run(talk._resolve_mentions(_DB(), [])) == [] and len(seen) == 1, "没有 @ 不查库"


def test_user_hash_is_stable_short_and_not_the_id():
    h = talk.user_hash(12345)
    assert h == talk.user_hash(12345) and len(h) == 8 and int(h, 16) >= 0
    assert h != talk.user_hash(12346)
    assert "12345" not in h
    hashes = {talk.user_hash(i) for i in range(2000)}
    assert len(hashes) == 2000, "8 位十六进制,两千个人里没有撞的"


def test_view_counting_threshold():
    """看满 5 秒或 30% 才算一次播放(§5.9)。"""
    assert act.view_counts(5000, 600_000)
    assert not act.view_counts(4999, 600_000)
    assert act.view_counts(3000, 10_000), "10 秒的片子看了 3 秒 = 30%"
    assert not act.view_counts(2999, 10_000)
    assert not act.view_counts(0, 0)


def test_viewer_key():
    class U:
        id = 7
    assert act.viewer_key(U(), "whatever", "ip") == "u7"
    k1 = act.viewer_key(None, "device-1", "ip-a")
    assert k1.startswith("d") and "device-1" not in k1 and len(k1) == 33
    assert act.viewer_key(None, "device-1", "ip-b") == k1, "有设备号就按设备号"
    assert act.viewer_key(None, "", "ip-a") != act.viewer_key(None, "", "ip-b")


def test_sprite_meta_and_cell():
    meta = vmedia.sprite_meta(4000, 1000, 1, 160, 90)
    assert meta == {"interval_ms": 1000, "cols": 10, "rows": 10, "w": 160, "h": 90, "count": 4}
    long = vmedia.sprite_meta(30 * 60 * 1000, 5000, 4, 160, 90)
    assert long["count"] == 360
    assert vmedia.sprite_cell(0, long) == (0, 0, 0)
    assert vmedia.sprite_cell(4999, long) == (0, 0, 0)
    assert vmedia.sprite_cell(5000, long) == (0, 0, 1)
    assert vmedia.sprite_cell(5000 * 10, long) == (0, 1, 0)
    assert vmedia.sprite_cell(5000 * 100, long) == (1, 0, 0), "第 101 格在第二张的左上角"
    assert vmedia.sprite_cell(10 ** 9, long) == (3, 5, 9), "超出时长的落在最后一格"


def test_vod_signature_binds_user_video_part_and_expiry():
    import time
    exp = int(time.time()) + 3600
    s = vsvc.vod_sig("sv1234567890", 5, 7, exp)
    assert vsvc.check_vod_sig("sv1234567890", 5, 7, exp, s)
    assert not vsvc.check_vod_sig("sv1234567890", 5, 8, exp, s), "换成别人不行"
    assert not vsvc.check_vod_sig("sv1234567890", 6, 7, exp, s), "换一 P 不行"
    assert not vsvc.check_vod_sig("svABCDEFGHJK", 5, 7, exp, s), "换一个视频不行"
    assert not vsvc.check_vod_sig("sv1234567890", 5, 7, exp + 1, s), "改到期时间不行"
    old = int(time.time()) - 1
    assert not vsvc.check_vod_sig("sv1234567890", 5, 7, old, vsvc.vod_sig("sv1234567890", 5, 7,
                                                                            old)), "过期不行"
    assert vsvc.vod_query("sv1234567890", 5, None) == "", "没登录不签名(公开稿件直接能看)"


def test_vid_format():
    for _ in range(200):
        vid = vsvc.new_vid()
        assert vsvc.VID_RE.fullmatch(vid) and len(vid) == 12
    assert not vsvc.VID_RE.fullmatch("sv0OIl123456"), "base58 里没有 0 O I l"
    assert not vsvc.VID_RE.fullmatch("BV1xx411c7mD")


def test_reason_codes_match_the_doc():
    """原因代码表(§5.11)和文档一张表。"""
    from pathlib import Path
    doc = (Path(__file__).resolve().parents[3] / "docs/DEV-PROMPTS-40.md").read_text(encoding="utf-8")
    sec = doc.split("### 5.11 原因代码", 1)[1].split("### 5.12", 1)[0]
    import re
    rows = dict(re.findall(r"^\| ([CVX]\d{3}) \| (.+?) \|$", sec, re.M))
    assert rows == vsvc.REASON_CODES
    with pytest.raises(HTTPException):
        vsvc.reason_ok("X999", "短")
    with pytest.raises(HTTPException):
        vsvc.reason_ok("Z000", "说明写得很清楚")
    vsvc.reason_ok("X999", "写清楚了原因")
    vsvc.reason_ok("V202", "")


def test_default_part_title_skips_machine_names():
    """安卓照片选择器给的文件名是媒体库编号(「24.mp4」),老版本 image_picker 是 UUID:不能当分 P 名。"""
    t = vsvc.title_from_file_name
    assert t("我的旅行 vlog.mp4") == "我的旅行 vlog"
    assert t("my trip.final.mov") == "my trip.final", "只去最后一个扩展名"
    assert t("VID20260912.mp4") == "VID20260912", "相机起的名字带字母,留着"
    assert t("  两头  空白 .mp4") == "两头 空白"
    assert t("长" * 100 + ".mp4") == "长" * vsvc.TITLE_MAX
    for machine in ("24.mp4", "1000000024", "image_picker_5F3A9C.mp4", "image_picker-ab12.mov",
                    "3F2504E0-4F89-11D3-9A0C-0305E82C3301.mp4"):
        assert t(machine) == "", machine
    assert t("") == "" and t(None) == ""
