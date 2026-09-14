import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:package_info_plus/package_info_plus.dart';
import 'package:superz_shared/superz_shared.dart';
import 'package:user_app/agent_tokens_page.dart';

/// 「我的 → 设置 → AI 助手」按权限签令牌(服务端见 security.AGENT_SCOPES)。
///
/// 守的几件事:
/// - 默认只勾「点餐」,发出去的 scopes 就是 ["order"] —— 多给一项得人自己勾;
/// - 一项都不勾签不了。服务端收到空的 scopes 会按「只点餐」签:界面上什么都没勾,
///   签出来却能下单,这比拦住更糟;
/// - 列表里每一把令牌都标出能做什么;老服务端不给 scopes 时按「点餐」标,不空着;
/// - 签完那一次给的 MCP 配置里,地址是 App 正连着的服务端、令牌是刚签的这串。
const _base = 'https://api.example.test';
const _token = 'agent-token-for-test';

/// 假服务端。列表回 [tokens];签发照新服务端的样子回,[old] 为真时照分权限之前的样子
/// (不认 scopes,也不回 scopes / scope_labels)。
class _Server {
  _Server({this.tokens = const [], this.old = false});

  final List<Map<String, dynamic>> tokens;
  final bool old;

  /// 每次签发请求的 body
  final issued = <Map<String, dynamic>>[];

  late final api = ApiClient(
    baseUrl: _base,
    httpClient: MockClient((req) async {
      Object body = <String, dynamic>{};
      if (req.url.path == '/auth/agent-tokens' && req.method == 'GET') {
        body = tokens;
      } else if (req.url.path == '/auth/agent-tokens' && req.method == 'POST') {
        final sent = jsonDecode(req.body) as Map<String, dynamic>;
        issued.add(sent);
        final scopes = old
            ? const ['order']
            : [...(sent['scopes'] as List? ?? const ['order'])];
        body = {
          'token': _token,
          'expires_at': '2026-12-12T00:00:00+00:00',
          if (!old) 'scopes': scopes,
          if (!old)
            'scope_labels': [
              for (final s in scopes) const {'order': '点餐', 'video': '发视频'}[s]
            ],
          'note': '**这串明文只显示这一次**,请立刻复制到助手的配置里。',
        };
      }
      return http.Response(jsonEncode(body), 200,
          headers: {'content-type': 'application/json; charset=utf-8'});
    }),
  );
}

Map<String, dynamic> _row(int id, String name,
        {List<String>? scopes, List<String>? labels}) =>
    {
      'id': id,
      'name': name,
      if (scopes != null) 'scopes': scopes,
      if (labels != null) 'scope_labels': labels,
      'created_at': '2026-09-01T08:00:00+00:00',
      'expires_at': '2026-11-30T08:00:00+00:00',
      'last_used_at': null,
      'revoked': false,
    };

void main() {
  setUpAll(() => PackageInfo.setMockInitialValues(
      appName: 'user_app',
      packageName: 'com.superz.user',
      version: '0.1.0',
      buildNumber: '1',
      buildSignature: ''));
  setUp(ApiClient.resetAppBuildForTest);

  Future<_Server> pump(WidgetTester t, _Server s) async {
    t.view
      ..devicePixelRatio = 3.0
      ..physicalSize = const Size(390, 844) * 3.0;
    addTearDown(t.view.reset);
    await t.pumpWidget(MaterialApp(
        theme: brandTheme(Brightness.light), home: AgentTokensPage(api: s.api)));
    await t.pumpAndSettle();
    return s;
  }

  Future<void> openIssue(WidgetTester t) async {
    await t.ensureVisible(find.text('签发一个新令牌'));
    await t.tap(find.text('签发一个新令牌'));
    await t.pumpAndSettle();
  }

  Finder scope(String label) => find.widgetWithText(CheckboxListTile, label);
  bool? checked(WidgetTester t, String label) =>
      t.widget<CheckboxListTile>(scope(label)).value;
  Finder issueButton() => find.widgetWithText(TextButton, '签发');

  List<String> chipsIn(WidgetTester t, Finder where) => [
        for (final c in t.widgetList<SzChip>(
            find.descendant(of: where, matching: find.byType(SzChip))))
          c.label
      ];

  testWidgets('默认只勾点餐,发出去的 scopes 就是 ["order"]', (t) async {
    final s = await pump(t, _Server());
    await openIssue(t);

    expect(checked(t, '点餐'), isTrue);
    expect(checked(t, '发视频'), isFalse, reason: '发视频得人自己勾');
    expect(find.text('需要先完成实名认证'), findsOneWidget);

    await t.enterText(find.byType(TextField), '我的 Claude');
    await t.tap(issueButton());
    await t.pumpAndSettle();

    expect(s.issued, hasLength(1));
    expect(s.issued.single['scopes'], ['order']);
    expect(s.issued.single['name'], '我的 Claude');
    expect(s.issued.single['days'], 90);
  });

  testWidgets('两项都不勾签不了:按钮灰掉、写明为什么,一条请求都不发', (t) async {
    final s = await pump(t, _Server());
    await openIssue(t);

    await t.tap(scope('点餐'));
    await t.pump();
    expect(checked(t, '点餐'), isFalse);
    expect(find.text('至少勾一项'), findsOneWidget);
    expect(t.widget<TextButton>(issueButton()).onPressed, isNull);

    await t.tap(issueButton());
    await t.pumpAndSettle();
    expect(s.issued, isEmpty);
    expect(scope('发视频'), findsOneWidget, reason: '签发弹窗不该被关掉');

    // 只勾发视频也能签,发出去的就只有 video
    await t.tap(scope('发视频'));
    await t.pump();
    expect(find.text('至少勾一项'), findsNothing);
    await t.tap(issueButton());
    await t.pumpAndSettle();
    expect(s.issued.single['scopes'], ['video']);
  });

  testWidgets('列表里每一把令牌都标出能做什么', (t) async {
    await pump(
        t,
        _Server(tokens: [
          _row(1, '点外卖的', scopes: ['order'], labels: ['点餐']),
          _row(2, '投稿助手', scopes: ['order', 'video'], labels: ['点餐', '发视频']),
        ]));

    expect(chipsIn(t, find.byKey(const ValueKey('agent-token-1'))), ['点餐']);
    expect(chipsIn(t, find.byKey(const ValueKey('agent-token-2'))),
        ['点餐', '发视频']);
  });

  testWidgets('老服务端不给 scopes:列表和签完那一次都按「点餐」标', (t) async {
    final s = await pump(t, _Server(old: true, tokens: [_row(7, '老助手')]));
    expect(chipsIn(t, find.byKey(const ValueKey('agent-token-7'))), ['点餐']);

    // 勾了发视频,老服务端也只会签点餐 —— 弹窗标的是签出来的,不是勾的
    await openIssue(t);
    await t.tap(scope('发视频'));
    await t.pump();
    await t.tap(issueButton());
    await t.pumpAndSettle();
    expect(s.issued.single['scopes'], ['order', 'video']);
    expect(chipsIn(t, find.byType(AlertDialog)), ['点餐']);
  });

  testWidgets('签完那一次:标出权限;MCP 配置里是 App 连着的服务端和刚签的这串',
      (t) async {
    String? copied;
    final messenger = t.binding.defaultBinaryMessenger;
    messenger.setMockMethodCallHandler(SystemChannels.platform, (call) async {
      if (call.method == 'Clipboard.setData') {
        copied = (call.arguments as Map)['text'] as String?;
      }
      return null;
    });
    addTearDown(
        () => messenger.setMockMethodCallHandler(SystemChannels.platform, null));

    await pump(t, _Server());
    await openIssue(t);
    await t.tap(scope('发视频'));
    await t.pump();
    await t.tap(issueButton());
    await t.pumpAndSettle();

    expect(chipsIn(t, find.byType(AlertDialog)), ['点餐', '发视频']);
    expect(find.textContaining('**'), findsNothing,
        reason: '服务端 note 里的 ** 不该原样印出来');

    await t.ensureVisible(find.widgetWithText(TextButton, '复制配置'));
    await t.tap(find.widgetWithText(TextButton, '复制配置'));
    await t.pump();
    final superz = (jsonDecode(copied!) as Map)['mcpServers']['superz'] as Map;
    expect(superz['command'], 'python3');
    expect(superz['args'], ['/绝对路径/server.py']);
    expect(superz['env'], {'SUPERZ_API': _base, 'SUPERZ_AGENT_TOKEN': _token});

    await t.tap(find.widgetWithText(TextButton, '复制令牌'));
    await t.pump();
    expect(copied, _token);
  });

  testWidgets('页面上有「操作说明」入口', (t) async {
    await pump(t, _Server());
    await t.ensureVisible(find.text('操作说明'));
    expect(find.widgetWithText(SzEntryTile, '操作说明'), findsOneWidget);
  });
}
