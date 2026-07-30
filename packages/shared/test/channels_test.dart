import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:superz_shared/superz_shared.dart';

/// 频道设计系统(#132)。
///
/// 守的是三件事:注册表是唯一事实来源、频道色不越界、
/// **未知频道能优雅回退** —— 服务端将来下发一个客户端还不认识的新频道时,
/// 页面要正常显示而不是白屏,这是聚合平台最容易翻车的地方。
void main() {
  Widget wrap(Widget child, {Brightness brightness = Brightness.light}) =>
      MaterialApp(
        theme: brandTheme(brightness),
        home: Scaffold(body: Center(child: child)),
      );

  group('注册表', () {
    test('已上线频道齐全且 key 唯一', () {
      expect(kChannels, isNotEmpty);
      final keys = kChannels.map((c) => c.key).toList();
      expect(keys.toSet().length, keys.length, reason: 'key 有重复');
    });

    test('色槽不越界', () {
      for (final c in kChannels) {
        expect(c.tone, greaterThanOrEqualTo(0), reason: c.key);
        expect(c.tone, lessThan(SzColors.light.channelTones.length),
            reason: '${c.key} 的色槽超出色板,加频道时忘了扩板');
      }
    });

    test('每个频道各占一个色槽,不共用', () {
      final tones = kChannels.map((c) => c.tone).toList();
      expect(tones.toSet().length, tones.length,
          reason: '两个频道共用同一个色槽 —— 用户分不出来');
    });

    test('channelOf 取不到返回 null 而不是抛异常', () {
      expect(channelOf('food'), isNotNull);
      expect(channelOf('未来的新频道'), isNull);
      expect(channelOf(null), isNull);
      expect(channelOf(''), isNull);
    });

    test('按 biz_type 反查', () {
      expect(channelOfBizType('food')?.key, 'food');
      expect(channelOfBizType('hotel')?.key, 'stay');
      expect(channelOfBizType('还没有的业务'), isNull);
    });
  });

  group('频道色', () {
    testWidgets('已知频道各不相同,且都不是平台色', (tester) async {
      late BuildContext ctx;
      await tester.pumpWidget(wrap(Builder(builder: (c) {
        ctx = c;
        return const SizedBox();
      })));
      final sz = Theme.of(ctx).sz;
      final colors = <Color>{};
      for (final c in kChannels) {
        final col = channelColor(ctx, c.key);
        expect(col, isNot(sz.clay),
            reason: '${c.key} 用了平台色 —— 平台色属于跨频道主 CTA,不属于任何频道');
        colors.add(col);
      }
      expect(colors.length, kChannels.length, reason: '有频道撞色');
    });

    testWidgets('未知频道回退平台色而不是崩', (tester) async {
      late BuildContext ctx;
      await tester.pumpWidget(wrap(Builder(builder: (c) {
        ctx = c;
        return const SizedBox();
      })));
      expect(channelColor(ctx, '服务端下发的新频道'), Theme.of(ctx).sz.clay);
      expect(channelColor(ctx, null), Theme.of(ctx).sz.clay);
    });

    testWidgets('深色态取的是深色槽位', (tester) async {
      late BuildContext ctx;
      await tester.pumpWidget(wrap(
          Builder(builder: (c) {
            ctx = c;
            return const SizedBox();
          }),
          brightness: Brightness.dark));
      final dark = channelColor(ctx, 'food');
      expect(dark, isNot(SzColors.light.channelTones[0]),
          reason: '深色模式仍取浅色槽位 —— 深色下会糊在背景里');
    });
  });

  group('组件', () {
    testWidgets('SzChannelChip 显示频道名与字符', (tester) async {
      await tester.pumpWidget(wrap(const SzChannelChip('stay')));
      expect(find.textContaining('住宿'), findsOneWidget);
      expect(find.textContaining('宿'), findsOneWidget);
    });

    testWidgets('未知频道的 chip 什么都不渲染(不是渲染成乱码)', (tester) async {
      await tester.pumpWidget(wrap(const SzChannelChip('nope')));
      expect(find.byType(Text), findsNothing);
    });

    testWidgets('SzChannelBar 是细条,不是色块', (tester) async {
      await tester.pumpWidget(wrap(const SzChannelBar('food')));
      final box = tester.widget<Container>(find.byType(Container));
      expect((box.constraints?.maxHeight ?? 3) <= 4, isTrue,
          reason: '标识条太厚会喧宾夺主');
    });
  });
}
