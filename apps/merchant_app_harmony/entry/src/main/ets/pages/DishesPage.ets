import { promptAction } from '@kit.ArkUI';
import { MerchantApi } from '../common/MerchantApi';
import { ApiException } from '../common/Api';
import { ArrayDataSource } from '../common/DataSource';
import { yuan } from '../common/Money';
import { Dish } from '../model/Models';

/**
 * 拍平后的一行:要么是分类标题,要么是一道菜。
 *
 * 「分类嵌菜品」是两层结构,没法直接交给 `LazyForEach`。
 * 拍成一维才能按需构建 —— 菜单上百道时,一次性建完首帧就卡,
 * **而卡的时候商家正在接单**。
 */
interface MenuRow {
  /** 非空 = 这是分类标题行 */
  category?: string;
  dish?: Dish;
  /** 同分类的菜。置顶要靠它算最小 sort */
  siblings: Dish[];
}

/**
 * 菜品管理。
 *
 * ## 长按始终是置顶
 *
 * 这是上一版就教给商家的手势。改成「第一次长按进多选、第二次才置顶」
 * 会让老用户按肌肉记忆连按两下,结果置顶了错的那道菜 —— **写库且无撤销**。
 * 多选走顶部显式的「批量」按钮进入。
 *
 * ## 估清不是下架
 *
 * 估清 = 今日售罄,次日 04:00 自动恢复;下架 = 一直不卖。
 * 两个词在界面上必须分得开,混了商家第二天会发现招牌菜没上架。
 */
@Component
export struct DishesPage {

  @State private dishes: Dish[] = [];
  @State private loaded: boolean = false;
  @State private errorText: string = '';
  @State private selecting: boolean = false;
  @State private selected: number[] = [];
  @State private batching: boolean = false;
  @State private busyId: number = 0;

  private api: MerchantApi = new MerchantApi();
  private ds: ArrayDataSource<MenuRow> = new ArrayDataSource<MenuRow>();
  /** 备货建议。拉不到不影响改菜单,所以单独存、单独兜底 */
  @State private stocking: Record<string, Object> | null = null;

  aboutToAppear(): void {
    this.load();
  }

  /**
   * 拉菜单。
   *
   * ⚠️ 失败时**不能**留在「还没有菜品」那一屏 —— 那句话会让商家以为
   * 菜真的没了,跑去重新录一遍。
   */
  private async load(): Promise<void> {
    // 两个请求互不依赖,先都发出去再逐个 await
    const dishesF: Promise<Dish[]> = this.api.myDishes();
    const stockingF: Promise<Record<string, Object>> =
        this.api.merchantStocking();

    // 备货建议是附加信息:先接住它的异常,免得没人 await 之前
    // 就变成未处理的异步错误
    let stocking: Record<string, Object> | null = this.stocking;
    try {
      stocking = await stockingF;
    } catch (_) {
      // 拉不到只是少显示一块,不拦着改菜单
    }

    try {
      this.dishes = await dishesF;
      this.stocking = stocking;
      this.errorText = '';
      this.rebuild();
    } catch (e) {
      this.errorText = (e as ApiException).message;
    } finally {
      this.loaded = true;
    }
  }

  /** 按分类分组再拍平。保持服务端返回的顺序 */
  private rebuild(): void {
    const groups: Map<string, Dish[]> = new Map<string, Dish[]>();
    const order: string[] = [];
    for (let i: number = 0; i < this.dishes.length; i++) {
      const d: Dish = this.dishes[i];
      const key: string = (d.category ?? '').length === 0
          ? '未分类' : (d.category as string);
      if (!groups.has(key)) {
        groups.set(key, []);
        order.push(key);
      }
      (groups.get(key) as Dish[]).push(d);
    }
    const rows: MenuRow[] = [];
    for (let i: number = 0; i < order.length; i++) {
      const key: string = order[i];
      const list: Dish[] = groups.get(key) as Dish[];
      rows.push({ category: key, siblings: list });
      for (let j: number = 0; j < list.length; j++) {
        rows.push({ dish: list[j], siblings: list });
      }
    }
    this.ds.reload(rows);
  }

  // ---------- 动作 ----------

  private async toggleOnSale(d: Dish, on: boolean): Promise<void> {
    this.busyId = d.id;
    try {
      await this.api.updateDish(d.id, { is_on_sale: on } as object);
      await this.load();
    } catch (e) {
      promptAction.showToast({ message: (e as ApiException).message });
    } finally {
      this.busyId = 0;
    }
  }

  private async sellOut(d: Dish): Promise<void> {
    this.busyId = d.id;
    try {
      await this.api.sellOutDish(d.id);
      await this.load();
      promptAction.showToast({
        message: `「${d.name}」已估清,明天 4 点自动恢复`,
      });
    } catch (e) {
      promptAction.showToast({ message: (e as ApiException).message });
    } finally {
      this.busyId = 0;
    }
  }

  private async cancelSellOut(d: Dish): Promise<void> {
    this.busyId = d.id;
    try {
      const r: Dish = await this.api.cancelSellOut(d.id);
      await this.load();
      promptAction.showToast({
        message: `「${d.name}」已恢复,库存 ${r.stock ?? 0}`,
      });
    } catch (e) {
      promptAction.showToast({ message: (e as ApiException).message });
    } finally {
      this.busyId = 0;
    }
  }

  private async restock(d: Dish): Promise<void> {
    this.busyId = d.id;
    try {
      await this.api.updateDish(d.id, { stock: 100 } as object);
      await this.load();
      promptAction.showToast({ message: `「${d.name}」已补货至 100` });
    } catch (e) {
      promptAction.showToast({ message: (e as ApiException).message });
    } finally {
      this.busyId = 0;
    }
  }

  /**
   * 置顶:排到本分类最前。
   *
   * **只改这一道的 sort,不整体重排** —— 一次请求,失败也不会打乱既有顺序。
   */
  private async pinToTop(d: Dish, siblings: Dish[]): Promise<void> {
    if (siblings.length > 0 && siblings[0].id === d.id) {
      promptAction.showToast({ message: `「${d.name}」已经在最前面了` });
      return;
    }
    let minSort: number = 0;
    for (let i: number = 0; i < siblings.length; i++) {
      const s: number = siblings[i].sort ?? 0;
      if (s < minSort) {
        minSort = s;
      }
    }
    const next: number = Math.max(-9999, Math.min(9999, minSort - 1));
    try {
      await this.api.reorderDishes([{ dish_id: d.id, sort: next } as object]);
      await this.load();
      promptAction.showToast({
        message: `「${d.name}」已置顶到「${d.category ?? '未分类'}」最前`,
      });
    } catch (e) {
      promptAction.showToast({ message: (e as ApiException).message });
    }
  }

  private toggleSelect(d: Dish): void {
    const i: number = this.selected.indexOf(d.id);
    if (i >= 0) {
      this.selected.splice(i, 1);
    } else {
      this.selected.push(d.id);
    }
    // ArkTS 的 @State 数组要整个换掉才会触发刷新
    this.selected = this.selected.slice();
  }

  private exitSelect(): void {
    this.selecting = false;
    this.selected = [];
  }

  /**
   * 批量执行:逐个调既有接口(菜品几十道,不值得为此加批量端点)。
   *
   * 单个失败不中断其余,最后汇总告诉商家成功几道。
   * [skip] 命中的直接跳过且**不计失败** —— 批量估清一批混合状态的菜时,
   * 已估清的那几道会被服务端 409 拒,算成「失败 2 道」会让商家以为出了故障。
   */
  private async batch(label: string, act: (id: number) => Promise<void>,
                      skip?: (d: Dish) => boolean): Promise<void> {
    const byId: Map<number, Dish> = new Map<number, Dish>();
    for (let i: number = 0; i < this.dishes.length; i++) {
      byId.set(this.dishes[i].id, this.dishes[i]);
    }
    const ids: number[] = [];
    for (let i: number = 0; i < this.selected.length; i++) {
      const d: Dish | undefined = byId.get(this.selected[i]);
      if (d === undefined) {
        continue;
      }
      if (skip !== undefined && skip(d)) {
        continue;
      }
      ids.push(d.id);
    }
    if (ids.length === 0) {
      this.exitSelect();
      promptAction.showToast({ message: `${label}:选中的菜已经是这个状态了` });
      return;
    }

    this.batching = true;
    let ok: number = 0;
    let failed: number = 0;
    for (let i: number = 0; i < ids.length; i++) {
      try {
        await act(ids[i]);
        ok += 1;
      } catch (_) {
        failed += 1;
      }
    }
    this.batching = false;
    this.exitSelect();
    await this.load();
    promptAction.showToast({
      message: failed === 0
          ? `${label}:${ok} 道已处理`
          : `${label}:成功 ${ok} 道,失败 ${failed} 道`,
    });
  }

  // ---------- 界面 ----------

  private stockShort(): Record<string, Object>[] {
    const st: Record<string, Object> | null = this.stocking;
    if (st === null) {
      return [];
    }
    const raw: Object | undefined = st['shortlist'];
    return (raw === undefined ? [] : raw) as Record<string, Object>[];
  }

  private priceText(d: Dish): string {
    const eff: number = d.effective_price_cents ?? d.price_cents;
    const flash: string = d.flash_active === true
        ? `(限时中,原价 ${yuan(d.price_cents)})` : '';
    const stock: string = d.sold_out_today === true
        ? '今日售罄(明日自动恢复)'
        : (d.stock ?? 0) === 0 ? '已售罄' : `库存 ${d.stock ?? 0}`;
    const daily: string = d.daily_stock === undefined
        ? '' : ` · 每日回满${d.daily_stock}`;
    return `${yuan(eff)}${flash} · ${stock}${daily} · 月售 ${d.monthly_sales ?? 0}`;
  }

  @Builder
  private header() {
    Row({ space: 10 }) {
      Text('菜品管理')
        .fontSize(17).fontWeight(FontWeight.Bold)
        .fontColor($r('app.color.ink')).layoutWeight(1);
      if (!this.selecting) {
        Text('批量')
          .fontSize(14).fontColor($r('app.color.brand'))
          .onClick(() => { this.selecting = true; });
      } else {
        Text('取消')
          .fontSize(14).fontColor($r('app.color.ink_muted'))
          .onClick(() => { this.exitSelect(); });
      }
    }
    .width('100%')
    .padding({ left: 14, right: 14, top: 10, bottom: 10 })
    .backgroundColor($r('app.color.surface'));
  }

  @Builder
  private stockingCard() {
    Column({ space: 6 }) {
      Text(`${this.stocking?.['meal_label'] ?? ''}备货提示(近 14 天同餐段销量估算)`)
        .fontSize(13).fontWeight(FontWeight.Medium)
        .fontColor($r('app.color.hold')).width('100%');
      ForEach(this.stockShort(), (s: Record<string, Object>) => {
        Row() {
          Text(`${s['name']}`).fontSize(13)
            .fontColor($r('app.color.ink')).layoutWeight(1);
          Text(`现 ${s['stock']} → 建议 ${s['suggested']} 份`)
            .fontSize(12).fontColor($r('app.color.ink_muted'));
        }
        .width('100%');
      }, (s: Record<string, Object>) => `${s['dish_id']}`);
      Text('纯建议,不会自动改库存')
        .fontSize(11).fontColor($r('app.color.ink_muted')).width('100%');
    }
    .width('100%').padding(12)
    .backgroundColor($r('app.color.surface_alt')).borderRadius(10)
    .margin({ bottom: 10 });
  }

  @Builder
  private dishRow(row: MenuRow) {
    if (row.category !== undefined) {
      Text(row.category)
        .fontSize(13).fontWeight(FontWeight.Medium)
        .fontColor($r('app.color.brand'))
        .width('100%')
        .padding({ left: 4, top: 12, bottom: 6 });
    } else {
      Row({ space: 10 }) {
        if (this.selecting) {
          Text(this.selected.indexOf((row.dish as Dish).id) >= 0 ? '☑' : '☐')
            .fontSize(20)
            .fontColor(this.selected.indexOf((row.dish as Dish).id) >= 0
              ? $r('app.color.brand') : $r('app.color.ink_faint'));
        }
        Column({ space: 3 }) {
          Row({ space: 6 }) {
            Text((row.dish as Dish).name)
              .fontSize(15)
              .fontColor((row.dish as Dish).is_on_sale === false
                ? $r('app.color.ink_muted') : $r('app.color.ink'))
              .decoration({
                type: (row.dish as Dish).is_on_sale === false
                  ? TextDecorationType.LineThrough : TextDecorationType.None,
              });
            // 缺图提成 chip:占位图再好看也不如让商家把图补上
            if (((row.dish as Dish).image_url ?? '').length === 0) {
              Text('缺图')
                .fontSize(10).fontColor($r('app.color.hold'))
                .padding({ left: 5, right: 5, top: 1, bottom: 1 })
                .borderRadius(4)
                .backgroundColor($r('app.color.surface_alt'));
            }
          }
          .width('100%');
          Text(this.priceText(row.dish as Dish))
            .fontSize(12)
            .fontColor((row.dish as Dish).stock === 0
              ? $r('app.color.danger') : $r('app.color.ink_muted'));
        }
        .alignItems(HorizontalAlign.Start).layoutWeight(1);

        if (!this.selecting) {
          this.rowActions(row.dish as Dish);
        }
      }
      .width('100%')
      .padding({ left: 4, right: 4, top: 10, bottom: 10 })
      .onClick(() => {
        if (this.selecting) {
          this.toggleSelect(row.dish as Dish);
        }
      })
      // **长按始终是置顶**,不重载成"进多选"
      .gesture(LongPressGesture().onAction(() => {
        if (!this.selecting && !this.batching) {
          this.pinToTop(row.dish as Dish, row.siblings);
        }
      }));
      Divider().color($r('app.color.line'));
    }
  }

  @Builder
  private rowActions(d: Dish) {
    Row({ space: 6 }) {
      if (d.is_on_sale !== false) {
        if (d.sold_out_today === true) {
          Button('恢复')
            .fontSize(12).height(30).padding({ left: 10, right: 10 })
            .backgroundColor($r('app.color.surface_alt'))
            .fontColor($r('app.color.ink'))
            .enabled(this.busyId === 0)
            .onClick(() => { this.cancelSellOut(d); });
        } else if ((d.stock ?? 0) > 0) {
          Button('估清')
            .fontSize(12).height(30).padding({ left: 10, right: 10 })
            .backgroundColor($r('app.color.surface_alt'))
            .fontColor($r('app.color.ink'))
            .enabled(this.busyId === 0)
            .onClick(() => { this.sellOut(d); });
        } else {
          Button('补货')
            .fontSize(12).height(30).padding({ left: 10, right: 10 })
            .backgroundColor($r('app.color.surface_alt'))
            .fontColor($r('app.color.ink'))
            .enabled(this.busyId === 0)
            .onClick(() => { this.restock(d); });
        }
      }
      // 读屏只念"开关"的话,不知道是哪道菜的。
      // 上下架直接决定这道菜能不能被点,按错了整天卖不出去
      Toggle({ type: ToggleType.Switch, isOn: d.is_on_sale !== false })
        .selectedColor($r('app.color.brand'))
        .enabled(this.busyId === 0 && !this.batching)
        .accessibilityText(`${d.name} ${d.is_on_sale !== false ? '在售' : '已下架'}`)
        .onChange((on: boolean) => { this.toggleOnSale(d, on); });
    }
  }

  @Builder
  private batchBar() {
    Row({ space: 8 }) {
      Text(`已选 ${this.selected.length}`)
        .fontSize(13).fontColor($r('app.color.ink'));
      Blank();
      Button('估清')
        .fontSize(13).height(34)
        .backgroundColor($r('app.color.surface_alt'))
        .fontColor($r('app.color.ink'))
        .enabled(!this.batching && this.selected.length > 0)
        .onClick(() => {
          // 已估清/已售罄的跳过:服务端会 409,
          // 算进"失败"会让商家以为出了故障
          this.batch('估清', (id: number) => this.api.sellOutDish(id)
              .then(() => {}),
            (d: Dish) => d.sold_out_today === true
              || d.is_on_sale === false || (d.stock ?? 0) <= 0);
        });
      Button('下架')
        .fontSize(13).height(34)
        .backgroundColor($r('app.color.surface_alt'))
        .fontColor($r('app.color.ink'))
        .enabled(!this.batching && this.selected.length > 0)
        .onClick(() => {
          this.batch('下架', (id: number) =>
            this.api.updateDish(id, { is_on_sale: false } as object)
              .then(() => {}),
            (d: Dish) => d.is_on_sale === false);
        });
      Button('上架')
        .fontSize(13).height(34)
        .backgroundColor($r('app.color.brand'))
        .enabled(!this.batching && this.selected.length > 0)
        .onClick(() => {
          this.batch('上架', (id: number) =>
            this.api.updateDish(id, { is_on_sale: true } as object)
              .then(() => {}),
            (d: Dish) => d.is_on_sale !== false);
        });
    }
    .width('100%')
    .padding({ left: 14, right: 14, top: 8, bottom: 14 })
    .backgroundColor($r('app.color.surface'));
  }

  build() {
    Column() {
      this.header();

      if (!this.loaded) {
        Column() {
          LoadingProgress().width(40).height(40);
        }
        .layoutWeight(1).justifyContent(FlexAlign.Center);
      } else if (this.errorText.length > 0) {
        // 「还没有菜品」和「没拉到」在这一页含义天差地别
        Column({ space: 12 }) {
          Text('菜单没能加载出来')
            .fontSize(15).fontColor($r('app.color.ink'));
          Text(this.errorText)
            .fontSize(13).fontColor($r('app.color.ink_muted'))
            .textAlign(TextAlign.Center);
          Button('重试')
            .height(40).width(130)
            .backgroundColor($r('app.color.brand'))
            .onClick(() => { this.load(); });
        }
        .layoutWeight(1).justifyContent(FlexAlign.Center).padding(30);
      } else if (this.dishes.length === 0) {
        Column({ space: 10 }) {
          Text('还没有菜品')
            .fontSize(15).fontColor($r('app.color.ink_muted'));
        }
        .layoutWeight(1).justifyContent(FlexAlign.Center);
      } else {
        Column() {
          Text(`共 ${this.dishes.length} 道 · 长按可置顶`)
            .fontSize(12).fontColor($r('app.color.ink_muted'))
            .width('100%').padding({ left: 4, top: 8, bottom: 4 });
          if (this.stockShort().length > 0) {
            this.stockingCard();
          }
          List() {
            LazyForEach(this.ds, (row: MenuRow) => {
              ListItem() {
                this.dishRow(row);
              }
            }, (row: MenuRow) =>
              row.category !== undefined
                ? `c-${row.category}`
                : `d-${(row.dish as Dish).id}-${(row.dish as Dish).is_on_sale}`
                  + `-${(row.dish as Dish).stock}`);
          }
          .layoutWeight(1).width('100%').scrollBar(BarState.Off);
        }
        .layoutWeight(1).width('100%')
        .padding({ left: 12, right: 12 });
      }

      if (this.selecting) {
        this.batchBar();
      }
    }
    .width('100%').height('100%')
    .backgroundColor($r('app.color.page'));
  }
}
