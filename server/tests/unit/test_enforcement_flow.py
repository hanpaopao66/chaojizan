"""处置的执行链:判定 → 生效 → 可见 → 申诉推翻 → 自动恢复(#306)。

## 这组测试守什么

`test_enforcement.py` 守的是目录本身(计次不计分、阈值绑严重程度)。
这一组守的是**它真的被接上了** —— 一张漂亮的目录如果没有任何生效点
读它,那就只是一页文案。

三件事最容易在后续改动里悄悄断掉:

1. **生效点绕过目录。** 三处限制原先直接读 `user.risk_level`;目录接上
   之后必须走 `level_for`,否则按目录被限制的人照样领补贴 ——
   而这种"规则写了但不生效"不会报错,只会让规则页变成谎话。
2. **判定的人替目录拍板。** 判定接口不该收 level 参数 ——
   判定的人只回答"这件事成立吗",给什么处置是目录定的。
3. **推翻等于删除。** 删了的话当事人看不到自己申诉赢了,审计也查不出
   改过什么。必须是"标记不计入,行还在"。
"""
import inspect

import pytest


class Test生效点必须走目录:
    """三处都改成 level_for。直接读 user.risk_level = 绕过目录。"""

    @pytest.mark.parametrize("mod,fn", [
        ("app.routers.orders", "create_order"),
        ("app.routers.merchants", "claim_shop_coupon"),
        ("app.routers.favorites", "_issue_favorite_coupon"),
    ])
    def test_读的是算出来的级别(self, mod, fn):
        import importlib
        m = importlib.import_module(mod)
        target = getattr(m, fn, None)
        if target is None:                      # 函数改名了,单独报出来
            pytest.fail(f"{mod}.{fn} 不存在了 —— 生效点没人守了")
        src = inspect.getsource(target)
        assert "level_for(" in src, f"{fn} 没走 level_for,绕过了处置目录"
        assert "user.risk_level in (" not in src, \
            f"{fn} 还在直接读 risk_level —— 按目录被处置的人会被漏掉"


class Test判定的人不替目录拍板:
    def test_判定接口不收level(self):
        """判定的人只回答"这件事成立吗"。给什么处置是目录定的 ——
        让判定人挑级别,等于把目录变成建议。"""
        from app.routers.admin import record_violation
        src = inspect.getsource(record_violation)
        assert '"level"' not in src.split("return")[0], \
            "判定接口收了 level 参数"
        assert "level_for" in src, "应当把算出来的级别回给调用方"

    def test_必须写明原因(self):
        from app.routers.admin import record_violation
        src = inspect.getsource(record_violation)
        assert "必须写明原因" in src, (
            "规则页上写着「任何处置都写明原因」—— 允许空 note 就是失约")

    def test_行为类型必须对得上端(self):
        """给一个骑手记「恶意售后」是判定错误,不是数据问题。"""
        from app.routers.admin import record_violation
        assert "rule.audience" in inspect.getsource(record_violation)


class Test推翻不是删除:
    def test_只打标记不删行(self):
        from app.routers.admin import overturn_violation
        src = inspect.getsource(overturn_violation)
        assert "overturned_at" in src
        assert "db.delete" not in src, (
            "删了的话:公示的处置总数对不上、当事人看不到自己申诉赢了、"
            "审计也查不出改过什么")

    def test_推翻之后级别自动重算(self):
        from app.routers.admin import overturn_violation
        assert "level_for" in inspect.getsource(overturn_violation)

    def test_重复推翻是幂等的(self):
        from app.routers.admin import overturn_violation
        assert "already" in inspect.getsource(overturn_violation)


class Test当事人看得见:
    def test_有本人可见的接口(self):
        from app.routers.auth import my_violations
        src = inspect.getsource(my_violations)
        assert "expires_at" in src, (
            "计次制特有的:当事人能自己算出还剩多久。"
            "不给这个数,他就只能问客服")
        assert "counted" in src, "被推翻的那条要看得出来已经不算了"

    def test_人工那条通道的原因也要给(self):
        """User.risk_level 那条不在逐条记录里 —— 不单独说明的话,
        当事人会看到"我一条都没有"却被限制着。"""
        from app.routers.auth import my_violations
        assert "manual_note" in inspect.getsource(my_violations)

    def test_不需要管理员权限(self):
        from app.routers.auth import my_violations
        sig = inspect.signature(my_violations)
        assert "user" in sig.parameters and "admin" not in sig.parameters


class Test线索不等于判定:
    def test_目录里没有自动判定(self):
        """曾经把虚假出餐标成「系统自动判定」,那是错的:
        true_ready_at 能看出"申报时餐没好",但那也可能是厨房临时耽搁。
        **按单自动记违规会把忙的店天天判成作恶。**

        自动的是累计和处置,不是判定。"""
        from app.services.enforcement import CATALOG, Rule
        assert not hasattr(Rule, "decided"), \
            "decided 已经换成 evidence —— 系统给线索,不给结论"
        for r in CATALOG:
            assert isinstance(r.evidence, str)

    def test_虚假出餐的线索是占比不是单次(self):
        from app.services.enforcement import CATALOG
        r = next(x for x in CATALOG if x.kind == "fake_ready")
        assert "占比" in r.evidence, (
            "看单次的话,忙的店偶尔耽搁就会被记成作恶")
