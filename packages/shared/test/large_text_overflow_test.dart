import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:superz_shared/superz_shared.dart';

import 'text_fit.dart';

/// 长辈版(1.4×)下共享组件会不会把字画出格子。
///
/// ## 为什么单独测这个
///
/// 这个 App 有长辈版大字模式,用户里老年人不少。而三端共用的这些组件
/// 里有 737 处硬编码字号 —— 1.0× 下排得下,不等于 1.4× 下排得下。
///
/// 判据在 `text_fit.dart` 里,那里写了为什么不能只看 `takeException()`,
/// 以及第一版判据错在哪。
void main() {

  Widget host(Widget child, {double scale = 1.4, Brightness b = Brightness.light}) =>
      MediaQuery(
        data: MediaQueryData(textScaler: TextScaler.linear(scale)),
        child: MaterialApp(
          theme: brandTheme(b),
          home: Scaffold(
            body: SingleChildScrollView(
              child: Padding(
                padding: const EdgeInsets.all(kPagePad),
                child: child,
              ),
            ),
          ),
        ),
      );



  /// 各组件的样例。文案取**真实长度**,不是「测试」两个字 ——
  /// 拿短文案测溢出等于没测。
  /// 各组件的样例。文案取**真实长度**,不是「测试」两个字 ——
  /// 拿短文案测溢出等于没测。金额也取真实位数:
  /// 「128,800」比「100」宽得多,而钱这一列恰恰是最容易挤爆的。
  final cases = <String, Widget>{
    'SzFeeRow 合计行': const SzFeeRow(
        label: '商家实收', amountCents: 128800,
        note: '已扣平台佣金 5%', emphasized: true),
    'SzFeeRow 抽成行': const SzFeeRow(
        label: '平台佣金', amountCents: -6440, note: '5% 封顶', isHold: true),
    'SzSectionTitle': const SzSectionTitle('本单钱怎么分的'),
    'SzChip 选中': const SzChip('川菜 · 麻辣', selected: true),
    'SzChip 长文案': const SzChip('满 50 减 10(每人限一次)'),
    'SzEmpty': const SzEmpty(text: '附近还没有商家入驻,换个地址看看'),
    'SzChannelChip': const SzChannelChip('food'),
    'SzCard 内文': SzCard(
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: const [
        Text('王记火锅(建设路总店)'),
        Text('起送 20 · 配送 3 元 · 预计 35 分钟送达'),
      ]),
    ),
    'SzStepper': SzStepper(quantity: 12, onAdd: () {}, onRemove: () {}),
    'SzError': SzError(error: '网络不太好,刷新试试', onRetry: () {}),
    'SzRetryBanner': SzRetryBanner(
        text: '这一段没加载出来,不影响下单', onRetry: () {}),
    'SzTimeline': const SzTimeline(steps: [
      SzStep('商家已接单', subtitle: '18:32 · 预计 20 分钟出餐'),
      SzStep('骑手已取餐', subtitle: '18:51 · 距您 1.2 公里'),
      SzStep('已送达', subtitle: '预计 19:07 送到建设路 88 号'),
    ]),
    'SzMoneyFlow': const SzMoneyFlow(items: [
      SzFlowItem(name: '商家实收', amountCents: 12880,
          fraction: 0.86, note: '扣 5% 平台佣金后'),
      SzFlowItem(name: '骑手配送费', amountCents: 1400,
          fraction: 0.09, note: '全额归骑手,平台不抽'),
      SzFlowItem(name: '平台佣金', amountCents: 720,
          fraction: 0.05, note: '封顶 5%'),
    ]),
    'SzLedgerCard': const SzLedgerCard(
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text('本月已结算 ¥12,880.00'),
        Text('下次打款 9 月 1 日 · 账期 T+1'),
      ]),
    ),
  };

  for (final width in [320.0, 360.0]) {
    group('${width.toInt()} 窄屏 · 长辈版 1.4×', () {
      cases.forEach((name, widget) {
        testWidgets('$name 不画出界', (tester) async {
          setPhoneViewport(tester, Size(width, 780));
          await tester.pumpWidget(host(widget));
          expect(tester.takeException(), isNull, reason: '$name 渲染抛异常');
          final bad = textsPaintingOutside(tester);
          expect(bad, isEmpty,
              reason: '$name 在 ${width.toInt()}px 屏 1.4× 字号下画出界:\n'
                  '${bad.join("\n")}');
        });
      });
    });
  }

  group('截断清单(不是失败,是要有人知道)', () {
    testWidgets('320 窄屏 1.4× 下被切成省略号的字', (tester) async {
      final all = <String>[];
      for (final entry in cases.entries) {
        setPhoneViewport(tester, const Size(320, 780));
        await tester.pumpWidget(host(entry.value));
        for (final t in truncatedTexts(tester)) {
          all.add('${entry.key}: $t');
        }
      }
      // 这一条**故意不断言为空** —— 截断是设计选择,不是缺陷。
      // 它的作用是把清单打出来:改字号或改文案时,
      // 谁被切了、切没切多是一眼能看见的事,而不是等用户来说。
      if (all.isNotEmpty) {
        // ignore: avoid_print
        print('  ⚠️ 320 窄屏 1.4× 下被截断:\n    ${all.join("\n    ")}');
      }
      expect(true, isTrue);
    });
  });
}
