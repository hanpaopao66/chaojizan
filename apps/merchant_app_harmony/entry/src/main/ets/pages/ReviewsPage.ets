import { promptAction } from '@kit.ArkUI';
import { MerchantApi } from '../common/MerchantApi';
import { ApiException } from '../common/Api';
import { ArrayDataSource } from '../common/DataSource';
import { AfterSale, Review } from '../model/Models';

/**
 * 评价与售后。
 *
 * ## 「这一栏没有评价」和「评价没拉到」不能长得一样
 *
 * 差评看不到,商家就错过了申诉窗口 —— 而判责一旦生效,钱是从结算款里扣的。
 * 所以拉失败要显式报错 + 给重试,不能设个 loaded=true 就当加载完了。
 * 安卓端刚改过这个,见 DEV-PROMPTS-27 #240。
 *
 * ## 售后同意即认责
 *
 * 「同意」这个按钮点下去,退款从商家结算款里扣。所以按钮旁边必须写清楚,
 * 而且必须给用户一句话回复 —— 一句话都不给的拒绝,顾客一定会投诉到平台。
 */
@Component
export struct ReviewsPage {
  onBack: () => void = () => {};

  /** 0 全部 / 1 差评(≤3星) / 2 待回复 */
  @State private filter: number = 0;
  @State private tab: number = 0;
  @State private loaded: boolean = false;
  @State private errorText: string = '';
  @State private afterSales: AfterSale[] = [];

  /** 回复面板 */
  @State private showReply: boolean = false;
  @State private replyText: string = '';
  @State private replyTarget: number = 0;
  @State private replyAppend: boolean = false;

  /** 售后处理面板 */
  @State private showProcess: boolean = false;
  @State private processText: string = '';
  @State private processId: number = 0;
  @State private processAccept: boolean = true;

  private api: MerchantApi = new MerchantApi();
  private ds: ArrayDataSource<Review> = new ArrayDataSource<Review>();

  aboutToAppear(): void {
    this.load();
  }

  private async load(): Promise<void> {
    // 两条互不依赖,先都发出去
    const reviewsF: Promise<Review[]> = this.api.myReviews(
        this.filter === 1 ? 3 : undefined, this.filter === 2);
    const salesF: Promise<AfterSale[]> = this.api.myAfterSales('pending');

    let sales: AfterSale[] = this.afterSales;
    try {
      sales = await salesF;
    } catch (_) {
      // 售后拉不到不拦着看评价。这一屏两块内容各自独立
    }

    try {
      const list: Review[] = await reviewsF;
      this.ds.reload(list);
      this.afterSales = sales;
      this.errorText = '';
    } catch (e) {
      this.errorText = (e as ApiException).message;
    } finally {
      this.loaded = true;
    }
  }

  // ---------- 回复评价 ----------

  private openReply(r: Review, append: boolean): void {
    this.replyTarget = r.id;
    this.replyAppend = append;
    this.replyText = '';
    this.showReply = true;
  }

  private async submitReply(): Promise<void> {
    const text: string = this.replyText.trim();
    if (text.length === 0) {
      return;
    }
    try {
      if (this.replyAppend) {
        await this.api.replyAppendReview(this.replyTarget, text);
      } else {
        await this.api.replyReview(this.replyTarget, text);
      }
      this.showReply = false;
      this.replyText = '';
      promptAction.showToast({ message: '已回复' });
      await this.load();
    } catch (e) {
      // 面板不关 —— 关了商家写的那段话就没了,得重打一遍
      promptAction.showToast({ message: (e as ApiException).message });
    }
  }

  // ---------- 处理售后 ----------

  private openProcess(s: AfterSale, accept: boolean): void {
    this.processId = s.id;
    this.processAccept = accept;
    // 同意时给一句默认话术,拒绝时**不给** —— 拒绝的理由必须商家自己写,
    // 套话式的拒绝只会把顾客推到平台客服那里
    this.processText = accept ? '非常抱歉给您带来不好的体验,已退您餐费' : '';
    this.showProcess = true;
  }

  private async submitProcess(): Promise<void> {
    const text: string = this.processText.trim();
    if (text.length === 0) {
      promptAction.showToast({ message: '给顾客写一句话,哪怕只是说明原因' });
      return;
    }
    try {
      await this.api.processAfterSale(this.processId, this.processAccept, text);
      this.showProcess = false;
      promptAction.showToast({
        message: this.processAccept ? '已同意退款' : '已拒绝并回复',
      });
      await this.load();
    } catch (e) {
      promptAction.showToast({ message: (e as ApiException).message });
    }
  }

  // ---------- 界面 ----------

  @Builder
  private replySheet() {
    Column({ space: 12 }) {
      Text(this.replyAppend ? '回复追评' : '回复评价')
        .fontSize(17).fontWeight(FontWeight.Bold)
        .fontColor($r('app.color.ink')).width('100%');
      Text('回复顾客都看得到。诚恳一点,比模板话术管用')
        .fontSize(12).fontColor($r('app.color.ink_muted')).width('100%');
      TextArea({ placeholder: '写一句给顾客的话', text: this.replyText })
        .height(96)
        .onChange((v: string) => { this.replyText = v; });
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
  private processSheet() {
    Column({ space: 12 }) {
      Text(this.processAccept ? '同意退款' : '拒绝售后')
        .fontSize(17).fontWeight(FontWeight.Bold)
        .fontColor($r('app.color.ink')).width('100%');
      // 同意即认责,钱从结算款扣。这句话必须在按钮之前就说
      Text(this.processAccept
        ? '同意即认责,退款金额从你的结算款里扣。'
        : '拒绝后顾客可以申请平台介入。给个具体原因,别写套话。')
        .fontSize(12).lineHeight(19)
        .fontColor(this.processAccept
          ? $r('app.color.hold') : $r('app.color.ink_muted'))
        .width('100%');
      TextArea({ placeholder: '给顾客的一句话', text: this.processText })
        .height(88)
        .onChange((v: string) => { this.processText = v; });
      Row({ space: 10 }) {
        Button('取消')
          .layoutWeight(1).height(44)
          .backgroundColor($r('app.color.surface_alt'))
          .fontColor($r('app.color.ink'))
          .onClick(() => { this.showProcess = false; });
        Button(this.processAccept ? '同意退款' : '拒绝')
          .layoutWeight(1).height(44)
          .backgroundColor(this.processAccept
            ? $r('app.color.brand') : $r('app.color.surface_alt'))
          .fontColor(this.processAccept
            ? Color.White : $r('app.color.danger'))
          .enabled(this.processText.trim().length > 0)
          .onClick(() => { this.submitProcess(); });
      }
      .width('100%');
    }
    .width('100%')
    .padding({ left: 18, right: 18, top: 18, bottom: 24 })
    .backgroundColor($r('app.color.surface'));
  }

  @Builder
  private reviewCard(r: Review) {
    Column({ space: 6 }) {
      Row({ space: 6 }) {
        Text('★'.repeat(r.merchant_rating) + '☆'.repeat(5 - r.merchant_rating))
          .fontSize(13)
          .fontColor(r.merchant_rating <= 3
            ? $r('app.color.danger') : $r('app.color.hold'));
        Blank();
        Text(r.created_at.substring(0, 10))
          .fontSize(11).fontColor($r('app.color.ink_muted'));
      }
      .width('100%');

      if ((r.comment ?? '').length > 0) {
        Text(r.comment).fontSize(14).lineHeight(21)
          .fontColor($r('app.color.ink')).width('100%');
      }
      if ((r.append_comment ?? '').length > 0) {
        Text(`追评:${r.append_comment}`)
          .fontSize(13).fontColor($r('app.color.ink_muted')).width('100%');
      }

      if ((r.reply ?? '').length > 0) {
        Text(`你的回复:${r.reply}`)
          .fontSize(12).lineHeight(19)
          .fontColor($r('app.color.ink_muted'))
          .width('100%').padding(8)
          .backgroundColor($r('app.color.surface_alt')).borderRadius(6);
      }

      Row({ space: 8 }) {
        Blank();
        if ((r.reply ?? '').length === 0) {
          Button('回复')
            .fontSize(12).height(30).padding({ left: 12, right: 12 })
            .backgroundColor($r('app.color.brand'))
            .onClick(() => { this.openReply(r, false); });
        } else if ((r.append_comment ?? '').length > 0
            && (r.append_reply ?? '').length === 0) {
          Button('回复追评')
            .fontSize(12).height(30).padding({ left: 12, right: 12 })
            .backgroundColor($r('app.color.surface_alt'))
            .fontColor($r('app.color.ink'))
            .onClick(() => { this.openReply(r, true); });
        }
      }
      .width('100%');
    }
    .width('100%').padding(14)
    .backgroundColor($r('app.color.surface')).borderRadius(12)
    .margin({ bottom: 10 });
  }

  @Builder
  private afterSaleCard(s: AfterSale) {
    Column({ space: 6 }) {
      Row() {
        Text(`#${s.order_no.length > 6
          ? s.order_no.substring(s.order_no.length - 6) : s.order_no}`)
          .fontSize(12).fontColor($r('app.color.ink_muted')).layoutWeight(1);
        Text(s.status_label ?? s.status)
          .fontSize(12).fontColor($r('app.color.hold'));
      }
      .width('100%');
      Text(s.reason).fontSize(14).lineHeight(21)
        .fontColor($r('app.color.ink')).width('100%');
      Row({ space: 8 }) {
        Blank();
        Button('拒绝')
          .fontSize(12).height(30).padding({ left: 12, right: 12 })
          .backgroundColor($r('app.color.surface_alt'))
          .fontColor($r('app.color.danger'))
          .onClick(() => { this.openProcess(s, false); });
        Button('同意退款')
          .fontSize(12).height(30).padding({ left: 12, right: 12 })
          .backgroundColor($r('app.color.brand'))
          .onClick(() => { this.openProcess(s, true); });
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
        Text('评价与售后')
          .fontSize(17).fontWeight(FontWeight.Bold)
          .fontColor($r('app.color.ink')).layoutWeight(1);
      }
      .width('100%')
      .padding({ left: 14, right: 14, top: 10, bottom: 10 })
      .backgroundColor($r('app.color.surface'));

      Row() {
        ForEach([0, 1], (i: number) => {
          Column({ space: 4 }) {
            Text(i === 0 ? '评价' : `待处理售后 ${this.afterSales.length}`)
              .fontSize(14)
              .fontWeight(this.tab === i ? FontWeight.Bold : FontWeight.Normal)
              .fontColor(this.tab === i
                ? $r('app.color.ink') : $r('app.color.ink_muted'));
            Divider().width(28).strokeWidth(2)
              .color(this.tab === i
                ? $r('app.color.brand') : Color.Transparent);
          }
          .layoutWeight(1).padding({ top: 10, bottom: 6 })
          .onClick(() => { this.tab = i; });
        }, (i: number) => `t${i}`);
      }
      .width('100%').backgroundColor($r('app.color.surface'));

      if (this.tab === 0) {
        Row({ space: 8 }) {
          ForEach([0, 1, 2], (i: number) => {
            Text(i === 0 ? '全部' : i === 1 ? '差评' : '待回复')
              .fontSize(12)
              .fontColor(this.filter === i
                ? Color.White : $r('app.color.ink'))
              .padding({ left: 12, right: 12, top: 5, bottom: 5 })
              .borderRadius(12)
              .backgroundColor(this.filter === i
                ? $r('app.color.brand') : $r('app.color.surface_alt'))
              .onClick(() => {
                this.filter = i;
                this.loaded = false;
                this.load();
              });
          }, (i: number) => `f${i}`);
        }
        .width('100%')
        .padding({ left: 12, right: 12, top: 8, bottom: 4 });
      }

      if (!this.loaded) {
        Column() {
          LoadingProgress().width(40).height(40);
        }
        .layoutWeight(1).justifyContent(FlexAlign.Center);
      } else if (this.tab === 0 && this.errorText.length > 0) {
        // 差评看不到就错过申诉窗口。「没有评价」和「没拉到」必须分开
        Column({ space: 12 }) {
          Text('评价没能加载出来')
            .fontSize(15).fontColor($r('app.color.ink'));
          Text(this.errorText).fontSize(13)
            .fontColor($r('app.color.ink_muted'))
            .textAlign(TextAlign.Center);
          Button('重试').height(40).width(130)
            .backgroundColor($r('app.color.brand'))
            .onClick(() => { this.load(); });
        }
        .layoutWeight(1).justifyContent(FlexAlign.Center).padding(30);
      } else if (this.tab === 0) {
        if (this.ds.totalCount() === 0) {
          Column() {
            Text('这一栏没有评价')
              .fontSize(14).fontColor($r('app.color.ink_muted'));
          }
          .layoutWeight(1).justifyContent(FlexAlign.Center);
        } else {
          List() {
            LazyForEach(this.ds, (r: Review) => {
              ListItem() {
                this.reviewCard(r);
              }
            }, (r: Review) => `${r.id}-${r.reply ?? ''}`);
          }
          .layoutWeight(1).width('100%')
          .padding({ left: 12, right: 12, top: 10 })
          .scrollBar(BarState.Off);
        }
      } else {
        if (this.afterSales.length === 0) {
          Column() {
            Text('没有待处理的售后')
              .fontSize(14).fontColor($r('app.color.ink_muted'));
          }
          .layoutWeight(1).justifyContent(FlexAlign.Center);
        } else {
          Scroll() {
            Column() {
              ForEach(this.afterSales, (s: AfterSale) => {
                this.afterSaleCard(s);
              }, (s: AfterSale) => `${s.id}`);
            }
            .width('100%').padding({ left: 12, right: 12, top: 10 });
          }
          .layoutWeight(1).scrollBar(BarState.Off);
        }
      }
    }
    .width('100%').height('100%')
    .backgroundColor($r('app.color.page'))
    .bindSheet($$this.showReply, this.replySheet(),
      { height: 300, dragBar: false })
    .bindSheet($$this.showProcess, this.processSheet(),
      { height: 320, dragBar: false });
  }
}
