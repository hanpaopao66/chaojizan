import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:merchant_app/web_limits_banner.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:superz_shared/superz_shared.dart';

/// 网页版能力边界横幅(#293)。
///
/// ## 为什么这条横幅值得测
///
/// 商家端网页版**不能替代手机 App 听单** —— 浏览器没有前台服务,
/// 标签页一关或被休眠,WebSocket 就断了。
///
/// 不说清楚的话商家会以为"开着网页 = 在听单",而漏单是这个 App
/// 最不能出的错。所以这条横幅不是装饰,它是**功能边界的声明**;
/// 谁把文案改软了(比如改成"部分功能受限"),得让测试拦下来。
void main() {
  Widget host() => MaterialApp(
        theme: brandTheme(Brightness.light),
        home: const Scaffold(body: WebLimitsBanner()),
      );

  setUp(() => SharedPreferences.setMockInitialValues({}));

  testWidgets('说清楚能用什么、不能用什么', (t) async {
    await t.pumpWidget(host());
    await t.pumpAndSettle();

    // 能用的要列出来 —— 商家据此决定"今天能不能只开网页版"
    expect(find.textContaining('接单'), findsWidgets);
    expect(find.textContaining('对账'), findsWidgets);

    // 不能用的必须点名,而且要说**为什么** ——
    // 只说"不支持"会被当成 bug 报上来
    final body = t.widgetList<Text>(find.byType(Text))
        .map((w) => w.data ?? '').join();
    expect(body, contains('听单'), reason: '没说清听单的边界 —— 那是最容易误解的');
    expect(body, contains('蓝牙'), reason: '没提蓝牙小票机连不了');
    expect(body, contains('云打印'), reason: '只说不能用、不说替代方案,等于把人堵死');
  });

  testWidgets('可以永久关掉,关了不再出现', (t) async {
    await t.pumpWidget(host());
    await t.pumpAndSettle();
    expect(find.byType(IconButton), findsOneWidget);

    await t.tap(find.byType(IconButton));
    await t.pumpAndSettle();
    expect(find.byType(Text), findsNothing, reason: '点了关闭还在显示');

    // 重建一次(模拟下次打开)
    await t.pumpWidget(const SizedBox());
    await t.pumpWidget(host());
    await t.pumpAndSettle();
    expect(find.byType(Text), findsNothing, reason: '关掉的横幅下次又冒出来了');
  });

  testWidgets('之前关过的,重新打开也不出现', (t) async {
    // 直接用"已经关过"的初值。前一条测的是这次点关闭,
    // 这条测的是**上次**关的还算数
    SharedPreferences.setMockInitialValues({'flutter.web_limits_dismissed': true});
    await t.pumpWidget(host());
    await t.pumpAndSettle();
    expect(find.byType(Text), findsNothing,
        reason: '上次关掉的横幅这次又冒出来了');
  });
}
