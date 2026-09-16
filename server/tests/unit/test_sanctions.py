"""社区治理的代码形状守卫(DEV-PROMPTS-40 #368 聊天部分、#371,S6 / S8)。

- 期限、状态、「同时几条生效拿哪条说话」、S8 的查看范围:纯函数,逐条锁住;
- 被挡时的 403 detail:字段齐全,非当事人拿不到写给当事人的说明、也不能申诉;
- 文档 docs/COMMUNITY-GOVERNANCE.md §1、§2、§3、§7 的表和代码逐字对得上;
- 封号是「默认全挡」:社交写接口都挂着 social_user,放行表里每一条都是真实存在的写接口;
- 新表没有和钱 / 排序有关的列(S3 / S4);透明中心取数的 SQL 不碰个人信息的列。
"""
import inspect
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi import HTTPException

from app.models import MODERATION_MODELS, SocialSanction
from app.services import community_stats, sanctions
from app.services.sanctions import (ACCOUNT_BAN_ALLOWED, BLOCKED_BY, compute_until,
                                    context_seqs, duration_of, restriction_detail, status_of,
                                    strongest)

ROOT = Path(__file__).resolve().parents[3]
DOC = ROOT / "docs/COMMUNITY-GOVERNANCE.md"
T0 = datetime(2026, 9, 12, 12, 0, tzinfo=timezone.utc)


def _s(action="mute", until=None, **kw) -> SocialSanction:
    base = dict(id=kw.pop("id", 1), target_type=kw.pop("target_type", "user"), target_id=7,
                action=action, reason_code=kw.pop("reason_code", "C101"), note=kw.pop("note", ""),
                until=until, created_at=kw.pop("created_at", T0), revoked_at=None,
                appeal_status="")
    base.update(kw)
    return SocialSanction(**base)


def _doc() -> str:
    assert DOC.exists(), f"找不到 {DOC}"
    return DOC.read_text(encoding="utf-8")


def _table_after(doc: str, heading: str) -> list[list[str]]:
    """标题下面第一张表的数据行(去掉表头和分隔行),每行按 | 切开。"""
    part = doc.split(heading, 1)[1]
    rows, started = [], False
    for line in part.splitlines():
        if line.startswith("|"):
            started = True
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            rows.append(cells)
        elif started:
            break
    return [r for r in rows[2:]]


# ---------------- 期限与状态 ----------------

def test_mute_must_be_timed():
    assert compute_until("mute", hours=24, now=T0) == T0 + timedelta(hours=24)
    for bad in (dict(hours=0), dict(hours=721), dict(hours=None), dict(permanent=True, hours=5)):
        with pytest.raises(HTTPException) as e:
            compute_until("mute", now=T0, **bad)
        assert e.value.status_code == 422


def test_bans_are_days_or_permanent():
    for action in ("ban_account", "ban_chat"):
        assert compute_until(action, days=7, now=T0) == T0 + timedelta(days=7)
        assert compute_until(action, permanent=True, now=T0) is None
        for bad in (dict(days=0), dict(days=3651), dict()):
            with pytest.raises(HTTPException):
                compute_until(action, now=T0, **bad)
    assert compute_until("warn", now=T0) is None
    assert compute_until("delete_messages", hours=3, now=T0) is None
    with pytest.raises(HTTPException):
        compute_until("mute_forever", now=T0)


def test_status_and_live():
    now = T0 + timedelta(hours=1)
    assert status_of(_s(until=T0 + timedelta(hours=2)), now) == "active"
    assert status_of(_s(until=T0 + timedelta(minutes=30)), now) == "expired"
    assert status_of(_s("ban_account", until=None), now) == "active", "封号没有到期时间 = 永久"
    assert status_of(_s("warn"), now) == "done"
    assert status_of(_s("delete_messages"), now) == "done"
    assert status_of(_s(until=T0 + timedelta(days=1), revoked_at=T0), now) == "revoked"
    assert not sanctions.is_live(_s("warn"), now), "一次性的处罚不挡人"


def test_strongest_speaks_for_several():
    mute = _s("mute", until=T0 + timedelta(days=1), id=1)
    ban7 = _s("ban_account", until=T0 + timedelta(days=7), id=2)
    ban_forever = _s("ban_account", until=None, id=3)
    chat = _s("ban_chat", until=None, id=4, target_type="chat")
    assert strongest([]) is None
    assert strongest([mute, ban7]).id == 2, "封号比禁言重"
    assert strongest([mute, ban7, ban_forever]).id == 3, "同种里永久的在前"
    assert strongest([mute, chat]).id == 4
    longer = _s("mute", until=T0 + timedelta(days=3), id=5)
    assert strongest([mute, longer]).id == 5, "同种里到期晚的在前"


def test_duration_text():
    assert duration_of("mute", T0 + timedelta(hours=24, milliseconds=-3), T0) == "24 小时"
    assert duration_of("ban_account", T0 + timedelta(days=7, milliseconds=-3), T0) == "7 天", \
        "先算到期、再落库,差几毫秒也要显示成 7 天"
    assert duration_of("ban_chat", None, T0) == "永久"
    assert duration_of("ban_account", T0 + timedelta(hours=30), T0) == "30 小时"
    assert duration_of("warn", None, T0) == "" and duration_of("delete_messages", None, T0) == ""


# ---------------- S8 的范围 ----------------

def test_context_is_five_each_side():
    assert context_seqs([10], floor=0, last_seq=20) == list(range(5, 16))
    assert context_seqs([10], floor=0, last_seq=12) == list(range(5, 13)), "不超过会话最新一条"
    assert context_seqs([4], floor=3, last_seq=20) == list(range(4, 10)), \
        "不越过举报人当时的可见下限(不含)"
    assert context_seqs([2], floor=0, last_seq=20) == list(range(1, 8)), "seq 从 1 开始"
    assert context_seqs([5, 8], floor=0, last_seq=30) == list(range(1, 14)), "几条的范围合并去重"
    assert context_seqs([], floor=0, last_seq=30) == [], "举报单没指定消息 = 什么都不给看"
    from app.services.chat_moderation import CONTEXT
    assert CONTEXT == 5
    assert "前后各 5 条" in _doc()


# ---------------- 403 的 detail ----------------

DETAIL_KEYS = {"error", "message", "sanction_id", "scope", "point", "action", "action_label",
               "reason_code", "reason_label", "note", "until", "permanent", "can_appeal",
               "appeal_status", "appeal_path"}


def test_detail_for_the_party():
    s = _s("mute", until=T0 + timedelta(hours=24), note="多次辱骂他人", id=12)
    d = restriction_detail(s, point="message", party=True)
    assert set(d) == DETAIL_KEYS
    assert d["error"] == "sanctioned" and d["reason_label"] == "骚扰、辱骂"
    assert d["can_appeal"] and d["appeal_path"] == "/social/v1/sanctions/12/appeal"
    assert d["until"] == (T0 + timedelta(hours=24)).isoformat() and not d["permanent"]
    assert "禁言" in d["message"] and "多次辱骂他人" in d["message"]
    assert "2026 年 9 月 13 日 20:00" in d["message"], "到期时间给人看的是北京时间"


def test_detail_for_a_member_of_a_banned_chat():
    s = _s("ban_chat", until=None, note="写给群主的说明", id=4, target_type="chat")
    d = restriction_detail(s, point="speak", party=False, chat_type="group")
    assert d["note"] == "" and "写给群主的说明" not in d["message"], "普通成员不是当事人"
    assert d["can_appeal"] is False and d["appeal_path"] is None and d["appeal_status"] == ""
    assert d["permanent"] and "群主可以申诉" in d["message"]
    owner = restriction_detail(s, point="speak", party=True, chat_type="channel")
    assert owner["can_appeal"] and "频道" in owner["message"]


def test_detail_after_appeal_or_revoke():
    s = _s("mute", until=T0 + timedelta(hours=1), appeal_status="open")
    assert restriction_detail(s, point="message", party=True)["can_appeal"] is False


def test_doc_detail_example_has_exactly_these_keys():
    doc = _doc()
    block = doc.split("## 3. 被挡时的 403", 1)[1].split("```json", 1)[1].split("```", 1)[0]
    assert set(json.loads(block)) == DETAIL_KEYS


# ---------------- 文档和代码逐字一致 ----------------

def test_doc_action_table_matches():
    rows = _table_after(_doc(), "## 1. 处罚种类")
    got = {r[0].strip("`"): r[1] for r in rows}
    assert got == sanctions.ACTION_LABELS, got
    assert "1–720 小时" in rows[[r[0] for r in rows].index("`mute`")][3]
    assert sanctions.MUTE_MAX_HOURS == 720 and sanctions.BAN_MAX_DAYS == 3650
    assert (sanctions.APPEAL_MIN, sanctions.APPEAL_MAX) == (5, 500)
    assert "5–500 字" in _doc()


def test_doc_enforcement_table_matches():
    rows = _table_after(_doc(), "## 2. 执行点")
    got = {r[0].strip("`"): tuple(x.strip() for x in r[2].split("、")) for r in rows}
    assert got == BLOCKED_BY, got


def test_doc_ban_allowlist_matches():
    doc = _doc()
    part = doc.split("默认全拒**,只放行下面这张表里的", 1)[1]
    rows = _table_after(part, "\n")
    got = {(r[0], r[1]) for r in rows if r and r[0] in ("GET", "POST", "PUT", "PATCH", "DELETE")}
    assert got == set(ACCOUNT_BAN_ALLOWED), got ^ set(ACCOUNT_BAN_ALLOWED)


def test_doc_record_fields_match():
    rows = _table_after(_doc(), "透明中心的处置记录只有这几个字段")
    assert tuple(r[0].strip("`") for r in rows) == community_stats.RECORD_KEYS


# ---------------- 封号:默认全挡 ----------------

SOCIAL_PREFIXES = ("/chat/v1", "/social/v1", "/video/v1", "/music/v1", "/media/v1")
WRITE = {"POST", "PUT", "PATCH", "DELETE"}
#: 不挂 social_user 的社交写接口(没登录也能调的):视频的播放心跳、音乐的收听上报。
#: 两个都不改任何人能看到的东西,而且不登录也能看 / 能听(#378 M5)
NOT_SOCIAL_USER = {("POST", "/video/v1/videos/{vid}/view"),
                   ("POST", "/music/v1/tracks/{tid}/play")}


def _leaf_routes(routes):
    for r in routes:
        inner = getattr(r, "original_router", None)
        if inner is not None:
            yield from _leaf_routes(inner.routes)
        else:
            yield r


def _calls(dep) -> set[str]:
    out = {getattr(dep.call, "__name__", "")}
    for d in dep.dependencies:
        out |= _calls(d)
    return out


def _social_writes():
    from app.main import app
    for r in _leaf_routes(app.routes):
        methods = getattr(r, "methods", None) or set()
        if r.path.startswith(SOCIAL_PREFIXES) and methods & WRITE:
            for m in methods & WRITE:
                yield m, r.path, r


def test_every_social_write_goes_through_social_user():
    """新加的社交写接口不挂 social_user,封号就管不住它 —— 这里红。"""
    found = list(_social_writes())
    assert len(found) >= 80, f"只扫到 {len(found)} 个社交写接口,扫描方式和 FastAPI 对不上了"
    missing = sorted(f"{m} {p}" for m, p, r in found
                     if "social_user" not in _calls(r.dependant)
                     and (m, p) not in NOT_SOCIAL_USER)
    assert not missing, f"这些社交写接口没挂 social_user,封号挡不住:{missing}"


def test_ban_allowlist_entries_are_real_write_routes():
    real = {(m, p) for m, p, _ in _social_writes()}
    stale = sorted(ACCOUNT_BAN_ALLOWED - real)
    assert not stale, f"封号放行表里有不存在的接口(改了路径没改这里):{stale}"
    assert ("POST", "/social/v1/sanctions/{sanction_id}/appeal") in ACCOUNT_BAN_ALLOWED, \
        "封号期间必须能申诉(S6)"
    for m, p in ACCOUNT_BAN_ALLOWED:
        assert not re.search(r"/messages$|/comments$|/danmaku$|/chats$|/uploads", p), \
            f"{m} {p}:发言、建群、投稿类的接口不能放行"


def test_central_guard_is_default_deny():
    src = inspect.getsource(__import__("app.routers.social", fromlist=["x"]).social_user)
    assert "ACCOUNT_BAN_ALLOWED" in src and 'check_user(db, user.id, "social_write")' in src


# ---------------- 列名与透明中心的 SQL ----------------

def test_no_money_or_rank_columns_in_moderation_tables():
    from tests.unit.test_video_invariants import _bad
    s3 = re.compile(r"bid|boost|paid|promot|rank_score|weight_override")
    cols = [f"{m.__tablename__}.{c.name}" for m in MODERATION_MODELS for c in m.__table__.columns]
    from app.models import ChatReport
    cols += [f"chat_reports.{c.name}" for c in ChatReport.__table__.columns]
    bad = [c for c in cols if s3.search(c.split(".")[1]) or _bad(c.split(".")[1])]
    assert not bad, bad


def test_transparency_sql_never_reads_personal_columns():
    """透明中心取数只读类型、代码、时间、申诉结果;说明、备注、谁、哪个会话的列一个都不许出现在 SQL 里。"""
    src = inspect.getsource(community_stats.public_section)
    sql = " ".join(re.findall(r'"""(.*?)"""', src, re.S) + re.findall(r'"([^"\n]*(?:SELECT|FROM)[^"\n]*)"', src))
    assert "FROM social_sanctions" in sql and "FROM admin_chat_views" in sql, "扫描没扫到 SQL"
    forbidden = ["note", "appeal_text", "target_id", "chat_id", "admin_id", "actor_id",
                 "reporter_id", "seqs", "carry_key", "title", "username", "phone",
                 "chat_messages", "users", "description"]
    hit = [w for w in forbidden if re.search(rf"\b{w}\b", sql)]
    assert not hit, f"透明中心的 SQL 读了个人信息相关的列:{hit}"
    assert set(community_stats.RECORD_KEYS) == {
        "date", "target_type", "action", "action_label", "reason_code", "reason_label",
        "duration", "appeal", "appeal_label", "revoked"}
