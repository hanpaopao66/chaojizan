import 'package:flutter_test/flutter_test.dart';
import 'package:superz_shared/superz_shared.dart';

/// 金刚区排版规则(一律聚合式,设计稿 1b / 2a)。
///
/// 这套规则干两件事:
///
/// 1. **别留空格子。** 5 个以内有几个排几列 —— 只开两个频道时两格平分一行,
///    不是左边两格、右边空三格,看着像页面没加载完;
/// 2. **别让最后一行只剩一个。** 首页曾经写死 3 列,而上线频道正好 4 个 ——
///    排成 3+1,第二行右边空掉三分之二。
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
      // 老的卡片式里 7 个是死角(3 列剩 1、2 列也剩 1);
      // 一律聚合式之后 7 个排 5+2,20 以内一个死角都没有
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

  group('5 个以内:有几个排几列,不留空格', () {
    test('1~5 个各排一满行', () {
      for (var n = 1; n <= 5; n++) {
        expect(channelGridColumns(n), n);
      }
    });

    test('只开两个频道时是两格平分一行(线上现在就是这样)', () {
      expect(channelGridColumns(2), 2);
    });
  });

  group('5 个往上:优先 5 列,末行不孤单', () {
    test('6 个退 4 列(5 列会剩 1 个)', () {
      expect(channelGridColumns(6), 4);
    });

    test('7 / 9 个仍然 5 列', () {
      expect(channelGridColumns(7), 5); // 5+2
      expect(channelGridColumns(9), 5); // 5+4
    });

    test('11 个退 4 列(4+4+3)', () {
      expect(channelGridColumns(11), 4);
    });

    test('每行不超过 5 个 —— 再密就点不准了', () {
      for (var n = 1; n <= 20; n++) {
        expect(channelGridColumns(n), lessThanOrEqualTo(5),
            reason: '$n 个频道排了 ${channelGridColumns(n)} 列');
      }
    });
  });

  group('宽屏按格宽分列(#295)', () {
    test('不传宽度时行为完全不变 —— 老调用点一个不受影响', () {
      expect(channelGridColumns(4), 4);
      expect(channelGridColumns(5), 5);
      expect(channelGridColumns(6), 4);
    });

    test('手机宽度下和不传一样', () {
      // 手机宽度 /120 不到 6 列,走不到宽屏分支
      expect(channelGridColumns(4, width: 324), channelGridColumns(4));
      expect(channelGridColumns(8, width: 354), channelGridColumns(8));
    });

    test('每格约 120 宽,多出来的频道往一行里排', () {
      // 聚合式一格只有一个字块加一行字,再宽就是两边空着
      expect(channelGridColumns(8, width: 1000), 8); // 1000/120 = 8,一行排完
      expect(channelGridColumns(12, width: 1000), 8); // 8+4
    });

    test('列数不超过 8 —— 再多一行扫过去就找不着了', () {
      expect(channelGridColumns(20, width: 3000), lessThanOrEqualTo(8));
    });

    test('列数不超过频道数,不留空格子', () {
      expect(channelGridColumns(3, width: 1400), 3);
    });

    test('宽屏上末行也不孤单', () {
      for (final w in [700.0, 900.0, 1040.0, 1400.0, 2000.0]) {
        for (var n = 3; n <= 20; n++) {
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

  test('打车上线(第 6 个频道)时排版自动成立', () {
    // kChannels 里「打车」是注释掉的下一个频道。它一进来就是 6 个 ——
    // 5 列会剩 1 个,自动退成 4+2,首页不用改一行代码
    const next = 6;
    expect(channelGridColumns(next), 4);
    expect(lastRow(next), 2);
  });
}
