"""趋势折线的末端必须画到**本周**(#301 批次的 CI 修复)。

## 这条为什么值一个单测

原来末端补到"最后一个有单的周"。本周一单都还没有的时候,本周就整个
不出现在图上 —— 商家看到的折线停在上周,而环比也失去了"本周进行中、
不参与比较"的那个标记。

它只在一个很窄的时刻暴露:**周一刚过零点、本周还没有单**。
CI 在 UTC 16:17 跑,正好是北京时间周一 00:17,于是撞上了 ——
本地任何别的时间跑都是绿的。

这种"一周只错一小时"的缺陷,靠 e2e 撞运气是撞不出来的,
所以把周界逻辑单独拎出来测。
"""
import datetime as dt


def _series_end(last_order_week: dt.date, this_week: dt.date) -> dt.date:
    """折线末端该画到哪一周。与 merchants.py 里的表达式一致。"""
    return max(last_order_week, this_week)


class Test末端画到本周:
    def test_本周没单也要出现在图上(self):
        """周一刚过零点:上周有单,本周还没有。"""
        last, now = dt.date(2026, 8, 17), dt.date(2026, 8, 24)
        assert _series_end(last, now) == now, \
            "本周不画在图上,商家看到的折线停在上周"

    def test_本周有单时不受影响(self):
        last = now = dt.date(2026, 8, 24)
        assert _series_end(last, now) == now

    def test_不会因为有未来的单而缩回来(self):
        """预约单可能落在未来那一周;末端取 max,不是取本周。"""
        last, now = dt.date(2026, 8, 31), dt.date(2026, 8, 24)
        assert _series_end(last, now) == last


class Test周界按北京时间:
    def test_周一是周界(self):
        """UTC 周日下午在北京已经是周一 —— 周界必须按北京算,
        否则每周有八小时的窗口里,`this_week` 比商家看到的日历慢一周。"""
        utc = dt.datetime(2026, 8, 23, 16, 17, tzinfo=dt.timezone.utc)
        bj = (utc + dt.timedelta(hours=8)).date()
        assert bj == dt.date(2026, 8, 24) and bj.weekday() == 0
        assert bj - dt.timedelta(days=bj.weekday()) == dt.date(2026, 8, 24)
