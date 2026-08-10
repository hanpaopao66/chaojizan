import { UserApi } from '../common/UserApi';

/**
 * 钱去哪了 / 5% 说明 / 见证节点。
 *
 * 这一页回答的是「为什么信你」。三部分:
 * 1. 每 100 元怎么分(实算,不是画饼);
 * 2. 5% 是什么、不是什么;
 * 3. 账本有谁在盯(见证节点)。
 *
 * ⚠️ 每 100 元的分账比例**读服务端的 fairness 端点**,不写死。
 * 安卓端这里是写死的常量(有注释说明是有意为之),但既然接口有真实数据,
 * 鸿蒙端就用真的 —— 写死的数字哪天和实际不符,这一页就变成了反面教材。
 */
@Component
export struct MoneyFlowPage {
  @State private fairness: Record<string, Object> | null = null;
  @State private nodes: Record<string, Object> | null = null;
  @State private loading: boolean = true;

  private api: UserApi = new UserApi();

  async aboutToAppear(): Promise<void> {
    this.api.fairnessPublic()
      .then((d: Record<string, Object>) => { this.fairness = d; })
      .catch(() => {})
      .finally(() => { this.loading = false; });
    this.api.nodesSummary()
      .then((d: Record<string, Object>) => { this.nodes = d; })
      .catch(() => {});
  }

  private nested(d: Record<string, Object> | null,
                 outer: string, inner: string): number {
    if (d === null) {
      return 0;
    }
    const o: Object = d[outer] ?? {};
    const map: Record<string, Object> = o as Record<string, Object>;
    const v: Object = map[inner] ?? 0;
    return typeof v === 'number' ? v : 0;
  }

  private num(d: Record<string, Object> | null, key: string): number {
    if (d === null) {
      return 0;
    }
    const v: Object = d[key] ?? 0;
    return typeof v === 'number' ? v : 0;
  }

  @Builder
  private bar(label: string, value: number, color: Resource) {
    Column({ space: 4 }) {
      Row() {
        Text(label).fontSize(13).fontColor($r('app.color.ink')).layoutWeight(1);
        Text(`${value} 元`).fontSize(13).fontColor(color);
      }
      .width('100%');
      Row() {
        Row().width(`${value > 100 ? 100 : value}%`).height(6)
          .backgroundColor(color).borderRadius(3);
      }
      .width('100%').height(6).backgroundColor($r('app.color.surface_alt')).borderRadius(3);
    }
    .width('100%');
  }

  build() {
    Scroll() {
      Column({ space: 10 }) {
        Column({ space: 10 }) {
          Text('每 100 元,钱是这么分的')
            .fontSize(18).fontWeight(FontWeight.Bold)
            .fontColor($r('app.color.ink')).width('100%');
          if (this.loading) {
            Row() { LoadingProgress().width(20).height(20); }.width('100%');
          } else {
            this.bar('商家实收', this.nested(this.fairness, 'per100', 'merchant'),
              $r('app.color.ink'));
            this.bar('骑手所得', this.nested(this.fairness, 'per100', 'rider'),
              $r('app.color.earn'));
            this.bar('平台佣金', this.nested(this.fairness, 'per100', 'commission'),
              $r('app.color.brand'));
            Text('数字来自服务端实算,不是宣传口径 —— 真实佣金率是 ' +
              `${(this.nested(this.fairness, 'commission', 'real_rate_30d') * 100).toFixed(2)}%`)
              .fontSize(11).fontColor($r('app.color.ink_muted')).width('100%');
          }
        }
        .width('100%').padding(16).backgroundColor($r('app.color.surface'))
        .borderRadius(14).alignItems(HorizontalAlign.Start);

        Column({ space: 8 }) {
          Text('5% 是什么')
            .fontSize(16).fontWeight(FontWeight.Medium)
            .fontColor($r('app.color.ink')).width('100%');
          Text('· 这是商家的**总负担上限**,不是起步价。5% 是上限不是目标,' +
            '哪天 3% 能活就降到 3%')
            .fontSize(13).fontColor($r('app.color.ink_muted')).width('100%');
          Text('· 平台**只有这一项收入**:不卖数据、不做竞价排名、' +
            '不收推广费、不抽配送费')
            .fontSize(13).fontColor($r('app.color.ink_muted')).width('100%');
          Text('· 配送费和小费 100% 归骑手,提现零手续费')
            .fontSize(13).fontColor($r('app.color.ink_muted')).width('100%');
          Text('· 到店团购核销才收 2%,住宿离店才收 5%')
            .fontSize(13).fontColor($r('app.color.ink_muted')).width('100%');
        }
        .width('100%').padding(16).backgroundColor($r('app.color.surface'))
        .borderRadius(14).alignItems(HorizontalAlign.Start);

        Column({ space: 8 }) {
          Text('账本有谁在盯')
            .fontSize(16).fontWeight(FontWeight.Medium)
            .fontColor($r('app.color.ink')).width('100%');
          Row() {
            Text('在线见证节点')
              .fontSize(13).fontColor($r('app.color.ink_muted')).layoutWeight(1);
            Text(`${this.num(this.nodes, 'online')} / ${this.num(this.nodes, 'total')}`)
              .fontSize(13).fontColor($r('app.color.ink'));
          }
          .width('100%');
          Row() {
            Text('复算一致')
              .fontSize(13).fontColor($r('app.color.ink_muted')).layoutWeight(1);
            Text(`${this.num(this.nodes, 'verified_ok')}`)
              .fontSize(13).fontColor($r('app.color.earn'));
          }
          .width('100%');
          Row() {
            Text('复算不一致')
              .fontSize(13).fontColor($r('app.color.ink_muted')).layoutWeight(1);
            Text(`${this.num(this.nodes, 'divergent')}`)
              .fontSize(13)
              .fontColor(this.num(this.nodes, 'divergent') > 0
                ? $r('app.color.brand') : $r('app.color.ink'));
          }
          .width('100%');
          Text('账务流水做成哈希链并对外锚定,社区节点持续复算 ——' +
            '改历史上任何一分钱,全网都会知道。')
            .fontSize(11).fontColor($r('app.color.ink_muted')).width('100%');
        }
        .width('100%').padding(16).backgroundColor($r('app.color.surface'))
        .borderRadius(14).alignItems(HorizontalAlign.Start);
      }
      .width('100%').padding({ left: 12, right: 12, top: 12, bottom: 16 });
    }
    .width('100%').height('100%')
    .backgroundColor($r('app.color.page'));
  }
}
