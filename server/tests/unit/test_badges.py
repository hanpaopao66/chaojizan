"""标签和勋章的纯函数与不变量(services/badges.py)。

守的几件事:
- 判据的真值表,门槛两边各一格;
- 透明中心的条件和发放判据是同一份:公示里的门槛拿来造数据,正好卡在得与不得的分界上;
- 数数的 SQL 用的也是这几个常量,而且除了 :ids 没有别的绑定参数;
- 别人看:隐藏了的和「没有」长得一样;自己看:都在,标着「已隐藏」;
- 标签的条数、字数、重复、冒充平台标志;
- 缓存:上限压在 PUBLIC_CACHE_MAX_SECONDS 下面,本人看总是现算,Redis 挂了照样算;
- 勋章不能买、不能手动发:库里没有存「谁得了哪枚」的地方,也没有发勋章的接口。
"""
import asyncio
import inspect
import re
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.services import badges as bd
from app.services.badges import (BADGE_KEYS, BADGES, COMPLETED_ORDERS_MIN, EARLY_BEFORE,
                                 PHOTO_REVIEWS_MIN, TAG_MAX_LEN, TAGS_MAX, Facts, card_view,
                                 earned_keys, normalize_tags, public_spec)

UTC = timezone.utc
BEFORE = EARLY_BEFORE - timedelta(days=30)
AFTER = EARLY_BEFORE + timedelta(days=1)


def test_registry_shape():
    assert BADGE_KEYS == ("real_name", "early", "uploader", "photo_reviewer", "regular")
    assert len({b.name for b in BADGES}) == len(BADGES), "勋章重名"
    for b in BADGES:
        assert len(b.icon) == 1 and "一" <= b.icon <= "鿿", f"{b.key} 的图标要是一个汉字"
        assert b.condition and b.counts and b.excludes, b.key
        assert len(b.condition) <= 30, f"{b.key}:条件是一句话,资料页的弹层里放得下"


def test_truth_table_each_badge_at_its_threshold():
    none = Facts(registered_at=AFTER)
    assert earned_keys(none) == []
    assert earned_keys(Facts(registered_at=AFTER, real_name=True)) == ["real_name"]
    assert earned_keys(Facts(registered_at=BEFORE)) == ["early"]
    assert earned_keys(Facts(registered_at=AFTER, public_videos=1)) == ["uploader"]
    assert earned_keys(Facts(registered_at=AFTER, photo_reviews=PHOTO_REVIEWS_MIN - 1)) == []
    assert earned_keys(Facts(registered_at=AFTER, photo_reviews=PHOTO_REVIEWS_MIN)) == ["photo_reviewer"]
    assert earned_keys(Facts(registered_at=AFTER, completed_orders=COMPLETED_ORDERS_MIN - 1)) == []
    assert earned_keys(Facts(registered_at=AFTER, completed_orders=COMPLETED_ORDERS_MIN)) == ["regular"]
    everything = Facts(registered_at=BEFORE, real_name=True, public_videos=1,
                       photo_reviews=PHOTO_REVIEWS_MIN, completed_orders=COMPLETED_ORDERS_MIN)
    assert earned_keys(everything) == list(BADGE_KEYS), "顺序跟着 BADGES 走"


def test_early_is_the_last_beijing_day_of_2026_inclusive():
    bj = timezone(timedelta(hours=8))
    assert earned_keys(Facts(registered_at=datetime(2026, 12, 31, 23, 59, 59, tzinfo=bj))) == ["early"]
    assert earned_keys(Facts(registered_at=datetime(2027, 1, 1, 0, 0, tzinfo=bj))) == []
    # 同一刻换成 UTC 写:北京 1 月 1 日零点 = UTC 12 月 31 日 16 点
    assert earned_keys(Facts(registered_at=datetime(2026, 12, 31, 15, 59, tzinfo=UTC))) == ["early"]
    assert earned_keys(Facts(registered_at=datetime(2026, 12, 31, 16, 0, tzinfo=UTC))) == []
    assert earned_keys(Facts(registered_at=None)) == [], "没有注册时间不算早期"
    assert "2026 年 12 月 31 日" in bd._BY_KEY["early"].condition


def test_public_spec_is_the_same_definition_as_the_judgement():
    """透明中心给的门槛拿来造数据,必须正好卡在得与不得的分界上 —— 公示和判据是同一份。"""
    spec = public_spec()
    assert [b["key"] for b in spec["badges"]] == list(BADGE_KEYS)
    for pub, b in zip(spec["badges"], BADGES):
        assert (pub["name"], pub["icon"], pub["condition"]) == (b.name, b.icon, b.condition)
        assert pub["counts"] == b.counts and pub["excludes"] == b.excludes
    fields = {"uploader": "public_videos", "photo_reviewer": "photo_reviews",
              "regular": "completed_orders"}
    for pub in spec["badges"]:
        if pub["min_count"] is not None:
            n = pub["min_count"]
            assert str(n) in pub["condition"], f"{pub['key']}:条件那句话里的数字就是门槛"
            f = fields[pub["key"]]
            assert pub["key"] in earned_keys(Facts(registered_at=AFTER, **{f: n}))
            assert pub["key"] not in earned_keys(Facts(registered_at=AFTER, **{f: n - 1}))
        if pub["before"] is not None:
            cut = datetime.fromisoformat(pub["before"])
            assert "early" in earned_keys(Facts(registered_at=cut - timedelta(seconds=1)))
            assert "early" not in earned_keys(Facts(registered_at=cut))
    assert spec["tags"]["max"] == TAGS_MAX and spec["tags"]["max_len"] == TAG_MAX_LEN
    assert str(TAGS_MAX) in spec["tags"]["rules"][0] and str(TAG_MAX_LEN) in spec["tags"]["rules"][0]
    assert spec["cache_minutes"] * 60 == bd.CACHE_SECONDS
    assert spec["source_url"].endswith("server/app/services/badges.py")


def test_counting_sql_uses_the_same_thresholds_and_only_binds_ids():
    sql = bd.facts_sql()
    assert f"LIMIT {PHOTO_REVIEWS_MIN})" in sql and f"LIMIT {COMPLETED_ORDERS_MIN})" in sql
    # 除了 :ids 没有别的绑定参数:状态、空串写成字面量(通用计划那个坑,见 models.NOT_APPEND_ORDER);
    # `::` 是类型转换不是参数
    binds = set(re.findall(r"(?<!:):([a-z_]+)", sql))
    assert binds == {"ids"}, binds
    for literal in ("v.status = 'published'", "v.visibility = 'public'", "o.status = 'completed'",
                    "o.parent_order_no = ''", "NOT r.hidden", "NOT r.flagged",
                    "coalesce(o.risk_flags->>'status', '') <> 'confirmed'",
                    "o.refund_cents < o.total_cents"):
        assert literal in sql, literal


@pytest.mark.parametrize("raw, want", [
    (["川菜", "夜猫子", "Python"], ["川菜", "夜猫子", "Python"]),
    (["  徒步  ", "a　 b"], ["徒步", "a b"]),
    (["八个字八个字八个"], ["八个字八个字八个"]),
    (["🐱猫奴"], ["🐱猫奴"]),
    ([], []),
])
def test_tags_ok(raw, want):
    assert normalize_tags(raw) == (want, None)


@pytest.mark.parametrize("raw, needle", [
    (["一", "二", "三", "四", "五", "六"], "最多 5 个"),
    (["九个字九个字九个字"], "最多 8 个字"),
    (["Python", "python"], "不能重复"),
    (["跑 步", "跑  步"], "不能重复"),
    ([""], "不能是空的"),
    (["   "], "不能是空的"),
    ([3], "格式不对"),
    ("川菜", "格式不对"),
    (["a‍b"], "不能显示"),
    (["官方推荐"], "平台发的标志"),
    (["实名认证"], "平台发的标志"),
    (["实名用户"], "平台发的标志"),
    (["UP主"], "平台发的标志"),
    (["老 顾客"], "平台发的标志"),
    (["Admin"], "平台发的标志"),
    (["超级赞客服"], "平台发的标志"),
])
def test_tags_rejected(raw, needle):
    got, problem = normalize_tags(raw)
    assert got == [] and problem and needle in problem, (raw, problem)


def _prof(tags=(), tags_hidden=False, hidden=()):
    return SimpleNamespace(tags=list(tags), tags_hidden=tags_hidden, badges_hidden=list(hidden))


def test_others_cannot_tell_hidden_from_missing():
    p = _prof(["川菜", "夜猫子"], tags_hidden=True, hidden=["real_name", "no_such_badge"])
    v = card_view(p, ["real_name", "early"], is_self=False)
    assert v["tags"] == [] and v["tags_hidden"] is False, "隐藏的标签对别人就是没有,也看不出藏了"
    assert [b["key"] for b in v["badges"]] == ["early"]
    assert all(b["hidden"] is False for b in v["badges"])
    nothing = card_view(_prof(), ["early"], is_self=False)
    assert v["tags"] == nothing["tags"] and v["tags_hidden"] == nothing["tags_hidden"]


def test_self_sees_everything_marked():
    p = _prof(["川菜"], tags_hidden=True, hidden=["real_name"])
    v = card_view(p, ["early", "real_name"], is_self=True)
    assert v["tags"] == ["川菜"] and v["tags_hidden"] is True
    assert [(b["key"], b["hidden"]) for b in v["badges"]] == [("real_name", True), ("early", False)]
    b = v["badges"][0]
    assert set(b) == {"key", "name", "icon", "condition", "hidden"}
    assert b["condition"] == bd._BY_KEY["real_name"].condition


def test_no_profile_row_means_nothing_hidden():
    v = card_view(None, ["early"], is_self=False)
    assert v == {"tags": [], "tags_hidden": False,
                 "badges": [bd.badge_out(bd._BY_KEY["early"], hidden=False)]}


def test_cache_ttl_is_capped_by_public_cache_setting(monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "public_cache_max_seconds", 0)
    assert bd.cache_ttl() == 0
    monkeypatch.setattr(settings, "public_cache_max_seconds", 86400)
    assert bd.cache_ttl() == bd.CACHE_SECONDS == 600
    monkeypatch.setattr(settings, "public_cache_max_seconds", 30)
    assert bd.cache_ttl() == 30


class _FakeRedis:
    def __init__(self, fail=False):
        self.store, self.fail, self.sets = {}, fail, []

    async def get(self, k):
        if self.fail:
            raise ConnectionError("redis down")
        return self.store.get(k)

    async def set(self, k, v, ex=None):
        if self.fail:
            raise ConnectionError("redis down")
        self.store[k] = v
        self.sets.append((k, ex))


def _patch(monkeypatch, redis, facts):
    from app.config import settings
    calls = []

    async def fake_facts(db, ids):
        calls.append(list(ids))
        return {i: facts for i in ids}

    monkeypatch.setattr(settings, "public_cache_max_seconds", 86400)
    monkeypatch.setattr(bd, "get_redis", lambda: redis)
    monkeypatch.setattr(bd, "facts_for", fake_facts)
    return calls


def test_cache_hit_skips_counting_and_self_view_always_counts(monkeypatch):
    r = _FakeRedis()
    calls = _patch(monkeypatch, r, Facts(registered_at=BEFORE))
    assert asyncio.run(bd.earned_for(None, 7)) == ["early"]
    assert calls == [[7]] and r.sets == [("badges:v1:7", 600)]
    assert asyncio.run(bd.earned_for(None, 7)) == ["early"]
    assert calls == [[7]], "命中缓存不再数"
    r.store["badges:v1:7"] = '["early", "real_name", "no_such_badge"]'
    assert asyncio.run(bd.earned_for(None, 7)) == ["real_name", "early"], "缓存里的未知 key 丢掉、按 BADGES 排"
    assert asyncio.run(bd.earned_for(None, 7, fresh=True)) == ["early"], "本人看:跳过缓存现算"
    assert calls == [[7], [7]] and r.store["badges:v1:7"] == '["early"]', "现算完顺手刷新缓存"


def test_redis_down_still_counts(monkeypatch):
    calls = _patch(monkeypatch, _FakeRedis(fail=True), Facts(registered_at=BEFORE, real_name=True))
    assert asyncio.run(bd.earned_for(None, 9)) == ["real_name", "early"]
    assert calls == [[9]]


def test_no_cache_when_capped_to_zero(monkeypatch):
    from app.config import settings
    r = _FakeRedis()
    calls = _patch(monkeypatch, r, Facts(registered_at=AFTER))
    monkeypatch.setattr(settings, "public_cache_max_seconds", 0)
    asyncio.run(bd.earned_for(None, 3))
    asyncio.run(bd.earned_for(None, 3))
    assert calls == [[3], [3]] and r.sets == [], "上限是 0(本地、CI)就每次现算,不写缓存"


# ---------------- 不能买、不能手动发 ----------------

PAY = re.compile(r"pay|price|cash|money|recharge|top_?up|purchase|buy|sell|reward|redeem|cents|"
                 r"grant|award|issue", re.I)


def _leaf_routes(routes):
    for r in routes:
        inner = getattr(r, "original_router", None)   # FastAPI 0.139 的 include_router 不摊平
        if inner is not None:
            yield from _leaf_routes(inner.routes)
        else:
            yield r


def test_nothing_stores_who_got_which_badge():
    """勋章每次现算:库里除了「我想隐藏哪几枚」,没有任何和勋章有关的表或列。"""
    from app.db import Base
    import app.models  # noqa: F401  所有表注册进 Base.metadata
    tables = [t for t in Base.metadata.tables if "badge" in t]
    cols = sorted(f"{t.name}.{c.name}" for t in Base.metadata.tables.values() for c in t.columns
                  if "badge" in c.name)
    # dishes.badges 是菜品角标(新品 / 招牌,商家自己勾的),和人的勋章无关
    assert tables == [] and cols == ["dishes.badges", "social_profiles.badges_hidden"], (tables, cols)


def test_no_route_can_sell_or_grant_a_badge():
    from app.main import app
    routes = [r for r in _leaf_routes(app.routes)
              if "badge" in getattr(r, "path", "")]
    assert len(routes) >= 3, f"只扫到 {len(routes)} 条,扫描方式和 FastAPI 对不上了"
    got = sorted((m, r.path) for r in routes for m in r.methods if m != "HEAD")
    assert got == [("GET", "/social/v1/me/tags-badges"), ("GET", "/transparency/badges"),
                   ("PATCH", "/social/v1/me/tags-badges")], got
    for r in routes:
        assert not PAY.search(r.endpoint.__name__), r.endpoint.__name__
    names = re.findall(r"^(?:async )?def ([a-z_0-9]+)", inspect.getsource(bd), re.M)
    assert len(names) >= 10 and not [n for n in names if PAY.search(n)], names


def test_changing_tags_is_blocked_during_account_ban_but_hiding_is_not():
    from app.routers import badges as rb
    from app.services.sanctions import ACCOUNT_BAN_ALLOWED
    assert ("PATCH", "/social/v1/me/tags-badges") in ACCOUNT_BAN_ALLOWED, "隐藏是自我保护,封号期间也能用"
    src = inspect.getsource(rb.patch_tags_badges)
    assert src.index('check_user(db, user.id, "social_write")') < src.index("p.tags = tags"), \
        "改标签是给别人看的字,封号期间照样挡(和签名一个口径)"
