"""超级赞号(相当于微信号)的改名规则与「按超级赞号找到我」:纯函数和代码形状(迁移 0133)。

接口行为在 e2e_custom_id:一年内再改被拒并告诉下次时间、旧号冷冻、到期可注册、按号找人、开关。
"""
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy.dialects import postgresql

from app.models import PRIVACY_DEFAULTS, SocialProfile
from app.routers.social import SWITCH_PRIVACY, card_link
from app.services.social import (USERNAME_CHANGE_DAYS, USERNAME_HOLD_DAYS, USERNAME_MAX,
                                 USERNAME_MIN, frozen_reason, hold_blocks,
                                 username_locked_until, username_next_change,
                                 username_searchable, validate_username)

ROOT = Path(__file__).resolve().parents[3]
BJ = timezone(timedelta(hours=8))


def test_next_change_counts_beijing_days_not_moments():
    assert username_next_change(None) is None, "没设过 / 存量号:没有限制"
    # 北京时间 09-13 晚上 11 点半设的:365 天后那天的零点起就能改,不用等到晚上 11 点半
    late = datetime(2026, 9, 13, 23, 30, tzinfo=BJ)
    assert username_next_change(late) == datetime(2027, 9, 13, tzinfo=BJ)
    # 同一个时刻用 UTC 存(库里就是这样):UTC 还是 09-13 15:30,算出来一样
    assert username_next_change(late.astimezone(timezone.utc)) == datetime(2027, 9, 13, tzinfo=BJ)
    # 北京 09-14 凌晨 0 点 10 分 = UTC 09-13 16:10:按北京的日期算,是 09-14 设的
    early = datetime(2026, 9, 13, 16, 10, tzinfo=timezone.utc)
    assert username_next_change(early) == datetime(2027, 9, 14, tzinfo=BJ)
    # 跨闰年:就是 365 天,不是「明年同一天」
    assert username_next_change(datetime(2027, 3, 1, 12, tzinfo=BJ)) == datetime(2028, 2, 29, tzinfo=BJ)
    assert USERNAME_CHANGE_DAYS == 365 and USERNAME_HOLD_DAYS == 180


def test_locked_until():
    set_at = datetime(2026, 9, 13, 12, tzinfo=BJ)
    nxt = datetime(2027, 9, 13, tzinfo=BJ)
    assert username_locked_until(set_at, set_at + timedelta(days=1)) == nxt
    assert username_locked_until(set_at, nxt - timedelta(seconds=1)) == nxt
    assert username_locked_until(set_at, nxt) is None, "到了那天零点就能改"
    assert username_locked_until(None, set_at) is None


def test_hold_truth_table():
    now = datetime(2026, 9, 14, 12, tzinfo=timezone.utc)
    live, gone = now + timedelta(days=1), now - timedelta(seconds=1)
    assert not hold_blocks(None, None, "user", 2, now), "没有冷冻记录"
    assert not hold_blocks(gone, 1, "user", 2, now), "过期了谁都能注册"
    assert hold_blocks(live, 1, "user", 2, now), "冷冻中,别人不能注册"
    assert not hold_blocks(live, 1, "user", 1, now), "原主人拿回去不受冷冻限制(一年一次另判)"
    assert hold_blocks(live, 1, "chat", 1, now), "群的 id 恰好等于原主人的 user id 也不算原主人"
    assert hold_blocks(live, None, "user", 1, now), "原主人的账号没了(外键置空):谁都不算原主人"


def test_frozen_reason_does_not_leak_when():
    """想注册的是陌生人:解冻日期能倒推出原主人哪天换的号,不该告诉他。"""
    for noun in ("超级赞号", "链接名"):
        msg = frozen_reason(noun)
        assert "冷冻" in msg and str(USERNAME_HOLD_DAYS) in msg, msg
        assert not re.search(r"\d{4}-\d{1,2}-\d{1,2}|\d+ 月 ?\d+ 日", msg), msg


def test_noun_in_messages():
    """人的叫「超级赞号」,群 / 频道的叫「链接名」,机器人(开发者后台)照旧叫「用户名」。"""
    bad = ["", "abcd", "a" * 33, "1abcde", "_abcde", "abcde_", "ab__cd", "ab-cde", "admin",
           "hellobot"]
    for name in bad:
        for noun in ("超级赞号", "链接名"):
            msg = validate_username(name, noun=noun)
            assert msg and noun in msg and "用户名" not in msg, (name, noun, msg)
    assert "用户名" in validate_username("hello", is_bot=True)
    assert validate_username("A" * USERNAME_MAX) is None
    assert validate_username("A" * (USERNAME_MAX + 1))
    assert validate_username("A" * USERNAME_MIN) is None
    assert validate_username("A" * (USERNAME_MIN - 1))
    assert validate_username("alicK"), "开尔文符号不是字母(只改大小写那条路也要挡住它)"


def _profile(username, search="everyone"):
    return SocialProfile(user_id=1, public_id="AbCdEfGh1234", username=username,
                         privacy={"username_search": search})


def test_card_link_follows_the_switch():
    assert card_link(_profile("Alice01")) == "https://chaojizan.cc/@Alice01"
    # 关了「按超级赞号找到我」:@ 链接对别人打不开,名片码改用随机编号
    assert card_link(_profile("Alice01", "nobody")) == "https://chaojizan.cc/u/AbCdEfGh1234"
    assert card_link(_profile(None)) == "https://chaojizan.cc/u/AbCdEfGh1234"


def test_switch_privacy_is_a_real_privacy_item():
    assert set(SWITCH_PRIVACY) <= set(PRIVACY_DEFAULTS)
    assert PRIVACY_DEFAULTS["username_search"] == "everyone", "缺省能被找到"


def test_username_searchable_sql():
    sql = str(username_searchable(SocialProfile.privacy).compile(dialect=postgresql.dialect()))
    assert "coalesce" in sql.lower() and "->>" in sql, sql


def test_every_namespace_insert_goes_through_claim():
    """往 usernames 里写的地方,除了建机器人,都得走 claim_username —— 那里才判冷冻。
    新加一条注册路径直接 insert(Username) 的话,冷冻中的号就能被它拿走。"""
    hits = []
    for p in (ROOT / "server/app").rglob("*.py"):
        for i, line in enumerate(p.read_text().splitlines(), 1):
            if re.search(r"insert\(\s*Username\s*\)", line):
                hits.append(f"{p.relative_to(ROOT)}:{i}")
    files = {h.split(":")[0] for h in hits}
    # 机器人的号必须以 bot 结尾、人的号不能以 bot 结尾,永远撞不上冷冻中的超级赞号
    assert files == {"server/app/services/social.py", "server/app/services/bots.py"}, hits
    assert validate_username("frozenbot") and validate_username("frozen", is_bot=True)


def test_client_rules_text_matches_server():
    """客户端「超级赞号」页上的规则说明是照服务端写的:位数、一年、冷冻天数对不上就红。"""
    src = (ROOT / "apps/user_app/lib/chat/pages/chat_settings_page.dart").read_text()
    assert f"{USERNAME_MIN}–{USERNAME_MAX} 位" in src
    assert f"满 {USERNAME_CHANGE_DAYS} 天" in src
    assert f"冷冻 {USERNAME_HOLD_DAYS} 天" in src
