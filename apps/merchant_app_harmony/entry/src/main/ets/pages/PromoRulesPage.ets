import { promptAction } from '@kit.ArkUI';
import { MerchantApi } from '../common/MerchantApi';
import { ApiException } from '../common/Api';
import { Dish, GiftRule, PromoRule, Shop } from '../model/Models';

/** 编辑中的一档满减 */
interface PromoDraft {
  threshold: string;
  off: string;
}

/** 编辑中的一档满赠 */
interface GiftDraft {
  threshold: string;
  dishId: number;
}

/**
 * 营销规则:满减 / 满赠 / 店铺券。
 *
 * ## 三者的关系要在界面上讲清楚
 *
 * 这是商家最常问的:**满减和店铺券二选其一取最优,满赠可以叠加。**
 * 不写出来的话,商家会以为满减和券能叠,然后按错误的成本去定价。
 *
 * ## 成本是谁出的也要写清楚
 *
 * 满减和店铺券的钱**商家自己出**,平台按让利后的实收计 5% ——
 * 商家让利,平台跟着少收。这句话值钱,因为别家不是这么算的。
 */
@Component
export struct PromoRulesPage {
  @Prop shop: Shop;
  onBack: () => void = () => {};
  onChanged: () => void = () => {};

  @State private promo: PromoDraft[] = [];
  @State private gifts: GiftDraft[] = [];
  @State private dishes: Dish[] = [];
  @State private coupons: Record<string, Object>[] = [];
  @State private loaded: boolean = false;
  @State private errorText: string = '';
  @State private busy: boolean = false;

  /** 新建店铺券 */
  @State private showCoupon: boolean = false;
  @State private cName: string = '满减券';
  @State private cThreshold: string = '';
  @State private cOff: string = '';
  @State private cTotal: string = '100';
  @State private cPerUser: string = '1';
  @State private cValidDays: string = '7';

  private api: MerchantApi = new MerchantApi();

  aboutToAppear(): void {
    this.promo = (this.shop.promo_rules ?? []).map((r: PromoRule) => {
      const d: PromoDraft = {
        threshold: `${Math.floor(r.threshold_cents / 100)}`,
        off: `${r.off_cents / 100}`,
      };
      return d;
    });
    this.gifts = (this.shop.gift_rules ?? []).map((r: GiftRule) => {
      const d: GiftDraft = {
        threshold: `${Math.floor(r.threshold_cents / 100)}`,
        dishId: r.dish_id,
      };
      return d;
    });
    this.load();
  }

  private async load(): Promise<void> {
    // 菜品(选赠品用)和券批次互不依赖,先都发出去
    const dishesF: Promise<Dish[]> = this.api.myDishes();
    const couponsF: Promise<Record<string, Object>[]> =
        this.api.myShopCouponBatches();

    let coupons: Record<string, Object>[] = this.coupons;
    try {
      coupons = await couponsF;
    } catch (_) {
      // 券批次拉不到只是少显示一块,不拦着改满减
    }

    try {
      this.dishes = (await dishesF).filter((d: Dish) => d.is_on_sale !== false);
      this.coupons = coupons;
      this.errorText = '';
    } catch (e) {
      this.errorText = (e as ApiException).message;
    } finally {
      this.loaded = true;
    }
  }

  // ---------- 满减 ----------

  private async savePromo(): Promise<void> {
    const rules: Record<string, Object>[] = [];
    for (let i: number = 0; i < this.promo.length; i++) {
      const t: number = Number.parseFloat(this.promo[i].threshold);
      const o: number = Number.parseFloat(this.promo[i].off);
      if (isNaN(t) || isNaN(o) || t <= 0 || o <= 0) {
        continue; // 空行/无效行直接忽略
      }
      if (o >= t) {
        promptAction.showToast({ message: '减的金额必须小于门槛(不能倒贴)' });
        return;
      }
      rules.push({
        threshold_cents: Math.round(t * 100),
        off_cents: Math.round(o * 100),
      });
    }
    this.busy = true;
    try {
      await this.api.updateShop({ promo_rules: rules } as object);
      promptAction.showToast({ message: '满减已保存' });
      this.onChanged();
    } catch (e) {
      promptAction.showToast({ message: (e as ApiException).message });
    } finally {
      this.busy = false;
    }
  }

  // ---------- 满赠 ----------

  private async saveGifts(): Promise<void> {
    const rules: Record<string, Object>[] = [];
    for (let i: number = 0; i < this.gifts.length; i++) {
      const t: number = Number.parseFloat(this.gifts[i].threshold);
      if (isNaN(t) || t <= 0 || this.gifts[i].dishId <= 0) {
        continue;
      }
      rules.push({
        threshold_cents: Math.round(t * 100),
        dish_id: this.gifts[i].dishId,
      });
    }
    this.busy = true;
    try {
      await this.api.updateShop({ gift_rules: rules } as object);
      promptAction.showToast({ message: '满赠已保存' });
      this.onChanged();
    } catch (e) {
      promptAction.showToast({ message: (e as ApiException).message });
    } finally {
      this.busy = false;
    }
  }

  private dishName(id: number): string {
    for (let i: number = 0; i < this.dishes.length; i++) {
      if (this.dishes[i].id === id) {
        return this.dishes[i].name;
      }
    }
    return '选菜品';
  }

  // ---------- 店铺券 ----------

  private async createCoupon(): Promise<void> {
    const t: number = Math.round(
        (Number.parseFloat(this.cThreshold) || 0) * 100);
    const o: number = Math.round((Number.parseFloat(this.cOff) || 0) * 100);
    const total: number = Number.parseInt(this.cTotal) || 0;
    if (o <= 0 || total <= 0 || (t > 0 && o >= t)) {
      promptAction.showToast({ message: '减额需大于 0 且小于门槛,总量大于 0' });
      return;
    }
    this.busy = true;
    try {
      await this.api.createShopCouponBatch({
        name: this.cName.trim(),
        threshold_cents: t,
        off_cents: o,
        total: total,
        per_user_limit: Number.parseInt(this.cPerUser) || 1,
        valid_days: Number.parseInt(this.cValidDays) || 7,
      } as object);
      this.showCoupon = false;
      this.cThreshold = '';
      this.cOff = '';
      await this.load();
      promptAction.showToast({ message: '券已发布' });
    } catch (e) {
      promptAction.showToast({ message: (e as ApiException).message });
    } finally {
      this.busy = false;
    }
  }

  private async toggleCoupon(b: Record<string, Object>): Promise<void> {
    try {
      await this.api.toggleShopCouponBatch(b['id'] as number);
      await this.load();
    } catch (e) {
      promptAction.showToast({ message: (e as ApiException).message });
    }
  }

  @Builder
  private couponSheet() {
    Column({ space: 10 }) {
      Text('新建店铺券')
        .fontSize(17).fontWeight(FontWeight.Bold)
        .fontColor($r('app.color.ink')).width('100%');
      TextInput({ placeholder: '券名', text: this.cName })
        .height(42).onChange((v: string) => { this.cName = v; });
      Row({ space: 8 }) {
        TextInput({ placeholder: '满(元,0 无门槛)', text: this.cThreshold })
          .type(InputType.Number).height(42).layoutWeight(1)
          .onChange((v: string) => { this.cThreshold = v; });
        TextInput({ placeholder: '减(元)', text: this.cOff })
          .type(InputType.Number).height(42).layoutWeight(1)
          .onChange((v: string) => { this.cOff = v; });
      }
      .width('100%');
      Row({ space: 8 }) {
        TextInput({ placeholder: '发行总量', text: this.cTotal })
          .type(InputType.Number).height(42).layoutWeight(1)
          .onChange((v: string) => { this.cTotal = v; });
        TextInput({ placeholder: '每人限领', text: this.cPerUser })
          .type(InputType.Number).height(42).layoutWeight(1)
          .onChange((v: string) => { this.cPerUser = v; });
        TextInput({ placeholder: '有效天数', text: this.cValidDays })
          .type(InputType.Number).height(42).layoutWeight(1)
          .onChange((v: string) => { this.cValidDays = v; });
      }
      .width('100%');
      Row({ space: 10 }) {
        Button('取消')
          .layoutWeight(1).height(44)
          .backgroundColor($r('app.color.surface_alt'))
          .fontColor($r('app.color.ink'))
          .onClick(() => { this.showCoupon = false; });
        Button(this.busy ? '发布中…' : '发布')
          .layoutWeight(1).height(44)
          .backgroundColor($r('app.color.brand'))
          .enabled(!this.busy)
          .onClick(() => { this.createCoupon(); });
      }
      .width('100%');
    }
    .width('100%')
    .padding({ left: 18, right: 18, top: 18, bottom: 24 })
    .backgroundColor($r('app.color.surface'));
  }

  build() {
    Column() {
      Row({ space: 10 }) {
        Text('‹').fontSize(24).fontColor($r('app.color.ink'))
          .onClick(() => { this.onBack(); });
        Text('营销规则')
          .fontSize(17).fontWeight(FontWeight.Bold)
          .fontColor($r('app.color.ink')).layoutWeight(1);
      }
      .width('100%')
      .padding({ left: 14, right: 14, top: 10, bottom: 10 })
      .backgroundColor($r('app.color.surface'));

      if (!this.loaded) {
        Column() {
          LoadingProgress().width(40).height(40);
        }
        .layoutWeight(1).justifyContent(FlexAlign.Center);
      } else if (this.errorText.length > 0) {
        Column({ space: 12 }) {
          Text('菜单没能加载出来,选不了赠品')
            .fontSize(15).fontColor($r('app.color.ink'));
          Text(this.errorText).fontSize(13)
            .fontColor($r('app.color.ink_muted')).textAlign(TextAlign.Center);
          Button('重试').height(40).width(130)
            .backgroundColor($r('app.color.brand'))
            .onClick(() => { this.load(); });
        }
        .layoutWeight(1).justifyContent(FlexAlign.Center).padding(30);
      } else {
        Scroll() {
          Column({ space: 12 }) {
            // 三者关系:商家最常问的
            Text('满减和店铺券**二选其一取最优,不叠加**;满赠可以和它们同时生效。')
              .fontSize(12).lineHeight(19)
              .fontColor($r('app.color.ink'))
              .width('100%').padding(12)
              .backgroundColor($r('app.color.surface_alt')).borderRadius(10);

            // ---- 满减 ----
            Column({ space: 8 }) {
              Text('满减(最多 3 档)')
                .fontSize(13).fontWeight(FontWeight.Medium)
                .fontColor($r('app.color.ink')).width('100%');
              ForEach(this.promo, (d: PromoDraft, i: number) => {
                Row({ space: 6 }) {
                  Text('满').fontSize(13).fontColor($r('app.color.ink'));
                  TextInput({ text: d.threshold })
                    .type(InputType.Number).height(40).width(64)
                    .onChange((v: string) => {
                      this.promo[i].threshold = v;
                      this.promo = this.promo.slice();
                    });
                  Text('元 减').fontSize(13).fontColor($r('app.color.ink'));
                  TextInput({ text: d.off })
                    .type(InputType.Number).height(40).width(64)
                    .onChange((v: string) => {
                      this.promo[i].off = v;
                      this.promo = this.promo.slice();
                    });
                  Text('元').fontSize(13).fontColor($r('app.color.ink'));
                  Blank();
                  Text('删')
                    .fontSize(13).fontColor($r('app.color.danger'))
                    .onClick(() => {
                      this.promo.splice(i, 1);
                      this.promo = this.promo.slice();
                    });
                }
                .width('100%');
              }, (d: PromoDraft, i: number) => `p${i}-${d.threshold}-${d.off}`);

              if (this.promo.length < 3) {
                Text('+ 加一档')
                  .fontSize(13).fontColor($r('app.color.brand'))
                  .width('100%')
                  .onClick(() => {
                    this.promo.push({ threshold: '', off: '' });
                    this.promo = this.promo.slice();
                  });
              }
              Text('满减成本由你承担,平台按满减后的实收计 5% 服务费 —— 你让利,平台跟着少收。')
                .fontSize(11).lineHeight(17)
                .fontColor($r('app.color.ink_muted')).width('100%');
              Button(this.busy ? '保存中…' : '保存满减')
                .width('100%').height(42)
                .backgroundColor($r('app.color.brand'))
                .enabled(!this.busy)
                .onClick(() => { this.savePromo(); });
            }
            .width('100%').padding(14)
            .backgroundColor($r('app.color.surface')).borderRadius(12);

            // ---- 满赠 ----
            Column({ space: 8 }) {
              Text('满赠(最多 2 档)')
                .fontSize(13).fontWeight(FontWeight.Medium)
                .fontColor($r('app.color.ink')).width('100%');
              ForEach(this.gifts, (g: GiftDraft, i: number) => {
                Column({ space: 6 }) {
                  Row({ space: 6 }) {
                    Text('满').fontSize(13).fontColor($r('app.color.ink'));
                    TextInput({ text: g.threshold })
                      .type(InputType.Number).height(40).width(64)
                      .onChange((v: string) => {
                        this.gifts[i].threshold = v;
                        this.gifts = this.gifts.slice();
                      });
                    Text('元赠').fontSize(13).fontColor($r('app.color.ink'));
                    Blank();
                    Text('删').fontSize(13).fontColor($r('app.color.danger'))
                      .onClick(() => {
                        this.gifts.splice(i, 1);
                        this.gifts = this.gifts.slice();
                      });
                  }
                  .width('100%');
                  // 赠品从在售菜里选。已下架的菜不在列表里 —— 强制重选
                  Flex({ wrap: FlexWrap.Wrap }) {
                    ForEach(this.dishes.slice(0, 12), (d: Dish) => {
                      Text(d.name)
                        .fontSize(12)
                        .fontColor(this.gifts[i].dishId === d.id
                          ? Color.White : $r('app.color.ink'))
                        .padding({ left: 10, right: 10, top: 5, bottom: 5 })
                        .margin({ right: 6, bottom: 6 })
                        .borderRadius(12)
                        .backgroundColor(this.gifts[i].dishId === d.id
                          ? $r('app.color.brand')
                          : $r('app.color.surface_alt'))
                        .onClick(() => {
                          this.gifts[i].dishId = d.id;
                          this.gifts = this.gifts.slice();
                        });
                    }, (d: Dish) => `${d.id}`);
                  }
                  .width('100%');
                }
                .width('100%').padding({ top: 4, bottom: 4 });
              }, (g: GiftDraft, i: number) => `g${i}-${g.dishId}`);

              if (this.gifts.length < 2) {
                Text('+ 加一档')
                  .fontSize(13).fontColor($r('app.color.brand'))
                  .width('100%')
                  .onClick(() => {
                    this.gifts.push({ threshold: '', dishId: 0 });
                    this.gifts = this.gifts.slice();
                  });
              }
              Text('赠品照常扣库存,库存不足该档自动失效;佣金不含赠品。')
                .fontSize(11).lineHeight(17)
                .fontColor($r('app.color.ink_muted')).width('100%');
              Button(this.busy ? '保存中…' : '保存满赠')
                .width('100%').height(42)
                .backgroundColor($r('app.color.brand'))
                .enabled(!this.busy)
                .onClick(() => { this.saveGifts(); });
            }
            .width('100%').padding(14)
            .backgroundColor($r('app.color.surface')).borderRadius(12);

            // ---- 店铺券 ----
            Column({ space: 8 }) {
              Row() {
                Text('店铺券')
                  .fontSize(13).fontWeight(FontWeight.Medium)
                  .fontColor($r('app.color.ink')).layoutWeight(1);
                Text('新建')
                  .fontSize(13).fontColor($r('app.color.brand'))
                  .onClick(() => { this.showCoupon = true; });
              }
              .width('100%');

              if (this.coupons.length === 0) {
                Text('还没发券')
                  .fontSize(13).fontColor($r('app.color.ink_muted'))
                  .width('100%').padding({ top: 10, bottom: 10 });
              } else {
                ForEach(this.coupons, (b: Record<string, Object>) => {
                  Row({ space: 10 }) {
                    Column({ space: 2 }) {
                      Text(`满${(b['threshold_cents'] as number) / 100}` +
                        `减${(b['off_cents'] as number) / 100} · ${b['name']}`)
                        .fontSize(14).fontColor($r('app.color.ink'));
                      Text(`已领 ${b['issued']}/${b['total']} · ` +
                        `每人${b['per_user_limit']}张 · ${b['valid_days']}天`)
                        .fontSize(11).fontColor($r('app.color.ink_muted'));
                    }
                    .alignItems(HorizontalAlign.Start).layoutWeight(1);
                    Toggle({ type: ToggleType.Switch,
                      isOn: b['active'] === true })
                      .selectedColor($r('app.color.brand'))
                      .onChange(() => { this.toggleCoupon(b); });
                  }
                  .width('100%').padding({ top: 8, bottom: 8 });
                  Divider().color($r('app.color.line'));
                }, (b: Record<string, Object>) => `${b['id']}`);
              }
              Text('券的成本你自己出(和满减同口径,平台按券后实收计 5%),用来引流拉复购。')
                .fontSize(11).lineHeight(17)
                .fontColor($r('app.color.ink_muted')).width('100%');
            }
            .width('100%').padding(14)
            .backgroundColor($r('app.color.surface')).borderRadius(12);

            Blank().height(30);
          }
          .width('100%').padding(12);
        }
        .layoutWeight(1).scrollBar(BarState.Off);
      }
    }
    .width('100%').height('100%')
    .backgroundColor($r('app.color.page'))
    .bindSheet($$this.showCoupon, this.couponSheet(),
      { height: 380, dragBar: false });
  }
}
