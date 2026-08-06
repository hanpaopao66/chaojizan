"""送达段停留时长:从「到收货点」到「点送达」的那几分钟。

## 这几分钟里发生了什么

找门牌、等门禁、等电梯、爬楼、打电话让人下来。它是"场景难度"
唯一可测量的部分 —— 校园/写字楼/医院之所以难,难就难在这里。

## 为什么按坐标网格 + 楼层段聚合,不按地址

同一栋楼十个人能写出十种地址("XX路8号1单元""XX路八号一单元"
"XX大厦A座")。按字符串聚合,永远攒不出一个有样本量的点位,
而没有样本量的分位数比没有更糟 —— 它看起来像个数,实际是噪音。

网格边长取 ~110m(0.001 度纬度约 111m)。再细会把同一栋楼的两个单元
分到不同格子里,再粗会把马路对面的老小区和新写字楼混成一格。

楼层分段而不是逐层:1-3 / 4-8 / 9-15 / 16+。逐层的话每个键的样本
被切得太碎;分段既保留"高层更慢"这个真实差异,又攒得起数。
不知道楼层(顾客没填)单独一段 —— **不猜**,猜错就是拿别人的数据
给这一单补时。

## 谁来用这份数据

- #182 ETA 补时:样本够了才生效,而且只放宽不收紧;
- 骑手端展示"这个点位历史平均多久";
- **不用来考核任何人**。一个点位慢,是这个点位的事,
  不是那天送这单的骑手的事。
"""
from sqlalchemy import Float, cast, func, select

#: 网格边长(度)。0.001 度纬度 ≈ 111m
GRID = 0.001

#: 楼层分段的上界(含)。最后一段是 16 层以上
FLOOR_BANDS = ((3, "1-3"), (8, "4-8"), (15, "9-15"))

#: 少于这个样本数不给分位数。拿 3 单算出来的数去补时,
#: 补错的概率比不补还高 —— 而错的补时会让 ETA 变成假承诺
MIN_SAMPLE = 20


def floor_band(floor: int | None) -> str:
    """楼层段。没填就是 "?" —— **不猜**,猜错等于拿别人的数据补这一单。"""
    if not floor or floor < 1:
        return "?"
    for upper, label in FLOOR_BANDS:
        if floor <= upper:
            return label
    return "16+"


def drop_key(lat: float | None, lng: float | None,
             floor: int | None) -> str | None:
    """聚合键:网格 + 楼层段。坐标缺失返回 None(这一单不进统计)。"""
    if lat is None or lng is None:
        return None
    gy = int(lat / GRID)
    gx = int(lng / GRID)
    return f"{gy}:{gx}:{floor_band(floor)}"


async def stats_for(db, keys) -> dict[str, dict]:
    """一批聚合键的送达段耗时统计。**批量取** ——
    逐个查会把一次抢单变成几十次往返(和 prep_time 同一个教训)。

    返回 {key: {"p75_minutes": float|None, "sample": int}}。
    样本不足时 p75_minutes 为 None,而不是给一个凑合的数:
    调用方必须能区分"这里确实快"和"我们还不知道"。
    """
    from ..models import Order

    keys = [k for k in set(keys) if k]
    if not keys:
        return {}
    rows = (await db.execute(
        select(Order.drop_key,
               func.count(Order.id),
               func.percentile_cont(0.75).within_group(
                   cast(Order.drop_minutes, Float)))
        .where(Order.drop_key.in_(keys), Order.drop_minutes.is_not(None))
        .group_by(Order.drop_key))).all()
    out: dict[str, dict] = {}
    for key, sample, p75 in rows:
        out[key] = {
            "sample": int(sample),
            "p75_minutes": (round(float(p75), 1)
                            if sample >= MIN_SAMPLE and p75 is not None
                            else None),
        }
    for key in keys:
        out.setdefault(key, {"sample": 0, "p75_minutes": None})
    return out
