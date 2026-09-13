import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:superz_shared/superz_shared.dart';
import 'package:user_app/reviews_page.dart';

/// 店铺评价页(设计稿 B):评分概览、筛选、差评照实排在列表里。
void main() {
  Map<String, dynamic> review(int id, int stars,
          {String comment = '',
          bool photo = false,
          String append = '',
          String day = '10'}) =>
      {
        'id': id,
        'merchant_rating': stars,
        'comment': comment,
        'image_urls': photo ? ['/uploads/a.jpg'] : [],
        'tags': const [],
        'reply': '',
        'append_content': append,
        'customer_name': '王**',
        'created_at': '2026-09-${day}T04:00:00Z',
      };

  final reviews = [
    review(1, 5, comment: '汤是真熬的', photo: true, day: '10'),
    review(2, 4, comment: '辣度偏辣', append: '第二次正好', day: '08'),
    review(3, 2, comment: '高峰等了四十分钟', day: '05'),
    review(4, 5, comment: '老味道', day: '03'),
  ];

  Merchant shop({int count = 4, double avg = 4.0}) => Merchant.fromJson({
        'id': 7,
        'name': '张记面馆',
        'lat': 30.0,
        'lng': 104.0,
        'is_open': true,
        'rating_avg': avg,
        'rating_count': count,
      });

  Future<void> pump(WidgetTester t, Merchant s) async {
    t.view
      ..devicePixelRatio = 3.0
      ..physicalSize = const Size(390, 844) * 3.0;
    addTearDown(t.view.reset);
    final api = ApiClient(
      baseUrl: 'http://test.local',
      httpClient: MockClient((req) async => http.Response(
          jsonEncode(req.url.path == '/merchants/7/reviews' ? reviews : []),
          200,
          headers: {'content-type': 'application/json; charset=utf-8'})),
    );
    await t.pumpWidget(MaterialApp(
      theme: brandTheme(Brightness.light),
      home: Scaffold(body: ReviewsList(api: api, merchantId: 7, shop: s)),
    ));
    await t.pumpAndSettle();
  }

  testWidgets('筛选的数对得上;差评按时间排在里面,不折叠', (t) async {
    await pump(t, shop());
    for (final s in ['全部 4', '有图 1', '好评 3', '差评 1', '有追评 1']) {
      expect(find.text(s), findsOneWidget, reason: '缺了「$s」');
    }
    // 差评就在第三条的位置(按时间),不是被挪到最后
    final bad = t.getTopLeft(find.text('高峰等了四十分钟')).dy;
    expect(bad, greaterThan(t.getTopLeft(find.text('辣度偏辣')).dy));
    expect(bad, lessThan(t.getTopLeft(find.text('老味道')).dy));
    // 好评率按 4–5 星算:3/4
    expect(find.text('4 条 · 75% 好评'), findsOneWidget);
  });

  testWidgets('点「差评」只剩差评;点「有追评」只剩带追评的', (t) async {
    await pump(t, shop());
    await t.tap(find.text('差评 1'));
    await t.pumpAndSettle();
    expect(find.text('高峰等了四十分钟'), findsOneWidget);
    expect(find.text('汤是真熬的'), findsNothing);

    await t.tap(find.text('有追评 1'));
    await t.pumpAndSettle();
    expect(find.text('【追评】第二次正好'), findsOneWidget);
    expect(find.text('高峰等了四十分钟'), findsNothing);
  });

  testWidgets('拿到的比店铺总数少:大字评分用店铺的,分布明说只算了最近几条', (t) async {
    await pump(t, shop(count: 268, avg: 4.8));
    expect(find.text('4.8'), findsOneWidget);
    expect(find.textContaining('268 条'), findsOneWidget);
    expect(find.text('分布、好评率和下面的筛选按最近 4 条算'), findsOneWidget);
  });

  testWidgets('拿全了就不写那句说明', (t) async {
    await pump(t, shop());
    expect(find.textContaining('按最近'), findsNothing);
  });
}
