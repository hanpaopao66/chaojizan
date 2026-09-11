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

/// 账本页(原「对账」):这一页上的每一个百分数和每一句「共 N 条」都得是真的。
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
      theme: brandTheme(Brightness.light,
          density: SzDensity.operate, accentTone: 0),
      home: Scaffold(
        body: Align(
          alignment: Alignment.topLeft,
          child: SizedBox(
              width: 390,
              height: height,
              child: FinancePage(api: api, title: '账本')),
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


  /// 某一天的 key(yyyy-MM-dd),[daysAgo] 天前
  String dayKey(int daysAgo) {
    final d = DateTime.now().subtract(Duration(days: daysAgo));
    return '${d.year}-${d.month.toString().padLeft(2, '0')}-'
        '${d.day.toString().padLeft(2, '0')}';
  }

  /// 近 [n] 天,每天一行
  List<Map<String, dynamic>> lastDays(int n, {double rate = 0.045}) => [
        for (var i = 0; i < n; i++)
          dayJson(dayKey(i), 10 + i, 10000 + i * 100, rate),
      ];

  /// 台面上那个大数(SzRollingAmount)的分
  int heroCents(WidgetTester t) =>
      t.widget<SzRollingAmount>(find.byType(SzRollingAmount)).cents;

  Future<void> pickPeriod(WidgetTester t, String label) async {
    await t.tap(find.descendant(
        of: find.byType(SzTextTabs), matching: find.text(label)));
    await t.pump();
  }

  /// 设计稿 6g:台面(一段时间的实收)+ 按日结算表。
  ///
  /// #33 4.3 的判据还在:「今天到手多少 / 为什么是这个数 / 能不能提出来」
  /// 要在首屏答得出来 —— 只是答法换成了「这个月的实收 + 表里今天那一行」。
  group('账本首屏答得出「到手多少、为什么是这个数」', () {
    testWidgets('本月实收和今天那一行都在首屏 645 以内', (t) async {
      await pumpFinance(t, financeFakeApi(daily: lastDays(1)));
      final hero = find.byType(SzRollingAmount);
      expect(hero, findsOneWidget);
      expect(t.getBottomLeft(hero).dy, lessThan(645));
      final now = DateTime.now();
      final todayRow = find.text('${now.month}/${now.day}');
      expect(todayRow, findsOneWidget, reason: '表里没有今天那一行');
      expect(t.getBottomLeft(todayRow).dy, lessThan(645),
          reason: '可视区是 844 − 47(安全区) − 56(标题行) − 96(底部导航) = 645。'
              '今天到手多少要滚一屏才看得到');
    });

    testWidgets('「菜价 − 平台 = 实收」闭合在台面上', (t) async {
      final rows = lastDays(3);
      await pumpFinance(t, financeFakeApi(daily: rows));
      // 本月里有几天取决于今天是几号:只算落在这个月的那几行
      final now = DateTime.now();
      final inMonth = [
        for (final r in rows)
          if (DateTime.parse(r['day'] as String).month == now.month) r,
      ];
      final food = inMonth.fold<int>(0, (s, r) => s + (r['food_cents'] as int));
      final fee =
          inMonth.fold<int>(0, (s, r) => s + (r['commission_cents'] as int));
      final net = inMonth.fold<int>(0, (s, r) => s + (r['net_cents'] as int));
      expect(net, food - fee, reason: '(前置)假数据自己要平');
      expect(heroCents(t), net,
          reason: '台面的大数就是这一期的实收合计,不是今天、也不是钱包余额');
      expect(find.text('菜价'), findsOneWidget);
      expect(find.text('平台 4.5%'), findsOneWidget);
      expect(find.textContaining('· 实收'), findsOneWidget);
      // 两格结构性的 0:配送费全额归骑手、平台不卖排名位
      expect(find.text('配送费抽'), findsOneWidget);
      expect(find.text('推广位'), findsOneWidget);
    });

    testWidgets('同一个数不写两遍:hero 卡不许回来', (t) async {
      await pumpFinance(t, financeFakeApi());
      // 台面上方原来还有一张 MoneyHeroCard,和台面合计是同一个数(#33 4.3)。
      // 现在台面自己就是那个大数(SzRollingAmount),页面上只许有这一个
      expect(find.byType(MoneyHeroCard), findsNothing,
          reason: 'hero 卡和台面是同一个数的两处显示 —— 留一处就够');
      expect(find.byType(SzRollingAmount), findsOneWidget);
    });

    testWidgets('台面上能直接导出对账单,可提现和打到哪张卡说在一起', (t) async {
      await pumpFinance(t, financeFakeApi());
      expect(find.text('导出对账单'), findsOneWidget);
      expect(find.textContaining('可提现'), findsWidgets);
    });

    testWidgets('没有「到卡」这一列 —— 服务端没有哪天的钱哪天到卡的数', (t) async {
      await pumpFinance(t, financeFakeApi(daily: lastDays(5)));
      // 设计稿每行后面有「已到卡 / 明日到卡」。提现是商家自己点、按笔打款,
      // 不按天;硬画一列就是编的
      expect(allTexts().where((s) => s.contains('已到卡') || s.contains('明日到卡')),
          isEmpty);
    });
  });

  /// 设计稿的页签是「9 月 / 8 月 / 全部」;日账单接口最多 90 天,
  /// 第三个照实叫「近 90 天」。
  group('月份页签:哪一段就只算哪一段', () {
    testWidgets('上个月只算上个月那几天', (t) async {
      final now = DateTime.now();
      final prev = DateTime(now.year, now.month - 1);
      String d(DateTime x) => '${x.year}-${x.month.toString().padLeft(2, '0')}-'
          '${x.day.toString().padLeft(2, '0')}';
      final rows = [
        dayJson(d(DateTime(now.year, now.month, 1)), 10, 20000, 0.045),
        dayJson(d(DateTime(prev.year, prev.month, 3)), 12, 30000, 0.045),
        dayJson(d(DateTime(prev.year, prev.month, 2)), 11, 40000, 0.045),
      ];
      await pumpFinance(t, financeFakeApi(daily: rows));
      await pickPeriod(t, '${prev.month} 月');
      final last = DateTime(now.year, now.month, 0).day;
      expect(find.text('${prev.month} 月 1 日 — $last 日 · 实收'), findsOneWidget);
      expect(heroCents(t),
          (rows[1]['net_cents'] as int) + (rows[2]['net_cents'] as int),
          reason: '上个月的实收混进了这个月的单');
    });

    testWidgets('近 90 天不收最早那个不完整的日子', (t) async {
      // 接口按 now() − 90 天滚动取数:第 90 天前那一天只取到一部分。
      // 照原样加进来,总数就小了一截还说不清 —— 所以不要它
      final rows = [
        dayJson(dayKey(0), 10, 10000, 0.045),
        dayJson(dayKey(90), 3, 5000, 0.045),
      ];
      await pumpFinance(t, financeFakeApi(daily: rows));
      await pickPeriod(t, '近 90 天');
      expect(heroCents(t), rows[0]['net_cents']);
    });
  });

  group('按日账单默认 7 行,更早的一按就出来', () {
    testWidgets('默认只列 7 天,并说清还有多少天没列', (t) async {
      await pumpFinance(t, financeFakeApi(daily: lastDays(30)));
      await pickPeriod(t, '近 90 天');
      expect(find.text('看更早的 23 天'), findsOneWidget,
          reason: '不说还有多少天,商家不知道自己没看全 —— '
              '这正是提现记录那条曾经犯过的错');
    });

    testWidgets('展开后 30 天一条不少', (t) async {
      await pumpFinance(t, financeFakeApi(daily: lastDays(30)));
      await pickPeriod(t, '近 90 天');
      await t.tap(find.text('看更早的 23 天'));
      await t.pump();
      final rowTexts = allTexts()
          .where((s) => RegExp(r'^\d{1,2}/\d{1,2}$').hasMatch(s))
          .toSet();
      expect(rowTexts, hasLength(30));
      expect(find.text('看更早的 23 天'), findsNothing,
          reason: '全列出来之后按钮该消失,不留一个点了没反应的按钮');
    });
  });

  /// #33 4.3 宽屏:≥620 的列宽上,单数单独成一列。
  group('宽屏两栏与按日表格', () {
    testWidgets('1200 宽:表头五列', (t) async {
      setPhoneViewport(t, const Size(1200, 1000));
      await t.pumpWidget(MaterialApp(
        theme: brandTheme(Brightness.light,
            density: SzDensity.operate, accentTone: 0),
        home: Scaffold(
          body: SizedBox(
              width: 1200,
              height: 1000,
              child: FinancePage(
                  api: financeFakeApi(daily: lastDays(7)), title: '账本')),
        ),
      ));
      await t.pump();
      await t.pump(const Duration(milliseconds: 400));

      for (final h in ['日期', '单数', '菜价', '平台', '实收']) {
        expect(find.text(h), findsWidgets, reason: '表头缺「$h」这一列');
      }
    });

    testWidgets('390 窄屏四列:菜价和单数合在一格', (t) async {
      await pumpFinance(t, financeFakeApi(daily: lastDays(7)));
      expect(find.text('菜价 · 单数'), findsOneWidget);
      expect(find.text('单数'), findsNothing,
          reason: '五列塞不进 390,单数和菜价合成一格');
    });
  });

  group('费率不许被整除截断', () {
    testWidgets('4.5% 的店,台面要写 4.5% —— 不是 4%', (t) async {
      // config.py 的档位表就有 0.045(500–999 单/月那一档),
      // 这不是极端输入。`0.045 * 100 ~/ 1` == 4
      await pumpFinance(t, financeFakeApi(rate: 0.045, daily: lastDays(1)));

      final texts = allTexts();
      expect(texts.where((s) => s == '平台 4%'), isEmpty,
          reason: '整数除法把 4.5% 截成了 4% —— '
              '在账目透明的台面上,平台把自己的抽成说小了 0.5 个点');
      expect(texts.where((s) => s.contains('4.5%')).length,
          greaterThanOrEqualTo(2),
          reason: '阶梯佣金卡和台面说的是同一个费率,同一屏上必须一致');
    });

    testWidgets('5% 的新店写「平台 5%」', (t) async {
      await pumpFinance(
          t, financeFakeApi(rate: 0.05, daily: lastDays(1, rate: 0.05)));
      expect(find.text('平台 5%'), findsOneWidget);
    });

    testWidgets('这一期没有流水时,退回按当前档位说,仍然不截断', (t) async {
      await pumpFinance(
          t,
          financeFakeApi(
              rate: 0.045, daily: [dayJson('2020-01-01', 3, 10000, 0.045)]));
      expect(find.text('平台 4.5%'), findsOneWidget,
          reason: '这个月一单没有也要说清这一档是多少,而且同样不许截断');
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
