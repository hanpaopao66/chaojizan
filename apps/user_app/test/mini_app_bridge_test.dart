import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:superz_shared/superz_shared.dart';
import 'package:user_app/mini_app_bridge.dart';

/// 只用来数「initData 接口被叫了几次」。
///
/// 数这个是为了把**权限闸门**和**取数**分开看:桥应该在闸门就把没权限的
/// 挡掉,压根不该走到这里。用真接口(连不上的 127.0.0.1:1)也能凭报错类型
/// 反推,但那要等一次真实的连接失败,测试会依赖网络行为 —— 直接数更稳。
class _CountingApi extends ApiClient {
  _CountingApi() : super(baseUrl: 'http://127.0.0.1:1');

  int initDataCalls = 0;

  @override
  Future<Map<String, dynamic>> miniAppInitData(int appId) async {
    initDataCalls++;
    return {'app_id': appId};
  }
}

/// 小程序桥的**业务层**(#292)。
///
/// ## 为什么单独测这一层
///
/// 手机端和 web 端的传输完全不同(原生 WebView 注入 vs 跨域 iframe
/// postMessage),但**五个方法该返回什么必须一模一样** ——
/// 不然小程序开发者要针对宿主写两套,这个平台就没人接了。
///
/// 传输层各测各的(iframe 那侧靠浏览器的 origin 校验,见
/// mini_app_host_web.dart 的注释);这里测的是两端共用的那一份。
void main() {
  MiniAppInfo app({List<String> perms = const []}) => MiniAppInfo(
        id: 1,
        name: '测试小程序',
        icon: '🧪',
        tagline: '',
        entryUrl: 'https://demo.example.com/',
        allowedOrigins: const ['https://demo.example.com'],
        perms: perms,
      );

  Future<BridgeReply?> call(WidgetTester tester, String method,
      {List<String> perms = const [],
      VoidCallback? onClose,
      VoidCallback? onExpand,
      ApiClient? api}) async {
    BridgeReply? out;
    await tester.pumpWidget(MaterialApp(
      theme: brandTheme(Brightness.light),
      home: Builder(builder: (context) {
        return TextButton(
          onPressed: () async {
            out = await handleBridgeCall(
              context,
              api: api ?? ApiClient(baseUrl: 'http://127.0.0.1:1'),
              app: app(perms: perms),
              method: method,
              onClose: onClose ?? () {},
              onExpand: onExpand ?? () {},
            );
          },
          child: const Text('go'),
        );
      }),
    ));
    await tester.tap(find.text('go'));
    await tester.pumpAndSettle();
    return out;
  }

  testWidgets('ready 直接成功', (t) async {
    expect((await call(t, 'ready'))?.ok, isTrue);
  });

  testWidgets('close 触发宿主动作,且**不应答**', (t) async {
    var closed = false;
    final r = await call(t, 'close', onClose: () => closed = true);
    expect(closed, isTrue, reason: 'close 没有关掉弹层');
    // 弹层都没了,应答给谁都没意义 —— 返回 null 表示不用回
    expect(r, isNull, reason: 'close 不该有应答');
  });

  testWidgets('expand 触发宿主动作并应答', (t) async {
    var expanded = false;
    final r = await call(t, 'expand', onExpand: () => expanded = true);
    expect(expanded, isTrue);
    expect(r?.ok, isTrue);
  });

  testWidgets('themeParams 回的是设计令牌,不是随手写的色值', (t) async {
    final r = await call(t, 'themeParams');
    expect(r?.ok, isTrue);
    final m = r!.data as Map<String, Object?>;
    // 和 brand.dart 的 SzColors.light 对齐 —— 小程序照着这个配色,
    // 主色改了它得跟着改,不能各写各的。
    // 大小写不敏感:toRadixString 出的是小写,而 CSS 两种都认
    expect((m['clay']! as String).toUpperCase(), '#C15F3C');
    expect((m['paper']! as String).toUpperCase(), '#F0EEE6');
    expect((m['ink']! as String).toUpperCase(), '#141413');
    expect(m['brightness'], 'light');
  });

  testWidgets('深色态回深色令牌', (t) async {
    BridgeReply? out;
    await t.pumpWidget(MaterialApp(
      theme: brandTheme(Brightness.dark),
      home: Builder(builder: (context) => TextButton(
        onPressed: () async {
          out = await handleBridgeCall(context,
              api: ApiClient(baseUrl: 'http://127.0.0.1:1'),
              app: app(), method: 'themeParams',
              onClose: () {}, onExpand: () {});
        },
        child: const Text('go'))),
    ));
    await t.tap(find.text('go'));
    await t.pumpAndSettle();
    expect((out!.data as Map)['brightness'], 'dark');
    expect(((out!.data as Map)['clay']! as String).toUpperCase(), '#E08A6B');
  });

  group('getInitData 的权限闸门', () {
    testWidgets('没申请 initData 权限的直接拒绝', (t) async {
      final r = await call(t, 'getInitData');
      expect(r?.ok, isFalse);
      expect(r!.data.toString(), contains('未申请 initData 权限'));
    });

    testWidgets('没权限时根本不会去请求接口,在闸门就拒了', (t) async {
      final api = _CountingApi();
      final r = await call(t, 'getInitData', api: api);
      expect(r!.data.toString(), contains('权限'),
          reason: '应该在权限那一关就拒绝,而不是先去请求接口');
      expect(api.initDataCalls, 0, reason: '没权限却已经去取数了');
    });

    testWidgets('权限是**每次调用都查**,不是打开时查一次', (t) async {
      // 清单可以在服务端随时改(下架、撤权限),不该等下次打开才生效。
      //
      // 只调一次是测不出这件事的 —— 桥就算把第一次的结论记下来永不复查,
      // 单次调用的结果也一模一样。必须调两次、中间把权限撤掉。
      final api = _CountingApi();

      // 第一次:有权限,正常放行并取数
      final first =
          await call(t, 'getInitData', perms: const ['initData'], api: api);
      expect(first?.ok, isTrue, reason: '有权限却被拒了');
      expect(api.initDataCalls, 1);

      // 第二次:权限被撤(服务端下了这个权限),必须当场拒绝 ——
      // 不能拿第一次查到的结论接着用
      final second = await call(t, 'getInitData', perms: const [], api: api);
      expect(second?.ok, isFalse, reason: '权限撤了还放行 —— 说明权限被缓存住了,不是每次都查');
      expect(second!.data.toString(), contains('未申请 initData 权限'));
      expect(api.initDataCalls, 1, reason: '撤权之后又去取了一次数 —— 闸门没拦住');
    });

    testWidgets('反过来也要跟上:先被拒,补了权限就该立刻能用', (t) async {
      // 缓存"拒绝"同样是 bug:小程序刚补申请下来的权限,
      // 不该等用户关掉重开才生效
      final api = _CountingApi();
      expect((await call(t, 'getInitData', api: api))?.ok, isFalse);
      final after =
          await call(t, 'getInitData', perms: const ['initData'], api: api);
      expect(after?.ok, isTrue, reason: '补了权限还被拒 —— 拒绝结论被缓存住了');
      expect(api.initDataCalls, 1);
    });
  });

  testWidgets('未知方法明确拒绝,不静默', (t) async {
    final r = await call(t, 'evalJavascript');
    expect(r?.ok, isFalse);
    expect(r!.data.toString(), contains('未知方法'));
  });
}
