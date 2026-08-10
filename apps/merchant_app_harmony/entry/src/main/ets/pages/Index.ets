import { common } from '@kit.AbilityKit';
import { promptAction, window } from '@kit.ArkUI';
import { Session } from '../common/Session';
import { Api, ApiException } from '../common/Api';
import { MerchantApi } from '../common/MerchantApi';
import { PushChannel } from '../common/PushChannel';
import { LoginPage } from './LoginPage';
import { OrdersPage } from './OrdersPage';
import { OrderDetailPage } from './OrderDetailPage';
import { DishesPage } from './DishesPage';
import { FinancePage } from './FinancePage';
import { ReviewsPage } from './ReviewsPage';
import { PrinterPage } from './PrinterPage';
import { ShopPage } from './ShopPage';
import { VoucherPage } from './VoucherPage';
import { PurchasesPage } from './PurchasesPage';
import { CertsPage } from './CertsPage';
import { AnalyticsPage } from './AnalyticsPage';
import { MessagesPage } from './MessagesPage';
import { RiderTrackPage, SelfDeliveryPage } from './DeliveryPages';
import { DashboardPage } from './DashboardPage';
import { PromoRulesPage } from './PromoRulesPage';
import { OperationsPage } from './OperationsPage';
import { AppealPage, PromoPage, RulesPage } from './SupportPages';
import { ChainPage, InvoicePage } from './MorePages';
import { OnboardingPage } from './OnboardingPage';
import { ApplymentPage } from './ApplymentPage';
import { StayPages } from './StayPages';
import { MerchantOrder, Shop } from '../model/Models';

/** 隐私政策版本。与 Flutter 端 legal.dart 的 kLegalVersion 保持一致 */
const LEGAL_VERSION: string = '2026-07-28';

/**
 * 应用根页面。
 *
 * ## 隐私门在最外层
 *
 * 同意之前**一个网络请求都不许发**。顺序是:读本地会话(不联网)→
 * 没同意过就先弹隐私门 → 同意之后才进主界面。同意前发一个请求就算
 * 「未经同意收集」,是工信部通报和商店驳回的头号事由。
 *
 * ## 冷启动的接口顺序不能反
 *
 * **先 `myBrand()` 再 `myShop()`。** 连锁账号在没选门店时
 * `/merchants/me` 是 404(后端不猜是哪家),顺序反了会把连锁老板
 * 一路带进「还没开店」的入驻引导 —— 他有二十家店,却被告知还没开店。
 *
 * ## 屏幕常亮
 *
 * 进接单页就把屏幕钉住。商家手机插电放柜台,这一条比什么都实用,
 * 而且**不需要任何权限** —— 是鸿蒙这边为数不多的白拿。
 */
@Entry
@Component
struct Index {
  @State private booted: boolean = false;
  @State private agreed: boolean = false;
  @State private loggedIn: boolean = false;
  @State private shop: Shop | null = null;
  @State private shops: Shop[] = [];
  @State private bootError: string = '';
  @State private detail: MerchantOrder | null = null;
  @State private showShopPicker: boolean = false;

  /**
   * 底部导航:0 订单 / 1 菜品 / 2 对账 / 3 店铺。
   *
   * 和安卓端同一套顺序 —— 商家换机器时肌肉记忆能接上,
   * 而"接单"永远在第一个。
   */
  @State private tab: number = 0;

  /** 二级页。空串 = 停在 tab 上 */
  @State private sub: string = '';

  /** 配送类二级页要带着那一单 */
  @State private tracking: MerchantOrder | null = null;

  private api: MerchantApi = new MerchantApi();

  async aboutToAppear(): Promise<void> {
    const ctx = getContext(this) as common.UIAbilityContext;
    const session: Session = Session.get();
    await session.init(ctx);

    Api.get().onUnauthorized = () => {
      this.loggedIn = false;
      this.shop = null;
      this.detail = null;
    };

    const v: string = await session.agreedPrivacyVersion();
    this.agreed = v === LEGAL_VERSION;
    this.loggedIn = session.isLoggedIn;
    // 上次选中的门店先恢复上,免得冷启动时第一批请求没带 X-Shop-Id
    this.api.shopId = session.shopId;
    this.booted = true;

    if (this.agreed && this.loggedIn) {
      await this.afterLogin();
    }
  }

  /** 同意隐私之后才能碰网络 */
  private async agree(): Promise<void> {
    await Session.get().agreePrivacy(LEGAL_VERSION);
    this.agreed = true;
    // 推送要等这一步之后才初始化 —— 它会读设备信息
    await PushChannel.setup();
    if (this.loggedIn) {
      await this.afterLogin();
    }
  }

  private async afterLogin(): Promise<void> {
    this.loggedIn = true;
    await PushChannel.bindUser(Session.get().userId);
    await this.loadShop();
    this.keepScreenOn(true);
  }

  /**
   * 冷启动拉店铺。
   *
   * ⚠️ 顺序:**先品牌后门店**。理由见类注释。
   */
  private async loadShop(): Promise<void> {
    try {
      const brand: Record<string, Object> = await this.api.myBrand();
      const raw: Object | undefined = brand['shops'];
      const list: Shop[] = (raw === undefined ? [] : raw) as Shop[];
      this.shops = list;

      if (list.length === 0) {
        // 还没开店:走入驻引导(这一批先给个说明,入驻页在 P1)
        this.shop = null;
        this.bootError = '';
        return;
      }
      // 上次选的店还在就用它,不在了(被删/被移出品牌)就退回第一家
      const saved: number | null = Session.get().shopId;
      const stillThere: boolean =
          saved !== null && list.some((s: Shop) => s.id === saved);
      const target: number = stillThere ? (saved as number) : list[0].id;
      await this.selectShop(target, false);
      this.bootError = '';
    } catch (e) {
      // **不能停在转圈上**:商家会以为应用卡了,反复杀进程重开
      this.bootError = (e as ApiException).message;
    }
  }

  /**
   * 切店。
   *
   * ⚠️ **一次切干净**:请求头的 `X-Shop-Id`、持久化的门店 id、店铺对象、
   * 详情页。漏掉任何一处就是「切到二店,屏幕上还是总店的单」,
   * 而商家会照着总店的单去二店备餐。
   *
   * WebSocket 和订单列表由 OrdersPage 负责 —— 它靠 `shop` 这个 @Prop
   * 变化触发重建,所以这里换掉 `shop` 就够了。
   */
  private async selectShop(id: number, notify: boolean): Promise<void> {
    this.api.shopId = id;
    await Session.get().saveShopId(id);
    this.detail = null;
    try {
      this.shop = await this.api.myShop();
      if (notify) {
        promptAction.showToast({ message: `已切换到「${this.shop.name}」` });
      }
    } catch (e) {
      this.bootError = (e as ApiException).message;
    }
  }

  /** 接单页屏幕常亮。商家手机插电放柜台,这一条不需要任何权限 */
  private keepScreenOn(on: boolean): void {
    try {
      window.getLastWindow(getContext(this)).then((w: window.Window) => {
        w.setWindowKeepScreenOn(on);
      });
    } catch (_) {
      // 拿不到窗口就算了,不影响接单
    }
  }

  // ---------- 界面 ----------

  @Builder
  private privacyGate() {
    Column({ space: 14 }) {
      Blank().height(60);
      Text('超级赞商家')
        .fontSize(26).fontWeight(FontWeight.Bold)
        .fontColor($r('app.color.ink'));
      Text('佣金只抽 5%,每一笔账都可查')
        .fontSize(14).fontColor($r('app.color.earn'));
      Blank().height(20);
      Text('在开始之前,请阅读并同意《商家服务协议》与《隐私政策》。\n\n' +
        '同意之前我们不会发起任何网络请求,也不会读取设备信息。')
        .fontSize(13).lineHeight(22)
        .fontColor($r('app.color.ink_muted'));
      Blank().layoutWeight(1);
      Button('同意并继续')
        .width('100%').height(48)
        .backgroundColor($r('app.color.brand'))
        .onClick(() => { this.agree(); });
      Button('不同意')
        .width('100%').height(44)
        .backgroundColor(Color.Transparent)
        .fontColor($r('app.color.ink_muted'))
        .onClick(() => {
          promptAction.showToast({ message: '不同意就没法接单,理解一下' });
        });
      Blank().height(20);
    }
    .width('100%').height('100%')
    .padding({ left: 24, right: 24 })
    .backgroundColor($r('app.color.surface'));
  }

  @Builder
  private bootFailed() {
    Column({ space: 12 }) {
      Text('店铺信息没能加载出来')
        .fontSize(16).fontColor($r('app.color.ink'));
      Text(this.bootError)
        .fontSize(13).fontColor($r('app.color.ink_muted'))
        .textAlign(TextAlign.Center);
      Button('重试')
        .height(42).width(140)
        .backgroundColor($r('app.color.brand'))
        .onClick(() => {
          this.bootError = '';
          this.loadShop();
        });
    }
    .width('100%').height('100%')
    .justifyContent(FlexAlign.Center)
    .padding(30)
    .backgroundColor($r('app.color.page'));
  }



  @Builder
  private shopPicker() {
    Column({ space: 0 }) {
      Text('切换门店')
        .fontSize(17).fontWeight(FontWeight.Bold)
        .fontColor($r('app.color.ink'))
        .width('100%')
        .padding({ left: 18, top: 18, bottom: 10 });
      ForEach(this.shops, (s: Shop) => {
        Row() {
          Column({ space: 2 }) {
            Text(s.name).fontSize(15).fontColor($r('app.color.ink'));
            Text(s.address).fontSize(12)
              .fontColor($r('app.color.ink_muted'))
              .maxLines(1).textOverflow({ overflow: TextOverflow.Ellipsis });
          }
          .alignItems(HorizontalAlign.Start).layoutWeight(1);
          if (this.shop !== null && this.shop.id === s.id) {
            Text('当前').fontSize(12).fontColor($r('app.color.brand'));
          }
        }
        .width('100%')
        .padding({ left: 18, right: 18, top: 12, bottom: 12 })
        .onClick(() => {
          this.showShopPicker = false;
          this.selectShop(s.id, true);
        });
      }, (s: Shop) => `${s.id}`);
      Blank().height(20);
    }
    .width('100%')
    .backgroundColor($r('app.color.surface'));
  }

  @Builder
  private tabBar() {
    Row() {
      ForEach([0, 1, 2, 3], (i: number) => {
        Column({ space: 2 }) {
          Text(i === 0 ? '📋' : i === 1 ? '🍜' : i === 2 ? '📊' : '🏪')
            .fontSize(19);
          Text(i === 0 ? '订单' : i === 1 ? '菜品' : i === 2 ? '对账' : '店铺')
            .fontSize(11)
            .fontColor(this.tab === i
              ? $r('app.color.brand') : $r('app.color.ink_muted'));
        }
        .layoutWeight(1)
        .onClick(() => {
          this.tab = i;
          this.sub = '';
        });
      }, (i: number) => `tab${i}`);
    }
    .width('100%')
    .padding({ top: 6, bottom: 10 })
    .backgroundColor($r('app.color.surface'));
  }

  /** 主界面。[shop] 保证非空 —— 调用处已经判过了 */
  @Builder
  private main(shop: Shop) {
    if (this.tracking !== null && this.sub === 'rider') {
      RiderTrackPage({
        order: this.tracking,
        shop: shop,
        onBack: () => { this.sub = ''; this.tracking = null; },
      });
    } else if (this.tracking !== null && this.sub === 'selfmap') {
      SelfDeliveryPage({
        order: this.tracking,
        shop: shop,
        onBack: () => { this.sub = ''; this.tracking = null; },
      });
    } else if (this.detail !== null) {
      OrderDetailPage({
        order: this.detail,
        shopName: shop.name,
        onBack: () => { this.detail = null; },
        onChanged: () => { this.detail = null; },
        onTrackRider: (o: MerchantOrder) => {
          this.tracking = o;
          this.sub = 'rider';
        },
        onSelfDeliveryMap: (o: MerchantOrder) => {
          this.tracking = o;
          this.sub = 'selfmap';
        },
      });
    } else if (this.sub === 'printer') {
      PrinterPage({
        shopName: shop.name,
        onBack: () => { this.sub = ''; },
      });
    } else if (this.sub === 'reviews') {
      ReviewsPage({ onBack: () => { this.sub = ''; } });
    } else if (this.sub === 'voucher') {
      VoucherPage({ onBack: () => { this.sub = ''; } });
    } else if (this.sub === 'purchases') {
      PurchasesPage({ onBack: () => { this.sub = ''; } });
    } else if (this.sub === 'certs') {
      CertsPage({ shop: shop, onBack: () => { this.sub = ''; } });
    } else if (this.sub === 'analytics') {
      AnalyticsPage({ onBack: () => { this.sub = ''; } });
    } else if (this.sub === 'messages') {
      MessagesPage({ onBack: () => { this.sub = ''; } });
    } else if (this.sub === 'dashboard') {
      DashboardPage({ onBack: () => { this.sub = ''; } });
    } else if (this.sub === 'promorules') {
      PromoRulesPage({
        shop: shop,
        onBack: () => { this.sub = ''; },
        onChanged: () => { this.loadShop(); },
      });
    } else if (this.sub === 'operations') {
      OperationsPage({
        shop: shop,
        onBack: () => { this.sub = ''; },
        onChanged: () => { this.loadShop(); },
      });
    } else if (this.sub === 'appeal') {
      AppealPage({ onBack: () => { this.sub = ''; } });
    } else if (this.sub === 'rules') {
      RulesPage({ onBack: () => { this.sub = ''; } });
    } else if (this.sub === 'promo') {
      PromoPage({ shop: shop, onBack: () => { this.sub = ''; } });
    } else if (this.sub === 'invoice') {
      InvoicePage({ onBack: () => { this.sub = ''; } });
    } else if (this.sub === 'chain') {
      ChainPage({
        shops: this.shops,
        onBack: () => { this.sub = ''; },
        onChanged: () => { this.loadShop(); },
      });
    } else if (this.sub === 'applyment') {
      ApplymentPage({ onBack: () => { this.sub = ''; } });
    } else if (this.sub === 'stay') {
      StayPages({ onBack: () => { this.sub = ''; } });
    } else {
      Column() {
        // 店名条:连锁商家点这里切店。单店时不显示箭头,免得他去点
        if (this.tab === 0) {
          Row({ space: 6 }) {
            Text(shop.name)
              .fontSize(17).fontWeight(FontWeight.Bold)
              .fontColor($r('app.color.ink'));
            if (this.shops.length > 1) {
              Text('▾').fontSize(14).fontColor($r('app.color.ink_muted'));
            }
            Blank();
            Text(shop.is_open ? '营业中' : '已打烊')
              .fontSize(13)
              .fontColor(shop.is_open
                ? $r('app.color.earn') : $r('app.color.ink_muted'));
          }
          .width('100%')
          .padding({ left: 14, right: 14, top: 12, bottom: 10 })
          .backgroundColor($r('app.color.surface'))
          .onClick(() => {
            if (this.shops.length > 1) {
              this.showShopPicker = true;
            }
          });
        }

        // 订单页**常驻**:它持有 WebSocket、轮询和催单定时器,
        // 切到别的页签就销毁的话,商家在看菜单时就听不到单了 ——
        // 而看菜单恰恰是午高峰前最常做的事
        Stack() {
          OrdersPage({
            shop: shop,
            onOpenOrder: (o: MerchantOrder) => { this.detail = o; },
          })
            .visibility(this.tab === 0 ? Visibility.Visible : Visibility.None);
          if (this.tab === 1) {
            DishesPage();
          }
          if (this.tab === 2) {
            FinancePage();
          }
          if (this.tab === 3) {
            ShopPage({
              shop: shop,
              onChanged: () => { this.loadShop(); },
              onOpenPrinter: () => { this.sub = 'printer'; },
              onOpenFinance: () => { this.tab = 2; },
              onOpenReviews: () => { this.sub = 'reviews'; },
              onOpenVoucher: () => { this.sub = 'voucher'; },
              onOpenPurchases: () => { this.sub = 'purchases'; },
              onOpenCerts: () => { this.sub = 'certs'; },
              onOpenAnalytics: () => { this.sub = 'analytics'; },
              onOpenMessages: () => { this.sub = 'messages'; },
              onOpenDashboard: () => { this.sub = 'dashboard'; },
              onOpenPromoRules: () => { this.sub = 'promorules'; },
              onOpenOperations: () => { this.sub = 'operations'; },
              onOpenAppeal: () => { this.sub = 'appeal'; },
              onOpenRules: () => { this.sub = 'rules'; },
              onOpenPromo: () => { this.sub = 'promo'; },
              onOpenInvoice: () => { this.sub = 'invoice'; },
              onOpenChain: () => { this.sub = 'chain'; },
              onOpenApplyment: () => { this.sub = 'applyment'; },
              onOpenStay: () => { this.sub = 'stay'; },
              onLogout: () => {
                this.loggedIn = false;
                this.shop = null;
                this.tab = 0;
              },
            });
          }
        }
        .layoutWeight(1).width('100%');

        this.tabBar();
      }
      .width('100%').height('100%');
    }
  }

  build() {
    Stack() {
      if (!this.booted) {
        Column() {
          LoadingProgress().width(40).height(40);
        }
        .width('100%').height('100%')
        .justifyContent(FlexAlign.Center)
        .backgroundColor($r('app.color.page'));
      } else if (!this.agreed) {
        this.privacyGate();
      } else if (!this.loggedIn) {
        LoginPage({ onLoggedIn: () => { this.afterLogin(); } });
      } else if (this.bootError.length > 0) {
        this.bootFailed();
      } else if (this.shop === null) {
        // 名下没店:直接进入驻,不是给一句「去别的端办」
        OnboardingPage({ onDone: () => { this.loadShop(); } });
      } else {
        // 非空值当参数传进 @Builder,不指望 ArkTS 对 `this.xxx` 做可空收窄 ——
        // 那个收窄在 build 里不保险,而这里错了就是整页起不来
        this.main(this.shop as Shop);
      }
    }
    .width('100%').height('100%')
    .bindSheet($$this.showShopPicker, this.shopPicker(), {
      height: SheetSize.FIT_CONTENT,
      dragBar: true,
    });
  }
}
