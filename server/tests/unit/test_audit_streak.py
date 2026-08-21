"""透明中心公示的「连续无差错天数」不许把没跑成的日子算成干净日子。

这个平台把账目透明当立身之本,所以这个数字虚高一天都不行:
自检挂掉那天**不写 audit_runs 行**(auto_flow.maybe_run_daily_audit
的防重键以前先占后跑,run_audit 抛异常被外层吞掉,当天就再也不跑了),
而老的数法只遍历"已存在的行"、只在 problems > 0 时停,
缺失的天直接跨过去接着数 —— 于是"没结论"在公示上和"没问题"长得一模一样。

纯函数,不连库不起服务,这几条样例就是它的规格。
"""
from datetime import date

from app.routers.transparency import clean_streak_days, missing_run_days


def runs(*pairs):
    """(day, problems) → 接口返回的那种字典列表,按 day 倒序。"""
    return [{"day": d, "checked_orders": 1, "problems": p} for d, p in pairs]


def test_连续零差错就照数():
    assert clean_streak_days(runs(
        ("2026-08-19", 0), ("2026-08-18", 0), ("2026-08-17", 0))) == 3


def test_遇到有差错的一天停下():
    assert clean_streak_days(runs(
        ("2026-08-19", 0), ("2026-08-18", 2), ("2026-08-17", 0))) == 1


def test_中间缺一天就断_不许跨过去接着数():
    # 8-18 那天自检没跑成(没有行)。老写法会数出 3,那是虚高的
    assert clean_streak_days(runs(
        ("2026-08-19", 0), ("2026-08-17", 0), ("2026-08-16", 0))) == 1


def test_缺好几天同样只算到断点():
    assert clean_streak_days(runs(
        ("2026-08-19", 0), ("2026-08-10", 0), ("2026-08-09", 0))) == 1


def test_一条记录都没有时是零():
    assert clean_streak_days([]) == 0
    assert missing_run_days([], date(2026, 8, 20)) == []


def test_缺失天数把断档显式列出来():
    got = missing_run_days(
        runs(("2026-08-19", 0), ("2026-08-16", 0)), date(2026, 8, 20))
    assert got == ["2026-08-17", "2026-08-18"]


def test_今天不算缺失_定时任务凌晨四点才跑():
    # 最近一条是昨天(8-19),今天(8-20)还没到 04:00 是常态,不能报缺
    got = missing_run_days(
        runs(("2026-08-19", 0), ("2026-08-18", 0)), date(2026, 8, 20))
    assert got == []


def test_最近一天就断档时_缺失里要有昨天():
    # 最近一条是 8-18,昨天(8-19)没跑成 —— 这正是"自检挂了"的样子
    got = missing_run_days(
        runs(("2026-08-18", 0), ("2026-08-17", 0)), date(2026, 8, 20))
    assert got == ["2026-08-19"]
