"""骑手现场难度反馈:定价、地址规整、共识判定(#301)。

## 这个模块存在的理由

配送费里的上门难度费取决于 `floor` / `has_elevator`,而这两个字段是
**用户在地址簿里自己填的**:大多数人不填(那就是 0,骑手爬六层白爬),
填了也没人核实。「要步行进小区 300 米」「车进不去只能推行」
「门禁要等保安」这些情况**根本没有字段**。

平台不可能知道每栋楼的情况。**跑过的人知道。**

## 群众至上,尊重劳动者 —— 落到代码上是什么

不是一句口号,是几条能被测试挡住的规则:

1. **反馈不得有任何代价。** 不影响评分、不影响派单权重、不影响接单资格。
   一旦反馈有代价,骑手就不说了,机制立刻死掉;
2. **难度只会变准,不会被"摊平"。** 严禁"这个地址大家都说难,
   说明难是常态,所以不算难"——那是 `clamp_eta_minutes` 挡的
   同一种自我收紧,换了个地方;
3. **补的钱由平台出。** 不向用户追收(顾客会觉得被坑,更要命的是
   会让骑手不敢反馈 —— 他知道这钱是从顾客身上要的),
   也不向商家追收(与商家无关);
4. **只加不减。** 没有任何一条路径允许"骑手反馈之后钱变少了";
5. **金额公开。** 每一项是什么、加多少钱,骑手端和用户端都查得到。
   **不给出金额的补贴等于施舍。**

## 防刷不靠给人打分

`(rider_id, addr_key)` 唯一约束 + 单笔上限 + 审计告警。
**不做骑手信用分** —— 沉淀的是地址的属性,不是人的行为。
"""
from __future__ import annotations

import math

#: 难度项 → (给用户看的名字, 说明)。
#:
#: 措辞是给**第一次看到它的人**写的:骑手在楼道里几秒钟要勾完,
#: 顾客在结算页要一眼看懂自己为什么多付了两块钱。
HARDSHIP_LABELS: dict[str, tuple[str, str]] = {
    "no_elevator": ("无电梯爬楼", "楼里没有电梯,要背着餐爬上去"),
    "walk_in": ("步行进小区", "车进不去或停在外面,要走一段才到楼下"),
    "no_vehicle": ("车辆禁入", "电动车进不去,只能推行或步行搬运"),
    "gate_hard": ("门禁难进", "要等保安、找业主或者登记才进得去"),
    "other": ("其他情况", "骑手补充说明"),
}

#: 每一项补多少钱(分)。**写死在代码里并公开**,不做后台可调的黑箱。
#:
#: 口径和 `pricing.door_fee_cents` 保持一致:
#: 爬楼按超出 4 楼的层数每层 ¥1、封顶 ¥5(等电梯的时间已经在 ETA 里
#: 补过,所以有电梯不算);步行进小区按每 100 米 ¥0.5、封顶 ¥3。
#:
#: 定价原则是「够用就好,不追求精确」—— 精确要举证,而举证的成本
#: 落在马路上跑车的人身上,那就又回到了我们要躲开的坑里。
NO_ELEVATOR_FREE_FLOOR = 4
NO_ELEVATOR_PER_FLOOR_CENTS = 100
NO_ELEVATOR_MAX_CENTS = 500

WALK_IN_FREE_M = 100
WALK_IN_PER_100M_CENTS = 50
WALK_IN_MAX_CENTS = 300

NO_VEHICLE_CENTS = 200
GATE_HARD_CENTS = 100
OTHER_CENTS = 0          # 说不清的情况不自动给钱,进人工看

#: 单笔补贴上限(分)。防滥用,**不是防骑手**。
#:
#: 所以它必须**高于每一项都封顶时的合计**:
#: 爬楼 500 + 步行 300 + 车禁入 200 + 门禁 100 = 1100。
#:
#: 一开始拍了个 800,看着"够用了" —— 实际会把最难的那一单砍掉 300,
#: 也就是**最该被补偿的人反而被砍**。这个上限的作用是挡住异常输入,
#: 不是给正常情况设天花板;每一项自己已经各有封顶了。
MAX_COMP_CENTS = 1100

#: 一个地址攒够几条**一致**反馈才转正(此后新订单直接按真实难度计价)。
#:
#: 2 条是权衡:1 条太容易被一次误报永久涨价,3 条在单量不大的城市
#: 可能几个月都攒不齐 —— 而攒不齐就等于这个机制不存在。
CONSENSUS_MIN = 2


def addr_key(lat: float, lng: float, floor: int | None) -> str:
    """地址的规整键:收货点 111m 网格 + 楼层。

    **不能用地址原文。** 同一栋楼的写法千奇百怪("XX小区3栋602"、
    "XX小区3号楼6楼2号"、"XX小区3-602"),按原文攒永远攒不够两条,
    机制就永远不转正。

    带上楼层是因为难度本来就是分层的:同一栋楼 2 楼和 12 楼不是一回事。
    没填楼层的按 0 归一类 —— 那类里攒出来的共识只对"这栋楼周边"
    成立(比如车进不去、门禁难),不会误伤具体楼层。
    """
    return f"{int(lat / 0.001)}:{int(lng / 0.001)}:{floor or 0}"


def comp_cents(kinds: list[str], floors: int | None,
               walk_m: int | None) -> int:
    """这一单该补多少(分)。

    ⚠️ **只加不减**,而且封顶。任何让这个函数返回负数或者
    "因为反馈多了所以少给"的改动,都违反了模块开头那五条。
    """
    total = 0
    if "no_elevator" in kinds and floors:
        over = floors - NO_ELEVATOR_FREE_FLOOR
        if over > 0:
            total += min(over * NO_ELEVATOR_PER_FLOOR_CENTS,
                         NO_ELEVATOR_MAX_CENTS)
    if "walk_in" in kinds and walk_m:
        over_m = walk_m - WALK_IN_FREE_M
        if over_m > 0:
            total += min(math.ceil(over_m / 100) * WALK_IN_PER_100M_CENTS,
                         WALK_IN_MAX_CENTS)
    if "no_vehicle" in kinds:
        total += NO_VEHICLE_CENTS
    if "gate_hard" in kinds:
        total += GATE_HARD_CENTS
    return min(total, MAX_COMP_CENTS)


def explain(kinds: list[str], floors: int | None,
            walk_m: int | None) -> list[str]:
    """把这笔钱**摊开**给人看,一项一行。

    「难度补贴 ¥3」说不清是怎么来的。骑手要能核对,顾客要能看懂
    自己为什么多付 —— 说不清来历的钱,给多少都不叫透明。
    """
    out: list[str] = []
    if "no_elevator" in kinds and floors:
        over = max(0, floors - NO_ELEVATOR_FREE_FLOOR)
        if over > 0:
            amt = min(over * NO_ELEVATOR_PER_FLOOR_CENTS,
                      NO_ELEVATOR_MAX_CENTS)
            out.append(f"无电梯爬到 {floors} 楼:超出 {over} 层 "
                       f"+¥{amt / 100:g}")
    if "walk_in" in kinds and walk_m:
        over_m = max(0, walk_m - WALK_IN_FREE_M)
        if over_m > 0:
            amt = min(math.ceil(over_m / 100) * WALK_IN_PER_100M_CENTS,
                      WALK_IN_MAX_CENTS)
            out.append(f"步行进小区约 {walk_m} 米 +¥{amt / 100:g}")
    if "no_vehicle" in kinds:
        out.append(f"车辆禁入,只能推行 +¥{NO_VEHICLE_CENTS / 100:g}")
    if "gate_hard" in kinds:
        out.append(f"门禁难进 +¥{GATE_HARD_CENTS / 100:g}")
    if "other" in kinds and not out:
        out.append("其他情况:已记录,平台人工看")
    return out


def consensus(rows: list[dict]) -> dict:
    """一个地址上多条反馈的共识。

    返回 `{"kinds": [...], "floors": int|None, "walk_m": int|None,
    "samples": int}`;`kinds` 只收**被至少 CONSENSUS_MIN 个人说过**的项。

    ## 误报要能自愈

    一条说"无电梯",后来三个人都说"有电梯"(即没勾这一项)——
    这一项的计数不再增长,而**新订单读的是共识而不是历史条数**,
    所以它自然退回去。一次误报不该让一个地址永久涨价。

    ## 取值取中位数,不取最大值

    爬楼层数、步行米数各人记的不一样。取最大值等于让最夸张的那次
    定价,取中位数是**多数人的实际体验** —— 而这正是"群众至上"
    在这里的字面意思。
    """
    if not rows:
        return {"kinds": [], "floors": None, "walk_m": None, "samples": 0}
    # 按**不同骑手**去重:同一个人在同一个地址跑十单,说的还是同一件事,
    # 不该因此就算十个人都这么说。防刷在这里,不在数据库约束里 ——
    # 每一单的现场情况该留档(今天车能进、明天施工进不去是两条事实),
    # 判定谁算数是业务逻辑的事。
    by_rider: dict[str, set[int]] = {}
    for r in rows:
        rid = r.get("rider_id")
        for k in set(r.get("kinds") or []):
            by_rider.setdefault(k, set()).add(rid)
    kinds = sorted(k for k, ids in by_rider.items()
                   if len(ids) >= CONSENSUS_MIN)

    def _median(vals: list[int]) -> int | None:
        vals = sorted(v for v in vals if v)
        if not vals:
            return None
        return vals[len(vals) // 2]

    return {
        "kinds": kinds,
        "floors": _median([r.get("floors") for r in rows
                           if "no_elevator" in (r.get("kinds") or [])]),
        "walk_m": _median([r.get("walk_m") for r in rows
                           if "walk_in" in (r.get("kinds") or [])]),
        # 样本数报的是**有多少个人说过**,不是多少条记录 ——
        # 「3 个骑手反馈过」和「1 个骑手反馈了 3 次」是两回事
        "samples": len({r.get("rider_id") for r in rows}),
    }


async def address_consensus(db, lat: float, lng: float,
                            floor: int | None) -> dict:
    """查一个地址的难度共识(#301)。没有反馈或没到门槛就返回空。

    下单和配送费预览都读这个 —— 用户下单前就看得到「这个地址骑手
    反馈过:无电梯 6 楼」,可以改选送到楼下省这笔钱;骑手接单前也
    看得到,不用骑到楼下才发现。
    """
    from sqlalchemy import select

    from ..models import RiderHardship

    key = addr_key(lat, lng, floor)
    rows = (await db.scalars(
        select(RiderHardship).where(RiderHardship.addr_key == key))).all()
    return consensus([
        {"kinds": r.kinds or [], "floors": r.floors, "walk_m": r.walk_m,
         "rider_id": r.rider_id}
        for r in rows
    ])
