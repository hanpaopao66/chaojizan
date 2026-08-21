import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:rider_app/profile_page.dart';
import 'package:superz_shared/superz_shared.dart';

import 'rider_fake_api.dart';

/// 角标只给「你还有事要做」的(#297)。
///
/// ## 每个候选都去核过接口
///
/// | 候选 | 挂不挂 | 为什么 |
/// |---|---|---|
/// | **消息未读** | ✅ 挂 | `unread` 是服务端 `COUNT`,和 page_size 无关 |
/// | 实名/收款/培训 | 状态值不是角标 | 服务端扁平枚举/bool,是真的;但它们是「状态」,「未登记」比一个红点有信息量 |
/// | 申诉有结果 | ❌ | 能算出「有结果」,**算不出「他看没看过」**。而结果本来就走消息中心推 —— 挂了会变成:骑手清掉消息、回来一看角标还在 |
/// | 装备可申领 | ❌ | 服务端**根本没有**「可申领」这个概念,没配额没冷却。「可申领 3 件」是客户端编的 |
/// | 今日已投保 | ❌ **而且会错** | `/riders/insurance` 今天没有行 = 「今天还没上过线」,不是「没保障」。挂「未投保」会在每个骑手每天早上误报一次 |
/// | 配送异常待处理 | ❌ | `open` 的意思是**平台在处理**,不是骑手要做什么 |
/// | 收入合计 | ❌ | `/riders/earnings` 硬 `LIMIT 100` 且无总数字段 |
///
/// ## 为什么反向断言比正向断言重要
///
/// 「消息有角标」这条谁都不会改坏。会出问题的是**下一个人加角标** ——
/// 「装备申领挂个红点吧,提醒骑手去领」听起来完全合理,
/// 而它会在每个骑手每天早上误报一次,骑手点进去发现什么也不用做。
/// **第三次之后他就不再信这个红点了**,连消息那个真的也不信。
///
/// 角标的价值全在于它从不说谎,所以这一组是**禁止清单**。
void main() {
  setUpRiderTest();

  Future<void> pump(WidgetTester t, ApiClient api,
      {double height = 2000}) async {
    setPhoneViewport(t, Size(390, height));
    await t.pumpWidget(MaterialApp(
      theme: brandTheme(Brightness.light),
      home: Scaffold(
          body: RiderProfilePage(
              api: api, onOpenWallet: () {}, onOpenOrders: () {})),
    ));
    await t.pumpAndSettle();
  }

  /// 页面上真正显示出来的角标个数(`isLabelVisible` 为真的那些)。
  int badgeCount(WidgetTester t) => find
      .byType(Badge)
      .evaluate()
      .where((e) => (e.widget as Badge).isLabelVisible)
      .length;

  group('全页只有一个角标', () {
    testWidgets('有未读时:恰好一个,数字是未读数', (t) async {
      await pump(t, fakeRiderApi(unread: 3));
      expect(badgeCount(t), 1, reason: '角标不止一个了 —— 见本文件的禁止清单');
      expect(find.text('3'), findsOneWidget);
    });

    testWidgets('未读为 0:一个角标都没有', (t) async {
      await pump(t, fakeRiderApi(unread: 0));
      expect(badgeCount(t), 0);
      expect(find.text('0'), findsNothing, reason: '0 不该显示成角标');
    });

    testWidgets('未读数拉不到:当 0,不显角标,入口照常在', (t) async {
      await pump(t, fakeRiderApi(failing: {'/riders/me/messages'}));
      expect(badgeCount(t), 0);
      expect(find.text('消息'), findsOneWidget);
    });

    testWidgets('未读很多:显示 20+ 不显示猜出来的数', (t) async {
      // 列表首页一次只拉得到 20 条,显示 21 会是**猜**的
      await pump(t, fakeRiderApi(unread: 57));
      expect(find.text('20+'), findsOneWidget);
    });
  });

  group('禁止清单:这些入口一律不许挂角标', () {
    // 挂在图标上的角标属于哪个入口 —— 按角标矩形落在谁的热区里判定
    List<String> badgedEntries(WidgetTester t) {
      final out = <String>[];
      for (final b in find.byType(Badge).evaluate()) {
        if (!(b.widget as Badge).isLabelVisible) continue;
        final box = b.renderObject! as RenderBox;
        final rect = box.localToGlobal(Offset.zero) & box.size;
        for (final e in find.byType(SzEntryTile).evaluate()) {
          final tb = e.renderObject! as RenderBox;
          final tr = tb.localToGlobal(Offset.zero) & tb.size;
          if (tr.overlaps(rect)) out.add((e.widget as SzEntryTile).title);
        }
      }
      return out;
    }

    testWidgets('保障组四条(含装备申领、意外保障)都没有角标', (t) async {
      await pump(t, fakeRiderApi(unread: 5));
      final badged = badgedEntries(t);
      for (final banned in ['意外保障', '紧急联系人', '事故上报', '装备申领']) {
        expect(badged, isNot(contains(banned)),
            reason: '「$banned」挂了角标。见本文件的禁止清单 —— '
                '尤其是意外保障:今天没有登记行意味着"今天还没上过线",'
                '不是"没保障",挂上去会每天早上误报一次');
      }
    });

    testWidgets('违规申诉、规则中心、收款账户都没有角标', (t) async {
      await pump(t, fakeRiderApi(unread: 5, payoutConfigured: false));
      final badged = badgedEntries(t);
      for (final banned in ['违规申诉', '规则中心', '收款账户', '联系平台客服']) {
        expect(badged, isNot(contains(banned)), reason: '「$banned」挂了角标');
      }
    });

    testWidgets('开工准备三件待办用带色状态值,不用数字角标', (t) async {
      await pump(
          t,
          fakeRiderApi(
              unread: 0,
              verifyStatus: 'unsubmitted',
              payoutConfigured: false,
              examPassed: false));
      // 三条待办全在,但一个角标也没有 ——
      // 「未登记」比一个红点有信息量,而红点还得让人点进去才知道是什么
      expect(find.text('去提交'), findsOneWidget);
      expect(find.text('未登记'), findsOneWidget);
      expect(find.text('未通过'), findsWidgets);
      expect(badgeCount(t), 0);
    });
  });

  group('角标不改变布局', () {
    testWidgets('有没有角标,网格一样高', (t) async {
      await pump(t, fakeRiderApi(unread: 0));
      final bare = t.getSize(find.byType(SzIconGrid)).height;
      await pump(t, fakeRiderApi(unread: 12));
      final badged = t.getSize(find.byType(SzIconGrid)).height;
      expect(badged, bare, reason: '角标把网格顶高了 —— 它该浮在图标角上');
    });
  });
}
