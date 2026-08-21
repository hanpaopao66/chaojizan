import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:rider_app/profile_page.dart';
import 'package:superz_shared/superz_shared.dart';

import 'rider_fake_api.dart';

/// 「我的」页的首屏入口密度(#297)。
///
/// ## 为什么拿数字锁
///
/// 密度这种事**没有报错** —— 功能全对、测试全绿,只是难用。
/// 改版前真机 390×844 上首屏只看得到 **7** 个入口:一张不可点的 128px
/// 数据卡,加四个 `SzSectionTitle`(每个连间距 26px,四个就是 104px,
/// 相当于两个多入口的地方),剩下的位置放六条带 hint 的列表。
///
/// 改完是 **12**。省下来的高度来自三处:去掉四个分组头(−104px)、
/// 三句立场表达从三条 hint 收进一条 footnote(−11px)、
/// 今日卡的口径行从两行压到一行(−18px)。
///
/// ## 算式(390×844,可视区 645)
///
/// ```
/// 12   顶部 padding
/// +110 今日战报卡(整卡可点)           → 122   1 个
/// +12  留白                            → 134
/// +82  网格 4 格                       → 216   4 个(累计 5)
/// +12                                  → 228
/// +240 保障组 4 条                     → 468   4 个(累计 9)
/// +12                                  → 480
/// +142 账目组 3 条                     → 622   3 个(累计 12)
/// +12                                  → 634
///      规则组第一条底 = 634+1+46 = 681 > 645  ✗
/// ```
///
/// 剩 23px 吃不到第 13 个(规则组第一条要 47px)。想凑的话砍
/// 「意外保障」或「装备申领」的 hint 各能省 17px —— **不建议**:
/// 为 2px 动保障组那几句是亏的。
void main() {
  setUpRiderTest();

  /// 把「我的」页放进真机口径的可视区里:宽 390、高 [kFirstScreen]，
  /// 也就是**只给它首屏那么大的窗**。
  Future<void> pump(WidgetTester t, ApiClient api,
      {double scale = 1.0, double height = kFirstScreen}) async {
    setPhoneViewport(t, const Size(390, 844));
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
    testWidgets('已上线跑单中:12 个(改版前 7)', (t) async {
      await pump(t, fakeRiderApi(unread: 3));
      final n = visibleEntries(t);
      expect(n, greaterThanOrEqualTo(12),
          reason: '首屏入口掉到了 $n 个。改版前是 7,这一版量到 12 ——'
              '掉下来说明有人往上面加了高度,或者把分组头加回来了');
    });

    testWidgets('已下线:和跑单中一样 12 个', (t) async {
      // 下线只影响 AppBar 上那个开关和疲劳提示行,不影响入口排布。
      // 今天的数照常显示(worklog 按自然日算,与有没有开着的会话无关)
      await pump(t, fakeRiderApi(fatigueLevel: 'none', fatigueMinutes: 0));
      expect(visibleEntries(t), greaterThanOrEqualTo(12));
    });

    testWidgets('长辈版 1.4×:10 个(改版前 6)', (t) async {
      await pump(t, fakeRiderApi(unread: 3), scale: 1.4);
      final n = visibleEntries(t);
      expect(n, greaterThanOrEqualTo(10), reason: '1.4× 下首屏只剩 $n 个入口');
    });

    testWidgets('疲劳提醒占一行,首屏仍有 11 个', (t) async {
      // 提示行是该出现的 —— 它比第 12 个入口重要
      await pump(
          t,
          fakeRiderApi(
              fatigueLevel: 'remind', fatigueMessage: '已连续在线 8 小时,歇会儿'));
      expect(visibleEntries(t), greaterThanOrEqualTo(11));
    });

    testWidgets('未通过实名认证(顶部横幅吃掉 40px):11 个', (t) async {
      // main.dart 的 _verifyBanner 在每个 tab 上方常驻,约 40px。
      // 开工准备块这时候会出现,把三件待办顶到首屏
      await pump(
          t,
          fakeRiderApi(
              verifyStatus: 'unsubmitted',
              payoutConfigured: false,
              examPassed: false),
          height: kFirstScreen - 40);
      expect(visibleEntries(t, limit: kFirstScreen - 40),
          greaterThanOrEqualTo(11));
    });
  });

  group('开工准备块:只在真有事要做时才存在', () {
    testWidgets('三件都办好了 → 整块不渲染', (t) async {
      await pump(t, fakeRiderApi());
      expect(find.text('实名认证'), findsNothing);
      expect(find.text('未登记'), findsNothing);
      expect(find.text('未通过'), findsNothing);
    });

    testWidgets('未实名 → 出现一条带 danger 语气的「实名认证」', (t) async {
      await pump(t, fakeRiderApi(verifyStatus: 'unsubmitted'));
      expect(find.text('实名认证'), findsOneWidget);
      expect(find.text('去提交'), findsOneWidget);
    });

    testWidgets('被驳回 → 写「被驳回」不写「去提交」', (t) async {
      await pump(t, fakeRiderApi(verifyStatus: 'rejected'));
      expect(find.text('被驳回'), findsOneWidget);
    });

    testWidgets('审核中 → 不催他(pending 不算待办)', (t) async {
      // 球在平台这边,催骑手没有意义
      await pump(t, fakeRiderApi(verifyStatus: 'pending'));
      expect(find.text('实名认证'), findsNothing);
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
    testWidgets('收款账户已登记 → 同行右对齐显示尾号,零额外高度', (t) async {
      await pump(t, fakeRiderApi(payoutTail: '4821'));
      expect(find.text('尾号 4821'), findsOneWidget);
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
