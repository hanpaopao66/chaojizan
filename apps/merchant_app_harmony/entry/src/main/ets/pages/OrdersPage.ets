import { promptAction } from '@kit.ArkUI';
import { common } from '@kit.AbilityKit';
import { MerchantApi } from '../common/MerchantApi';
import { ApiException } from '../common/Api';
import { Listen, ListenEvent, ListenState } from '../common/Listen';
import { Announcer } from '../common/Announcer';
import { BtPrinter, NO_DEVICE } from '../common/BtPrinter';
import { PushPayload } from '../common/PushChannel';
import { AppEvents } from '../entryability/EntryAbility';
import { yuan } from '../common/Money';
import { ArrayDataSource } from '../common/DataSource';
import { MerchantOrder, OrderItem, OrderStatus, Shop } from '../model/Models';

/**
 * 接单主流程。**商家端最不能出事的一屏。**
 *
 * ## 三条从安卓端搬过来的教训
 *
 * 1. **拉失败绝不清空列表、绝不静默**。`orders` 同时驱动列表和催单语音,
 *    拉不到时列表是空的、语音不响,商家看到「一切正常,今天没单」,
 *    而单在往里进。顶部横条要明说,空态文案也要跟着变
 *    (见 DEV-PROMPTS-27 #237);
 * 2. **持续催单**:只要有 paid 的单,每 10 秒响一次,直到商家处理。
 *    后厨有油烟机和抽风,响一声很可能没人听见;
 * 3. **接单/拒单按钮要读出订单号和金额**。一屏十几单时,读屏用户
 *    听到的只有「按钮」,而按错的代价是真金白银。
 *
 * ## 鸿蒙特有的一条
 *
 * 回到前台**必须主动全量拉一次**,不能只等 WebSocket 补发 ——
 * 息屏期间连接早断了,服务端不会补发断线期间的消息。
 */
@Component
export struct OrdersPage {
  @Prop shop: Shop;
  onOpenOrder: (order: MerchantOrder) => void = () => {};

  @State private orders: MerchantOrder[] = [];
  @State private listenState: number = ListenState.LIVE;
  @State private listenText: string = '';
  @State private errorText: string = '';
  @State private acting: string = '';
  @State private tab: number = 0;

  private api: MerchantApi = new MerchantApi();
  private listen: Listen = new Listen();
  private announcer: Announcer = new Announcer();
  private alertTimer: number = -1;
  /** 已经自动打印过的单号。**必须去重** —— 轮询每 15 秒一次,不去重会重复出票 */
  private printed: Set<string> = new Set<string>();
  private firstLoadDone: boolean = false;
  /** LazyForEach 的数据源。列表长了 ForEach 会在首帧把每一行都建出来 */
  private ds: ArrayDataSource<MerchantOrder> =
      new ArrayDataSource<MerchantOrder>();

  aboutToAppear(): void {
    const ctx = getContext(this) as common.UIAbilityContext;
    this.announcer.init(ctx);
    BtPrinter.init(ctx);

    this.listen.onRefresh = () => { this.refresh(); };
    this.listen.onEvent = (e: ListenEvent) => { this.handleEvent(e); };
    this.listen.onStateChange = (s: ListenState) => {
      this.listenState = s;
      this.listenText = this.listen.stateText;
    };
    this.listen.start(this.api.baseUrl, this.shop.id);

    // 前后台由 Ability 转发过来 —— Component 拿不到 Ability 的生命周期
    AppEvents.onForeground = () => { this.listen.onForeground(); };
    AppEvents.onBackground = () => { this.listen.onBackground(); };
    AppEvents.onPush = (p: PushPayload) => { this.handlePush(p); };
    AppEvents.drainPush();

    // 持续催单:有待接单就每 10 秒响一次,直到商家处理
    this.alertTimer = setInterval(() => {
      if (this.orders.some((o: MerchantOrder) => o.status === OrderStatus.PAID)) {
        this.announcer.announce();
      }
    }, 10000);

    this.refresh();
  }

  aboutToDisappear(): void {
    if (this.alertTimer >= 0) {
      clearInterval(this.alertTimer);
      this.alertTimer = -1;
    }
    this.listen.stop();
    this.announcer.dispose();
    AppEvents.onForeground = null;
    AppEvents.onBackground = null;
    AppEvents.onPush = null;
  }

  // ---------- 数据 ----------

  /**
   * 拉订单列表。
   *
   * ⚠️ **失败不清空 `orders`。** 保留上一次的结果比变成空列表安全 ——
   * 空列表和「今天没单」长得一模一样,而商家会照着它去休息。
   */
  private async refresh(): Promise<void> {
    try {
      const list: MerchantOrder[] = await this.api.myOrders();
      this.orders = list;
      this.syncDs();
      this.errorText = '';
      this.listen.markOrdersOk();
      this.autoPrint(list);
    } catch (e) {
      const msg: string = (e as ApiException).message;
      this.errorText = msg;
      this.listen.markOrdersFailed(msg);
    } finally {
      this.firstLoadDone = true;
      this.listenText = this.listen.stateText;
      this.listenState = this.listen.state;
    }
  }

  private handleEvent(e: ListenEvent): void {
    if (e.type === 'new_order') {
      this.announcer.announce();
      promptAction.showToast({
        message: `🔔 新订单:${e.summary ?? ''} ${yuan(e.total_cents ?? 0)}`,
        duration: 5000,
      });
    } else if (e.type === 'urge') {
      // 用户催单:也要响 —— 顾客已经等急了
      this.announcer.announce();
      promptAction.showToast({
        message: `🔥 用户催单:${e.summary ?? ''}`,
        duration: 5000,
      });
    } else if (e.type === 'bad_review') {
      // 差评响应越快挽回余地越大
      promptAction.showToast({
        message: `💬 收到 ${e.rating ?? 0} 星评价:${e.summary ?? ''}`,
        duration: 8000,
      });
    }
  }

  /** 点通知进来:直接落到那一单。落到列表让他自己找,等于白推 */
  private async handlePush(p: PushPayload): Promise<void> {
    await this.refresh();
    const no: string | undefined = p.order_no;
    if (no === undefined) {
      return;
    }
    const hit: MerchantOrder | undefined =
        this.orders.find((o: MerchantOrder) => o.order_no === no);
    if (hit !== undefined) {
      this.onOpenOrder(hit);
    }
  }

  /**
   * 新单自动出票。
   *
   * **去重是硬要求**:轮询每 15 秒一次,同一单会被反复看到,
   * 不去重就是一单出十几张票 —— 纸是商家自己买的。
   */
  private async autoPrint(list: MerchantOrder[]): Promise<void> {
    if (!await BtPrinter.autoPrintEnabled()) {
      return;
    }
    for (let i: number = 0; i < list.length; i++) {
      const o: MerchantOrder = list[i];
      if (o.status !== OrderStatus.PAID || this.printed.has(o.order_no)) {
        continue;
      }
      this.printed.add(o.order_no);
      const err: string | null = await BtPrinter.printOrder(o, this.shop.name);
      if (err !== null && err !== NO_DEVICE) {
        promptAction.showToast({ message: `自动打印失败:${err}` });
      }
    }
  }

  // ---------- 动作 ----------

  private async act(order: MerchantOrder, to: string): Promise<void> {
    if (this.acting.length > 0) {
      return;
    }
    this.acting = order.order_no;
    try {
      await this.api.transition(order.order_no, to);
      await this.refresh();
    } catch (e) {
      promptAction.showToast({ message: (e as ApiException).message });
    } finally {
      this.acting = '';
    }
  }

  private async printOne(order: MerchantOrder): Promise<void> {
    const err: string | null = await BtPrinter.printOrder(order, this.shop.name);
    if (err === NO_DEVICE) {
      promptAction.showToast({ message: '还没连蓝牙打印机,去「店铺 - 打印设置」连一台' });
      return;
    }
    promptAction.showToast({ message: err === null ? '已出票' : err });
  }

  /** 读屏用的订单指代:「尾号 3721,48.00 元」 */
  private speech(o: MerchantOrder): string {
    const no: string = o.order_no;
    const tail: string = no.length > 4 ? no.substring(no.length - 4) : no;
    return `尾号 ${tail},${(o.total_cents / 100).toFixed(2)} 元`;
  }

  // ---------- 界面 ----------

  private get visible(): MerchantOrder[] {
    if (this.tab === 0) {
      return this.orders.filter(
          (o: MerchantOrder) => OrderStatus.isActive(o.status));
    }
    return this.orders.filter(
        (o: MerchantOrder) => OrderStatus.isFinal(o.status));
  }

  /** 列表数据变了就同步给数据源。切页签、拉完数据都要叫 */
  private syncDs(): void {
    this.ds.reload(this.visible);
  }

  @Builder
  private stateBar() {
    Row({ space: 8 }) {
      // 这盏灯回答的是「我现在还能不能收到单」。**照实说,不许含糊**
      Text(this.listenState === ListenState.LIVE ? '●'
        : this.listenState === ListenState.BACKGROUND ? '◐' : '○')
        .fontSize(13)
        .fontColor(this.listenState === ListenState.LIVE
          ? $r('app.color.earn')
          : this.listenState === ListenState.BROKEN
            ? $r('app.color.danger') : $r('app.color.hold'));
      Text(this.listenText.length > 0 ? this.listenText : '实时听单中')
        .fontSize(12)
        .fontColor(this.listenState === ListenState.BROKEN
          ? $r('app.color.danger') : $r('app.color.ink_muted'))
        .layoutWeight(1);
    }
    .width('100%')
    .padding({ left: 14, right: 14, top: 8, bottom: 8 })
    .backgroundColor(this.listenState === ListenState.BROKEN
      ? $r('app.color.brand_soft') : $r('app.color.surface_alt'));
  }

  /** 顶部警示条:**首次加载失败不能和「今天没单」长得一样** */
  @Builder
  private staleBanner() {
    Row({ space: 8 }) {
      Text('⚠').fontSize(15).fontColor($r('app.color.danger'));
      Text(this.errorText.length > 0
        ? `订单列表没能加载出来(${this.errorText})—— 下面的空白不代表没有单,点这里重试`
        : '订单列表有一阵没更新成功了,可能有新单没显示。点这里重试')
        .fontSize(13)
        .lineHeight(19)
        .fontColor($r('app.color.danger'))
        .layoutWeight(1);
      Text('↻').fontSize(15).fontColor($r('app.color.danger'));
    }
    .width('100%')
    .padding({ left: 14, right: 14, top: 10, bottom: 10 })
    .backgroundColor('#1AC0392B')
    .onClick(() => { this.refresh(); });
  }

  @Builder
  private orderCard(o: MerchantOrder) {
    Column({ space: 8 }) {
      Row() {
        Text(o.status_label ?? o.status)
          .fontSize(13)
          .fontWeight(FontWeight.Medium)
          .fontColor(o.status === OrderStatus.PAID
            ? $r('app.color.danger') : $r('app.color.ink'));
        Blank();
        Text(`#${o.order_no.length > 6
          ? o.order_no.substring(o.order_no.length - 6) : o.order_no}`)
          .fontSize(12)
          .fontColor($r('app.color.ink_muted'));
      }
      .width('100%');

      ForEach(o.items ?? [], (it: OrderItem) => {
        Row() {
          Text(`${it.name} ×${it.quantity}`)
            .fontSize(14).fontColor($r('app.color.ink')).layoutWeight(1);
          Text(yuan(it.price_cents * it.quantity))
            .fontSize(14).fontColor($r('app.color.ink_muted'));
        }
        .width('100%');
      }, (it: OrderItem, i: number) => `${it.dish_id}-${i}`);

      if ((o.remark ?? '').length > 0) {
        Text(`备注:${o.remark}`)
          .fontSize(12).fontColor($r('app.color.hold')).width('100%');
      }

      Row() {
        Text('实付').fontSize(13).fontColor($r('app.color.ink_muted'));
        Blank();
        Text(yuan(o.total_cents))
          .fontSize(17).fontWeight(FontWeight.Bold)
          .fontColor($r('app.color.ink'));
      }
      .width('100%');

      // 佣金摆在卡片上,不藏进详情。账目透明不能只写在首页
      if ((o.commission_cents ?? 0) > 0) {
        Row() {
          Text('平台佣金').fontSize(11).fontColor($r('app.color.ink_muted'));
          Blank();
          Text(`-${yuan(o.commission_cents ?? 0)}`)
            .fontSize(11).fontColor($r('app.color.hold'));
        }
        .width('100%');
      }

      this.actions(o);
    }
    .width('100%')
    .padding(14)
    .backgroundColor($r('app.color.surface'))
    .borderRadius(12)
    .margin({ bottom: 10 })
    .onClick(() => { this.onOpenOrder(o); });
  }

  @Builder
  private actions(o: MerchantOrder) {
    Row({ space: 8 }) {
      Button('打印')
        .fontSize(13).height(36)
        .backgroundColor($r('app.color.surface_alt'))
        .fontColor($r('app.color.ink'))
        .accessibilityText(`打印小票,${this.speech(o)}`)
        .onClick(() => { this.printOne(o); });
      Blank();
      if (o.status === OrderStatus.PAID) {
        Button('拒单')
          .fontSize(13).height(36)
          .backgroundColor($r('app.color.surface_alt'))
          .fontColor($r('app.color.danger'))
          .accessibilityText(`拒单,${this.speech(o)}`)
          .onClick(() => { this.act(o, OrderStatus.CANCELLED); });
        Button(this.acting === o.order_no ? '处理中…' : '接单')
          .fontSize(13).height(36)
          .backgroundColor($r('app.color.brand'))
          .enabled(this.acting.length === 0)
          .accessibilityText(`接单,${this.speech(o)}`)
          .onClick(() => { this.act(o, OrderStatus.ACCEPTED); });
      } else if (o.status === OrderStatus.ACCEPTED) {
        Button(this.acting === o.order_no ? '处理中…' : '出餐完成')
          .fontSize(13).height(36)
          .backgroundColor($r('app.color.brand'))
          .enabled(this.acting.length === 0)
          .accessibilityText(`出餐完成,${this.speech(o)}`)
          .onClick(() => { this.act(o, OrderStatus.READY); });
      } else if (o.status === OrderStatus.READY && o.self_delivery === true) {
        Button('开始配送(自送)')
          .fontSize(13).height(36)
          .backgroundColor($r('app.color.brand'))
          .accessibilityText(`开始配送,自送,${this.speech(o)}`)
          .onClick(() => { this.act(o, OrderStatus.PICKED_UP); });
      }
    }
    .width('100%')
    .margin({ top: 4 });
  }

  build() {
    Column() {
      this.stateBar();
      if (this.listen.ordersStale) {
        this.staleBanner();
      }

      Row({ space: 0 }) {
        ForEach([0, 1], (i: number) => {
          Column({ space: 4 }) {
            Text(i === 0 ? '进行中' : '已完成')
              .fontSize(14)
              .fontWeight(this.tab === i ? FontWeight.Bold : FontWeight.Normal)
              .fontColor(this.tab === i
                ? $r('app.color.ink') : $r('app.color.ink_muted'));
            Divider()
              .width(28).strokeWidth(2)
              .color(this.tab === i ? $r('app.color.brand') : Color.Transparent);
          }
          .layoutWeight(1)
          .padding({ top: 10, bottom: 6 })
          .onClick(() => {
            this.tab = i;
            this.syncDs();
          });
        }, (i: number) => `${i}`);
      }
      .width('100%')
      .backgroundColor($r('app.color.surface'));

      if (!this.firstLoadDone) {
        Column() {
          LoadingProgress().width(40).height(40);
        }
        .layoutWeight(1).justifyContent(FlexAlign.Center);
      } else if (this.visible.length === 0) {
        Column({ space: 6 }) {
          // 空态文案跟着状态走:拉失败时**绝不能**说「没有订单」
          Text(this.listen.ordersStale ? '订单列表没能加载出来' : '这一栏没有订单')
            .fontSize(14).fontColor($r('app.color.ink_muted'));
          if (this.listen.ordersStale) {
            Button('重试').fontSize(13).height(34)
              .backgroundColor($r('app.color.brand'))
              .onClick(() => { this.refresh(); });
          }
        }
        .layoutWeight(1).justifyContent(FlexAlign.Center);
      } else {
        // 午高峰几十单,LazyForEach 才不会在首帧就卡住 ——
        // 而卡住的那几百毫秒,商家正在接单
        List({ space: 0 }) {
          LazyForEach(this.ds, (o: MerchantOrder) => {
            ListItem() {
              this.orderCard(o);
            }
          }, (o: MerchantOrder) => `${o.order_no}-${o.status}`);
        }
        .layoutWeight(1)
        .width('100%')
        .padding({ left: 12, right: 12, top: 10 })
        .scrollBar(BarState.Off);
      }
    }
    .width('100%')
    .height('100%')
    .backgroundColor($r('app.color.page'));
  }
}
