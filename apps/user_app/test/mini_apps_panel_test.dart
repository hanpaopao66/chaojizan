/// 小程序下拉面板的排版(2026-09-15 用户:要紧凑;我的小程序默认折叠;最近使用和常用放到上面)。
///
/// ## 这个测试防的是什么
///
/// 面板是随手一拉的地方,占地方就没人用。这几条都没有报错可言,改一行布局就可能悄悄退回去:
/// 最近使用、常用在最上面;我的小程序默认收着、点了才展开;常用不重复上一行已经有的;
/// 格子里只有图标和名字;手机上一行 5 个;系统把字调大时格子跟着长、不截字。
library;

import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:package_info_plus/package_info_plus.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:superz_shared/superz_shared.dart';
import 'package:user_app/mini_apps_panel.dart';

Map<String, dynamic> card(int i, String name) => {
      'appid': 'sz${i.toRadixString(16).padLeft(16, '0')}',
      'id': i,
      'name': name,
      'icon': name.substring(0, 1),
      'tagline': '$name的一句话介绍',
      'kind': 'game',
      'hosting': 'hosted',
      'developer': {'name': '官方', 'label': '官方', 'official': true},
    };

/// 已登录的假客户端:面板只有登录了才去拉「最近使用 / 常用 / 我的小程序」
Future<ApiClient> loggedIn({
  List<Map<String, dynamic>> recent = const [],
  List<Map<String, dynamic>> frequent = const [],
  List<Map<String, dynamic>> starred = const [],
}) async {
  SharedPreferences.setMockInitialValues({'auth_token': 't', 'auth_role': 'customer'});
  final api = ApiClient(
    baseUrl: 'http://test.local',
    httpClient: MockClient((req) async {
      final Object payload = switch (req.url.path) {
        '/auth/me' => {'id': 1, 'name': '测试', 'role': 'customer'},
        '/mini-apps/me' => {'recent': recent, 'frequent': frequent, 'starred': starred},
        _ => <String, dynamic>{},
      };
      return http.Response(jsonEncode(payload), 200,
          headers: {'content-type': 'application/json; charset=utf-8'});
    }),
  );
  expect(await api.restoreSession(expectRole: 'customer'), isTrue);
  return api;
}

Future<void> openPanel(WidgetTester t, ApiClient api, List<Map<String, dynamic>> catalog,
    {Size size = const Size(390, 844)}) async {
  t.view
    ..devicePixelRatio = 3.0
    ..physicalSize = size * 3.0;
  addTearDown(t.view.reset);
  await t.pumpWidget(MaterialApp(
    theme: brandTheme(Brightness.light),
    home: Builder(
      builder: (context) => Scaffold(
        body: Center(
          child: TextButton(
            onPressed: () => showMiniAppsPanel(context,
                api: api, apps: catalog.map(MiniAppCard.fromJson).toList()),
            child: const Text('打开面板'),
          ),
        ),
      ),
    ),
  ));
  await t.tap(find.text('打开面板'));
  await t.pumpAndSettle();
}

double top(WidgetTester t, String text) => t.getTopLeft(find.text(text)).dy;

void main() {
  // 进程里第一个请求会先取包信息(ApiClient 里带 2 秒超时)。测试是假时钟,直接 await 时时间不走,
  // 那 2 秒永远到不了 —— 不 mock 的话第一个测试挂满 10 分钟(见 mini_apps_hint_test 的同一条)
  setUpAll(() {
    TestWidgetsFlutterBinding.ensureInitialized();
    PackageInfo.setMockInitialValues(
      appName: 'user_app',
      packageName: 'com.chaojizan.user',
      version: '0.1.0',
      buildNumber: '1',
      buildSignature: '',
    );
  });

  final a = card(1, '记事本'), b = card(2, '贪吃蛇'), c = card(3, '扫雷'), d = card(4, '五子棋'),
      e = card(5, '萌兽三路'), f = card(6, '方块消除');

  testWidgets('从上到下:最近使用、常用、我的小程序、全部小程序', (t) async {
    final api = await loggedIn(recent: [a, b], frequent: [c], starred: [d]);
    await openPanel(t, api, [f]);
    expect(top(t, '最近使用'), lessThan(top(t, '常用')));
    expect(top(t, '常用'), lessThan(top(t, '我的小程序')));
    expect(top(t, '我的小程序'), lessThan(top(t, '全部小程序')));
  });

  testWidgets('我的小程序默认折叠,点标题展开、再点收起', (t) async {
    final api = await loggedIn(starred: [d, e]);
    await openPanel(t, api, [f]);
    expect(find.text('我的小程序'), findsOneWidget);
    expect(find.text('2'), findsOneWidget, reason: '折叠时标着里面有几个');
    expect(find.text('五子棋'), findsNothing, reason: '默认折叠');
    expect(find.text('萌兽三路'), findsNothing);
    await t.tap(find.text('我的小程序'));
    await t.pumpAndSettle();
    expect(find.text('五子棋'), findsOneWidget);
    expect(find.text('萌兽三路'), findsOneWidget);
    await t.tap(find.text('我的小程序'));
    await t.pumpAndSettle();
    expect(find.text('五子棋'), findsNothing);
    expect(find.text('方块消除'), findsOneWidget, reason: '折叠的是我的小程序,不是整个面板');
  });

  testWidgets('常用里不重复最近使用那一行已经有的', (t) async {
    // 记事本既是最近用的、又是最常用的:只在「最近使用」里出现一次
    final api = await loggedIn(recent: [a, b], frequent: [a, c]);
    await openPanel(t, api, [f]);
    expect(find.text('记事本'), findsOneWidget);
    expect(find.text('扫雷'), findsOneWidget);
  });

  testWidgets('常用都已经在最近使用里了:常用那一段不出现', (t) async {
    final api = await loggedIn(recent: [a, b], frequent: [b, a]);
    await openPanel(t, api, [f]);
    expect(find.text('常用'), findsNothing);
  });

  testWidgets('格子只画图标和名字,一句话介绍留给详情页', (t) async {
    final api = await loggedIn(recent: [a]);
    await openPanel(t, api, [f]);
    expect(find.text('记事本'), findsOneWidget);
    expect(find.textContaining('一句话介绍'), findsNothing);
  });

  testWidgets('最近使用只摆一行:手机上一行 5 个', (t) async {
    final many = [for (var i = 0; i < 8; i++) card(10 + i, '应用$i')];
    final api = await loggedIn(recent: many);
    await openPanel(t, api, [f]);
    expect(find.text('应用4'), findsOneWidget);
    expect(find.text('应用5'), findsNothing, reason: '第 6 个起在第二行,抽屉里不摆');
    // 同一行:5 个名字的纵坐标一样
    final ys = {for (var i = 0; i < 5; i++) top(t, '应用$i')};
    expect(ys.length, 1);
  });

  test('列数按可用宽度:小屏 4 个,常见手机 5 个,宽屏多排、最多 8 个', () {
    expect(miniAppPanelColumns(320), 4);
    expect(miniAppPanelColumns(360), 5);
    expect(miniAppPanelColumns(390), 5);
    expect(miniAppPanelColumns(414), 5);
    expect(miniAppPanelColumns(430), 6);
    expect(miniAppPanelColumns(720), 8, reason: '宽屏限宽 720(SzContentWidth),再宽也是 8 个');
  });

  testWidgets('系统字号调大:格子跟着长,名字不被截、不溢出', (t) async {
    t.platformDispatcher.textScaleFactorTestValue = 1.3;
    addTearDown(t.platformDispatcher.clearTextScaleFactorTestValue);
    final api = await loggedIn(recent: [a, b, c], frequent: [d], starred: [e]);
    await openPanel(t, api, [f]);
    await t.tap(find.text('我的小程序'));
    await t.pumpAndSettle();
    expect(t.takeException(), isNull);
    expect(find.text('萌兽三路'), findsOneWidget);
  });
}
