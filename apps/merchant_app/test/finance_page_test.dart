import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:merchant_app/finance_page.dart';
import 'package:package_info_plus/package_info_plus.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:superz_shared/superz_shared.dart';

import 'order_fake_api.dart' show setPhoneViewport;

/// 对账页:这一页上的每一个百分数和每一句「共 N 条」都得是真的。
///
/// ## 为什么这一页格外不能错
///
/// 账目透明是这个平台唯一抄不走的差异点(页尾那张承诺卡就写着
/// 「每日 4:00 自动核账,差一分钱系统报警」)。在这样一页上把平台自己的
/// 抽成写小 0.5 个点,比在别处错得严重得多。
void main() {
  setUpAll(() {
    TestWidgetsFlutterBinding.ensureInitialized();
    PackageInfo.setMockInitialValues(
      appName: 'merchant_app',
      packageName: 'com.superz.merchant',
      version: '0.1.0',
      buildNumber: '1',
      buildSignature: '',
    );
  });
  setUp(() => SharedPreferences.setMockInitialValues({}));

  String todayKey() {
    final d = DateTime.now();
    return '${d.year}-${d.month.toString().padLeft(2, '0')}-'
        '${d.day.toString().padLeft(2, '0')}';
  }

  /// 一天的账:流水 [food] 分,佣金按 [rate] 抽。
  Map<String, dynamic> dayJson(String day, int orders, int food, double rate) {
    final commission = (food * rate).round();
    return {
      'day': day,
      'order_count': orders,
      'food_cents': food,
      'commission_cents': commission,
      'net_cents': food - commission,
    };
  }

  ApiClient financeFakeApi({
    double rate = 0.045,
    List<Map<String, dynamic>>? daily,
    List<Map<String, dynamic>>? withdrawals,
    int withdrawable = 128650,
  }) =>
      ApiClient(
        baseUrl: 'http://test.local',
        httpClient: MockClient((req) async {
          Object? payload;
          switch (req.url.path) {
            case '/merchants/me/finance/daily':
              payload = daily ?? [dayJson(todayKey(), 18, 50400, rate)];
            case '/merchants/me/wallet':
              payload = {
                'balance_cents': withdrawable + 100000,
                'total_earned_cents': 986400,
                'pending_withdrawal_cents': 0,
                'withdrawn_cents': 857750,
                'deposit_required_cents': 100000,
                'deposit_held_cents': 100000,
                'withdrawable_cents': withdrawable,
              };
            case '/merchants/me/withdrawals':
              payload = withdrawals ?? <Map<String, dynamic>>[];
            case '/merchants/me/quality':
              payload = {
                'completed_30d': 412,
                'ready_late_30d': 21,
                'ready_late_rate': 0.051,
                'rejects_30d': 3,
                'promise_ready_minutes': 15,
              };
            case '/merchants/me/commission-tier':
              payload = {
                'commission_rate': rate,
                'tier_rate': rate,
                'tiers': const [],
                'last_month_completed': 640,
                'this_month_completed': 128,
                'next_tier_from': 1000,
                'next_tier_rate': 0.04,
                'orders_to_next': 872,
              };
            default:
              payload = <String, dynamic>{};
          }
          return http.Response(jsonEncode(payload), 200,
              headers: {'content-type': 'application/json; charset=utf-8'});
        }),
      );

  Future<void> pumpFinance(WidgetTester t, ApiClient api,
      {double height = 4600}) async {
    setPhoneViewport(t, Size(390, height));
    await t.pumpWidget(MaterialApp(
      theme: brandTheme(Brightness.light, density: SzDensity.operate),
      home: Scaffold(
        body: Align(
          alignment: Alignment.topLeft,
          child: SizedBox(
              width: 390, height: height, child: FinancePage(api: api)),
        ),
      ),
    ));
    await t.pump();
    await t.pump(const Duration(milliseconds: 400));
  }

  List<String> allTexts() => find
      .byType(Text)
      .evaluate()
      .map((e) => (e.widget as Text).data ?? '')
      .where((s) => s.isNotEmpty)
      .toList();

  group('费率不许被整除截断', () {
    testWidgets('4.5% 的店,分账台面要写 4.5% —— 不是 4%', (t) async {
      // config.py 的档位表就有 0.045(500–999 单/月那一档),
      // 这不是极端输入。`0.045 * 100 ~/ 1` == 4
      await pumpFinance(t, financeFakeApi(rate: 0.045));

      final texts = allTexts();
      expect(texts.where((s) => s.contains('按 4% 计')), isEmpty,
          reason: '整数除法把 4.5% 截成了 4% —— '
              '在账目透明的台面上,平台把自己的抽成说小了 0.5 个点');
      expect(texts.where((s) => s.contains('4.5%')).length,
          greaterThanOrEqualTo(2),
          reason: '阶梯佣金卡和分账台面说的是同一个费率,同一屏上必须一致');
    });

    testWidgets('5% 的新店也不许显示成 5.0 以外的数', (t) async {
      await pumpFinance(t, financeFakeApi(rate: 0.05));
      final texts = allTexts();
      expect(texts.where((s) => s.contains('按 5.0% 计')), isNotEmpty);
    });

    testWidgets('今天还没有流水时,退回按当前档位说,仍然不截断', (t) async {
      await pumpFinance(
          t,
          financeFakeApi(
              rate: 0.045, daily: [dayJson('2020-01-01', 3, 10000, 0.045)]));
      final texts = allTexts();
      expect(texts.where((s) => s.contains('按 4% 计')), isEmpty);
      expect(texts.where((s) => s.contains('按 4.5% 计')), isNotEmpty,
          reason: '今天没单也要说清这一档是多少,而且同样不许截断');
    });
  });

  group('提现记录说几条就是几条', () {
    List<Map<String, dynamic>> manyWithdrawals(int n) => [
          for (var i = 0; i < n; i++)
            {
              'id': i + 1,
              'amount_cents': 50000 + i,
              'status': i == 0 ? 'pending' : 'paid',
              'reject_reason': '',
              'created_at':
                  DateTime.now().subtract(Duration(days: i)).toIso8601String(),
            },
        ];

    testWidgets('30 条提现时,页面上只列最近几条,并给得出「全部」的入口', (t) async {
      await pumpFinance(t, financeFakeApi(withdrawals: manyWithdrawals(30)));

      expect(find.text('全部提现记录'), findsOneWidget,
          reason: '客户端 take(20)、服务端 limit(100),而标题只写「提现记录」——'
              '提现频繁的店永远看不到更早的,也不知道自己没看全');
      // 首屏那几条是**最近**的,不是「前 20 条」
      final amounts = allTexts().where((s) => s.startsWith('¥500'));
      expect(amounts.length, lessThan(20), reason: '一页塞 20 条提现记录,把按日账单挤到更后面去了');
    });

    testWidgets('一条提现都没有时,整块不出现', (t) async {
      await pumpFinance(t, financeFakeApi(withdrawals: const []));
      expect(find.text('全部提现记录'), findsNothing);
      expect(allTexts().where((s) => s.contains('提现记录')), isEmpty);
    });
  });
}
