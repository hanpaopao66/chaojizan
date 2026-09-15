import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:package_info_plus/package_info_plus.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:superz_shared/superz_shared.dart';
import 'package:user_app/chat/links.dart';
import 'package:user_app/chat/pages/chat_settings_page.dart';
import 'package:user_app/chat/pages/contacts_page.dart';
import 'package:user_app/chat/pages/my_card_page.dart';
import 'package:user_app/chat/pages/user_profile_page.dart';
import 'package:user_app/chat/store.dart';
import 'package:user_app/main.dart' show superZTheme;
import 'package:user_app/qr_login/qr_scan_page.dart';

/// 超级赞号(相当于微信号)和加联系人的客户端这一侧(服务端在 server/tests 的 test_custom_id / e2e_custom_id):
///
/// - 添加联系人:11 位手机号按手机号找,别的按超级赞号找;找到了摆出名片、「添加到联系人」;找不到照实说;
/// - 扫一扫:扫到本站的名片码直接打开资料页;外站长得一样的链接不打开,摆出来让人自己决定;
/// - 超级赞号页:一年一次的名额没到时写明下次哪天能改,只改大小写照样能存;
/// - 我的名片:关了「按超级赞号找到我」时说清楚码里为什么是随机编号。

const _pid = 'AbCdEfGh2345';

Map<String, dynamic> _card({bool contact = false}) => {
      'id': 5,
      'name': '王小二',
      'username': 'xiaowang_01',
      'avatar': '',
      'bio': '',
      'public_id': _pid,
      'last_seen': {'online': false, 'at': null, 'approx': 'recently'},
      'is_contact': contact,
      'contact_alias': '',
      'blocked': false,
      'is_bot': false,
      'is_self': false,
    };

class FakeSocial {
  final requests = <http.Request>[];
  bool added = false;
  String searchSwitch = 'everyone';

  List<http.Request> where(String method, String path) =>
      [for (final r in requests) if (r.method == method && r.url.path == path) r];

  static http.Response _json(Object body, [int code = 200]) =>
      http.Response(jsonEncode(body), code, headers: {'content-type': 'application/json; charset=utf-8'});

  late final MockClient client = MockClient((req) async {
    requests.add(req);
    final p = req.url.path;
    if (p == '/social/v1/me') {
      return _json({
        'id': 1,
        'name': '我自己',
        'username': 'me_first',
        'username_next_change_at': null,
        'avatar': '',
        'public_id': 'Zz9876543210',
        'privacy': {'username_search': searchSwitch},
        'link': searchSwitch == 'nobody' ? 'https://chaojizan.cc/u/Zz9876543210' : 'https://chaojizan.cc/@me_first',
      });
    }
    if (req.method == 'POST' && p == '/social/v1/find-by-phone') {
      final phone = (jsonDecode(req.body) as Map)['phone'];
      if (phone == '13900001111') return _json(_card(contact: added));
      return _json({'detail': '没有找到。对方可能还没注册,或者关闭了「按手机号找到我」'}, 404);
    }
    if (p == '/social/v1/resolve/xiaowang_01') return _json({'type': 'user', 'user': _card(contact: added)});
    if (p.startsWith('/social/v1/resolve/')) {
      return _json({'detail': '没有找到。可能是超级赞号输错了,或者对方关闭了「按超级赞号找到我」'}, 404);
    }
    if (p == '/social/v1/resolve-id/$_pid') return _json({'type': 'user', 'user': _card(contact: added)});
    if (req.method == 'POST' && p == '/social/v1/contacts') {
      added = true;
      return _json(_card(contact: true));
    }
    if (p == '/social/v1/users/5') return _json(_card(contact: added));
    return _json({'detail': '没有这个接口'}, 404);
  });

  ApiClient api() => ApiClient(baseUrl: 'http://test.local', httpClient: client);
}

Future<void> settle(WidgetTester tester) async {
  for (var i = 0; i < 8; i++) {
    await tester.pump(const Duration(milliseconds: 20));
  }
}

void main() {
  setUpAll(() {
    TestWidgetsFlutterBinding.ensureInitialized();
    // package_info_plus 在测试环境没有平台通道,不铺好的话第一个请求要等它超时
    PackageInfo.setMockInitialValues(
        appName: 'user_app', packageName: 'com.superz.user', version: '0.1.0', buildNumber: '1', buildSignature: '');
  });
  setUp(() => SharedPreferences.setMockInitialValues({}));
  tearDown(() => ChatStore.instance.debugDetach());

  group('名片链接只认本站', () {
    test('本站的 /@号、/u/编号 认;别的域名、别的路径不认', () {
      expect(cardRefOf('https://chaojizan.cc/@xiaowang_01')?.username, 'xiaowang_01');
      expect(cardRefOf('  https://www.chaojizan.cc/@xiaowang_01\n')?.username, 'xiaowang_01');
      expect(cardRefOf('https://CHAOJIZAN.CC/@xiaowang_01')?.username, 'xiaowang_01');
      expect(cardRefOf('https://chaojizan.cc/u/$_pid')?.publicId, _pid);
      // 长得一样的外站链接
      expect(cardRefOf('https://chaojizan.cc.evil.example/@xiaowang_01'), isNull);
      expect(cardRefOf('https://evil.example/@xiaowang_01'), isNull);
      expect(cardRefOf('https://chaojizan.cc@evil.example/@xiaowang_01'), isNull);
      expect(cardRefOf('https://evilchaojizan.cc/@xiaowang_01'), isNull);
      expect(cardRefOf('https://chaojizan.cc:8443/@xiaowang_01'), isNull);
      // 本站但不是名片:频道里的一条、邀请链接、登录码、格式不对的号
      expect(cardRefOf('https://chaojizan.cc/@somechannel/12'), isNull);
      expect(cardRefOf('https://chaojizan.cc/join/abcdefgh'), isNull);
      expect(cardRefOf('https://chaojizan.cc/l/AbCdEfGhIjKlMnOpQrStUvWxYz012345'), isNull);
      expect(cardRefOf('https://chaojizan.cc/@ab'), isNull);
      expect(cardRefOf('https://chaojizan.cc/u/0OIl'), isNull);
      expect(cardRefOf('javascript:alert(1)'), isNull);
      expect(cardRefOf('xiaowang_01'), isNull);
    });

    test('添加联系人的输入框:11 位按手机号,别的按超级赞号', () {
      expect(contactQueryOf('139 0000-1111').kind, ContactQueryKind.phone);
      expect(contactQueryOf('+86 13900001111').value, '13900001111');
      expect(contactQueryOf('@xiaowang_01').kind, ContactQueryKind.username);
      expect(contactQueryOf('@xiaowang_01').value, 'xiaowang_01');
      expect(contactQueryOf('xiaowang_01').kind, ContactQueryKind.username);
      expect(contactQueryOf('https://chaojizan.cc/u/$_pid').kind, ContactQueryKind.publicId);
      expect(contactQueryOf('chaojizan.cc/@xiaowang_01').value, 'xiaowang_01');
      expect(contactQueryOf('https://chaojizan.cc/join/abcdefgh').kind, ContactQueryKind.link);
      expect(contactQueryOf('1380000').kind, ContactQueryKind.invalid, reason: '纯数字不是 11 位:不当成号去找');
      expect(contactQueryOf('王小二').kind, ContactQueryKind.invalid);
      expect(contactQueryOf('ab').kind, ContactQueryKind.invalid);
    });
  });

  group('添加联系人', () {
    late FakeSocial server;

    Future<void> pumpPage(WidgetTester tester) async {
      server = FakeSocial();
      ChatStore.instance.debugAttach(server.api());
      await tester.pumpWidget(MaterialApp(theme: superZTheme(Brightness.light), home: const AddContactPage()));
      await settle(tester);
    }

    Future<void> search(WidgetTester tester, String q) async {
      await tester.enterText(find.byType(TextField), q);
      await tester.tap(find.byIcon(Icons.search));
      await settle(tester);
    }

    testWidgets('11 位手机号:按手机号找,摆出名片,「添加到联系人」直接加上', (tester) async {
      await pumpPage(tester);
      await search(tester, '139 0000 1111');
      expect(jsonDecode(server.where('POST', '/social/v1/find-by-phone').single.body)['phone'], '13900001111');
      expect(server.requests.where((r) => r.url.path.startsWith('/social/v1/resolve')), isEmpty);
      expect(find.text('王小二'), findsOneWidget);
      expect(find.text('超级赞号:@xiaowang_01'), findsOneWidget);
      await tester.tap(find.text('添加到联系人'));
      await settle(tester);
      expect(jsonDecode(server.where('POST', '/social/v1/contacts').single.body)['user_id'], 5);
      expect(find.text('已在你的联系人里'), findsOneWidget);
      expect(find.text('发消息'), findsOneWidget);
      expect(find.text('添加到联系人'), findsNothing);
    });

    testWidgets('别的按超级赞号找(@ 可带可不带),找到了能加', (tester) async {
      await pumpPage(tester);
      await search(tester, '@xiaowang_01');
      expect(server.where('GET', '/social/v1/resolve/xiaowang_01'), hasLength(1));
      expect(server.where('POST', '/social/v1/find-by-phone'), isEmpty);
      expect(find.text('超级赞号:@xiaowang_01'), findsOneWidget);
      await tester.tap(find.text('添加到联系人'));
      await settle(tester);
      expect(server.where('POST', '/social/v1/contacts'), hasLength(1));
      expect(find.text('已在你的联系人里'), findsOneWidget);
    });

    testWidgets('按号找不到:照实说可能的原因,再告诉当面怎么加', (tester) async {
      await pumpPage(tester);
      await search(tester, 'nobody_here');
      expect(find.textContaining('没有找到。可能是超级赞号输错了,或者对方关闭了「按超级赞号找到我」'), findsOneWidget);
      // 页名跟着底部那一格走(nav.chat,默认「聊天」;2026-09-15 以前叫「消息」)
      expect(find.textContaining('「聊天设置 → 我的名片」'), findsOneWidget);
      expect(find.text('添加到联系人'), findsNothing);
    });

    testWidgets('按手机号找不到:照实说', (tester) async {
      await pumpPage(tester);
      await search(tester, '13900002222');
      expect(find.textContaining('对方可能还没注册,或者关闭了「按手机号找到我」'), findsOneWidget);
    });

    testWidgets('纯数字又不是 11 位:不发请求,直接说', (tester) async {
      await pumpPage(tester);
      final before = server.requests.length;
      await search(tester, '1380000');
      expect(server.requests.length, before, reason: '输错了不该去问服务端');
      expect(find.textContaining('手机号要输完整的 11 位'), findsOneWidget);
    });

    testWidgets('底下有「我的名片」入口,显示自己的号', (tester) async {
      await pumpPage(tester);
      expect(find.text('我的名片'), findsOneWidget);
      expect(find.text('@me_first'), findsOneWidget);
    });

    testWidgets('窄屏手机 + 长辈版 1.4 倍字:名片卡、加完之后那一行都不溢出', (tester) async {
      tester.view.physicalSize = const Size(360 * 3, 760 * 3);
      tester.view.devicePixelRatio = 3;
      addTearDown(tester.view.reset);
      server = FakeSocial();
      ChatStore.instance.debugAttach(server.api());
      await tester.pumpWidget(MaterialApp(
        theme: superZTheme(Brightness.light),
        builder: (context, child) => MediaQuery(
            data: MediaQuery.of(context).copyWith(textScaler: const TextScaler.linear(1.4)), child: child!),
        home: const AddContactPage(),
      ));
      await settle(tester);
      await search(tester, 'xiaowang_01');
      expect(find.text('添加到联系人'), findsOneWidget);
      await tester.tap(find.text('添加到联系人'));
      await settle(tester);
      expect(find.text('已在你的联系人里'), findsOneWidget);
      // 溢出的话 Flutter 会报 RenderFlex overflowed,测试框架当异常抛出来
      expect(tester.takeException(), isNull);
    });
  });

  group('扫一扫扫到名片码', () {
    late FakeSocial server;

    Future<void> pumpScan(WidgetTester tester, String code) async {
      server = FakeSocial();
      final api = server.api();
      ChatStore.instance.debugAttach(api);
      await tester.pumpWidget(MaterialApp(
        theme: superZTheme(Brightness.light),
        home: QrScanPage(
          api: api,
          scannerBuilder: (context, onCode) => Center(
            child: TextButton(onPressed: () => onCode(code), child: const Text('假装扫到')),
          ),
        ),
      ));
      await tester.tap(find.text('假装扫到'));
      await settle(tester);
    }

    testWidgets('本站 /@号:直接打开对方资料页,页上能加联系人', (tester) async {
      await pumpScan(tester, 'https://chaojizan.cc/@xiaowang_01');
      expect(server.where('GET', '/social/v1/resolve/xiaowang_01'), hasLength(1));
      expect(find.byType(UserProfilePage), findsOneWidget);
      await tester.pump(const Duration(milliseconds: 500)); // 等换页动画走完,旧页才从树上下来
      expect(find.byType(QrScanPage), findsNothing, reason: '扫码页换成资料页,返回就回到扫之前的地方');
      expect(find.text('王小二'), findsOneWidget);
      expect(find.text('加为联系人'), findsOneWidget);
      await tester.tap(find.text('加为联系人'));
      await settle(tester);
      expect(server.where('POST', '/social/v1/contacts'), hasLength(1));
    });

    testWidgets('本站 /u/名片编号:一样打开资料页', (tester) async {
      await pumpScan(tester, 'https://chaojizan.cc/u/$_pid');
      expect(server.where('GET', '/social/v1/resolve-id/$_pid'), hasLength(1));
      expect(find.byType(UserProfilePage), findsOneWidget);
    });

    testWidgets('号找不到(比如对方关了按号找到):照实说,可以继续扫', (tester) async {
      await pumpScan(tester, 'https://chaojizan.cc/@nobody_here');
      expect(find.text('打不开这张名片'), findsOneWidget);
      expect(find.byType(UserProfilePage), findsNothing);
      await tester.tap(find.text('继续扫'));
      await settle(tester);
      expect(find.byType(QrScanPage), findsOneWidget);
    });

    for (final url in [
      'https://chaojizan.cc.evil.example/@xiaowang_01',
      'https://evil.example/@xiaowang_01',
      'https://evil.example/u/$_pid',
    ]) {
      testWidgets('外站长得一样的链接不打开:$url', (tester) async {
        await pumpScan(tester, url);
        expect(server.requests, isEmpty, reason: '不是本站的名片码,一个请求都不该发');
        expect(find.byType(UserProfilePage), findsNothing);
        expect(find.text('扫到的内容'), findsOneWidget);
        expect(find.text(url), findsOneWidget);
        expect(find.text('打开链接'), findsOneWidget, reason: '要不要打开由人自己点');
      });
    }

    testWidgets('本站但不是名片(邀请链接):也摆出来,不自动打开', (tester) async {
      await pumpScan(tester, 'https://chaojizan.cc/join/abcdefgh');
      expect(server.requests, isEmpty);
      expect(find.text('扫到的内容'), findsOneWidget);
    });
  });

  group('超级赞号页', () {
    Future<void> pumpUsername(WidgetTester tester, {DateTime? next}) async {
      final server = FakeSocial();
      ChatStore.instance.debugAttach(server.api());
      await tester.pumpWidget(MaterialApp(
        theme: superZTheme(Brightness.light),
        home: UsernamePage(current: 'xiaowang_01', nextChangeAt: next),
      ));
      await settle(tester);
    }

    TextButton saveButton(WidgetTester tester) =>
        tester.widget<TextButton>(find.widgetWithText(TextButton, '保存'));

    testWidgets('一年一次的名额没到:写明下次哪天能改;换别的号存不了,只改大小写能存', (tester) async {
      // 服务端给的是北京时间零点;日期按北京时间写(测试机在哪个时区都一样),和服务端拒绝时那句话对得上
      final next = DateTime.parse('${DateTime.now().year + 1}-03-01T00:00:00+08:00');
      final day = '${DateTime.now().year + 1}-03-01';
      await pumpUsername(tester, next: next);
      expect(find.text('下次可修改:$day'), findsOneWidget);
      expect(find.text('超级赞号'), findsWidgets);
      expect(find.textContaining('5–32 位'), findsOneWidget, reason: '规则说明照服务端的真实规则写');
      await tester.enterText(find.byType(TextField), 'another_01');
      await settle(tester);
      expect(find.text('一年只能改一次,下次可修改:$day'), findsOneWidget);
      expect(saveButton(tester).onPressed, isNull);
      await tester.enterText(find.byType(TextField), 'XiaoWang_01');
      await settle(tester);
      expect(find.text('只改大小写,不算修改'), findsOneWidget);
      expect(saveButton(tester).onPressed, isNotNull);
    });

    testWidgets('名额到了:不显示下次可修改', (tester) async {
      await pumpUsername(tester);
      expect(find.textContaining('下次可修改'), findsNothing);
      expect(find.text('不用超级赞号了'), findsOneWidget);
    });
  });

  testWidgets('我的名片:关了按超级赞号找到我,说清楚码里为什么是随机编号', (tester) async {
    final server = FakeSocial()..searchSwitch = 'nobody';
    ChatStore.instance.debugAttach(server.api());
    await tester.pumpWidget(MaterialApp(theme: superZTheme(Brightness.light), home: const MyCardPage()));
    await settle(tester);
    expect(find.text('https://chaojizan.cc/u/Zz9876543210'), findsOneWidget);
    expect(find.textContaining('你关了「按超级赞号找到我」'), findsOneWidget);
  });
}
