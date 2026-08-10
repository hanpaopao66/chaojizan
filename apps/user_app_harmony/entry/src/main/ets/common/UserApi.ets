import { Api } from './Api';
import { Session } from './Session';
import { Address, AfterSale, Coupon, DeliveryFeePreview, Dish, FrequentDish,
  LoginResult, Merchant, MerchantCategory, Order, OrderEvent, ParsedAddress,
  RefundRecord, Review, RiderLocation, SmsCodeResult, VoucherDeal,
  VoucherTicket, WechatPrepay } from '../model/Models';
import { util } from '@kit.ArkTS';
import { preferences } from '@kit.ArkData';
import { common } from '@kit.AbilityKit';

const STORE: string = 'superz_session';
const K_DEVICE: string = 'device_id';

/** 下单请求体 */
export interface CreateOrderBody {
  merchant_id: number;
  items: OrderItemIn[];
  pickup: boolean;
  tip_cents: number;
  coupon_id?: number;
  address?: string;
  lat?: number;
  lng?: number;
  contact_name?: string;
  contact_phone?: string;
  remark?: string;
  tableware?: number;
}

export interface OrderItemIn {
  dish_id: number;
  quantity: number;
  /**
   * 选中的规格/加料**名字**列表。服务端 `resolve_options` 按名字回查加价并
   * **重算单价** —— 客户端不要传价格,传了也不算数
   */
  choices?: string[];
}

/** 云端购物车的一行 */
export interface CartItemIn {
  dish_id: number;
  quantity: number;
  choices?: string[];
}

/** 新增/修改地址的字段 */
export interface AddressIn {
  contact_name: string;
  contact_phone: string;
  address: string;
  detail?: string;
  lat: number;
  lng: number;
  is_default?: boolean;
  tag?: string;
  floor?: number;
  has_elevator?: boolean;
}

/**
 * 用户端要用到的接口,照着 `packages/shared/lib/src/api_client.dart`
 * 的用户子集搬过来。路径和请求体字段都是从那份实现里核准的,
 * **不要凭印象改** —— 服务端一行没动,对不上就是这边写错了。
 */
export class UserApi {
  private api: Api = Api.get();

  // ---------- 登录 ----------

  /**
   * 发验证码。短信服务未配置时返回开发模式验证码,已配置返回空。
   * 服务端有 60 秒冷却、同号日 8 条、同 IP 日 20 条、第 3 条起滑块的防刷,
   * 客户端不用再自己做一套,把服务端的报错原样显示就对了
   */
  async sendSmsCode(phone: string): Promise<SmsCodeResult> {
    const body: Record<string, string> = { 'phone': phone };
    const data = await this.api.request('POST', '/auth/sms-code', body);
    return (data ?? {}) as SmsCodeResult;
  }

  /** 验证码登录,新手机号自动注册 */
  async smsLogin(context: common.UIAbilityContext, phone: string,
                 code: string): Promise<LoginResult> {
    const deviceId: string = await this.deviceId(context);
    const body: Record<string, string> = {
      'phone': phone,
      'code': code,
      'device_id': deviceId,
      'role': 'customer',
    };
    const data = await this.api.request('POST', '/auth/sms-login', body);
    const result: LoginResult = data as LoginResult;
    await Session.get().saveLogin(result.token, result.user_id, result.name, phone);
    return result;
  }

  /**
   * 设备标识。
   *
   * **本地随机生成一个 UUID 存起来,不读系统的设备号。**
   * 安卓端的权限清单里特意没有设备识别码,鸿蒙版不该反过来去要 ——
   * 服务端要 device_id 只是为了"同设备不建邀请关系"这类防刷判断,
   * 一个稳定的随机串就够用,没必要拿真实硬件标识
   */
  private async deviceId(context: common.UIAbilityContext): Promise<string> {
    const store: preferences.Preferences =
      await preferences.getPreferences(context, STORE);
    const existing: preferences.ValueType = await store.get(K_DEVICE, '');
    if (typeof existing === 'string' && existing.length > 0) {
      return existing;
    }
    const fresh: string = util.generateRandomUUID(true);
    await store.put(K_DEVICE, fresh);
    await store.flush();
    return fresh;
  }

  // ---------- 商家与菜单 ----------

  /**
   * 附近商家。
   *
   * **不要自己传更大的 radius_m。** 服务端 2026-08 已把浏览半径收敛到配送上限
   * (merchants.py 的 _browse_radius_m),传大了也会被向下压回去 ——
   * 这条规则的意思是:列表里出现的每一家店都必须下得了配送单,
   * 而不是"先让用户看到再说"
   */
  async merchants(lat: number, lng: number, sort: string = 'distance',
                  limit: number = 50, offset: number = 0,
                  category: string = ''): Promise<Merchant[]> {
    const query: Record<string, string> = {
      'lat': `${lat}`,
      'lng': `${lng}`,
      'sort': sort,
      'limit': `${limit}`,
    };
    if (offset > 0) {
      query['offset'] = `${offset}`;
    }
    if (category.length > 0) {
      query['category'] = category;
    }
    const data = await this.api.request('GET', '/merchants', undefined, query);
    return (data ?? []) as Merchant[];
  }

  async merchantDetail(merchantId: number): Promise<Merchant> {
    const data = await this.api.request('GET', `/merchants/${merchantId}`);
    return data as Merchant;
  }

  async menu(merchantId: number): Promise<Dish[]> {
    const data = await this.api.request('GET', `/merchants/${merchantId}/dishes`);
    return (data ?? []) as Dish[];
  }

  /**
   * 搜索。**默认排序是 comprehensive(综合)**,不是距离 ——
   * 搜"麻辣烫"的人要的是好的麻辣烫,不是最近的那家
   */
  async searchMerchants(q: string, lat: number, lng: number,
                        sort: string = 'comprehensive',
                        maxDistanceM?: number, minRating?: number,
                        hasPromo: boolean = false,
                        maxMinOrderCents?: number): Promise<Merchant[]> {
    const query: Record<string, string> = {
      'q': q, 'sort': sort, 'lat': `${lat}`, 'lng': `${lng}`,
    };
    if (maxDistanceM !== undefined) {
      query['max_distance_m'] = `${maxDistanceM}`;
    }
    if (minRating !== undefined) {
      query['min_rating'] = `${minRating}`;
    }
    if (hasPromo) {
      query['has_promo'] = 'true';
    }
    if (maxMinOrderCents !== undefined) {
      query['max_min_order_cents'] = `${maxMinOrderCents}`;
    }
    const data = await this.api.request('GET', '/merchants/search', undefined, query);
    return (data ?? []) as Merchant[];
  }

  /** 输入联想。调用方自己做防抖(250ms),别每敲一个字就发一次 */
  async suggest(q: string): Promise<string[]> {
    const data = await this.api.request('GET', '/merchants/suggest', undefined,
      { 'q': q } as Record<string, string>);
    return (data ?? []) as string[];
  }

  /** 热搜词。服务端按**真实销量**算,不是运营手填的 */
  async hotKeywords(): Promise<string[]> {
    const data = await this.api.request('GET', '/merchants/hot-keywords');
    return (data ?? []) as string[];
  }

  /** 品类清单。**别在客户端硬编码副本** —— 安卓端存了一份,改品类要发版 */
  async categories(): Promise<MerchantCategory[]> {
    const data = await this.api.request('GET', '/merchants/categories');
    return (data ?? []) as MerchantCategory[];
  }

  /** 这家店我常买的菜 */
  async frequentDishes(merchantId: number): Promise<Dish[]> {
    const data = await this.api.request('GET',
      `/merchants/${merchantId}/frequent-dishes`);
    return (data ?? []) as Dish[];
  }

  /** 我的常点(跨店)。近 90 天的「店 + 菜」组合 */
  async myFrequentDishes(limit: number = 5): Promise<FrequentDish[]> {
    const data = await this.api.request('GET', '/orders/frequent', undefined,
      { 'limit': `${limit}` } as Record<string, string>);
    const map: Record<string, Object> = (data ?? {}) as Record<string, Object>;
    return (map['items'] ?? []) as FrequentDish[];
  }

  // ---------- 收藏 ----------

  async favoriteIds(): Promise<number[]> {
    const data = await this.api.request('GET', '/favorites/ids');
    return (data ?? []) as number[];
  }

  async favorites(): Promise<Merchant[]> {
    const data = await this.api.request('GET', '/favorites');
    return (data ?? []) as Merchant[];
  }

  async addFavorite(merchantId: number): Promise<void> {
    await this.api.request('POST', `/favorites/${merchantId}`);
  }

  async removeFavorite(merchantId: number): Promise<void> {
    await this.api.request('DELETE', `/favorites/${merchantId}`);
  }

  // ---------- 云端购物车 ----------

  /**
   * 取云端车。**游客没有云端车**(服务端要 customer 角色),
   * 这不是 bug 是角色限制 —— 界面上要让用户知道"登录后购物车会保留"
   */
  async getCart(merchantId: number): Promise<CartItemIn[]> {
    const data = await this.api.request('GET', `/cart/${merchantId}`);
    const map: Record<string, Object> = (data ?? {}) as Record<string, Object>;
    return (map['items'] ?? []) as CartItemIn[];
  }

  /** 整份覆盖保存(空 items = 清空该店的车)。调用方做防抖,别每次加减都发 */
  async putCart(merchantId: number, items: CartItemIn[]): Promise<void> {
    const body: Record<string, Object> = { 'items': items };
    await this.api.request('PUT', `/cart/${merchantId}`, body);
  }

  /** 这家店的评价。店铺页少了评价 tab,新店就没有任何信任来源 */
  async merchantReviews(merchantId: number): Promise<Review[]> {
    const data = await this.api.request('GET', `/merchants/${merchantId}/reviews`);
    return (data ?? []) as Review[];
  }

  /** 这家店可领的券。**进店才看得见**,所以店铺页一定要有这个入口 */
  async claimableShopCoupons(merchantId: number): Promise<Record<string, Object>[]> {
    const data = await this.api.request('GET', `/merchants/${merchantId}/coupons`);
    return (data ?? []) as Record<string, Object>[];
  }

  async claimShopCoupon(merchantId: number, batchId: number): Promise<void> {
    await this.api.request('POST', `/merchants/${merchantId}/coupons/${batchId}/claim`);
  }

  // ---------- 地址与券 ----------

  async addresses(): Promise<Address[]> {
    const data = await this.api.request('GET', '/addresses');
    return (data ?? []) as Address[];
  }

  async addAddress(body: AddressIn): Promise<Address> {
    const data = await this.api.request('POST', '/addresses', body);
    return data as Address;
  }

  async updateAddress(id: number, body: AddressIn): Promise<Address> {
    const data = await this.api.request('PATCH', `/addresses/${id}`, body);
    return data as Address;
  }

  async deleteAddress(id: number): Promise<void> {
    await this.api.request('DELETE', `/addresses/${id}`);
  }

  /**
   * 智能识别:粘贴一段「张三 138xxxx 某某小区3栋502」自动拆字段。
   * 拆错了要让用户能改 —— 识别是省事,不是代替用户确认
   */
  async parseAddress(text: string): Promise<ParsedAddress> {
    const body: Record<string, string> = { 'text': text };
    const data = await this.api.request('POST', '/addresses/parse', body);
    return (data ?? {}) as ParsedAddress;
  }

  /**
   * 我的券包。
   *
   * ⚠️ 服务端返回的 `usable` **只判「未使用且未过期」,不含门槛**。
   * 结算页选券必须自己按 `min_spend_cents` 过滤、并和满减比价 ——
   * 照着面额挑最大的那张会被下单接口 409 打回,
   * 而页面上已经显示了"已省 X 元",用户会觉得平台说话不算数。
   * 安卓端的 #188 就是修这个,鸿蒙版直接按正确的写
   */
  async myCoupons(): Promise<Coupon[]> {
    const data = await this.api.request('GET', '/orders/coupons/mine');
    return (data ?? []) as Coupon[];
  }

  /**
   * 配送费预览。**下单前就要让用户看到最终要付多少** ——
   * 配送费是按距离和时段算的,不预览的话用户到付款那一步才发现比预期贵,
   * 那是最容易弃单的地方
   */
  async deliveryFeePreview(merchantId: number, lat: number,
                           lng: number): Promise<DeliveryFeePreview> {
    const query: Record<string, string> = {
      'merchant_id': `${merchantId}`,
      'lat': `${lat}`,
      'lng': `${lng}`,
      'to_door': 'true',
    };
    const data = await this.api.request('GET', '/orders/delivery-fee',
      undefined, query);
    return data as DeliveryFeePreview;
  }

  // ---------- 下单与支付 ----------

  async createOrder(body: CreateOrderBody): Promise<Order> {
    const data = await this.api.request('POST', '/orders', body);
    return data as Order;
  }

  async myOrders(limit: number = 20): Promise<Order[]> {
    const query: Record<string, string> = { 'limit': `${limit}` };
    const data = await this.api.request('GET', '/orders', undefined, query);
    return (data ?? []) as Order[];
  }

  async getOrder(orderNo: string): Promise<Order> {
    const data = await this.api.request('GET', `/orders/${orderNo}`);
    return data as Order;
  }

  // ---------- 团购券 ----------

  /** 在售团购券。**核销才收 2%**,未核销随时全额退 */
  async voucherDeals(): Promise<VoucherDeal[]> {
    const data = await this.api.request('GET', '/vouchers');
    return (data ?? []) as VoucherDeal[];
  }

  async buyVoucher(voucherId: number): Promise<VoucherTicket> {
    const data = await this.api.request('POST', `/vouchers/${voucherId}/purchase`);
    return data as VoucherTicket;
  }

  /** 我的券包 */
  async myVoucherTickets(): Promise<VoucherTicket[]> {
    const data = await this.api.request('GET', '/vouchers/purchases/mine');
    return (data ?? []) as VoucherTicket[];
  }

  /** 未核销全额退。**不靠「过期不退」摸钱**,这是产品承诺 */
  async refundVoucher(purchaseNo: string): Promise<VoucherTicket> {
    const data = await this.api.request('POST',
      `/vouchers/purchases/${purchaseNo}/refund`);
    return data as VoucherTicket;
  }

  // ---------- 地址辅助(服务端接口,不依赖地图 SDK) ----------

  /**
   * 地址搜索联想。**这个不需要地图 SDK** —— 服务端代理了地图服务商,
   * 客户端只发关键词。没有地图也能让用户搜到"某某小区"而不是手打全称
   */
  async geoTips(keywords: string, city: string): Promise<Record<string, Object>[]> {
    const q: Record<string, string> = { 'keywords': keywords, 'city': city };
    const data = await this.api.request('GET', '/geo/tips', undefined, q);
    return (data ?? []) as Record<string, Object>[];
  }

  /** 逆地理:坐标反查地址。定位之后把"我在哪"变成一句人话 */
  async geoReverse(lat: number, lng: number): Promise<Record<string, Object>> {
    const q: Record<string, string> = { 'lat': `${lat}`, 'lng': `${lng}` };
    const data = await this.api.request('GET', '/geo/reverse', undefined, q);
    return (data ?? {}) as Record<string, Object>;
  }

  /** 下单后改配送地址。**服务端会重算配送费并判范围**,客户端别自己算 */
  async changeAddress(orderNo: string, addr: Address): Promise<Order> {
    const body: Record<string, Object> = {
      'address': addr.address,
      'lat': addr.lat,
      'lng': addr.lng,
      'contact_name': addr.contact_name,
      'contact_phone': addr.contact_phone,
    };
    const data = await this.api.request('POST',
      `/orders/${orderNo}/change-address`, body);
    return data as Order;
  }

  /**
   * 临时放行完整门牌。
   *
   * 地址保护开着时骑手只看得到粗地址;快到了用户可以主动放行 ——
   * **是用户按需放行,不是平台默认公开**,这个方向不能反
   */
  async revealAddress(orderNo: string): Promise<Order> {
    const data = await this.api.request('POST', `/orders/${orderNo}/reveal-address`);
    return data as Order;
  }

  // ---------- 住宿:评价与售后 ----------

  async createStayReview(orderNo: string, rating: number,
                         comment: string): Promise<Record<string, Object>> {
    const body: Record<string, Object> = { 'rating': rating, 'comment': comment };
    const data = await this.api.request('POST',
      `/stays/orders/${orderNo}/review`, body);
    return (data ?? {}) as Record<string, Object>;
  }

  async myStayReview(orderNo: string): Promise<Record<string, Object> | null> {
    const data = await this.api.request('GET', `/stays/orders/${orderNo}/review`);
    return data as Record<string, Object> | null;
  }

  /**
   * 住宿售后。kind 里最要紧的是**到店无房** ——
   * 那种情况商家要赔首晚 30% 违约金,这是写在产品口径里的
   */
  async createStayAftersale(orderNo: string, kind: string,
                            note: string): Promise<Record<string, Object>> {
    const body: Record<string, Object> = { 'kind': kind, 'note': note };
    const data = await this.api.request('POST',
      `/stays/orders/${orderNo}/aftersale`, body);
    return (data ?? {}) as Record<string, Object>;
  }

  async myStayAftersale(orderNo: string): Promise<Record<string, Object> | null> {
    const data = await this.api.request('GET',
      `/stays/orders/${orderNo}/aftersale`);
    return data as Record<string, Object> | null;
  }

  // ---------- 跑腿:帮买加价协商 ----------

  /**
   * 骑手问"要多花钱吗"的回复。
   *
   * 同意 → 骑手照买,差额之后结;不同意 → 按买不到处理,
   * 商品款全额退,跑腿费只收骑手到店那一段。
   * **骑手正站在货架前等回复**,所以这个入口要显眼、要快。
   */
  async decideRaise(orderNo: string, agree: boolean): Promise<Order> {
    const body: Record<string, Object> = { 'agree': agree };
    const data = await this.api.request('POST',
      `/errands/${orderNo}/raise/decide`, body);
    return data as Order;
  }

  // ---------- 拼单 ----------

  /** 开一个拼单车。返回里带 code,分享给朋友用 */
  async openGroupCart(merchantId: number): Promise<Record<string, Object>> {
    const body: Record<string, Object> = { 'merchant_id': merchantId };
    const data = await this.api.request('POST', '/group-carts', body);
    return (data ?? {}) as Record<string, Object>;
  }

  async joinGroupCart(code: string): Promise<Record<string, Object>> {
    const data = await this.api.request('POST', `/group-carts/${code}/join`);
    return (data ?? {}) as Record<string, Object>;
  }

  async getGroupCart(code: string): Promise<Record<string, Object>> {
    const data = await this.api.request('GET', `/group-carts/${code}`);
    return (data ?? {}) as Record<string, Object>;
  }

  async setGroupCartItem(code: string, dishId: number,
                         quantity: number): Promise<Record<string, Object>> {
    const body: Record<string, Object> = {
      'dish_id': dishId, 'quantity': quantity,
    };
    const data = await this.api.request('POST', `/group-carts/${code}/items`, body);
    return (data ?? {}) as Record<string, Object>;
  }

  /** 发起人锁车并下单。**一次性**:锁了就不能再改 */
  async lockGroupCart(code: string): Promise<Record<string, Object>> {
    const data = await this.api.request('POST', `/group-carts/${code}/lock`, {});
    return (data ?? {}) as Record<string, Object>;
  }

  // ---------- 实名认证 ----------

  /** 实名状态。酒类订单要用 */
  async identityStatus(): Promise<Record<string, Object>> {
    const data = await this.api.request('GET', '/auth/identity-status');
    return (data ?? {}) as Record<string, Object>;
  }

  /**
   * 提交实名。**身份证号发出去就不再留在客户端** ——
   * 服务端加密落库,这边不缓存、不写偏好
   */
  async verifyIdentity(realName: string, idNo: string): Promise<Record<string, Object>> {
    const body: Record<string, string> = { 'real_name': realName, 'id_no': idNo };
    const data = await this.api.request('POST', '/auth/verify-identity', body);
    return (data ?? {}) as Record<string, Object>;
  }

  // ---------- 自助退款与加急 ----------

  /** 能不能自助退。服务端判,客户端别自己算规则 */
  async selfRefundCheck(orderNo: string): Promise<Record<string, Object>> {
    const data = await this.api.request('GET', `/orders/${orderNo}/self-refund/check`);
    return (data ?? {}) as Record<string, Object>;
  }

  async selfRefund(orderNo: string): Promise<Order> {
    const data = await this.api.request('POST', `/orders/${orderNo}/self-refund`);
    return data as Order;
  }

  /** 加急小费。**纯用户出、100% 归骑手,平台不补贴也不抽** */
  async boostTip(orderNo: string, addCents: number): Promise<Order> {
    const body: Record<string, Object> = { 'add_cents': addCents };
    const data = await this.api.request('POST', `/orders/${orderNo}/boost-tip`, body);
    return data as Order;
  }

  /** 加菜:关联原单、免配送费、随原单配送 */
  async appendOrder(parentOrderNo: string, merchantId: number,
                    items: OrderItemIn[]): Promise<Order> {
    const body: Record<string, Object> = {
      'merchant_id': merchantId,
      'items': items,
      'pickup': false,
      'tip_cents': 0,
      'append_to': parentOrderNo,
    };
    const data = await this.api.request('POST', '/orders', body);
    return data as Order;
  }

  // ---------- 住宿 ----------

  /** 找酒店。**离店才收 5%**:订单取消、客人未入住,平台分文不取 */
  async hotels(query: Record<string, string>): Promise<Record<string, Object>[]> {
    const data = await this.api.request('GET', '/stays/hotels', undefined, query);
    return (data ?? []) as Record<string, Object>[];
  }

  async hotelDetail(hotelId: number): Promise<Record<string, Object>> {
    const data = await this.api.request('GET', `/stays/hotels/${hotelId}`);
    return (data ?? {}) as Record<string, Object>;
  }

  /** 酒店点评 */
  async hotelReviews(hotelId: number): Promise<Record<string, Object>[]> {
    const data = await this.api.request('GET', `/stays/hotels/${hotelId}/reviews`);
    return (data ?? []) as Record<string, Object>[];
  }

  async createStayOrder(body: Record<string, Object>): Promise<Record<string, Object>> {
    const data = await this.api.request('POST', '/stays/orders', body);
    return (data ?? {}) as Record<string, Object>;
  }

  async stayOrderDetail(orderNo: string): Promise<Record<string, Object>> {
    const data = await this.api.request('GET', `/stays/orders/${orderNo}`);
    return (data ?? {}) as Record<string, Object>;
  }

  async myStayOrders(): Promise<Record<string, Object>[]> {
    const data = await this.api.request('GET', '/stays/orders/mine');
    return (data ?? []) as Record<string, Object>[];
  }

  /** 取消试算。**先算清楚扣多少再让用户点确认**,不做"点了才知道" */
  async stayCancelPreview(orderNo: string): Promise<Record<string, Object>> {
    const data = await this.api.request('GET',
      `/stays/orders/${orderNo}/cancel-preview`);
    return (data ?? {}) as Record<string, Object>;
  }

  async cancelStayOrder(orderNo: string): Promise<Record<string, Object>> {
    const data = await this.api.request('POST', `/stays/orders/${orderNo}/cancel`);
    return (data ?? {}) as Record<string, Object>;
  }

  // ---------- 跑腿 ----------

  /**
   * 跑腿报价。**服务费单列,不藏在总价里** ——
   * 外卖的配送费我们一分不抽、跑腿收 2%,两个口径同时存在,
   * 不在下单页写清楚就会变成"你不是说配送费不抽吗"
   */
  async errandQuote(body: Record<string, Object>): Promise<Record<string, Object>> {
    const data = await this.api.request('POST', '/errands/quote', body);
    return (data ?? {}) as Record<string, Object>;
  }

  /** 帮送下单。**建出来是待支付,必须立刻接支付** —— 安卓端在这里丢过单 */
  async createErrand(body: Record<string, Object>): Promise<Order> {
    const data = await this.api.request('POST', '/errands', body);
    return data as Order;
  }

  async errandBuyQuote(body: Record<string, Object>): Promise<Record<string, Object>> {
    const data = await this.api.request('POST', '/errands/buy/quote', body);
    return (data ?? {}) as Record<string, Object>;
  }

  async createErrandBuy(body: Record<string, Object>): Promise<Order> {
    const data = await this.api.request('POST', '/errands/buy', body);
    return data as Order;
  }

  // ---------- 我的:券、发票、实名、工单、公告 ----------

  async myInvoices(): Promise<Record<string, Object>[]> {
    const data = await this.api.request('GET', '/invoices/mine');
    return (data ?? []) as Record<string, Object>[];
  }

  async createInvoice(body: Record<string, Object>): Promise<Record<string, Object>> {
    const data = await this.api.request('POST', '/invoices', body);
    return (data ?? {}) as Record<string, Object>;
  }

  async myTickets(): Promise<Record<string, Object>[]> {
    const data = await this.api.request('GET', '/tickets/mine');
    return (data ?? []) as Record<string, Object>[];
  }

  async createTicket(body: Record<string, Object>): Promise<Record<string, Object>> {
    const data = await this.api.request('POST', '/tickets', body);
    return (data ?? {}) as Record<string, Object>;
  }

  /** 平台公告。audience 传 user */
  async announcements(): Promise<Record<string, Object>[]> {
    const data = await this.api.request('GET', '/announcements', undefined,
      { 'audience': 'user' } as Record<string, string>);
    return (data ?? []) as Record<string, Object>[];
  }

  /** 帮助中心 FAQ。服务端下发,改文案不用发版 */
  async faq(): Promise<Record<string, Object>[]> {
    const data = await this.api.request('GET', '/support/faq');
    return (data ?? []) as Record<string, Object>[];
  }

  /** 邀请信息:我的邀请码、已邀请人数 */
  async myReferral(): Promise<Record<string, Object>> {
    const data = await this.api.request('GET', '/referrals/me');
    return (data ?? {}) as Record<string, Object>;
  }

  /** 填别人的邀请码(注册 24 小时内) */
  async claimReferral(code: string): Promise<Record<string, Object>> {
    const body: Record<string, string> = { 'code': code };
    const data = await this.api.request('POST', '/referrals/claim', body);
    return (data ?? {}) as Record<string, Object>;
  }

  // ---------- 商家证照与明厨亮灶(法定公示) ----------

  /**
   * 证照公示。**餐饮商家要同时公示营业执照和食品经营许可证** ——
   * 总局令第 123 号第十一条,不是可选项
   */
  async merchantLicenses(merchantId: number): Promise<Record<string, Object>[]> {
    const data = await this.api.request('GET', `/merchants/${merchantId}/licenses`);
    return (data ?? []) as Record<string, Object>[];
  }

  async kitchenCamOf(merchantId: number): Promise<Record<string, Object>> {
    const data = await this.api.request('GET',
      `/merchants/${merchantId}/kitchen-cam`);
    return (data ?? {}) as Record<string, Object>;
  }

  // ---------- 透明中心(全部公开,不需要登录) ----------

  private async transparency(path: string): Promise<Record<string, Object>> {
    const data = await this.api.request('GET', `/transparency/${path}`);
    return (data ?? {}) as Record<string, Object>;
  }

  /** 每日核账。**对不上的那天要看得出来**,不是只报"一切正常" */
  auditPublic(): Promise<Record<string, Object>> {
    return this.transparency('audit');
  }

  /** 佣金收进来多少、花到哪去了、平台留存多少 */
  fundsPublic(): Promise<Record<string, Object>> {
    return this.transparency('funds');
  }

  /** 平台自己赔出去的钱(超时券/餐损/退款) */
  compensationPublic(): Promise<Record<string, Object>> {
    return this.transparency('compensation');
  }

  /** 月度财报(实时聚合,不是手工填的) */
  reportsPublic(): Promise<Record<string, Object>> {
    return this.transparency('reports');
  }

  /** 近 30 天分账公平性证据 */
  fairnessPublic(): Promise<Record<string, Object>> {
    return this.transparency('fairness');
  }

  /** 线上运行版本 + 与仓库一致的更新日志 */
  changelogPublic(): Promise<Record<string, Object>> {
    return this.transparency('changelog');
  }

  /** 90 天可用率。**探针缺档按不可用算**,不给自己留面子 */
  uptimePublic(): Promise<Record<string, Object>> {
    return this.transparency('uptime');
  }

  /** 明厨亮灶发标/验标/撤标规则 */
  kitchenCamSpec(): Promise<Record<string, Object>> {
    return this.transparency('kitchen-cam');
  }

  /** 规则变更留痕、反作弊处置、客服质量 */
  governancePublic(): Promise<Record<string, Object>> {
    return this.transparency('governance');
  }

  /** 派单算法公开说明 */
  dispatchSpec(): Promise<Record<string, Object>> {
    return this.transparency('dispatch');
  }

  /** 见证节点网络概览。ledger 路由没挂前缀,路径就是 /nodes/summary */
  async nodesSummary(): Promise<Record<string, Object>> {
    const data = await this.api.request('GET', '/nodes/summary');
    return (data ?? {}) as Record<string, Object>;
  }

  /** 平台统计概览(首页/信任页用) */
  async statsOverview(): Promise<Record<string, Object>> {
    const data = await this.api.request('GET', '/stats/overview');
    return (data ?? {}) as Record<string, Object>;
  }

  // ---------- 订单后链路 ----------

  /** 订单事件流(时间轴)。每一步都有时间戳,不是客户端猜的 */
  async orderEvents(orderNo: string): Promise<OrderEvent[]> {
    const data = await this.api.request('GET', `/orders/${orderNo}/events`);
    return (data ?? []) as OrderEvent[];
  }

  /** 骑手位置。**只在配送中有值**,其余状态返回 null */
  async riderLocation(orderNo: string): Promise<RiderLocation | null> {
    const data = await this.api.request('GET', `/orders/${orderNo}/rider-location`);
    return data as RiderLocation | null;
  }

  /** 催单。控频与上限都在服务端,客户端不用自己算 */
  async urgeOrder(orderNo: string): Promise<Record<string, Object>> {
    const data = await this.api.request('POST', `/orders/${orderNo}/urge`);
    return (data ?? {}) as Record<string, Object>;
  }

  /** 用户取消订单。服务端判能不能取消(商家接单前免费、接单 2 分钟内可反悔) */
  async cancelOrder(orderNo: string, reason: string): Promise<Order> {
    const body: Record<string, string> = {
      'to_status': 'cancelled',
      'reason': reason,
    };
    const data = await this.api.request('POST',
      `/orders/${orderNo}/transition`, body);
    return data as Order;
  }

  /** 确认收货 */
  async confirmReceived(orderNo: string): Promise<Order> {
    const body: Record<string, string> = { 'to_status': 'completed', 'reason': '' };
    const data = await this.api.request('POST',
      `/orders/${orderNo}/transition`, body);
    return data as Order;
  }

  // ---------- 售后 ----------

  /** 申请售后。**图片是必传的** —— 有图才能快速判责,没图只能拖 */
  async createAfterSale(orderNo: string, reason: string,
                        images: string[]): Promise<AfterSale> {
    const body: Record<string, Object> = { 'reason': reason, 'images': images };
    const data = await this.api.request('POST',
      `/orders/${orderNo}/after-sale`, body);
    return data as AfterSale;
  }

  /** 本单的售后申请,没有返回 null */
  async orderAfterSale(orderNo: string): Promise<AfterSale | null> {
    const data = await this.api.request('GET', `/orders/${orderNo}/after-sale`);
    return data as AfterSale | null;
  }

  /** 退款逐笔明细。订单上的 refund_cents 是汇总,这里是流水 */
  async orderRefunds(orderNo: string): Promise<RefundRecord[]> {
    const data = await this.api.request('GET', `/orders/${orderNo}/refunds`);
    return (data ?? []) as RefundRecord[];
  }

  /**
   * 食品安全投诉。**红线通道,不经商家直达平台**,可附医疗凭证。
   * kind: foreign_object 异物 / spoiled 变质 / sick 食用后不适
   */
  async reportFoodSafety(orderNo: string, kind: string, description: string,
                         images: string[], medicalUrls: string[]): Promise<void> {
    const body: Record<string, Object> = {
      'order_no': orderNo,
      'kind': kind,
      'description': description,
      'images': images,
      'medical_urls': medicalUrls,
    };
    await this.api.request('POST', '/food-safety', body);
  }

  /** 本单的食安投诉状态,没投诉过返回 null */
  async foodSafetyOfOrder(orderNo: string): Promise<Record<string, Object> | null> {
    const data = await this.api.request('GET', `/food-safety/order/${orderNo}`);
    return data as Record<string, Object> | null;
  }

  /** 我提交过的食安投诉 */
  async myFoodSafetyReports(): Promise<Record<string, Object>[]> {
    const data = await this.api.request('GET', '/food-safety/mine');
    return (data ?? []) as Record<string, Object>[];
  }

  // ---------- 评价 ----------

  /** 本单的评价,没评过返回 null */
  async orderReview(orderNo: string): Promise<Review | null> {
    const data = await this.api.request('GET', `/orders/${orderNo}/review`);
    return data as Review | null;
  }

  /** 提交评价。商家与骑手分开打分,标签也分开挂 */
  async submitReview(orderNo: string, merchantRating: number,
                     riderRating: number, comment: string,
                     isAnonymous: boolean, imageUrls: string[],
                     tags: string[], riderTags: string[]): Promise<Review> {
    const body: Record<string, Object> = {
      'merchant_rating': merchantRating,
      'comment': comment,
      'image_urls': imageUrls,
      'tags': tags,
      'rider_tags': riderTags,
      'is_anonymous': isAnonymous,
    };
    if (riderRating > 0) {
      body['rider_rating'] = riderRating;
    }
    const data = await this.api.request('POST', `/orders/${orderNo}/review`, body);
    return data as Review;
  }

  /** 追评(7 天内一次) */
  async appendReview(reviewId: number, text: string): Promise<Review> {
    const body: Record<string, string> = { 'append_comment': text };
    const data = await this.api.request('POST',
      `/reviews/${reviewId}/append`, body);
    return data as Review;
  }

  // ---------- 订单内沟通 ----------

  /** 聊天记录。peer: rider / merchant */
  async orderMessages(orderNo: string, peer: string): Promise<Record<string, Object>> {
    const data = await this.api.request('GET', `/orders/${orderNo}/messages`,
      undefined, { 'peer': peer } as Record<string, string>);
    return (data ?? {}) as Record<string, Object>;
  }

  async sendOrderMessage(orderNo: string, to: string, content: string): Promise<void> {
    const body: Record<string, string> = {
      'to': to, 'kind': 'text', 'content': content,
    };
    await this.api.request('POST', `/orders/${orderNo}/messages`, body);
  }

  /** 该单未读数。**不接这个,骑手发消息用户完全不知道** */
  async orderUnread(orderNo: string): Promise<number> {
    const data = await this.api.request('GET', `/orders/${orderNo}/unread`);
    const map: Record<string, Object> = (data ?? {}) as Record<string, Object>;
    const n: Object = map['unread'] ?? 0;
    return typeof n === 'number' ? n : 0;
  }

  /** 微信统一下单。商户号未配置时服务端返回 503 */
  async wechatPrepay(orderNo: string): Promise<WechatPrepay> {
    const data = await this.api.request('POST', `/orders/${orderNo}/pay/wechat`);
    return data as WechatPrepay;
  }

  /** 模拟支付。生产 MOCK_PAY_ENABLED=false 时返回 403,这是对的 */
  async mockPay(orderNo: string): Promise<Order> {
    const data = await this.api.request('POST', `/orders/${orderNo}/pay/mock`);
    return data as Order;
  }
}
