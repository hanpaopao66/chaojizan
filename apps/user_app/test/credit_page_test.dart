import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:package_info_plus/package_info_plus.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:superz_shared/superz_shared.dart';
import 'package:user_app/credit_page.dart';
import 'package:user_app/main.dart';

/// 「我的信用分」:分数、每一项加减分和对应的记录、每条扣分旁边的申诉。
///
/// ## 守的是什么
///
/// - 每一条扣分都**指得出是哪一单、哪一天、到哪天不再计分**,旁边就是申诉;
/// - 申诉入口按服务端给的 `appeal.via` 走:原通道(配送异常 72 小时内)打 `/appeals`,
///   接不上的打 `/credit/me/appeals`(客服工单),申诉过的只显示状态、不再给按钮;
/// - 公式那一段是服务端 `rules` 原样摊开 —— 页面上不写死任何分值(测试里的 rules
///   故意用了一套和线上不一样的数,页面照样照着它显示);
/// - 「我的」页那一行挂的是分数和等级。
void main() {
  setUpAll(() {
    TestWidgetsFlutterBinding.ensureInitialized();
    PackageInfo.setMockInitialValues(
      appName: 'user_app',
      packageName: 'com.superz.user',
      version: '0.1.0',
      buildNumber: '1',
      buildSignature: '',
    );
  });
  setUp(() => SharedPreferences.setMockInitialValues({}));

  // 故意和线上的常量不一样:页面必须照着服务端给的这一份显示,不能自己写一份
  final rules = <String, dynamic>{
    'formula': '信用分 = 80 + 完成订单加分 − 扣分合计,结果限定在 0–100 之间。只看最近 120 天',
    'base_why': '新用户从 80 分起步',
    'levels': [
      {'min': 80, 'key': 'good', 'label': '良好'},
      {'min': 60, 'key': 'fair', 'label': '一般'},
      {'min': 0, 'key': 'low', 'label': '偏低'},
    ],
    'level_rule': '只要没有计分的扣分项,不管新老用户都是「良好」',
    'plus': [
      {
        'key': 'order_completed',
        'label': '完成一单',
        'points': 2,
        'cap': 6,
        'counts': '最近 120 天里完成的订单,每单 +2,最多 +6',
        'not_counted': ['追加的菜'],
      }
    ],
    'minus': [
      {
        'key': 'delivery_fault',
        'label': '配送时联系不上或地址有误,平台判为顾客原因',
        'points': -7,
        'counts': '每次 −7',
        'appeal': '72 小时内在订单页申诉',
      },
    ],
    'minus_cap': '扣分不设上限,扣到 0 为止',
    'not_counted': [
      {'what': '给差评、评价被隐藏', 'why': '不等于你做错了什么'},
    ],
    'visibility': [
      {'who': '商家', 'what': '接单之后,在这一单上看到分数和等级,看不到明细'},
    ],
    'never_used_for': ['不用来自动拒单'],
    'appeal': {'summary': '每一条扣分旁边都有「申诉」', 'once': '一条记录走一次工单申诉'},
    'refresh': '你自己看到的是现算的',
  };

  // 时刻都取 UTC 正午:页面按本地日期显示,正午在 ±11 小时的时区里都落在同一天
  // (开发机常在 PDT,取凌晨的话本地日期会早一天)
  Map<String, dynamic> credit() => {
        'score': 71,
        'level': 'fair',
        'level_label': '一般',
        'base': 80,
        'plus': 4,
        'minus': 13,
        'formula_line': '80 + 4 − 13 = 71',
        'window_days': 120,
        'orders': {
          'count': 2,
          'points': 4,
          'cap': 6,
          'recent': [
            {'order_no': 'aaaaaaaaaaaa11a1b2', 'at': '2026-09-10T12:00:00+00:00'},
            {'order_no': 'aaaaaaaaaaaa22c3d4', 'at': '2026-09-01T12:00:00+00:00'},
          ],
        },
        'deductions': [
          {
            'kind': 'delivery_fault',
            'record_id': 12,
            'title': '配送时联系不上,平台判为顾客原因(按送达处理)',
            'order_no': 'bbbbbbbbbbbbffe901',
            'note': '骑手有通话记录',
            'points': -7,
            'at': '2026-09-12T12:00:00+00:00',
            'expires_at': '2027-01-10T12:00:00+00:00',
            'appeal': {
              'via': 'appeal',
              'target_type': 'delivery_issue',
              'target_id': 12,
              'state': '',
              'label': '申诉',
              'note': '',
              'after': '申诉成立后,这一条不再计分,分数马上重算',
            },
          },
          {
            'kind': 'violation',
            'record_id': 5,
            'title': '违规成立:恶意售后',
            'order_no': '',
            'note': '同一话术在三家店要求退款',
            'points': -3,
            'at': '2026-09-02T12:00:00+00:00',
            'expires_at': '2026-12-31T12:00:00+00:00',
            'appeal': {
              'via': 'ticket',
              'target_type': '',
              'target_id': 0,
              'state': '',
              'label': '申诉(客服工单)',
              'note': '',
              'after': '申诉成立后,这一条不再计分,分数马上重算',
            },
          },
          {
            'kind': 'violation',
            'record_id': 6,
            'title': '违规成立:刷单',
            'order_no': 'cccccccccccc778899',
            'note': '',
            'points': -3,
            'at': '2026-08-20T12:00:00+00:00',
            'expires_at': '2026-12-18T12:00:00+00:00',
            'appeal': {
              'via': '',
              'target_type': '',
              'target_id': 0,
              'state': 'upheld',
              'label': '申诉后维持原判',
              'note': '三家店的记录话术一致',
              'after': '申诉成立后,这一条不再计分,分数马上重算',
            },
          },
        ],
        'excluded': [
          {
            'kind': 'delivery_fault',
            'record_id': 3,
            'title': '配送时地址有误,平台判为顾客原因(按送达处理)',
            'order_no': 'dddddddddddd445566',
            'at': '2026-07-01T12:00:00+00:00',
            'why': '申诉成立,不再计分',
          }
        ],
        'rules': rules,
      };

  /// 记下每一个请求(方法、路径、请求体)
  final calls = <(String, String, Map<String, dynamic>)>[];

  ApiClient fakeApi() => ApiClient(
        baseUrl: 'http://test.local',
        httpClient: MockClient((req) async {
          final body = req.body.isEmpty
              ? <String, dynamic>{}
              : (jsonDecode(req.body) as Map).cast<String, dynamic>();
          calls.add((req.method, req.url.path, body));
          Object? payload;
          switch (req.url.path) {
            case '/auth/login':
              payload = {'token': 'tkn', 'user_id': 1, 'name': '张三', 'role': 'customer'};
            case '/auth/me':
              payload = {
                'id': 1, 'phone': '13800000001', 'name': '张三', 'role': 'customer',
                'avatar_url': '', 'birthday': '', 'marketing_push': true,
                'risk_level': '', 'risk_note': '', 'identity_verified': false,
              };
            case '/credit/me':
              payload = credit();
            case '/credit/me/brief':
              payload = {'score': 71, 'level': 'fair', 'level_label': '一般'};
            case '/credit/me/appeals':
              payload = {'id': 1, 'status': 'open', 'ticket_id': 9, 'note': ''};
            case '/appeals':
              payload = {'id': 2, 'status': 'open'};
            case '/config':
              payload = {'marketing': true};
            case '/orders':
            case '/stays/orders/mine':
              payload = <Object>[];
            case '/mini-apps/catalog':
              payload = {'items': [], 'total': 0, 'next_cursor': null,
                         'categories': [], 'sort_rule': ''};
            default:
              payload = <String, dynamic>{};
          }
          return http.Response(jsonEncode(payload), 200,
              headers: {'content-type': 'application/json; charset=utf-8'});
        }),
      );

  Future<ApiClient> loggedIn() async {
    calls.clear();
    final api = fakeApi();
    await api.login('13800000001', 'pw');
    return api;
  }

  /// 竖着给足高度:整页一次铺开,断言不受懒加载影响
  Future<void> pumpPage(WidgetTester t, Widget page) async {
    t.view
      ..devicePixelRatio = 3.0
      ..physicalSize = const Size(390, 3600) * 3.0;
    addTearDown(t.view.reset);
    await t.pumpWidget(MaterialApp(theme: brandTheme(Brightness.light), home: page));
    await t.pumpAndSettle();
  }

  bool hasText(String needle) => find
      .byType(Text)
      .evaluate()
      .map((e) => (e.widget as Text).data ?? '')
      .any((s) => s.contains(needle));

  testWidgets('分数、公式行、每一条扣分都指得出是哪一单哪一天', (t) async {
    await pumpPage(t, CreditPage(api: await loggedIn()));
    expect(find.text('71'), findsOneWidget);
    expect(find.text('一般'), findsOneWidget);
    expect(hasText('80 + 4 − 13 = 71'), isTrue);
    expect(hasText('只看最近 120 天'), isTrue);
    // 扣分:标题、分值、订单尾号、日期、到哪天不再计分、平台的说明
    expect(hasText('配送时联系不上,平台判为顾客原因'), isTrue);
    expect(find.text('-7'), findsOneWidget);
    expect(hasText('订单尾号 ffe901'), isTrue);
    expect(hasText('2027-01-10 起不再计分'), isTrue);
    expect(hasText('平台的说明:骑手有通话记录'), isTrue);
    // 加分:单数和最近的单
    expect(hasText('完成订单 2 单'), isTrue);
    expect(find.text('+4'), findsOneWidget);
    expect(hasText('订单尾号 11a1b2'), isTrue);
    // 申诉成立、不再计分的那一条也看得到
    expect(hasText('申诉成立,不再计分'), isTrue);
    expect(hasText('配送时地址有误'), isTrue);
  });

  testWidgets('申诉入口按 via 走;申诉过的只显示状态;每条都写明申诉成立后不再计分', (t) async {
    await pumpPage(t, CreditPage(api: await loggedIn()));
    expect(find.widgetWithText(TextButton, '申诉'), findsOneWidget);
    expect(find.widgetWithText(TextButton, '申诉(客服工单)'), findsOneWidget);
    // 维持原判的那条:没有按钮,写明结论
    expect(hasText('申诉后维持原判'), isTrue);
    expect(hasText('复核结论:三家店的记录话术一致'), isTrue);
    expect(find.textContaining('申诉成立后,这一条不再计分'), findsNWidgets(3));
  });

  testWidgets('走工单:打 /credit/me/appeals,带着是哪一条', (t) async {
    await pumpPage(t, CreditPage(api: await loggedIn()));
    await t.tap(find.widgetWithText(TextButton, '申诉(客服工单)'));
    await t.pumpAndSettle();
    await t.enterText(find.byType(TextField), '那天的退款是商家自己同意的');
    await t.tap(find.widgetWithText(FilledButton, '提交申诉'));
    await t.pumpAndSettle();
    final post = calls.where((c) => c.$1 == 'POST' && c.$2 == '/credit/me/appeals');
    expect(post, hasLength(1));
    expect(post.first.$3['kind'], 'violation');
    expect(post.first.$3['record_id'], 5);
    expect(calls.where((c) => c.$2 == '/appeals'), isEmpty);
    // 提交完重拉一次明细
    expect(calls.where((c) => c.$2 == '/credit/me').length, 2);
  });

  testWidgets('走原通道:打 /appeals,target 是那张配送异常工单', (t) async {
    await pumpPage(t, CreditPage(api: await loggedIn()));
    await t.tap(find.widgetWithText(TextButton, '申诉'));
    await t.pumpAndSettle();
    await t.enterText(find.byType(TextField), '我一直在家,手机没有未接来电');
    await t.tap(find.widgetWithText(FilledButton, '提交申诉'));
    await t.pumpAndSettle();
    final post = calls.where((c) => c.$1 == 'POST' && c.$2 == '/appeals').toList();
    expect(post, hasLength(1));
    expect(post.first.$3['target_type'], 'delivery_issue');
    expect(post.first.$3['target_id'], 12);
    expect(calls.where((c) => c.$2 == '/credit/me/appeals'), isEmpty);
  });

  testWidgets('公式那一段照着服务端给的 rules 显示,不写死分值', (t) async {
    await pumpPage(t, CreditPage(api: await loggedIn()));
    expect(hasText('信用分 = 80 + 完成订单加分'), isTrue);
    expect(hasText('良好 ≥ 80 · 一般 60–79 · 偏低 0–59'), isTrue);
    expect(hasText('最近 120 天里完成的订单,每单 +2,最多 +6'), isTrue);
    expect(hasText('不算:追加的菜'), isTrue);
    expect(hasText('给差评、评价被隐藏:不等于你做错了什么'), isTrue);
    expect(hasText('商家:接单之后,在这一单上看到分数和等级,看不到明细'), isTrue);
    expect(hasText('不用来自动拒单'), isTrue);
  });

  testWidgets('「我的」页那一行挂分数和等级', (t) async {
    await pumpPage(t, Scaffold(body: ProfileView(api: await loggedIn())));
    expect(find.text('我的信用分'), findsOneWidget);
    expect(find.text('71 分 · 一般'), findsOneWidget);
  });

  testWidgets('老服务端没有这个接口:那一行不挂 0 分', (t) async {
    calls.clear();
    final api = ApiClient(
      baseUrl: 'http://test.local',
      httpClient: MockClient((req) async {
        if (req.url.path == '/credit/me/brief') {
          return http.Response('{"detail":"Not Found"}', 404,
              headers: {'content-type': 'application/json'});
        }
        final payload = switch (req.url.path) {
          '/auth/login' => {'token': 'tkn', 'user_id': 1, 'name': '张三', 'role': 'customer'},
          '/orders' || '/stays/orders/mine' => <Object>[],
          _ => <String, dynamic>{},
        };
        return http.Response(jsonEncode(payload), 200,
            headers: {'content-type': 'application/json; charset=utf-8'});
      }),
    );
    await api.login('13800000001', 'pw');
    await pumpPage(t, Scaffold(body: ProfileView(api: api)));
    expect(find.text('我的信用分'), findsOneWidget);
    expect(hasText('0 分'), isFalse);
  });
}
