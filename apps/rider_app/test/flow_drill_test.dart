import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:rider_app/onboarding_page.dart';
import 'package:superz_shared/superz_shared.dart';

/// 模拟跑一单(#309)。
///
/// ## 这里锁什么
///
/// **必须按顺序**。演练如果允许乱点,它教出来的就是"随便点点都行",
/// 而真实订单里服务端会把不按顺序的操作顶回来 —— 新骑手在顾客门口
/// 才发现按不动,比没演练过更糟。
///
/// 按错**不惩罚但要说清楚为什么**:演练里按错是好事。
void main() {
  final flow = [
    {'key': 'grab', 'action': '抢单', 'tip': '先看清取餐点和送达点在哪'},
    {'key': 'picked_up', 'action': '已取餐', 'tip': '到店先点「我到店了」再等餐'},
    {'key': 'delivered', 'action': '送达', 'tip': '按订单上写的送法来'},
  ];

  Future<void> pump(WidgetTester t) async {
    await t.pumpWidget(MaterialApp(
      theme: brandTheme(Brightness.light),
      home: RiderFlowDrillPage(flow: flow),
    ));
    await t.pumpAndSettle();
  }

  testWidgets('演练不产生真实订单 —— 这句话必须写在最前面', (t) async {
    await pump(t);
    expect(find.textContaining('不会产生真实订单'), findsOneWidget);
  });

  testWidgets('必须按顺序:跳步会被拦下并说明原因', (t) async {
    await pump(t);
    await t.tap(find.widgetWithText(FilledButton, '送达'));
    await t.pumpAndSettle();
    expect(find.textContaining('还轮不到这一步'), findsOneWidget,
        reason: '允许乱点的话,演练教出来的是「随便点点都行」—— '
            '而真实订单里服务端会顶回来');
  });

  testWidgets('按对了往前走,走完给收尾', (t) async {
    await pump(t);
    for (final label in ['抢单', '已取餐', '送达']) {
      await t.tap(find.widgetWithText(FilledButton, label));
      await t.pumpAndSettle();
    }
    expect(find.text('走完了'), findsOneWidget);
    expect(find.widgetWithText(FilledButton, '回去做确认题'), findsOneWidget);
  });

  testWidgets('重复点已完成的步骤:说清楚而不是静默不动', (t) async {
    await pump(t);
    await t.tap(find.widgetWithText(FilledButton, '抢单'));
    await t.pumpAndSettle();
    // 已完成的步骤按钮收起来了,点下一步之外的「送达」验证同一条提示路径
    await t.tap(find.widgetWithText(FilledButton, '送达'));
    await t.pumpAndSettle();
    expect(find.textContaining('还轮不到'), findsOneWidget);
  });

  testWidgets('轮到的那一步才显示提示 —— 一次给三段话等于没给', (t) async {
    await pump(t);
    expect(find.textContaining('先看清取餐点'), findsOneWidget);
    expect(find.textContaining('到店先点'), findsNothing,
        reason: '还没轮到就把提示全铺出来,新手会直接划过去');
  });
}
