"""规则变更留痕:规则不许静默地改(#305)。

## 这组测试守什么

规则页的每个数字都从代码常量算出来 —— 这比"后台可编辑的文案"强,
文档不可能和实现对不上。但它有个反面:**改一个常量就等于悄悄改了规则,
没有任何人被告知**。

给零售商家加「发货必须拍照」就是这么进去的:那是新增的一项义务,
走的是一个 commit。生产上真有零售商家的话,他们会在点「已出餐」报错的
那一刻才知道这条规则存在。

## 存快照不存 diff

diff 是快照的函数,反过来不成立。存 diff 的话算法改进了没法重算,
中间漏一次就再也对不上(账本锚点是同一个理由)。

## ⚠️ 这一版只做「不再静默」

真正的公示是"先公告、N 天后生效",要求每条新规则各自有开关。
这里只保证变更被记下来且公开可读 —— 测试里也把这个边界写明,
免得后来的人以为公示期已经有了。
"""
import inspect

from app.services import rules


class Test指纹只认内容:
    def test_内容一样指纹就一样(self):
        a = [{"title": "钱", "items": ["一", "二"]}]
        b = [{"title": "钱", "items": ["一", "二"]}]
        assert rules.content_hash(a) == rules.content_hash(b)

    def test_改一个字指纹就变(self):
        a = [{"title": "食安", "items": ["30 天内成立 3 起自动停业"]}]
        b = [{"title": "食安", "items": ["30 天内成立 5 起自动停业"]}]
        assert rules.content_hash(a) != rules.content_hash(b), (
            "公示 3 起、代码里写 5 起 —— 指纹认不出来的话,"
            "这种事就会一直没人发现")

    def test_删一条也算变(self):
        a = [{"title": "钱", "items": ["一", "二"]}]
        b = [{"title": "钱", "items": ["一"]}]
        assert rules.content_hash(a) != rules.content_hash(b)


class Test逐条diff:
    def test_新增(self):
        old = [{"title": "钱", "items": ["一"]}]
        new = [{"title": "钱", "items": ["一", "二"]}]
        d = rules.diff_sections(old, new)
        assert d == [{"title": "钱", "removed": [], "added": ["二"]}]

    def test_删除(self):
        old = [{"title": "钱", "items": ["一", "二"]}]
        new = [{"title": "钱", "items": ["一"]}]
        d = rules.diff_sections(old, new)
        assert d == [{"title": "钱", "removed": ["二"], "added": []}]

    def test_改一条等于删一条加一条(self):
        """按条比不按字比:规则是一条一条的,字级 diff 会把
        「30 天 3 起」改成「30 天 5 起」显示成一堆红绿字符,反而看不清。"""
        old = [{"title": "食安", "items": ["30 天内成立 3 起"]}]
        new = [{"title": "食安", "items": ["30 天内成立 5 起"]}]
        d = rules.diff_sections(old, new)
        assert d[0]["removed"] == ["30 天内成立 3 起"]
        assert d[0]["added"] == ["30 天内成立 5 起"]

    def test_没变就是空(self):
        a = [{"title": "钱", "items": ["一"]}]
        assert rules.diff_sections(a, a) == []

    def test_整节新增(self):
        old = []
        new = [{"title": "新的一节", "items": ["一"]}]
        d = rules.diff_sections(old, new)
        assert d == [{"title": "新的一节", "removed": [], "added": ["一"]}]


class Test只跟最近一版比:
    def test_改回去也要记一版(self):
        """A→B→A 的第三步是一次真实的变更 —— **改回去也是改**。
        跟历史上所有版本比对的话,回滚就成了静默操作。"""
        src = inspect.getsource(rules.record_if_changed)
        assert "desc(RuleRevision.revision)" in src and ".limit(1)" in src, \
            "要跟最近一版比,不是跟历史上所有版本比"


class Test并发不该报错:
    def test_撞唯一约束要吞掉(self):
        """两个人同时打开规则页,后一个插入撞约束。
        留痕不该因为这个把请求打挂。"""
        src = inspect.getsource(rules.record_if_changed)
        assert "except Exception:" in src and "rollback" in src


class Test边界写明了:
    def test_模型抬头说清楚没有生效前置(self):
        """免得后来的人以为公示期已经有了。"""
        from app.models import RuleRevision
        doc = inspect.getdoc(RuleRevision) or ""
        assert "生效前置" in doc and "不做" in doc

    def test_接口文档也说清楚(self):
        from app.routers.platform import public_rule_revisions
        doc = inspect.getdoc(public_rule_revisions) or ""
        assert "不是「什么时候生效」" in doc

    def test_留痕接口是公开的(self):
        from app.routers.platform import public_rule_revisions
        sig = inspect.signature(public_rule_revisions)
        assert "user" not in sig.parameters, "规则改过什么,不该要登录才看得到"
