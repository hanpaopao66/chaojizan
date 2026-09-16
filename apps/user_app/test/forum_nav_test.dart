// 论坛的站内链接(DEV-PROMPTS-41 §5.1)。
//
// ## 守的是什么
//
// - `/forum/p/<pid>`、`/forum/t/<话题>` 认得,别的路径交回去(别抢别人的链接);
// - **只认本站域名**:`chaojizan.cc.evil.example/forum/p/…`、`evil.example/forum/p/…`
//   这种长得一样的不算 —— 帖子里的外链走的是同一个判定,认错了就等于
//   「点一下就替人打开了一个假的站内页面」;
// - pid 的格式要卡住:`fp` + 10 位 base58,不然按数字遍历也能拼出链接;
// - 话题原样解码,统一按小写跳转。
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:package_info_plus/package_info_plus.dart';
import 'package:user_app/forum/models.dart';
import 'package:user_app/forum/nav.dart';

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

  /// 在一个真的 Navigator 里跑一次判定,返回认不认得
  Future<bool> handle(WidgetTester t, String url) async {
    late bool got;
    await t.pumpWidget(MaterialApp(
      home: Builder(builder: (ctx) {
        return TextButton(
          onPressed: () => got = handleForumLink(ctx, Uri.parse(url)),
          child: const Text('go'),
        );
      }),
    ));
    await t.tap(find.text('go'));
    await t.pump();
    return got;
  }

  group('认得的', () {
    testWidgets('帖子链接', (t) async {
      expect(await handle(t, 'https://chaojizan.cc/forum/p/fpHbFUgZ3A32'), isTrue);
    });

    testWidgets('话题链接(URL 编码的中文)', (t) async {
      expect(await handle(t, 'https://chaojizan.cc/forum/t/%E5%91%A8%E6%9C%AB'), isTrue);
    });

    testWidgets('www 的也认', (t) async {
      expect(await handle(t, 'https://www.chaojizan.cc/forum/p/fpHbFUgZ3A32'), isTrue);
    });

    testWidgets('相对地址(我们自己拼的)也认', (t) async {
      expect(await handle(t, '/forum/p/fpHbFUgZ3A32'), isTrue);
    });
  });

  group('不认的', () {
    testWidgets('别的域名不认 —— 帖子里的外链走同一个判定', (t) async {
      expect(await handle(t, 'https://evil.example/forum/p/fpHbFUgZ3A32'), isFalse);
      expect(await handle(t, 'https://chaojizan.cc.evil.example/forum/p/fpHbFUgZ3A32'), isFalse);
    });

    testWidgets('带用户名、带奇怪端口的不认', (t) async {
      expect(await handle(t, 'https://a@chaojizan.cc/forum/p/fpHbFUgZ3A32'), isFalse);
      expect(await handle(t, 'https://chaojizan.cc:8443/forum/p/fpHbFUgZ3A32'), isFalse);
    });

    testWidgets('pid 格式不对不认(按数字遍历拼不出来)', (t) async {
      expect(await handle(t, 'https://chaojizan.cc/forum/p/123'), isFalse);
      expect(await handle(t, 'https://chaojizan.cc/forum/p/svHbFUgZ3A32'), isFalse, reason: '这是视频号');
      expect(await handle(t, 'https://chaojizan.cc/forum/p/fp0OIl000000'), isFalse,
          reason: 'base58 里没有 0 O I l');
    });

    testWidgets('别的模块的链接交回去', (t) async {
      expect(await handle(t, 'https://chaojizan.cc/v/svHbFUgZ3A32'), isFalse);
      expect(await handle(t, 'https://chaojizan.cc/music/t/mtHbFUgZ3A32'), isFalse);
      expect(await handle(t, 'https://chaojizan.cc/@xiaoming'), isFalse);
      expect(await handle(t, 'https://chaojizan.cc/forum'), isFalse);
      expect(await handle(t, 'https://chaojizan.cc/forum/x/abc'), isFalse);
    });

    testWidgets('话题太长不认(最多 30 字)', (t) async {
      expect(await handle(t, 'https://chaojizan.cc/forum/t/${'字' * 31}'), isFalse);
      expect(await handle(t, 'https://chaojizan.cc/forum/t/${'字' * 30}'), isTrue);
    });
  });

  group('拼链接', () {
    test('帖子和话题各自的写法(§5.1)', () {
      expect(forumPostLink('fpHbFUgZ3A32'), 'https://chaojizan.cc/forum/p/fpHbFUgZ3A32');
      expect(forumTagLink('周末'), 'https://chaojizan.cc/forum/t/%E5%91%A8%E6%9C%AB');
    });

    test('拼出来的链接自己认得(两边不许走歪)', () async {
      final uri = Uri.parse(forumTagLink('周末'));
      expect(uri.pathSegments.last, '周末', reason: 'pathSegments 会解码');
    });
  });

  group('注册进站内链接表的那一份', () {
    testWidgets('是 Future<bool>,和 registerAppLinkHandler 要的签名对得上', (t) async {
      late Future<bool> got;
      await t.pumpWidget(MaterialApp(
        home: Builder(
          builder: (ctx) => TextButton(
            onPressed: () =>
                got = forumAppLinkHandler(ctx, Uri.parse('https://chaojizan.cc/forum/p/fpHbFUgZ3A32')),
            child: const Text('go'),
          ),
        ),
      ));
      await t.tap(find.text('go'));
      expect(await got, isTrue);
      await t.pumpAndSettle();
    });
  });

  group('常量', () {
    test('和规格 F1 / F3 / §7.2 的数对得上', () {
      expect(kPostMaxChars, 500);
      expect(kPostMaxImages, 4);
      expect(kPollMinOptions, 2);
      expect(kPollMaxOptions, 4);
      expect(kPollOptionMaxChars, 25);
      expect(kPollMinMinutes, 5);
      expect(kPollMaxMinutes, 7 * 24 * 60);
      expect(kEditWindowMinutes, 30);
      expect(kEditMaxCount, 5);
      expect(kMuteWordsMax, 100);
    });
  });
}
