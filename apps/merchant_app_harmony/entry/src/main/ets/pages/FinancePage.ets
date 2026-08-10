import { promptAction } from '@kit.ArkUI';
import { MerchantApi } from '../common/MerchantApi';
import { ApiException } from '../common/Api';
import { yuan } from '../common/Money';
import { DayStat, Wallet, Withdrawal } from '../model/Models';

/**
 * 对账。
 *
 * ## 五个请求先全部发出去再逐个 await
 *
 * 它们互不依赖,排成一队就是五个来回 —— 店里网不好时点开「对账」
 * 是几秒钟的白屏。安卓端刚改过这个,见 DEV-PROMPTS-27 #238。
 *
 * **各自兜底**:钱包和流水是这一页的主角,拉不到要报错;
 * 品质分和费率档是附加信息,挂了不该把整页打回错误态 ——
 * 商家来这一页多半是要看钱、要提现,不是来看品质分的。
 *
 * ## 账目透明是唯一抄不走的差异点
 *
 * 「被抽了多少」要和「挣了多少」摆在同一屏,不能藏进二级页。
 * 佣金用 hold 色(被抽走的),实收用 ink —— 颜色本身就是一种说明。
 */
@Component
export struct FinancePage {

  @State private daily: DayStat[] = [];
  @State private wallet: Wallet | null = null;
  @State private withdrawals: Withdrawal[] = [];
  @State private quality: Record<string, Object> | null = null;
  @State private tier: Record<string, Object> | null = null;
  @State private loaded: boolean = false;
  @State private errorText: string = '';

  private api: MerchantApi = new MerchantApi();

  aboutToAppear(): void {
    this.load();
  }

  private async load(): Promise<void> {
    // 先全部发出去,这一步不能 await,否则又串回去了
    const dailyF: Promise<DayStat[]> = this.api.financeDaily();
    const walletF: Promise<Wallet> = this.api.merchantWallet();
    const wdF: Promise<Withdrawal[]> = this.api.merchantWithdrawals();
    const qualityF: Promise<Record<string, Object>> = this.api.merchantQuality();
    const tierF: Promise<Record<string, Object>> =
        this.api.merchantCommissionTier();

    // 附加信息:挂了退回上一次的值。**必须先接住异常** ——
    // 已经发出去的 Promise 没人 await 就是未处理的异步错误
    let quality: Record<string, Object> | null = this.quality;
    let tier: Record<string, Object> | null = this.tier;
    try {
      quality = await qualityF;
    } catch (_) {
      // 品质分不是这一页的主角,拉不到不拦着看钱
    }
    try {
      tier = await tierF;
    } catch (_) {
      // 费率档同上
    }

    try {
      const daily: DayStat[] = await dailyF;
      const wallet: Wallet = await walletF;
      const wds: Withdrawal[] = await wdF;
      this.daily = daily;
      this.wallet = wallet;
      this.withdrawals = wds;
      this.quality = quality;
      this.tier = tier;
      this.errorText = '';
    } catch (e) {
      this.errorText = (e as ApiException).message;
    } finally {
      this.loaded = true;
    }
  }

  private async withdraw(): Promise<void> {
    const w: Wallet | null = this.wallet;
    if (w === null) {
      return;
    }
    const amount: number = w.withdrawable_cents ?? w.balance_cents;
    if (amount <= 0) {
      promptAction.showToast({ message: '当前没有可提现的余额' });
      return;
    }
    try {
      await this.api.requestMerchantWithdrawal(amount);
      promptAction.showToast({ message: `已提交提现 ${yuan(amount)},等待打款` });
      await this.load();
    } catch (e) {
      promptAction.showToast({ message: (e as ApiException).message });
    }
  }

  private todayKey(): string {
    const d: Date = new Date();
    const two = (n: number): string => n < 10 ? `0${n}` : `${n}`;
    return `${d.getFullYear()}-${two(d.getMonth() + 1)}-${two(d.getDate())}`;
  }

  private todayStat(): DayStat | null {
    const key: string = this.todayKey();
    for (let i: number = 0; i < this.daily.length; i++) {
      if (this.daily[i].day === key) {
        return this.daily[i];
      }
    }
    return null;
  }

  @Builder
  private row(label: string, value: string, color: Resource,
              big: boolean = false) {
    Row() {
      Text(label).fontSize(big ? 14 : 13)
        .fontColor($r('app.color.ink_muted')).layoutWeight(1);
      Text(value)
        .fontSize(big ? 20 : 14)
        .fontWeight(big ? FontWeight.Bold : FontWeight.Normal)
        .fontColor(color);
    }
    .width('100%').padding({ top: 5, bottom: 5 });
  }

  @Builder
  private walletCard(w: Wallet) {
    Column({ space: 8 }) {
      this.row('可提现', yuan(w.withdrawable_cents ?? w.balance_cents),
        $r('app.color.earn'), true);
      if ((w.pending_cents ?? 0) > 0) {
        this.row('在途(订单未完成)', yuan(w.pending_cents ?? 0),
          $r('app.color.ink_muted'));
      }
      Button('提现')
        .width('100%').height(42)
        .backgroundColor($r('app.color.brand'))
        .enabled((w.withdrawable_cents ?? w.balance_cents) > 0)
        .onClick(() => { this.withdraw(); });
    }
    .width('100%').padding(14)
    .backgroundColor($r('app.color.surface')).borderRadius(12);
  }

  @Builder
  private tierCard() {
    Column({ space: 6 }) {
      Row() {
        Text('阶梯佣金').fontSize(13).fontWeight(FontWeight.Medium)
          .fontColor($r('app.color.ink')).layoutWeight(1);
        // 费率是"被抽走的",用 hold 不用强调色
        Text(`${((this.tier?.['commission_rate'] as number ?? 0.05) * 100).toFixed(1)}%`)
          .fontSize(17).fontWeight(FontWeight.Bold)
          .fontColor($r('app.color.hold'));
      }
      .width('100%');
      Text(`上月完成 ${this.tier?.['last_month_completed'] ?? 0} 单 · ` +
        `本月已完成 ${this.tier?.['this_month_completed'] ?? 0} 单`)
        .fontSize(12).lineHeight(19)
        .fontColor($r('app.color.ink_muted')).width('100%');
      Text('每月 1 日按上月单量自动重算,只降不升;5% 永远是上限')
        .fontSize(11).fontColor($r('app.color.ink_muted')).width('100%');
    }
    .width('100%').padding(14)
    .backgroundColor($r('app.color.surface')).borderRadius(12);
  }

  @Builder
  private todayCard() {
    Column({ space: 4 }) {
      Text('今天').fontSize(13).fontWeight(FontWeight.Medium)
        .fontColor($r('app.color.ink')).width('100%');
      this.row('菜品流水', yuan(this.todayStat()?.food_cents ?? 0),
        $r('app.color.ink'));
      this.row('平台佣金', `-${yuan(this.todayStat()?.commission_cents ?? 0)}`,
        $r('app.color.hold'));
      Divider().color($r('app.color.line')).margin({ top: 6, bottom: 6 });
      this.row(`今日实收 · ${this.todayStat()?.order_count ?? 0} 单`,
        yuan(this.todayStat()?.net_cents ?? 0), $r('app.color.earn'), true);
    }
    .width('100%').padding(14)
    .backgroundColor($r('app.color.surface')).borderRadius(12);
  }

  build() {
    Column() {
      Row({ space: 10 }) {
        Text('对账')
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
        // 拉失败就说清楚并给重试 —— 转个没头的圈,商家只能杀进程重开
        Column({ space: 12 }) {
          Text('对账数据没能加载出来')
            .fontSize(15).fontColor($r('app.color.ink'));
          Text(this.errorText)
            .fontSize(13).fontColor($r('app.color.ink_muted'))
            .textAlign(TextAlign.Center);
          Button('重试').height(40).width(130)
            .backgroundColor($r('app.color.brand'))
            .onClick(() => { this.load(); });
        }
        .layoutWeight(1).justifyContent(FlexAlign.Center).padding(30);
      } else {
        Scroll() {
          Column({ space: 12 }) {
            if (this.wallet !== null) {
              this.walletCard(this.wallet as Wallet);
            }
            if (this.tier !== null) {
              this.tierCard();
            }
            this.todayCard();

            // ---- 按日账单 ----
            Column({ space: 0 }) {
              Text('按日账单 · 近 30 天')
                .fontSize(13).fontWeight(FontWeight.Medium)
                .fontColor($r('app.color.ink'))
                .width('100%').margin({ bottom: 8 });
              if (this.daily.length === 0) {
                Text('还没有入账记录\n订单完成后会出现在这里')
                  .fontSize(13).lineHeight(20)
                  .fontColor($r('app.color.ink_muted'))
                  .textAlign(TextAlign.Center).width('100%')
                  .padding({ top: 20, bottom: 20 });
              } else {
                ForEach(this.daily, (d: DayStat) => {
                  Row() {
                    Column({ space: 2 }) {
                      Text(d.day).fontSize(14)
                        .fontColor($r('app.color.ink'));
                      Text(`${d.order_count} 单 · 佣金 ${yuan(d.commission_cents)}`)
                        .fontSize(11).fontColor($r('app.color.ink_muted'));
                    }
                    .alignItems(HorizontalAlign.Start).layoutWeight(1);
                    Text(yuan(d.net_cents))
                      .fontSize(15).fontWeight(FontWeight.Medium)
                      .fontColor($r('app.color.ink'));
                  }
                  .width('100%').padding({ top: 10, bottom: 10 });
                  Divider().color($r('app.color.line'));
                }, (d: DayStat) => d.day);
              }
            }
            .width('100%').padding(14)
            .backgroundColor($r('app.color.surface')).borderRadius(12);

            // ---- 提现记录 ----
            if (this.withdrawals.length > 0) {
              Column({ space: 0 }) {
                Text('提现记录')
                  .fontSize(13).fontWeight(FontWeight.Medium)
                  .fontColor($r('app.color.ink'))
                  .width('100%').margin({ bottom: 8 });
                ForEach(this.withdrawals.slice(0, 20), (w: Withdrawal) => {
                  Row() {
                    Column({ space: 2 }) {
                      Text(yuan(w.amount_cents)).fontSize(14)
                        .fontColor($r('app.color.ink'));
                      Text(w.created_at.substring(0, 10))
                        .fontSize(11).fontColor($r('app.color.ink_muted'));
                    }
                    .alignItems(HorizontalAlign.Start).layoutWeight(1);
                    Text(w.status_label ?? w.status)
                      .fontSize(12).fontColor($r('app.color.ink_muted'));
                  }
                  .width('100%').padding({ top: 9, bottom: 9 });
                  Divider().color($r('app.color.line'));
                }, (w: Withdrawal) => `${w.id}`);
              }
              .width('100%').padding(14)
              .backgroundColor($r('app.color.surface')).borderRadius(12);
            }

            // 承诺:账目透明是唯一抄不走的差异点,写在对账页尾最合适
            Column({ space: 4 }) {
              Text('超级赞承诺')
                .fontSize(13).fontWeight(FontWeight.Bold)
                .fontColor($r('app.color.earn')).width('100%');
              Text('佣金只抽 5%,单量越大费率越低 · 每日 4:00 自动核账,' +
                '差一分钱系统报警 · 账目写进开源代码,欢迎监督')
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
