import { common } from '@kit.AbilityKit';
import { preferences } from '@kit.ArkData';
import { UserApi } from '../common/UserApi';
import { ApiException } from '../common/Api';
import { Merchant } from '../model/Models';
import { MerchantCard } from './MerchantCard';

const STORE: string = 'superz_session';
const K_HISTORY: string = 'search_history';
const MAX_HISTORY: number = 10;
/** 联想防抖。每敲一个字就发一次请求既费流量也把服务端打满 */
const SUGGEST_DEBOUNCE_MS: number = 250;

/**
 * 搜索。
 *
 * **默认排序是「综合」不是「距离」** —— 搜「麻辣烫」的人要的是好的麻辣烫,
 * 不是最近的那家。距离排序留给首页。
 *
 * 距离档位没有 5km:服务端已经把浏览半径收敛到配送上限(4km),
 * 留一个 5km 的选项等于骗人 —— 选了和「不限」结果一样。
 */
@Component
export struct SearchPage {
  lat: number = 0;
  lng: number = 0;
  onOpenMerchant: (merchantId: number) => void = () => {};

  @State private keyword: string = '';
  @State private history: string[] = [];
  @State private hot: string[] = [];
  @State private suggests: string[] = [];
  @State private results: Merchant[] = [];
  @State private searched: boolean = false;
  @State private loading: boolean = false;
  @State private error: string = '';
  @State private sort: string = 'comprehensive';
  @State private maxDistanceM: number = 0; // 0 = 不限
  @State private minRating: number = 0;
  @State private hasPromo: boolean = false;

  private api: UserApi = new UserApi();
  private suggestTimer: number = -1;
  private store: preferences.Preferences | null = null;

  async aboutToAppear(): Promise<void> {
    const context = getContext(this) as common.UIAbilityContext;
    try {
      this.store = await preferences.getPreferences(context, STORE);
      const raw: preferences.ValueType = await this.store.get(K_HISTORY, '');
      if (typeof raw === 'string' && raw.length > 0) {
        this.history = JSON.parse(raw) as string[];
      }
    } catch (e) {
      this.history = [];
    }
    try {
      this.hot = await this.api.hotKeywords();
    } catch (e) {
      this.hot = []; // 热词拉不到不影响搜索
    }
  }

  aboutToDisappear(): void {
    if (this.suggestTimer >= 0) {
      clearTimeout(this.suggestTimer);
      this.suggestTimer = -1;
    }
  }

  private async saveHistory(word: string): Promise<void> {
    const next: string[] = [word];
    for (let i = 0; i < this.history.length; i++) {
      if (this.history[i] !== word && next.length < MAX_HISTORY) {
        next.push(this.history[i]);
      }
    }
    this.history = next;
    if (this.store !== null) {
      await this.store.put(K_HISTORY, JSON.stringify(next));
      await this.store.flush();
    }
  }

  private async clearHistory(): Promise<void> {
    this.history = [];
    if (this.store !== null) {
      await this.store.put(K_HISTORY, '');
      await this.store.flush();
    }
  }

  private onKeywordChange(v: string): void {
    this.keyword = v;
    if (this.suggestTimer >= 0) {
      clearTimeout(this.suggestTimer);
    }
    if (v.trim().length === 0) {
      this.suggests = [];
      this.searched = false;
      return;
    }
    this.suggestTimer = setTimeout(() => {
      this.api.suggest(v.trim())
        .then((list: string[]) => { this.suggests = list; })
        .catch(() => { this.suggests = []; });
      this.suggestTimer = -1;
    }, SUGGEST_DEBOUNCE_MS);
  }

  private async search(word: string): Promise<void> {
    const q: string = word.trim();
    if (q.length === 0) {
      return;
    }
    this.keyword = q;
    this.suggests = [];
    this.loading = true;
    this.searched = true;
    this.error = '';
    try {
      this.results = await this.api.searchMerchants(
        q, this.lat, this.lng, this.sort,
        this.maxDistanceM > 0 ? this.maxDistanceM : undefined,
        this.minRating > 0 ? this.minRating : undefined,
        this.hasPromo);
      await this.saveHistory(q);
    } catch (e) {
      this.error = (e as ApiException).message;
    } finally {
      this.loading = false;
    }
  }

  @Builder
  private chip(text: string, active: boolean, onTap: () => void) {
    Text(text)
      .fontSize(12)
      .padding({ left: 12, right: 12, top: 6, bottom: 6 })
      .margin({ right: 8, bottom: 8 })
      .borderRadius(14)
      .backgroundColor(active ? $r('app.color.brand_soft') : $r('app.color.surface_alt'))
      .fontColor(active ? $r('app.color.brand') : $r('app.color.ink'))
      .onClick(onTap);
  }

  @Builder
  private filters() {
    Column({ space: 2 }) {
      Flex({ wrap: FlexWrap.Wrap }) {
        this.chip('综合', this.sort === 'comprehensive', () => {
          this.sort = 'comprehensive';
          this.search(this.keyword);
        });
        this.chip('距离', this.sort === 'distance', () => {
          this.sort = 'distance';
          this.search(this.keyword);
        });
        this.chip('评分', this.sort === 'rating', () => {
          this.sort = 'rating';
          this.search(this.keyword);
        });
        this.chip('销量', this.sort === 'sales', () => {
          this.sort = 'sales';
          this.search(this.keyword);
        });
      }
      .width('100%');
      Flex({ wrap: FlexWrap.Wrap }) {
        // 没有 5km 档:服务端浏览半径已收敛到配送上限,选了也是一样的结果
        this.chip('1km 内', this.maxDistanceM === 1000, () => {
          this.maxDistanceM = this.maxDistanceM === 1000 ? 0 : 1000;
          this.search(this.keyword);
        });
        this.chip('2km 内', this.maxDistanceM === 2000, () => {
          this.maxDistanceM = this.maxDistanceM === 2000 ? 0 : 2000;
          this.search(this.keyword);
        });
        this.chip('4.5 分以上', this.minRating >= 4.5, () => {
          this.minRating = this.minRating >= 4.5 ? 0 : 4.5;
          this.search(this.keyword);
        });
        this.chip('有优惠', this.hasPromo, () => {
          this.hasPromo = !this.hasPromo;
          this.search(this.keyword);
        });
      }
      .width('100%');
    }
    .width('100%').padding({ left: 12, right: 12 });
  }

  build() {
    Column() {
      Row({ space: 8 }) {
        TextInput({ placeholder: '搜店铺、搜菜名', text: this.keyword })
          .height(40).layoutWeight(1)
          .onChange((v: string) => { this.onKeywordChange(v); })
          .onSubmit(() => { this.search(this.keyword); });
        Text('搜索')
          .fontSize(14).fontColor($r('app.color.brand'))
          .onClick(() => { this.search(this.keyword); });
      }
      .width('100%').padding({ left: 12, right: 12, top: 10, bottom: 8 });

      if (this.suggests.length > 0) {
        List() {
          ForEach(this.suggests, (s: string) => {
            ListItem() {
              Text(s)
                .fontSize(14).fontColor($r('app.color.ink'))
                .width('100%')
                .padding({ left: 16, right: 16, top: 12, bottom: 12 });
            }
            .onClick(() => { this.search(s); });
          }, (s: string) => s);
        }
        .layoutWeight(1).backgroundColor($r('app.color.surface'));
      } else if (!this.searched) {
        Scroll() {
          Column({ space: 14 }) {
            if (this.history.length > 0) {
              Row() {
                Text('搜索历史')
                  .fontSize(13).fontColor($r('app.color.ink_muted')).layoutWeight(1);
                Text('清空')
                  .fontSize(12).fontColor($r('app.color.ink_muted'))
                  .onClick(() => { this.clearHistory(); });
              }
              .width('100%');
              Flex({ wrap: FlexWrap.Wrap }) {
                ForEach(this.history, (h: string) => {
                  this.chip(h, false, () => { this.search(h); });
                }, (h: string) => `h-${h}`);
              }
              .width('100%');
            }
            if (this.hot.length > 0) {
              Text('大家在搜(按真实销量)')
                .fontSize(13).fontColor($r('app.color.ink_muted')).width('100%');
              Flex({ wrap: FlexWrap.Wrap }) {
                ForEach(this.hot, (h: string) => {
                  this.chip(h, false, () => { this.search(h); });
                }, (h: string) => `hot-${h}`);
              }
              .width('100%');
            }
          }
          .width('100%').padding(16).alignItems(HorizontalAlign.Start);
        }
        .layoutWeight(1);
      } else {
        this.filters();
        if (this.loading) {
          Column() { LoadingProgress().width(36).height(36); }
          .width('100%').layoutWeight(1).justifyContent(FlexAlign.Center);
        } else if (this.error.length > 0) {
          Column({ space: 12 }) {
            Text(this.error).fontSize(14).fontColor($r('app.color.ink_muted'));
            Button('重试').onClick(() => { this.search(this.keyword); });
          }
          .width('100%').layoutWeight(1).justifyContent(FlexAlign.Center);
        } else if (this.results.length === 0) {
          Column({ space: 6 }) {
            Text('没有找到相关的店')
              .fontSize(14).fontColor($r('app.color.ink_muted'));
            Text('换个词试试,或者把筛选放宽一点')
              .fontSize(12).fontColor($r('app.color.ink_muted'));
          }
          .width('100%').layoutWeight(1).justifyContent(FlexAlign.Center);
        } else {
          List({ space: 10 }) {
            ForEach(this.results, (m: Merchant) => {
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
    }
    .width('100%').height('100%')
    .backgroundColor($r('app.color.page'));
  }
}
