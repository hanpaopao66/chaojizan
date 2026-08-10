import { Api } from './Api';
import { AfterSale, DayStat, Dish, LoginResult, MerchantOrder, Review, Shop,
  SmsCodeResult, Wallet, Withdrawal } from '../model/Models';

/**
 * 商家端接口层。
 *
 * 对着安卓端 `apps/merchant_app/lib` 里扫出来的 **102 个接口**逐条打勾建的:
 *
 * ```bash
 * grep -rhoE "api\.[a-zA-Z][a-zA-Z0-9]*\(" apps/merchant_app/lib \
 *   | sed 's/api\.//;s/(//' | sort -u
 * ```
 *
 * 方法名、路径、动词与 `packages/shared/lib/src/api_client.dart` 一一对应 ——
 * **故意不改名**。改了之后两端对同一个接口有两个叫法,查问题时得先做一次
 * 翻译,而这类翻译工作最后总会漏。
 *
 * 所有请求都经 [Api],不许在页面里自己 `http.createHttp()`(理由见 Api.ets)。
 */
export class MerchantApi {
  private api: Api = Api.get();

  /**
   * 当前操作的店。
   *
   * ⚠️ **这个值靠 `X-Shop-Id` 请求头传给服务端**(见 Api.ets),
   * 不是靠路径参数。连锁老板切店时**必须同时**换掉:这个头、
   * WebSocket 连接、营业开关、今日营业额、订单列表 ——
   * 漏掉任何一处就是「切到二店,屏幕上还是总店的单」,
   * 而他会照着总店的单去二店备餐。
   *
   * 单店商家这里是 null,服务端按账号直接定位。
   */
  get shopId(): number | null {
    return this.api.shopId;
  }

  set shopId(id: number | null) {
    this.api.shopId = id;
  }

  get baseUrl(): string {
    return this.api.baseUrl;
  }

  resolveUrl(url: string): string {
    return this.api.resolveUrl(url);
  }

  // ==================== 登录 ====================

  async sendSmsCode(phone: string): Promise<SmsCodeResult> {
    const data: object | null = await this.api.request(
        'POST', '/auth/sms/send', { phone: phone } as object);
    return (data ?? {}) as SmsCodeResult;
  }

  async loginBySms(phone: string, code: string): Promise<LoginResult> {
    const data: object | null = await this.api.request('POST', '/auth/sms/login',
        { phone: phone, code: code, role: 'merchant' } as object);
    return data as LoginResult;
  }

  // ==================== 店铺 ====================

  async myShop(): Promise<Shop> {
    return await this.api.request('GET', '/merchants/me') as Shop;
  }

  /**
   * 我的品牌与门店列表。
   *
   * 单店商家也能调:brand 为 null、shops 只有一家 —— 门店选择器用同一份
   * 数据,客户端不用为「是不是连锁」分两套逻辑。
   *
   * ⚠️ **冷启动必须先调它再调 [myShop]**:连锁账号在没选门店时
   * `/merchants/me` 是 404(后端不猜是哪家),顺序反了会把连锁老板
   * 一路带进「还没开店」的入驻引导。
   */
  async myBrand(): Promise<Record<string, Object>> {
    const data: object | null = await this.api.request('GET', '/brands/me');
    return (data ?? {}) as Record<string, Object>;
  }

  async brandOverview(): Promise<Record<string, Object>> {
    const data: object | null = await this.api.request(
        'GET', '/brands/me/overview');
    return (data ?? {}) as Record<string, Object>;
  }

  async createBrand(name: string, shopId: number): Promise<Record<string, Object>> {
    const data: object | null = await this.api.request('POST', '/brands/me',
        { name: name, shop_id: shopId } as object);
    return (data ?? {}) as Record<string, Object>;
  }

  async openBrandShop(body: object): Promise<Record<string, Object>> {
    const data: object | null = await this.api.request(
        'POST', '/brands/me/shops', body);
    return (data ?? {}) as Record<string, Object>;
  }

  async updateShop(patch: object): Promise<Shop> {
    return await this.api.request('PATCH', '/merchants/me', patch) as Shop;
  }

  async setShopOpen(isOpen: boolean): Promise<Shop> {
    return this.updateShop({ is_open: isOpen } as object);
  }

  async applyShop(body: object): Promise<Shop> {
    return await this.api.request('POST', '/merchants', body) as Shop;
  }

  /** 临时歇业:关店 + 到点自动恢复(区别于手动关店忘了开) */
  async restShop(hours?: number, untilClose?: boolean): Promise<Shop> {
    const body: Record<string, Object> = {};
    if (hours !== undefined) {
      body['hours'] = hours;
    }
    if (untilClose === true) {
      body['until_close'] = true;
    }
    return await this.api.request('POST', '/merchants/me/rest', body) as Shop;
  }

  /** 高峰忙碌模式:延长出餐承诺 / 暂停接单 */
  async setBusy(body: object): Promise<object> {
    const data: object | null = await this.api.request(
        'POST', '/merchants/me/busy', body);
    return data ?? {};
  }

  async merchantPrepTime(): Promise<Record<string, Object>> {
    const data: object | null = await this.api.request(
        'GET', '/merchants/me/prep-time');
    return (data ?? {}) as Record<string, Object>;
  }

  async merchantKitchenCam(): Promise<Record<string, Object>> {
    const data: object | null = await this.api.request(
        'GET', '/merchants/me/kitchen-cam');
    return (data ?? {}) as Record<string, Object>;
  }

  async setMerchantKitchenCam(body: object): Promise<object> {
    const data: object | null = await this.api.request(
        'PUT', '/merchants/me/kitchen-cam', body);
    return data ?? {};
  }

  async removeMerchantKitchenCam(): Promise<void> {
    await this.api.request('DELETE', '/merchants/me/kitchen-cam');
  }

  async merchantRules(): Promise<Record<string, Object>> {
    const data: object | null = await this.api.request(
        'GET', '/merchants/me/rules');
    return (data ?? {}) as Record<string, Object>;
  }

  async merchantPromo(): Promise<Record<string, Object>> {
    const data: object | null = await this.api.request(
        'GET', '/merchants/me/promo');
    return (data ?? {}) as Record<string, Object>;
  }

  // ==================== 订单 ====================

  /**
   * 我店的订单。
   *
   * ⚠️ 拉失败**绝不能静默** —— `_orders` 同时驱动订单列表和持续催单语音,
   * 拉不到时列表是空的、语音不响,商家看到的是「一切正常,今天没单」,
   * 实际上单在往里进。安卓端为此翻过车,见 DEV-PROMPTS-27 #237。
   */
  async myOrders(): Promise<MerchantOrder[]> {
    const data: object | null = await this.api.request('GET', '/orders');
    return (data ?? []) as MerchantOrder[];
  }

  /** 状态流转:接单 / 出餐 / 开始配送 */
  async transition(orderNo: string, to: string, reason?: string):
      Promise<MerchantOrder> {
    const body: Record<string, Object> = { to: to };
    if (reason !== undefined && reason.length > 0) {
      body['reason'] = reason;
    }
    return await this.api.request(
        'POST', `/orders/${orderNo}/transition`, body) as MerchantOrder;
  }

  /** 自取核销:核对取餐码 */
  async pickupVerify(orderNo: string, code: string): Promise<MerchantOrder> {
    return await this.api.request('POST', `/orders/${orderNo}/pickup-verify`,
        { code: code } as object) as MerchantOrder;
  }

  /** 缺货退款:按菜退,不整单退 */
  async refundItem(orderNo: string, dishId: number, quantity: number):
      Promise<MerchantOrder> {
    return await this.api.request('POST', `/orders/${orderNo}/refund-item`,
        { dish_id: dishId, quantity: quantity } as object) as MerchantOrder;
  }

  /** 回复顾客催单 */
  async urgeReply(orderNo: string, content: string): Promise<void> {
    await this.api.request('POST', `/orders/${orderNo}/urge-reply`,
        { content: content } as object);
  }

  async riderLocation(orderNo: string): Promise<Record<string, Object>> {
    const data: object | null = await this.api.request(
        'GET', `/orders/${orderNo}/rider-location`);
    return (data ?? {}) as Record<string, Object>;
  }

  /** 云打印补打 */
  async reprintOrder(orderNo: string): Promise<void> {
    await this.api.request('POST', `/merchants/me/orders/${orderNo}/print`);
  }

  // ==================== 看板 ====================

  async merchantToday(): Promise<Record<string, Object>> {
    const data: object | null = await this.api.request(
        'GET', '/merchants/me/today');
    return (data ?? {}) as Record<string, Object>;
  }

  async merchantTodos(): Promise<Record<string, Object>> {
    const data: object | null = await this.api.request(
        'GET', '/merchants/me/todos');
    return (data ?? {}) as Record<string, Object>;
  }

  async merchantTrend(weeks: number): Promise<Record<string, Object>> {
    const data: object | null = await this.api.request(
        'GET', '/merchants/me/trend', undefined, { weeks: `${weeks}` });
    return (data ?? {}) as Record<string, Object>;
  }

  async merchantFunnel(): Promise<Record<string, Object>> {
    const data: object | null = await this.api.request(
        'GET', '/merchants/me/funnel');
    return (data ?? {}) as Record<string, Object>;
  }

  async merchantAnalytics(days: number): Promise<Record<string, Object>> {
    const data: object | null = await this.api.request(
        'GET', '/merchants/me/analytics', undefined, { days: `${days}` });
    return (data ?? {}) as Record<string, Object>;
  }

  async merchantQuality(): Promise<Record<string, Object>> {
    const data: object | null = await this.api.request(
        'GET', '/merchants/me/quality');
    return (data ?? {}) as Record<string, Object>;
  }

  async merchantWinback(): Promise<Record<string, Object>> {
    const data: object | null = await this.api.request(
        'GET', '/merchants/me/winback');
    return (data ?? {}) as Record<string, Object>;
  }

  async merchantStocking(meal?: string): Promise<Record<string, Object>> {
    const query: Record<string, string> | undefined =
        (meal === undefined || meal.length === 0) ? undefined : { meal: meal };
    const data: object | null = await this.api.request(
        'GET', '/merchants/me/stocking', undefined, query);
    return (data ?? {}) as Record<string, Object>;
  }

  // ==================== 菜品 ====================

  async myDishes(): Promise<Dish[]> {
    const data: object | null = await this.api.request(
        'GET', '/merchants/me/dishes');
    return (data ?? []) as Dish[];
  }

  async addDish(body: object): Promise<Dish> {
    return await this.api.request(
        'POST', '/merchants/me/dishes', body) as Dish;
  }

  async updateDish(dishId: number, patch: object): Promise<Dish> {
    return await this.api.request(
        'PATCH', `/merchants/me/dishes/${dishId}`, patch) as Dish;
  }

  /** 估清(今日售罄):库存清零打标,次日 04:00 自动恢复 */
  async sellOutDish(dishId: number): Promise<Dish> {
    return await this.api.request(
        'POST', `/merchants/me/dishes/${dishId}/sell-out`) as Dish;
  }

  async cancelSellOut(dishId: number): Promise<Dish> {
    return await this.api.request(
        'POST', `/merchants/me/dishes/${dishId}/sell-out/cancel`) as Dish;
  }

  async batchStock(items: object[]): Promise<void> {
    await this.api.request('POST', '/merchants/me/dishes/batch-stock',
        { items: items } as object);
  }

  /** 置顶:只改这一道的 sort,不整体重排 */
  async reorderDishes(items: object[]): Promise<void> {
    await this.api.request('POST', '/merchants/me/dishes/reorder',
        { items: items } as object);
  }

  // ==================== 对账 ====================

  async financeDaily(): Promise<DayStat[]> {
    const data: object | null = await this.api.request(
        'GET', '/merchants/me/finance/daily');
    return (data ?? []) as DayStat[];
  }

  async financeOrders(day: string): Promise<MerchantOrder[]> {
    const data: object | null = await this.api.request(
        'GET', '/merchants/me/finance/orders', undefined, { day: day });
    return (data ?? []) as MerchantOrder[];
  }

  async merchantWallet(): Promise<Wallet> {
    return await this.api.request('GET', '/merchants/me/wallet') as Wallet;
  }

  async merchantWithdrawals(): Promise<Withdrawal[]> {
    const data: object | null = await this.api.request(
        'GET', '/merchants/me/withdrawals');
    return (data ?? []) as Withdrawal[];
  }

  async requestMerchantWithdrawal(amountCents: number): Promise<Withdrawal> {
    return await this.api.request('POST', '/merchants/me/withdrawals',
        { amount_cents: amountCents } as object) as Withdrawal;
  }

  /** 阶梯佣金:单量越大费率越低,5% 永远是上限,只降不升 */
  async merchantCommissionTier(): Promise<Record<string, Object>> {
    const data: object | null = await this.api.request(
        'GET', '/merchants/me/commission-tier');
    return (data ?? {}) as Record<string, Object>;
  }

  /** 对账单 CSV。**返回的是纯文本不是 JSON**,单独走一条路 */
  async merchantStatementCsv(month: string): Promise<string> {
    return this.api.requestText(
        'GET', '/merchants/me/statement.csv', { month: month });
  }

  async invoiceSummary(period: string): Promise<Record<string, Object>> {
    const data: object | null = await this.api.request(
        'GET', '/invoices/summary', undefined, { period: period });
    return (data ?? {}) as Record<string, Object>;
  }

  async myInvoices(): Promise<Record<string, Object>[]> {
    const data: object | null = await this.api.request('GET', '/invoices/mine');
    return (data ?? []) as Record<string, Object>[];
  }

  async applyInvoice(body: object): Promise<void> {
    await this.api.request('POST', '/invoices', body);
  }

  // ==================== 评价与售后 ====================

  async myReviews(maxRating?: number, unreplied?: boolean, before?: number):
      Promise<Review[]> {
    const query: Record<string, string> = {};
    if (maxRating !== undefined) {
      query['max_rating'] = `${maxRating}`;
    }
    if (unreplied === true) {
      query['unreplied'] = 'true';
    }
    if (before !== undefined) {
      query['before'] = `${before}`;
    }
    const data: object | null = await this.api.request(
        'GET', '/merchants/me/reviews', undefined,
        Object.keys(query).length === 0 ? undefined : query);
    return (data ?? []) as Review[];
  }

  async replyReview(reviewId: number, text: string): Promise<Review> {
    return await this.api.request(
        'POST', `/merchants/me/reviews/${reviewId}/reply`,
        { reply: text } as object) as Review;
  }

  async replyAppendReview(reviewId: number, text: string): Promise<Review> {
    return await this.api.request(
        'POST', `/merchants/me/reviews/${reviewId}/append-reply`,
        { reply: text } as object) as Review;
  }

  async myReviewTagStats(): Promise<Record<string, Object>> {
    const data: object | null = await this.api.request(
        'GET', '/merchants/me/reviews/tag-stats');
    return (data ?? {}) as Record<string, Object>;
  }

  async ratingOverview(): Promise<Record<string, Object>> {
    const data: object | null = await this.api.request(
        'GET', '/merchants/me/reviews/overview');
    return (data ?? {}) as Record<string, Object>;
  }

  async replyTemplates(): Promise<Record<string, Object>[]> {
    const data: object | null = await this.api.request(
        'GET', '/merchants/me/reply-templates');
    return (data ?? []) as Record<string, Object>[];
  }

  async myAfterSales(status?: string): Promise<AfterSale[]> {
    const query: Record<string, string> | undefined =
        status === undefined ? undefined : { status: status };
    const data: object | null = await this.api.request(
        'GET', '/merchants/me/after-sales', undefined, query);
    return (data ?? []) as AfterSale[];
  }

  /** 同意即认责,从结算款扣。都必须给用户一句话回复 */
  async processAfterSale(id: number, accept: boolean, reply: string):
      Promise<AfterSale> {
    const action: string = accept ? 'accept' : 'reject';
    return await this.api.request('POST', `/after-sales/${id}/${action}`,
        { reply: reply } as object) as AfterSale;
  }

  async myAppeals(): Promise<Record<string, Object>[]> {
    const data: object | null = await this.api.request('GET', '/appeals/mine');
    return (data ?? []) as Record<string, Object>[];
  }

  async submitAppeal(body: object): Promise<void> {
    await this.api.request('POST', '/appeals', body);
  }

  // ==================== 营销 ====================

  async myShopCouponBatches(): Promise<Record<string, Object>[]> {
    const data: object | null = await this.api.request(
        'GET', '/merchants/me/coupon-batches');
    return (data ?? []) as Record<string, Object>[];
  }

  async createShopCouponBatch(body: object): Promise<void> {
    await this.api.request('POST', '/merchants/me/coupon-batches', body);
  }

  async toggleShopCouponBatch(batchId: number): Promise<void> {
    await this.api.request(
        'POST', `/merchants/me/coupon-batches/${batchId}/toggle`);
  }

  async myVoucherDeals(): Promise<Record<string, Object>[]> {
    const data: object | null = await this.api.request('GET', '/vouchers/mine');
    return (data ?? []) as Record<string, Object>[];
  }

  async createVoucher(body: object): Promise<void> {
    await this.api.request('POST', '/vouchers', body);
  }

  /** 团购券核销。核销才收 2%,未核销随时全额退 */
  async redeemVoucher(code: string): Promise<Record<string, Object>> {
    const data: object | null = await this.api.request('POST', '/vouchers/redeem',
        { code: code } as object);
    return (data ?? {}) as Record<string, Object>;
  }

  // ==================== 消息 ====================

  async merchantMessages(category?: string, before?: number):
      Promise<Record<string, Object>> {
    const query: Record<string, string> = {};
    if (category !== undefined && category.length > 0) {
      query['category'] = category;
    }
    if (before !== undefined) {
      query['before'] = `${before}`;
    }
    const data: object | null = await this.api.request(
        'GET', '/merchants/me/messages', undefined,
        Object.keys(query).length === 0 ? undefined : query);
    return (data ?? {}) as Record<string, Object>;
  }

  async merchantMessagesRead(): Promise<void> {
    await this.api.request('POST', '/merchants/me/messages/read');
  }

  // ==================== 资质与合规 ====================

  async healthCerts(): Promise<Record<string, Object>[]> {
    const data: object | null = await this.api.request(
        'GET', '/merchants/me/health-certs');
    return (data ?? []) as Record<string, Object>[];
  }

  async saveHealthCert(body: object): Promise<void> {
    await this.api.request('POST', '/merchants/me/health-certs', body);
  }

  async archiveHealthCert(id: number): Promise<void> {
    await this.api.request('DELETE', `/merchants/me/health-certs/${id}`);
  }

  async myLicenseRenewal(): Promise<Record<string, Object>> {
    const data: object | null = await this.api.request(
        'GET', '/merchants/me/license-renewal');
    return (data ?? {}) as Record<string, Object>;
  }

  async submitLicenseRenewal(body: object): Promise<void> {
    await this.api.request('POST', '/merchants/me/license-renewal', body);
  }

  /** 证照 OCR。服务端默认关,配了 OCR_ENDPOINT 才启用 */
  async ocrLicense(imageUrl: string): Promise<Record<string, Object>> {
    const data: object | null = await this.api.request('POST', '/ocr/license',
        { image_url: imageUrl } as object);
    return (data ?? {}) as Record<string, Object>;
  }

  // ==================== 进货台账 ====================

  async purchases(q?: string): Promise<Record<string, Object>> {
    const query: Record<string, string> | undefined =
        (q === undefined || q.length === 0) ? undefined : { q: q };
    const data: object | null = await this.api.request(
        'GET', '/merchants/me/purchases', undefined, query);
    return (data ?? {}) as Record<string, Object>;
  }

  async addPurchase(body: object): Promise<void> {
    await this.api.request('POST', '/merchants/me/purchases', body);
  }

  async deletePurchase(id: number): Promise<void> {
    await this.api.request('DELETE', `/merchants/me/purchases/${id}`);
  }

  async purchaseSuppliers(): Promise<Record<string, Object>[]> {
    const data: object | null = await this.api.request(
        'GET', '/merchants/me/purchases/suppliers');
    return (data ?? []) as Record<string, Object>[];
  }

  // ==================== 打印机 ====================

  async printers(): Promise<Record<string, Object>> {
    const data: object | null = await this.api.request(
        'GET', '/merchants/me/printers');
    return (data ?? {}) as Record<string, Object>;
  }

  async addPrinter(body: object): Promise<void> {
    await this.api.request('POST', '/merchants/me/printers', body);
  }

  async removePrinter(id: number): Promise<void> {
    await this.api.request('DELETE', `/merchants/me/printers/${id}`);
  }

  // ==================== 店员 ====================

  async myStaff(): Promise<Record<string, Object>[]> {
    const data: object | null = await this.api.request(
        'GET', '/merchants/me/staff');
    return (data ?? []) as Record<string, Object>[];
  }

  async addStaff(phone: string, name: string): Promise<void> {
    await this.api.request('POST', '/merchants/me/staff',
        { phone: phone, name: name } as object);
  }

  async removeStaff(userId: number): Promise<void> {
    await this.api.request('DELETE', `/merchants/me/staff/${userId}`);
  }

  // ==================== 上传与地址 ====================

  async geoTips(keyword: string, lat?: number, lng?: number):
      Promise<Record<string, Object>[]> {
    const query: Record<string, string> = { keyword: keyword };
    if (lat !== undefined && lng !== undefined) {
      query['lat'] = `${lat}`;
      query['lng'] = `${lng}`;
    }
    const data: object | null = await this.api.request(
        'GET', '/geo/tips', undefined, query);
    return (data ?? []) as Record<string, Object>[];
  }

  async geoReverse(lat: number, lng: number): Promise<Record<string, Object>> {
    const data: object | null = await this.api.request('GET', '/geo/reverse',
        undefined, { lat: `${lat}`, lng: `${lng}` });
    return (data ?? {}) as Record<string, Object>;
  }

  // ==================== 微信特约商户进件 ====================
  //
  // ⚠️ 这条链路碰的是身份证号和银行账户,是整个商家端最敏感的一段。
  //
  // **客户端永远拿不到明文**:服务端把敏感字段 Fernet 加密落库,
  // 回给客户端的只有尾号(`*_tail`)。所以这里既不能"回填完整值",
  // 也不能因为输入框是空的就把服务端已存的值清掉 ——
  // 空输入框 + 服务端有尾号 = 之前存过了,**不算缺、不要覆盖**。

  async myApplyment(): Promise<Record<string, Object>> {
    const data: object | null = await this.api.request(
        'GET', '/merchants/me/applyment');
    return (data ?? {}) as Record<string, Object>;
  }

  /** 存进件资料。**只提交本次真填了的字段**,别把空串当"清空"发上去 */
  async saveApplyment(body: object): Promise<Record<string, Object>> {
    const data: object | null = await this.api.request(
        'PUT', '/merchants/me/applyment', body);
    return (data ?? {}) as Record<string, Object>;
  }

  // ==================== 酒店民宿 ====================

  async stayMerchantOrders(state: string): Promise<Record<string, Object>[]> {
    const data: object | null = await this.api.request(
        'GET', '/stays/me/orders', undefined, { state: state });
    return (data ?? []) as Record<string, Object>[];
  }

  async stayConfirm(orderNo: string): Promise<Record<string, Object>> {
    const data: object | null = await this.api.request(
        'POST', `/stays/me/orders/${orderNo}/confirm`);
    return (data ?? {}) as Record<string, Object>;
  }

  async stayReject(orderNo: string, reason: string):
      Promise<Record<string, Object>> {
    const data: object | null = await this.api.request(
        'POST', `/stays/me/orders/${orderNo}/reject`,
        { reason: reason } as object);
    return (data ?? {}) as Record<string, Object>;
  }

  async stayCheckin(orderNo: string): Promise<Record<string, Object>> {
    const data: object | null = await this.api.request(
        'POST', `/stays/me/orders/${orderNo}/checkin`);
    return (data ?? {}) as Record<string, Object>;
  }

  async stayCheckout(orderNo: string): Promise<Record<string, Object>> {
    const data: object | null = await this.api.request(
        'POST', `/stays/me/orders/${orderNo}/checkout`);
    return (data ?? {}) as Record<string, Object>;
  }

  async stayRoomTypes(): Promise<Record<string, Object>[]> {
    const data: object | null = await this.api.request(
        'GET', '/stays/me/room-types');
    return (data ?? []) as Record<string, Object>[];
  }

  async createRoomType(body: object): Promise<Record<string, Object>> {
    const data: object | null = await this.api.request(
        'POST', '/stays/me/room-types', body);
    return (data ?? {}) as Record<string, Object>;
  }

  async updateRoomType(id: number, patch: object):
      Promise<Record<string, Object>> {
    const data: object | null = await this.api.request(
        'PATCH', `/stays/me/room-types/${id}`, patch);
    return (data ?? {}) as Record<string, Object>;
  }

  /** 批量改价 / 改房量 / 关房。一次改一段日期,不是一天一天点 */
  async setStayCalendar(body: object): Promise<void> {
    await this.api.request('PUT', '/stays/me/calendar', body);
  }

  async merchantStayReviews(): Promise<Record<string, Object>[]> {
    const data: object | null = await this.api.request(
        'GET', '/stays/me/reviews');
    return (data ?? []) as Record<string, Object>[];
  }

  async replyStayReview(reviewId: number, reply: string):
      Promise<Record<string, Object>> {
    const data: object | null = await this.api.request(
        'POST', `/stays/me/reviews/${reviewId}/reply`,
        { reply: reply } as object);
    return (data ?? {}) as Record<string, Object>;
  }

  async merchantStayAftersales(): Promise<Record<string, Object>[]> {
    const data: object | null = await this.api.request(
        'GET', '/stays/me/aftersales');
    return (data ?? []) as Record<string, Object>[];
  }

  async respondStayAftersale(id: number, accept: boolean, reply: string):
      Promise<Record<string, Object>> {
    const data: object | null = await this.api.request(
        'POST', `/stays/me/aftersales/${id}/respond`,
        { accept: accept, reply: reply } as object);
    return (data ?? {}) as Record<string, Object>;
  }

}
