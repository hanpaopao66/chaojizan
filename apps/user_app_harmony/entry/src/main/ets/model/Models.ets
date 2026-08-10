/**
 * 数据模型:只搬用户端真正用到的那个子集。
 *
 * 字段名严格对齐服务端(`server/app/schemas.py`),**不在客户端另起中文名**——
 * 状态文案、堂食标识、配送费构成的中文名服务端都下发
 * (`status_label` / `dine_in_label` / `fee_part_labels`),
 * 客户端自己维护一份迟早分叉,而分叉的后果是三端说法不一致,
 * 用户会觉得平台在糊弄他。
 *
 * 金额一律是「分」的整数,见 common/Money.ets 里的说明。
 */

/**
 * 满减档:满 threshold_cents 减 off_cents。
 * 服务端按门槛升序遍历、后者覆盖前者 —— **取最高档,不累加**
 */
export interface PromoRule {
  threshold_cents: number;
  off_cents: number;
}

/** 商家列表项与详情共用。服务端返回的字段远多于这些,只声明用得到的 */
export interface Merchant {
  id: number;
  name: string;
  description: string;
  address: string;
  lat: number;
  lng: number;
  is_open: boolean;
  rating_avg?: number;
  rating_count?: number;
  monthly_sales?: number;
  announcement?: string;
  logo_url?: string;
  min_order_cents?: number;
  packing_fee_cents?: number;
  category?: string;
  distance_m?: number;
  /** 明厨亮灶:法定公示项,**没装的店也要显示「无明厨亮灶」**,不是只给有的加徽章 */
  kitchen_cam?: boolean;
  kitchen_cam_label?: string;
  /**
   * 堂食标识(总局令第 123 号第十二条)。三态 unknown/yes/no,
   * **未填报就照实显示「未填报」** —— 替商家猜一个填上去,
   * 就是拿平台信用给没人核实过的信息背书
   */
  dine_in_status?: string;
  dine_in_label?: string;
  promo_labels?: string[];
  /** 满减规则。选券要和它比价,详见 common/Cart.ets */
  promo_rules?: PromoRule[];
}

/** 规格/加料里的一个选项。`delta_cents` 是相对基础价的加价 */
export interface DishChoice {
  name: string;
  delta_cents?: number;
}

/**
 * 规格组。`required` = 必选(必须恰好选一项),`multi` = 可多选。
 * 服务端 `resolve_options` 会按这套规则校验并**重算单价** ——
 * 客户端算出来的只用于显示,对不上时以服务端为准
 */
export interface DishOptionGroup {
  name: string;
  required?: boolean;
  multi?: boolean;
  choices: DishChoice[];
}

/** 菜品 */
export interface Dish {
  id: number;
  merchant_id: number;
  name: string;
  description?: string;
  price_cents: number;
  image_url?: string;
  category?: string;
  stock?: number;
  sold_out?: boolean;
  on_sale?: boolean;
  monthly_sales?: number;
  packing_fee_cents?: number;
  /** 规格与加料组。空数组 = 这道菜没有规格,直接加购 */
  options?: DishOptionGroup[];
}

/** 我的常点:近 90 天点得最多的「店 + 菜」组合 */
export interface FrequentDish {
  merchant_id: number;
  merchant_name: string;
  merchant_open: boolean;
  dish_id: number;
  dish_name: string;
  price_cents: number;
  times?: number;
}

/** 品类。**走接口不要在客户端硬编码** —— 改品类不用发版 */
export interface MerchantCategory {
  slug: string;
  name: string;
  emoji?: string;
}

/** 地址智能识别的返回:把一段粘贴的文字拆成字段 */
export interface ParsedAddress {
  contact_name?: string;
  contact_phone?: string;
  address?: string;
  detail?: string;
}

/** 订单里的一行 */
export interface OrderItem {
  dish_id: number;
  name: string;
  price_cents: number;
  quantity: number;
}

/** 配送费构成的一项。中文名由服务端给,客户端不另写映射 */
export interface FeePart {
  key: string;
  cents: number;
}

/** 订单 */
export interface Order {
  id: number;
  order_no: string;
  merchant_id: number;
  merchant_name?: string;
  status: string;
  /** 中文状态名,服务端下发 */
  status_label?: string;
  total_cents: number;
  food_cents?: number;
  delivery_fee_cents?: number;
  packing_fee_cents?: number;
  discount_cents?: number;
  subsidy_cents?: number;
  commission_cents?: number;
  refund_cents?: number;
  tip_cents?: number;
  created_at: string;
  eta_at?: string;
  cancel_reason?: string;
  items?: OrderItem[];
  fee_parts?: FeePart[];
  summary?: string;
  pickup?: boolean;
  self_delivery?: boolean;
  /** 地址保护:骑手只见粗地址。用户可临时放行完整门牌 */
  addr_protect?: boolean;
  addr_revealed?: boolean;
  /** 跑腿帮买:骑手申请加价时是 pending,要用户拍板 */
  goods_raise_status?: string;
  goods_raise_cents?: number;
  goods_budget_cents?: number;
}

/** 订单事件(时间轴的一项)。中文名服务端给,客户端不另写映射 */
export interface OrderEvent {
  id: number;
  order_no: string;
  from_status?: string;
  to_status: string;
  label?: string;
  actor_role?: string;
  reason?: string;
  created_at: string;
}

/** 骑手位置。只在配送中有值 */
export interface RiderLocation {
  lat: number;
  lng: number;
  updated_at?: string;
  rider_name?: string;
  rider_phone?: string;
  distance_m?: number;
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
  fault?: string;
  created_at: string;
  processed_at?: string;
}

/** 退款流水。审计核对 Σ流水 == 订单 refund_cents */
export interface RefundRecord {
  id: number;
  order_no: string;
  amount_cents: number;
  reason?: string;
  status: string;
  status_label?: string;
  created_at: string;
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
  rider_tags?: string[];
  is_anonymous?: boolean;
  reply?: string;
  append_reply?: string;
  user_name?: string;
  created_at: string;
}

/** 订单内的一条消息 */
export interface OrderMessage {
  id: number;
  from_role: string;
  content: string;
  kind?: string;
  created_at: string;
}

/** 收货地址 */
export interface Address {
  id: number;
  contact_name: string;
  contact_phone: string;
  address: string;
  detail?: string;
  lat: number;
  lng: number;
  is_default?: boolean;
  floor?: number;
  has_elevator?: boolean;
}

/** 我的优惠券 */
export interface Coupon {
  id: number;
  amount_cents: number;
  min_spend_cents: number;
  expires_at: string;
  usable: boolean;
  used: boolean;
  note?: string;
  /** merchant = 商家出钱的店铺券(限本店);platform = 平台券 */
  funder?: string;
  merchant_id?: number;
}

/** 在售团购券。核销才收 2%,未核销随时全额退 */
export interface VoucherDeal {
  id: number;
  merchant_id: number;
  merchant_name?: string;
  title: string;
  description?: string;
  sell_price_cents: number;
  face_value_cents: number;
  stock?: number;
  valid_days?: number;
}

/** 我买的券 */
export interface VoucherTicket {
  purchase_no: string;
  voucher_id: number;
  title?: string;
  merchant_name?: string;
  sell_price_cents: number;
  face_value_cents: number;
  code?: string;
  status: string;
  status_label?: string;
  expires_at?: string;
  redeemed_at?: string;
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
 * 配送费预览。`labels` 是构成项的中文名,服务端下发 ——
 * **客户端不另写一套映射**,否则会出现"骑手端说爬楼费、顾客端说远距离费"
 */
export interface DeliveryFeePreview {
  delivery_fee_cents: number;
  in_range: boolean;
  parts?: FeePart[];
  labels?: Record<string, string>;
  door_fee_cents?: number;
}

/** 微信支付统一下单参数(APP 拉起支付用) */
export interface WechatPrepay {
  appid: string;
  partnerid: string;
  prepayid: string;
  package: string;
  noncestr: string;
  timestamp: string;
  sign: string;
}

/** 订单状态常量。判断用它,显示用服务端给的 status_label */
export class OrderStatus {
  static readonly PENDING_PAYMENT: string = 'pending_payment';
  static readonly PAID: string = 'paid';
  static readonly ACCEPTED: string = 'accepted';
  static readonly READY: string = 'ready';
  static readonly PICKED_UP: string = 'picked_up';
  static readonly DELIVERED: string = 'delivered';
  static readonly COMPLETED: string = 'completed';
  static readonly CANCELLED: string = 'cancelled';

  /** 终态:不会再变,详情页可以停掉轮询 */
  static isFinal(status: string): boolean {
    return status === OrderStatus.COMPLETED || status === OrderStatus.CANCELLED;
  }
}
