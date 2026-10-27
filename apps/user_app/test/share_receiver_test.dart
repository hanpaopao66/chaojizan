import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:user_app/share_receiver.dart';

/// 系统分享(ACTION_SEND)收进来的解析与冷启动取件。
///
/// 原生 intent 那一段没法在 Dart 测试里跑,但「原生 map → 内容」的规则
/// (只有字、只有图、空分享)和「冷启动去取」这条链路可以锁住 ——
/// 改坏了不至于要装到手机上看分享面板里有没有超级赞才发现。
void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  const channel = MethodChannel('com.chaojizan.user/share');

  tearDown(() {
    ShareReceiver.instance.pending.value = null;
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(channel, null);
  });

  group('解析原生分享', () {
    test('只有文字', () {
      final s = IncomingShare.fromMap({'text': '看看这个', 'files': <String>[]});
      expect(s, isNotNull);
      expect(s!.text, '看看这个');
      expect(s.files, isEmpty);
    });

    test('只有图片', () {
      final s = IncomingShare.fromMap({
        'text': null,
        'files': ['/data/cache/shared/a.jpg'],
      });
      expect(s, isNotNull);
      expect(s!.text, '');
      expect(s.files, ['/data/cache/shared/a.jpg']);
    });

    test('图文一起', () {
      final s = IncomingShare.fromMap({
        'text': '给你看',
        'files': ['/data/cache/shared/a.jpg', '/data/cache/shared/b.png'],
      });
      expect(s!.text, '给你看');
      expect(s.files, hasLength(2));
    });

    test('空分享和脏数据不产生空动作', () {
      expect(IncomingShare.fromMap(null), isNull);
      expect(IncomingShare.fromMap('不是 map'), isNull);
      expect(IncomingShare.fromMap({'text': '   ', 'files': <String>[]}), isNull);
      expect(IncomingShare.fromMap({'text': '', 'files': ['']}), isNull);
    });
  });

  testWidgets('冷启动:原生留着的分享在 init 时取回来', (t) async {
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(channel, (call) async {
      if (call.method == 'takeInitialShare') {
        return {'text': '从浏览器分享的链接', 'files': <String>[]};
      }
      return null;
    });
    await ShareReceiver.instance.init();
    expect(ShareReceiver.instance.pending.value?.text, '从浏览器分享的链接');
  });
}
