/**
 * 商家端数据模型:只搬商家端真正用到的那个子集。
 *
 * 字段名严格对齐服务端(`server/app/schemas.py`),**不在客户端另起中文名**——
 * 状态文案、配送费构成的中文名服务端都下发(`status_label` /
 * `fee_part_labels`),客户端自己维护一份迟早分叉,而分叉的后果是
 * 三端说法不一致:顾客端说「上门难度」、商家端说「door」,
 * 商家被问起来只能干瞪眼。
 *
 * 金额一律是「分」的整数,见 common/Money.ets 里的说明。
 */

/** 订单里的一行 */
export interface OrderItem {
  dish_id: number;
  name: string;
  price_cents: number;
  quantity: number;
}

/**
 * 配送费构成的一项。
 *
 * ⚠️ **服务端下发的 `fee_parts` 是字典不是数组**
 * (`{"base": 300, "night": 0, "weather": 0, "door": 300}`,
 * 见 `server/app/schemas.py` 的 `fee_parts: dict`)。
 * 这个 interface 是渲染/打印用的中间形态,由 [feePartList] 摊平得到。
 */
export interface FeePart {
  key: string;
  /** 中文名。取自服务端下发的 `fee_part_labels`,取不到才退回 key */
  label: string;
  cents: number;
}

/**
 * 把 `fee_parts` 字典 + `fee_part_labels` 字典摊成数组。
 *
 * **只留大于 0 的项**:「夜间加价 0 元」这种行没有信息量。
 * 小票只有 32 列,更不该拿去印零。
 */
export function feePartList(parts?: Record<string, number>,
                            labels?: Record<string, string>): FeePart[] {
  const out: FeePart[] = [];
  if (parts === undefined) {
    return out;
  }
  const keys: string[] = Object.keys(parts);
  for (let i: number = 0; i < keys.length; i++) {
    const k: string = keys[i];
    const cents: number = parts[k];
    if (cents === undefined || cents <= 0) {
      continue;
    }
    const label: string | undefined =
        labels === undefined ? undefined : labels[k];
    out.push({ key: k, label: label ?? k, cents: cents });
  }
  return out;
}

/**
 * 商家视角的订单。
 *
 * 比顾客视角多出来的:`commission_cents`(被抽了多少)、
 * `pickup_code`(自取核销码)、`rider_id` / `rider_name`(骑手到哪了)、
 * `parent_order_no`(追加单要和母单一起出)。
 */
export interface MerchantOrder {
  id: number;
  order_no: string;
  merchant_id: number;
  status: string;
  /** 中文状态名,服务端下发。判断用 status,显示用这个 */
  status_label?: string;
  created_at: string;
  eta_at?: string;

  total_cents: number;
  food_cents?: number;
  delivery_fee_cents?: number;
  packing_fee_cents?: number;
  discount_cents?: number;
  /** 平台佣金。**印在小票上、显示在列表上** —— 账目透明不能只写在首页 */
  commission_cents?: number;
  refund_cents?: number;
  tip_cents?: number;

  items?: OrderItem[];
  /** 字典,不是数组。渲染/打印前先过 [feePartList] */
  fee_parts?: Record<string, number>;
  fee_part_labels?: Record<string, string>;
  summary?: string;
  remark?: string;

  /** 自取单:免配送费,靠取餐码核销 */
  pickup?: boolean;
  pickup_code?: string;
  /** 商家自送:不派骑手,商家自己点「开始配送」 */
  self_delivery?: boolean;
  /** 顾客选了送到楼下,骑手不上楼。默认 true */
  to_door?: boolean;
  /** 预约单的中文时段名,服务端下发 */
  scheduled_label?: string;
  /** 含酒精:小票上要提示查验年龄 */
  has_alcohol?: boolean;
  /** 追加单的母单号:要和母单一起出餐 */
  parent_order_no?: string;

  contact_name?: string;
  contact_phone?: string;
  address?: string;
  lat?: number;
  lng?: number;

  rider_id?: number;
  rider_name?: string;
  rider_phone?: string;

  cancel_reason?: string;
}

/** 商家自己的店 */
export interface Shop {
  id: number;
  name: string;
  description?: string;
  address: string;
  lat: number;
  lng: number;
  is_open: boolean;
  announcement?: string;
  logo_url?: string;
  photos?: string[];
  category?: string;
  min_order_cents?: number;
  packing_fee_cents?: number;
  rating_avg?: number;
  rating_count?: number;
  open_time?: string;
  close_time?: string;
  /** 临时歇业到点自动恢复。有值 = 正在歇业中 */
  closed_until?: string;
  /** 食安停业闸门:置位时商家自己开不回来,服务端也会 403 */
  food_safety_hold?: boolean;
  /** 看这个店的人是不是店员(店员没有提现/改价/改设置的权限) */
  viewer_is_staff?: boolean;
  viewer_is_owner?: boolean;
  license_expires_at?: string;
  license_days_left?: number;
  license_stage?: string;
  promo_labels?: string[];
  promo_rules?: PromoRule[];
  gift_rules?: GiftRule[];
  holiday_plans?: Record<string, string>[];
  dine_in_status?: string;
  dine_in_label?: string;
  kitchen_cam?: boolean;
}

/** 满减档:满 threshold_cents 减 off_cents。**取最高档,不累加** */
export interface PromoRule {
  threshold_cents: number;
  off_cents: number;
}

/** 满赠档:满 threshold_cents 赠某菜 1 份 */
export interface GiftRule {
  threshold_cents: number;
  dish_id: number;
  name?: string;
}

/** 菜品(商家视角:多了库存、排序、限时价) */
export interface Dish {
  id: number;
  merchant_id: number;
  name: string;
  description?: string;
  price_cents: number;
  /** 限时价生效时的实际售价 */
  effective_price_cents?: number;
  flash_active?: boolean;
  image_url?: string;
  category?: string;
  stock?: number;
  /** 今日估清:次日 04:00 自动恢复 */
  sold_out_today?: boolean;
  /** 每日回满的份数 */
  daily_stock?: number;
  is_on_sale?: boolean;
  monthly_sales?: number;
  sort?: number;
  packing_fee_cents?: number;
}

/** 评价 */
export interface Review {
  id: number;
  order_no: string;
  merchant_rating: number;
  rider_rating?: number;
  comment?: string;
  append_comment?: string;
  image_urls?: string[];
  tags?: string[];
  is_anonymous?: boolean;
  reply?: string;
  append_reply?: string;
  user_name?: string;
  created_at: string;
}

/** 售后申请 */
export interface AfterSale {
  id: number;
  order_no: string;
  reason: string;
  images?: string[];
  status: string;
  status_label?: string;
  reply?: string;
  /** 判责:merchant / rider / platform / user */
  fault?: string;
  created_at: string;
  processed_at?: string;
}

/** 钱包 */
export interface Wallet {
  balance_cents: number;
  pending_cents?: number;
  withdrawable_cents?: number;
}

/** 提现记录 */
export interface Withdrawal {
  id: number;
  amount_cents: number;
  status: string;
  status_label?: string;
  created_at: string;
  processed_at?: string;
  reject_reason?: string;
}

/** 按日账单的一天 */
export interface DayStat {
  day: string;
  order_count: number;
  food_cents: number;
  commission_cents: number;
  net_cents: number;
}

/** 短信登录的返回 */
export interface LoginResult {
  token: string;
  user_id: number;
  name: string;
  role?: string;
}

/** 发验证码的返回。短信未配置时给开发模式验证码 */
export interface SmsCodeResult {
  dev_code?: string;
}

/**
 * 订单状态常量。判断用它,显示用服务端给的 status_label。
 *
 * 商家端关心的流转:paid(待接单)→ accepted(已接单)→ ready(已出餐)
 * → picked_up(骑手取走)→ delivered → completed。
 */
export class OrderStatus {
  static readonly PENDING_PAYMENT: string = 'pending_payment';
  /** **待接单**。商家端一切紧迫感的来源:有这个状态的单就要一直响 */
  static readonly PAID: string = 'paid';
  static readonly ACCEPTED: string = 'accepted';
  static readonly READY: string = 'ready';
  static readonly PICKED_UP: string = 'picked_up';
  static readonly DELIVERED: string = 'delivered';
  static readonly COMPLETED: string = 'completed';
  static readonly CANCELLED: string = 'cancelled';

  /** 终态:不会再变 */
  static isFinal(status: string): boolean {
    return status === OrderStatus.COMPLETED || status === OrderStatus.CANCELLED;
  }

  /** 还在进行中的单:商家要盯着的那些 */
  static isActive(status: string): boolean {
    return status === OrderStatus.PAID || status === OrderStatus.ACCEPTED ||
        status === OrderStatus.READY || status === OrderStatus.PICKED_UP;
  }
}
