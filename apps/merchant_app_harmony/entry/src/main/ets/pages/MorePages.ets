import { promptAction } from '@kit.ArkUI';
import { MerchantApi } from '../common/MerchantApi';
import { ApiException } from '../common/Api';
import { yuan } from '../common/Money';
import { Shop } from '../model/Models';

/**
 * 开发票。
 *
 * 商家给平台开的是**服务费发票**(平台抽的那 5%),不是给顾客开的餐费票。
 * 这个区别要写清楚,否则商家会拿它去给顾客报销。
 */
@Component
export struct InvoicePage {
  onBack: () => void = () => {};

  @State private period: string = '';
  @State private summary: Record<string, Object> | null = null;
  @State private mine: Record<string, Object>[] = [];
  @State private loaded: boolean = false;
  @State private errorText: string = '';
  @State private busy: boolean = false;

  @State private title: string = '';
  @State private taxNo: string = '';
  @State private email: string = '';

  private api: MerchantApi = new MerchantApi();

  aboutToAppear(): void {
    this.period = this.recentPeriods()[0];
    this.load();
  }

  /** 最近 6 个月,YYYY-MM */
  private recentPeriods(): string[] {
    const out: string[] = [];
    const now: Date = new Date();
    for (let i: number = 0; i < 6; i++) {
      const d: Date = new Date(now.getFullYear(), now.getMonth() - i, 1);
      const m: number = d.getMonth() + 1;
      out.push(`${d.getFullYear()}-${m < 10 ? `0${m}` : `${m}`}`);
    }
    return out;
  }

  private async load(): Promise<void> {
    // 两个互不依赖,先都发出去
    const summaryF: Promise<Record<string, Object>> =
        this.api.invoiceSummary(this.period);
    const mineF: Promise<Record<string, Object>[]> = this.api.myInvoices();
    try {
      const s: Record<string, Object> = await summaryF;
      const m: Record<string, Object>[] = await mineF;
      this.summary = s;
      this.mine = m;
      if (this.title.length === 0) {
        this.title = `${s['title'] ?? ''}`;
        this.taxNo = `${s['tax_no'] ?? ''}`;
        this.email = `${s['email'] ?? ''}`;
      }
      this.errorText = '';
    } catch (e) {
      this.errorText = (e as ApiException).message;
    } finally {
      this.loaded = true;
    }
  }

  private async apply(): Promise<void> {
    if (this.title.trim().length === 0 || this.email.trim().length === 0) {
      promptAction.showToast({ message: '抬头和邮箱都要填' });
      return;
    }
    this.busy = true;
    try {
      await this.api.applyInvoice({
        period: this.period,
        title: this.title.trim(),
        tax_no: this.taxNo.trim(),
        email: this.email.trim(),
      } as object);
      await this.load();
      promptAction.showToast({ message: '已申请,开好会发到你的邮箱' });
    } catch (e) {
      promptAction.showToast({ message: (e as ApiException).message });
    } finally {
      this.busy = false;
    }
  }

  build() {
    Column() {
      Row({ space: 10 }) {
        Text('‹').fontSize(24).fontColor($r('app.color.ink'))
          .onClick(() => { this.onBack(); });
        Text('开发票')
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
          Text('发票信息没能加载出来')
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
            Text('这里开的是**平台服务费**的发票(平台抽的那 5%),' +
              '不是给顾客开的餐费票。')
              .fontSize(12).lineHeight(19)
              .fontColor($r('app.color.ink'))
              .width('100%').padding(12)
              .backgroundColor($r('app.color.surface_alt')).borderRadius(10);

            Column({ space: 10 }) {
              Text('选择月份')
                .fontSize(13).fontWeight(FontWeight.Medium)
                .fontColor($r('app.color.ink')).width('100%');
              Flex({ wrap: FlexWrap.Wrap }) {
                ForEach(this.recentPeriods(), (p: string) => {
                  Text(p)
                    .fontSize(12)
                    .fontColor(this.period === p
                      ? Color.White : $r('app.color.ink'))
                    .padding({ left: 12, right: 12, top: 6, bottom: 6 })
                    .margin({ right: 6, bottom: 6 })
                    .borderRadius(12)
                    .backgroundColor(this.period === p
                      ? $r('app.color.brand') : $r('app.color.surface_alt'))
                    .onClick(() => {
                      this.period = p;
                      this.loaded = false;
                      this.load();
                    });
                }, (p: string) => p);
              }
              .width('100%');
              Row() {
                Text('可开金额').fontSize(13)
                  .fontColor($r('app.color.ink_muted')).layoutWeight(1);
                Text(yuan((this.summary?.['amount_cents'] ?? 0) as number))
                  .fontSize(19).fontWeight(FontWeight.Bold)
                  .fontColor($r('app.color.ink'));
              }
              .width('100%');
            }
            .width('100%').padding(14)
            .backgroundColor($r('app.color.surface')).borderRadius(12);

            Column({ space: 10 }) {
              Text('开票信息')
                .fontSize(13).fontWeight(FontWeight.Medium)
                .fontColor($r('app.color.ink')).width('100%');
              TextInput({ placeholder: '发票抬头', text: this.title })
                .height(44).onChange((v: string) => { this.title = v; });
              TextInput({ placeholder: '税号(个人可不填)', text: this.taxNo })
                .height(44).onChange((v: string) => { this.taxNo = v; });
              TextInput({ placeholder: '接收邮箱', text: this.email })
                .type(InputType.Email).height(44)
                .onChange((v: string) => { this.email = v; });
              Button(this.busy ? '申请中…' : '申请开票')
                .width('100%').height(44)
                .backgroundColor($r('app.color.brand'))
                .enabled(!this.busy
                  && ((this.summary?.['amount_cents'] ?? 0) as number) > 0)
                .onClick(() => { this.apply(); });
            }
            .width('100%').padding(14)
            .backgroundColor($r('app.color.surface')).borderRadius(12);

            if (this.mine.length > 0) {
              Column({ space: 0 }) {
                Text('开票记录')
                  .fontSize(13).fontWeight(FontWeight.Medium)
                  .fontColor($r('app.color.ink'))
                  .width('100%').margin({ bottom: 8 });
                ForEach(this.mine, (v: Record<string, Object>) => {
                  Row() {
                    Column({ space: 2 }) {
                      Text(`${v['period']} · ${yuan(v['amount_cents'] as number)}`)
                        .fontSize(14).fontColor($r('app.color.ink'));
                      Text(`${v['title'] ?? ''}`)
                        .fontSize(11).fontColor($r('app.color.ink_muted'));
                    }
                    .alignItems(HorizontalAlign.Start).layoutWeight(1);
                    Text(`${v['status_label'] ?? v['status']}`)
                      .fontSize(12).fontColor($r('app.color.ink_muted'));
                  }
                  .width('100%').padding({ top: 9, bottom: 9 });
                  Divider().color($r('app.color.line'));
                }, (v: Record<string, Object>) => `${v['id']}`);
              }
              .width('100%').padding(14)
              .backgroundColor($r('app.color.surface')).borderRadius(12);
            }

            Blank().height(30);
          }
          .width('100%').padding(12);
        }
        .layoutWeight(1).scrollBar(BarState.Off);
      }
    }
    .width('100%').height('100%')
    .backgroundColor($r('app.color.page'));
  }
}

/**
 * 连锁品牌后台:多店汇总 + 开新店。
 *
 * ## 单店商家也能看到这一页
 *
 * brand 为 null、shops 只有一家 —— 数据结构是同一份,客户端不用为
 * 「是不是连锁」分两套逻辑。单店商家看到的是「把这家店升级成品牌」。
 */
@Component
export struct ChainPage {
  @Prop shops: Shop[];
  onBack: () => void = () => {};
  onChanged: () => void = () => {};

  @State private overview: Record<string, Object> | null = null;
  @State private brand: Record<string, Object> | null = null;
  @State private errorText: string = '';
  @State private loaded: boolean = false;
  @State private busy: boolean = false;

  @State private showCreate: boolean = false;
  @State private brandName: string = '';

  private api: MerchantApi = new MerchantApi();

  aboutToAppear(): void {
    this.load();
  }

  private async load(): Promise<void> {
    // 两个互不依赖,先都发出去
    const brandF: Promise<Record<string, Object>> = this.api.myBrand();
    const overviewF: Promise<Record<string, Object>> = this.api.brandOverview();

    // 汇总是附加信息:还没建品牌时它会 404,不该把整页打回错误态
    try {
      this.overview = await overviewF;
    } catch (_) {
      // 没建品牌时没有汇总,正常
    }
    try {
      this.brand = await brandF;
      this.errorText = '';
    } catch (e) {
      this.errorText = (e as ApiException).message;
    } finally {
      this.loaded = true;
    }
  }

  private hasBrand(): boolean {
    return this.brand !== null && this.brand['brand'] !== undefined
        && this.brand['brand'] !== null;
  }

  private async createBrand(): Promise<void> {
    if (this.brandName.trim().length === 0 || this.shops.length === 0) {
      return;
    }
    this.busy = true;
    try {
      await this.api.createBrand(this.brandName.trim(), this.shops[0].id);
      this.showCreate = false;
      await this.load();
      this.onChanged();
      promptAction.showToast({ message: '品牌已建立' });
    } catch (e) {
      promptAction.showToast({ message: (e as ApiException).message });
    } finally {
      this.busy = false;
    }
  }

  private num(key: string): number {
    const v: Object | undefined = this.overview?.[key];
    return v === undefined ? 0 : v as number;
  }

  @Builder
  private createSheet() {
    Column({ space: 10 }) {
      Text('把这家店升级成品牌')
        .fontSize(17).fontWeight(FontWeight.Bold)
        .fontColor($r('app.color.ink')).width('100%');
      Text('建立品牌之后可以开分店,菜单和营销规则各店独立,' +
        '账目各店分开算 —— 不会混在一起。')
        .fontSize(12).lineHeight(18)
        .fontColor($r('app.color.ink_muted')).width('100%');
      TextInput({ placeholder: '品牌名', text: this.brandName })
        .height(44).onChange((v: string) => { this.brandName = v; });
      Row({ space: 10 }) {
        Button('取消')
          .layoutWeight(1).height(44)
          .backgroundColor($r('app.color.surface_alt'))
          .fontColor($r('app.color.ink'))
          .onClick(() => { this.showCreate = false; });
        Button(this.busy ? '创建中…' : '创建')
          .layoutWeight(1).height(44)
          .backgroundColor($r('app.color.brand'))
          .enabled(!this.busy && this.brandName.trim().length > 0)
          .onClick(() => { this.createBrand(); });
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
        Text('连锁门店')
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
          Text('门店信息没能加载出来')
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
            if (this.overview !== null) {
              Column({ space: 8 }) {
                Text('全部门店今日汇总')
                  .fontSize(13).fontWeight(FontWeight.Medium)
                  .fontColor($r('app.color.ink')).width('100%');
                Row() {
                  Column({ space: 2 }) {
                    Text(`${this.num('orders')}`)
                      .fontSize(20).fontWeight(FontWeight.Bold)
                      .fontColor($r('app.color.ink'));
                    Text('单').fontSize(11)
                      .fontColor($r('app.color.ink_muted'));
                  }
                  .layoutWeight(1).alignItems(HorizontalAlign.Center);
                  Column({ space: 2 }) {
                    Text(yuan(this.num('net_cents')))
                      .fontSize(20).fontWeight(FontWeight.Bold)
                      .fontColor($r('app.color.earn'));
                    Text('实收').fontSize(11)
                      .fontColor($r('app.color.ink_muted'));
                  }
                  .layoutWeight(1).alignItems(HorizontalAlign.Center);
                  Column({ space: 2 }) {
                    Text(`${this.shops.length}`)
                      .fontSize(20).fontWeight(FontWeight.Bold)
                      .fontColor($r('app.color.ink'));
                    Text('家店').fontSize(11)
                      .fontColor($r('app.color.ink_muted'));
                  }
                  .layoutWeight(1).alignItems(HorizontalAlign.Center);
                }
                .width('100%');
              }
              .width('100%').padding(14)
              .backgroundColor($r('app.color.surface')).borderRadius(12);
            }

            Column({ space: 0 }) {
              Text('门店')
                .fontSize(13).fontWeight(FontWeight.Medium)
                .fontColor($r('app.color.ink'))
                .width('100%').margin({ bottom: 8 });
              ForEach(this.shops, (s: Shop) => {
                Row() {
                  Column({ space: 2 }) {
                    Text(s.name).fontSize(14)
                      .fontColor($r('app.color.ink'));
                    Text(s.address).fontSize(11)
                      .fontColor($r('app.color.ink_muted'))
                      .maxLines(1)
                      .textOverflow({ overflow: TextOverflow.Ellipsis });
                  }
                  .alignItems(HorizontalAlign.Start).layoutWeight(1);
                  Text(s.is_open ? '营业中' : '已打烊')
                    .fontSize(12)
                    .fontColor(s.is_open
                      ? $r('app.color.earn') : $r('app.color.ink_muted'));
                }
                .width('100%').padding({ top: 9, bottom: 9 });
                Divider().color($r('app.color.line'));
              }, (s: Shop) => `${s.id}`);
            }
            .width('100%').padding(14)
            .backgroundColor($r('app.color.surface')).borderRadius(12);

            if (!this.hasBrand()) {
              Button('把这家店升级成品牌')
                .width('100%').height(44)
                .backgroundColor($r('app.color.brand'))
                .enabled(this.shops.length > 0)
                .onClick(() => { this.showCreate = true; });
            } else {
              Text('开分店要填新店的地址和证照,这一版请在安卓端或网页端操作。')
                .fontSize(12).lineHeight(19)
                .fontColor($r('app.color.ink_muted'))
                .width('100%').padding(12)
                .backgroundColor($r('app.color.surface_alt')).borderRadius(10);
            }

            Blank().height(30);
          }
          .width('100%').padding(12);
        }
        .layoutWeight(1).scrollBar(BarState.Off);
      }
    }
    .width('100%').height('100%')
    .backgroundColor($r('app.color.page'))
    .bindSheet($$this.showCreate, this.createSheet(),
      { height: 300, dragBar: false });
  }
}
