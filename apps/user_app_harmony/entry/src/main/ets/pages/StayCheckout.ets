import { promptAction } from '@kit.ArkUI';
import { UserApi } from '../common/UserApi';
import { ApiException } from '../common/Api';
import { Session } from '../common/Session';
import { yuan } from '../common/Money';

/**
 * 酒店详情与下单。
 *
 * 住宿这条线之前是「看得见买不了」——列表和订单都有,唯独没有详情和下单页。
 *
 * 产品口径要写在页面上:**佣金 5%,离店才收**。订单取消、客人未入住,
 * 平台分文不取;无排他、无竞价排名、无年费。用户对 OTA 最大的不信任
 * 就是"看不见的差价",这几句是回答那个不信任的。
 *
 * ⚠️ **取消政策必须在下单前就明示**,不能等取消时才告诉他扣多少 ——
 * 那正是 OTA 最被骂的做法。
 */
@Component
export struct HotelDetailPage {
  hotelId: number = 0;
  onBooked: (orderNo: string) => void = () => {};
  onNeedLogin: () => void = () => {};

  @State private hotel: Record<string, Object> | null = null;
  @State private rooms: Record<string, Object>[] = [];
  @State private reviews: Record<string, Object>[] = [];
  @State private loading: boolean = true;
  @State private error: string = '';
  /** 选中的房型 */
  @State private pickedRoom: number = 0;
  @State private checkin: string = '';
  @State private checkout: string = '';
  @State private roomsQty: number = 1;
  @State private guestName: string = '';
  @State private guestPhone: string = '';
  @State private submitting: boolean = false;

  private api: UserApi = new UserApi();

  async aboutToAppear(): Promise<void> {
    // 默认今天入住、明天离店,省得用户先去点两次日期
    const now: Date = new Date();
    this.checkin = this.fmt(now);
    this.checkout = this.fmt(new Date(now.getTime() + 86400000));
    this.guestName = Session.get().userName;
    this.guestPhone = Session.get().userPhone;
    await this.load();
  }

  private fmt(d: Date): string {
    const m: number = d.getMonth() + 1;
    const day: number = d.getDate();
    return `${d.getFullYear()}-${m < 10 ? '0' : ''}${m}-${day < 10 ? '0' : ''}${day}`;
  }

  private async load(): Promise<void> {
    this.loading = true;
    this.error = '';
    try {
      this.hotel = await this.api.hotelDetail(this.hotelId);
      const rt: Object = this.hotel['room_types'] ?? [];
      this.rooms = rt as Record<string, Object>[];
      if (this.rooms.length > 0) {
        this.pickedRoom = this.num(this.rooms[0], 'id');
      }
      this.api.hotelReviews(this.hotelId)
        .then((r: Record<string, Object>[]) => { this.reviews = r; })
        .catch(() => {});
    } catch (e) {
      this.error = (e as ApiException).message;
    } finally {
      this.loading = false;
    }
  }

  private str(m: Record<string, Object> | null, key: string): string {
    if (m === null) {
      return '';
    }
    const v: Object = m[key] ?? '';
    return typeof v === 'string' ? v : '';
  }

  private num(m: Record<string, Object> | null, key: string): number {
    if (m === null) {
      return 0;
    }
    const v: Object = m[key] ?? 0;
    return typeof v === 'number' ? v : 0;
  }

  private get room(): Record<string, Object> | null {
    const f: Record<string, Object> | undefined = this.rooms.find(
      (r: Record<string, Object>) => this.num(r, 'id') === this.pickedRoom);
    return f === undefined ? null : f;
  }

  /** 住几晚。日期差按天算,不做时区花活 */
  private get nights(): number {
    const a: number = Date.parse(this.checkin);
    const b: number = Date.parse(this.checkout);
    if (isNaN(a) || isNaN(b) || b <= a) {
      return 0;
    }
    return Math.round((b - a) / 86400000);
  }

  private get total(): number {
    return this.num(this.room, 'price_cents') * this.nights * this.roomsQty;
  }

  private get valid(): boolean {
    return this.room !== null && this.nights > 0
      && this.guestName.trim().length > 0
      && /^1[3-9]\d{9}$/.test(this.guestPhone);
  }

  private async submit(): Promise<void> {
    if (!Session.get().isLoggedIn) {
      this.onNeedLogin();
      return;
    }
    if (!this.valid || this.submitting) {
      return;
    }
    this.submitting = true;
    try {
      const body: Record<string, Object> = {
        'room_type_id': this.pickedRoom,
        'checkin_date': this.checkin,
        'checkout_date': this.checkout,
        'rooms_qty': this.roomsQty,
        'guest_name': this.guestName.trim(),
        'guest_phone': this.guestPhone.trim(),
      };
      const order: Record<string, Object> = await this.api.createStayOrder(body);
      // 住宿的支付和外卖不是一套通道。微信支付接上之前**不许假装成功**
      promptAction.showToast({
        message: '已下单,等商家确认。支付待微信支付接入,可在住宿订单里继续',
        duration: 4000,
      });
      this.onBooked(this.str(order, 'order_no'));
    } catch (e) {
      promptAction.showToast({ message: (e as ApiException).message, duration: 4000 });
    } finally {
      this.submitting = false;
    }
  }

  @Builder
  private roomRow(r: Record<string, Object>) {
    Row() {
      Column({ space: 3 }) {
        Text(this.str(r, 'name'))
          .fontSize(15).fontColor($r('app.color.ink'));
        if (this.str(r, 'bed_type').length > 0) {
          Text(this.str(r, 'bed_type'))
            .fontSize(12).fontColor($r('app.color.ink_muted'));
        }
        if (this.num(r, 'stock') >= 0) {
          Text(this.num(r, 'stock') > 0
            ? `余 ${this.num(r, 'stock')} 间` : '今日满房')
            .fontSize(11)
            .fontColor(this.num(r, 'stock') > 0
              ? $r('app.color.ink_muted') : $r('app.color.brand'));
        }
      }
      .layoutWeight(1).alignItems(HorizontalAlign.Start);
      Column({ space: 2 }) {
        Text(`${yuan(this.num(r, 'price_cents'))}/晚`)
          .fontSize(15).fontColor($r('app.color.brand'));
        Text(this.pickedRoom === this.num(r, 'id') ? '已选' : '选它')
          .fontSize(12)
          .fontColor(this.pickedRoom === this.num(r, 'id')
            ? $r('app.color.brand') : $r('app.color.ink_muted'));
      }
      .alignItems(HorizontalAlign.End);
    }
    .width('100%').padding(14)
    .backgroundColor(this.pickedRoom === this.num(r, 'id')
      ? $r('app.color.brand_soft') : $r('app.color.surface'))
    .borderRadius(12)
    .onClick(() => { this.pickedRoom = this.num(r, 'id'); });
  }

  build() {
    Column() {
      if (this.loading) {
        Column() { LoadingProgress().width(36).height(36); }
        .width('100%').layoutWeight(1).justifyContent(FlexAlign.Center);
      } else if (this.error.length > 0 || this.hotel === null) {
        Column({ space: 12 }) {
          Text(this.error.length > 0 ? this.error : '酒店信息加载失败')
            .fontSize(14).fontColor($r('app.color.ink_muted'));
          Button('重试').onClick(() => { this.load(); });
        }
        .width('100%').layoutWeight(1).justifyContent(FlexAlign.Center);
      } else {
        Scroll() {
          Column({ space: 10 }) {
            Column({ space: 6 }) {
              Text(this.str(this.hotel, 'name'))
                .fontSize(19).fontWeight(FontWeight.Bold)
                .fontColor($r('app.color.ink')).width('100%');
              Text(this.str(this.hotel, 'address'))
                .fontSize(12).fontColor($r('app.color.ink_muted')).width('100%');
              Text('佣金 5%,离店才收 —— 取消或没入住,平台分文不取')
                .fontSize(12).fontColor($r('app.color.earn')).width('100%');
            }
            .width('100%').padding(16).backgroundColor($r('app.color.surface'))
            .borderRadius(14).alignItems(HorizontalAlign.Start);

            // 取消政策**下单前就写清楚**,不等取消时才说
            if (this.str(this.hotel, 'cancel_policy').length > 0) {
              Column({ space: 4 }) {
                Text('取消政策')
                  .fontSize(14).fontWeight(FontWeight.Medium)
                  .fontColor($r('app.color.ink')).width('100%');
                Text(this.str(this.hotel, 'cancel_policy'))
                  .fontSize(12).fontColor($r('app.color.ink_muted')).width('100%');
                Text('到店无房商家赔首晚 30% 违约金给你')
                  .fontSize(12).fontColor($r('app.color.earn')).width('100%');
              }
              .width('100%').padding(16).backgroundColor($r('app.color.surface'))
              .borderRadius(14).alignItems(HorizontalAlign.Start);
            }

            Column({ space: 8 }) {
              Text('选房型')
                .fontSize(15).fontWeight(FontWeight.Medium)
                .fontColor($r('app.color.ink')).width('100%');
              if (this.rooms.length === 0) {
                Text('这家店还没有可订的房型')
                  .fontSize(13).fontColor($r('app.color.ink_muted')).width('100%');
              }
              ForEach(this.rooms, (r: Record<string, Object>) => {
                this.roomRow(r);
              }, (r: Record<string, Object>) => `${this.num(r, 'id')}`);
            }
            .width('100%').padding(12).alignItems(HorizontalAlign.Start);

            Column({ space: 10 }) {
              Text('入住信息')
                .fontSize(15).fontWeight(FontWeight.Medium)
                .fontColor($r('app.color.ink')).width('100%');
              Row({ space: 10 }) {
                TextInput({ placeholder: '入住 2026-08-09', text: this.checkin })
                  .height(44).layoutWeight(1)
                  .onChange((v: string) => { this.checkin = v; });
                TextInput({ placeholder: '离店 2026-08-10', text: this.checkout })
                  .height(44).layoutWeight(1)
                  .onChange((v: string) => { this.checkout = v; });
              }
              .width('100%');
              Row({ space: 10 }) {
                Text('房间数')
                  .fontSize(13).fontColor($r('app.color.ink_muted')).layoutWeight(1);
                Button('−').width(30).height(30).fontSize(16)
                  .backgroundColor($r('app.color.surface_alt')).fontColor($r('app.color.ink'))
                  .onClick(() => {
                    if (this.roomsQty > 1) {
                      this.roomsQty -= 1;
                    }
                  });
                Text(`${this.roomsQty}`).fontSize(14);
                Button('+').width(30).height(30).fontSize(16)
                  .backgroundColor($r('app.color.brand'))
                  .onClick(() => { this.roomsQty += 1; });
              }
              .width('100%');
              TextInput({ placeholder: '入住人姓名', text: this.guestName })
                .height(44).onChange((v: string) => { this.guestName = v; });
              TextInput({ placeholder: '手机号', text: this.guestPhone })
                .type(InputType.PhoneNumber).maxLength(11).height(44)
                .onChange((v: string) => { this.guestPhone = v; });
            }
            .width('100%').padding(16).backgroundColor($r('app.color.surface'))
            .borderRadius(14).alignItems(HorizontalAlign.Start);

            if (this.reviews.length > 0) {
              Column({ space: 6 }) {
                Text(`住客点评 ${this.reviews.length}`)
                  .fontSize(15).fontWeight(FontWeight.Medium)
                  .fontColor($r('app.color.ink')).width('100%');
                ForEach(this.reviews.slice(0, 5), (r: Record<string, Object>) => {
                  Column({ space: 2 }) {
                    Text(`${this.num(r, 'rating')} 分`)
                      .fontSize(12).fontColor($r('app.color.brand')).width('100%');
                    Text(this.str(r, 'comment'))
                      .fontSize(13).fontColor($r('app.color.ink')).width('100%');
                  }
                  .width('100%').padding({ top: 6, bottom: 6 })
                  .alignItems(HorizontalAlign.Start);
                }, (r: Record<string, Object>) => `${this.num(r, 'id')}`);
              }
              .width('100%').padding(16).backgroundColor($r('app.color.surface'))
              .borderRadius(14).alignItems(HorizontalAlign.Start);
            }
          }
          .width('100%').padding({ left: 12, right: 12, top: 12, bottom: 16 });
        }
        .layoutWeight(1).scrollBar(BarState.Off);

        Row() {
          Column({ space: 2 }) {
            Text(this.nights > 0 ? yuan(this.total) : '选好日期')
              .fontSize(18).fontWeight(FontWeight.Bold)
              .fontColor($r('app.color.brand'));
            if (this.nights > 0) {
              Text(`${this.nights} 晚 × ${this.roomsQty} 间`)
                .fontSize(11).fontColor($r('app.color.ink_muted'));
            }
          }
          .layoutWeight(1).alignItems(HorizontalAlign.Start);
          Button(this.submitting ? '提交中…' : '预订')
            .width(120).height(44)
            .enabled(this.valid && !this.submitting)
            .backgroundColor(this.valid
              ? $r('app.color.brand') : $r('app.color.line'))
            .onClick(() => { this.submit(); });
        }
        .width('100%').padding(12).backgroundColor($r('app.color.surface'))
        .border({ width: { top: 1 }, color: $r('app.color.line') });
      }
    }
    .width('100%').height('100%').backgroundColor($r('app.color.page'));
  }
}
