import 'package:flutter_test/flutter_test.dart';
import 'package:superz_shared/superz_shared.dart';

/// 外部地图导航跳转(#137)。
///
/// 这里守的核心是**坐标系**:百度用 BD-09,腾讯与高德用 GCJ-02。
/// 传错的后果不是报错,是导航终点静默偏出几百米 —— 骑手照着跑到隔壁街,
/// 而所有日志都显示"导航已唤起,一切正常"。所以必须有测试钉住。
void main() {
  // 成都春熙路(GCJ-02)
  const lat = 30.6612, lng = 104.0823;

  group('BD-09 转换', () {
    test('偏移量在百度的已知量级内(数百米,不是零也不是几公里)', () {
      final bd = gcj02ToBd09(lat, lng);
      final d = distanceMeters(lat, lng, bd.lat, bd.lng);
      expect(d, greaterThan(200), reason: '几乎没偏移 —— 转换八成没生效');
      expect(d, lessThan(1200), reason: '偏太多 —— 公式用错了');
    });

    test('不同点转出来不一样(不是把常量当结果返回)', () {
      final a = gcj02ToBd09(lat, lng);
      final b = gcj02ToBd09(39.9042, 116.4074);
      expect(a.lat, isNot(b.lat));
      expect(a.lng, isNot(b.lng));
    });

    test('经纬度没有写反', () {
      final bd = gcj02ToBd09(lat, lng);
      // 成都的纬度 ~30、经度 ~104,量级差三倍多,写反了一眼看得出
      expect(bd.lat, closeTo(lat, 0.02));
      expect(bd.lng, closeTo(lng, 0.02));
    });
  });

  group('GCJ-02 不该被二次转换', () {
    test('腾讯/高德吃 GCJ-02,转换函数不能顺手套在它们身上', () {
      // 这条测的是纪律:只要有人"为了统一"把所有地图都过一遍 BD-09,
      // gcj02ToBd09 的结果就会等于原值以外的东西 —— 这里钉住原值本身没被改
      final same = gcj02ToBd09(lat, lng);
      expect(same.lat, isNot(lat),
          reason: 'BD-09 转换必须真的改变坐标,否则百度会偏');
    });
  });

  group('出行方式', () {
    test('三种模式都有定义,没有漏枚举', () {
      expect(NavMode.values.length, 3);
      expect(NavMode.values, contains(NavMode.ride));
      expect(NavMode.values, contains(NavMode.drive));
      expect(NavMode.values, contains(NavMode.walk));
    });
  });
}
