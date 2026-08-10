import { promptAction } from '@kit.ArkUI';
import { UserApi, CreateOrderBody, OrderItemIn } from '../common/UserApi';
import { ApiException } from '../common/Api';
import { Session } from '../common/Session';
import { isPaid, payOrder } from '../common/Pay';
import { Address, Coupon, DeliveryFeePreview, Merchant, Order } from '../model/Models';
import { CartLine, bestCoupon, choicesLabel, CouponVerdict, foodCents,
  judgeCoupon, manjianCents, packingCents, totalOffCents,
  unitCents } from '../common/Cart';
import { yuan } from '../common/Money';

/**
 * 结算页。
 *
 * 这一页最容易出错的地方是**选券**:服务端 `/coupons` 的 `usable`
 * 只判「未使用且未过期」,不含门槛。照着面额挑最大的那张,
 * 页面会显示"已省 10 元"而提交时被 409 打回 —— 用户看到的是
 * "说好的优惠不算数"。判定逻辑全部放在 `common/Cart.ets` 里,
 * 那份代码是照着服务端 `orders.py` 的下单分支逐行对齐的。
 *
 * 另一条:**金额变化后要重算券**。改份数、切自取都会让原来选的券失效,
 * 只在进页面时算一次的话,用户改完数量再提交照样 409。
 */
@Component
export struct CheckoutPage {
  merchant: Merchant | null = null;
  lines: CartLine[] = [];
  onPaid: (order: Order) => void = () => {};
  onNeedLogin: () => void = () => {};

  @State private addresses: Address[] = [];
  @State private pickedAddressId: number = 0;
  @State private coupons: Coupon[] = [];
  @State private pickedCouponId: number = 0;
  /** 用户手动选过券没有。手选之后金额变化只做失效检查,不再自动换 */
  @State private couponTouched: boolean = false;
  @State private remark: string = '';
  @State private pickup: boolean = false;
  @State private deliveryFee: number = 0;
  @State private inRange: boolean = true;
  @State private loading: boolean = true;
  @State private submitting: boolean = false;

  private api: UserApi = new UserApi();

  async aboutToAppear(): Promise<void> {
    if (!Session.get().isLoggedIn) {
      this.onNeedLogin();
      return;
    }
    await this.load();
  }

  private async load(): Promise<void> {
    this.loading = true;
    try {
      this.addresses = await this.api.addresses();
      const def: Address | undefined = this.addresses.find(
        (a: Address) => a.is_default === true);
      const first: Address | undefined =
        def !== undefined ? def : this.addresses[0];
      if (first !== undefined) {
        this.pickedAddressId = first.id;
        await this.refreshDeliveryFee(first);
      }
      this.coupons = await this.api.myCoupons();
      this.autoPickCoupon();
    } catch (e) {
      promptAction.showToast({ message: (e as ApiException).message });
    } finally {
      this.loading = false;
    }
  }

  private get address(): Address | null {
    const found: Address | undefined = this.addresses.find(
      (a: Address) => a.id === this.pickedAddressId);
    return found === undefined ? null : found;
  }

  private async refreshDeliveryFee(addr: Address): Promise<void> {
    if (this.merchant === null) {
      return;
    }
    try {
      const p: DeliveryFeePreview = await this.api.deliveryFeePreview(
        this.merchant.id, addr.lat, addr.lng);
      this.deliveryFee = p.delivery_fee_cents;
      this.inRange = p.in_range;
    } catch (e) {
      // 预览失败不该拦住下单,但也不能显示一个假的 0 ——
      // 提交时服务端会按真实费用算,这里标成"以下单为准"
      this.deliveryFee = -1;
      this.inRange = true;
    }
  }

  private get food(): number {
    return foodCents(this.lines);
  }

  private get packing(): number {
    return this.merchant === null ? 0 : packingCents(this.merchant, this.lines);
  }

  /** 当前选中的券的判定。金额一变这里就跟着变,不缓存 */
  private get pickedVerdict(): CouponVerdict | null {
    if (this.merchant === null || this.pickedCouponId === 0) {
      return null;
    }
    const c: Coupon | undefined = this.coupons.find(
      (x: Coupon) => x.id === this.pickedCouponId);
    if (c === undefined) {
      return null;
    }
    const v: CouponVerdict = judgeCoupon(c, this.merchant, this.food, this.packing);
    return v.usable ? v : null;
  }

  private autoPickCoupon(): void {
    if (this.merchant === null || this.couponTouched) {
      return;
    }
    const best: CouponVerdict | null =
      bestCoupon(this.coupons, this.merchant, this.food, this.packing);
    this.pickedCouponId = best === null ? 0 : best.coupon.id;
  }

  private get offCents(): number {
    if (this.merchant === null) {
      return 0;
    }
    return totalOffCents(this.merchant, this.food, this.packing, this.pickedVerdict);
  }

  private get payable(): number {
    const fee: number = this.pickup ? 0 : Math.max(this.deliveryFee, 0);
    const total: number = this.food + this.packing + fee - this.offCents;
    return total < 0 ? 0 : total;
  }

  private async submit(): Promise<void> {
    if (this.merchant === null || this.submitting) {
      return;
    }
    if (!this.pickup && this.address === null) {
      promptAction.showToast({ message: '请先选择收货地址' });
      return;
    }
    if (!this.pickup && !this.inRange) {
      promptAction.showToast({ message: '这个地址超出配送范围,换一个地址试试' });
      return;
    }
    this.submitting = true;
    try {
      const items: OrderItemIn[] = [];
      for (let i = 0; i < this.lines.length; i++) {
        const l: CartLine = this.lines[i];
        // choices 传的是规格/加料的**名字**,服务端按名字回查加价并重算单价
        items.push({
          dish_id: l.dish.id,
          quantity: l.quantity,
          choices: l.choices.length > 0 ? l.choices : undefined,
        });
      }
      const body: CreateOrderBody = {
        merchant_id: this.merchant.id,
        items: items,
        pickup: this.pickup,
        tip_cents: 0,
        remark: this.remark,
      };
      const v: CouponVerdict | null = this.pickedVerdict;
      if (v !== null) {
        body.coupon_id = v.coupon.id;
      }
      const addr: Address | null = this.address;
      if (!this.pickup && addr !== null) {
        body.address = addr.address;
        body.lat = addr.lat;
        body.lng = addr.lng;
        body.contact_name = addr.contact_name;
        body.contact_phone = addr.contact_phone;
      }
      const order: Order = await this.api.createOrder(body);
      // 建单成功就立刻进支付。**订单是 pending_payment 状态建出来的**,
      // 不接支付的话它会挂在那儿,15 分钟后被自动清扫
      const after: Order = await payOrder(this.api, order);
      this.onPaid(after);
      if (!isPaid(after)) {
        promptAction.showToast({
          message: '订单已保留为「待支付」,可在订单列表继续支付',
          duration: 3500,
        });
      }
    } catch (e) {
      // 服务端的 409 文案写得很具体(未达门槛/超出配送范围/售罄/打烊),
      // 原样显示比翻译成"下单失败"有用得多
      promptAction.showToast({ message: (e as ApiException).message, duration: 4000 });
    } finally {
      this.submitting = false;
    }
  }

  @Builder
  private couponSheet() {
    Column({ space: 8 }) {
      Text('选择优惠券').fontSize(16).fontWeight(FontWeight.Medium).width('100%');
      ForEach(this.coupons, (c: Coupon) => {
        Row() {
          Column({ space: 2 }) {
            Text(yuan(c.amount_cents))
              .fontSize(16).fontColor($r('app.color.brand'));
            Text(c.min_spend_cents > 0 ? `满 ${yuan(c.min_spend_cents)} 可用` : '无门槛')
              .fontSize(12).fontColor($r('app.color.ink_muted'));
          }
          .layoutWeight(1)
          .alignItems(HorizontalAlign.Start);
          // 不可用的券**置灰但不隐藏**,并写清楚差多少 ——
          // 藏起来用户会以为券没了,写出来他还有机会去凑单
          if (this.merchant !== null) {
            Text(judgeCoupon(c, this.merchant, this.food, this.packing).usable
              ? (this.pickedCouponId === c.id ? '已选' : '选它')
              : judgeCoupon(c, this.merchant, this.food, this.packing).reason)
              .fontSize(12)
              .fontColor(judgeCoupon(c, this.merchant, this.food, this.packing).usable
                ? $r('app.color.brand') : $r('app.color.ink_muted'));
          }
        }
        .width('100%')
        .padding(12)
        .backgroundColor($r('app.color.surface'))
        .borderRadius(10)
        .onClick(() => {
          if (this.merchant === null) {
            return;
          }
          if (!judgeCoupon(c, this.merchant, this.food, this.packing).usable) {
            return;
          }
          this.couponTouched = true;
          this.pickedCouponId = this.pickedCouponId === c.id ? 0 : c.id;
        });
      }, (c: Coupon) => `${c.id}`);
    }
    .width('100%')
    .padding(16);
  }

  @Builder
  private feeRow(label: string, value: string, highlight: boolean) {
    Row() {
      Text(label).fontSize(13).fontColor($r('app.color.ink_muted')).layoutWeight(1);
      Text(value).fontSize(13)
        .fontColor(highlight ? $r('app.color.earn') : $r('app.color.ink'));
    }
    .width('100%')
    .padding({ top: 5, bottom: 5 });
  }

  build() {
    Column() {
      if (this.loading) {
        Column() { LoadingProgress().width(36).height(36); }
        .width('100%').layoutWeight(1).justifyContent(FlexAlign.Center);
      } else {
        Scroll() {
          Column({ space: 10 }) {
            // 地址
            Column({ space: 6 }) {
              Text(this.pickup ? '到店自取' : '收货地址')
                .fontSize(13).fontColor($r('app.color.ink_muted')).width('100%');
              if (this.pickup) {
                Text(this.merchant?.address ?? '')
                  .fontSize(15).fontColor($r('app.color.ink')).width('100%');
              } else if (this.address !== null) {
                Text(this.address.address)
                  .fontSize(15).fontColor($r('app.color.ink')).width('100%');
                Text(`${this.address.contact_name} ${this.address.contact_phone}`)
                  .fontSize(12).fontColor($r('app.color.ink_muted')).width('100%');
                if (!this.inRange) {
                  Text('这个地址超出配送范围')
                    .fontSize(12).fontColor($r('app.color.brand')).width('100%');
                }
              } else {
                Text('还没有收货地址,先去「我的」添加一个')
                  .fontSize(14).fontColor($r('app.color.brand')).width('100%');
              }
              Row({ space: 8 }) {
                Text('到店自取(免配送费)')
                  .fontSize(13).fontColor($r('app.color.ink_muted')).layoutWeight(1);
                Toggle({ type: ToggleType.Switch, isOn: this.pickup })
                  .onChange((on: boolean) => {
                    this.pickup = on;
                    // 切自取会改变实付,券的可用性也可能变 —— 重算
                    this.autoPickCoupon();
                  });
              }
              .width('100%');
            }
            .width('100%').padding(16).backgroundColor($r('app.color.surface'))
            .alignItems(HorizontalAlign.Start);

            // 商品清单。**规格要显示出来** —— 用户点的是"大份加辣",
            // 结算页只写菜名的话他没法确认自己点对了没有
            Column({ space: 6 }) {
              Text(this.merchant?.name ?? '')
                .fontSize(15).fontWeight(FontWeight.Medium)
                .fontColor($r('app.color.ink')).width('100%');
              ForEach(this.lines, (l: CartLine) => {
                Row() {
                  Column({ space: 2 }) {
                    Text(l.dish.name)
                      .fontSize(13).fontColor($r('app.color.ink'));
                    if (l.choices.length > 0) {
                      Text(choicesLabel(l.choices))
                        .fontSize(11).fontColor($r('app.color.ink_muted'));
                    }
                  }
                  .layoutWeight(1).alignItems(HorizontalAlign.Start);
                  Text(`${yuan(unitCents(l))} ×${l.quantity}`)
                    .fontSize(13).fontColor($r('app.color.ink_muted'));
                }
                .width('100%').padding({ top: 4, bottom: 4 });
              }, (l: CartLine) => `${l.dish.id}|${l.choices.join(',')}`);
            }
            .width('100%').padding(16).backgroundColor($r('app.color.surface'))
            .alignItems(HorizontalAlign.Start);

            // 券
            this.couponSheet();

            // 备注
            Column({ space: 6 }) {
              Text('备注').fontSize(13).fontColor($r('app.color.ink_muted')).width('100%');
              TextInput({ placeholder: '口味、忌口等(如:不要辣)', text: this.remark })
                .height(44)
                .onChange((v: string) => { this.remark = v; });
            }
            .width('100%').padding(16).backgroundColor($r('app.color.surface'))
            .alignItems(HorizontalAlign.Start);

            // 费用明细。**每一项都摊开** —— 这个平台的立身之本是账目透明,
            // 结算页藏着掖着就没得谈了
            Column() {
              this.feeRow('餐费', yuan(this.food), false);
              this.feeRow('打包费', yuan(this.packing), false);
              this.feeRow('配送费',
                this.pickup ? '免' :
                  (this.deliveryFee < 0 ? '以下单为准' : yuan(this.deliveryFee)), false);
              if (this.merchant !== null
                && manjianCents(this.merchant, this.food, this.packing) > 0
                && (this.pickedVerdict === null
                  || this.pickedVerdict.coupon.funder !== 'merchant')) {
                this.feeRow('满减',
                  `-${yuan(manjianCents(this.merchant, this.food, this.packing))}`, true);
              }
              if (this.pickedVerdict !== null) {
                this.feeRow(
                  this.pickedVerdict.coupon.funder === 'merchant'
                    ? '店铺券(已取代满减)' : '优惠券',
                  `-${yuan(this.pickedVerdict.offCents)}`, true);
              }
              Divider().margin({ top: 6, bottom: 6 });
              Row() {
                Text('实付').fontSize(15).fontColor($r('app.color.ink')).layoutWeight(1);
                Text(yuan(this.payable))
                  .fontSize(20).fontWeight(FontWeight.Bold)
                  .fontColor($r('app.color.brand'));
              }
              .width('100%');
              Text('这一单的钱怎么分,付款后在订单详情里可以逐项查看')
                .fontSize(11).fontColor($r('app.color.ink_muted'))
                .width('100%').margin({ top: 6 });
            }
            .width('100%').padding(16).backgroundColor($r('app.color.surface'))
            .alignItems(HorizontalAlign.Start);
          }
          .width('100%');
        }
        .layoutWeight(1)
        .scrollBar(BarState.Off);

        Row() {
          Text(`实付 ${yuan(this.payable)}`)
            .fontSize(16).fontWeight(FontWeight.Bold)
            .fontColor($r('app.color.ink')).layoutWeight(1);
          Button(this.submitting ? '提交中…' : '提交订单')
            .width(120).height(44)
            .enabled(!this.submitting && this.lines.length > 0)
            .backgroundColor($r('app.color.brand'))
            // 读屏用户要在按下之前知道要付多少,而不是听到一句"提交订单"
            .accessibilityText(`提交订单,实付 ${yuan(this.payable)}`)
            .onClick(() => { this.submit(); });
        }
        .width('100%')
        .padding(12)
        .backgroundColor($r('app.color.surface'))
        .border({ width: { top: 1 }, color: $r('app.color.line') });
      }
    }
    .width('100%')
    .height('100%')
    .backgroundColor($r('app.color.page'));
  }
}
