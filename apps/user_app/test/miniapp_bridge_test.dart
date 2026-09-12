import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:superz_shared/superz_shared.dart';
import 'package:user_app/miniapp/bridge.dart';
import 'package:user_app/miniapp/controller.dart';

/// 小程序桥 v2 的分发器与方法表(DEV-PROMPTS-39 #324)。
///
/// 两端(手机 WebView、web iframe)的传输各不相同,但**同一条消息该怎么应答必须一样** ——
/// 这里测的就是两端共用的那一份:令牌、能力当场查、错误码、状态变化。
/// 「iframe 冒充」这一条是整套设计的安全核心:页面里嵌的第三方 iframe 能调到原生通道,
/// 但拿不到只发给主框架的令牌,它的调用必须被**静默丢弃**。
class _FakeUi implements MiniAppUi {
  final calls = <String>[];
  String? popupAnswer = 'ok';
  bool consent = true;
  bool openOk = true;

  @override
  Future<bool> askProfileConsent() async {
    calls.add('consent');
    return consent;
  }

  @override
  void close() => calls.add('close');

  @override
  void expand() => calls.add('expand');

  @override
  void haptic(String type, String? style) => calls.add('haptic:$type:$style');

  @override
  Future<bool> lockOrientation(bool lock) async => true;

  @override
  Future<bool> openExternal(Uri url) async {
    calls.add('open:$url');
    return openOk;
  }

  @override
  Future<bool> setFullscreen(bool on) async => true;

  @override
  Future<bool> share(String text) async {
    calls.add('share:$text');
    return true;
  }

  @override
  Future<String?> showPopup(String? title, String message, List<Map<String, dynamic>> buttons) async {
    calls.add('popup:$message:${buttons.length}');
    return popupAnswer;
  }
}

MiniAppLaunch _launch({List<String> caps = const ['initData', 'storage', 'share', 'haptics', 'popup', 'openLink'],
    String kind = 'app', int bridge = 2}) =>
    MiniAppLaunch.fromJson({
      'url': 'https://sz0123456789abcdef.miniapps.example/v/7/index.html#szWebAppData=x',
      'init_data': 'x',
      'app': {
        'appid': 'sz0123456789abcdef',
        'id': 3,
        'name': '记事本',
        'kind': kind,
        'allowed_origins': ['https://sz0123456789abcdef.miniapps.example'],
        'capabilities': caps,
        'bridge': bridge,
      },
    });

void main() {
  final storageBodies = <String, Object?>{};
  ApiClient api() => ApiClient(
        baseUrl: 'http://test.local',
        httpClient: MockClient((req) async {
          final path = req.url.path;
          if (path.contains('/storage/')) {
            final body = jsonDecode(req.body) as Map<String, dynamic>;
            storageBodies[path] = body;
            if (body['if_rev'] == 9) {
              return http.Response(jsonEncode({'detail': {'code': 4007, 'message': '版本号不符'}}), 409,
                  headers: {'content-type': 'application/json'});
            }
            return http.Response(jsonEncode({'key': body['key'], 'rev': 2}), 200,
                headers: {'content-type': 'application/json'});
          }
          if (path.endsWith('/profile')) {
            return http.Response(jsonEncode({'init_data': 'user=%7B%22nickname%22%3A%22x%22%7D'}), 200,
                headers: {'content-type': 'application/json'});
          }
          return http.Response('{}', 200, headers: {'content-type': 'application/json'});
        }),
      );

  late _FakeUi ui;
  late MiniAppController c;
  final sent = <Map<String, dynamic>>[];

  setUp(() {
    ui = _FakeUi();
    sent.clear();
    c = MiniAppController(api: api(), launch: _launch(), ui: ui, platform: 'android');
    c.send = sent.add;
  });

  Future<Map<String, dynamic>?> call(String method, [Map<String, dynamic> params = const {}, String? token]) =>
      c.receive({'v': 2, 'type': 'call', 'id': 1, 'method': method, 'params': params, 'token': token ?? c.dispatcher.token});

  group('握手与令牌', () {
    test('hello 回 init,带令牌、主题、能力', () async {
      c.themeParams = {'bg_color': '#F0EEE6'};
      final init = await c.receive(jsonEncode({'v': 2, 'type': 'hello', 'sdk': '2.0.0'}));
      expect(init!['type'], 'init');
      expect(init['token'], c.dispatcher.token);
      expect(init['capabilities'], contains('storage'));
      expect((init['app'] as Map)['appid'], 'sz0123456789abcdef');
    });

    test('不带令牌、带错令牌的调用被静默丢弃(挡住页面里嵌的 iframe 冒充)', () async {
      expect(await c.receive({'v': 2, 'type': 'call', 'id': 1, 'method': 'close', 'params': {}}), isNull);
      expect(await call('close', {}, 'forged-token'), isNull);
      expect(ui.calls, isEmpty, reason: '冒充的调用不能有任何副作用');
    });

    test('页面重新加载后换令牌,旧令牌作废', () async {
      final old = c.dispatcher.token;
      c.onPageStarted();
      expect(c.dispatcher.token, isNot(old));
      expect(await call('close', {}, old), isNull);
    });

    test('不是 v2 的消息不理', () async {
      expect(await c.receive({'type': 'call', 'method': 'close'}), isNull);
      expect(await c.receive('not json'), isNull);
    });
  });

  group('能力当场查', () {
    test('没申请到的能力回 4001', () async {
      final r = await call('requestProfile');
      expect(r!['ok'], false);
      expect((r['error'] as Map)['code'], BridgeCode.capabilityNotGranted);
      expect(ui.calls, isEmpty);
    });

    test('全屏只给小游戏', () async {
      final r = await call('requestFullscreen');
      expect((r!['error'] as Map)['code'], BridgeCode.capabilityNotGranted);
    });

    test('能力被收回后下一次调用立刻 4001(不是等下次打开)', () async {
      expect((await call('haptic', {'type': 'impact', 'style': 'light'}))!['ok'], true);
      c.launch = _launch(caps: const ['initData', 'storage']);
      expect(((await call('haptic', {'type': 'impact'}))!['error'] as Map)['code'], BridgeCode.capabilityNotGranted);
    });

    test('宿主不认识的方法回 4003', () async {
      expect(((await call('getLocation'))!['error'] as Map)['code'], BridgeCode.notSupported);
    });
  });

  group('方法', () {
    test('ready 撤掉启动页;主按钮、返回键、关闭确认改状态', () async {
      await call('ready');
      expect(c.ready, isTrue);
      await call('mainButton', {'text': '新建笔记', 'is_visible': true, 'color': '#C15F3C'});
      expect(c.mainButton.visible, isTrue);
      expect(c.mainButton.text, '新建笔记');
      await call('backButton', {'is_visible': true});
      expect(c.backButtonVisible, isTrue);
      await call('setClosingConfirmation', {'enabled': true});
      expect(c.closingConfirmation, isTrue);
      c.clickMain();
      expect(sent.last, {'v': 2, 'type': 'event', 'name': 'mainButtonClicked'});
    });

    test('颜色只收 #RRGGBB', () async {
      final r = await call('setHeaderColor', {'color': 'red'});
      expect((r!['error'] as Map)['code'], BridgeCode.invalidParams);
    });

    test('弹窗最多 3 个按钮;回按下的按钮 id', () async {
      final bad = await call('showPopup', {'message': 'x', 'buttons': [{}, {}, {}, {}]});
      expect((bad!['error'] as Map)['code'], BridgeCode.invalidParams);
      final r = await call('showPopup', {'message': '删除?', 'buttons': [{'id': 'ok', 'type': 'ok'}, {'type': 'cancel'}]});
      expect(r!['data'], {'button_id': 'ok'});
    });

    test('openLink 只收 http(s);用户取消回 4002', () async {
      expect(((await call('openLink', {'url': 'javascript:alert(1)'}))!['error'] as Map)['code'],
          BridgeCode.invalidParams);
      ui.openOk = false;
      expect(((await call('openLink', {'url': 'https://a.example'}))!['error'] as Map)['code'], BridgeCode.userDenied);
    });

    test('云存储透传给服务端;4007 原样回给页面', () async {
      final ok = await call('CloudStorage.setItem', {'key': 'n:1', 'value': 'v', 'if_rev': 1});
      expect(ok!['ok'], true);
      expect(storageBodies['/mini-apps/sz0123456789abcdef/storage/set'], {'key': 'n:1', 'value': 'v', 'if_rev': 1});
      final conflict = await call('CloudStorage.setItem', {'key': 'n:1', 'value': 'v', 'if_rev': 9});
      expect((conflict!['error'] as Map)['code'], BridgeCode.revConflict);
    });

    test('requestProfile:用户拒绝回 4002;同意后回新签的 initData', () async {
      c.launch = _launch(caps: const ['initData', 'profile']);
      ui.consent = false;
      expect(((await call('requestProfile'))!['error'] as Map)['code'], BridgeCode.userDenied);
      ui.consent = true;
      final r = await call('requestProfile');
      expect((r!['data'] as Map)['init_data'], contains('nickname'));
    });

    test('share 默认带上直达链接', () async {
      await call('share', {'text': '看看这个'});
      expect(ui.calls.last, contains('/m/sz0123456789abcdef'));
    });

    test('托管应用调 v1 的 getInitData 回 4003', () async {
      expect(((await call('legacy.getInitData'))!['error'] as Map)['code'], BridgeCode.notSupported);
    });
  });

  group('宿主 → 页面的事件', () {
    test('主题变了才发 themeChanged;视口、安全区同理', () {
      c.updateTheme({'bg_color': '#1B1A17'}, 'dark');
      c.updateTheme({'bg_color': '#1B1A17'}, 'dark');
      expect(sent.where((m) => m['name'] == 'themeChanged').length, 1);
      c.updateViewport(600, stable: true);
      c.updateViewport(600, stable: true);
      expect(sent.where((m) => m['name'] == 'viewportChanged').length, 1);
      c.updateSafeArea({'top': 24, 'bottom': 0, 'left': 0, 'right': 0}, {'top': 0, 'bottom': 0, 'left': 0, 'right': 0});
      expect(sent.where((m) => m['name'] == 'safeAreaChanged').length, 1);
    });
  });

  group('工具', () {
    test('导航白名单按 origin 比,不按前缀', () {
      const allowed = ['https://sz0123456789abcdef.miniapps.example'];
      expect(originAllowed('https://sz0123456789abcdef.miniapps.example/v/7/a.html', allowed), isTrue);
      expect(originAllowed('https://sz0123456789abcdef.miniapps.example.evil.com/', allowed), isFalse);
      expect(originAllowed('http://sz0123456789abcdef.miniapps.example/', allowed), isFalse);
      expect(originAllowed('javascript:alert(1)', allowed), isFalse);
    });

    test('令牌每次不同、够长', () {
      final a = newSessionToken();
      expect(a.length, greaterThanOrEqualTo(21));
      expect(newSessionToken(), isNot(a));
    });
  });
}
