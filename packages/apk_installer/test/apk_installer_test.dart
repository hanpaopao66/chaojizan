import 'package:apk_installer/apk_installer.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';

/// 后台下载那套(`DownloadManager`)的 Dart 侧契约。
///
/// 原生那半边(真的排队、真的下)在这儿测不了,但**两边的约定**要钉住:
/// 传什么参数、状态码怎么翻译、总量未知时进度给什么。这几条错了的表现都是
/// 「一直转圈」或者「明明下完了却不动」——**不报错**,最难查。
void main() {
  // 这一组是纯 `test()`(没有 widget),binding 不会自己起来 ——
  // 不显式初始化,连 mock 通道都挂不上
  TestWidgetsFlutterBinding.ensureInitialized();

  late List<MethodCall> calls;
  late Map<String, dynamic> reply;

  void handler(Future<Object?> Function(MethodCall) h) {
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(
            const MethodChannel('superz/apk_installer'), h);
  }

  setUp(() {
    debugDefaultTargetPlatformOverride = TargetPlatform.android;
    calls = [];
    reply = {};
    handler((c) async {
      calls.add(c);
      if (c.method == 'download') return 42;
      if (c.method == 'downloadStatus') return reply;
      return true;
    });
  });

  tearDown(() {
    debugDefaultTargetPlatformOverride = null;
    handler((c) async => null);
  });

  test('排队时把落地文件名交过去——落点要和 FileProvider 那份 apk/ 目录对上', () async {
    final id = await ApkInstaller.download(
        'https://dl.example.test/x.apk', 'superz-0.24.0.apk',
        title: '超级赞 v0.24.0');
    expect(id, 42);
    expect(calls.single.method, 'download');
    expect(calls.single.arguments, {
      'url': 'https://dl.example.test/x.apk',
      'fileName': 'superz-0.24.0.apk',
      'title': '超级赞 v0.24.0',
    });
  });

  group('状态翻译', () {
    Future<ApkDownloadStatus> st(Map<String, dynamic> m) {
      reply = m;
      return ApkInstaller.downloadStatus(42);
    }

    test('下完了', () async {
      final s = await st({
        'status': 'done', 'soFar': 100, 'total': 100,
        'path': '/x/apk/a.apk', 'reason': 0,
      });
      expect(s.done, isTrue);
      expect(s.failed, isFalse);
      expect(s.path, '/x/apk/a.apk');
    });

    test('失败和「被划掉」都算 failed——调用方据此退回浏览器', () async {
      expect((await st({'status': 'failed', 'reason': 1004})).failed, isTrue);
      // 用户在通知栏把这条下载划掉了,或者系统清了记录
      expect((await st({'status': 'gone'})).failed, isTrue);
    });

    test('在下和暂停都不算完,也不算失败', () async {
      for (final k in ['running', 'paused']) {
        final s = await st({'status': k, 'soFar': 1, 'total': 2});
        expect(s.done, isFalse, reason: k);
        expect(s.failed, isFalse, reason: k);
      }
    });

    test('**服务端没给总长度时进度是 null,不是 0**', () async {
      // DownloadManager 这种情况下 total 回 -1。拿它做除数得到负数进度,
      // 进度条会画满或者画反 —— 要交给不确定进度条
      final s = await st({'status': 'running', 'soFar': 500, 'total': -1});
      expect(s.fraction, isNull);
      expect(s.total, -1);
    });

    test('进度夹在 0–1:服务端报的总长度比实际小也不会溢出', () async {
      final s = await st({'status': 'running', 'soFar': 300, 'total': 100});
      expect(s.fraction, 1.0);
    });

    test('原生回了空也不崩,当成「这条没了」', () async {
      handler((c) async => null);
      final s = await ApkInstaller.downloadStatus(42);
      expect(s.failed, isTrue,
          reason: '查不到就当没了、重新下 —— 不是抛异常把整轮带倒');
    });
  });

  test('非安卓上不许排队——那边根本没有 DownloadManager', () async {
    debugDefaultTargetPlatformOverride = TargetPlatform.iOS;
    expect(() => ApkInstaller.download('https://x/a.apk', 'a.apk'),
        throwsUnsupportedError);
  });

  test('取消下载吞掉原生的异常——取消失败不该顶掉调用方', () async {
    handler((c) async => throw PlatformException(code: 'boom'));
    await ApkInstaller.cancelDownload(42); // 不抛就算过
  });
}
