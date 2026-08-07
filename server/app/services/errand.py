"""跑腿(帮送 / 帮买):取件点访问器与服务费口径。

结构决策见 docs/DESIGN-errand.md,这里只记两句最要紧的:

## 为什么不把 Order.merchant_id 改成可空

跑腿单确实没有商家,但 `merchant_id` 是 NOT NULL 且有 106 处代码依赖它。
改可空要逐处判空,而**漏判一处不会立刻报错** —— 它会在某条冷路径上
悄悄算错一笔钱。所以跑腿单挂到本城一个 `biz_type='errand'` 的服务主体上,
非空约束不动。

`biz_type` 在代码里是白名单用法(到处是 `== "food"`,不是 `!= "hotel"`),
所以这个主体天然不会出现在外卖列表和搜索里 —— 排除机制已经存在,
不用我们自己新写一堆 `if not errand`。

## 取件点为什么在订单上而不在主体上

外卖的取件点是固定的(那家店),跑腿的取件点是用户当场填的,每单都不同。
所以订单自带 pickup_*,读的时候统一走 `pickup_point()`。
"""
from dataclasses import dataclass

#: 订单类型。food 是默认值,存量订单迁移后全是它
KIND_FOOD = "food"
KIND_ERRAND_SEND = "errand_send"   # 帮送:东西是用户自己的,A 点取 B 点送
KIND_ERRAND_BUY = "errand_buy"     # 帮买:骑手去买,用户预付商品款给平台

ERRAND_KINDS = (KIND_ERRAND_SEND, KIND_ERRAND_BUY)

KIND_LABELS = {
    KIND_FOOD: "外卖",
    KIND_ERRAND_SEND: "帮送",
    KIND_ERRAND_BUY: "帮买",
}


def is_errand(order) -> bool:
    return getattr(order, "order_kind", KIND_FOOD) in ERRAND_KINDS


@dataclass(frozen=True)
class PickupPoint:
    """骑手要去哪取。"""
    name: str
    address: str
    lat: float | None
    lng: float | None


def pickup_point(order, merchant) -> PickupPoint:
    """外卖 = 商家位置;跑腿 = 订单自带的取件点。

    抢单池、地图、导航、顺路计算全部走这里,不各自读 `merchant.lat/lng` ——
    各读各的话,跑腿单在某个页面上会把骑手导到那个虚拟服务主体的坐标去。

    跑腿单缺坐标时回 None 而不是退回商家坐标:退回去等于给一个**错的**
    取件点,骑手照着导航跑到别处;给 None,客户端至少知道自己没坐标。
    """
    if is_errand(order):
        return PickupPoint(
            name=KIND_LABELS.get(order.order_kind, "跑腿"),
            address=order.pickup_address or "",
            lat=order.pickup_lat,
            lng=order.pickup_lng,
        )
    if merchant is None:
        return PickupPoint(name="", address="", lat=None, lng=None)
    return PickupPoint(name=merchant.name, address=merchant.address,
                       lat=merchant.lat, lng=merchant.lng)


def service_fee_cents(errand_fee_cents: int) -> int:
    """平台从跑腿费里收的服务费。

    ## 为什么跑腿收、外卖不收

    外卖的配送费**一分不抽**,平台收入来自商家佣金。跑腿没有商家,
    2% 是平台在这条业务上唯一的收入。两个口径同时存在,
    **界面上必须讲清楚**,否则就是"你不是说配送费不抽吗"。

    与团购券同口径(核销才收 2%),并且在账单上单独列出来,不藏在总价里。
    """
    from ..config import settings

    return round(errand_fee_cents * settings.errand_service_fee_bps / 10000)
