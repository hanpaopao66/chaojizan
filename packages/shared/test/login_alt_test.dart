import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:superz_shared/superz_shared.dart';

/// 登录页的「另一种登录方式」(用户端网页版、桌面版的扫码登录):
///
/// - 不传(手机上、商家端、骑手端):和原来一模一样,只有手机号,也没有「扫码登录」这行字;
/// - 传了:先显示它,底下「用手机号登录」切过去,手机号那一屏底下再切回来;
/// - 它说登录成功了,登录页照常收尾(onLoggedIn)。
///
/// 共享包只管摆在哪、怎么切,不知道里面是什么 —— 所以这里塞一个假的面板就够。
void main() {
  Widget page({Widget Function(BuildContext, SzAltLoginHost)? alt, VoidCallback? onDone,
          bool altFirst = true}) =>
      MaterialApp(
        theme: brandTheme(Brightness.light),
        home: SmsLoginPage(
          title: '登录后继续',
          api: ApiClient(baseUrl: 'http://test.local'),
          altLogin: alt,
          altLoginFirst: altFirst,
          onLoggedIn: (_, __) => onDone?.call(),
        ),
      );

  testWidgets('altLoginFirst=false(手机浏览器):先显示手机号,底下能切到扫码', (tester) async {
    await tester.pumpWidget(page(alt: (_, __) => const Text('假的扫码面板'), altFirst: false));
    expect(find.text('手机号'), findsOneWidget);
    expect(find.text('假的扫码面板'), findsNothing);
    await tester.ensureVisible(find.text('扫码登录'));
    await tester.tap(find.text('扫码登录'));
    await tester.pump();
    expect(find.text('假的扫码面板'), findsOneWidget);
  });

  testWidgets('不传:只有手机号登录,没有扫码的入口', (tester) async {
    await tester.pumpWidget(page());
    expect(find.text('手机号'), findsOneWidget);
    expect(find.text('扫码登录'), findsNothing);
    expect(find.text('用手机号登录'), findsNothing);
  });

  testWidgets('传了:先显示它,能切到手机号、再切回来', (tester) async {
    await tester.pumpWidget(page(alt: (_, __) => const Text('假的扫码面板')));
    expect(find.text('假的扫码面板'), findsOneWidget);
    expect(find.text('手机号'), findsNothing);

    await tester.tap(find.text('用手机号登录'));
    await tester.pump();
    expect(find.text('假的扫码面板'), findsNothing);
    expect(find.text('手机号'), findsOneWidget);

    await tester.ensureVisible(find.text('扫码登录'));
    await tester.tap(find.text('扫码登录'));
    await tester.pump();
    expect(find.text('假的扫码面板'), findsOneWidget);
  });

  testWidgets('面板说登录成功了,登录页照常收尾;面板也能自己切到手机号', (tester) async {
    var done = 0;
    late SzAltLoginHost host;
    await tester.pumpWidget(page(
        alt: (_, h) {
          host = h;
          return const Text('假的扫码面板');
        },
        onDone: () => done++));
    host.loggedIn();
    expect(done, 1);

    host.usePhone();
    await tester.pump();
    expect(find.text('手机号'), findsOneWidget);
  });
}
