import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:rider_app/appeal_page.dart';
import 'package:rider_app/dispatch_spec_page.dart';
import 'package:rider_app/heatmap_page.dart';
import 'package:rider_app/messages_page.dart';
import 'package:rider_app/onboarding_page.dart';
import 'package:rider_app/profile_page.dart';
import 'package:rider_app/reviews_page.dart';
import 'package:rider_app/weekly_page.dart';
import 'package:superz_shared/superz_shared.dart';

import 'rider_fake_api.dart';

/// 「我的」页每一个入口都得真的去一个地方(#297)。
///
/// ## 这个测试防的是什么
///
/// 改版前这一页 16 个入口里有 8 个**不去它说的地方**:
///
/// - 6 个走 `_toWallet()` —— 切到钱包 tab,再弹一条
///   「已跳到钱包页,相关入口在『保障与规则』」叫骑手自己往下翻;
/// - 2 个走 `_snack()` —— 连跳都不跳,只弹一句话告诉你该去哪找。
///
/// 而这 8 个入口的目标页**全都已经存在**(`RiderAccidentPage`、
/// `EmergencyContactsPage`、`RiderGearPage`、`RiderInsurancePage`、
/// `RiderExamPage`、`PayoutAccountPage`、`RiderAppealPage`),
/// 差的只是一行 `onTap`。
///
/// 最糟的是**事故上报**:骑手出了事故,点「事故上报」,
/// App 把他扔到钱包页弹个 toast。这不是密度问题,是安全问题。
///
/// ## 判据为什么是「不许弹 SnackBar」
///
/// 光断言「切了 tab 或 push 了页」拦不住 `_toWallet` —— 它**确实**切了 tab。
/// 真正的区别是:到位的入口什么也不用说,没到位的入口才需要
/// 再弹一句话解释「其实你要的东西在别处」。
/// **那句解释本身就是没接线的自白**,所以判据落在它身上。
int _seq = 0;

void main() {
  setUpRiderTest();

  /// 这一页应该有的全部入口,以及点下去该发生什么。
  ///
  /// `page` = 该 push 出来的页面类型;`tab` = 该切到的 tab
  /// (只有「我的钱包」「我的订单」两个,它们本来就是 tab)。
  const wallet = Object();
  const orders = Object();
  final expected = <String, Object>{
    // 网格
    '我的订单': orders,
    '哪儿有单': RiderHeatmapPage,
    '顾客评价': RiderReviewsPage,
    '消息': RiderMessagesPage,
    // 保障
    '意外保障': RiderInsurancePage,
    '紧急联系人': EmergencyContactsPage,
    '事故上报': RiderAccidentPage,
    '装备申领': RiderGearPage,
    // 账目
    '我的钱包': wallet,
    '收款账户': PayoutAccountPage,
    '联系平台客服': SupportPage,
    // 规则
    '抢单怎么排的': DispatchSpecPage,
    '规则中心': RiderRulesPage,
    '违规申诉': RiderAppealPage,
    '上岗培训': RiderExamPage,
    '给平台提意见': RiderFeedbackPage,
  };

  /// 点一个入口,回答三件事:push 出了什么页 / 切了哪个 tab / 弹没弹 SnackBar。
  Future<({Type? pushed, Object? tab, bool snacked})> tapEntry(
      WidgetTester t, String title,
      {ApiClient? api}) async {
    Object? tab;
    final observer = _PushSpy();
    // ⚠️ 视口给够高(390×3000),让整个 ListView 一次建完。
    //
    // 用真机高度 + `scrollUntilVisible` 会**假红**:ListView 是懒构建的,
    // 滚过去的条目又被回收,`dragUntilVisible` 拿 element 时扑空报
    // 「Bad state: No element」—— 那是测试脚手架的问题,不是页面的问题。
    // 这个测试问的是「点下去去哪」,不是「一屏能看见几个」;
    // 后者是 profile_density_test.dart 的事,那里才需要 645 的口径
    setPhoneViewport(t, const Size(390, 3000));
    await t.pumpWidget(MaterialApp(
      // ⚠️ 每次换一个 key,强制整棵树重建。
      //
      // 不换的话 `pumpWidget` 会**复用**上一次的 element 树,而上一次点击
      // push 出来的页还压在 Navigator 上 —— 被完全盖住的不透明路由,
      // 它底下那一页会被标成 offstage,`find.text` 默认跳过 offstage,
      // 于是第二个入口开始全部报「找不到」。单独跑每条都过、
      // 连起来跑就红,就是这个
      key: ValueKey(_seq++),
      theme: brandTheme(Brightness.light),
      navigatorObservers: [observer],
      home: Scaffold(
        body: RiderProfilePage(
          api: api ?? fakeRiderApi(),
          onOpenWallet: () => tab = wallet,
          onOpenOrders: () => tab = orders,
        ),
      ),
    ));
    await t.pumpAndSettle();

    final target = find.text(title);
    expect(target, findsWidgets, reason: '这一页上找不到「$title」这个入口');
    // 首页那次 push 也会被 didPush 记下 —— 不清掉的话「什么也没 push」
    // 会读成上一条的残留,断言就变成了空断言
    observer.lastPushed = null;
    await t.tap(target.first);
    // 一帧就够:路由的 didPush 是同步发的,SnackBar 也已经插进树里。
    // 不 settle —— 被 push 的页会去拉它自己的数据,那不是这个测试的事
    await t.pump();
    final snacked = find.byType(SnackBar).evaluate().isNotEmpty;
    final pushed = observer.lastPushed;
    // 目标页构建时可能因为假后端返回 {} 而报错,与本测试无关,清掉
    t.takeException();
    return (pushed: pushed, tab: tab, snacked: snacked);
  }

  group('每个入口都真的去一个地方', () {
    // 这一组是**总法**:不写死入口清单,页面上有几个就验几个。
    // 以后加入口不用改这个测试,加错了它自己会红
    testWidgets('没有任何一个入口只是弹一句话告诉你该去哪找', (t) async {
      setPhoneViewport(t, const Size(390, 844));
      await t.pumpWidget(MaterialApp(
        theme: brandTheme(Brightness.light),
        home: Scaffold(body: RiderProfilePage(api: fakeRiderApi())),
      ));
      await t.pumpAndSettle();
      final titles = <String>[
        for (final e in find.byType(SzEntryTile).evaluate())
          (e.widget as SzEntryTile).title,
        for (final e in find.byType(SzIconGrid).evaluate())
          ...(e.widget as SzIconGrid).items.map((i) => i.label),
      ];
      expect(titles, isNotEmpty);

      final offenders = <String>[];
      for (final title in titles) {
        final r = await tapEntry(t, title);
        if (r.snacked || (r.pushed == null && r.tab == null)) {
          offenders.add('$title(${r.snacked ? "弹了 SnackBar" : "什么也没发生"})');
        }
      }
      expect(offenders, isEmpty,
          reason: '这些入口没有真的接线,只是告诉你该去哪找:\n  ${offenders.join("\n  ")}');
    });
  });

  group('每个入口去的是哪一页', () {
    for (final entry in expected.entries) {
      testWidgets('${entry.key} → ${entry.value}', (t) async {
        final r = await tapEntry(t, entry.key);
        expect(r.snacked, isFalse,
            reason: '「${entry.key}」弹了 SnackBar —— 到位的入口不需要再解释一句');
        if (entry.value is Type) {
          expect(r.pushed, entry.value,
              reason: '「${entry.key}」该 push 出 ${entry.value},'
                  '实际是 ${r.pushed ?? "什么也没 push"}');
        } else {
          expect(r.tab, same(entry.value), reason: '「${entry.key}」该切 tab,实际没切');
        }
      });
    }

    testWidgets('事故上报是安全入口:一步到位,不经过钱包 tab', (t) async {
      // 单独拎出来,因为它是这一页唯一一个「点晚了会出人命」的入口。
      // 中间多一跳、多一个要读的 toast,都是在出事的时候加摩擦
      final r = await tapEntry(t, '事故上报');
      expect(r.pushed, RiderAccidentPage);
      expect(r.tab, isNull, reason: '事故上报把骑手扔去了钱包 tab');
      expect(r.snacked, isFalse);
    });

    testWidgets('违规申诉进的是列表模式(order 传 null)', (t) async {
      // RiderAppealPage 的构造函数注释写着「从「我的」进来时为 null(只看列表)」
      // —— 这个页当初就是为这个入口写的,线一直没接上
      final r = await tapEntry(t, '违规申诉');
      expect(r.pushed, RiderAppealPage);
    });
  });

  group('今日卡是「我的周报」唯一的入口,不许当装饰删掉', () {
    testWidgets('卡底那行可供性文字在', (t) async {
      setPhoneViewport(t, const Size(390, 844));
      await t.pumpWidget(MaterialApp(
        theme: brandTheme(Brightness.light),
        home: Scaffold(body: RiderProfilePage(api: fakeRiderApi())),
      ));
      await t.pumpAndSettle();
      // 周报没有自己的列表条 —— 它是今日卡的落点。
      // 那行「看周报 →」是**唯一**告诉骑手这张卡能点的东西,
      // 删了它周报就真的没入口了
      expect(find.textContaining('看周报'), findsOneWidget,
          reason: '卡底的「看周报 →」没了 —— 周报现在没有任何入口');
    });

    testWidgets('点今日卡进周报', (t) async {
      final r = await tapEntry(t, '今日在线');
      expect(r.pushed, RiderWeeklyPage);
      expect(r.snacked, isFalse);
    });
  });
}

/// 记下最近一次 push 的是什么页。
class _PushSpy extends NavigatorObserver {
  Type? lastPushed;

  @override
  void didPush(Route<dynamic> route, Route<dynamic>? previousRoute) {
    final page = route is MaterialPageRoute ? route.builder : null;
    if (page == null) return;
    // builder 还没跑过,拿不到实例 —— 跑一次拿类型。
    // 目标页的 initState 会去拉数据,拉不到不影响这里取类型
    try {
      lastPushed = page(_ctx!).runtimeType;
    } catch (_) {
      lastPushed = null;
    }
  }

  BuildContext? get _ctx => navigator?.context;
}
