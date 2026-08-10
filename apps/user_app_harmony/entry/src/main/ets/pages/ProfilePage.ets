import { promptAction } from '@kit.ArkUI';
import { Session } from '../common/Session';

/**
 * 「我的」。
 *
 * 入口一律走路由回调,这一页自己不 push —— 谁能跳到哪集中在 Index 里,
 * 加页面只改一个地方。协议与注销移到设置页,这里保持一屏能看完。
 */
@Component
export struct ProfilePage {
  onNeedLogin: () => void = () => {};
  onOpenAddresses: () => void = () => {};
  onOpenTransparency: () => void = () => {};
  onOpenRoute: (route: string) => void = () => {};
  @State private version: number = 0;

  /** 手机号脱敏。屏幕会被别人看到,没必要把完整号码摆出来 */
  private maskedPhone(): string {
    const p: string = Session.get().userPhone;
    if (p.length !== 11) {
      return p;
    }
    return `${p.substring(0, 3)}****${p.substring(7)}`;
  }

  /** 需要登录才能进的页面,统一在这里挡一次 */
  private needLogin(route: string): void {
    if (!Session.get().isLoggedIn) {
      this.onNeedLogin();
      return;
    }
    this.onOpenRoute(route);
  }

  @Builder
  private entry(title: string, hint: string, onTap: () => void) {
    Row() {
      Column({ space: 2 }) {
        Text(title).fontSize(15).fontColor($r('app.color.ink'));
        if (hint.length > 0) {
          Text(hint).fontSize(11).fontColor($r('app.color.ink_muted'));
        }
      }
      .layoutWeight(1)
      .alignItems(HorizontalAlign.Start);
      Text('›').fontSize(18).fontColor($r('app.color.ink_muted'));
    }
    .width('100%')
    .padding({ left: 16, right: 16, top: 14, bottom: 14 })
    .backgroundColor($r('app.color.surface'))
    .onClick(onTap);
  }

  build() {
    Column({ space: 10 }) {
      Column({ space: 6 }) {
        if (Session.get().isLoggedIn) {
          Text(Session.get().userName.length > 0
            ? Session.get().userName : '超级赞用户')
            .fontSize(19).fontWeight(FontWeight.Bold)
            .fontColor($r('app.color.ink'));
          Text(this.maskedPhone())
            .fontSize(13).fontColor($r('app.color.ink_muted'));
        } else {
          Text('未登录').fontSize(19).fontWeight(FontWeight.Bold)
            .fontColor($r('app.color.ink'));
          Button('登录 / 注册')
            .height(38)
            .backgroundColor($r('app.color.brand'))
            .onClick(() => { this.onNeedLogin(); });
        }
      }
      .width('100%').padding(20).backgroundColor($r('app.color.surface'))
      .alignItems(HorizontalAlign.Start);

      Column({ space: 1 }) {
        this.entry('收货地址', '', () => {
          if (!Session.get().isLoggedIn) {
            this.onNeedLogin();
            return;
          }
          this.onOpenAddresses();
        });
        // 原生页,不再跳网页 —— 这是产品的招牌,不该借网页凑数
        this.entry('平台体检', '核账差错、可用率、赔付记录,难看也照实显示',
          () => { this.onOpenTransparency(); });
        this.entry('钱去哪了', '每 100 元怎么分,实算不是画饼',
          () => { this.onOpenRoute('moneyFlow'); });
        this.entry('我的收藏', '', () => { this.needLogin('favorites'); });
        this.entry('我的优惠券', '', () => { this.needLogin('coupons'); });
        this.entry('我的券包', '到店团购券', () => { this.needLogin('myVouchers'); });
        this.entry('到店团购', '核销才收 2%,未用全额退',
          () => { this.onOpenRoute('voucherDeals'); });
        this.entry('邀请好友', '奖励由商家出,不是平台补贴',
          () => { this.needLogin('invite'); });
        this.entry('实名认证', '只为买酒核验年龄',
          () => { this.needLogin('identity'); });
        this.entry('我的食安投诉', '处理进度与平台回复',
          () => { this.needLogin('foodSafetyRecords'); });
        this.entry('消息中心', '', () => { this.onOpenRoute('messages'); });
        this.entry('帮助中心', '配送范围 / 退款规则 / 常见问题',
          () => { this.onOpenRoute('help'); });
        this.entry('联系平台客服', '', () => { this.needLogin('support'); });
        this.entry('设置', '关于 / 协议 / 注销账号',
          () => { this.onOpenRoute('settings'); });
      }
      .width('100%');

      Column({ space: 6 }) {
        Text('我们只收商家 5%,封顶')
          .fontSize(14).fontColor($r('app.color.earn')).width('100%');
        Text('配送费一分不截留、全部归骑手,小费也是。' +
          '平台不卖数据、不做竞价排名、不收推广费。' +
          '每一单的钱怎么分,订单详情里可以逐项查。')
          .fontSize(12).fontColor($r('app.color.ink_muted')).width('100%');
      }
      .width('100%').padding(16).backgroundColor($r('app.color.surface'))
      .alignItems(HorizontalAlign.Start);

      if (Session.get().isLoggedIn) {
        Button('退出登录')
          .width('92%').height(44)
          .backgroundColor(Color.Transparent)
          .fontColor($r('app.color.ink_muted'))
          .onClick(async () => {
            await Session.get().clear();
            this.version += 1; // 触发重绘
            promptAction.showToast({ message: '已退出' });
          });
      }
    }
    .width('100%').height('100%')
    .backgroundColor($r('app.color.page'));
  }
}
