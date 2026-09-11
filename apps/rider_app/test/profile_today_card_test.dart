import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:rider_app/profile_page.dart';
import 'package:superz_shared/superz_shared.dart';

import 'rider_fake_api.dart';

/// 「我的」页的身份行和三个数(设计稿 5i):来源对不对、放不放得下。
///
/// ## 这里锁的几件事,都是线上吃过亏的
///
/// **① 数字来自服务端聚合,不来自订单列表。** 老的今日卡曾经由 `_todayDone`
/// 从 `_mine` 里筛 `completed||delivered`,而 `_mine` 只留在途单 —— 两个集合
/// 不相交,每个骑手每一天都看到 0。现在累计单数、本月所得都读 `/riders/me/worklog`
/// (服务端 count/sum,无 limit)。
///
/// **② 数字放不下。** 三格等分,「¥12,345」在 320 屏 1.4× 下曾经溢出。
/// 现在每格 FittedBox 缩放,这里按几个量级逐个量。
///
/// **③ 没数据给「—」,真的 0 给 0。** 0 是一个看起来像真值的数,
/// 骑手会读它("我这个月怎么才挣 0"),然后它又自己变了。
///
/// **④ 不放任何分数、等级、段位。** 「用户评价」是顾客打分的平均,
/// 只摆出来,不参与排序和派单。
void main() {
  setUpRiderTest();

  Future<void> pump(WidgetTester t, ApiClient api,
      {double scale = 1.0, double width = 390}) async {
    setPhoneViewport(t, Size(width, 844));
    await t.pumpWidget(MediaQuery(
      data: MediaQueryData(textScaler: TextScaler.linear(scale)),
      child: MaterialApp(
        theme: brandTheme(Brightness.light),
        home: Scaffold(
            body: RiderProfilePage(
                api: api, onOpenWallet: () {}, onOpenOrders: () {})),
      ),
    ));
    await t.pumpAndSettle();
  }

  group('身份行', () {
    testWidgets('名字、实名标、加入年月、累计单数都在', (t) async {
      await pump(t, fakeRiderApi(totalOrders: 1842));
      expect(find.text('王师傅'), findsOneWidget);
      expect(find.text('已实名'), findsOneWidget);
      expect(find.text('骑手 · 2026 年 3 月加入 · 1,842 单'), findsOneWidget);
    });

    testWidgets('没通过实名:不挂「已实名」', (t) async {
      await pump(t, fakeRiderApi(verifyStatus: 'pending'));
      expect(find.text('已实名'), findsNothing);
    });
  });

  group('三个数来自服务端聚合', () {
    testWidgets('评价 4.9、本月所得 ¥5,214、罚款 0', (t) async {
      await pump(t, fakeRiderApi(monthEarnedCents: 521400));
      expect(find.text('4.9'), findsOneWidget);
      expect(find.text('¥5,214'), findsOneWidget);
      expect(find.text('0'), findsOneWidget);
      expect(find.text('罚款 · 没有这项'), findsOneWidget);
    });

    testWidgets('订单列表返回什么都不影响这些数', (t) async {
      await pump(
          t,
          fakeRiderApi(
            monthEarnedCents: 521400,
            orders: [
              for (var i = 0; i < 20; i++)
                {
                  'order_no': 'SZ$i',
                  'merchant_id': 1,
                  'merchant_name': '楼下面馆',
                  'status': 'completed',
                  'items': <dynamic>[],
                  'food_cents': 1000,
                  'delivery_fee_cents': 500,
                  'total_cents': 1500,
                  'address': 'x',
                  'lat': 30.0,
                  'lng': 104.0,
                  'created_at': '2026-08-25T12:00:00+08:00',
                },
            ],
          ));
      expect(find.text('¥5,214'), findsOneWidget);
    });
  });

  group('没数据给「—」,真的 0 给 0', () {
    testWidgets('worklog 拉不到:本月所得是「—」', (t) async {
      await pump(t, fakeRiderApi(failing: {'/riders/me/worklog'}));
      expect(find.text('—'), findsWidgets);
      expect(find.text('¥0'), findsNothing);
    });

    testWidgets('这个月真的还没挣:写 ¥0,不写「—」', (t) async {
      await pump(t, fakeRiderApi(monthEarnedCents: 0));
      expect(find.text('¥0'), findsOneWidget);
    });

    testWidgets('还没有顾客评价:评价格是「—」,不是 0 分', (t) async {
      await pump(t, fakeRiderApi(ratingCount: 0));
      expect(find.text('—'), findsWidgets);
      expect(find.text('0.0'), findsNothing);
    });
  });

  group('溢出护栏:多大的数都不许画出格', () {
    for (final cents in [0, 8600, 521400, 12345600]) {
      for (final width in [320.0, 390.0]) {
        for (final scale in [1.0, 1.4]) {
          testWidgets('¥${cents ~/ 100} @$width ${scale}x', (t) async {
            await pump(t, fakeRiderApi(monthEarnedCents: cents),
                scale: scale, width: width);
            expect(t.takeException(), isNull);
          });
        }
      }
    }
  });

  group('疲劳提醒', () {
    testWidgets('remind 档显示休息提示', (t) async {
      await pump(
          t,
          fakeRiderApi(
              fatigueLevel: 'remind', fatigueMessage: '已连续在线 8 小时,歇会儿'));
      expect(find.text('已连续在线 8 小时,歇会儿'), findsOneWidget);
    });

    testWidgets('正常档不显示', (t) async {
      await pump(t, fakeRiderApi(fatigueLevel: 'ok', fatigueMessage: ''));
      expect(find.byIcon(Icons.bedtime_outlined), findsNothing);
    });

    testWidgets('fatigue 整个拉不到也不影响这一页', (t) async {
      await pump(t, fakeRiderApi(failing: {'/riders/me/fatigue'}));
      expect(find.text('王师傅'), findsOneWidget);
      expect(find.text('¥5,214'), findsOneWidget);
    });
  });

  group('不放分数、等级、段位', () {
    testWidgets('首屏上没有服务分/派单分/段位这类字样', (t) async {
      // /transparency/dispatch 的 never_do 里公开承诺过
      // 「不按骑手评分或等级差别对待」—— 这一页出现分数就是当众违背它。
      // 只看首屏:折叠线以下的承诺卡里本来就写着「我们没有服务分」
      await pump(t, fakeRiderApi());
      for (final banned in ['服务分', '安全分', '派单分', '青铜', '等级', '段位']) {
        expect(find.textContaining(banned), findsNothing,
            reason: '出现了「$banned」—— 见 profile_page.dart 类文档的红线');
      }
    });
  });
}
