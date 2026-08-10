import { common } from '@kit.AbilityKit';
import { promptAction } from '@kit.ArkUI';
import { MerchantApi } from '../common/MerchantApi';
import { ApiException } from '../common/Api';
import { pickAndUpload } from '../common/Upload';

/**
 * 微信特约商户进件。
 *
 * ## ⚠️ 这是整个商家端最敏感的一段
 *
 * 它碰身份证号和银行账户。三条规矩,**一条都不能破**:
 *
 * 1. **客户端永远拿不到明文**。服务端把敏感字段 Fernet 加密落库,
 *    回给客户端的只有尾 4 位(`legal_person_id_tail` / `settle_account_tail`)。
 *    所以输入框里**回填不了完整值**,只能在 placeholder 里显示「已保存,尾号 1234」;
 * 2. **空输入框 ≠ 清空**。商家再进这一页时输入框是空的,
 *    这时候提交如果把空串发上去,服务端已存的值就被清掉了 ——
 *    而他完全不知道自己刚把银行账户抹了。所以**只提交本次真填了的字段**;
 * 3. **不在客户端留任何副本**。不存 preferences、不放 AppStorage、
 *    不打日志。填完提交,内存里那份随页面销毁一起没。
 *
 * ## 为什么要进件
 *
 * 走服务商模式 + 分账,钱由微信直接结给商家,平台不碰资金池 ——
 * 这是合规的那条路(不进件就是二清,《非银行支付机构监督管理条例》管的就是这个)。
 * 这句话要写在页面上:商家凭什么把身份证给你,得有个说法。
 */
@Component
export struct ApplymentPage {
  onBack: () => void = () => {};

  @State private data: Record<string, Object> | null = null;
  @State private loaded: boolean = false;
  @State private errorText: string = '';
  @State private busy: boolean = false;

  // 非敏感字段:可以回填
  @State private legalName: string = '';
  @State private bankName: string = '';
  @State private accountName: string = '';
  @State private contactPhone: string = '';
  @State private idFront: string = '';
  @State private idBack: string = '';

  // 敏感字段:**只能填,不回填**。空 = 这次没改
  @State private idNo: string = '';
  @State private accountNo: string = '';

  @State private uploading: string = '';

  private api: MerchantApi = new MerchantApi();

  aboutToAppear(): void {
    this.load();
  }

  private s(key: string): string {
    const v: Object | undefined = this.data?.[key];
    return v === undefined ? '' : `${v}`;
  }

  private async load(): Promise<void> {
    try {
      const d: Record<string, Object> = await this.api.myApplyment();
      this.data = d;
      // 只回填非敏感字段
      this.legalName = this.s('legal_person_name');
      this.bankName = this.s('settle_bank_name');
      this.accountName = this.s('settle_account_name');
      this.contactPhone = this.s('contact_phone');
      this.idFront = this.s('legal_person_id_front_url');
      this.idBack = this.s('legal_person_id_back_url');
      this.errorText = '';
    } catch (e) {
      this.errorText = (e as ApiException).message;
    } finally {
      this.loaded = true;
    }
  }

  private async upload(which: string): Promise<void> {
    this.uploading = which;
    try {
      const url: string | null = await pickAndUpload(
          getContext(this) as common.UIAbilityContext, 'applyment');
      if (url !== null) {
        if (which === 'front') {
          this.idFront = url;
        } else {
          this.idBack = url;
        }
      }
    } catch (e) {
      promptAction.showToast({ message: (e as ApiException).message });
    } finally {
      this.uploading = '';
    }
  }

  /**
   * 提交。
   *
   * **只放本次真填了的字段。** 敏感字段留空就是「这次不改」,
   * 不是「清空」—— 把空串发上去会把服务端已存的银行账户抹掉,
   * 而商家完全不知道。
   */
  private async submit(): Promise<void> {
    const body: Record<string, Object> = {};
    if (this.legalName.trim().length > 0) {
      body['legal_person_name'] = this.legalName.trim();
    }
    if (this.bankName.trim().length > 0) {
      body['settle_bank_name'] = this.bankName.trim();
    }
    if (this.accountName.trim().length > 0) {
      body['settle_account_name'] = this.accountName.trim();
    }
    if (this.contactPhone.trim().length > 0) {
      body['contact_phone'] = this.contactPhone.trim();
    }
    if (this.idFront.length > 0) {
      body['legal_person_id_front_url'] = this.idFront;
    }
    if (this.idBack.length > 0) {
      body['legal_person_id_back_url'] = this.idBack;
    }
    // 敏感字段:只有真填了才提交
    if (this.idNo.trim().length > 0) {
      body['legal_person_id_no'] = this.idNo.trim();
    }
    if (this.accountNo.trim().length > 0) {
      body['settle_account_no'] = this.accountNo.trim();
    }

    if (Object.keys(body).length === 0) {
      promptAction.showToast({ message: '没有改动' });
      return;
    }

    this.busy = true;
    try {
      await this.api.saveApplyment(body);
      // 提交完立刻把敏感字段从内存里清掉,不留副本
      this.idNo = '';
      this.accountNo = '';
      await this.load();
      promptAction.showToast({ message: '已保存' });
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
      if (why.length > 0) {
        Text(why).fontSize(11).lineHeight(17)
          .fontColor($r('app.color.ink_muted')).width('100%');
      }
      TextInput({ placeholder: hint, text: value })
        .height(44).onChange(onChange);
    }
    .width('100%');
  }

  /**
   * 敏感字段的输入框。
   *
   * 已存过的显示「已保存,尾号 1234」当 placeholder ——
   * **不是把值填进去**,客户端根本拿不到完整值。
   */
  @Builder
  private secretField(label: string, why: string, tail: string,
                      value: string, onChange: (v: string) => void) {
    Column({ space: 4 }) {
      Text(label).fontSize(13).fontWeight(FontWeight.Medium)
        .fontColor($r('app.color.ink')).width('100%');
      Text(why).fontSize(11).lineHeight(17)
        .fontColor($r('app.color.ink_muted')).width('100%');
      TextInput({
        placeholder: tail.length > 0
            ? `已保存,尾号 ${tail}(留空就是不改)` : '填写完整号码',
        text: value,
      })
        .height(44).onChange(onChange);
      if (tail.length > 0) {
        Text('这一项已经存过了。留空提交不会动它 —— 要改才重新填。')
          .fontSize(11).fontColor($r('app.color.hold')).width('100%');
      }
    }
    .width('100%');
  }

  build() {
    Column() {
      Row({ space: 10 }) {
        Text('‹').fontSize(24).fontColor($r('app.color.ink'))
          .onClick(() => { this.onBack(); });
        Text('收款进件')
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
          Text('进件资料没能加载出来')
            .fontSize(15).fontColor($r('app.color.ink'));
          Text(`${this.errorText}\n\n空白不代表你还没提交过 —— 别重复填一遍。`)
            .fontSize(13).lineHeight(20)
            .fontColor($r('app.color.ink_muted')).textAlign(TextAlign.Center);
          Button('重试').height(40).width(130)
            .backgroundColor($r('app.color.brand'))
            .onClick(() => { this.load(); });
        }
        .layoutWeight(1).justifyContent(FlexAlign.Center).padding(30);
      } else {
        Scroll() {
          Column({ space: 14 }) {
            // 凭什么把身份证给你 —— 得有个说法
            Column({ space: 4 }) {
              Text('为什么要这些资料')
                .fontSize(13).fontWeight(FontWeight.Bold)
                .fontColor($r('app.color.ink')).width('100%');
              Text('进件之后,顾客付的钱由微信**直接结给你**,平台不碰资金池。' +
                '平台的 5% 走分账自动扣,不经过我们的账户 ——\n\n' +
                '这是合规的那条路。不进件的话就是平台代收代付,' +
                '也就是「二清」,那条路我们不走。')
                .fontSize(12).lineHeight(20)
                .fontColor($r('app.color.ink_muted')).width('100%');
            }
            .width('100%').padding(14)
            .backgroundColor($r('app.color.surface_alt')).borderRadius(12);

            if (this.s('status_label').length > 0) {
              Row() {
                Text('当前状态').fontSize(13)
                  .fontColor($r('app.color.ink_muted')).layoutWeight(1);
                Text(this.s('status_label'))
                  .fontSize(14).fontWeight(FontWeight.Medium)
                  .fontColor($r('app.color.hold'));
              }
              .width('100%').padding(14)
              .backgroundColor($r('app.color.surface')).borderRadius(12);
            }

            Column({ space: 12 }) {
              this.field('法人姓名', '要和身份证上一致',
                this.legalName, '', (v: string) => { this.legalName = v; });

              this.secretField('法人身份证号',
                '微信侧实名核验用。**平台这边加密存储,谁都看不到明文**,' +
                '连我们自己的后台也只显示尾号',
                this.s('legal_person_id_tail'), this.idNo,
                (v: string) => { this.idNo = v; });

              Column({ space: 4 }) {
                Text('身份证照片').fontSize(13).fontWeight(FontWeight.Medium)
                  .fontColor($r('app.color.ink')).width('100%');
                Text('人像面和国徽面各一张。只给微信核验用,不公开')
                  .fontSize(11).fontColor($r('app.color.ink_muted'))
                  .width('100%');
                Row({ space: 10 }) {
                  Button(this.uploading === 'front' ? '上传中…'
                    : this.idFront.length > 0 ? '✓ 人像面' : '传人像面')
                    .layoutWeight(1).height(42)
                    .backgroundColor(this.idFront.length > 0
                      ? $r('app.color.surface_alt') : $r('app.color.brand'))
                    .fontColor(this.idFront.length > 0
                      ? $r('app.color.ink') : Color.White)
                    .enabled(this.uploading.length === 0)
                    .onClick(() => { this.upload('front'); });
                  Button(this.uploading === 'back' ? '上传中…'
                    : this.idBack.length > 0 ? '✓ 国徽面' : '传国徽面')
                    .layoutWeight(1).height(42)
                    .backgroundColor(this.idBack.length > 0
                      ? $r('app.color.surface_alt') : $r('app.color.brand'))
                    .fontColor(this.idBack.length > 0
                      ? $r('app.color.ink') : Color.White)
                    .enabled(this.uploading.length === 0)
                    .onClick(() => { this.upload('back'); });
                }
                .width('100%');
              }
              .width('100%');
            }
            .width('100%').padding(14)
            .backgroundColor($r('app.color.surface')).borderRadius(12);

            Column({ space: 12 }) {
              Text('结算账户')
                .fontSize(13).fontWeight(FontWeight.Bold)
                .fontColor($r('app.color.ink')).width('100%');
              Text('钱打到这张卡。**户名必须和法人姓名一致**,对不上微信会驳回')
                .fontSize(11).lineHeight(17)
                .fontColor($r('app.color.ink_muted')).width('100%');

              this.field('开户银行', '', this.bankName, '例:招商银行',
                (v: string) => { this.bankName = v; });
              this.field('账户名', '', this.accountName, '和法人姓名一致',
                (v: string) => { this.accountName = v; });
              this.secretField('银行账号',
                '加密存储,平台后台只显示尾号',
                this.s('settle_account_tail'), this.accountNo,
                (v: string) => { this.accountNo = v; });
              this.field('联系电话', '微信把进件进度通知发到这个号',
                this.contactPhone, '', (v: string) => { this.contactPhone = v; });
            }
            .width('100%').padding(14)
            .backgroundColor($r('app.color.surface')).borderRadius(12);

            Button(this.busy ? '保存中…' : '保存')
              .width('100%').height(48)
              .backgroundColor($r('app.color.brand'))
              .enabled(!this.busy)
              .onClick(() => { this.submit(); });

            Text('提交之后微信还会有两步要你本人操作:验证打款金额、' +
              '超级管理员本人扫码签约。到那一步这里会提示你。')
              .fontSize(12).lineHeight(19)
              .fontColor($r('app.color.ink_muted')).width('100%');

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
