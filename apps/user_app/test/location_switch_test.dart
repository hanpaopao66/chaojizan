import 'package:flutter_test/flutter_test.dart';
import 'package:user_app/main.dart';

/// 跨城提示的判据(#282)。
///
/// ## 这个测试防的是什么
///
/// 它决定「要不要打断用户」。打断错了比不打断更烦人 ——
/// 而最坏的一种错是**自动改地址**:人在北京出差、给西安家里老人点单
/// 是最常见的场景之一,App 因为「你人在北京」把地址偷偷改掉,
/// 他不看第二眼就会把饭点到自己出差的酒店。
///
/// 所以这里锁的不只是阈值,还有「什么时候根本不该问」。
void main() {
  group('什么时候提示切换位置', () {
    test('没选收货地址时不提示 —— 那本来就按当前位置找店,人动了直接跟', () {
      expect(
          shouldSuggestLocationSwitch(
              hasDeliveryAddress: false,
              dismissedThisSession: false,
              distanceMeters: 900000),
          isFalse);
    });

    test('这次会话点过「不用」就不再问', () {
      expect(
          shouldSuggestLocationSwitch(
              hasDeliveryAddress: true,
              dismissedThisSession: true,
              distanceMeters: 900000),
          isFalse);
    });

    test('拿不到距离时不提示 —— 不确定就别打断', () {
      expect(
          shouldSuggestLocationSwitch(
              hasDeliveryAddress: true,
              dismissedThisSession: false,
              distanceMeters: null),
          isFalse);
    });

    test('同城跨区(公司→家 20km)不提示', () {
      expect(
          shouldSuggestLocationSwitch(
              hasDeliveryAddress: true,
              dismissedThisSession: false,
              distanceMeters: 20000),
          isFalse,
          reason: '20km 在一个城市里很常见,这种距离上弹提示纯属打扰');
    });

    test('阈值边界:30km 不提示,刚过就提示', () {
      expect(
          shouldSuggestLocationSwitch(
              hasDeliveryAddress: true,
              dismissedThisSession: false,
              distanceMeters: 30000),
          isFalse);
      expect(
          shouldSuggestLocationSwitch(
              hasDeliveryAddress: true,
              dismissedThisSession: false,
              distanceMeters: 30001),
          isTrue);
    });

    test('跨城(西安→北京 约 900km)提示', () {
      expect(
          shouldSuggestLocationSwitch(
              hasDeliveryAddress: true,
              dismissedThisSession: false,
              distanceMeters: 900000),
          isTrue);
    });
  });
}
