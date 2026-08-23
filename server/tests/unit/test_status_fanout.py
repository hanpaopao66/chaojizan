"""状态变更推给该收到的每一端(#302)。

## 这组测试在防什么

三个关键点击的按钮早就有了(商家「出餐完成」、骑手「已取餐」「已送达」),
但信号只走到顾客一端 —— 商家出餐了,在楼下等餐的骑手收不到,
只能靠 15 秒轮询;骑手取餐/送达了,商家看板要自己刷。

这类"少推了一个人"的缺陷**不会报错、不会有人报 bug**:
骑手只觉得这 App 慢,商家只觉得要多刷两下。所以要有测试盯着。

另外锁两条容易走歪的:
- **不推给动作的发起人**(他刚点完,再推一遍是骚扰);
- **措辞要说下一步动作**,不是复述状态字段。
"""
import asyncio

from app.services import push

CUSTOMER, MERCHANT, RIDER = 101, 202, 303


def _fanout(status, actor=None, rider=RIDER, merchant=MERCHANT):
    """跑一次 fanout,返回 [(收件人, 标题, 正文)]。"""
    sent = []

    async def fake_push(uid, title, body, data=None):
        sent.append((uid, title, body))

    orig = push.push_to_user
    push.push_to_user = fake_push
    try:
        asyncio.run(push.fanout_order_status(
            status, customer_id=CUSTOMER, merchant_owner_id=merchant,
            rider_id=rider, order_no="A1", actor_id=actor))
    finally:
        push.push_to_user = orig
    return sent


class Test出餐要通知骑手:
    def test_商家出餐骑手收得到(self):
        """**这一条是整个改动的由来。**

        骑手站在店门口等餐,餐好了他得马上知道 —— 这几分钟是他的收入。
        """
        got = _fanout("ready", actor=MERCHANT)
        assert RIDER in [u for u, _, _ in got], "商家出餐了骑手没收到通知"

    def test_还没人抢的单不推骑手(self):
        got = _fanout("ready", actor=MERCHANT, rider=None)
        assert [u for u, _, _ in got] == [CUSTOMER]

    def test_措辞说的是下一步动作(self):
        """「订单状态更新:待取餐」对骑手没有意义,他要的是「餐好了,可以取了」。"""
        got = _fanout("ready", actor=MERCHANT)
        rider_msg = next(t + b for u, t, b in got if u == RIDER)
        assert "取" in rider_msg
        assert "待取餐" not in rider_msg, "在复述状态字段,不是在说该干什么"


class Test取餐送达要通知商家:
    def test_骑手取餐商家收得到(self):
        got = _fanout("picked_up", actor=RIDER)
        assert MERCHANT in [u for u, _, _ in got]

    def test_骑手送达商家收得到(self):
        got = _fanout("delivered", actor=RIDER)
        assert MERCHANT in [u for u, _, _ in got]


class Test完成要告诉骑手钱到账了:
    def test_结算时推给骑手(self):
        """跑完一单没有任何回音,要自己翻钱包页去看 ——
        钱到账是最该主动说一声的事。"""
        got = _fanout("completed", actor=CUSTOMER)
        rider_msg = next((t + b for u, t, b in got if u == RIDER), "")
        assert rider_msg, "骑手跑完一单,钱到账了却没人告诉他"
        assert "入账" in rider_msg or "结清" in rider_msg


class Test不推给发起人:
    def test_谁点的不推给谁(self):
        for status, actor in (("ready", MERCHANT), ("picked_up", RIDER),
                              ("delivered", RIDER)):
            got = _fanout(status, actor=actor)
            assert actor not in [u for u, _, _ in got], \
                f"{status} 推给了刚点它的人,这是骚扰"

    def test_没有发起人时全推(self):
        """系统自动流转(超时自动确认等)没有发起人,该收的都得收到。"""
        got = _fanout("cancelled", actor=None)
        assert {CUSTOMER, MERCHANT, RIDER} == {u for u, _, _ in got}


class Test不认识的状态不乱推:
    def test_没配的状态静默跳过(self):
        assert _fanout("pending_payment", actor=None) == []

    def test_每个状态每人最多一条(self):
        """别把"及时"做成"每 15 秒响一次"。"""
        for status in ("ready", "picked_up", "delivered",
                       "completed", "cancelled"):
            got = _fanout(status, actor=None)
            uids = [u for u, _, _ in got]
            assert len(uids) == len(set(uids)), f"{status} 给同一个人推了两条"
