"""三端规则页:什么算破坏规则、后果是什么、怎么申诉(#305)。

## 为什么三端都要有

原先只有商家有规则页(`/merchants/me/rules`),而且要登录才看得到。
两个问题:

1. **骑手和用户没有地方读规则。** 平台对他们做什么、不做什么,
   散在代码注释、承诺文案和账本里,没有一个能指过去的地方。
2. **规则要在加入之前就能读到。** 想入驻的商家、想跑单的骑手,
   得先看见规则再决定要不要来 —— 登录后才给看,顺序是反的。

## 判据是公平,而公平的形状是「对称」

「一方能做另一方不能做」就是不公平(见申诉通道那次的判据)。
所以这里的**结构三端一字不差**:同样的分级、同样的可见性、
同样的申诉入口。各端只在「什么行为会触发」上不同 —— 因为三端
能做的坏事本来就不一样,而不是因为平台对谁更宽。

## 慢不等于坏

出餐慢、送得慢、点得少,都是能力和条件的问题,**不处置**。
处置只针对**故意破坏规则**:恶意售后、虚假出餐、食安事故。
这条界线是 `prep_time` 那次定的君子协定的延伸 ——
君子协定管的是"别拿测量当鞭子",不是"不管作恶"。

## 每个数字都从代码里的真实常量算

和 `merchants.my_rules` / `platform._pledge_copy` 同一个做法:
公示 30 天 3 起自动停业、代码里写的却是 5 起,这种事只要可能发生
就迟早会发生。所以这里一个数字都不许手写。
"""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

#: 三端。key 同时是路由参数,别改 —— 客户端按它拉自己那份
AUDIENCES = ("customer", "merchant", "rider")

AUDIENCE_LABELS = {
    "customer": "用户",
    "merchant": "商家",
    "rider": "骑手",
}


def _risk_section(audience: str) -> dict:
    """处置分级。**三端这一节的结构一字不差** —— 这就是公平的形状。

    行为清单和判据**直接从 enforcement.CATALOG 生成** ——
    公示的表和实际执行的表是同一张,不可能对不上。这是这一页
    「每个数字都从代码常量算」那条原则的延续。

    只有「什么行为会触发」按端不同,因为三端能做的坏事本来就不一样。
    """
    from .credit import ORDER_CAP
    from .enforcement import LEVEL_LABELS, SEVERITY, public_table

    rows = public_table(audience)
    sev_lines = [
        f"　· **{LEVEL_LABELS[s.level]}** —— "
        + ("暂停平台补贴与优惠资格,正常经营/接单/下单不拦"
           if s.level == "limit" else "转人工复核期间的临时状态")
        for s in sorted(SEVERITY.values(), key=lambda x: x.times, reverse=True)
    ]
    return {
        "title": "什么会被处置",
        "items": [
            "**慢不算坏。** 出餐慢、送得晚、单量少,都是能力和条件的问题,"
            "平台不处置;慢和晚也不折算成任何分数(信用分里单量最多只加 "
            f"{ORDER_CAP} 分,一单没有也在最高一档)",
            "处置只针对**故意破坏规则**,按行为分类计次 —— "
            "**不同类不累加**,各看各的:",
            *[f"　· {r['label']}:{r['when']} → {r['level_label']}"
              + (f"({r['note']})" if r['note'] else "")
              for r in rows],
            "",
            "处置分两级,三端同一套:",
            *sev_lines,
            "",
            "**任何处置都对本人可见,写明原因,并且可以申诉。**"
            "误判优先放行 —— 宁可漏掉一个,不冤枉一个",
            "申诉成立的那一条**立刻不计入**,级别自动重算 —— "
            "不需要你等它「恢复」,也没有什么分要加回来",
            "窗口滚过去就自动归零,没有需要你去做的「修复」动作",
            "处置的月度总数在透明中心公示(只有计数,没有个案)",
        ],
    }


def _appeal_section(hours: int) -> dict:
    """申诉。**三端同一个窗口、同一套通道** —— 这是对称性的核心。"""
    return {
        "title": "申诉",
        "items": [
            f"判责结果、评价、处置,都可以在 {hours} 小时内申诉,每项一次",
            "申诉不用你自己举证:等餐时长、天气、订单实际距离这些"
            "平台都有,会自动附上",
            "改判成立,那一条判责撤销,信用分那一条不再计分;顾客已经拿到的退款不追回",
            # 2026-09-15 定:平台判错了,平台自己认(见 routers/appeals)
            "改判时的钱:平台判错了,平台自己认 —— 骑手责任改判,判责时扣的钱退回;商家售后判责改判,"
            "冲掉的净额和另出的配送费、小费都补回;顾客的取消分摊、「按送达处理」改判,钱原路退回。"
            "这些钱都由平台出,每一笔都在透明中心「申诉改判」和公开账本里",
        ],
    }


async def rules_for(audience: str, db: AsyncSession) -> dict:
    """某一端的规则页。**公开可读,不需要登录。**"""
    if audience not in AUDIENCES:
        raise ValueError(f"未知的端:{audience}")

    from ..config import settings
    from ..routers.admin import FS_AUTO_SUSPEND_COUNT
    from ..routers.after_sales import APPLY_WINDOW_DAYS
    from ..routers.appeals import APPEAL_WINDOW
    from ..services.labor_guard import (FATIGUE_REMIND_MINUTES,
                                        LABOR_PROMISES, RIDE_SPEED_KMH)

    appeal_hours = int(APPEAL_WINDOW.total_seconds() // 3600)
    tiers = settings.commission_tiers or [[0, "0.050"]]
    top_rate = max(float(r[1]) for r in tiers)

    if audience == "merchant":
        sections = [
            {
                "title": "抽成",
                "items": [
                    f"总负担 {top_rate * 100:g}% 封顶,单量越大费率越低",
                    "平台配送的配送费 100% 归骑手,平台一分不抽;"
                    "自配送的单配送费归你",
                    "没有竞价排名,不存在花钱买曝光",
                ],
            },
            {
                "title": "食品安全(唯一会直接影响经营的红线)",
                "items": [
                    f"30 天内成立 {FS_AUTO_SUSPEND_COUNT} 起食安投诉,"
                    "系统自动暂停营业并转人工复核",
                    "投诉直达平台不经商家,处置动作全部留痕",
                    "投诉核实成立:顾客拿回全款,由你承担(钱怎么走见下一节「判为商家责任的单」),"
                    f"记一条商家责任、扣信用分;{appeal_hours} 小时内可以对这笔售后判责申诉",
                ],
            },
            {
                # 2026-09-15 定:商家有责任,商家连配送费和小费一起出(services/merchant_fault)
                "title": "判为商家责任的单",
                "items": [
                    "你同意的售后,和平台判为商家责任的(顾客申诉「售后被拒」成立、"
                    "骑手到店没出餐或餐不齐、食安投诉成立):顾客拿回全款,含配送费和小费",
                    "钱由你出:这单净额冲回(佣金平台也不收);骑手跑了这一趟,配送费和小费照归骑手,"
                    "这一份也由你出,账上另记一行",
                    "余额可以因此为负:之后的收入先抵,提现按余额算",
                    "你自己配送的单,配送费本来就在你的入账里,冲回净额就一起退了,不另扣",
                    f"平台判的,{appeal_hours} 小时内可以申诉:改判成立,冲回的净额和另出的那行都补回你的"
                    "收入,钱由平台出(平台判错了,平台自己认),顾客拿到的退款不追回",
                ],
            },
            {
                "title": "排序怎么来的",
                "items": [
                    "用户端排序只用真实评分、销量、距离 —— 没有可以买的位置",
                    "**评分会影响你的曝光**:这不是处罚机制,是用户在选店 ——"
                    "但它确实决定谁被看见",
                    "信用分不参与排序、曝光和搜索:店铺页、列表、搜索里根本没有它",
                    "出餐时长不参与任何排序与筛选:只给你自己看、"
                    "让骑手知道大概等多久、给用户更准的送达时间",
                ],
            },
        ]
    elif audience == "rider":
        sections = [
            {
                "title": "钱",
                "items": [
                    "配送费和小费 100% 归你,平台分文不取",
                    "判为骑手责任(洒餐、丢餐等)的那一单:顾客全额退款,这单配送费不计;"
                    "商家那份餐钱先由骑手保障金池出,池子不够的从你的收入里扣(余额不够的,"
                    f"之后的收入先抵)。{appeal_hours} 小时内可以申诉,成立的话扣的钱全部退回",
                    "恶劣天气加价的同时一定放宽时限",
                    # 等餐超时补偿(平台出钱)2026-09-14 停发:这句不能再说。
                    # 等餐时长照旧记录、照旧公示,是申诉超时的证据
                    "到店等餐的时长照实记录、公示,是你申诉超时的证据;"
                    "平台不再给等餐补偿,也不向商家收钱",
                    # 难度反馈当场补钱(平台出)2026-09-14 停了(services/hardship 第 3 条)
                    "反馈「这单不好送」不当场补钱;同一个地方两个骑手说过之后,"
                    "以后的单把难度费算进配送费,顾客下单前看得到,全归你",
                    "提现户名必须和实名一致 —— 这条是保护你自己的钱",
                ],
            },
            {
                "title": "平台承诺不做的事",
                # 直接引用 labor_guard 那份 —— 那里每一条都有对应测试,
                # 在这里另抄一份就等于给自己留了一个对不上的机会
                "items": list(LABOR_PROMISES),
            },
            {
                "title": "时间是怎么算的",
                "items": [
                    f"骑行速度按 {RIDE_SPEED_KMH:g} km/h 的**固定常量**算,"
                    "不用你的实际速度 —— 跑得快不会被加码",
                    "爬楼、等电梯的时间算进预计时长,不用你自己扛",
                    f"连续在线 {FATIGUE_REMIND_MINUTES // 60} 小时会提醒你休息,"
                    "**但不会断你的单**",
                ],
            },
            {
                "title": "不考核你什么",
                "items": [
                    "没有服务分、派单分、段位、骑手等级这类影响接单的东西 —— "
                    "信用分只算平台判定成立、能申诉的事,只在接单之后给这一单的顾客、商家看,"
                    "不进派单",
                    "接单率、转单次数、异常上报次数**都只统计不考核** ——"
                    "车坏了、身体不适本来就该能转单",
                    "在线时长、跑单里程只是记录,不进派单、限流、封禁的判据",
                ],
            },
        ]
    else:  # customer
        sections = [
            {
                "title": "钱",
                "items": [
                    "不做大数据杀熟:同一时刻同一家店,谁看到的价都一样",
                    "配送费按距离算,规则公开,不按你的手机型号或消费记录变",
                    "没有竞价排名,排在前面的店不是花钱买的",
                    # 2026-09-14 拍板「平台没有钱,不做平台出钱的安抚和营销」(services/eta、coupons、referrals)
                    "送达比预计晚 15 分钟以上会收到一条致歉;平台不出钱发安抚券、新客券,"
                    "邀请有礼也停了 —— 已经领到的券照旧能用",
                ],
            },
            {
                "title": "取消和退款",
                "items": [
                    "商家接单前随时可取消,全额退",
                    "接单后有 2 分钟反悔窗口,仍然全额退",
                    "再往后按**成本实际发生到哪一步**分摊 —— "
                    "餐做了、骑手空跑了一趟,那些是真实发生且收不回的",
                    f"送达后 {APPLY_WINDOW_DAYS} 天内可以申请售后",
                    # 2026-09-15 定:商家有责任,顾客拿回全款(services/merchant_fault)
                    "售后成立(商家同意,或者平台判为商家、骑手的责任),全额退款,含配送费和小费;"
                    "钱由有责任的一方出,不由平台出",
                ],
            },
            {
                "title": "你的信息",
                "items": [
                    "骑手和商家默认只看到粗地址和中性称呼,"
                    "完整门牌要你临时放行才给",
                    "放门口的单必须拍照留证,那张照片**只有你和平台看得到**",
                    "生日只收月日不收年份 —— 用不到的信息不收",
                ],
            },
        ]

    # 信用分(2026-09 拍板,三种角色同一套机制)。两节**三端结构一样**:「信用分」讲你自己的分
    # 怎么算、谁能看到;「交易对方的信用分」讲接单之后能看到谁的、不许拿它做什么 ——
    # 都从 services/credit 的常量生成。它**不是处置**:不限制下单、接单、营业,
    # 所以不并进下面「什么会被处置」那一节
    from .credit import counterpart_lines, rules_lines
    sections.append({"title": "信用分", "items": rules_lines(audience)})
    sections.append({"title": "交易对方的信用分", "items": counterpart_lines(audience)})

    # 三端共用的两节放在最后,**顺序和措辞都一样** —— 这是对称性的体现,
    # 不是重复代码:任何一端单独改了,就是不公平的开始
    sections.append(_risk_section(audience))
    sections.append(_appeal_section(appeal_hours))
    return {
        "audience": audience,
        "audience_label": AUDIENCE_LABELS[audience],
        "sections": sections,
    }


# ---------------------------------------------------------------------------
# 变更留痕
# ---------------------------------------------------------------------------


def content_hash(sections: list) -> str:
    """规则内容的指纹。**只认内容,不认顺序之外的东西**。"""
    import hashlib
    import json

    blob = json.dumps(sections, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


async def record_if_changed(audience: str, sections: list,
                            db: AsyncSession) -> None:
    """规则变了就记一版。没变什么都不做。

    ## 为什么在读的时候记,而不是启动时或部署时

    规则是**算出来的**,而它依赖运行时开关(等餐补偿那种)。启动时记一次
    的话,后台拨一下开关、规则实际变了,却没有任何一版留痕。
    在读的时候比对,是唯一能覆盖"内容真的变了"这件事的时机。

    代价是给一个 GET 加了写。规则页是低频接口,而且只在**真的变了**
    的时候才写,所以稳态下就是一次索引查询。

    并发两个人同时打开:后一个插入撞唯一约束,吞掉。留痕不该因为
    两个人同时看规则而报错。
    """
    from sqlalchemy import desc, select

    from ..models import RuleRevision

    h = content_hash(sections)
    last = await db.scalar(
        select(RuleRevision)
        .where(RuleRevision.audience == audience)
        .order_by(desc(RuleRevision.revision))
        .limit(1))
    # 只跟**最近一版**比,不跟历史上所有版本比 ——
    # A→B→A 的第三步是一次真实的变更(改回去也是改),该记
    if last is not None and last.content_hash == h:
        return
    db.add(RuleRevision(
        audience=audience,
        revision=(last.revision + 1) if last else 1,
        content_hash=h,
        sections=sections,
    ))
    try:
        await db.commit()
    except Exception:
        await db.rollback()   # 撞唯一约束 = 别人刚记过,不是错


def diff_sections(old: list, new: list) -> list:
    """两版规则之间逐条的增删。

    按「小节标题 + 条目原文」比,不做字级 diff:规则是**一条一条**的,
    改一条的实质是"旧的这条没了、新的这条来了",字级 diff 只会把
    "30 天 3 起"改成"30 天 5 起"显示成一堆红绿字符,反而看不清。
    """
    def flat(secs):
        return {(s.get("title", ""), i)
                for s in secs for i in s.get("items", []) if i}

    a, b = flat(old), flat(new)
    out = []
    for title in dict.fromkeys(
            [s.get("title", "") for s in old] + [s.get("title", "") for s in new]):
        removed = sorted(i for (t, i) in a - b if t == title)
        added = sorted(i for (t, i) in b - a if t == title)
        if removed or added:
            out.append({"title": title, "removed": removed, "added": added})
    return out
