/// 消息模块的文字格式:时间、文件大小、时长、预览。纯函数,单测锁住。
library;

import '../models.dart';

const _weekdays = ['周一', '周二', '周三', '周四', '周五', '周六', '周日'];

String two(int n) => n.toString().padLeft(2, '0');

String hm(DateTime t) => '${two(t.hour)}:${two(t.minute)}';

bool sameDay(DateTime a, DateTime b) =>
    a.year == b.year && a.month == b.month && a.day == b.day;

/// 会话列表右上角的时间:今天写几点,昨天写「昨天」,一周内写周几,今年写月/日,更早写年/月/日。
String listTime(DateTime t, [DateTime? now]) {
  final n = now ?? DateTime.now();
  if (sameDay(t, n)) return hm(t);
  final y = n.subtract(const Duration(days: 1));
  if (sameDay(t, y)) return '昨天';
  final days = DateTime(n.year, n.month, n.day).difference(DateTime(t.year, t.month, t.day)).inDays;
  if (days < 7 && days > 0) return _weekdays[t.weekday - 1];
  if (t.year == n.year) return '${t.month}/${t.day}';
  return '${t.year}/${t.month}/${t.day}';
}

/// 聊天页里按天分隔的那一行。
String dayLabel(DateTime t, [DateTime? now]) {
  final n = now ?? DateTime.now();
  if (sameDay(t, n)) return '今天';
  if (sameDay(t, n.subtract(const Duration(days: 1)))) return '昨天';
  if (t.year == n.year) return '${t.month}月${t.day}日 ${_weekdays[t.weekday - 1]}';
  return '${t.year}年${t.month}月${t.day}日';
}

String fileSize(int bytes) {
  if (bytes < 1024) return '$bytes B';
  if (bytes < 1024 * 1024) return '${(bytes / 1024).toStringAsFixed(bytes < 10 * 1024 ? 1 : 0)} KB';
  if (bytes < 1024 * 1024 * 1024) {
    return '${(bytes / 1024 / 1024).toStringAsFixed(bytes < 10 * 1024 * 1024 ? 1 : 0)} MB';
  }
  return '${(bytes / 1024 / 1024 / 1024).toStringAsFixed(1)} GB';
}

/// 语音、视频的时长:1:05、12:30、1:02:03
String duration(int ms) {
  final s = (ms / 1000).round();
  final h = s ~/ 3600, m = (s % 3600) ~/ 60, sec = s % 60;
  return h > 0 ? '$h:${two(m)}:${two(sec)}' : '$m:${two(sec)}';
}

const kindLabels = {
  'photo': '图片',
  'video': '视频',
  'file': '文件',
  'voice': '语音',
  'video_note': '视频消息',
  'sticker': '贴纸',
  'gif': 'GIF',
  'location': '位置',
  'contact': '名片',
  'poll': '投票',
  'dice': '骰子',
  'call': '通话',
  'card': '分享',
};

/// 分享卡片按分享的是什么给一个词(DEV-PROMPTS-41 §5.9)
const cardKindLabels = {
  'track': '歌曲',
  'release': '专辑',
  'playlist': '歌单',
  'artist': '音乐人',
  'post': '动态',
  'video': '视频',
};

/// 服务消息的一句话(「小王 邀请 小李 加入了群」)。[actor] 是做这件事的人(是我就传「你」),
/// [meId] 用来把被操作的人里的「我」写成「你」(「小王 邀请 你 加入了群」)。
///
/// 频道([channel])不说是谁做的:订阅者看到的是「频道」,不是某个管理员(和 Telegram 一样)。
String serviceText(ChatMessage m, {required String actor, int? meId, bool channel = false}) {
  final s = m.service ?? const {};
  final a = s['action'];
  final ids = [for (final x in (s['user_ids'] as List? ?? const [])) (x as num?)?.toInt()];
  List<String> names() {
    final ns = [for (final x in (s['names'] as List? ?? const [])) '$x'];
    return [for (var i = 0; i < ns.length; i++) (meId != null && i < ids.length && ids[i] == meId) ? '你' : ns[i]];
  }

  final targetIsMe = meId != null && (s['user_id'] as num?)?.toInt() == meId;
  if (channel) {
    switch (a) {
      case 'chat_create':
        return '频道「${s['title'] ?? ''}」创建了';
      case 'title_change':
        return '频道改名为「${s['title'] ?? ''}」';
      case 'photo_change':
        return '频道换了头像';
      case 'pin':
        final p = '${s['preview'] ?? ''}';
        return p.isEmpty ? '置顶了一条消息' : '置顶了「$p」';
    }
  }
  final self = actor == '你' ? '你' : '${s['name'] ?? actor}';
  switch (a) {
    case 'chat_create':
      return '$actor 创建了「${s['title'] ?? ''}」';
    case 'members_add':
      return '$actor 邀请 ${names().join('、')} 加入了群';
    case 'member_join':
      return '$self 加入了群';
    case 'member_leave':
      return '$self 退出了群';
    case 'member_kick':
      return '$actor 把 ${targetIsMe ? '你' : (s['name'] ?? '一位成员')} 移出了群';
    case 'title_change':
      return '$actor 把群名改成了「${s['title'] ?? ''}」';
    case 'photo_change':
      return '$actor 换了群头像';
    case 'pin':
      final p = '${s['preview'] ?? ''}';
      return p.isEmpty ? '$actor 置顶了一条消息' : '$actor 置顶了「$p」';
    case 'call':
      return '通话';
    default:
      return '$actor 更新了会话';
  }
}

/// 剧透那几段换成「▒」:会话列表、回复引用、置顶条这些地方不能直接露出来(点开才看)。
String maskSpoilers(String text, List<MsgEntity> entities) {
  final spans = [for (final e in entities) if (e.type == 'spoiler') (e.offset, e.offset + e.length)];
  if (spans.isEmpty || text.isEmpty) return text;
  final b = StringBuffer();
  for (var i = 0; i < text.length; i++) {
    final c = text.codeUnitAt(i);
    final hidden = spans.any((s) => i >= s.$1 && i < s.$2);
    if (!hidden || c == 0x20 || c == 0x0A) {
      b.writeCharCode(c);
    } else if (c >= 0xDC00 && c <= 0xDFFF) {
      // 代理对的后半:前半已经写过一个 ▒ 了
    } else {
      b.write('▒');
    }
  }
  return b.toString();
}

/// 一条消息的一行预览(会话列表、回复引用、置顶条、通知)。
String previewOf(ChatMessage m) {
  final text = maskSpoilers(m.text, m.entities);
  if (m.kind == 'text') return text.replaceAll('\n', ' ');
  if (m.kind == 'poll') return '📊 ${m.poll?.question ?? '投票'}';
  if (m.kind == 'dice') return '${m.dice?['emoji'] ?? '🎲'}';
  if (m.kind == 'sticker') return '${m.sticker?['emoji'] ?? ''}[贴纸]';
  if (m.kind == 'location') return '[位置] ${m.location?['title'] ?? ''}'.trim();
  if (m.kind == 'contact') return '[名片] ${m.contact?['name'] ?? ''}'.trim();
  if (m.kind == 'call') return callLabel(m.call);
  if (m.kind == 'card') {
    final c = m.card ?? const {};
    final what = cardKindLabels['${c['type'] ?? ''}'] ?? '分享';
    final title = '${c['title'] ?? ''}'.replaceAll('\n', ' ');
    return title.isEmpty ? '[$what]' : '[$what] $title';
  }
  final label = kindLabels[m.kind] ?? '';
  final cap = text.replaceAll('\n', ' ');
  if (m.kind == 'file' && m.media.isNotEmpty && cap.isEmpty) return '[文件] ${m.media.first.name}';
  if (m.kind == 'voice' && m.media.isNotEmpty) {
    return '[语音] ${duration(m.media.first.durationMs)}';
  }
  return cap.isEmpty ? '[$label]' : '[$label] $cap';
}

/// 通话记录的一句话。[mine] 给了就按方向说(我打出去的 / 打给我的),不给就是中性的(列表预览)。
String callLabel(Map<String, dynamic>? c, {bool? mine}) {
  if (c == null) return '[通话]';
  final video = c['video'] == true;
  final kind = video ? '视频通话' : '语音通话';
  final st = c['state'] ?? c['result'];
  final secs = (c['duration'] as num?)?.toInt() ?? 0;
  if (mine != null) {
    return switch (st) {
      'ended' => '${mine ? '呼出' : '呼入'}的$kind ${duration(secs * 1000)}',
      'missed' => mine ? '$kind · 对方未接听' : '未接$kind',
      'declined' => mine ? '$kind · 对方已拒绝' : '$kind · 已拒绝',
      'busy' => mine ? '$kind · 对方忙线' : '未接$kind',
      'canceled' || 'cancelled' => mine ? '$kind · 已取消' : '未接$kind',
      _ => kind,
    };
  }
  return switch (st) {
    'ended' => '[$kind] ${duration(secs * 1000)}',
    'missed' => '[$kind] 未接',
    'declined' => '[$kind] 已拒绝',
    'busy' => '[$kind] 对方忙线',
    'canceled' || 'cancelled' => '[$kind] 已取消',
    _ => '[$kind]',
  };
}

/// 未读数角标上的字:超过 999 写 999+
String badgeText(int n) => n > 999 ? '999+' : '$n';

/// 只有 1–3 个 emoji、没有别的字 → 按大表情显示(和 Telegram 一样)。
bool isBigEmoji(String text) {
  final t = text.trim();
  if (t.isEmpty || t.runes.length > 12) return false;
  var count = 0;
  for (final r in t.runes) {
    if (r == 0x200D || r == 0xFE0F || (r >= 0x1F3FB && r <= 0x1F3FF)) continue; // 连接符、变体、肤色
    if (r == 0x20) continue;
    final emoji = (r >= 0x1F000 && r <= 0x1FAFF) ||
        (r >= 0x2600 && r <= 0x27BF) ||
        (r >= 0x2300 && r <= 0x23FF) ||
        (r >= 0x2B00 && r <= 0x2BFF) ||
        r == 0x00A9 ||
        r == 0x00AE ||
        r == 0x203C ||
        r == 0x2049 ||
        (r >= 0x1F1E6 && r <= 0x1F1FF);
    if (!emoji) return false;
    count++;
  }
  return count > 0 && count <= 6; // 国旗是两个区域字母,肤色组合按上面跳过
}
