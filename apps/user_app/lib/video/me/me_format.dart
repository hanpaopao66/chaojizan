// 「我的」几页的纯函数:历史按天分组、历史的副标题、硬币流水的文字。单测锁住。
import '../models.dart';

/// 历史里的一条(VIDEO-API 5.1)。
class HistoryEntry {
  const HistoryEntry({required this.video, this.partIdx = 0, this.positionMs = 0, this.durationMs = 0, this.watchedAt});

  factory HistoryEntry.fromJson(Object? j) {
    final m = vMap(j);
    return HistoryEntry(
      video: VideoCard.fromJson(m['video']),
      partIdx: vInt(m['part_idx']),
      positionMs: vInt(m['position_ms']),
      durationMs: vInt(m['duration_ms']),
      watchedAt: m['watched_at'] == null ? null : DateTime.tryParse('${m['watched_at']}')?.toLocal(),
    );
  }

  final VideoCard video;
  final int partIdx;
  final int positionMs;
  final int durationMs;
  final DateTime? watchedAt;

  /// 看到哪了(0–1),封面底下那条进度;不知道时长就不画
  double? get progress => durationMs > 0 ? (positionMs / durationMs).clamp(0.0, 1.0) : null;

  /// 看完了:过了 95%(片尾字幕不看也算看完)。
  ///
  /// 不用「离结尾不到 3 秒」:4 秒的短片看到 2.5 秒也离结尾不到 3 秒,会被说成看完了
  /// (真数据里撞上过);长视频的片尾本来就在最后 5% 里,95% 一条就够。
  bool get finished => durationMs > 0 && positionMs / durationMs >= .95;
}

bool _sameDay(DateTime a, DateTime b) => a.year == b.year && a.month == b.month && a.day == b.day;

/// 分组的标题:今天 / 昨天 / 今年的写「9月8日」/ 往年的带年份。
///
/// 「昨天」按日历算(`DateTime(y, m, d - 1)` 会自己进位到上个月),不按「减 24 小时」——
/// 夏令时那天减 24 小时会落到前天或者还在今天。
String historyDayLabel(DateTime t, DateTime now) {
  if (_sameDay(t, now)) return '今天';
  if (_sameDay(t, DateTime(now.year, now.month, now.day - 1))) return '昨天';
  if (t.year == now.year) return '${t.month}月${t.day}日';
  return '${t.year}年${t.month}月${t.day}日';
}

typedef HistoryGroup = ({String label, List<HistoryEntry> items});

/// 历史按天分组。接口本来就是新看的在前,组的顺序按第一次出现的先后,组内保持原顺序;
/// 同一天的就算中间被别的天隔开(翻页边界上时钟不准)也并进同一组,不出现两个「今天」。
List<HistoryGroup> groupHistoryByDay(List<HistoryEntry> items, DateTime now) {
  final groups = <String, List<HistoryEntry>>{};
  for (final e in items) {
    final label = e.watchedAt == null ? '更早' : historyDayLabel(e.watchedAt!, now);
    (groups[label] ??= []).add(e);
  }
  return [for (final g in groups.entries) (label: g.key, items: g.value)];
}

String _two(int n) => n.toString().padLeft(2, '0');

/// 历史一行的副标题:「P2 看到 1:05 · 14:32」/「已看完 · 昨天 20:10」;失效的视频直接说失效。
String historySubtitle(HistoryEntry e) {
  if (e.video.invalid) return '视频已失效';
  final part = e.partIdx > 0 ? 'P${e.partIdx + 1} ' : '';
  final String where;
  if (e.finished) {
    where = '已看完';
  } else if (e.positionMs < 1000) {
    where = '刚点开';
  } else {
    where = '看到 ${vDuration(e.positionMs)}';
  }
  final t = e.watchedAt;
  return t == null ? '$part$where' : '$part$where · ${_two(t.hour)}:${_two(t.minute)}';
}

/// 硬币流水的原因(服务端给了中文就用它;这四个是全部来源,S4:没有充值、提现、兑换)。
const coinReasonLabels = {
  'daily': '每日首次打开视频',
  'video_approved': '投稿过审',
  'coin_give': '投币',
  'coin_receive': '收到投币',
};

String coinReason(Map<String, dynamic> item) {
  final label = '${item['reason_label'] ?? ''}';
  if (label.isNotEmpty) return label;
  final r = '${item['reason'] ?? ''}';
  return coinReasonLabels[r] ?? r;
}

/// 金额带正负号:+2 / −1(减号用 U+2212,和账单页一个写法,不和连字符混)。
String coinDelta(int d) => d > 0 ? '+$d' : (d < 0 ? '−${-d}' : '0');
