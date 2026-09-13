import 'package:flutter_test/flutter_test.dart';
import 'package:user_app/video/notify/notify_format.dart';

/// 「视频互动」会话把四类互动合成一条时间线(设计稿 C)。服务端只能按类拉、各有各的游标,
/// 合的时候只显示到「水位」为止 —— 否则翻下一页时会有条目插回已经显示过的位置。
void main() {
  final t0 = DateTime(2026, 9, 13, 12);
  NotifyItem n(int id, String kind, int minutesAgo, {bool read = true}) => NotifyItem.fromJson({
        'id': id,
        'kind': kind,
        'read': read,
        'updated_at': t0.subtract(Duration(minutes: minutesAgo)).toUtc().toIso8601String(),
      });

  test('四类合成一条,从新到旧;还有下一页的那类卡住水位', () {
    final m = NotifyMerge()
      ..put('reply', [n(1, 'reply', 1), n(2, 'reply', 10)], next: 'r2')
      ..put('at', [n(3, 'at', 5)])
      ..put('like', [n(4, 'like', 2), n(5, 'like', 30)])
      ..put('system', const []);
    // reply 还有下一页,它拉到的最旧那条是 10 分钟前:比它更旧的(like 的 30 分钟前)先不显示
    expect([for (final x in m.visible()) x.id], [1, 4, 3, 2]);
    expect(m.nextKind(), 'reply');
    expect(m.cursorOf('reply'), 'r2');

    // 往上翻:拉了 reply 的下一页,水位没了,30 分钟前那条才排进来
    m.put('reply', [n(6, 'reply', 20)], older: true);
    expect([for (final x in m.visible()) x.id], [1, 4, 3, 2, 6, 5]);
    expect(m.hasMore, isFalse);
  });

  test('新来的赞把那条刷到最前:同一个 id 只留新的一份,游标不退回第一页', () {
    final m = NotifyMerge()
      ..put('like', [n(4, 'like', 2), n(5, 'like', 30)], next: 'l2')
      ..put('reply', const [])
      ..put('at', const [])
      ..put('system', const []);
    m.put('like', [n(4, 'like', 40)], next: 'l2', older: true); // 翻到了第二页
    // 开着的时候来了新赞:重拉第一页,id 5 的那条被刷到了最新
    m.put('like', [n(5, 'like', 0, read: false), n(4, 'like', 2)], next: 'l2-first');
    expect([for (final x in m.visible()) x.id], [5, 4]);
    expect(m.visible().first.read, isFalse);
    expect(m.cursorOf('like'), 'l2', reason: '已经往上翻过,游标还停在翻到的地方');
  });

  test('未读数只数「提醒设置」里勾上的几类', () {
    const unread = {'reply': 2, 'at': 1, 'like': 9, 'system': 1, 'total': 13};
    expect(notifyBadgeCount(unread, {'reply', 'at', 'like', 'system'}), 13);
    expect(notifyBadgeCount(unread, {'reply', 'at'}), 3);
    expect(notifyBadgeCount(unread, const {}), 0);
  });
}
