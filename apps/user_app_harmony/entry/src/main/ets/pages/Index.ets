import { common, Want } from '@kit.AbilityKit';
import { promptAction } from '@kit.ArkUI';
import { Session } from '../common/Session';
import { Api } from '../common/Api';
import { MainTabs } from './MainTabs';
import { LoginPage } from './LoginPage';
import { MerchantPage } from './MerchantPage';
import { CheckoutPage } from './CheckoutPage';
import { OrderDetailPage } from './OrderDetailPage';
import { SearchPage } from './SearchPage';
import { CategoryPage } from './CategoryPage';
import { AddressEditPage, AddressListPage } from './AddressPages';
import { ChatPage } from './ChatPage';
import { AfterSalePage } from './AfterSalePage';
import { ReviewPage } from './ReviewPage';
import { TransparencyPage } from './TransparencyPage';
import { MoneyFlowPage } from './MoneyFlowPage';
import { CouponsPage, FavoritesPage, HelpPage, LicensesPage, MessagesPage,
  SettingsPage, SupportPage } from './MyPages';
import { MyVouchersPage, VoucherDealsPage, VoucherDetailPage } from './VoucherPages';
import { ErrandPage } from './ErrandPage';
import { HotelListPage, StayAfterPage, StayOrdersPage } from './StayPages';
import { HotelDetailPage } from './StayCheckout';
import { ShareCardPage } from './ShareCard';
import { GroupCartPage } from './GroupCartPage';
import { IdentityPage, InvitePage } from './InviteIdentity';
import { AppendOrderPage, FoodSafetyRecordsPage } from './AppendOrderPage';
import { AddressEditParam, AddressListParam, CategoryParam, ChatParam,
  CheckoutParam, LicensesParam, MerchantParam, OrderActionParam,
  AppendOrderParam, GroupCartParam, HotelDetailParam, HotelsParam,
  OrderDetailParam, Routes,
  SearchParam, ShareCardParam,
  VoucherDetailParam } from '../model/Params';
import { Address, Merchant, Order, VoucherDeal } from '../model/Models';
import { CartLine } from '../common/Cart';

/**
 * 应用长辈版字体缩放。
 *
 * 1.4 封顶 —— 再大布局会溢出,安卓端也是这个数。
 * 拿不到这个能力(旧版本 API)就静默跳过:字没放大总比崩了强。
 */
export function applyFontScale(context: common.UIAbilityContext, elder: boolean): void {
  try {
    context.getApplicationContext().setFontSizeScale(elder ? 1.4 : 1.0);
  } catch (e) {
    // 系统不支持就算了,不打扰用户
  }
}

/** 隐私政策版本。与 Flutter 端 legal.dart 的 kLegalVersion 保持一致 */
const LEGAL_VERSION: string = '2026-07-28';
const PRIVACY_URL: string = 'https://chaojizan.cc/legal/privacy';
const TERMS_URL: string = 'https://chaojizan.cc/legal/terms';

/**
 * 应用根页面。
 *
 * **隐私门在最外层,同意之前一个网络请求都不许发。**
 * 顺序是:读本地会话(不联网)→ 没同意过就先弹隐私门 → 同意之后才进主界面,
 * 而主界面才会去定位、去拉商家列表。
 *
 * 安卓端在这件事上返过一次工:开屏页套在隐私门外面,启动就请求 /splash
 * 并下载开屏图 —— 首次启动在用户点"同意"之前就已经联网了。
 * 这是工信部通报和应用商店驳回的头号事由,鸿蒙版从第一版就摆对。
 *
 * 路由集中在这里(NavPathStack + navDestination),页面之间不互相 push ——
 * 谁能跳到哪一目了然,加页面也只改这一个地方。
 */
@Entry
@Component
struct Index {
  /** 会话读完之前什么都不画,避免闪一下登录态又变回来 */
  @State private ready: boolean = false;
  @State private agreed: boolean = false;
  private pathStack: NavPathStack = new NavPathStack();

  async aboutToAppear(): Promise<void> {
    const context = getContext(this) as common.UIAbilityContext;
    const session: Session = Session.get();
    await session.init(context);
    const agreedVersion: string = await session.agreedPrivacyVersion();
    // 版本变了要重新征得同意 —— 但只在**实质扩大**处理范围时才升版本号,
    // 收敛处理范围(比如删掉一条用不到的权限)不该把老用户全拦一遍
    this.agreed = agreedVersion === LEGAL_VERSION;
    // 长辈版:应用级字体缩放,一处生效全局
    applyFontScale(context, await session.elderMode());
    Api.get().onUnauthorized = () => {
      promptAction.showToast({ message: '登录已过期,请重新登录' });
      this.pathStack.pushPath({ name: Routes.LOGIN });
    };
    this.ready = true;
  }

  private async onAgree(): Promise<void> {
    await Session.get().agreePrivacy(LEGAL_VERSION);
    this.agreed = true;
    // 同意之后才允许初始化推送、地图这类收集类 SDK。
    // 目前这一版还没接,接的时候放在这里,别往前挪
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

  @Builder
  private privacyGate() {
    Column() {
      Text('超级赞')
        .fontSize(28)
        .fontWeight(FontWeight.Bold)
        .fontColor($r('app.color.brand'))
        .margin({ top: 64, bottom: 8 });
      Text('点外卖,每一单分账可查')
        .fontSize(15)
        .fontColor($r('app.color.ink_muted'));

      Column({ space: 10 }) {
        Text('在开始之前,有几句话要先说清楚:')
          .fontSize(14).fontColor($r('app.color.ink')).width('100%');
        Text('· 商家总负担 5% 封顶,配送费一分不截留、全部归骑手')
          .fontSize(13).fontColor($r('app.color.ink_muted')).width('100%');
        Text('· 我们需要你的位置来展示附近的商家、计算配送费。' +
          '不给也能用,只是看到的是演示区域的店')
          .fontSize(13).fontColor($r('app.color.ink_muted')).width('100%');
        Text('· 不收集后台定位、设备识别码、装机列表。' +
          '你点「同意」之前,这个 App 不会发出任何一个网络请求')
          .fontSize(13).fontColor($r('app.color.ink_muted')).width('100%');
      }
      .padding(16)
      .margin({ top: 28, left: 20, right: 20 })
      .borderRadius(14)
      .backgroundColor($r('app.color.surface_alt'))
      .alignItems(HorizontalAlign.Start);

      Row() {
        Text('详见 ').fontSize(13).fontColor($r('app.color.ink_muted'));
        Text('《用户协议》')
          .fontSize(13).fontColor($r('app.color.brand'))
          .onClick(() => this.openUrl(TERMS_URL));
        Text(' 与 ').fontSize(13).fontColor($r('app.color.ink_muted'));
        Text('《隐私政策》')
          .fontSize(13).fontColor($r('app.color.brand'))
          .onClick(() => this.openUrl(PRIVACY_URL));
      }
      .margin({ top: 16 });

      Blank();

      Button('同意并继续')
        .width('86%').height(46)
        .backgroundColor($r('app.color.brand'))
        .onClick(() => { this.onAgree(); });

      Button('不同意')
        .width('86%').height(44)
        .margin({ top: 8, bottom: 32 })
        .backgroundColor(Color.Transparent)
        .fontColor($r('app.color.ink_muted'))
        .onClick(() => {
          // 不同意就退出。**不做"仅浏览模式"那种绕过** ——
          // 不同意却继续用,等于同意这件事没有意义
          const context = getContext(this) as common.UIAbilityContext;
          context.terminateSelf();
        });
    }
    .width('100%').height('100%')
    .backgroundColor($r('app.color.surface'));
  }

  /** 路由表。所有页面跳转都从这里出去,页面之间不互相 push */
  @Builder
  private pageMap(name: string, param: object) {
    if (name === Routes.LOGIN) {
      NavDestination() {
        LoginPage({
          onLoggedIn: () => { this.pathStack.pop(); },
        });
      }
      .title('登录');
    } else if (name === Routes.MERCHANT) {
      NavDestination() {
        MerchantPage({
          merchantId: (param as MerchantParam).merchantId,
          onCheckout: (m: Merchant, lines: CartLine[]) => {
            const p: CheckoutParam = { merchant: m, lines: lines };
            this.pathStack.pushPath({ name: Routes.CHECKOUT, param: p });
          },
        });
      }
      .title('点餐');
    } else if (name === Routes.CHECKOUT) {
      NavDestination() {
        CheckoutPage({
          merchant: (param as CheckoutParam).merchant,
          lines: (param as CheckoutParam).lines,
          onNeedLogin: () => { this.pathStack.pushPath({ name: Routes.LOGIN }); },
          onPaid: (order: Order) => {
            // 不管付没付成都进详情:付成了能看进度,没付成那里有「去支付」。
            // 先把结算页从栈里去掉,免得用户返回时又下一单
            this.pathStack.pop();
            const p: OrderDetailParam = { orderNo: order.order_no };
            this.pathStack.pushPath({ name: Routes.ORDER_DETAIL, param: p });
          },
        });
      }
      .title('确认订单');
    } else if (name === Routes.ORDER_DETAIL) {
      NavDestination() {
        OrderDetailPage({
          orderNo: (param as OrderDetailParam).orderNo,
          onOpenChat: (orderNo: string, peer: string) => {
            const p: ChatParam = { orderNo: orderNo, peer: peer };
            this.pathStack.pushPath({ name: Routes.CHAT, param: p });
          },
          onOpenReview: (orderNo: string) => {
            const p: OrderActionParam = { orderNo: orderNo };
            this.pathStack.pushPath({ name: Routes.REVIEW, param: p });
          },
          onOpenAfterSale: (orderNo: string) => {
            const p: OrderActionParam = { orderNo: orderNo };
            this.pathStack.pushPath({ name: Routes.AFTER_SALE, param: p });
          },
          onShare: (order: Order) => {
            const p: ShareCardParam = { order: order };
            this.pathStack.pushPath({ name: Routes.SHARE_CARD, param: p });
          },
          onOpenAppend: (orderNo: string, merchantId: number) => {
            const p: AppendOrderParam = {
              parentOrderNo: orderNo, merchantId: merchantId,
            };
            this.pathStack.pushPath({ name: Routes.APPEND_ORDER, param: p });
          },
        });
      }
      .title('订单详情');
    } else if (name === Routes.CHAT) {
      NavDestination() {
        ChatPage({
          orderNo: (param as ChatParam).orderNo,
          peer: (param as ChatParam).peer,
        });
      }
      .title((param as ChatParam).peer === 'rider' ? '和骑手说句话' : '和商家说句话');
    } else if (name === Routes.AFTER_SALE) {
      NavDestination() {
        AfterSalePage({
          orderNo: (param as OrderActionParam).orderNo,
          onDone: () => { this.pathStack.pop(); },
        });
      }
      .title('申请售后');
    } else if (name === Routes.REVIEW) {
      NavDestination() {
        ReviewPage({
          orderNo: (param as OrderActionParam).orderNo,
          onDone: () => { this.pathStack.pop(); },
        });
      }
      .title('写评价');
    } else if (name === Routes.TRANSPARENCY) {
      NavDestination() {
        TransparencyPage();
      }
      .title('平台体检');
    } else if (name === Routes.MONEY_FLOW) {
      NavDestination() { MoneyFlowPage(); }.title('钱去哪了');
    } else if (name === Routes.FAVORITES) {
      NavDestination() {
        FavoritesPage({
          onOpenMerchant: (id: number) => {
            const p: MerchantParam = { merchantId: id };
            this.pathStack.pushPath({ name: Routes.MERCHANT, param: p });
          },
        });
      }.title('我的收藏');
    } else if (name === Routes.COUPONS) {
      NavDestination() { CouponsPage(); }.title('我的优惠券');
    } else if (name === Routes.MESSAGES) {
      NavDestination() { MessagesPage(); }.title('消息中心');
    } else if (name === Routes.HELP) {
      NavDestination() {
        HelpPage({
          onOpenSupport: () => {
            this.pathStack.pushPath({ name: Routes.SUPPORT });
          },
        });
      }.title('帮助中心');
    } else if (name === Routes.SUPPORT) {
      NavDestination() { SupportPage(); }.title('联系平台客服');
    } else if (name === Routes.SETTINGS) {
      NavDestination() { SettingsPage(); }.title('设置');
    } else if (name === Routes.LICENSES) {
      NavDestination() {
        LicensesPage({ merchantId: (param as LicensesParam).merchantId });
      }.title('证照公示');
    } else if (name === Routes.VOUCHER_DEALS) {
      NavDestination() {
        VoucherDealsPage({
          onOpenDeal: (d: VoucherDeal) => {
            const p: VoucherDetailParam = { deal: d };
            this.pathStack.pushPath({ name: Routes.VOUCHER_DETAIL, param: p });
          },
        });
      }.title('到店团购');
    } else if (name === Routes.VOUCHER_DETAIL) {
      NavDestination() {
        VoucherDetailPage({
          deal: (param as VoucherDetailParam).deal,
          onBought: () => {
            this.pathStack.pop();
            this.pathStack.pushPath({ name: Routes.MY_VOUCHERS });
          },
        });
      }.title('团购详情');
    } else if (name === Routes.MY_VOUCHERS) {
      NavDestination() { MyVouchersPage(); }.title('我的券包');
    } else if (name === Routes.ERRAND) {
      NavDestination() {
        ErrandPage({
          onPaid: (order: Order) => {
            // 下单后直接进详情。付没付成都进 —— 没付成那里有「去支付」
            this.pathStack.pop();
            const p: OrderDetailParam = { orderNo: order.order_no };
            this.pathStack.pushPath({ name: Routes.ORDER_DETAIL, param: p });
          },
        });
      }.title('跑腿');
    } else if (name === Routes.HOTELS) {
      NavDestination() {
        HotelListPage({
          lat: (param as HotelsParam).lat,
          lng: (param as HotelsParam).lng,
          onOpenHotel: (id: number) => {
            const p: HotelDetailParam = { hotelId: id };
            this.pathStack.pushPath({ name: Routes.HOTEL_DETAIL, param: p });
          },
        });
      }.title('住宿');
    } else if (name === Routes.SHARE_CARD) {
      NavDestination() {
        ShareCardPage({ order: (param as ShareCardParam).order });
      }.title('晒这一单的账');
    } else if (name === Routes.GROUP_CART) {
      NavDestination() {
        GroupCartPage({
          merchantId: (param as GroupCartParam).merchantId,
          code: (param as GroupCartParam).code,
          onPaid: (orderNo: string) => {
            this.pathStack.pop();
            const p: OrderDetailParam = { orderNo: orderNo };
            this.pathStack.pushPath({ name: Routes.ORDER_DETAIL, param: p });
          },
        });
      }.title('拼单');
    } else if (name === Routes.APPEND_ORDER) {
      NavDestination() {
        AppendOrderPage({
          parentOrderNo: (param as AppendOrderParam).parentOrderNo,
          merchantId: (param as AppendOrderParam).merchantId,
          onPaid: (orderNo: string) => {
            this.pathStack.pop();
            const p: OrderDetailParam = { orderNo: orderNo };
            this.pathStack.pushPath({ name: Routes.ORDER_DETAIL, param: p });
          },
        });
      }.title('加菜');
    } else if (name === Routes.FOOD_SAFETY_RECORDS) {
      NavDestination() { FoodSafetyRecordsPage(); }.title('我的食安投诉');
    } else if (name === Routes.INVITE) {
      NavDestination() { InvitePage(); }.title('邀请好友');
    } else if (name === Routes.IDENTITY) {
      NavDestination() { IdentityPage(); }.title('实名认证');
    } else if (name === Routes.HOTEL_DETAIL) {
      NavDestination() {
        HotelDetailPage({
          hotelId: (param as HotelDetailParam).hotelId,
          onNeedLogin: () => { this.pathStack.pushPath({ name: Routes.LOGIN }); },
          onBooked: () => {
            this.pathStack.pop();
            this.pathStack.pushPath({ name: Routes.STAY_ORDERS });
          },
        });
      }.title('酒店详情');
    } else if (name === Routes.STAY_ORDERS) {
      NavDestination() {
        StayOrdersPage({
          onOpenAfter: (orderNo: string) => {
            const p: OrderActionParam = { orderNo: orderNo };
            this.pathStack.pushPath({ name: Routes.STAY_AFTER, param: p });
          },
        });
      }.title('住宿订单');
    } else if (name === Routes.STAY_AFTER) {
      NavDestination() {
        StayAfterPage({
          orderNo: (param as OrderActionParam).orderNo,
          onDone: () => { this.pathStack.pop(); },
        });
      }.title('住宿评价与售后');
    } else if (name === Routes.SEARCH) {
      NavDestination() {
        SearchPage({
          lat: (param as SearchParam).lat,
          lng: (param as SearchParam).lng,
          onOpenMerchant: (id: number) => {
            const p: MerchantParam = { merchantId: id };
            this.pathStack.pushPath({ name: Routes.MERCHANT, param: p });
          },
        });
      }
      .title('搜索');
    } else if (name === Routes.CATEGORY) {
      NavDestination() {
        CategoryPage({
          lat: (param as CategoryParam).lat,
          lng: (param as CategoryParam).lng,
          initialSlug: (param as CategoryParam).slug,
          onOpenMerchant: (id: number) => {
            const p: MerchantParam = { merchantId: id };
            this.pathStack.pushPath({ name: Routes.MERCHANT, param: p });
          },
        });
      }
      .title('分类');
    } else if (name === Routes.ADDRESS_LIST) {
      NavDestination() {
        AddressListPage({
          selectMode: (param as AddressListParam).selectMode,
          onPick: () => { this.pathStack.pop(); },
          onEdit: (a: Address | null) => {
            const p: AddressEditParam = { editing: a };
            this.pathStack.pushPath({ name: Routes.ADDRESS_EDIT, param: p });
          },
        });
      }
      .title('收货地址');
    } else if (name === Routes.ADDRESS_EDIT) {
      NavDestination() {
        AddressEditPage({
          editing: (param as AddressEditParam).editing,
          onSaved: () => { this.pathStack.pop(); },
        });
      }
      .title((param as AddressEditParam).editing === null ? '添加地址' : '编辑地址');
    }
  }

  build() {
    Stack() {
      if (!this.ready) {
        // 只是读一次本地存储,毫秒级;这里不该出现任何网络等待
        Column() { LoadingProgress().width(40).height(40); }
        .width('100%').height('100%')
        .justifyContent(FlexAlign.Center);
      } else if (!this.agreed) {
        this.privacyGate();
      } else {
        Navigation(this.pathStack) {
          MainTabs({
            onOpenMerchant: (id: number) => {
              const p: MerchantParam = { merchantId: id };
              this.pathStack.pushPath({ name: Routes.MERCHANT, param: p });
            },
            onOpenSearch: (lat: number, lng: number) => {
              const p: SearchParam = { lat: lat, lng: lng };
              this.pathStack.pushPath({ name: Routes.SEARCH, param: p });
            },
            onOpenCategory: (lat: number, lng: number, slug: string) => {
              const p: CategoryParam = { lat: lat, lng: lng, slug: slug };
              this.pathStack.pushPath({ name: Routes.CATEGORY, param: p });
            },
            onOpenAddresses: () => {
              const p: AddressListParam = { selectMode: false };
              this.pathStack.pushPath({ name: Routes.ADDRESS_LIST, param: p });
            },
            onOpenTransparency: () => {
              this.pathStack.pushPath({ name: Routes.TRANSPARENCY });
            },
            onOpenRoute: (route: string) => {
              this.pathStack.pushPath({ name: route });
            },
            onOpenOrder: (orderNo: string) => {
              const p: OrderDetailParam = { orderNo: orderNo };
              this.pathStack.pushPath({ name: Routes.ORDER_DETAIL, param: p });
            },
            onNeedLogin: () => {
              this.pathStack.pushPath({ name: Routes.LOGIN });
            },
          });
        }
        .hideTitleBar(true)
        .mode(NavigationMode.Stack)
        .navDestination(this.pageMap);
      }
    }
    .width('100%').height('100%');
  }
}
