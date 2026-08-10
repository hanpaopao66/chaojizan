import { HomePage } from './HomePage';
import { OrdersPage } from './OrdersPage';
import { ProfilePage } from './ProfilePage';

/**
 * 底部三个 tab:首页 / 订单 / 我的。
 *
 * **业务不进 tab,一律走首页的入口。** 团购、住宿、跑腿这些业务会持续增加,
 * 塞进 tab 的话每加一条业务就要重排导航;tab 只放"功能",保持稳定。
 * 这条是安卓端定下来的,鸿蒙端照做。
 *
 * 用 `Tabs` 而不是每次切换重建页面:从「订单」切回「首页」不该重新定位、
 * 重新拉一遍商家列表 —— 用户等一遍、手机费一遍电。
 */
@Component
export struct MainTabs {
  onOpenMerchant: (merchantId: number) => void = () => {};
  onOpenOrder: (orderNo: string) => void = () => {};
  onNeedLogin: () => void = () => {};
  onOpenSearch: (lat: number, lng: number) => void = () => {};
  onOpenCategory: (lat: number, lng: number, slug: string) => void = () => {};
  onOpenAddresses: () => void = () => {};
  onOpenTransparency: () => void = () => {};
  onOpenRoute: (route: string) => void = () => {};

  @State private index: number = 0;

  @Builder
  private barItem(title: string, idx: number) {
    Column({ space: 2 }) {
      Text(title)
        .fontSize(12)
        .fontColor(this.index === idx
          ? $r('app.color.brand') : $r('app.color.ink_muted'));
    }
    .width('100%')
    .height(52)
    .justifyContent(FlexAlign.Center);
  }

  build() {
    Tabs({ barPosition: BarPosition.End, index: this.index }) {
      TabContent() {
        HomePage({
          onOpenMerchant: this.onOpenMerchant,
          onOpenSearch: this.onOpenSearch,
          onOpenCategory: this.onOpenCategory,
        });
      }
      .tabBar(this.barItem('首页', 0));

      TabContent() {
        OrdersPage({ onOpen: this.onOpenOrder, onNeedLogin: this.onNeedLogin });
      }
      .tabBar(this.barItem('订单', 1));

      TabContent() {
        ProfilePage({
          onNeedLogin: this.onNeedLogin,
          onOpenAddresses: this.onOpenAddresses,
          onOpenTransparency: this.onOpenTransparency,
          onOpenRoute: this.onOpenRoute,
        });
      }
      .tabBar(this.barItem('我的', 2));
    }
    .width('100%')
    .height('100%')
    .barHeight(56)
    .animationDuration(0)
    .onChange((i: number) => { this.index = i; });
  }
}
