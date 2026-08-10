import { Merchant } from '../model/Models';
import { distanceText, yuan } from '../common/Money';

/**
 * 商家卡片。首页、搜索、品类、收藏四个地方都用这一份。
 *
 * 各画一遍的下场是:改一处标识要改四遍,而漏掉的那一处正好是法定公示项 ——
 * 明厨亮灶和堂食标识是总局令第 123 号要求**列表页**展示的,
 * 少一个页面就是一个合规缺口。
 */
@Component
export struct MerchantCard {
  merchant: Merchant | null = null;

  build() {
    Column({ space: 6 }) {
      if (this.merchant !== null) {
        Row() {
          Text(this.merchant.name)
            .fontSize(16).fontWeight(FontWeight.Medium)
            .fontColor($r('app.color.ink')).layoutWeight(1)
            .maxLines(1).textOverflow({ overflow: TextOverflow.Ellipsis });
          if (!this.merchant.is_open) {
            Text('休息中').fontSize(12).fontColor($r('app.color.ink_muted'));
          }
        }
        .width('100%');

        Row({ space: 10 }) {
          if (this.merchant.rating_avg !== undefined
            && this.merchant.rating_avg !== null) {
            Text(`${this.merchant.rating_avg.toFixed(1)} 分`)
              .fontSize(12).fontColor($r('app.color.ink_muted'));
          }
          if (this.merchant.monthly_sales !== undefined
            && this.merchant.monthly_sales > 0) {
            Text(`月售 ${this.merchant.monthly_sales}`)
              .fontSize(12).fontColor($r('app.color.ink_muted'));
          }
          if (this.merchant.distance_m !== undefined) {
            Text(distanceText(this.merchant.distance_m))
              .fontSize(12).fontColor($r('app.color.ink_muted'));
          }
          if (this.merchant.min_order_cents !== undefined
            && this.merchant.min_order_cents > 0) {
            Text(`起送 ${yuan(this.merchant.min_order_cents)}`)
              .fontSize(12).fontColor($r('app.color.ink_muted'));
          }
        }
        .width('100%');

        // 法定公示项(总局令第 123 号第十二、十三条):
        // 明厨亮灶与堂食标识,**有和无两种都要标**,不是只给有的加徽章。
        // 中文名用服务端下发的 label,客户端不另写映射
        Row({ space: 8 }) {
          Text(this.merchant.kitchen_cam_label ?? '无明厨亮灶')
            .fontSize(11)
            .fontColor(this.merchant.kitchen_cam === true
              ? $r('app.color.earn') : $r('app.color.ink_muted'));
          Text(this.merchant.dine_in_label ?? '未填报')
            .fontSize(11)
            .fontColor(this.merchant.dine_in_status === 'yes'
              ? $r('app.color.earn') : $r('app.color.ink_muted'));
        }
        .width('100%');

        if ((this.merchant.promo_labels ?? []).length > 0) {
          Flex({ wrap: FlexWrap.Wrap }) {
            ForEach(this.merchant.promo_labels ?? [], (p: string) => {
              Text(p)
                .fontSize(11).fontColor($r('app.color.brand'))
                .padding({ left: 6, right: 6, top: 2, bottom: 2 })
                .margin({ right: 6, top: 2 })
                .borderRadius(4)
                .backgroundColor($r('app.color.brand_soft'));
            }, (p: string) => p);
          }
          .width('100%');
        }
      }
    }
    .width('100%')
    .padding(14)
    .backgroundColor($r('app.color.surface'))
    .borderRadius(14)
    .alignItems(HorizontalAlign.Start)
    // 无障碍:读屏用户听到的是一句完整的话,不是七八个孤立的词。
    // 安卓端 Semantics 用了 0 次,是明确的欠账 —— 鸿蒙端不再欠一遍
    .accessibilityText(this.merchant === null ? '' :
      `${this.merchant.name},` +
      `${this.merchant.is_open ? '营业中' : '休息中'},` +
      `${this.merchant.dine_in_label ?? '堂食未填报'},` +
      `${this.merchant.kitchen_cam_label ?? '无明厨亮灶'}`);
  }
}
