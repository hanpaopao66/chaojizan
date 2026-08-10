import { promptAction } from '@kit.ArkUI';
import { MerchantApi } from '../common/MerchantApi';
import { ApiException } from '../common/Api';
import { yuan } from '../common/Money';

/**
 * 经营分析 + 老客召回。
 *
 * ## 平台不给你顾客名单
 *
 * 商家看到的只有**人数**。谁没来、手机号是多少,平台不给他,也不给任何人 ——
 * 名单一旦交出去就再也收不回来。想把人叫回来就发一批券,
 * 平台按频控替他送出去。
 *
 * 这条要**写在界面上**,不是写在隐私政策里。商家问"为什么不给我名单"的时候,
 * 答案要就在他眼前。
 *
 * ## 分析数据仅自己可见
 *
 * 时段分布、菜品排行、客单价、复购 —— 这些是商家的经营机密,
 * 平台不拿它去做别的事。同样写在界面上。
 */
@Component
export struct AnalyticsPage {
  onBack: () => void = () => {};

  @State private days: number = 7;
  @State private data: Record<string, Object> | null = null;
  @State private errorText: string = '';
  @State private winback: Record<string, Object> | null = null;
  @State private winbackError: string = '';
  @State private busy: boolean = false;

  private api: MerchantApi = new MerchantApi();

  aboutToAppear(): void {
    this.load();
  }

  private async load(): Promise<void> {
    const analyticsF: Promise<Record<string, Object>> =
        this.api.merchantAnalytics(this.days);
    const winbackF: Promise<Record<string, Object>> = this.api.merchantWinback();

    // 召回是附加信息:拉不到不拦着看经营分析
    try {
      this.winback = await winbackF;
      this.winbackError = '';
    } catch (e) {
      this.winbackError = (e as ApiException).message;
    }

    try {
      this.data = await analyticsF;
      this.errorText = '';
    } catch (e) {
      // 转个没头的圈,商家只能杀进程重开
      this.errorText = (e as ApiException).message;
    }
  }

  private n(m: Record<string, Object> | null, key: string): number {
    if (m === null) {
      return 0;
    }
    const v: Object | undefined = m[key];
    return v === undefined ? 0 : v as number;
  }

  @Builder
  private stat(label: string, value: string, unit: string) {
    Column({ space: 2 }) {
      Text(value)
        .fontSize(19).fontWeight(FontWeight.Bold)
        .fontColor($r('app.color.ink'));
      Text(`${label}${unit.length > 0 ? `(${unit})` : ''}`)
        .fontSize(11).fontColor($r('app.color.ink_muted'));
    }
    .layoutWeight(1).alignItems(HorizontalAlign.Center);
  }

  build() {
    Column() {
      Row({ space: 10 }) {
        Text('‹').fontSize(24).fontColor($r('app.color.ink'))
          .onClick(() => { this.onBack(); });
        Text('经营分析')
          .fontSize(17).fontWeight(FontWeight.Bold)
          .fontColor($r('app.color.ink')).layoutWeight(1);
      }
      .width('100%')
      .padding({ left: 14, right: 14, top: 10, bottom: 10 })
      .backgroundColor($r('app.color.surface'));

      Row({ space: 8 }) {
        ForEach([7, 30], (d: number) => {
          Text(`近 ${d} 天`)
            .fontSize(12)
            .fontColor(this.days === d ? Color.White : $r('app.color.ink'))
            .padding({ left: 12, right: 12, top: 5, bottom: 5 })
            .borderRadius(12)
            .backgroundColor(this.days === d
              ? $r('app.color.brand') : $r('app.color.surface_alt'))
            .onClick(() => {
              this.days = d;
              this.data = null;
              this.load();
            });
        }, (d: number) => `d${d}`);
      }
      .width('100%').padding({ left: 12, right: 12, top: 8, bottom: 4 });

      Scroll() {
        Column({ space: 12 }) {
          // ---- 总览 ----
          if (this.data === null && this.errorText.length > 0) {
            Column({ space: 12 }) {
              Text('经营数据没能加载出来')
                .fontSize(15).fontColor($r('app.color.ink'));
              Text(this.errorText).fontSize(13)
                .fontColor($r('app.color.ink_muted'))
                .textAlign(TextAlign.Center);
              Button('重试').height(40).width(130)
                .backgroundColor($r('app.color.brand'))
                .onClick(() => { this.load(); });
            }
            .width('100%').padding(30);
          } else if (this.data === null) {
            LoadingProgress().width(40).height(40).margin({ top: 40 });
          } else {
            Column({ space: 10 }) {
              Text('总览(完成单口径,与对账一致)')
                .fontSize(13).fontWeight(FontWeight.Medium)
                .fontColor($r('app.color.ink')).width('100%');
              Row() {
                this.stat('完成', `${this.n(this.data, 'orders')}`, '单');
                this.stat('流水',
                  yuan(this.n(this.data, 'food_cents')), '');
                this.stat('客单价',
                  yuan(this.n(this.data, 'avg_order_cents')), '');
              }
              .width('100%');
              Row() {
                this.stat('复购率',
                  `${(this.n(this.data, 'repeat_rate') * 100).toFixed(0)}%`, '');
                this.stat('新客', `${this.n(this.data, 'new_customers')}`, '人');
                this.stat('佣金',
                  yuan(this.n(this.data, 'commission_cents')), '');
              }
              .width('100%');
              Text('这些数字仅你自己可见,平台不拿去做别的事。')
                .fontSize(11).fontColor($r('app.color.ink_muted'))
                .width('100%');
            }
            .width('100%').padding(14)
            .backgroundColor($r('app.color.surface')).borderRadius(12);
          }

          // ---- 老客召回 ----
          Column({ space: 8 }) {
            Text('老客召回')
              .fontSize(13).fontWeight(FontWeight.Medium)
              .fontColor($r('app.color.ink')).width('100%');

            if (this.winbackError.length > 0) {
              Row({ space: 8 }) {
                Text('⚠').fontSize(14).fontColor($r('app.color.danger'));
                Text(`召回数据没拉到(${this.winbackError})。点这里重试`)
                  .fontSize(12).fontColor($r('app.color.danger'))
                  .layoutWeight(1);
              }
              .width('100%').padding(10)
              .backgroundColor('#1AC0392B').borderRadius(8)
              .onClick(() => { this.load(); });
            } else if (this.winback === null) {
              LoadingProgress().width(26).height(26);
            } else {
              Row() {
                this.stat('30 天没来过',
                  `${this.n(this.winback, 'dormant_30d')}`, '人');
                this.stat('90 天没来过',
                  `${this.n(this.winback, 'dormant_90d')}`, '人');
                this.stat('半年内来过',
                  `${this.n(this.winback, 'customers_180d')}`, '人');
              }
              .width('100%');
            }

            // **这段话要摆在商家眼前**,不是藏在隐私政策里
            Text('平台不会给你顾客名单')
              .fontSize(13).fontWeight(FontWeight.Bold)
              .fontColor($r('app.color.ink'))
              .width('100%').margin({ top: 6 });
            Text('你看到的只有人数。谁没来、手机号是多少,平台不给你,' +
              '也不给任何人 —— 名单一旦交出去就再也收不回来。\n\n' +
              '想把人叫回来,就发一批券:平台按每人每月最多一次、' +
              '每周最多两条的频控替你送出去,发完即止。')
              .fontSize(12).lineHeight(19)
              .fontColor($r('app.color.ink_muted')).width('100%');

            Text('发券这一步这一版还没做,请在安卓端或网页端操作。')
              .fontSize(11).fontColor($r('app.color.hold')).width('100%');
          }
          .width('100%').padding(14)
          .backgroundColor($r('app.color.surface')).borderRadius(12);

          Blank().height(30);
        }
        .width('100%').padding(12);
      }
      .layoutWeight(1).scrollBar(BarState.Off);
    }
    .width('100%').height('100%')
    .backgroundColor($r('app.color.page'));
  }
}
