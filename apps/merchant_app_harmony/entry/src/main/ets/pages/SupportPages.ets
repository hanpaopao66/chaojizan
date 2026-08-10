import { common, Want } from '@kit.AbilityKit';
import { promptAction } from '@kit.ArkUI';
import { MerchantApi } from '../common/MerchantApi';
import { ApiException } from '../common/Api';
import { AfterSale, Review, Shop } from '../model/Models';

/**
 * 判责申诉:对「判商家责任的售后」与「差评」在 72 小时内申诉。
 *
 * 申诉成立:售后恢复被冲的净额(**平台认亏,不追用户款**);
 * 差评隐藏并回调评分。
 *
 * ## 空页面和加载失败在这一页含义完全相反
 *
 * 空 = 没有可申诉的,商家可以放心;失败 = 有没有不知道,而 72 小时在走。
 */
@Component
export struct AppealPage {
  onBack: () => void = () => {};

  @State private afterSales: AfterSale[] = [];
  @State private badReviews: Review[] = [];
  @State private appealed: string[] = [];
  @State private loaded: boolean = false;
  @State private errorText: string = '';

  @State private showForm: boolean = false;
  @State private formTitle: string = '';
  @State private formType: string = '';
  @State private formId: number = 0;
  @State private reason: string = '';
  @State private busy: boolean = false;

  private api: MerchantApi = new MerchantApi();

  aboutToAppear(): void {
    this.load();
  }

  private async load(): Promise<void> {
    // 三个请求先全部发出去再逐个 await —— 互不依赖,不必排队
    const salesF: Promise<AfterSale[]> = this.api.myAfterSales();
    const reviewsF: Promise<Review[]> = this.api.myReviews();
    const appealsF: Promise<Record<string, Object>[]> = this.api.myAppeals();

    try {
      const sales: AfterSale[] = await salesF;
      const reviews: Review[] = await reviewsF;
      const appeals: Record<string, Object>[] = await appealsF;
      // 只列可能需要申诉的:已同意退款且非骑手责的售后 / 3 星及以下差评
      this.afterSales = sales.filter((a: AfterSale) =>
          a.status === 'accepted' && a.fault !== 'rider');
      this.badReviews = reviews.filter((r: Review) => r.merchant_rating <= 3);
      this.appealed = appeals.map((a: Record<string, Object>) =>
          `${a['target_type']}:${a['target_id']}`);
      this.errorText = '';
    } catch (e) {
      // 拉不到**不能装作没有**:空 = 没有可申诉的,商家会放心;
      // 而实际可能有,72 小时在走
      this.errorText = (e as ApiException).message;
    } finally {
      this.loaded = true;
    }
  }

  private done(type: string, id: number): boolean {
    return this.appealed.indexOf(`${type}:${id}`) >= 0;
  }

  private open(type: string, id: number, title: string): void {
    this.formType = type;
    this.formId = id;
    this.formTitle = title;
    this.reason = '';
    this.showForm = true;
  }

  private async submit(): Promise<void> {
    if (this.reason.trim().length === 0) {
      promptAction.showToast({ message: '说明一下为什么不该判你责任' });
      return;
    }
    this.busy = true;
    try {
      await this.api.submitAppeal({
        target_type: this.formType,
        target_id: this.formId,
        reason: this.reason.trim(),
      } as object);
      this.showForm = false;
      await this.load();
      promptAction.showToast({ message: '申诉已提交,平台会尽快复核并推送结果' });
    } catch (e) {
      promptAction.showToast({ message: (e as ApiException).message });
    } finally {
      this.busy = false;
    }
  }

  @Builder
  private formSheet() {
    Column({ space: 10 }) {
      Text('申诉')
        .fontSize(17).fontWeight(FontWeight.Bold)
        .fontColor($r('app.color.ink')).width('100%');
      Text(this.formTitle)
        .fontSize(13).fontColor($r('app.color.ink_muted')).width('100%');
      Text('申诉成立的话:售后会恢复被冲的净额(平台认亏,不追用户款);' +
        '差评会隐藏并回调评分。写具体一点,比如出餐监控、聊天记录能对上什么。')
        .fontSize(12).lineHeight(18)
        .fontColor($r('app.color.ink_muted')).width('100%');
      TextArea({ placeholder: '为什么不该判你责任', text: this.reason })
        .height(110).onChange((v: string) => { this.reason = v; });
      Row({ space: 10 }) {
        Button('取消')
          .layoutWeight(1).height(44)
          .backgroundColor($r('app.color.surface_alt'))
          .fontColor($r('app.color.ink'))
          .onClick(() => { this.showForm = false; });
        Button(this.busy ? '提交中…' : '提交申诉')
          .layoutWeight(1).height(44)
          .backgroundColor($r('app.color.brand'))
          .enabled(!this.busy)
          .onClick(() => { this.submit(); });
      }
      .width('100%');
    }
    .width('100%')
    .padding({ left: 18, right: 18, top: 18, bottom: 24 })
    .backgroundColor($r('app.color.surface'));
  }

  build() {
    Column() {
      Row({ space: 10 }) {
        Text('‹').fontSize(24).fontColor($r('app.color.ink'))
          .onClick(() => { this.onBack(); });
        Text('判责申诉')
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
      } else if (this.errorText.length > 0) {
        Column({ space: 12 }) {
          Text('可申诉的记录没能加载出来')
            .fontSize(15).fontColor($r('app.color.ink'));
          Text(`${this.errorText}\n\n空白不代表没有可申诉的 —— 申诉窗口只有 72 小时。`)
            .fontSize(13).lineHeight(20)
            .fontColor($r('app.color.ink_muted')).textAlign(TextAlign.Center);
          Button('重试').height(40).width(130)
            .backgroundColor($r('app.color.brand'))
            .onClick(() => { this.load(); });
        }
        .layoutWeight(1).justifyContent(FlexAlign.Center).padding(30);
      } else {
        Scroll() {
          Column({ space: 12 }) {
            Column({ space: 8 }) {
              Text('判商家责任的售后')
                .fontSize(13).fontWeight(FontWeight.Medium)
                .fontColor($r('app.color.ink')).width('100%');
              if (this.afterSales.length === 0) {
                Text('没有判商家责任的售后记录')
                  .fontSize(13).fontColor($r('app.color.ink_muted'))
                  .width('100%').padding({ top: 10, bottom: 10 });
              } else {
                ForEach(this.afterSales, (a: AfterSale) => {
                  Row({ space: 10 }) {
                    Column({ space: 2 }) {
                      Text(`#${a.order_no.length > 6
                        ? a.order_no.substring(a.order_no.length - 6)
                        : a.order_no}`)
                        .fontSize(13).fontColor($r('app.color.ink'));
                      Text(a.reason).fontSize(12)
                        .fontColor($r('app.color.ink_muted'))
                        .maxLines(2)
                        .textOverflow({ overflow: TextOverflow.Ellipsis });
                    }
                    .alignItems(HorizontalAlign.Start).layoutWeight(1);
                    if (this.done('after_sale', a.id)) {
                      Text('已申诉').fontSize(12)
                        .fontColor($r('app.color.ink_muted'));
                    } else {
                      Button('申诉')
                        .fontSize(12).height(30)
                        .padding({ left: 12, right: 12 })
                        .backgroundColor($r('app.color.surface_alt'))
                        .fontColor($r('app.color.ink'))
                        .onClick(() => {
                          this.open('after_sale', a.id, `售后 #${a.order_no}`);
                        });
                    }
                  }
                  .width('100%').padding({ top: 9, bottom: 9 });
                  Divider().color($r('app.color.line'));
                }, (a: AfterSale) => `s${a.id}`);
              }
            }
            .width('100%').padding(14)
            .backgroundColor($r('app.color.surface')).borderRadius(12);

            Column({ space: 8 }) {
              Text('3 星及以下的评价')
                .fontSize(13).fontWeight(FontWeight.Medium)
                .fontColor($r('app.color.ink')).width('100%');
              if (this.badReviews.length === 0) {
                Text('没有差评')
                  .fontSize(13).fontColor($r('app.color.ink_muted'))
                  .width('100%').padding({ top: 10, bottom: 10 });
              } else {
                ForEach(this.badReviews, (r: Review) => {
                  Row({ space: 10 }) {
                    Column({ space: 2 }) {
                      Text(`${r.merchant_rating} 星`)
                        .fontSize(13).fontColor($r('app.color.danger'));
                      Text(r.comment ?? '(没写文字)')
                        .fontSize(12)
                        .fontColor($r('app.color.ink_muted'))
                        .maxLines(2)
                        .textOverflow({ overflow: TextOverflow.Ellipsis });
                    }
                    .alignItems(HorizontalAlign.Start).layoutWeight(1);
                    if (this.done('review', r.id)) {
                      Text('已申诉').fontSize(12)
                        .fontColor($r('app.color.ink_muted'));
                    } else {
                      Button('申诉')
                        .fontSize(12).height(30)
                        .padding({ left: 12, right: 12 })
                        .backgroundColor($r('app.color.surface_alt'))
                        .fontColor($r('app.color.ink'))
                        .onClick(() => {
                          this.open('review', r.id, `${r.merchant_rating} 星评价`);
                        });
                    }
                  }
                  .width('100%').padding({ top: 9, bottom: 9 });
                  Divider().color($r('app.color.line'));
                }, (r: Review) => `r${r.id}`);
              }
            }
            .width('100%').padding(14)
            .backgroundColor($r('app.color.surface')).borderRadius(12);

            Blank().height(30);
          }
          .width('100%').padding(12);
        }
        .layoutWeight(1).scrollBar(BarState.Off);
      }
    }
    .width('100%').height('100%')
    .backgroundColor($r('app.color.page'))
    .bindSheet($$this.showForm, this.formSheet(),
      { height: 380, dragBar: false });
  }
}

/**
 * 平台规则中心。
 *
 * 页面本身没什么特别的,**特别的是数字的来源**:服务端从代码里的常量
 * 算出来下发,不是后台可编辑的运营文案。公示「30 天 3 起自动停业」、
 * 代码里写的却是 5 起 —— 这种事只要可能发生就迟早会发生。
 */
@Component
export struct RulesPage {
  onBack: () => void = () => {};

  @State private rules: Record<string, Object> | null = null;
  @State private errorText: string = '';
  @State private loaded: boolean = false;

  private api: MerchantApi = new MerchantApi();

  aboutToAppear(): void {
    this.load();
  }

  private async load(): Promise<void> {
    try {
      this.rules = await this.api.merchantRules();
      this.errorText = '';
    } catch (e) {
      this.errorText = (e as ApiException).message;
    } finally {
      this.loaded = true;
    }
  }

  private sections(): Record<string, Object>[] {
    const raw: Object | undefined = this.rules?.['sections'];
    return (raw === undefined ? [] : raw) as Record<string, Object>[];
  }

  build() {
    Column() {
      Row({ space: 10 }) {
        Text('‹').fontSize(24).fontColor($r('app.color.ink'))
          .onClick(() => { this.onBack(); });
        Text('平台规则')
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
      } else if (this.errorText.length > 0) {
        Column({ space: 12 }) {
          Text('规则没能加载出来')
            .fontSize(15).fontColor($r('app.color.ink'));
          Text(this.errorText).fontSize(13)
            .fontColor($r('app.color.ink_muted')).textAlign(TextAlign.Center);
          Button('重试').height(40).width(130)
            .backgroundColor($r('app.color.brand'))
            .onClick(() => { this.load(); });
        }
        .layoutWeight(1).justifyContent(FlexAlign.Center).padding(30);
      } else {
        Scroll() {
          Column({ space: 12 }) {
            Text('下面每个数字都是从平台代码里的常量算出来的,不是运营写的文案 ——' +
              '公示的和执行的必须是同一个数。')
              .fontSize(12).lineHeight(19)
              .fontColor($r('app.color.ink'))
              .width('100%').padding(12)
              .backgroundColor($r('app.color.surface_alt')).borderRadius(10);

            ForEach(this.sections(), (sec: Record<string, Object>) => {
              Column({ space: 6 }) {
                Text(`${sec['title'] ?? ''}`)
                  .fontSize(14).fontWeight(FontWeight.Medium)
                  .fontColor($r('app.color.ink')).width('100%');
                ForEach((sec['items'] ?? []) as string[], (it: string) => {
                  Text(`· ${it}`)
                    .fontSize(13).lineHeight(21)
                    .fontColor($r('app.color.ink_muted')).width('100%');
                }, (it: string, i: number) => `${i}-${it}`);
              }
              .width('100%').padding(14)
              .backgroundColor($r('app.color.surface')).borderRadius(12);
            }, (sec: Record<string, Object>) => `${sec['title']}`);

            Blank().height(30);
          }
          .width('100%').padding(12);
        }
        .layoutWeight(1).scrollBar(BarState.Off);
      }
    }
    .width('100%').height('100%')
    .backgroundColor($r('app.color.page'));
  }
}

/**
 * 店铺专属码与推广物料。
 *
 * 平台**没有补贴预算**,买不来流量,商家自己带客是唯一能规模化的获客渠道 ——
 * 而商家在这里每单多留十几个点,本来就有动力把老客带过来。
 * **平台出物料不出钱**,这一点直说,别让商家等着平台发券。
 */
@Component
export struct PromoPage {
  @Prop shop: Shop;
  onBack: () => void = () => {};

  @State private promo: Record<string, Object> | null = null;
  @State private errorText: string = '';
  @State private loaded: boolean = false;

  private api: MerchantApi = new MerchantApi();

  aboutToAppear(): void {
    this.load();
  }

  private async load(): Promise<void> {
    try {
      this.promo = await this.api.merchantPromo();
      this.errorText = '';
    } catch (e) {
      this.errorText = (e as ApiException).message;
    } finally {
      this.loaded = true;
    }
  }

  private openUrl(url: string): void {
    const context = getContext(this) as common.UIAbilityContext;
    const want: Want = {
      action: 'ohos.want.action.viewData',
      entities: ['entity.system.browsable'],
      uri: url,
    };
    context.startAbility(want).catch(() => {
      promptAction.showToast({ message: '没有找到可以打开网页的应用' });
    });
  }

  build() {
    Column() {
      Row({ space: 10 }) {
        Text('‹').fontSize(24).fontColor($r('app.color.ink'))
          .onClick(() => { this.onBack(); });
        Text('推广物料')
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
      } else if (this.errorText.length > 0) {
        Column({ space: 12 }) {
          Text('推广物料没能加载出来')
            .fontSize(15).fontColor($r('app.color.ink'));
          Text(this.errorText).fontSize(13)
            .fontColor($r('app.color.ink_muted')).textAlign(TextAlign.Center);
          Button('重试').height(40).width(130)
            .backgroundColor($r('app.color.brand'))
            .onClick(() => { this.load(); });
        }
        .layoutWeight(1).justifyContent(FlexAlign.Center).padding(30);
      } else {
        Scroll() {
          Column({ space: 12 }) {
            Column({ space: 8 }) {
              Text('你的店铺专属码')
                .fontSize(13).fontWeight(FontWeight.Medium)
                .fontColor($r('app.color.ink')).width('100%');
              Text(`${this.promo?.['landing_url'] ?? ''}`)
                .fontSize(12).fontColor($r('app.color.ink_muted'))
                .width('100%');
              Text('顾客扫码先看到你的落地页,再下载 App —— ' +
                '中间不插别家的广告位,这是和别家最不一样的地方。')
                .fontSize(12).lineHeight(19)
                .fontColor($r('app.color.ink_muted')).width('100%');
              Button('打开海报生成页')
                .width('100%').height(42)
                .backgroundColor($r('app.color.brand'))
                .enabled(`${this.promo?.['poster_url'] ?? ''}`.length > 0)
                .onClick(() => {
                  this.openUrl(`${this.promo?.['poster_url'] ?? ''}`);
                });
            }
            .width('100%').padding(14)
            .backgroundColor($r('app.color.surface')).borderRadius(12);

            Column({ space: 6 }) {
              Text('平台出物料,不出钱')
                .fontSize(13).fontWeight(FontWeight.Bold)
                .fontColor($r('app.color.ink')).width('100%');
              Text('我们没有补贴预算,也不打算靠烧钱换单量 —— 烧完就没了,' +
                '而低抽成是能一直做下去的。你每单多留十几个点,' +
                '把老客带过来这件事本来就该你我一起做。')
                .fontSize(12).lineHeight(19)
                .fontColor($r('app.color.ink_muted')).width('100%');
            }
            .width('100%').padding(14)
            .backgroundColor($r('app.color.earn_soft')).borderRadius(12);

            Blank().height(30);
          }
          .width('100%').padding(12);
        }
        .layoutWeight(1).scrollBar(BarState.Off);
      }
    }
    .width('100%').height('100%')
    .backgroundColor($r('app.color.page'));
  }
}
