"""申诉时限的口径必须只有一处(#294 改版顺带)。

## 为什么要有这条

店铺页把「判责申诉」收进了图标网格,格子上挂的角标要回答
「你有几单**还来得及**申诉」—— 不是「历史上有几单被判过责」。
后者点进去多半什么也做不了,给它挂红数字只会制造焦虑
(与 `SzIconGridItem.badge` 的口径一致:只给"你还有事要做"的)。

于是 `merchants.py` 的 todos 要数一遍「在窗口内的」,
而 `appeals.py` 提交时也要判一次「在不在窗口内」。**两处必须同一个口径** ——
各写一遍的话,今天都是 72 小时,哪天有人只改了一处,
角标说有 2 单可申诉、点进去提交却被 422 挡回来。

所以判据抽成一个纯函数,两处都调它,这里把它钉住。
"""
from datetime import datetime, timedelta, timezone

from app.routers.appeals import APPEAL_WINDOW, appeal_cutoff, within_window


def _ago(**kw):
    return datetime.now(timezone.utc) - timedelta(**kw)


class Test窗口判定:
    def test_刚裁决的在窗口内(self):
        assert within_window(_ago(minutes=1)) is True

    def test_七十一小时还来得及(self):
        assert within_window(_ago(hours=71)) is True

    def test_七十三小时过期了(self):
        assert within_window(_ago(hours=73)) is False

    def test_没裁决过的不算可申诉(self):
        """`processed_at` 为空 = 这单还没判过责,没有东西可申诉。"""
        assert within_window(None) is False

    def test_不带时区的当成UTC(self):
        """数据库里取出来的 datetime 可能是 naive 的。

        当成本地时间解读的话,东八区会凭空多出 8 小时窗口 ——
        商家在第 75 小时提交,前端放行、后端 422。
        """
        naive = datetime.utcnow() - timedelta(hours=71)
        assert within_window(naive) is True
        naive_old = datetime.utcnow() - timedelta(hours=73)
        assert within_window(naive_old) is False


class Test游标与判定同源:
    """SQL 里要按时间戳筛,不可能对每一行调 within_window。

    所以给一个 `appeal_cutoff()` 供 WHERE 用 —— 它和 `within_window`
    必须严格互为反面,否则「数出来的」和「提交得了的」对不上。
    """

    def test_游标就是窗口起点(self):
        now = datetime.now(timezone.utc)
        assert abs((now - appeal_cutoff(now)) - APPEAL_WINDOW) < timedelta(
            seconds=1)

    def test_游标之后的都在窗口内(self):
        now = datetime.now(timezone.utc)
        cutoff = appeal_cutoff(now)
        assert within_window(cutoff + timedelta(minutes=1), now=now) is True
        assert within_window(cutoff - timedelta(minutes=1), now=now) is False
