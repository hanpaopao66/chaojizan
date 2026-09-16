// 音乐人中心在本机先过一遍的规矩(§4 M2、§5.3)。
//
// 服务端照样全量校验 —— 这里这一份只是为了**当场说清楚哪儿不行**:
// 把 8 首歌传完、封面选好,点了提交才被退回来说「第 3 首还在转码」,
// 是最让人恼火的一种失败。
import '../models.dart';

/// 艺名的保留词。冒充平台和官方身份不靠审核主页拦(没有实名也审不出真假,M2),
/// 但这几个词本身不许用 —— 它们指的是平台自己。
const kReservedArtistNames = [
  '超级赞',
  'superz',
  '官方',
  '客服',
  '管理员',
  'admin',
  'official',
  'staff',
];

/// 艺名合不合规。不合规返回那句话,合规返回 null。
///
/// 唯一性由服务端判(客户端不可能知道别人叫什么),这里只管长度和保留词。
String? validateArtistName(String raw) {
  final name = raw.trim();
  if (name.isEmpty) return '起个艺名吧';
  // 按字符数算,不按字节 —— 两个汉字就是 2 个字
  final n = name.runes.length;
  if (n < 2) return '艺名至少 2 个字';
  if (n > 30) return '艺名最多 30 个字';
  final lower = name.toLowerCase();
  for (final w in kReservedArtistNames) {
    if (lower.contains(w.toLowerCase())) return '艺名里不能有「$w」';
  }
  return null;
}

/// 简介长度。
String? validateArtistBio(String raw) => raw.trim().runes.length > 300 ? '简介最多 300 个字' : null;

/// 作品信息够不够建草稿。
String? validateReleaseInfo({required String title, required String genre, required String language}) {
  if (title.trim().isEmpty) return '给作品起个名字';
  if (title.trim().runes.length > 60) return '作品名最多 60 个字';
  if (genre.trim().isEmpty) return '选一个曲风';
  if (language.trim().isEmpty) return '选一个语种';
  return null;
}

/// 歌名。
String? validateTrackTitle(String raw) {
  final t = raw.trim();
  if (t.isEmpty) return '给这首歌起个名字';
  if (t.runes.length > 60) return '歌名最多 60 个字';
  return null;
}

/// 提交审核前在本机先查一遍(§5.3 提交的前提)。
///
/// 全部不合格的地方一次说完,而不是修一条报一条 —— 一次说完才知道还差多少。
List<String> releaseSubmitProblems(MRelease release) {
  final problems = <String>[];
  if (release.tracks.isEmpty) problems.add('至少要有 1 首歌');
  if (release.cover.isEmpty) problems.add('还没有封面');
  final pending = [
    for (final t in release.tracks)
      if (!t.transcodeReady) t.title,
  ];
  if (pending.isNotEmpty) {
    final failed = [
      for (final t in release.tracks)
        if (t.transcodeStatus == 'failed') t.title,
    ];
    if (failed.isNotEmpty) {
      problems.add('这几首转码失败了,删了重传:${failed.join('、')}');
    }
    final busy = pending.where((t) => !failed.contains(t)).toList();
    if (busy.isNotEmpty) problems.add('这几首还在转码,等一下:${busy.join('、')}');
  }
  final undeclared = [
    for (final t in release.tracks)
      if (t.declaration != 'original' && t.declaration != 'authorized') t.title,
  ];
  if (undeclared.isNotEmpty) {
    problems.add('这几首还没勾原创 / 已获授权:${undeclared.join('、')}');
  }
  return problems;
}

/// 这个状态下能不能改信息、增删歌曲(§5.3:只有草稿 / 未通过 / 已下架能改)。
bool releaseEditable(MRelease r) => r.editable;

/// 这个状态下该给哪个动作按钮。
///
/// | 状态 | 能做的 |
/// |---|---|
/// | 草稿 / 未通过 / 已下架 | 提交审核 |
/// | 审核中 | 撤回提交 |
/// | 已发布 | 下架 |
/// | 被下架 | 没有(只能申诉) |
String releaseActionLabel(String status) => switch (status) {
      'reviewing' => '撤回提交',
      'published' => '下架',
      'removed' => '',
      _ => '提交审核',
    };
