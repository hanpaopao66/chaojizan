import { common } from '@kit.AbilityKit';
import { promptAction } from '@kit.ArkUI';
import { UserApi } from '../common/UserApi';
import { ApiException } from '../common/Api';
import { pickAndUpload, UploadPurpose } from '../common/Upload';

/**
 * 申请售后。
 *
 * **两条路分开**:普通售后走商家先处理;食品安全是红线,不经商家直达平台。
 * 混成一个入口的后果是:吃出异物的投诉先转给被投诉的那一方,
 * 而那正是最不该由他处理的一类。
 *
 * 图片是必传的 —— 有图才谈得上快速判责,没图只能拖,拖到最后是用户吃亏。
 *
 * ⚠️ 未完成:**部分退款**(勾菜品/填金额)。安卓端也没有,只能整单发文字,
 * 少送一个菜要么全退要么不退,商家和用户两头不服。要服务端先支持。
 */
@Component
export struct AfterSalePage {
  orderNo: string = '';
  onDone: () => void = () => {};

  /** normal 普通售后 / food_safety 食安红线 */
  @State private kind: string = 'normal';
  /** 食安细分:foreign_object 异物 / spoiled 变质 / sick 食用后不适 */
  @State private fsKind: string = 'foreign_object';
  @State private reason: string = '';
  @State private images: string[] = [];
  @State private submitting: boolean = false;
  @State private uploading: boolean = false;

  private api: UserApi = new UserApi();

  /**
   * 选图并上传。**食安投诉的图落私密桶** —— 里面可能有医疗信息,
   * 在个保法下属于敏感个人信息,比身份证更不能公开直出
   */
  private async addPhotos(): Promise<void> {
    if (this.uploading) {
      return;
    }
    const left: number = 3 - this.images.length;
    if (left <= 0) {
      promptAction.showToast({ message: '最多 3 张' });
      return;
    }
    this.uploading = true;
    try {
      const ctx = getContext(this) as common.UIAbilityContext;
      const purpose: string = this.kind === 'food_safety'
        ? UploadPurpose.FOOD_SAFETY : UploadPurpose.AFTER_SALE;
      const urls: string[] = await pickAndUpload(ctx, purpose, left);
      if (urls.length > 0) {
        this.images = this.images.concat(urls);
      }
    } catch (e) {
      promptAction.showToast({ message: (e as ApiException).message });
    } finally {
      this.uploading = false;
    }
  }

  private async submit(): Promise<void> {
    const text: string = this.reason.trim();
    if (text.length === 0) {
      promptAction.showToast({ message: '说一下发生了什么' });
      return;
    }
    if (this.images.length === 0) {
      promptAction.showToast({ message: '请至少上传一张照片,有图才能快速判责' });
      return;
    }
    this.submitting = true;
    try {
      if (this.kind === 'food_safety') {
        await this.api.reportFoodSafety(this.orderNo, this.fsKind, text,
          this.images, []);
        promptAction.showToast({
          message: '已提交,平台会直接处理,不经过商家',
          duration: 3500,
        });
      } else {
        await this.api.createAfterSale(this.orderNo, text, this.images);
        promptAction.showToast({ message: '已提交,商家会先处理' });
      }
      this.onDone();
    } catch (e) {
      promptAction.showToast({ message: (e as ApiException).message });
    } finally {
      this.submitting = false;
    }
  }

  @Builder
  private kindTab(label: string, value: string, hint: string) {
    Column({ space: 2 }) {
      Text(label)
        .fontSize(14)
        .fontColor(this.kind === value
          ? $r('app.color.brand') : $r('app.color.ink'));
      Text(hint)
        .fontSize(11).fontColor($r('app.color.ink_muted'));
    }
    .layoutWeight(1).padding(10)
    .borderRadius(10)
    .backgroundColor(this.kind === value ? $r('app.color.brand_soft') : $r('app.color.surface'))
    .onClick(() => { this.kind = value; });
  }

  @Builder
  private fsChip(label: string, value: string) {
    Text(label)
      .fontSize(13)
      .padding({ left: 12, right: 12, top: 6, bottom: 6 })
      .margin({ right: 8 })
      .borderRadius(14)
      .backgroundColor(this.fsKind === value ? $r('app.color.brand_soft') : $r('app.color.surface_alt'))
      .fontColor(this.fsKind === value
        ? $r('app.color.brand') : $r('app.color.ink'))
      .onClick(() => { this.fsKind = value; });
  }

  build() {
    Scroll() {
      Column({ space: 12 }) {
        Row({ space: 8 }) {
          this.kindTab('普通售后', 'normal', '洒漏、少送、口味等,商家先处理');
          this.kindTab('食品安全', 'food_safety', '异物、变质、吃了不舒服');
        }
        .width('100%');

        if (this.kind === 'food_safety') {
          Column({ space: 8 }) {
            Text('这是红线通道')
              .fontSize(14).fontWeight(FontWeight.Medium)
              .fontColor($r('app.color.brand')).width('100%');
            Text('食安投诉**不经过商家**,直接由平台处理。' +
              '如果去过医院,可以一并上传凭证。')
              .fontSize(12).fontColor($r('app.color.ink_muted')).width('100%');
            Row() {
              this.fsChip('异物', 'foreign_object');
              this.fsChip('变质', 'spoiled');
              this.fsChip('食用后不适', 'sick');
            }
            .width('100%');
          }
          .width('100%').padding(14).backgroundColor($r('app.color.brand_soft'))
          .borderRadius(12).alignItems(HorizontalAlign.Start);
        }

        TextArea({ placeholder: '发生了什么?写具体一点,处理会更快', text: this.reason })
          .height(110)
          .onChange((v: string) => { this.reason = v; });

        Column({ space: 6 }) {
          Text(`照片(必传,已上传 ${this.images.length} 张)`)
            .fontSize(13).fontColor($r('app.color.ink_muted')).width('100%');
          Text('有图才能快速判责退款。没有图的话,处理会慢很多。')
            .fontSize(11).fontColor($r('app.color.ink_muted')).width('100%');
          // 走系统图库选择器:选完只给这几张的临时读权限,
          // **不申请相册权限、更不申请相机** —— 用不到的权限一个都不要
          Button(this.uploading ? '上传中…' : '从相册选择')
            .height(40).fontSize(13)
            .enabled(!this.uploading && this.images.length < 3)
            .backgroundColor($r('app.color.brand'))
            .onClick(() => { this.addPhotos(); });
          if (this.images.length > 0) {
            Row({ space: 8 }) {
              ForEach(this.images, (u: string) => {
                Text('已上传')
                  .fontSize(11).fontColor($r('app.color.earn'))
                  .padding({ left: 8, right: 8, top: 4, bottom: 4 })
                  .borderRadius(8).backgroundColor($r('app.color.earn_soft'))
                  .onClick(() => {
                    this.images = this.images.filter((x: string) => x !== u);
                  });
              }, (u: string) => u);
            }
            .width('100%');
            Text('点一下可以去掉某一张')
              .fontSize(11).fontColor($r('app.color.ink_muted')).width('100%');
          }
        }
        .width('100%').padding(14).backgroundColor($r('app.color.surface'))
        .borderRadius(12).alignItems(HorizontalAlign.Start);

        Button(this.submitting ? '提交中…' : '提交')
          .width('100%').height(46)
          .enabled(!this.submitting)
          .backgroundColor($r('app.color.brand'))
          .onClick(() => { this.submit(); });
      }
      .width('100%').padding(16).alignItems(HorizontalAlign.Start);
    }
    .width('100%').height('100%')
    .backgroundColor($r('app.color.page'));
  }
}
