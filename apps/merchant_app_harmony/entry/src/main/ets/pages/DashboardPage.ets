import { MerchantApi } from '../common/MerchantApi';
import { ApiException } from '../common/Api';
import { yuan } from '../common/Money';

/** 趋势里的一周 */
interface WeekPoint {
  week: string;
  orders: number;
  food_cents: number;
  customers: number;
  /** 没单时是 null 而不是 0 —— 0 会被读成「客单价跌到零」 */
  avg_cents?: number;
  /** 本周还没过完,单量天然偏低 */
  partial?: boolean;
}

/**
 * 经营看板:打烊后坐下来看的那一屏。
 *
 * ## 守住的那条线
 *
 * **看了这张图,商家会做什么决定?** 答不上来的图不放。
 *
 * | 图 | 回答的问题 | 商家的动作 |
 * |---|---|---|
 * | 近 8 周趋势 | 生意在变好还是变坏 | 决定要不要调整 |
 * | 流失漏斗 | 单量掉在哪一环 | 针对性修 |
 *
 * ## 三条呈现纪律(从安卓端搬)
 *
 * - **先结论后图表**:每张图上方一句话说明它说明了什么。
 *   能一句话说清的,不该让商家自己从折线里读;
 * - **环比用周不用天**:外卖周内节律强(周末 ≠ 周三),按天比会把节律
 *   当趋势,得出「周一生意变差了」这种废话 —— 每个周一都比周日差。
 *   而且**本周不参与环比**:周二拿两天比上周整七天,
 *   每个周一周二商家都会白慌一场;
 * - **没数据时说没数据,不画平线** —— 一条平线会被读成「生意很平稳」。
 *
 * ## 不做的
 *
 * 不做同行对比、不做区域排名。一旦排名影响生意,商家的动作会从
 * 「把菜做好」变成「把数字做好看」。
 */
@Component
export struct DashboardPage {
  onBack: () => void = () => {};

  @State private series: WeekPoint[] = [];
  @State private funnel: Record<string, Object> | null = null;
  @State private today: Record<string, Object> | null = null;
  @State private errorText: string = '';
  @State private funnelError: string = '';
  @State private loaded: boolean = false;

  private api: MerchantApi = new MerchantApi();

  aboutToAppear(): void {
    this.load();
  }

  private async load(): Promise<void> {
    // 三个互不依赖,先都发出去
    const trendF: Promise<Record<string, Object>> = this.api.merchantTrend(8);
    const funnelF: Promise<Record<string, Object>> = this.api.merchantFunnel();
    const todayF: Promise<Record<string, Object>> = this.api.merchantToday();

    // 漏斗和今日是附加信息:拉不到不拦着看趋势
    try {
      this.funnel = await funnelF;
      this.funnelError = '';
    } catch (e) {
      this.funnelError = (e as ApiException).message;
    }
    try {
      this.today = await todayF;
    } catch (_) {
      // 今日概览在订单页也有一份,这里缺了不影响复盘
    }

    try {
      const t: Record<string, Object> = await trendF;
      const raw: Object | undefined = t['series'];
      this.series = (raw === undefined ? [] : raw) as WeekPoint[];
      this.errorText = '';
    } catch (e) {
      this.errorText = (e as ApiException).message;
    } finally {
      this.loaded = true;
    }
  }

  /** 完整的周(排掉本周)。环比只拿完整周比 */
  private fullWeeks(): WeekPoint[] {
    return this.series.filter((w: WeekPoint) => w.partial !== true);
  }

  /**
   * 一句话结论。**这是这一页最有价值的部分** ——
   * 商家不该自己从折线里读出"生意在变差"。
   */
  private verdict(): string {
    const full: WeekPoint[] = this.fullWeeks();
    if (full.length < 2) {
      return '数据还不够两个完整周,先攒一攒 —— 不拿半周的数字下结论。';
    }
    const cur: WeekPoint = full[full.length - 1];
    const prev: WeekPoint = full[full.length - 2];
    if (prev.orders === 0) {
      return `上一个完整周 ${cur.orders} 单。再上一周没有单,没法比。`;
    }
    const pct: number = (cur.orders - prev.orders) / prev.orders * 100;
    const abs: string = Math.abs(pct).toFixed(0);
    if (Math.abs(pct) < 5) {
      return `上一个完整周 ${cur.orders} 单,和前一周基本持平。`;
    }
    return pct > 0
        ? `上一个完整周 ${cur.orders} 单,比前一周多了 ${abs}%。`
        : `上一个完整周 ${cur.orders} 单,比前一周少了 ${abs}% —— ` +
          '往下翻漏斗,看是哪一环在漏。';
  }

  private maxOrders(): number {
    let m: number = 1;
    for (let i: number = 0; i < this.series.length; i++) {
      if (this.series[i].orders > m) {
        m = this.series[i].orders;
      }
    }
    return m;
  }

  private rate(key: string): number {
    const v: Object | undefined = this.funnel?.[key];
    return v === undefined ? 0 : v as number;
  }

  private cnt(key: string): number {
    const v: Object | undefined = this.funnel?.[key];
    return v === undefined ? 0 : v as number;
  }

  /** 漏斗里最漏的那一环。直接点名,别让商家自己比三个百分比 */
  private worstStep(): string {
    if (this.funnel === null) {
      return '';
    }
    const steps: string[] = ['看到 → 进店', '进店 → 结算', '结算 → 下单'];
    const rates: number[] = [
      this.rate('visit_rate'), this.rate('checkout_rate'),
      this.rate('order_rate'),
    ];
    let worst: number = 0;
    for (let i: number = 1; i < rates.length; i++) {
      if (rates[i] < rates[worst]) {
        worst = i;
      }
    }
    if (rates[worst] === 0) {
      return '这几天数据太少,漏斗还看不出名堂。';
    }
    const hint: string = worst === 0
        ? '门头图、店名、评分决定别人点不点进来。'
        : worst === 1
            ? '菜单和起送价决定他愿不愿意凑单 —— 起送价太高是最常见的原因。'
            : '结算页劝退多半是配送费或出餐时长。';
    return `最漏的一环是「${steps[worst]}」,` +
        `${(rates[worst] * 100).toFixed(0)}%。${hint}`;
  }

  @Builder
  private weekBar(w: WeekPoint) {
    Column({ space: 4 }) {
      Text(`${w.orders}`)
        .fontSize(10)
        .fontColor(w.partial === true
          ? $r('app.color.ink_faint') : $r('app.color.ink_muted'));
      // 高度按最大值归一。没单的那周**柱子为零**,不画一条平线糊弄
      Column()
        .width(18)
        .height(Math.max(2, w.orders / this.maxOrders() * 96))
        .borderRadius(3)
        .backgroundColor(w.partial === true
          ? $r('app.color.surface_alt') : $r('app.color.brand'));
      Text(w.week.length >= 10 ? w.week.substring(5) : w.week)
        .fontSize(9).fontColor($r('app.color.ink_faint'));
    }
    .layoutWeight(1).alignItems(HorizontalAlign.Center);
  }

  @Builder
  private funnelStep(label: string, count: number, rate: number) {
    Column({ space: 3 }) {
      Row() {
        Text(label).fontSize(13)
          .fontColor($r('app.color.ink_muted')).layoutWeight(1);
        Text(`${count} 人`).fontSize(13)
          .fontColor($r('app.color.ink'));
      }
      .width('100%');
      Row() {
        Column()
          .height(6).borderRadius(3)
          .width(`${Math.max(2, rate * 100)}%`)
          .backgroundColor($r('app.color.brand'));
      }
      .width('100%')
      .backgroundColor($r('app.color.surface_alt'))
      .borderRadius(3);
    }
    .width('100%').padding({ top: 6, bottom: 6 });
  }

  build() {
    Column() {
      Row({ space: 10 }) {
        Text('‹').fontSize(24).fontColor($r('app.color.ink'))
          .onClick(() => { this.onBack(); });
        Text('经营看板')
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
          Text('看板数据没能加载出来')
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
            // ---- 近 8 周趋势 ----
            Column({ space: 10 }) {
              Text('近 8 周单量')
                .fontSize(13).fontWeight(FontWeight.Medium)
                .fontColor($r('app.color.ink')).width('100%');
              // 先结论后图表
              Text(this.verdict())
                .fontSize(13).lineHeight(20)
                .fontColor($r('app.color.ink')).width('100%');

              if (this.series.length === 0) {
                Text('还没有数据。有单之后这里会按周画出来。')
                  .fontSize(12).fontColor($r('app.color.ink_muted'))
                  .width('100%').padding({ top: 16, bottom: 16 });
              } else {
                Row({ space: 4 }) {
                  ForEach(this.series, (w: WeekPoint) => {
                    this.weekBar(w);
                  }, (w: WeekPoint) => w.week);
                }
                .width('100%').alignItems(VerticalAlign.Bottom)
                .padding({ top: 8 });
                Text('浅色那根是本周,还没过完,不参与环比。')
                  .fontSize(11).fontColor($r('app.color.ink_muted'))
                  .width('100%');
              }
            }
            .width('100%').padding(14)
            .backgroundColor($r('app.color.surface')).borderRadius(12);

            // ---- 流失漏斗 ----
            Column({ space: 8 }) {
              Text('顾客流失在哪一环')
                .fontSize(13).fontWeight(FontWeight.Medium)
                .fontColor($r('app.color.ink')).width('100%');
              Text('我们不卖曝光位,但把真实的漏斗给你看 —— 哪一环在漏,自己就知道该改什么。')
                .fontSize(11).lineHeight(17)
                .fontColor($r('app.color.ink_muted')).width('100%');

              if (this.funnelError.length > 0) {
                Row({ space: 8 }) {
                  Text('⚠').fontSize(14).fontColor($r('app.color.danger'));
                  Text(`漏斗没拉到(${this.funnelError})。点这里重试`)
                    .fontSize(12).fontColor($r('app.color.danger'))
                    .layoutWeight(1);
                }
                .width('100%').padding(10)
                .backgroundColor('#1AC0392B').borderRadius(8)
                .onClick(() => { this.load(); });
              } else if (this.funnel === null) {
                LoadingProgress().width(26).height(26);
              } else {
                Text(this.worstStep())
                  .fontSize(13).lineHeight(20)
                  .fontColor($r('app.color.ink')).width('100%')
                  .margin({ top: 2, bottom: 4 });
                this.funnelStep('看到你的店', this.cnt('impression'), 1);
                this.funnelStep('点进来看了', this.cnt('visit'),
                  this.rate('visit_rate'));
                this.funnelStep('进了结算页', this.cnt('checkout'),
                  this.rate('checkout_rate'));
                this.funnelStep('真的下了单', this.cnt('ordered'),
                  this.rate('order_rate'));
              }
            }
            .width('100%').padding(14)
            .backgroundColor($r('app.color.surface')).borderRadius(12);

            // ---- 今日 ----
            if (this.today !== null) {
              Column({ space: 6 }) {
                Text('今天')
                  .fontSize(13).fontWeight(FontWeight.Medium)
                  .fontColor($r('app.color.ink')).width('100%');
                Row() {
                  Text('实收').fontSize(13)
                    .fontColor($r('app.color.ink_muted')).layoutWeight(1);
                  Text(yuan((this.today?.['today'] as Record<string, Object>
                    | undefined)?.['net_cents'] as number ?? 0))
                    .fontSize(19).fontWeight(FontWeight.Bold)
                    .fontColor($r('app.color.earn'));
                }
                .width('100%');
              }
              .width('100%').padding(14)
              .backgroundColor($r('app.color.surface')).borderRadius(12);
            }

            Text('不做同行对比、不做区域排名。一旦排名影响生意,' +
              '动作就会从「把菜做好」变成「把数字做好看」。')
              .fontSize(11).lineHeight(18)
              .fontColor($r('app.color.ink_muted'))
              .width('100%').padding({ left: 4, right: 4 });

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
