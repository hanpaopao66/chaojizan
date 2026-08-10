import { promptAction } from '@kit.ArkUI';
import { UserApi } from '../common/UserApi';
import { ApiException } from '../common/Api';
import { isPaid, payOrder } from '../common/Pay';
import { Order } from '../model/Models';
import { yuan } from '../common/Money';

/**
 * 跑腿:帮我送 / 帮我买。
 *
 * ⚠️ **下单之后必须立刻进支付。** 安卓端在这里出过最严重的一个洞:
 * 订单建出来是 `pending_payment`,而路由 push 完不管返回值 ——
 * 用户填完地址、看完报价、点了下单,页面一关单子就没了,
 * 15 分钟后被自动清扫。白填一遍,平台一分钱收不到。
 *
 * **服务费单列**:外卖的配送费我们一分不抽,跑腿收 2%。
 * 两个口径同时存在,不写清楚就会变成"你不是说配送费不抽吗"。
 */
@Component
export struct ErrandPage {
  onPaid: (order: Order) => void = () => {};

  /** send 帮我送 / buy 帮我买 */
  @State private mode: string = 'send';
  @State private fromAddr: string = '';
  @State private toAddr: string = '';
  @State private itemDesc: string = '';
  @State private budgetText: string = '';
  @State private contactName: string = '';
  @State private contactPhone: string = '';
  @State private noContraband: boolean = false;
  @State private quote: Record<string, Object> | null = null;
  @State private quoting: boolean = false;
  @State private submitting: boolean = false;

  private api: UserApi = new UserApi();

  private num(d: Record<string, Object> | null, key: string): number {
    if (d === null) {
      return 0;
    }
    const v: Object = d[key] ?? 0;
    return typeof v === 'number' ? v : 0;
  }

  private body(): Record<string, Object> {
    const budget: number = Math.round(parseFloat(this.budgetText) * 100);
    const b: Record<string, Object> = {
      'from_address': this.fromAddr.trim(),
      'to_address': this.toAddr.trim(),
      'item_desc': this.itemDesc.trim(),
      'contact_name': this.contactName.trim(),
      'contact_phone': this.contactPhone.trim(),
    };
    if (this.mode === 'buy' && !isNaN(budget)) {
      b['goods_budget_cents'] = budget;
    }
    return b;
  }

  private async refreshQuote(): Promise<void> {
    if (this.fromAddr.trim().length === 0 || this.toAddr.trim().length === 0) {
      return;
    }
    this.quoting = true;
    try {
      this.quote = this.mode === 'buy'
        ? await this.api.errandBuyQuote(this.body())
        : await this.api.errandQuote(this.body());
    } catch (e) {
      this.quote = null;
      promptAction.showToast({ message: (e as ApiException).message });
    } finally {
      this.quoting = false;
    }
  }

  private get valid(): boolean {
    return this.fromAddr.trim().length > 0 && this.toAddr.trim().length > 0
      && this.itemDesc.trim().length > 0
      && /^1[3-9]\d{9}$/.test(this.contactPhone)
      && this.noContraband && this.quote !== null;
  }

  private async submit(): Promise<void> {
    if (!this.valid || this.submitting) {
      if (!this.noContraband) {
        promptAction.showToast({ message: '请先确认不含违禁物品' });
      }
      return;
    }
    this.submitting = true;
    try {
      const order: Order = this.mode === 'buy'
        ? await this.api.createErrandBuy(this.body())
        : await this.api.createErrand(this.body());
      // **建单成功立刻进支付。** 这是安卓端丢单的那个洞,鸿蒙端不许重演
      const after: Order = await payOrder(this.api, order);
      this.onPaid(after);
      if (!isPaid(after)) {
        promptAction.showToast({
          message: '订单已保留为「待支付」,可在订单列表继续支付',
          duration: 3500,
        });
      }
    } catch (e) {
      promptAction.showToast({ message: (e as ApiException).message, duration: 4000 });
    } finally {
      this.submitting = false;
    }
  }

  @Builder
  private modeTab(label: string, value: string, hint: string) {
    Column({ space: 2 }) {
      Text(label).fontSize(15)
        .fontColor(this.mode === value
          ? $r('app.color.brand') : $r('app.color.ink'));
      Text(hint).fontSize(11).fontColor($r('app.color.ink_muted'));
    }
    .layoutWeight(1).padding(12).borderRadius(10)
    .backgroundColor(this.mode === value ? $r('app.color.brand_soft') : $r('app.color.surface'))
    .onClick(() => {
      this.mode = value;
      this.quote = null;
    });
  }

  build() {
    Column() {
      Scroll() {
        Column({ space: 12 }) {
          Row({ space: 8 }) {
            this.modeTab('帮我送', 'send', '东西是你自己的,A 点取 B 点送');
            this.modeTab('帮我买', 'buy', '骑手垫钱买,按小票结算');
          }
          .width('100%');

          TextInput({ placeholder: '取件地址', text: this.fromAddr })
            .height(46).onChange((v: string) => { this.fromAddr = v; });
          TextInput({ placeholder: '送达地址', text: this.toAddr })
            .height(46).onChange((v: string) => { this.toAddr = v; });
          TextInput({
            placeholder: this.mode === 'buy' ? '要买什么(写具体些)' : '物品描述',
            text: this.itemDesc,
          })
            .height(46).onChange((v: string) => { this.itemDesc = v; });
          if (this.mode === 'buy') {
            TextInput({ placeholder: '预估商品金额(元)', text: this.budgetText })
              .type(InputType.Number).height(46)
              .onChange((v: string) => { this.budgetText = v; });
          }
          TextInput({ placeholder: '联系人', text: this.contactName })
            .height(46).onChange((v: string) => { this.contactName = v; });
          TextInput({ placeholder: '联系电话', text: this.contactPhone })
            .type(InputType.PhoneNumber).maxLength(11).height(46)
            .onChange((v: string) => { this.contactPhone = v; });

          Button(this.quoting ? '算价中…' : '算一下多少钱')
            .width('100%').height(42)
            .backgroundColor($r('app.color.surface_alt')).fontColor($r('app.color.ink'))
            .onClick(() => { this.refreshQuote(); });

          if (this.quote !== null) {
            Column({ space: 4 }) {
              Row() {
                Text('跑腿费')
                  .fontSize(13).fontColor($r('app.color.ink_muted')).layoutWeight(1);
                Text(yuan(this.num(this.quote, 'delivery_fee_cents')))
                  .fontSize(13).fontColor($r('app.color.ink'));
              }
              .width('100%');
              // 服务费**单列**。藏在总价里就等于默认用户不会问
              Row() {
                Text('平台服务费(2%)')
                  .fontSize(13).fontColor($r('app.color.ink_muted')).layoutWeight(1);
                Text(yuan(this.num(this.quote, 'service_fee_cents')))
                  .fontSize(13).fontColor($r('app.color.ink'));
              }
              .width('100%');
              if (this.mode === 'buy') {
                Row() {
                  Text('商品款(按小票结算,多退少补)')
                    .fontSize(13).fontColor($r('app.color.ink_muted')).layoutWeight(1);
                  Text(yuan(this.num(this.quote, 'goods_budget_cents')))
                    .fontSize(13).fontColor($r('app.color.ink'));
                }
                .width('100%');
              }
              Divider().margin({ top: 6, bottom: 6 });
              Row() {
                Text('合计').fontSize(15).fontColor($r('app.color.ink')).layoutWeight(1);
                Text(yuan(this.num(this.quote, 'total_cents')))
                  .fontSize(18).fontWeight(FontWeight.Bold)
                  .fontColor($r('app.color.brand'));
              }
              .width('100%');
              Text('跑腿的服务费和外卖的配送费是两回事:' +
                '外卖配送费我们一分不抽,跑腿收 2%。')
                .fontSize(11).fontColor($r('app.color.ink_muted')).width('100%');
            }
            .width('100%').padding(14).backgroundColor($r('app.color.surface'))
            .borderRadius(12).alignItems(HorizontalAlign.Start);
          }

          Row({ space: 8 }) {
            Checkbox()
              .select(this.noContraband)
              .selectedColor($r('app.color.brand'))
              .onChange((v: boolean) => { this.noContraband = v; });
            Text('我确认不含违禁物品(易燃易爆、管制刀具、活体动物等)')
              .fontSize(12).fontColor($r('app.color.ink_muted')).layoutWeight(1);
          }
          .width('100%');
        }
        .width('100%').padding(16).alignItems(HorizontalAlign.Start);
      }
      .layoutWeight(1).scrollBar(BarState.Off);

      Row() {
        Text(this.quote === null ? '先算价' : yuan(this.num(this.quote, 'total_cents')))
          .fontSize(16).fontWeight(FontWeight.Bold)
          .fontColor($r('app.color.ink')).layoutWeight(1);
        Button(this.submitting ? '提交中…' : '下单并支付')
          .width(130).height(44)
          .enabled(this.valid && !this.submitting)
          .backgroundColor(this.valid
            ? $r('app.color.brand') : $r('app.color.line'))
          .onClick(() => { this.submit(); });
      }
      .width('100%').padding(12).backgroundColor($r('app.color.surface'))
      .border({ width: { top: 1 }, color: $r('app.color.line') });
    }
    .width('100%').height('100%').backgroundColor($r('app.color.page'));
  }
}
