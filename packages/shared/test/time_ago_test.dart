import 'package:flutter_test/flutter_test.dart';
import 'package:superz_shared/design.dart';

/// 相对时间的分档边界最容易写错(跨天、跨年、未来时间),用例钉住。
void main() {
  String ago(Duration d) =>
      szTimeAgo(DateTime.now().subtract(d).toUtc().toIso8601String());

  test('一分钟内说刚刚', () {
    expect(ago(const Duration(seconds: 20)), '刚刚');
  });

  test('一小时内给分钟', () {
    expect(ago(const Duration(minutes: 12)), '12 分钟前');
    expect(ago(const Duration(minutes: 59)), '59 分钟前');
  });

  test('同一天给小时', () {
    final now = DateTime.now();
    // 只有当天早于当前时刻足够多小时才落进"当天"这一档
    if (now.hour >= 3) {
      expect(ago(const Duration(hours: 2)), '2 小时前');
    }
  });

  test('昨天带时刻', () {
    final t = DateTime.now().subtract(const Duration(days: 1));
    final s = szTimeAgo(t.toUtc().toIso8601String());
    expect(s.startsWith('昨天 '), isTrue, reason: s);
  });

  test('更早的同年记录退回 M/D HH:MM,精度不丢', () {
    final t = DateTime.now().subtract(const Duration(days: 5));
    final s = szTimeAgo(t.toUtc().toIso8601String());
    expect(s, contains('${t.month}/${t.day} '));
    expect(s.contains(':'), isTrue, reason: s);
  });

  test('跨年只给日期', () {
    final t = DateTime(DateTime.now().year - 1, 3, 8, 10, 30);
    expect(szTimeAgo(t.toUtc().toIso8601String()), '${t.year}/3/8');
  });

  test('未来时间(预约单/时钟不准)不说负数', () {
    final t = DateTime.now().add(const Duration(hours: 3));
    final s = szTimeAgo(t.toUtc().toIso8601String());
    expect(s.contains('-'), isFalse, reason: s);
    expect(s.contains('前'), isFalse, reason: s);
  });

  test('时间戳解析不了时返回空串,不崩', () {
    expect(szTimeAgo('not-a-time'), '');
    expect(szTimeAgo(''), '');
  });
}
