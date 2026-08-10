import { Coupon, Dish, DishChoice, DishOptionGroup, Merchant,
  PromoRule } from '../model/Models';

/**
 * 购物车里的一行。
 *
 * `choices` 是选中的规格/加料**名字**。**同一道菜不同规格算不同行**,
 * 不要合并份数 —— 「大份加辣」和「小份不辣」是两样东西,
 * 合并之后用户改份数会改错那一行
 */
export interface CartLine {
  dish: Dish;
  quantity: number;
  choices: string[];
}

/**
 * 这一行的单价 = 菜品基础价 + 选中项的加价。
 *
 * ⚠️ 这个数**只用于显示**。下单时服务端 `resolve_options` 会按名字回查
 * 重算一遍,对不上以服务端为准 —— 客户端算价只是为了让用户在点之前
 * 知道要花多少,不是账目依据
 */
export function unitCents(line: CartLine): number {
  let price: number = line.dish.price_cents;
  const groups: DishOptionGroup[] = line.dish.options ?? [];
  for (let g = 0; g < groups.length; g++) {
    const choices: DishChoice[] = groups[g].choices ?? [];
    for (let c = 0; c < choices.length; c++) {
      if (line.choices.indexOf(choices[c].name) >= 0) {
        price += choices[c].delta_cents ?? 0;
      }
    }
  }
  return price;
}

/** 行标识:菜 id + 规格组合。加减份数、云端车比对都用它 */
export function lineKey(dishId: number, choices: string[]): string {
  const sorted: string[] = choices.slice().sort();
  return `${dishId}|${sorted.join(',')}`;
}

/** 规格的展示名:「大份 · 加辣」。没选规格时返回空串 */
export function choicesLabel(choices: string[]): string {
  return choices.join(' · ');
}

/** 一张券在当前金额下的判定结果 */
export interface CouponVerdict {
  coupon: Coupon;
  /** 能不能用 */
  usable: boolean;
  /** 真正能抵掉多少分。不可用时为 0 */
  offCents: number;
  /** 不可用的原因,直接显示给用户。可用时为空串 */
  reason: string;
}

/**
 * 金额与选券。
 *
 * **这一整个文件的口径必须和服务端 `orders.py` 的下单逻辑逐行对齐。**
 * 对不上的后果不是算错几分钱,是页面上显示"已省 10 元"、提交时被 409 打回,
 * 用户看到的是"说好的优惠不算数"。安卓端的 #188 修的就是这个:
 * 老代码只按面额倒序取第一张券,完全不看门槛。
 *
 * 全程「分」的整数,不做浮点运算。
 */

/** 餐费:(基础价 + 规格加价) × 份数 */
export function foodCents(lines: CartLine[]): number {
  let sum: number = 0;
  for (let i = 0; i < lines.length; i++) {
    sum += unitCents(lines[i]) * lines[i].quantity;
  }
  return sum;
}

/**
 * 打包费 = 商家固定打包费 + 菜品级打包费 × 份数。
 * 服务端就是这么加的,只算商家那一项会让券的门槛判定偏低
 */
export function packingCents(merchant: Merchant, lines: CartLine[]): number {
  let sum: number = merchant.packing_fee_cents ?? 0;
  for (let i = 0; i < lines.length; i++) {
    sum += (lines[i].dish.packing_fee_cents ?? 0) * lines[i].quantity;
  }
  return sum;
}

/**
 * 满减档位。
 *
 * 服务端按门槛**升序**遍历,每命中一档就覆盖前一档 —— 也就是**取最高的那一档**,
 * 不是累加。写成累加的话金额会比服务端算的低,提交时对不上
 */
export function manjianCents(merchant: Merchant, food: number, packing: number): number {
  const rules: PromoRule[] = merchant.promo_rules ?? [];
  const sorted: PromoRule[] = rules.slice().sort(
    (a: PromoRule, b: PromoRule) => a.threshold_cents - b.threshold_cents);
  let discount: number = 0;
  for (let i = 0; i < sorted.length; i++) {
    const r: PromoRule = sorted[i];
    if (r.threshold_cents > 0 && food >= r.threshold_cents) {
      discount = Math.min(r.off_cents, food + packing);
    }
  }
  return discount;
}

/**
 * 判定一张券在当前金额下能不能用、能抵多少。
 *
 * 两类券的规则不一样,而且**平台券的门槛是减完满减之后再判的** ——
 * 这一条最容易漏:一张「满 50 可用」的平台券,在 55 元、有满 50 减 12 的单上,
 * 基数看着够,减完满减只剩 43,照样不满足门槛
 */
export function judgeCoupon(coupon: Coupon, merchant: Merchant,
                            food: number, packing: number): CouponVerdict {
  const basis: number = food + packing;
  const manjian: number = manjianCents(merchant, food, packing);

  if (!coupon.usable) {
    return { coupon: coupon, usable: false, offCents: 0, reason: '已使用或已过期' };
  }

  if (coupon.funder === 'merchant') {
    // 店铺券:只能在发券商家使用
    if (coupon.merchant_id !== merchant.id) {
      return { coupon: coupon, usable: false, offCents: 0, reason: '只能在发券商家使用' };
    }
    if (basis < coupon.min_spend_cents) {
      const gap: number = coupon.min_spend_cents - basis;
      return {
        coupon: coupon, usable: false, offCents: 0,
        reason: `还差 ${(gap / 100).toFixed(2)} 元`,
      };
    }
    const shopOff: number = Math.min(coupon.amount_cents, basis);
    // 店铺券和满减二选其一取最优 —— 不优于满减就不让用,
    // 服务端会直接 409,客户端提前说清楚比让他提交失败强
    if (shopOff <= manjian) {
      return { coupon: coupon, usable: false, offCents: 0, reason: '本单满减更划算' };
    }
    return { coupon: coupon, usable: true, offCents: shopOff, reason: '' };
  }

  // 平台券:门槛按"减完满减之后"的金额判
  const afterManjian: number = basis - manjian;
  if (afterManjian < coupon.min_spend_cents) {
    const gap: number = coupon.min_spend_cents - afterManjian;
    return {
      coupon: coupon, usable: false, offCents: 0,
      reason: `还差 ${(gap / 100).toFixed(2)} 元`,
    };
  }
  const off: number = Math.min(coupon.amount_cents, afterManjian);
  if (off <= 0) {
    return { coupon: coupon, usable: false, offCents: 0, reason: '本单已无可抵扣金额' };
  }
  return { coupon: coupon, usable: true, offCents: off, reason: '' };
}

/**
 * 自动选最优券。
 *
 * 以满减为基准线,**只有严格优于满减时才换券**,打平不换 ——
 * 打平时换券等于白烧用户一张券,而他省的钱一分没多
 */
export function bestCoupon(coupons: Coupon[], merchant: Merchant,
                           food: number, packing: number): CouponVerdict | null {
  let best: CouponVerdict | null = null;
  for (let i = 0; i < coupons.length; i++) {
    const v: CouponVerdict = judgeCoupon(coupons[i], merchant, food, packing);
    if (!v.usable) {
      continue;
    }
    if (best === null || v.offCents > best.offCents) {
      best = v;
    }
  }
  return best;
}

/**
 * 最终优惠额。
 *
 * 店铺券**取代**满减(不叠加),平台券在满减之外再减。
 * 首单立减是服务端判的(要查用户有没有付过款),客户端算不了 ——
 * 所以这里给出的是**抵扣上限**,真实到手只会更省,不会因此 409
 */
export function totalOffCents(merchant: Merchant, food: number, packing: number,
                              picked: CouponVerdict | null): number {
  const manjian: number = manjianCents(merchant, food, packing);
  if (picked === null || !picked.usable) {
    return manjian;
  }
  if (picked.coupon.funder === 'merchant') {
    return picked.offCents; // 取代满减
  }
  return manjian + picked.offCents;
}
