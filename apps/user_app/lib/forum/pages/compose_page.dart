// 发帖 / 回复 / 引用 / 改正文(F1、F3、F4、§5.6)。
import 'dart:async';

import 'package:flutter/material.dart';
import 'package:image_picker/image_picker.dart';
import 'package:superz_shared/superz_shared.dart';

import '../../video/me/common.dart' show vConfirm;
import '../compose_form.dart';
import '../models.dart';
import '../nav.dart';
import '../widgets/common.dart';
import '../widgets/post_card.dart';
import '../widgets/post_tile.dart';

class ComposePage extends StatefulWidget {
  const ComposePage({super.key, this.card, this.quotePid, this.replyToPid, this.origin, this.edit});

  /// 预带的站内卡片 `{type, id}`(从歌 / 视频 / 帖子「分享到论坛」过来)
  final Map<String, dynamic>? card;
  final String? quotePid;
  final String? replyToPid;

  /// 回复 / 引用的那条原帖,摆在输入框上面让人看着写
  final FPost? origin;

  /// 改自己发过的那条
  final FPost? edit;

  @override
  State<ComposePage> createState() => _ComposePageState();
}

class _ComposePageState extends State<ComposePage> {
  late final ComposeDraft _draft = ComposeDraft(
    text: widget.edit?.text ?? '',
    card: widget.card,
    quotePid: widget.quotePid,
    replyToPid: widget.replyToPid,
    editing: widget.edit != null,
    images: [
      // 编辑时原帖的图照样摆着,但动不了(F3)
      for (final m in widget.edit?.media ?? const <FMedia>[]) ComposeImage(name: '', url: m.url),
    ],
  );
  late final TextEditingController _text = TextEditingController(text: _draft.text);
  final _focus = FocusNode();
  bool _sending = false;

  /// @ / # 联想的候选;空 = 不弹
  List<_Suggestion> _suggestions = const [];
  ({String kind, int start, String query})? _query;
  Timer? _debounce;

  @override
  void initState() {
    super.initState();
    _text.addListener(_onText);
  }

  @override
  void dispose() {
    _debounce?.cancel();
    _text.dispose();
    _focus.dispose();
    super.dispose();
  }

  // ---------------- 正文与联想 ----------------

  void _onText() {
    _draft.text = _text.text;
    final sel = _text.selection;
    final q = sel.isValid && sel.isCollapsed ? composeMentionQuery(_text.text, sel.baseOffset) : null;
    setState(() => _query = q);
    _debounce?.cancel();
    if (q == null || q.query.isEmpty) {
      _suggestions = const [];
      return;
    }
    // 联想每敲一下就查一次的话,搜索限流(每分钟 60 次)一会儿就满了
    _debounce = Timer(const Duration(milliseconds: 280), () => unawaited(_suggest(q)));
  }

  Future<void> _suggest(({String kind, int start, String query}) q) async {
    try {
      final list = <_Suggestion>[];
      if (q.kind == '@') {
        final r = await forumApi.searchUsers(q.query);
        for (final p in r.items.take(6)) {
          if ((p.username ?? '').isEmpty) continue;
          list.add(_Suggestion(kind: '@', value: p.username!, title: p.name, subtitle: '@${p.username}'));
        }
      } else {
        final r = await forumApi.searchTags(q.query);
        for (final t in r.items.take(6)) {
          list.add(_Suggestion(kind: '#', value: t.display, title: '#${t.display}', subtitle: '${t.authors24h} 人用过'));
        }
      }
      if (!mounted || _query?.start != q.start) return;
      setState(() => _suggestions = list);
    } catch (_) {
      // 联想查不到不打扰人,静默收起
      if (mounted) setState(() => _suggestions = const []);
    }
  }

  void _pick(_Suggestion s) {
    final q = _query;
    if (q == null) return;
    final r = composeApplySuggestion(_text.text, q.start, _text.selection.baseOffset, s.kind, s.value);
    _text.value = TextEditingValue(text: r.text, selection: TextSelection.collapsed(offset: r.cursor));
    setState(() => _suggestions = const []);
  }

  // ---------------- 图片 ----------------

  Future<void> _addImage() async {
    if (!_draft.canAddImage) {
      fToast(context, '最多 $kPostMaxImages 张图');
      return;
    }
    XFile? x;
    try {
      x = await ImagePicker().pickImage(source: ImageSource.gallery, maxWidth: 2048, imageQuality: 88);
    } catch (e) {
      if (mounted) fToast(context, '打不开相册');
      return;
    }
    if (x == null) return;
    final bytes = await x.readAsBytes();
    final item = ComposeImage(name: x.name);
    setState(() => _draft.images.add(item));
    try {
      // uploadImage 一次传完,没有分段进度 —— 进度条只画「在传 / 传完」两态,
      // 不编一个假的百分比(一张图几百 KB,编出来的数只会更让人困惑)
      setState(() => item.progress = 0.35);
      final url = await forumApi.uploadImage(bytes, x.name.isEmpty ? 'image.jpg' : x.name);
      if (!mounted) return;
      setState(() {
        item.url = url;
        item.progress = 1;
      });
    } on ApiException catch (e) {
      if (!mounted) return;
      setState(() => item.error = e.message);
      fToast(context, e.message);
    }
  }

  // ---------------- 投票 ----------------

  void _togglePoll() {
    setState(() => _draft.poll = _draft.poll == null ? ComposePoll() : null);
  }

  Future<void> _pickPollDuration() async {
    final poll = _draft.poll;
    if (poll == null) return;
    const choices = <String, int>{
      '5 分钟': 5,
      '1 小时': 60,
      '6 小时': 360,
      '1 天': 24 * 60,
      '3 天': 3 * 24 * 60,
      '7 天': kPollMaxMinutes,
    };
    final pick = await szShowSheet<int>(
      context: context,
      builder: (ctx) => SafeArea(
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          const ListTile(title: Text('投票多久结束', style: TextStyle(fontWeight: FontWeight.w600))),
          for (final e in choices.entries)
            ListTile(title: Text(e.key), onTap: () => Navigator.pop(ctx, e.value)),
        ]),
      ),
    );
    if (pick == null) return;
    setState(() => poll.minutes = pick);
  }

  // ---------------- 谁能回复 ----------------

  Future<void> _pickReplyPolicy() async {
    final pick = await szShowSheet<String>(
      context: context,
      builder: (ctx) => SafeArea(
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          const ListTile(title: Text('谁能回复', style: TextStyle(fontWeight: FontWeight.w600))),
          for (final e in fReplyPolicies.entries)
            ListTile(
              title: Text(e.value),
              trailing: _draft.replyPolicy == e.key ? const Icon(Icons.check) : null,
              onTap: () => Navigator.pop(ctx, e.key),
            ),
        ]),
      ),
    );
    if (pick == null) return;
    setState(() => _draft.replyPolicy = pick);
  }

  // ---------------- 发出去 ----------------

  Future<void> _send() async {
    final err = _draft.error;
    if (err != null) {
      fToast(context, err);
      return;
    }
    setState(() => _sending = true);
    try {
      final FPost made;
      if (widget.edit != null) {
        made = await forumApi.editPost(widget.edit!.pid, _draft.text.trim());
      } else {
        made = await forumApi.createPost(
          text: _draft.text.trim(),
          media: _draft.mediaUrls,
          card: _draft.card,
          quotePid: _draft.quotePid,
          replyToPid: _draft.replyToPid,
          pollOptions: _draft.poll?.filled,
          pollMinutes: _draft.poll?.minutes,
          replyPolicy: _draft.isReply ? null : _draft.replyPolicy,
        );
      }
      if (mounted) Navigator.of(context).pop(made);
    } on ApiException catch (e) {
      if (mounted) {
        setState(() => _sending = false);
        fToast(context, e.message);
      }
    }
  }

  Future<bool> _confirmLeave() async {
    if (!_draft.dirty || _sending) return true;
    return vConfirm(context, title: '不发了?', body: '写的内容不会留着。', ok: '不发了', danger: true);
  }

  /// 写了一半按返回:问一句再走。PopScope 的 canPop 是 false,所以要自己 pop。
  Future<void> _onPop(bool didPop) async {
    if (didPop) return;
    if (await _confirmLeave() && mounted) Navigator.of(context).pop();
  }

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    final left = _draft.remaining;
    final title = widget.edit != null
        ? '改一下'
        : (_draft.isReply ? '回复' : (_draft.isQuote ? '引用' : '发帖'));
    return PopScope(
      canPop: false,
      onPopInvokedWithResult: (didPop, _) => _onPop(didPop),
      child: SzPageScaffold(
        appBar: AppBar(
          title: Text(title),
          actions: [
            Padding(
              padding: const EdgeInsets.only(right: 8),
              child: Center(
                child: FilledButton(
                  onPressed: _sending || !_draft.canSend ? null : _send,
                  child: Text(widget.edit != null ? '保存' : (_draft.isReply ? '回复' : '发布')),
                ),
              ),
            ),
          ],
        ),
        body: Column(children: [
          Expanded(
            child: ListView(padding: const EdgeInsets.all(kPagePad), children: [
              if (widget.origin != null) ...[
                Text(_draft.isReply ? '回复这条' : '引用这条',
                    style: TextStyle(fontSize: kFontNote, color: sz.inkMuted)),
                const SizedBox(height: 6),
                _OriginBox(post: widget.origin!),
                const SizedBox(height: 12),
              ],
              if (widget.edit != null)
                Padding(
                  padding: const EdgeInsets.only(bottom: 10),
                  child: Text(
                    '发出后 $kEditWindowMinutes 分钟内能改,最多 $kEditMaxCount 次;'
                    '旧的正文会留在编辑历史里,图片和投票改不了。',
                    style: TextStyle(fontSize: kFontNote, color: sz.inkMuted, height: 1.5),
                  ),
                ),
              TextField(
                controller: _text,
                focusNode: _focus,
                autofocus: true,
                maxLines: null,
                minLines: 4,
                // maxLength 不设:超了要让人看见「−3」再自己删,直接截掉会吃字
                keyboardType: TextInputType.multiline,
                style: const TextStyle(fontSize: kFontTitle, height: 1.6),
                decoration: InputDecoration(
                  border: InputBorder.none,
                  hintText: _draft.isReply ? '说点什么…' : '有什么新鲜事?',
                ),
              ),
              if (_suggestions.isNotEmpty) _suggestBox(sz),
              if (_draft.images.isNotEmpty) ...[
                const SizedBox(height: 10),
                _imageRow(sz),
              ],
              if (_draft.card != null) ...[
                const SizedBox(height: 10),
                _cardBox(sz),
              ],
              if (_draft.poll != null) ...[
                const SizedBox(height: 12),
                _pollBox(sz),
              ],
              const SizedBox(height: 80),
            ]),
          ),
          Divider(height: 1, color: sz.line),
          SafeArea(
            top: false,
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
              child: Row(children: [
                IconButton(
                  tooltip: '图片(最多 $kPostMaxImages 张)',
                  onPressed: _draft.canAddImage ? _addImage : null,
                  icon: const Icon(Icons.image_outlined),
                ),
                IconButton(
                  tooltip: '投票',
                  onPressed: widget.edit != null ? null : _togglePoll,
                  icon: Icon(Icons.poll_outlined, color: _draft.poll != null ? sz.clay : null),
                ),
                if (widget.edit == null && !_draft.isReply)
                  TextButton.icon(
                    onPressed: _pickReplyPolicy,
                    icon: const Icon(Icons.people_outline, size: 16),
                    label: Text(_draft.replyPolicy == 'all' ? '所有人能回复' : '${_draft.replyPolicyName}能回复',
                        style: const TextStyle(fontSize: kFontNote)),
                  ),
                const Spacer(),
                Text('$left',
                    style: szTabular(
                        fontSize: kFontNote,
                        color: left < 0 ? sz.danger : (left <= 20 ? sz.hold : sz.inkMuted))),
                const SizedBox(width: 12),
              ]),
            ),
          ),
        ]),
      ),
    );
  }

  Widget _suggestBox(SzColors sz) => Container(
        margin: const EdgeInsets.only(top: 6),
        decoration: BoxDecoration(
          border: Border.all(color: sz.line),
          borderRadius: BorderRadius.circular(kRadiusMd),
        ),
        child: Column(children: [
          for (final s in _suggestions)
            ListTile(
              dense: true,
              title: Text(s.title, maxLines: 1, overflow: TextOverflow.ellipsis),
              subtitle: Text(s.subtitle, style: TextStyle(fontSize: kFontMicro, color: sz.inkMuted)),
              onTap: () => _pick(s),
            ),
        ]),
      );

  Widget _imageRow(SzColors sz) => Wrap(
        spacing: 8,
        runSpacing: 8,
        children: [
          for (var i = 0; i < _draft.images.length; i++)
            Stack(children: [
              ClipRRect(
                borderRadius: BorderRadius.circular(kRadiusSm),
                child: SizedBox(
                  width: 92,
                  height: 92,
                  child: _draft.images[i].done
                      ? Image(image: szNetImage(forumResolve(_draft.images[i].url)), fit: BoxFit.cover,
                          errorBuilder: (_, __, ___) => Container(color: sz.surfaceAlt))
                      : Container(
                          color: sz.surfaceAlt,
                          child: Center(
                            child: _draft.images[i].failed
                                ? Icon(Icons.error_outline, color: sz.danger)
                                : const SizedBox(
                                    width: 22, height: 22, child: CircularProgressIndicator(strokeWidth: 2)),
                          ),
                        ),
                ),
              ),
              if (widget.edit == null)
                Positioned(
                  right: 0,
                  top: 0,
                  child: GestureDetector(
                    onTap: () => setState(() => _draft.images.removeAt(i)),
                    child: Container(
                      margin: const EdgeInsets.all(2),
                      padding: const EdgeInsets.all(2),
                      decoration: const BoxDecoration(color: Colors.black54, shape: BoxShape.circle),
                      child: const Icon(Icons.close, size: 14, color: Colors.white),
                    ),
                  ),
                ),
            ]),
        ],
      );

  Widget _cardBox(SzColors sz) => Stack(children: [
        // 预带的卡片这时候还没有快照(标题封面服务端发的时候才查),先摆一个占位条
        Container(
          padding: const EdgeInsets.all(12),
          decoration: BoxDecoration(
            border: Border.all(color: sz.line),
            borderRadius: BorderRadius.circular(kRadiusMd),
          ),
          child: Row(children: [
            Icon(Icons.link, size: 16, color: sz.inkMuted),
            const SizedBox(width: 8),
            Expanded(
              child: Text('带一张${FCard.fromJson(_draft.card).typeName}卡片',
                  style: TextStyle(fontSize: kFontBody, color: sz.ink)),
            ),
            IconButton(
              tooltip: '去掉',
              onPressed: () => setState(() => _draft.card = null),
              icon: const Icon(Icons.close, size: 16),
            ),
          ]),
        ),
      ]);

  Widget _pollBox(SzColors sz) {
    final poll = _draft.poll!;
    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        border: Border.all(color: sz.line),
        borderRadius: BorderRadius.circular(kRadiusMd),
      ),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        for (var i = 0; i < poll.options.length; i++)
          Padding(
            padding: const EdgeInsets.only(bottom: 8),
            child: Row(children: [
              Expanded(
                child: TextFormField(
                  initialValue: poll.options[i],
                  maxLength: kPollOptionMaxChars,
                  onChanged: (v) => setState(() => poll.options[i] = v),
                  decoration: InputDecoration(
                    isDense: true,
                    counterText: '',
                    border: const OutlineInputBorder(),
                    hintText: '第 ${i + 1} 项',
                  ),
                ),
              ),
              if (poll.canRemove)
                IconButton(
                  tooltip: '去掉这一项',
                  onPressed: () => setState(() => poll.options.removeAt(i)),
                  icon: const Icon(Icons.remove_circle_outline, size: 18),
                ),
            ]),
          ),
        Row(children: [
          if (poll.canAdd)
            TextButton.icon(
              onPressed: () => setState(() => poll.options.add('')),
              icon: const Icon(Icons.add, size: 16),
              label: const Text('加一项'),
            ),
          const Spacer(),
          TextButton(onPressed: _pickPollDuration, child: Text(_durationLabel(poll.minutes))),
          IconButton(
            tooltip: '不投票了',
            onPressed: _togglePoll,
            icon: const Icon(Icons.close, size: 16),
          ),
        ]),
        if (poll.error != null)
          Text(poll.error!, style: TextStyle(fontSize: kFontNote, color: sz.danger)),
      ]),
    );
  }

  static String _durationLabel(int minutes) {
    if (minutes >= 24 * 60) return '${minutes ~/ (24 * 60)} 天';
    if (minutes >= 60) return '${minutes ~/ 60} 小时';
    return '$minutes 分钟';
  }
}

extension on ComposeDraft {
  String get replyPolicyName => fReplyPolicies[replyPolicy] ?? '所有人';
}

class _Suggestion {
  const _Suggestion({required this.kind, required this.value, required this.title, required this.subtitle});

  final String kind;
  final String value;
  final String title;
  final String subtitle;
}

/// 回复 / 引用时摆在上面的那条原帖:只看,不给操作栏
class _OriginBox extends StatelessWidget {
  const _OriginBox({required this.post});

  final FPost post;

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    return Container(
      decoration: BoxDecoration(
        color: sz.surfaceAlt,
        borderRadius: BorderRadius.circular(kRadiusMd),
      ),
      child: post.card != null && post.text.isEmpty
          ? Padding(padding: const EdgeInsets.all(10), child: PostCardView(post.card!))
          : PostTile(post: post, showActions: false),
    );
  }
}
