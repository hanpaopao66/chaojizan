import { promptAction } from '@kit.ArkUI';
import { MerchantApi } from '../common/MerchantApi';
import { ApiException } from '../common/Api';
import { Shop } from '../model/Models';

/**
 * 经营设置:店员、节假日计划、出餐承诺、明厨亮灶。
 *
 * 这四项在安卓端分散在 `shop_tab.dart`(2100 行,刚拆过)和几个独立页里。
 * 鸿蒙端合成一页,**因为它们的共同点是「一个月改一次」** ——
 * 分成四个入口只会让商家找不着。
 *
 * ## 店员权限边界要写在面板上
 *
 * 店员能接单/出餐/估清,**不能提现/改价/改设置**。写出来,
 * 免得店主以为加了店员对方就能替他管账。
 *
 * ## 出餐承诺是承诺,不是估计
 *
 * 填的数字会显示给顾客,超时会计入品质分。所以旁边要给**实测值** ——
 * 让商家照着自己的实际出餐时长填,而不是拍一个好看的数字。
 */
@Component
export struct OperationsPage {
  @Prop shop: Shop;
  onBack: () => void = () => {};
  onChanged: () => void = () => {};

  @State private staff: Record<string, Object>[] = [];
  @State private staffError: string = '';
  @State private prep: Record<string, Object> | null = null;
  @State private cam: Record<string, Object> | null = null;
  @State private loaded: boolean = false;
  @State private busy: boolean = false;

  /** 加店员 */
  @State private showStaff: boolean = false;
  @State private sPhone: string = '';
  @State private sName: string = '';

  /** 出餐承诺 */
  @State private showPrep: boolean = false;
  @State private prepMinutes: string = '';

  /** 明厨亮灶 */
  @State private showCam: boolean = false;
  @State private camUrl: string = '';

  /** 节假日计划 */
  @State private plans: Record<string, Object>[] = [];
  @State private showPlan: boolean = false;
  @State private planFrom: string = '';
  @State private planTo: string = '';

  private api: MerchantApi = new MerchantApi();

  aboutToAppear(): void {
    this.plans = (this.shop.holiday_plans ?? []) as Record<string, Object>[];
    this.load();
  }

  private async load(): Promise<void> {
    // 三条互不依赖,先都发出去
    const staffF: Promise<Record<string, Object>[]> = this.api.myStaff();
    const prepF: Promise<Record<string, Object>> = this.api.merchantPrepTime();
    const camF: Promise<Record<string, Object>> =
        this.api.merchantKitchenCam();

    try {
      this.prep = await prepF;
    } catch (_) {
      // 出餐承诺拉不到只是少显示实测值,不拦着管店员
    }
    try {
      this.cam = await camF;
    } catch (_) {
      // 明厨亮灶同上
    }
    try {
      this.staff = await staffF;
      this.staffError = '';
    } catch (e) {
      // **不能吞**:拉不到就显示空名单的话,店主会以为店员已经清光了,
      // 而那些账号还能听单、还能改菜单
      this.staffError = (e as ApiException).message;
    }
    this.loaded = true;
  }

  // ---------- 店员 ----------

  private async addStaff(): Promise<void> {
    if (this.sPhone.trim().length < 11) {
      promptAction.showToast({ message: '填一个 11 位手机号' });
      return;
    }
    this.busy = true;
    try {
      await this.api.addStaff(this.sPhone.trim(), this.sName.trim());
      this.showStaff = false;
      this.sPhone = '';
      this.sName = '';
      await this.load();
      promptAction.showToast({ message: '已添加' });
    } catch (e) {
      promptAction.showToast({ message: (e as ApiException).message });
    } finally {
      this.busy = false;
    }
  }

  private async removeStaff(s: Record<string, Object>): Promise<void> {
    try {
      await this.api.removeStaff(s['user_id'] as number);
      await this.load();
      promptAction.showToast({ message: `已移除 ${s['name'] ?? ''}` });
    } catch (e) {
      promptAction.showToast({ message: (e as ApiException).message });
    }
  }

  // ---------- 出餐承诺 ----------

  private async savePrep(): Promise<void> {
    const m: number = Number.parseInt(this.prepMinutes);
    if (isNaN(m) || m <= 0) {
      promptAction.showToast({ message: '填一个分钟数' });
      return;
    }
    this.busy = true;
    try {
      await this.api.updateShop({ promise_minutes: m } as object);
      this.showPrep = false;
      await this.load();
      this.onChanged();
      promptAction.showToast({ message: `出餐承诺改成 ${m} 分钟` });
    } catch (e) {
      promptAction.showToast({ message: (e as ApiException).message });
    } finally {
      this.busy = false;
    }
  }

  // ---------- 明厨亮灶 ----------

  private async saveCam(): Promise<void> {
    this.busy = true;
    try {
      await this.api.setMerchantKitchenCam({ url: this.camUrl.trim() } as object);
      this.showCam = false;
      await this.load();
      promptAction.showToast({ message: '已保存' });
    } catch (e) {
      promptAction.showToast({ message: (e as ApiException).message });
    } finally {
      this.busy = false;
    }
  }

  private async removeCam(): Promise<void> {
    try {
      await this.api.removeMerchantKitchenCam();
      await this.load();
      promptAction.showToast({ message: '已撤下' });
    } catch (e) {
      promptAction.showToast({ message: (e as ApiException).message });
    }
  }

  // ---------- 节假日计划 ----------

  private async savePlans(): Promise<void> {
    this.busy = true;
    try {
      await this.api.updateShop({ holiday_plans: this.plans } as object);
      this.showPlan = false;
      this.onChanged();
      promptAction.showToast({ message: '节假日计划已保存' });
    } catch (e) {
      promptAction.showToast({ message: (e as ApiException).message });
    } finally {
      this.busy = false;
    }
  }

  private addPlan(): void {
    if (this.planFrom.length < 10) {
      promptAction.showToast({ message: '填一个开始日期 YYYY-MM-DD' });
      return;
    }
    this.plans.push({
      from: this.planFrom,
      to: this.planTo.length >= 10 ? this.planTo : this.planFrom,
      closed: true,
    });
    this.plans = this.plans.slice();
    this.planFrom = '';
    this.planTo = '';
  }

  @Builder
  private staffSheet() {
    Column({ space: 10 }) {
      Text('添加店员')
        .fontSize(17).fontWeight(FontWeight.Bold)
        .fontColor($r('app.color.ink')).width('100%');
      Text('店员能接单/出餐/估清,不能提现/改价/改设置。对方需先下载 App 登录一次。')
        .fontSize(12).lineHeight(18)
        .fontColor($r('app.color.ink_muted')).width('100%');
      TextInput({ placeholder: '手机号', text: this.sPhone })
        .type(InputType.PhoneNumber).maxLength(11).height(44)
        .onChange((v: string) => { this.sPhone = v; });
      TextInput({ placeholder: '备注名(如:小王)', text: this.sName })
        .height(44).onChange((v: string) => { this.sName = v; });
      Row({ space: 10 }) {
        Button('取消')
          .layoutWeight(1).height(44)
          .backgroundColor($r('app.color.surface_alt'))
          .fontColor($r('app.color.ink'))
          .onClick(() => { this.showStaff = false; });
        Button(this.busy ? '添加中…' : '添加')
          .layoutWeight(1).height(44)
          .backgroundColor($r('app.color.brand'))
          .enabled(!this.busy)
          .onClick(() => { this.addStaff(); });
      }
      .width('100%');
    }
    .width('100%')
    .padding({ left: 18, right: 18, top: 18, bottom: 24 })
    .backgroundColor($r('app.color.surface'));
  }

  @Builder
  private prepSheet() {
    Column({ space: 10 }) {
      Text('出餐承诺')
        .fontSize(17).fontWeight(FontWeight.Bold)
        .fontColor($r('app.color.ink')).width('100%');
      // 给实测值:让他照实际填,而不是拍一个好看的数字
      Text(this.prep === null || this.prep['measured_p75'] === undefined
        ? '还没有足够的实测数据。先按你自己的感觉填,攒够单量后这里会给实测值。'
        : `你近 30 天的实测出餐时长:75% 的单在 ` +
          `${this.prep['measured_p75']} 分钟内出餐。`)
        .fontSize(12).lineHeight(18)
        .fontColor($r('app.color.ink')).width('100%');
      Text('这个数字会显示给顾客,超时会计入品质分。填得比实际短不会让单变多,只会让差评变多。')
        .fontSize(11).lineHeight(17)
        .fontColor($r('app.color.hold')).width('100%');
      TextInput({ placeholder: '分钟', text: this.prepMinutes })
        .type(InputType.Number).height(44)
        .onChange((v: string) => { this.prepMinutes = v; });
      Row({ space: 10 }) {
        Button('取消')
          .layoutWeight(1).height(44)
          .backgroundColor($r('app.color.surface_alt'))
          .fontColor($r('app.color.ink'))
          .onClick(() => { this.showPrep = false; });
        Button('保存')
          .layoutWeight(1).height(44)
          .backgroundColor($r('app.color.brand'))
          .enabled(!this.busy)
          .onClick(() => { this.savePrep(); });
      }
      .width('100%');
    }
    .width('100%')
    .padding({ left: 18, right: 18, top: 18, bottom: 24 })
    .backgroundColor($r('app.color.surface'));
  }

  @Builder
  private camSheet() {
    Column({ space: 10 }) {
      Text('明厨亮灶')
        .fontSize(17).fontWeight(FontWeight.Bold)
        .fontColor($r('app.color.ink')).width('100%');
      Text('把后厨摄像头的直播地址填进来,顾客在店铺页能直接看。' +
        '**没装的店也会显示「无明厨亮灶」** —— 这是法定公示项,' +
        '不是给有的店加徽章。')
        .fontSize(12).lineHeight(18)
        .fontColor($r('app.color.ink_muted')).width('100%');
      TextInput({ placeholder: '直播地址(m3u8 / flv)', text: this.camUrl })
        .height(44).onChange((v: string) => { this.camUrl = v; });
      Row({ space: 10 }) {
        Button('取消')
          .layoutWeight(1).height(44)
          .backgroundColor($r('app.color.surface_alt'))
          .fontColor($r('app.color.ink'))
          .onClick(() => { this.showCam = false; });
        Button('保存')
          .layoutWeight(1).height(44)
          .backgroundColor($r('app.color.brand'))
          .enabled(!this.busy && this.camUrl.trim().length > 0)
          .onClick(() => { this.saveCam(); });
      }
      .width('100%');
    }
    .width('100%')
    .padding({ left: 18, right: 18, top: 18, bottom: 24 })
    .backgroundColor($r('app.color.surface'));
  }

  @Builder
  private planSheet() {
    Column({ space: 10 }) {
      Text('节假日计划')
        .fontSize(17).fontWeight(FontWeight.Bold)
        .fontColor($r('app.color.ink')).width('100%');
      Text('提前告诉顾客哪几天不开门。顾客提前看得到,就不会下单之后被取消 ——' +
        '取消是差评的头号来源。')
        .fontSize(12).lineHeight(18)
        .fontColor($r('app.color.ink_muted')).width('100%');
      Row({ space: 8 }) {
        TextInput({ placeholder: '从 YYYY-MM-DD', text: this.planFrom })
          .height(42).layoutWeight(1)
          .onChange((v: string) => { this.planFrom = v; });
        TextInput({ placeholder: '到(可留空)', text: this.planTo })
          .height(42).layoutWeight(1)
          .onChange((v: string) => { this.planTo = v; });
      }
      .width('100%');
      Button('加一条歇业计划')
        .width('100%').height(40)
        .backgroundColor($r('app.color.surface_alt'))
        .fontColor($r('app.color.ink'))
        .onClick(() => { this.addPlan(); });

      ForEach(this.plans, (p: Record<string, Object>, i: number) => {
        Row() {
          Text(`${p['from']} ~ ${p['to']} 歇业`)
            .fontSize(13).fontColor($r('app.color.ink')).layoutWeight(1);
          Text('删').fontSize(13).fontColor($r('app.color.danger'))
            .onClick(() => {
              this.plans.splice(i, 1);
              this.plans = this.plans.slice();
            });
        }
        .width('100%').padding({ top: 6, bottom: 6 });
      }, (p: Record<string, Object>, i: number) => `pl${i}-${p['from']}`);

      Row({ space: 10 }) {
        Button('取消')
          .layoutWeight(1).height(44)
          .backgroundColor($r('app.color.surface_alt'))
          .fontColor($r('app.color.ink'))
          .onClick(() => { this.showPlan = false; });
        Button(this.busy ? '保存中…' : '保存')
          .layoutWeight(1).height(44)
          .backgroundColor($r('app.color.brand'))
          .enabled(!this.busy)
          .onClick(() => { this.savePlans(); });
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
        Text('经营设置')
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
            // ---- 店员 ----
            Column({ space: 8 }) {
              Row() {
                Text('店员(子账号)')
                  .fontSize(13).fontWeight(FontWeight.Medium)
                  .fontColor($r('app.color.ink')).layoutWeight(1);
                Text('添加')
                  .fontSize(13).fontColor($r('app.color.brand'))
                  .onClick(() => { this.showStaff = true; });
              }
              .width('100%');
              Text('店员能接单/出餐/估清,不能提现/改价/改设置。')
                .fontSize(11).fontColor($r('app.color.ink_muted'))
                .width('100%');

              if (this.staffError.length > 0) {
                // 空名单会让店主以为店员清光了,而那些账号还在听单
                Row({ space: 8 }) {
                  Text('⚠').fontSize(14).fontColor($r('app.color.danger'));
                  Text(`店员名单没拉到(${this.staffError})—— 下面的空白不代表没有店员。点这里重试`)
                    .fontSize(12).lineHeight(18)
                    .fontColor($r('app.color.danger')).layoutWeight(1);
                }
                .width('100%').padding(10)
                .backgroundColor('#1AC0392B').borderRadius(8)
                .onClick(() => { this.load(); });
              } else if (this.staff.length === 0) {
                Text('还没有店员')
                  .fontSize(13).fontColor($r('app.color.ink_muted'))
                  .width('100%').padding({ top: 10, bottom: 10 });
              } else {
                ForEach(this.staff, (s: Record<string, Object>) => {
                  Row() {
                    Column({ space: 2 }) {
                      Text(`${s['name'] ?? ''}`).fontSize(14)
                        .fontColor($r('app.color.ink'));
                      Text(`${s['phone'] ?? ''}`).fontSize(11)
                        .fontColor($r('app.color.ink_muted'));
                    }
                    .alignItems(HorizontalAlign.Start).layoutWeight(1);
                    Text('移除')
                      .fontSize(12).fontColor($r('app.color.danger'))
                      .onClick(() => { this.removeStaff(s); });
                  }
                  .width('100%').padding({ top: 9, bottom: 9 });
                  Divider().color($r('app.color.line'));
                }, (s: Record<string, Object>) => `${s['user_id']}`);
              }
            }
            .width('100%').padding(14)
            .backgroundColor($r('app.color.surface')).borderRadius(12);

            // ---- 其余三项 ----
            Column({ space: 0 }) {
              Row() {
                Column({ space: 2 }) {
                  Text('出餐承诺').fontSize(15)
                    .fontColor($r('app.color.ink'));
                  Text(this.prep === null
                    ? '未设置'
                    : `${this.prep['promise_minutes'] ?? '未设置'} 分钟`)
                    .fontSize(12).fontColor($r('app.color.ink_muted'));
                }
                .alignItems(HorizontalAlign.Start).layoutWeight(1);
                Text('›').fontSize(18).fontColor($r('app.color.ink_faint'));
              }
              .width('100%').padding({ top: 12, bottom: 12 })
              .onClick(() => {
                this.prepMinutes =
                    `${this.prep?.['promise_minutes'] ?? ''}`;
                this.showPrep = true;
              });
              Divider().color($r('app.color.line'));

              Row() {
                Column({ space: 2 }) {
                  Text('节假日计划').fontSize(15)
                    .fontColor($r('app.color.ink'));
                  Text(this.plans.length === 0
                    ? '未设置' : `已排 ${this.plans.length} 条`)
                    .fontSize(12).fontColor($r('app.color.ink_muted'));
                }
                .alignItems(HorizontalAlign.Start).layoutWeight(1);
                Text('›').fontSize(18).fontColor($r('app.color.ink_faint'));
              }
              .width('100%').padding({ top: 12, bottom: 12 })
              .onClick(() => { this.showPlan = true; });
              Divider().color($r('app.color.line'));

              Row() {
                Column({ space: 2 }) {
                  Text('明厨亮灶').fontSize(15)
                    .fontColor($r('app.color.ink'));
                  Text(this.cam !== null
                    && `${this.cam['url'] ?? ''}`.length > 0
                    ? '已开通,顾客可直接看后厨' : '未开通(顾客端会显示「无明厨亮灶」)')
                    .fontSize(12).fontColor($r('app.color.ink_muted'));
                }
                .alignItems(HorizontalAlign.Start).layoutWeight(1);
                if (this.cam !== null
                    && `${this.cam['url'] ?? ''}`.length > 0) {
                  Text('撤下')
                    .fontSize(12).fontColor($r('app.color.danger'))
                    .onClick(() => { this.removeCam(); });
                } else {
                  Text('›').fontSize(18).fontColor($r('app.color.ink_faint'));
                }
              }
              .width('100%').padding({ top: 12, bottom: 12 })
              .onClick(() => {
                this.camUrl = `${this.cam?.['url'] ?? ''}`;
                this.showCam = true;
              });
            }
            .width('100%').padding({ left: 14, right: 14 })
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
    .bindSheet($$this.showStaff, this.staffSheet(),
      { height: 320, dragBar: false })
    .bindSheet($$this.showPrep, this.prepSheet(),
      { height: 340, dragBar: false })
    .bindSheet($$this.showCam, this.camSheet(),
      { height: 320, dragBar: false })
    .bindSheet($$this.showPlan, this.planSheet(),
      { height: '70%', dragBar: true });
  }
}
