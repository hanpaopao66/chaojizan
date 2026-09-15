import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:superz_shared/superz_shared.dart';
import 'package:user_app/miniapp/bridge.dart';
import 'package:user_app/miniapp/controller.dart';
import 'package:user_app/miniapp/theme.dart';

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

  group('Telegram 兼容(协议 2.1)', () {
    test('宿主下发 Telegram 的 15 个主题色键,外加 line_color;亮暗两套都齐', () {
      expect(kTelegramThemeKeys.length, 15);
      for (final (sz, b) in [(SzColors.light, Brightness.light), (SzColors.dark, Brightness.dark)]) {
        final t = miniAppThemeParams(sz, b);
        for (final k in kTelegramThemeKeys) {
          expect(t[k], matches(RegExp(r'^#[0-9A-F]{6}$')), reason: '$b 缺 $k');
        }
        expect(t['line_color'], isNotNull, reason: 'line_color 是超级赞多出来的,保留');
        expect(t.length, 16);
        // 后加的 6 个键和 SDK 给老宿主补齐时用的是同一张对应表(packages/miniapp-sdk 的 DERIVED_THEME)
        expect(t['header_bg_color'], t['bg_color']);
        expect(t['bottom_bar_bg_color'], t['secondary_bg_color']);
        expect(t['section_bg_color'], t['secondary_bg_color']);
        expect(t['section_header_text_color'], t['hint_color']);
        expect(t['section_separator_color'], t['line_color']);
        expect(t['subtitle_text_color'], t['hint_color']);
      }
    });

    test('init 报协议 2.1;启动地址片段里的版本换成宿主的,initData 一个字节不动', () async {
      final init = await c.receive({'v': 2, 'type': 'hello', 'sdk': '2.1.0'});
      expect(init!['version'], kBridgeProtocolVersion);
      expect(kBridgeProtocolVersion, '2.1');
      const data = 'szWebAppData=app_id%3Dsz0%26user%3D%257B%2522open_id%2522%257D';
      expect(withHostVersion('https://a.example/v/1/index.html#$data&szWebAppVersion=2.0&szWebAppPlatform=android'),
          'https://a.example/v/1/index.html#$data&szWebAppVersion=2.1&szWebAppPlatform=android');
      expect(withHostVersion('https://a.example/v/1/index.html#$data'),
          'https://a.example/v/1/index.html#$data&szWebAppVersion=2.1');
      expect(withHostVersion('https://a.example/entry'), 'https://a.example/entry', reason: '没有片段的老条目不动');
      expect(c.entryUrl, endsWith('#szWebAppData=x&szWebAppVersion=2.1'));
    });

    test('setBottomBarColor 只收 #RRGGBB,记到控制器上画底栏', () async {
      final bad = await call('setBottomBarColor', {'color': 'bottom_bar_bg_color'});
      expect((bad!['error'] as Map)['code'], BridgeCode.invalidParams, reason: '主题色键由 SDK 换成色值再发');
      final ok = await call('setBottomBarColor', {'color': '#102030'});
      expect(ok!['ok'], isTrue);
      expect(c.bottomBarColor, '#102030');
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

  group('导航逃逸(网页版)', () {
    test('load 之后回了同一个 nonce 的 pong:还是这个小程序', () {
      final w = EscapeWatch();
      final n = w.onLoad();
      expect(w.waiting, isTrue);
      w.onPong(n);
      expect(w.waiting, isFalse);
    });

    test('上一个文档的 pong 顶不了这一个(nonce 每次 load 都换)', () {
      final w = EscapeWatch();
      final first = w.onLoad();
      w.onPong(first);
      final second = w.onLoad(); // 页面跳去了别的站:这一问没人答
      expect(second, isNot(first));
      w.onPong(first);
      expect(w.waiting, isTrue);
    });

    test('答错 nonce、空 nonce 都不算', () {
      final w = EscapeWatch();
      w.onLoad();
      w.onPong('guess');
      w.onPong(null);
      expect(w.waiting, isTrue);
    });
  });
}
