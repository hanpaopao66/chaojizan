import { UserApi } from '../common/UserApi';
import { ApiException } from '../common/Api';
import { Session } from '../common/Session';
import { isPaid, payOrder } from '../common/Pay';
import { Order, OrderStatus } from '../model/Models';
import { yuan } from '../common/Money';

/**
 * 订单列表。
 *
 * **待支付的单必须在列表里就能付。** 安卓端漏过这个:跑腿单建出来是
 * pending_payment,而全端只有结算页调支付,用户点进订单只能干看着,
 * 15 分钟后被自动清扫 —— 白填一遍地址,平台一分钱收不到。
 */
@Component
export struct OrdersPage {
  onOpen: (orderNo: string) => void = () => {};
  onNeedLogin: () => void = () => {};

  @State private orders: Order[] = [];
  @State private loading: boolean = true;
  @State private error: string = '';

  private api: UserApi = new UserApi();

  async aboutToAppear(): Promise<void> {
    await this.load();
  }

  async onPageShow(): Promise<void> {
    // 从详情页返回、或刚下完单回来,列表要是新的
    await this.load();
  }

  private async load(): Promise<void> {
    if (!Session.get().isLoggedIn) {
      this.loading = false;
      this.orders = [];
      return;
    }
    this.loading = true;
    this.error = '';
    try {
      this.orders = await this.api.myOrders();
    } catch (e) {
      this.error = (e as ApiException).message;
    } finally {
      this.loading = false;
    }
  }

  private async pay(order: Order): Promise<void> {
    const after: Order = await payOrder(this.api, order);
    if (isPaid(after)) {
      await this.load();
    }
  }

  @Builder
  private card(o: Order) {
    Column({ space: 6 }) {
      Row() {
        Text(o.merchant_name !== undefined && o.merchant_name.length > 0
          ? o.merchant_name : '订单')
          .fontSize(15).fontWeight(FontWeight.Medium)
          .fontColor($r('app.color.ink')).layoutWeight(1)
          .maxLines(1).textOverflow({ overflow: TextOverflow.Ellipsis });
        // 状态中文名用服务端下发的 status_label,客户端不另写映射
        Text(o.status_label ?? o.status)
          .fontSize(12)
          .fontColor(o.status === OrderStatus.CANCELLED
            ? $r('app.color.ink_muted') : $r('app.color.brand'));
      }
      .width('100%');

      if ((o.summary ?? '').length > 0) {
        Text(o.summary)
          .fontSize(12).fontColor($r('app.color.ink_muted'))
          .maxLines(2).textOverflow({ overflow: TextOverflow.Ellipsis })
          .width('100%');
      }

      // 商家拒单会写原因,而且服务端强制要求填 —— 一定要显示出来。
      // 只写「已取消」三个字,用户完全不知道发生了什么
      if (o.status === OrderStatus.CANCELLED
        && (o.cancel_reason ?? '').length > 0) {
        Text(`原因:${o.cancel_reason}`)
          .fontSize(12).fontColor($r('app.color.brand')).width('100%');
      }

      Row() {
        Text(yuan(o.total_cents))
          .fontSize(15).fontWeight(FontWeight.Bold)
          .fontColor($r('app.color.ink')).layoutWeight(1);
        if (o.status === OrderStatus.PENDING_PAYMENT) {
          Button('去支付')
            .height(30).fontSize(12)
            .backgroundColor($r('app.color.brand'))
            .accessibilityText(`去支付 ${yuan(o.total_cents)}`)
            .onClick(() => { this.pay(o); });
        }
      }
      .width('100%');
    }
    .width('100%')
    .padding(14)
    .backgroundColor($r('app.color.surface'))
    .borderRadius(14)
    .alignItems(HorizontalAlign.Start)
    .onClick(() => { this.onOpen(o.order_no); });
  }

  build() {
    Column() {
      Text('我的订单')
        .fontSize(20).fontWeight(FontWeight.Bold)
        .fontColor($r('app.color.ink')).width('100%')
        .padding({ left: 16, right: 16, top: 14, bottom: 8 });

      if (!Session.get().isLoggedIn) {
        Column({ space: 12 }) {
          Text('登录后查看订单').fontSize(14).fontColor($r('app.color.ink_muted'));
          Button('去登录')
            .backgroundColor($r('app.color.brand'))
            .onClick(() => { this.onNeedLogin(); });
        }
        .width('100%').layoutWeight(1).justifyContent(FlexAlign.Center);
      } else if (this.loading) {
        Column() { LoadingProgress().width(36).height(36); }
        .width('100%').layoutWeight(1).justifyContent(FlexAlign.Center);
      } else if (this.error.length > 0) {
        Column({ space: 12 }) {
          Text(this.error).fontSize(14).fontColor($r('app.color.ink_muted'));
          Button('重试').onClick(() => { this.load(); });
        }
        .width('100%').layoutWeight(1).justifyContent(FlexAlign.Center);
      } else if (this.orders.length === 0) {
        Column() {
          Text('还没有订单').fontSize(14).fontColor($r('app.color.ink_muted'));
        }
        .width('100%').layoutWeight(1).justifyContent(FlexAlign.Center);
      } else {
        List({ space: 10 }) {
          ForEach(this.orders, (o: Order) => {
            ListItem() { this.card(o); }
          }, (o: Order) => o.order_no);
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
