import 'package:flutter_test/flutter_test.dart';
import 'package:superz_shared/superz_shared.dart';
import 'package:user_app/address_pages.dart';

/// 地址簿排序(#171)。
///
/// ## 为什么这个文件在 user_app 而不在 packages/shared
///
/// 排序只有用户端用,逻辑就住在 `lib/address_pages.dart`。
/// 测试原先放在 `packages/shared/test/` 下 —— 那里**物理上 import 不到**
/// 用户端的代码,于是它只能把排序规则抄一份在测试体里,测的是副本:
/// 把生产代码里「默认地址置顶」那行删掉,它照样全绿。
///
/// 现在测的是 `sortAddressBook` 本人。
void main() {
  Address addr({
    required int id,
    required String name,
    required double lat,
    required double lng,
    bool isDefault = false,
  }) =>
      Address.fromJson({
        'id': id,
        'contact_name': name,
        'contact_phone': '13800000000',
        'address': name,
        'detail': '',
        'lat': lat,
        'lng': lng,
        'is_default': isDefault,
      });

  // 成都春熙路一带。myLat/myLng 正好压在 2 号地址上
  const myLat = 30.6598, myLng = 104.0810;
  final rows = [
    addr(id: 1, name: '公司前台', lat: 30.6700, lng: 104.0900, isDefault: true),
    addr(id: 2, name: '春熙路 2 单元 501', lat: 30.6598, lng: 104.0810),
    addr(id: 3, name: '天府广场', lat: 30.6570, lng: 104.0650),
  ];

  test('默认地址排最前,但「距离最近」标在真的最近那个上', () {
    final r = sortAddressBook(rows, myLat: myLat, myLng: myLng);

    // 默认地址仍排最前 —— 用户特意设过,那是他的明确意愿,
    // 哪怕它是三个里最远的(1.4km)也不能被距离挤走
    expect(r.list.first.isDefault, isTrue);
    expect(r.list.first.id, 1);
    // 但「距离最近」标的是真的最近那个,不是排序后的第一个
    expect(r.nearestId, 2);
    expect(r.nearestM, lessThan(10));
  });

  test('默认地址之外按距离排,不是原顺序', () {
    // 3 号(1.5km)比 2 号(0m)远,把它放在前面喂进去 ——
    // 排完必须换过来,否则说明根本没按距离排
    final r = sortAddressBook(
      [rows[0], rows[2], rows[1]],
      myLat: myLat,
      myLng: myLng,
    );
    expect(r.list.map((a) => a.id).toList(), [1, 2, 3]);
  });

  test('默认地址本来就最近时,置顶和标签指同一个', () {
    final r = sortAddressBook([
      addr(id: 1, name: '公司前台', lat: 30.6700, lng: 104.0900),
      addr(id: 2, name: '春熙路', lat: myLat, lng: myLng, isDefault: true),
    ], myLat: myLat, myLng: myLng);
    expect(r.list.first.id, 2);
    expect(r.nearestId, 2);
  });

  test('没定位:保持服务端顺序,不打「距离最近」标签', () {
    // 定位失败/没授权时不能因此让用户选不了地址
    final r = sortAddressBook(rows);
    expect(r.list.map((a) => a.id).toList(), [1, 2, 3]);
    expect(r.nearestId, isNull, reason: '没定位就别声称谁最近');
  });

  test('只有一个地址时不排也不标', () {
    final one = [rows[2]];
    final r = sortAddressBook(one, myLat: myLat, myLng: myLng);
    expect(r.list.single.id, 3);
    expect(r.nearestId, isNull, reason: '独一份没有「最近」可言');
  });

  test('不就地改调用方的列表', () {
    // _load() 拿到的是接口返回的列表,排序不该反过来把它搅了
    final input = [rows[2], rows[1], rows[0]];
    sortAddressBook(input, myLat: myLat, myLng: myLng);
    expect(input.map((a) => a.id).toList(), [3, 2, 1]);
  });
}
