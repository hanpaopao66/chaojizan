import 'package:flutter_test/flutter_test.dart';
import 'package:superz_shared/superz_shared.dart';

/// 地址簿排序(#171)。
///
/// 两件事**故意分开**:
///
/// - **排序**:默认地址永远排最前 —— 用户特意设过「默认」,
///   那是他的明确意愿,不该被算出来的距离盖过去;
/// - **「距离最近」标签**:标在真的最近的那个上,而不是排序后的第一个。
///
/// 合成一件事的话,要么默认地址被挤走(违背用户意愿),
/// 要么标签指着一个并不最近的地址(是在骗人)。
void main() {
  test('默认地址排最前,但「距离最近」标在真的最近那个上', () {
    final rows = [
      (id: 1, name: '公司前台', lat: 30.6700, lng: 104.0900, isDefault: true),
      (id: 2, name: '春熙路 2 单元 501', lat: 30.6598, lng: 104.0810, isDefault: false),
      (id: 3, name: '天府广场', lat: 30.6570, lng: 104.0650, isDefault: false),
    ];
    const myLat = 30.6598, myLng = 104.0810;

    final sorted = [...rows]..sort((a, b) {
        if (a.isDefault != b.isDefault) return a.isDefault ? -1 : 1;
        return distanceMeters(myLat, myLng, a.lat, a.lng)
            .compareTo(distanceMeters(myLat, myLng, b.lat, b.lng));
      });

    var best = 0;
    var bestD = double.infinity;
    for (var i = 0; i < sorted.length; i++) {
      final d = distanceMeters(myLat, myLng, sorted[i].lat, sorted[i].lng);
      if (d < bestD) { bestD = d; best = i; }
    }

    for (final r in sorted) {
      final d = distanceMeters(myLat, myLng, r.lat, r.lng);
      // ignore: avoid_print
      print('  ${r.name} ${d.toStringAsFixed(0)}m'
          '${r.isDefault ? " [默认]" : ""}'
          '${r.id == sorted[best].id ? "  ← 距离最近" : ""}');
    }

    // 默认地址仍排最前 —— 用户特意设过,那是他的明确意愿
    expect(sorted.first.isDefault, isTrue);
    // 但「距离最近」标的是真的最近那个,不是排序后的第一个
    expect(sorted[best].name, '春熙路 2 单元 501');
    expect(bestD, lessThan(10));
  });
}
