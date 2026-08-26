import 'package:flutter_test/flutter_test.dart';
import 'package:superz_shared/superz_shared.dart';

/// 列表用的短金额。
///
/// [yuan] 是账目口径,永远两位小数 —— 对账、退款、分账里一分钱都不能省,
/// **那个不许动**。这个是扫读口径:列表卡上「人均 ¥20.00 · 起送 ¥15.00」
/// 里的四个 .00 不带信息,只占宽度,而那一行本来就快排不下。
void main() {
  test('整元不带小数', () {
    expect(yuanShort(2000), '¥20');
    expect(yuanShort(0), '¥0');
    expect(yuanShort(100), '¥1');
  });

  test('有零头才带,能省一位就省一位', () {
    expect(yuanShort(2050), '¥20.5');
    expect(yuanShort(2055), '¥20.55');
    expect(yuanShort(1), '¥0.01');
  });

  test('账目口径原样保留,没被顺手改掉', () {
    expect(yuan(2000), '¥20.00', reason: '对账的金额一分都不许省');
    expect(yuan(2050), '¥20.50');
  });
}
