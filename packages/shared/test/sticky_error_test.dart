import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:superz_shared/superz_shared.dart';

/// 出错页点「重试」,拉成功了要回到正常页面。
///
/// 原来出错页排在最前面判断,拉成功时又不清 _error:断一次网,这一页就一直挂在出错页上,
/// 点重试只是在后台把数据拉回来了,界面纹丝不动。全仓的静态检查见 scripts/check_sticky_error.py。
void main() {
  testWidgets('明厨亮灶:第一次拉失败,点重试拉成功,就回到正常页面', (tester) async {
    var calls = 0;
    await tester.pumpWidget(MaterialApp(
      theme: brandTheme(Brightness.light),
      home: KitchenCamPage(
        shopName: '老王面馆',
        load: () async {
          calls++;
          if (calls == 1) throw Exception('网络开小差了');
          return {'has_kitchen_cam': false, 'label': '未接入', 'message': '这家店还没接明厨亮灶'};
        },
      ),
    ));
    await tester.pumpAndSettle();
    expect(find.text('重试'), findsOneWidget);

    await tester.tap(find.text('重试'));
    await tester.pumpAndSettle();
    expect(calls, 2);
    expect(find.text('重试'), findsNothing, reason: '拉成功了还挂着出错页');
    expect(find.text('这家店还没接明厨亮灶'), findsOneWidget);
  });
}
