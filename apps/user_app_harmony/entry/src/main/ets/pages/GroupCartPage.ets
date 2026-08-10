import { pasteboard } from '@kit.BasicServicesKit';
import { promptAction } from '@kit.ArkUI';
import { UserApi } from '../common/UserApi';
import { ApiException } from '../common/Api';
import { Dish } from '../model/Models';
import { yuan } from '../common/Money';

/** 拼单车轮询。服务端有 WS 频道,先用轮询,接上 WS 再换 */
const POLL_MS: number = 3000;

/**
 * 拼单。
 *
 * 服务端用 Redis 存车、2 小时 TTL、最多 10 人、各改各的菜、
 * 发起人锁单一次性付、下单时原子关车。
 *
 * ⚠️ 安卓端在这里有个明确的短板:**邀请只有一串可复制的数字**,
 * 没有分享物料、没有链接,朋友还得先装 App 再注册再输码 ——
 * 拼单是天然的多人触点,却漏在第一跳。鸿蒙端至少把口令做成
 * 一句可以直接粘进群里的话。
 *
 * **分账不碰**:拼单只是合并下单,AA 线下自己算。满减按合车总额算。
 */
@Component
export struct GroupCartPage {
  merchantId: number = 0;
  code: string = '';
  onPaid: (orderNo: string) => void = () => {};

  @State private cart: Record<string, Object> | null = null;
  @State private dishes: Dish[] = [];
  @State private loading: boolean = true;
  @State private error: string = '';
  @State private locking: boolean = false;

  private api: UserApi = new UserApi();
  private timer: number = -1;

  async aboutToAppear(): Promise<void> {
    try {
      this.dishes = await this.api.menu(this.merchantId);
    } catch (e) {
      this.dishes = [];
    }
    await this.ensureCart();
    this.timer = setInterval(() => { this.refresh(); }, POLL_MS);
  }

  aboutToDisappear(): void {
    if (this.timer >= 0) {
      clearInterval(this.timer);
      this.timer = -1;
    }
  }

  /** 有码就加入,没码就开一个 */
  private async ensureCart(): Promise<void> {
    this.loading = true;
    this.error = '';
    try {
      if (this.code.length > 0) {
        this.cart = await this.api.joinGroupCart(this.code);
      } else {
        this.cart = await this.api.openGroupCart(this.merchantId);
        this.code = this.str(this.cart, 'code');
      }
    } catch (e) {
      this.error = (e as ApiException).message;
    } finally {
      this.loading = false;
    }
  }

  private async refresh(): Promise<void> {
    if (this.code.length === 0) {
      return;
    }
    try {
      this.cart = await this.api.getGroupCart(this.code);
    } catch (e) {
      // 轮询失败不打扰,下一轮再来
    }
  }

  private str(m: Record<string, Object> | null, key: string): string {
    if (m === null) {
      return '';
    }
    const v: Object = m[key] ?? '';
    return typeof v === 'string' ? v : '';
  }

  private num(m: Record<string, Object> | null, key: string): number {
    if (m === null) {
      return 0;
    }
    const v: Object = m[key] ?? 0;
    return typeof v === 'number' ? v : 0;
  }

  private get items(): Record<string, Object>[] {
    if (this.cart === null) {
      return [];
    }
    const v: Object = this.cart['items'] ?? [];
    return v as Record<string, Object>[];
  }

  private async setItem(dishId: number, qty: number): Promise<void> {
    try {
      this.cart = await this.api.setGroupCartItem(this.code, dishId, qty);
    } catch (e) {
      promptAction.showToast({ message: (e as ApiException).message });
    }
  }

  /** 口令做成一句能直接粘进群里的话,而不是一串裸数字 */
  private copyInvite(): void {
    const text: string = `我在超级赞开了个拼单,口令 ${this.code},` +
      `打开 App 输口令就能加菜。这家外卖商家只被抽 5%,配送费全归骑手。`;
    const data: pasteboard.PasteData =
      pasteboard.createData(pasteboard.MIMETYPE_TEXT_PLAIN, text);
    pasteboard.getSystemPasteboard().setData(data).then(() => {
      promptAction.showToast({ message: '口令已复制,粘到群里就行', duration: 3000 });
    }).catch(() => {
      promptAction.showToast({ message: `口令 ${this.code}` });
    });
  }

  private async lock(): Promise<void> {
    if (this.locking) {
      return;
    }
    this.locking = true;
    try {
      const r: Record<string, Object> = await this.api.lockGroupCart(this.code);
      const orderNo: string = this.str(r, 'order_no');
      if (orderNo.length > 0) {
        this.onPaid(orderNo);
      } else {
        promptAction.showToast({ message: '已锁车,去订单里付款' });
      }
    } catch (e) {
      promptAction.showToast({ message: (e as ApiException).message });
    } finally {
      this.locking = false;
    }
  }

  @Builder
  private itemRow(it: Record<string, Object>) {
    Row() {
      Column({ space: 2 }) {
        Text(this.str(it, 'dish_name'))
          .fontSize(14).fontColor($r('app.color.ink'));
        // 谁点的要写出来 —— 拼单最常见的争执就是"这个谁点的"
        Text(this.str(it, 'user_name').length > 0
          ? this.str(it, 'user_name') : '同行的人')
          .fontSize(11).fontColor($r('app.color.ink_muted'));
      }
      .layoutWeight(1).alignItems(HorizontalAlign.Start);
      Text(`${yuan(this.num(it, 'price_cents'))} ×${this.num(it, 'quantity')}`)
        .fontSize(13).fontColor($r('app.color.ink_muted'));
    }
    .width('100%').padding({ top: 8, bottom: 8 });
  }

  build() {
    Column() {
      if (this.loading) {
        Column() { LoadingProgress().width(36).height(36); }
        .width('100%').layoutWeight(1).justifyContent(FlexAlign.Center);
      } else if (this.error.length > 0) {
        Column({ space: 12 }) {
          Text(this.error).fontSize(14).fontColor($r('app.color.ink_muted'));
          Button('重试').onClick(() => { this.ensureCart(); });
        }
        .width('100%').layoutWeight(1).justifyContent(FlexAlign.Center);
      } else {
        Scroll() {
          Column({ space: 10 }) {
            Column({ space: 8 }) {
              Text('拼单口令')
                .fontSize(13).fontColor($r('app.color.ink_muted')).width('100%');
              Text(this.code)
                .fontSize(28).fontWeight(FontWeight.Bold)
                .fontColor($r('app.color.brand')).width('100%');
              Text(`已有 ${this.num(this.cart, 'member_count')} 人 · 最多 10 人 · 2 小时后自动关闭`)
                .fontSize(11).fontColor($r('app.color.ink_muted')).width('100%');
              Button('复制邀请话术')
                .height(38).fontSize(13)
                .backgroundColor($r('app.color.brand'))
                .onClick(() => { this.copyInvite(); });
            }
            .width('100%').padding(16).backgroundColor($r('app.color.surface'))
            .borderRadius(14).alignItems(HorizontalAlign.Start);

            Column({ space: 4 }) {
              Text('大家点了什么')
                .fontSize(15).fontWeight(FontWeight.Medium)
                .fontColor($r('app.color.ink')).width('100%');
              if (this.items.length === 0) {
                Text('还没有人点菜')
                  .fontSize(13).fontColor($r('app.color.ink_muted')).width('100%');
              }
              ForEach(this.items, (it: Record<string, Object>) => {
                this.itemRow(it);
              }, (it: Record<string, Object>) =>
                `${this.num(it, 'dish_id')}-${this.str(it, 'user_name')}`);
            }
            .width('100%').padding(16).backgroundColor($r('app.color.surface'))
            .borderRadius(14).alignItems(HorizontalAlign.Start);

            Column({ space: 4 }) {
              Text('加菜')
                .fontSize(15).fontWeight(FontWeight.Medium)
                .fontColor($r('app.color.ink')).width('100%');
              ForEach(this.dishes.slice(0, 30), (d: Dish) => {
                Row() {
                  Text(d.name)
                    .fontSize(14).fontColor($r('app.color.ink')).layoutWeight(1);
                  Text(yuan(d.price_cents))
                    .fontSize(13).fontColor($r('app.color.brand'))
                    .margin({ right: 10 });
                  Button('+').width(28).height(28).fontSize(15)
                    .backgroundColor($r('app.color.brand'))
                    .onClick(() => { this.setItem(d.id, 1); });
                }
                .width('100%').padding({ top: 6, bottom: 6 });
              }, (d: Dish) => `${d.id}`);
            }
            .width('100%').padding(16).backgroundColor($r('app.color.surface'))
            .borderRadius(14).alignItems(HorizontalAlign.Start);
          }
          .width('100%').padding({ left: 12, right: 12, top: 12, bottom: 16 });
        }
        .layoutWeight(1).scrollBar(BarState.Off);

        Row() {
          Column({ space: 2 }) {
            Text(yuan(this.num(this.cart, 'total_cents')))
              .fontSize(18).fontWeight(FontWeight.Bold)
              .fontColor($r('app.color.ink'));
            // 说清楚谁付钱,免得所有人都在等别人点
            Text('由发起人统一付款,AA 你们自己算')
              .fontSize(11).fontColor($r('app.color.ink_muted'));
          }
          .layoutWeight(1).alignItems(HorizontalAlign.Start);
          Button(this.locking ? '处理中…' : '锁车下单')
            .width(120).height(44)
            .enabled(!this.locking && this.items.length > 0)
            .backgroundColor($r('app.color.brand'))
            .onClick(() => { this.lock(); });
        }
        .width('100%').padding(12).backgroundColor($r('app.color.surface'))
        .border({ width: { top: 1 }, color: $r('app.color.line') });
      }
    }
    .width('100%').height('100%').backgroundColor($r('app.color.page'));
  }
}
