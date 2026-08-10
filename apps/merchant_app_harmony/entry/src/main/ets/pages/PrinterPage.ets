import { promptAction } from '@kit.ArkUI';
import { MerchantApi } from '../common/MerchantApi';
import { ApiException } from '../common/Api';
import { BtPrinter, NO_DEVICE, PairedDevice } from '../common/BtPrinter';

/**
 * 打印设置。
 *
 * ## 蓝牙与云打印互为补充
 *
 * 蓝牙零成本复用商家现有设备,但依赖商家手机在场;
 * 云打印(服务端飞鹅直推)反之。两者都配置时会各出一张 —— 这一点要说明,
 * 否则商家会以为出了 bug 在重复打印。
 *
 * ## 配对必须去系统设置
 *
 * 鸿蒙侧应用内直接配对经典蓝牙的路子不通畅。这里**直说**,
 * 别让商家在应用里点半天没反应,然后打客服说打印机坏了。
 */
@Component
export struct PrinterPage {
  onBack: () => void = () => {};
  shopName: string = '';

  @State private paired: PairedDevice[] = [];
  @State private saved: PairedDevice | null = null;
  @State private autoPrint: boolean = true;
  @State private scanning: boolean = false;
  @State private btError: string = '';

  /** 云打印。拉不到时**不能**显示成「平台还未开通」 */
  @State private cloudLoaded: boolean = false;
  @State private cloudEnabled: boolean = false;
  @State private cloudError: string = '';
  @State private printers: Record<string, Object>[] = [];

  private api: MerchantApi = new MerchantApi();

  aboutToAppear(): void {
    this.loadLocal();
    this.loadCloud();
  }

  private async loadLocal(): Promise<void> {
    this.saved = await BtPrinter.savedDevice();
    this.autoPrint = await BtPrinter.autoPrintEnabled();
  }

  private async loadCloud(): Promise<void> {
    try {
      const s: Record<string, Object> = await this.api.printers();
      this.cloudEnabled = s['enabled'] === true;
      const raw: Object | undefined = s['items'];
      this.printers = (raw === undefined ? [] : raw) as Record<string, Object>[];
      this.cloudError = '';
    } catch (e) {
      // **不能**因此显示成「平台还未开通云打印」—— 那是一句关于平台的
      // 事实陈述,商家据此就不去绑打印机了
      this.cloudError = (e as ApiException).message;
    } finally {
      this.cloudLoaded = true;
    }
  }

  private async scan(): Promise<void> {
    this.scanning = true;
    this.btError = '';
    try {
      this.paired = await BtPrinter.pairedDevices();
      if (this.paired.length === 0) {
        this.btError = '系统里还没有配对过的蓝牙设备';
      }
    } catch (e) {
      this.btError = (e as Error).message;
    } finally {
      this.scanning = false;
    }
  }

  private async choose(d: PairedDevice): Promise<void> {
    await BtPrinter.saveDevice(d.addr, d.name);
    this.saved = d;
    promptAction.showToast({ message: `已选「${d.name}」,先打一张测试页看看` });
  }

  private async test(): Promise<void> {
    const err: string | null = await BtPrinter.printTest(this.shopName);
    if (err === NO_DEVICE) {
      promptAction.showToast({ message: '先选一台打印机' });
      return;
    }
    promptAction.showToast({
      message: err === null ? '已出票,去看看纸出来没有' : err,
    });
  }

  private async unbind(): Promise<void> {
    await BtPrinter.clearDevice();
    this.saved = null;
    promptAction.showToast({ message: '已解除绑定' });
  }

  @Builder
  private section(title: string) {
    Text(title)
      .fontSize(13).fontWeight(FontWeight.Medium)
      .fontColor($r('app.color.ink'))
      .width('100%').margin({ bottom: 8 });
  }

  build() {
    Column() {
      Row({ space: 10 }) {
        Text('‹').fontSize(24).fontColor($r('app.color.ink'))
          .onClick(() => { this.onBack(); });
        Text('打印设置')
          .fontSize(17).fontWeight(FontWeight.Bold)
          .fontColor($r('app.color.ink')).layoutWeight(1);
      }
      .width('100%')
      .padding({ left: 14, right: 14, top: 10, bottom: 10 })
      .backgroundColor($r('app.color.surface'));

      Scroll() {
        Column({ space: 12 }) {
          // ---- 蓝牙 ----
          Column({ space: 10 }) {
            this.section('蓝牙小票机');
            Text('通用 58mm 热敏小票机,市面上几十块的都认。' +
              '**先在系统设置里和打印机配对**,再回来这里选。')
              .fontSize(12).lineHeight(19)
              .fontColor($r('app.color.ink_muted')).width('100%');

            if (this.saved !== null) {
              Row() {
                Column({ space: 2 }) {
                  Text((this.saved as PairedDevice).name)
                    .fontSize(15).fontColor($r('app.color.ink'));
                  Text('已绑定').fontSize(11)
                    .fontColor($r('app.color.earn'));
                }
                .alignItems(HorizontalAlign.Start).layoutWeight(1);
                Button('解绑')
                  .fontSize(12).height(30).padding({ left: 12, right: 12 })
                  .backgroundColor($r('app.color.surface_alt'))
                  .fontColor($r('app.color.danger'))
                  .onClick(() => { this.unbind(); });
              }
              .width('100%');

              Row({ space: 10 }) {
                Text('来单自动打印')
                  .fontSize(14).fontColor($r('app.color.ink')).layoutWeight(1);
                Toggle({ type: ToggleType.Switch, isOn: this.autoPrint })
                  .selectedColor($r('app.color.brand'))
                  .onChange((on: boolean) => {
                    this.autoPrint = on;
                    BtPrinter.setAutoPrint(on);
                  });
              }
              .width('100%');

              Button('打一张测试页')
                .width('100%').height(42)
                .backgroundColor($r('app.color.surface_alt'))
                .fontColor($r('app.color.ink'))
                .onClick(() => { this.test(); });
            }

            Button(this.scanning ? '读取中…' : '选择已配对的打印机')
              .width('100%').height(42)
              .backgroundColor($r('app.color.brand'))
              .enabled(!this.scanning)
              .onClick(() => { this.scan(); });

            if (this.btError.length > 0) {
              Text(this.btError)
                .fontSize(12).fontColor($r('app.color.danger')).width('100%');
            }

            ForEach(this.paired, (d: PairedDevice) => {
              Row() {
                Column({ space: 2 }) {
                  Text(d.name).fontSize(14)
                    .fontColor($r('app.color.ink'));
                  Text(d.addr).fontSize(11)
                    .fontColor($r('app.color.ink_muted'));
                }
                .alignItems(HorizontalAlign.Start).layoutWeight(1);
                if (this.saved !== null
                    && (this.saved as PairedDevice).addr === d.addr) {
                  Text('当前').fontSize(12).fontColor($r('app.color.brand'));
                }
              }
              .width('100%').padding({ top: 8, bottom: 8 })
              .onClick(() => { this.choose(d); });
              Divider().color($r('app.color.line'));
            }, (d: PairedDevice) => d.addr);
          }
          .width('100%').padding(14)
          .backgroundColor($r('app.color.surface')).borderRadius(12);

          // ---- 云打印 ----
          Column({ space: 10 }) {
            this.section('云打印机(推荐)');
            Text('打印机自带流量卡/WiFi 联网,新订单支付成功后平台直接推送出票 ——' +
              '手机没电、应用被杀都不影响。支持飞鹅系列。')
              .fontSize(12).lineHeight(19)
              .fontColor($r('app.color.ink_muted')).width('100%');

            if (!this.cloudLoaded) {
              LoadingProgress().width(28).height(28);
            } else if (this.cloudError.length > 0) {
              // 只缺这一块,页面主体还能用 —— 用横幅而不是整页错误态
              Row({ space: 8 }) {
                Text('⚠').fontSize(14).fontColor($r('app.color.danger'));
                Text(`云打印配置没拉到(${this.cloudError}),开没开通现在说不准。点这里重试`)
                  .fontSize(12).lineHeight(18)
                  .fontColor($r('app.color.danger')).layoutWeight(1);
              }
              .width('100%').padding(10)
              .backgroundColor('#1AC0392B').borderRadius(8)
              .onClick(() => { this.loadCloud(); });
            } else if (!this.cloudEnabled) {
              Text('平台还未开通云打印服务,先用上面的蓝牙打印;开通后这里会自动亮起。')
                .fontSize(12).lineHeight(19)
                .fontColor($r('app.color.hold')).width('100%');
            } else if (this.printers.length === 0) {
              Text('还没有绑定云打印机')
                .fontSize(13).fontColor($r('app.color.ink_muted'))
                .width('100%');
            } else {
              ForEach(this.printers, (p: Record<string, Object>) => {
                Row() {
                  Text(`${p['name'] ?? p['sn']}`)
                    .fontSize(14).fontColor($r('app.color.ink')).layoutWeight(1);
                  Text(`${p['status_label'] ?? ''}`)
                    .fontSize(12).fontColor($r('app.color.ink_muted'));
                }
                .width('100%').padding({ top: 8, bottom: 8 });
                Divider().color($r('app.color.line'));
              }, (p: Record<string, Object>) => `${p['id']}`);
            }
          }
          .width('100%').padding(14)
          .backgroundColor($r('app.color.surface')).borderRadius(12);

          // 两个都配了会各出一张 —— 说清楚,免得商家以为是 bug
          if (this.saved !== null && this.cloudEnabled) {
            Text('你同时配了蓝牙和云打印,新单会各出一张票。只想要一张的话,'
              + '把上面的「来单自动打印」关掉。')
              .fontSize(12).lineHeight(19)
              .fontColor($r('app.color.hold'))
              .width('100%').padding(12)
              .backgroundColor($r('app.color.surface_alt')).borderRadius(10);
          }

          Blank().height(30);
        }
        .width('100%').padding(12);
      }
      .layoutWeight(1).scrollBar(BarState.Off);
    }
    .width('100%').height('100%')
    .backgroundColor($r('app.color.page'));
  }
}
