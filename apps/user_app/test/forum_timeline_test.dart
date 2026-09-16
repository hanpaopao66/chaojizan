// 论坛时间线:分页、转发条目、rank、浏览上报、开关关着的 503(DEV-PROMPTS-41 §8.3)。
//
// ## 守的是什么
//
// - 推荐按 `page` 翻(§5.2:按分数排的用 page),关注按 `cursor` 翻 ——
//   翻错了会一直拿第一页,用户以为「只有这么多」;
// - 转发条目的 `by` 是转的人,`post.author` 还是原作者 —— 弄反了就成了冒名;
// - 服务端多给 / 少给 / 给错 `rank` 都不能崩;
// - 浏览上报攒够 50 条或到点才发一次(F5),不是一条一个请求;
// - 开关关着时是 503,页面要给服务端那句原话、**不给重试按钮**。
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/testing.dart';
import 'package:http/http.dart' as http;
import 'package:package_info_plus/package_info_plus.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:superz_shared/superz_shared.dart';
import 'package:user_app/forum/api.dart';
import 'package:user_app/forum/models.dart';
import 'package:user_app/forum/nav.dart';
import 'package:user_app/forum/view_reporter.dart';
import 'package:user_app/forum/widgets/common.dart';
import 'package:user_app/forum/widgets/timeline.dart';

Map<String, dynamic> postJson(String pid, {String author = '小王', int authorId = 42, Map<String, dynamic> over = const {}}) => {
      'pid': pid,
      'author': {'id': authorId, 'name': author, 'username': 'u$authorId', 'avatar': ''},
      'text': '第 $pid 条',
      'entities': {'tags': <dynamic>[], 'mentions': <dynamic>[], 'links': <dynamic>[]},
      'media': <dynamic>[],
      'counts': {'replies': 0, 'reposts': 0, 'quotes': 0, 'likes': 0, 'bookmarks': 0, 'views': 3},
      'viewer': {'liked': false, 'reposted': false, 'bookmarked': false},
      'reply_policy': 'all',
      'can_reply': true,
      'created_at': '2026-09-15T12:00:00+08:00',
      ...over,
    };

/// 造一个走 MockClient 的 ForumApi。[routes] 按「方法 路径」给响应体。
({ForumApi api, List<String> calls, List<Map<String, dynamic>> bodies}) mockApi(
    Object? Function(http.Request req) handle) {
  final calls = <String>[];
  final bodies = <Map<String, dynamic>>[];
  final client = ApiClient(
    baseUrl: 'http://test.local',
    httpClient: MockClient((req) async {
      calls.add('${req.method} ${req.url.path}${req.url.query.isEmpty ? '' : '?${req.url.query}'}');
      if (req.body.isNotEmpty) {
        try {
          bodies.add((jsonDecode(req.body) as Map).cast<String, dynamic>());
        } catch (_) {}
      }
      final r = handle(req);
      if (r is http.Response) return r;
      return http.Response(jsonEncode(r ?? const {}), 200,
          headers: {'content-type': 'application/json; charset=utf-8'});
    }),
  );
  return (api: ForumApi(client), calls: calls, bodies: bodies);
}

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
  setUp(() {
    SharedPreferences.setMockInitialValues({});
    resetForumDeviceIdForTest();
  });
  tearDown(() => forumApiOverride = null);

  group('推荐按 page 翻', () {
    test('第一页拿 page=0,第二页拿 page=1', () async {
      final m = mockApi((req) {
        final page = int.parse(req.url.queryParameters['page'] ?? '0');
        return {
          'items': [
            {'type': 'post', 'post': postJson('fp${page}a')},
          ],
          'has_more': page < 1,
        };
      });
      forumApiOverride = m.api;
      final pager = forumPagePager((page) => m.api.foryou(page));
      await pager.refresh();
      expect(pager.items.single.post.pid, 'fp0a');
      expect(pager.hasMore, isTrue);

      await pager.more();
      expect(pager.items.map((x) => x.post.pid), ['fp0a', 'fp1a']);
      expect(pager.hasMore, isFalse, reason: 'has_more 是 false 就到底了');
      expect(m.calls, ['GET /forum/v1/timeline/foryou?page=0', 'GET /forum/v1/timeline/foryou?page=1']);

      // 到底之后再滑也不该再请求
      await pager.more();
      expect(m.calls.length, 2);
      pager.dispose();
    });

    test('刷新回到第一页', () async {
      final m = mockApi((req) => {
            'items': [
              {'type': 'post', 'post': postJson('fp${req.url.queryParameters['page']}')}
            ],
            'has_more': true,
          });
      final pager = forumPagePager((page) => m.api.foryou(page));
      await pager.refresh();
      await pager.more();
      expect(pager.items.length, 2);
      await pager.refresh();
      expect(pager.items.length, 1);
      expect(pager.items.single.post.pid, 'fp0');
      pager.dispose();
    });
  });

  group('关注按 cursor 翻', () {
    test('把服务端给的游标原样传回去', () async {
      final m = mockApi((req) {
        final cursor = req.url.queryParameters['cursor'];
        if (cursor == null) {
          return {
            'items': [
              {'type': 'post', 'post': postJson('fpA')}
            ],
            'has_more': true,
            'next_cursor': '1757900000000000_12',
          };
        }
        return {
          'items': [
            {'type': 'post', 'post': postJson('fpB')}
          ],
          'has_more': false,
          'next_cursor': null,
        };
      });
      final pager = forumCursorPager((cursor) => m.api.followingTimeline(cursor: cursor));
      await pager.refresh();
      await pager.more();
      expect(pager.items.map((x) => x.post.pid), ['fpA', 'fpB']);
      expect(m.calls[1], contains('cursor=1757900000000000_12'));
      expect(pager.hasMore, isFalse, reason: 'next_cursor 为 null 就是到底了');
      pager.dispose();
    });
  });

  group('转发条目', () {
    test('by 是转的人,帖子还是原作者的', () async {
      final m = mockApi((req) => {
            'items': [
              {
                'type': 'repost',
                'by': {'id': 9, 'name': '小李', 'username': 'u9', 'avatar': ''},
                'at': '2026-09-15T13:00:00+08:00',
                'post': postJson('fpA', author: '小王', authorId: 42),
              },
              {'type': 'post', 'post': postJson('fpB', author: '小张', authorId: 43)},
            ],
            'has_more': false,
          });
      final r = await m.api.followingTimeline();
      expect(r.items.first.isRepost, isTrue);
      expect(r.items.first.by?.name, '小李');
      expect(r.items.first.post.author?.name, '小王');
      expect(r.items.last.isRepost, isFalse);
      expect(r.items.last.by, isNull);
    });
  });

  group('rank', () {
    test('带中间量时能摊成一句话', () async {
      final m = mockApi((req) => {
            'items': [
              {
                'type': 'post',
                'post': postJson('fpA'),
                'rank': {
                  'score': 3.21,
                  'parts': {'likes': 5, 'reposts': 2, 'quotes': 0, 'repliers': 1, 'hours': 4},
                  'why': '5 人赞、2 人转发',
                },
              }
            ],
            'has_more': false,
          });
      final r = await m.api.foryou(0);
      expect(fRankWhy(r.items.single.rank), '5 人赞、2 人转发');
    });

    test('没有 rank、rank 是坏数据都不崩', () async {
      final m = mockApi((req) => {
            'items': [
              {'type': 'post', 'post': postJson('fpA')},
              {'type': 'post', 'post': postJson('fpB'), 'rank': '不是对象'},
              {'type': 'post', 'post': postJson('fpC'), 'rank': {'parts': '也不是对象'}},
            ],
            'has_more': false,
          });
      final r = await m.api.foryou(0);
      expect(r.items.length, 3);
      for (final item in r.items) {
        expect(fRankWhy(item.rank), '');
      }
    });
  });

  group('开关关着', () {
    test('503 认得出来,是「不给重试」的那一类', () async {
      final m = mockApi((req) => http.Response(
            jsonEncode({'detail': '论坛暂未开放'}),
            503,
            headers: {'content-type': 'application/json; charset=utf-8'},
          ));
      try {
        await m.api.foryou(0);
        fail('应该抛出来');
      } on ApiException catch (e) {
        expect(e.statusCode, 503);
        expect(e.message, '论坛暂未开放');
        expect(ForumApi.isOff(e), isTrue);
      }
    });

    test('发帖被暂停也是 503,文案是服务端那句', () async {
      final m = mockApi((req) => http.Response(
            jsonEncode({'detail': '论坛发帖暂停中'}),
            503,
            headers: {'content-type': 'application/json; charset=utf-8'},
          ));
      try {
        await m.api.createPost(text: '试试');
        fail('应该抛出来');
      } on ApiException catch (e) {
        expect(ForumApi.isOff(e), isTrue);
        expect(e.message, '论坛发帖暂停中');
      }
    });

    test('别的错不是「开关关着」,要给重试', () async {
      final m = mockApi((req) => http.Response('{"detail":"服务器开小差了"}', 500,
          headers: {'content-type': 'application/json; charset=utf-8'}));
      try {
        await m.api.foryou(0);
        fail('应该抛出来');
      } on ApiException catch (e) {
        expect(ForumApi.isOff(e), isFalse);
      }
    });
  });

  group('发帖请求体', () {
    test('回复、引用、投票、谁能回复都按 §8.3 的字段名发', () async {
      final m = mockApi((req) => postJson('fpNew'));
      await m.api.createPost(
        text: '来投个票',
        media: ['/img/forum/u42-a.jpg'],
        card: {'type': 'track', 'id': 'mtA'},
        quotePid: 'fpQ',
        replyToPid: 'fpR',
        pollOptions: ['甲', '乙'],
        pollMinutes: 60,
        replyPolicy: 'following',
      );
      final body = m.bodies.single;
      expect(body['text'], '来投个票');
      expect(body['media'], ['/img/forum/u42-a.jpg']);
      expect(body['card'], {'type': 'track', 'id': 'mtA'});
      expect(body['quote_pid'], 'fpQ');
      expect(body['reply_to_pid'], 'fpR');
      expect(body['poll'], {
        'options': ['甲', '乙'],
        'minutes': 60
      });
      expect(body['reply_policy'], 'following');
    });

    test('没投票时不发 poll 这个键', () async {
      final m = mockApi((req) => postJson('fpNew'));
      await m.api.createPost(text: '就一句话');
      expect(m.bodies.single.containsKey('poll'), isFalse);
      expect(m.bodies.single.containsKey('media'), isFalse);
    });
  });

  group('关注走全站那张表', () {
    test('关注打的是 /social/v1,不是 /forum/v1', () async {
      final m = mockApi((req) => {'followed': true, 'fans': 21});
      final r = await m.api.follow(42, true);
      expect(m.calls.single, 'POST /social/v1/users/42/follow');
      expect(r['fans'], 21);
    });

    test('取消关注是 DELETE 同一个路径', () async {
      final m = mockApi((req) => {'followed': false, 'fans': 20});
      await m.api.follow(42, false);
      expect(m.calls.single, 'DELETE /social/v1/users/42/follow');
    });
  });

  group('浏览上报', () {
    test('攒够 50 条发一次,一次一个请求', () async {
      final batches = <List<String>>[];
      final r = ForumViewReporter((pids, _) async => batches.add(pids));
      for (var i = 0; i < 50; i++) {
        r.sawPid('fp$i');
      }
      await Future<void>.delayed(Duration.zero);
      expect(batches.length, 1);
      expect(batches.single.length, 50);
      r.dispose();
    });

    test('不满 50 条时到点发一次', () async {
      final batches = <List<String>>[];
      final r = ForumViewReporter((pids, _) async => batches.add(pids),
          every: const Duration(milliseconds: 20));
      r.sawPid('fpA');
      r.sawPid('fpB');
      expect(batches, isEmpty, reason: '还没到点,先攒着');
      await Future<void>.delayed(const Duration(milliseconds: 60));
      expect(batches.single, ['fpA', 'fpB']);
      r.dispose();
    });

    test('同一条只报一次', () async {
      final batches = <List<String>>[];
      final r = ForumViewReporter((pids, _) async => batches.add(pids),
          every: const Duration(milliseconds: 20));
      r.sawPid('fpA');
      r.sawPid('fpA');
      r.sawPid('fpA');
      await Future<void>.delayed(const Duration(milliseconds: 60));
      expect(batches.single, ['fpA']);
      r.dispose();
    });

    test('占位条目不报(没内容可看)', () async {
      final batches = <List<String>>[];
      final r = ForumViewReporter((pids, _) async => batches.add(pids),
          every: const Duration(milliseconds: 20));
      r.saw(FPost.fromJson({'pid': 'fpGone', 'unavailable': true}));
      r.saw(FPost.fromJson(postJson('fpOk')));
      await Future<void>.delayed(const Duration(milliseconds: 60));
      expect(batches.single, ['fpOk']);
      r.dispose();
    });

    test('上报失败不往外抛(浏览数不是账,少一次不用补)', () async {
      final r = ForumViewReporter((pids, _) async => throw Exception('网断了'),
          every: const Duration(milliseconds: 20));
      r.sawPid('fpA');
      await Future<void>.delayed(const Duration(milliseconds: 60));
      expect(r.pendingCount, 0);
      r.dispose();
    });

    test('没登录时带设备号', () async {
      String? got;
      final r = ForumViewReporter((pids, deviceId) async => got = deviceId,
          deviceId: 'dev-abc', every: const Duration(milliseconds: 20));
      r.sawPid('fpA');
      await Future<void>.delayed(const Duration(milliseconds: 60));
      expect(got, 'dev-abc');
      r.dispose();
    });

    test('设备号存下来之后一直是同一个', () async {
      final a = await forumDeviceId();
      final b = await forumDeviceId();
      expect(a, b);
      expect(a.length, 32);
    });
  });

  group('列表画出来', () {
    Widget host(Widget child) => MaterialApp(
          theme: brandTheme(Brightness.light),
          home: Scaffold(body: child),
        );

    testWidgets('两条帖子 + 一条转发 + 一条占位都画得出来', (t) async {
      final m = mockApi((req) => {
            'items': [
              {'type': 'post', 'post': postJson('fpA')},
              {
                'type': 'repost',
                'by': {'id': 9, 'name': '小李', 'username': 'u9', 'avatar': ''},
                'at': '2026-09-15T13:00:00+08:00',
                'post': postJson('fpB'),
              },
              {
                'type': 'post',
                'post': {'pid': 'fpGone', 'unavailable': true, 'reason': 'removed'}
              },
            ],
            'has_more': false,
          });
      forumApiOverride = m.api;
      final pager = forumPagePager((page) => m.api.foryou(page));
      await pager.refresh();
      await t.pumpWidget(host(ForumTimeline(pager: pager)));
      await t.pump();

      expect(find.text('第 fpA 条'), findsOneWidget);
      expect(find.text('小李 转发了'), findsOneWidget);
      expect(find.text('这条帖子已下架'), findsOneWidget);
      pager.dispose();
    });

    testWidgets('一条都没有时给空状态', (t) async {
      final m = mockApi((req) => {'items': <dynamic>[], 'has_more': false});
      forumApiOverride = m.api;
      final pager = forumPagePager((page) => m.api.foryou(page));
      await pager.refresh();
      await t.pumpWidget(host(ForumTimeline(pager: pager, emptyText: '这里还没有帖子')));
      await t.pump();
      expect(find.text('这里还没有帖子'), findsOneWidget);
      pager.dispose();
    });

    testWidgets('503 给服务端那句原话,不给重试按钮', (t) async {
      final m = mockApi((req) => http.Response(jsonEncode({'detail': '论坛暂未开放'}), 503,
          headers: {'content-type': 'application/json; charset=utf-8'}));
      forumApiOverride = m.api;
      final pager = forumPagePager((page) => m.api.foryou(page));
      await pager.refresh();
      await t.pumpWidget(host(
        Builder(builder: (ctx) => forumErrorView(pager.error, pager.refresh)),
      ));
      await t.pump();
      expect(find.textContaining('论坛暂未开放'), findsOneWidget);
      expect(find.text('重试'), findsNothing);
      pager.dispose();
    });
  });
}
