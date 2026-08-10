import { promptAction } from '@kit.ArkUI';
import { UserApi, CartItemIn } from '../common/UserApi';
import { ApiException } from '../common/Api';
import { Session } from '../common/Session';
import { Dish, DishChoice, DishOptionGroup, Merchant, Review } from '../model/Models';
import { CartLine, choicesLabel, foodCents, lineKey, manjianCents,
  packingCents, unitCents } from '../common/Cart';
import { yuan } from '../common/Money';

/**
 * 平台起送价下限。
 *
 * ⚠️ 这是服务端 `config.py` 的 `min_order_cents` 的**副本**,改那边要改这边。
 * 服务端下单时取 `max(商家设的起送价, 这个下限)`,而商家很可能没设 ——
 * 客户端只比商家那个值的话,「去结算」按钮可点、提交必被 409 打回。
 * 安卓端就踩过这个,表现是用户凑够了商家写的起送价却下不了单。
 *
 * 更干净的做法是服务端把它下发出来,那样两边不会分叉;
 * 在接口加这个字段之前,这里先照抄并标明出处。
 */
const PLATFORM_MIN_ORDER_CENTS: number = 1500;
/** 云端车保存防抖。每次加减都发一次请求是没必要的 */
const CART_SAVE_DEBOUNCE_MS: number = 800;

@Component
export struct MerchantPage {
  merchantId: number = 0;
  onCheckout: (merchant: Merchant, lines: CartLine[]) => void = () => {};

  @State private merchant: Merchant | null = null;
  @State private dishes: Dish[] = [];
  @State private lines: CartLine[] = [];
  @State private frequent: Dish[] = [];
  @State private favorite: boolean = false;
  @State private loading: boolean = true;
  @State private error: string = '';
  /** 正在选规格的菜。null = 不显示规格面板 */
  @State private optionDish: Dish | null = null;
  @State private optionPicked: string[] = [];
  /** 0 点餐 / 1 评价 */
  @State private tab: number = 0;
  @State private reviews: Review[] = [];
  @State private claimable: Record<string, Object>[] = [];

  private api: UserApi = new UserApi();
  private saveTimer: number = -1;

  async aboutToAppear(): Promise<void> {
    await this.load();
  }

  aboutToDisappear(): void {
    if (this.saveTimer >= 0) {
      clearTimeout(this.saveTimer);
      this.saveTimer = -1;
    }
  }

  private async load(): Promise<void> {
    this.loading = true;
    this.error = '';
    try {
      // 互不依赖的请求并发发,串起来等于让用户白等几个来回
      const detailP: Promise<Merchant> = this.api.merchantDetail(this.merchantId);
      const menuP: Promise<Dish[]> = this.api.menu(this.merchantId);
      this.merchant = await detailP;
      this.dishes = await menuP;
      if (Session.get().isLoggedIn) {
        await this.restoreCart();
        try {
          this.frequent = await this.api.frequentDishes(this.merchantId);
        } catch (e) {
          this.frequent = []; // 常买拉不到不影响点餐
        }
        try {
          const ids: number[] = await this.api.favoriteIds();
          this.favorite = ids.indexOf(this.merchantId) >= 0;
        } catch (e) {
          this.favorite = false;
        }
        // 可领券只在店铺页看得见,拉不到不影响点餐
        this.api.claimableShopCoupons(this.merchantId)
          .then((c: Record<string, Object>[]) => { this.claimable = c; })
          .catch(() => {});
      }
      // 评价是新店唯一的信任来源,和菜单一起拉
      this.api.merchantReviews(this.merchantId)
        .then((r: Review[]) => { this.reviews = r; })
        .catch(() => {});
    } catch (e) {
      this.error = (e as ApiException).message;
    } finally {
      this.loading = false;
    }
  }

  /**
   * 从云端车恢复。**只恢复还在售、库存够的菜** ——
   * 上次加的菜今天下架了还留在车里,用户到结算才被 409 打回
   */
  private async restoreCart(): Promise<void> {
    try {
      const saved: CartItemIn[] = await this.api.getCart(this.merchantId);
      const next: CartLine[] = [];
      for (let i = 0; i < saved.length; i++) {
        const it: CartItemIn = saved[i];
        const dish: Dish | undefined = this.dishes.find(
          (d: Dish) => d.id === it.dish_id);
        if (dish === undefined || dish.sold_out === true) {
          continue;
        }
        next.push({ dish: dish, quantity: it.quantity, choices: it.choices ?? [] });
      }
      this.lines = next;
    } catch (e) {
      // 游客没有云端车(服务端要 customer 角色),不是错误
    }
  }

  /** 防抖保存。整份覆盖,空数组 = 清空该店的车 */
  private scheduleSave(): void {
    if (!Session.get().isLoggedIn) {
      return;
    }
    if (this.saveTimer >= 0) {
      clearTimeout(this.saveTimer);
    }
    this.saveTimer = setTimeout(() => {
      const items: CartItemIn[] = [];
      for (let i = 0; i < this.lines.length; i++) {
        items.push({
          dish_id: this.lines[i].dish.id,
          quantity: this.lines[i].quantity,
          choices: this.lines[i].choices,
        });
      }
      this.api.putCart(this.merchantId, items).catch(() => {
        // 存不上不打扰用户:车还在内存里,下单照常
      });
      this.saveTimer = -1;
    }, CART_SAVE_DEBOUNCE_MS);
  }

  private qtyOfKey(key: string): number {
    for (let i = 0; i < this.lines.length; i++) {
      const l: CartLine = this.lines[i];
      if (lineKey(l.dish.id, l.choices) === key) {
        return l.quantity;
      }
    }
    return 0;
  }

  /** 这道菜(所有规格加起来)已经点了几份。库存要按这个判 */
  private qtyOfDish(dishId: number): number {
    let n: number = 0;
    for (let i = 0; i < this.lines.length; i++) {
      if (this.lines[i].dish.id === dishId) {
        n += this.lines[i].quantity;
      }
    }
    return n;
  }

  /**
   * 加减份数。**每次都重建数组**,否则 @State 不触发重绘。
   *
   * 加的时候校验库存 —— 安卓端在这里有 bug:走规格路径时直接 quantity++,
   * 绕过了无规格路径的库存拦截,结果车里能放下比库存还多的份数
   */
  private changeQty(dish: Dish, choices: string[], delta: number): void {
    if (delta > 0) {
      const stock: number = dish.stock ?? -1;
      if (stock >= 0 && this.qtyOfDish(dish.id) >= stock) {
        promptAction.showToast({ message: `${dish.name} 只剩 ${stock} 份了` });
        return;
      }
    }
    const key: string = lineKey(dish.id, choices);
    const next: CartLine[] = [];
    let found: boolean = false;
    for (let i = 0; i < this.lines.length; i++) {
      const l: CartLine = this.lines[i];
      if (lineKey(l.dish.id, l.choices) === key) {
        found = true;
        const q: number = l.quantity + delta;
        if (q > 0) {
          next.push({ dish: l.dish, quantity: q, choices: l.choices });
        }
      } else {
        next.push(l);
      }
    }
    if (!found && delta > 0) {
      next.push({ dish: dish, quantity: delta, choices: choices });
    }
    this.lines = next;
    this.scheduleSave();
  }

  /** 点「+」:有规格的先弹面板,没有的直接加 */
  private onPlus(dish: Dish): void {
    const groups: DishOptionGroup[] = dish.options ?? [];
    if (groups.length === 0) {
      this.changeQty(dish, [], 1);
      return;
    }
    // 必选组预选第一项,省一次点击;可多选组默认不选
    const preset: string[] = [];
    for (let g = 0; g < groups.length; g++) {
      const grp: DishOptionGroup = groups[g];
      if (grp.required === true && (grp.choices ?? []).length > 0) {
        preset.push(grp.choices[0].name);
      }
    }
    this.optionPicked = preset;
    this.optionDish = dish;
  }

  private toggleChoice(group: DishOptionGroup, name: string): void {
    const multi: boolean = group.multi === true;
    const picked: string[] = this.optionPicked.slice();
    const groupNames: string[] = (group.choices ?? []).map(
      (c: DishChoice) => c.name);
    if (picked.indexOf(name) >= 0) {
      // 必选组不允许取消到空
      if (group.required === true && !multi) {
        return;
      }
      this.optionPicked = picked.filter((n: string) => n !== name);
      return;
    }
    const kept: string[] = multi
      ? picked
      : picked.filter((n: string) => groupNames.indexOf(n) < 0);
    kept.push(name);
    this.optionPicked = kept;
  }

  /** 规格面板里的实时单价,让用户在确认之前就知道要花多少 */
  private previewUnit(dish: Dish): number {
    const line: CartLine = { dish: dish, quantity: 1, choices: this.optionPicked };
    return unitCents(line);
  }

  private confirmOptions(): void {
    const dish: Dish | null = this.optionDish;
    if (dish === null) {
      return;
    }
    // 必选组必须都选到了才让确认 —— 服务端会以 422 拒绝,提前挡住
    const groups: DishOptionGroup[] = dish.options ?? [];
    for (let g = 0; g < groups.length; g++) {
      const grp: DishOptionGroup = groups[g];
      if (grp.required !== true) {
        continue;
      }
      const names: string[] = (grp.choices ?? []).map((c: DishChoice) => c.name);
      const hit: boolean = this.optionPicked.some(
        (n: string) => names.indexOf(n) >= 0);
      if (!hit) {
        promptAction.showToast({ message: `请选择${grp.name}` });
        return;
      }
    }
    this.changeQty(dish, this.optionPicked, 1);
    this.optionDish = null;
    this.optionPicked = [];
  }

  private async toggleFavorite(): Promise<void> {
    if (!Session.get().isLoggedIn) {
      promptAction.showToast({ message: '登录后可以收藏' });
      return;
    }
    try {
      if (this.favorite) {
        await this.api.removeFavorite(this.merchantId);
        this.favorite = false;
      } else {
        await this.api.addFavorite(this.merchantId);
        this.favorite = true;
        promptAction.showToast({ message: '已收藏' });
      }
    } catch (e) {
      promptAction.showToast({ message: (e as ApiException).message });
    }
  }

  private get food(): number {
    return foodCents(this.lines);
  }

  private get minOrder(): number {
    const shopMin: number = this.merchant?.min_order_cents ?? 0;
    return Math.max(shopMin, PLATFORM_MIN_ORDER_CENTS);
  }

  private get canCheckout(): boolean {
    return this.lines.length > 0 && this.food >= this.minOrder
      && (this.merchant?.is_open ?? false);
  }

  @Builder
  private header(m: Merchant) {
    Column({ space: 8 }) {
      Row() {
        Text(m.name)
          .fontSize(20).fontWeight(FontWeight.Bold)
          .fontColor($r('app.color.ink')).layoutWeight(1);
        Text(this.favorite ? '已收藏' : '收藏')
          .fontSize(13)
          .fontColor(this.favorite
            ? $r('app.color.brand') : $r('app.color.ink_muted'))
          .onClick(() => { this.toggleFavorite(); });
      }
      .width('100%');

      Row({ space: 10 }) {
        if (m.rating_avg !== undefined && m.rating_avg !== null) {
          Text(`${m.rating_avg.toFixed(1)} 分`)
            .fontSize(12).fontColor($r('app.color.ink_muted'));
        }
        if (m.monthly_sales !== undefined && m.monthly_sales > 0) {
          Text(`月售 ${m.monthly_sales}`)
            .fontSize(12).fontColor($r('app.color.ink_muted'));
        }
        Text(`起送 ${yuan(this.minOrder)}`)
          .fontSize(12).fontColor($r('app.color.ink_muted'));
      }
      .width('100%');

      // 法定公示项:明厨亮灶与堂食标识,**两种都要标**
      Row({ space: 8 }) {
        Text(m.kitchen_cam_label ?? '无明厨亮灶')
          .fontSize(11)
          .fontColor(m.kitchen_cam === true
            ? $r('app.color.earn') : $r('app.color.ink_muted'));
        Text(m.dine_in_label ?? '未填报')
          .fontSize(11)
          .fontColor(m.dine_in_status === 'yes'
            ? $r('app.color.earn') : $r('app.color.ink_muted'));
      }
      .width('100%');

      if ((m.announcement ?? '').length > 0) {
        Text(m.announcement)
          .fontSize(12).fontColor($r('app.color.ink_muted')).width('100%');
      }

      // 把平台主张落到这一家店。抽象的「5% 封顶」在这里才有意义
      Text('这家店在超级赞只被抽 5%,省下的抽成让在了菜价上')
        .fontSize(12).fontColor($r('app.color.earn')).width('100%');

      if (!m.is_open) {
        Text('休息中,暂时不能下单')
          .fontSize(13).fontColor($r('app.color.brand')).width('100%');
      }
    }
    .width('100%').padding(16).backgroundColor($r('app.color.surface'))
    .alignItems(HorizontalAlign.Start);
  }

  @Builder
  private frequentRow() {
    if (this.frequent.length > 0) {
      Column({ space: 6 }) {
        Text('我常买')
          .fontSize(13).fontColor($r('app.color.ink_muted')).width('100%');
        Row({ space: 8 }) {
          ForEach(this.frequent, (d: Dish) => {
            Text(d.name)
              .fontSize(12)
              .fontColor($r('app.color.brand'))
              .padding({ left: 10, right: 10, top: 5, bottom: 5 })
              .borderRadius(12)
              .backgroundColor($r('app.color.brand_soft'))
              .onClick(() => { this.onPlus(d); });
          }, (d: Dish) => `freq-${d.id}`);
        }
        .width('100%');
      }
      .width('100%').padding(16).backgroundColor($r('app.color.surface'))
      .alignItems(HorizontalAlign.Start);
    }
  }

  private couponNum(c: Record<string, Object>, key: string): number {
    const v: Object = c[key] ?? 0;
    return typeof v === 'number' ? v : 0;
  }

  /** 可领券横条。**进店才看得见**,商家自己出的钱不该没人知道 */
  @Builder
  private claimStrip() {
    if (this.claimable.length > 0) {
      Row({ space: 8 }) {
        ForEach(this.claimable, (c: Record<string, Object>) => {
          Row({ space: 4 }) {
            Text(`${yuan(this.couponNum(c, 'amount_cents'))}`)
              .fontSize(13).fontColor($r('app.color.brand'));
            Text(this.couponNum(c, 'min_spend_cents') > 0
              ? `满${yuan(this.couponNum(c, 'min_spend_cents'))}` : '无门槛')
              .fontSize(11).fontColor($r('app.color.ink_muted'));
            Text('领')
              .fontSize(11).fontColor($r('app.color.brand'));
          }
          .padding({ left: 10, right: 10, top: 5, bottom: 5 })
          .borderRadius(12).backgroundColor($r('app.color.brand_soft'))
          .onClick(() => {
            this.api.claimShopCoupon(this.merchantId, this.couponNum(c, 'id'))
              .then(() => {
                promptAction.showToast({ message: '已领取,结算时自动用最优的' });
                this.claimable = this.claimable.filter(
                  (x: Record<string, Object>) =>
                    this.couponNum(x, 'id') !== this.couponNum(c, 'id'));
              })
              .catch((e: Object) => {
                promptAction.showToast({ message: (e as ApiException).message });
              });
          });
        }, (c: Record<string, Object>) => `${this.couponNum(c, 'id')}`);
      }
      .width('100%')
      .padding({ left: 16, right: 16, top: 8, bottom: 8 })
      .backgroundColor($r('app.color.surface'));
    }
  }

  @Builder
  private tabBar() {
    Row() {
      ForEach([0, 1], (i: number) => {
        Column({ space: 3 }) {
          Text(i === 0 ? '点餐' : `评价 ${this.reviews.length}`)
            .fontSize(14)
            .fontWeight(this.tab === i ? FontWeight.Medium : FontWeight.Normal)
            .fontColor(this.tab === i
              ? $r('app.color.brand') : $r('app.color.ink_muted'));
          Divider()
            .width(28).strokeWidth(2)
            .color(this.tab === i
              ? $r('app.color.brand') : Color.Transparent);
        }
        .layoutWeight(1)
        .onClick(() => { this.tab = i; });
      }, (i: number) => `${i}`);
    }
    .width('100%').padding({ top: 8, bottom: 4 })
    .backgroundColor($r('app.color.surface'));
  }

  @Builder
  private reviewRow(r: Review) {
    Column({ space: 4 }) {
      Row({ space: 8 }) {
        Text(r.is_anonymous === true ? '匿名用户' : (r.user_name ?? '用户'))
          .fontSize(13).fontColor($r('app.color.ink')).layoutWeight(1);
        Text(`${r.merchant_rating} 分`)
          .fontSize(12).fontColor($r('app.color.brand'));
      }
      .width('100%');
      if ((r.comment ?? '').length > 0) {
        Text(r.comment)
          .fontSize(13).fontColor($r('app.color.ink')).width('100%');
      }
      if ((r.append_comment ?? '').length > 0) {
        Text(`追评:${r.append_comment}`)
          .fontSize(12).fontColor($r('app.color.ink_muted')).width('100%');
      }
      if ((r.reply ?? '').length > 0) {
        Text(`商家回复:${r.reply}`)
          .fontSize(12).fontColor($r('app.color.earn')).width('100%');
      }
    }
    .width('100%')
    .padding({ left: 16, right: 16, top: 12, bottom: 12 })
    .backgroundColor($r('app.color.surface'))
    .alignItems(HorizontalAlign.Start);
  }

  @Builder
  private dishRow(d: Dish) {
    Column({ space: 4 }) {
      Row({ space: 12 }) {
        Column({ space: 4 }) {
          Text(d.name)
            .fontSize(15).fontColor($r('app.color.ink'))
            .maxLines(1).textOverflow({ overflow: TextOverflow.Ellipsis });
          if ((d.description ?? '').length > 0) {
            Text(d.description)
              .fontSize(12).fontColor($r('app.color.ink_muted'))
              .maxLines(1).textOverflow({ overflow: TextOverflow.Ellipsis });
          }
          Row({ space: 8 }) {
            Text(yuan(d.price_cents))
              .fontSize(15).fontColor($r('app.color.brand'));
            if ((d.options ?? []).length > 0) {
              Text('起').fontSize(11).fontColor($r('app.color.ink_muted'));
            }
            if ((d.stock ?? -1) >= 0 && (d.stock ?? 0) <= 5
              && d.sold_out !== true) {
              Text(`仅剩 ${d.stock}`)
                .fontSize(11).fontColor($r('app.color.brand'));
            }
          }
        }
        .layoutWeight(1).alignItems(HorizontalAlign.Start);

        if (d.sold_out === true) {
          Text('售罄').fontSize(12).fontColor($r('app.color.ink_muted'));
        } else {
          Row({ space: 8 }) {
            // 无规格的菜才在行内显示减号:有规格时车里可能有好几行,
            // 减哪一行说不清楚,统一到购物车里改
            if ((d.options ?? []).length === 0
              && this.qtyOfKey(lineKey(d.id, [])) > 0) {
              Button('−')
                .width(28).height(28).fontSize(16)
                .backgroundColor($r('app.color.line'))
                .fontColor($r('app.color.ink'))
                .onClick(() => { this.changeQty(d, [], -1); });
              Text(`${this.qtyOfKey(lineKey(d.id, []))}`).fontSize(14);
            } else if ((d.options ?? []).length > 0
              && this.qtyOfDish(d.id) > 0) {
              Text(`${this.qtyOfDish(d.id)}`)
                .fontSize(14).fontColor($r('app.color.brand'));
            }
            Button((d.options ?? []).length > 0 ? '选规格' : '+')
              .height(28)
              .width((d.options ?? []).length > 0 ? 64 : 28)
              .fontSize((d.options ?? []).length > 0 ? 12 : 16)
              .backgroundColor($r('app.color.brand'))
              // 一个光秃秃的「+」对读屏用户没有任何信息
              .accessibilityText(`把 ${d.name} 加进购物车,${yuan(d.price_cents)}`)
              .onClick(() => { this.onPlus(d); });
          }
        }
      }
      .width('100%');
    }
    .width('100%')
    .padding({ left: 16, right: 16, top: 12, bottom: 12 })
    .backgroundColor($r('app.color.surface'))
    .alignItems(HorizontalAlign.Start);
  }

  /** 规格面板。用页面内浮层而不是 Dialog,状态好管、也不怕上下文丢失 */
  @Builder
  private optionSheet(d: Dish) {
    Column() {
      Column({ space: 12 }) {
        Row() {
          Text(d.name)
            .fontSize(17).fontWeight(FontWeight.Medium)
            .fontColor($r('app.color.ink')).layoutWeight(1);
          Text('关闭')
            .fontSize(13).fontColor($r('app.color.ink_muted'))
            .onClick(() => {
              this.optionDish = null;
              this.optionPicked = [];
            });
        }
        .width('100%');

        ForEach(d.options ?? [], (g: DishOptionGroup) => {
          Column({ space: 8 }) {
            Row({ space: 6 }) {
              Text(g.name).fontSize(14).fontColor($r('app.color.ink'));
              if (g.required === true) {
                Text('必选').fontSize(11).fontColor($r('app.color.brand'));
              }
              if (g.multi === true) {
                Text('可多选').fontSize(11).fontColor($r('app.color.ink_muted'));
              }
            }
            .width('100%');
            Flex({ wrap: FlexWrap.Wrap }) {
              ForEach(g.choices ?? [], (c: DishChoice) => {
                Text((c.delta_cents ?? 0) > 0
                  ? `${c.name} +${yuan(c.delta_cents ?? 0)}` : c.name)
                  .fontSize(13)
                  .padding({ left: 12, right: 12, top: 6, bottom: 6 })
                  .margin({ right: 8, bottom: 8 })
                  .borderRadius(14)
                  .backgroundColor(this.optionPicked.indexOf(c.name) >= 0
                    ? $r('app.color.brand_soft') : $r('app.color.surface_alt'))
                  .fontColor(this.optionPicked.indexOf(c.name) >= 0
                    ? $r('app.color.brand') : $r('app.color.ink'))
                  .onClick(() => { this.toggleChoice(g, c.name); });
              }, (c: DishChoice) => `${g.name}-${c.name}`);
            }
            .width('100%');
          }
          .width('100%').alignItems(HorizontalAlign.Start);
        }, (g: DishOptionGroup) => g.name);

        Row() {
          Text(yuan(this.previewUnit(d)))
            .fontSize(18).fontWeight(FontWeight.Bold)
            .fontColor($r('app.color.brand')).layoutWeight(1);
          Button('加入购物车')
            .height(42).width(128)
            .backgroundColor($r('app.color.brand'))
            .onClick(() => { this.confirmOptions(); });
        }
        .width('100%').margin({ top: 4 });
      }
      .width('100%').padding(18)
      .backgroundColor($r('app.color.surface'))
      .borderRadius({ topLeft: 18, topRight: 18 })
      .alignItems(HorizontalAlign.Start);
    }
    .width('100%').height('100%')
    .justifyContent(FlexAlign.End)
    .backgroundColor($r('app.color.scrim'))
    .onClick(() => {
      this.optionDish = null;
      this.optionPicked = [];
    });
  }

  @Builder
  private cartBar(m: Merchant) {
    Column() {
      // 差多少起送:安卓端漏了这句,用户只能自己算
      if (this.lines.length > 0 && this.food < this.minOrder) {
        Text(`还差 ${yuan(this.minOrder - this.food)} 起送`)
          .fontSize(12).fontColor($r('app.color.brand'))
          .width('100%')
          .padding({ left: 16, right: 16, bottom: 4 });
      }
      // 有规格的行在这里列出来,不然用户看不到自己点的是哪个规格
      ForEach(this.lines.filter((l: CartLine) => l.choices.length > 0),
        (l: CartLine) => {
          Row() {
            Text(`${l.dish.name} · ${choicesLabel(l.choices)}`)
              .fontSize(11).fontColor($r('app.color.ink_muted')).layoutWeight(1)
              .maxLines(1).textOverflow({ overflow: TextOverflow.Ellipsis });
            Text('−').fontSize(14).fontColor($r('app.color.ink_muted'))
              .margin({ right: 10 })
              .onClick(() => { this.changeQty(l.dish, l.choices, -1); });
            Text(`×${l.quantity}`).fontSize(11)
              .fontColor($r('app.color.ink_muted'));
          }
          .width('100%').padding({ left: 16, right: 16, bottom: 2 });
        }, (l: CartLine) => lineKey(l.dish.id, l.choices));

      Row() {
        Column({ space: 2 }) {
          Text(yuan(this.food))
            .fontSize(18).fontWeight(FontWeight.Bold)
            .fontColor($r('app.color.ink'));
          Text(`另计打包费 ${yuan(packingCents(m, this.lines))}`)
            .fontSize(11).fontColor($r('app.color.ink_muted'));
        }
        .layoutWeight(1).alignItems(HorizontalAlign.Start);

        if (manjianCents(m, this.food, packingCents(m, this.lines)) > 0) {
          Text(`已减 ${yuan(manjianCents(m, this.food, packingCents(m, this.lines)))}`)
            .fontSize(12).fontColor($r('app.color.earn'))
            .margin({ right: 10 });
        }

        Button('去结算')
          .width(104).height(42)
          .enabled(this.canCheckout)
          .backgroundColor(this.canCheckout
            ? $r('app.color.brand') : $r('app.color.line'))
          .accessibilityText(this.canCheckout
            ? `去结算,餐费 ${yuan(this.food)}`
            : `还差 ${yuan(this.minOrder - this.food)} 起送,暂时不能结算`)
          .onClick(() => {
            if (this.merchant !== null) {
              this.onCheckout(this.merchant, this.lines);
            }
          });
      }
      .width('100%').padding({ left: 16, right: 16, top: 8, bottom: 8 });
    }
    .width('100%').backgroundColor($r('app.color.surface'))
    .border({ width: { top: 1 }, color: $r('app.color.line') });
  }

  build() {
    Stack() {
      Column() {
        if (this.loading) {
          Column() { LoadingProgress().width(36).height(36); }
          .width('100%').layoutWeight(1).justifyContent(FlexAlign.Center);
        } else if (this.error.length > 0 || this.merchant === null) {
          Column({ space: 12 }) {
            Text(this.error.length > 0 ? this.error : '店铺信息加载失败')
              .fontSize(14).fontColor($r('app.color.ink_muted'));
            Button('重试').onClick(() => { this.load(); });
          }
          .width('100%').layoutWeight(1).justifyContent(FlexAlign.Center);
        } else {
          Scroll() {
            Column({ space: 1 }) {
              this.header(this.merchant);
              this.claimStrip();
              this.tabBar();
              if (this.tab === 0) {
                this.frequentRow();
                ForEach(this.dishes, (d: Dish) => {
                  this.dishRow(d);
                }, (d: Dish) => `${d.id}`);
              } else if (this.reviews.length === 0) {
                Text('这家店还没有评价')
                  .fontSize(13).fontColor($r('app.color.ink_muted'))
                  .width('100%').textAlign(TextAlign.Center)
                  .padding({ top: 40, bottom: 40 })
                  .backgroundColor($r('app.color.surface'));
              } else {
                ForEach(this.reviews, (r: Review) => {
                  this.reviewRow(r);
                }, (r: Review) => `${r.id}`);
              }
            }
            .width('100%');
          }
          .layoutWeight(1).scrollBar(BarState.Off);

          this.cartBar(this.merchant);
        }
      }
      .width('100%').height('100%')
      .backgroundColor($r('app.color.page'));

      if (this.optionDish !== null) {
        this.optionSheet(this.optionDish);
      }
    }
    .width('100%').height('100%');
  }
}
