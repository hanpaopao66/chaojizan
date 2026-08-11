import { abilityAccessCtrl, common, Permissions } from '@kit.AbilityKit';
import { geoLocationManager } from '@kit.LocationKit';
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
 *
 * ## 地址不让商家自己打字
 *
 * 老板填店址时多半就站在店里,所以**进这一页就自动定位**,逆地理反查出
 * 主地址;店在商场里、定位飘了就搜店名跳过去。这两条都能定坐标,
 * 而坐标才是真正起作用的东西 —— 它决定谁能搜到这家店、配送费怎么算。
 * 让商家打字填地址,填出来的和实际坐标对不上是常事。
 *
 * **但输入框不能全删。** 腾讯逆地理给不出门牌号(`geo.py` 那段注释也承认
 * 只能给到「XX 大厦」这种参照物),而「3 栋 502」「美食城 B12 号铺」
 * 恰恰是骑手真正靠它找到店的信息。所以主地址只读、由定位或搜索决定,
 * 输入框降级成「门牌 / 几号铺」这一项。
 */
@Component
export struct OnboardingPage {
  onDone: () => void = () => {};

  @State private name: string = '';
  @State private description: string = '';
  /** 主地址:**只读**,由定位或搜索决定。商家改不了它,只能重新定位/重搜 */
  @State private address: string = '';
  /** 门牌 / 几号铺 / 楼层。逆地理给不出这一段,只能商家自己补 */
  @State private detail: string = '';
  @State private locating: boolean = false;
  @State private keyword: string = '';
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

  aboutToAppear(): void {
    // 进页面就定位 —— 老板多半就站在店里。**不等他点按钮**:
    // 那个按钮他不一定会点,而不点的后果是坐标全靠打字反查,常常差几百米
    this.locate();
  }

  private get dirty(): boolean {
    return this.name.length > 0 || this.address.length > 0
        || this.licenseNo.length > 0 || this.licenseImage.length > 0;
  }

  /**
   * 用当前位置定位,再逆地理反查出主地址。
   *
   * 拒权限不阻塞:退回搜索那条路。**但要说清楚** ——
   * 不说的话商家会以为定位坏了,反复点。
   */
  private async locate(): Promise<void> {
    if (this.locating) {
      return;
    }
    this.locating = true;
    try {
      const context = getContext(this) as common.UIAbilityContext;
      const perms: Permissions[] = ['ohos.permission.APPROXIMATELY_LOCATION'];
      const granted = await abilityAccessCtrl.createAtManager()
          .requestPermissionsFromUser(context, perms);
      if (granted.authResults.length === 0 || granted.authResults[0] !== 0) {
        promptAction.showToast({ message: '没给定位权限,用下面的搜索找到你的店' });
        return;
      }
      const req: geoLocationManager.CurrentLocationRequest = {
        priority: geoLocationManager.LocationRequestPriority.ACCURACY,
        scenario: geoLocationManager.LocationRequestScenario.UNSET,
        timeoutMs: 8000,
      };
      const loc = await geoLocationManager.getCurrentLocation(req);
      this.lat = loc.latitude;
      this.lng = loc.longitude;
      // 逆地理:把坐标变成一句人话。失败不影响 —— 坐标已经拿到了,
      // 而坐标才是起作用的那个东西
      try {
        const poi: Record<string, Object> =
            await this.api.geoReverse(this.lat, this.lng);
        const name: string = `${poi['name'] ?? ''}`;
        if (name.length > 0) {
          this.address = name;
        }
      } catch (_) {
        this.address = '已定位(地址名没取到,不影响)';
      }
    } catch (_) {
      promptAction.showToast({ message: '定位失败,用下面的搜索找到你的店' });
    } finally {
      this.locating = false;
    }
  }

  /** 搜店名。走服务端代理的腾讯位置服务,Key 不进客户端 */
  private async search(): Promise<void> {
    if (this.keyword.trim().length < 2) {
      return;
    }
    try {
      this.tips = await this.api.geoTips(this.keyword.trim(),
        this.lat === 0 ? undefined : this.lat,
        this.lng === 0 ? undefined : this.lng);
      if (this.tips.length === 0) {
        promptAction.showToast({ message: '没搜到,换个说法试试(比如带上街道名)' });
      }
    } catch (e) {
      promptAction.showToast({ message: (e as ApiException).message });
    }
  }

  private pickTip(t: Record<string, Object>): void {
    this.address = `${t['name'] ?? ''}`;
    this.lat = (t['lat'] ?? 0) as number;
    this.lng = (t['lng'] ?? 0) as number;
    this.tips = [];
    this.keyword = '';
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
      out.push('门店位置(点「重新定位」或搜店名)');
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
        // 主地址(定位/搜索来的)+ 门牌(商家补的)拼成一条。
        // 服务端只有一个 address 字段
        address: this.detail.trim().length > 0
            ? `${this.address.trim()} ${this.detail.trim()}`
            : this.address.trim(),
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

            Column({ space: 6 }) {
              Text('门店位置').fontSize(13).fontWeight(FontWeight.Medium)
                .fontColor($r('app.color.ink')).width('100%');
              Text('决定谁能搜到你、配送费怎么算。' +
                '你要是就在店里,下面这个地址应该已经对了')
                .fontSize(11).lineHeight(17)
                .fontColor($r('app.color.ink_muted')).width('100%');

              // 主地址:**只读**。它由定位或搜索决定,不让打字 ——
              // 打出来的地址和实际坐标对不上是常事,
              // 而真正起作用的是坐标
              Row({ space: 10 }) {
                Column({ space: 2 }) {
                  Text(this.address.length > 0
                    ? this.address
                    : (this.locating ? '正在定位…' : '还没定位'))
                    .fontSize(15)
                    .fontColor(this.address.length > 0
                      ? $r('app.color.ink') : $r('app.color.ink_muted'));
                  if (this.lat !== 0) {
                    Text(`已定位 ${this.lat.toFixed(5)}, ${this.lng.toFixed(5)}`)
                      .fontSize(11).fontColor($r('app.color.earn'));
                  }
                }
                .alignItems(HorizontalAlign.Start).layoutWeight(1);
                Button(this.locating ? '定位中' : '重新定位')
                  .fontSize(12).height(32).padding({ left: 12, right: 12 })
                  .backgroundColor($r('app.color.surface_alt'))
                  .fontColor($r('app.color.ink'))
                  .enabled(!this.locating)
                  .onClick(() => { this.locate(); });
              }
              .width('100%').padding(12)
              .backgroundColor($r('app.color.surface_alt')).borderRadius(10);

              // 店在商场里、定位飘了就搜店名跳过去
              Row({ space: 8 }) {
                TextInput({ placeholder: '定位不准?搜店名或地标', text: this.keyword })
                  .height(42).layoutWeight(1)
                  .onChange((v: string) => { this.keyword = v; })
                  .onSubmit(() => { this.search(); });
                Button('搜')
                  .fontSize(13).height(42).width(56)
                  .backgroundColor($r('app.color.brand'))
                  .enabled(this.keyword.trim().length >= 2)
                  .onClick(() => { this.search(); });
              }
              .width('100%');

              if (this.tips.length > 0) {
                ForEach(this.tips.slice(0, 6),
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

              // 门牌这一段机器给不出来,只能商家自己补 ——
              // 而这恰恰是骑手真正靠它找到店的信息
              TextInput({ placeholder: '门牌 / 几号铺 / 楼层(选填,但骑手很需要)',
                text: this.detail })
                .height(44)
                .onChange((v: string) => { this.detail = v; });
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
