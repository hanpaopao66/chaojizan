import { abilityAccessCtrl, common, Permissions } from '@kit.AbilityKit';
import { geoLocationManager } from '@kit.LocationKit';
import { UserApi } from '../common/UserApi';
import { ApiException } from '../common/Api';
import { Session } from '../common/Session';
import { FrequentDish, Merchant, MerchantCategory } from '../model/Models';
import { MerchantCard } from './MerchantCard';
import { yuan } from '../common/Money';

/**
 * 演示城市坐标(成都春熙路)。
 *
 * 定位拿不到、或者用户所在区域还没开通时降级到这里,**并且在界面上明说**。
 * 安卓端就是这么做的:静默换坐标会让用户以为看到的是身边的店,
 * 点进去发现送不到,那比不给列表更伤。
 */
const DEMO_LAT: number = 30.66;
const DEMO_LNG: number = 104.08;
/** 与服务端 merchants.py 的 _PAGE_MAX 一致 */
const PAGE_SIZE: number = 50;

/** LazyForEach 的数据源。商家一多,ForEach 会把全部卡片一次性建出来 */
class MerchantSource implements IDataSource {
  private items: Merchant[] = [];
  private listeners: DataChangeListener[] = [];

  totalCount(): number {
    return this.items.length;
  }

  getData(index: number): Merchant {
    return this.items[index];
  }

  registerDataChangeListener(listener: DataChangeListener): void {
    if (this.listeners.indexOf(listener) < 0) {
      this.listeners.push(listener);
    }
  }

  unregisterDataChangeListener(listener: DataChangeListener): void {
    const i: number = this.listeners.indexOf(listener);
    if (i >= 0) {
      this.listeners.splice(i, 1);
    }
  }

  reset(items: Merchant[]): void {
    this.items = items;
    for (let i = 0; i < this.listeners.length; i++) {
      this.listeners[i].onDataReloaded();
    }
  }

  append(more: Merchant[]): void {
    this.items = this.items.concat(more);
    for (let i = 0; i < this.listeners.length; i++) {
      this.listeners[i].onDataReloaded();
    }
  }
}

@Component
export struct HomePage {
  onOpenMerchant: (merchantId: number) => void = () => {};
  onOpenSearch: (lat: number, lng: number) => void = () => {};
  onOpenCategory: (lat: number, lng: number, slug: string) => void = () => {};

  private api: UserApi = new UserApi();
  private source: MerchantSource = new MerchantSource();

  @State private loading: boolean = true;
  @State private error: string = '';
  @State private count: number = 0;
  @State private sort: string = 'distance';
  @State private categories: MerchantCategory[] = [];
  @State private frequent: FrequentDish[] = [];
  /** 是不是拿到了真实定位。false 时界面上要说清楚 */
  @State private realLocation: boolean = false;
  /** 是不是因为本地没开通而降级到了演示城市 */
  @State private fellBack: boolean = false;

  private lat: number = DEMO_LAT;
  private lng: number = DEMO_LNG;
  private loadingMore: boolean = false;
  private noMore: boolean = false;

  async aboutToAppear(): Promise<void> {
    await this.locate();
    await this.load();
    // 品类和常点都是锦上添花,失败不影响主列表
    this.api.categories()
      .then((list: MerchantCategory[]) => { this.categories = list; })
      .catch(() => {});
    if (Session.get().isLoggedIn) {
      this.api.myFrequentDishes()
        .then((list: FrequentDish[]) => { this.frequent = list; })
        .catch(() => {});
    }
  }

  /**
   * 定位。**用到时才申请权限**,不在启动时一次性要一堆 ——
   * 而且拒绝了也要能用,只是看到的是演示区域
   */
  private async locate(): Promise<void> {
    try {
      const context = getContext(this) as common.UIAbilityContext;
      const permissions: Permissions[] = ['ohos.permission.APPROXIMATELY_LOCATION'];
      const atManager = abilityAccessCtrl.createAtManager();
      const granted = await atManager.requestPermissionsFromUser(context, permissions);
      if (granted.authResults.length === 0 || granted.authResults[0] !== 0) {
        return; // 用户拒绝:保持演示坐标,realLocation 仍是 false
      }
      const request: geoLocationManager.CurrentLocationRequest = {
        priority: geoLocationManager.LocationRequestPriority.FIRST_FIX,
        scenario: geoLocationManager.LocationRequestScenario.UNSET,
        timeoutMs: 8000,
      };
      const location = await geoLocationManager.getCurrentLocation(request);
      this.lat = location.latitude;
      this.lng = location.longitude;
      this.realLocation = true;
    } catch (e) {
      // 定位失败不是错误路径,是常态(室内、关了定位、没有权限)
      this.realLocation = false;
    }
  }

  private async load(): Promise<void> {
    this.loading = true;
    this.error = '';
    this.noMore = false;
    try {
      let list: Merchant[] = await this.api.merchants(
        this.lat, this.lng, this.sort, PAGE_SIZE, 0);
      // 定位正常但附近没有开通:降级到演示城市。审核人员在外地也能看到内容,
      // 而且数据链路和真实用户完全一致
      if (list.length === 0 && this.realLocation) {
        const demo: Merchant[] = await this.api.merchants(
          DEMO_LAT, DEMO_LNG, this.sort, PAGE_SIZE, 0);
        if (demo.length > 0) {
          this.fellBack = true;
          this.lat = DEMO_LAT;
          this.lng = DEMO_LNG;
          list = demo;
        }
      }
      this.source.reset(list);
      this.count = list.length;
      this.noMore = list.length < PAGE_SIZE;
    } catch (e) {
      this.error = (e as ApiException).message;
    } finally {
      this.loading = false;
    }
  }

  /** 触底加载下一页。失败就停,不反复重试打服务器 */
  private async loadMore(): Promise<void> {
    if (this.loadingMore || this.noMore) {
      return;
    }
    this.loadingMore = true;
    try {
      const next: Merchant[] = await this.api.merchants(
        this.lat, this.lng, this.sort, PAGE_SIZE, this.count);
      this.source.append(next);
      this.count += next.length;
      this.noMore = next.length < PAGE_SIZE;
    } catch (e) {
      this.noMore = true;
    } finally {
      this.loadingMore = false;
    }
  }

  /** 平台主张。抽象的口号没意义,给的是三条可验证的 */
  @Builder
  private promiseStrip() {
    Row({ space: 6 }) {
      Text('商家 5% 封顶').fontSize(12).fontColor($r('app.color.earn'));
      Text('·').fontSize(12).fontColor($r('app.color.line'));
      Text('配送费全归骑手').fontSize(12).fontColor($r('app.color.earn'));
      Text('·').fontSize(12).fontColor($r('app.color.line'));
      Text('每单分账可查').fontSize(12).fontColor($r('app.color.earn'));
    }
    .width('100%').padding({ left: 16, right: 16, top: 6, bottom: 6 });
  }

  @Builder
  private searchBar() {
    Row() {
      Text('搜店铺、搜菜名')
        .fontSize(14).fontColor($r('app.color.ink_muted')).layoutWeight(1);
    }
    .width('100%')
    .padding({ left: 14, right: 14, top: 10, bottom: 10 })
    .margin({ left: 12, right: 12 })
    .borderRadius(20)
    .backgroundColor($r('app.color.surface'))
    .onClick(() => { this.onOpenSearch(this.lat, this.lng); });
  }

  /** 品类快捷入口。清单来自接口,改品类不用发版 */
  @Builder
  private categoryRow() {
    if (this.categories.length > 0) {
      Scroll() {
        Row() {
          ForEach(this.categories.slice(0, 12), (c: MerchantCategory) => {
            Column({ space: 3 }) {
              Text(c.emoji !== undefined && c.emoji.length > 0 ? c.emoji : '🍽')
                .fontSize(20);
              Text(c.name).fontSize(11).fontColor($r('app.color.ink'));
            }
            .width(64)
            .onClick(() => { this.onOpenCategory(this.lat, this.lng, c.slug); });
          }, (c: MerchantCategory) => c.slug);
        }
        .padding({ left: 12, right: 12, top: 8, bottom: 8 });
      }
      .scrollable(ScrollDirection.Horizontal)
      .scrollBar(BarState.Off)
      .width('100%');
    }
  }

  /** 我的常点:近 90 天点得最多的「店 + 菜」,一键回到那家店 */
  @Builder
  private frequentRow() {
    if (this.frequent.length > 0) {
      Column({ space: 6 }) {
        Text('我的常点')
          .fontSize(13).fontColor($r('app.color.ink_muted')).width('100%');
        Scroll() {
          Row({ space: 8 }) {
            ForEach(this.frequent, (f: FrequentDish) => {
              Column({ space: 2 }) {
                Text(f.dish_name)
                  .fontSize(12).fontColor($r('app.color.ink'))
                  .maxLines(1).textOverflow({ overflow: TextOverflow.Ellipsis });
                Text(`${f.merchant_name} · ${yuan(f.price_cents)}`)
                  .fontSize(10).fontColor($r('app.color.ink_muted'))
                  .maxLines(1).textOverflow({ overflow: TextOverflow.Ellipsis });
              }
              .width(120).padding(8)
              .borderRadius(10).backgroundColor($r('app.color.surface'))
              .alignItems(HorizontalAlign.Start)
              .onClick(() => { this.onOpenMerchant(f.merchant_id); });
            }, (f: FrequentDish) => `${f.merchant_id}-${f.dish_id}`);
          }
        }
        .scrollable(ScrollDirection.Horizontal).scrollBar(BarState.Off)
        .width('100%');
      }
      .width('100%').padding({ left: 12, right: 12, top: 6, bottom: 6 })
      .alignItems(HorizontalAlign.Start);
    }
  }

  @Builder
  private sortChips() {
    Row({ space: 8 }) {
      ForEach(['distance', 'rating', 'sales'], (s: string) => {
        Text(s === 'distance' ? '距离最近' : (s === 'rating' ? '评分最高' : '销量最高'))
          .fontSize(12)
          .padding({ left: 12, right: 12, top: 6, bottom: 6 })
          .borderRadius(14)
          .backgroundColor(this.sort === s ? $r('app.color.brand_soft') : $r('app.color.surface'))
          .fontColor(this.sort === s
            ? $r('app.color.brand') : $r('app.color.ink'))
          .onClick(() => {
            this.sort = s;
            this.load();
          });
      }, (s: string) => s);
    }
    .width('100%').padding({ left: 12, right: 12, top: 4, bottom: 6 });
  }

  build() {
    Column() {
      Row() {
        Text('超级赞')
          .fontSize(20).fontWeight(FontWeight.Bold)
          .fontColor($r('app.color.brand'));
      }
      .width('100%').padding({ left: 16, right: 16, top: 10, bottom: 2 });

      this.promiseStrip();
      this.searchBar();
      this.categoryRow();
      this.frequentRow();

      if (!this.realLocation || this.fellBack) {
        Text(this.fellBack
          ? '您所在区域暂未开通,正在展示演示城市的商家'
          : '未获取到定位,正在展示演示区域的商家')
          .fontSize(12).fontColor($r('app.color.ink_muted'))
          .width('100%').padding({ left: 16, right: 16, bottom: 4 });
      }

      this.sortChips();

      if (this.loading) {
        Column() { LoadingProgress().width(36).height(36); }
        .width('100%').layoutWeight(1).justifyContent(FlexAlign.Center);
      } else if (this.error.length > 0) {
        Column({ space: 12 }) {
          Text(this.error)
            .fontSize(14).fontColor($r('app.color.ink_muted'))
            .textAlign(TextAlign.Center);
          Button('重试').onClick(() => { this.load(); });
        }
        .width('100%').layoutWeight(1)
        .justifyContent(FlexAlign.Center).padding(32);
      } else if (this.count === 0) {
        Column() {
          Text('附近暂时没有营业的商家')
            .fontSize(14).fontColor($r('app.color.ink_muted'));
        }
        .width('100%').layoutWeight(1).justifyContent(FlexAlign.Center);
      } else {
        List({ space: 10 }) {
          LazyForEach(this.source, (m: Merchant) => {
            ListItem() {
              MerchantCard({ merchant: m });
            }
            .onClick(() => { this.onOpenMerchant(m.id); });
          }, (m: Merchant) => `${m.id}`);
          // 排序口径的兜底承诺。**这不是装饰,是产品主张**
          ListItem() {
            Text('没有竞价排名 · 排序只按你选的口径')
              .fontSize(11).fontColor($r('app.color.ink_muted'))
              .width('100%').textAlign(TextAlign.Center)
              .padding({ top: 14, bottom: 10 });
          }
        }
        .width('100%').layoutWeight(1)
        .padding({ left: 12, right: 12, bottom: 12 })
        .scrollBar(BarState.Off)
        .onReachEnd(() => { this.loadMore(); });
      }
    }
    .width('100%').height('100%')
    .backgroundColor($r('app.color.page'));
  }
}
