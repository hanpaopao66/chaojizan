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


#: 帮送禁运。**硬编码拦截,不能只写在用户协议里** ——
#: 写在协议里等于没写:没人看,出了事平台也脱不了责任。
#: 命中就拒单并说明是哪一类,让用户知道为什么而不是"提交失败"
FORBIDDEN_ITEMS = (
    ("危险化学品", ("汽油", "柴油", "酒精", "硫酸", "盐酸", "农药", "化学")),
    ("易燃易爆", ("烟花", "爆竹", "打火机", "气罐", "煤气", "液化气", "炸")),
    ("活体动物", ("活体", "宠物", "猫", "狗", "鸟", "鱼苗", "活鸡", "活鸭")),
    ("现金与贵重金属", ("现金", "钞票", "金条", "黄金", "首饰", "珠宝")),
    ("管制刀具", ("管制刀", "匕首", "弹簧刀", "枪")),
    ("药品", ("处方药", "药品", "针剂", "疫苗")),
)


def forbidden_reason(text: str) -> str | None:
    """物品描述命中禁运清单就返回中文原因,否则 None。

    只做关键词粗筛 —— 它拦不住存心绕的人,但拦得住"随手写了汽油"
    这类真实情况,而后者才是多数。真要严格得靠人工核验,
    那是另一条成本曲线,现在这个量级不划算。
    """
    lowered = (text or "").lower()
    for label, words in FORBIDDEN_ITEMS:
        if any(w in lowered for w in words):
            return label
    return None


async def service_merchant(db, city: str):
    """本城的跑腿服务主体(没有就建一个)。

    它是一个 `biz_type='errand'` 的 Merchant —— 存在的唯一理由是让
    跑腿单能挂在 `Order.merchant_id` 这个非空外键上,而不必把上百处
    依赖它的代码全部改成判空(见 docs/DESIGN-errand.md)。

    **它不会出现在任何外卖界面里**:列表、搜索、首页推荐全都是
    `biz_type == "food"` 的白名单写法。

    owner 挂平台管理员:这个主体没有真实经营者,也不产生商家入账
    (结算里对跑腿单不生成 MerchantEarning),所以 owner 只是个外键占位。
    """
    from sqlalchemy import select

    from ..models import Merchant, MerchantStatus, User, UserRole

    city = city or ""
    shop = await db.scalar(
        select(Merchant).where(Merchant.biz_type == "errand",
                               Merchant.city == city)
        .order_by(Merchant.id).limit(1))
    if shop is not None:
        return shop
    owner = await db.scalar(
        select(User).where(User.role == UserRole.admin)
        .order_by(User.id).limit(1))
    if owner is None:
        raise RuntimeError("没有管理员账号,无法创建跑腿服务主体")
    shop = Merchant(
        owner_id=owner.id,
        name=f"{city or '本城'}跑腿服务",
        biz_type="errand",
        city=city,
        address="",
        lat=0.0, lng=0.0,
        status=MerchantStatus.approved,
        is_open=True,
    )
    db.add(shop)
    await db.flush()
    return shop


# ---------- 帮买:垫资与差额 ----------

#: 实付超预估的浮动上限:20% 且不超过 20 元。
#: 上限内平台先结给骑手、再向用户补收;超出必须骑手发起确认、用户同意。
#:
#: ⚠️ 这两个数不是随便定的。**骑手不该被迫做"超了一点点先垫上"这个判断题**
#: —— 那看起来贴心,实际是把平台的规则缺失转嫁给收入最低的那个人。
#: 有了明确上限,他在店里只需要看一眼:超了就点确认,不超就直接买。
RAISE_RATIO = 0.20
RAISE_MAX_CENTS = 2000


def raise_limit_cents(budget_cents: int) -> int:
    """这一单允许骑手自行超支多少(不用问用户)。"""
    return min(int(budget_cents * RAISE_RATIO), RAISE_MAX_CENTS)


def settle_goods(budget_cents: int, actual_cents: int) -> dict:
    """帮买的商品款结算。

    返回 {rider_goods, refund_cents, extra_charge_cents, note}:
    - `rider_goods`:结给骑手的商品款(=实付,平台一分不抽 ——
      那是他替用户垫付的钱,对它抽成没有任何道理);
    - `refund_cents`:实付少于预估时退给用户的差额;
    - `extra_charge_cents`:实付多于预估时向用户补收的金额。
    """
    diff = actual_cents - budget_cents
    if diff <= 0:
        return {"rider_goods": actual_cents, "refund_cents": -diff,
                "extra_charge_cents": 0,
                "note": (f"实付比预估少 {-diff / 100:.2f} 元,已原路退回"
                         if diff else "实付与预估一致")}
    return {"rider_goods": actual_cents, "refund_cents": 0,
            "extra_charge_cents": diff,
            "note": f"实付比预估多 {diff / 100:.2f} 元,需向你补收"}


def unavailable_fee_cents(fee_parts: dict) -> int:
    """买不到时收多少跑腿费。

    **只收到店那段的距离费**(base),夜间/天气/上门难度都不收 ——
    上门那一段根本没发生。

    骑手确实跑了这一趟不该白跑,用户也确实没拿到东西;
    折中方案的前提是**在下单页提前说清楚**,提前说了就不叫坑。
    """
    return int((fee_parts or {}).get("base", 0))
