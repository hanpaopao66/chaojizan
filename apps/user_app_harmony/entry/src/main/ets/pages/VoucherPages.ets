import { promptAction } from '@kit.ArkUI';
import { UserApi } from '../common/UserApi';
import { ApiException } from '../common/Api';
import { VoucherDeal, VoucherTicket } from '../model/Models';
import { yuan } from '../common/Money';

/**
 * 到店团购券。
 *
 * 产品口径:**核销才收 2%,未使用随时全额退**,不靠「过期不退」摸钱。
 * 这两句要写在页面上 —— 用户对团购券最大的顾虑就是"买了用不掉钱就没了"。
 *
 * 安卓端的两个短板,鸿蒙端补上:
 * 1. **有详情页**。安卓端点卡片直接弹购买抽屉、确认即扣款,中间没有可回退的一步;
 * 2. **不写没有实现支撑的承诺**。安卓端券包页写着"过期前有提醒",
 *    而服务端根本没有这个任务 —— 这种话宁可不写。
 */
@Component
export struct VoucherDealsPage {
  onOpenDeal: (deal: VoucherDeal) => void = () => {};

  @State private deals: VoucherDeal[] = [];
  @State private loading: boolean = true;
  @State private error: string = '';

  private api: UserApi = new UserApi();

  async aboutToAppear(): Promise<void> {
    await this.load();
  }

  private async load(): Promise<void> {
    this.loading = true;
    this.error = '';
    try {
      this.deals = await this.api.voucherDeals();
    } catch (e) {
      this.error = (e as ApiException).message;
    } finally {
      this.loading = false;
    }
  }

  @Builder
  private card(d: VoucherDeal) {
    Column({ space: 6 }) {
      Text(d.title)
        .fontSize(16).fontWeight(FontWeight.Medium)
        .fontColor($r('app.color.ink')).width('100%');
      if ((d.merchant_name ?? '').length > 0) {
        Text(d.merchant_name)
          .fontSize(12).fontColor($r('app.color.ink_muted')).width('100%');
      }
      Row({ space: 8 }) {
        Text(yuan(d.sell_price_cents))
          .fontSize(18).fontWeight(FontWeight.Bold)
          .fontColor($r('app.color.brand'));
        Text(`价值 ${yuan(d.face_value_cents)}`)
          .fontSize(12).fontColor($r('app.color.ink_muted'))
          .decoration({ type: TextDecorationType.LineThrough });
      }
      .width('100%');
      Text('未核销随时全额退')
        .fontSize(11).fontColor($r('app.color.earn')).width('100%');
    }
    .width('100%').padding(14).backgroundColor($r('app.color.surface'))
    .borderRadius(14).alignItems(HorizontalAlign.Start)
    .onClick(() => { this.onOpenDeal(d); });
  }

  build() {
    Column() {
      Text('核销才收 2%,未使用随时全额退')
        .fontSize(12).fontColor($r('app.color.earn'))
        .width('100%').padding({ left: 16, right: 16, top: 10, bottom: 8 });

      if (this.loading) {
        Column() { LoadingProgress().width(36).height(36); }
        .width('100%').layoutWeight(1).justifyContent(FlexAlign.Center);
      } else if (this.error.length > 0) {
        Column({ space: 12 }) {
          Text(this.error).fontSize(14).fontColor($r('app.color.ink_muted'));
          Button('重试').onClick(() => { this.load(); });
        }
        .width('100%').layoutWeight(1).justifyContent(FlexAlign.Center);
      } else if (this.deals.length === 0) {
        Column() {
          Text('商家们还没上团购')
            .fontSize(14).fontColor($r('app.color.ink_muted'));
        }
        .width('100%').layoutWeight(1).justifyContent(FlexAlign.Center);
      } else {
        List({ space: 10 }) {
          ForEach(this.deals, (d: VoucherDeal) => {
            ListItem() { this.card(d); }
          }, (d: VoucherDeal) => `${d.id}`);
        }
        .width('100%').layoutWeight(1)
        .padding({ left: 12, right: 12, bottom: 12 })
        .scrollBar(BarState.Off);
      }
    }
    .width('100%').height('100%')
    .backgroundColor($r('app.color.page'));
  }
}

/** 团购券详情。**安卓端没有这一页**,点卡片直接扣款,中间没有可回退的一步 */
@Component
export struct VoucherDetailPage {
  deal: VoucherDeal | null = null;
  onBought: () => void = () => {};

  @State private buying: boolean = false;
  private api: UserApi = new UserApi();

  private async buy(): Promise<void> {
    const d: VoucherDeal | null = this.deal;
    if (d === null || this.buying) {
      return;
    }
    this.buying = true;
    try {
      await this.api.buyVoucher(d.id);
      // 团购券的支付走的是券自己的通道,和外卖订单不是一套。
      // 微信支付接上之前这里同样**不许假装成功**
      promptAction.showToast({
        message: '已下单。支付待微信支付接入,可在「我的券包」里继续',
        duration: 3500,
      });
      this.onBought();
    } catch (e) {
      promptAction.showToast({ message: (e as ApiException).message });
    } finally {
      this.buying = false;
    }
  }

  build() {
    Column() {
      if (this.deal !== null) {
        Scroll() {
          Column({ space: 10 }) {
            Column({ space: 8 }) {
              Text(this.deal.title)
                .fontSize(19).fontWeight(FontWeight.Bold)
                .fontColor($r('app.color.ink')).width('100%');
              if ((this.deal.merchant_name ?? '').length > 0) {
                Text(this.deal.merchant_name)
                  .fontSize(13).fontColor($r('app.color.ink_muted')).width('100%');
              }
              Row({ space: 10 }) {
                Text(yuan(this.deal.sell_price_cents))
                  .fontSize(24).fontWeight(FontWeight.Bold)
                  .fontColor($r('app.color.brand'));
                Text(`价值 ${yuan(this.deal.face_value_cents)}`)
                  .fontSize(13).fontColor($r('app.color.ink_muted'))
                  .decoration({ type: TextDecorationType.LineThrough });
              }
              .width('100%');
              if ((this.deal.description ?? '').length > 0) {
                Text(this.deal.description)
                  .fontSize(13).fontColor($r('app.color.ink')).width('100%');
              }
            }
            .width('100%').padding(16).backgroundColor($r('app.color.surface'))
            .borderRadius(14).alignItems(HorizontalAlign.Start);

            Column({ space: 6 }) {
              Text('买之前请知道')
                .fontSize(15).fontWeight(FontWeight.Medium)
                .fontColor($r('app.color.ink')).width('100%');
              Text('· 到店出示券码核销,**核销才收商家 2%**')
                .fontSize(13).fontColor($r('app.color.ink_muted')).width('100%');
              Text('· 没核销的券**随时全额退**,不做"过期不退"')
                .fontSize(13).fontColor($r('app.color.ink_muted')).width('100%');
              // ⚠️ 不写"过期前会提醒你" —— 服务端没有这个任务,
              // 写了就是一句没有实现支撑的承诺
              if (this.deal.valid_days !== undefined
                && this.deal.valid_days > 0) {
                Text(`· 有效期 ${this.deal.valid_days} 天`)
                  .fontSize(13).fontColor($r('app.color.ink_muted')).width('100%');
              }
            }
            .width('100%').padding(16).backgroundColor($r('app.color.surface'))
            .borderRadius(14).alignItems(HorizontalAlign.Start);
          }
          .width('100%').padding({ left: 12, right: 12, top: 12, bottom: 16 });
        }
        .layoutWeight(1).scrollBar(BarState.Off);

        Row() {
          Text(yuan(this.deal.sell_price_cents))
            .fontSize(18).fontWeight(FontWeight.Bold)
            .fontColor($r('app.color.brand')).layoutWeight(1);
          Button(this.buying ? '处理中…' : '立即购买')
            .width(120).height(44)
            .enabled(!this.buying)
            .backgroundColor($r('app.color.brand'))
            .onClick(() => { this.buy(); });
        }
        .width('100%').padding(12).backgroundColor($r('app.color.surface'))
        .border({ width: { top: 1 }, color: $r('app.color.line') });
      }
    }
    .width('100%').height('100%')
    .backgroundColor($r('app.color.page'));
  }
}

/** 我的券包 */
@Component
export struct MyVouchersPage {
  @State private tickets: VoucherTicket[] = [];
  @State private loading: boolean = true;
  @State private error: string = '';

  private api: UserApi = new UserApi();

  async aboutToAppear(): Promise<void> {
    await this.load();
  }

  private async load(): Promise<void> {
    this.loading = true;
    this.error = '';
    try {
      this.tickets = await this.api.myVoucherTickets();
    } catch (e) {
      this.error = (e as ApiException).message;
    } finally {
      this.loading = false;
    }
  }

  private async refund(t: VoucherTicket): Promise<void> {
    try {
      await this.api.refundVoucher(t.purchase_no);
      await this.load();
      promptAction.showToast({ message: '已全额退款' });
    } catch (e) {
      promptAction.showToast({ message: (e as ApiException).message });
    }
  }

  @Builder
  private card(t: VoucherTicket) {
    Column({ space: 6 }) {
      Row() {
        Text(t.title ?? '团购券')
          .fontSize(15).fontWeight(FontWeight.Medium)
          .fontColor($r('app.color.ink')).layoutWeight(1);
        Text(t.status_label ?? t.status)
          .fontSize(12).fontColor($r('app.color.ink_muted'));
      }
      .width('100%');
      if ((t.merchant_name ?? '').length > 0) {
        Text(t.merchant_name)
          .fontSize(12).fontColor($r('app.color.ink_muted')).width('100%');
      }
      // 券码要大要清楚 —— 用户是站在店里给店员看的
      if ((t.code ?? '').length > 0 && t.status !== 'refunded') {
        Text(t.code)
          .fontSize(24).fontWeight(FontWeight.Bold)
          .fontColor($r('app.color.brand')).width('100%')
          .textAlign(TextAlign.Center)
          .padding({ top: 8, bottom: 8 });
      }
      Row() {
        Text(yuan(t.sell_price_cents))
          .fontSize(14).fontColor($r('app.color.ink')).layoutWeight(1);
        if (t.status === 'paid') {
          Text('未核销,可全额退')
            .fontSize(12).fontColor($r('app.color.earn'))
            .onClick(() => { this.refund(t); });
        }
      }
      .width('100%');
    }
    .width('100%').padding(14).backgroundColor($r('app.color.surface'))
    .borderRadius(14).alignItems(HorizontalAlign.Start);
  }

  build() {
    Column() {
      if (this.loading) {
        Column() { LoadingProgress().width(36).height(36); }
        .width('100%').layoutWeight(1).justifyContent(FlexAlign.Center);
      } else if (this.error.length > 0) {
        Column({ space: 12 }) {
          Text(this.error).fontSize(14).fontColor($r('app.color.ink_muted'));
          Button('重试').onClick(() => { this.load(); });
        }
        .width('100%').layoutWeight(1).justifyContent(FlexAlign.Center);
      } else if (this.tickets.length === 0) {
        Column() {
          Text('券包是空的').fontSize(14).fontColor($r('app.color.ink_muted'));
        }
        .width('100%').layoutWeight(1).justifyContent(FlexAlign.Center);
      } else {
        List({ space: 10 }) {
          ForEach(this.tickets, (t: VoucherTicket) => {
            ListItem() { this.card(t); }
          }, (t: VoucherTicket) => t.purchase_no);
        }
        .width('100%').layoutWeight(1)
        .padding({ left: 12, right: 12, top: 12, bottom: 12 })
        .scrollBar(BarState.Off);
      }
    }
    .width('100%').height('100%')
    .backgroundColor($r('app.color.page'));
  }
}
