import { Address, Merchant, Order, VoucherDeal } from './Models';
import { CartLine } from '../common/Cart';

/**
 * 路由参数。
 *
 * NavPathStack 传的是 object,取出来要 `as` 回去 —— 把形状集中声明在这里,
 * 别在每个 pushPath 的地方各写一遍匿名结构:那样改一个字段要翻遍全工程,
 * 而且漏掉一处编译器不会提醒(运行时才是 undefined)。
 */

export interface MerchantParam {
  merchantId: number;
}

export interface CheckoutParam {
  merchant: Merchant;
  lines: CartLine[];
}

export interface OrderDetailParam {
  orderNo: string;
}

/** 搜索页要当前坐标才能按距离排序 */
export interface SearchParam {
  lat: number;
  lng: number;
}

export interface CategoryParam {
  lat: number;
  lng: number;
  slug: string;
}

/** 地址簿。selectMode = 从结算页进来,选中即返回 */
export interface AddressListParam {
  selectMode: boolean;
}

/** 编辑地址。editing 为 null = 新增 */
export interface AddressEditParam {
  editing: Address | null;
}

/** 订单内沟通。peer = rider / merchant */
export interface ChatParam {
  orderNo: string;
  peer: string;
}

/** 售后与评价共用:只要订单号 */
export interface OrderActionParam {
  orderNo: string;
}

/** 酒店列表要坐标 */
export interface HotelsParam {
  lat: number;
  lng: number;
}

/** 加菜:关联原单 */
export interface AppendOrderParam {
  parentOrderNo: string;
  merchantId: number;
}

/** 晒单分账卡 */
export interface ShareCardParam {
  order: Order;
}

/** 拼单:code 为空 = 新开一个 */
export interface GroupCartParam {
  merchantId: number;
  code: string;
}

/** 酒店详情与下单 */
export interface HotelDetailParam {
  hotelId: number;
}

/** 证照公示:按门店 */
export interface LicensesParam {
  merchantId: number;
}

/** 团购券详情 */
export interface VoucherDetailParam {
  deal: VoucherDeal;
}

/** 路由名。写成常量,避免拼错字符串导致跳到空白页 */
export class Routes {
  static readonly LOGIN: string = 'login';
  static readonly MERCHANT: string = 'merchant';
  static readonly CHECKOUT: string = 'checkout';
  static readonly ORDER_DETAIL: string = 'orderDetail';
  static readonly SEARCH: string = 'search';
  static readonly CATEGORY: string = 'category';
  static readonly ADDRESS_LIST: string = 'addressList';
  static readonly ADDRESS_EDIT: string = 'addressEdit';
  static readonly CHAT: string = 'chat';
  static readonly AFTER_SALE: string = 'afterSale';
  static readonly REVIEW: string = 'review';
  static readonly TRANSPARENCY: string = 'transparency';
  static readonly MONEY_FLOW: string = 'moneyFlow';
  static readonly FAVORITES: string = 'favorites';
  static readonly COUPONS: string = 'coupons';
  static readonly MESSAGES: string = 'messages';
  static readonly HELP: string = 'help';
  static readonly SUPPORT: string = 'support';
  static readonly SETTINGS: string = 'settings';
  static readonly LICENSES: string = 'licenses';
  static readonly VOUCHER_DEALS: string = 'voucherDeals';
  static readonly VOUCHER_DETAIL: string = 'voucherDetail';
  static readonly MY_VOUCHERS: string = 'myVouchers';
  static readonly ERRAND: string = 'errand';
  static readonly HOTELS: string = 'hotels';
  static readonly STAY_ORDERS: string = 'stayOrders';
  static readonly HOTEL_DETAIL: string = 'hotelDetail';
  static readonly SHARE_CARD: string = 'shareCard';
  static readonly GROUP_CART: string = 'groupCart';
  static readonly INVITE: string = 'invite';
  static readonly IDENTITY: string = 'identity';
  static readonly APPEND_ORDER: string = 'appendOrder';
  static readonly FOOD_SAFETY_RECORDS: string = 'foodSafetyRecords';
  static readonly STAY_AFTER: string = 'stayAfter';
}
