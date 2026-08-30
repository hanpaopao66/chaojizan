"""三端规则页:对称就是公平的形状(#305)。

## 这组测试守什么

「一方能做另一方不能做」就是不公平 —— 这是申诉通道那次定下的判据。
规则页是它的延伸:**三端读到的处置分级和申诉口径必须一字不差**,
各端只在「什么行为会触发」上不同,因为三端能做的坏事本来就不一样,
而不是因为平台对谁更宽。

所以这里测的不是"页面有没有内容",是**三份内容之间的关系**。
这类不对称不会报错,只会在某一天被人发现"凭什么骑手申诉只有 24 小时
而商家有 72 小时" —— 而那时它已经这样跑了半年。

`labor_guard.LABOR_PROMISES` 的注释写着「每一条都有对应测试 ——
承诺要能被验证,否则只是话术」。这一组是同一个意思。
"""
import asyncio

import pytest

from app.services import rules


def _run(coro):
    return asyncio.run(coro)


class _FakeDB:
    """规则页只用 db 查一个运行时开关(等餐补偿),不需要真库。"""


@pytest.fixture()
def three(monkeypatch):
    async def fake_flag(_db):
        return False
    monkeypatch.setattr("app.services.flags.wait_comp_on", fake_flag)
    return {a: _run(rules.rules_for(a, _FakeDB())) for a in rules.AUDIENCES}


class Test三端都有:
    def test_三端一个不少(self):
        assert set(rules.AUDIENCES) == {"customer", "merchant", "rider"}

    def test_每端都有内容(self, three):
        for a, r in three.items():
            assert r["sections"], a
            for s in r["sections"]:
                assert s["title"] and s["items"], (a, s)


class Test处置那一节三端一字不差:
    """**这是公平的核心。** 分级、可见性、申诉资格,三端必须完全一样;
    只有「什么行为会触发」可以不同。"""

    def _risk(self, r):
        return next(s for s in r["sections"] if s["title"] == "什么会被处置")

    def test_标题相同(self, three):
        for r in three.values():
            assert self._risk(r)["title"] == "什么会被处置"

    def test_分级与承诺部分逐字相同(self, three):
        """把各端自己的触发行为剔掉,剩下的必须完全一致。"""
        common = {}
        for a, r in three.items():
            items = [x for x in self._risk(r)["items"]
                     if not x.startswith("　· ")]
            common[a] = items
        vals = list(common.values())
        assert vals[0] == vals[1] == vals[2], (
            f"处置口径三端不一致 —— 那就是「一方能做另一方不能做」:\n"
            + "\n".join(f"{a}: {v}" for a, v in common.items()))

    def test_每端都写明了可见可申诉(self, three):
        for a, r in three.items():
            text = "".join(self._risk(r)["items"])
            assert "可见" in text and "申诉" in text, a
            assert "误判优先放行" in text, a

    def test_每端都写明慢不算坏(self, three):
        """君子协定的延伸:测量不是鞭子。三端都要写,不能只对商家写。"""
        for a, r in three.items():
            assert "慢不算坏" in self._risk(r)["items"][0], a

    def test_每端都有各自的触发行为(self, three):
        """结构一样不等于内容空 —— 每端都得说清楚什么算破坏规则。"""
        for a, r in three.items():
            triggers = [x for x in self._risk(r)["items"]
                        if x.startswith("　· ")]
            assert len(triggers) >= 2, f"{a} 没说清楚什么会被处置"


class Test申诉那一节三端一字不差:
    def _appeal(self, r):
        return next(s for s in r["sections"] if s["title"] == "申诉")

    def test_逐字相同(self, three):
        vals = [self._appeal(r)["items"] for r in three.values()]
        assert vals[0] == vals[1] == vals[2], (
            "申诉口径三端不一致 —— 窗口或举证责任只要有一端不同,就是不公平")

    def test_窗口来自常量不是手写(self, three):
        from app.routers.appeals import APPEAL_WINDOW
        hours = int(APPEAL_WINDOW.total_seconds() // 3600)
        for a, r in three.items():
            assert f"{hours} 小时" in "".join(self._appeal(r)["items"]), a


class Test数字不许手写:
    def test_没有裸的中文数字规则(self, three):
        """公示 30 天 3 起、代码里写 5 起,这种事只要可能发生就会发生。
        这条是弱守卫:真正的保证是 rules.py 里所有数字都来自 import。"""
        import inspect
        src = inspect.getsource(rules.rules_for)
        for name in ("FS_AUTO_SUSPEND_COUNT", "APPEAL_WINDOW",
                     "APPLY_WINDOW_DAYS", "RIDE_SPEED_KMH",
                     "FATIGUE_REMIND_MINUTES", "commission_tiers"):
            assert name in src, f"{name} 没从常量取,是手写的"

    def test_骑手承诺直接引用labor_guard(self):
        """在这里另抄一份 = 给自己留一个对不上的机会。
        labor_guard 那份每一条都有对应测试。"""
        import inspect
        src = inspect.getsource(rules.rules_for)
        assert "list(LABOR_PROMISES)" in src


class Test等餐补偿关着时不许出现:
    def test_开关关闭则骑手页不提补偿(self, three):
        """公示了却不给,比不公示更坏(4c2d0d1 的原话)。"""
        text = "".join(
            i for s in three["rider"]["sections"] for i in s["items"])
        assert "等餐超时有补偿" not in text

    def test_开关打开则出现(self, monkeypatch):
        async def on(_db):
            return True
        monkeypatch.setattr("app.services.flags.wait_comp_on", on)
        r = _run(rules.rules_for("rider", _FakeDB()))
        text = "".join(i for s in r["sections"] for i in s["items"])
        assert "等餐超时有补偿" in text


class Test公开可读:
    def test_路由没有登录依赖(self):
        import inspect

        from app.routers.platform import public_rules
        sig = inspect.signature(public_rules)
        assert "user" not in sig.parameters, (
            "规则要在加入之前就能读到 —— 想入驻的商家、想跑单的骑手,"
            "得先看见规则再决定要不要来")
