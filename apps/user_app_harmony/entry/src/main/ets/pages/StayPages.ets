import { promptAction } from '@kit.ArkUI';
import { UserApi } from '../common/UserApi';
import { ApiException } from '../common/Api';
import { yuan } from '../common/Money';

/**
 * 住宿。
 *
 * 产品口径:**佣金 5%,离店才收** —— 订单取消、客人未入住,平台分文不取。
 * 无排他、无竞价排名、无年费。这几句要写在列表页上:
 * 用户对 OTA 最大的不信任就是"看不见的差价"。
 *
 * 取消**先试算再确认**:扣多少先算清楚,不做"点了才知道"。
 */
@Component
export struct HotelListPage {
  lat: number = 0;
  lng: number = 0;
  onOpenHotel: (hotelId: number) => void = () => {};

  @State private hotels: Record<string, Object>[] = [];
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
      const q: Record<string, string> = {
        'lat': `${this.lat}`,
        'lng': `${this.lng}`,
      };
      this.hotels = await this.api.hotels(q);
    } catch (e) {
      this.error = (e as ApiException).message;
    } finally {
      this.loading = false;
    }
  }

  private str(m: Record<string, Object>, key: string): string {
    const v: Object = m[key] ?? '';
    return typeof v === 'string' ? v : '';
  }

  private num(m: Record<string, Object>, key: string): number {
    const v: Object = m[key] ?? 0;
    return typeof v === 'number' ? v : 0;
  }

  @Builder
  private card(h: Record<string, Object>) {
    Column({ space: 6 }) {
      Text(this.str(h, 'name'))
        .fontSize(16).fontWeight(FontWeight.Medium)
        .fontColor($r('app.color.ink')).width('100%');
      Text(this.str(h, 'address'))
        .fontSize(12).fontColor($r('app.color.ink_muted')).width('100%')
        .maxLines(1).textOverflow({ overflow: TextOverflow.Ellipsis });
      Row({ space: 8 }) {
        if (this.num(h, 'min_price_cents') > 0) {
          Text(`${yuan(this.num(h, 'min_price_cents'))} 起`)
            .fontSize(16).fontColor($r('app.color.brand'));
        }
        if (this.num(h, 'rating_avg') > 0) {
          Text(`${this.num(h, 'rating_avg').toFixed(1)} 分`)
            .fontSize(12).fontColor($r('app.color.ink_muted'));
        }
      }
      .width('100%');
    }
    .width('100%').padding(14).backgroundColor($r('app.color.surface'))
    .borderRadius(14).alignItems(HorizontalAlign.Start)
    .onClick(() => { this.onOpenHotel(this.num(h, 'id')); });
  }

  build() {
    Column() {
      Text('佣金 5%,离店才收 —— 取消或没入住,平台分文不取')
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
      } else if (this.hotels.length === 0) {
        Column() {
          Text('这一带还没有酒店入驻')
            .fontSize(14).fontColor($r('app.color.ink_muted'));
        }
        .width('100%').layoutWeight(1).justifyContent(FlexAlign.Center);
      } else {
        List({ space: 10 }) {
          ForEach(this.hotels, (h: Record<string, Object>) => {
            ListItem() { this.card(h); }
          }, (h: Record<string, Object>) => `${this.num(h, 'id')}`);
        }
        .width('100%').layoutWeight(1)
        .padding({ left: 12, right: 12, bottom: 12 })
        .scrollBar(BarState.Off);
      }
    }
    .width('100%').height('100%').backgroundColor($r('app.color.page'));
  }
}

/** 我的住宿订单。取消前先试算,把要扣多少说清楚再让用户确认 */
@Component
export struct StayOrdersPage {
  onOpenAfter: (orderNo: string) => void = () => {};

  @State private orders: Record<string, Object>[] = [];
  @State private loading: boolean = true;
  @State private preview: Record<string, Object> | null = null;
  @State private pendingCancel: string = '';

  private api: UserApi = new UserApi();

  async aboutToAppear(): Promise<void> {
    await this.load();
  }

  private async load(): Promise<void> {
    this.loading = true;
    try {
      this.orders = await this.api.myStayOrders();
    } catch (e) {
      this.orders = [];
    } finally {
      this.loading = false;
    }
  }

  private str(m: Record<string, Object>, key: string): string {
    const v: Object = m[key] ?? '';
    return typeof v === 'string' ? v : '';
  }

  private num(m: Record<string, Object>, key: string): number {
    const v: Object = m[key] ?? 0;
    return typeof v === 'number' ? v : 0;
  }

  /** 先试算。**不做"点了才知道扣多少"** */
  private async askCancel(orderNo: string): Promise<void> {
    try {
      this.preview = await this.api.stayCancelPreview(orderNo);
      this.pendingCancel = orderNo;
    } catch (e) {
      promptAction.showToast({ message: (e as ApiException).message });
    }
  }

  private async doCancel(): Promise<void> {
    if (this.pendingCancel.length === 0) {
      return;
    }
    try {
      await this.api.cancelStayOrder(this.pendingCancel);
      this.pendingCancel = '';
      this.preview = null;
      await this.load();
      promptAction.showToast({ message: '已取消' });
    } catch (e) {
      promptAction.showToast({ message: (e as ApiException).message });
    }
  }

  build() {
    Stack() {
      Column() {
        if (this.loading) {
          Column() { LoadingProgress().width(36).height(36); }
          .width('100%').layoutWeight(1).justifyContent(FlexAlign.Center);
        } else if (this.orders.length === 0) {
          Column() {
            Text('还没有住宿订单')
              .fontSize(14).fontColor($r('app.color.ink_muted'));
          }
          .width('100%').layoutWeight(1).justifyContent(FlexAlign.Center);
        } else {
          List({ space: 10 }) {
            ForEach(this.orders, (o: Record<string, Object>) => {
              ListItem() {
                Column({ space: 6 }) {
                  Row() {
                    Text(this.str(o, 'hotel_name'))
                      .fontSize(15).fontWeight(FontWeight.Medium)
                      .fontColor($r('app.color.ink')).layoutWeight(1);
                    Text(this.str(o, 'status_label').length > 0
                      ? this.str(o, 'status_label') : this.str(o, 'status'))
                      .fontSize(12).fontColor($r('app.color.brand'));
                  }
                  .width('100%');
                  Text(`${this.str(o, 'checkin_date')} 至 ${this.str(o, 'checkout_date')}`)
                    .fontSize(12).fontColor($r('app.color.ink_muted')).width('100%');
                  Row() {
                    Text(yuan(this.num(o, 'total_cents')))
                      .fontSize(15).fontWeight(FontWeight.Bold)
                      .fontColor($r('app.color.ink')).layoutWeight(1);
                    if (this.str(o, 'status') !== 'cancelled'
                      && this.str(o, 'status') !== 'checked_out') {
                      Text('取消')
                        .fontSize(13).fontColor($r('app.color.ink_muted'))
                        .margin({ right: 14 })
                        .onClick(() => { this.askCancel(this.str(o, 'order_no')); });
                    }
                    Text('评价 / 售后')
                      .fontSize(13).fontColor($r('app.color.brand'))
                      .onClick(() => { this.onOpenAfter(this.str(o, 'order_no')); });
                  }
                  .width('100%');
                }
                .width('100%').padding(14).backgroundColor($r('app.color.surface'))
                .borderRadius(14).alignItems(HorizontalAlign.Start);
              }
            }, (o: Record<string, Object>) => this.str(o, 'order_no'));
          }
          .width('100%').layoutWeight(1)
          .padding({ left: 12, right: 12, top: 12, bottom: 12 })
          .scrollBar(BarState.Off);
        }
      }
      .width('100%').height('100%').backgroundColor($r('app.color.page'));

      if (this.preview !== null) {
        Column() {
          Column({ space: 10 }) {
            Text('取消这一单')
              .fontSize(17).fontWeight(FontWeight.Medium)
              .fontColor($r('app.color.ink')).width('100%');
            Row() {
              Text('可退金额')
                .fontSize(14).fontColor($r('app.color.ink_muted')).layoutWeight(1);
              Text(yuan(this.num(this.preview, 'refund_cents')))
                .fontSize(18).fontWeight(FontWeight.Bold)
                .fontColor($r('app.color.earn'));
            }
            .width('100%');
            if (this.num(this.preview, 'penalty_cents') > 0) {
              Row() {
                Text('按取消政策扣')
                  .fontSize(14).fontColor($r('app.color.ink_muted')).layoutWeight(1);
                Text(yuan(this.num(this.preview, 'penalty_cents')))
                  .fontSize(14).fontColor($r('app.color.brand'));
              }
              .width('100%');
            }
            Text('取消政策在下单前就写明了,这里只是把数算给你看')
              .fontSize(11).fontColor($r('app.color.ink_muted')).width('100%');
            Row({ space: 10 }) {
              Button('再想想')
                .layoutWeight(1).height(42)
                .backgroundColor($r('app.color.surface_alt')).fontColor($r('app.color.ink'))
                .onClick(() => {
                  this.preview = null;
                  this.pendingCancel = '';
                });
              Button('确认取消')
                .layoutWeight(1).height(42)
                .backgroundColor($r('app.color.brand'))
                .onClick(() => { this.doCancel(); });
            }
            .width('100%');
          }
          .width('100%').padding(18).backgroundColor($r('app.color.surface'))
          .borderRadius({ topLeft: 18, topRight: 18 })
          .alignItems(HorizontalAlign.Start);
        }
        .width('100%').height('100%')
        .justifyContent(FlexAlign.End)
        .backgroundColor($r('app.color.scrim'));
      }
    }
    .width('100%').height('100%');
  }
}


/**
 * 住宿评价与售后。
 *
 * **到店无房**是这条线最要紧的一类售后:产品口径写着商家赔首晚 30% 违约金,
 * 而这个承诺只有在用户报得上来的时候才算数 —— 所以入口要给足。
 */
@Component
export struct StayAfterPage {
  orderNo: string = '';
  onDone: () => void = () => {};

  /** 0 写评价 / 1 报售后 */
  @State private tab: number = 0;
  @State private rating: number = 5;
  @State private comment: string = '';
  @State private kind: string = 'no_room';
  @State private note: string = '';
  @State private existing: Record<string, Object> | null = null;
  @State private submitting: boolean = false;

  private api: UserApi = new UserApi();

  async aboutToAppear(): Promise<void> {
    try {
      this.existing = await this.api.myStayReview(this.orderNo);
    } catch (e) {
      this.existing = null;
    }
  }

  private async submitReview(): Promise<void> {
    if (this.submitting) {
      return;
    }
    this.submitting = true;
    try {
      await this.api.createStayReview(this.orderNo, this.rating,
        this.comment.trim());
      promptAction.showToast({ message: '评价已提交,谢谢' });
      this.onDone();
    } catch (e) {
      promptAction.showToast({ message: (e as ApiException).message });
    } finally {
      this.submitting = false;
    }
  }

  private async submitAfterSale(): Promise<void> {
    if (this.note.trim().length === 0) {
      promptAction.showToast({ message: '说一下发生了什么' });
      return;
    }
    this.submitting = true;
    try {
      await this.api.createStayAftersale(this.orderNo, this.kind,
        this.note.trim());
      promptAction.showToast({
        message: '已提交,平台会介入处理',
        duration: 3000,
      });
      this.onDone();
    } catch (e) {
      promptAction.showToast({ message: (e as ApiException).message });
    } finally {
      this.submitting = false;
    }
  }

  @Builder
  private kindChip(label: string, value: string, hint: string) {
    Column({ space: 2 }) {
      Text(label)
        .fontSize(14)
        .fontColor(this.kind === value
          ? $r('app.color.brand') : $r('app.color.ink'));
      Text(hint).fontSize(11).fontColor($r('app.color.ink_muted'));
    }
    .width('100%').padding(12).borderRadius(10)
    .backgroundColor(this.kind === value
      ? $r('app.color.brand_soft') : $r('app.color.surface'))
    .alignItems(HorizontalAlign.Start)
    .onClick(() => { this.kind = value; });
  }

  build() {
    Scroll() {
      Column({ space: 12 }) {
        Row() {
          ForEach([0, 1], (i: number) => {
            Text(i === 0 ? '写评价' : '报售后')
              .fontSize(14)
              .fontColor(this.tab === i
                ? $r('app.color.brand') : $r('app.color.ink_muted'))
              .layoutWeight(1).textAlign(TextAlign.Center)
              .padding({ top: 10, bottom: 10 })
              .onClick(() => { this.tab = i; });
          }, (i: number) => `${i}`);
        }
        .width('100%').backgroundColor($r('app.color.surface'))
        .borderRadius(12);

        if (this.tab === 0) {
          if (this.existing !== null) {
            Text('这一单你已经评价过了')
              .fontSize(14).fontColor($r('app.color.ink_muted')).width('100%');
          } else {
            Column({ space: 10 }) {
              Text('住得怎么样')
                .fontSize(15).fontWeight(FontWeight.Medium)
                .fontColor($r('app.color.ink')).width('100%');
              Row({ space: 6 }) {
                ForEach([1, 2, 3, 4, 5], (i: number) => {
                  Text(i <= this.rating ? '★' : '☆')
                    .fontSize(26)
                    .fontColor(i <= this.rating
                      ? $r('app.color.brand') : $r('app.color.line'))
                    .onClick(() => { this.rating = i; });
                }, (i: number) => `s${i}`);
              }
              TextArea({ placeholder: '想说点什么(选填)', text: this.comment })
                .height(100)
                .onChange((v: string) => { this.comment = v; });
              Button(this.submitting ? '提交中…' : '提交评价')
                .width('100%').height(46)
                .enabled(!this.submitting)
                .backgroundColor($r('app.color.brand'))
                .onClick(() => { this.submitReview(); });
            }
            .width('100%').padding(16).backgroundColor($r('app.color.surface'))
            .borderRadius(12).alignItems(HorizontalAlign.Start);
          }
        } else {
          Column({ space: 8 }) {
            // 到店无房排第一:它对应的是一条有金额的承诺,不是普通抱怨
            this.kindChip('到店无房', 'no_room',
              '商家赔你首晚 30% 违约金,这是写在产品口径里的');
            this.kindChip('房间与描述不符', 'not_as_described', '设施、房型、面积对不上');
            this.kindChip('卫生问题', 'hygiene', '');
            this.kindChip('其他', 'other', '');
            TextArea({ placeholder: '说清楚发生了什么,处理会更快', text: this.note })
              .height(100)
              .onChange((v: string) => { this.note = v; });
            Button(this.submitting ? '提交中…' : '提交')
              .width('100%').height(46)
              .enabled(!this.submitting)
              .backgroundColor($r('app.color.brand'))
              .onClick(() => { this.submitAfterSale(); });
          }
          .width('100%').padding(12).alignItems(HorizontalAlign.Start);
        }
      }
      .width('100%').padding(12).alignItems(HorizontalAlign.Start);
    }
    .width('100%').height('100%').backgroundColor($r('app.color.page'));
  }
}
