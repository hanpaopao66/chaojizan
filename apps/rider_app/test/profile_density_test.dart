import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:rider_app/profile_page.dart';
import 'package:superz_shared/superz_shared.dart';

import 'rider_fake_api.dart';

/// 「我的」页的首屏入口密度。
///
/// ## 为什么拿数字锁
///
/// 密度这种事**没有报错** —— 功能全对、测试全绿,只是难用。
///
/// ## 设计稿 5i 之后的口径
///
/// #297 那一版把首屏压到 12 个入口(一张今日卡 + 4 格网格 + 两组列表)。
/// 5i 的首屏换了主角:身份卡、认证台面(实名 / 健康证 / 结算卡)、
/// 三个数、四条设置 —— 认证台面三行各带一句状态,比光杆入口高,
/// 所以首屏入口数降到 9(实测)。这是稿子的取舍:**跑单前置的三件事
/// 放到最上面**,比多挤两个入口进首屏更要紧。
///
/// 锁的是「别再往下掉」:掉了说明有人往上面加了高度,或者把分组头加回来了。
void main() {
  setUpRiderTest();

  /// 把「我的」页放进真机口径的可视区里:宽 390、高 [kFirstScreen]，
  /// 也就是**只给它首屏那么大的窗**。
  Future<void> pump(WidgetTester t, ApiClient api,
      {double scale = 1.0, double height = kFirstScreen}) async {
    // 折叠线以下的断言给足视口:ListView 是懒构建的,视口外的条目根本不建
    setPhoneViewport(t, Size(390, height > 844 ? height : 844));
    await t.pumpWidget(MediaQuery(
      data: MediaQueryData(textScaler: TextScaler.linear(scale)),
      child: MaterialApp(
        theme: brandTheme(Brightness.light),
        home: Scaffold(
          body: Align(
            alignment: Alignment.topLeft,
            child: SizedBox(
                width: 390,
                height: height,
                // 两个 tab 回调必须给 —— 真机上 main.dart 一直传。
                // 不传的话「我的订单」「我的钱包」的 onTap 是 null,
                // 密度会少数两个,而那是测试的问题不是页面的问题
                child: RiderProfilePage(
                    api: api, onOpenWallet: () {}, onOpenOrders: () {})),
          ),
        ),
      ),
    ));
    await t.pumpAndSettle();
  }

  group('首屏入口数', () {
    testWidgets('已上线跑单中:9 个', (t) async {
      await pump(t, fakeRiderApi(unread: 3));
      final n = visibleEntries(t);
      expect(n, greaterThanOrEqualTo(9),
          reason: '首屏入口掉到了 $n 个(5i 之后实测 9)——'
              '掉下来说明有人往上面加了高度,或者把分组头加回来了');
    });

    testWidgets('已下线:和跑单中一样', (t) async {
      await pump(t, fakeRiderApi(fatigueLevel: 'none', fatigueMinutes: 0));
      expect(visibleEntries(t), greaterThanOrEqualTo(9));
    });

    testWidgets('长辈版 1.4×:7 个', (t) async {
      await pump(t, fakeRiderApi(unread: 3), scale: 1.4);
      final n = visibleEntries(t);
      expect(n, greaterThanOrEqualTo(7), reason: '1.4× 下首屏只剩 $n 个入口');
    });

    testWidgets('疲劳提醒占一行,首屏仍有 8 个', (t) async {
      // 提示行是该出现的 —— 它比最后一个入口重要
      await pump(
          t,
          fakeRiderApi(
              fatigueLevel: 'remind', fatigueMessage: '已连续在线 8 小时,歇会儿'));
      expect(visibleEntries(t), greaterThanOrEqualTo(8));
    });

    testWidgets('三件待办都没办(认证台面多一行培训):首屏仍有 8 个', (t) async {
      await pump(
          t,
          fakeRiderApi(
              verifyStatus: 'unsubmitted',
              payoutConfigured: false,
              examPassed: false),
          height: kFirstScreen - 40);
      expect(visibleEntries(t, limit: kFirstScreen - 40),
          greaterThanOrEqualTo(8));
    });
  });

  group('认证台面:办好了写状态,没办写待办', () {
    testWidgets('三件都办好了 → 有效 / 尾号,没有待办字样', (t) async {
      await pump(t, fakeRiderApi());
      expect(find.text('有效'), findsOneWidget);
      expect(find.textContaining('尾号 4821'), findsOneWidget);
      expect(find.text('未登记'), findsNothing);
      expect(find.text('未通过'), findsNothing);
      expect(find.text('去提交'), findsNothing);
    });

    testWidgets('未实名 → 「去提交」', (t) async {
      await pump(t, fakeRiderApi(verifyStatus: 'unsubmitted'));
      expect(find.text('实名认证'), findsOneWidget);
      expect(find.text('去提交'), findsOneWidget);
    });

    testWidgets('被驳回 → 写「被驳回」不写「去提交」', (t) async {
      await pump(t, fakeRiderApi(verifyStatus: 'rejected'));
      expect(find.text('被驳回'), findsOneWidget);
    });

    testWidgets('审核中 → 写「审核中」,不催他', (t) async {
      // 球在平台这边,催骑手没有意义
      await pump(t, fakeRiderApi(verifyStatus: 'pending'));
      expect(find.text('审核中'), findsOneWidget);
      expect(find.text('去提交'), findsNothing);
    });

    testWidgets('收款账户未登记 → 提前告诉他,别等提现被顶回来', (t) async {
      await pump(t, fakeRiderApi(payoutConfigured: false));
      expect(find.text('未登记'), findsOneWidget);
    });

    testWidgets('培训没过 → 出现「未通过」', (t) async {
      await pump(t, fakeRiderApi(examPassed: false));
      expect(find.text('未通过'), findsWidgets);
    });

    testWidgets('三个接口全挂 → 一条也不报(宁可漏报不可误报)', (t) async {
      // 挂一个假的「你没实名」会让骑手白跑一趟认证页
      await pump(
          t,
          fakeRiderApi(failing: {
            '/riders/profile',
            '/payout-account',
            '/riders/exam/status',
          }));
      expect(find.text('去提交'), findsNothing);
      expect(find.text('未登记'), findsNothing);
      expect(find.text('未通过'), findsNothing);
    });
  });

  group('状态值:能变成值的 hint 就该变', () {
    testWidgets('结算卡已登记 → 写银行和尾号', (t) async {
      await pump(t, fakeRiderApi(payoutTail: '4821'));
      expect(find.textContaining('招商银行 · 尾号 4821'), findsOneWidget);
    });

    testWidgets('上岗培训显示「已通过」', (t) async {
      await pump(t, fakeRiderApi(examPassed: true));
      // 折叠线以下,给足高度再找
      await pump(t, fakeRiderApi(examPassed: true), height: 2000);
      expect(find.text('已通过'), findsOneWidget);
    });
  });

  group('立场表达走 footnote,不塞进每一行', () {
    testWidgets('规则组只有一句脚注,三条入口都是光杆', (t) async {
      await pump(t, fakeRiderApi(), height: 2000);
      expect(find.textContaining('派单公式与每个权重全部公开'), findsOneWidget);
      // 原来这三句分别挂在三条的 hint 上,各付 17px
      expect(find.text('完整公式与每个权重的理由,全部公开'), findsNothing);
      expect(find.text('有异议就申诉,平台人工复核'), findsNothing);
      expect(find.text('哪不好用、哪条规则不合理,一定有人看'), findsNothing);
    });

    testWidgets('没有 SzSectionTitle —— 块间用留白分,不用分组头', (t) async {
      await pump(t, fakeRiderApi(), height: 2000);
      expect(find.byType(SzSectionTitle), findsNothing,
          reason: '分组头回来了。四个连间距吃 104px,是两个多入口的地方');
    });
  });

  group('宽屏', () {
    testWidgets('720 限宽下不溢出、不切字', (t) async {
      // 外壳 SzNavScaffold 走 kContentMaxWidth(720),这里直接量限宽后的内容
      setPhoneViewport(t, const Size(1024, 900));
      await t.pumpWidget(MaterialApp(
        theme: brandTheme(Brightness.light),
        home: Scaffold(
          body: Center(
            child: SizedBox(
                width: kContentMaxWidth,
                child: RiderProfilePage(
                    api: fakeRiderApi(unread: 3),
                    onOpenWallet: () {},
                    onOpenOrders: () {})),
          ),
        ),
      ));
      await t.pumpAndSettle();
      expect(t.takeException(), isNull);
      expect(textsPaintingOutside(t), isEmpty);
    });
  });
}
