/// 站内链接的分发(DEV-PROMPTS-41 §5.1):音乐、论坛的链接由模块自己注册处理函数,
/// 聊天不反向依赖它们 —— 加一个新模块不用改 links.dart,关掉一个模块也不会留下打不开的死链接。
library;

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:package_info_plus/package_info_plus.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:user_app/chat/links.dart';

void main() {
  setUpAll(() => PackageInfo.setMockInitialValues(
      appName: 'user_app', packageName: 'com.superz.user', version: '0.1.0', buildNumber: '1', buildSignature: ''));
  setUp(() {
    SharedPreferences.setMockInitialValues({});
    clearAppLinkHandlers();
  });
  tearDown(clearAppLinkHandlers);

  /// 拿一个真的 BuildContext 去调 openAppLink
  Future<bool> open(WidgetTester tester, String url) async {
    late bool result;
    await tester.pumpWidget(MaterialApp(
      home: Builder(builder: (ctx) {
        return TextButton(
          onPressed: () async => result = await openAppLink(ctx, Uri.parse(url)),
          child: const Text('go'),
        );
      }),
    ));
    await tester.tap(find.text('go'));
    await tester.pumpAndSettle();
    return result;
  }

  testWidgets('注册过的模块认自己的链接', (tester) async {
    final seen = <String>[];
    registerAppLinkHandler((ctx, uri) async {
      if (uri.pathSegments.isEmpty || uri.pathSegments.first != 'music') return false;
      seen.add(uri.path);
      return true;
    });

    expect(await open(tester, 'https://chaojizan.cc/music/t/mt1234567890'), isTrue);
    expect(seen, ['/music/t/mt1234567890']);
  });

  testWidgets('没人认的链接照旧返回 false(调用方去问要不要用浏览器打开)', (tester) async {
    registerAppLinkHandler((ctx, uri) async => false);
    expect(await open(tester, 'https://chaojizan.cc/forum/p/fp1234567890'), isFalse);
  });

  testWidgets('别人家的域名一律不认,注册的处理函数也不会被问到', (tester) async {
    var asked = false;
    registerAppLinkHandler((ctx, uri) async {
      asked = true;
      return true;
    });
    expect(await open(tester, 'https://chaojizan.cc.evil.example/music/t/mt1234567890'), isFalse);
    expect(asked, isFalse);
  });

  testWidgets('同一个函数注册两次只算一次', (tester) async {
    var calls = 0;
    Future<bool> handler(BuildContext ctx, Uri uri) async {
      calls++;
      return true;
    }

    registerAppLinkHandler(handler);
    registerAppLinkHandler(handler);
    expect(await open(tester, 'https://chaojizan.cc/music/t/mt1234567890'), isTrue);
    expect(calls, 1);
  });
}
