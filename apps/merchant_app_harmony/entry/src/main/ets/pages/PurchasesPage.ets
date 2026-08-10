import { promptAction } from '@kit.ArkUI';
import { MerchantApi } from '../common/MerchantApi';
import { ApiException } from '../common/Api';
import { ArrayDataSource } from '../common/DataSource';

/**
 * 进货查验台账(食品溯源)。
 *
 * 《食品安全法》五十三条要求记录食品名称、规格、数量、生产日期或批号、
 * 保质期、进货日期、供货者名称/地址/联系方式并保存凭证;留存期不少于
 * 保质期满后六个月(没有明确保质期的两年)。
 *
 * 这是餐饮小商家普遍不做、而出事时**唯一能自证清白**的东西。所以整页的
 * 设计压力都在一件事上:**让人真的愿意录第二次、第三次**。
 *
 * - 只有食材名与进货日期必填,缺项当场列出**但不拦**;
 * - 供货商可从用过的里选,一选带出地址与电话;
 * - 留存到期日平台替你算,不用商家记规则。
 *
 * 手机端尤其重要:收货就在后门口,拍一张票据当场录完,
 * 回到电脑前就没人补了。
 */
@Component
export struct PurchasesPage {
  onBack: () => void = () => {};

  @State private items: Record<string, Object>[] = [];
  @State private loaded: boolean = false;
  @State private errorText: string = '';
  @State private note: string = '';
  @State private query: string = '';

  /** 新增面板 */
  @State private showAdd: boolean = false;
  @State private busy: boolean = false;
  @State private fName: string = '';
  @State private fSpec: string = '';
  @State private fQty: string = '';
  @State private fBatch: string = '';
  @State private fSupplier: string = '';
  @State private fAddress: string = '';
  @State private fPhone: string = '';
  @State private fPurchased: string = '';

  @State private suppliers: Record<string, Object>[] = [];

  private api: MerchantApi = new MerchantApi();
  private ds: ArrayDataSource<Record<string, Object>> =
      new ArrayDataSource<Record<string, Object>>();

  aboutToAppear(): void {
    this.fPurchased = this.today();
    this.load();
  }

  private today(): string {
    const d: Date = new Date();
    const two = (n: number): string => n < 10 ? `0${n}` : `${n}`;
    return `${d.getFullYear()}-${two(d.getMonth() + 1)}-${two(d.getDate())}`;
  }

  private async load(): Promise<void> {
    // 供货商列表是附加信息:拉不到只是不能"一选带出",不拦着录台账
    const supF: Promise<Record<string, Object>[]> = this.api.purchaseSuppliers();
    let sup: Record<string, Object>[] = this.suppliers;
    try {
      sup = await supF;
    } catch (_) {
      // 只影响填表时的便利,不影响主流程
    }

    try {
      const r: Record<string, Object> = await this.api.purchases(
          this.query.length === 0 ? undefined : this.query);
      const raw: Object | undefined = r['items'];
      this.items = (raw === undefined ? [] : raw) as Record<string, Object>[];
      this.ds.reload(this.items);
      this.note = `${r['note'] ?? ''}`;
      this.suppliers = sup;
      this.errorText = '';
    } catch (e) {
      this.errorText = (e as ApiException).message;
    } finally {
      this.loaded = true;
    }
  }

  private async submit(): Promise<void> {
    if (this.fName.trim().length === 0) {
      promptAction.showToast({ message: '至少填食材名' });
      return;
    }
    this.busy = true;
    try {
      const body: Record<string, Object> = {
        name: this.fName.trim(),
        spec: this.fSpec.trim(),
        qty: this.fQty.trim(),
        batch_no: this.fBatch.trim(),
        purchased_on: this.fPurchased,
        supplier_name: this.fSupplier.trim(),
        supplier_address: this.fAddress.trim(),
        supplier_phone: this.fPhone.trim(),
      };
      await this.api.addPurchase(body);
      this.showAdd = false;
      this.resetForm();
      promptAction.showToast({ message: '已记下这一笔' });
      await this.load();
    } catch (e) {
      // 面板不关 —— 关了商家填的一整屏就没了
      promptAction.showToast({ message: (e as ApiException).message });
    } finally {
      this.busy = false;
    }
  }

  private resetForm(): void {
    this.fName = '';
    this.fSpec = '';
    this.fQty = '';
    this.fBatch = '';
    this.fSupplier = '';
    this.fAddress = '';
    this.fPhone = '';
    this.fPurchased = this.today();
  }

  private async remove(r: Record<string, Object>): Promise<void> {
    try {
      await this.api.deletePurchase(r['id'] as number);
      await this.load();
    } catch (e) {
      promptAction.showToast({ message: (e as ApiException).message });
    }
  }

  private pickSupplier(s: Record<string, Object>): void {
    this.fSupplier = `${s['name'] ?? ''}`;
    this.fAddress = `${s['address'] ?? ''}`;
    this.fPhone = `${s['phone'] ?? ''}`;
  }

  @Builder
  private field(label: string, value: string, hint: string,
                onChange: (v: string) => void) {
    Column({ space: 4 }) {
      Text(label).fontSize(12)
        .fontColor($r('app.color.ink_muted')).width('100%');
      TextInput({ placeholder: hint, text: value })
        .height(42)
        .onChange(onChange);
    }
    .width('100%');
  }

  @Builder
  private addSheet() {
    Scroll() {
      Column({ space: 10 }) {
        Text('记一笔进货')
          .fontSize(17).fontWeight(FontWeight.Bold)
          .fontColor($r('app.color.ink')).width('100%');
        Text('只有食材名和进货日期必填,其余缺了会提醒但不拦你先记下')
          .fontSize(12).lineHeight(18)
          .fontColor($r('app.color.ink_muted')).width('100%');

        this.field('食材名 *', this.fName, '例:牛腩',
          (v: string) => { this.fName = v; });
        this.field('进货日期 *', this.fPurchased, 'YYYY-MM-DD',
          (v: string) => { this.fPurchased = v; });
        this.field('规格', this.fSpec, '例:5kg/箱',
          (v: string) => { this.fSpec = v; });
        this.field('数量', this.fQty, '例:2 箱',
          (v: string) => { this.fQty = v; });
        this.field('批号 / 生产日期', this.fBatch, '票上有就抄一下',
          (v: string) => { this.fBatch = v; });

        if (this.suppliers.length > 0) {
          Text('用过的供货商(点一下带出地址电话)')
            .fontSize(12).fontColor($r('app.color.ink_muted')).width('100%');
          Flex({ wrap: FlexWrap.Wrap }) {
            ForEach(this.suppliers.slice(0, 6),
              (s: Record<string, Object>) => {
                Text(`${s['name']}`)
                  .fontSize(12).fontColor($r('app.color.ink'))
                  .padding({ left: 10, right: 10, top: 5, bottom: 5 })
                  .margin({ right: 6, bottom: 6 })
                  .borderRadius(12)
                  .backgroundColor($r('app.color.surface_alt'))
                  .onClick(() => { this.pickSupplier(s); });
              }, (s: Record<string, Object>) => `${s['name']}`);
          }
          .width('100%');
        }

        this.field('供货商', this.fSupplier, '谁供的',
          (v: string) => { this.fSupplier = v; });
        this.field('供货商地址', this.fAddress, '',
          (v: string) => { this.fAddress = v; });
        this.field('供货商电话', this.fPhone, '',
          (v: string) => { this.fPhone = v; });

        Row({ space: 10 }) {
          Button('取消')
            .layoutWeight(1).height(44)
            .backgroundColor($r('app.color.surface_alt'))
            .fontColor($r('app.color.ink'))
            .onClick(() => { this.showAdd = false; });
          Button(this.busy ? '保存中…' : '保存')
            .layoutWeight(1).height(44)
            .backgroundColor($r('app.color.brand'))
            .enabled(!this.busy && this.fName.trim().length > 0)
            .onClick(() => { this.submit(); });
        }
        .width('100%').margin({ top: 4, bottom: 10 });
      }
      .width('100%')
      .padding({ left: 18, right: 18, top: 18, bottom: 18 });
    }
    .height('100%')
    .backgroundColor($r('app.color.surface'));
  }

  @Builder
  private recordRow(r: Record<string, Object>) {
    Row({ space: 10 }) {
      Column({ space: 3 }) {
        Text(`${r['name']}`)
          .fontSize(15).fontColor($r('app.color.ink'));
        Text(`${r['purchased_on'] ?? ''} · ${r['supplier_name'] ?? '未填供货商'}`)
          .fontSize(12).fontColor($r('app.color.ink_muted'));
        if (`${r['keep_until'] ?? ''}`.length > 0) {
          Text(`至少留到 ${r['keep_until']}`)
            .fontSize(11).fontColor($r('app.color.hold'));
        }
      }
      .alignItems(HorizontalAlign.Start).layoutWeight(1);
      Text('删')
        .fontSize(13).fontColor($r('app.color.danger'))
        .onClick(() => { this.remove(r); });
    }
    .width('100%').padding({ top: 10, bottom: 10 });
    Divider().color($r('app.color.line'));
  }

  build() {
    Column() {
      Row({ space: 10 }) {
        Text('‹').fontSize(24).fontColor($r('app.color.ink'))
          .onClick(() => { this.onBack(); });
        Text('进货台账')
          .fontSize(17).fontWeight(FontWeight.Bold)
          .fontColor($r('app.color.ink')).layoutWeight(1);
        Text('记一笔')
          .fontSize(14).fontColor($r('app.color.brand'))
          .onClick(() => { this.showAdd = true; });
      }
      .width('100%')
      .padding({ left: 14, right: 14, top: 10, bottom: 10 })
      .backgroundColor($r('app.color.surface'));

      Row({ space: 8 }) {
        TextInput({ placeholder: '搜食材或供货商', text: this.query })
          .height(40).layoutWeight(1)
          .onChange((v: string) => { this.query = v; })
          .onSubmit(() => { this.load(); });
      }
      .width('100%').padding({ left: 12, right: 12, top: 8, bottom: 4 });

      if (!this.loaded) {
        Column() {
          LoadingProgress().width(40).height(40);
        }
        .layoutWeight(1).justifyContent(FlexAlign.Center);
      } else if (this.errorText.length > 0) {
        Column({ space: 12 }) {
          Text('台账没能加载出来')
            .fontSize(15).fontColor($r('app.color.ink'));
          Text(this.errorText).fontSize(13)
            .fontColor($r('app.color.ink_muted')).textAlign(TextAlign.Center);
          Button('重试').height(40).width(130)
            .backgroundColor($r('app.color.brand'))
            .onClick(() => { this.load(); });
        }
        .layoutWeight(1).justifyContent(FlexAlign.Center).padding(30);
      } else {
        Column() {
          if (this.query.length === 0) {
            // 为什么值得记:出事时这本台账是唯一能自证清白的东西
            Column({ space: 4 }) {
              Text('出事时,这本台账是唯一能自证清白的东西')
                .fontSize(13).fontWeight(FontWeight.Medium)
                .fontColor($r('app.color.ink')).width('100%');
              Text('「这批肉是谁供的、什么时候进的、票在哪」——' +
                '答不上来就只能自己扛。')
                .fontSize(12).lineHeight(18)
                .fontColor($r('app.color.ink_muted')).width('100%');
            }
            .width('100%').padding(12)
            .backgroundColor($r('app.color.surface_alt')).borderRadius(10)
            .margin({ bottom: 10 });
          }

          if (this.items.length === 0) {
            Text(this.query.length === 0
              ? '还没有进货记录' : `没有找到「${this.query}」的进货记录`)
              .fontSize(14).fontColor($r('app.color.ink_muted'))
              .width('100%').textAlign(TextAlign.Center)
              .padding({ top: 40, bottom: 40 });
          } else {
            // 台账**只增不减**,开一年就是几百条 —— 按需构建
            List() {
              LazyForEach(this.ds, (r: Record<string, Object>) => {
                ListItem() {
                  this.recordRow(r);
                }
              }, (r: Record<string, Object>) => `${r['id']}`);
            }
            .layoutWeight(1).width('100%').scrollBar(BarState.Off);
          }

          if (this.note.length > 0 && this.query.length === 0) {
            Text(this.note)
              .fontSize(11).fontColor($r('app.color.ink_muted'))
              .width('100%').padding({ top: 8, bottom: 8 });
          }
        }
        .layoutWeight(1).width('100%')
        .padding({ left: 12, right: 12, top: 4 });
      }
    }
    .width('100%').height('100%')
    .backgroundColor($r('app.color.page'))
    .bindSheet($$this.showAdd, this.addSheet(),
      { height: '82%', dragBar: true });
  }
}
