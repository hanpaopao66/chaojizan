import { common } from '@kit.AbilityKit';
import { promptAction } from '@kit.ArkUI';
import { UserApi } from '../common/UserApi';
import { ApiException } from '../common/Api';
import { pickAndUpload, UploadPurpose } from '../common/Upload';

/**
 * 写评价。
 *
 * **商家和骑手分开打分**,标签也分开挂 —— 菜不好吃不该算在骑手头上,
 * 送得慢也不该拉低商家评分。这是安卓端就定下的口径,不是新发明。
 *
 * **匿名是真匿名**:服务端不下发用户名,不是前端遮一下。
 */
@Component
export struct ReviewPage {
  orderNo: string = '';
  onDone: () => void = () => {};

  @State private merchantRating: number = 5;
  @State private riderRating: number = 5;
  @State private comment: string = '';
  @State private anonymous: boolean = false;
  @State private tags: string[] = [];
  @State private riderTags: string[] = [];
  @State private submitting: boolean = false;
  @State private images: string[] = [];
  @State private uploading: boolean = false;

  private api: UserApi = new UserApi();

  /** 评价配图走公开桶 —— 评价本身就是公开的 */
  private async addPhotos(): Promise<void> {
    if (this.uploading || this.images.length >= 3) {
      return;
    }
    this.uploading = true;
    try {
      const ctx = getContext(this) as common.UIAbilityContext;
      const urls: string[] = await pickAndUpload(ctx, UploadPurpose.REVIEW,
        3 - this.images.length);
      if (urls.length > 0) {
        this.images = this.images.concat(urls);
      }
    } catch (e) {
      promptAction.showToast({ message: (e as ApiException).message });
    } finally {
      this.uploading = false;
    }
  }

  private static readonly MERCHANT_TAGS: string[] = [
    '味道不错', '分量足', '包装好', '出餐快', '性价比高',
  ];
  private static readonly RIDER_TAGS: string[] = [
    '送得快', '态度好', '包装完好', '按要求放置',
  ];

  private toggle(list: string[], t: string, isRider: boolean): void {
    const next: string[] = list.indexOf(t) >= 0
      ? list.filter((x: string) => x !== t)
      : list.concat([t]);
    if (isRider) {
      this.riderTags = next;
    } else {
      this.tags = next;
    }
  }

  private async submit(): Promise<void> {
    if (this.submitting) {
      return;
    }
    this.submitting = true;
    try {
      await this.api.submitReview(this.orderNo, this.merchantRating,
        this.riderRating, this.comment.trim(), this.anonymous,
        this.images, this.tags, this.riderTags);
      promptAction.showToast({ message: '评价已提交,谢谢' });
      this.onDone();
    } catch (e) {
      promptAction.showToast({ message: (e as ApiException).message });
    } finally {
      this.submitting = false;
    }
  }

  @Builder
  private stars(value: number, onPick: (v: number) => void) {
    Row({ space: 6 }) {
      ForEach([1, 2, 3, 4, 5], (i: number) => {
        Text(i <= value ? '★' : '☆')
          .fontSize(26)
          .fontColor(i <= value
            ? $r('app.color.brand') : $r('app.color.line'))
          .onClick(() => { onPick(i); });
      }, (i: number) => `${i}`);
    }
  }

  @Builder
  private tagRow(all: string[], picked: string[], isRider: boolean) {
    Flex({ wrap: FlexWrap.Wrap }) {
      ForEach(all, (t: string) => {
        Text(t)
          .fontSize(12)
          .padding({ left: 10, right: 10, top: 5, bottom: 5 })
          .margin({ right: 8, bottom: 8 })
          .borderRadius(12)
          .backgroundColor(picked.indexOf(t) >= 0 ? $r('app.color.brand_soft') : $r('app.color.surface_alt'))
          .fontColor(picked.indexOf(t) >= 0
            ? $r('app.color.brand') : $r('app.color.ink'))
          .onClick(() => { this.toggle(picked, t, isRider); });
      }, (t: string) => `${isRider ? 'r' : 'm'}-${t}`);
    }
    .width('100%');
  }

  build() {
    Scroll() {
      Column({ space: 14 }) {
        Column({ space: 8 }) {
          Text('给商家打分')
            .fontSize(15).fontWeight(FontWeight.Medium)
            .fontColor($r('app.color.ink')).width('100%');
          this.stars(this.merchantRating, (v: number) => {
            this.merchantRating = v;
          });
          this.tagRow(ReviewPage.MERCHANT_TAGS, this.tags, false);
        }
        .width('100%').padding(16).backgroundColor($r('app.color.surface'))
        .borderRadius(12).alignItems(HorizontalAlign.Start);

        Column({ space: 8 }) {
          Text('给骑手打分')
            .fontSize(15).fontWeight(FontWeight.Medium)
            .fontColor($r('app.color.ink')).width('100%');
          // 分开打分不是形式:菜不好吃不该算在骑手头上
          Text('骑手的分只看配送,和菜品无关')
            .fontSize(11).fontColor($r('app.color.ink_muted')).width('100%');
          this.stars(this.riderRating, (v: number) => { this.riderRating = v; });
          this.tagRow(ReviewPage.RIDER_TAGS, this.riderTags, true);
        }
        .width('100%').padding(16).backgroundColor($r('app.color.surface'))
        .borderRadius(12).alignItems(HorizontalAlign.Start);

        TextArea({ placeholder: '想说点什么(选填)', text: this.comment })
          .height(100)
          .onChange((v: string) => { this.comment = v; });

        Column({ space: 6 }) {
          Text(`配图(选填,已上传 ${this.images.length}/3)`)
            .fontSize(13).fontColor($r('app.color.ink_muted')).width('100%');
          Button(this.uploading ? '上传中…' : '从相册选择')
            .height(40).fontSize(13)
            .enabled(!this.uploading && this.images.length < 3)
            .backgroundColor($r('app.color.surface_alt')).fontColor($r('app.color.ink'))
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
          }
        }
        .width('100%').padding(14).backgroundColor($r('app.color.surface'))
        .borderRadius(12).alignItems(HorizontalAlign.Start);

        Row() {
          Column({ space: 2 }) {
            Text('匿名评价')
              .fontSize(14).fontColor($r('app.color.ink'));
            Text('匿名是真匿名:服务端不下发你的名字,不是前端遮一下')
              .fontSize(11).fontColor($r('app.color.ink_muted'));
          }
          .layoutWeight(1).alignItems(HorizontalAlign.Start);
          Toggle({ type: ToggleType.Switch, isOn: this.anonymous })
            .onChange((on: boolean) => { this.anonymous = on; });
        }
        .width('100%').padding(14).backgroundColor($r('app.color.surface'))
        .borderRadius(12);

        Button(this.submitting ? '提交中…' : '提交评价')
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
