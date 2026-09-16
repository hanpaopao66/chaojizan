// 发帖页的校验和草稿(F1、§5.6)。**纯逻辑,不碰 Flutter** —— 口径和服务端一致,
// 两边不一样时这里先红。
//
// 校验放在客户端只是为了「发出去之前就告诉你哪儿不行」,不是权威:
// 违禁词、@ 查不查得到人、图片是不是自己传的,一律服务端说了算。

import 'entities.dart';
import 'models.dart';

/// 一张待发的图:选好了还在传的时候有进度,传完了有地址。
class ComposeImage {
  ComposeImage({required this.name, this.url = '', this.progress = 0, this.error = ''});

  final String name;

  /// 传完拿到的相对地址(`/img/forum/u42-….jpg`);还在传时是空串
  String url;

  /// 0–1
  double progress;
  String error;

  bool get done => url.isNotEmpty;
  bool get failed => error.isNotEmpty;
}

/// 投票草稿。
class ComposePoll {
  ComposePoll({List<String>? options, this.minutes = 24 * 60})
      : options = options ?? ['', ''];

  final List<String> options;

  /// 时长(分钟):5 分钟–7 天
  int minutes;

  /// 去掉空项之后的选项;发出去的是这一份
  List<String> get filled => [for (final o in options) if (o.trim().isNotEmpty) o.trim()];

  bool get canAdd => options.length < kPollMaxOptions;
  bool get canRemove => options.length > kPollMinOptions;

  /// 校验:2–4 项、每项 1–25 字、不能重复、时长 5 分钟–7 天。
  /// 返回 null 表示能发。
  String? get error {
    final os = filled;
    if (os.length < kPollMinOptions) return '投票至少要 $kPollMinOptions 项';
    if (os.length > kPollMaxOptions) return '投票最多 $kPollMaxOptions 项';
    for (final o in os) {
      if (o.runes.length > kPollOptionMaxChars) return '每一项最多 $kPollOptionMaxChars 字';
    }
    if (os.toSet().length != os.length) return '有两项写得一样';
    if (minutes < kPollMinMinutes) return '投票最短 $kPollMinMinutes 分钟';
    if (minutes > kPollMaxMinutes) return '投票最长 7 天';
    return null;
  }
}

/// 发帖页手里的那份草稿。
class ComposeDraft {
  ComposeDraft({
    this.text = '',
    List<ComposeImage>? images,
    this.card,
    this.poll,
    this.replyPolicy = 'all',
    this.quotePid,
    this.replyToPid,
    this.editing = false,
  }) : images = images ?? [];

  String text;
  final List<ComposeImage> images;

  /// `{type, id}`:从歌 / 视频 / 帖子分享过来时预带(I3,只报这两个字段)
  Map<String, dynamic>? card;
  ComposePoll? poll;
  String replyPolicy;
  final String? quotePid;
  final String? replyToPid;

  /// 改自己发过的那条(F3:只能改正文,图和投票不能改)
  final bool editing;

  bool get isReply => replyToPid != null;
  bool get isQuote => quotePid != null;

  /// 还能加图吗(≤4;编辑时不能动图)
  bool get canAddImage => !editing && images.length < kPostMaxImages;

  /// 有图 / 卡片 / 投票时正文可以为空(§5.6)
  bool get hasAttachment => images.isNotEmpty || card != null || poll != null;

  int get length => forumTextLength(text);

  /// 还剩几个字能写(负数 = 超了)
  int get remaining => kPostMaxChars - length;

  /// 图还在传,或者传失败了
  bool get uploading => images.any((i) => !i.done && !i.failed);

  /// 能不能点「发布」。返回 null 表示能,否则是不能发的那句话。
  String? get error {
    if (editing) {
      // 改正文:图和投票都在,但只按正文判 —— 原帖有图时正文可以为空
      final e = forumTextError(text, hasMedia: images.isNotEmpty, hasCard: card != null, hasPoll: poll != null);
      return e;
    }
    if (images.length > kPostMaxImages) return '最多 $kPostMaxImages 张图';
    if (uploading) return '图片还在上传';
    final bad = images.where((i) => i.failed);
    if (bad.isNotEmpty) return '有图片没传上去,删掉再发';
    final pollError = poll?.error;
    if (pollError != null) return pollError;
    return forumTextError(text,
        hasMedia: images.isNotEmpty, hasCard: card != null, hasPoll: poll != null);
  }

  bool get canSend => error == null;

  /// 传完的图片地址(发出去的就是这一份)
  List<String> get mediaUrls => [for (final i in images) if (i.done) i.url];

  /// 有没有动过(退出时要不要问一句「不发了?」)
  bool get dirty => text.trim().isNotEmpty || images.isNotEmpty || poll != null || card != null;
}

/// 输入框里正在打的 @ 或 # —— 用来决定要不要弹联想。
///
/// 判据是「光标前面最近的那个 @ 或 #,到光标之间没有空白」。
/// 返回的 [start] 是那个 @ / # 的位置,[query] 是它后面已经打了的字。
({String kind, int start, String query})? composeMentionQuery(String text, int cursor) {
  if (cursor < 0 || cursor > text.length) return null;
  final head = text.substring(0, cursor);
  for (var i = head.length - 1; i >= 0; i--) {
    final ch = head[i];
    if (ch == '@' || ch == '#') {
      // @ / # 前面必须是开头或者空白,不然 `a@b` 这种邮箱地址也会弹联想
      if (i > 0 && !' \t\n'.contains(head[i - 1])) return null;
      final q = head.substring(i + 1);
      if (q.length > 30) return null;
      return (kind: ch, start: i, query: q);
    }
    if (' \t\n'.contains(ch)) return null;
  }
  return null;
}

/// 把联想选中的那一条填回输入框:替换掉 `@已打的字` 这一段。
/// 返回新的正文和新的光标位置。
({String text, int cursor}) composeApplySuggestion(
    String text, int start, int cursor, String kind, String value) {
  final insert = '$kind$value ';
  final next = text.replaceRange(start, cursor, insert);
  return (text: next, cursor: start + insert.length);
}
