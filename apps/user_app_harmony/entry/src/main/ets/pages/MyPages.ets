import { common, Want } from '@kit.AbilityKit';
import { promptAction } from '@kit.ArkUI';
import { UserApi } from '../common/UserApi';
import { ApiException } from '../common/Api';
import { Session } from '../common/Session';
import { applyFontScale } from './Index';
import { Coupon, Merchant } from '../model/Models';
import { MerchantCard } from './MerchantCard';
import { yuan } from '../common/Money';

/** 我的收藏 */
@Component
export struct FavoritesPage {
  onOpenMerchant: (merchantId: number) => void = () => {};

  @State private list: Merchant[] = [];
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
      this.list = await this.api.favorites();
    } catch (e) {
      this.error = (e as ApiException).message;
    } finally {
      this.loading = false;
    }
  }

  build() {
    Column() {
      if (this.loading) {
        Column() { LoadingProgress().width(36).height(36); }
        .width('100%').layoutWeight(1).justifyContent(FlexAlign.Center);
      } else if (this.error.length > 0) {
        Column({ space: 12 }) {
          Text(this.error).fontSize(14).fontColor($r('app.color.ink_muted'));
          Button('重试').onClick(() => { this.load(); });
        }
        .width('100%').layoutWeight(1).justifyContent(FlexAlign.Center);
      } else if (this.list.length === 0) {
        Column() {
          Text('还没有收藏的店')
            .fontSize(14).fontColor($r('app.color.ink_muted'));
        }
        .width('100%').layoutWeight(1).justifyContent(FlexAlign.Center);
      } else {
        List({ space: 10 }) {
          ForEach(this.list, (m: Merchant) => {
            ListItem() { MerchantCard({ merchant: m }); }
            .onClick(() => { this.onOpenMerchant(m.id); });
          }, (m: Merchant) => `${m.id}`);
        }
        .width('100%').layoutWeight(1)
        .padding({ left: 12, right: 12, top: 12, bottom: 12 })
        .scrollBar(BarState.Off);
      }
    }
    .width('100%').height('100%').backgroundColor($r('app.color.page'));
  }
}

/**
 * 我的优惠券。
 *
 * **门槛要写清楚**。安卓端的券包只列面额和有效期,用户拿着一张
 * 「满 50 减 10」以为随便用,到结算页才发现用不了。
 */
@Component
export struct CouponsPage {
  @State private list: Coupon[] = [];
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
      this.list = await this.api.myCoupons();
    } catch (e) {
      this.error = (e as ApiException).message;
    } finally {
      this.loading = false;
    }
  }

  @Builder
  private card(c: Coupon) {
    Row() {
      Column({ space: 4 }) {
        Text(yuan(c.amount_cents))
          .fontSize(20).fontWeight(FontWeight.Bold)
          .fontColor(c.usable ? $r('app.color.brand') : $r('app.color.ink_muted'));
        Text(c.min_spend_cents > 0
          ? `满 ${yuan(c.min_spend_cents)} 可用` : '无门槛')
          .fontSize(12).fontColor($r('app.color.ink_muted'));
        // 店铺券只能在发券商家用,不写出来用户会以为哪家都行
        Text(c.funder === 'merchant' ? '仅限发券商家' : '平台券,不限店')
          .fontSize(11).fontColor($r('app.color.ink_muted'));
      }
      .layoutWeight(1).alignItems(HorizontalAlign.Start);
      Column({ space: 2 }) {
        Text(c.used ? '已使用' : (c.usable ? '可用' : '已过期'))
          .fontSize(12)
          .fontColor(c.usable ? $r('app.color.earn') : $r('app.color.ink_muted'));
        Text(c.expires_at.length > 10 ? c.expires_at.substring(0, 10) : c.expires_at)
          .fontSize(11).fontColor($r('app.color.ink_muted'));
      }
      .alignItems(HorizontalAlign.End);
    }
    .width('100%').padding(14).backgroundColor($r('app.color.surface'))
    .borderRadius(14);
  }

  build() {
    Column() {
      if (this.loading) {
        Column() { LoadingProgress().width(36).height(36); }
        .width('100%').layoutWeight(1).justifyContent(FlexAlign.Center);
      } else if (this.error.length > 0) {
        Column({ space: 12 }) {
          Text(this.error).fontSize(14).fontColor($r('app.color.ink_muted'));
          Button('重试').onClick(() => { this.load(); });
        }
        .width('100%').layoutWeight(1).justifyContent(FlexAlign.Center);
      } else if (this.list.length === 0) {
        Column() {
          Text('还没有优惠券').fontSize(14).fontColor($r('app.color.ink_muted'));
        }
        .width('100%').layoutWeight(1).justifyContent(FlexAlign.Center);
      } else {
        List({ space: 10 }) {
          ForEach(this.list, (c: Coupon) => {
            ListItem() { this.card(c); }
          }, (c: Coupon) => `${c.id}`);
        }
        .width('100%').layoutWeight(1)
        .padding({ left: 12, right: 12, top: 12, bottom: 12 })
        .scrollBar(BarState.Off);
      }
    }
    .width('100%').height('100%').backgroundColor($r('app.color.page'));
  }
}

/**
 * 消息中心:平台公告 + 未读提示。
 *
 * 安卓端这一页是只读快照且不可点进订单 —— 鸿蒙端至少要能点进去。
 */
@Component
export struct MessagesPage {
  @State private announcements: Record<string, Object>[] = [];
  @State private loading: boolean = true;

  private api: UserApi = new UserApi();

  async aboutToAppear(): Promise<void> {
    try {
      this.announcements = await this.api.announcements();
    } catch (e) {
      this.announcements = [];
    } finally {
      this.loading = false;
    }
  }

  private str(m: Record<string, Object>, key: string): string {
    const v: Object = m[key] ?? '';
    return typeof v === 'string' ? v : '';
  }

  build() {
    Column() {
      if (this.loading) {
        Column() { LoadingProgress().width(36).height(36); }
        .width('100%').layoutWeight(1).justifyContent(FlexAlign.Center);
      } else if (this.announcements.length === 0) {
        Column() {
          Text('暂时没有公告').fontSize(14).fontColor($r('app.color.ink_muted'));
        }
        .width('100%').layoutWeight(1).justifyContent(FlexAlign.Center);
      } else {
        List({ space: 10 }) {
          ForEach(this.announcements, (a: Record<string, Object>) => {
            ListItem() {
              Column({ space: 4 }) {
                Text(this.str(a, 'title'))
                  .fontSize(15).fontWeight(FontWeight.Medium)
                  .fontColor($r('app.color.ink')).width('100%');
                Text(this.str(a, 'content'))
                  .fontSize(13).fontColor($r('app.color.ink_muted')).width('100%');
                Text(this.str(a, 'created_at'))
                  .fontSize(11).fontColor($r('app.color.ink_muted')).width('100%');
              }
              .width('100%').padding(14).backgroundColor($r('app.color.surface'))
              .borderRadius(14).alignItems(HorizontalAlign.Start);
            }
          }, (a: Record<string, Object>) => this.str(a, 'id') + this.str(a, 'title'));
        }
        .width('100%').layoutWeight(1)
        .padding({ left: 12, right: 12, top: 12, bottom: 12 })
        .scrollBar(BarState.Off);
      }
    }
    .width('100%').height('100%').backgroundColor($r('app.color.page'));
  }
}

/** 帮助中心。FAQ 服务端下发,改文案不用发版;本地留一份兜底 */
@Component
export struct HelpPage {
  onOpenSupport: () => void = () => {};

  @State private faqs: Record<string, Object>[] = [];
  @State private loading: boolean = true;

  private api: UserApi = new UserApi();

  private static readonly FALLBACK: string[] = [
    '配送范围:目前只送 4 公里内,列表里出现的店都送得到',
    '退款:未出餐可全额退;出餐后走售后,平台会介入',
    '配送费:按距离算,一分不截留全部归骑手',
    '佣金:只收商家 5% 封顶,菜价里没有平台税',
  ];

  async aboutToAppear(): Promise<void> {
    try {
      this.faqs = await this.api.faq();
    } catch (e) {
      this.faqs = [];
    } finally {
      this.loading = false;
    }
  }

  private str(m: Record<string, Object>, key: string): string {
    const v: Object = m[key] ?? '';
    return typeof v === 'string' ? v : '';
  }

  build() {
    Scroll() {
      Column({ space: 10 }) {
        if (this.loading) {
          Row() { LoadingProgress().width(24).height(24); }.width('100%');
        } else if (this.faqs.length > 0) {
          ForEach(this.faqs, (f: Record<string, Object>) => {
            Column({ space: 4 }) {
              Text(this.str(f, 'question'))
                .fontSize(14).fontWeight(FontWeight.Medium)
                .fontColor($r('app.color.ink')).width('100%');
              Text(this.str(f, 'answer'))
                .fontSize(13).fontColor($r('app.color.ink_muted')).width('100%');
            }
            .width('100%').padding(14).backgroundColor($r('app.color.surface'))
            .borderRadius(12).alignItems(HorizontalAlign.Start);
          }, (f: Record<string, Object>) => this.str(f, 'question'));
        } else {
          // 服务端拉不到就用本地兜底,不要留一片白
          ForEach(HelpPage.FALLBACK, (t: string) => {
            Text(t)
              .fontSize(13).fontColor($r('app.color.ink')).width('100%')
              .padding(14).backgroundColor($r('app.color.surface')).borderRadius(12);
          }, (t: string) => t);
        }

        Button('还是没解决?联系平台客服')
          .width('100%').height(46)
          .backgroundColor($r('app.color.brand'))
          .onClick(() => { this.onOpenSupport(); });
      }
      .width('100%').padding(12).alignItems(HorizontalAlign.Start);
    }
    .width('100%').height('100%').backgroundColor($r('app.color.page'));
  }
}

/**
 * 客服工单。
 *
 * ⚠️ **这个功能的全部意义在回复。** 只存不回的话,这张表就是个许愿池,
 * 而且比没有更糟:提过一次没人理,以后连提都懒得提。
 */
@Component
export struct SupportPage {
  @State private tickets: Record<string, Object>[] = [];
  @State private draft: string = '';
  @State private loading: boolean = true;
  @State private sending: boolean = false;

  private api: UserApi = new UserApi();

  async aboutToAppear(): Promise<void> {
    await this.load();
  }

  private async load(): Promise<void> {
    try {
      this.tickets = await this.api.myTickets();
    } catch (e) {
      this.tickets = [];
    } finally {
      this.loading = false;
    }
  }

  private str(m: Record<string, Object>, key: string): string {
    const v: Object = m[key] ?? '';
    return typeof v === 'string' ? v : '';
  }

  private async submit(): Promise<void> {
    const text: string = this.draft.trim();
    if (text.length === 0 || this.sending) {
      return;
    }
    this.sending = true;
    try {
      const body: Record<string, Object> = { 'content': text };
      await this.api.createTicket(body);
      this.draft = '';
      await this.load();
      promptAction.showToast({ message: '已提交,平台会回复你' });
    } catch (e) {
      promptAction.showToast({ message: (e as ApiException).message });
    } finally {
      this.sending = false;
    }
  }

  build() {
    Column() {
      if (this.loading) {
        Column() { LoadingProgress().width(36).height(36); }
        .width('100%').layoutWeight(1).justifyContent(FlexAlign.Center);
      } else {
        List({ space: 10 }) {
          ForEach(this.tickets, (t: Record<string, Object>) => {
            ListItem() {
              Column({ space: 4 }) {
                Text(this.str(t, 'content'))
                  .fontSize(14).fontColor($r('app.color.ink')).width('100%');
                Text(this.str(t, 'status_label').length > 0
                  ? this.str(t, 'status_label') : this.str(t, 'status'))
                  .fontSize(12).fontColor($r('app.color.ink_muted')).width('100%');
                if (this.str(t, 'reply').length > 0) {
                  Text(`平台回复:${this.str(t, 'reply')}`)
                    .fontSize(13).fontColor($r('app.color.earn')).width('100%');
                }
              }
              .width('100%').padding(14).backgroundColor($r('app.color.surface'))
              .borderRadius(12).alignItems(HorizontalAlign.Start);
            }
          }, (t: Record<string, Object>) => this.str(t, 'id') + this.str(t, 'content'));
        }
        .width('100%').layoutWeight(1)
        .padding({ left: 12, right: 12, top: 12 })
        .scrollBar(BarState.Off);
      }

      Column({ space: 8 }) {
        TextArea({ placeholder: '说说遇到了什么', text: this.draft })
          .height(80)
          .onChange((v: string) => { this.draft = v; });
        Button(this.sending ? '提交中…' : '提交')
          .width('100%').height(44)
          .enabled(!this.sending && this.draft.trim().length > 0)
          .backgroundColor($r('app.color.brand'))
          .onClick(() => { this.submit(); });
      }
      .width('100%').padding(12).backgroundColor($r('app.color.surface'));
    }
    .width('100%').height('100%').backgroundColor($r('app.color.page'));
  }
}

/** 商家证照公示。**餐饮要同时公示营业执照和食品经营许可证**(总局令 123 号第十一条) */
@Component
export struct LicensesPage {
  merchantId: number = 0;

  @State private items: Record<string, Object>[] = [];
  @State private loading: boolean = true;

  private api: UserApi = new UserApi();

  async aboutToAppear(): Promise<void> {
    try {
      this.items = await this.api.merchantLicenses(this.merchantId);
    } catch (e) {
      this.items = [];
    } finally {
      this.loading = false;
    }
  }

  private str(m: Record<string, Object>, key: string): string {
    const v: Object = m[key] ?? '';
    return typeof v === 'string' ? v : '';
  }

  build() {
    Column() {
      if (this.loading) {
        Column() { LoadingProgress().width(36).height(36); }
        .width('100%').layoutWeight(1).justifyContent(FlexAlign.Center);
      } else if (this.items.length === 0) {
        Column() {
          Text('这家店还没有公示证照')
            .fontSize(14).fontColor($r('app.color.brand'));
        }
        .width('100%').layoutWeight(1).justifyContent(FlexAlign.Center);
      } else {
        List({ space: 10 }) {
          ForEach(this.items, (it: Record<string, Object>) => {
            ListItem() {
              Column({ space: 4 }) {
                Text(this.str(it, 'label'))
                  .fontSize(15).fontWeight(FontWeight.Medium)
                  .fontColor($r('app.color.ink')).width('100%');
                if (this.str(it, 'subject').length > 0) {
                  Text(`主体:${this.str(it, 'subject')}`)
                    .fontSize(12).fontColor($r('app.color.ink_muted')).width('100%');
                }
                if (this.str(it, 'no').length > 0) {
                  Text(`编号:${this.str(it, 'no')}`)
                    .fontSize(12).fontColor($r('app.color.ink_muted')).width('100%');
                }
              }
              .width('100%').padding(14).backgroundColor($r('app.color.surface'))
              .borderRadius(12).alignItems(HorizontalAlign.Start);
            }
          }, (it: Record<string, Object>) => this.str(it, 'kind'));
        }
        .width('100%').layoutWeight(1)
        .padding({ left: 12, right: 12, top: 12, bottom: 12 })
        .scrollBar(BarState.Off);
      }
    }
    .width('100%').height('100%').backgroundColor($r('app.color.page'));
  }
}

/**
 * 设置。
 *
 * **没有「检查更新」入口** —— 鸿蒙没有 APK 概念,华为商店也禁止绕过审核
 * 的应用内自升级,更新交给应用市场。安卓端为此专门做了 store 渠道包摘权限,
 * 鸿蒙端从一开始就不该有。
 */
@Component
export struct SettingsPage {
  onDeleted: () => void = () => {};

  @State private confirming: boolean = false;
  @State private countdown: number = 0;
  @State private elder: boolean = false;

  private timer: number = -1;

  async aboutToAppear(): Promise<void> {
    this.elder = await Session.get().elderMode();
  }

  private async toggleElder(on: boolean): Promise<void> {
    this.elder = on;
    await Session.get().setElderMode(on);
    const ctx = getContext(this) as common.UIAbilityContext;
    applyFontScale(ctx, on);
  }

  aboutToDisappear(): void {
    if (this.timer >= 0) {
      clearInterval(this.timer);
      this.timer = -1;
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

  /**
   * 账号注销。**三步走,不做成一个按钮点了就没** ——
   * 《个人信息保护法》和应用商店都要求有这个入口,但注销是不可逆的,
   * 给足反悔的机会才算负责
   */
  private startDelete(): void {
    this.confirming = true;
    this.countdown = 5;
    if (this.timer >= 0) {
      clearInterval(this.timer);
    }
    this.timer = setInterval(() => {
      this.countdown -= 1;
      if (this.countdown <= 0) {
        clearInterval(this.timer);
        this.timer = -1;
      }
    }, 1000);
  }

  build() {
    Scroll() {
      Column({ space: 10 }) {
        Column({ space: 6 }) {
          Text('关于')
            .fontSize(15).fontWeight(FontWeight.Medium)
            .fontColor($r('app.color.ink')).width('100%');
          Text('超级赞 · 鸿蒙原生版')
            .fontSize(13).fontColor($r('app.color.ink_muted')).width('100%');
          Text('陕ICP备2025064101号-5')
            .fontSize(12).fontColor($r('app.color.ink_muted')).width('100%');
          Text('线上运行的版本 = 开源仓库的 tag,更新说明与提交一字不差')
            .fontSize(11).fontColor($r('app.color.ink_muted')).width('100%');
        }
        .width('100%').padding(16).backgroundColor($r('app.color.surface'))
        .borderRadius(12).alignItems(HorizontalAlign.Start);

        Column({ space: 6 }) {
          Row() {
            Column({ space: 2 }) {
              Text('长辈版(大字)')
                .fontSize(15).fontColor($r('app.color.ink'));
              Text('全局字号放大到 1.4 倍,给看不清小字的人')
                .fontSize(11).fontColor($r('app.color.ink_muted'));
            }
            .layoutWeight(1).alignItems(HorizontalAlign.Start);
            Toggle({ type: ToggleType.Switch, isOn: this.elder })
              .onChange((on: boolean) => { this.toggleElder(on); });
          }
          .width('100%');
        }
        .width('100%').padding(16).backgroundColor($r('app.color.surface'))
        .borderRadius(12).alignItems(HorizontalAlign.Start);

        Column({ space: 1 }) {
          Text('用户协议')
            .fontSize(15).fontColor($r('app.color.ink')).width('100%')
            .padding(14).backgroundColor($r('app.color.surface'))
            .onClick(() => { this.openUrl('https://chaojizan.cc/legal/terms'); });
          Text('隐私政策')
            .fontSize(15).fontColor($r('app.color.ink')).width('100%')
            .padding(14).backgroundColor($r('app.color.surface'))
            .onClick(() => { this.openUrl('https://chaojizan.cc/legal/privacy'); });
        }
        .width('100%');

        Column({ space: 8 }) {
          Text('注销账号')
            .fontSize(15).fontWeight(FontWeight.Medium)
            .fontColor($r('app.color.ink')).width('100%');
          Text('注销后:订单记录、地址、优惠券、收藏全部删除,**不可恢复**。' +
            '有在途订单、未提现余额时无法注销。')
            .fontSize(12).fontColor($r('app.color.ink_muted')).width('100%');
          if (!this.confirming) {
            Button('我要注销')
              .width('100%').height(42)
              .backgroundColor(Color.Transparent)
              .fontColor($r('app.color.brand'))
              .onClick(() => { this.startDelete(); });
          } else {
            Button(this.countdown > 0
              ? `请再确认一次(${this.countdown}s)` : '确认注销')
              .width('100%').height(42)
              .enabled(this.countdown === 0)
              .backgroundColor($r('app.color.brand'))
              .onClick(() => {
                // 注销接口待接。**不做假的成功态** ——
                // 没删就是没删,不能让用户以为账号已经没了
                promptAction.showToast({
                  message: '注销接口待接入,请先联系平台客服',
                  duration: 3000,
                });
              });
          }
        }
        .width('100%').padding(16).backgroundColor($r('app.color.surface'))
        .borderRadius(12).alignItems(HorizontalAlign.Start);

        if (Session.get().isLoggedIn) {
          Button('退出登录')
            .width('100%').height(44)
            .backgroundColor(Color.Transparent)
            .fontColor($r('app.color.ink_muted'))
            .onClick(async () => {
              await Session.get().clear();
              promptAction.showToast({ message: '已退出' });
            });
        }
      }
      .width('100%').padding(12).alignItems(HorizontalAlign.Start);
    }
    .width('100%').height('100%').backgroundColor($r('app.color.page'));
  }
}
