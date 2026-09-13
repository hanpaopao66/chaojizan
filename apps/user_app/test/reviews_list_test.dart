import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:superz_shared/superz_shared.dart';
import 'package:user_app/reviews_page.dart';

/// 店铺评价页(设计稿 B):评分概览、筛选、差评照实排在列表里。
///
/// 概览和筛选条数来自服务端的全店概览,列表按筛选分页向服务端要。
/// 这里的假服务端照 reviews.py 的口径算:好评 ≥4 星、差评 ≤2 星、
/// 有追评 = 有 append_at、有图 = 首评或追评带图;按 id 倒序,before 是游标。
void main() {
  Map<String, dynamic> review(int id, int stars,
          {String? comment, bool photo = false, String append = ''}) =>
      {
        'id': id,
        'merchant_rating': stars,
        'comment': comment ?? '第$id条',
        'image_urls': photo ? ['/uploads/a.jpg'] : [],
        'tags': const [],
        'reply': '',
        'append_content': append,
        if (append.isNotEmpty) 'append_at': '2026-09-11T04:00:00Z',
        'customer_name': '王**',
        // id 越大越新
        'created_at':
            DateTime.utc(2026, 9, 1).add(Duration(hours: id)).toIso8601String(),
      };

  /// 45 条:id 3/13/23/33/43 是 2 星,8 的倍数是 3 星,其余 5 星;
  /// 5 的倍数带图;id 44 带追评;id 43 是那条要按时间排在中间的差评
  List<Map<String, dynamic>> shopReviews() => [
        for (var id = 45; id >= 1; id--)
          review(
            id,
            id % 10 == 3
                ? 2
                : id % 8 == 0
                    ? 3
                    : 5,
            comment: switch (id) {
              45 => '汤是真熬的',
              44 => '辣度偏辣',
              43 => '高峰等了四十分钟',
              42 => '老味道',
              _ => null,
            },
            photo: id % 5 == 0,
            append: id == 44 ? '第二次正好' : '',
          ),
      ];

  bool matches(Map<String, dynamic> r, String filter) => switch (filter) {
        'photo' => (r['image_urls'] as List).isNotEmpty,
        'good' => (r['merchant_rating'] as int) >= 4,
        'bad' => (r['merchant_rating'] as int) <= 2,
        'append' => r['append_at'] != null,
        _ => true,
      };

  late List<Uri> requests;

  /// [failPages]:第几次拉列表(从 1 数)返回 500
  Future<void> pump(WidgetTester t,
      {List<Map<String, dynamic>>? data,
      Set<int> failPages = const {},
      bool failFirstOverview = false}) async {
    t.view
      ..devicePixelRatio = 3.0
      ..physicalSize = const Size(390, 844) * 3.0;
    addTearDown(t.view.reset);
    final all = data ?? shopReviews();
    requests = [];
    var pageCalls = 0;
    var overviewCalls = 0;
    final api = ApiClient(
      baseUrl: 'http://test.local',
      httpClient: MockClient((req) async {
        requests.add(req.url);
        Object body = const [];
        if (req.url.path == '/merchants/7/reviews/overview') {
          overviewCalls++;
          if (failFirstOverview && overviewCalls == 1) {
            return http.Response(jsonEncode({'detail': '服务开小差了'}), 500,
                headers: {'content-type': 'application/json; charset=utf-8'});
          }
          final stars = {for (var s = 1; s <= 5; s++) '$s': 0};
          var sum = 0;
          for (final r in all) {
            final s = r['merchant_rating'] as int;
            stars['$s'] = stars['$s']! + 1;
            sum += s;
          }
          body = {
            'count': all.length,
            'avg': all.isEmpty ? null : (sum / all.length * 10).round() / 10,
            'stars': stars,
            for (final f in ['photo', 'good', 'bad', 'append'])
              f: all.where((r) => matches(r, f)).length,
          };
        } else if (req.url.path == '/merchants/7/reviews') {
          pageCalls++;
          if (failPages.contains(pageCalls)) {
            return http.Response(jsonEncode({'detail': '服务开小差了'}), 500,
                headers: {'content-type': 'application/json; charset=utf-8'});
          }
          final q = req.url.queryParameters;
          final filter = q['filter'] ?? 'all';
          final before = int.tryParse(q['before'] ?? '');
          final limit = int.tryParse(q['limit'] ?? '') ?? 50;
          body = all
              .where((r) => matches(r, filter))
              .where((r) => before == null || (r['id'] as int) < before)
              .take(limit)
              .toList();
        }
        return http.Response(jsonEncode(body), 200,
            headers: {'content-type': 'application/json; charset=utf-8'});
      }),
    );
    await t.pumpWidget(MaterialApp(
      theme: brandTheme(Brightness.light),
      home: Scaffold(body: ReviewsList(api: api, merchantId: 7)),
    ));
    await t.pumpAndSettle();
  }

  List<Uri> pageRequests() =>
      requests.where((u) => u.path == '/merchants/7/reviews').toList();

  Future<void> scrollToEnd(WidgetTester t) async {
    for (var i = 0; i < 30; i++) {
      // 带图的评价里还有横向的图片列表,外层的是第一个
      await t.drag(find.byType(ListView).first, const Offset(0, -900));
      await t.pumpAndSettle();
    }
  }

  testWidgets('筛选和分布是全店的数:列表只拉了第一页,条数照样是全店', (t) async {
    await pump(t);
    // 45 条:差评 5 条、3 星 5 条、好评 35 条;有图 9 条;追评 1 条
    for (final s in ['全部 45', '有图 9', '好评 35', '差评 5', '有追评 1']) {
      expect(find.text(s), findsOneWidget, reason: '缺了「$s」');
    }
    // 均分 200/45 → 4.4;好评率 35/45 → 78%
    expect(find.text('4.4'), findsOneWidget);
    expect(find.text('45 条 · 78% 好评'), findsOneWidget);
    // 第一页只要了 20 条
    expect(pageRequests().single.queryParameters['limit'], '20');
    // 原来的「按最近 N 条算」那句说明不要了:数就是全店的
    expect(find.textContaining('按最近'), findsNothing);
  });

  testWidgets('差评按时间排在里面,不折叠、不往后挪', (t) async {
    await pump(t);
    final bad = t.getTopLeft(find.text('高峰等了四十分钟')).dy;
    expect(bad, greaterThan(t.getTopLeft(find.text('辣度偏辣')).dy));
    expect(bad, lessThan(t.getTopLeft(find.text('老味道')).dy));
  });

  testWidgets('点「差评」向服务端要差评;点「有追评」只剩带追评的', (t) async {
    await pump(t);
    await t.tap(find.text('差评 5'));
    await t.pumpAndSettle();
    expect(pageRequests().last.queryParameters['filter'], 'bad');
    expect(pageRequests().last.queryParameters.containsKey('before'), isFalse,
        reason: '换筛选要从第一页拉起');
    expect(find.text('高峰等了四十分钟'), findsOneWidget);
    expect(find.text('汤是真熬的'), findsNothing);
    // 概览不跟着筛选变:还是全店
    expect(find.text('全部 45'), findsOneWidget);

    await t.tap(find.text('有追评 1'));
    await t.pumpAndSettle();
    expect(find.text('【追评】第二次正好'), findsOneWidget);
    expect(find.text('高峰等了四十分钟'), findsNothing);
  });

  testWidgets('滑到底接着拉下一页,游标是上一页最后一条;拉完就停', (t) async {
    await pump(t);
    expect(pageRequests().length, 1, reason: '没滑到底不去要下一页');
    await scrollToEnd(t);
    final pages = pageRequests();
    expect(pages.length, 3, reason: '45 条按 20 一页是三页,第三页不满就不再要');
    expect(pages[1].queryParameters['before'], '26');
    expect(pages[2].queryParameters['before'], '6');
    expect(find.text('第1条'), findsOneWidget);
  });

  testWidgets('翻页没拉到:页尾说一声,点了按同一个游标再要', (t) async {
    await pump(t, failPages: {2});
    await scrollToEnd(t);
    expect(find.text('没加载出来,点这里重试'), findsOneWidget);
    // 已经拉到的第一页还在
    expect(find.text('第26条'), findsOneWidget);
    await t.tap(find.text('没加载出来,点这里重试'));
    await t.pumpAndSettle();
    expect(pageRequests()[2].queryParameters['before'], '26');
    expect(find.text('没加载出来,点这里重试'), findsNothing);
  });

  testWidgets('第一次没拉到给出错页,点重试回来就正常了', (t) async {
    await pump(t, failFirstOverview: true);
    expect(find.text('服务开小差了'), findsOneWidget);
    await t.tap(find.text('重试'));
    await t.pumpAndSettle();
    expect(find.text('服务开小差了'), findsNothing);
    expect(find.text('全部 45'), findsOneWidget);
  });

  testWidgets('一条评价都没有:空态,不画概览', (t) async {
    await pump(t, data: const []);
    expect(find.text('还没有评价,下单后来做第一个评价的人'), findsOneWidget);
    expect(find.textContaining('全部'), findsNothing);
  });

  testWidgets('筛出来是空的:说「还没有X的评价」', (t) async {
    await pump(t, data: [review(2, 5), review(1, 4)]);
    await t.tap(find.text('差评 0'));
    await t.pumpAndSettle();
    expect(find.text('还没有差评的评价'), findsOneWidget);
  });
}
