/// 资料页上的关注(DEV-PROMPTS-41 #377):关注关系全站一张表,视频、动态、音乐是同一份。
///
/// 守的是:资料页读的是 `/social/v1/users/{id}/follow-stats`(不挂任何模块开关)、点一下就写
/// `/social/v1/users/{id}/follow`、按钮和粉丝数当场跟着变;这个接口拿不到时(没登录、老服务端)
/// 资料页照常能看,只是不显示这一行。
///
/// 后半段守的是 #382 那三个板块入口:关注一次、三处都跟着来,那就得三处都有门 ——
/// 「TA 的视频」「TA 的动态」人人都有,「TA 的音乐」要先是音乐人。这几行是 import 一掉就
/// 静默少一格的那种接线,analyze 不报。
library;

import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:package_info_plus/package_info_plus.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:superz_shared/superz_shared.dart';
import 'package:user_app/chat/pages/user_profile_page.dart';
import 'package:user_app/chat/store.dart';
import 'package:user_app/main.dart' show superZTheme;
import 'package:user_app/music/api.dart' show MusicApi;
import 'package:user_app/music/nav.dart' as music;

void main() {
  setUpAll(() => PackageInfo.setMockInitialValues(
      appName: 'user_app', packageName: 'com.superz.user', version: '0.1.0', buildNumber: '1', buildSignature: ''));
  setUp(() => SharedPreferences.setMockInitialValues({}));
  tearDown(() => ChatStore.instance.stop());

  http.Response json(Object body, [int code = 200]) => http.Response(jsonEncode(body), code,
      headers: {'content-type': 'application/json; charset=utf-8'});

  /// [statsCode] 不是 200 时模拟「拿不到关注关系」
  ({ApiClient api, List<String> calls}) server({bool followed = false, int fans = 12, int statsCode = 200}) {
    final calls = <String>[];
    var isFollowed = followed;
    var fansNow = fans;
    final api = ApiClient(
      baseUrl: 'https://api.example.test',
      httpClient: MockClient((req) async {
        final path = req.url.path;
        calls.add('${req.method} $path');
        if (path == '/social/v1/users/42/follow-stats') {
          if (statsCode != 200) return json({'detail': '不行'}, statsCode);
          return json({'fans': fansNow, 'following': 3, 'followed': isFollowed, 'follows_you': true});
        }
        if (path == '/social/v1/users/42/follow') {
          isFollowed = req.method == 'POST';
          fansNow += isFollowed ? 1 : -1;
          return json({'followed': isFollowed, 'fans': fansNow});
        }
        if (path == '/social/v1/users/42') {
          return json({'id': 42, 'name': '小王', 'avatar': '', 'username': 'xiaowang'});
        }
        return json(<String, dynamic>{});
      }),
    );
    return (api: api, calls: calls);
  }

  Future<void> pump(WidgetTester tester) async {
    tester.view
      ..devicePixelRatio = 1
      ..physicalSize = const Size(390, 900);
    addTearDown(tester.view.reset);
    await tester.pumpWidget(MaterialApp(
        theme: superZTheme(Brightness.light), home: const UserProfilePage(userId: 42)));
    await tester.pumpAndSettle();
  }

  testWidgets('没关注:显示关注数和粉丝数、「他关注了你」和「关注」按钮', (tester) async {
    final s = server();
    ChatStore.instance.debugUseClient(s.api);
    await pump(tester);

    expect(s.calls, contains('GET /social/v1/users/42/follow-stats'));
    expect(find.text('关注'), findsWidgets);
    expect(find.text('粉丝'), findsOneWidget);
    expect(find.text('12'), findsOneWidget);
    expect(find.text('3'), findsOneWidget);
    expect(find.text('他关注了你'), findsOneWidget);
  });

  testWidgets('点「关注」:写 /social/v1 的接口,按钮变「已关注」、粉丝数 +1', (tester) async {
    final s = server();
    ChatStore.instance.debugUseClient(s.api);
    await pump(tester);

    await tester.tap(find.widgetWithText(InkWell, '关注').last);
    await tester.pumpAndSettle();

    expect(s.calls, contains('POST /social/v1/users/42/follow'));
    expect(find.text('已关注'), findsOneWidget);
    expect(find.text('13'), findsOneWidget);

    await tester.tap(find.widgetWithText(InkWell, '已关注').last);
    await tester.pumpAndSettle();
    expect(s.calls, contains('DELETE /social/v1/users/42/follow'));
    expect(find.text('12'), findsOneWidget);
  });

  testWidgets('拿不到关注关系(没登录、老服务端):资料页照常,只是没有这一行', (tester) async {
    final s = server(statsCode: 401);
    ChatStore.instance.debugUseClient(s.api);
    await pump(tester);

    expect(find.text('小王'), findsWidgets, reason: '资料本身还在');
    expect(find.text('粉丝'), findsNothing);
    expect(find.text('关注'), findsNothing);
  });

  /// [artist] 为 false 时 `/music/v1/users/42/artist` 404 —— 不是音乐人(接口关着也是这条路)
  void useMusic({required bool artist}) => music.musicApi = MusicApi(ApiClient(
        baseUrl: 'https://api.example.test',
        httpClient: MockClient((req) async => req.url.path == '/music/v1/users/42/artist' && artist
            ? json({'aid': 'a1', 'name': '小王', 'tracks': 7})
            : json({'detail': '不是音乐人'}, 404)),
      ));

  tearDown(() => useMusic(artist: false));

  testWidgets('不是音乐人:「TA 的视频」「TA 的动态」照样有,「TA 的音乐」不出', (tester) async {
    final s = server();
    ChatStore.instance.debugUseClient(s.api);
    useMusic(artist: false);
    await pump(tester);

    expect(find.text('小王 的视频'), findsOneWidget);
    expect(find.text('小王 的动态'), findsOneWidget, reason: '动态不用先开通,人人都有一份');
    expect(find.text('小王 的音乐'), findsNothing);
  });

  testWidgets('是音乐人:三个入口都在,音乐那格写着有几首歌', (tester) async {
    final s = server();
    ChatStore.instance.debugUseClient(s.api);
    useMusic(artist: true);
    await pump(tester);

    expect(find.text('小王 的视频'), findsOneWidget);
    expect(find.text('小王 的音乐'), findsOneWidget);
    expect(find.text('音乐人 · 7 首歌'), findsOneWidget);
    expect(find.text('小王 的动态'), findsOneWidget);
  });
}
