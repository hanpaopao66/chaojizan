"""新手模拟跑单的步骤(#309)。

## 为什么这层要有测试

演练教的是**按钮怎么按**,而新骑手会照着它按第一单。
真流程改了(插一步、改顺序)而演练没跟上,教出来的就是错的操作 ——
这个错误只会在他第一单、拿着真顾客的饭的时候暴露。

所以判据不是「有几步」,是**「和状态机是同一份」**。
"""
from app.routers.riders import _delivery_flow
from app.state_machine import TRANSITIONS, OrderStatus


class Test流程与状态机同源:
    def test_每一步都是状态机里骑手真能做的流转(self):
        flow = _delivery_flow()
        for step in flow:
            if step["key"] == "grab":
                continue     # 抢单改的是 rider_id 不是 status
            pair = (OrderStatus(step["from"]), OrderStatus(step["to"]))
            assert pair in TRANSITIONS, f"演练里有状态机没有的一步:{step}"
            assert "rider" in TRANSITIONS[pair], (
                f"演练教骑手做一件他没权限做的事:{step}")

    def test_状态机里骑手能做的每一步演练都覆盖到(self):
        """反向也要成立 —— 少一步的表现是新骑手到那一步不知道该点什么。"""
        flow_pairs = {(s["from"], s["to"]) for s in _delivery_flow()
                      if s["key"] != "grab"}
        for (a, b), roles in TRANSITIONS.items():
            if "rider" in roles:
                assert (a.value, b.value) in flow_pairs, (
                    f"状态机有 {a.value}→{b.value} 但演练里没有 —— "
                    f"新骑手走到这一步会不知道点什么")

    def test_顺序是真实顺序不是字典序(self):
        flow = _delivery_flow()
        assert flow[0]["key"] == "grab", "第一步必须是抢单"
        keys = [s["key"] for s in flow]
        assert keys.index("picked_up") < keys.index("delivered"), \
            "先送达后取餐 —— 照着演练按第一单会一步都按不动"


class Test提示:
    def test_关键步骤有提示但不是每步都堆一段话(self):
        """每步都写一段话等于没写:新手会直接划过去。"""
        flow = _delivery_flow()
        with_tip = [s for s in flow if s["tip"]]
        assert with_tip, "一条提示都没有"
        for s in with_tip:
            assert len(s["tip"]) <= 120, f"这条太长了会被划过去:{s['tip']}"

    def test_到店那一步必须提醒先点我到店了(self):
        """等餐时长从点「我到店了」开始算,不点就等于白等 ——
        这是新骑手最常吃的一次亏,而且吃了也不知道。"""
        tip = next(s["tip"] for s in _delivery_flow()
                   if s["key"] == "picked_up")
        assert "我到店了" in tip and "等餐" in tip
