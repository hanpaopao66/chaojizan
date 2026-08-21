import 'package:flutter/foundation.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:superz_shared/superz_shared.dart';

/// 外部地图导航跳转(#137)。
///
/// 这里守的核心是**坐标系**:百度用 BD-09,腾讯与高德用 GCJ-02。
/// 传错的后果不是报错,是导航终点静默偏出几百米 —— 骑手照着跑到隔壁街,
/// 而所有日志都显示"导航已唤起,一切正常"。所以必须有测试钉住。
///
/// 钉的是 `navAppUri` / `navWebUri` 真的吐出来的 URL(和 `navigateTo`
/// 用的是同一份构造闭包),不是 `gcj02ToBd09` 这个纯函数本身 ——
/// 只测后者的话,把腾讯和高德也顺手过一遍 BD-09 照样全绿。
void main() {
  // 成都春熙路(GCJ-02)
  const lat = 30.6612, lng = 104.0823;
  const name = '春熙路店'; // 故意不带逗号:高德 web 的 to= 是逗号分隔的三段

  /// 把 "30.66,104.08" 这种拆成一对数
  ({double lat, double lng}) pair(String s, {bool lngFirst = false}) {
    final p = s.split(',').take(2).map(double.parse).toList();
    return lngFirst ? (lat: p[1], lng: p[0]) : (lat: p[0], lng: p[1]);
  }

  /// 断言这对坐标就是传进去的 GCJ-02 原值(没被谁顺手转了一道)
  void expectRawGcj(({double lat, double lng}) got, String where) {
    expect(got.lat, closeTo(lat, 1e-9), reason: '$where 的纬度被改过了');
    expect(got.lng, closeTo(lng, 1e-9), reason: '$where 的经度被改过了');
  }

  /// 断言这对坐标是转过的 BD-09
  void expectBd09(({double lat, double lng}) got, String where) {
    final bd = gcj02ToBd09(lat, lng);
    expect(got.lat, closeTo(bd.lat, 1e-9), reason: '$where 没转 BD-09');
    expect(got.lng, closeTo(bd.lng, 1e-9), reason: '$where 没转 BD-09');
    // 顺带确认"转过"这件事本身是看得见的,不是转了个寂寞
    expect(distanceMeters(lat, lng, got.lat, got.lng), greaterThan(200),
        reason: '$where 和 GCJ-02 原值几乎重合 —— 转换没生效');
  }

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
    // 这里测的是纪律:只要有人"为了统一"把所有地图都过一遍 BD-09,
    // 腾讯/高德的 URL 里坐标就不再等于传进去的原值,这几条必须红。

    test('腾讯 App:tocoord 是 GCJ-02 原值', () {
      final u = navAppUri('腾讯地图', lat: lat, lng: lng, name: name);
      expect(u.scheme, 'qqmap');
      expectRawGcj(pair(u.queryParameters['tocoord']!), '腾讯 App');
    });

    test('腾讯网页:tocoord 是 GCJ-02 原值', () {
      final u = navWebUri('腾讯地图', lat: lat, lng: lng, name: name);
      expect(u.host, 'apis.map.qq.com');
      expectRawGcj(pair(u.queryParameters['tocoord']!), '腾讯网页');
    });

    // 高德的 App 链接分平台,两条都得钉 —— 只钉一条的话,
    // 另一条平台改坏了在 CI 上是看不出来的
    for (final p in [TargetPlatform.iOS, TargetPlatform.android]) {
      test('高德 App(${p.name}):dlat/dlon 是 GCJ-02 原值,且 dev=0', () {
        debugDefaultTargetPlatformOverride = p;
        addTearDown(() => debugDefaultTargetPlatformOverride = null);
        final u = navAppUri('高德地图', lat: lat, lng: lng, name: name);
        expect(u.scheme, p == TargetPlatform.iOS ? 'iosamap' : 'amapuri');
        expectRawGcj(
          (
            lat: double.parse(u.queryParameters['dlat']!),
            lng: double.parse(u.queryParameters['dlon']!),
          ),
          '高德 App(${p.name})',
        );
        // dev=0 = "我给的已经是 GCJ-02,别再纠偏一次"。
        // 丢了它高德会自己再转一道,效果和二次转换一样
        expect(u.queryParameters['dev'], '0');
      });
    }

    test('高德网页:to= 是 经度,纬度 顺序的 GCJ-02 原值', () {
      final u = navWebUri('高德地图', lat: lat, lng: lng, name: name);
      expect(u.host, 'uri.amap.com');
      final to = u.queryParameters['to']!.split(',');
      expect(to.last, name, reason: '第三段应该是名字');
      expectRawGcj(pair(u.queryParameters['to']!, lngFirst: true), '高德网页');
    });

    test('百度是唯一要转的:App 链接里是 BD-09,并声明 coord_type', () {
      final u = navAppUri('百度地图', lat: lat, lng: lng, name: name);
      expect(u.scheme, 'baidumap');
      final dest = u.queryParameters['destination']!;
      expect(dest, contains('name:$name'));
      expectBd09(pair(dest.split('latlng:').last), '百度 App');
      // 坐标转了但没声明坐标系,百度会按 GCJ-02 解释 —— 等于白转
      expect(u.queryParameters['coord_type'], 'bd09ll');
    });

    test('百度网页:destination 是 BD-09,并声明 coord_type', () {
      final u = navWebUri('百度地图', lat: lat, lng: lng, name: name);
      expect(u.host, 'api.map.baidu.com');
      expectBd09(pair(u.queryParameters['destination']!), '百度网页');
      expect(u.queryParameters['coord_type'], 'bd09ll');
    });

    test('三家都在,一家也没漏', () {
      expect(kNavMaps, ['腾讯地图', '高德地图', '百度地图']);
    });
  });

  group('出行方式', () {
    test('三种模式都有定义,没有漏枚举', () {
      expect(NavMode.values.length, 3);
      expect(NavMode.values, contains(NavMode.ride));
      expect(NavMode.values, contains(NavMode.drive));
      expect(NavMode.values, contains(NavMode.walk));
    });

    // 三家的出行方式参数名各不相同,写串了不报错 ——
    // 骑手拿到的是驾车路线(走机动车道、绕高架),比不给导航更糟
    for (final map in ['腾讯地图', '高德地图', '百度地图']) {
      test('$map:三种模式给出三个不同的链接', () {
        final urls = {
          for (final m in NavMode.values)
            m: navAppUri(map, lat: lat, lng: lng, name: name, mode: m)
                .toString(),
        };
        expect(urls.values.toSet().length, 3,
            reason: '$map 有两种出行方式跳到了同一个链接:$urls');
      });
    }
  });

  test('未知地图名当场报错,不静默给个错链接', () {
    expect(() => navAppUri('谷歌地图', lat: lat, lng: lng, name: name),
        throwsArgumentError);
  });
}
