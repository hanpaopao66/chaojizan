import 'package:flutter_test/flutter_test.dart';
import 'package:rider_app/location_service.dart';

/// 保活上报的取舍。
///
/// 这一组测的是**不上报**这件事,而不是上报 —— 定位死掉之后
/// `lastFix` 会一直停在最后一个坐标上,保活定时器每 15 秒把它当新位置报一次,
/// 服务端那套「位置过期就停用接单半径筛选」的保护因此永远不会触发。
/// 骑手看到的只是「今天怎么没单」。
void main() {
  final now = DateTime(2026, 8, 20, 12, 0);
  Fix fixAt(Duration ago) => (lat: 30.66, lng: 104.08, at: now.subtract(ago));

  group('keepAliveDecision', () {
    test('位置是新的:照报', () {
      expect(
        keepAliveDecision(
            fix: fixAt(const Duration(seconds: 10)), gpsActive: true, now: now),
        PositionReport.fix,
      );
    });

    test('位置过期(超过 2 分钟):什么都不报', () {
      expect(
        keepAliveDecision(
            fix: fixAt(const Duration(minutes: 3)), gpsActive: true, now: now),
        PositionReport.stale,
      );
    });

    test('定位死了很久,坐标还在 —— 依然不许报', () {
      expect(
        keepAliveDecision(
            fix: fixAt(const Duration(hours: 4)), gpsActive: true, now: now),
        PositionReport.stale,
        reason: '这就是修之前每 15 秒报一次的那个陈年坐标',
      );
    });

    test('刚好卡在门槛上算新的', () {
      expect(
        keepAliveDecision(
            fix: fixAt(const Duration(minutes: 2)), gpsActive: true, now: now),
        PositionReport.fix,
      );
      expect(
        keepAliveDecision(
            fix: fixAt(const Duration(minutes: 2, seconds: 1)),
            gpsActive: true,
            now: now),
        PositionReport.stale,
      );
    });

    test('没有真 GPS(演示/没权限):报兜底坐标,这条路径不声称是真实位置', () {
      expect(
        keepAliveDecision(fix: null, gpsActive: false, now: now),
        PositionReport.fallback,
      );
      // 兜底模式下即使有个旧坐标,也走兜底 —— 不会把旧的当新的报
      expect(
        keepAliveDecision(
            fix: fixAt(const Duration(hours: 1)), gpsActive: false, now: now),
        PositionReport.fallback,
      );
    });

    test('GPS 活着但还没出第一个点:等,别报', () {
      expect(
        keepAliveDecision(fix: null, gpsActive: true, now: now),
        PositionReport.waiting,
      );
    });
  });

  group('LocationService.isFresh', () {
    test('没有定位过 = 不新鲜', () {
      expect(LocationService().isFresh(), isFalse);
    });

    test('刚拿到的点是新鲜的', () {
      final svc = LocationService()
        ..lastFix = (lat: 30.66, lng: 104.08, at: DateTime.now());
      expect(svc.isFresh(), isTrue);
    });

    test('十分钟前的点不新鲜', () {
      final svc = LocationService()
        ..lastFix = (
          lat: 30.66,
          lng: 104.08,
          at: DateTime.now().subtract(const Duration(minutes: 10)),
        );
      expect(svc.isFresh(), isFalse);
    });

    test('stop() 之后位置作废 —— 停了还拿旧坐标报就是在报一个过去的位置', () {
      final svc = LocationService()
        ..lastFix = (lat: 30.66, lng: 104.08, at: DateTime.now());
      svc.stop();
      expect(svc.lastFix, isNull);
      expect(svc.isFresh(), isFalse);
      expect(svc.isActive, isFalse);
    });
  });
}
