import 'package:flutter_test/flutter_test.dart';
import 'package:superz_shared/superz_shared.dart';

/// 金刚区列数规则。
///
/// 这条规则只干一件事:**别让最后一行只剩一张卡**。
/// 首页曾经写死 3 列,而上线频道正好 4 个 —— 排成 3+1,第二行右边
/// 空掉三分之二,用户看着像没加载完。
///
/// 加频道的人不该靠人肉数格子,所以在这里锁住。
void main() {
  test('末行绝不只剩一张卡(7 个除外,2 列 3 列都躲不开)', () {
    for (var n = 1; n <= 12; n++) {
      final cols = channelGridColumns(n);
      final last = n % cols == 0 ? cols : n % cols;
      if (n == 7) continue; // 7 个:3 列剩 1、2 列也剩 1,无解
      expect(last == 1 && n > cols, isFalse,
          reason: '$n 个频道排 $cols 列,末行只剩 1 张 —— 右边会空掉一大片');
    }
  });

  test('4 个频道走 2 列排成 2×2(这就是当初那个 bug)', () {
    expect(channelGridColumns(4), 2);
  });

  test('3 / 5 / 6 个仍然是 3 列,别为了 4 个把别的也改窄', () {
    expect(channelGridColumns(3), 3);
    expect(channelGridColumns(5), 3);
    expect(channelGridColumns(6), 3);
  });

  test('1~2 个就按实际个数排,不留空格', () {
    expect(channelGridColumns(1), 1);
    expect(channelGridColumns(2), 2);
  });

  test('当前真实频道数排出来不孤单', () {
    final cols = channelGridColumns(kChannels.length);
    final last = kChannels.length % cols == 0
        ? cols
        : kChannels.length % cols;
    expect(last > 1 || kChannels.length <= cols, isTrue,
        reason: '现在有 ${kChannels.length} 个频道,排 $cols 列会剩 $last 张');
  });
}
