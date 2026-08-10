import { promptAction } from '@kit.ArkUI';
import { MerchantApi } from '../common/MerchantApi';
import { ApiException } from '../common/Api';
import { Shop } from '../model/Models';

/**
 * 资质:从业人员健康证 + 食品经营许可证续期。
 *
 * ## 两者的后果完全不同,界面上不能混
 *
 * - **健康证到期只提醒不停业**。证是按人的,一个员工过期停整家店不成比例;
 * - **食品经营许可证过期会停业**(过期后 7 天宽限期,之后暂停接单)。
 *
 * 把这两句话分别写在各自那一块上。混了商家会以为员工证过期也要停业,
 * 或者更糟 —— 以为许可证过期也只是提醒一下。
 *
 * ## 健康证离职归档不删除
 *
 * 监管查的是「当时在岗的人有没有证」。删掉等于把当时的合规记录也删了。
 *
 * ## 换证申请拉不到时不能显示成「没有待审申请」
 *
 * 那句话对应着「再交一份」的按钮,商家会重复提交。安卓端刚修过,
 * 见 DEV-PROMPTS-27 #240。
 */
@Component
export struct CertsPage {
  @Prop shop: Shop;
  onBack: () => void = () => {};

  @State private certs: Record<string, Object>[] = [];
  @State private certsError: string = '';
  @State private renewal: Record<string, Object> | null = null;
  @State private renewalError: string = '';
  @State private loaded: boolean = false;

  /** 新增健康证 */
  @State private showAdd: boolean = false;
  @State private busy: boolean = false;
  @State private fName: string = '';
  @State private fNo: string = '';
  @State private fExpires: string = '';

  private api: MerchantApi = new MerchantApi();

  aboutToAppear(): void {
    this.load();
  }

  private async load(): Promise<void> {
    // 两块互不依赖,先都发出去
    const certsF: Promise<Record<string, Object>[]> = this.api.healthCerts();
    const renewalF: Promise<Record<string, Object>> =
        this.api.myLicenseRenewal();

    try {
      this.certs = await certsF;
      this.certsError = '';
    } catch (e) {
      this.certsError = (e as ApiException).message;
    }

    try {
      const r: Record<string, Object> = await renewalF;
      const raw: Object | undefined = r['renewal'];
      this.renewal = raw === undefined ? null : raw as Record<string, Object>;
      this.renewalError = '';
    } catch (e) {
      // **不能装作没有**:这一页上「没有待审申请」直接对应着
      // 「再交一份」那个按钮,商家会重复提交
      this.renewalError = (e as ApiException).message;
    }

    this.loaded = true;
  }

  private async saveCert(): Promise<void> {
    if (this.fName.trim().length === 0) {
      promptAction.showToast({ message: '填一下员工姓名' });
      return;
    }
    this.busy = true;
    try {
      await this.api.saveHealthCert({
        name: this.fName.trim(),
        cert_no: this.fNo.trim(),
        expires_at: this.fExpires.trim(),
      } as object);
      this.showAdd = false;
      this.fName = '';
      this.fNo = '';
      this.fExpires = '';
      await this.load();
      promptAction.showToast({ message: '已录入' });
    } catch (e) {
      promptAction.showToast({ message: (e as ApiException).message });
    } finally {
      this.busy = false;
    }
  }

  /** 离职归档。**不是删除** —— 监管查的是当时在岗的人有没有证 */
  private async archive(c: Record<string, Object>): Promise<void> {
    try {
      await this.api.archiveHealthCert(c['id'] as number);
      await this.load();
      promptAction.showToast({ message: '已归档(记录保留)' });
    } catch (e) {
      promptAction.showToast({ message: (e as ApiException).message });
    }
  }

  @Builder
  private addSheet() {
    Column({ space: 10 }) {
      Text('录一张健康证')
        .fontSize(17).fontWeight(FontWeight.Bold)
        .fontColor($r('app.color.ink')).width('100%');
      Text('接触直接入口食品的员工每年体检、持证上岗(《食品安全法》四十五条)')
        .fontSize(12).lineHeight(18)
        .fontColor($r('app.color.ink_muted')).width('100%');
      TextInput({ placeholder: '员工姓名', text: this.fName })
        .height(44).onChange((v: string) => { this.fName = v; });
      TextInput({ placeholder: '证号(可留空)', text: this.fNo })
        .height(44).onChange((v: string) => { this.fNo = v; });
      TextInput({ placeholder: '有效期至 YYYY-MM-DD', text: this.fExpires })
        .height(44).onChange((v: string) => { this.fExpires = v; });
      Row({ space: 10 }) {
        Button('取消')
          .layoutWeight(1).height(44)
          .backgroundColor($r('app.color.surface_alt'))
          .fontColor($r('app.color.ink'))
          .onClick(() => { this.showAdd = false; });
        Button(this.busy ? '保存中…' : '保存')
          .layoutWeight(1).height(44)
          .backgroundColor($r('app.color.brand'))
          .enabled(!this.busy)
          .onClick(() => { this.saveCert(); });
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
        Text('资质')
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
      } else {
        Scroll() {
          Column({ space: 12 }) {
            // ---- 食品经营许可证 ----
            Column({ space: 8 }) {
              Text('食品经营许可证')
                .fontSize(13).fontWeight(FontWeight.Medium)
                .fontColor($r('app.color.ink')).width('100%');

              if (this.renewalError.length > 0) {
                // 只缺这一块,证照本身的信息还在 —— 用横幅不用整页错误态
                Row({ space: 8 }) {
                  Text('⚠').fontSize(14).fontColor($r('app.color.danger'));
                  Text('换证申请状态没拉到,下面显示的「没有待审申请」不一定是真的。点这里重试')
                    .fontSize(12).lineHeight(18)
                    .fontColor($r('app.color.danger')).layoutWeight(1);
                }
                .width('100%').padding(10)
                .backgroundColor('#1AC0392B').borderRadius(8)
                .onClick(() => { this.load(); });
              }

              if ((this.shop.license_expires_at ?? '').length > 0) {
                Row() {
                  Text('有效期至').fontSize(13)
                    .fontColor($r('app.color.ink_muted')).layoutWeight(1);
                  Text(this.shop.license_expires_at)
                    .fontSize(14).fontColor($r('app.color.ink'));
                }
                .width('100%');
                if (this.shop.license_days_left !== undefined) {
                  Text((this.shop.license_days_left as number) >= 0
                    ? `还剩 ${this.shop.license_days_left} 天`
                    : `已过期 ${-(this.shop.license_days_left as number)} 天`)
                    .fontSize(12)
                    .fontColor((this.shop.license_days_left as number) >= 30
                      ? $r('app.color.ink_muted') : $r('app.color.danger'))
                    .width('100%');
                }
              } else {
                Text('还没登记有效期。登记后我们会在到期前 30 / 7 / 1 天提醒你 ——' +
                  '证过期是静默失效,没人提醒就只能等监管上门。')
                  .fontSize(12).lineHeight(18)
                  .fontColor($r('app.color.hold')).width('100%');
              }

              if (this.renewal !== null
                  && this.renewal?.['status'] === 'pending') {
                Text(`新证核验中(编号 ${this.renewal?.['license_no'] ?? ''}),` +
                  '核验期间照常营业,通过后自动替换。')
                  .fontSize(12).lineHeight(18)
                  .fontColor($r('app.color.hold')).width('100%');
              } else if (this.renewalError.length === 0) {
                Text('提交新证要拍证照原件,这一版请在安卓端或网页端提交。')
                  .fontSize(12).lineHeight(18)
                  .fontColor($r('app.color.ink_muted')).width('100%');
              }

              // 后果:和健康证不一样,这一条会停业
              Text('过期后仍可营业 7 天,之后需人工核验新证才能恢复接单。')
                .fontSize(11).fontColor($r('app.color.danger')).width('100%');
            }
            .width('100%').padding(14)
            .backgroundColor($r('app.color.surface')).borderRadius(12);

            // ---- 健康证 ----
            Column({ space: 8 }) {
              Row() {
                Text('从业人员健康证')
                  .fontSize(13).fontWeight(FontWeight.Medium)
                  .fontColor($r('app.color.ink')).layoutWeight(1);
                Text('录一张')
                  .fontSize(13).fontColor($r('app.color.brand'))
                  .onClick(() => { this.showAdd = true; });
              }
              .width('100%');

              // 后果:和许可证不一样,这一条不停业
              Text('到期只提醒不停业 —— 证是按人的,一个员工过期停整家店不成比例。')
                .fontSize(11).lineHeight(17)
                .fontColor($r('app.color.ink_muted')).width('100%');

              if (this.certsError.length > 0) {
                Row({ space: 8 }) {
                  Text('⚠').fontSize(14).fontColor($r('app.color.danger'));
                  Text(`健康证台账没拉到(${this.certsError})。点这里重试`)
                    .fontSize(12).fontColor($r('app.color.danger'))
                    .layoutWeight(1);
                }
                .width('100%').padding(10)
                .backgroundColor('#1AC0392B').borderRadius(8)
                .onClick(() => { this.load(); });
              } else if (this.certs.length === 0) {
                Text('还没有录入健康证')
                  .fontSize(13).fontColor($r('app.color.ink_muted'))
                  .width('100%').padding({ top: 12, bottom: 12 });
              } else {
                ForEach(this.certs, (c: Record<string, Object>) => {
                  Row({ space: 10 }) {
                    Column({ space: 2 }) {
                      Text(`${c['name']}`).fontSize(14)
                        .fontColor($r('app.color.ink'));
                      Text(`有效期至 ${c['expires_at'] ?? '未填'}`)
                        .fontSize(11)
                        .fontColor(c['expired'] === true
                          ? $r('app.color.danger')
                          : $r('app.color.ink_muted'));
                    }
                    .alignItems(HorizontalAlign.Start).layoutWeight(1);
                    // 归档不是删除:监管查的是当时在岗的人有没有证
                    Text('离职归档')
                      .fontSize(12).fontColor($r('app.color.ink_muted'))
                      .onClick(() => { this.archive(c); });
                  }
                  .width('100%').padding({ top: 9, bottom: 9 });
                  Divider().color($r('app.color.line'));
                }, (c: Record<string, Object>) => `${c['id']}`);
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
    }
    .width('100%').height('100%')
    .backgroundColor($r('app.color.page'))
    .bindSheet($$this.showAdd, this.addSheet(),
      { height: 340, dragBar: false });
  }
}
