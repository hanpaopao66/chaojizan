import 'dart:convert';
import 'dart:io';

import 'package:crypto/crypto.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:package_info_plus/package_info_plus.dart';
import 'package:path_provider_platform_interface/path_provider_platform_interface.dart';
import 'package:plugin_platform_interface/plugin_platform_interface.dart';
import 'package:superz_shared/superz_shared.dart';

/// 应用内自动更新(`update_checker.dart`)。
///
/// ## 守的是什么
///
/// **「拿不到包」和「拿到了但现在装不了」是两件事,退路不一样。**
///
/// 2026-09-17 用户报的:下载期间熄屏,包下完了,却跳去浏览器重下一遍。
/// 成因是 Android 10 起**后台不许 startActivity**,而熄屏时 App 就在后台 ——
/// 拉安装界面这一下失败,而那个 catch 不区分两种失败,一律跳浏览器。
/// 于是一个已经下好、已经校验通过的 57MB 包被直接扔掉。
///
/// 这条路径**此前一条测试都没有**(`ApkInstaller.supported` 里那个
/// `Platform.isAndroid` 让它在测试进程里恒假,任何用例都只能走到「跳浏览器」)。
void main() {
  late Directory tmp;
  late List<String> launched;      // 被打开的外部链接(= 跳了浏览器)
  late List<String> installed;     // 被交给系统安装器的路径
  late int apkHits;                // APK 被下载了几次
  late String apkSha;
  late bool installThrows;         // 模拟「熄屏,拉不起安装界面」
  late bool downloadFails;         // 模拟下载本身出错
  late http.Client client;

  final apkBytes = Uint8List.fromList(List.generate(4096, (i) => i % 256));

  setUp(() async {
    tmp = await Directory.systemTemp.createTemp('sz_update_test');
    launched = [];
    installed = [];
    apkHits = 0;
    installThrows = false;
    apkSha = sha256.convert(apkBytes).toString();

    PackageInfo.setMockInitialValues(
        appName: 'user_app', packageName: 'com.chaojizan.user',
        version: '0.23.0', buildNumber: '2066', buildSignature: '');
    ApiClient.resetAppBuildForTest();

    downloadFails = false;
    // **必须用 MockClient**:flutter_test 掐掉了真实 HTTP(所有请求回 400),
    // 起本地服务器那条路在 widget test 里走不通
    client = MockClient((req) async {
      if (req.url.path == '/app/latest') {
        return http.Response(
            jsonEncode({
              'build': 2067, 'version': '0.24.0', 'notes': '新版',
              'url': 'https://dl.example.test/chaojizan-user-arm64.apk',
              'sha256': apkSha, 'force': false,
            }),
            200,
            headers: {'content-type': 'application/json; charset=utf-8'});
      }
      return http.Response('', 404);
    });

    // **换 platform interface,别去猜 channel 的方法名**:
    // getExternalStorageDirectory 底下走的不是一个简单的「回一个字符串」
    PathProviderPlatform.instance = _FakePathProvider(tmp.path);

    final m = TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger;
    // 模拟系统的下载队列(DownloadManager)。**这是生产走的那条路** ——
    // 「排队」那一下就把文件写出来,和真的下完了一样
    m.setMockMethodCallHandler(
        const MethodChannel('superz/apk_installer'), (call) async {
      switch (call.method) {
        case 'canInstall':
          return true;

        case 'download':
          apkHits++;
          if (!downloadFails) {
            final dir = Directory('${tmp.path}/apk');
            dir.createSync(recursive: true);
            File('${dir.path}/${call.arguments['fileName']}')
                .writeAsBytesSync(apkBytes);
          }
          return 7;

        case 'downloadStatus':
          return downloadFails
              ? {'status': 'failed', 'soFar': 0, 'total': 0, 'reason': 1004}
              : {
                  'status': 'done',
                  'soFar': apkBytes.length,
                  'total': apkBytes.length,
                  'reason': 0,
                };

        case 'cancelDownload':
          return true;

        case 'install':
          if (installThrows) {
            // 后台起 Activity 被系统挡下来时,原生侧回的就是这个
            throw PlatformException(
                code: 'install_failed', message: '拉起安装器失败');
          }
          installed.add(call.arguments['path'] as String);
          return true;
      }
      return null;
    });
    m.setMockMethodCallHandler(
        const MethodChannel('plugins.flutter.io/url_launcher'), (call) async {
      if (call.method == 'launch') {
        launched.add(call.arguments['url'] as String);
        return true;
      }
      return call.method == 'canLaunch' ? true : null;
    });
  });

  tearDown(() async {
    if (tmp.existsSync()) tmp.deleteSync(recursive: true);
  });

  /// `debugDefaultTargetPlatformOverride` **必须在测试体内部还原** ——
  /// 放 tearDown 里太晚:flutter_test 在测试体结束那一刻就查
  /// 「foundation 的 debug 变量有没有被改过」,查完才轮到 tearDown。
  void android(String name, Future<void> Function(WidgetTester) body) {
    testWidgets(name, (t) async {
      debugDefaultTargetPlatformOverride = TargetPlatform.android;
      try {
        await body(t);
      } finally {
        debugDefaultTargetPlatformOverride = null;
      }
    });
  }

  Future<void> open(WidgetTester t) async {
    await t.pumpWidget(MaterialApp(
      home: Builder(builder: (ctx) {
        return TextButton(
            onPressed: () => checkForUpdate(ctx,
                baseUrl: 'https://api.example.test', app: 'user',
                client: client),
            child: const Text('查更新'));
      }),
    ));
    await t.tap(find.text('查更新'));
    await t.pumpAndSettle();
  }

  /// 点「立即更新 / 立即安装」并等它真的跑完。
  ///
  /// **必须 `runAsync`**:下载那一步是真的文件读写,而 widget test 默认跑在
  /// 假时钟上 —— 不放进 runAsync 的话请求发出去了、盘却永远写不完,
  /// `_download()` 不返回,后面的断言全看不到东西(第一版就栽在这儿)。
  Future<void> tapUpdate(WidgetTester t) async {
    // **点击本身也要在 runAsync 里**:下载那一步是真的文件读写,而
    // widget test 默认跑在假时钟上。在 runAsync 外面点的话,处理器启动的
    // future 链留在假时区里 —— 请求发得出去,盘却永远写不完,
    // `_download()` 不返回,后面的断言什么都看不到。
    await t.runAsync(() async {
      // 点**按钮**,别按文字找:提示语里也有「立即安装」四个字,
      // 用 textContaining 会同时匹配到那一句,tap 不知道该点哪个
      await t.tap(find.byType(FilledButton));
      await Future<void>.delayed(const Duration(milliseconds: 300));
    });
    await t.pump();
  }

  android('顺利时:下一次、装一次,不碰浏览器', (t) async {
    await open(t);
    expect(find.textContaining('0.24.0'), findsOneWidget);
    await tapUpdate(t);
    expect(apkHits, 1);
    expect(installed, hasLength(1));
    expect(launched, isEmpty, reason: '应用内装得上就不该跳浏览器');
  });

  android('**熄屏那一下**:包下好了但装不起来,不许跳浏览器', (t) async {
    installThrows = true;
    await open(t);
    await tapUpdate(t);

    expect(apkHits, 1, reason: '包是下完了的');
    expect(launched, isEmpty,
        reason: '包已经下好、也校验过了,跳浏览器等于让人把同一个包再下一遍 ——'
            '这正是 2026-09-17 用户报的那个');
    expect(find.textContaining('已经下好了'), findsOneWidget,
        reason: '要告诉他包在手里、只是现在装不了,而不是让他以为下载失败了');
  });

  android('装不上之后再点一次:直接装,不重新下载', (t) async {
    installThrows = true;
    await open(t);
    await tapUpdate(t);
    expect(apkHits, 1);

    installThrows = false;          // 回到前台了
    await tapUpdate(t);
    expect(apkHits, 1, reason: '**不许再下一遍** —— 包还在手里,哈希也对得上');
    expect(installed, hasLength(1), reason: '这一次该装上了');
    expect(launched, isEmpty);
  });

  android('按钮在包下好之后改说「立即安装」', (t) async {
    installThrows = true;
    await open(t);
    expect(find.text('立即更新'), findsOneWidget);
    await tapUpdate(t);
    expect(find.text('立即安装'), findsOneWidget,
        reason: '还写「立即更新」的话,人会以为点下去又要下一遍');
  });

  android('回到前台自动把安装器拉起来,不用他自己想起来再点', (t) async {
    installThrows = true;
    await open(t);
    await tapUpdate(t);
    expect(installed, isEmpty);

    installThrows = false;
    await t.runAsync(() async {
      t.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
      await Future<void>.delayed(const Duration(milliseconds: 300));
    });
    await t.pump();
    expect(installed, hasLength(1), reason: '亮屏回到前台正是能拉起安装界面的时候');
    expect(apkHits, 1, reason: '自动续上那一下也不该重新下载');
  });

  android('**下载真的失败时**才跳浏览器', (t) async {
    downloadFails = true;              // 系统那条下载报失败
    await open(t);
    await tapUpdate(t);
    expect(launched, hasLength(1),
        reason: '手里什么都没有,这时候退回浏览器是对的');
    expect(installed, isEmpty);
  });

  android('校验不过时跳浏览器,而且把那个包删掉', (t) async {
    apkSha = 'f' * 64;                 // 和真实内容对不上
    await open(t);
    await tapUpdate(t);
    expect(installed, isEmpty, reason: '校验不过的包绝不能交给安装器');
    expect(launched, hasLength(1));
    final left = Directory('${tmp.path}/apk')
        .listSync()
        .where((f) => f.path.endsWith('.apk'));
    expect(left, isEmpty, reason: '校验不过的残骸要删掉,别留在用户手机上');
  });
}

/// 只答「外部存储目录」这一问,其余一律 null —— 用例里用不到。
class _FakePathProvider extends PathProviderPlatform
    with MockPlatformInterfaceMixin {
  _FakePathProvider(this.dir);

  final String dir;

  @override
  Future<String?> getExternalStoragePath() async => dir;

  @override
  Future<String?> getApplicationDocumentsPath() async => dir;

  @override
  Future<String?> getTemporaryPath() async => dir;

  @override
  Future<String?> getApplicationSupportPath() async => dir;
}
