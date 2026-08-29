import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:rider_app/profile_page.dart';
import 'package:superz_shared/superz_shared.dart';

import 'rider_fake_api.dart';

/// 黄金位那三个数字:来源对不对、放不放得下(#297)。
///
/// ## 这个测试锁的是三个已经在线上的 bug
///
/// **① 两个数恒为 0。** 老代码从主页传 `todayOrders`/`todayCents`,
/// 它们由 `_todayDone` 算 —— 而 `_todayDone` 从 `_mine` 里筛
/// `completed||delivered`,`_mine` 却只留 `accepted/ready/pickedUp`。
/// **两个集合不相交。** 每个骑手每一天看到的都是「今日完成 0 单」。
/// 就算筛对了也还是错的:源头 `myOrders()` 默认 `limit=20`。
///
/// **② 数字放不下。** 每格 108px,而「86.00」在 szMoney 22px 下要 111.3px,
/// 加「元」和间距共 124.6 —— `RenderFlex overflowed by 17 pixels`,
/// 1.4× 下溢出 65px。**只要日收入 ≥ ¥10 就溢出。**
/// 之前没人报,是因为 bug ① 让它永远显示「0.00」(4 字符,刚好塞得下)。
/// **修了①就会当场暴露②** —— 所以这两条必须一起锁。
///
/// **③「在线时长」量的不是今天。** `/riders/me/fatigue` 服务端注释写着
/// 「本次连续在线:取最近一条还没下线的会话」,没有开着的会话返回 0。
/// 中午下线吃个饭再上线,读数归零;收工回家打开写着 0.0 小时。
///
/// ## 为什么用「喂两个互相矛盾的值」来验来源
///
/// 断言「显示 8.2」本身证明不了它读的是哪个字段 —— 两个来源恰好相等时
/// 测试照样绿。所以 fatigue 和 worklog 故意喂**不一样**的数:
/// 只有读对了字段才可能显示对的那个。
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

  group('三个数来自 worklog,不来自订单列表', () {
    testWidgets('37 单 / 8.2 小时 / 215.00 元 —— 全部照服务端聚合的数显示', (t) async {
      await pump(
          t,
          fakeRiderApi(
            todayOrders: 37,
            todayMinutes: 492,
            todayEarnedCents: 21500,
          ));
      expect(find.text('37'), findsOneWidget);
      expect(find.text('8.2'), findsOneWidget);
      expect(find.text('215.00'), findsOneWidget);
    });

    testWidgets('订单列表返回什么都不影响这三个数', (t) async {
      // 一页 20 条**已完成**的单摆在那儿。老代码会拿它求和(而且求错),
      // 新代码根本不看它 —— 统计该服务端算,不该客户端凑
      await pump(
          t,
          fakeRiderApi(
            todayOrders: 37,
            todayEarnedCents: 21500,
            orders: [
              for (var i = 0; i < 20; i++)
                {
                  'order_no': 'SZ$i',
                  'merchant_id': 1,
                  'merchant_name': '楼下面馆',
                  'status': 'completed',
                  'items': <dynamic>[],
                  'food_cents': 2000,
                  'delivery_fee_cents': 500,
                  'total_cents': 2500,
                  'commission_cents': 0,
                  'discount_cents': 0,
                  'subsidy_cents': 0,
                  'refund_cents': 0,
                  'address': '某小区',
                  'lat': 30.66,
                  'lng': 104.08,
                  'created_at': '2026-08-21T12:00:00+08:00',
                },
            ],
          ));
      expect(find.text('37'), findsOneWidget);
      expect(find.text('215.00'), findsOneWidget);
      // 20 × ¥5 配送费 = ¥100。要是哪天又有人去拿订单列表求和,这条会红
      expect(find.text('100.00'), findsNothing);
    });

    testWidgets('「今日在线」读 worklog.today_minutes,不读 fatigue.online_minutes',
        (t) async {
      // 骑手中午下线吃饭又上线:本次会话才 12 分钟,但今天已经在线 8.2 小时。
      // 读错字段的话会显示 0.2
      await pump(t, fakeRiderApi(todayMinutes: 492, fatigueMinutes: 12));
      expect(find.text('8.2'), findsOneWidget,
          reason: '「今日在线」读成了本次会话时长 —— 那是 fatigue 的口径,不是今天的');
      expect(find.text('0.2'), findsNothing);
    });

    testWidgets('已下线(fatigue 返回 0)时今天的数照常显示', (t) async {
      // 收工回家打开 App:没有开着的会话,fatigue 返回 online_minutes=0。
      // 今天跑的 8.2 小时不该因此变成 0
      await pump(
          t,
          fakeRiderApi(
              todayMinutes: 492, fatigueMinutes: 0, fatigueLevel: 'none'));
      expect(find.text('8.2'), findsOneWidget);
      expect(find.text('0.0'), findsNothing);
    });
  });

  group('没数据给「—」,真的 0 给 0', () {
    testWidgets('worklog 拉不到:三个数都是「—」不是 0', (t) async {
      // 0 是一个**看起来像真值**的数,骑手会读它("我今天怎么才跑 0 单"),
      // 然后它又自己变了。占位符不会被误读
      await pump(t, fakeRiderApi(failing: {'/riders/me/worklog'}));
      expect(find.text('—'), findsNWidgets(3));
      expect(find.text('0'), findsNothing);
      expect(find.text('0.00'), findsNothing);
    });

    testWidgets('今天真的还没跑单:照写 0,不写「—」', (t) async {
      await pump(t,
          fakeRiderApi(todayOrders: 0, todayMinutes: 0, todayEarnedCents: 0));
      expect(find.text('0'), findsOneWidget);
      expect(find.text('0.0'), findsOneWidget);
      expect(find.text('0.00'), findsOneWidget);
      expect(find.text('—'), findsNothing);
    });
  });

  group('里程放周报,不放这张卡(#309)', () {
    testWidgets('今日卡上不出现公里数 —— 加一行会把入口挤出首屏', (t) async {
      await pump(t, fakeRiderApi(todayMeters: 42100));
      expect(find.textContaining('公里'), findsNothing,
          reason: '这张卡是「一眼看今天」的三个数。加第四行会把一个入口'
              '挤出首屏(见 profile_density_test:长辈版 1.4× 下要 ≥10 个,'
              '改版前只有 6,是调出来的)。里程去周报 —— '
              '「跑这些路值不值」本来就是去那儿分析的');
    });

    testWidgets('通往周报的那行还在 —— 它是里程的唯一入口', (t) async {
      await pump(t, fakeRiderApi(todayMeters: 42100));
      expect(find.textContaining('看周报'), findsOneWidget);
    });
  });

  group('溢出护栏:多大的数都不许画出格', () {
    // ¥0 / 平常一天 / 好的一天 / 周结算那种大数,各来一遍
    for (final cents in [0, 8600, 48600, 128650]) {
      for (final scale in [1.0, 1.4]) {
        for (final width in [320.0, 390.0]) {
          testWidgets('¥${(cents / 100).toStringAsFixed(2)} @$width $scale×',
              (t) async {
            await pump(t, fakeRiderApi(todayEarnedCents: cents),
                scale: scale, width: width);
            expect(t.takeException(), isNull,
                reason: '数字把那一格顶爆了 —— 值和单位要整体 FittedBox 缩');
            expect(textsPaintingOutside(t), isEmpty,
                reason: '有字画到盒子外面了(这类问题不抛异常,只能这样查)');
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
      await pump(t, fakeRiderApi(fatigueLevel: 'ok'));
      expect(find.textContaining('连续在线'), findsNothing);
    });

    testWidgets('fatigue 整个拉不到也不影响这一页', (t) async {
      // 疲劳提示挂了不该让骑手看不到今天挣了多少
      await pump(t, fakeRiderApi(failing: {'/riders/me/fatigue'}));
      expect(find.text('14'), findsOneWidget);
    });
  });

  group('这张卡不给关', () {
    // 用户端和商家端的黄金位卡都做成了「可以永久关掉」——**这一张刻意没做**,
    // 而且不是漏了。理由三条,任何一条单独成立都够:
    //
    // ① **它不是宣言,是数据。** 「宣言看一次就够」这条判据的前提是内容不变;
    //    今日完成/在线/收入每跑一单就变一次,关掉它等于关掉今天的账。
    //
    // ② **这一端的宣言本来就不在黄金位。** `_promises()` 是一张独立的
    //    SzLedgerCard,注释写着「**刻意在折叠线以下**……不该占黄金位那 110px」。
    //    也就是说骑手端早就用「放到折叠线以下」解决了同一个打扰问题,
    //    黄金位这里根本没有可关的宣言。
    //
    // ③ **卡底那行「配送费 100% 归你 · 看周报 →」是入口本身。**
    //    `RiderWeeklyPage` 全仓只有 `profile_page.dart` 这一个构造点,
    //    那行字是唯一告诉骑手这张卡能点的东西(profile_routes_test.dart
    //    已经拿一条用例锁着它)。把那一行做成可关 = 把周报变成暗手势。
    //
    // 外加一条:疲劳提醒也画在这张卡里。**可关闭的容器不该装安全提示。**
    testWidgets('没有关闭按钮', (t) async {
      await pump(t, fakeRiderApi());
      expect(find.byIcon(Icons.close), findsNothing,
          reason: '今日战报卡上出现了关闭键 —— 见本组注释:'
              '它是每 20 分钟变一次的数据,不是看一次就够的宣言');
    });

    testWidgets('「看周报 →」那一行也不给单独关', (t) async {
      await pump(t, fakeRiderApi());
      expect(find.textContaining('看周报'), findsOneWidget);
      // 那一行右边不许长出任何可点的小控件(关闭键/「不再显示」之类)。
      // 它是 RiderWeeklyPage 唯一的可供性,遮掉就等于删掉入口
      final row = find.ancestor(
          of: find.textContaining('看周报'), matching: find.byType(Row));
      expect(find.descendant(of: row.first, matching: find.byType(InkWell)),
          findsNothing,
          reason: '「看周报 →」那行里多了一个可点控件');
    });

    testWidgets('疲劳提醒在这张卡里 —— 可关闭的容器不该装安全提示', (t) async {
      await pump(
          t,
          fakeRiderApi(
              fatigueLevel: 'throttle', fatigueMessage: '已连续在线 12 小时,该歇了'));
      expect(find.text('已连续在线 12 小时,该歇了'), findsOneWidget);
      expect(find.byIcon(Icons.close), findsNothing,
          reason: '疲劳提醒所在的卡片可以被关掉');
    });
  });

  group('不放分数、等级、段位', () {
    testWidgets('页面上没有服务分/派单分/段位这类字样', (t) async {
      // /transparency/dispatch 的 never_do 里公开承诺过
      // 「不按骑手评分或等级差别对待」—— 这一页出现分数就是当众违背它
      await pump(t, fakeRiderApi());
      for (final banned in ['服务分', '安全分', '派单分', '青铜', '等级', '段位']) {
        expect(find.textContaining(banned), findsNothing,
            reason: '出现了「$banned」—— 见 profile_page.dart 类文档的红线');
      }
    });
  });
}
