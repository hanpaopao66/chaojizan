// 作品编辑页(§8.2 /studio/releases/*、§5.3 状态机)。
//
// 一页管到底:作品信息、封面、加歌(选音频 → 分片上传带进度 → 建歌)、
// 歌词和署名、不适宜未成年人开关、原创 / 已获授权声明、转码状态、排序,
// 以及提交审核 / 撤回 / 下架 / 申诉。
//
// 提交前**在本机先查一遍**(§5.3 的四个前提):把 8 首歌传完、封面选好,
// 点了提交才被退回来说「第 3 首还在转码」,是最让人恼火的一种失败。
import 'dart:async';

import 'package:file_selector/file_selector.dart';
import 'package:flutter/material.dart';
import 'package:image_picker/image_picker.dart' show ImagePicker, ImageSource;
import 'package:superz_shared/superz_shared.dart';

import '../../video/me/common.dart';
import '../../video/models.dart';
import '../models.dart';
import '../nav.dart';
import '../widgets/common.dart';
import 'studio_rules.dart';
import 'upload_tasks.dart';

/// [rid] 为空 = 建新作品(填完信息就建草稿,然后原地变成编辑)。
class MusicReleaseEditPage extends StatefulWidget {
  const MusicReleaseEditPage({super.key, this.rid});

  final String? rid;

  @override
  State<MusicReleaseEditPage> createState() => _MusicReleaseEditPageState();
}

class _MusicReleaseEditPageState extends State<MusicReleaseEditPage> {
  String? _rid;
  MRelease? _release;
  Object? _error;
  bool _busy;
  Timer? _poll;

  /// 建新作品时的表单
  final _title = TextEditingController();
  String _kind = 'single';
  String _genre = '';
  String _language = '';
  final _description = TextEditingController();
  List<MGenre> _genres = [];

  /// 建过至少一次(返回上一页时告诉列表要刷新)
  bool _dirty = false;

  _MusicReleaseEditPageState() : _busy = false;

  static const _kinds = [
    (key: 'single', name: '单曲'),
    (key: 'ep', name: 'EP'),
    (key: 'album', name: '专辑'),
  ];
  static const _languages = ['国语', '粤语', '英语', '日语', '韩语', '纯音乐', '其他'];

  @override
  void initState() {
    super.initState();
    _rid = widget.rid;
    musicApi.genres().then((g) {
      if (mounted) setState(() => _genres = g);
    }).catchError((Object _) {});
    if (_rid != null) _load();
  }

  @override
  void dispose() {
    _poll?.cancel();
    _title.dispose();
    _description.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    final rid = _rid;
    if (rid == null) return;
    try {
      final r = await musicApi.studioRelease(rid);
      if (!mounted) return;
      setState(() {
        _release = r;
        _error = null;
      });
      _schedulePoll(r);
    } catch (e) {
      if (mounted) setState(() => _error = e);
    }
  }

  /// 还有歌在转码就过几秒再拉一次 —— 转码是服务端排队做的,没有推送(§5.3)
  void _schedulePoll(MRelease r) {
    _poll?.cancel();
    if (!r.tracks.any((t) => t.transcodeStatus == 'pending' || t.transcodeStatus == 'processing')) return;
    _poll = Timer(const Duration(seconds: 5), _load);
  }

  @override
  Widget build(BuildContext context) {
    final r = _release;
    return PopScope(
      canPop: true,
      onPopInvokedWithResult: (didPop, _) {},
      child: SzPageScaffold(
        contentMaxWidth: kFeedMaxWidth,
        appBar: AppBar(
          title: Text(_rid == null ? '新建作品' : '作品'),
          leading: IconButton(
            icon: const Icon(Icons.arrow_back),
            onPressed: () => Navigator.pop(context, _dirty),
          ),
          actions: [
            if (r != null && r.editable)
              IconButton(
                icon: const Icon(Icons.more_horiz),
                tooltip: '更多',
                onPressed: () => _menu(r),
              ),
          ],
        ),
        body: _rid == null
            ? _newForm(context)
            : (r == null
                ? (_error != null
                    ? SzRefreshableEmpty(onRefresh: _load, child: musicErrorView(_error, _load))
                    : const Center(child: CircularProgressIndicator()))
                : RefreshIndicator(onRefresh: _load, child: _editor(context, r))),
      ),
    );
  }

  // ---------------- 建草稿 ----------------

  Widget _newForm(BuildContext context) {
    final sz = Theme.of(context).sz;
    return ListView(
      padding: const EdgeInsets.all(kPagePad),
      children: [
        TextField(
          controller: _title,
          maxLength: 60,
          decoration: const InputDecoration(labelText: '作品名', border: OutlineInputBorder()),
        ),
        const SizedBox(height: 10),
        Text('类型', style: TextStyle(fontSize: kFontBodyLg, color: sz.ink)),
        const SizedBox(height: 6),
        Wrap(spacing: 8, children: [
          for (final k in _kinds)
            SzChip(k.name, selected: _kind == k.key, onTap: () => setState(() => _kind = k.key)),
        ]),
        const SizedBox(height: 14),
        Text('曲风', style: TextStyle(fontSize: kFontBodyLg, color: sz.ink)),
        const SizedBox(height: 6),
        Wrap(spacing: 8, runSpacing: 8, children: [
          for (final g in _genres)
            SzChip(g.name, selected: _genre == g.key, onTap: () => setState(() => _genre = g.key)),
        ]),
        const SizedBox(height: 14),
        Text('语种', style: TextStyle(fontSize: kFontBodyLg, color: sz.ink)),
        const SizedBox(height: 6),
        Wrap(spacing: 8, runSpacing: 8, children: [
          for (final l in _languages)
            SzChip(l, selected: _language == l, onTap: () => setState(() => _language = l)),
        ]),
        const SizedBox(height: 14),
        TextField(
          controller: _description,
          maxLength: 500,
          minLines: 3,
          maxLines: 6,
          decoration: const InputDecoration(labelText: '作品简介(可以不填)', border: OutlineInputBorder()),
        ),
        const SizedBox(height: 18),
        SizedBox(
          width: double.infinity,
          child: FilledButton(
            onPressed: _busy ? null : _create,
            child: _busy
                ? const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2))
                : const Text('建草稿,下一步加歌'),
          ),
        ),
      ],
    );
  }

  Future<void> _create() async {
    final problem = validateReleaseInfo(title: _title.text, genre: _genre, language: _language);
    if (problem != null) {
      mToast(context, problem);
      return;
    }
    setState(() => _busy = true);
    try {
      final r = await musicApi.createRelease(
        title: _title.text.trim(),
        kind: _kind,
        genre: _genre,
        language: _language,
        description: _description.text.trim(),
      );
      if (!mounted) return;
      setState(() {
        _rid = r.rid;
        _release = r;
        _dirty = true;
      });
    } catch (e) {
      if (mounted) mToast(context, e);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  // ---------------- 编辑 ----------------

  Widget _editor(BuildContext context, MRelease r) {
    final sz = Theme.of(context).sz;
    final problems = releaseSubmitProblems(r);
    return ListView(
      padding: const EdgeInsets.only(bottom: 24),
      children: [
        Padding(
          padding: const EdgeInsets.all(kPagePad),
          child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
            InkWell(
              onTap: r.editable ? _pickCover : null,
              child: Stack(alignment: Alignment.bottomRight, children: [
                MCover(url: r.cover, name: r.title, size: 88, radius: kRadiusMd),
                if (r.editable)
                  CircleAvatar(radius: 12, backgroundColor: sz.clay, child: Icon(Icons.edit, size: 13, color: sz.paper)),
              ]),
            ),
            const SizedBox(width: 12),
            Expanded(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Row(children: [
                  Flexible(
                    child: Text(r.title,
                        maxLines: 2,
                        overflow: TextOverflow.ellipsis,
                        style: TextStyle(fontSize: kFontTitle, color: sz.ink, fontWeight: FontWeight.w600)),
                  ),
                  const SizedBox(width: 6),
                  VTag(mReleaseStatusName(r.status),
                      color: r.status == 'rejected' || r.status == 'removed' ? sz.danger : null),
                ]),
                Text(
                    [mReleaseKindName(r.kind), if (r.genre.isNotEmpty) r.genre, if (r.language.isNotEmpty) r.language]
                        .join(' · '),
                    style: TextStyle(fontSize: kFontNote, color: sz.inkMuted)),
                if (r.editable)
                  TextButton(
                    onPressed: () => _editInfo(r),
                    style: TextButton.styleFrom(padding: EdgeInsets.zero, minimumSize: const Size(0, 28)),
                    child: const Text('改信息', style: TextStyle(fontSize: kFontNote)),
                  ),
              ]),
            ),
          ]),
        ),
        if (r.rejectCode.isNotEmpty || r.rejectNote.isNotEmpty)
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: kPagePad),
            child: _RejectBox(release: r, onAppeal: () => _appeal(r)),
          ),
        MSection('歌曲(${r.tracks.length})', onMore: r.editable ? _addTrack : null, moreLabel: '加歌'),
        _Uploads(rid: r.rid, onDone: _load),
        if (r.tracks.isEmpty)
          Padding(
            padding: const EdgeInsets.fromLTRB(kPagePad, 4, kPagePad, 8),
            child: Text('还没有歌。支持 mp3 / m4a / aac / flac / wav / ogg,单首 200MB 以内、5 秒到 20 分钟。',
                style: TextStyle(fontSize: kFontNote, color: sz.inkMuted, height: 1.6)),
          ),
        if (r.editable && r.tracks.length > 1)
          ReorderableListView.builder(
            shrinkWrap: true,
            physics: const NeverScrollableScrollPhysics(),
            buildDefaultDragHandles: false,
            itemCount: r.tracks.length,
            onReorderItem: (from, to) => _reorder(r, from, to),
            itemBuilder: (context, i) => _TrackRow(
              key: ValueKey(r.tracks[i].tid),
              track: r.tracks[i],
              index: i,
              editable: true,
              onEdit: () => _editTrack(r, r.tracks[i]),
              onDelete: () => _deleteTrack(r, r.tracks[i]),
            ),
          )
        else
          for (var i = 0; i < r.tracks.length; i++)
            _TrackRow(
              track: r.tracks[i],
              index: i,
              editable: r.editable,
              onEdit: () => _editTrack(r, r.tracks[i]),
              onDelete: () => _deleteTrack(r, r.tracks[i]),
            ),
        const SizedBox(height: 10),
        if (problems.isNotEmpty && r.editable)
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: kPagePad),
            child: Container(
              width: double.infinity,
              padding: const EdgeInsets.all(kCardPad),
              decoration: BoxDecoration(
                color: sz.surfaceAlt,
                borderRadius: BorderRadius.circular(kRadiusMd),
                border: Border.all(color: sz.line),
              ),
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text('提交前还差这些', style: TextStyle(fontSize: kFontBodyLg, color: sz.ink, fontWeight: FontWeight.w600)),
                const SizedBox(height: 4),
                for (final p in problems)
                  Padding(
                    padding: const EdgeInsets.symmetric(vertical: 2),
                    child: Text('· $p', style: TextStyle(fontSize: kFontNote, color: sz.inkMuted, height: 1.5)),
                  ),
              ]),
            ),
          ),
        const SizedBox(height: 12),
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: kPagePad),
          child: _actionButton(context, r, problems),
        ),
      ],
    );
  }

  Widget _actionButton(BuildContext context, MRelease r, List<String> problems) {
    final label = releaseActionLabel(r.status);
    if (label.isEmpty) {
      return r.canAppeal
          ? SizedBox(width: double.infinity, child: OutlinedButton(onPressed: () => _appeal(r), child: const Text('申诉')))
          : const SizedBox.shrink();
    }
    final submitting = r.editable;
    return SizedBox(
      width: double.infinity,
      child: FilledButton(
        // 缺东西时按钮不禁用:禁用了就只剩一个灰按钮,还得自己猜为什么。
        // 点下去把差的那几条摆出来,比灰着不动有用
        onPressed: _busy ? null : () => _action(r, problems),
        child: Text(submitting && problems.isNotEmpty ? '$label(还差 ${problems.length} 项)' : label),
      ),
    );
  }

  Future<void> _action(MRelease r, List<String> problems) async {
    if (r.editable) {
      if (problems.isNotEmpty) {
        mToast(context, problems.first);
        return;
      }
      if (!await vConfirm(context,
          title: '提交审核?',
          body: '过审之后歌就不能改了 —— 要改得先下架重交。审核结果会用互动消息告诉你。',
          ok: '提交')) {
        return;
      }
      await _call(() => musicApi.submitRelease(r.rid));
      return;
    }
    if (r.status == 'reviewing') {
      if (!await vConfirm(context, title: '撤回提交?', body: '撤回之后回到草稿,可以接着改')) return;
      await _call(() => musicApi.cancelSubmit(r.rid));
      return;
    }
    if (r.status == 'published') {
      if (!await vConfirm(context,
          title: '下架「${r.title}」?',
          body: '下架之后别人听不到了,你可以改完再交一次',
          ok: '下架',
          danger: true)) {
        return;
      }
      await _call(() => musicApi.withdrawRelease(r.rid));
    }
  }

  Future<void> _call(Future<Object?> Function() f) async {
    setState(() => _busy = true);
    try {
      await f();
      _dirty = true;
      await _load();
    } catch (e) {
      if (mounted) mToast(context, e);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _appeal(MRelease r) async {
    final text = await vPrompt(context,
        title: '申诉',
        hint: '说明你的理由。每个决定只能申诉一次,会换一位管理员复核',
        maxLength: 500,
        maxLines: 5,
        validate: (t) => t.trim().length < 10 ? '把理由说清楚一点(至少 10 个字)' : null);
    if (text == null || !mounted) return;
    await _call(() => musicApi.appeal(r.rid, text.trim()));
    if (mounted) mToast(context, '申诉已提交,会换一位管理员复核');
  }

  Future<void> _editInfo(MRelease r) async {
    final title = await vPrompt(context,
        title: '作品名',
        initial: r.title,
        maxLength: 60,
        validate: (t) => validateReleaseInfo(title: t, genre: r.genre, language: r.language));
    if (title == null || !mounted) return;
    final desc = await vPrompt(context, title: '作品简介', initial: r.description, maxLength: 500, maxLines: 5);
    if (desc == null || !mounted) return;
    await _call(() => musicApi.patchRelease(r.rid, {'title': title.trim(), 'description': desc.trim()}));
  }

  Future<void> _pickCover() async {
    try {
      final x = await ImagePicker().pickImage(source: ImageSource.gallery, maxWidth: 1400, imageQuality: 88);
      if (x == null || !mounted) return;
      setState(() => _busy = true);
      // 作品封面过审前是私密的,所以走 /media/v1 拿 media_id,不是公开图片
      final media = await musicApi.uploadReleaseCover(await x.readAsBytes(), x.name);
      if (!mounted) return;
      await musicApi.patchRelease(_rid!, {'cover_media_id': vInt(media['id'])});
      _dirty = true;
      await _load();
    } catch (e) {
      if (mounted) mToast(context, e);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _addTrack() async {
    final picked = await openFile(acceptedTypeGroups: const [
      XTypeGroup(label: '音频', extensions: ['mp3', 'm4a', 'aac', 'flac', 'wav', 'ogg']),
    ]);
    if (picked == null || !mounted) return;
    final size = await picked.length();
    if (!mounted) return;
    if (size > kAudioMaxBytes) {
      mToast(context, '单首最大 200MB,这个文件有 ${(size / 1024 / 1024).toStringAsFixed(0)}MB');
      return;
    }
    final info = await _askTrackInfo(picked.name);
    if (info == null || !mounted) return;
    MusicUploads.instance.start(
      _rid!,
      picked,
      size,
      title: info.title,
      declaration: info.declaration,
      onDone: _load,
    );
    _dirty = true;
    setState(() {});
  }

  /// 加歌之前先问歌名和声明 —— 声明是**必选**的(§4 M1),不给缺省值。
  Future<({String title, String declaration})?> _askTrackInfo(String filename) async {
    final controller = TextEditingController(
        text: filename.contains('.') ? filename.substring(0, filename.lastIndexOf('.')) : filename);
    String? declaration;
    String? error;
    return showDialog<({String title, String declaration})>(
      context: context,
      builder: (ctx) => SzDisposeWith(
        controllers: [controller],
        child: StatefulBuilder(
          builder: (ctx, setLocal) => SzDialog(
            title: const Text('加一首歌'),
            content: Column(mainAxisSize: MainAxisSize.min, children: [
              TextField(
                controller: controller,
                maxLength: 60,
                decoration: InputDecoration(labelText: '歌名', errorText: error, counterText: ''),
              ),
              const SizedBox(height: 12),
              Align(
                alignment: Alignment.centerLeft,
                child: Text('这首歌是', style: TextStyle(fontSize: kFontBody, color: Theme.of(ctx).sz.ink)),
              ),
              const SizedBox(height: 6),
              Wrap(spacing: 8, children: [
                for (final d in ['original', 'authorized'])
                  SzChip(mDeclarationName(d),
                      selected: declaration == d, onTap: () => setLocal(() => declaration = d)),
              ]),
              const SizedBox(height: 6),
              Align(
                alignment: Alignment.centerLeft,
                child: Text('两者都不是的不要传 —— 侵权会下架并留记录',
                    style: TextStyle(fontSize: kFontMicro, color: Theme.of(ctx).sz.inkMuted)),
              ),
            ]),
            actions: [
              TextButton(onPressed: () => Navigator.pop(ctx), child: const Text('取消')),
              FilledButton(
                onPressed: () {
                  final e = validateTrackTitle(controller.text) ??
                      (declaration == null ? '选一下是原创还是已获授权' : null);
                  if (e != null) {
                    setLocal(() => error = e);
                    return;
                  }
                  Navigator.pop(ctx, (title: controller.text.trim(), declaration: declaration!));
                },
                child: const Text('开始上传'),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Future<void> _editTrack(MRelease r, MTrack t) async {
    final changed = await Navigator.of(context)
        .push<bool>(MaterialPageRoute<bool>(builder: (_) => MusicTrackEditPage(track: t, editable: r.editable)));
    if (changed == true) {
      _dirty = true;
      await _load();
    }
  }

  Future<void> _deleteTrack(MRelease r, MTrack t) async {
    if (!await vConfirm(context, title: '删掉「${t.title}」?', ok: '删除', danger: true)) return;
    await _call(() async {
      await musicApi.deleteTrack(t.tid);
      return null;
    });
  }

  /// [to] 是拔掉之后的落点(`onReorderItem` 的口径),不用再自己减一。
  Future<void> _reorder(MRelease r, int from, int to) async {
    if (to == from) return;
    final t = r.tracks.removeAt(from);
    r.tracks.insert(to, t);
    setState(() {});
    try {
      await musicApi.orderTracks(r.rid, [for (final x in r.tracks) x.tid]);
      _dirty = true;
    } catch (e) {
      if (!mounted) return;
      mToast(context, e);
      await _load();
    }
  }

  Future<void> _menu(MRelease r) async {
    final pick = await szShowSheet<String>(
      context: context,
      builder: (ctx) => SafeArea(
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          ListTile(
              leading: const Icon(Icons.delete_outline),
              title: const Text('删除这个作品'),
              onTap: () => Navigator.pop(ctx, 'delete')),
        ]),
      ),
    );
    if (pick != 'delete' || !mounted) return;
    if (!await vConfirm(context,
        title: '删除「${r.title}」?', body: '连同里面的歌一起删掉,删了就找不回来了', ok: '删除', danger: true)) {
      return;
    }
    try {
      await musicApi.deleteRelease(r.rid);
      if (mounted) Navigator.pop(context, true);
    } catch (e) {
      if (mounted) mToast(context, e);
    }
  }
}

/// 驳回 / 下架的原因和申诉入口。
class _RejectBox extends StatelessWidget {
  const _RejectBox({required this.release, required this.onAppeal});

  final MRelease release;
  final VoidCallback onAppeal;

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(kCardPad),
      decoration: BoxDecoration(
        color: sz.danger.withValues(alpha: .06),
        borderRadius: BorderRadius.circular(kRadiusMd),
        border: Border.all(color: sz.danger.withValues(alpha: .3)),
      ),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text(release.status == 'removed' ? '这个作品被下架了' : '这次没通过',
            style: TextStyle(fontSize: kFontBodyLg, color: sz.danger, fontWeight: FontWeight.w600)),
        const SizedBox(height: 4),
        Text([release.rejectCode, release.rejectNote].where((s) => s.isNotEmpty).join('  '),
            style: TextStyle(fontSize: kFontBody, color: sz.ink, height: 1.6)),
        if (release.canAppeal) ...[
          const SizedBox(height: 8),
          Align(
            alignment: Alignment.centerLeft,
            child: OutlinedButton(onPressed: onAppeal, child: const Text('我有异议,申诉')),
          ),
          Text('每个决定只能申诉一次,会换一位管理员复核 —— 原审核人不能复核自己的决定',
              style: TextStyle(fontSize: kFontMicro, color: sz.inkMuted)),
        ],
      ]),
    );
  }
}

/// 正在传的那几首。
class _Uploads extends StatelessWidget {
  const _Uploads({required this.rid, required this.onDone});

  final String rid;
  final Future<void> Function() onDone;

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    return AnimatedBuilder(
      animation: MusicUploads.instance,
      builder: (context, _) {
        final tasks = MusicUploads.instance.of(rid);
        if (tasks.isEmpty) return const SizedBox.shrink();
        return Column(children: [
          for (final t in tasks)
            ListTile(
              dense: true,
              leading: Icon(
                t.state == TrackUploadState.failed ? Icons.error_outline : Icons.upload_file,
                color: t.state == TrackUploadState.failed ? sz.danger : sz.inkMuted,
              ),
              title: Text(t.title.isEmpty ? t.name : t.title, maxLines: 1, overflow: TextOverflow.ellipsis),
              subtitle: t.state == TrackUploadState.failed
                  ? Text(t.error ?? '上传失败', style: TextStyle(fontSize: kFontNote, color: sz.danger))
                  : (t.state == TrackUploadState.creating
                      ? Text('在建歌…', style: TextStyle(fontSize: kFontNote, color: sz.inkMuted))
                      : LinearProgressIndicator(value: t.progress, minHeight: 3)),
              trailing: t.state == TrackUploadState.failed
                  ? Row(mainAxisSize: MainAxisSize.min, children: [
                      TextButton(
                          onPressed: () => MusicUploads.instance.retry(t, onDone: onDone), child: const Text('重试')),
                      IconButton(
                          icon: const Icon(Icons.close, size: 18),
                          tooltip: '不传了',
                          onPressed: () => MusicUploads.instance.dismiss(t)),
                    ])
                  : (t.active
                      ? IconButton(
                          icon: const Icon(Icons.close, size: 18),
                          tooltip: '取消上传',
                          onPressed: () => MusicUploads.instance.cancel(t))
                      : null),
            ),
        ]);
      },
    );
  }
}

class _TrackRow extends StatelessWidget {
  const _TrackRow({
    super.key,
    required this.track,
    required this.index,
    required this.editable,
    required this.onEdit,
    required this.onDelete,
  });

  final MTrack track;
  final int index;
  final bool editable;
  final VoidCallback onEdit;
  final VoidCallback onDelete;

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    final failed = track.transcodeStatus == 'failed';
    final busy = track.transcodeStatus == 'pending' || track.transcodeStatus == 'processing';
    return ListTile(
      dense: true,
      leading: SizedBox(
        width: 26,
        child: Text('${index + 1}', textAlign: TextAlign.center, style: TextStyle(color: sz.inkFaint)),
      ),
      title: Row(children: [
        Flexible(child: Text(track.title, maxLines: 1, overflow: TextOverflow.ellipsis)),
        if (track.explicit) ...[const SizedBox(width: 6), const MExplicitTag()],
      ]),
      subtitle: Text(
        [
          if (track.durationMs > 0) vDuration(track.durationMs),
          if (busy || failed) mTranscodeName(track.transcodeStatus),
          if (failed && track.failReason.isNotEmpty) track.failReason,
          if (track.declaration.isNotEmpty) mDeclarationName(track.declaration),
          if (track.lyricsKind.isNotEmpty && track.lyricsKind != 'none') '有歌词',
        ].join(' · '),
        maxLines: 2,
        overflow: TextOverflow.ellipsis,
        style: TextStyle(fontSize: kFontNote, color: failed ? sz.danger : sz.inkMuted),
      ),
      trailing: Row(mainAxisSize: MainAxisSize.min, children: [
        if (busy)
          const Padding(
            padding: EdgeInsets.only(right: 6),
            child: SizedBox(width: 14, height: 14, child: CircularProgressIndicator(strokeWidth: 2)),
          ),
        if (editable) ...[
          IconButton(icon: const Icon(Icons.delete_outline, size: 18), tooltip: '删掉', onPressed: onDelete),
          ReorderableDragStartListener(index: index, child: Icon(Icons.drag_handle, size: 20, color: sz.inkFaint)),
        ],
      ]),
      onTap: onEdit,
    );
  }
}

/// 一首歌的详细编辑:歌词、署名、不适宜未成年人、声明。
class MusicTrackEditPage extends StatefulWidget {
  const MusicTrackEditPage({super.key, required this.track, this.editable = true});

  final MTrack track;
  final bool editable;

  @override
  State<MusicTrackEditPage> createState() => _MusicTrackEditPageState();
}

class _MusicTrackEditPageState extends State<MusicTrackEditPage> {
  late final TextEditingController _title = TextEditingController(text: widget.track.title);
  late final TextEditingController _lyrics = TextEditingController(text: widget.track.lyrics);
  late final Map<String, TextEditingController> _credits = {
    for (final k in const ['lyricist', 'composer', 'arranger', 'producer'])
      k: TextEditingController(
          text: [for (final n in vList(widget.track.credits[k])) '$n'].join('、')),
  };
  late bool _explicit = widget.track.explicit;
  late String _declaration = widget.track.declaration.isEmpty ? 'original' : widget.track.declaration;
  bool _busy = false;
  String? _titleError;

  static const _creditLabels = {'lyricist': '作词', 'composer': '作曲', 'arranger': '编曲', 'producer': '制作人'};

  @override
  void dispose() {
    _title.dispose();
    _lyrics.dispose();
    for (final c in _credits.values) {
      c.dispose();
    }
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    final e = widget.editable;
    return SzPageScaffold(
      appBar: AppBar(
        title: const Text('歌曲'),
        actions: [if (e) TextButton(onPressed: _busy ? null : _save, child: const Text('保存'))],
      ),
      body: ListView(
        padding: const EdgeInsets.all(kPagePad),
        children: [
          if (!e)
            Padding(
              padding: const EdgeInsets.only(bottom: 12),
              child: Text('这个作品已经在审核中或已发布,歌不能改了。要改先撤回或下架。',
                  style: TextStyle(fontSize: kFontNote, color: sz.inkMuted, height: 1.6)),
            ),
          TextField(
            controller: _title,
            enabled: e,
            maxLength: 60,
            decoration: InputDecoration(labelText: '歌名', errorText: _titleError, border: const OutlineInputBorder()),
          ),
          const SizedBox(height: 12),
          Text('署名', style: TextStyle(fontSize: kFontBodyLg, color: sz.ink)),
          const SizedBox(height: 6),
          for (final k in _creditLabels.keys)
            Padding(
              padding: const EdgeInsets.only(bottom: 8),
              child: TextField(
                controller: _credits[k],
                enabled: e,
                decoration: InputDecoration(
                  labelText: _creditLabels[k],
                  hintText: '多个人用「、」隔开',
                  isDense: true,
                  border: const OutlineInputBorder(),
                ),
              ),
            ),
          const SizedBox(height: 6),
          Text('歌词', style: TextStyle(fontSize: kFontBodyLg, color: sz.ink)),
          const SizedBox(height: 4),
          Text('贴 LRC(带 [00:12.00] 这种时间标签)播放页会跟着滚;贴纯文本也行,只是不滚。',
              style: TextStyle(fontSize: kFontNote, color: sz.inkMuted, height: 1.6)),
          const SizedBox(height: 6),
          TextField(
            controller: _lyrics,
            enabled: e,
            minLines: 6,
            maxLines: 20,
            decoration: const InputDecoration(border: OutlineInputBorder()),
          ),
          const SizedBox(height: 12),
          SwitchListTile(
            value: _explicit,
            onChanged: e ? (v) => setState(() => _explicit = v) : null,
            contentPadding: EdgeInsets.zero,
            title: const Text('含不适宜未成年人的内容'),
            subtitle: Text('勾了之后歌名旁边会标一个「不宜」',
                style: TextStyle(fontSize: kFontNote, color: sz.inkMuted)),
          ),
          const SizedBox(height: 6),
          Text('声明(必选)', style: TextStyle(fontSize: kFontBodyLg, color: sz.ink)),
          const SizedBox(height: 6),
          Wrap(spacing: 8, children: [
            for (final d in ['original', 'authorized'])
              SzChip(mDeclarationName(d),
                  selected: _declaration == d, onTap: e ? () => setState(() => _declaration = d) : null),
          ]),
          const SizedBox(height: 6),
          Text('两者都不是的不要传 —— 侵权会下架并留记录,反复侵权会停用音乐人身份。',
              style: TextStyle(fontSize: kFontMicro, color: sz.inkMuted, height: 1.6)),
          if (widget.track.transcodeStatus == 'failed') ...[
            const SizedBox(height: 14),
            Text('转码失败:${widget.track.failReason.isEmpty ? '文件可能损坏或格式不对' : widget.track.failReason}。删了重传一次。',
                style: TextStyle(fontSize: kFontNote, color: sz.danger, height: 1.6)),
          ],
        ],
      ),
    );
  }

  Future<void> _save() async {
    final err = validateTrackTitle(_title.text);
    setState(() => _titleError = err);
    if (err != null) return;
    setState(() => _busy = true);
    try {
      await musicApi.patchTrack(widget.track.tid, {
        'title': _title.text.trim(),
        'lyrics': _lyrics.text,
        'explicit': _explicit,
        'declaration': _declaration,
        'credits': {
          for (final k in _creditLabels.keys)
            k: _credits[k]!
                .text
                .split(RegExp(r'[、,,/]'))
                .map((s) => s.trim())
                .where((s) => s.isNotEmpty)
                .toList(),
        },
      });
      if (mounted) Navigator.pop(context, true);
    } catch (e) {
      if (mounted) mToast(context, e);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }
}
