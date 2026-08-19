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
