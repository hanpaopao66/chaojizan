import 'package:flutter_test/flutter_test.dart';
import 'package:superz_shared/design.dart';

/// 相对时间的分档边界最容易写错(跨天、跨年、未来时间),用例钉住。
///
/// ## 为什么把"现在"也钉死
///
/// 分档全是拿"现在"当尺子量出来的。以前这里直接用 `DateTime.now()`,
/// 于是「同一天给小时」那条只能写成 `if (now.hour >= 3) { expect(...) }` ——
/// **每天 0 点到 3 点整条用例一个断言都不跑**。把 szTimeAgo 里当天那一档
/// 整个改成永远返回「刚刚」,在那三个小时里跑,测试照样全绿。
///
/// 现在每条都自带基准时刻:任何时刻跑、跑多少遍,结果都一样,
/// 而且能覆盖到真实时钟很难蹲到的那几个点(刚过午夜、跨年前夜)。
void main() {
  /// [now] 时刻回看 [ago] 之前发生的事,该显示成什么
  String at(DateTime now, Duration ago) =>
      szTimeAgo(now.subtract(ago).toUtc().toIso8601String(), now: now);

  /// 三个基准。`午夜刚过` 是旧写法**永远覆盖不到**的那一档,
  /// 而它恰好是最容易错的:两小时前已经是昨天了。
  const anchors = {
    '下午': (year: 2026, month: 5, day: 20, hour: 14, minute: 30),
    '午夜刚过': (year: 2026, month: 5, day: 20, hour: 0, minute: 30),
    '跨年前夜': (year: 2026, month: 1, day: 1, hour: 2, minute: 5),
  };

  group('不管此刻几点,近的档都一样', () {
    for (final e in anchors.entries) {
      final a = e.value;
      final now = DateTime(a.year, a.month, a.day, a.hour, a.minute);

      test('${e.key}:一分钟内说刚刚', () {
        expect(at(now, const Duration(seconds: 20)), '刚刚');
        expect(at(now, const Duration(seconds: 59)), '刚刚');
      });

      test('${e.key}:一小时内给分钟', () {
        expect(at(now, const Duration(minutes: 1)), '1 分钟前');
        expect(at(now, const Duration(minutes: 12)), '12 分钟前');
        expect(at(now, const Duration(minutes: 59)), '59 分钟前');
      });

      test('${e.key}:满一小时就换档,不再说分钟', () {
        expect(at(now, const Duration(minutes: 60)), isNot(contains('分钟')));
      });

      test('${e.key}:未来时间(预约单/时钟不准)不说负数', () {
        final s = at(now, const Duration(hours: -3));
        expect(s.contains('-'), isFalse, reason: s);
        expect(s.contains('前'), isFalse, reason: s);
      });
    }
  });

  group('当天 / 昨天的分界是午夜,不是"满 24 小时"', () {
    // 下午两点半回看两小时前 —— 还是同一天
    final noon = DateTime(2026, 5, 20, 14, 30);
    test('同一天给小时', () {
      expect(at(noon, const Duration(hours: 2)), '2 小时前');
      expect(at(noon, const Duration(hours: 14)), '14 小时前');
    });

    test('当天最早也只到 00:00,再往前就是昨天', () {
      // 14:30 往前 14 小时 30 分正好是 00:00,还算今天;再多一分钟就跨了
      expect(at(noon, const Duration(hours: 14, minutes: 30)), '14 小时前');
      expect(at(noon, const Duration(hours: 14, minutes: 31)), '昨天 23:59');
    });

    test('午夜刚过时,两小时前已经是昨天了(旧写法蹲不到这一档)', () {
      final justAfterMidnight = DateTime(2026, 5, 20, 0, 30);
      expect(at(justAfterMidnight, const Duration(hours: 2)), '昨天 22:30');
      // 而 31 分钟前还在今天,只是不到一小时,走分钟档
      expect(at(justAfterMidnight, const Duration(minutes: 31)), '31 分钟前');
    });

    test('昨天带时刻', () {
      expect(at(noon, const Duration(days: 1)), '昨天 14:30');
      // 补零:9 点要显示成 09:05 而不是 9:5
      final s = szTimeAgo(DateTime(2026, 5, 19, 9, 5).toUtc().toIso8601String(),
          now: noon);
      expect(s, '昨天 09:05');
    });
  });

  group('更早的记录退回日期', () {
    final noon = DateTime(2026, 5, 20, 14, 30);

    test('同年退回 M/D HH:MM,精度不丢', () {
      expect(at(noon, const Duration(days: 5)), '5/15 14:30');
    });

    test('前天就不再说「昨天」了', () {
      expect(at(noon, const Duration(days: 2)), '5/18 14:30');
    });

    test('跨年只给日期,不给时刻', () {
      expect(
          szTimeAgo(DateTime(2025, 3, 8, 10, 30).toUtc().toIso8601String(),
              now: noon),
          '2025/3/8');
    });

    test('元旦刚过时,昨天仍然是「昨天」而不是跨年日期', () {
      // 1 月 1 日回看 12 月 31 日:虽然年份不同,但它就是昨天
      final newYear = DateTime(2026, 1, 1, 2, 5);
      expect(at(newYear, const Duration(days: 1)), '昨天 02:05');
    });
  });

  test('时间戳解析不了时返回空串,不崩', () {
    expect(szTimeAgo('not-a-time'), '');
    expect(szTimeAgo(''), '');
  });

  test('不传 now 时用系统时钟,行为和以前一样', () {
    // 生产代码走的是这条路径,别让"可注入"变成"只有测试路径是对的"
    expect(szTimeAgo(DateTime.now().toUtc().toIso8601String()), '刚刚');
    expect(
        szTimeAgo(DateTime.now()
            .subtract(const Duration(minutes: 12))
            .toUtc()
            .toIso8601String()),
        '12 分钟前');
  });
}
