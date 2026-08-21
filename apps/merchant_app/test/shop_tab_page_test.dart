import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:merchant_app/shop_tab.dart';
import 'package:package_info_plus/package_info_plus.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:superz_shared/superz_shared.dart';

import 'shop_fake_api.dart';

/// 店铺页:入口密度、待办数字的来源、以及几条不许被密度改造碰掉的东西。
///
/// ## 这个测试防的是什么
///
/// 改版前这一页是 6 个分组、33 个入口从上到下排成一条 3045px 的长列 ——
/// 真机 390×844 上首屏只看得到 **5 个入口**,而「售后待处理」在第四屏。
/// 订单页的待办行点「售后待处理 N」切过来,落地要再滚两千多像素。
///
/// 密度这种事**没有报错**:功能全对、旧测试全绿,只是难用。
///
/// ## 为什么不用源码文本断言
///
/// 这一页自己就是反例。旧测试用 `contains('controller: _announcement')`
/// 锁「公告输入框留在页面里」—— 公告搬进弹层之后那行文本还在(弹层里也用
/// 同一个 controller),断言照样绿。**文本在,行为没了。**
/// 所以这里一律真渲染、量矩形。
void setPhoneViewport(WidgetTester tester, Size logical) {
  tester.view
    ..devicePixelRatio = 3.0
    ..physicalSize = logical * 3.0;
  addTearDown(tester.view.reset);
}

void main() {
  // 390×844 的机器上 ListView 拿到的可视高度:
  //   844 − 47(顶部安全区) − 56(AppBar) − 96(底部导航 62 + 底部安全区 34)
  const firstScreen = 645.0;

  /// 证照横幅在场时店铺页剩下的可视高度。
  ///
  /// `LicenseBanner` 挂在 `main.dart` 的 body 里、**横跨所有 tab**
  /// (它是唯一一件"到点就自动出事"的事:过期 → 7 天宽限 → 自动停业),
  /// 所以它不在 ShopTabPage 内部,但它实打实吃掉 84px。
  const withLicenseBanner = firstScreen - 84;

  /// [limit] 以内**完整可见**的可点入口个数。判据是「有 onTap 的 InkWell 矩形」:
  /// - 底边超出可视区的不算(露一半的入口扫不到也点不安心);
  /// - 嵌套的只算最里面那个(身份行里套着换门头照的圆按钮,算一个)。
  ///
  /// 数的是**用户的问题**(「不滚动我能点到几样东西」),不是某个组件类型 ——
  /// 这样重排、把列表换成网格都不会让这个数字失真。
  int visibleEntries(WidgetTester t, {double limit = firstScreen}) {
    final rects = <Rect>[];
    for (final element in find.byType(InkWell).evaluate()) {
      final w = element.widget as InkWell;
      if (w.onTap == null) continue;
      final box = element.renderObject as RenderBox?;
      if (box == null || !box.hasSize) continue;
      final rect = box.localToGlobal(Offset.zero) & box.size;
      if (rect.isEmpty || rect.bottom > limit) continue;
      rects.add(rect);
    }
    rects.sort((a, b) => (a.width * a.height).compareTo(b.width * b.height));
    final kept = <Rect>[];
    for (final r in rects) {
      if (kept.any((k) => r.contains(k.topLeft) && r.contains(k.bottomRight))) {
        continue;
      }
      kept.add(r);
    }
    return kept.length;
  }

  /// 某段文字的矩形(用来验"它在不在首屏""它在不在另一样东西上面")。
  Rect rectOf(WidgetTester t, Finder f) {
    final box = t.renderObject<RenderBox>(f);
    return box.localToGlobal(Offset.zero) & box.size;
  }

  /// 竖直区间 [top, bottom) 内出现的所有文字。
  List<String> textsInBand(WidgetTester t, double top, double bottom) {
    final out = <String>[];
    for (final e in find.byType(Text).evaluate()) {
      final data = (e.widget as Text).data;
      if (data == null) continue;
      final box = e.renderObject as RenderBox?;
      if (box == null || !box.hasSize) continue;
      final r = box.localToGlobal(Offset.zero) & box.size;
      if (r.top >= top && r.bottom <= bottom) out.add(data);
    }
    return out;
  }

  /// 把店铺页放进真机口径的可视区:宽 [width]、高 [boxHeight]。
  ///
  /// ⚠️ **[viewHeight] 必须 ≥ [boxHeight]。** `SizedBox` 会被父级约束夹住 ——
  /// 渲染视口只有 844 时,写 `SizedBox(height: 3400)` 拿到的仍是 844,
  /// ListView 因此只建 前一千多像素。踩过一次:
  /// 「首屏没有 100 条」和「整页压根没渲染到那一行」长得一模一样,
  /// 断言会假绿。所以视口和盒子一起放大。
  Future<void> pumpShop(
    WidgetTester t,
    ApiClient api, {
    double scale = 1.0,
    double width = 390,
    double boxHeight = firstScreen,
    double? viewHeight,
    VoidCallback? onOpenFinance,
  }) async {
    setPhoneViewport(t, Size(width, viewHeight ?? 844));
    await t.pumpWidget(MediaQuery(
      data: MediaQueryData(textScaler: TextScaler.linear(scale)),
      child: MaterialApp(
        theme: brandTheme(Brightness.light, density: SzDensity.operate),
        home: Scaffold(
          body: Align(
            alignment: Alignment.topLeft,
            child: SizedBox(
              width: width,
              height: boxHeight,
              child: ShopTabPage(api: api, onOpenFinance: onOpenFinance),
            ),
          ),
        ),
      ),
    ));
    await t.pumpAndSettle();
  }

  /// 整页渲染(验"某一行存不存在""它在哪一屏"用)。视口和盒子一起给到 3600。
  Future<void> pumpShopFull(WidgetTester t, ApiClient api,
          {VoidCallback? onOpenFinance}) =>
      pumpShop(t, api,
          boxHeight: 3600, viewHeight: 3600, onOpenFinance: onOpenFinance);

  Future<ApiClient> loggedIn({
    Map<String, dynamic>? shop,
    List<Map<String, dynamic>> afterSales = const [],
    List<Map<String, dynamic>> reviews = const [],
    Map<String, dynamic>? prep,
    Map<String, dynamic>? todos,
    Map<String, dynamic>? tier,
    void Function(String path)? onRequest,
  }) async {
    SharedPreferences.setMockInitialValues({});
    final api = shopFakeApi(
      shop: shop,
      afterSales: afterSales,
      reviews: reviews,
      prep: prep,
      todos: todos,
      tier: tier,
      onRequest: onRequest,
    );
    await api.login('13800000009', 'pw');
    return api;
  }

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

  group('顾客评价的数字不许是从一页列表里数出来的', () {
    testWidgets('总数走 shop.ratingCount,不是 _reviews.length', (t) async {
      // 服务端 /merchants/me/reviews 是 .limit(100)(reviews.py:334)。
      // 一家有 312 条评价的店,列表只会回 100 条 —— 拿 length 去标「N 条」
      // 就会永远显示 100,而且**错得悄无声息**。
      // 这和用户端刚修掉的 myOrders() limit=20 算「累计」是同一形状。
      final api = await loggedIn(
        shop: shopJson(ratingCount: 312),
        reviews: [for (var i = 0; i < 100; i++) reviewJson(i, reply: '谢谢')],
      );
      await pumpShopFull(t, api);
      expect(find.textContaining('312'), findsWidgets,
          reason: '评价总数应显示 shop.ratingCount(312),'
              '现在显示的是被 limit 截断的那一页的长度');
      expect(find.text('100 条'), findsNothing,
          reason: '「100 条」正是 limit=100 截出来的假总数');
    });

    testWidgets('待回复走服务端 todos,不是客户端 where 出来的', (t) async {
      // 列表这一页里 100 条全回复过了,但服务端 todos 说还有 4 条差评没回
      // (近 7 天 ≤3 星未回,merchants.py:3377)—— 客户端数不出这个 4
      final api = await loggedIn(
        shop: shopJson(ratingCount: 312),
        reviews: [for (var i = 0; i < 100; i++) reviewJson(i, reply: '谢谢')],
        todos: todosJson(badUnreplied: 4),
      );
      await pumpShopFull(t, api);
      expect(find.textContaining('4 条待回复'), findsOneWidget,
          reason: '待回复数应来自 todos.bad_reviews_unreplied');
    });

    testWidgets('不再为了数评价去拉整页评价列表', (t) async {
      final hit = <String>[];
      final api = await loggedIn(onRequest: hit.add);
      await pumpShopFull(t, api);
      expect(hit, isNot(contains('/merchants/me/reviews')),
          reason: '拉 100 条评价只为了在入口上显示一个数字 —— '
              'shop.ratingCount 和 todos 都已经有了');
    });
  });

  group('承诺页的「去对账页验」不能是个点了没反应的按钮', () {
    testWidgets('onOpenFinance 一路传到 MerchantPromisesPage', (t) async {
      // 这个平台的立场是「承诺可自验」。自验按钮坏掉比密度严重得多:
      // ShopTabPage 收了 onOpenFinance(:27,:32)、main.dart 也传了进来,
      // 但 build 里一次没用,构造 MerchantPromisesPage 时也没往下传 ——
      // 于是 promises_page.dart:195 的 widget.onOpenFinance?.call() 永远是空操作,
      // 商家点「对账页看你的真实费率」只会把承诺页关掉,然后什么也不发生
      var opened = false;
      final api = await loggedIn();
      await pumpShopFull(t, api, onOpenFinance: () => opened = true);

      await t.tap(find.text('平台对你的承诺'));
      await t.pumpAndSettle();
      expect(find.text('这五条都能自己验'), findsOneWidget,
          reason: '没进到承诺页');

      await t.tap(find.text('佣金 5% 封顶,而且只降不升'));
      await t.pumpAndSettle();
      expect(opened, isTrue,
          reason: '承诺页里的「去对账页验」点了没反应 —— '
              'onOpenFinance 断在 ShopTabPage');
    });
  });

  group('首屏密度 —— 这一页唯一的验收标准', () {
    testWidgets('正常营业:首屏至少 17 个入口', (t) async {
      final api = await loggedIn();
      await pumpShop(t, api);
      final n = visibleEntries(t);
      expect(n, greaterThanOrEqualTo(17),
          reason: '首屏只看得到 $n 个入口。改版前是 5 个,'
              '这一页的全部意义就是把这个数字提上来');
    });

    testWidgets('证照横幅在场:横幅吃掉 84px,首屏仍有 15 个', (t) async {
      final api = await loggedIn(
        shop: shopJson(licenseStage: 'soon', licenseDaysLeft: 23),
      );
      await pumpShop(t, api);
      final n = visibleEntries(t, limit: withLicenseBanner);
      expect(n, greaterThanOrEqualTo(15),
          reason: '横幅一分不缩(它是到点自动停业的提醒),'
              '但也不该把整页挤没(当前 $n)');
    });

    testWidgets('有售后待处理:售后块置顶,且首屏仍有 12 个入口', (t) async {
      // 订单页的待办行「售后待处理 N」点了就切到这一页(main.dart:788)。
      // 改版前它在 y≈2170 —— 商家点了待办,落地要再滚两千多像素才找得到
      final api = await loggedIn(
        afterSales: [afterSaleJson()],
        todos: todosJson(afterSales: 1),
      );
      await pumpShop(t, api);
      expect(rectOf(t, find.text('同意退款')).bottom,
          lessThanOrEqualTo(firstScreen),
          reason: '售后的处理按钮不在首屏 —— 商家从待办点过来要现找');
      final n = visibleEntries(t);
      expect(n, greaterThanOrEqualTo(12), reason: '当前 $n');
    });

    // 改造前后的对比数字从这里出。**只打印不断言** —— 断言在上面。
    // 这条的用处是让「改了多少」有一份可复现的记录:
    // `git stash` 掉 lib/ 的改动再跑一次,拿到的就是改造前的三个数
    testWidgets('MEASURE 三种状态的首屏入口数', (t) async {
      await pumpShop(t, await loggedIn());
      final normal = visibleEntries(t);

      await pumpShop(
          t,
          await loggedIn(
              shop: shopJson(
                  isOpen: false,
                  closedUntil: DateTime.now()
                      .toUtc()
                      .add(const Duration(hours: 2))
                      .toIso8601String())));
      final resting = visibleEntries(t);

      await pumpShop(t,
          await loggedIn(shop: shopJson(licenseStage: 'soon', licenseDaysLeft: 23)));
      final licensed = visibleEntries(t, limit: withLicenseBanner);

      // ignore: avoid_print
      print('MEASURE\t正常营业=$normal\t临时歇业中=$resting\t证照即将到期=$licensed');
    });
  });

  group('黄金位:平台与你的账', () {
    testWidgets('三个入口都在首屏,且排在营业设置之上', (t) async {
      final api = await loggedIn();
      await pumpShop(t, api);
      for (final label in ['钱怎么分的', '平台对你的承诺', '平台规则']) {
        expect(find.text(label), findsOneWidget, reason: '缺了「$label」');
        expect(rectOf(t, find.text(label)).bottom,
            lessThanOrEqualTo(firstScreen),
            reason: '「$label」被推出首屏了');
      }
      expect(rectOf(t, find.text('钱怎么分的')).top,
          lessThan(rectOf(t, find.text('营业时间与歇业')).top),
          reason: '这段关系的三份文件该排在店铺设置之前');
    });

    testWidgets('显示费率与单量(服务端聚合的),但不显示金额', (t) async {
      final api = await loggedIn(tier: tierJson(rate: 0.045, thisMonth: 128));
      await pumpShop(t, api);
      expect(find.textContaining('4.5%'), findsOneWidget,
          reason: '费率来自 commission-tier 的 commission_rate,'
              '和对账页「阶梯佣金」同一个字段');
      expect(find.textContaining('128'), findsOneWidget,
          reason: '本月单量来自服务端 completed_counts,不是客户端求和');

      // 「本月被抽了多少钱」拿不到正确的数:客户端只有近 30 天日账单,
      // 按日求和得到的是「近 30 天」却要标成「本月」——
      // 这正是用户端 myOrders() limit=20 算「累计」那个 bug 的形状
      final gold = textsInBand(t, 0, 170);
      expect(gold.where((s) => s.contains('¥')), isEmpty,
          reason: '黄金位卡上出现了金额:${gold.where((s) => s.contains("¥"))} —— '
              '客户端算不出正确的「本月服务费合计」,服务端还没给这个字段');
    });

    testWidgets('不放今日营业数据 —— 订单 tab 已经在说同一个数', (t) async {
      final api = await loggedIn();
      await pumpShopFull(t, api);
      expect(find.textContaining('今日'), findsNothing,
          reason: '_todayCard() 已经在订单 tab(商家开 App 的落地页)显示'
              '「今日 N 单 · ¥X」。同一个数字放两处,迟早两处口径不一样');
    });

    testWidgets('店员看不到费率与单量,但看得到承诺', (t) async {
      // 对账 tab 对非店主是一块「这不是给你看的」占位页(main.dart:1516),
      // 所以费率/单量不给;但「平台对你的承诺」是这段关系本身,给
      final api = await loggedIn(shop: shopJson(viewerIsStaff: true, viewerIsOwner: false));
      await pumpShop(t, api);
      expect(find.text('平台对你的承诺'), findsOneWidget);
      expect(find.text('钱怎么分的'), findsNothing,
          reason: '切过去是一块占位页 —— 点进去才发现是死路的入口不该给');
      expect(find.textContaining('128'), findsNothing,
          reason: '单量属于经营数据,不给店员');
    });
  });

  group('临时歇业:注释说的和代码做的要一致', () {
    testWidgets('没歇业时不占一行 —— 天天摆着等于每天提醒一件不该常做的事',
        (t) async {
      final api = await loggedIn();
      await pumpShopFull(t, api);
      expect(find.text('临时歇业'), findsNothing,
          reason: 'shop_tab.dart 自己的注释就写着这句,'
              '但旧代码的 else 分支恰恰每天显示一条');
      expect(find.text('营业时间与歇业'), findsOneWidget,
          reason: '收进营业时间弹层了,入口名要说明它在哪');
    });

    testWidgets('歇业中:状态条在列表首位,且带「立即恢复」', (t) async {
      final api = await loggedIn(
        shop: shopJson(
            isOpen: false,
            closedUntil: DateTime.now()
                .toUtc()
                .add(const Duration(hours: 2))
                .toIso8601String()),
      );
      await pumpShop(t, api);
      expect(find.text('临时歇业中'), findsOneWidget);
      expect(find.text('立即恢复'), findsOneWidget);
      expect(rectOf(t, find.text('临时歇业中')).top,
          lessThan(rectOf(t, find.text('营业时间与歇业')).top),
          reason: '「歇业中」是当前状态,必须排在常规设置之前 —— '
              'AppBar 只说得出「已打烊」,说不出「14:00 自动恢复」');
      expect(rectOf(t, find.text('临时歇业中')).bottom,
          lessThanOrEqualTo(firstScreen));
    });

    testWidgets('歇业选项收在营业时间弹层里,没丢', (t) async {
      final api = await loggedIn();
      await pumpShop(t, api);
      await t.tap(find.text('营业时间与歇业'));
      await t.pumpAndSettle();
      for (final label in ['每天开门', '每天打烊', '歇 1 小时', '歇到今天打烊']) {
        expect(find.text(label), findsOneWidget, reason: '弹层里缺了「$label」');
      }
    });
  });

  group('店铺公告:收成一条带状态值的入口', () {
    testWidgets('页面上没有内联输入框', (t) async {
      final api = await loggedIn();
      await pumpShopFull(t, api);
      expect(find.byType(TextField), findsNothing,
          reason: '167px 的内联输入框换成 46px 的一条 —— '
              '公告一个月改几次,那 167px 每次打开都要付');
    });

    testWidgets('入口上显示的是顾客此刻真正看到的那句话', (t) async {
      final api =
          await loggedIn(shop: shopJson(announcement: '今天牛肉卖完了,明天早上补货'));
      await pumpShop(t, api);
      expect(find.text('今天牛肉卖完了,明天早上补货'), findsOneWidget,
          reason: '公告要显示在入口的 value 上 —— '
              '「元旦放假」挂到三月还没撤,这样才看得见');
    });

    testWidgets('没设公告时显示「未设置」', (t) async {
      final api = await loggedIn(shop: shopJson(announcement: ''));
      await pumpShop(t, api);
      expect(find.text('未设置'), findsWidgets);
    });

    testWidgets('点开才有输入框,而且有明确的保存点', (t) async {
      final api = await loggedIn();
      await pumpShop(t, api);
      await t.tap(find.text('店铺公告'));
      await t.pumpAndSettle();
      expect(find.byType(TextField), findsOneWidget);
      expect(find.text('保存公告'), findsOneWidget,
          reason: '弹层里必须有唯一、明确的保存点 —— '
              '旧版改完不点保存直接切 tab 就丢了,还没有任何提示');
    });
  });

  group('分组头砍掉,卡片边界表达结构', () {
    testWidgets('六个分组头一个不剩', (t) async {
      final api = await loggedIn();
      await pumpShopFull(t, api);
      // 分组头 41px × 6 = 246px,一屏的一半。卡片边界 + 12px 留白
      // 已经把分区表达完了,再加分组头是白付钱
      for (final title in ['营业', '价格与活动', '门店与合规', '工具', '经营', '证照与台账']) {
        expect(find.text(title), findsNothing, reason: '分组头「$title」还在');
      }
    });

    testWidgets('「其他」那个 0 条子项的空组没了,但网页版说明还在', (t) async {
      final api = await loggedIn();
      await pumpShopFull(t, api);
      expect(find.text('其他'), findsNothing,
          reason: '分组头 41 + 一个 0 高度的描边空卡 + 脚注 40 = 98px,'
              '只为了说一句话');
      expect(find.textContaining('chaojizan.cc/merchant'), findsOneWidget,
          reason: '话要留下,壳子不要');
    });

    testWidgets('两条钱与合规的脚注留着', (t) async {
      final api = await loggedIn();
      await pumpShopFull(t, api);
      expect(find.textContaining('平台按满减后的实收计'), findsOneWidget,
          reason: '这是钱的口径:商家做满减前最会犹豫的就是'
              '「按打折前还是打折后抽」');
      expect(find.textContaining('不替你担责'), findsOneWidget,
          reason: '免责声明,23px 是最便宜的一条');
    });
  });

  group('网格化:给不出状态值、标题两三个字的入口', () {
    testWidgets('15 个跳转型入口都在,一个没丢', (t) async {
      final api = await loggedIn();
      await pumpShopFull(t, api);
      for (final label in [
        '券核销', '店铺券', '团购券', '小票打印', '经营看板',
        '老客召回', '专属码', '消息', '客服', '判责申诉',
        '门店相册', '店员', '健康证', '进货台账', '连锁店群',
      ]) {
        expect(find.text(label), findsOneWidget, reason: '网格里缺了「$label」');
      }
    });

    testWidgets('常用工具那 10 格全在首屏', (t) async {
      final api = await loggedIn();
      await pumpShop(t, api);
      for (final label in [
        '券核销', '店铺券', '团购券', '小票打印', '经营看板',
        '老客召回', '专属码', '消息', '客服', '判责申诉',
      ]) {
        expect(rectOf(t, find.text(label)).bottom,
            lessThanOrEqualTo(firstScreen),
            reason: '「$label」被推出首屏');
      }
    });

    testWidgets('角标只给「你还有事要做」的', (t) async {
      final api = await loggedIn(todos: todosJson(messagesUnread: 3, appealable: 0));
      await pumpShop(t, api);
      expect(find.text('3'), findsOneWidget, reason: '未读消息该挂角标');
      expect(find.text('0'), findsNothing, reason: '0 不显示');
    });

    testWidgets('判责申诉的角标是「还来得及申诉的」,不是历史判责数', (t) async {
      final api = await loggedIn(todos: todosJson(appealable: 2));
      await pumpShop(t, api);
      expect(find.text('2'), findsOneWidget);
    });

    testWidgets('健康证角标读对了 key —— 服务端叫 health_certs_expiring',
        (t) async {
      // 这类 key 写错**没有任何报错**:`_todo()` 拿不到就返回 0,
      // 角标安静地不显示,而商家的健康证正在过期。
      // 第一版就把它写成了 health_expiring
      final api = await loggedIn(todos: todosJson(healthExpiring: 2));
      await pumpShopFull(t, api);
      expect(find.text('2'), findsOneWidget,
          reason: 'todos 的 key 是 health_certs_expiring(merchants.py:3429)');
    });

    testWidgets('店员看不到店员管理/连锁/收款资料', (t) async {
      final api = await loggedIn(shop: shopJson(viewerIsStaff: true, viewerIsOwner: false));
      await pumpShopFull(t, api);
      for (final label in ['店员', '连锁店群', '收款资料']) {
        expect(find.text(label), findsNothing,
            reason: '「$label」的接口按店主判权,给了也只会报错');
      }
    });
  });

  group('不许被密度改造碰掉的', () {
    testWidgets('_measuredPrep() 原样保留 —— 那是数据不是解释', (t) async {
      final api = await loggedIn(prep: prepJson());
      await pumpShopFull(t, api);
      expect(find.textContaining('实测 22 分钟'), findsOneWidget);
      expect(find.textContaining('P50 16 / P80 22 / P95 31'), findsOneWidget,
          reason: '分位数那一行是商家判断"要不要调承诺值"的依据');
      expect(find.textContaining('不参与排序'), findsOneWidget,
          reason: '这条红线必须原样显示 —— 不写清楚商家会为这个数经营,'
              '比如菜没好先点「出餐」,数据反而失真');
    });

    testWidgets('样本不够时照实说,不给假装精确的数', (t) async {
      final api = await loggedIn(prep: prepJson(enough: false));
      await pumpShopFull(t, api);
      expect(find.textContaining('还不够算实测值'), findsOneWidget);
    });

    testWidgets('带开关的入口条不超过 72px —— 不许缩触控区', (t) async {
      setPhoneViewport(t, const Size(390, 844));
      final w = SzEntryTile(
        icon: Icons.flash_on_outlined,
        title: '自动接单',
        hint: '来单免确认直接进制作,拒单和缺货退款仍可手动',
        trailing: Switch(value: true, onChanged: (_) {}),
        onTap: () {},
      );
      await t.pumpWidget(MaterialApp(
        theme: brandTheme(Brightness.light, density: SzDensity.operate),
        home: Scaffold(
            body: SingleChildScrollView(
                child: Align(alignment: Alignment.topCenter, child: w))),
      ));
      await t.pumpAndSettle();
      final h = t.getSize(find.byWidget(w)).height;
      // 72 = Switch 的 48px 触控区 + 上下各 12 的内边距。
      // 实测 Switch 光杆条也是 72 —— **hint 在这一档是免费的**,
      // 所以三条开关入口的说明一句都不砍(砍了一分不省)
      expect(h, lessThanOrEqualTo(72),
          reason: '开关行涨到 ${h.toStringAsFixed(0)}px 了');
    });

    testWidgets('三条开关的说明都还在', (t) async {
      final api = await loggedIn();
      await pumpShopFull(t, api);
      expect(find.textContaining('配送费全归你'), findsOneWidget);
      expect(find.textContaining('来单免确认'), findsOneWidget);
      expect(find.textContaining('顾客收餐时能核对'), findsOneWidget);
    });

    testWidgets('目录式 hint 砍干净了', (t) async {
      final api = await loggedIn();
      await pumpShopFull(t, api);
      expect(find.textContaining('趋势、时段、出餐时长、菜品贡献'), findsNothing,
          reason: '那是一份目录,目的页自己会答');
      expect(find.textContaining('不设就按平台默认估算'), findsNothing,
          reason: '它下面 103px 的实测块才是这一条真正的说明');
    });
  });

  group('合规项照实显示', () {
    testWidgets('堂食未填报标红,不替商家猜一个', (t) async {
      final api = await loggedIn(shop: shopJson(dineInStatus: 'unknown'));
      await pumpShopFull(t, api);
      expect(find.text('未填报'), findsOneWidget);
    });

    testWidgets('明厨亮灶用服务端的 listed_label,不读 shop.kitchen_cam',
        (t) async {
      // MerchantOut.kitchen_cam 默认 False,而 /merchants/me 是
      // model_validate(shop) —— 直接读它,装了摄像头的店会被显示成「无」
      final hit = <String>[];
      final api = await loggedIn(onRequest: hit.add);
      await pumpShopFull(t, api);
      expect(hit, contains('/merchants/me/kitchen-cam'));
      expect(find.text('无明厨亮灶'), findsOneWidget);
    });

    testWidgets('许可证到期日显示在入口上', (t) async {
      final api = await loggedIn(shop: shopJson(licenseExpiresAt: '2027-03-15'));
      await pumpShopFull(t, api);
      expect(find.textContaining('2027-03-15'), findsOneWidget);
    });
  });
}
