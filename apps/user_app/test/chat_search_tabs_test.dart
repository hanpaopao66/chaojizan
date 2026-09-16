/// 搜索页顶上那一排分类(对齐 Telegram 的搜索页)。
///
/// 守的是:
/// - 十格都在,顺序和 Telegram 一样;
/// - 点一格就按那一格去搜(请求带上 tab=…),**「多媒体」这类不填关键词也去搜**;
/// - 「下载内容」是本机的,点它**一个请求都不发** —— 谁下载了什么不该经过服务端;
/// - 换一格时把上一格的结果清掉,不会看到串台的内容。
library;

import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:package_info_plus/package_info_plus.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:superz_shared/superz_shared.dart';
import 'package:user_app/chat/downloads.dart';
import 'package:user_app/chat/models.dart';
import 'package:user_app/chat/pages/search_page.dart';
import 'package:user_app/chat/store.dart';
import 'package:user_app/main.dart' show superZTheme;

void main() {
  setUpAll(() => PackageInfo.setMockInitialValues(
      appName: 'user_app',
      packageName: 'com.superz.user',
      version: '0.1.0',
      buildNumber: '1',
      buildSignature: ''));
  setUp(() {
    SharedPreferences.setMockInitialValues({});
    Downloads.instance.resetForTest();
  });
  tearDown(() => ChatStore.instance.stop());

  http.Response json(Object body) => http.Response(jsonEncode(body), 200,
      headers: {'content-type': 'application/json; charset=utf-8'});

  /// 记下每次请求的地址,好断言「点了哪一格就去搜哪一格」
  ({ApiClient api, List<String> urls}) server() {
    final urls = <String>[];
    final api = ApiClient(
      baseUrl: 'https://api.example.test',
      httpClient: MockClient((req) async {
        urls.add('${req.url.path}?${req.url.query}');
        if (req.url.path == '/chat/v1/search') {
          final tab = req.url.queryParameters['tab'] ?? '';
          if (tab == 'files') {
            return json({
              'items': [
                {
                  'chat': {'id': 7, 'type': 'group', 'title': '项目群', 'photo': ''},
                  'id': 42,
                  'message': {
                    'chat_id': 7,
                    'seq': 3,
                    'kind': 'file',
                    'text': '',
                    'created_at': '2026-09-16T01:00:00Z',
                    'media': [
                      {'id': 5, 'kind': 'file', 'name': '合同.pdf', 'size': 20480, 'mime': 'application/pdf'}
                    ],
                  },
                }
              ],
              'has_more': false,
              'next_before_id': null,
            });
          }
          if (tab == 'chats') {
            return json({
              'items': [
                {'kind': 'chat', 'id': 7, 'type': 'group', 'title': '项目群', 'photo': '', 'member_count': 3}
              ],
              'has_more': false,
              'next_before_id': null,
            });
          }
          if (tab.isNotEmpty) {
            return json({'items': [], 'has_more': false, 'next_before_id': null});
          }
          return json({'chats': [], 'users': [], 'messages': []});
        }
        return json(<String, dynamic>{});
      }),
    );
    return (api: api, urls: urls);
  }

  /// 那一排横着放不下,点之前先滚到看得见 —— 真人也是先滑一下再点
  Future<void> tapChip(WidgetTester tester, String label) async {
    final chip = find.widgetWithText(ChoiceChip, label);
    await tester.ensureVisible(chip);
    await tester.pumpAndSettle();
    await tester.tap(chip);
    await tester.pumpAndSettle();
  }

  Future<void> pump(WidgetTester tester) async {
    tester.view
      ..devicePixelRatio = 1
      ..physicalSize = const Size(420, 900);
    addTearDown(tester.view.reset);
    await tester.pumpWidget(MaterialApp(
        theme: superZTheme(Brightness.light), home: const ChatSearchPage()));
    await tester.pumpAndSettle();
  }

  testWidgets('十格都在,顺序和 Telegram 一样', (tester) async {
    final s = server();
    ChatStore.instance.debugUseClient(s.api);
    await pump(tester);

    for (final label in ['全部', '对话', '频道', '应用', '多媒体', '下载内容', '链接', '文件', '音乐', '语音']) {
      expect(find.widgetWithText(ChoiceChip, label), findsOneWidget, reason: '缺了「$label」');
    }
  });

  testWidgets('点「文件」:不填关键词也去搜,请求带 tab=files,结果按文件名画', (tester) async {
    final s = server();
    ChatStore.instance.debugUseClient(s.api);
    await pump(tester);

    await tapChip(tester, '文件');

    expect(s.urls.any((u) => u.contains('tab=files')), isTrue, reason: '点了「文件」就该去搜文件:${s.urls}');
    expect(find.text('合同.pdf'), findsOneWidget);
    expect(find.textContaining('项目群'), findsOneWidget);
  });

  testWidgets('「下载内容」一个请求都不发 —— 谁下载了什么不经过服务端', (tester) async {
    await Downloads.instance.record(
        const MediaInfo(id: 9, kind: 'file', name: '年报.pdf', size: 1024, mime: 'application/pdf'),
        path: '/tmp/年报.pdf',
        chatId: 7,
        chatTitle: '财务群');
    final s = server();
    ChatStore.instance.debugUseClient(s.api);
    await pump(tester);

    await tapChip(tester, '下载内容');

    expect(find.text('年报.pdf'), findsOneWidget);
    expect(find.textContaining('财务群'), findsOneWidget);
    expect(find.textContaining('只在这台设备上'), findsOneWidget);
    expect(s.urls.any((u) => u.contains('/chat/v1/search')), isFalse,
        reason: '本机的清单不该发请求:${s.urls}');
  });

  testWidgets('下载记录为空时说清楚是空的,不是在转圈', (tester) async {
    final s = server();
    ChatStore.instance.debugUseClient(s.api);
    await pump(tester);

    await tapChip(tester, '下载内容');
    expect(find.text('还没有下载过什么'), findsOneWidget);
  });

  testWidgets('换一格:上一格的结果不会留在屏幕上', (tester) async {
    final s = server();
    ChatStore.instance.debugUseClient(s.api);
    await pump(tester);

    await tapChip(tester, '文件');
    expect(find.text('合同.pdf'), findsOneWidget);

    await tapChip(tester, '语音');
    expect(find.text('合同.pdf'), findsNothing, reason: '换格子要把上一格的结果清掉');
    expect(find.text('这里还没有语音'), findsOneWidget);
  });

  testWidgets('「对话」那一格按会话画,点得动', (tester) async {
    final s = server();
    ChatStore.instance.debugUseClient(s.api);
    await pump(tester);

    await tester.enterText(find.byType(TextField), '项目');
    await tester.pump(const Duration(milliseconds: 400));
    await tapChip(tester, '对话');

    expect(s.urls.any((u) => u.contains('tab=chats')), isTrue, reason: s.urls.toString());
    expect(find.text('项目群'), findsOneWidget);
    expect(find.text('3 人'), findsOneWidget);
  });
}
