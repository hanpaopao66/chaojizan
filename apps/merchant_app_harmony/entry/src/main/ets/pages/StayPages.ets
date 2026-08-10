import { promptAction } from '@kit.ArkUI';
import { MerchantApi } from '../common/MerchantApi';
import { ApiException } from '../common/Api';
import { yuan } from '../common/Money';

/**
 * 酒店民宿:订单 / 房型 / 日历 / 评价 / 售后。
 *
 * 这是和外卖并行的另一条产品线,节奏完全不同:
 * 外卖按分钟算,住宿按天算 —— **所以不共用听单那一套**,
 * 没有语音催单、没有 15 秒轮询,进页面拉一次就够。
 *
 * ## 确认/拒单要慎重
 *
 * 住宿的拒单成本比外卖高得多:顾客可能已经买了车票。
 * 所以拒单必须填理由,而且理由会原样给到顾客。
 */
@Component
export struct StayPages {
  onBack: () => void = () => {};

  /** 0 订单 / 1 房型日历 / 2 评价 / 3 售后 */
  @State private tab: number = 0;

  @State private orders: Record<string, Object>[] = [];
  @State private roomTypes: Record<string, Object>[] = [];
  @State private reviews: Record<string, Object>[] = [];
  @State private aftersales: Record<string, Object>[] = [];
  @State private loaded: boolean = false;
  @State private errorText: string = '';
  @State private busy: boolean = false;

  /** 拒单 */
  @State private showReject: boolean = false;
  @State private rejectNo: string = '';
  @State private rejectReason: string = '';

  /** 回复评价 */
  @State private showReply: boolean = false;
  @State private replyId: number = 0;
  @State private replyText: string = '';

  /** 批量改价/关房 */
  @State private showCalendar: boolean = false;
  @State private calFrom: string = '';
  @State private calTo: string = '';
  @State private calPrice: string = '';
  @State private calQty: string = '';
  @State private calRoomIds: number[] = [];
  @State private calClosed: boolean = false;

  private api: MerchantApi = new MerchantApi();

  aboutToAppear(): void {
    this.load();
  }

  private async load(): Promise<void> {
    // 四块互不依赖,先都发出去
    const ordersF: Promise<Record<string, Object>[]> =
        this.api.stayMerchantOrders('all');
    const roomsF: Promise<Record<string, Object>[]> = this.api.stayRoomTypes();
    const reviewsF: Promise<Record<string, Object>[]> =
        this.api.merchantStayReviews();
    const salesF: Promise<Record<string, Object>[]> =
        this.api.merchantStayAftersales();

    // 后三块是附加信息:拉不到不拦着看订单 —— 订单是要立刻处理的
    try {
      this.roomTypes = await roomsF;
    } catch (_) {
      // 房型拉不到只影响日历页
    }
    try {
      this.reviews = await reviewsF;
    } catch (_) {
      // 评价同上
    }
    try {
      this.aftersales = await salesF;
    } catch (_) {
      // 售后同上
    }

    try {
      this.orders = await ordersF;
      this.errorText = '';
    } catch (e) {
      this.errorText = (e as ApiException).message;
    } finally {
      this.loaded = true;
    }
  }

  // ---------- 订单 ----------

  private async confirm(no: string): Promise<void> {
    this.busy = true;
    try {
      await this.api.stayConfirm(no);
      await this.load();
      promptAction.showToast({ message: '已确认,顾客会收到通知' });
    } catch (e) {
      promptAction.showToast({ message: (e as ApiException).message });
    } finally {
      this.busy = false;
    }
  }

  private async doReject(): Promise<void> {
    if (this.rejectReason.trim().length === 0) {
      promptAction.showToast({ message: '写清楚为什么住不了 —— 顾客可能已经买了车票' });
      return;
    }
    this.busy = true;
    try {
      await this.api.stayReject(this.rejectNo, this.rejectReason.trim());
      this.showReject = false;
      this.rejectReason = '';
      await this.load();
      promptAction.showToast({ message: '已拒单并全额退款' });
    } catch (e) {
      promptAction.showToast({ message: (e as ApiException).message });
    } finally {
      this.busy = false;
    }
  }

  private async checkin(no: string): Promise<void> {
    try {
      await this.api.stayCheckin(no);
      await this.load();
    } catch (e) {
      promptAction.showToast({ message: (e as ApiException).message });
    }
  }

  private async checkout(no: string): Promise<void> {
    try {
      await this.api.stayCheckout(no);
      await this.load();
    } catch (e) {
      promptAction.showToast({ message: (e as ApiException).message });
    }
  }

  // ---------- 日历 ----------

  private async saveCalendar(): Promise<void> {
    if (this.calRoomIds.length === 0 || this.calFrom.length < 10) {
      promptAction.showToast({ message: '选房型、填开始日期' });
      return;
    }
    const body: Record<string, Object> = {
      room_type_ids: this.calRoomIds,
      from_date: this.calFrom,
      to_date: this.calTo.length >= 10 ? this.calTo : this.calFrom,
    };
    const p: number = Math.round((Number.parseFloat(this.calPrice) || 0) * 100);
    if (p > 0) {
      body['price_cents'] = p;
    }
    const q: number = Number.parseInt(this.calQty);
    if (!isNaN(q) && q >= 0) {
      body['total_qty'] = q;
    }
    body['closed'] = this.calClosed;

    this.busy = true;
    try {
      await this.api.setStayCalendar(body);
      this.showCalendar = false;
      promptAction.showToast({ message: '已批量设置' });
    } catch (e) {
      promptAction.showToast({ message: (e as ApiException).message });
    } finally {
      this.busy = false;
    }
  }

  // ---------- 评价 / 售后 ----------

  private async submitReply(): Promise<void> {
    if (this.replyText.trim().length === 0) {
      return;
    }
    try {
      await this.api.replyStayReview(this.replyId, this.replyText.trim());
      this.showReply = false;
      this.replyText = '';
      await this.load();
      promptAction.showToast({ message: '已回复' });
    } catch (e) {
      promptAction.showToast({ message: (e as ApiException).message });
    }
  }

  private async respond(id: number, accept: boolean): Promise<void> {
    try {
      await this.api.respondStayAftersale(id, accept,
          accept ? '已为您办理退款' : '很抱歉,按订单约定这一单不能退');
      await this.load();
      promptAction.showToast({ message: accept ? '已同意' : '已拒绝' });
    } catch (e) {
      promptAction.showToast({ message: (e as ApiException).message });
    }
  }

  // ---------- 界面 ----------

  @Builder
  private rejectSheet() {
    Column({ space: 10 }) {
      Text('拒单')
        .fontSize(17).fontWeight(FontWeight.Bold)
        .fontColor($r('app.color.ink')).width('100%');
      // 住宿拒单的成本比外卖高得多
      Text('顾客可能已经买了车票。写清楚为什么住不了 —— 这句话会原样给到他,' +
        '而且会全额退款。')
        .fontSize(12).lineHeight(18)
        .fontColor($r('app.color.hold')).width('100%');
      TextArea({ placeholder: '例:这两天满房了,系统没同步过来',
        text: this.rejectReason })
        .height(96).onChange((v: string) => { this.rejectReason = v; });
      Row({ space: 10 }) {
        Button('取消')
          .layoutWeight(1).height(44)
          .backgroundColor($r('app.color.surface_alt'))
          .fontColor($r('app.color.ink'))
          .onClick(() => { this.showReject = false; });
        Button(this.busy ? '提交中…' : '确认拒单')
          .layoutWeight(1).height(44)
          .backgroundColor($r('app.color.surface_alt'))
          .fontColor($r('app.color.danger'))
          .enabled(!this.busy)
          .onClick(() => { this.doReject(); });
      }
      .width('100%');
    }
    .width('100%')
    .padding({ left: 18, right: 18, top: 18, bottom: 24 })
    .backgroundColor($r('app.color.surface'));
  }

  @Builder
  private replySheet() {
    Column({ space: 10 }) {
      Text('回复评价')
        .fontSize(17).fontWeight(FontWeight.Bold)
        .fontColor($r('app.color.ink')).width('100%');
      TextArea({ placeholder: '写一句给客人的话', text: this.replyText })
        .height(96).onChange((v: string) => { this.replyText = v; });
      Row({ space: 10 }) {
        Button('取消')
          .layoutWeight(1).height(44)
          .backgroundColor($r('app.color.surface_alt'))
          .fontColor($r('app.color.ink'))
          .onClick(() => { this.showReply = false; });
        Button('发布')
          .layoutWeight(1).height(44)
          .backgroundColor($r('app.color.brand'))
          .enabled(this.replyText.trim().length > 0)
          .onClick(() => { this.submitReply(); });
      }
      .width('100%');
    }
    .width('100%')
    .padding({ left: 18, right: 18, top: 18, bottom: 24 })
    .backgroundColor($r('app.color.surface'));
  }

  @Builder
  private calendarSheet() {
    Column({ space: 10 }) {
      Text('批量改价 / 关房')
        .fontSize(17).fontWeight(FontWeight.Bold)
        .fontColor($r('app.color.ink')).width('100%');
      Text('一次改一段日期,不用一天一天点。留空的项不改。')
        .fontSize(12).fontColor($r('app.color.ink_muted')).width('100%');

      Text('房型').fontSize(12)
        .fontColor($r('app.color.ink_muted')).width('100%');
      Flex({ wrap: FlexWrap.Wrap }) {
        ForEach(this.roomTypes, (r: Record<string, Object>) => {
          Text(`${r['name']}`)
            .fontSize(12)
            .fontColor(this.calRoomIds.indexOf(r['id'] as number) >= 0
              ? Color.White : $r('app.color.ink'))
            .padding({ left: 10, right: 10, top: 5, bottom: 5 })
            .margin({ right: 6, bottom: 6 })
            .borderRadius(12)
            .backgroundColor(this.calRoomIds.indexOf(r['id'] as number) >= 0
              ? $r('app.color.brand') : $r('app.color.surface_alt'))
            .onClick(() => {
              const id: number = r['id'] as number;
              const i: number = this.calRoomIds.indexOf(id);
              if (i >= 0) {
                this.calRoomIds.splice(i, 1);
              } else {
                this.calRoomIds.push(id);
              }
              this.calRoomIds = this.calRoomIds.slice();
            });
        }, (r: Record<string, Object>) => `${r['id']}`);
      }
      .width('100%');

      Row({ space: 8 }) {
        TextInput({ placeholder: '从 YYYY-MM-DD', text: this.calFrom })
          .height(42).layoutWeight(1)
          .onChange((v: string) => { this.calFrom = v; });
        TextInput({ placeholder: '到', text: this.calTo })
          .height(42).layoutWeight(1)
          .onChange((v: string) => { this.calTo = v; });
      }
      .width('100%');
      Row({ space: 8 }) {
        TextInput({ placeholder: '价格(元/晚)', text: this.calPrice })
          .type(InputType.Number).height(42).layoutWeight(1)
          .onChange((v: string) => { this.calPrice = v; });
        TextInput({ placeholder: '房量', text: this.calQty })
          .type(InputType.Number).height(42).layoutWeight(1)
          .onChange((v: string) => { this.calQty = v; });
      }
      .width('100%');
      Row({ space: 10 }) {
        Text('这段日期关房(不可订)')
          .fontSize(13).fontColor($r('app.color.ink')).layoutWeight(1);
        Toggle({ type: ToggleType.Switch, isOn: this.calClosed })
          .selectedColor($r('app.color.danger'))
          .onChange((v: boolean) => { this.calClosed = v; });
      }
      .width('100%');

      Row({ space: 10 }) {
        Button('取消')
          .layoutWeight(1).height(44)
          .backgroundColor($r('app.color.surface_alt'))
          .fontColor($r('app.color.ink'))
          .onClick(() => { this.showCalendar = false; });
        Button(this.busy ? '保存中…' : '保存')
          .layoutWeight(1).height(44)
          .backgroundColor($r('app.color.brand'))
          .enabled(!this.busy)
          .onClick(() => { this.saveCalendar(); });
      }
      .width('100%');
    }
    .width('100%')
    .padding({ left: 18, right: 18, top: 18, bottom: 24 })
    .backgroundColor($r('app.color.surface'));
  }

  @Builder
  private orderCard(o: Record<string, Object>) {
    Column({ space: 6 }) {
      Row() {
        Text(`${o['status_label'] ?? o['status']}`)
          .fontSize(13).fontWeight(FontWeight.Medium)
          .fontColor(o['status'] === 'pending'
            ? $r('app.color.danger') : $r('app.color.ink'));
        Blank();
        Text(yuan((o['total_cents'] ?? 0) as number))
          .fontSize(15).fontWeight(FontWeight.Bold)
          .fontColor($r('app.color.ink'));
      }
      .width('100%');
      Text(`${o['room_type_name'] ?? ''} · ${o['check_in'] ?? ''} 至 ${o['check_out'] ?? ''}`)
        .fontSize(13).fontColor($r('app.color.ink')).width('100%');
      Text(`${o['contact_name'] ?? ''} ${o['contact_phone'] ?? ''}`)
        .fontSize(12).fontColor($r('app.color.ink_muted')).width('100%');

      Row({ space: 8 }) {
        Blank();
        if (o['status'] === 'pending') {
          Button('拒单')
            .fontSize(12).height(30).padding({ left: 12, right: 12 })
            .backgroundColor($r('app.color.surface_alt'))
            .fontColor($r('app.color.danger'))
            .onClick(() => {
              this.rejectNo = `${o['order_no']}`;
              this.rejectReason = '';
              this.showReject = true;
            });
          Button('确认')
            .fontSize(12).height(30).padding({ left: 12, right: 12 })
            .backgroundColor($r('app.color.brand'))
            .enabled(!this.busy)
            .onClick(() => { this.confirm(`${o['order_no']}`); });
        } else if (o['status'] === 'confirmed') {
          Button('办入住')
            .fontSize(12).height(30).padding({ left: 12, right: 12 })
            .backgroundColor($r('app.color.brand'))
            .onClick(() => { this.checkin(`${o['order_no']}`); });
        } else if (o['status'] === 'checked_in') {
          Button('办退房')
            .fontSize(12).height(30).padding({ left: 12, right: 12 })
            .backgroundColor($r('app.color.surface_alt'))
            .fontColor($r('app.color.ink'))
            .onClick(() => { this.checkout(`${o['order_no']}`); });
        }
      }
      .width('100%');
    }
    .width('100%').padding(14)
    .backgroundColor($r('app.color.surface')).borderRadius(12)
    .margin({ bottom: 10 });
  }

  build() {
    Column() {
      Row({ space: 10 }) {
        Text('‹').fontSize(24).fontColor($r('app.color.ink'))
          .onClick(() => { this.onBack(); });
        Text('住宿')
          .fontSize(17).fontWeight(FontWeight.Bold)
          .fontColor($r('app.color.ink')).layoutWeight(1);
        if (this.tab === 1) {
          Text('批量设置')
            .fontSize(14).fontColor($r('app.color.brand'))
            .onClick(() => { this.showCalendar = true; });
        }
      }
      .width('100%')
      .padding({ left: 14, right: 14, top: 10, bottom: 10 })
      .backgroundColor($r('app.color.surface'));

      Row() {
        ForEach([0, 1, 2, 3], (i: number) => {
          Column({ space: 4 }) {
            Text(i === 0 ? '订单' : i === 1 ? '房型' : i === 2 ? '评价' : '售后')
              .fontSize(14)
              .fontWeight(this.tab === i ? FontWeight.Bold : FontWeight.Normal)
              .fontColor(this.tab === i
                ? $r('app.color.ink') : $r('app.color.ink_muted'));
            Divider().width(24).strokeWidth(2)
              .color(this.tab === i
                ? $r('app.color.brand') : Color.Transparent);
          }
          .layoutWeight(1).padding({ top: 10, bottom: 6 })
          .onClick(() => { this.tab = i; });
        }, (i: number) => `st${i}`);
      }
      .width('100%').backgroundColor($r('app.color.surface'));

      if (!this.loaded) {
        Column() {
          LoadingProgress().width(40).height(40);
        }
        .layoutWeight(1).justifyContent(FlexAlign.Center);
      } else if (this.tab === 0 && this.errorText.length > 0) {
        Column({ space: 12 }) {
          Text('住宿订单没能加载出来')
            .fontSize(15).fontColor($r('app.color.ink'));
          Text(`${this.errorText}\n\n空白不代表没有待确认的订单。`)
            .fontSize(13).lineHeight(20)
            .fontColor($r('app.color.ink_muted')).textAlign(TextAlign.Center);
          Button('重试').height(40).width(130)
            .backgroundColor($r('app.color.brand'))
            .onClick(() => { this.load(); });
        }
        .layoutWeight(1).justifyContent(FlexAlign.Center).padding(30);
      } else {
        Scroll() {
          Column() {
            if (this.tab === 0) {
              if (this.orders.length === 0) {
                Text('还没有住宿订单')
                  .fontSize(14).fontColor($r('app.color.ink_muted'))
                  .width('100%').textAlign(TextAlign.Center)
                  .padding({ top: 40, bottom: 40 });
              } else {
                ForEach(this.orders, (o: Record<string, Object>) => {
                  this.orderCard(o);
                }, (o: Record<string, Object>) => `${o['order_no']}`);
              }
            } else if (this.tab === 1) {
              if (this.roomTypes.length === 0) {
                Text('还没有房型。新增房型要填面积、床型、设施,\n' +
                  '这一版请在安卓端或网页端添加。')
                  .fontSize(13).lineHeight(20)
                  .fontColor($r('app.color.ink_muted'))
                  .width('100%').textAlign(TextAlign.Center)
                  .padding({ top: 40, bottom: 40 });
              } else {
                ForEach(this.roomTypes, (r: Record<string, Object>) => {
                  Row() {
                    Column({ space: 2 }) {
                      Text(`${r['name']}`).fontSize(15)
                        .fontColor($r('app.color.ink'));
                      Text(`${yuan((r['price_cents'] ?? 0) as number)}/晚 · ` +
                        `共 ${r['total_qty'] ?? 0} 间`)
                        .fontSize(12).fontColor($r('app.color.ink_muted'));
                    }
                    .alignItems(HorizontalAlign.Start).layoutWeight(1);
                    Toggle({ type: ToggleType.Switch,
                      isOn: r['on_sale'] !== false })
                      .selectedColor($r('app.color.brand'))
                      .onChange((on: boolean) => {
                        this.api.updateRoomType(r['id'] as number,
                          { on_sale: on } as object)
                          .then(() => { this.load(); })
                          .catch((e: Object) => {
                            promptAction.showToast({
                              message: (e as ApiException).message,
                            });
                          });
                      });
                  }
                  .width('100%').padding(14)
                  .backgroundColor($r('app.color.surface')).borderRadius(12)
                  .margin({ bottom: 10 });
                }, (r: Record<string, Object>) => `${r['id']}`);
              }
            } else if (this.tab === 2) {
              if (this.reviews.length === 0) {
                Text('还没有评价')
                  .fontSize(14).fontColor($r('app.color.ink_muted'))
                  .width('100%').textAlign(TextAlign.Center)
                  .padding({ top: 40, bottom: 40 });
              } else {
                ForEach(this.reviews, (r: Record<string, Object>) => {
                  Column({ space: 6 }) {
                    Text(`${'★'.repeat((r['rating'] ?? 5) as number)}`)
                      .fontSize(13).fontColor($r('app.color.hold'))
                      .width('100%');
                    Text(`${r['comment'] ?? ''}`)
                      .fontSize(14).lineHeight(21)
                      .fontColor($r('app.color.ink')).width('100%');
                    if (`${r['reply'] ?? ''}`.length > 0) {
                      Text(`你的回复:${r['reply']}`)
                        .fontSize(12).fontColor($r('app.color.ink_muted'))
                        .width('100%');
                    } else {
                      Row() {
                        Blank();
                        Button('回复')
                          .fontSize(12).height(30)
                          .padding({ left: 12, right: 12 })
                          .backgroundColor($r('app.color.brand'))
                          .onClick(() => {
                            this.replyId = r['id'] as number;
                            this.replyText = '';
                            this.showReply = true;
                          });
                      }
                      .width('100%');
                    }
                  }
                  .width('100%').padding(14)
                  .backgroundColor($r('app.color.surface')).borderRadius(12)
                  .margin({ bottom: 10 });
                }, (r: Record<string, Object>) => `${r['id']}`);
              }
            } else {
              if (this.aftersales.length === 0) {
                Text('没有待处理的售后')
                  .fontSize(14).fontColor($r('app.color.ink_muted'))
                  .width('100%').textAlign(TextAlign.Center)
                  .padding({ top: 40, bottom: 40 });
              } else {
                ForEach(this.aftersales, (a: Record<string, Object>) => {
                  Column({ space: 6 }) {
                    Text(`${a['reason'] ?? ''}`)
                      .fontSize(14).lineHeight(21)
                      .fontColor($r('app.color.ink')).width('100%');
                    Row({ space: 8 }) {
                      Blank();
                      Button('拒绝')
                        .fontSize(12).height(30)
                        .padding({ left: 12, right: 12 })
                        .backgroundColor($r('app.color.surface_alt'))
                        .fontColor($r('app.color.danger'))
                        .onClick(() => {
                          this.respond(a['id'] as number, false);
                        });
                      Button('同意退款')
                        .fontSize(12).height(30)
                        .padding({ left: 12, right: 12 })
                        .backgroundColor($r('app.color.brand'))
                        .onClick(() => {
                          this.respond(a['id'] as number, true);
                        });
                    }
                    .width('100%');
                  }
                  .width('100%').padding(14)
                  .backgroundColor($r('app.color.surface')).borderRadius(12)
                  .margin({ bottom: 10 });
                }, (a: Record<string, Object>) => `${a['id']}`);
              }
            }
          }
          .width('100%').padding({ left: 12, right: 12, top: 10 });
        }
        .layoutWeight(1).scrollBar(BarState.Off);
      }
    }
    .width('100%').height('100%')
    .backgroundColor($r('app.color.page'))
    .bindSheet($$this.showReject, this.rejectSheet(),
      { height: 320, dragBar: false })
    .bindSheet($$this.showReply, this.replySheet(),
      { height: 280, dragBar: false })
    .bindSheet($$this.showCalendar, this.calendarSheet(),
      { height: '72%', dragBar: true });
  }
}
