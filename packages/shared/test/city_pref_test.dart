import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:superz_shared/superz_shared.dart';

/// 地址搜索的城市从哪来(#281 反馈)。
///
/// ## 这个顺序反过来过一次,别再反回去
///
/// 原来是「记住的选择 > 定位」,理由是「他多半在给固定的地方点单,
/// 每次重选是折磨」。但那个顺序在两种真实场景里都是错的:
///
/// - 他在西安,偶尔给北京朋友点一次 → 记住北京 → 此后一直北京,
///   而他人在西安,搜自己家又搜不到 —— 正是这个组件当初要解决的那个 bug;
/// - 他从西安搬到北京 → 记住西安 → 定位早变了,城市却不跟。
///
/// 所以默认跟定位;记住的那个只在**定位拿不到**时兜底。
void main() {
  setUp(() => SharedPreferences.setMockInitialValues({}));

  test('定位拿得到时,以定位为准 —— 哪怕记过别的城市', () async {
    await CityPref.save('北京市');
    final city = await CityPref.resolve(
      lastKnown: () async => (lat: 34.34, lng: 108.94), // 西安
      reverse: (lat, lng) async => '西安市', // 服务端给的结构化城市名
    );
    expect(city, '西安市',
        reason: '记住的城市盖过了定位 —— 他人在西安却在按北京搜,'
            '搜自己家会一条都搜不到');
  });

  test('定位拿不到时,用记住的那个兜底', () async {
    await CityPref.save('北京市');
    final city = await CityPref.resolve(
      lastKnown: () async => null,
      reverse: (lat, lng) async => '',
    );
    expect(city, '北京市');
  });

  test('逆地理失败时也退回记住的', () async {
    await CityPref.save('成都市');
    final city = await CityPref.resolve(
      lastKnown: () async => (lat: 34.34, lng: 108.94),
      reverse: (lat, lng) async => throw Exception('网络炸了'),
    );
    expect(city, '成都市');
  });

  test('都没有就留空 —— 不猜一个填进去', () async {
    final city = await CityPref.resolve(
      lastKnown: () async => null,
      reverse: (lat, lng) async => '',
    );
    expect(city, '',
        reason: '猜错了用户会以为已经选对,然后搜不出东西也不知道为什么');
  });

  test('城市名原样用,客户端不做任何解析', () async {
    // 解析在服务端(/geo/reverse 取腾讯的 address_component.city,
    // 直辖市那里 city 为空所以退回 province)。客户端再抠一次的下场是
    // 贪婪正则把「陕西省西安市雁塔区」抠成「陕西省西安市」
    for (final want in ['西安市', '北京市', '南宁市', '成都市']) {
      SharedPreferences.setMockInitialValues({});
      final city = await CityPref.resolve(
        lastKnown: () async => (lat: 1.0, lng: 1.0),
        reverse: (lat, lng) async => want,
      );
      expect(city, want);
    }
  });

  test('服务端给不出城市时留空,不硬凑', () async {
    final city = await CityPref.resolve(
      lastKnown: () async => (lat: 1.0, lng: 1.0),
      reverse: (lat, lng) async => '',
    );
    expect(city, '');
  });
}
