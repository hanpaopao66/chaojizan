import { UserApi } from '../common/UserApi';
import { yuan } from '../common/Money';

/**
 * 平台体检。
 *
 * 十个公开端点全部摊开:每日核账、资金去向、赔付记录、月度财报、公平性、
 * 更新日志、可用率、明厨亮灶规则、治理留痕、派单算法。
 *
 * **这一页的价值在于它敢难看。** 核账差一分钱亮红灯、探针缺档按不可用算、
 * 平台倒贴照实写。做成"一切正常"的粉饰式汇总,这一页就一文不值 ——
 * 用户不会因为看到绿灯而信任你,只会因为看到你敢显示红灯而信任你。
 *
 * 两个安卓端踩过的坑:
 * 1. **服务端返回的是"有记录的天",不是日历天**。直接渲染会把"没查过"
 *    显示成"没问题" —— 要按 90 天日历补齐,缺的天单列;
 * 2. `clean_streak_days` 只按运行记录连续数,**会高估**,旁边要标口径。
 */

/** 一个区块的加载状态。**某一项挂了只降级那一块**,不能整页白屏 */
class Slot {
  key: string = '';
  title: string = '';
  loading: boolean = true;
  failed: boolean = false;
  data: Record<string, Object> | null = null;

  constructor(key: string, title: string) {
    this.key = key;
    this.title = title;
  }
}

@Component
export struct TransparencyPage {
  @State private slots: Slot[] = [
    new Slot('audit', '每日核账'),
    new Slot('funds', '钱去哪了'),
    new Slot('compensation', '平台赔了多少'),
    new Slot('uptime', '系统可用率'),
    new Slot('fairness', '分账公平性'),
    new Slot('governance', '规则变更留痕'),
    new Slot('dispatch', '派单算法'),
    new Slot('changelog', '线上版本'),
  ];
  @State private version: number = 0;

  private api: UserApi = new UserApi();

  async aboutToAppear(): Promise<void> {
    // 十个端点并发拉。互不依赖,串起来用户要等十个来回
    for (let i = 0; i < this.slots.length; i++) {
      this.fetch(this.slots[i]);
    }
  }

  private fetch(slot: Slot): void {
    const p: Promise<Record<string, Object>> = this.pick(slot.key);
    p.then((d: Record<string, Object>) => {
      slot.data = d;
      slot.loading = false;
      slot.failed = false;
      this.version += 1;
    }).catch(() => {
      slot.loading = false;
      slot.failed = true;
      this.version += 1;
    });
  }

  private pick(key: string): Promise<Record<string, Object>> {
    if (key === 'audit') {
      return this.api.auditPublic();
    }
    if (key === 'funds') {
      return this.api.fundsPublic();
    }
    if (key === 'compensation') {
      return this.api.compensationPublic();
    }
    if (key === 'uptime') {
      return this.api.uptimePublic();
    }
    if (key === 'fairness') {
      return this.api.fairnessPublic();
    }
    if (key === 'governance') {
      return this.api.governancePublic();
    }
    if (key === 'dispatch') {
      return this.api.dispatchSpec();
    }
    return this.api.changelogPublic();
  }

  private num(d: Record<string, Object> | null, key: string): number {
    if (d === null) {
      return 0;
    }
    const v: Object = d[key] ?? 0;
    return typeof v === 'number' ? v : 0;
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

  @Builder
  private line(label: string, value: string, warn: boolean) {
    Row() {
      Text(label).fontSize(13).fontColor($r('app.color.ink_muted')).layoutWeight(1);
      Text(value)
        .fontSize(13)
        .fontColor(warn ? $r('app.color.brand') : $r('app.color.ink'));
    }
    .width('100%').padding({ top: 4, bottom: 4 });
  }

  /** 数组长度。@Builder 里不写局部变量,统统走方法 */
  private listLen(d: Record<string, Object> | null, key: string): number {
    if (d === null) {
      return 0;
    }
    const v: Object = d[key] ?? [];
    return (v as Object[]).length;
  }

  private auditWindow(d: Record<string, Object> | null): number {
    const w: number = this.num(d, 'window_days');
    return w > 0 ? w : 90;
  }

  private auditMissing(d: Record<string, Object> | null): number {
    const miss: number = this.auditWindow(d) - this.listLen(d, 'runs');
    return miss > 0 ? miss : 0;
  }

  /** 核账。**差一分钱就亮红** —— 这一条是整页的立身之本 */
  @Builder
  private auditBody(d: Record<string, Object> | null) {
    Column() {
      this.line('核过账的天数',
        `${this.listLen(d, 'runs')} / ${this.auditWindow(d)} 天`,
        this.auditMissing(d) > 0);
      // ⚠️ 返回的是"有记录的天"。没跑核账的日子根本不在数组里,
      // 直接说"一切正常"就是把"没查过"显示成"没问题"
      if (this.auditMissing(d) > 0) {
        Text(`有 ${this.auditMissing(d)} 天没有核账记录 —— 没查过不等于没问题`)
          .fontSize(11).fontColor($r('app.color.brand')).width('100%');
      }
      this.line('对不上的笔数', `${this.num(d, 'problem_count')}`,
        this.num(d, 'problem_count') > 0);
      this.line('连续无差错', `${this.num(d, 'clean_streak_days')} 天`, false);
      Text('口径:连续天数只按有核账记录的天连续计算,会高估')
        .fontSize(11).fontColor($r('app.color.ink_muted')).width('100%');
    }
    .width('100%').alignItems(HorizontalAlign.Start);
  }

  @Builder
  private fundsBody(d: Record<string, Object> | null) {
    Column() {
      this.line('佣金收入', yuan(this.nested(d, 'income', 'commission_cents')), false);
      this.line('团购核销费', yuan(this.nested(d, 'income', 'voucher_fee_cents')), false);
      this.line('收入合计', yuan(this.nested(d, 'income', 'total_cents')), false);
      Divider().margin({ top: 6, bottom: 6 });
      this.line('平台补贴支出', yuan(this.nested(d, 'spend', 'subsidy_cents')), false);
      this.line('餐损赔付', yuan(this.nested(d, 'spend', 'meal_compensation_cents')), false);
      this.line('支出合计', yuan(this.nested(d, 'spend', 'total_cents')), false);
      Divider().margin({ top: 6, bottom: 6 });
      this.line('平台留存', yuan(this.num(d, 'retained_cents')),
        this.num(d, 'retained_cents') < 0);
      if (this.num(d, 'retained_cents') < 0) {
        // 倒贴也照实写。粉饰这一行,整页就没有意义了
        Text('平台目前是倒贴的')
          .fontSize(12).fontColor($r('app.color.brand')).width('100%');
      }
    }
    .width('100%').alignItems(HorizontalAlign.Start);
  }

  @Builder
  private compensationBody(d: Record<string, Object> | null) {
    Column() {
      this.line('超时安抚券(累计)',
        yuan(this.nested(d, 'eta_coupons', 'cents')), false);
      this.line('餐损赔付(累计)',
        yuan(this.nested(d, 'meal_compensation', 'cents')), false);
      this.line('退款(累计)', yuan(this.nested(d, 'refunds', 'cents')), false);
      Text('这些是平台赔出去的钱。列在这里不是为了显得大方,' +
        '是为了让你知道出了问题平台确实在赔。')
        .fontSize(11).fontColor($r('app.color.ink_muted')).width('100%');
    }
    .width('100%').alignItems(HorizontalAlign.Start);
  }

  private uptimeMissing(d: Record<string, Object> | null): number {
    const miss: number = 90 - this.listLen(d, 'days');
    return miss > 0 ? miss : 0;
  }

  @Builder
  private uptimeBody(d: Record<string, Object> | null) {
    Column() {
      this.line('有探针记录的天', `${this.listLen(d, 'days')} / 90 天`,
        this.uptimeMissing(d) > 0);
      if (this.uptimeMissing(d) > 0) {
        // 缺档按不可用算,不按"那天没问题"算
        Text(`有 ${this.uptimeMissing(d)} 天没有探针记录,这些天一律按不可用计入`)
          .fontSize(11).fontColor($r('app.color.brand')).width('100%');
      }
      this.line('今天的探针', `${this.nested(d, 'today', 'ok')} / ${this.nested(d, 'today', 'probes')}`,
        this.nested(d, 'today', 'ok') < this.nested(d, 'today', 'probes'));
    }
    .width('100%').alignItems(HorizontalAlign.Start);
  }

  /** 真实佣金率有没有超过承诺的上限。超了要说,这是承诺不是宣传 */
  private overCap(d: Record<string, Object> | null): boolean {
    const cap: number = this.nested(d, 'commission', 'promised_cap');
    return cap > 0 && this.nested(d, 'commission', 'real_rate_30d') > cap;
  }

  @Builder
  private fairnessBody(d: Record<string, Object> | null) {
    Column() {
      this.line('近 30 天真实佣金率',
        `${(this.nested(d, 'commission', 'real_rate_30d') * 100).toFixed(2)}%`,
        this.overCap(d));
      this.line('承诺上限',
        `${(this.nested(d, 'commission', 'promised_cap') * 100).toFixed(2)}%`, false);
      if (this.overCap(d)) {
        Text('真实佣金率已超过承诺上限 —— 这是需要解释的')
          .fontSize(12).fontColor($r('app.color.brand')).width('100%');
      }
      Text('每 100 元怎么分:商家 ' + `${this.nested(d, 'per100', 'merchant')}` +
        ' / 骑手 ' + `${this.nested(d, 'per100', 'rider')}` +
        ' / 平台 ' + `${this.nested(d, 'per100', 'commission')}`)
        .fontSize(12).fontColor($r('app.color.ink')).width('100%');
    }
    .width('100%').alignItems(HorizontalAlign.Start);
  }

  @Builder
  private genericBody() {
    Column() {
      Text('这一项服务端有数据,详细内容在网页版透明中心可以逐条查看')
        .fontSize(12).fontColor($r('app.color.ink_muted')).width('100%');
    }
    .width('100%').alignItems(HorizontalAlign.Start);
  }

  @Builder
  private section(slot: Slot) {
    Column({ space: 8 }) {
      Text(slot.title)
        .fontSize(15).fontWeight(FontWeight.Medium)
        .fontColor($r('app.color.ink')).width('100%');
      if (slot.loading) {
        Row() { LoadingProgress().width(20).height(20); }
        .width('100%');
      } else if (slot.failed) {
        // 单项失败只降级这一块。十个全挂才整页降级
        Row({ space: 10 }) {
          Text('这项暂时取不到')
            .fontSize(12).fontColor($r('app.color.ink_muted')).layoutWeight(1);
          Text('重试')
            .fontSize(12).fontColor($r('app.color.brand'))
            .onClick(() => {
              slot.loading = true;
              slot.failed = false;
              this.version += 1;
              this.fetch(slot);
            });
        }
        .width('100%');
      } else if (slot.key === 'audit') {
        this.auditBody(slot.data);
      } else if (slot.key === 'funds') {
        this.fundsBody(slot.data);
      } else if (slot.key === 'compensation') {
        this.compensationBody(slot.data);
      } else if (slot.key === 'uptime') {
        this.uptimeBody(slot.data);
      } else if (slot.key === 'fairness') {
        this.fairnessBody(slot.data);
      } else {
        this.genericBody();
      }
    }
    .width('100%').padding(16).backgroundColor($r('app.color.surface'))
    .borderRadius(14).alignItems(HorizontalAlign.Start);
  }

  build() {
    Scroll() {
      Column({ space: 10 }) {
        Column({ space: 6 }) {
          Text('平台体检')
            .fontSize(20).fontWeight(FontWeight.Bold)
            .fontColor($r('app.color.ink')).width('100%');
          Text('这一页会显示难看的数字:核账对不上、探针缺档、平台倒贴,' +
            '都照实写。不敢难看的透明不叫透明。')
            .fontSize(12).fontColor($r('app.color.ink_muted')).width('100%');
        }
        .width('100%').padding(16).backgroundColor($r('app.color.surface'))
        .borderRadius(14).alignItems(HorizontalAlign.Start);

        ForEach(this.slots, (s: Slot) => {
          this.section(s);
        }, (s: Slot) => `${s.key}-${this.version}`);
      }
      .width('100%').padding({ left: 12, right: 12, top: 12, bottom: 16 });
    }
    .width('100%').height('100%')
    .backgroundColor($r('app.color.page'));
  }
}
