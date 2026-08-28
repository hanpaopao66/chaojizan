"""排队的规则:公平性那三条,以及几个算错了会骗人的数。

## 这一组守什么

排队功能里真正会出事的不是状态机,是**规则被悄悄改软**:

1. 有人加一个「持券优先」的分支 —— 那就是卖插队权;
2. 有人给商家开一个「立即过号」的开关 —— 用户过号有代价、商家秒过号
   零成本,对称性就没了;
3. 有人把预计等待改成报期望值而不是上限 —— 报低了用户白等一肚子气。

这三条都不会让任何现有用例变红(功能全对),所以必须单独钉。
"""
import inspect
import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.services import queue as q


def code_of(obj) -> str:
    """源码,**剥掉注释和文档字符串**。

    这一组里有几条是在源码上做断言的,而模块注释里正大光明地写着
    「买券不能插队」这几个字 —— 不剥的话断言会命中解释本身。
    (test_audit_midlow_fixes 里踩过一次,同一个解法。)
    """
    src = inspect.getsource(obj)
    src = re.sub(r'"""(?:.|\n)*?"""', "", src)
    return "\n".join(l.split("#", 1)[0] for l in src.splitlines())


class Fake:
    """够用的桌型替身 —— pick_table_type 只看这四个字段。"""

    def __init__(self, id, lo, hi, active=True):
        self.id, self.seats_min, self.seats_max = id, lo, hi
        self.is_active = active


# ---------- 公平性:三条硬规则 ----------


class Test买券不能插队:
    def test_取号的入参里没有券(self):
        """`take_ticket` 的签名只有(店, 人, 人数)。

        一旦有人加了 voucher_id / is_member / priority 这类参数,
        这条就红 —— 那是把「花钱买位置」引进来的第一步。
        """
        params = list(inspect.signature(q.take_ticket).parameters)
        assert params == ["db", "shop", "customer_id", "party_size"], (
            f"取号的入参变了:{params} —— 排队只该看人数和先来后到")

    def test_整个服务层的逻辑不碰券(self):
        """扫的是**逻辑**,不含 public_spec。

        public_spec 是公示文案,里面有一节就叫 no_priority ——
        「不存在优先权」这句话本身当然会出现 priority 这个词。
        把文案也扫进来的话,这条守卫会因为「我们声明了不做这件事」而变红,
        那就成了不许解释的守卫(check_wide_layout.sh 刚犯过同一个毛病)。
        """
        import types
        src = "\n".join(
            code_of(fn) for name, fn in vars(q).items()
            if isinstance(fn, types.FunctionType)
            and fn.__module__ == q.__name__ and name != "public_spec")
        for word in ("voucher", "Voucher", "member", "vip", "priority"):
            assert word not in src, (
                f"排队的逻辑里出现了 {word!r} —— 取号和买没买券必须无关,"
                f"绑起来就是「花钱买插队权」的变体")

    def test_公示里确实声明了不卖插队权(self):
        """上一条把文案排除在外,这一条保证文案没被删掉。"""
        spec = q.public_spec()
        assert "插队" in spec["no_priority"]["claim"]
        assert spec["no_priority"]["how_to_check"], (
            "声明了「不卖插队权」却没说怎么自己查 —— 那只是一句口号")


class Test没有任何接口能把号往前挪:
    """`sort_key` 只有三种改法:取号排到队尾、过号往后挪、不改。"""

    def test_顺延只会往后不会往前(self):
        keys = [Decimal(i) for i in range(1, 11)]
        me = Decimal("0.5")          # 我在队头
        new = q.deferred_sort_key(keys, 3)
        assert new > me, "顺延之后位置反而更靠前了"
        assert new > keys[2], "顺延 3 桌,但没排到第 3 桌之后"
        assert new < keys[3], "顺延 3 桌,却被排到了第 4 桌之后 —— 罚多了"

    def test_顺延不动别人的位置(self):
        """取中点而不是重排全队 —— 别人的位置不因为你过号而改变。"""
        keys = [Decimal(i) for i in range(1, 11)]
        before = list(keys)
        q.deferred_sort_key(keys, 3)
        assert keys == before, "算新位置的时候把别人的键改了"

    def test_前面不足_N_桌就去队尾(self):
        new = q.deferred_sort_key([Decimal(1), Decimal(2)], 3)
        assert new > Decimal(2), "前面只有 2 桌,顺延 3 桌应该到队尾"

    def test_队列空时不炸(self):
        assert q.deferred_sort_key([], 3) == Decimal(1)

    def test_连续两次顺延都还在合法位置(self):
        """第二次过号会转待恢复,但恢复之后还会再算一次 —— 精度要够。"""
        keys = [Decimal(i) for i in range(1, 21)]
        a = q.deferred_sort_key(keys, 3)
        b = q.deferred_sort_key(sorted(keys + [a]), 3)
        assert Decimal(3) < a < Decimal(4)
        assert Decimal(3) < b < Decimal(4) and b != a


class Test商家不能秒过号:
    """对称性:用户过号有代价,商家叫完就点过号也不能零成本。"""

    def test_刚叫号不许过(self):
        assert not q.can_pass(datetime.now(timezone.utc)), (
            "叫号当场就能标过号 —— 客人还在往里走的路上")

    def test_过了宽限期才许过(self):
        old = datetime.now(timezone.utc) - timedelta(
            seconds=q.CALL_GRACE_SECONDS + 1)
        assert q.can_pass(old)

    def test_边界上就算够(self):
        edge = datetime.now(timezone.utc) - timedelta(
            seconds=q.CALL_GRACE_SECONDS)
        assert q.can_pass(edge), "正好到点却还不让过,商家会一直点不动"

    def test_没叫号不能过(self):
        assert not q.can_pass(None), "没叫过号就能标过号"

    def test_宽限期不是商家可配项(self):
        """一旦挪进 QueueSetting,商家就能设成 0,这条规则等于没有。"""
        from app.models import QueueSetting
        cols = set(QueueSetting.__table__.columns.keys())
        assert "call_grace_seconds" not in cols, (
            "叫号宽限期被挪进商家设置了 —— 商家会把它设成 0")

    def test_默认值够长(self):
        """平台部署方能改这个数(e2e 就把它调小了),但**默认值**要够 ——
        默认值站错边的话,没读过文档的自部署者就把这条保护关掉了。

        读 bare Settings:本机 .env 里为了跑 e2e 设成了 2 秒,
        直接读 settings 的话这条断言测的是我的开发环境。
        """
        from app.config import Settings
        assert Settings(_env_file=None).queue_call_grace_seconds >= 60
        assert q.CALL_GRACE_SECONDS >= 60

    def test_公示报的是实际生效值(self):
        """自部署者可以把它改小,但改了就得写在公示上 —— 藏不住。"""
        spec = q.public_spec()
        assert spec["merchant_limits"]["call_grace_seconds"] == q.grace_seconds()


# ---------- 几个算错了会骗人的数 ----------


class Test预计等待报的是上限:
    @pytest.mark.parametrize("ahead,tables,turn,want", [
        (0, 4, 45, 45),      # 队头也要等一轮:桌都坐着呢
        (3, 4, 45, 45),      # 4 张桌,前面 3 桌 → 同一轮
        (4, 4, 45, 90),      # 第 5 位 → 第二轮
        (5, 2, 45, 135),     # 2 张桌,第 6 位 → 第三轮
        (0, 1, 60, 60),
    ])
    def test_按轮次算(self, ahead, tables, turn, want):
        assert q.wait_upper_minutes(ahead, tables, turn) == want

    def test_没桌不炸(self):
        assert q.wait_upper_minutes(3, 0, 45) == 0

    def test_永远不低估(self):
        """报低了用户白等一肚子气,报高了实际更快是惊喜。

        这条钉的是「估的是上限」这个立场:同样的前方桌数,
        估出来的时间不该少于「你至少要等的轮数 × 时长」。
        """
        for ahead in range(0, 30):
            for tables in range(1, 6):
                got = q.wait_upper_minutes(ahead, tables, 45)
                least = ((ahead // tables) if ahead % tables else
                         (ahead // tables)) * 45
                assert got >= least

    def test_口径要公示(self):
        assert q.WAIT_BASIS and "向上取整" in q.WAIT_BASIS, (
            "预计等待的算法必须写成一句能公示的人话 —— "
            "用户要能自己复算,否则这个数字就是个说了算的黑箱")


class Test挑桌型挑能坐下的最小那档:
    def test_挑最小合适的(self):
        types = [Fake(1, 1, 2), Fake(2, 3, 4), Fake(3, 5, 10)]
        assert q.pick_table_type(types, 2).id == 1
        assert q.pick_table_type(types, 4).id == 2
        assert q.pick_table_type(types, 6).id == 3

    def test_坐不下返回_None(self):
        assert q.pick_table_type([Fake(1, 1, 4)], 8) is None

    def test_跳过停用的桌型(self):
        types = [Fake(1, 1, 4, active=False), Fake(2, 1, 6)]
        assert q.pick_table_type(types, 2).id == 2

    def test_没有桌型也不炸(self):
        assert q.pick_table_type([], 2) is None

    def test_不让小桌去占大桌那条队(self):
        """2 个人挑包间排队,包间队被占着,真 8 个人的反而排不上 ——
        那本身就是一种插队,所以桌型由服务端定,不给用户选。"""
        types = [Fake(1, 1, 2), Fake(2, 6, 10)]
        assert q.pick_table_type(types, 2).id == 1


class Test放号上限:
    def test_桌数乘倍数(self):
        assert q.issue_cap(12, 3) == 36

    def test_倍数至少是_1(self):
        assert q.issue_cap(10, 0) == 10, "倍数传 0 会变成一个号都不放"

    def test_没桌就是_0(self):
        assert q.issue_cap(0, 3) == 0


class Test号码可读:
    def test_按桌型分字母(self):
        a, b = q.ticket_code(1, 7), q.ticket_code(2, 7)
        assert a != b and a.endswith("007")

    def test_序号补零(self):
        assert q.ticket_code(0, 12) == "A012"


class Test按北京时间切日:
    def test_不是本机日期(self):
        """开发机在 PDT 时本地日期比北京晚一天 —— 用 date.today()
        号码会在下午整体串一天(账本那边踩过)。"""
        src = code_of(q.beijing_today)
        assert "Asia/Shanghai" in src
        assert "date.today()" not in src
