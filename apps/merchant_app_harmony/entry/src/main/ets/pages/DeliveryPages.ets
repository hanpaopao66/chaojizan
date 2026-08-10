import { common } from '@kit.AbilityKit';
import { MerchantApi } from '../common/MerchantApi';
import { ApiException } from '../common/Api';
import { distanceMeters, navigateTo } from '../common/Geo';
import { distanceText } from '../common/Money';
import { MerchantOrder, OrderStatus, Shop } from '../model/Models';

/**
 * 自配送:送去哪、多远。
 *
 * 商家自送时和骑手是同一种处境:**要先知道送去哪、多远,再决定这单自不自送**。
 * 此前商家端全程没有这个,只有一行文字地址 —— 远近全靠猜,
 * 猜错了就是自己骑半小时送一单 3 块钱配送费的活。
 *
 * 没有地图 SDK(要开发者账号,和推送同一个卡点),所以给距离 + 拉起系统地图。
 * 这不是凑合:商家本来也要切到高德/百度才能真正导航。
 */
@Component
export struct SelfDeliveryPage {
  @Prop order: MerchantOrder;
  @Prop shop: Shop;
  onBack: () => void = () => {};

  private meters(): number | null {
    const sLat: number | undefined = this.shop.lat;
    const sLng: number | undefined = this.shop.lng;
    const oLat: number | undefined = this.order.lat;
    const oLng: number | undefined = this.order.lng;
    if (sLat === undefined || sLng === undefined
        || oLat === undefined || oLng === undefined) {
      return null;
    }
    return distanceMeters(sLat, sLng, oLat, oLng);
  }

  build() {
    Column() {
      Row({ space: 10 }) {
        Text('‹').fontSize(24).fontColor($r('app.color.ink'))
          .onClick(() => { this.onBack(); });
        Text('自配送 · 送去哪')
          .fontSize(17).fontWeight(FontWeight.Bold)
          .fontColor($r('app.color.ink')).layoutWeight(1);
      }
      .width('100%')
      .padding({ left: 14, right: 14, top: 10, bottom: 10 })
      .backgroundColor($r('app.color.surface'));

      Column({ space: 12 }) {
        Column({ space: 8 }) {
          Text('直线距离')
            .fontSize(13).fontColor($r('app.color.ink_muted')).width('100%');
          Text(this.meters() === null
            ? '算不出来(缺坐标)' : distanceText(this.meters() as number))
            .fontSize(30).fontWeight(FontWeight.Bold)
            .fontColor($r('app.color.ink')).width('100%');
          Text('实际骑行距离通常比直线远三到五成。这单配送费 ' +
            `${((this.order.delivery_fee_cents ?? 0) / 100).toFixed(2)} 元,` +
            '自送的话这笔归你。')
            .fontSize(12).lineHeight(19)
            .fontColor($r('app.color.ink_muted')).width('100%');
        }
        .width('100%').padding(14)
        .backgroundColor($r('app.color.surface')).borderRadius(12);

        Column({ space: 6 }) {
          Text('送到')
            .fontSize(13).fontColor($r('app.color.ink_muted')).width('100%');
          Text(this.order.address ?? '')
            .fontSize(16).lineHeight(24)
            .fontColor($r('app.color.ink')).width('100%');
          Text(`${this.order.contact_name ?? ''} ${this.order.contact_phone ?? ''}`)
            .fontSize(14).fontColor($r('app.color.ink')).width('100%');
          if (this.order.to_door === false) {
            Text('顾客选了送到楼下,不用上楼')
              .fontSize(12).fontColor($r('app.color.hold')).width('100%');
          }
        }
        .width('100%').padding(14)
        .backgroundColor($r('app.color.surface')).borderRadius(12);

        Button('用地图导航过去')
          .width('100%').height(46)
          .backgroundColor($r('app.color.brand'))
          .enabled(this.order.lat !== undefined && this.order.lng !== undefined)
          .onClick(() => {
            navigateTo(getContext(this) as common.UIAbilityContext,
              this.order.lat as number, this.order.lng as number,
              this.order.address ?? '送达点');
          });

        Blank();
      }
      .layoutWeight(1).width('100%').padding(12);
    }
    .width('100%').height('100%')
    .backgroundColor($r('app.color.page'));
  }
}

/**
 * 骑手在哪。
 *
 * 顾客催单时先打给店家,**店家不该两眼一抹黑**。
 *
 * ## 「拿不到位置」和「骑手还没上报位置」要分开说
 *
 * 这两种情况在界面上长得一样,但商家该回给顾客的话完全不同:
 * 前者是我们的问题,后者是骑手刚接单还没动。安卓端刚修过这个歧义。
 */
@Component
export struct RiderTrackPage {
  @Prop order: MerchantOrder;
  @Prop shop: Shop;
  onBack: () => void = () => {};

  @State private loc: Record<string, Object> | null = null;
  @State private loaded: boolean = false;
  @State private errorText: string = '';

  private api: MerchantApi = new MerchantApi();
  private timer: number = -1;

  aboutToAppear(): void {
    this.refresh();
    this.timer = setInterval(() => { this.refresh(); }, 5000);
  }

  aboutToDisappear(): void {
    if (this.timer >= 0) {
      clearInterval(this.timer);
      this.timer = -1;
    }
  }

  private async refresh(): Promise<void> {
    try {
      const r: Record<string, Object> =
          await this.api.riderLocation(this.order.order_no);
      this.loc = r;
      this.errorText = '';
    } catch (e) {
      this.errorText = (e as ApiException).message;
    } finally {
      this.loaded = true;
    }
  }

  private hasRider(): boolean {
    return this.loc !== null && this.loc['lat'] !== undefined
        && this.loc['lng'] !== undefined;
  }

  private toCustomer(): number | null {
    if (!this.hasRider()) {
      return null;
    }
    const oLat: number | undefined = this.order.lat;
    const oLng: number | undefined = this.order.lng;
    if (oLat === undefined || oLng === undefined) {
      return null;
    }
    return distanceMeters(this.loc?.['lat'] as number,
      this.loc?.['lng'] as number, oLat, oLng);
  }

  build() {
    Column() {
      Row({ space: 10 }) {
        Text('‹').fontSize(24).fontColor($r('app.color.ink'))
          .onClick(() => { this.onBack(); });
        Text('骑手在哪')
          .fontSize(17).fontWeight(FontWeight.Bold)
          .fontColor($r('app.color.ink')).layoutWeight(1);
      }
      .width('100%')
      .padding({ left: 14, right: 14, top: 10, bottom: 10 })
      .backgroundColor($r('app.color.surface'));

      if (!this.loaded) {
        Column() {
          LoadingProgress().width(40).height(40);
        }
        .layoutWeight(1).justifyContent(FlexAlign.Center);
      } else {
        Column({ space: 12 }) {
          Column({ space: 8 }) {
            if (this.hasRider()) {
              Text(this.order.status === OrderStatus.PICKED_UP
                ? '配送中' : '已接单,正在赶来取餐')
                .fontSize(13).fontColor($r('app.color.ink_muted'))
                .width('100%');
              Text(this.toCustomer() === null
                ? '—' : `距顾客 ${distanceText(this.toCustomer() as number)}`)
                .fontSize(28).fontWeight(FontWeight.Bold)
                .fontColor($r('app.color.ink')).width('100%');
              Text('位置 5 秒自动刷新')
                .fontSize(12).fontColor($r('app.color.ink_muted'))
                .width('100%');
            } else if (this.errorText.length > 0) {
              // 拿不到 ≠ 骑手没在送。这句话决定商家怎么回顾客
              Text('拿不到骑手位置')
                .fontSize(17).fontWeight(FontWeight.Bold)
                .fontColor($r('app.color.danger')).width('100%');
              Text(`${this.errorText}\n\n这不代表骑手没在送,5 秒后自动重试。` +
                '要给顾客一个准信的话,直接打骑手电话。')
                .fontSize(13).lineHeight(20)
                .fontColor($r('app.color.ink_muted')).width('100%');
            } else {
              Text('骑手还没上报位置')
                .fontSize(17).fontWeight(FontWeight.Bold)
                .fontColor($r('app.color.ink')).width('100%');
              Text('可能刚接单或设备离线,稍等自动刷新。')
                .fontSize(13).lineHeight(20)
                .fontColor($r('app.color.ink_muted')).width('100%');
            }
          }
          .width('100%').padding(14)
          .backgroundColor($r('app.color.surface')).borderRadius(12);

          if (this.loc !== null
              && `${this.loc['rider_name'] ?? ''}`.length > 0) {
            Column({ space: 6 }) {
              Text('骑手')
                .fontSize(13).fontColor($r('app.color.ink_muted'))
                .width('100%');
              Text(`${this.loc['rider_name']} ${this.loc['rider_phone'] ?? ''}`)
                .fontSize(16).fontColor($r('app.color.ink')).width('100%');
            }
            .width('100%').padding(14)
            .backgroundColor($r('app.color.surface')).borderRadius(12);
          }

          if (this.hasRider()) {
            Button('在地图上看骑手位置')
              .width('100%').height(46)
              .backgroundColor($r('app.color.surface_alt'))
              .fontColor($r('app.color.ink'))
              .onClick(() => {
                navigateTo(getContext(this) as common.UIAbilityContext,
                  this.loc?.['lat'] as number, this.loc?.['lng'] as number,
                  '骑手位置');
              });
          }

          Blank();
        }
        .layoutWeight(1).width('100%').padding(12);
      }
    }
    .width('100%').height('100%')
    .backgroundColor($r('app.color.page'));
  }
}
