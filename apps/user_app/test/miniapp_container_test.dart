import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:superz_shared/superz_shared.dart';
import 'package:user_app/miniapp/container.dart';
import 'package:user_app/miniapp/controller.dart';

/// 小程序容器的那一圈宿主界面(2026-09-15:全屏放开给所有应用、外框向 Telegram 靠)。
///
/// 网页(WebView / iframe)在测试环境里起不来,用 [MiniAppFrame.viewBuilder] 换成一块铺满的假页面 ——
/// 它和真网页一样占满内容区,点到它就记一笔。这里守的是宿主那一圈:
///
/// - 全屏进出:应用从弹层铺满整屏、顶栏收成胶囊、再回到弹层原来的大小;小游戏打开就是全屏;
/// - 胶囊盖在页面**上面**:页面铺满整屏也挡不住它,点 `···` 能看到「由 XX 提供」和认证标记;
/// - 安全区照实报、内容安全区把胶囊那一截算进去;
/// - 返回键在全屏时照原来的规则。
const _appid = 'sz0123456789abcdef';

Map<String, dynamic> _card({String kind = 'app'}) => {
      'appid': _appid,
      'id': 3,
      'name': '记事本',
      'icon': '记',
      'kind': kind,
      'hosting': 'hosted',
      'developer': {'name': '某某科技', 'kind': 'company', 'verified': true, 'label': '企业 · 已认证'},
    };

ApiClient _api({String kind = 'app'}) => ApiClient(
      baseUrl: 'http://test.local',
      httpClient: MockClient((req) async {
        final path = req.url.path;
        Object body = const {};
        if (path == '/mini-apps/$_appid/launch') {
          body = {
            'url': 'https://$_appid.mp.example/v/7/index.html#szWebAppData=x&szWebAppVersion=2.0',
            'init_data': 'x',
            'app': {
              ..._card(kind: kind),
              'allowed_origins': ['https://$_appid.mp.example'],
              'capabilities': ['initData', 'storage', 'popup', 'fullscreen', 'orientation'],
              'bridge': 2,
              'orientation': 'portrait',
              'background_color': '#F0EEE6',
            },
          };
        } else if (path == '/mini-apps/$_appid') {
          body = {..._card(kind: kind), 'me': {'starred': false, 'tester': false, 'profile_granted': false}};
        } else if (path == '/mini-apps/$_appid/status') {
          body = {'blocked': false};
        }
        return http.Response(jsonEncode(body), 200, headers: {'content-type': 'application/json'});
      }),
    );

/// 一个打开着的小程序。页面是铺满内容区的假页面:点到它 [pageTaps] 加一
class _Opened {
  MiniAppController? c;
  final sent = <Map<String, dynamic>>[];
  int pageTaps = 0;
  int _id = 0;

  Future<Map<String, dynamic>?> call(WidgetTester t, String method, [Map<String, dynamic> params = const {}]) async {
    final r = await c!.receive({
      'v': 2, 'type': 'call', 'id': ++_id, 'method': method, 'params': params, 'token': c!.dispatcher.token,
    });
    await t.pumpAndSettle();
    return r;
  }

  List<String> events() => [for (final m in sent) if (m['type'] == 'event') '${m['name']}'];
}

Future<_Opened> _open(WidgetTester t, {String kind = 'app', Size size = const Size(390, 844)}) async {
  SharedPreferences.setMockInitialValues({});
  t.view.physicalSize = size * 3;
  t.view.devicePixelRatio = 3;
  t.view.padding = const FakeViewPadding(top: 24 * 3, bottom: 16 * 3);
  addTearDown(t.view.reset);
  final o = _Opened();
  final api = _api(kind: kind);
  final card = MiniAppCard.fromJson(_card(kind: kind));
  await t.pumpWidget(MaterialApp(
    theme: brandTheme(Brightness.light),
    home: Builder(
      builder: (context) => Scaffold(
        body: Center(
          child: FilledButton(
            onPressed: () => Navigator.of(context).push(miniAppRoute(
                context,
                MiniAppFrame(
                  api: api,
                  card: card,
                  fullscreen: card.isGame,
                  viewBuilder: (_, c) {
                    o.c = c;
                    c.send ??= o.sent.add;
                    return GestureDetector(
                      behavior: HitTestBehavior.opaque,
                      onTap: () => o.pageTaps++,
                      child: const ColoredBox(key: Key('page'), color: Color(0xFF3366AA), child: SizedBox.expand()),
                    );
                  },
                ),
                game: card.isGame)),
            child: const Text('打开'),
          ),
        ),
      ),
    ),
  ));
  await t.tap(find.text('打开'));
  // 启动页上的转圈是无限动画,ready 之前不能 pumpAndSettle:一帧一帧推到启动应答回来
  for (var i = 0; i < 30 && o.c == null; i++) {
    await t.pump(const Duration(milliseconds: 100));
  }
  await t.pump(const Duration(milliseconds: 400));
  expect(o.c, isNotNull, reason: '启动应答回来后应该建出页面');
  await o.call(t, 'ready');
  return o;
}

Rect _panel(WidgetTester t) => t.getRect(find.byKey(const ValueKey('miniapp-panel')));

Finder get _capsule => find.byType(MiniAppCapsule);

Finder _inCapsule(String tooltip) => find.descendant(of: _capsule, matching: find.byTooltip(tooltip));

void main() {
  testWidgets('应用:requestFullscreen → 铺满整屏、顶栏收成右上角胶囊;exitFullscreen 回到弹层原来的大小', (t) async {
    final o = await _open(t);
    final sheet = _panel(t);
    expect(sheet.top, greaterThan(100), reason: '打开时是半屏弹层');
    expect(_capsule, findsNothing);
    expect(o.c!.contentSafeArea['top'], 0);

    await o.call(t, 'requestFullscreen');
    expect(_panel(t), const Rect.fromLTWH(0, 0, 390, 844), reason: '全屏铺满整屏');
    expect(_capsule, findsOneWidget);
    expect(o.events(), contains('fullscreenChanged'));
    expect(o.c!.fullscreen, isTrue);
    // 安全区照实报;内容安全区把胶囊那一截算进去(状态栏 24 + 胶囊离顶 8 + 高 40)
    expect(o.c!.safeArea['top'], 24);
    expect(o.c!.contentSafeArea['top'], 24 + kCapsuleTop + kCapsuleHeight);
    final cap = t.getRect(_capsule);
    expect(cap.bottom, lessThanOrEqualTo(o.c!.contentSafeArea['top']!), reason: '胶囊整个落在内容安全区以上');
    expect(cap.right, lessThanOrEqualTo(390));

    await o.call(t, 'exitFullscreen');
    expect(_panel(t), sheet, reason: '退出全屏回到弹层原来的大小');
    expect(_capsule, findsNothing);
    expect(o.c!.fullscreen, isFalse);
    expect(o.c!.contentSafeArea['top'], 0);
    expect(o.events().where((e) => e == 'fullscreenChanged').length, 2);
  });

  testWidgets('胶囊盖在页面上面:页面铺满整屏也挡不住;点 ··· 出菜单,看得到「由 XX 提供」和认证标记', (t) async {
    final o = await _open(t);
    await o.call(t, 'requestFullscreen');
    await t.tapAt(const Offset(100, 400));
    expect(o.pageTaps, 1, reason: '胶囊以外的地方是页面的');
    await t.tap(_inCapsule('更多'));
    await t.pumpAndSettle();
    expect(o.pageTaps, 1, reason: '点在胶囊上的不会漏给页面');
    final menu = find.byType(BottomSheet);
    expect(menu, findsOneWidget);
    expect(find.descendant(of: menu, matching: find.text('由 某某科技 提供 · 企业 · 已认证')), findsOneWidget);
    expect(find.descendant(of: menu, matching: find.text('投诉')), findsOneWidget);
  });

  testWidgets('胶囊的 × 按关闭规则走:开了关闭确认的先问一句', (t) async {
    final o = await _open(t);
    await o.call(t, 'requestFullscreen');
    await o.call(t, 'setClosingConfirmation', {'enabled': true});
    await t.tap(_inCapsule('关闭'));
    await t.pumpAndSettle();
    expect(find.text('确定关闭?'), findsOneWidget);
    await t.tap(find.text('再等等'));
    await t.pumpAndSettle();
    expect(find.byType(MiniAppFrame), findsOneWidget);
    await t.tap(_inCapsule('关闭'));
    await t.pumpAndSettle();
    await t.tap(find.widgetWithText(TextButton, '关闭'));
    await t.pumpAndSettle();
    expect(find.byType(MiniAppFrame), findsNothing);
  });

  testWidgets('返回键在全屏时照原来的规则:页面显示了 BackButton 交给页面,没显示就关', (t) async {
    final o = await _open(t);
    await o.call(t, 'requestFullscreen');
    await o.call(t, 'backButton', {'is_visible': true});
    await t.binding.handlePopRoute();
    await t.pumpAndSettle();
    expect(o.events().last, 'backButtonClicked');
    expect(find.byType(MiniAppFrame), findsOneWidget);
    await o.call(t, 'backButton', {'is_visible': false});
    await t.binding.handlePopRoute();
    await t.pumpAndSettle();
    expect(find.byType(MiniAppFrame), findsNothing);
  });

  testWidgets('小游戏:打开就是全屏只留胶囊;exitFullscreen 露出顶栏但仍铺满', (t) async {
    final o = await _open(t, kind: 'game');
    expect(_panel(t), const Rect.fromLTWH(0, 0, 390, 844));
    expect(_capsule, findsOneWidget);
    expect(o.c!.fullscreen, isTrue, reason: 'init 里 isFullscreen 要是 true');
    await o.call(t, 'requestFullscreen');
    expect(o.events().last, 'fullscreenFailed', reason: '已经是全屏:ALREADY_FULLSCREEN');
    await o.call(t, 'exitFullscreen');
    expect(_capsule, findsNothing);
    expect(_panel(t), const Rect.fromLTWH(0, 0, 390, 844), reason: '小游戏退出全屏不变成弹层');
    expect(o.c!.safeArea['top'], 0, reason: '顶栏盖在网页上面,网页的顶不再挨着状态栏');
  });

  testWidgets('平板宽度:应用是居中的面板;全屏铺满整个窗口', (t) async {
    final o = await _open(t, size: const Size(768, 1024));
    final p = _panel(t);
    expect(p.left, greaterThan(0));
    expect(p.center.dx, closeTo(384, 0.5));
    await o.call(t, 'requestFullscreen');
    expect(_panel(t), const Rect.fromLTWH(0, 0, 768, 1024));
    expect(_capsule, findsOneWidget);
    await o.call(t, 'exitFullscreen');
    expect(_panel(t), p);
  });

  testWidgets('拖顶栏:半屏 ↔ 全屏;expand() 拉到最高', (t) async {
    final o = await _open(t);
    final before = _panel(t);
    await t.drag(find.byTooltip('更多'), const Offset(0, -300));
    await t.pumpAndSettle();
    expect(_panel(t).top, lessThan(before.top));
    await t.drag(find.byTooltip('更多'), const Offset(0, 600));
    await t.pumpAndSettle();
    expect(_panel(t).height, closeTo((844 - 24) * kMiniAppSheetMin, 1), reason: '往下拖到最低,不会拖没');
    await o.call(t, 'expand');
    expect(_panel(t).height, closeTo((844 - 24) * kMiniAppSheetMax, 1));
    expect(o.c!.expanded, isTrue);
  });
}
