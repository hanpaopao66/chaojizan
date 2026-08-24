"""账本纪元:公告过的重置 vs 毁账(#2)。

## 这组测试守的是什么

纪元记录给了平台一条说「这次重置是公告过的」的路。这条路一旦太宽,
整套见证体系就废了 —— 平台可以一边删账一边补一条纪元来解释。

所以这里锁的全是**边界**:

- 纪元记录本身被改、被删,照样是篡改(否则可以事后编一条来解释任何删账);
- 只有落在**已公告范围内**的那几天才豁免,范围外的照旧报警;
- 指纹不含时间戳 —— 服务端换个时区写法就让全网节点集体误报,
  那种误报比漏报更致命:它会让所有人学会忽略这个警报。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "witness"))

import superz_witness as w  # noqa: E402

EPOCH1 = {
    "epoch": 1, "started_day": "2026-06-29",
    "reason": "清理演示数据", "prev_tip_hash": "",
    "prev_first_day": "2026-06-13", "prev_last_day": "2026-06-28",
    "announced_at": "2026-08-24T00:00:00Z",
}


class Test纪元指纹:
    def test_内容变了指纹就变(self):
        for key, val in (("epoch", 2), ("started_day", "2026-07-01"),
                         ("reason", "别的理由"), ("prev_tip_hash", "ab" * 32),
                         ("prev_first_day", "2026-06-14"),
                         ("prev_last_day", "2026-06-27")):
            assert w._epoch_fingerprint({**EPOCH1, key: val}) \
                != w._epoch_fingerprint(EPOCH1), f"{key} 改了指纹却没变"

    def test_时间戳不进指纹(self):
        """服务端换个时区写法就让全网节点集体报「纪元被改」——
        而那种误报比漏报更致命:它会教会所有人忽略这个警报。"""
        other = {**EPOCH1, "announced_at": "2026-08-24 08:00:00+08:00"}
        assert w._epoch_fingerprint(other) == w._epoch_fingerprint(EPOCH1)

    def test_缺字段也算得出来(self):
        """老服务端可能少给几个字段,不能因此崩掉整轮见证。"""
        assert w._epoch_fingerprint({"epoch": 1})


class Test日期辅助:
    def test_正常前一天(self):
        assert w._prev_day("2026-06-29") == "2026-06-28"

    def test_跨月(self):
        assert w._prev_day("2026-07-01") == "2026-06-30"

    def test_坏输入返回空串(self):
        """返回空串而不是抛异常,也不是返回一个猜的日期 ——
        空串在调用处会让「覆盖判定」直接不成立,也就是**不豁免**。
        判不出来的时候要倒向报警那一侧。"""
        for bad in ("", "nope", "2026-13-01", "2026-06"):
            assert w._prev_day(bad) == ""


def _covered_factory(epochs):
    """复刻 run_cycle 里的覆盖判定,单独测边界。"""
    announced = [(e.get("prev_first_day") or "", e.get("prev_last_day") or "",
                  e.get("started_day") or "", e.get("reason") or "")
                 for e in epochs]

    def covered(day):
        for first, last, started, reason in announced:
            hi = last or (started and w._prev_day(started)) or ""
            if first and hi and first <= day <= hi:
                return reason or "(未写明原因)"
        return ""
    return covered


class Test只豁免公告范围内的那几天:
    def test_范围内豁免(self):
        c = _covered_factory([EPOCH1])
        for d in ("2026-06-13", "2026-06-20", "2026-06-28"):
            assert c(d), f"{d} 在公告范围内却没豁免"

    def test_范围外照旧报警(self):
        """这是整条路最要紧的一条:纪元不是万能借口。"""
        c = _covered_factory([EPOCH1])
        for d in ("2026-06-12", "2026-06-29", "2026-08-01"):
            assert not c(d), f"{d} 在公告范围外却被豁免了"

    def test_没有纪元记录时一律不豁免(self):
        """老服务端没有这个接口 —— 行为必须退回改动之前,一切照旧报警。"""
        c = _covered_factory([])
        assert not c("2026-06-20")

    def test_缺起止范围不豁免(self):
        """一条不写清抹掉了哪几天的纪元记录,不能豁免任何东西 ——
        否则「重置」就成了一句空话就能盖住一切的咒语。"""
        c = _covered_factory([{**EPOCH1, "prev_first_day": "",
                               "prev_last_day": ""}])
        assert not c("2026-06-20")

    def test_没写结束日时用新链起点兜底(self):
        c = _covered_factory([{**EPOCH1, "prev_last_day": ""}])
        assert c("2026-06-28"), "started_day 前一天该算在旧链范围里"
        assert not c("2026-06-29"), "新链第一天不属于旧链"


class Test服务端契约:
    def test_接口和模型字段对得上(self):
        """节点认的是这几个字段名。服务端改名而节点没跟上,
        表现是「豁免突然失效、全网集体报警」——而且很难查。"""
        from app.models import LedgerEpoch
        cols = set(LedgerEpoch.__table__.columns.keys())
        assert {"epoch", "started_day", "reason", "prev_tip_hash",
                "prev_first_day", "prev_last_day"} <= cols

    def test_重置必须写原因(self):
        """空原因的重置等于没公告 —— 直接拒绝,不给"事后再补"的机会。"""
        import asyncio

        from app.services.ledger import open_new_epoch
        try:
            asyncio.run(open_new_epoch(None, "   "))
        except ValueError as e:
            assert "原因" in str(e)
        else:
            raise AssertionError("空原因居然放过了")
