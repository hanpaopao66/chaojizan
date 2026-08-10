import { promptAction } from '@kit.ArkUI';
import { MerchantApi } from '../common/MerchantApi';
import { ApiException } from '../common/Api';
import { BtPrinter, NO_DEVICE } from '../common/BtPrinter';
import { yuan } from '../common/Money';
import { feePartList, FeePart, MerchantOrder, OrderItem,
  OrderStatus } from '../model/Models';

/**
 * 订单详情。
 *
 * 商家在这一屏要能回答顾客的三类问题:菜对不对、什么时候到、
 * 「配送费怎么这么贵」。
 *
 * 最后一条尤其重要:配送费**一分不归商家**,却总要商家替我们解释。
 * 所以构成拆分要摆出来,让他能直接指给顾客看,而不是背话术。
 */
@Component
export struct OrderDetailPage {
  @Prop order: MerchantOrder;
  shopName: string = '';
  onBack: () => void = () => {};
  onChanged: () => void = () => {};
  /** 看骑手到哪了。顾客催单先打给店家,店家不该两眼一抹黑 */
  onTrackRider: (o: MerchantOrder) => void = () => {};
  /** 自送前先看送去哪、多远 —— 远近全靠猜,猜错就是自己骑半小时 */
  onSelfDeliveryMap: (o: MerchantOrder) => void = () => {};

  @State private current: MerchantOrder = {} as MerchantOrder;
  @State private busy: boolean = false;
  @State private showCodeSheet: boolean = false;
  @State private codeInput: string = '';

  private api: MerchantApi = new MerchantApi();

  aboutToAppear(): void {
    this.current = this.order;
  }

  private async act(to: string): Promise<void> {
    if (this.busy) {
      return;
    }
    this.busy = true;
    try {
      this.current = await this.api.transition(this.current.order_no, to);
      this.onChanged();
    } catch (e) {
      promptAction.showToast({ message: (e as ApiException).message });
    } finally {
      this.busy = false;
    }
  }

  private async print(): Promise<void> {
    const err: string | null =
        await BtPrinter.printOrder(this.current, this.shopName);
    if (err === NO_DEVICE) {
      promptAction.showToast({ message: '还没连蓝牙打印机,去「店铺 - 打印设置」连一台' });
      return;
    }
    promptAction.showToast({ message: err === null ? '已出票' : err });
  }

  /**
   * 自取核销。
   *
   * 取餐码是 4 位数字,让商家直接输 —— 顾客报一句「8421」比掏手机
   * 调出二维码再让商家扫快得多,而取餐窗口前是最不能耽误的地方。
   *
   * `promptAction.showDialog` **没有输入框**,所以走页面内的输入面板,
   * 不是拿一个假弹窗糊过去。
   */
  private async submitCode(): Promise<void> {
    const code: string = this.codeInput.trim();
    if (code.length === 0) {
      return;
    }
    try {
      this.current = await this.api.pickupVerify(this.current.order_no, code);
      this.showCodeSheet = false;
      this.codeInput = '';
      promptAction.showToast({ message: '核销成功' });
      this.onChanged();
    } catch (e) {
      // 码错了是最常见的情况,**面板不关** —— 关了商家得重新点一遍
      promptAction.showToast({ message: (e as ApiException).message });
    }
  }

  @Builder
  private codeSheet() {
    Column({ space: 12 }) {
      Text('核对取餐码')
        .fontSize(17).fontWeight(FontWeight.Bold)
        .fontColor($r('app.color.ink')).width('100%');
      Text('让顾客报一下取餐码')
        .fontSize(13).fontColor($r('app.color.ink_muted')).width('100%');
      TextInput({ placeholder: '4 位数字', text: this.codeInput })
        .type(InputType.Number)
        .maxLength(6)
        .height(48)
        .onChange((v: string) => { this.codeInput = v; });
      Row({ space: 10 }) {
        Button('取消')
          .layoutWeight(1).height(44)
          .backgroundColor($r('app.color.surface_alt'))
          .fontColor($r('app.color.ink'))
          .onClick(() => {
            this.showCodeSheet = false;
            this.codeInput = '';
          });
        Button('核销')
          .layoutWeight(1).height(44)
          .backgroundColor($r('app.color.brand'))
          .enabled(this.codeInput.trim().length > 0)
          .onClick(() => { this.submitCode(); });
      }
      .width('100%');
    }
    .width('100%')
    .padding({ left: 18, right: 18, top: 18, bottom: 24 })
    .backgroundColor($r('app.color.surface'));
  }

  @Builder
  private row(label: string, value: string, strong: boolean = false) {
    Row() {
      Text(label).fontSize(13).fontColor($r('app.color.ink_muted'))
        .layoutWeight(1);
      Text(value)
        .fontSize(strong ? 16 : 13)
        .fontWeight(strong ? FontWeight.Bold : FontWeight.Normal)
        .fontColor($r('app.color.ink'));
    }
    .width('100%')
    .padding({ top: 4, bottom: 4 });
  }

  @Builder
  private card(title: string) {
    Text(title)
      .fontSize(13)
      .fontWeight(FontWeight.Medium)
      .fontColor($r('app.color.ink'))
      .width('100%')
      .margin({ bottom: 6 });
  }

  build() {
    Column() {
      Row({ space: 10 }) {
        Text('‹').fontSize(24).fontColor($r('app.color.ink'))
          .onClick(() => { this.onBack(); });
        Text(this.current.status_label ?? '订单详情')
          .fontSize(17).fontWeight(FontWeight.Bold)
          .fontColor($r('app.color.ink')).layoutWeight(1);
        Text('打印')
          .fontSize(14).fontColor($r('app.color.brand'))
          .onClick(() => { this.print(); });
      }
      .width('100%')
      .padding({ left: 14, right: 14, top: 10, bottom: 10 })
      .backgroundColor($r('app.color.surface'));

      Scroll() {
        Column({ space: 12 }) {
          // ---- 菜品 ----
          Column() {
            this.card('菜品');
            ForEach(this.current.items ?? [], (it: OrderItem) => {
              Row() {
                Text(`${it.name} ×${it.quantity}`)
                  .fontSize(14).fontColor($r('app.color.ink')).layoutWeight(1);
                Text(yuan(it.price_cents * it.quantity))
                  .fontSize(14).fontColor($r('app.color.ink_muted'));
              }
              .width('100%').padding({ top: 4, bottom: 4 });
            }, (it: OrderItem, i: number) => `${it.dish_id}-${i}`);
            if ((this.current.remark ?? '').length > 0) {
              Text(`备注:${this.current.remark}`)
                .fontSize(13).fontColor($r('app.color.hold'))
                .width('100%').margin({ top: 6 });
            }
          }
          .width('100%').padding(14)
          .backgroundColor($r('app.color.surface')).borderRadius(12);

          // ---- 账目 ----
          Column() {
            this.card('这一单的账');
            this.row('菜品', yuan(this.current.food_cents ?? 0));
            if ((this.current.packing_fee_cents ?? 0) > 0) {
              this.row('打包费', yuan(this.current.packing_fee_cents ?? 0));
            }
            if ((this.current.discount_cents ?? 0) > 0) {
              this.row('满减(你出)', `-${yuan(this.current.discount_cents ?? 0)}`);
            }
            if (this.current.pickup === true) {
              this.row('配送费', '到店自取,免配送费');
            } else {
              this.row('配送费(全归骑手)',
                yuan(this.current.delivery_fee_cents ?? 0));
              // 构成拆分:顾客当面问「怎么这么贵」时,商家能直接指给他看。
              // 中文名由服务端下发,客户端不另写映射
              ForEach(feePartList(this.current.fee_parts,
                this.current.fee_part_labels), (p: FeePart) => {
                Row() {
                  Text(`· ${p.label}`).fontSize(11)
                    .fontColor($r('app.color.ink_muted')).layoutWeight(1);
                  Text(yuan(p.cents)).fontSize(11)
                    .fontColor($r('app.color.ink_muted'));
                }
                .width('100%');
              }, (p: FeePart) => p.key);
            }
            Divider().margin({ top: 8, bottom: 8 })
              .color($r('app.color.line'));
            this.row('用户实付', yuan(this.current.total_cents), true);
            this.row('平台佣金',
              `-${yuan(this.current.commission_cents ?? 0)}`);
          }
          .width('100%').padding(14)
          .backgroundColor($r('app.color.surface')).borderRadius(12);

          // ---- 收货 ----
          Column() {
            this.card(this.current.pickup === true ? '取餐' : '送达');
            if (this.current.pickup === true) {
              this.row('取餐码', this.current.pickup_code ?? '');
            } else {
              this.row('联系人',
                `${this.current.contact_name ?? ''} ${this.current.contact_phone ?? ''}`);
              Text(this.current.address ?? '')
                .fontSize(14).fontColor($r('app.color.ink'))
                .width('100%').margin({ top: 4 });
              if (this.current.to_door === false) {
                Text('顾客选了送到楼下,骑手不上楼')
                  .fontSize(12).fontColor($r('app.color.hold'))
                  .width('100%').margin({ top: 4 });
              }
            }
          }
          .width('100%').padding(14)
          .backgroundColor($r('app.color.surface')).borderRadius(12);

          Blank().height(80);
        }
        .width('100%').padding(12);
      }
      .layoutWeight(1)
      .scrollBar(BarState.Off);

      // ---- 底部动作 ----
      if (OrderStatus.isActive(this.current.status)) {
        Row({ space: 10 }) {
          if (this.current.status === OrderStatus.PAID) {
            Button('拒单')
              .layoutWeight(1).height(44)
              .backgroundColor($r('app.color.surface_alt'))
              .fontColor($r('app.color.danger'))
              .onClick(() => { this.act(OrderStatus.CANCELLED); });
            Button(this.busy ? '处理中…' : '接单')
              .layoutWeight(2).height(44)
              .backgroundColor($r('app.color.brand'))
              .enabled(!this.busy)
              .onClick(() => { this.act(OrderStatus.ACCEPTED); });
          } else if (this.current.status === OrderStatus.ACCEPTED) {
            if (this.current.self_delivery === true) {
              Button('看送去哪')
                .layoutWeight(1).height(44)
                .backgroundColor($r('app.color.surface_alt'))
                .fontColor($r('app.color.ink'))
                .onClick(() => { this.onSelfDeliveryMap(this.current); });
            }
            Button(this.busy ? '处理中…' : '出餐完成')
              .layoutWeight(1).height(44)
              .backgroundColor($r('app.color.brand'))
              .enabled(!this.busy)
              .onClick(() => { this.act(OrderStatus.READY); });
          } else if (this.current.status === OrderStatus.READY) {
            if (this.current.pickup === true) {
              Button('核销取餐码')
                .layoutWeight(1).height(44)
                .backgroundColor($r('app.color.brand'))
                .onClick(() => { this.showCodeSheet = true; });
            } else if (this.current.self_delivery === true) {
              Button('开始配送(自送)')
                .layoutWeight(1).height(44)
                .backgroundColor($r('app.color.brand'))
                .onClick(() => { this.act(OrderStatus.PICKED_UP); });
            } else if (this.current.rider_id !== undefined) {
              // 平台配送且骑手已接:看骑手到哪了
              Button('骑手在哪')
                .layoutWeight(1).height(44)
                .backgroundColor($r('app.color.surface_alt'))
                .fontColor($r('app.color.ink'))
                .onClick(() => { this.onTrackRider(this.current); });
            } else {
              Text('等骑手来取餐')
                .fontSize(13).fontColor($r('app.color.ink_muted'))
                .layoutWeight(1).textAlign(TextAlign.Center);
            }
          }
        }
        .width('100%')
        .padding({ left: 14, right: 14, top: 10, bottom: 14 })
        .backgroundColor($r('app.color.surface'));
      }
    }
    .width('100%').height('100%')
    .backgroundColor($r('app.color.page'))
    .bindSheet($$this.showCodeSheet, this.codeSheet(), {
      height: 260,
      dragBar: false,
    });
  }
}
