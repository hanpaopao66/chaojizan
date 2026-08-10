import { call } from '@kit.TelephonyKit';
import { promptAction } from '@kit.ArkUI';
import { UserApi } from '../common/UserApi';
import { ApiException } from '../common/Api';
import { isPaid, payOrder } from '../common/Pay';
import { AfterSale, FeePart, feePartList, Order, OrderEvent, OrderItem, OrderStatus,
  RefundRecord, Review, RiderLocation } from '../model/Models';
import { distanceText, yuan } from '../common/Money';

/** 轮询间隔。WebSocket 是主,这个是断线兜底 */
const POLL_MS: number = 15000;

/**
 * 订单详情。
 *
 * 这一页是整个产品的招牌:**「这一单的钱去哪了」**。
 * 别家外卖只给一个总数,我们把商家实收、骑手所得、平台留存摊开 ——
 * 这是结构上做得到而他们做不到的事(他们的骑手侧定价是商业机密,
 * 摊开等于公布调控手段;我们没有中间层,每一分都说得清)。
 *
 * 数字读的是**下单那一刻的快照**,不按当前费率重算 ——
 * 费率调过之后重算出来的和当时收的对不上,那比不显示更糟。
 */
@Component
export struct OrderDetailPage {
  orderNo: string = '';
  onOpenChat: (orderNo: string, peer: string) => void = () => {};
  onOpenReview: (orderNo: string) => void = () => {};
  onOpenAfterSale: (orderNo: string) => void = () => {};
  onShare: (order: Order) => void = () => {};
  onOpenAppend: (orderNo: string, merchantId: number) => void = () => {};

  @State private order: Order | null = null;
  @State private events: OrderEvent[] = [];
  @State private rider: RiderLocation | null = null;
  @State private afterSale: AfterSale | null = null;
  @State private refunds: RefundRecord[] = [];
  @State private review: Review | null = null;
  @State private foodSafety: Record<string, Object> | null = null;
  @State private unread: number = 0;
  /** 能不能自助退(服务端判,客户端别自己算规则) */
  @State private selfRefundable: boolean = false;
  @State private loading: boolean = true;
  @State private error: string = '';

  private api: UserApi = new UserApi();
  private timer: number = -1;

  async aboutToAppear(): Promise<void> {
    await this.load();
    this.startPolling();
  }

  aboutToDisappear(): void {
    this.stopTimer();
  }

  /** 退到后台停表。切走之后还每 15 秒发一轮,费流量费电 */
  onPageHide(): void {
    this.stopTimer();
  }

  onPageShow(): void {
    this.load();
    this.startPolling();
  }

  private startPolling(): void {
    this.stopTimer();
    if (this.order !== null && OrderStatus.isFinal(this.order.status)) {
      return; // 终态不会再变,继续轮询是白跑
    }
    this.timer = setInterval(() => { this.load(); }, POLL_MS);
  }

  private stopTimer(): void {
    if (this.timer >= 0) {
      clearInterval(this.timer);
      this.timer = -1;
    }
  }

  private async load(): Promise<void> {
    this.error = '';
    try {
      const o: Order = await this.api.getOrder(this.orderNo);
      this.order = o;
      // 附属数据各自兜底:某一项拉不到不该把整页打回错误态
      this.api.orderEvents(this.orderNo)
        .then((e: OrderEvent[]) => { this.events = e; }).catch(() => {});
      if (!OrderStatus.isFinal(o.status)) {
        this.api.orderUnread(this.orderNo)
          .then((n: number) => { this.unread = n; }).catch(() => {});
      }
      if (o.status === OrderStatus.PICKED_UP) {
        this.api.riderLocation(this.orderNo)
          .then((r: RiderLocation | null) => { this.rider = r; }).catch(() => {});
      }
      if (o.status === OrderStatus.DELIVERED || o.status === OrderStatus.COMPLETED) {
        this.api.orderAfterSale(this.orderNo)
          .then((a: AfterSale | null) => { this.afterSale = a; }).catch(() => {});
      }
      if (o.status === OrderStatus.COMPLETED) {
        this.api.orderReview(this.orderNo)
          .then((r: Review | null) => { this.review = r; }).catch(() => {});
      }
      if ((o.refund_cents ?? 0) > 0) {
        this.api.orderRefunds(this.orderNo)
          .then((r: RefundRecord[]) => { this.refunds = r; }).catch(() => {});
      }
      this.api.foodSafetyOfOrder(this.orderNo)
        .then((f: Record<string, Object> | null) => { this.foodSafety = f; })
        .catch(() => {});
      // 自助退款:能不能退由服务端判。客户端复刻一份规则迟早和它分叉,
      // 那时用户会看到"能退"的按钮点下去被拒
      if (!OrderStatus.isFinal(o.status)) {
        this.api.selfRefundCheck(this.orderNo)
          .then((c: Record<string, Object>) => {
            this.selfRefundable = c['refundable'] === true;
          })
          .catch(() => { this.selfRefundable = false; });
      }
      if (OrderStatus.isFinal(o.status)) {
        this.stopTimer();
      }
    } catch (e) {
      if (this.order === null) {
        this.error = (e as ApiException).message;
      }
    } finally {
      this.loading = false;
    }
  }

  /** 加急小费。**纯用户出、100% 归骑手,平台不补贴也不抽** */
  private async boost(addCents: number): Promise<void> {
    try {
      await this.api.boostTip(this.orderNo, addCents);
      await this.load();
      promptAction.showToast({ message: '已加,附近骑手会立刻收到通知' });
    } catch (e) {
      promptAction.showToast({ message: (e as ApiException).message });
    }
  }

  /**
   * 临时放行完整门牌。
   *
   * 地址保护开着时骑手只看得到粗地址,快到了用户可以主动放行 ——
   * **是用户按需放行,不是平台默认公开**,这个方向不能反。
   */
  private async reveal(): Promise<void> {
    try {
      await this.api.revealAddress(this.orderNo);
      await this.load();
      promptAction.showToast({ message: '已把门牌号给骑手' });
    } catch (e) {
      promptAction.showToast({ message: (e as ApiException).message });
    }
  }

  /** 帮买加价:骑手正站在货架前等回复,所以这个决定要能一秒做完 */
  private async decideRaise(agree: boolean): Promise<void> {
    try {
      await this.api.decideRaise(this.orderNo, agree);
      await this.load();
      promptAction.showToast({
        message: agree ? '已同意,骑手照买' : '已拒绝,商品款会全额退给你',
      });
    } catch (e) {
      promptAction.showToast({ message: (e as ApiException).message });
    }
  }

  private async doSelfRefund(): Promise<void> {
    try {
      await this.api.selfRefund(this.orderNo);
      await this.load();
      promptAction.showToast({ message: '已退款,原路返回' });
    } catch (e) {
      promptAction.showToast({ message: (e as ApiException).message });
    }
  }

  private async urge(): Promise<void> {
    try {
      await this.api.urgeOrder(this.orderNo);
      promptAction.showToast({ message: '已催,商家和骑手都会收到' });
    } catch (e) {
      promptAction.showToast({ message: (e as ApiException).message });
    }
  }

  private async cancel(): Promise<void> {
    try {
      await this.api.cancelOrder(this.orderNo, '不想要了');
      await this.load();
      promptAction.showToast({ message: '已取消' });
    } catch (e) {
      promptAction.showToast({ message: (e as ApiException).message });
    }
  }

  private async confirm(): Promise<void> {
    try {
      await this.api.confirmReceived(this.orderNo);
      await this.load();
    } catch (e) {
      promptAction.showToast({ message: (e as ApiException).message });
    }
  }

  private dial(phone: string): void {
    if (phone.length === 0) {
      return;
    }
    call.makeCall(phone).catch(() => {
      promptAction.showToast({ message: `拨号失败,号码 ${phone}` });
    });
  }

  /** 商家实收 = 餐费 + 打包费 − 平台佣金 */
  private merchantNet(o: Order): number {
    return (o.food_cents ?? 0) + (o.packing_fee_cents ?? 0)
      - (o.commission_cents ?? 0);
  }

  /** 骑手所得 = 配送费 + 小费。**平台一分不抽**,这是写在首页的承诺 */
  private riderNet(o: Order): number {
    return (o.delivery_fee_cents ?? 0) + (o.tip_cents ?? 0);
  }

  @Builder
  private row(label: string, value: string, color: Resource) {
    Row() {
      Text(label).fontSize(13).fontColor($r('app.color.ink_muted')).layoutWeight(1);
      Text(value).fontSize(13).fontColor(color);
    }
    .width('100%').padding({ top: 5, bottom: 5 });
  }

  /** 状态时间轴。每一步的时间戳来自服务端事件流,不是客户端猜的 */
  @Builder
  private timeline() {
    if (this.events.length > 0) {
      Column({ space: 8 }) {
        Text('订单进度')
          .fontSize(15).fontWeight(FontWeight.Medium)
          .fontColor($r('app.color.ink')).width('100%');
        ForEach(this.events, (e: OrderEvent) => {
          Row({ space: 8 }) {
            Text('·').fontSize(14).fontColor($r('app.color.brand'));
            Text(e.label !== undefined && e.label.length > 0
              ? e.label : e.to_status)
              .fontSize(13).fontColor($r('app.color.ink')).layoutWeight(1);
            Text(e.created_at.length > 16
              ? e.created_at.substring(11, 16) : e.created_at)
              .fontSize(11).fontColor($r('app.color.ink_muted'));
          }
          .width('100%');
          if ((e.reason ?? '').length > 0) {
            Text(`  ${e.reason}`)
              .fontSize(11).fontColor($r('app.color.ink_muted')).width('100%');
          }
        }, (e: OrderEvent) => `${e.id}`);
      }
      .width('100%').padding(16).backgroundColor($r('app.color.surface'))
      .borderRadius(14).alignItems(HorizontalAlign.Start);
    }
  }

  /** 骑手信息。没有地图 SDK 时降级成"还有多远",不要留一块白板 */
  @Builder
  private riderCard(r: RiderLocation) {
    Column({ space: 6 }) {
      Row() {
        Text(`骑手 ${r.rider_name ?? ''}`)
          .fontSize(15).fontColor($r('app.color.ink')).layoutWeight(1);
        if ((r.rider_phone ?? '').length > 0) {
          Text('打电话')
            .fontSize(13).fontColor($r('app.color.brand'))
            .onClick(() => { this.dial(r.rider_phone as string); });
        }
      }
      .width('100%');
      if (r.distance_m !== undefined) {
        Text(`距你还有 ${distanceText(r.distance_m)}`)
          .fontSize(13).fontColor($r('app.color.earn')).width('100%');
      }
      Text('地图轨迹待接入腾讯鸿蒙地图 SDK,现在先给距离')
        .fontSize(11).fontColor($r('app.color.ink_muted')).width('100%');
    }
    .width('100%').padding(16).backgroundColor($r('app.color.surface'))
    .borderRadius(14).alignItems(HorizontalAlign.Start);
  }

  /** 食安投诉状态。投诉能提交却查不到进度,比没有入口更伤 */
  @Builder
  private foodSafetyCard(report: Record<string, Object>) {
    Column({ space: 6 }) {
      Text(`食品安全投诉 · ${this.fsLabel(report)}`)
        .fontSize(14).fontWeight(FontWeight.Medium)
        .fontColor($r('app.color.brand')).width('100%');
      Text('食安投诉不经商家,由平台直接处理。处理完会通知你。')
        .fontSize(11).fontColor($r('app.color.ink_muted')).width('100%');
    }
    .width('100%').padding(16).backgroundColor($r('app.color.brand_soft'))
    .borderRadius(14).alignItems(HorizontalAlign.Start);
  }

  private fsLabel(report: Record<string, Object>): string {
    const s: Object = report['status'] ?? 'open';
    if (s === 'confirmed') {
      return '投诉成立,平台已处理';
    }
    if (s === 'dismissed') {
      return '调查后未认定';
    }
    return '平台受理中';
  }

  @Builder
  private actions(o: Order) {
    Column({ space: 8 }) {
      if (this.unread > 0) {
        Text(`有 ${this.unread} 条新消息`)
          .fontSize(13).fontWeight(FontWeight.Medium)
          .fontColor($r('app.color.brand')).width('100%');
      }
      Row({ space: 8 }) {
        if (o.status !== OrderStatus.CANCELLED
          && o.status !== OrderStatus.PENDING_PAYMENT) {
          Button('联系商家')
            .height(38).fontSize(13).layoutWeight(1)
            .backgroundColor($r('app.color.surface_alt')).fontColor($r('app.color.ink'))
            .onClick(() => { this.onOpenChat(o.order_no, 'merchant'); });
          if (o.pickup !== true) {
            Button('联系骑手')
              .height(38).fontSize(13).layoutWeight(1)
              .backgroundColor($r('app.color.surface_alt')).fontColor($r('app.color.ink'))
              .onClick(() => { this.onOpenChat(o.order_no, 'rider'); });
          }
        }
      }
      .width('100%');
      Row({ space: 8 }) {
        if (o.status === OrderStatus.PAID || o.status === OrderStatus.ACCEPTED
          || o.status === OrderStatus.READY || o.status === OrderStatus.PICKED_UP) {
          Button('催一下')
            .height(38).fontSize(13).layoutWeight(1)
            .backgroundColor($r('app.color.surface_alt')).fontColor($r('app.color.ink'))
            .onClick(() => { this.urge(); });
        }
        if (o.status === OrderStatus.PAID || o.status === OrderStatus.ACCEPTED) {
          Button('取消订单')
            .height(38).fontSize(13).layoutWeight(1)
            .backgroundColor($r('app.color.surface_alt')).fontColor($r('app.color.ink_muted'))
            .onClick(() => { this.cancel(); });
        }
        if (o.status === OrderStatus.DELIVERED) {
          Button('确认收货')
            .height(38).fontSize(13).layoutWeight(1)
            .backgroundColor($r('app.color.brand'))
            .onClick(() => { this.confirm(); });
        }
        if (o.addr_protect === true && o.addr_revealed !== true
          && o.status === OrderStatus.PICKED_UP) {
          Button('把门牌给骑手')
            .height(38).fontSize(13).layoutWeight(1)
            .backgroundColor($r('app.color.surface_alt'))
            .fontColor($r('app.color.ink'))
            .onClick(() => { this.reveal(); });
        }
        if (o.status === OrderStatus.PAID || o.status === OrderStatus.ACCEPTED) {
          Button('加菜')
            .height(38).fontSize(13).layoutWeight(1)
            .backgroundColor($r('app.color.surface_alt'))
            .fontColor($r('app.color.ink'))
            .onClick(() => { this.onOpenAppend(o.order_no, o.merchant_id); });
        }
        if (this.selfRefundable) {
          Button('立即退款')
            .height(38).fontSize(13).layoutWeight(1)
            .backgroundColor($r('app.color.surface_alt')).fontColor($r('app.color.ink'))
            .onClick(() => { this.doSelfRefund(); });
        }
      }
      .width('100%');
      // 无人接单时可以加急。**这笔钱全归骑手**,平台不补贴也不抽
      if (o.status === OrderStatus.PAID && o.pickup !== true) {
        Row({ space: 8 }) {
          Text('没人接单?加点小费,全归骑手')
            .fontSize(12).fontColor($r('app.color.ink_muted')).layoutWeight(1);
          Button('+¥2').height(30).fontSize(12)
            .backgroundColor($r('app.color.surface_alt')).fontColor($r('app.color.ink'))
            .onClick(() => { this.boost(200); });
          Button('+¥5').height(30).fontSize(12)
            .backgroundColor($r('app.color.surface_alt')).fontColor($r('app.color.ink'))
            .onClick(() => { this.boost(500); });
        }
        .width('100%');
      }
      Row({ space: 8 }) {
        if ((o.status === OrderStatus.DELIVERED
          || o.status === OrderStatus.COMPLETED) && this.afterSale === null) {
          Button('申请售后')
            .height(38).fontSize(13).layoutWeight(1)
            .backgroundColor($r('app.color.surface_alt')).fontColor($r('app.color.ink'))
            .onClick(() => { this.onOpenAfterSale(o.order_no); });
        }
        if (o.status === OrderStatus.COMPLETED && this.review === null) {
          Button('去评价')
            .height(38).fontSize(13).layoutWeight(1)
            .backgroundColor($r('app.color.brand'))
            .onClick(() => { this.onOpenReview(o.order_no); });
        }
      }
      .width('100%');
    }
    .width('100%').padding(16).backgroundColor($r('app.color.surface'))
    .borderRadius(14).alignItems(HorizontalAlign.Start);
  }

  @Builder
  private afterSaleCard(a: AfterSale) {
    Column({ space: 6 }) {
      Text(`售后 · ${a.status_label ?? a.status}`)
        .fontSize(14).fontWeight(FontWeight.Medium)
        .fontColor($r('app.color.ink')).width('100%');
      Text(a.reason)
        .fontSize(12).fontColor($r('app.color.ink_muted')).width('100%');
      if ((a.reply ?? '').length > 0) {
        Text(`回复:${a.reply}`)
          .fontSize(12).fontColor($r('app.color.ink')).width('100%');
      }
      ForEach(this.refunds, (r: RefundRecord) => {
        Row() {
          Text(`退款 ${r.status_label ?? r.status}`)
            .fontSize(12).fontColor($r('app.color.ink_muted')).layoutWeight(1);
          Text(yuan(r.amount_cents))
            .fontSize(12).fontColor($r('app.color.earn'));
        }
        .width('100%');
      }, (r: RefundRecord) => `${r.id}`);
    }
    .width('100%').padding(16).backgroundColor($r('app.color.surface'))
    .borderRadius(14).alignItems(HorizontalAlign.Start);
  }

  @Builder
  private shareCard(o: Order) {
    Column({ space: 2 }) {
      Text('这一单的钱去哪了')
        .fontSize(15).fontWeight(FontWeight.Medium)
        .fontColor($r('app.color.ink')).width('100%')
        .margin({ bottom: 6 });
      this.row('商家实收', yuan(this.merchantNet(o)), $r('app.color.ink'));
      this.row('骑手所得(配送费与小费全额)', yuan(this.riderNet(o)),
        $r('app.color.earn'));
      this.row('平台留存(佣金)', yuan(o.commission_cents ?? 0),
        $r('app.color.ink'));
      if ((o.subsidy_cents ?? 0) > 0) {
        this.row('平台补贴', `-${yuan(o.subsidy_cents ?? 0)}`, $r('app.color.earn'));
      }
      if ((o.discount_cents ?? 0) > 0) {
        this.row('商家优惠', `-${yuan(o.discount_cents ?? 0)}`, $r('app.color.earn'));
      }
      Text('配送费一分不截留,全部归骑手;平台只收商家佣金,5% 封顶')
        .fontSize(11).fontColor($r('app.color.ink_muted'))
        .width('100%').margin({ top: 8 });
      // 别家做不到这件事(骑手侧定价是商业机密),所以它值得被转发
      Button('晒一下这一单的账')
        .width('100%').height(38).fontSize(13)
        .margin({ top: 10 })
        .backgroundColor($r('app.color.surface_alt')).fontColor($r('app.color.ink'))
        .onClick(() => { this.onShare(o); });
    }
    .width('100%').padding(16).backgroundColor($r('app.color.surface'))
    .borderRadius(14).alignItems(HorizontalAlign.Start);
  }

  build() {
    Column() {
      if (this.loading) {
        Column() { LoadingProgress().width(36).height(36); }
        .width('100%').layoutWeight(1).justifyContent(FlexAlign.Center);
      } else if (this.order === null) {
        Column({ space: 12 }) {
          Text(this.error.length > 0 ? this.error : '订单加载失败')
            .fontSize(14).fontColor($r('app.color.ink_muted'));
          Button('重试').onClick(() => {
            this.loading = true;
            this.load();
          });
        }
        .width('100%').layoutWeight(1).justifyContent(FlexAlign.Center);
      } else {
        Scroll() {
          Column({ space: 10 }) {
            Column({ space: 4 }) {
              Text(this.order.status_label ?? this.order.status)
                .fontSize(22).fontWeight(FontWeight.Bold)
                .fontColor($r('app.color.ink'));
              Text(`订单号 ${this.order.order_no}`)
                .fontSize(12).fontColor($r('app.color.ink_muted'));
              // 商家拒单会写原因,服务端强制填 —— 一定要显示。
              // 只写「已取消」三个字,用户完全不知道发生了什么
              if (this.order.status === OrderStatus.CANCELLED
                && (this.order.cancel_reason ?? '').length > 0) {
                Text(`原因:${this.order.cancel_reason}`)
                  .fontSize(13).fontColor($r('app.color.brand'));
              }
            }
            .width('100%').padding(20).backgroundColor($r('app.color.surface'))
            .alignItems(HorizontalAlign.Center);

            // 待支付:这一页最重要的动作就是付款,排在所有卡片之前
            if (this.order.status === OrderStatus.PENDING_PAYMENT) {
              Button(`去支付 ${yuan(this.order.total_cents)}`)
                .width('92%').height(46)
                .backgroundColor($r('app.color.brand'))
                .onClick(async () => {
                  if (this.order === null) {
                    return;
                  }
                  const after: Order = await payOrder(this.api, this.order);
                  if (isPaid(after)) {
                    await this.load();
                  }
                });
            }

            // 帮买:骑手问「要多花钱吗」。**这个卡必须排最前** ——
            // 骑手正站在货架前等回复,埋在下半段等于让他一直站着
            if (this.order.goods_raise_status === 'pending') {
              Column({ space: 8 }) {
                Text('骑手问你:要多花点钱吗')
                  .fontSize(16).fontWeight(FontWeight.Medium)
                  .fontColor($r('app.color.ink')).width('100%');
                Text(`你预估 ${yuan(this.order.goods_budget_cents ?? 0)},` +
                  `实际要 ${yuan(this.order.goods_raise_cents ?? 0)}`)
                  .fontSize(13).fontColor($r('app.color.ink')).width('100%');
                Text('同意 → 骑手照买,差额之后跟你结;' +
                  '不同意 → 按买不到处理,商品款全额退你,' +
                  '跑腿费只收骑手到店那一段。')
                  .fontSize(12).fontColor($r('app.color.ink_muted')).width('100%');
                Row({ space: 10 }) {
                  Button('不同意')
                    .layoutWeight(1).height(40)
                    .backgroundColor($r('app.color.surface_alt'))
                    .fontColor($r('app.color.ink'))
                    .onClick(() => { this.decideRaise(false); });
                  Button('同意')
                    .layoutWeight(1).height(40)
                    .backgroundColor($r('app.color.brand'))
                    .onClick(() => { this.decideRaise(true); });
                }
                .width('100%');
              }
              .width('100%').padding(16).backgroundColor($r('app.color.brand_soft'))
              .borderRadius(14).alignItems(HorizontalAlign.Start);
            }

            if (this.foodSafety !== null) {
              this.foodSafetyCard(this.foodSafety);
            }
            if (this.rider !== null) {
              this.riderCard(this.rider);
            }
            this.actions(this.order);
            if (this.afterSale !== null) {
              this.afterSaleCard(this.afterSale);
            }
            this.timeline();

            // 明细
            Column() {
              ForEach(this.order.items ?? [], (it: OrderItem) => {
                Row() {
                  Text(it.name).fontSize(13)
                    .fontColor($r('app.color.ink')).layoutWeight(1);
                  Text(`${yuan(it.price_cents)} ×${it.quantity}`)
                    .fontSize(13).fontColor($r('app.color.ink_muted'));
                }
                .width('100%').padding({ top: 5, bottom: 5 });
              }, (it: OrderItem, idx: number) => `${it.dish_id}-${idx}`);
              Divider().margin({ top: 6, bottom: 6 });
              this.row('配送费', yuan(this.order.delivery_fee_cents ?? 0),
                $r('app.color.ink'));
              // 配送费构成:中文名由服务端下发,客户端不另写一份 ——
              // 两份口径迟早分叉,那时骑手端和顾客端会对同一笔钱有两种说法。
              // fee_parts 是**字典**,先摊平再渲染(直接 ForEach 一项都出不来)
              ForEach(feePartList(this.order.fee_parts,
                this.order.fee_part_labels), (p: FeePart) => {
                Row() {
                  Text(`· ${p.label}`).fontSize(11)
                    .fontColor($r('app.color.ink_muted')).layoutWeight(1);
                  Text(yuan(p.cents)).fontSize(11)
                    .fontColor($r('app.color.ink_muted'));
                }
                .width('100%');
              }, (p: FeePart) => p.key);
              Divider().margin({ top: 6, bottom: 6 });
              Row() {
                Text('实付').fontSize(15).fontColor($r('app.color.ink')).layoutWeight(1);
                Text(yuan(this.order.total_cents))
                  .fontSize(18).fontWeight(FontWeight.Bold)
                  .fontColor($r('app.color.brand'));
              }
              .width('100%');
            }
            .width('100%').padding(16).backgroundColor($r('app.color.surface'))
            .borderRadius(14).alignItems(HorizontalAlign.Start);

            this.shareCard(this.order);
          }
          .width('100%').padding({ left: 12, right: 12, bottom: 16 });
        }
        .layoutWeight(1).scrollBar(BarState.Off);
      }
    }
    .width('100%').height('100%')
    .backgroundColor($r('app.color.page'));
  }
}
