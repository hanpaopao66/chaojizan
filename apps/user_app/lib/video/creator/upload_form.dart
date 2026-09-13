// 投稿表单:字段、客户端校验、「改了什么」的差量。纯 Dart,单测直接跑。
//
// 规则和服务端 server/app/services/video.py 的 clean_fields / _check_submittable 一一对应。
// 客户端先拦一遍只是为了少一个来回、把错误标在对应的输入框下面;
// 拦不住的(屏蔽词、店铺没在营业、封面不是自己的)服务端照样拦,它的 detail 原样展示。
import '../models.dart';
import 'creator_models.dart';

const kTitleMax = 80;
const kDescMax = 2000;
const kTagsMax = 10;
const kTagMax = 20;

/// 一个稿件最多 10 P;单 P ≤ 1GB、≤ 30 分钟(D8,时长由服务端探测)
const kPartsMax = 10;
const kPartMaxBytes = 1024 * 1024 * 1024;

/// 定时发布:5 分钟之后、30 天之内
const kScheduleMin = Duration(minutes: 5);
const kScheduleMax = Duration(days: 30);

/// 字数按码点数:服务端是 Python 的 `len()`。Dart 的 `length` 是 UTF-16 码元,一个 emoji 会被数成 2 个,
/// 客户端说「超了」而服务端收得下,反过来也一样。
int textLen(String s) => s.runes.length;

/// 标题里连续的空白(含换行)压成一个空格、去掉首尾 —— 和服务端 `" ".join(t.split())` 同一个口径,
/// 不然「看起来没改」的标题会被当成改动送去重审。
String normalizeTitle(String s) => s.trim().split(RegExp(r'\s+')).where((x) => x.isNotEmpty).join(' ');

final _urlRe = RegExp(r'^https?://\S{3,290}$');

String? checkTitle(String raw, {required bool submitting}) {
  final t = normalizeTitle(raw);
  if (t.isEmpty) return submitting ? '标题不能为空' : null;
  if (textLen(t) > kTitleMax) return '标题最多 $kTitleMax 字';
  return null;
}

String? checkDescription(String raw) => textLen(raw.trim()) > kDescMax ? '简介最多 $kDescMax 字' : null;

String? checkZone(String zone, {required bool submitting}) => submitting && zone.isEmpty ? '请选择分区' : null;

String? checkTags(List<String> tags) {
  if (tags.length > kTagsMax) return '标签最多 $kTagsMax 个';
  for (final t in tags) {
    if (textLen(t) > kTagMax) return '每个标签最多 $kTagMax 字';
  }
  return null;
}

/// 转载必须写来源,而且得是 http(s) 链接;自制不看这一栏。
String? checkSource(String copyright, String url, {required bool submitting}) {
  if (copyright != 'repost') return null;
  final u = url.trim();
  if (u.isEmpty) return submitting ? '转载要填写来源链接' : null;
  if (!_urlRe.hasMatch(u)) return '转载来源要填 http(s) 开头的链接';
  return null;
}

/// 挂了店铺就必须声明有没有合作(D16)——有合作的视频上要标「合作」,这一项不许默认。
String? checkCollab(int? shopId, bool? collab, {required bool submitting}) =>
    submitting && shopId != null && collab == null ? '挂了店铺就要选「与商家有无合作」' : null;

/// 定时发布要在 5 分钟之后、30 天之内(按 [now] 算;两头都不含糊:正好 5 分钟算合规)。
String? checkSchedule(DateTime? at, DateTime now) {
  if (at == null) return null;
  if (at.isBefore(now.add(kScheduleMin)) || at.isAfter(now.add(kScheduleMax))) {
    return '定时发布要设在 5 分钟之后、30 天之内';
  }
  return null;
}

/// 输入框里敲的一段字拆成标签:逗号、顿号、分号、空格都算分隔;开头的 # 去掉(服务端也会去)。
List<String> splitTagInput(String raw) {
  final out = <String>[];
  for (final p in raw.split(RegExp(r'[,，、;；\s]+'))) {
    final t = p.replaceFirst(RegExp(r'^[#＃]+'), '').trim();
    if (t.isNotEmpty) out.add(t);
  }
  return out;
}

/// 把新敲的标签并进已有的:重复的跳过;超长的、超数的不加,并说明原因(已经加进去的不回退)。
({List<String> tags, String? error}) addTags(List<String> current, String raw) {
  final out = [...current];
  String? error;
  for (final t in splitTagInput(raw)) {
    if (out.contains(t)) continue;
    if (textLen(t) > kTagMax) {
      error = '每个标签最多 $kTagMax 字';
      continue;
    }
    if (out.length >= kTagsMax) {
      error = '标签最多 $kTagsMax 个';
      break;
    }
    out.add(t);
  }
  return (tags: out, error: error);
}

/// 下一版里的一 P:id + 标题。
class PartDraft {
  const PartDraft(this.id, this.title);

  final int id;
  final String title;

  Map<String, Object?> toJson() => {'id': id, 'title': normalizeTitle(title)};

  @override
  bool operator ==(Object other) =>
      other is PartDraft && other.id == id && normalizeTitle(other.title) == normalizeTitle(title);

  @override
  int get hashCode => Object.hash(id, normalizeTitle(title));

  @override
  String toString() => 'P$id:$title';
}

/// 投稿表单的全部字段。
class UploadForm {
  UploadForm({
    this.title = '',
    this.description = '',
    this.zone = '',
    List<String>? tags,
    this.copyright = 'original',
    this.sourceUrl = '',
    this.visibility = 'public',
    this.allowDanmaku = true,
    this.allowComments = true,
    this.shopId,
    this.shopName = '',
    this.shopCollab,
    this.scheduledAt,
    this.coverMediaId,
    List<PartDraft>? parts,
  })  : tags = tags ?? [],
        parts = parts ?? [];

  String title;
  String description;
  String zone;
  List<String> tags;

  /// original 自制 / repost 转载
  String copyright;
  String sourceUrl;

  /// public 公开 / unlisted 不公开(拿链接能看)/ private 私密
  String visibility;
  bool allowDanmaku;
  bool allowComments;
  int? shopId;

  /// 只给界面显示用,不送服务端
  String shopName;
  bool? shopCollab;
  DateTime? scheduledAt;
  int? coverMediaId;
  List<PartDraft> parts;

  /// 从创作中心的稿件读出「现在的样子」:已发布的稿件有没审的改动时,**改动里的值优先** ——
  /// UP 主接着编辑的是他的改动,不是线上那一版。
  factory UploadForm.fromCreator(CreatorVideo v) {
    final f = v.pending?.fields ?? const <String, dynamic>{};
    bool has(String k) => f.containsKey(k);
    int? intOrNull(Object? x) => x == null ? null : vInt(x);
    final shopId = has('shop_id') ? intOrNull(f['shop_id']) : v.shopId;
    return UploadForm(
      title: has('title') ? '${f['title'] ?? ''}' : v.title,
      description: has('description') ? '${f['description'] ?? ''}' : v.description,
      zone: has('zone') ? '${f['zone'] ?? ''}' : v.card.zone,
      tags: has('tags') ? [for (final t in vList(f['tags'])) '$t'] : [...v.card.tags],
      copyright: has('copyright') ? (f['copyright'] == 'repost' ? 'repost' : 'original') : v.copyright,
      sourceUrl: has('source_url') ? '${f['source_url'] ?? ''}' : v.sourceUrl,
      visibility: v.visibility,
      allowDanmaku: v.allowDanmaku,
      allowComments: v.allowComments,
      shopId: shopId,
      // 改动里换了店铺的话,线上那家的名字就对不上了:留空,页面再按 id 查
      shopName: shopId != null && shopId == v.shopId ? '${v.shop?['name'] ?? ''}' : '',
      shopCollab: has('shop_collab') ? f['shop_collab'] as bool? : v.shopCollab,
      scheduledAt: v.scheduledAt,
      coverMediaId: has('cover_media_id') ? intOrNull(f['cover_media_id']) : v.coverMediaId,
      parts: effectiveParts(v),
    );
  }

  UploadForm copy() => UploadForm(
        title: title,
        description: description,
        zone: zone,
        tags: [...tags],
        copyright: copyright,
        sourceUrl: sourceUrl,
        visibility: visibility,
        allowDanmaku: allowDanmaku,
        allowComments: allowComments,
        shopId: shopId,
        shopName: shopName,
        shopCollab: shopCollab,
        scheduledAt: scheduledAt,
        coverMediaId: coverMediaId,
        parts: [...parts],
      );

  /// 送给服务端的字段(已经规范化)。
  ///
  /// [withSchedule] 为假时不带定时发布:**已发布**的稿件请求里只要出现 scheduled_at(哪怕是 null)
  /// 服务端就回 409「已经发布了,不能再设定时发布」。
  Map<String, Object?> fields({bool withSchedule = true}) => {
        'title': normalizeTitle(title),
        'description': description.trim(),
        'zone': zone.isEmpty ? null : zone,
        'tags': [...tags],
        'copyright': copyright,
        // 改回自制时把来源清掉,别让一条用不上的旧链接一直挂在稿件上
        'source_url': copyright == 'repost' ? sourceUrl.trim() : '',
        'visibility': visibility,
        'allow_danmaku': allowDanmaku,
        'allow_comments': allowComments,
        'shop_id': shopId,
        'shop_collab': shopId == null ? null : shopCollab,
        if (withSchedule) 'scheduled_at': scheduledAt?.toUtc().toIso8601String(),
        'cover_media_id': coverMediaId,
        'parts': [for (final p in parts) p.toJson()],
      };
}

/// 下一版的分 P(顺序 + 标题):改动里动过分 P 就用改动的清单;
/// 否则按 version_part_ids(没发布过 = 全部,已发布 = 线上那几 P)。
List<PartDraft> effectiveParts(CreatorVideo v) {
  final pp = v.pending?.parts;
  if (pp != null) return [for (final x in pp) PartDraft(vInt(x['id']), '${x['title'] ?? ''}')];
  final ids = v.versionPartIds.isNotEmpty ? v.versionPartIds : [for (final p in v.parts) p.id];
  return [
    for (final id in ids)
      if (v.partById(id) case final p?) PartDraft(id, p.title),
  ];
}

bool _same(Object? a, Object? b) {
  if (a is List && b is List) {
    if (a.length != b.length) return false;
    for (var i = 0; i < a.length; i++) {
      if (!_same(a[i], b[i])) return false;
    }
    return true;
  }
  if (a is Map && b is Map) {
    if (a.length != b.length) return false;
    for (final k in a.keys) {
      if (!b.containsKey(k) || !_same(a[k], b[k])) return false;
    }
    return true;
  }
  return a == b;
}

/// 改了什么:只送变了的字段(PATCH 语义)。
///
/// 只送差量不只是省流量:已发布的稿件把**没改的内容字段**原样送回去,服务端会当成「改回线上的值」
/// 处理还好,但把没改的 scheduled_at 送回去就是 409;而草稿送一堆没变的字段又会让屏蔽词再过一遍。
Map<String, Object?> formDiff(UploadForm base, UploadForm cur, {bool withSchedule = true}) {
  final a = base.fields(withSchedule: withSchedule);
  final b = cur.fields(withSchedule: withSchedule);
  final out = <String, Object?>{};
  for (final k in b.keys) {
    if (!_same(a[k], b[k])) out[k] = b[k];
  }
  // 换了店铺,合作声明跟着一起送:声明是对「这家店」说的,不能沿用上一家的
  if (out.containsKey('shop_id') && b['shop_id'] != null) out['shop_collab'] = b['shop_collab'];
  return out;
}

/// 定时发布的时间改没改(按时刻比,不按 DateTime 对象比 —— 一个是本地时间一个是 UTC 也算同一刻)。
bool scheduleChanged(UploadForm base, UploadForm cur) {
  final a = base.scheduledAt, b = cur.scheduledAt;
  if (a == null || b == null) return a != b;
  return !a.isAtSameMomentAs(b);
}

/// 表单的问题,按字段给(key:title / description / zone / tags / source / shop / schedule / parts)。
///
/// [submitting] 为假(存草稿)时只查格式和长度、不查必填 —— 草稿本来就可以没写完。
/// 定时发布只在**改了**的时候查:已经等着定时发布的稿件,离发布只剩 3 分钟时再存一次别的字段,
/// 不该因为「要设在 5 分钟之后」被拦下(那个时间根本不会再送)。
Map<String, String> validateForm(UploadForm f,
    {required DateTime now, required bool submitting, UploadForm? base, bool withSchedule = true}) {
  final e = <String, String>{};
  void put(String k, String? msg) {
    if (msg != null) e[k] = msg;
  }

  put('title', checkTitle(f.title, submitting: submitting));
  put('description', checkDescription(f.description));
  put('zone', checkZone(f.zone, submitting: submitting));
  put('tags', checkTags(f.tags));
  put('source', checkSource(f.copyright, f.sourceUrl, submitting: submitting));
  put('shop', checkCollab(f.shopId, f.shopCollab, submitting: submitting));
  if (withSchedule && (base == null || scheduleChanged(base, f))) put('schedule', checkSchedule(f.scheduledAt, now));
  if (submitting && f.parts.isEmpty) e['parts'] = '至少要有 1 P';
  if (f.parts.length > kPartsMax) e['parts'] = '一个视频最多 $kPartsMax P';
  return e;
}

/// 服务端的分 P 变了(新传的挂上了、别的设备删了一 P):本地排好的顺序和改过的标题留着,
/// 新来的接在后面,服务端已经没有的去掉。
List<PartDraft> mergeParts(List<PartDraft> local, List<PartDraft> server) {
  final serverIds = {for (final p in server) p.id};
  final out = [for (final p in local) if (serverIds.contains(p.id)) p];
  final have = {for (final p in out) p.id};
  for (final p in server) {
    if (!have.contains(p.id)) out.add(p);
  }
  return out;
}

/// 服务端的稿件变了(上传完挂上了新的一 P、另一台设备改了稿、刚存完草稿),把表单挪到新的基线上:
/// **我没动过的字段跟着服务端走,我动过的保留我的**(三方合并)。
///
/// 不这么做的话,只拿新基线去算差量,另一台设备刚改的标题会被这边一个没碰过的旧值盖回去。
UploadForm rebaseForm(UploadForm oldBase, UploadForm cur, UploadForm fresh) {
  T pick<T>(T o, T c, T n) => _same(c, o) ? n : c;
  final shopUntouched = cur.shopId == oldBase.shopId && cur.shopCollab == oldBase.shopCollab;
  final oldTitles = {for (final p in oldBase.parts) p.id: normalizeTitle(p.title)};
  final freshTitles = {for (final p in fresh.parts) p.id: p.title};
  final parts = [
    for (final p in mergeParts(cur.parts, fresh.parts))
      // 这一 P 的标题我没改过:用服务端的(可能是另一台设备改的)
      if (oldTitles[p.id] == normalizeTitle(p.title) && freshTitles.containsKey(p.id))
        PartDraft(p.id, freshTitles[p.id]!)
      else
        p,
  ];
  // 顺序:我没挪过就跟服务端的顺序
  final oldOrder = [for (final p in oldBase.parts) p.id];
  final curOrder = [for (final p in cur.parts) p.id];
  final orderedParts = _same(oldOrder, curOrder)
      ? [
          for (final p in fresh.parts)
            parts.firstWhere((x) => x.id == p.id, orElse: () => p),
        ]
      : parts;
  return UploadForm(
    title: pick(oldBase.title, cur.title, fresh.title),
    description: pick(oldBase.description, cur.description, fresh.description),
    zone: pick(oldBase.zone, cur.zone, fresh.zone),
    tags: _same(cur.tags, oldBase.tags) ? [...fresh.tags] : [...cur.tags],
    copyright: pick(oldBase.copyright, cur.copyright, fresh.copyright),
    sourceUrl: pick(oldBase.sourceUrl, cur.sourceUrl, fresh.sourceUrl),
    visibility: pick(oldBase.visibility, cur.visibility, fresh.visibility),
    allowDanmaku: pick(oldBase.allowDanmaku, cur.allowDanmaku, fresh.allowDanmaku),
    allowComments: pick(oldBase.allowComments, cur.allowComments, fresh.allowComments),
    shopId: shopUntouched ? fresh.shopId : cur.shopId,
    shopName: shopUntouched ? fresh.shopName : cur.shopName,
    shopCollab: shopUntouched ? fresh.shopCollab : cur.shopCollab,
    scheduledAt: scheduleChanged(oldBase, cur) ? cur.scheduledAt : fresh.scheduledAt,
    coverMediaId: pick(oldBase.coverMediaId, cur.coverMediaId, fresh.coverMediaId),
    parts: orderedParts,
  );
}

/// 文件名去掉扩展名,当第一 P 的默认标题 / 稿件的默认标题(B 站也是这么预填的)。
String titleFromFileName(String name) {
  final base = name.contains('.') ? name.substring(0, name.lastIndexOf('.')) : name;
  final t = normalizeTitle(base.replaceAll('_', ' '));
  final runes = t.runes.toList();
  return runes.length > kTitleMax ? String.fromCharCodes(runes.take(kTitleMax)) : t;
}
