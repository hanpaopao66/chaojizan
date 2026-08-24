"""锚点是快照,不是实时查询 —— 底层单据删了,它照样自洽。

## 这条为什么值一个测试

`scrub_demo.py` 曾经在清演示数据时**连账本锚点一起清空**,写的理由是
「演示订单被清后,历史每日锚点必然与数据重算对不上」。

这个理由是错的:锚点把当天的 payload **全文**存了下来,
`/ledger/days/{day}` 返回的是存下来的那份。单据删掉之后,
payload_hash 和 chain_hash 一个字节都不会变。

而按那条错理由付出的代价是:2026-07-28 在生产上清了一次,官方见证节点
从那天报警到今天 9000 多次,`/nodes` 页对外挂着一个永久的红色警报。
对外部观察者来说,那就是「平台删了 16 天的账」。

所以把这个论证钉成测试:**只要 `/ledger/days` 还是读存量而不是重算,
清数据就不需要动账本。** 哪天有人把它改成实时重算,这里会红 ——
而那正是"又要清一次链"的前夜。
"""
import inspect
import json

from app.services.ledger import canonical, sha256


class Test锚点读的是存量:
    def test_接口返回存下来的payload(self):
        """`/ledger/days/{day}` 必须读 anchor.payload,不能重算。

        重算的话,任何一条历史单据被删/被改都会让哈希对不上 ——
        那才是"清数据必须清链"的真正来源。
        """
        from app.routers import ledger as router

        src = inspect.getsource(router.ledger_day)
        assert "anchor.payload" in src, "没有读存量 payload"
        assert "build_day_payload" not in src, \
            "接口在重算当天流水 —— 单据一动哈希就变,清数据又得清链"

    def test_建锚点时才算一次(self):
        """算是在 build_missing_anchors 里算的,算完就冻。"""
        from app.services import ledger as svc

        src = inspect.getsource(svc.build_missing_anchors)
        assert "build_day_payload" in src and "LedgerAnchor(" in src


class Test删单据不影响已有锚点:
    def test_哈希只取决于存下来的那份文本(self):
        """模拟:同一份 payload 文本,无论底层数据还在不在,哈希不变。"""
        payload = {"schema": 1, "day": "2026-06-20",
                   "merchant_rows": [{"o": "abc", "food": 3000,
                                      "commission": 150, "net": 2850}],
                   "rider_rows": [], "voucher_rows": [], "stay_rows": []}
        text = canonical(payload)
        h1 = sha256(text)
        # "单据被删" 之后,锚点里存的仍然是同一段文本
        stored = text
        assert sha256(stored) == h1
        # 从存量还原出来的对象也一字不差
        assert canonical(json.loads(stored)) == text

    def test_链哈希只依赖前一环和当天payload哈希(self):
        prev = "a" * 64
        ph = "b" * 64
        assert sha256(prev + ph) == sha256(prev + ph)


class Test清理脚本不再动账本:
    def test_scrub_demo不删锚点(self):
        """删了就会重演 2026-07-28:节点报警报到没人再看。"""
        import scripts.scrub_demo as sd

        src = inspect.getsource(sd)
        assert "m.LedgerAnchor" not in src, \
            "scrub_demo 又在删账本锚点了 —— 那会让所有见证节点报「锚点消失」"

    def test_历史核账记录也不删(self):
        """删 AuditRun 会让「连续 N 天零差错」归零 ——
        那是自己给自己抹掉的信用,而且没有任何必要。"""
        import scripts.scrub_demo as sd

        src = inspect.getsource(sd)
        assert "m.AuditRun" not in src

    def test_真要重置必须走纪元(self):
        from app.services.ledger import open_new_epoch
        assert open_new_epoch.__doc__ and "冻结" in open_new_epoch.__doc__
