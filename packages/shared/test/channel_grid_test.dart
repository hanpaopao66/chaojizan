import 'package:flutter_test/flutter_test.dart';
import 'package:superz_shared/superz_shared.dart';

/// 金刚区排版规则。
///
/// 这套规则干两件事:
///
/// 1. **别让最后一行只剩一张卡。** 首页曾经写死 3 列,而上线频道正好 4 个 ——
///    排成 3+1,第二行右边空掉三分之二,用户看着像没加载完。
/// 2. **频道多了自动换排法。** 卡片式带一句话说明,频道少时很有用
///    (「帮我送」没人天生知道是什么);但 5 个往上就排不下了,
///    该切成聚合平台那种 4–5 列的图标网格。
///
/// 加频道的人不该靠人肉数格子,所以在这里锁住。
void main() {
  /// 末行剩几张。整除时是满行。
  int lastRow(int n) {
    final cols = channelGridColumns(n);
    return n % cols == 0 ? cols : n % cols;
  }

  group('末行不孤单', () {
    test('1~20 个频道,末行都不只剩一张', () {
      final orphans = <int>[];
      for (var n = 1; n <= 20; n++) {
        final cols = channelGridColumns(n);
        if (n > cols && lastRow(n) == 1) orphans.add(n);
      }
      // 7 个是卡片式的死角:3 列剩 1、2 列也剩 1,躲不开。
      // 但 7 已经进聚合式了(5 列排成 5+2),所以现在一个死角都没有
      expect(orphans, isEmpty,
          reason: '这些频道数会排出孤儿行:$orphans');
    });

    test('真到 21 个才会重新出现孤儿行,那时候该做分组了', () {
      // 21 % 5 == 1 且 21 % 4 == 1 —— 两种列数都躲不开。
      // 记在这里不是为了将来去修它,是为了说明**规则的边界在哪**:
      // 一个首页塞 21 个频道,问题不在列数
      expect(lastRow(21), 1);
    });
  });

  group('卡片式(≤4 个频道)', () {
    test('4 个走 2 列排成 2×2 —— 这就是当初那个 bug', () {
      expect(channelGridLayout(4), SzChannelLayout.card);
      expect(channelGridColumns(4), 2);
    });

    test('3 个是 3 列一满行', () {
      expect(channelGridColumns(3), 3);
    });

    test('1~2 个按实际个数排,不留空格', () {
      expect(channelGridColumns(1), 1);
      expect(channelGridColumns(2), 2);
    });
  });

  group('聚合式(≥5 个频道)', () {
    test('第 5 个频道一进来就换排法', () {
      expect(channelGridLayout(kChannelCardMax), SzChannelLayout.card);
      expect(channelGridLayout(kChannelCardMax + 1), SzChannelLayout.compact);
    });

    test('5 个排一满行', () {
      expect(channelGridColumns(5), 5);
    });

    test('6 个退 4 列(5 列会剩 1 个)', () {
      expect(channelGridColumns(6), 4);
    });

    test('7 / 9 个仍然 5 列', () {
      expect(channelGridColumns(7), 5); // 5+2
      expect(channelGridColumns(9), 5); // 5+4
    });

    test('每行不超过 5 个 —— 再密就点不准了', () {
      for (var n = 5; n <= 20; n++) {
        expect(channelGridColumns(n), lessThanOrEqualTo(5),
            reason: '$n 个频道排了 ${channelGridColumns(n)} 列');
      }
    });
  });

  group('宽屏按格宽分列(#295)', () {
    test('不传宽度时行为完全不变 —— 老调用点一个不受影响', () {
      expect(channelGridColumns(4), 2);
      expect(channelGridColumns(5), 5);
      expect(channelGridColumns(6), 4);
    });

    test('手机宽度下和不传一样', () {
      // 360 屏减掉页面留白约 324:324/260 = 1 列,走不到宽屏分支
      expect(channelGridColumns(4, width: 324), 2);
    });

    test('每格约 260 宽,按这个算列数', () {
      // 判据是**每格多宽**不是屏幕多宽 ——
      // 1440px 上四个频道排两列时每格 550,而内容只占前 200。
      //
      // 700 / 260 = 2 列(不是"宽屏就一定要三列以上") ——
      // 第一版这里断言 >2,是我把"屏幕宽"和"格子宽"混了
      expect(channelGridColumns(4, width: 700), 2); // 700/260 = 2
      // 800/260 = 3,但**4 个排 3 列末行只剩 1** —— 降到 2 列排成 2×2。
      // "末行不孤单"优先于"格子别太宽",因为孤儿行看着像页面没加载完
      expect(channelGridColumns(4, width: 800), 2);
      expect(channelGridColumns(4, width: 1040), 4); // 1040/260 = 4,一行排完
      // 列数不会超过频道数,不留空格子
      expect(channelGridColumns(4, width: 2000), 4);
      // 5 个频道:800 下 3 列排成 3+2,不孤单
      expect(channelGridColumns(5, width: 800), 3);
    });

    test('列数不超过 6 —— 再多一行扫过去就找不着了', () {
      expect(channelGridColumns(12, width: 3000), lessThanOrEqualTo(6));
    });

    test('列数不超过频道数,不留空格子', () {
      expect(channelGridColumns(3, width: 1400), lessThanOrEqualTo(3));
    });

    test('宽屏上末行也不孤单', () {
      for (final w in [700.0, 900.0, 1040.0, 1400.0, 2000.0]) {
        for (var n = 3; n <= 12; n++) {
          final c = channelGridColumns(n, width: w);
          final last = n % c == 0 ? c : n % c;
          expect(last == 1 && n > c, isFalse,
              reason: '$n 个频道在 ${w.toInt()}px 下排 $c 列,末行只剩一个');
        }
      }
    });
  });

  test('当前真实频道数排出来不孤单', () {
    expect(lastRow(kChannels.length) > 1 ||
            kChannels.length <= channelGridColumns(kChannels.length),
        isTrue,
        reason: '现在有 ${kChannels.length} 个频道,'
            '排 ${channelGridColumns(kChannels.length)} 列会剩 '
            '${lastRow(kChannels.length)} 张');
  });

  test('打车上线(第 5 个频道)时排版自动成立', () {
    // kChannels 里「打车」是注释掉的下一个频道。它一进来就是 5 个,
    // 这个测试保证那天首页不用改一行代码
    const next = 5;
    expect(channelGridLayout(next), SzChannelLayout.compact);
    expect(channelGridColumns(next), 5);
    expect(lastRow(next), 5);
  });
}
