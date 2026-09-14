import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:package_info_plus/package_info_plus.dart';
import 'package:qr_flutter/qr_flutter.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:superz_shared/superz_shared.dart';
import 'package:user_app/main.dart' show superZTheme;
import 'package:user_app/qr_login/login_devices_page.dart';
import 'package:user_app/qr_login/qr_confirm_page.dart';
import 'package:user_app/qr_login/qr_login.dart';
import 'package:user_app/qr_login/qr_login_panel.dart';
import 'package:user_app/qr_login/qr_scan_page.dart';

/// 扫码登录 / 一键登录的客户端这一侧(服务端在 server/tests 的单测和 e2e_qr_login):
///
/// - 网页版登录面板:二维码、已扫码、确认后接好会话并记住这台设备、手机上取消、过期自动换、换够了停;
/// - 一键登录面板:记住的账号先显示一键登录;失效了忘掉它改成扫码;切换账号带上原来那把 key;
/// - 扫一扫:登录码 → 确认页;别的内容摆出来、不自动打开;别的域名上的 /l/… 不当登录码;
/// - 确认页:设备、IP、时间、那句「不是你本人请点取消」都在;登录 / 取消 / 直接返回;
/// - 手机上查待确认的时机;已登录的网页和电脑:列表和移除。

const _sid = 'AbCdEfGhIjKlMnOpQrStUvWxYz012345';

/// 假服务端。轮询没东西可给时**挂着**(和真服务端的长轮询一样),测试用 [emit] 放出下一个状态
class FakeServer {
  final requests = <http.Request>[];
  final _queued = <Map<String, dynamic>>[];
  Completer<Map<String, dynamic>>? _held;
  int created = 0;

  /// 建会话时带这把 device_key 的回 403(一键登录已失效)
  String deadKey = '';
  int? scanError;
  String scanErrorDetail = '';
  List<Map<String, dynamic>> pending = [];
  List<Map<String, dynamic>> devices = [];

  void emit(Map<String, dynamic> r) {
    final h = _held;
    if (h != null && !h.isCompleted) {
      _held = null;
      h.complete(r);
    } else {
      _queued.add(r);
    }
  }

  /// 测试结束前放掉挂着的轮询(不然 ApiClient 的超时计时器留在那儿,测试框架会报)
  void release() {
    final h = _held;
    _held = null;
    if (h != null && !h.isCompleted) h.complete({'status': 'cancelled'});
  }

  List<http.Request> where(String method, String path) =>
      [for (final r in requests) if (r.method == method && r.url.path == path) r];

  static http.Response _json(Object body, [int code = 200]) => http.Response(
      jsonEncode(body), code,
      headers: {'content-type': 'application/json; charset=utf-8'});

  late final MockClient client = MockClient((req) async {
    requests.add(req);
    final p = req.url.path;
    if (req.method == 'POST' && p == '/auth/qr/sessions') {
      final body = jsonDecode(req.body) as Map<String, dynamic>;
      final key = '${body['device_key'] ?? ''}';
      if (key.isNotEmpty && key == deadKey) {
        return _json({'detail': '这台设备的一键登录已经失效,请扫码登录'}, 403);
      }
      created++;
      final sid = 'S$created'.padRight(32, 'x');
      return _json({
        'sid': sid,
        'secret': 'secret-$created',
        'qr': key.isEmpty ? 'https://chaojizan.cc/l/$sid' : '',
        'mode': key.isEmpty ? 'qr' : 'oneclick',
        'status': key.isEmpty ? 'pending' : 'scanned',
        'expires_at': '2026-09-14T10:02:00+00:00',
        'ttl': 120,
      });
    }
    if (req.method == 'GET' && p.startsWith('/auth/qr/sessions/')) {
      if (_queued.isNotEmpty) return _json(_queued.removeAt(0));
      final c = Completer<Map<String, dynamic>>();
      _held = c;
      return _json(await c.future);
    }
    if (p == '/auth/me') {
      return _json({'id': 7, 'name': '张三丰', 'phone': '13800000007', 'role': 'customer'});
    }
    if (p.endsWith('/scan')) {
      if (scanError != null) return _json({'detail': scanErrorDetail}, scanError!);
      return _json(request());
    }
    if (p.endsWith('/confirm') || p.endsWith('/cancel')) return _json({'ok': true});
    if (p == '/auth/qr/pending') return _json({'items': pending});
    if (req.method == 'GET' && p == '/auth/login-devices') {
      return _json({'items': devices, 'idle_days': 30});
    }
    if (req.method == 'DELETE' && p.startsWith('/auth/login-devices/')) {
      devices = [];
      return _json({'ok': true});
    }
    return _json({'detail': '没有这个接口'}, 404);
  });

  ApiClient api() => ApiClient(baseUrl: 'http://test.local', httpClient: client);
}

/// 服务端 request_view 的样子
Map<String, dynamic> request({String mode = 'qr', bool sameNetwork = true}) => {
      'sid': _sid,
      'mode': mode,
      'client': 'web',
      'device': 'Chrome · macOS',
      'ip': '123.45.*.*',
      'same_network': sameNetwork,
      'created_at': '2026-09-14T03:05:00+00:00',
      'expires_at': '2026-09-14T03:07:00+00:00',
    };

Map<String, Object> remembered({String key = 'key-old'}) => {
      'qr_login_device_v1': jsonEncode({
        'key': key,
        'device_id': 5,
        'user_id': 7,
        'name': '张三丰',
        'avatar_url': '',
      }),
    };

Map<String, dynamic> confirmed({String key = 'key-new'}) => {
      'status': 'confirmed',
      'token': 'aaa.bbb.ccc',
      'user_id': 7,
      'role': 'customer',
      'name': '张三丰',
      'avatar_url': '',
      'device_key': key,
      'device_id': 5,
    };

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
      appName: 'user_app',
      packageName: 'com.superz.user',
      version: '0.1.0',
      buildNumber: '1',
      buildSignature: '',
    );
  });

  group('网页版登录面板', () {
    late FakeServer server;
    late ApiClient api;
    late int loggedIn;

    Future<void> pumpPanel(WidgetTester tester, {Map<String, Object>? prefs}) async {
      SharedPreferences.setMockInitialValues(prefs ?? {});
      server = FakeServer();
      api = server.api();
      loggedIn = 0;
      await tester.pumpWidget(MaterialApp(
        theme: superZTheme(Brightness.light),
        home: Scaffold(
          body: Center(
            child: SizedBox(
              width: 360,
              child: QrLoginPanel(
                api: api,
                host: SzAltLoginHost(usePhone: () {}, loggedIn: () => loggedIn++),
                client: 'web',
                platform: '',
              ),
            ),
          ),
        ),
      ));
      await settle(tester);
    }

    Future<void> finish(WidgetTester tester) async {
      await tester.pumpWidget(const SizedBox());
      server.release();
      await settle(tester);
    }

    testWidgets('没记住账号:直接是二维码,secret 只在请求头里', (tester) async {
      await pumpPanel(tester);
      expect(find.byType(QrImageView), findsOneWidget);
      expect(find.textContaining('「扫一扫」'), findsOneWidget);
      final create = server.where('POST', '/auth/qr/sessions').single;
      expect(jsonDecode(create.body)['client'], 'web');
      final poll = server.requests.last;
      expect(poll.url.path, '/auth/qr/sessions/${'S1'.padRight(32, 'x')}');
      expect(poll.headers['X-QR-Secret'], 'secret-1');
      expect(poll.url.toString().contains('secret-1'), isFalse,
          reason: 'secret 进了 URL,就会跟着路径进访问日志');
      await finish(tester);
    });

    testWidgets('扫了码:显示打码的昵称,请在手机上点登录', (tester) async {
      await pumpPanel(tester);
      server.emit({
        'status': 'scanned',
        'mode': 'qr',
        'user': {'name': '张*丰', 'avatar_url': ''},
      });
      await settle(tester);
      expect(find.text('张*丰'), findsOneWidget);
      expect(find.text('已扫码,请在手机上点「登录」'), findsOneWidget);
      // 下一次轮询带着看到的状态去等变化
      expect(server.requests.last.url.queryParameters['state'], 'scanned');
      await finish(tester);
    });

    testWidgets('手机上确认了:接好会话、记住这台设备、交给登录页收尾', (tester) async {
      await pumpPanel(tester);
      server.emit({'status': 'scanned', 'mode': 'qr', 'user': {'name': '张*丰'}});
      await settle(tester);
      server.emit(confirmed());
      await settle(tester);
      expect(loggedIn, 1);
      expect(api.isLoggedIn, isTrue);
      expect(api.userId, 7);
      expect(api.userPhone, '13800000007'); // 回包里没有,接好之后问 /auth/me 补上的
      final memory = await QrLoginMemory.load();
      expect(memory?.deviceKey, 'key-new');
      expect(memory?.deviceId, 5);
      expect(memory?.name, '张三丰');
      await finish(tester);
    });

    testWidgets('手机上取消:说一声,点一下换新码', (tester) async {
      await pumpPanel(tester);
      server.emit({'status': 'cancelled'});
      await settle(tester);
      expect(find.text('你在手机上取消了这次登录'), findsOneWidget);
      await tester.tap(find.text('刷新二维码'));
      await settle(tester);
      expect(server.created, 2);
      expect(find.text('你在手机上取消了这次登录'), findsNothing);
      await finish(tester);
    });

    testWidgets('过期了自动换一张;一直没人扫,换到第 5 张就停下等人点', (tester) async {
      await pumpPanel(tester);
      server.emit({'status': 'expired'});
      await settle(tester);
      expect(server.created, 2);
      final qr = tester.widget<QrImageView>(find.byType(QrImageView));
      expect(qr, isNotNull);
      for (var i = 0; i < 3; i++) {
        server.emit({'status': 'expired'});
        await settle(tester);
      }
      expect(server.created, 5);
      server.emit({'status': 'expired'});
      await settle(tester);
      expect(server.created, 5, reason: '标签页忘在后台,不该一直去服务端建会话');
      expect(find.text('二维码已过期'), findsOneWidget);
      await tester.tap(find.text('刷新二维码'));
      await settle(tester);
      expect(server.created, 6);
      await finish(tester);
    });

    testWidgets('记住了账号:先显示一键登录,点了才发到手机', (tester) async {
      await pumpPanel(tester, prefs: remembered());
      expect(find.text('张三丰'), findsOneWidget);
      expect(find.text('一键登录'), findsOneWidget);
      expect(find.text('切换账号'), findsOneWidget);
      expect(server.created, 0, reason: '没点之前不该往手机上发任何东西');

      await tester.tap(find.text('一键登录'));
      await settle(tester);
      final create = server.where('POST', '/auth/qr/sessions').single;
      expect(jsonDecode(create.body)['device_key'], 'key-old');
      expect(find.text('已发到你的手机,请在手机上点「登录」'), findsOneWidget);
      expect(find.text('等待手机确认…'), findsOneWidget);

      server.emit(confirmed(key: 'key-rotated'));
      await settle(tester);
      expect(loggedIn, 1);
      expect((await QrLoginMemory.load())?.deviceKey, 'key-rotated',
          reason: 'key 每用一次换一把,要记新的那把');
      await finish(tester);
    });

    testWidgets('手机上没点确认 / 取消了:回到可以再点一次', (tester) async {
      await pumpPanel(tester, prefs: remembered());
      await tester.tap(find.text('一键登录'));
      await settle(tester);
      server.emit({'status': 'cancelled'});
      await settle(tester);
      expect(find.text('你在手机上取消了这次登录'), findsOneWidget);
      expect(find.text('一键登录'), findsOneWidget);
      await finish(tester);
    });

    testWidgets('一键登录失效了:忘掉这台设备,改成扫码,并说清楚为什么', (tester) async {
      await pumpPanel(tester, prefs: remembered(key: 'dead'));
      server.deadKey = 'dead';
      await tester.tap(find.text('一键登录'));
      await settle(tester);
      expect(await QrLoginMemory.load(), isNull);
      expect(find.byType(QrImageView), findsOneWidget);
      expect(find.text('这台设备的一键登录已经失效,请扫码登录'), findsOneWidget);
      await finish(tester);
    });

    testWidgets('切换账号:回到扫码,带上原来那把 key(同一个人扫就不多出一台设备)', (tester) async {
      await pumpPanel(tester, prefs: remembered());
      await tester.tap(find.text('切换账号'));
      await settle(tester);
      expect(find.byType(QrImageView), findsOneWidget);
      final body = jsonDecode(server.where('POST', '/auth/qr/sessions').single.body)
          as Map<String, dynamic>;
      expect(body['prev_device_key'], 'key-old');
      expect(body.containsKey('device_key'), isFalse, reason: '扫码登录不能带 device_key,那是一键登录');
      await finish(tester);
    });
  });

  group('扫一扫', () {
    test('只认官方域名或者这台服务器上的 /l/<sid>', () {
      const api = 'http://10.0.2.2:8013';
      expect(loginSidOf('https://chaojizan.cc/l/$_sid', apiBase: api), _sid);
      expect(loginSidOf('https://www.chaojizan.cc/l/$_sid', apiBase: api), _sid);
      expect(loginSidOf('http://10.0.2.2:8013/l/$_sid', apiBase: api), _sid);
      expect(loginSidOf('  https://chaojizan.cc/l/$_sid\n', apiBase: api), _sid);
      // 别的域名上长得一样的:不是我们发的码
      expect(loginSidOf('https://chaojizan.cc.evil.example/l/$_sid', apiBase: api), isNull);
      expect(loginSidOf('https://evil.example/l/$_sid', apiBase: api), isNull);
      expect(loginSidOf('https://chaojizan.cc/s/$_sid', apiBase: api), isNull);
      expect(loginSidOf('https://chaojizan.cc/l/short', apiBase: api), isNull);
      expect(loginSidOf('https://chaojizan.cc/l/$_sid/x', apiBase: api), isNull);
      expect(loginSidOf('就一段字', apiBase: api), isNull);
      expect(loginSidOf('javascript:alert(1)', apiBase: api), isNull);
    });

    late FakeServer server;

    Future<void> pumpScan(WidgetTester tester, String code) async {
      SharedPreferences.setMockInitialValues({});
      server = FakeServer();
      await tester.pumpWidget(MaterialApp(
        theme: superZTheme(Brightness.light),
        home: QrScanPage(
          api: server.api(),
          scannerBuilder: (context, onCode) => Center(
            child: TextButton(onPressed: () => onCode(code), child: const Text('假装扫到')),
          ),
        ),
      ));
      await tester.tap(find.text('假装扫到'));
      await settle(tester);
    }

    testWidgets('扫到登录码:调 scan,换成确认页', (tester) async {
      await pumpScan(tester, 'https://chaojizan.cc/l/$_sid');
      expect(server.where('POST', '/auth/qr/sessions/$_sid/scan'), hasLength(1));
      expect(find.byType(QrConfirmPage), findsOneWidget);
      expect(find.text('在 Chrome · macOS 上登录超级赞?'), findsOneWidget);
    });

    testWidgets('扫到别的内容:摆出来让人自己决定,不自动打开', (tester) async {
      await pumpScan(tester, 'https://example.com/promo?id=1');
      expect(find.text('扫到的内容'), findsOneWidget);
      expect(find.text('https://example.com/promo?id=1'), findsOneWidget);
      expect(find.text('打开链接'), findsOneWidget);
      expect(find.text('复制'), findsOneWidget);
      expect(server.requests, isEmpty, reason: '不是登录码,一个请求都不该发');
      expect(find.byType(QrConfirmPage), findsNothing);
    });

    testWidgets('扫到的是一段字:没有「打开链接」', (tester) async {
      await pumpScan(tester, '桌号 12');
      expect(find.text('桌号 12'), findsOneWidget);
      expect(find.text('打开链接'), findsNothing);
      expect(find.text('复制'), findsOneWidget);
    });

    testWidgets('登录码登不了(被别人扫过):照实说,可以继续扫', (tester) async {
      SharedPreferences.setMockInitialValues({});
      server = FakeServer()
        ..scanError = 409
        ..scanErrorDetail = '这个二维码已经被别人扫过了,请在电脑上刷新二维码';
      await tester.pumpWidget(MaterialApp(
        theme: superZTheme(Brightness.light),
        home: QrScanPage(
          api: server.api(),
          scannerBuilder: (context, onCode) => Center(
            child: TextButton(
                onPressed: () => onCode('https://chaojizan.cc/l/$_sid'),
                child: const Text('假装扫到')),
          ),
        ),
      ));
      await tester.tap(find.text('假装扫到'));
      await settle(tester);
      expect(find.text('登录不了'), findsOneWidget);
      expect(find.text('这个二维码已经被别人扫过了,请在电脑上刷新二维码'), findsOneWidget);
      await tester.tap(find.text('继续扫'));
      await settle(tester);
      expect(find.byType(QrScanPage), findsOneWidget);
      expect(find.byType(QrConfirmPage), findsNothing);
    });
  });

  group('确认页', () {
    late FakeServer server;
    bool? result;

    Future<void> pumpConfirm(WidgetTester tester, Map<String, dynamic> req) async {
      SharedPreferences.setMockInitialValues({});
      server = FakeServer();
      result = null;
      final api = server.api();
      await tester.pumpWidget(MaterialApp(
        theme: superZTheme(Brightness.light),
        home: Builder(
          builder: (context) => Scaffold(
            body: Center(
              child: TextButton(
                onPressed: () async {
                  result = await Navigator.of(context).push<bool>(MaterialPageRoute(
                      builder: (_) => QrConfirmPage(api: api, request: req)));
                },
                child: const Text('打开'),
              ),
            ),
          ),
        ),
      ));
      await tester.tap(find.text('打开'));
      await tester.pumpAndSettle();
    }

    testWidgets('设备、IP、同一个网络、时间,还有那句提醒都在', (tester) async {
      await pumpConfirm(tester, request());
      expect(find.text('在 Chrome · macOS 上登录超级赞?'), findsOneWidget);
      expect(find.text('123.45.*.*'), findsOneWidget);
      expect(find.text('和这台手机是同一个网络'), findsOneWidget);
      // 按手机的本地时间显示(测试机在哪个时区都对)
      final t = DateTime.parse('2026-09-14T03:05:00+00:00').toLocal();
      expect(find.textContaining('${t.month} 月 ${t.day} 日'), findsOneWidget);
      expect(find.textContaining('如果不是你本人正在电脑前操作,请点取消'), findsOneWidget);
    });

    testWidgets('不是同一个网络就不写这一行;一键登录多说一句', (tester) async {
      await pumpConfirm(tester, request(mode: 'oneclick', sameNetwork: false));
      expect(find.text('和这台手机是同一个网络'), findsNothing);
      expect(find.textContaining('之前扫码登录过你的账号'), findsOneWidget);
    });

    testWidgets('点登录:调 confirm,关页', (tester) async {
      await pumpConfirm(tester, request());
      await tester.tap(find.text('登录'));
      await tester.pumpAndSettle();
      expect(server.where('POST', '/auth/qr/sessions/$_sid/confirm'), hasLength(1));
      expect(server.where('POST', '/auth/qr/sessions/$_sid/cancel'), isEmpty);
      expect(find.byType(QrConfirmPage), findsNothing);
      expect(result, isTrue);
    });

    testWidgets('点取消:调 cancel', (tester) async {
      await pumpConfirm(tester, request());
      await tester.tap(find.text('取消'));
      await tester.pumpAndSettle();
      expect(server.where('POST', '/auth/qr/sessions/$_sid/cancel'), hasLength(1));
      expect(server.where('POST', '/auth/qr/sessions/$_sid/confirm'), isEmpty);
      expect(result, isFalse);
    });

    testWidgets('什么都没选就返回:当作取消,电脑那边不用干等', (tester) async {
      await pumpConfirm(tester, request());
      await tester.pageBack();
      await tester.pumpAndSettle();
      expect(server.where('POST', '/auth/qr/sessions/$_sid/cancel'), hasLength(1));
    });
  });

  group('一键登录的确认请求(手机上)', () {
    testWidgets('收到事件、回到前台:查待确认,有就弹', (tester) async {
      SharedPreferences.setMockInitialValues({});
      final server = FakeServer()..pending = [request(mode: 'oneclick')];
      final api = server.api();
      await api.adoptQrLogin(confirmed());
      final shown = <Map<String, dynamic>>[];
      final events = StreamController<({String type, Map<String, dynamic> data})>.broadcast();
      final w = QrLoginWatcher.instance
        ..presenter = ((r) async {
          shown.add(r);
        })
        ..start(api, events.stream);
      await settle(tester);
      expect(shown, hasLength(1), reason: '一启动(从推送点进来)就查一次');
      expect(shown.single['device'], 'Chrome · macOS');

      events.add((type: 'qr_login', data: {'sid': _sid}));
      await settle(tester);
      expect(shown, hasLength(2));

      w.didChangeAppLifecycleState(AppLifecycleState.resumed);
      await settle(tester);
      expect(shown, hasLength(3));

      server.pending = [];
      events.add((type: 'qr_login', data: {'sid': _sid}));
      await settle(tester);
      expect(shown, hasLength(3), reason: '以查到的为准:事件是补齐来的旧事件时,不该弹');
      w
        ..presenter = null
        ..stop();
      await events.close();
    });

    test('token 里的设备号:认得出「被移除的是不是我」', () {
      String part(Map<String, dynamic> m) =>
          base64Url.encode(utf8.encode(jsonEncode(m))).replaceAll('=', '');
      expect(loginDeviceOfToken('h.${part({'sub': '7', 'ld': 5})}.s'), 5);
      expect(loginDeviceOfToken('h.${part({'sub': '7'})}.s'), isNull);
      expect(loginDeviceOfToken('坏的'), isNull);
      expect(loginDeviceOfToken(null), isNull);
    });
  });

  testWidgets('已登录的网页和电脑:列表、移除', (tester) async {
    SharedPreferences.setMockInitialValues({});
    final server = FakeServer()
      ..devices = [
        {
          'id': 5,
          'client': 'web',
          'device': 'Chrome · macOS',
          'ip': '123.45.*.*',
          'created_at': '2026-09-01T03:05:00+00:00',
          'last_used_at': '2026-09-14T03:05:00+00:00',
          'current': false,
        }
      ];
    await tester.pumpWidget(MaterialApp(
        theme: superZTheme(Brightness.light),
        home: LoginDevicesPage(api: server.api())));
    await tester.pumpAndSettle();
    expect(find.text('Chrome · macOS'), findsOneWidget);
    expect(find.textContaining('IP 123.45.*.*'), findsOneWidget);
    expect(find.textContaining('30 天没用过的会自动失效'), findsOneWidget);

    await tester.tap(find.text('移除'));
    await tester.pumpAndSettle();
    expect(find.text('移除「Chrome · macOS」?'), findsOneWidget);
    await tester.tap(find.widgetWithText(TextButton, '移除').last);
    await tester.pumpAndSettle();
    expect(server.where('DELETE', '/auth/login-devices/5'), hasLength(1));
    expect(find.text('还没有用扫码登录过网页版或电脑版'), findsOneWidget);
  });
}
