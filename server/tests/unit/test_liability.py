"""判责与分摊口径:这是对外承诺,所以每条都要能被验证。

## 这组测试守什么

`labor_guard.LABOR_PROMISES` 立的规矩是「承诺要能被验证,否则只是话术」。
这里是同一个规矩用在钱上,而钱比话更需要钉死:

1. **四方相加恒等于用户已付**。少一分就是有人凭空吃了钱、多一分就是平台
   凭空造了钱,两种都会让公开账本的恒等式当场破掉;
2. **取消场景平台佣金恒为 0**。这是承诺的第一条,而它最容易在"顺手补个
   佣金逻辑"的改动里被悄悄改掉;
3. **出餐之前不归这个模块管**。既有的 2 分钟反悔窗口和"商家超时可全退"
   已经上线且推敲过,这个模块不许覆盖它们;
4. **公示的数字必须从常量读**。抄一份的话,改了代码忘了改公示,
   公示就成了假的 —— 那比不公示更糟。
"""
import pytest

from app.services import liability as L

# 一组不那么整的数,专门用来暴露取整误差
MONEY = dict(food_cents=2350, packing_fee_cents=150, discount_cents=400,
             delivery_fee_cents=487, tip_cents=113)
PAID = 2350 + 150 - 400 + 487 + 113          # = 2700


class Test四方相加不能少也不能多:
    @pytest.mark.parametrize("stage", [
        L.STAGE_BEFORE_COST, L.STAGE_COOKED,
        L.STAGE_RIDER_ARRIVED, L.STAGE_IN_DELIVERY,
    ])
    def test_每个阶段都对得平(self, stage):
        s = L.split_for_cancel(stage, **MONEY)
        assert s.total_cents == PAID, (
            f"{stage}:四方合计 {s.total_cents} ≠ 用户已付 {PAID} —— "
            f"有人凭空吃了钱或平台凭空造了钱")

    @pytest.mark.parametrize("fee", [0, 1, 3, 7, 99, 487, 500, 1001])
    def test_配送费取整不吞钱(self, fee):
        """空跑费按比例算会取整,余额必须补回用户,一分都不许蒸发。"""
        money = dict(MONEY, delivery_fee_cents=fee)
        paid = (money["food_cents"] + money["packing_fee_cents"]
                - money["discount_cents"] + fee + money["tip_cents"])
        s = L.split_for_cancel(L.STAGE_RIDER_ARRIVED, **money)
        assert s.total_cents == paid, f"配送费 {fee} 分时对不平"

    def test_满减大于餐费时商家不倒扣(self):
        """应收钳 0,与 settlement.credit_merchant 同口径。"""
        money = dict(MONEY, food_cents=100, packing_fee_cents=0,
                     discount_cents=9999)
        s = L.split_for_cancel(L.STAGE_IN_DELIVERY, **money)
        assert s.merchant_cents == 0, "商家被倒扣了钱"


class Test平台佣金在取消时恒为零:
    @pytest.mark.parametrize("stage", [
        L.STAGE_BEFORE_COST, L.STAGE_COOKED,
        L.STAGE_RIDER_ARRIVED, L.STAGE_IN_DELIVERY,
    ])
    def test_一分都不收(self, stage):
        s = L.split_for_cancel(stage, **MONEY)
        assert s.commission_cents == 0, (
            "取消场景收了佣金 —— 直接违背 LIABILITY_PROMISES 第一条")

    def test_账单上要单列这一行让用户看见平台让掉了什么(self):
        s = L.split_for_cancel(L.STAGE_IN_DELIVERY, **MONEY)
        plat = [l for l in s.lines if l.to == "platform"]
        assert len(plat) == 1 and plat[0].cents == 0
        assert plat[0].why, "让掉了却不说,等于没让"


class Test各阶段谁拿什么:
    def test_出餐前全额退(self):
        s = L.split_for_cancel(L.STAGE_BEFORE_COST, **MONEY)
        assert (s.refund_cents, s.merchant_cents, s.rider_cents) == (PAID, 0, 0)

    def test_已出餐骑手没到店_餐费归商家配送费退用户(self):
        s = L.split_for_cancel(L.STAGE_COOKED, **MONEY)
        assert s.merchant_cents == 2350 + 150 - 400
        assert s.refund_cents == 487 + 113, "骑手还没到店,配送费该整笔退"
        assert s.rider_cents == 0, "骑手什么都没做,不该拿钱"

    def test_骑手已到店_拿空跑费余额退用户(self):
        s = L.split_for_cancel(L.STAGE_RIDER_ARRIVED, **MONEY)
        assert s.rider_cents == int(487 * L.IDLE_TRIP_SHARE)
        assert s.merchant_cents == 2350 + 150 - 400
        assert s.refund_cents == PAID - s.rider_cents - s.merchant_cents

    def test_配送中_用户拿回零但账要说清(self):
        s = L.split_for_cancel(L.STAGE_IN_DELIVERY, **MONEY)
        assert s.refund_cents == 0
        assert s.rider_cents == 487 + 113, "配送费+小费必须整笔归骑手"
        assert s.merchant_cents == 2350 + 150 - 400
        assert all(l.why for l in s.lines), "有一行没写为什么"

    def test_只有配送中那一档要交代餐的去向(self):
        """餐在骑手车上才需要说它归谁;还没取餐的餐还在店里。"""
        assert L.split_for_cancel(L.STAGE_IN_DELIVERY, **MONEY).food_to
        for stage in (L.STAGE_BEFORE_COST, L.STAGE_COOKED,
                      L.STAGE_RIDER_ARRIVED):
            assert not L.split_for_cancel(stage, **MONEY).food_to


class Test出餐之前不归这个模块管:
    def test_ready之后才认(self):
        assert L.stage_of("ready", rider_arrived=False) == L.STAGE_COOKED
        assert L.stage_of("ready", rider_arrived=True) == L.STAGE_RIDER_ARRIVED
        assert L.stage_of("picked_up", rider_arrived=True) == L.STAGE_IN_DELIVERY

    @pytest.mark.parametrize("status", ["pending_payment", "paid", "accepted"])
    def test_出餐之前一律抛错走原路(self, status):
        """既有的 2 分钟反悔窗口和"商家超时可全退"已经上线,不许被覆盖。"""
        with pytest.raises(ValueError):
            L.stage_of(status, rider_arrived=False)

    @pytest.mark.parametrize("status", ["delivered", "completed", "cancelled"])
    def test_送达之后也不归这里管(self, status):
        """送达之后走售后,不走取消分摊。"""
        with pytest.raises(ValueError):
            L.stage_of(status, rider_arrived=False)


class Test公示与代码同源:
    def test_空跑费比例直接读常量(self, monkeypatch):
        monkeypatch.setattr(L, "IDLE_TRIP_SHARE", 0.25)
        assert L.public_spec()["idle_trip_share"]["value"] == 0.25, (
            "公示的数字是抄的,不是读的 —— 改了代码公示不会跟着变")

    def test_承诺原样出现在公示里(self):
        assert L.public_spec()["promises"] is L.LIABILITY_PROMISES

    def test_每个阶段都要有成本说明(self):
        stages = L.public_spec()["stages"]
        assert len(stages) == len(L.STAGE_LABELS)
        for s in stages:
            assert s["label"] and s["cost_incurred"], f"{s['stage']} 没说清楚"

    def test_申诉通道三方都要能用(self):
        who = L.public_spec()["appeal"]["who"]
        for role in ("用户", "商家", "骑手"):
            assert role in who, f"公示里没写 {role} 能申诉"

    def test_那条例外要写明适用边界(self):
        """例外不写边界就会变成万能借口。"""
        exc = L.public_spec()["the_one_exception"]
        assert exc["why"] and exc["scope"]
