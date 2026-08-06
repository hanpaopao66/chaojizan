"""连锁品牌(总部视角)。

## 三条设计红线

1. **单店商家零感知**:`Merchant.brand_id` 为空时,所有既有端点走原路径。
   品牌层是加法不是改造。
2. **证照按门店独立**:新开门店可以复制菜单,但**证照必须重新提交**。
   食品经营许可证是按门店核发的 —— 复用等于让平台给未经核验的门店背书,
   出了食安问题追不到具体门店头上。
3. **不做品牌级钱包**:资金仍按门店结算。钱一旦在总部合并,
   门店就说不清自己那份对不对,与「每一笔分账可查可申诉」直接冲突。

## 不做总部强制改价

菜单模板可以下发,但**库存与上下架状态不覆盖** —— 那是门店当天的
经营决策(今天这道菜的料没了,总部在几百公里外不知道)。
门店经营自主权不该被平台的产品设计架空。
"""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..models import (Brand, BrandMember, Dish, Merchant, MerchantStatus,
                      Order, Review, User)
from ..security import require_role
from ..services.staff import my_shops
from ..state_machine import OrderStatus

router = APIRouter(prefix="/brands", tags=["连锁品牌"])


async def _my_brand(db: AsyncSession, user: User) -> Brand | None:
    """我所属的品牌(自己建的,或被拉进来的)。"""
    brand = await db.scalar(select(Brand).where(Brand.owner_id == user.id))
    if brand is not None:
        return brand
    member = await db.scalar(
        select(BrandMember).where(BrandMember.user_id == user.id))
    return await db.get(Brand, member.brand_id) if member else None


@router.post("/me")
async def create_brand(
    payload: dict,
    user: User = Depends(require_role("merchant")),
    db: AsyncSession = Depends(get_db),
):
    """把现有的店升级成品牌总部(第一家店成为品牌首店)。

    只有店主能建;一个人一个品牌 —— 再多就该是两家公司的事了。
    """
    from ..services.moderation import guard_text

    name = str(payload.get("name", "")).strip()[:50]
    if len(name) < 2:
        raise HTTPException(422, "品牌名至少 2 个字")
    await guard_text(db, name, "品牌名")
    if await _my_brand(db, user) is not None:
        raise HTTPException(409, "你已经有品牌了")
    # 客户端会把 shop_id 传过来(它知道当前选的是哪家)。**不能收下就用** ——
    # 校验归属之后才认,否则等于让人把别人的店挂到自己品牌下
    wanted = payload.get("shop_id")
    if wanted:
        shop = await db.get(Merchant, int(wanted))
        if shop is None or shop.owner_id != user.id:
            raise HTTPException(404, "门店不存在")
    else:
        shop = await db.scalar(
            select(Merchant).where(Merchant.owner_id == user.id)
            .order_by(Merchant.id))
    if shop is None:
        raise HTTPException(404, "先有一家店才能建品牌")
    brand = Brand(name=name, owner_id=user.id,
                  logo_url=str(payload.get("logo_url", ""))[:300])
    db.add(brand)
    await db.flush()
    shop.brand_id = brand.id
    await db.commit()
    await db.refresh(brand)
    return {"id": brand.id, "name": brand.name, "shops": 1}


@router.get("/me")
async def my_brand(
    user: User = Depends(require_role("merchant")),
    db: AsyncSession = Depends(get_db),
):
    """我的品牌与门店列表。没有品牌时 brand 为 null,
    shops 仍返回我能操作的店 —— 客户端用同一份数据做门店选择器。"""
    brand = await _my_brand(db, user)
    shops = await my_shops(db, user)
    return {
        "brand": None if brand is None else {
            "id": brand.id, "name": brand.name, "logo_url": brand.logo_url,
            "is_owner": brand.owner_id == user.id,
        },
        "shops": [{
            "id": s.id, "name": s.name, "address": s.address,
            "status": s.status.value, "is_open": s.is_open,
            "in_brand": s.brand_id is not None,
        } for s in shops],
    }


@router.get("/me/members")
async def list_members(
    user: User = Depends(require_role("merchant")),
    db: AsyncSession = Depends(get_db),
):
    """品牌成员(区域经理)。只有品牌所有者看得到 ——
    谁能管哪几家店属于组织内部信息。"""
    brand = await _my_brand(db, user)
    if brand is None or brand.owner_id != user.id:
        raise HTTPException(403, "只有品牌所有者能查看成员")
    rows = (await db.execute(
        select(BrandMember, User.name, User.phone)
        .join(User, User.id == BrandMember.user_id)
        .where(BrandMember.brand_id == brand.id)
        .order_by(BrandMember.id))).all()
    return [{
        "id": m.id, "user_id": m.user_id, "role": m.role,
        "name": name,
        # 手机号打码:成员列表是给品牌老板看谁在管店的,不是通讯录
        "phone": f"{phone[:3]}****{phone[-4:]}" if len(phone) >= 7 else "",
        "shop_ids": m.shop_ids,
        "created_at": m.created_at,
    } for m, name, phone in rows]


@router.post("/me/members")
async def add_member(
    payload: dict,
    user: User = Depends(require_role("merchant")),
    db: AsyncSession = Depends(get_db),
):
    """按手机号把人加成区域经理,并指定管辖门店(空 = 全部门店)。

    对方必须**已经用商家端登录过**(同手机号的商家账号) ——
    与店员的加入方式一致,不替人开账号。
    """
    from ..models import UserRole

    brand = await _my_brand(db, user)
    if brand is None or brand.owner_id != user.id:
        raise HTTPException(403, "只有品牌所有者能加成员")
    phone = str(payload.get("phone", "")).strip()
    target = await db.scalar(select(User).where(
        User.phone == phone, User.role == UserRole.merchant))
    if target is None:
        raise HTTPException(
            404, "对方需先用商家端 App 或网页登录过一次(同手机号的商家账号)")
    if target.id == user.id:
        raise HTTPException(422, "你已经是品牌所有者了")
    # 对方自己有品牌的话,_brand_scope 会优先认他自己的品牌、直接忽略这条
    # 成员记录 —— 加进来是个静默空操作:界面上显示"已添加",实际一点权限
    # 都没给。宁可在这里说清楚
    if await db.scalar(select(Brand.id).where(Brand.owner_id == target.id)):
        raise HTTPException(
            422, "对方自己已经是某个品牌的所有者,不能同时受雇于本品牌")
    shop_ids = [int(i) for i in (payload.get("shop_ids") or [])]
    if shop_ids:
        valid = set(await db.scalars(
            select(Merchant.id).where(Merchant.id.in_(shop_ids),
                                      Merchant.brand_id == brand.id)))
        if valid != set(shop_ids):
            raise HTTPException(422, "授权门店必须是本品牌的店")
    existing = await db.scalar(select(BrandMember).where(
        BrandMember.brand_id == brand.id, BrandMember.user_id == target.id))
    if existing is not None:
        existing.shop_ids = shop_ids   # 已在品牌里 = 改授权范围
    else:
        db.add(BrandMember(brand_id=brand.id, user_id=target.id,
                           role="manager", shop_ids=shop_ids))
    await db.commit()
    return {"ok": True, "name": target.name,
            "shops": len(shop_ids) or "全部"}


@router.delete("/me/members/{member_id}")
async def remove_member(
    member_id: int,
    user: User = Depends(require_role("merchant")),
    db: AsyncSession = Depends(get_db),
):
    """移出品牌:立即失去所有门店权限。"""
    brand = await _my_brand(db, user)
    if brand is None or brand.owner_id != user.id:
        raise HTTPException(403, "只有品牌所有者能移除成员")
    member = await db.get(BrandMember, member_id)
    if member is None or member.brand_id != brand.id:
        raise HTTPException(404, "成员不存在")
    await db.delete(member)
    await db.commit()
    return {"ok": True}


@router.get("/me/overview")
async def brand_overview(
    days: int = Query(default=7, ge=1, le=90),
    user: User = Depends(require_role("merchant")),
    db: AsyncSession = Depends(get_db),
):
    """跨店汇总:哪家店在涨、哪家在掉,一屏看完。

    每家店一行,给的都是**门店自己也看得到的同一个数** ——
    总部视角不引入门店看不到的指标,否则店长会觉得自己在被暗中打分。
    """
    shops = [s for s in await my_shops(db, user) if s.brand_id is not None]
    if not shops:
        raise HTTPException(404, "还没有品牌门店")
    since = datetime.now(timezone.utc) - timedelta(days=days)
    ids = [s.id for s in shops]

    # 单量/营业额:与门店端「今日看板」同口径(下单口径,扣退款)
    gross = Order.food_cents + Order.packing_fee_cents - Order.discount_cents
    rows = (await db.execute(
        select(Order.merchant_id, func.count(Order.id),
               func.sum(func.greatest(gross - Order.refund_cents, 0)),
               func.count(Order.id).filter(Order.ready_late.is_(True)))
        .where(Order.merchant_id.in_(ids), Order.created_at > since,
               Order.status.in_([OrderStatus.DELIVERED,
                                 OrderStatus.COMPLETED]))
        .group_by(Order.merchant_id))).all()
    stats = {r[0]: (r[1], int(r[2] or 0), r[3]) for r in rows}

    # 未回差评:总部最该盯的一项(门店可能自己不看评价)
    bad_rows = (await db.execute(
        select(Review.merchant_id, func.count(Review.id))
        .where(Review.merchant_id.in_(ids), Review.merchant_rating <= 3,
               Review.reply == "", Review.hidden.is_(False),
               Review.created_at > since)
        .group_by(Review.merchant_id))).all()
    bad = {r[0]: r[1] for r in bad_rows}

    items = []
    for s in shops:
        orders, net, late = stats.get(s.id, (0, 0, 0))
        items.append({
            "shop_id": s.id, "name": s.name,
            "status": s.status.value, "is_open": s.is_open,
            "orders": orders, "net_cents": net,
            "ready_late": late,
            "rating_avg": (round(s.rating_sum / s.rating_count, 2)
                           if s.rating_count else None),
            "bad_unreplied": bad.get(s.id, 0),
        })
    items.sort(key=lambda x: -x["net_cents"])
    return {
        "days": days,
        "shops": items,
        "total": {
            "shops": len(items),
            "orders": sum(i["orders"] for i in items),
            "net_cents": sum(i["net_cents"] for i in items),
            "bad_unreplied": sum(i["bad_unreplied"] for i in items),
        },
        "note": "各店的数与他们自己看到的完全一致 —— 总部不看暗中打分的指标。",
    }


@router.post("/me/shops")
async def open_brand_shop(
    payload: dict,
    user: User = Depends(require_role("merchant")),
    db: AsyncSession = Depends(get_db),
):
    """新开一家品牌门店:复制配置,但**证照必须重新提交**。

    复制的是"省去重新录一遍菜单"的那部分工作:菜品、分类、营业时间、
    满减模板。**不复制**:证照、坐标、库存 —— 前者是法定按门店核发的,
    后两者本来就是这家店独有的。

    新店照走完整审核(pending → 人工核验 → approved),
    与任何一家新店一视同仁。
    """
    brand = await _my_brand(db, user)
    if brand is None or brand.owner_id != user.id:
        raise HTTPException(403, "只有品牌所有者能开新门店")
    src = await db.get(Merchant, int(payload.get("copy_from") or 0))
    if src is None or src.brand_id != brand.id:
        raise HTTPException(422, "参照门店必须是本品牌的店")

    from ..services.moderation import guard_text

    required = ("name", "address", "lat", "lng", "license_no",
                "license_image_url")
    missing = [k for k in required if not payload.get(k)]
    if missing:
        raise HTTPException(
            422, "新门店必须自己提交证照与地址(食品经营许可证按门店核发,"
                 "不能复用总部或其他门店的)")

    await guard_text(db, str(payload["name"]), "门店名称")
    await guard_text(db, str(payload["address"]), "门店地址")
    shop = Merchant(
        name=str(payload["name"])[:50],
        description=src.description,
        address=str(payload["address"])[:200],
        lat=float(payload["lat"]), lng=float(payload["lng"]),
        # 证照:新店自己的,一个字段都不从 src 抄
        license_no=str(payload["license_no"])[:50],
        license_image_url=str(payload["license_image_url"])[:300],
        category=src.category, biz_type=src.biz_type,
        brand_id=brand.id, owner_id=user.id,
        status=MerchantStatus.pending, is_open=False,
        # 可复制的经营配置
        open_time=src.open_time, close_time=src.close_time,
        min_order_cents=src.min_order_cents,
        packing_fee_cents=src.packing_fee_cents,
        promise_ready_minutes=src.promise_ready_minutes,
        promo_rules=src.promo_rules,
    )
    db.add(shop)
    await db.flush()

    # 菜单复制:库存归零 —— 新店还没进货,直接抄库存等于一开门就超卖
    dishes = (await db.scalars(
        select(Dish).where(Dish.merchant_id == src.id,
                           Dish.is_on_sale.is_(True)))).all()
    for d in dishes:
        db.add(Dish(
            merchant_id=shop.id, name=d.name, category=d.category,
            price_cents=d.price_cents, stock=0, is_on_sale=True,
            description=d.description, badges=d.badges, options=d.options,
            sort=d.sort, is_alcohol=d.is_alcohol,
            serve_window=d.serve_window,
        ))
    await db.commit()
    await db.refresh(shop)
    return {
        "id": shop.id, "name": shop.name, "status": shop.status.value,
        "dishes_copied": len(dishes),
        "note": "菜单已复制(库存为 0,进货后补);证照已提交,等待平台人工核验。",
    }


@router.post("/me/promo-sync")
async def sync_promo(
    payload: dict,
    user: User = Depends(require_role("merchant")),
    db: AsyncSession = Depends(get_db),
):
    """满减下发:把源门店的满减档位应用到目标门店。

    **下发之后门店仍然可以自己改。** 这看着和"总部统一"的直觉相反,
    但满减的成本是**门店承担的**(结算时从门店实收里扣) —— 谁出钱谁有
    最终决定权。总部能做的是把模板推过去省得每家重录一遍,
    不是替门店决定要亏多少。与菜单下发不覆盖库存是同一个道理。
    """
    from ..schemas import PromoRule

    brand = await _my_brand(db, user)
    if brand is None or brand.owner_id != user.id:
        raise HTTPException(403, "只有品牌所有者能下发营销")
    src = await db.get(Merchant, int(payload.get("from_shop") or 0))
    if src is None or src.brand_id != brand.id:
        raise HTTPException(422, "源门店必须是本品牌的店")
    target_ids = [int(i) for i in (payload.get("to_shops") or [])]
    if not 1 <= len(target_ids) <= 50:
        raise HTTPException(422, "一次最多下发到 50 家门店")
    targets = (await db.scalars(
        select(Merchant).where(Merchant.id.in_(target_ids),
                               Merchant.brand_id == brand.id))).all()
    if len(targets) != len(set(target_ids)):
        raise HTTPException(422, "目标门店必须都是本品牌的店")

    # 源门店的档位照样过一遍校验:存量数据可能是更早的规则写进去的,
    # 直接搬过去等于把一个校验不过的配置复制到 50 家店
    rules = [PromoRule(**r).model_dump() for r in (src.promo_rules or [])]
    done = []
    for shop in targets:
        if shop.id == src.id:
            continue
        shop.promo_rules = list(rules)
        done.append({"shop_id": shop.id, "name": shop.name})
    await db.commit()
    return {
        "from_shop": src.id, "rules": len(rules), "shops": done,
        "note": "已下发。门店仍可自行调整 —— 满减的钱是门店出的,"
                "最终决定权在他们手上。",
    }


@router.post("/me/coupon-sync")
async def sync_coupons(
    payload: dict,
    user: User = Depends(require_role("merchant")),
    db: AsyncSession = Depends(get_db),
):
    """券下发:按同一份模板,在每家目标门店**各建一个批次**。

    ## 为什么不建一个"品牌级批次"让几家店共用预算

    券的成本是 funder=merchant、**由发券的那家门店全额承担**。共用预算
    就变成"我店的钱被别店花了" —— 门店对不上自己那份账,而
    「每一笔分账可查可申诉」是平台写在规则中心里的承诺。
    与"不做品牌级钱包"是同一条线。

    所以各店各建、各出各的:total 是**每家店各自的**发放上限,
    不是几家店分一个总额。返回体里明说这一点。
    """
    from ..models import CouponBatch
    from ..services.moderation import guard_text

    brand = await _my_brand(db, user)
    if brand is None or brand.owner_id != user.id:
        raise HTTPException(403, "只有品牌所有者能下发营销")
    target_ids = [int(i) for i in (payload.get("to_shops") or [])]
    if not 1 <= len(target_ids) <= 50:
        raise HTTPException(422, "一次最多下发到 50 家门店")
    targets = (await db.scalars(
        select(Merchant).where(Merchant.id.in_(target_ids),
                               Merchant.brand_id == brand.id))).all()
    if len(targets) != len(set(target_ids)):
        raise HTTPException(422, "目标门店必须都是本品牌的店")

    name = str(payload.get("name", "")).strip()[:50]
    if len(name) < 2:
        raise HTTPException(422, "券名称至少 2 个字")
    await guard_text(db, name, "券名称")
    try:
        off = int(payload["off_cents"])
        threshold = int(payload["threshold_cents"])
        total = int(payload["total"])
        valid_days = int(payload.get("valid_days") or 7)
    except (KeyError, TypeError, ValueError):
        raise HTTPException(422, "请填写门槛、面额、每店发放量与有效期")
    if off <= 0 or threshold <= 0 or off >= threshold:
        raise HTTPException(422, "面额必须大于 0 且小于门槛(不能倒贴)")
    if not 1 <= total <= 100_000:
        raise HTTPException(422, "每店发放量 1–100000")
    if not 1 <= valid_days <= 90:
        raise HTTPException(422, "有效期 1–90 天")
    trigger = str(payload.get("trigger") or "claim")
    if trigger not in ("claim", "favorite"):
        raise HTTPException(422, "发放方式只支持 claim(主动领)/favorite(收藏即送)")

    created = []
    for shop in targets:
        db.add(CouponBatch(
            name=name, trigger=trigger, merchant_id=shop.id,
            amount_cents=off, min_spend_cents=threshold,
            total=total, valid_days=valid_days,
            per_user_limit=int(payload.get("per_user_limit") or 1),
            active=True))
        created.append({"shop_id": shop.id, "name": shop.name})
    await db.commit()
    return {
        "shops": created, "total_per_shop": total,
        "note": f"每家店各建了一个批次,各发 {total} 张、各自承担成本 —— "
                "不是几家店分一个总额。门店可以自己停掉自己那个批次。",
    }


@router.get("/me/finance")
async def brand_finance(
    days: int = Query(default=30, ge=1, le=90),
    user: User = Depends(require_role("merchant")),
    db: AsyncSession = Depends(get_db),
):
    """跨店对账汇总(只读)。

    ## 刻意**不做品牌级钱包**

    钱一旦在总部合并,门店就说不清自己那份对不对 —— 而
    「每一笔分账可查可申诉」是平台写在规则中心里的承诺。
    所以资金仍然按门店结算、按门店提现,这里只是把每家店的数并排列出来,
    省去逐店点进去看。**能看的每一个数,门店自己也看得到同一个。**

    只对品牌所有者开放:与 money_shop 同一条边界 ——
    区域经理能改价改设置,但碰不到钱。
    """
    from ..models import MerchantEarning

    brand = await _my_brand(db, user)
    if brand is None or brand.owner_id != user.id:
        raise HTTPException(403, "跨店对账只对品牌所有者开放")
    shops = [s for s in await my_shops(db, user)
             if s.brand_id == brand.id and s.owner_id == user.id]
    if not shops:
        raise HTTPException(404, "还没有品牌门店")
    ids = [s.id for s in shops]
    since = datetime.now(timezone.utc) - timedelta(days=days)

    rows = (await db.execute(
        select(MerchantEarning.merchant_id,
               func.count(MerchantEarning.id),
               func.coalesce(func.sum(MerchantEarning.food_cents), 0),
               func.coalesce(func.sum(MerchantEarning.commission_cents), 0),
               func.coalesce(func.sum(MerchantEarning.net_cents), 0))
        .where(MerchantEarning.merchant_id.in_(ids),
               MerchantEarning.created_at >= since)
        .group_by(MerchantEarning.merchant_id))).all()
    stat = {r[0]: r[1:] for r in rows}

    items = []
    for s in shops:
        n, gross, commission, net = stat.get(s.id, (0, 0, 0, 0))
        items.append({
            "shop_id": s.id, "name": s.name,
            "orders": n,
            "gross_cents": int(gross),
            "commission_cents": int(commission),
            "net_cents": int(net),
            # 实际费率(算出来的,不是配置里那个) —— 档位降费之后
            # 配置值和真实抽成会不一样,给真实的
            "effective_rate": (round(int(commission) / int(gross), 4)
                               if gross else 0.0),
        })
    items.sort(key=lambda x: -x["net_cents"])
    return {
        "days": days,
        "shops": items,
        "total": {
            "orders": sum(i["orders"] for i in items),
            "gross_cents": sum(i["gross_cents"] for i in items),
            "commission_cents": sum(i["commission_cents"] for i in items),
            "net_cents": sum(i["net_cents"] for i in items),
        },
        "note": "只读汇总。**资金仍按门店结算、按门店提现** —— "
                "钱在总部合并的话,门店就说不清自己那份对不对。"
                "这里每一个数,门店自己也看得到同一个。",
    }


@router.get("/me/finance.csv")
async def brand_finance_csv(
    days: int = Query(default=30, ge=1, le=90),
    user: User = Depends(require_role("merchant")),
    db: AsyncSession = Depends(get_db),
):
    """跨店对账汇总导出。逐店一行 + 合计一行,拿去做账直接能用。"""
    import csv
    import io

    from fastapi.responses import StreamingResponse

    data = await brand_finance(days=days, user=user, db=db)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["门店", "订单数", "流水(元)", "平台佣金(元)",
                "实得(元)", "实际费率"])
    for i in data["shops"]:
        w.writerow([i["name"], i["orders"],
                    f'{i["gross_cents"] / 100:.2f}',
                    f'{i["commission_cents"] / 100:.2f}',
                    f'{i["net_cents"] / 100:.2f}',
                    f'{i["effective_rate"] * 100:.2f}%'])
    t = data["total"]
    w.writerow(["合计", t["orders"], f'{t["gross_cents"] / 100:.2f}',
                f'{t["commission_cents"] / 100:.2f}',
                f'{t["net_cents"] / 100:.2f}', ""])
    w.writerow([])
    w.writerow(["说明", data["note"]])
    # \ufeff:Excel 不给 BOM 就把中文认成乱码,商家打开是一屏问号
    return StreamingResponse(
        io.BytesIO(("\ufeff" + buf.getvalue()).encode("utf-8")),
        media_type="text/csv",
        headers={"Content-Disposition":
                 f'attachment; filename="brand-finance-{days}d.csv"'})


@router.post("/me/menu-sync")
async def sync_menu(
    payload: dict,
    user: User = Depends(require_role("merchant")),
    db: AsyncSession = Depends(get_db),
):
    """菜单下发:把源门店的菜品应用到目标门店。

    **不覆盖库存与上下架状态** —— 那是门店当天的经营决策
    (今天这道菜的料没了,总部在几百公里外不知道)。
    按菜名匹配:同名的更新价格/描述/标签/规格,没有的新建(库存 0)。
    """
    brand = await _my_brand(db, user)
    if brand is None or brand.owner_id != user.id:
        raise HTTPException(403, "只有品牌所有者能下发菜单")
    src = await db.get(Merchant, int(payload.get("from_shop") or 0))
    target_ids = [int(i) for i in (payload.get("to_shops") or [])]
    if src is None or src.brand_id != brand.id:
        raise HTTPException(422, "源门店必须是本品牌的店")
    if not 1 <= len(target_ids) <= 50:
        raise HTTPException(422, "一次最多下发到 50 家门店")
    targets = (await db.scalars(
        select(Merchant).where(Merchant.id.in_(target_ids),
                               Merchant.brand_id == brand.id))).all()
    if len(targets) != len(set(target_ids)):
        raise HTTPException(422, "目标门店必须都是本品牌的店")

    src_dishes = (await db.scalars(
        select(Dish).where(Dish.merchant_id == src.id,
                           Dish.is_on_sale.is_(True)))).all()
    result = []
    for shop in targets:
        if shop.id == src.id:
            continue
        existing = {d.name: d for d in (await db.scalars(
            select(Dish).where(Dish.merchant_id == shop.id)))}
        created = updated = 0
        for d in src_dishes:
            hit = existing.get(d.name)
            if hit is None:
                db.add(Dish(
                    merchant_id=shop.id, name=d.name, category=d.category,
                    price_cents=d.price_cents, stock=0, is_on_sale=True,
                    description=d.description, badges=d.badges,
                    options=d.options, sort=d.sort, is_alcohol=d.is_alcohol,
                    serve_window=d.serve_window))
                created += 1
            else:
                # 只同步"总部该统一的"字段;库存与上下架属门店自主
                hit.price_cents = d.price_cents
                hit.category = d.category
                hit.description = d.description
                hit.badges = d.badges
                hit.options = d.options
                hit.sort = d.sort
                updated += 1
        result.append({"shop_id": shop.id, "name": shop.name,
                       "created": created, "updated": updated})
    await db.commit()
    return {
        "from_shop": src.id, "dishes": len(src_dishes), "results": result,
        "note": "库存与上下架状态没有被覆盖 —— 那是各店当天的经营决策。",
    }
