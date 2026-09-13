import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:package_info_plus/package_info_plus.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:superz_shared/superz_shared.dart';
import 'package:user_app/chat/chat_tab.dart';
import 'package:user_app/chat/extras.dart';
import 'package:user_app/chat/models.dart';
import 'package:user_app/chat/store.dart';
import 'package:user_app/chat/ui/conv_row.dart';
import 'package:user_app/main.dart' show superZTheme;
import 'package:user_app/video/notify/notifications_page.dart';
import 'package:user_app/video/notify/notify_prefs.dart';

/// 「消息」列表(设计稿 A「万物皆会话」):平台服务号、订单群、视频互动都是列表里的会话行,
/// 还在送的订单群置顶;底栏数的是有未读的行,静音的视频互动不算。
void main() {
  setUpAll(() => PackageInfo.setMockInitialValues(
      appName: 'user_app', packageName: 'com.superz.user', version: '0.1.0', buildNumber: '1', buildSignature: ''));
  setUp(() => SharedPreferences.setMockInitialValues({}));
  tearDown(() async {
    ChatExtras.instance.debugReset();
    ChatStore.instance.chats.clear();
    videoNotifyUnreadKinds.value = const {};
    await VideoNotifyPrefs.instance.setMuted(false);
    for (final (k, _) in notifyKinds) {
      await VideoNotifyPrefs.instance.setKind(k, true);
    }
  });

  final now = DateTime.now().toUtc();
  String ago(Duration d) => now.subtract(d).toIso8601String();

  Future<ApiClient> loggedIn() async {
    final api = ApiClient(
      baseUrl: 'http://test.local',
      httpClient: MockClient((req) async {
        final Object payload = switch (req.url.path) {
          '/auth/login' => {'token': 'tkn', 'user_id': 1, 'name': '周小满', 'role': 'customer'},
          // 服务号读的是 /announcements/history(到期的也在);老接口留着兜底
          '/announcements' || '/announcements/history' => [
              {'id': 7, 'title': '「消息」「视频」两个新入口上线了', 'content': '底栏换了', 'created_at': ago(const Duration(minutes: 30))},
            ],
          '/orders/chat-threads' => {
              'items': [
                {
                  'order_no': 'o1',
                  'title': '订单 #aaa001 · 张记面馆',
                  'status': 'picked_up',
                  'status_label': '配送中',
                  'unread': 2,
                  'readonly': false,
                  'last': {
                    'from': 'rider',
                    'sender_name': '赵师傅',
                    'kind': 'text',
                    'content': '到楼下了',
                    'created_at': ago(const Duration(minutes: 2)),
                  },
                  'updated_at': ago(const Duration(minutes: 2)),
                },
                {
                  'order_no': 'o2',
                  'title': '订单 #bbb002 · 砂锅粥',
                  'status': 'completed',
                  'status_label': '已完成',
                  'unread': 0,
                  'readonly': true,
                  'last': null,
                  'updated_at': ago(const Duration(days: 2)),
                },
              ],
            },
          _ => <String, dynamic>{},
        };
        return http.Response(jsonEncode(payload), 200,
            headers: {'content-type': 'application/json; charset=utf-8'});
      }),
    );
    await api.login('13800000001', 'x');
    return api;
  }

  Future<void> pumpTab(WidgetTester tester, ApiClient api) async {
    tester.view.physicalSize = const Size(390, 1200);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
    await tester.pumpWidget(MaterialApp(theme: superZTheme(Brightness.light), home: Scaffold(body: ChatTab(api: api))));
    for (var i = 0; i < 5; i++) {
      await tester.pump(const Duration(milliseconds: 20));
    }
  }

  testWidgets('服务号、订单群、视频互动都是会话行;在送的订单群置顶,送完的按时间排', (tester) async {
    await pumpTab(tester, await loggedIn());

    expect(find.text('超级赞'), findsOneWidget);
    expect(find.byType(VerifiedMark), findsOneWidget, reason: '平台服务号带认证标');
    expect(find.text('「消息」「视频」两个新入口上线了'), findsOneWidget, reason: '服务号的预览是最新一条公告');
    expect(find.text('视频互动'), findsOneWidget);
    expect(find.byType(BotTag), findsOneWidget);
    expect(find.textContaining('配送中 · '), findsOneWidget);
    expect(find.textContaining('赵师傅: 到楼下了'), findsOneWidget);

    double y(String t) => tester.getTopLeft(find.text(t)).dy;
    expect(y('超级赞'), lessThan(y('订单 #aaa001 · 张记面馆')));
    expect(y('订单 #aaa001 · 张记面馆'), lessThan(y('订单 #bbb002 · 砂锅粥')), reason: '在送的置顶,送完的往下排');
    expect(y('订单 #bbb002 · 砂锅粥'), lessThan(y('视频互动')), reason: '视频互动没有提醒时排在最后');

    // 服务号 1 条新公告、订单群 2 条未读:底栏各算一行
    expect(find.descendant(of: find.byType(UnreadBadge), matching: find.text('1')), findsOneWidget);
    expect(find.descendant(of: find.byType(UnreadBadge), matching: find.text('2')), findsOneWidget);
    expect(chatExtraBadge.value, 2);
    ChatExtras.instance.debugReset(); // 在送的单会挂一个一分钟的轮询,测试结束前停掉
  });

  testWidgets('视频互动:静音后角标变灰、不进底栏;提醒设置里关掉的那类不算未读', (tester) async {
    await pumpTab(tester, await loggedIn());
    videoNotifyUnreadKinds.value = {'reply': 3, 'at': 0, 'like': 4, 'system': 0};
    await tester.pump();
    UnreadBadge badgeOf(String n) =>
        tester.widget<UnreadBadge>(find.ancestor(of: find.text(n), matching: find.byType(UnreadBadge)));
    expect(badgeOf('7').muted, isFalse);
    expect(chatExtraBadge.value, 3, reason: '服务号 + 订单群 + 视频互动');

    await VideoNotifyPrefs.instance.setMuted(true);
    await tester.pump();
    expect(badgeOf('7').muted, isTrue, reason: '静音了还看得到有几条,只是变灰');
    expect(chatExtraBadge.value, 2, reason: '静音的视频互动不算进底栏');

    await VideoNotifyPrefs.instance.setMuted(false);
    await VideoNotifyPrefs.instance.setKind('like', false);
    await tester.pump();
    expect(find.descendant(of: find.byType(UnreadBadge), matching: find.text('3')), findsOneWidget,
        reason: '赞不算了,只剩 3 条回复');
    ChatExtras.instance.debugReset();
  });

  testWidgets('聊天会话那一行:免打扰的灰角标,长按出菜单', (tester) async {
    ChatStore.instance.chats[5] = ChatInfo.fromJson({
      'id': 5,
      'type': 'group',
      'title': '高新路 3 号楼街坊群',
      'perms': {'in_chat': true},
      'my': {'muted_until': '2100-01-01T00:00:00Z'},
      'unread': 6,
      'last_seq': 6,
      'last_message': {
        'chat_id': 5,
        'seq': 6,
        'kind': 'text',
        'text': '今天砂锅粥有活动,满 30 减 5',
        'created_at': ago(const Duration(minutes: 20)),
        'sender': {'id': 9, 'name': '刘姐'},
      },
    });
    await pumpTab(tester, await loggedIn());

    expect(find.text('高新路 3 号楼街坊群'), findsOneWidget);
    final badge = tester.widget<UnreadBadge>(find.ancestor(of: find.text('6'), matching: find.byType(UnreadBadge)));
    expect(badge.muted, isTrue);

    await tester.longPress(find.text('高新路 3 号楼街坊群'));
    await tester.pumpAndSettle();
    expect(find.text('取消免打扰'), findsOneWidget);
    expect(find.text('置顶'), findsOneWidget);
    expect(find.text('归档'), findsOneWidget);
    ChatExtras.instance.debugReset();
  });
}
