// 发现页(DEV-PROMPTS-41 §8.2 GET /home):各块摆得对、开关关着时说「暂未开放」而且不给重试。
//
// 接口用 MockClient 喂 —— 服务端那边还在并行做,客户端按 §8.2 的形状写。
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:package_info_plus/package_info_plus.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:superz_shared/superz_shared.dart';
import 'package:user_app/music/api.dart';
import 'package:user_app/music/nav.dart';
import 'package:user_app/music/pages/home_page.dart';

Map<String, dynamic> track(String tid, String title, {String artist = '小林', Map<String, dynamic>? rank}) => {
      'tid': tid,
      'title': title,
      'duration_ms': 210000,
      'cover': '/img/music_cover/$tid.jpg',
      'genre': 'pop',
      'genre_name': '流行',
      'plays': 1200,
      'likes': 30,
      'artist': {'aid': 'maHbFUgZ3A32', 'name': artist, 'user_id': 42},
      'release': {'rid': 'mrHbFUgZ3A32', 'title': '夏天', 'kind': 'single'},
      'published_at': '2026-09-15T12:00:00+08:00',
      if (rank != null) 'rank': rank,
    };

const _home = <String, dynamic>{};

void main() {
  setUpAll(() {
    // package_info_plus 在测试环境没有平台通道,不铺好的话第一个请求永远不返回
    TestWidgetsFlutterBinding.ensureInitialized();
    PackageInfo.setMockInitialValues(
      appName: 'user_app',
      packageName: 'com.superz.user',
      version: '0.1.0',
      buildNumber: '1',
      buildSignature: '',
    );
  });

  setUp(() => SharedPreferences.setMockInitialValues({}));

  /// 把 [payload] 当 `/music/v1/home` 的回包;[status] 不是 200 时原样返回那个状态。
  void mock(Map<String, dynamic> payload, {int status = 200, String detail = ''}) {
    musicApi = MusicApi(ApiClient(
      baseUrl: 'http://test.local',
      httpClient: MockClient((req) async {
        if (status != 200) {
          return http.Response(jsonEncode({'detail': detail}), status,
              headers: {'content-type': 'application/json; charset=utf-8'});
        }
        return http.Response(jsonEncode(payload), 200,
            headers: {'content-type': 'application/json; charset=utf-8'});
      }),
    ));
  }

  Future<void> pumpDiscover(WidgetTester tester) async {
    // 屏给得高一点:ListView 只建看得见的那几条,默认 600 高的话
    // 「推荐歌单」「新歌」压根没被建出来,断言会以为它们没画
    tester.view.physicalSize = const Size(420, 3000);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(() {
      tester.view.resetPhysicalSize();
      tester.view.resetDevicePixelRatio();
    });
    await tester.pumpWidget(MaterialApp(
      theme: brandTheme(Brightness.light),
      // 每次都换一把钥匙:同一个类型的 widget 再 pump 一次时 Flutter 会复用
      // 原来那个 State,于是上一轮拉到的数据还在,换了回包也看不出变化
      home: Scaffold(body: MusicDiscoverView(key: UniqueKey())),
    ));
    await tester.pumpAndSettle();
  }

  testWidgets('发现页把每日推荐、榜单、推荐歌单、新歌、曲风都摆出来', (tester) async {
    mock({
      'daily': [
        track('mt1', '晚风', rank: {'score': 152.5, 'why': '近7天 35 人收听、4 人加入歌单'}),
        track('mt2', '清晨'),
      ],
      'daily_personalized': true,
      'playlists': [
        {
          'pid': 'mpHbFUgZ3A32',
          'title': '通勤路上',
          'track_count': 20,
          'collects': 5,
          'owner': {'id': 7, 'name': '小明'},
        }
      ],
      'new_tracks': [track('mt3', '新歌一首')],
      'charts': [
        {
          'key': 'hot',
          'name': '热歌榜',
          'updated_at': '2026-09-15T10:00:00+08:00',
          'top': [track('mt1', '晚风'), track('mt2', '清晨')],
        }
      ],
      'genres': [
        {'key': 'pop', 'name': '流行'},
        {'key': 'rock', 'name': '摇滚'},
      ],
    });
    await pumpDiscover(tester);

    expect(find.text('每日推荐'), findsOneWidget);
    expect(find.text('榜单'), findsOneWidget);
    expect(find.text('热歌榜'), findsOneWidget);
    expect(find.text('推荐歌单'), findsOneWidget);
    expect(find.text('通勤路上'), findsOneWidget);
    expect(find.text('新歌'), findsOneWidget);
    expect(find.text('新歌一首'), findsOneWidget);
    // 曲风是可点的入口
    expect(find.text('流行'), findsWidgets);
    expect(find.text('摇滚'), findsOneWidget);
    // 搜索框常驻
    expect(find.text('搜歌曲、歌手、专辑、歌单'), findsOneWidget);
  });

  testWidgets('每一首推荐都带算分的中间量,旁边有「怎么算的」', (tester) async {
    mock({
      'daily': [
        track('mt1', '晚风', rank: {'score': 152.5, 'why': '近7天 35 人收听、4 人加入歌单'})
      ],
      'daily_personalized': true,
    });
    await pumpDiscover(tester);
    expect(find.text('近7天 35 人收听、4 人加入歌单'), findsOneWidget);
    expect(find.text('怎么算的'), findsWidgets);
  });

  testWidgets('关掉个性化之后把话说出来,而不是悄悄换一套结果', (tester) async {
    mock({
      'daily': [track('mt1', '晚风')],
      'daily_personalized': false,
    });
    await pumpDiscover(tester);
    expect(find.text('已关掉个性化,按热歌榜分数排'), findsOneWidget);

    mock({
      'daily': [track('mt1', '晚风')],
      'daily_personalized': true,
    });
    await pumpDiscover(tester);
    expect(find.text('按你听过、喜欢过的算,公式公开'), findsOneWidget);
  });

  testWidgets('开关关着(503):说「音乐暂未开放」,而且不给重试按钮', (tester) async {
    mock(_home, status: 503, detail: '音乐暂未开放');
    await pumpDiscover(tester);
    // 503 是急停闸不是故障 —— 重试一百次也还是关着
    expect(find.text('音乐暂未开放'), findsOneWidget);
    expect(find.text('重试'), findsNothing);
  });

  testWidgets('拉不到(500):给重试按钮', (tester) async {
    mock(_home, status: 500, detail: '服务器开小差了');
    await pumpDiscover(tester);
    expect(find.text('重试'), findsOneWidget);
  });

  testWidgets('一首歌都还没有的时候引导去开通音乐人,不是干晾一个空页', (tester) async {
    mock(const {'daily': [], 'playlists': [], 'new_tracks': [], 'charts': [], 'genres': []});
    await pumpDiscover(tester);
    expect(find.textContaining('音乐人传上来、过了审就会出现在这里'), findsOneWidget);
    expect(find.text('开通音乐人'), findsOneWidget);
  });

  testWidgets('服务端只给半截也画得出来,不崩', (tester) async {
    // charts 里没有 top、歌里没有 artist,都是服务端可能少给的
    mock({
      'charts': [
        {'key': 'hot', 'name': '热歌榜'}
      ],
      'new_tracks': [
        {'tid': 'mt9', 'title': '只有名字'}
      ],
    });
    await pumpDiscover(tester);
    expect(find.text('热歌榜'), findsOneWidget);
    expect(find.text('只有名字'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('首页两页签:发现 / 我的', (tester) async {
    mock(const {'daily': [], 'playlists': [], 'new_tracks': [], 'charts': [], 'genres': []});
    await tester.pumpWidget(MaterialApp(
      theme: brandTheme(Brightness.light),
      home: const MusicHomePage(),
    ));
    await tester.pumpAndSettle();
    expect(find.text('发现'), findsOneWidget);
    expect(find.text('我的'), findsOneWidget);
    expect(find.text('音乐'), findsOneWidget);
  });
}
