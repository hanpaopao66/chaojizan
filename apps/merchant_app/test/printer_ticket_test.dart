/// 小票版式测试:**没有真机也要能核版式**。
///
/// 58mm 热敏纸只有 32 列(汉字占 2 列)。排不下就折行,而折行的地址
/// 在店里读起来是灾难 —— 骑手来取餐,商家念半天念不对门牌。
/// 这个测试把 ESC/POS 字节流解回文字,断言内容与列宽,
/// 顺带把整张票打到控制台,改版式时能一眼看出长什么样。
library;

import 'package:fast_gbk/fast_gbk.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:merchant_app/printer_service.dart';
import 'package:superz_shared/superz_shared.dart';

/// 把字节流里的 ESC/POS 控制码剔掉,只留可读文本
String render(List<int> bytes) {
  final text = <int>[];
  for (var i = 0; i < bytes.length; i++) {
    final b = bytes[i];
    if (b == 0x1B) { i += (bytes[i + 1] == 0x61 || bytes[i + 1] == 0x45) ? 2 : 1; continue; }
    if (b == 0x1D) { i += 2; continue; }
    text.add(b);
  }
  return gbk.decode(text);
}

Order sample({bool toDoor = true, bool pickup = false}) => Order.fromJson({
      'order_no': 'SZ20260806000123',
      'merchant_id': 1,
      'lat': 30.6612,
      'lng': 104.0823,
      'status': 'accepted',
      'created_at': '2026-08-06T12:34:00Z',
      'pickup': pickup,
      'pickup_code': pickup ? '8421' : '',
      'items': [
        {'name': '招牌牛腩饭', 'quantity': 2, 'price_cents': 2800},
        {'name': '酸梅汤', 'quantity': 1, 'price_cents': 600},
      ],
      'food_cents': 6200,
      'packing_fee_cents': 200,
      'discount_cents': 500,
      'delivery_fee_cents': 800,
      'fee_parts': {'base': 300, 'night': 200, 'door': 300},
      'fee_part_labels': {'base': '基础配送', 'night': '夜间加价', 'door': '上门难度'},
      'to_door': toDoor,
      'tip_cents': 0,
      'total_cents': 6700,
      'contact_name': '张先生',
      'contact_phone': '138****1234',
      'address': '成都市高新区天府大道北段 1 号 3 栋 502',
      'remark': '不要香菜,多给一双筷子',
    });

void main() {
  test('外卖小票:内容齐全、配送费构成印出来、不超 32 列', () {
    final t = render(BtPrinter.ticketBytes(sample(), '赞小碗'));
    // ignore: avoid_print
    print('\n===== 58mm 小票预览(| 是纸边)=====\n'
        '${t.split('\n').map((l) => '|$l').join('\n')}\n'
        '================================\n');

    for (final must in [
      '超级赞', '赞小碗', 'SZ20260806000123', '招牌牛腩饭', '酸梅汤',
      '不要香菜', '张先生', '天府大道', '平台只抽5%',
    ]) {
      expect(t, contains(must), reason: '小票缺了「$must」');
    }
    // 配送费构成:顾客当面问"怎么这么贵",商家要能直接指给他看
    expect(t, contains('上门难度'));
    expect(t, contains('夜间加价'));

    // 列宽:58mm = 32 列,汉字占 2 列。
    //
    // 只管**我们自己排的行**(金额、拆分、页脚)。地址、备注、菜名是
    // 用户数据,长度不可控,再怎么排都可能折行 —— 对它们断言等于
    // 断言"用户不许写长地址",没有意义。
    // 真正要拦的是我们把三项拆分连成 37 列这种自己造的溢出。
    int cols(String s) => s.runes.fold(0, (n, r) => n + (r > 0x7F ? 2 : 1));
    const userData = ['天府大道', '不要香菜', '招牌牛腩饭', '酸梅汤'];
    for (final line in t.split('\n')) {
      if (userData.any(line.contains)) continue;
      expect(cols(line) <= 32, isTrue,
          reason: '这一行 ${cols(line)} 列,超出 58mm 纸宽会折行:「$line」');
    }
  });

  test('顾客选送到楼下要印出来', () {
    final t = render(BtPrinter.ticketBytes(sample(toDoor: false), '赞小碗'));
    expect(t, contains('送到楼下'),
        reason: '不印的话商家会以为骑手偷懒不上楼');
  });

  test('自取单印取餐码,不印配送费', () {
    final t = render(BtPrinter.ticketBytes(sample(pickup: true), '赞小碗'));
    expect(t, contains('8421'));
    expect(t, contains('免配送费'));
  });
}
