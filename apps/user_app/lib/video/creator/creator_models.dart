// 创作中心的数据对象和状态标签(VIDEO-API 8.2 / 8.3)。纯 Dart,单测直接喂 JSON。
import '../models.dart';

DateTime? _time(Object? v) => v == null ? null : DateTime.tryParse('$v')?.toLocal();
String _str(Object? v) => v == null ? '' : '$v';

/// 已发布稿件没审完的改动(`pending`)。线上那一版在它审过之前一个字不动(§5.8)。
class PendingChange {
  const PendingChange({
    required this.state,
    this.stateLabel = '',
    this.fields = const {},
    this.parts,
    this.submittedAt,
    this.rejectCode = '',
    this.rejectLabel = '',
    this.rejectNote = '',
    this.failReason = '',
    this.coverPreview = '',
  });

  /// editing 改动未提交 / processing 改动转码中 / reviewing 改动审核中 / rejected 改动未通过 / failed 改动转码失败
  final String state;
  final String stateLabel;

  /// 只列改了的内容字段(值是改动后的)
  final Map<String, dynamic> fields;

  /// 下一版的分 P 清单 `[{id, title}]`;没动分 P 时为 null
  final List<Map<String, dynamic>>? parts;
  final DateTime? submittedAt;
  final String rejectCode;
  final String rejectLabel;
  final String rejectNote;
  final String failReason;

  /// 改动里换了封面时,新封面的预览(带签名的私密地址)
  final String coverPreview;

  /// 审核 / 转码中的改动不能再动内容(服务端 409)
  bool get busy => state == 'processing' || state == 'reviewing';

  static PendingChange? fromJson(Object? j) {
    if (j is! Map) return null;
    final m = j.cast<String, dynamic>();
    return PendingChange(
      state: _str(m['state']),
      stateLabel: _str(m['state_label']),
      fields: vMap(m['fields']),
      parts: m['parts'] is List ? [for (final p in vList(m['parts'])) vMap(p)] : null,
      submittedAt: _time(m['submitted_at']),
      rejectCode: _str(m['reject_code']),
      rejectLabel: _str(m['reject_label']),
      rejectNote: _str(m['reject_note']),
      failReason: _str(m['fail_reason']),
      coverPreview: _str(m['cover_preview']),
    );
  }
}

/// 一条审核 / 下架 / 申诉记录。
class Decision {
  const Decision({
    required this.id,
    required this.action,
    this.actionLabel = '',
    this.reasonCode = '',
    this.reasonLabel = '',
    this.note = '',
    this.appealOf,
    this.createdAt,
    this.canAppeal = false,
    this.appealState,
  });

  final int id;

  /// approve / reject / approve_changes / reject_changes / remove / appeal / appeal_upheld / appeal_overturned
  final String action;
  final String actionLabel;
  final String reasonCode;
  final String reasonLabel;
  final String note;
  final int? appealOf;
  final DateTime? createdAt;
  final bool canAppeal;

  /// 申诉那一条:open 处理中 / resolved 已处理
  final String? appealState;

  factory Decision.fromJson(Object? j) {
    final m = vMap(j);
    return Decision(
      id: vInt(m['id']),
      action: _str(m['action']),
      actionLabel: _str(m['action_label']),
      reasonCode: _str(m['reason_code']),
      reasonLabel: _str(m['reason_label']),
      note: _str(m['note']),
      appealOf: m['appeal_of'] == null ? null : vInt(m['appeal_of']),
      createdAt: _time(m['created_at']),
      canAppeal: m['can_appeal'] == true,
      appealState: m['appeal_state'] as String?,
    );
  }

  bool get negative => const {'reject', 'reject_changes', 'remove', 'appeal_upheld'}.contains(action);
}

/// 创作中心里的一个稿件(`GET /creator/videos/{vid}` 的完整对象;列表接口给的是它的子集,缺的字段取缺省)。
class CreatorVideo {
  CreatorVideo._(this.raw, this.card);

  factory CreatorVideo.fromJson(Object? j) {
    final m = vMap(j);
    return CreatorVideo._(m, VideoCard.fromJson(m));
  }

  final Map<String, dynamic> raw;
  final VideoCard card;

  String get vid => card.vid;
  String get title => card.title;
  String get status => raw['status'] is String ? raw['status'] as String : 'draft';
  String get statusLabel => _str(raw['status_label']);
  String get visibility => raw['visibility'] is String ? raw['visibility'] as String : 'public';
  String get rejectCode => _str(raw['reject_code']);
  String get rejectLabel => _str(raw['reject_label']);
  String get rejectNote => _str(raw['reject_note']);
  String get failReason => _str(raw['fail_reason']);
  DateTime? get scheduledAt => _time(raw['scheduled_at']);
  DateTime? get submittedAt => _time(raw['submitted_at']);
  DateTime? get createdAt => _time(raw['created_at']);
  late final PendingChange? pending = PendingChange.fromJson(raw['pending']);

  String get description => _str(raw['description']);
  String get copyright => raw['copyright'] == 'repost' ? 'repost' : 'original';
  String get sourceUrl => _str(raw['source_url']);
  bool get allowDanmaku => raw['allow_danmaku'] != false;
  bool get allowComments => raw['allow_comments'] != false;

  /// 挂的店铺 `{id, name, logo}`(D16)
  Map<String, dynamic>? get shop => raw['shop'] is Map ? vMap(raw['shop']) : null;
  int? get shopId => raw['shop_id'] == null ? null : vInt(raw['shop_id']);
  bool? get shopCollab => raw['shop_collab'] as bool?;
  int? get coverMediaId => raw['cover_media_id'] == null ? null : vInt(raw['cover_media_id']);

  /// 过审后是公开地址,没过审时是带签名的私密地址(只有 UP 主和审核员看得到)
  String get coverPreview => _str(raw['cover_preview']);
  String get link => _str(raw['link']);
  late final List<VideoPart> parts = [for (final p in vList(raw['parts'])) VideoPart.fromJson(p)];
  late final List<int> versionPartIds = [for (final x in vList(raw['version_part_ids'])) vInt(x)];
  late final List<Decision> decisions = [for (final d in vList(raw['decisions'])) Decision.fromJson(d)];

  VideoPart? partById(int id) {
    for (final p in parts) {
      if (p.id == id) return p;
    }
    return null;
  }

  /// 线上有一版(已发布 / 等定时发布):再改内容进待审,线上不变
  bool get isLive => status == 'published' || status == 'scheduled';

  /// 转码 / 审核中(稿件本身或改动)不能改内容;已下架什么都不能改
  bool get contentLocked =>
      status == 'processing' || status == 'reviewing' || status == 'removed' || (pending?.busy ?? false);

  /// 现在能申诉的那条结论;不能申诉时是 null。
  ///
  /// 和服务端 appeal() 同一个判据:只看**最近一次**「驳回 / 改动被驳回 / 下架」,它没被申诉过,
  /// 而且稿件还停在那个结论上 —— 驳回之后改过、重新提交了,就直接走审核,不用申诉(服务端回 409)。
  /// 只看每条的 can_appeal 不够:那一项只管「这条申诉过没有」,不管稿件后来改没改。
  Decision? get appealTarget {
    Decision? last;
    for (final d in decisions) {
      if (const {'reject', 'reject_changes', 'remove'}.contains(d.action)) last = d;
    }
    if (last == null || !last.canAppeal) return null;
    final still = switch (last.action) {
      'reject' => status == 'rejected',
      'reject_changes' => pending?.state == 'rejected',
      'remove' => status == 'removed',
      _ => false,
    };
    return still ? last : null;
  }

  bool get canAppeal => appealTarget != null;

  /// 能不能「去看看」:线上有一版才有东西可看
  bool get watchable => isLive;

  /// 列表和详情页标题:草稿还没起名字时别显示一片空白
  String get displayTitle => title.trim().isEmpty ? '未命名稿件' : title;
}

/// 标签的语气:中性(草稿)/ 进行中(转码、审核、定时)/ 好(已通过)/ 要处理(未通过、下架、失败)。
enum CreatorTone { neutral, busy, good, bad }

/// 创作中心的一个状态标签。[detail] 是标签后面跟的原因(「未通过(原因)」的那个原因)。
class CreatorTag {
  const CreatorTag(this.label, this.tone, {this.detail = ''});

  final String label;
  final CreatorTone tone;
  final String detail;

  @override
  String toString() => detail.isEmpty ? label : '$label($detail)';
}

/// 原因的一句话:「标题 / 封面与内容不符:标题和内容对不上」;没有中文名时退回代码。
String reasonText(String label, String note, [String code = '']) {
  final head = label.isNotEmpty ? label : code;
  if (head.isEmpty) return note;
  if (note.isEmpty || note == head) return head;
  return '$head:$note';
}

/// 稿件的状态标签(8.2 的状态 + 已发布稿件的改动状态)。第一个是稿件本身,改动有的话跟在后面。
///
/// 列表里要一眼分清「等别人」和「等我」:转码、审核、定时是等平台(busy),
/// 未通过、下架、转码失败是要我去处理的(bad,带原因)。
List<CreatorTag> creatorTags(CreatorVideo v) {
  final tags = <CreatorTag>[];
  switch (v.status) {
    case 'draft':
      tags.add(const CreatorTag('草稿', CreatorTone.neutral));
    case 'processing':
      tags.add(const CreatorTag('转码中', CreatorTone.busy));
    case 'reviewing':
      tags.add(const CreatorTag('审核中', CreatorTone.busy));
    case 'scheduled':
      final at = v.scheduledAt;
      tags.add(CreatorTag('定时发布', CreatorTone.busy,
          detail: at == null ? '' : '${at.month}月${at.day}日 ${_two(at.hour)}:${_two(at.minute)} 公开'));
    case 'published':
      tags.add(const CreatorTag('已通过', CreatorTone.good));
    case 'rejected':
      tags.add(CreatorTag('未通过', CreatorTone.bad, detail: reasonText(v.rejectLabel, v.rejectNote, v.rejectCode)));
    case 'failed':
      tags.add(CreatorTag('转码失败', CreatorTone.bad, detail: v.failReason));
    case 'removed':
      tags.add(CreatorTag('已下架', CreatorTone.bad, detail: reasonText(v.rejectLabel, v.rejectNote, v.rejectCode)));
    default:
      tags.add(CreatorTag(v.statusLabel.isNotEmpty ? v.statusLabel : v.status, CreatorTone.neutral));
  }
  final p = v.pending;
  if (p != null) {
    switch (p.state) {
      case 'editing':
        tags.add(const CreatorTag('改动未提交', CreatorTone.neutral));
      case 'processing':
        tags.add(const CreatorTag('改动转码中', CreatorTone.busy));
      case 'reviewing':
        tags.add(const CreatorTag('改动审核中', CreatorTone.busy));
      case 'rejected':
        tags.add(CreatorTag('改动未通过', CreatorTone.bad, detail: reasonText(p.rejectLabel, p.rejectNote, p.rejectCode)));
      case 'failed':
        tags.add(CreatorTag('改动转码失败', CreatorTone.bad, detail: p.failReason));
      default:
        if (p.stateLabel.isNotEmpty) tags.add(CreatorTag(p.stateLabel, CreatorTone.neutral));
    }
  }
  return tags;
}

String _two(int n) => n.toString().padLeft(2, '0');

/// 创作中心的页签(和服务端 CREATOR_FILTERS 一一对应)。
const creatorTabs = <(String key, String label)>[
  ('all', '全部'),
  ('processing', '进行中'),
  ('reviewing', '审核中'),
  ('published', '已通过'),
  ('rejected', '未通过'),
  ('removed', '已下架'),
];

/// 这个状态的稿件该不该出现在这个页签里(实时事件来了,决定是改那一行、挪走还是插进来)。
bool inCreatorTab(String tab, String status) => switch (tab) {
      'all' => status != 'deleted',
      'processing' => const {'draft', 'processing', 'failed'}.contains(status),
      'reviewing' => status == 'reviewing',
      'published' => status == 'published' || status == 'scheduled',
      'rejected' => status == 'rejected',
      'removed' => status == 'removed',
      _ => false,
    };

/// 页签上的数字:总览接口按状态给了各有几个,按页签的口径加起来。
int creatorTabCount(String tab, Map<String, dynamic> byStatus) {
  var n = 0;
  for (final e in byStatus.entries) {
    if (inCreatorTab(tab, e.key)) n += vInt(e.value);
  }
  return n;
}

/// 七项数据的 key 和中文名(创作中心的总览、单稿数据共用)。
const statMetrics = <(String key, String label)>[
  ('views', '播放'),
  ('likes', '点赞'),
  ('coins', '硬币'),
  ('favorites', '收藏'),
  ('comments', '评论'),
  ('danmaku', '弹幕'),
  ('shares', '分享'),
];

/// 改动里动了哪些内容(给「改动未提交 / 审核中」那张卡片列一句「改了:标题、标签」)。
const pendingFieldLabels = {
  'title': '标题',
  'description': '简介',
  'zone': '分区',
  'tags': '标签',
  'copyright': '自制 / 转载',
  'source_url': '转载来源',
  'shop_id': '挂的店铺',
  'shop_collab': '合作声明',
  'cover_media_id': '封面',
};

String pendingSummary(PendingChange p) {
  final names = [
    for (final k in p.fields.keys) pendingFieldLabels[k] ?? k,
    if (p.parts != null) '分 P',
  ];
  return names.isEmpty ? '' : '改了:${names.join('、')}';
}
