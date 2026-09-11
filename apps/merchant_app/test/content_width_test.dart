import 'package:flutter_test/flutter_test.dart';
import 'package:merchant_app/main.dart';
import 'package:superz_shared/superz_shared.dart';

/// 宽屏下每个 tab 的内容限宽(#295)。
///
/// `responsive.dart` 把三个宽度写得很明白:
///
/// | 常量 | 值 | 给什么用 |
/// |---|---|---|
/// | [kContentMaxWidth] | 720 | 单列内容:设置页、表单、正文 |
/// | [kFeedMaxWidth] | 1080 | 卡片流:商家列表、订单列表 |
/// | [kWideMaxWidth] | 1440 | 看板类:要并排放图表的 |
///
/// 「店铺」页是**单列设置页**,不是卡片流 —— 一条 `SzEntryTile` 拉到 1080px,
/// 图标在最左、状态值在最右,中间一米空白,眼睛得来回扫。
/// 这正是 `responsive.dart` 类文档举的那个反例。
///
/// 2026-09 浅色定稿:五个 tab(看板 / 订单 / 菜单 / 账本 / 店铺)。
void main() {
  test('tab 下标就是底部导航的顺序', () {
    expect([kTabBoard, kTabOrders, kTabMenu, kTabLedger, kTabShop],
        [0, 1, 2, 3, 4]);
  });

  test('看板是卡片流,1080', () {
    // 名字叫看板,但里面是台面 + 待接单卡,没有要并排放的图表 ——
    // 不归「看板类」那一档
    expect(merchantTabMaxWidth(kTabBoard), kFeedMaxWidth);
  });

  test('订单是卡片流,1080', () {
    expect(merchantTabMaxWidth(kTabOrders), kFeedMaxWidth);
  });

  test('菜单是卡片流,1080', () {
    expect(merchantTabMaxWidth(kTabMenu), kFeedMaxWidth);
  });

  test('账本要并排放表格和图表,1440', () {
    expect(merchantTabMaxWidth(kTabLedger), kWideMaxWidth);
  });

  test('店铺是单列设置页,720', () {
    expect(merchantTabMaxWidth(kTabShop), kContentMaxWidth,
        reason: '店铺页归到卡片流(1080)是分类错了 —— '
            '它是一列入口条和开关,不是并排的卡片');
  });
}
