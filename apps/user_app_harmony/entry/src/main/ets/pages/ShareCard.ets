import { componentSnapshot, promptAction } from '@kit.ArkUI';
import { image } from '@kit.ImageKit';
import { photoAccessHelper } from '@kit.MediaLibraryKit';
import { fileIo } from '@kit.CoreFileKit';
import { common } from '@kit.AbilityKit';
import { Order } from '../model/Models';
import { yuan } from '../common/Money';

/**
 * 晒单分账卡。
 *
 * **这是这个产品唯一落成的差异化传播物料。** 别家外卖的晒单卡是菜品图 + 价格,
 * 我们的是三色分账条:商家实收 / 骑手所得(配送费与小费全额)/ 平台留存。
 *
 * 为什么它有传播力:美团、淘宝闪购、京东三家都**做不到**这件事 ——
 * 他们的骑手侧定价是商业机密,摊开等于公布调控手段。我们没有中间层,
 * 每一分都说得清,所以敢把它印在一张能转发的图上。
 *
 * **金额可以打码**:有人愿意晒"钱怎么分"但不愿意晒自己花了多少,
 * 这两件事不该绑在一起。
 */
@Component
export struct ShareCardPage {
  order: Order | null = null;

  /** 打码:只显示比例不显示金额 */
  @State private maskAmount: boolean = false;
  @State private saving: boolean = false;

  private snapshotId: string = 'superz_share_card';

  private merchantNet(o: Order): number {
    return (o.food_cents ?? 0) + (o.packing_fee_cents ?? 0)
      - (o.commission_cents ?? 0);
  }

  private riderNet(o: Order): number {
    return (o.delivery_fee_cents ?? 0) + (o.tip_cents ?? 0);
  }

  private platformNet(o: Order): number {
    return o.commission_cents ?? 0;
  }

  private money(cents: number): string {
    return this.maskAmount ? '＊＊' : yuan(cents);
  }

  /** 三段比例。总额为 0 时平均分,免得除零画出空条 */
  private ratio(part: number, o: Order): number {
    const total: number = this.merchantNet(o) + this.riderNet(o)
      + this.platformNet(o);
    if (total <= 0) {
      return 33;
    }
    return Math.round(part * 100 / total);
  }

  /**
   * 存成图片。
   *
   * `componentSnapshot.get` 按组件 id 截图 —— 比自己用 Canvas 画一遍省事,
   * 而且所见即所得,不会出现"界面上好看、导出来错位"。
   */
  private async saveToAlbum(): Promise<void> {
    if (this.saving) {
      return;
    }
    this.saving = true;
    try {
      const pixelMap: image.PixelMap =
        await componentSnapshot.get(this.snapshotId);
      const packer: image.ImagePacker = image.createImagePacker();
      const buf: ArrayBuffer = await packer.packing(pixelMap,
        { format: 'image/jpeg', quality: 92 });

      const ctx = getContext(this) as common.UIAbilityContext;
      const helper = photoAccessHelper.getPhotoAccessHelper(ctx);
      // 用系统的「保存到相册」能力:同样不需要申请相册写权限,
      // 用户在系统弹窗里确认一次即可
      const uri: string = await helper.createAsset(
        photoAccessHelper.PhotoType.IMAGE, 'jpg');
      const file = await fileIo.open(uri,
        fileIo.OpenMode.READ_WRITE | fileIo.OpenMode.CREATE);
      try {
        await fileIo.write(file.fd, buf);
      } finally {
        await fileIo.close(file);
      }
      promptAction.showToast({ message: '已存到相册,去微信发给朋友吧' });
    } catch (e) {
      promptAction.showToast({ message: '存图失败,稍后再试' });
    } finally {
      this.saving = false;
    }
  }

  @Builder
  private segment(label: string, amount: string, pct: number, color: Resource) {
    Column({ space: 4 }) {
      Row() {
        Text(label).fontSize(13).fontColor($r('app.color.ink')).layoutWeight(1);
        Text(amount).fontSize(14).fontColor(color);
      }
      .width('100%');
      Row() {
        Row().width(`${pct}%`).height(8).backgroundColor(color).borderRadius(4);
      }
      .width('100%').height(8)
      .backgroundColor($r('app.color.surface_alt')).borderRadius(4);
    }
    .width('100%');
  }

  build() {
    Column() {
      Scroll() {
        Column({ space: 12 }) {
          if (this.order !== null) {
            // 这一块是要被截图的,id 给 componentSnapshot 用
            Column({ space: 14 }) {
              Column({ space: 4 }) {
                Text('这一单的钱是这么分的')
                  .fontSize(18).fontWeight(FontWeight.Bold)
                  .fontColor($r('app.color.ink')).width('100%');
                Text(this.order.merchant_name ?? '')
                  .fontSize(13).fontColor($r('app.color.ink_muted')).width('100%');
              }
              .width('100%').alignItems(HorizontalAlign.Start);

              this.segment('商家实收', this.money(this.merchantNet(this.order)),
                this.ratio(this.merchantNet(this.order), this.order),
                $r('app.color.ink'));
              this.segment('骑手所得(配送费与小费全额)',
                this.money(this.riderNet(this.order)),
                this.ratio(this.riderNet(this.order), this.order),
                $r('app.color.earn'));
              this.segment('平台留存(佣金)',
                this.money(this.platformNet(this.order)),
                this.ratio(this.platformNet(this.order), this.order),
                $r('app.color.brand'));

              Column({ space: 3 }) {
                Text('商家 5% 封顶 · 配送费一分不截留 · 每单分账可查')
                  .fontSize(12).fontColor($r('app.color.earn')).width('100%');
                Text('超级赞 chaojizan.cc')
                  .fontSize(11).fontColor($r('app.color.ink_muted')).width('100%');
              }
              .width('100%').alignItems(HorizontalAlign.Start);
            }
            .id(this.snapshotId)
            .width('100%').padding(20).backgroundColor($r('app.color.surface'))
            .borderRadius(16).alignItems(HorizontalAlign.Start);

            Row() {
              Column({ space: 2 }) {
                Text('金额打码')
                  .fontSize(14).fontColor($r('app.color.ink'));
                // 愿意晒"钱怎么分"和愿意晒"我花了多少"是两件事
                Text('只晒比例,不晒自己花了多少')
                  .fontSize(11).fontColor($r('app.color.ink_muted'));
              }
              .layoutWeight(1).alignItems(HorizontalAlign.Start);
              Toggle({ type: ToggleType.Switch, isOn: this.maskAmount })
                .onChange((on: boolean) => { this.maskAmount = on; });
            }
            .width('100%').padding(14).backgroundColor($r('app.color.surface'))
            .borderRadius(12);

            Text('别家外卖只给你一个总数。我们把每一分的去向摊开 —— ' +
              '他们做不到:骑手侧的定价是商业机密,摊开等于公布调控手段。')
              .fontSize(12).fontColor($r('app.color.ink_muted')).width('100%');
          }
        }
        .width('100%').padding({ left: 12, right: 12, top: 12, bottom: 16 });
      }
      .layoutWeight(1).scrollBar(BarState.Off);

      Row({ space: 10 }) {
        Button(this.saving ? '生成中…' : '存成图片')
          .layoutWeight(1).height(46)
          .enabled(!this.saving)
          .backgroundColor($r('app.color.brand'))
          .onClick(() => { this.saveToAlbum(); });
      }
      .width('100%').padding(12).backgroundColor($r('app.color.surface'))
      .border({ width: { top: 1 }, color: $r('app.color.line') });
    }
    .width('100%').height('100%').backgroundColor($r('app.color.page'));
  }
}
