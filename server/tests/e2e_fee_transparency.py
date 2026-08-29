"""配送费构成透明 + 上门难度费(AP·AO)。

## 这一批的立场

我们的配送费有个别家没有的性质:**顾客付的钱和骑手拿的钱是同一个数**
(credit_rider_for_order 里写着"一分不少全归骑手")。美团/淘宝闪购是
两笔独立定价,中间差额由平台调节。

代价是「给骑手加钱 = 给顾客加价」,好处是**账可以彻底摊开**。
所以这一批的重点不是加了多少钱,是**每一笔都说得清**:
- 拆分存快照带进订单(此前只在预览里露一次,下单后就没人看得到);
- 骑手**接单前**就看得到构成(美团官方只承诺"看得到价格",看不到明细);
- 顾客自己选送上门还是送楼下,差价明码标出。

另外守两条:
- 有电梯不收上门费(等电梯的时间已经在 ETA 里补过,再收就是收两次);
- 等餐补偿**不进 delivery_fee_cents** —— 那是顾客付的钱,
  顾客不该为商家的慢买单。
"""
import asyncio
import random
import sys
from pathlib import Path
from urllib.parse import urlencode

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text  # noqa: E402

from app.db import SessionLocal  # noqa: E402

from .util import CUSTOMER, MERCHANT, RIDER, call, login  # noqa: E402
from .util import DEMO_SHOP_ID  # noqa: E402
from .util import orderable_dish  # noqa: E402

customer = login(CUSTOMER)
merchant = login(MERCHANT)
rider = login(RIDER)

FAR = {"lat": 30.6927, "lng": 104.0823}


def check_door_fee_rules():
    """上门难度费的判定 —— 直接对函数下断言,不受配送费下限影响。"""
    from app.services.pricing import door_fee_cents

    assert door_fee_cents(None, None) == 0, "没填楼层不收(不猜)"
    assert door_fee_cents(3, False) == 0, "4 楼及以下不收"
    assert door_fee_cents(6, False) == 200, "无电梯 6 楼:超出 2 层 × ¥1"
    assert door_fee_cents(20, False) == 500, "封顶 ¥5"
    assert door_fee_cents(6, True) == 0, \
        "有电梯不收 —— 等电梯的时间已经在 ETA 里补过,再收就是收两次钱"
    assert door_fee_cents(6, False, to_door=False) == 0, \
        "顾客选了送到楼下就不收(骑手也没有义务上楼)"
    print("✓ 上门难度费:不猜、4 楼以下免、有电梯免、选楼下免、封顶 ¥5")


def preview(**kw):
    q = urlencode({"merchant_id": DEMO_SHOP_ID, **FAR, **kw})
    return call("GET", f"/orders/delivery-fee?{q}", customer)


async def main():
    check_door_fee_rules()

    # ---- 预览:拆分 + 中文名 + 送上门差价 ----
    flat = preview()
    assert set(flat["parts"]) >= {"base", "night", "weather", "door"}, flat
    assert flat["labels"]["door"].startswith("上门难度"), flat["labels"]
    assert flat["parts"]["door"] == 0, "没填楼层不收"

    high = preview(floor=6, has_elevator="false")
    assert high["parts"]["door"] == 200, high["parts"]
    assert high["fee_cents"] == flat["fee_cents"] + 200, \
        f"上门费该实打实加进总额:{flat['fee_cents']} → {high['fee_cents']}"
    # 让顾客在**选之前**就看到差价,而不是选完才发现多收了
    assert high["door_fee_cents"] == 200, high
    print(f"✓ 预览带拆分与中文名;6 楼无电梯送上门 +¥"
          f"{high['parts']['door'] / 100:g},差价预先可见")

    downstairs = preview(floor=6, has_elevator="false", to_door="false")
    assert downstairs["parts"]["door"] == 0
    assert downstairs["fee_cents"] == flat["fee_cents"]
    assert downstairs["door_fee_cents"] == 200, \
        "选了楼下也要能看到「送上门要多少」,否则顾客没法比较"
    print("✓ 选「送到楼下」不收上门费,但仍显示送上门要多少(可比较)")

    # ---- 下单:拆分快照进订单,四端都看得到 ----
    dishes = call("GET", f"/merchants/{DEMO_SHOP_ID}/dishes")
    dish = orderable_dish(dishes, min_stock=4)
    order = call("POST", "/orders", customer, {
        "merchant_id": DEMO_SHOP_ID,
        "items": [{"dish_id": dish["id"], "quantity": 1}],
        "address": "透明测试地址 6 楼", **FAR,
        "floor": 6, "has_elevator": False, "to_door": True})
    assert order["fee_parts"]["door"] == 200, order["fee_parts"]
    assert order["fee_part_labels"]["door"], "中文名要跟着数一起给"
    assert order["to_door"] is True
    assert sum(order["fee_parts"].values()) == order["delivery_fee_cents"], \
        f"拆分之和必须等于实收 —— 对不上就不叫透明:{order['fee_parts']}"
    assert "6楼无电梯送上门" in order["promo_note"], order["promo_note"]
    print("✓ 拆分快照进订单,之和等于实收,并在下单说明里写明原因")

    # 商家侧也看得到(顾客问起配送费贵时能解释)
    mine = call("GET", f"/orders/{order['order_no']}", merchant)
    assert mine["fee_parts"].get("door") == 200, mine.get("fee_parts")
    print("✓ 商家侧同样看得到拆分")

    # ---- 骑手**接单前**就看得到构成 ----
    #
    # 这是这一批最实的一条:别家骑手端只给一个总数,骑手要跑到楼下
    # 才发现是 6 楼没电梯。抢单池里就带上拆分,才谈得上判断值不值。
    call("POST", f"/orders/{order['order_no']}/pay/mock", customer)
    call("POST", f"/orders/{order['order_no']}/transition", merchant,
         {"to_status": "accepted"})
    pool = call("GET", "/riders/available-orders", rider)
    row = next((o for o in pool if o["order_no"] == order["order_no"]), None)
    assert row is not None, "订单没进抢单池,后面的断言就没意义了"
    assert row["fee_parts"].get("door") == 200, row.get("fee_parts")
    assert row["fee_part_labels"]["door"], "光给数字没用,得有中文名"
    assert sum(row["fee_parts"].values()) == row["delivery_fee_cents"], \
        f"骑手看到的拆分之和必须等于他能拿到的钱:{row['fee_parts']}"
    print("✓ 骑手抢单池里接单前可见拆分与中文名,之和等于到手配送费")

    # ---- 快照不随费率变化重算 ----
    async with SessionLocal() as db:
        await db.execute(
            text("UPDATE orders SET fee_parts = jsonb_set("
                 "fee_parts, '{base}', to_jsonb(99999)) "
                 "WHERE order_no = :n"),
            {"n": order["order_no"]})
        await db.commit()
    again = call("GET", f"/orders/{order['order_no']}", customer)
    assert again["fee_parts"]["base"] == 99999, \
        "读的是快照本身,不是拿当前费率重算 —— 重算出来的和当时收的对不上"
    print("✓ 拆分读快照而非重算(费率调了、天气关了也不会变)")

    # 收尾:这一单已经付过款,不留在库里占着。清扫任务可能已经因为
    # 「长时间无骑手」自动取消掉了 —— 那也是取消,不该让收尾动作
    # 把一条本来通过的用例判红
    call("POST", f"/orders/{order['order_no']}/transition", customer,
         {"to_status": "cancelled"}, expect_error=True)

    # ---- 自取单没有配送费,也就没有拆分 ----
    pickup = call("POST", "/orders", customer, {
        "merchant_id": DEMO_SHOP_ID,
        "items": [{"dish_id": dish["id"], "quantity": 1}],
        "pickup": True, "floor": 6, "has_elevator": False})
    assert pickup["delivery_fee_cents"] == 0 and not pickup["fee_parts"], \
        f"自取没有配送费更没有上门费:{pickup['fee_parts']}"
    call("POST", f"/orders/{pickup['order_no']}/transition", customer,
         {"to_status": "cancelled"})
    print("✓ 自取单无配送费也无拆分")

    print("\ne2e_fee_transparency 全部通过 ✅")


if __name__ == "__main__":
    asyncio.run(main())
