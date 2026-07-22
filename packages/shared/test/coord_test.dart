import 'package:flutter_test/flutter_test.dart';
import 'package:superz_shared/superz_shared.dart';

void main() {
  test('GCJ-02 ↔ WGS-84 往返误差小于 0.1 米', () {
    // 成都/北京/广州三个城市抽查
    const samples = [(30.6612, 104.0823), (39.9042, 116.4074), (23.1291, 113.2644)];
    for (final (lat, lng) in samples) {
      final gcj = wgs84ToGcj02(lat, lng);
      final back = gcj02ToWgs84(gcj.lat, gcj.lng);
      expect(distanceMeters(lat, lng, back.lat, back.lng), lessThan(0.1));
    }
  });

  test('境外坐标不做偏移', () {
    final r = gcj02ToWgs84(35.6762, 139.6503); // 东京
    expect(r.lat, 35.6762);
    expect(r.lng, 139.6503);
  });

  test('canonicalJson+sha256 与服务端 Python 参考值一致', () {
    final sample = {
      'day': '2026-07-16', 'schema': 1,
      'commission_rate_max': 0.06, 'voucher_rate': 0.03,
      'merchant_rows': [
        {'o': 'abc123', 'food': 3000, 'commission': 180,
         'net': 2820, 'kind': 'earning'}
      ],
      'rider_rows': [], 'voucher_rows': [],
      'totals': {'merchant_net': 2820, 'platform_commission': 180,
                 'rider_amount': 0, 'voucher_fee': 0},
      'note': '中文测试',
    };
    expect(sha256Hex(canonicalJson(sample)),
        '69a0332dc83ec05396524ce180eb913b7eaabf21c1d5f58e88daf198f4f8f30c');
  });

  test('verifyRows 抓得住佣金超限与净额造假', () {
    expect(verifyRows({'merchant_rows': [
      {'o': 'x', 'food': 3000, 'commission': 180, 'net': 2820, 'kind': 'earning'}
    ]}), isEmpty);
    expect(verifyRows({'merchant_rows': [
      {'o': 'x', 'food': 3000, 'commission': 600, 'net': 2400, 'kind': 'earning'}
    ]}), isNotEmpty); // 20% 佣金必须被抓
    expect(verifyRows({'rider_rows': [
      {'o': 'x', 'amount': -500, 'kind': 'earning'}
    ]}), isNotEmpty); // 配送费冲减必须被抓
  });
}
