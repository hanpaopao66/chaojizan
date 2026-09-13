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
