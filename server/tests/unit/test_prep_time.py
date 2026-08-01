"""出餐时长统计(#143)。

守两件事:
1. **分位数算得对**,包括样本不足与异常值的处理;
2. **样本不足时不装精确** —— 给一个拿 3 单算出来的 P80,
   比明说"样本不足、用商家自报值"更坏。
"""
from app.services import prep_time as pt


def stat(samples, p50=None, p80=None, p95=None, fallback=15):
    return pt.PrepStat(merchant_id=1, samples=samples,
                       p50=p50, p80=p80, p95=p95, fallback_minutes=fallback)


class Test分位数:
    def test_单点(self):
        assert pt._quantile([10.0], 0.5) == 10.0

    def test_中位数(self):
        assert pt._quantile([10.0, 20.0, 30.0], 0.5) == 20.0

    def test_线性插值(self):
        # 两点之间取 P50 应落在中间
        assert pt._quantile([10.0, 20.0], 0.5) == 15.0

    def test_单调不减(self):
        vals = sorted([5.0, 8.0, 12.0, 20.0, 35.0, 60.0])
        q = [pt._quantile(vals, x) for x in (0.5, 0.8, 0.95)]
        assert q == sorted(q)

    def test_空样本返回零而不是崩(self):
        assert pt._quantile([], 0.8) == 0.0


class Test样本不足不装精确:
    def test_样本够才算实测(self):
        assert stat(pt.MIN_SAMPLES, p80=22.0).enough
        assert not stat(pt.MIN_SAMPLES - 1, p80=22.0).enough

    def test_样本不足回退商家自报值(self):
        s = stat(3, p80=2.0, fallback=18)
        assert s.wait_minutes == 18
        assert s.source == "declared"

    def test_样本足够才用实测值(self):
        s = stat(50, p80=22.0, fallback=15)
        assert s.wait_minutes == 22.0
        assert s.source == "measured"

    def test_来源必须可区分(self):
        """所有出口都要标明这个数是实测还是自报 ——
        骑手看到「等 22 分钟」和「大概 15 分钟(样本还少)」,
        决策是不一样的。"""
        assert stat(50, p80=1.0).source != stat(1, p80=1.0).source


class Test等待预期取P80:
    def test_用P80而不是中位数(self):
        """按中位数到店,有一半概率白等。等待的成本落在骑手身上,
        预期就该偏保守。"""
        s = stat(50, p50=10.0, p80=22.0, p95=40.0)
        assert s.wait_minutes == 22.0
        assert s.wait_minutes != s.p50


class Test异常值:
    def test_上限是合理的(self):
        """超过它多半是商家忘了点出餐,不是真实出餐时长 ——
        不剔掉的话 P95 会被垃圾数据拉飞。"""
        assert 30 <= pt.OUTLIER_MAX_MINUTES <= 240

    def test_有下限且不能是0(self):
        """**做一份饭不可能不花时间。**

        下限如果是 0,商家习惯性连点「接单」→「出餐」的样本会全被采信,
        实测算出来是 0 分钟 —— 商家端会显示「承诺值可以往下调」,
        他真去调低,然后每单超时:平台掏安抚券、骑手干等、顾客 ETA 不准。
        三方一起受损,起因只是一个不该采信的 0。
        """
        assert pt.OUTLIER_MIN_MINUTES > 0, "下限是 0 等于没有下限"
        # 上限不能太高:一份便当热好装盒也就一两分钟,
        # 卡到 5 分钟会把真实的快店误判成异常
        assert pt.OUTLIER_MIN_MINUTES <= 3

    def test_区间是闭合且非空的(self):
        assert pt.OUTLIER_MIN_MINUTES < pt.OUTLIER_MAX_MINUTES

    def test_窗口不至于被半年前的旧状态拖住(self):
        assert 7 <= pt.WINDOW_DAYS <= 90

    def test_样本下限不能太低(self):
        """拿 3 单算 P80 是噪声。"""
        assert pt.MIN_SAMPLES >= 5
