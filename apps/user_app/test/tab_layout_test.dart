import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:package_info_plus/package_info_plus.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:superz_shared/superz_shared.dart';
import 'package:user_app/chat/chat_tab.dart';
import 'package:user_app/main.dart' show superZTheme;
import 'package:user_app/video/models.dart';
import 'package:user_app/video/widgets/cards.dart';
import 'package:user_app/video/widgets/feed.dart';

/// 安卓真机走查(#376)撞到、网页版看不出来的两处排版。
void main() {
  // package_info_plus 在测试环境没有平台通道,不铺好的话请求会挂着一个 2 秒的兜底计时器(同 home_nav_test)
  setUpAll(() => PackageInfo.setMockInitialValues(
      appName: 'user_app', packageName: 'com.superz.user', version: '0.1.0', buildNumber: '1', buildSignature: ''));
  setUp(() => SharedPreferences.setMockInitialValues({}));

  ApiClient fakeApi() => ApiClient(
        baseUrl: 'http://test.local',
        httpClient: MockClient((req) async => http.Response(jsonEncode(<String, dynamic>{}), 200,
            headers: {'content-type': 'application/json; charset=utf-8'})),
      );

  // 「消息」tab 自己画标题栏(外壳不给),标题栏已经让过状态栏;下面的列表原来又按顶部安全区补了一次,
  // 手机上「通知」那一行上面空出一截状态栏高。网页没有状态栏(顶部安全区是 0),所以网页上看不出来
  testWidgets('消息 tab:有状态栏时「通知」和没状态栏时一样紧贴标题栏', (tester) async {
    // 「通知」离标题栏底边多远:有状态栏和没状态栏(网页)应当一样
    Future<double> gapUnderBar(double statusBar) async {
      await tester.pumpWidget(MaterialApp(
        key: ValueKey(statusBar),
        theme: superZTheme(Brightness.light),
        home: Builder(
          builder: (context) => MediaQuery(
            data: MediaQuery.of(context).copyWith(
              padding: EdgeInsets.only(top: statusBar),
              viewPadding: EdgeInsets.only(top: statusBar),
            ),
            // 和 main.dart 的外壳一样:消息 tab 时 Scaffold 没有 appBar,body 拿到的是带顶部安全区的 MediaQuery
            child: Scaffold(body: ChatTab(api: fakeApi())),
          ),
        ),
      ));
      await tester.pump();
      final barBottom = tester.getBottomLeft(find.byType(AppBar)).dy;
      expect(barBottom, greaterThanOrEqualTo(statusBar), reason: '标题栏自己要让开状态栏');
      return tester.getTopLeft(find.text('通知')).dy - barBottom;
    }

    final web = await gapUnderBar(0);
    final phone = await gapUnderBar(40);
    expect(phone, closeTo(web, .5), reason: '列表又按状态栏补了一次:网页 $web,手机 $phone');
  });

  // 视频卡片流原来是写死的宽高比(.86):手机宽度上标题下面空出一大截,换成长辈字号又不够。
  // 现在格子高 = 封面 + 两行标题 + UP 主一行。直接铺一个真的卡片流,量两件事:两行标题放得下、没有多出来的空白
  for (final scale in [1.0, 1.3]) {
    testWidgets('视频卡片流:两行标题刚好放下,UP 主贴底(字号 ×$scale)', (tester) async {
      tester.view.physicalSize = const Size(400, 900);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.reset);
      await tester.pumpWidget(MaterialApp(
        theme: superZTheme(Brightness.light),
        home: Builder(
          builder: (context) => MediaQuery(
            data: MediaQuery.of(context).copyWith(textScaler: TextScaler.linear(scale)),
            child: Scaffold(
              body: VideoFeed(
                load: (page, cursor) async => VPage([
                  VideoCard(
                    vid: 'sv1',
                    title: '楼下面馆探店:牛肉面到底值不值 18 块,老板说汤是熬了一整夜的',
                    uploader: const VPerson(id: 1, name: '用户4543'),
                  ),
                  VideoCard(vid: 'sv2', title: '短标题', uploader: const VPerson(id: 2, name: '用户9805')),
                ]),
              ),
            ),
          ),
        ),
      ));
      await tester.pump();
      expect(tester.takeException(), isNull);
      expect(find.byType(VideoGridCard), findsNWidgets(2));

      final title = tester.renderObject<RenderParagraph>(find.textContaining('楼下面馆'));
      expect(title.didExceedMaxLines, isTrue, reason: '样例标题要长到两行放不下,才量得到两行的高度');
      // 标题占满封面和 UP 主之间;两行字本身多高
      final twoLines = title.getMaxIntrinsicHeight(title.size.width);
      expect(title.size.height, greaterThanOrEqualTo(twoLines - .5), reason: '两行标题被裁掉了');
      expect(title.size.height - twoLines, lessThan(4),
          reason: '标题下面多出 ${title.size.height - twoLines} 的空白(原来写死比例时是 30–60)');
      // 两张卡同一排、一样高,UP 主那一行都贴着卡片底边(下面只有 8 的留白)
      for (final (up, i) in [('用户4543', 0), ('用户9805', 1)]) {
        final cardRect = tester.getRect(find.byType(VideoGridCard).at(i));
        expect(cardRect.bottom - tester.getRect(find.text(up)).bottom, lessThan(14), reason: up);
      }
    });
  }
}
