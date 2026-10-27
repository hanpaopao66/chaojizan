import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:superz_shared/superz_shared.dart';
import 'package:user_app/home_compose.dart';

/// 首页右上角「+」菜单(2026-09-18)。
///
/// 锁两件事:四件事都在、选哪件返回哪件;桌面/网页上**不摆扫一扫** ——
/// 没有相机,摆一个点进去就报错的入口不如不摆。
void main() {
  Future<void> pumpTrigger(WidgetTester t, {required bool canScan,
      required void Function(HomeComposeAction?) onPicked}) async {
    await t.pumpWidget(MaterialApp(
      theme: brandTheme(Brightness.light),
      home: Builder(
        builder: (context) => Scaffold(
          body: Center(
            child: FilledButton(
              onPressed: () async {
                onPicked(await showHomeComposeSheet(context, canScan: canScan));
              },
              child: const Text('打开'),
            ),
          ),
        ),
      ),
    ));
    await t.tap(find.text('打开'));
    await t.pumpAndSettle();
  }

  testWidgets('手机:四件事都在,选哪件返回哪件', (t) async {
    HomeComposeAction? picked;
    await pumpTrigger(t, canScan: true, onPicked: (p) => picked = p);
    for (final label in ['扫一扫', '我的名片', '发起群聊', '添加联系人']) {
      expect(find.text(label), findsOneWidget, reason: label);
    }
    await t.tap(find.text('发起群聊'));
    await t.pumpAndSettle();
    expect(picked, HomeComposeAction.group);
  });

  testWidgets('桌面/网页:没有扫一扫,其余三件照常', (t) async {
    HomeComposeAction? picked;
    await pumpTrigger(t, canScan: false, onPicked: (p) => picked = p);
    expect(find.text('扫一扫'), findsNothing);
    expect(find.text('我的名片'), findsOneWidget);
    expect(find.text('发起群聊'), findsOneWidget);
    expect(find.text('添加联系人'), findsOneWidget);
    await t.tap(find.text('添加联系人'));
    await t.pumpAndSettle();
    expect(picked, HomeComposeAction.addContact);
  });
}
