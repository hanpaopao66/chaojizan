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
      reverse: (lat, lng) async => '陕西省西安市雁塔区科技路',
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

  test('省名不能被吃进城市里 —— 「陕西省西安市」不是城市名', () async {
    for (final (raw, want) in [
      ('陕西省西安市雁塔区科技路', '西安市'),
      ('北京市朝阳区建国路', '北京市'), // 直辖市没有省前缀
      ('广西壮族自治区南宁市青秀区', '南宁市'),
      ('四川省成都市锦江区春熙路', '成都市'),
    ]) {
      SharedPreferences.setMockInitialValues({});
      final city = await CityPref.resolve(
        lastKnown: () async => (lat: 1.0, lng: 1.0),
        reverse: (lat, lng) async => raw,
      );
      expect(city, want,
          reason: '「$raw」解析成了「$city」—— 拿它当腾讯 POI 的 city 参数'
              '会搜出 0 条,而界面上看不出为什么');
    }
  });

  test('逆地理串里没有「市」时不硬凑', () async {
    final city = await CityPref.resolve(
      lastKnown: () async => (lat: 1.0, lng: 1.0),
      reverse: (lat, lng) async => '某个海外地址',
    );
    expect(city, '');
  });
}
