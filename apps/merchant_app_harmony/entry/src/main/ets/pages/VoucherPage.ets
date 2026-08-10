import { promptAction } from '@kit.ArkUI';
import { scanBarcode, scanCore } from '@kit.ScanKit';
import { BusinessError } from '@kit.BasicServicesKit';
import { hilog } from '@kit.PerformanceAnalysisKit';
import { MerchantApi } from '../common/MerchantApi';
import { ApiException } from '../common/Api';
import { yuan } from '../common/Money';

const DOMAIN: number = 0x0001;
const TAG: string = 'superz';

/**
 * 团购券核销。
 *
 * ## 核销才收 2%,未核销随时全额退
 *
 * 这是这条业务和别家最不一样的地方,**核销结果里要把这笔账摊开**:
 * 售价多少、服务费多少、本单应收多少。商家当场就能对上,
 * 不用等月底看账单才发现被抽了多少。
 *
 * ## Scan Kit 不用申请相机权限
 *
 * 默认界面扫码由系统托管相机,应用侧零权限声明 —— 比安卓端还省一步
 * (安卓端要先弹一次权限说明再申请 CAMERA)。
 *
 * ## 扫不了要能手输
 *
 * 顾客手机屏碎了、二维码糊了、店里光线暗,这些都会发生。
 * **手输入口一直摆在那儿**,不是藏在"扫码失败"之后 ——
 * 取餐窗口前不能让商家先失败一次才找到备选路径。
 */
@Component
export struct VoucherPage {
  onBack: () => void = () => {};

  @State private code: string = '';
  @State private busy: boolean = false;
  @State private deals: Record<string, Object>[] = [];
  @State private loaded: boolean = false;
  @State private errorText: string = '';

  /** 核销成功的结果。非空时弹结果面板 */
  @State private result: Record<string, Object> | null = null;

  private api: MerchantApi = new MerchantApi();

  aboutToAppear(): void {
    this.load();
  }

  private async load(): Promise<void> {
    try {
      this.deals = await this.api.myVoucherDeals();
      this.errorText = '';
    } catch (e) {
      this.errorText = (e as ApiException).message;
    } finally {
      this.loaded = true;
    }
  }

  /** 扫顾客的券码二维码(二维码内容即券码) */
  private async scan(): Promise<void> {
    const options: scanBarcode.ScanOptions = {
      scanTypes: [scanCore.ScanType.QR_CODE, scanCore.ScanType.CODE_128],
      enableMultiMode: false,
      // 允许从相册选:顾客把券截图发过来的情况不少
      enableAlbum: true,
    };
    try {
      const r: scanBarcode.ScanResult =
          await scanBarcode.startScanForResult(getContext(this), options);
      const scanned: string = (r.originalValue ?? '').trim();
      if (scanned.length === 0) {
        return;
      }
      await this.redeem(scanned);
    } catch (e) {
      // 用户按返回取消扫码也会走到这里。**不能报错** ——
      // 主动取消不是故障,弹个红字只会让人以为出问题了
      const code: number = (e as BusinessError).code ?? 0;
      hilog.info(DOMAIN, TAG, '扫码结束 code=%{public}d', code);
    }
  }

  private async redeem(raw: string): Promise<void> {
    const code: string = raw.replace(/\s/g, '');
    if (code.length < 6) {
      promptAction.showToast({ message: '请输入完整券码' });
      return;
    }
    this.busy = true;
    try {
      this.result = await this.api.redeemVoucher(code);
      this.code = '';
    } catch (e) {
      promptAction.showToast({ message: (e as ApiException).message });
    } finally {
      this.busy = false;
    }
  }

  private num(m: Record<string, Object> | null, key: string): number {
    if (m === null) {
      return 0;
    }
    const v: Object | undefined = m[key];
    return v === undefined ? 0 : v as number;
  }

  @Builder
  private resultSheet() {
    Column({ space: 10 }) {
      Text('✓ 核销成功')
        .fontSize(20).fontWeight(FontWeight.Bold)
        .fontColor($r('app.color.earn')).width('100%');
      Text(`${this.result?.['title'] ?? ''}`)
        .fontSize(15).fontColor($r('app.color.ink')).width('100%');
      Text(`面值 ${yuan(this.num(this.result, 'face_value_cents'))}`)
        .fontSize(13).fontColor($r('app.color.ink_muted')).width('100%');

      Divider().color($r('app.color.line')).margin({ top: 4, bottom: 4 });

      // 这笔账当场摊开:核销才收 2%,商家不用等月底才知道被抽了多少
      Row() {
        Text('售价').fontSize(13)
          .fontColor($r('app.color.ink_muted')).layoutWeight(1);
        Text(yuan(this.num(this.result, 'sell_price_cents')))
          .fontSize(13).fontColor($r('app.color.ink'));
      }
      .width('100%');
      Row() {
        Text('平台服务费(2%)').fontSize(13)
          .fontColor($r('app.color.ink_muted')).layoutWeight(1);
        Text(`-${yuan(this.num(this.result, 'commission_cents'))}`)
          .fontSize(13).fontColor($r('app.color.hold'));
      }
      .width('100%');
      Row() {
        Text('本单应收').fontSize(14)
          .fontColor($r('app.color.ink')).layoutWeight(1);
        Text(yuan(this.num(this.result, 'net_cents')))
          .fontSize(20).fontWeight(FontWeight.Bold)
          .fontColor($r('app.color.earn'));
      }
      .width('100%');

      Button('好的')
        .width('100%').height(44)
        .backgroundColor($r('app.color.brand'))
        .margin({ top: 6 })
        .onClick(() => { this.result = null; });
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
        Text('团购券核销')
          .fontSize(17).fontWeight(FontWeight.Bold)
          .fontColor($r('app.color.ink')).layoutWeight(1);
      }
      .width('100%')
      .padding({ left: 14, right: 14, top: 10, bottom: 10 })
      .backgroundColor($r('app.color.surface'));

      Scroll() {
        Column({ space: 12 }) {
          Column({ space: 10 }) {
            Button(this.busy ? '核销中…' : '扫码核销')
              .width('100%').height(48)
              .backgroundColor($r('app.color.brand'))
              .enabled(!this.busy)
              .onClick(() => { this.scan(); });

            // 手输入口一直摆着,不藏在"扫码失败"之后
            Row({ space: 10 }) {
              TextInput({ placeholder: '或者手输券码', text: this.code })
                .height(44).layoutWeight(1)
                .onChange((v: string) => { this.code = v; });
              Button('核销')
                .height(44).width(74)
                .backgroundColor($r('app.color.surface_alt'))
                .fontColor($r('app.color.ink'))
                .enabled(!this.busy && this.code.trim().length >= 6)
                .onClick(() => { this.redeem(this.code); });
            }
            .width('100%');

            Text('顾客屏碎了、码糊了、店里光线暗都可能扫不出来,手输一样能核销')
              .fontSize(12).lineHeight(19)
              .fontColor($r('app.color.ink_muted')).width('100%');
          }
          .width('100%').padding(14)
          .backgroundColor($r('app.color.surface')).borderRadius(12);

          // ---- 在售的券 ----
          Column({ space: 0 }) {
            Text('在售团购券')
              .fontSize(13).fontWeight(FontWeight.Medium)
              .fontColor($r('app.color.ink'))
              .width('100%').margin({ bottom: 8 });

            if (!this.loaded) {
              LoadingProgress().width(28).height(28);
            } else if (this.errorText.length > 0) {
              // 只缺这一块,核销照样能用 —— 用横幅不用整页错误态
              Row({ space: 8 }) {
                Text('⚠').fontSize(14).fontColor($r('app.color.danger'));
                Text(`在售券没拉到(${this.errorText}),不影响核销。点这里重试`)
                  .fontSize(12).lineHeight(18)
                  .fontColor($r('app.color.danger')).layoutWeight(1);
              }
              .width('100%').padding(10)
              .backgroundColor('#1AC0392B').borderRadius(8)
              .onClick(() => { this.load(); });
            } else if (this.deals.length === 0) {
              Text('还没发布团购券\n低价引流,核销才收 2% 服务费')
                .fontSize(13).lineHeight(20)
                .fontColor($r('app.color.ink_muted'))
                .textAlign(TextAlign.Center).width('100%')
                .padding({ top: 16, bottom: 16 });
            } else {
              ForEach(this.deals, (d: Record<string, Object>) => {
                Row() {
                  Column({ space: 2 }) {
                    Text(`${d['title']}`).fontSize(14)
                      .fontColor($r('app.color.ink'));
                    Text(`售价 ${yuan(d['sell_price_cents'] as number)} · ` +
                      `面值 ${yuan(d['face_value_cents'] as number)} · ` +
                      `余 ${d['stock'] ?? 0}`)
                      .fontSize(11).fontColor($r('app.color.ink_muted'));
                  }
                  .alignItems(HorizontalAlign.Start).layoutWeight(1);
                }
                .width('100%').padding({ top: 9, bottom: 9 });
                Divider().color($r('app.color.line'));
              }, (d: Record<string, Object>) => `${d['id']}`);
            }
          }
          .width('100%').padding(14)
          .backgroundColor($r('app.color.surface')).borderRadius(12);

          Blank().height(30);
        }
        .width('100%').padding(12);
      }
      .layoutWeight(1).scrollBar(BarState.Off);
    }
    .width('100%').height('100%')
    .backgroundColor($r('app.color.page'))
    .bindSheet(this.result !== null, this.resultSheet(),
      { height: 320, dragBar: false });
  }
}
