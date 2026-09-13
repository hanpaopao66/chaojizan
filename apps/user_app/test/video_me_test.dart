// 视频「我的」和互动消息(DEV-PROMPTS-40 #366 #367)的纯函数:历史按天分组、历史副标题、硬币流水、
// 互动消息的标题和头像合并、翻页器、角标跟着用户事件走。
import 'dart:async';

import 'package:flutter_test/flutter_test.dart';
import 'package:user_app/chat/store.dart';
import 'package:user_app/video/me/common.dart';
import 'package:user_app/video/me/me_format.dart';
import 'package:user_app/video/models.dart';
import 'package:user_app/video/notify/notifications_page.dart';
import 'package:user_app/video/notify/notify_format.dart';

HistoryEntry at(DateTime t, {String vid = 'svA', int pos = 5200, int dur = 6000, int part = 0, bool invalid = false}) =>
    HistoryEntry(
      video: VideoCard(vid: vid, title: invalid ? '视频已失效' : '标题', invalid: invalid),
      partIdx: part,
      positionMs: pos,
      durationMs: dur,
      watchedAt: t,
    );

NotifyItem notify(Map<String, dynamic> over) => NotifyItem.fromJson({
      'id': 407,
      'kind': 'reply',
      'title': '',
      'text': '+1',
      'actor': {'id': 238, 'name': '小王', 'username': null, 'avatar': ''},
      'actors': [
        {'id': 238, 'name': '小王', 'username': null, 'avatar': ''},
      ],
      'count': 1,
      'video': {'vid': 'svHbFUgZ3A32', 'title': '示例视频', 'cover': '/img/x.jpg'},
      'comment': {'id': 234, 'root_id': 232, 'deleted': false},
      'data': {'target': 'comment', 'root_id': 232, 'replied_text': '谢谢!'},
      'read': false,
      'created_at': '2026-09-13T02:09:40.060815+00:00',
      'updated_at': '2026-09-13T02:09:40.060815+00:00',
      ...over,
    });

Map<String, dynamic> person(int id, String name) => {'id': id, 'name': name, 'username': null, 'avatar': ''};

void main() {
  group('历史按天分组', () {
    final now = DateTime(2026, 9, 12, 10, 0);

    test('今天 / 昨天 / 今年的日期 / 往年带年份', () {
      expect(historyDayLabel(DateTime(2026, 9, 12, 0, 1), now), '今天');
      expect(historyDayLabel(DateTime(2026, 9, 11, 23, 59), now), '昨天');
      expect(historyDayLabel(DateTime(2026, 9, 11, 0, 0), now), '昨天');
      expect(historyDayLabel(DateTime(2026, 9, 10, 23, 0), now), '9月10日');
      expect(historyDayLabel(DateTime(2025, 12, 31, 12, 0), now), '2025年12月31日');
    });

    test('「昨天」按日历算:跨月、跨年', () {
      expect(historyDayLabel(DateTime(2026, 9, 30, 22), DateTime(2026, 10, 1, 8)), '昨天');
      expect(historyDayLabel(DateTime(2025, 12, 31, 23), DateTime(2026, 1, 1, 0, 30)), '昨天');
      // 离现在不到 24 小时但已经是前天了
      expect(historyDayLabel(DateTime(2026, 9, 10, 23, 50), DateTime(2026, 9, 12, 0, 10)), '9月10日');
    });

    test('新看的在前,组的顺序和组内顺序都不变', () {
      final items = [
        at(DateTime(2026, 9, 12, 9), vid: 'a'),
        at(DateTime(2026, 9, 12, 1), vid: 'b'),
        at(DateTime(2026, 9, 11, 22), vid: 'c'),
        at(DateTime(2026, 9, 3, 8), vid: 'd'),
        at(DateTime(2025, 11, 1), vid: 'e'),
      ];
      final g = groupHistoryByDay(items, now);
      expect([for (final x in g) x.label], ['今天', '昨天', '9月3日', '2025年11月1日']);
      expect([for (final x in g.first.items) x.video.vid], ['a', 'b']);
    });

    test('同一天被隔开(翻页边界上时钟不准)也并进一组;没有时间的放「更早」', () {
      final items = [
        at(DateTime(2026, 9, 12, 9), vid: 'a'),
        at(DateTime(2026, 9, 11, 9), vid: 'b'),
        at(DateTime(2026, 9, 12, 8), vid: 'c'),
        HistoryEntry(video: VideoCard(vid: 'd', title: 't')),
      ];
      final g = groupHistoryByDay(items, now);
      expect([for (final x in g) x.label], ['今天', '昨天', '更早']);
      expect([for (final x in g.first.items) x.video.vid], ['a', 'c']);
    });

    test('空列表没有组', () {
      expect(groupHistoryByDay(const [], now), isEmpty);
    });
  });

  group('历史的一行', () {
    test('进度:不知道时长不画;超出的夹到 1', () {
      expect(at(DateTime(2026), dur: 0).progress, isNull);
      expect(at(DateTime(2026), pos: 3000, dur: 6000).progress, .5);
      expect(at(DateTime(2026), pos: 9000, dur: 6000).progress, 1);
    });

    test('副标题:看到哪、第几 P、几点', () {
      final t = DateTime(2026, 9, 12, 14, 32);
      expect(historySubtitle(at(t, pos: 65000, dur: 600000)), '看到 1:05 · 14:32');
      expect(historySubtitle(at(t, pos: 65000, dur: 600000, part: 1)), 'P2 看到 1:05 · 14:32');
      expect(historySubtitle(at(t, pos: 597500, dur: 600000)), '已看完 · 14:32');
      expect(historySubtitle(at(t, pos: 580000, dur: 600000)), '已看完 · 14:32', reason: '过了 95% 算看完');
      expect(historySubtitle(at(t, pos: 200, dur: 600000)), '刚点开 · 14:32');
      // 4 秒的短片看到 2.5 秒:离结尾不到 3 秒,但只看了六成,不能说看完了
      expect(historySubtitle(at(t, pos: 2500, dur: 4000)), '看到 0:02 · 14:32');
      expect(historySubtitle(at(t, invalid: true)), '视频已失效');
    });

    test('从接口的一条读出来(失效的视频也读得出)', () {
      final e = HistoryEntry.fromJson({
        'video': {'vid': 'svX', 'title': '视频已失效', 'cover': '', 'invalid': true},
        'part_idx': 1,
        'position_ms': 5200,
        'duration_ms': 6000,
        'watched_at': '2026-09-13T02:09:39.974617+00:00',
      });
      expect(e.video.invalid, isTrue);
      expect(e.partIdx, 1);
      expect(e.watchedAt, DateTime.utc(2026, 9, 13, 2, 9, 39, 974, 617).toLocal());
    });
  });

  group('硬币', () {
    test('正负号:+2 / −1(减号是 U+2212)', () {
      expect(coinDelta(2), '+2');
      expect(coinDelta(-1), '−1');
      expect(coinDelta(0), '0');
    });

    test('原因:服务端给了中文用中文,没给按四个来源翻', () {
      expect(coinReason({'reason': 'coin_give', 'reason_label': '投币'}), '投币');
      expect(coinReason({'reason': 'daily'}), '每日首次打开视频');
      expect(coinReason({'reason': 'video_approved', 'reason_label': ''}), '投稿过审');
      expect(coinReasonLabels.keys, ['daily', 'video_approved', 'coin_give', 'coin_receive'],
          reason: 'S4:硬币只有这四种流水,没有充值、提现、兑换');
    });
  });

  group('互动消息的标题', () {
    test('服务端拼好的直接用', () {
      expect(notifyHeadline(notify({'title': '用户0036 回复了你的评论'})), '用户0036 回复了你的评论');
    });

    test('没给标题时按服务端同一套口径拼', () {
      expect(notifyHeadline(notify({})), '小王 回复了你的评论');
      expect(notifyHeadline(notify({'data': {'target': 'video'}})), '小王 评论了你的视频');
      expect(notifyHeadline(notify({'kind': 'at'})), '小王 在评论里 @ 了你');
      expect(notifyHeadline(notify({'kind': 'like', 'count': 12, 'data': {'target': 'video'}})), '小王等 12 人赞了你的视频');
      expect(notifyHeadline(notify({'kind': 'like', 'count': 1, 'data': {'target': 'comment'}})), '小王 赞了你的评论');
      expect(notifyHeadline(notify({'kind': 'system', 'actor': null, 'actors': [], 'data': {'title': '视频审核通过'}})),
          '视频审核通过');
      expect(notifyHeadline(notify({'kind': 'system', 'actor': null, 'actors': [], 'data': {}})), '系统通知');
      expect(notifyHeadline(notify({'kind': 'reply', 'actor': null, 'actors': []})), '有人 回复了你的评论');
    });
  });

  group('头像合并', () {
    test('最近那个人在最前,按 id 去重,最多 3 个;赞合并的剩下几个人算进 +N', () {
      final n = notify({
        'kind': 'like',
        'count': 12,
        'actor': person(3, '丙'),
        'actors': [person(3, '丙'), person(2, '乙'), person(1, '甲'), person(9, '壬')],
      });
      final a = notifyAvatars(n);
      expect([for (final p in a.shown) p.name], ['丙', '乙', '甲']);
      expect(a.more, 9);
    });

    test('不是赞:只有一个人,没有 +N', () {
      final a = notifyAvatars(notify({}));
      expect([for (final p in a.shown) p.id], [238]);
      expect(a.more, 0);
    });

    test('赞数比画出来的头像还少(有人取消了赞):不出现负数', () {
      final a = notifyAvatars(notify({
        'kind': 'like',
        'count': 1,
        'actors': [person(238, '小王'), person(5, '小李')],
      }));
      expect(a.shown.length, 2);
      expect(a.more, 0);
    });

    test('系统通知没有人', () {
      final a = notifyAvatars(notify({'kind': 'system', 'actor': null, 'actors': []}));
      expect(a.shown, isEmpty);
      expect(a.more, 0);
    });
  });

  group('互动消息的跳转和标签', () {
    test('有评论就定位到评论;评论删了只打开视频', () {
      expect(notify({}).commentId, 234);
      expect(notify({'comment': {'id': 234, 'root_id': 232, 'deleted': true}}).commentId, isNull);
      expect(notify({'comment': null}).commentId, isNull);
      expect(notify({'video': null}).vid, '');
    });

    test('系统通知的动作', () {
      expect(systemActionLabel('approve'), '审核通过');
      expect(systemActionLabel('reject_changes'), '改动未通过');
      expect(systemActionLabel('appeal_overturned'), '申诉成立');
      expect(systemActionLabel('whatever'), '');
      expect(systemActionBad('remove'), isTrue);
      expect(systemActionBad('approve'), isFalse);
    });

    test('角标超过 99 写 99+', () {
      expect(unreadBadge(7), '7');
      expect(unreadBadge(100), '99+');
    });

    test('四个页签的顺序', () {
      expect([for (final k in notifyKinds) k.$1], ['reply', 'at', 'like', 'system']);
    });
  });

  group('互动消息角标跟着用户事件走', () {
    test('notify 事件的 unread.total 直接覆盖角标;停掉之后清零、不再跟', () async {
      // 测试里没登录:start 不去拉接口,只挂订阅
      startVideoNotifyWatcher();
      expect(videoNotifyUnread.value, 0);
      final events = ChatStore.instance.userEvents;
      events.add((type: 'notify', data: {'kind': 'reply', 'unread': {'reply': 2, 'at': 0, 'like': 1, 'system': 1, 'total': 4}}));
      await Future<void>.delayed(Duration.zero);
      expect(videoNotifyUnread.value, 4);
      // 别的类型的事件不碰角标
      events.add((type: 'video', data: {'vid': 'svX', 'status': 'reviewing'}));
      await Future<void>.delayed(Duration.zero);
      expect(videoNotifyUnread.value, 4);
      // 重复调 start 不会挂第二个订阅(否则每个事件会被处理两次,这里看不出来,但不能漏掉订阅)
      startVideoNotifyWatcher();
      events.add((type: 'notify', data: {'kind': null, 'unread': {'total': 0}}));
      await Future<void>.delayed(Duration.zero);
      expect(videoNotifyUnread.value, 0);
      stopVideoNotifyWatcher();
      events.add((type: 'notify', data: {'unread': {'total': 9}}));
      await Future<void>.delayed(Duration.zero);
      expect(videoNotifyUnread.value, 0);
    });
  });

  group('按游标翻页', () {
    test('翻到 next_cursor 为 null 为止', () async {
      final calls = <String?>[];
      final p = CursorPager<int>((cursor) async {
        calls.add(cursor);
        return cursor == null ? (items: [1, 2], next: 'c2', extra: const <String, dynamic>{}) : (items: [3], next: null, extra: const <String, dynamic>{});
      });
      await p.refresh();
      expect(p.items, [1, 2]);
      expect(p.hasMore, isTrue);
      await p.more();
      expect(p.items, [1, 2, 3]);
      expect(p.hasMore, isFalse);
      await p.more();
      expect(calls, [null, 'c2'], reason: '到底了不再请求');
    });

    test('下拉刷新时,晚回来的旧一页丢掉,不接在新的第一页后面', () async {
      final slow = Completer<CursorPage<int>>();
      var first = true;
      final p = CursorPager<int>((cursor) {
        if (cursor == null) {
          final page = first ? [1, 2] : [10, 20];
          first = false;
          return Future.value((items: page, next: 'c2', extra: const <String, dynamic>{}));
        }
        return slow.future;
      });
      await p.refresh();
      final more = p.more(); // 第二页在路上
      await p.refresh(); // 这时候下拉刷新
      slow.complete((items: [3], next: null, extra: const <String, dynamic>{}));
      await more;
      expect(p.items, [10, 20]);
      expect(p.hasMore, isTrue);
    });

    test('第一页失败是整页错误;有数据之后再失败只在尾巴上提示,旧数据留着', () async {
      var fail = true;
      final p = CursorPager<int>((cursor) async {
        if (fail) throw Exception('断网');
        return (items: [1], next: null, extra: const <String, dynamic>{});
      });
      await p.refresh();
      expect(p.error, isNotNull);
      expect(p.loaded, isFalse);
      fail = false;
      await p.refresh();
      expect(p.items, [1]);
      expect(p.error, isNull);
      fail = true;
      await p.refresh();
      expect(p.items, [1]);
      expect(p.moreError, isNotNull);
    });

    test('改一条 / 插一条 / 删一条', () async {
      final p = CursorPager<String>((_) async => (items: ['a', 'b'], next: null, extra: const <String, dynamic>{}));
      await p.refresh();
      p.upsert((x) => x == 'b', 'B');
      p.upsert((x) => x == 'z', 'z', orInsert: true);
      p.upsert((x) => x == 'y', 'y');
      expect(p.items, ['z', 'a', 'B']);
      p.removeWhere((x) => x == 'a');
      expect(p.items, ['z', 'B']);
    });
  });
}
