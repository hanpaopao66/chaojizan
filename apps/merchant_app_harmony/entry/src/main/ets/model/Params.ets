import { Dish, MerchantOrder, Review } from './Models';

/**
 * 路由名与跳转参数。
 *
 * 路由名集中在一处、参数显式建类型 —— ArkTS 的 `NavPathStack.pushPath`
 * 收 `Object`,写错名字或少传字段都要跑到那一页才炸。
 * 集中声明至少让编译器帮忙看住参数。
 */
export class Routes {
  static readonly ORDER_DETAIL: string = 'orderDetail';
  static readonly DISHES: string = 'dishes';
  static readonly DISH_EDIT: string = 'dishEdit';
  static readonly FINANCE: string = 'finance';
  static readonly DAY_ORDERS: string = 'dayOrders';
  static readonly REVIEWS: string = 'reviews';
  static readonly AFTER_SALES: string = 'afterSales';
  static readonly SHOP_SETTINGS: string = 'shopSettings';
  static readonly PRINTER: string = 'printer';
  static readonly MESSAGES: string = 'messages';
  static readonly SHOP_PICKER: string = 'shopPicker';
}

/** 订单详情 */
export interface OrderDetailParam {
  order: MerchantOrder;
}

/** 菜品编辑。dish 为空 = 新增 */
export interface DishEditParam {
  dish?: Dish;
}

/** 某一天的逐单明细 */
export interface DayOrdersParam {
  day: string;
}

/** 评价列表。filter: 0 全部 / 1 差评(≤3星) / 2 待回复 */
export interface ReviewsParam {
  filter: number;
}

/** 回复评价 */
export interface ReplyParam {
  review: Review;
  append: boolean;
}
