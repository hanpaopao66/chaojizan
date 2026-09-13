// 互动消息的数据对象和显示用的纯函数(标题、头像合并、系统通知的动作)。单测锁住。
import '../models.dart';

/// 四个页签(VIDEO-API 9):回复我的 / @我的 / 收到的赞 / 系统通知
const notifyKinds = <(String kind, String label)>[
  ('reply', '回复我的'),
  ('at', '@我的'),
  ('like', '收到的赞'),
  ('system', '系统通知'),
];

/// 互动消息的一条。
class NotifyItem {
  const NotifyItem({
    required this.id,
    required this.kind,
    this.title = '',
    this.text = '',
    this.actor,
    this.actors = const [],
    this.count = 1,
    this.video,
    this.comment,
    this.data = const {},
    this.read = false,
    this.createdAt,
    this.updatedAt,
  });

  factory NotifyItem.fromJson(Object? j) {
    final m = vMap(j);
    return NotifyItem(
      id: vInt(m['id']),
      kind: '${m['kind'] ?? ''}',
      title: '${m['title'] ?? ''}',
      text: '${m['text'] ?? ''}',
      actor: m['actor'] is Map ? VPerson.fromJson(m['actor']) : null,
      actors: [for (final a in vList(m['actors'])) VPerson.fromJson(a)],
      count: vInt(m['count']) > 0 ? vInt(m['count']) : 1,
      video: m['video'] is Map ? vMap(m['video']) : null,
      comment: m['comment'] is Map ? vMap(m['comment']) : null,
      data: vMap(m['data']),
      read: m['read'] == true,
      createdAt: DateTime.tryParse('${m['created_at'] ?? ''}')?.toLocal(),
      updatedAt: DateTime.tryParse('${m['updated_at'] ?? ''}')?.toLocal(),
    );
  }

  final int id;

  /// reply / at / like / system
  final String kind;

  /// 服务端拼好的一句话
  final String title;

  /// 评论内容片段(评论删了是「该评论已删除」);系统通知是正文
  final String text;

  /// 最近那个人 / 最近几个人(赞合并时最多 3 个);系统通知是 null / []
  final VPerson? actor;
  final List<VPerson> actors;

  /// 赞的合并数(这个对象当前的赞数);其他类是 1
  final int count;

  /// 相关视频 `{vid, title, cover}`,删了是 null
  final Map<String, dynamic>? video;

  /// 跳转用 `{id, root_id, deleted}`
  final Map<String, dynamic>? comment;
  final Map<String, dynamic> data;
  final bool read;
  final DateTime? createdAt;

  /// 赞合并之后「最近一次」的时间(新的赞来了会刷新)
  final DateTime? updatedAt;

  String get vid => '${video?['vid'] ?? ''}';

  /// 点开要定位的评论:评论还在才给(删了的定位不到,直接打开视频)
  int? get commentId {
    final c = comment;
    if (c == null || c['deleted'] == true || c['id'] == null) return null;
    return vInt(c['id']);
  }
}

/// 这一条的标题。服务端拼好了就原样显示(VIDEO-API 9「直接显示」);
/// 没给时按服务端同一套口径自己拼,保证不会出现一行空白。
String notifyHeadline(NotifyItem n) {
  if (n.title.isNotEmpty) return n.title;
  final name = n.actor != null && n.actor!.name.isNotEmpty
      ? n.actor!.name
      : (n.actors.isNotEmpty && n.actors.first.name.isNotEmpty ? n.actors.first.name : '有人');
  final target = n.data['target'] == 'video' ? '视频' : '评论';
  switch (n.kind) {
    case 'like':
      return n.count > 1 ? '$name等 ${n.count} 人赞了你的$target' : '$name 赞了你的$target';
    case 'at':
      return '$name 在评论里 @ 了你';
    case 'reply':
      return n.data['target'] == 'video' ? '$name 评论了你的视频' : '$name 回复了你的评论';
    case 'system':
      final t = '${n.data['title'] ?? ''}';
      return t.isNotEmpty ? t : '系统通知';
  }
  return name;
}

/// 头像怎么排:最近那个人在最前,其余按 actors 的顺序、按 id 去重,最多 [max] 个。
/// [more] 是没画出来的人数 —— 赞合并时「等 12 人」里剩下的那 9 个,给头像后面的「+9」用;
/// 其他类只有一个人,more 恒为 0。
({List<VPerson> shown, int more}) notifyAvatars(NotifyItem n, {int max = 3}) {
  final seen = <int>{};
  final shown = <VPerson>[];
  for (final p in [if (n.actor != null) n.actor!, ...n.actors]) {
    if (shown.length >= max) break;
    if (seen.add(p.id)) shown.add(p);
  }
  final total = n.kind == 'like' && n.count > shown.length ? n.count : shown.length;
  return (shown: shown, more: total - shown.length);
}

/// 系统通知的动作 → 一个短标签(审核结果、处罚、申诉结果)。认不出来的给空串,不显示标签。
String systemActionLabel(String action) => switch (action) {
      'approve' => '审核通过',
      'reject' => '未通过',
      'approve_changes' => '改动已通过',
      'reject_changes' => '改动未通过',
      'remove' => '已下架',
      'appeal_overturned' => '申诉成立',
      'appeal_upheld' => '申诉未成立',
      'published' => '已发布',
      'failed' => '转码失败',
      _ => '',
    };

/// 这个动作对 UP 主来说是不是坏消息(标签用错误色、带原因)
bool systemActionBad(String action) =>
    const {'reject', 'reject_changes', 'remove', 'appeal_upheld', 'failed'}.contains(action);

/// 角标上的数:超过 99 写 99+
String unreadBadge(int n) => n > 99 ? '99+' : '$n';

/// 「视频互动」会话的未读数:只数「提醒设置」里勾上的那几类([kinds])。
/// [unread] 是服务端的 `{reply, at, like, system, total}`,这里不用 total —— total 把四类都加上了。
int notifyBadgeCount(Map<String, int> unread, Set<String> kinds) {
  var n = 0;
  for (final (k, _) in notifyKinds) {
    if (kinds.contains(k)) n += unread[k] ?? 0;
  }
  return n;
}

/// 一条互动在时间线上的时刻:赞合并后新来的赞会把它刷到最新(服务端也按 updated_at 排)。
DateTime notifyTime(NotifyItem n) => n.updatedAt ?? n.createdAt ?? DateTime.fromMillisecondsSinceEpoch(0);

int _newerFirst(NotifyItem a, NotifyItem b) {
  final c = notifyTime(b).compareTo(notifyTime(a));
  return c != 0 ? c : b.id.compareTo(a.id);
}

/// 把四类互动合成一条时间线(设计稿 C:一条互动 = 一条消息,没有页签)。
///
/// 服务端只能按类拉(`kind` 必填),每类各自按时间倒序、各有各的游标。合的时候有个坑:
/// 某一类拉到的最旧那条之后,别的类里可能还有更旧、但还没拉到的 —— 直接把手里的四串排一排,
/// 翻到下一页时会有条目「插」回已经显示过的位置。所以只显示到**水位**为止:
/// 还有下一页的那几类里,「已拉到的最旧那条」最新的那个时刻;再往下等拉了下一页才确定。
class NotifyMerge {
  final Map<String, List<NotifyItem>> _items = {};
  final Map<String, String?> _cursor = {};
  final Map<String, bool> _more = {};

  bool get loaded => _more.length == notifyKinds.length;

  /// 放进某一类的一页,和手里已有的合并;同一个 id 出现两次(新的赞把那条刷到了最前)时留新拉到的那份。
  ///
  /// [older] 是往上翻拉到的下一页:游标跟着往后走。否则是第一页(打开时、来了新提醒时重拉):
  /// 这一类以前没拉过才记它的游标 —— 已经往上翻过几页的话,游标还停在翻到的地方,不退回去。
  void put(String kind, List<NotifyItem> items, {String? next, bool older = false}) {
    final known = _more.containsKey(kind);
    final list = [...?_items[kind]];
    final ids = {for (final n in items) n.id};
    list.removeWhere((n) => ids.contains(n.id));
    list.addAll(items);
    list.sort(_newerFirst);
    _items[kind] = list;
    if (older || !known) {
      _cursor[kind] = next;
      _more[kind] = next != null;
    }
  }

  DateTime? get _watermark {
    DateTime? w;
    for (final (k, _) in notifyKinds) {
      if (_more[k] != true) continue;
      final list = _items[k] ?? const <NotifyItem>[];
      if (list.isEmpty) continue;
      final t = notifyTime(list.last);
      if (w == null || t.isAfter(w)) w = t;
    }
    return w;
  }

  /// 现在能确定顺序的那些,从新到旧。
  List<NotifyItem> visible() {
    final all = [for (final l in _items.values) ...l]..sort(_newerFirst);
    final w = _watermark;
    if (w == null) return all;
    return [for (final n in all) if (!notifyTime(n).isBefore(w)) n];
  }

  /// 往上翻该拉哪一类(水位就卡在它身上);null = 全拉完了。
  String? nextKind() {
    String? pick;
    DateTime? best;
    for (final (k, _) in notifyKinds) {
      if (_more[k] != true) continue;
      final list = _items[k] ?? const <NotifyItem>[];
      final t = list.isEmpty ? null : notifyTime(list.last);
      if (pick == null || (t != null && (best == null || t.isAfter(best)))) {
        pick = k;
        best = t;
      }
    }
    return pick;
  }

  String? cursorOf(String kind) => _cursor[kind];

  bool get hasMore => nextKind() != null;
}
