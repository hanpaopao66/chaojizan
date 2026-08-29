"""骑手每日汇总(#310):**记录不等于考核**。

## 这一组守的是一条边界,不是一个功能

平台记录骑手数据,是为了看清运力和成本 —— 一天有多少人在跑、
跑了多少公里、有多少单是被自己的偏好挡掉的。这些是产品决策的依据。

但同一份数据,只要接进派单,立刻就变成绳索:
「昨天跑得少的今天少派单」这种逻辑不需要谁存心作恶,
它会以「优化运力效率」的名义自然长出来。

所以边界画在这里,判断标准和评价体系那条一样:

    **这个数字会不会影响他能看到的单?**
    会,就是绳索;不会,才是数据。

下面每一条都在检查这条边界没有被跨过去。
"""
import inspect
from datetime import date, datetime, timezone

from app.services import rider_stats


class Test红线_统计不进派单:
    def test_派单模块不引用日汇总表(self):
        """dispatch 是决定「谁看得到这一单」的地方。
        RiderDailyStat 一旦出现在这里,记录就变成了考核。"""
        import app.services.dispatch as d
        src = inspect.getsource(d)
        for banned in ("RiderDailyStat", "rider_daily_stats", "rider_stats"):
            assert banned not in src, (
                f"派单模块引用了 {banned} —— 昨天跑得少的今天少派单,"
                f"这种逻辑不需要谁存心作恶,它会以「优化效率」的名义长出来")

    def test_抢单池不按历史数据筛人(self):
        """available_orders 决定骑手能看到哪些单。"""
        import app.routers.riders as r
        src = inspect.getsource(r.available_orders)
        for banned in ("RiderDailyStat", "rider_daily_stats"):
            assert banned not in src, f"抢单池按历史数据筛人了:{banned}"

    def test_公开承诺里仍然写着不做评分体系(self):
        """记录这件事不能悄悄改掉对外的立场。"""
        from app.services import dispatch as d
        never = "".join(d.public_spec()["never_do"])
        assert "评分" in never or "等级" in never


class Test北京自然日:
    def test_跨零点按北京日切(self):
        """UTC 16:00 = 北京次日 0:00。按 UTC 切的话,
        骑手晚上跑的单会算到前一天,他对不上自己的记忆。"""
        d = rider_stats.bj_day(
            datetime(2026, 8, 29, 16, 0, tzinfo=timezone.utc))
        assert d == date(2026, 8, 30)

    def test_北京日窗口是左闭右开的一整天(self):
        start, end = rider_stats.day_window(date(2026, 8, 30))
        assert (end - start).total_seconds() == 86400
        # 北京 8/30 00:00 == UTC 8/29 16:00
        assert start == datetime(2026, 8, 29, 16, 0, tzinfo=timezone.utc)

    def test_naive_时间当成_utc_而不是本地时区(self):
        """库里取出来的时间可能没带时区。按本地时区解释的话,
        同一份数据在不同机器上会汇总到不同的天。"""
        d = rider_stats.bj_day(datetime(2026, 8, 29, 16, 0))
        assert d == date(2026, 8, 30)


class Test不落库就丢的那个数:
    def test_挡掉计数失败不能把抢单接口拖挂(self):
        """它是统计。Redis 挂了就少一个数,不能少一次抢单。"""
        import asyncio
        from unittest.mock import patch

        with patch("app.services.rider_stats.get_redis",
                   side_effect=RuntimeError("redis 挂了")):
            asyncio.run(rider_stats.bump_filtered(1, 5))   # 不抛就算过

    def test_零不写(self):
        """没挡掉就别写 —— 每次抢单都打一次 Redis 纯属浪费。"""
        import asyncio
        from unittest.mock import patch

        with patch("app.services.rider_stats.get_redis") as g:
            asyncio.run(rider_stats.bump_filtered(1, 0))
            g.assert_not_called()
