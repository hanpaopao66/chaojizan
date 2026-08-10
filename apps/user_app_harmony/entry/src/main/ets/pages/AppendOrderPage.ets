import { promptAction } from '@kit.ArkUI';
import { UserApi, OrderItemIn } from '../common/UserApi';
import { ApiException } from '../common/Api';
import { isPaid, payOrder } from '../common/Pay';
import { Dish, Order } from '../model/Models';
import { yuan } from '../common/Money';

/**
 * 加菜。
 *
 * 关联原单、**免配送费**、随原单配送、骑手也是原来那个 ——
 * 所以只在原单还没被取走之前有意义。原单取消则级联取消。
 *
 * 这一页不做规格:加菜是"临时想起来还要个可乐"的场景,
 * 要挑规格的菜让用户回店铺页正常点更清楚。
 */
@Component
export struct AppendOrderPage {
  parentOrderNo: string = '';
  merchantId: number = 0;
  onPaid: (orderNo: string) => void = () => {};

  @State private dishes: Dish[] = [];
  @State private picked: Map<number, number> = new Map();
  @State private version: number = 0;
  @State private loading: boolean = true;
  @State private error: string = '';
  @State private submitting: boolean = false;

  private api: UserApi = new UserApi();

  async aboutToAppear(): Promise<void> {
    this.loading = true;
    try {
      this.dishes = await this.api.menu(this.merchantId);
    } catch (e) {
      this.error = (e as ApiException).message;
    } finally {
      this.loading = false;
    }
  }

  private qty(id: number): number {
    return this.picked.get(id) ?? 0;
  }

  private change(d: Dish, delta: number): void {
    const q: number = this.qty(d.id) + delta;
    if (q <= 0) {
      this.picked.delete(d.id);
    } else {
      const stock: number = d.stock ?? -1;
      if (stock >= 0 && q > stock) {
        promptAction.showToast({ message: `${d.name} 只剩 ${stock} 份了` });
        return;
      }
      this.picked.set(d.id, q);
    }
    this.version += 1; // Map 改了不触发重绘,用计数器顶一下
  }

  private get total(): number {
    let sum: number = 0;
    for (let i = 0; i < this.dishes.length; i++) {
      const d: Dish = this.dishes[i];
      sum += d.price_cents * this.qty(d.id);
    }
    return sum;
  }

  private get count(): number {
    let n: number = 0;
    this.picked.forEach((v: number) => { n += v; });
    return n;
  }

  private async submit(): Promise<void> {
    if (this.count === 0 || this.submitting) {
      return;
    }
    this.submitting = true;
    try {
      const items: OrderItemIn[] = [];
      this.picked.forEach((q: number, id: number) => {
        items.push({ dish_id: id, quantity: q });
      });
      const order: Order = await this.api.appendOrder(
        this.parentOrderNo, this.merchantId, items);
      // 加菜单同样是待支付建出来的,不接支付就会被自动清扫
      const after: Order = await payOrder(this.api, order);
      this.onPaid(after.order_no);
      if (!isPaid(after)) {
        promptAction.showToast({
          message: '加菜单已保留为「待支付」,可在订单列表继续支付',
          duration: 3500,
        });
      }
    } catch (e) {
      promptAction.showToast({ message: (e as ApiException).message, duration: 4000 });
    } finally {
      this.submitting = false;
    }
  }

  build() {
    Column() {
      Text('加菜免配送费,和原单一起送')
        .fontSize(12).fontColor($r('app.color.earn'))
        .width('100%').padding({ left: 16, right: 16, top: 10, bottom: 8 });

      if (this.loading) {
        Column() { LoadingProgress().width(36).height(36); }
        .width('100%').layoutWeight(1).justifyContent(FlexAlign.Center);
      } else if (this.error.length > 0) {
        Column() {
          Text(this.error).fontSize(14).fontColor($r('app.color.ink_muted'));
        }
        .width('100%').layoutWeight(1).justifyContent(FlexAlign.Center);
      } else {
        List({ space: 1 }) {
          ForEach(this.dishes, (d: Dish) => {
            ListItem() {
              Row({ space: 12 }) {
                Column({ space: 3 }) {
                  Text(d.name).fontSize(15).fontColor($r('app.color.ink'));
                  Text(yuan(d.price_cents))
                    .fontSize(14).fontColor($r('app.color.brand'));
                }
                .layoutWeight(1).alignItems(HorizontalAlign.Start);
                if (d.sold_out === true) {
                  Text('售罄').fontSize(12).fontColor($r('app.color.ink_muted'));
                } else {
                  Row({ space: 8 }) {
                    if (this.qty(d.id) > 0) {
                      Button('−').width(28).height(28).fontSize(16)
                        .backgroundColor($r('app.color.surface_alt'))
                        .fontColor($r('app.color.ink'))
                        .onClick(() => { this.change(d, -1); });
                      Text(`${this.qty(d.id)}`).fontSize(14);
                    }
                    Button('+').width(28).height(28).fontSize(16)
                      .backgroundColor($r('app.color.brand'))
                      .onClick(() => { this.change(d, 1); });
                  }
                }
              }
              .width('100%')
              .padding({ left: 16, right: 16, top: 12, bottom: 12 })
              .backgroundColor($r('app.color.surface'));
            }
          }, (d: Dish) => `${d.id}-${this.version}`);
        }
        .width('100%').layoutWeight(1).scrollBar(BarState.Off);

        Row() {
          Text(this.count > 0 ? yuan(this.total) : '还没选菜')
            .fontSize(17).fontWeight(FontWeight.Bold)
            .fontColor($r('app.color.ink')).layoutWeight(1);
          Button(this.submitting ? '提交中…' : `加 ${this.count} 份`)
            .width(120).height(44)
            .enabled(this.count > 0 && !this.submitting)
            .backgroundColor(this.count > 0
              ? $r('app.color.brand') : $r('app.color.line'))
            .onClick(() => { this.submit(); });
        }
        .width('100%').padding(12).backgroundColor($r('app.color.surface'))
        .border({ width: { top: 1 }, color: $r('app.color.line') });
      }
    }
    .width('100%').height('100%').backgroundColor($r('app.color.page'));
  }
}

/**
 * 我的食安投诉。
 *
 * 投诉能提交却查不到进度,用户交完照片就没下文了 —— 对一个把食安
 * 当卖点的平台,投诉黑洞比没有投诉入口更伤。
 *
 * **不认定的那一档照实写**,不粉饰成"已处理"。这一页的可信度
 * 全靠它敢显示对用户不利的结果。
 */
@Component
export struct FoodSafetyRecordsPage {
  @State private rows: Record<string, Object>[] = [];
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
      this.rows = await this.api.myFoodSafetyReports();
    } catch (e) {
      this.error = (e as ApiException).message;
    } finally {
      this.loading = false;
    }
  }

  private str(m: Record<string, Object>, key: string): string {
    const v: Object = m[key] ?? '';
    return typeof v === 'string' ? v : '';
  }

  private kindLabel(k: string): string {
    if (k === 'foreign_object') {
      return '异物';
    }
    if (k === 'spoiled') {
      return '变质';
    }
    if (k === 'sick') {
      return '食用后不适';
    }
    return '食安问题';
  }

  private statusLabel(s: string): string {
    if (s === 'confirmed') {
      return '投诉成立,平台已处理';
    }
    if (s === 'dismissed') {
      return '调查后未认定';
    }
    return '平台受理中';
  }

  private latestNote(m: Record<string, Object>): string {
    const v: Object = m['actions'] ?? [];
    const arr: Object[] = v as Object[];
    if (arr.length === 0) {
      return '';
    }
    const last: Record<string, Object> = arr[arr.length - 1] as Record<string, Object>;
    const n: Object = last['note'] ?? '';
    return typeof n === 'string' ? n : '';
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
      } else if (this.rows.length === 0) {
        Column() {
          Text('你还没有提交过食安投诉')
            .fontSize(14).fontColor($r('app.color.ink_muted'));
        }
        .width('100%').layoutWeight(1).justifyContent(FlexAlign.Center);
      } else {
        List({ space: 10 }) {
          ForEach(this.rows, (m: Record<string, Object>) => {
            ListItem() {
              Column({ space: 6 }) {
                Row() {
                  Text(`${this.kindLabel(this.str(m, 'kind'))} · 订单 ${this.str(m, 'order_no')}`)
                    .fontSize(14).fontWeight(FontWeight.Medium)
                    .fontColor($r('app.color.ink')).layoutWeight(1)
                    .maxLines(1).textOverflow({ overflow: TextOverflow.Ellipsis });
                  Text(this.statusLabel(this.str(m, 'status')))
                    .fontSize(12)
                    .fontColor(this.str(m, 'status') === 'confirmed'
                      ? $r('app.color.earn') : $r('app.color.ink_muted'));
                }
                .width('100%');
                Text(this.str(m, 'description'))
                  .fontSize(12).fontColor($r('app.color.ink_muted'))
                  .maxLines(3).textOverflow({ overflow: TextOverflow.Ellipsis })
                  .width('100%');
                if (this.latestNote(m).length > 0) {
                  Text(`平台回复:${this.latestNote(m)}`)
                    .fontSize(12).fontColor($r('app.color.ink')).width('100%');
                }
              }
              .width('100%').padding(14).backgroundColor($r('app.color.surface'))
              .borderRadius(14).alignItems(HorizontalAlign.Start);
            }
          }, (m: Record<string, Object>) => this.str(m, 'order_no') + this.str(m, 'kind'));
        }
        .width('100%').layoutWeight(1)
        .padding({ left: 12, right: 12, top: 12, bottom: 12 })
        .scrollBar(BarState.Off);
      }
    }
    .width('100%').height('100%').backgroundColor($r('app.color.page'));
  }
}
