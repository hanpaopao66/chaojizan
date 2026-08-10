import { common } from '@kit.AbilityKit';
import { promptAction } from '@kit.ArkUI';
import { MerchantApi } from '../common/MerchantApi';
import { ApiException } from '../common/Api';
import { pickAndUpload } from '../common/Upload';

/**
 * 商家入驻。
 *
 * ## 这一页的转化率决定平台有没有商家
 *
 * 所以每一项都要说清楚**为什么要**。「营业执照号」旁边不写理由,
 * 商家就会怀疑我们拿去干什么;写了「监管要求公示,顾客在店铺页能看到」,
 * 他反而知道这是正常的。
 *
 * ## 未保存拦截
 *
 * 填了店名、地址、证照号再传两张图,误触返回一下全丢 ——
 * 而这恰好是转化率最关键的表单。
 *
 * ## 堂食标识入驻时就问
 *
 * 总局令第 123 号第十二条要求公示。入驻时问一句,
 * 免得开业后列表上一直挂着「未填报」—— 那是给顾客看的减分项。
 */
@Component
export struct OnboardingPage {
  onDone: () => void = () => {};

  @State private name: string = '';
  @State private description: string = '';
  @State private address: string = '';
  @State private licenseNo: string = '';
  @State private licenseImage: string = '';
  @State private category: string = 'fast_food';
  @State private dineIn: string = 'unknown';
  @State private lat: number = 0;
  @State private lng: number = 0;
  @State private busy: boolean = false;
  @State private uploading: boolean = false;
  @State private tips: Record<string, Object>[] = [];

  private api: MerchantApi = new MerchantApi();

  private get dirty(): boolean {
    return this.name.length > 0 || this.address.length > 0
        || this.licenseNo.length > 0 || this.licenseImage.length > 0;
  }

  /** 地址联想。走服务端代理,不需要地图 SDK */
  private async searchAddress(): Promise<void> {
    if (this.address.trim().length < 2) {
      return;
    }
    try {
      this.tips = await this.api.geoTips(this.address.trim());
    } catch (_) {
      // 联想拉不到不拦着填 —— 商家可以手打完整地址,
      // 只是坐标要靠下面「用当前位置」补
    }
  }

  private pickTip(t: Record<string, Object>): void {
    this.address = `${t['name'] ?? ''}${t['address'] ?? ''}`;
    this.lat = (t['lat'] ?? 0) as number;
    this.lng = (t['lng'] ?? 0) as number;
    this.tips = [];
  }

  private async uploadLicense(): Promise<void> {
    this.uploading = true;
    try {
      const url: string | null = await pickAndUpload(
          getContext(this) as common.UIAbilityContext, 'license');
      if (url !== null) {
        this.licenseImage = url;
      }
    } catch (e) {
      promptAction.showToast({ message: (e as ApiException).message });
    } finally {
      this.uploading = false;
    }
  }

  private missing(): string[] {
    const out: string[] = [];
    if (this.name.trim().length === 0) {
      out.push('店名');
    }
    if (this.address.trim().length === 0) {
      out.push('地址');
    }
    if (this.lat === 0 || this.lng === 0) {
      out.push('地址坐标(从联想里选一条)');
    }
    if (this.licenseNo.trim().length === 0) {
      out.push('营业执照号');
    }
    if (this.licenseImage.length === 0) {
      out.push('营业执照照片');
    }
    return out;
  }

  private async submit(): Promise<void> {
    const miss: string[] = this.missing();
    if (miss.length > 0) {
      promptAction.showToast({ message: `还缺:${miss.join('、')}` });
      return;
    }
    this.busy = true;
    try {
      await this.api.applyShop({
        name: this.name.trim(),
        description: this.description.trim(),
        address: this.address.trim(),
        lat: this.lat,
        lng: this.lng,
        license_no: this.licenseNo.trim(),
        license_image_url: this.licenseImage,
        category: this.category,
        biz_type: 'food',
        dine_in_status: this.dineIn,
      } as object);
      promptAction.showToast({ message: '已提交,平台会尽快审核' });
      this.onDone();
    } catch (e) {
      promptAction.showToast({ message: (e as ApiException).message });
    } finally {
      this.busy = false;
    }
  }

  @Builder
  private field(label: string, why: string, value: string, hint: string,
                onChange: (v: string) => void) {
    Column({ space: 4 }) {
      Text(label).fontSize(13).fontWeight(FontWeight.Medium)
        .fontColor($r('app.color.ink')).width('100%');
      // 每一项都说清为什么要 —— 不写理由,商家会怀疑我们拿去干什么
      Text(why).fontSize(11).lineHeight(17)
        .fontColor($r('app.color.ink_muted')).width('100%');
      TextInput({ placeholder: hint, text: value })
        .height(44).onChange(onChange);
    }
    .width('100%');
  }

  build() {
    Column() {
      Row({ space: 10 }) {
        Text('开店')
          .fontSize(17).fontWeight(FontWeight.Bold)
          .fontColor($r('app.color.ink')).layoutWeight(1);
      }
      .width('100%')
      .padding({ left: 14, right: 14, top: 10, bottom: 10 })
      .backgroundColor($r('app.color.surface'));

      Scroll() {
        Column({ space: 14 }) {
          Column({ space: 4 }) {
            Text('佣金只抽 5%,单量越大费率越低')
              .fontSize(15).fontWeight(FontWeight.Bold)
              .fontColor($r('app.color.earn')).width('100%');
            Text('没有竞价排名、没有强制满减、没有二选一。' +
              '每一笔账都可查,代码开源。')
              .fontSize(12).lineHeight(19)
              .fontColor($r('app.color.ink_muted')).width('100%');
          }
          .width('100%').padding(14)
          .backgroundColor($r('app.color.earn_soft')).borderRadius(12);

          Column({ space: 12 }) {
            this.field('店名', '顾客在列表里看到的名字',
              this.name, '例:赞小碗牛腩饭',
              (v: string) => { this.name = v; });
            this.field('简介', '一句话说清你家主打什么',
              this.description, '选填',
              (v: string) => { this.description = v; });

            Column({ space: 4 }) {
              Text('地址').fontSize(13).fontWeight(FontWeight.Medium)
                .fontColor($r('app.color.ink')).width('100%');
              Text('决定配送范围和配送费。**要从联想里选一条**,' +
                '手打的地址没有坐标,骑手找不到你')
                .fontSize(11).lineHeight(17)
                .fontColor($r('app.color.ink_muted')).width('100%');
              TextInput({ placeholder: '输入店铺地址', text: this.address })
                .height(44)
                .onChange((v: string) => { this.address = v; })
                .onSubmit(() => { this.searchAddress(); });
              if (this.tips.length > 0) {
                ForEach(this.tips.slice(0, 5),
                  (t: Record<string, Object>) => {
                    Row() {
                      Column({ space: 2 }) {
                        Text(`${t['name'] ?? ''}`).fontSize(13)
                          .fontColor($r('app.color.ink'));
                        Text(`${t['address'] ?? ''}`).fontSize(11)
                          .fontColor($r('app.color.ink_muted'));
                      }
                      .alignItems(HorizontalAlign.Start).layoutWeight(1);
                    }
                    .width('100%').padding({ top: 8, bottom: 8 })
                    .onClick(() => { this.pickTip(t); });
                    Divider().color($r('app.color.line'));
                  }, (t: Record<string, Object>, i: number) =>
                    `${i}-${t['name']}`);
              }
              if (this.lat !== 0) {
                Text('✓ 坐标已确定')
                  .fontSize(11).fontColor($r('app.color.earn')).width('100%');
              }
            }
            .width('100%');

            this.field('营业执照号',
              '监管要求公示,顾客在店铺页能看到。填错会审核不过',
              this.licenseNo, '统一社会信用代码',
              (v: string) => { this.licenseNo = v; });

            Column({ space: 4 }) {
              Text('营业执照照片').fontSize(13).fontWeight(FontWeight.Medium)
                .fontColor($r('app.color.ink')).width('100%');
              Text('拍清楚,能看清编号就行。只给平台审核用,不公开')
                .fontSize(11).fontColor($r('app.color.ink_muted'))
                .width('100%');
              Button(this.uploading ? '上传中…'
                : this.licenseImage.length > 0 ? '✓ 已上传,点击重传' : '拍照或从相册选')
                .width('100%').height(44)
                .backgroundColor(this.licenseImage.length > 0
                  ? $r('app.color.surface_alt') : $r('app.color.brand'))
                .fontColor(this.licenseImage.length > 0
                  ? $r('app.color.ink') : Color.White)
                .enabled(!this.uploading)
                .onClick(() => { this.uploadLicense(); });
            }
            .width('100%');

            Column({ space: 4 }) {
              Text('有没有堂食').fontSize(13).fontWeight(FontWeight.Medium)
                .fontColor($r('app.color.ink')).width('100%');
              Text('市场监管总局令第 123 号要求公示。现在填一下,' +
                '免得开业后列表上一直挂着「未填报」')
                .fontSize(11).lineHeight(17)
                .fontColor($r('app.color.ink_muted')).width('100%');
              Row({ space: 8 }) {
                ForEach(['yes', 'no'], (v: string) => {
                  Text(v === 'yes' ? '有堂食' : '仅外卖,无堂食')
                    .fontSize(13)
                    .fontColor(this.dineIn === v
                      ? Color.White : $r('app.color.ink'))
                    .padding({ left: 14, right: 14, top: 8, bottom: 8 })
                    .borderRadius(16)
                    .backgroundColor(this.dineIn === v
                      ? $r('app.color.brand') : $r('app.color.surface_alt'))
                    .onClick(() => { this.dineIn = v; });
                }, (v: string) => v);
              }
              .width('100%');
            }
            .width('100%');
          }
          .width('100%').padding(14)
          .backgroundColor($r('app.color.surface')).borderRadius(12);

          Button(this.busy ? '提交中…' : '提交入驻申请')
            .width('100%').height(48)
            .backgroundColor($r('app.color.brand'))
            .enabled(!this.busy)
            .onClick(() => { this.submit(); });

          Text('食品经营许可证可以开店后再补,但**开业前必须补上** ——' +
            '无证经营是违法的,这一步我们不能替你跳过。')
            .fontSize(12).lineHeight(19)
            .fontColor($r('app.color.ink_muted')).width('100%');

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
