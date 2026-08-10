import { promptAction } from '@kit.ArkUI';
import { MerchantApi } from '../common/MerchantApi';
import { ApiException } from '../common/Api';
import { Session } from '../common/Session';
import { PushChannel } from '../common/PushChannel';
import { Shop } from '../model/Models';

/**
 * 店铺。
 *
 * 只做**每天真会用到的那几项**:营业开关、临时歇业、公告、出餐承诺。
 * 满减/满赠/店铺券/员工这些低频设置这一版先不做 —— 商家一个月改一次,
 * 用安卓端或网页端就行,没必要为它们把这一页堆成两千行。
 *
 * ## 食安停业闸门
 *
 * 置位时商家自己开不回来(服务端也会 403)。**开关直接禁用**,
 * 比让他点了报错好 —— 报错他会以为是网络问题,反复点。
 */
@Component
export struct ShopPage {
  @Prop shop: Shop;
  onChanged: () => void = () => {};
  onOpenPrinter: () => void = () => {};
  onOpenFinance: () => void = () => {};
  onOpenReviews: () => void = () => {};
  onOpenVoucher: () => void = () => {};
  onOpenPurchases: () => void = () => {};
  onOpenCerts: () => void = () => {};
  onOpenAnalytics: () => void = () => {};
  onOpenMessages: () => void = () => {};
  onOpenPromoRules: () => void = () => {};
  onOpenOperations: () => void = () => {};
  onOpenDashboard: () => void = () => {};
  onOpenAppeal: () => void = () => {};
  onOpenRules: () => void = () => {};
  onOpenPromo: () => void = () => {};
  onOpenInvoice: () => void = () => {};
  onOpenChain: () => void = () => {};
  onOpenApplyment: () => void = () => {};
  onOpenStay: () => void = () => {};
  onLogout: () => void = () => {};

  @State private current: Shop = {} as Shop;
  @State private busy: boolean = false;
  @State private announcement: string = '';
  @State private showAnnouncement: boolean = false;

  private api: MerchantApi = new MerchantApi();

  aboutToAppear(): void {
    this.current = this.shop;
    this.announcement = this.shop.announcement ?? '';
  }

  private async setOpen(on: boolean): Promise<void> {
    this.busy = true;
    try {
      this.current = await this.api.setShopOpen(on);
      this.onChanged();
    } catch (e) {
      promptAction.showToast({ message: (e as ApiException).message });
    } finally {
      this.busy = false;
    }
  }

  /** 临时歇业:关店 + 到点自动恢复,区别于手动关店忘了开 */
  private async rest(hours: number): Promise<void> {
    this.busy = true;
    try {
      this.current = await this.api.restShop(hours);
      const until: string = this.current.closed_until ?? '';
      promptAction.showToast({
        message: until.length >= 16
            ? `已歇业,${until.substring(11, 16)} 自动恢复营业`
            : '已歇业,到点自动恢复',
      });
      this.onChanged();
    } catch (e) {
      promptAction.showToast({ message: (e as ApiException).message });
    } finally {
      this.busy = false;
    }
  }

  private async endRest(): Promise<void> {
    // 提前结束歇业 = 直接开店(服务端开店动作会清歇业标记)
    await this.setOpen(true);
  }

  private async saveAnnouncement(): Promise<void> {
    try {
      this.current = await this.api.updateShop(
          { announcement: this.announcement.trim() } as object);
      this.showAnnouncement = false;
      promptAction.showToast({ message: '公告已更新' });
      this.onChanged();
    } catch (e) {
      promptAction.showToast({ message: (e as ApiException).message });
    }
  }

  private async logout(): Promise<void> {
    await PushChannel.unbind();
    await Session.get().clear();
    this.onLogout();
  }

  @Builder
  private announcementSheet() {
    Column({ space: 12 }) {
      Text('店铺公告')
        .fontSize(17).fontWeight(FontWeight.Bold)
        .fontColor($r('app.color.ink')).width('100%');
      Text('顾客在店铺页最上面看到。写清楚出餐大概多久、有没有停售的菜')
        .fontSize(12).fontColor($r('app.color.ink_muted')).width('100%');
      TextArea({ placeholder: '例:今天备料充足,出餐约 15 分钟',
        text: this.announcement })
        .height(96)
        .onChange((v: string) => { this.announcement = v; });
      Row({ space: 10 }) {
        Button('取消')
          .layoutWeight(1).height(44)
          .backgroundColor($r('app.color.surface_alt'))
          .fontColor($r('app.color.ink'))
          .onClick(() => {
            this.showAnnouncement = false;
            this.announcement = this.current.announcement ?? '';
          });
        Button('保存')
          .layoutWeight(1).height(44)
          .backgroundColor($r('app.color.brand'))
          .onClick(() => { this.saveAnnouncement(); });
      }
      .width('100%');
    }
    .width('100%')
    .padding({ left: 18, right: 18, top: 18, bottom: 24 })
    .backgroundColor($r('app.color.surface'));
  }

  @Builder
  private entry(title: string, note: string, onTap: () => void) {
    Row({ space: 10 }) {
      Column({ space: 2 }) {
        Text(title).fontSize(15).fontColor($r('app.color.ink'));
        Text(note).fontSize(12).fontColor($r('app.color.ink_muted'));
      }
      .alignItems(HorizontalAlign.Start).layoutWeight(1);
      Text('›').fontSize(18).fontColor($r('app.color.ink_faint'));
    }
    .width('100%').padding({ top: 12, bottom: 12 })
    .onClick(onTap);
  }

  build() {
    Column() {
      Row({ space: 10 }) {
        Text('店铺')
          .fontSize(17).fontWeight(FontWeight.Bold)
          .fontColor($r('app.color.ink')).layoutWeight(1);
      }
      .width('100%')
      .padding({ left: 14, right: 14, top: 10, bottom: 10 })
      .backgroundColor($r('app.color.surface'));

      Scroll() {
        Column({ space: 12 }) {
          // ---- 营业状态 ----
          Column({ space: 10 }) {
            Row({ space: 10 }) {
              Column({ space: 2 }) {
                Text(this.current.name)
                  .fontSize(16).fontWeight(FontWeight.Bold)
                  .fontColor($r('app.color.ink'));
                Text(this.current.address).fontSize(12)
                  .fontColor($r('app.color.ink_muted'))
                  .maxLines(1)
                  .textOverflow({ overflow: TextOverflow.Ellipsis });
              }
              .alignItems(HorizontalAlign.Start).layoutWeight(1);
              Toggle({ type: ToggleType.Switch,
                isOn: this.current.is_open })
                .selectedColor($r('app.color.brand'))
                // 食安停业时商家自己开不回来,直接禁用比让他点了报错好
                .enabled(!this.busy
                  && this.current.food_safety_hold !== true)
                .onChange((on: boolean) => { this.setOpen(on); });
            }
            .width('100%');

            if (this.current.food_safety_hold === true) {
              Text('食安停业中:这不是你关的,也开不回来。处理完食安问题后由平台解除。')
                .fontSize(12).lineHeight(19)
                .fontColor($r('app.color.danger')).width('100%');
            }

            if ((this.current.closed_until ?? '').length > 0) {
              Row({ space: 10 }) {
                Text(`歇业中,${(this.current.closed_until as string).substring(11, 16)} 自动恢复`)
                  .fontSize(13).fontColor($r('app.color.hold'))
                  .layoutWeight(1);
                Button('现在就开')
                  .fontSize(12).height(30).padding({ left: 12, right: 12 })
                  .backgroundColor($r('app.color.surface_alt'))
                  .fontColor($r('app.color.ink'))
                  .onClick(() => { this.endRest(); });
              }
              .width('100%');
            } else if (this.current.is_open) {
              Row({ space: 8 }) {
                Text('临时歇业')
                  .fontSize(13).fontColor($r('app.color.ink_muted'))
                  .layoutWeight(1);
                ForEach([1, 2], (h: number) => {
                  Button(`${h} 小时`)
                    .fontSize(12).height(30).padding({ left: 12, right: 12 })
                    .backgroundColor($r('app.color.surface_alt'))
                    .fontColor($r('app.color.ink'))
                    .enabled(!this.busy)
                    .onClick(() => { this.rest(h); });
                }, (h: number) => `r${h}`);
              }
              .width('100%');
            }
          }
          .width('100%').padding(14)
          .backgroundColor($r('app.color.surface')).borderRadius(12);

          // ---- 常用入口 ----
          Column({ space: 0 }) {
            this.entry('公告',
              (this.current.announcement ?? '').length > 0
                ? (this.current.announcement as string) : '未设置',
              () => { this.showAnnouncement = true; });
            Divider().color($r('app.color.line'));
            this.entry('打印设置', '蓝牙小票机与云打印',
              () => { this.onOpenPrinter(); });
            Divider().color($r('app.color.line'));
            this.entry('对账', '钱包、提现、按日账单',
              () => { this.onOpenFinance(); });
            Divider().color($r('app.color.line'));
            this.entry('评价与售后', '差评回复、退款处理',
              () => { this.onOpenReviews(); });
            Divider().color($r('app.color.line'));
            this.entry('消息中心', '平台公告与通知',
              () => { this.onOpenMessages(); });
          }
          .width('100%').padding({ left: 14, right: 14 })
          .backgroundColor($r('app.color.surface')).borderRadius(12);

          // ---- 合规与经营 ----
          Column({ space: 0 }) {
            this.entry('团购券核销', '扫码或手输券码,核销才收 2%',
              () => { this.onOpenVoucher(); });
            Divider().color($r('app.color.line'));
            this.entry('进货台账', '出事时唯一能自证清白的东西',
              () => { this.onOpenPurchases(); });
            Divider().color($r('app.color.line'));
            this.entry('资质', '食品经营许可证、从业人员健康证',
              () => { this.onOpenCerts(); });
            Divider().color($r('app.color.line'));
            this.entry('经营分析', '时段、客单价、复购、老客召回(仅自己可见)',
              () => { this.onOpenAnalytics(); });
          }
          .width('100%').padding({ left: 14, right: 14 })
          .backgroundColor($r('app.color.surface')).borderRadius(12);

          // ---- 经营与营销 ----
          Column({ space: 0 }) {
            this.entry('经营看板', '近 8 周趋势、顾客流失在哪一环',
              () => { this.onOpenDashboard(); });
            Divider().color($r('app.color.line'));
            this.entry('营销规则', '满减 / 满赠 / 店铺券',
              () => { this.onOpenPromoRules(); });
            Divider().color($r('app.color.line'));
            this.entry('经营设置', '店员、节假日、出餐承诺、明厨亮灶',
              () => { this.onOpenOperations(); });
            Divider().color($r('app.color.line'));
            this.entry('推广物料', '店铺专属码与海报(平台出物料不出钱)',
              () => { this.onOpenPromo(); });
            Divider().color($r('app.color.line'));
            this.entry('连锁门店', '多店汇总与品牌',
              () => { this.onOpenChain(); });
            Divider().color($r('app.color.line'));
            this.entry('住宿', '客房订单、房型、日历',
              () => { this.onOpenStay(); });
          }
          .width('100%').padding({ left: 14, right: 14 })
          .backgroundColor($r('app.color.surface')).borderRadius(12);

          // ---- 钱与规则 ----
          Column({ space: 0 }) {
            this.entry('收款进件', '走服务商模式,钱由微信直接结给你',
              () => { this.onOpenApplyment(); });
            Divider().color($r('app.color.line'));
            this.entry('开发票', '平台服务费的发票',
              () => { this.onOpenInvoice(); });
            Divider().color($r('app.color.line'));
            this.entry('判责申诉', '对判你责任的售后和差评申诉(72 小时内)',
              () => { this.onOpenAppeal(); });
            Divider().color($r('app.color.line'));
            this.entry('平台规则', '每个数字都从代码里的常量算出来',
              () => { this.onOpenRules(); });
          }
          .width('100%').padding({ left: 14, right: 14 })
          .backgroundColor($r('app.color.surface')).borderRadius(12);

          // ---- 后台通道状态。**照实说** ----
          Column({ space: 6 }) {
            Text('新单提醒')
              .fontSize(13).fontWeight(FontWeight.Medium)
              .fontColor($r('app.color.ink')).width('100%');
            Text(PushChannel.ready
              ? '推送已开启:应用退到后台、锁屏也能收到新单提醒。'
              : '推送还没接通:**应用退到后台可能收不到新单**,'
                + '营业时请把应用放在前台,屏幕会自动常亮。')
              .fontSize(12).lineHeight(19)
              .fontColor(PushChannel.ready
                ? $r('app.color.earn') : $r('app.color.danger'))
              .width('100%');
          }
          .width('100%').padding(14)
          .backgroundColor($r('app.color.surface')).borderRadius(12);

          Button('退出登录')
            .width('100%').height(44)
            .backgroundColor($r('app.color.surface'))
            .fontColor($r('app.color.danger'))
            .onClick(() => { this.logout(); });

          Blank().height(30);
        }
        .width('100%').padding(12);
      }
      .layoutWeight(1).scrollBar(BarState.Off);
    }
    .width('100%').height('100%')
    .backgroundColor($r('app.color.page'))
    .bindSheet($$this.showAnnouncement, this.announcementSheet(),
      { height: 300, dragBar: false });
  }
}
