"""每日账务自检——账本的守夜人。

核对的恒等式(近 30 天):
  1. 每笔完成订单必须有商家入账,且 net == food - commission,**且收款方是本店**
  2. 每笔有骑手的完成订单必须有骑手入账,且金额 == 骑手应得(见 _rider_due:
     配送费 + 小费 + 平台承担的等餐补偿 − 跑腿服务费;外卖配送费平台一分不抽),
     **且收款人是接单的那个骑手**
  3. 非取消订单:total == food + delivery
  4. 任何骑手的可提现余额不得为负;商家余额同理(按店主整户核,口径直接复用钱包)
  5. 每笔订单的 refund_cents 必须等于 refunds 流水之和(失败流水不算 → 自动暴露)
  5b. 退款不得超过用户实付 —— 判据是"剩余应付不许为负"(见该条的长注释:
      total_cents 是剩余应付不是累计实付,直接比 refund_cents 会造出几百盏假红灯)
  5-券/5-住宿(规则 14/15):同一条恒等式在另外两条业务线上的版本。
      规则 5 按 `Refund.order_id` 取数,而券和住宿的流水那一列是 NULL
      (它们不属于任何外卖订单),结构上落在规则 5 的视野之外 ——
      这两格以前是空的:券和住宿的"退款"只改了个状态字段,一条流水都没写。
      住宿那条核的是**能原路退回去**的部分,不是 refund_cents:
      「到店无房」的退款额含商家违约金,本来就超过用户实付(详见规则 15)
  6. 售后退款(完成单退餐费,配送费已履约不退)的已结算订单必须有商家冲账负数行
  7. 全局恒等,分两侧:菜品侧 Σ应收 == Σ商家净额+Σ佣金(售后冲账单剔除);
     配送侧 Σ配送费 == Σ骑手入账(售后单保留 —— 配送费 100% 归骑手的账面铁证)

**收款方那两句是最便宜的一类覆盖。** 上面每条恒等式都按 order_id join,
金额两边都对、钱记到另一家分店/另一个骑手头上时,它们全绿。
连锁店主名下十家分店,记错一家谁都看不出来 —— 两行 `==` 就把这一整类堵死。

另有几条不是恒等式、但同样是"账面与真实资金对不上"的检查:

- **分账台账不许长期挂着**:pending 超时未走通、以及已放弃的 failed,
  都意味着台账写着这笔钱该怎么分、实际一分没动(分账渠道尚未接入,
  桩不再伪造 success,挂起量就靠这条露出来);
- **退款不许卡在 requested**:发起了、渠道没回,钱既没退给用户也没留在账上;
- **非完成订单不许挂来路不明的入账行**:上面 1/6/7 全部从 completed 出发遍历,
  6.5 又只看非外卖单,于是"取消单上的商家入账"整个落在视野之外 ——
  而无骑手兜底取消恰恰会往那儿写赔付行(auto_flow);
- **住宿 PAID 不许长期挂着**:钱已收、商家没确认,而住宿清扫对 PAID
  没有任何超时兜底,规则 9 又把这个状态整个排除;
- **到店无房的违约金不许无声挂着**:商家余额当场扣了,用户那一半却
  超过他的实付额、退款通道退不了,得等「转账到零钱」接入 ——
  这是一笔真实负债,聚合成一条报出来(规则 15 末尾)。

**时间窗取的列必须是"钱落定的那一刻"**,不是下单那一刻:券按 redeemed_at
(有效期最长 365 天,按 created_at 取窗的话第 31 天以后核销的券一生都不会被看到)、
住宿离店按 completed_at、住宿取消按 cancelled_at。口径与对外账本
(services/ledger.py)逐列对齐 —— 公示的数和自检的数必须是同一批流水。

不平 → 写 audit_alerts + logger.error,管理后台首页红条展示。
backfill_missing_earnings() 可对缺账的历史订单补记账(自愈,幂等)。
"""
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_
from sqlalchemy import func as sa_func
from sqlalchemy import select
from sqlalchemy.orm import aliased

from ..db import SessionLocal
from ..models import (
    AuditAlert,
    EarningKind,
    MerchantEarning,
    Order,
    Refund,
    RefundStatus,
    RiderEarning,
    User,
    UserRole,
    Withdrawal,
    WithdrawalStatus,
)
from ..state_machine import OrderStatus
from .settlement import settle_order

logger = logging.getLogger("superz.audit")

WINDOW_DAYS = 30

#: 退款发起后多久还停在 requested 就算"挂住了"。与分账的 STUCK_HOURS 同量级:
#: 模拟通道即时成功、微信正常也是秒级,超过这个数只能是渠道没回执。
REFUND_STUCK_HOURS = 6

#: 住宿已支付后多久商家还不确认/不拒单就算"钱压着"。比退款宽松得多 ——
#: 商家半夜收到的单第二天早上处理是常态,不能因此天天报红。
STAY_PAID_STUCK_HOURS = 24

#: 无骑手兜底取消时给商家的餐损赔付行的 note 前缀。
#: **三处共用同一个前缀**:auto_flow 写入、这里判定"是合规赔付不是野账"、
#: routers/transparency.py 的 /funds 按它公示赔付支出。
#: 各写各的字符串的话,改一处就会让另外两处静默失效(一个漏报、一个少算)。
NO_RIDER_COMP_NOTE = "无骑手接单取消,平台赔付餐损"


def _rider_due(order) -> int:
    """骑手这一单应得多少。

    **不是**"顾客付的配送费" —— 两者在三种情况下不相等,
    漏掉任何一种,逐单检查和全局恒等都会长期报红:

    - **等餐补偿**:平台承担、不进 `delivery_fee_cents`
      (顾客不该为商家出餐慢买单),但确实进了骑手入账;
    - **跑腿服务费**:跑腿没有商家,平台从跑腿费里收 2%,骑手拿 98%;
    - **外卖配送费**:平台一分不抽,不减。

    逐单检查与全局恒等**必须共用这一个函数**。两处各写一遍的话,
    加一笔新钱时只改了一处,另一处就成了长期红灯 ——
    而长期红灯的下场是所有人习惯"红了也没关系"。
    """
    from .errand import is_errand, service_fee_cents

    from .errand import KIND_ERRAND_BUY

    due = order.delivery_fee_cents + order.tip_cents
    due += (order.fee_parts or {}).get("wait", 0)
    if is_errand(order):
        due -= service_fee_cents(order.delivery_fee_cents)
    # 帮买的商品款按小票实付结给骑手,平台一分不抽 ——
    # 那是他替用户垫付的钱
    if order.order_kind == KIND_ERRAND_BUY:
        due += (order.goods_actual_cents
                if order.goods_actual_cents is not None
                else order.goods_budget_cents)
    return due


async def _reversal_due_ids(db, order_ids) -> set[int]:
    """该冲账的订单 id —— 规则 6 与历史补录**共用这一套口径**。

    ## 判据不能是「累计退款 ≥ 剩余餐费」

    原来这么写:`refund_cents >= total_cents - 配送费`。这两个数根本不是
    一个口径,规则 5b 的长注释里已经把这个坑写过一遍,这里又踩了一次:
    `refund_cents` 是**累计**已退(只增不减),`total_cents` 是**剩余**
    应付(缺货退款、改地址退差价都会把它同步下调)。拿累计值去比剩余值,
    相等只是巧合,不是证据。

        下单 2 份×4500,满减 2000 → 实付 7000+配送
        缺货退 1 份(摊掉满减退 3500)→ 剩余应付 3500+配送
        送达完成 → 商家入账按**已扣减后**的 food 口径记 3500,佣金 140

    累计退款 3500 == 剩余餐费 3500,旧判据成立 —— 可这单从头到尾没有售后。
    退掉的那一份在结算时**根本没算进商家应收**
    (settlement.credit_merchant_for_order 读的是退款后的 food/discount),
    再冲一次账等于凭空从商家身上扣走 3360 分。而缺货退款只能发生在
    待接单/制作中(routers/orders.refund_item 的状态闸),**永远早于结算**。

    这不只是一盏假红灯:backfill_legacy_refund_records 拿同一个判据
    真的去执行 reverse_merchant_earning,照旧口径跑一次就会把这种单的
    商家净额抹平 —— 假红灯背后跟着的是真扣钱。

    ## 正确的判据:钱是**什么时候**退的

    结算发生在订单完成那一刻。完成**之前**退的钱已经体现在入账金额里,
    没有可冲的;完成**之后**退的钱,商家已经收进账了,必须冲回。
    两个信号取并集,不做单点依赖:

    1. `after_sales` 里有已受理的售后 —— 完成后退款的正规入口。
       after_sales.accept、admin 的配送异常仲裁/骑手责任/食安投诉,
       每一条退款都会写这张表并落 fault,这才是规则 6 名字里那个"售后"。
    2. 退款流水时间 ≥ 订单完成时刻 —— 任何绕开 after_sales 的退款路径
       也照抓不误,规则不吊死在一张表上。完成时刻缺失的老单
       (库里约两成)退回用入账行时间兜底。

    fault 判 rider/platform 的先行赔付单除外:平台垫的钱,商家无责,
    净额保留不冲账(admin.py 食安那段管这个叫「规则 6 豁免口径」)。
    """
    from ..models import AfterSale, AfterSaleStatus

    rows = (await db.scalars(
        select(AfterSale).where(AfterSale.order_id.in_(order_ids)))).all()
    exempt = {a.order_id for a in rows if a.fault in ("rider", "platform")}
    due = {a.order_id for a in rows if a.status == AfterSaleStatus.accepted}
    settled_at = sa_func.coalesce(Order.completed_at, MerchantEarning.created_at)
    due |= set(await db.scalars(
        select(Refund.order_id)
        .join(Order, Order.id == Refund.order_id)
        .join(MerchantEarning,
              and_(MerchantEarning.order_id == Refund.order_id,
                   MerchantEarning.kind == EarningKind.earning))
        .where(Refund.order_id.in_(order_ids),
               Refund.status != RefundStatus.failed,
               Refund.created_at >= settled_at)))
    return due - exempt


async def _refund_sums(db, biz_type: str, id_subquery) -> dict[int, int]:
    """{业务 id: 真的退出去了多少分}。失败流水不算 —— 钱没动就不能算已退。

    **一条 GROUP BY,不是每笔业务一次查询。** 规则 14/15 要核的是"近 30 天
    每一笔退款",开发库里已经是上千笔,逐笔发一次 SQL 就是上千次往返;
    而这套自检的全部意义是"差一分钱系统报警",它必须随单量增长还能跑完
    (规则 1 上面那段长注释是同一件事的另一个版本:参数上限 32767)。

    `id_subquery` 传子查询而不是 id 列表,同样是那条纪律。
    """
    rows = await db.execute(
        select(Refund.biz_id, sa_func.sum(Refund.amount_cents))
        .where(Refund.biz_type == biz_type,
               Refund.biz_id.in_(id_subquery),
               Refund.status != RefundStatus.failed)
        .group_by(Refund.biz_id))
    return {biz_id: total for biz_id, total in rows}


async def run_audit() -> list[dict]:
    """执行全部核对,返回问题列表并写入告警表。"""
    problems: list[dict] = []
    since = datetime.now(timezone.utc) - timedelta(days=WINDOW_DAYS)

    async with SessionLocal() as db:
        # 1+2) 完成订单 vs 账本
        completed = (
            await db.scalars(
                select(Order).where(
                    Order.status == OrderStatus.COMPLETED,
                    Order.created_at >= since,
                )
            )
        ).all()
        # **用子查询,不要把 id 列表逐个绑成参数。**
        #
        # `in_([...])` 会给每个 id 绑一个占位符,而 PostgreSQL 的单条语句
        # 参数上限是 32767 —— 一个月完成单超过这个数,每日核账就直接抛
        # `the number of query arguments cannot exceed 32767` 挂掉。
        #
        # 挂掉的后果不是"少一条告警",是**整个核账不再运行** ——
        # 而这套东西的全部意义就是"差一分钱系统报警"。
        # 它必须随单量增长而继续能跑,不能到某个量级就自己停了。
        completed_ids = select(Order.id).where(
            Order.status == OrderStatus.COMPLETED,
            Order.created_at >= since,
        )
        m_earnings = {
            e.order_id: e
            for e in await db.scalars(
                select(MerchantEarning).where(
                    MerchantEarning.order_id.in_(completed_ids),
                    MerchantEarning.kind == EarningKind.earning,
                )
            )
        }
        m_reversals = {
            e.order_id
            for e in await db.scalars(
                select(MerchantEarning).where(
                    MerchantEarning.order_id.in_(completed_ids),
                    MerchantEarning.kind == EarningKind.reversal,
                )
            )
        }
        r_earnings = {
            e.order_id: e
            for e in await db.scalars(
                select(RiderEarning).where(
                    RiderEarning.order_id.in_(completed_ids),
                    RiderEarning.kind == EarningKind.earning,
                )
            )
        }
        def order_gross(o: Order) -> int:
            """商家应收口径 = 菜品 + 打包费 - 商家满减;
            自配送单配送费归商家,一并计入(与结算同口径)。"""
            gross = o.food_cents + o.packing_fee_cents - o.discount_cents
            if o.self_delivery:
                gross += o.delivery_fee_cents
            return gross

        from .errand import is_errand, service_fee_cents

        # 平台认赔过的单(帮买售后受理时 fault="platform")。
        # AfterSale/AfterSaleStatus 在这个函数里是局部 import 的(见上面
        # 冲账那段),那个 import 在别的作用域,这里要自己拿一次
        from ..models import AfterSale as _AfterSale
        from ..models import AfterSaleStatus as _AfterSaleStatus
        # 这些单的恒等式必然不平 —— 平台吃下的商品款没有对应账目行。
        absorbed_rows = (await db.scalars(
            select(_AfterSale.order_id)
            .where(_AfterSale.order_id.in_([o.id for o in completed] or [0]),
                   _AfterSale.status == _AfterSaleStatus.accepted,
                   _AfterSale.fault == "platform"))).all()
        platform_absorbed = set(absorbed_rows)
        absorbed_n = 0
        absorbed_cents = 0

        for order in completed:
            # 收款人校验:金额对、人错也是错账。
            #
            # 下面所有恒等式都按 order_id join,两边金额一致就通过 ——
            # 于是"钱记到另一个骑手头上"是一个金额永远平、审计永远绿的错误。
            # 跑腿单也要查,所以放在 is_errand 分支之前。
            re = r_earnings.get(order.id)
            if (order.rider_id is not None and re is not None
                    and re.rider_id != order.rider_id):
                problems.append({
                    "check": "rider_earning_payee_mismatch",
                    "detail": f"订单 {order.order_no} 骑手入账记在骑手 "
                              f"#{re.rider_id} 名下,实际接单的是 "
                              f"#{order.rider_id} —— 钱发错人,金额恒等式看不出来",
                })
            # 跑腿单没有商家入账(见 settlement),它有自己的恒等式:
            # 用户实付 == 骑手入账 + 平台服务费
            if is_errand(order):
                fee = service_fee_cents(order.delivery_fee_cents)
                if re is not None and order.rider_id is not None:
                    # 帮买按小票实付结算,和预估不一致时差额已原路退/补收,
                    # 所以拿 refund_cents 校平
                    lhs = re.amount_cents + fee + order.refund_cents
                    if lhs != order.total_cents:
                        # 平台认赔的那些**不报警,聚合成日志**(#33 已拍板:
                        # 关灯,不是记账)。
                        #
                        # 帮买售后受理时 fault 记的是 "platform"(跑腿没有
                        # 商家,认责方就是平台自己),平台把商品款吃下来 ——
                        # 而这笔亏损在账本里**没有任何一行**,于是这条恒等式
                        # 每受理一次就亮一次,亮的还都是真事。
                        #
                        # ⚠️ **关灯不等于账平了。** 这笔钱确实流出去了,
                        # 只是没人记它。哪天要把它记上(平台侧的赔付支出行),
                        # 从这里改回来:去掉 absorbed 分支,让它照常报,
                        # 直到 settlement 那边真的写出那一行。
                        if order.id in platform_absorbed:
                            absorbed_n += 1
                            # lhs − total,不是 total − lhs:认赔的形态是
                            # 「用户退了钱(已退↑)、骑手照常拿钱」,所以
                            # 左边比实付大,差额就是**平台多掏的那部分**。
                            # 写反了这个数会变成负的,而它是这笔亏损在系统里
                            # 唯一的痕迹 —— 符号错了就会被读成"平台还赚了"
                            absorbed_cents += lhs - order.total_cents
                        else:
                            problems.append({
                                "check": "errand_identity_mismatch",
                                "detail": f"跑腿单 {order.order_no} 不平:"
                                          f"骑手入账 {re.amount_cents} + 服务费 {fee}"
                                          f" + 已退 {order.refund_cents}"
                                          f" ≠ 用户实付 {order.total_cents}",
                            })
                continue
            me = m_earnings.get(order.id)
            if me is None:
                problems.append({
                    "check": "merchant_earning_missing",
                    "detail": f"完成订单 {order.order_no} 缺商家入账",
                })
            else:
                if me.merchant_id != order.merchant_id:
                    problems.append({
                        "check": "merchant_earning_payee_mismatch",
                        "detail": f"订单 {order.order_no} 商家入账记在门店 "
                                  f"#{me.merchant_id} 名下,下单的是 "
                                  f"#{order.merchant_id} —— 连锁记错分店,"
                                  "金额恒等式看不出来",
                    })
                if me.net_cents != order_gross(order) - order.commission_cents:
                    problems.append({
                        "check": "merchant_earning_mismatch",
                        "detail": f"订单 {order.order_no} 商家净额 {me.net_cents} "
                                  f"≠ 应收 {order_gross(order)}"
                                  f"-佣金 {order.commission_cents}",
                    })
            if order.rider_id is not None:
                if re is None:
                    problems.append({
                        "check": "rider_earning_missing",
                        "detail": f"完成订单 {order.order_no} 缺骑手入账",
                    })
                elif re.amount_cents != _rider_due(order):
                    problems.append({
                        "check": "rider_earning_mismatch",
                        "detail": f"订单 {order.order_no} 骑手入账 {re.amount_cents} "
                                  f"≠ 应得 {_rider_due(order)}"
                                  f"(配送费 {order.delivery_fee_cents}"
                                  f" + 小费 {order.tip_cents}"
                                  f" + 等餐补偿 {(order.fee_parts or {}).get('wait', 0)}"
                                  f" − 跑腿服务费)",
                    })

        # 平台认赔聚合成一条日志(#33 已拍板「关灯」)。
        #
        # 走 logger 不进 problems:进 problems 就还是红灯,而这些不平**每一笔
        # 都是已知的、主动的**——平台受理帮买售后时把商品款吃下来了。
        #
        # ⚠️ 这条日志要留着,而且要带金额:**关灯之后,它是这笔亏损在系统里
        # 唯一的痕迹**。账本里仍然没有对应的行(services/settlement 没写),
        # 所以这个数不会出现在任何对外的账目上 —— 要改成记账,见上面那段注释。
        if absorbed_n:
            logger.info(
                "跑腿平台认赔 %s 笔共 %s 分:恒等式按已拍板的口径不报警。"
                "注意这笔亏损在账本里没有对应行,只有这条日志",
                absorbed_n, absorbed_cents)

        # 3) 订单金额自洽:实付 = 菜品 + 打包 - 满减 + 配送 - 平台补贴
        bad_totals = (
            await db.scalars(
                select(Order).where(
                    Order.status != OrderStatus.CANCELLED,
                    Order.created_at >= since,
                    Order.total_cents
                    != Order.food_cents + Order.packing_fee_cents
                    - Order.discount_cents + Order.delivery_fee_cents
                    + Order.tip_cents - Order.subsidy_cents,
                )
            )
        ).all()
        for order in bad_totals:
            problems.append({
                "check": "order_total_mismatch",
                "detail": f"订单 {order.order_no} 实付 {order.total_cents} ≠ "
                          f"菜品 {order.food_cents}+打包 {order.packing_fee_cents}"
                          f"-满减 {order.discount_cents}+配送 {order.delivery_fee_cents}"
                          f"-补贴 {order.subsidy_cents}",
            })

        # 4) 骑手余额不得为负
        riders = (
            await db.scalars(select(User).where(User.role == UserRole.rider))
        ).all()
        for rider in riders:
            earned = await db.scalar(
                select(sa_func.coalesce(sa_func.sum(RiderEarning.amount_cents), 0))
                .where(RiderEarning.rider_id == rider.id)
            )
            out = await db.scalar(
                select(sa_func.coalesce(sa_func.sum(Withdrawal.amount_cents), 0))
                .where(
                    Withdrawal.user_id == rider.id,
                    Withdrawal.role == "rider",
                    Withdrawal.status.notin_(
                        [WithdrawalStatus.rejected, WithdrawalStatus.failed]),
                )
            )
            if earned - out < 0:
                problems.append({
                    "check": "rider_balance_negative",
                    "detail": f"骑手 {rider.phone} 余额为负:{earned - out} 分",
                })

        # 4b) 商家余额不得为负。
        #
        # **口径直接调钱包那个函数,不在这里抄第二份。** 上面 _rider_due 的
        # 注释写着"逐单检查与全局恒等必须共用这一个函数",商家这边曾经没照做,
        # 代价是两条永不消失的假红灯:
        #   - 审计只算 外卖净额+团购净额,钱包还算了住宿净额 —— 纯住宿商家
        #     一提现,审计当场算出负数,天天报红;
        #   - 提现按 owner_id 减,而审计是**按店逐个循环**的:店主名下两家店
        #     各挣 10 万、共提 15 万,审计对每家店都算「10万−15万」,两条红灯。
        # 挣的钱按店算(merchant_id),提的钱按店主算(owner_id),
        # 那么"余额为负"这件事本身就只能按店主整户判定。
        from ..models import Merchant
        from ..routers.merchants import _merchant_wallet

        merchants = (await db.scalars(select(Merchant))).all()
        by_owner: dict[int, list] = {}
        for shop in merchants:
            by_owner.setdefault(shop.owner_id, []).append(shop)
        for owner_id, shops in by_owner.items():
            earned = 0
            out = 0
            for shop in shops:
                w = await _merchant_wallet(db, shop)
                earned += w.total_earned_cents      # 按店:外卖+团购+住宿
                # 提现按 owner_id 查,同一店主的每家店返回的都是同一个数,
                # 取一次就够(累加就会把连锁的提现重复扣 N 遍)
                out = w.pending_withdrawal_cents + w.withdrawn_cents
            if earned - out < 0:
                names = "、".join(s.name for s in shops)
                problems.append({
                    "check": "merchant_balance_negative",
                    "detail": f"店主 #{owner_id}(名下 {len(shops)} 家店:{names})"
                              f"整户余额为负:{earned - out} 分"
                              f"(累计入账 {earned},提现 {out})",
                })

        # 5) 退款一致性:订单汇总 == 逐笔流水之和(failed 不计入 → 自动暴露渠道失败)
        refunded_orders = (
            await db.scalars(
                select(Order).where(
                    Order.refund_cents > 0, Order.created_at >= since
                )
            )
        ).all()
        for order in refunded_orders:
            refunded = await db.scalar(
                select(sa_func.coalesce(sa_func.sum(Refund.amount_cents), 0)).where(
                    Refund.order_id == order.id,
                    Refund.status != RefundStatus.failed,
                )
            )
            if refunded != order.refund_cents:
                problems.append({
                    "check": "refund_mismatch",
                    "detail": f"订单 {order.order_no} 退款汇总 {order.refund_cents} "
                              f"≠ 流水之和 {refunded}(可能有渠道退款失败,需人工介入)",
                })

        # 5b) 退款上界:退出去的钱不许超过用户付进来的钱。
        #
        # **判据是 total_cents < 0,不是 refund_cents > total_cents。**
        # 这一条踩过坑,写清楚免得有人"顺手改回去":
        #
        # `total_cents` 不是"累计实付",是**剩余应付** —— 缺货退款
        # (routers/orders.py partial_refund:总额与菜品同步扣减)、
        # 改地址退配送费差价(同文件 change_address)都是退钱的同时
        # 把 total_cents 一起下调,after_sales.py 的注释写得最直白:
        # 「total_cents 在缺货部分退款时已同步扣减,此处即用户当前净付金额」。
        # 而 `refund_cents` 是**累计**值,只增不减。于是"先缺货退一半、
        # 再整单取消退剩下的"这种完全正常的单,refund_cents 天然大于
        # total_cents —— 本地库里这样的单有 400 多笔,按那个判据写就是
        # 400 多盏永不消失的假红灯,比不查还糟。
        #
        # 那怎么抓真的超退?所有退款路径的金额要么自己封顶
        # (`max(0, total - keep)` / `refund_amount = order.total_cents`),
        # 要么走"退多少就从 total 扣多少"的下调口径。**唯一能退超的方式,
        # 就是从 total 里扣掉一个比它还大的数** —— 剩余应付被扣成负数。
        # 用户不可能倒欠平台钱,total_cents < 0 就是平台净流出的铁证,
        # 而且它不依赖任何"这笔算不算下调"的判断,不会误伤。
        #
        # **这条不加任何排除条件。** 下面规则 7 遇到退超了的单是把它从恒等式里
        # 剔除(active 的过滤是 refund < total),于是超退不但不报警,
        # 还顺手把自己从全局核对里摘了出去 —— 越离谱的单越安静。
        over_refunded = (
            await db.scalars(
                select(Order).where(
                    Order.total_cents < 0,
                    Order.created_at >= since,
                )
            )
        ).all()
        for order in over_refunded:
            problems.append({
                "check": "refund_exceeds_total",
                "detail": f"订单 {order.order_no}({order.status.value})"
                          f"退款超过用户实付:剩余应付被扣成 {order.total_cents} 分,"
                          f"累计已退 {order.refund_cents} 分,平台净流出 "
                          f"{-order.total_cents} 分 —— 用户不可能倒欠钱",
            })

        # 6) 售后退款的已结算订单必须已冲账(商家净额不能白拿)。
        #    「该不该冲账」的判据见 _reversal_due_ids ——
        #    是结算之后确实往外退过钱,不是金额上的巧合
        reversal_due = await _reversal_due_ids(db, completed_ids)
        for order in completed:
            if (order.id in reversal_due
                    and order.id in m_earnings
                    and order.id not in m_reversals):
                problems.append({
                    "check": "reversal_missing",
                    "detail": f"订单 {order.order_no} 售后已退餐费但商家入账未冲账",
                })

        # 6.5) 跑腿单一分商家入账都不该有。
        #
        # 这条是补盲区的:下面菜品侧恒等把跑腿单整个剔除了(它本来就没有商家入账),
        # 于是**任何**给跑腿单记的商家入账行都落在检查视野之外 —— 无论金额多离谱。
        # 真出过一次:无骑手兜底把跑腿单当成"商家已出餐"赔了餐损,
        # merchant_id 指向的是虚拟服务主体,帮买单那笔还等于用户的商品款。
        # 剔除一类订单的同时,必须补一条"它确实没有"的检查,否则剔除就等于失明。
        # 求净额而不是逐行:已被冲账的行两两抵消,不该再报
        from .errand import KIND_FOOD
        errand_paid = (await db.execute(
            select(Order.order_no, sa_func.sum(MerchantEarning.net_cents))
            .join(MerchantEarning, MerchantEarning.order_id == Order.id)
            .where(Order.order_kind != KIND_FOOD, Order.created_at >= since)
            .group_by(Order.order_no)
            .having(sa_func.sum(MerchantEarning.net_cents) != 0))).all()
        for order_no, net in errand_paid:
            problems.append({
                "check": "errand_merchant_earning",
                "detail": f"跑腿单 {order_no} 挂了商家入账 {net} 分 —— "
                          "跑腿没有商家,这笔钱没有对应的经营者",
            })

        # 7) 全局恒等(完成且未全退的订单,分两条核):
        #    菜品侧:Σ菜品金额 == Σ商家净额 + Σ平台佣金(售后冲账单两侧同时剔除:
        #           钱已退用户,商家/平台谁都不该再挂账)
        #    配送侧:Σ配送费(有骑手的单) == Σ骑手入账 —— 配送费 100% 归骑手的账面铁证
        #           (售后单保留在此侧:配送已履约,骑手入账与配送费依然一一对应)
        active = [o for o in completed if o.refund_cents < o.total_cents]
        # 跑腿单剔除:它没有商家入账,留在菜品侧这条恒等式里必然不平。
        # 它的钱在上面逐单那条跑腿恒等式里核过了
        active_food = [o for o in active
                       if o.id not in m_reversals and not is_errand(o)]
        food_lhs = sum(order_gross(o) for o in active_food)
        food_rhs = sum(
            m_earnings[o.id].net_cents + m_earnings[o.id].commission_cents
            for o in active_food if o.id in m_earnings
        )
        if food_lhs != food_rhs:
            problems.append({
                "check": "global_identity_mismatch",
                "detail": f"商家侧恒等不平:Σ应收(菜品+打包-满减) {food_lhs} "
                          f"≠ Σ净额+佣金 {food_rhs}"
                          f"(差 {food_lhs - food_rhs} 分,近 {WINDOW_DAYS} 天)",
            })
        fee_lhs = sum(_rider_due(o)
                      for o in active if o.rider_id is not None)
        fee_rhs = sum(
            r_earnings[o.id].amount_cents
            for o in active if o.rider_id is not None and o.id in r_earnings
        )
        if fee_lhs != fee_rhs:
            problems.append({
                "check": "global_identity_mismatch",
                "detail": f"配送侧恒等不平:Σ(配送费+小费) {fee_lhs} ≠ Σ骑手入账 {fee_rhs}"
                          f"(差 {fee_lhs - fee_rhs} 分,近 {WINDOW_DAYS} 天)",
            })

        # 8) 团购券:每张已核销券 净额+服务费 == 售价(逐张),全局 Σ 同样恒等
        #
        # **窗口按 redeemed_at,不是 created_at。** 券的钱是核销那一刻才落定的
        # (net/commission 都在 routers/vouchers.py 核销时才写),而有效期默认
        # 90 天、上限 365 天。按下单时间取窗的话,第 31 天以后核销的券
        # **一生中没有任何一天会被审计看到** —— 它落定的时候,自检早就
        # 不看它了。对外账本(ledger.py: replace("created_at","redeemed_at"))
        # 取的就是这一列,自检必须和公示同一批流水。
        from ..models import VoucherPurchase, VoucherPurchaseStatus

        redeemed = (
            await db.scalars(
                select(VoucherPurchase).where(
                    VoucherPurchase.status == VoucherPurchaseStatus.redeemed,
                    VoucherPurchase.redeemed_at >= since,
                )
            )
        ).all()
        for p in redeemed:
            if p.net_cents + p.commission_cents != p.sell_price_cents:
                problems.append({
                    "check": "voucher_split_mismatch",
                    "detail": f"团购券 {p.purchase_no} 分账不平:"
                              f"净额 {p.net_cents}+服务费 {p.commission_cents}"
                              f" ≠ 售价 {p.sell_price_cents}",
                })

        # 9) 住宿:资金按状态逐单恒等——
        #    离店: 佣金+净额 == 房费 且 佣金 <= 房费×5%;
        #    取消/未入住/拒单: 佣金必须为 0 且 净额+退款 == 房费
        from ..models import StayOrder
        from ..state_machine import StayOrderStatus

        #
        # **窗口按资金落定时刻取,不是下单时刻。** 住宿是提前订的:提前一个月
        # 订房、住完离店,按 created_at 取 30 天窗的话这单 100% 漏检 ——
        # 它产生佣金的那天已经在窗外了。离店看 completed_at,
        # 取消/拒单/未入住看 cancelled_at,与 ledger.py 逐列对齐。
        from sqlalchemy import and_ as sa_and
        from sqlalchemy import or_ as sa_or

        settled_stays = (await db.scalars(
            select(StayOrder).where(sa_or(
                sa_and(StayOrder.status == StayOrderStatus.COMPLETED,
                       StayOrder.completed_at >= since),
                sa_and(StayOrder.status.in_([
                           StayOrderStatus.CANCELLED, StayOrderStatus.NOSHOW,
                           StayOrderStatus.REJECTED]),
                       StayOrder.cancelled_at >= since),
            )))).all()
        for o in settled_stays:
            if o.status == StayOrderStatus.COMPLETED:
                bad = (o.fee_cents + o.net_cents != o.total_cents
                       or o.fee_cents * 100 > o.total_cents * 5)
            else:
                bad = (o.fee_cents != 0
                       or o.net_cents + o.refund_cents != o.total_cents)
            if bad:
                problems.append({
                    "check": "stay_split_mismatch",
                    "detail": f"住宿单 {o.order_no}({o.status.value}) 资金不平:"
                              f"房费 {o.total_cents} 佣金 {o.fee_cents}"
                              f" 净额 {o.net_cents} 退款 {o.refund_cents}",
                })

        # 10) 分账挂起:台账说这笔货款该分给商家,而渠道一分钱都没动。
        #     不设时间窗 —— 挂着的钱不会因为过了 30 天就不欠了,
        #     而上面那些恒等式只看近 30 天是因为它们核的是"当期账对不对"。
        #     一笔一条会刷屏(渠道未接入期间每单都挂),所以聚合成一条,
        #     带上笔数、金额、最久多久,够管理端判断严重程度就行。
        from .profit_sharing import STUCK_HOURS, stuck_summary
        ps = await stuck_summary(db)
        if ps["stuck"]:
            problems.append({
                "check": "profit_sharing_stuck",
                "detail": f"分账挂起 {ps['stuck']} 笔共 {ps['stuck_cents']} 分"
                          f"超过 {STUCK_HOURS} 小时未走通,最久的"
                          f" {ps['oldest_order_no']} 已挂 {ps['oldest_hours']} 小时"
                          f"——这些货款仍在平台侧,商家没收到",
            })
        if ps["failed"]:
            problems.append({
                "check": "profit_sharing_failed",
                "detail": f"分账已放弃 {ps['failed']} 笔共 {ps['failed_cents']} 分"
                          f"(超重试上限),需人工处理:清扫只捞 pending,"
                          f"failed 不会自己恢复",
            })

        # 11) 退款挂在 requested:向渠道发起了、渠道没回。
        #     钱既没到用户手上,也不在平台账上算数 —— 规则 5 把 requested
        #     算进"流水之和"(只排除 failed),所以恒等式那边一片安宁。
        #     分账挂起有专门一条,退款挂起以前没有,这条把口子补上。
        #     同样不设时间窗(挂着的钱不会因为过了 30 天就不欠了),
        #     同样聚合成一条(渠道抽风时会是几百笔,一笔一条等于刷屏)。
        now_utc = datetime.now(timezone.utc)
        stuck_n, stuck_cents, stuck_oldest = (await db.execute(
            select(sa_func.count(Refund.id),
                   sa_func.coalesce(sa_func.sum(Refund.amount_cents), 0),
                   sa_func.min(Refund.created_at))
            .where(Refund.status == RefundStatus.requested,
                   Refund.created_at
                   < now_utc - timedelta(hours=REFUND_STUCK_HOURS)))).one()
        if stuck_n:
            if stuck_oldest.tzinfo is None:  # 与仓库其它处一致:naive 当 UTC
                stuck_oldest = stuck_oldest.replace(tzinfo=timezone.utc)
            oldest_h = int((now_utc - stuck_oldest).total_seconds() // 3600)
            problems.append({
                "check": "refund_stuck",
                "detail": f"退款挂起 {stuck_n} 笔共 {stuck_cents} 分超过 "
                          f"{REFUND_STUCK_HOURS} 小时仍是 requested,最久的已挂 "
                          f"{oldest_h} 小时 —— 渠道没回执,用户没收到钱",
            })

        # 11b) 渠道**拒绝**的退款(failed):这一条以前不存在,而
        #      services/wechat_pay.py 的 `request_refund` 注释里写着
        #      「审计规则 5c 会把它捞出来要人工介入」—— 承诺了一条不存在的规则。
        #
        #      为什么它会隐形:渠道拒绝时**不累计** `order.refund_cents`
        #      (钱一分没退出去,账面不能写"已退"),而恒等式那几条又都用
        #      `status != failed` 把这些流水排除在 Σ 之外。两边一起躲开,
        #      于是「用户该收到钱、但一分没收到」这件事,在一个号称
        #      「差一分钱就报警」的自检里完全没有痕迹。
        #
        #      **失败后人工重发成功的不再报**:同一笔业务(biz_type+biz_id)
        #      后来有过 success 的退款,就说明这事有人管了。不加这个条件的话
        #      它会天天红一条,而天天红的告警等于没有告警。
        retried = aliased(Refund)
        failed_n, failed_cents = (await db.execute(
            select(sa_func.count(Refund.id),
                   sa_func.coalesce(sa_func.sum(Refund.amount_cents), 0))
            .where(Refund.status == RefundStatus.failed,
                   Refund.created_at
                   < now_utc - timedelta(hours=REFUND_STUCK_HOURS),
                   ~select(1)
                   .where(retried.biz_type == Refund.biz_type,
                          retried.biz_id == Refund.biz_id,
                          retried.status == RefundStatus.success,
                          retried.created_at > Refund.created_at)
                   .exists()))).one()
        if failed_n:
            problems.append({
                "check": "refund_failed",
                "detail": f"退款被渠道拒绝 {failed_n} 笔共 {failed_cents} 分,"
                          f"且之后没有成功的重发 —— 这笔钱既没退给用户,"
                          f"也不在任何恒等式里(失败流水被 Σ 排除),"
                          f"必须人工重发或退现",
            })

        # 12) 非完成订单上挂着的商家入账行。
        #
        # 这是和 6.5 同一类的补盲区。规则 1/6/7 全部从 completed 那批单出发遍历,
        # 6.5 又只看 order_kind != 外卖,于是**取消单上的外卖商家入账行**
        # 谁都遍历不到。而无骑手兜底取消(services/auto_flow.py)恰恰会往那儿
        # 写一条平台赔付餐损的入账行 —— 那是真金白银从平台流向商家,
        # 却是审计视野里唯一一块没人看的地方。
        #
        # **只报"来路不明"的,不把合规赔付本身报成红灯。** 兜底赔付是设计内的
        # 支出(透明中心 /funds 已按 note 公示),天天红一条只会让人习惯忽略红灯;
        # 合规赔付的笔数金额随告警文案一起带出来,够对账就行。
        from .errand import KIND_FOOD
        from .liability import SPLIT_EARNING_NOTE as _SPLIT_NOTE
        noncompleted_rows = (await db.execute(
            select(Order.order_no, Order.status, Order.order_kind,
                   Order.food_cents, Order.packing_fee_cents,
                   Order.discount_cents, Order.self_delivery,
                   Order.delivery_fee_cents,
                   sa_func.sum(MerchantEarning.net_cents),
                   sa_func.sum(MerchantEarning.commission_cents),
                   sa_func.min(MerchantEarning.note))
            .join(MerchantEarning, MerchantEarning.order_id == Order.id)
            .where(Order.status != OrderStatus.COMPLETED,
                   Order.created_at >= since)
            .group_by(Order.order_no, Order.status, Order.order_kind,
                      Order.food_cents, Order.packing_fee_cents,
                      Order.discount_cents, Order.self_delivery,
                      Order.delivery_fee_cents)
            .having(sa_func.sum(MerchantEarning.net_cents) != 0))).all()
        comp_n, comp_cents, bad_rows = 0, 0, []
        split_n, split_cents = 0, 0
        for (order_no, status, kind, food, packing, discount,
             self_deliv, delivery_fee,
             net, commission, note) in noncompleted_rows:
            # 应收口径必须和 settlement.credit_merchant 一致:
            # **自配送单的配送费归商家**(运力是他出的)。
            # 少了这一句,自配送单的分摊取消会被判成"来路不明的入账",
            # 每一单都红一条 —— 同一类坑这一批已经撞过三次了。
            expected = max(food + packing - discount, 0)
            if self_deliv:
                expected += delivery_fee
            shape_ok = (status == OrderStatus.CANCELLED
                        and kind == KIND_FOOD
                        and commission == 0
                        and net == expected)
            # 取消单上有商家入账,现在有**两种**设计内的形态。两种都要
            # 验形状(状态、业务线、佣金为 0、净额等于应收)再看 note ——
            # 只看 note 的话,一个写错的备注字符串就能把错账洗白。
            #
            # 判责分摊在这里放行**不等于没人管它**:它转交给规则 16
            # (cancel_split_not_balanced),那条比这里严 —— 这里只核商家
            # 一侧,规则 16 核的是商家 + 骑手 + 退款 == 用户实付。
            sanctioned = shape_ok and (
                note.startswith(NO_RIDER_COMP_NOTE)         # 平台兜底赔付
                or note.startswith(_SPLIT_NOTE))            # 用户取消判责分摊
            if sanctioned and note.startswith(_SPLIT_NOTE):
                split_n += 1
                split_cents += net
            elif sanctioned:
                comp_n += 1
                comp_cents += net
            else:
                bad_rows.append((order_no, status, net, commission, note))
        if comp_n:  # 合规赔付不报警,记一行日志够管理端复核
            logger.info("平台兜底赔付(近 %s 天):%s 笔共 %s 分",
                        WINDOW_DAYS, comp_n, comp_cents)
        if split_n:
            # **和兜底赔付分开数。** 兜底那笔是平台真金白银流向商家,
            # 分摊这笔的钱来自用户已付 —— 混在一起数,平台支出会虚高
            logger.info("用户取消判责分摊(近 %s 天):%s 笔共 %s 分",
                        WINDOW_DAYS, split_n, split_cents)
        for order_no, status, net, commission, note in bad_rows:
            problems.append({
                "check": "noncompleted_order_earning",
                "detail": f"未完成订单 {order_no}({status.value})挂着商家入账 "
                          f"{net} 分、佣金 {commission} 分,note「{note[:40]}」——"
                          f"不是兜底赔付的形态,这笔钱没有对应的已完成交易"
                          f"(同期合规兜底赔付 {comp_n} 笔共 {comp_cents} 分)",
            })

        # 13) 住宿 PAID 挂起:钱已收、商家一直没确认。
        #     规则 9 只核已结算的四个终态,PAID/CONFIRMED/CHECKED_IN 整个排除;
        #     而住宿清扫(auto_flow._sweep_stays)对 CREATED 有支付超时、
        #     对 CONFIRMED 有 noshow、对 CHECKED_IN 有自动离店,**唯独 PAID
        #     没有任何超时兜底** —— 商家不点确认,这笔钱就无限期压在平台侧,
        #     既不结算也不退款,而且没有任何一条检查看得见它。
        stay_n, stay_cents, stay_oldest = (await db.execute(
            select(sa_func.count(StayOrder.id),
                   sa_func.coalesce(sa_func.sum(StayOrder.total_cents), 0),
                   sa_func.min(StayOrder.paid_at))
            .where(StayOrder.status == StayOrderStatus.PAID,
                   StayOrder.paid_at
                   < now_utc - timedelta(hours=STAY_PAID_STUCK_HOURS)))).one()
        if stay_n:
            if stay_oldest.tzinfo is None:
                stay_oldest = stay_oldest.replace(tzinfo=timezone.utc)
            oldest_h = int((now_utc - stay_oldest).total_seconds() // 3600)
            problems.append({
                "check": "stay_paid_stuck",
                "detail": f"住宿已支付未确认 {stay_n} 笔共 {stay_cents} 分超过 "
                          f"{STAY_PAID_STUCK_HOURS} 小时,最久的已挂 {oldest_h} 小时"
                          f" —— 钱在平台侧,商家没确认也没拒单,清扫对 PAID "
                          f"没有超时兜底,只能人工推",
            })

        # 14) 团购券退款:Σ退款流水 == 应退额。
        #
        # 形态照抄规则 5(订单那条),补的是**同一类恒等式在券这条线上的缺口**:
        # 规则 5 查的是 `Refund.order_id == order.id`,而券的流水 order_id 是
        # NULL(它不属于任何外卖订单),结构上就落在规则 5 的视野之外。
        # 券只有"未使用全额退"一种口径,应退额恒等于售价。
        #
        # **窗口按 refunded_at,不是 created_at。** 券的有效期最长 365 天,
        # 按下单时间取 30 天窗的话,第 31 天以后退的券一生都不会被看到 ——
        # 和规则 8 用 redeemed_at 是同一个理由(钱落定的那一刻),
        # 退掉的券没核销过,redeemed_at 永远是 NULL,所以单开一列。
        #
        # 显式再导一遍(规则 8/9 的块里也导过):这两条的取数完全依赖它们,
        # 而"靠上面某个块顺手导进来的名字"会在有人调整规则顺序时静默崩掉
        from ..models import (
            REFUND_BIZ_STAY,
            REFUND_BIZ_VOUCHER,
            VoucherPurchase,
            VoucherPurchaseStatus,
        )

        voucher_window = and_(
            VoucherPurchase.status == VoucherPurchaseStatus.refunded,
            VoucherPurchase.refunded_at >= since)
        refunded_vouchers = (await db.scalars(
            select(VoucherPurchase).where(voucher_window))).all()
        voucher_paid = await _refund_sums(
            db, REFUND_BIZ_VOUCHER, select(VoucherPurchase.id).where(voucher_window))
        for p in refunded_vouchers:
            paid_back = voucher_paid.get(p.id, 0)
            if paid_back != p.sell_price_cents:
                problems.append({
                    "check": "voucher_refund_mismatch",
                    "detail": f"团购券 {p.purchase_no} 标着已退款,退款流水却是 "
                              f"{paid_back} 分 ≠ 售价 {p.sell_price_cents} 分"
                              f"(渠道退款失败,或者这笔退款从来没推给渠道)",
                })

        # 15) 住宿退款:Σ退款流水 == **能原路退回去**的那部分,不是 refund_cents。
        #
        # 两者不总相等,差在「到店无房」:那条路上
        # `refund_cents = 房费 + 商家违约金(首晚 30%)`,**超过用户实付**,
        # 而微信退款 API 的硬约束是「退款额 ≤ 原支付额」——
        # 照 refund_cents 整笔推过去会被渠道直接拒掉,而账面写着已退。
        # 口径与写入端共用 routers/stays.channel_refundable_cents 那一个函数
        # (两处各写一遍的话,改一处就是长期红灯)。
        #
        # 超出的违约金是一笔**真实负债**:商家余额已经扣了(net = -违约金),
        # 用户还没拿到,得等「转账到零钱」接入。它照规则 12 的办法处理 ——
        # 有已成立的「到店无房」售后单背书、且金额对得上,就不当红灯报
        # (天天报一条谁都不看),只在下面聚合成一条待转账负债;
        # 没有背书的超退是真超退,一笔一条报出来。
        from ..models import (
            StayAfterSale,
            StayAfterSaleKind,
            StayAfterSaleStatus,
            StayOrder,
        )
        from ..routers.stays import channel_refundable_cents
        from ..state_machine import StayOrderStatus

        stay_window = and_(
            StayOrder.status.in_([StayOrderStatus.CANCELLED,
                                  StayOrderStatus.NOSHOW,
                                  StayOrderStatus.REJECTED]),
            StayOrder.refund_cents > 0,
            StayOrder.cancelled_at >= since)
        refunded_stays = (await db.scalars(
            select(StayOrder).where(stay_window))).all()
        # 子查询,不把 id 列表逐个绑成参数(理由见规则 1 上面那段长注释)
        no_room_penalty = {
            a.stay_order_id: a.penalty_cents
            for a in await db.scalars(select(StayAfterSale).where(
                StayAfterSale.stay_order_id.in_(
                    select(StayOrder.id).where(stay_window)),
                StayAfterSale.kind == StayAfterSaleKind.no_room,
                StayAfterSale.status.in_([StayAfterSaleStatus.accepted,
                                          StayAfterSaleStatus.auto_accepted])))
        }
        stay_paid = await _refund_sums(
            db, REFUND_BIZ_STAY, select(StayOrder.id).where(stay_window))
        owed_n, owed_cents = 0, 0
        for o in refunded_stays:
            due = channel_refundable_cents(o)
            paid_back = stay_paid.get(o.id, 0)
            if paid_back != due:
                problems.append({
                    "check": "stay_refund_mismatch",
                    "detail": f"住宿单 {o.order_no}({o.status.value})"
                              f"应原路退 {due} 分,退款流水却是 {paid_back} 分"
                              f"(订单上写着已退 {o.refund_cents} 分)——"
                              f"渠道退款失败,或者这笔退款从来没推给渠道",
                })
            excess = o.refund_cents - due
            if excess <= 0:
                continue
            if no_room_penalty.get(o.id) == excess:
                owed_n += 1
                owed_cents += excess
            else:
                problems.append({
                    "check": "stay_refund_exceeds_paid",
                    "detail": f"住宿单 {o.order_no}({o.status.value})退款 "
                              f"{o.refund_cents} 分超过用户实付 {o.total_cents} 分,"
                              f"超出 {excess} 分却没有已成立的「到店无房」售后单"
                              f"背书 —— 平台净流出,用户不可能倒欠钱",
                })
        if owed_n:
            problems.append({
                "check": "stay_penalty_unpaid",
                "detail": f"到店无房违约金 {owed_n} 笔共 {owed_cents} 分还没给到用户"
                          f"(近 {WINDOW_DAYS} 天):商家余额已经扣了,而违约金超过"
                          f"用户实付,退款通道退不了,「转账到零钱」尚未接入 ——"
                          f"这是一笔真实负债,不是账目错误",
            })

        # 规则 16:判责分摊取消的单,四方相加必须等于用户已付。
        #
        # **这条不加的话,分摊就是一条审计看不见的钱路径。** 上面每条恒等式
        # 都按 `status == COMPLETED` 取数,而分摊发生在**取消单**上 ——
        # 结构上整个落在它们的视野之外:商家和骑手都记了账、用户拿了部分退款,
        # 却没有任何一条规则核对过它们加起来对不对。
        #
        # 取消单上现在有两种钱路径,必须分清楚,判据是入账行的备注前缀
        # (由 liability.SPLIT_EARNING_NOTE 定义,结算和这里同源):
        #
        #   无人接单兜底   商家拿全额 + 用户也全额退,差额是**平台认赔**
        #   判责分摊       商家 + 骑手 + 退款 == 用户已付,平台一分不垫
        #
        # 用户已付按和 liability 同一个口径算(商家应收钳 0 之后再加配送费
        # 和小费),不直接用 total_cents —— 那一列是**剩余应付**不是累计实付,
        # 规则 5b 的长注释解释过为什么。
        from ..routers.appeals import APPEAL_REFUND_NOTE
        from .liability import SPLIT_EARNING_NOTE

        # 申诉改判会让平台**额外**退一笔给用户,于是「商家 + 骑手 + 退款」
        # 会超过用户实付 —— 超出的正是平台认亏的那部分。不认得它的话,
        # 每一次申诉成立都会报一条假红灯,而假红灯多了真红灯就没人看。
        appeal_paid = {
            oid: amt for oid, amt in (await db.execute(
                select(Refund.order_id, sa_func.sum(Refund.amount_cents))
                .where(Refund.reason == APPEAL_REFUND_NOTE,
                       Refund.status == RefundStatus.success,
                       Refund.order_id.is_not(None))
                .group_by(Refund.order_id))).all()
        }

        _re_sub = (
            select(RiderEarning.order_id,
                   RiderEarning.amount_cents.label("rider_cents"))
            .where(RiderEarning.kind == EarningKind.earning).subquery())
        split_absorbed_n, split_absorbed_cents = 0, 0
        split_rows = (await db.execute(
            select(Order, MerchantEarning.net_cents,
                   MerchantEarning.commission_cents,
                   sa_func.coalesce(_re_sub.c.rider_cents, 0))
            .join(MerchantEarning,
                  and_(MerchantEarning.order_id == Order.id,
                       MerchantEarning.kind == EarningKind.earning,
                       MerchantEarning.note.like(SPLIT_EARNING_NOTE + "%")))
            .outerjoin(_re_sub, _re_sub.c.order_id == Order.id)
            .where(Order.status == OrderStatus.CANCELLED,
                   Order.created_at >= since))).all()
        for o, net_cents, comm_cents, rider_cents in split_rows:
            paid = (max(o.food_cents + o.packing_fee_cents
                        - o.discount_cents, 0)
                    + o.delivery_fee_cents + o.tip_cents)
            got = net_cents + rider_cents + o.refund_cents
            absorbed = appeal_paid.get(o.id, 0)   # 申诉改判平台补退的部分
            if got - absorbed != paid:
                problems.append({
                    "check": "cancel_split_not_balanced",
                    "detail": f"分摊取消单 {o.order_no}:商家 {net_cents} + "
                              f"骑手 {rider_cents} + 退款 {o.refund_cents} "
                              f"− 申诉改判平台补退 {absorbed} = {got - absorbed} 分,"
                              f"而用户实付 {paid} 分 —— 差 "
                              f"{got - absorbed - paid} 分是凭空多出来或"
                              f"凭空少掉的钱",
                })
            elif absorbed:
                split_absorbed_n += 1
                split_absorbed_cents += absorbed
            if comm_cents != 0:
                problems.append({
                    "check": "cancel_split_commission_charged",
                    "detail": f"分摊取消单 {o.order_no} 收了 {comm_cents} 分佣金"
                              f" —— 直接违背公示的「取消时平台一分佣金都不收」",
                })

        if split_absorbed_n:
            logger.info("分摊取消的申诉改判(近 %s 天):%s 笔共 %s 分由平台认亏",
                        WINDOW_DAYS, split_absorbed_n, split_absorbed_cents)

        for p in problems:
            db.add(AuditAlert(check_name=p["check"], detail=p["detail"][:500]))
            logger.error("账务告警 [%s] %s", p["check"], p["detail"])

        # 运行记录(透明中心公示口径):同一天重跑覆盖,取最新结果
        from zoneinfo import ZoneInfo

        from ..models import AuditRun

        day = datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat()
        run = await db.scalar(select(AuditRun).where(AuditRun.day == day))
        if run is None:
            run = AuditRun(day=day)
            db.add(run)
        run.checked_orders = len(completed)
        run.problem_count = len(problems)
        await db.commit()

    if not problems:
        logger.info("账务自检通过:近 %s 天账目全部恒等", WINDOW_DAYS)
    return problems


async def backfill_legacy_refund_records() -> int:
    """退款流水/冲账功能上线前的历史退款记录,补录流水和冲账行(幂等)。

    - refund_cents 与流水之和的差额 → 补一条 mock 流水(note 标注历史补录)
    - 全额退款且已结算但没冲账 → 补冲账负数行
    - **券与住宿同理**:它们的退款接渠道之前一条流水都没写,
      库里存量不补的话规则 14/15 会对每一笔历史退款报一条,
      开发库里就是上千盏永不消失的红灯 —— 比不查更糟
    上线切换时执行一次,此后审计的 5/6/14/15 号恒等式即可长期保持全绿。
    """
    import uuid as _uuid

    from ..models import (
        REFUND_BIZ_FOOD,
        REFUND_BIZ_STAY,
        REFUND_BIZ_VOUCHER,
        Refund,
        RefundStatus,
        StayOrder,
        VoucherPurchase,
        VoucherPurchaseStatus,
    )
    from ..routers.stays import channel_refundable_cents
    from ..state_machine import StayOrderStatus
    from .settlement import reverse_merchant_earning

    def _legacy_refund(biz_type, biz_id, biz_no, amount, **extra) -> Refund:
        """补录行长得和真流水一样,只是 reason 标了出处。

        **mock + success**:补录的前提就是"这笔钱事实上已经退了/该退",
        只是当时没有这张表(或者这条业务线还没接渠道)。
        """
        return Refund(
            biz_type=biz_type, biz_id=biz_id,
            out_refund_no=f"{biz_no}-legacy-{_uuid.uuid4().hex[:6]}",
            amount_cents=amount,
            reason="历史退款补录(refunds 流水表上线前)",
            channel="mock", status=RefundStatus.success, **extra)

    fixed = 0
    since = datetime.now(timezone.utc) - timedelta(days=WINDOW_DAYS)
    async with SessionLocal() as db:
        refunded_ids = select(Order.id).where(
            Order.refund_cents > 0, Order.created_at >= since
        )
        # 冲账口径与规则 6 完全共用一个函数,不再各抄一份。
        # 口径不一致的教训:补录了入账却按旧口径不补冲账,规则 6 永久红灯。
        # 而按旧那个「累计退款 ≥ 剩余餐费」的巧合判据补冲账更糟 ——
        # 会把缺货退款后正常完成的单的商家净额直接扣掉(见 _reversal_due_ids)
        reversal_due = await _reversal_due_ids(db, refunded_ids)
        refunded = (
            await db.scalars(
                select(Order).where(
                    Order.refund_cents > 0, Order.created_at >= since
                )
            )
        ).all()
        for order in refunded:
            flows = await db.scalar(
                select(sa_func.coalesce(sa_func.sum(Refund.amount_cents), 0)).where(
                    Refund.order_id == order.id,
                    Refund.status != RefundStatus.failed,
                )
            )
            gap = order.refund_cents - flows
            if gap > 0:
                db.add(_legacy_refund(REFUND_BIZ_FOOD, order.id,
                                      order.order_no, gap,
                                      order_id=order.id,
                                      order_no=order.order_no))
                fixed += 1
            if (order.id in reversal_due
                    and await reverse_merchant_earning(db, order, "历史售后冲账补录")):
                fixed += 1

        # ---- 团购券:应退额 = 售价 ----
        voucher_window = and_(
            VoucherPurchase.status == VoucherPurchaseStatus.refunded,
            VoucherPurchase.refunded_at >= since)
        voucher_flows = await _refund_sums(
            db, REFUND_BIZ_VOUCHER,
            select(VoucherPurchase.id).where(voucher_window))
        for p in (await db.scalars(
                select(VoucherPurchase).where(voucher_window))).all():
            gap = p.sell_price_cents - voucher_flows.get(p.id, 0)
            if gap > 0:
                db.add(_legacy_refund(REFUND_BIZ_VOUCHER, p.id,
                                      p.purchase_no, gap))
                fixed += 1

        # ---- 住宿:应退额 = **能原路退回去**的那部分(口径与规则 15 共用)----
        stay_window = and_(
            StayOrder.status.in_([StayOrderStatus.CANCELLED,
                                  StayOrderStatus.NOSHOW,
                                  StayOrderStatus.REJECTED]),
            StayOrder.refund_cents > 0,
            StayOrder.cancelled_at >= since)
        stay_flows = await _refund_sums(
            db, REFUND_BIZ_STAY, select(StayOrder.id).where(stay_window))
        for o in (await db.scalars(
                select(StayOrder).where(stay_window))).all():
            gap = channel_refundable_cents(o) - stay_flows.get(o.id, 0)
            if gap > 0:
                db.add(_legacy_refund(REFUND_BIZ_STAY, o.id, o.order_no, gap))
                fixed += 1
        await db.commit()
    if fixed:
        logger.info("历史退款补录完成:%s 处", fixed)
    return fixed


async def backfill_missing_earnings() -> int:
    """对缺账的历史完成订单补记账(结算功能上线前的老订单),幂等。"""
    fixed = 0
    since = datetime.now(timezone.utc) - timedelta(days=WINDOW_DAYS)
    async with SessionLocal() as db:
        completed = (
            await db.scalars(
                select(Order).where(
                    Order.status == OrderStatus.COMPLETED,
                    Order.created_at >= since,
                )
            )
        ).all()
        for order in completed:
            has_m = await db.scalar(
                select(MerchantEarning.id).where(
                    MerchantEarning.order_id == order.id,
                    MerchantEarning.kind == EarningKind.earning,
                )
            )
            has_r = order.rider_id is None or await db.scalar(
                select(RiderEarning.id).where(
                    RiderEarning.order_id == order.id,
                    RiderEarning.kind == EarningKind.earning,
                )
            )
            if not has_m or not has_r:
                await settle_order(db, order)  # 内部幂等,只补缺的
                fixed += 1
        await db.commit()
    if fixed:
        logger.info("补账完成:%s 笔历史订单", fixed)
    return fixed
