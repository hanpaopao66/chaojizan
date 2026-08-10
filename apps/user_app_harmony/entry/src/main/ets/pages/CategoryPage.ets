import { UserApi } from '../common/UserApi';
import { ApiException } from '../common/Api';
import { Merchant, MerchantCategory } from '../model/Models';
import { MerchantCard } from './MerchantCard';

/**
 * 品类页。
 *
 * **品类清单走接口不硬编码。** 安卓端在客户端存了一份副本
 * (`merchant_categories.dart`),结果改一个品类名要发一次版 ——
 * 而品类是运营会动的东西,不该和发版绑在一起。
 */
@Component
export struct CategoryPage {
  lat: number = 0;
  lng: number = 0;
  initialSlug: string = '';
  onOpenMerchant: (merchantId: number) => void = () => {};

  @State private categories: MerchantCategory[] = [];
  @State private slug: string = '';
  @State private merchants: Merchant[] = [];
  @State private loading: boolean = true;
  @State private error: string = '';

  private api: UserApi = new UserApi();

  async aboutToAppear(): Promise<void> {
    this.slug = this.initialSlug;
    try {
      this.categories = await this.api.categories();
    } catch (e) {
      this.categories = []; // 拉不到品类就只显示全部
    }
    await this.load();
  }

  private async load(): Promise<void> {
    this.loading = true;
    this.error = '';
    try {
      this.merchants = await this.api.merchants(
        this.lat, this.lng, 'distance', 50, 0, this.slug);
    } catch (e) {
      this.error = (e as ApiException).message;
    } finally {
      this.loading = false;
    }
  }

  @Builder
  private tab(name: string, value: string) {
    Text(name)
      .fontSize(13)
      .padding({ left: 12, right: 12, top: 7, bottom: 7 })
      .margin({ right: 8 })
      .borderRadius(14)
      .backgroundColor(this.slug === value ? $r('app.color.brand_soft') : $r('app.color.surface'))
      .fontColor(this.slug === value
        ? $r('app.color.brand') : $r('app.color.ink'))
      .onClick(() => {
        this.slug = value;
        this.load();
      });
  }

  build() {
    Column() {
      Scroll() {
        Row() {
          this.tab('全部', '');
          ForEach(this.categories, (c: MerchantCategory) => {
            this.tab(c.emoji !== undefined && c.emoji.length > 0
              ? `${c.emoji} ${c.name}` : c.name, c.slug);
          }, (c: MerchantCategory) => c.slug);
        }
        .padding({ left: 12, right: 12, top: 10, bottom: 10 });
      }
      .scrollable(ScrollDirection.Horizontal)
      .scrollBar(BarState.Off)
      .width('100%');

      if (this.loading) {
        Column() { LoadingProgress().width(36).height(36); }
        .width('100%').layoutWeight(1).justifyContent(FlexAlign.Center);
      } else if (this.error.length > 0) {
        Column({ space: 12 }) {
          Text(this.error).fontSize(14).fontColor($r('app.color.ink_muted'));
          Button('重试').onClick(() => { this.load(); });
        }
        .width('100%').layoutWeight(1).justifyContent(FlexAlign.Center);
      } else if (this.merchants.length === 0) {
        // 空品类不摆烂:这一带还没有这个品类的店,说清楚而不是留一片白
        Column({ space: 6 }) {
          Text('这一带还没有这个品类的店')
            .fontSize(14).fontColor($r('app.color.ink_muted'));
          Text('换个品类看看,或者回首页看附近全部')
            .fontSize(12).fontColor($r('app.color.ink_muted'));
        }
        .width('100%').layoutWeight(1).justifyContent(FlexAlign.Center);
      } else {
        List({ space: 10 }) {
          ForEach(this.merchants, (m: Merchant) => {
            ListItem() {
              MerchantCard({ merchant: m });
            }
            .onClick(() => { this.onOpenMerchant(m.id); });
          }, (m: Merchant) => `${m.id}`);
        }
        .width('100%').layoutWeight(1)
        .padding({ left: 12, right: 12, bottom: 12 })
        .scrollBar(BarState.Off);
      }
    }
    .width('100%').height('100%')
    .backgroundColor($r('app.color.page'));
  }
}
