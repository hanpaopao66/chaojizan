import 'dart:async';
import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:image_picker/image_picker.dart';
import 'package:superz_shared/superz_shared.dart';

import '../../chat/store.dart';
import '../../identity_page.dart';
import '../../session.dart';
import '../me/common.dart';
import '../models.dart';
import '../nav.dart';
import 'creator_models.dart';
import 'upload_form.dart';
import 'upload_tasks.dart';

/// 分区的兜底清单:zones 接口没拉到时用(和 VIDEO-API 0.7 一致)。
const _fallbackZones = <(String, String)>[
  ('life', '生活'), ('food', '美食'), ('shop_visit', '探店'), ('game', '游戏'), ('knowledge', '知识'),
  ('tech', '科技'), ('music', '音乐'), ('dance', '舞蹈'), ('film', '影视'), ('animal', '动物圈'),
  ('sports', '运动'), ('car', '汽车'), ('fashion', '时尚'), ('funny', '搞笑'), ('travel', '旅行'),
];

/// 投稿 / 编辑稿件(#358)。[vid] 为空 = 新投稿;有 = 编辑已有的稿件。
///
/// 新投稿的顺序是「先选视频、马上建草稿、边传边填」:
/// - 选完视频就建草稿 —— 没实名(D11)、今天投满了、投稿没开放,在传 1GB 之前就知道;
/// - 原片交给全局的上传任务([VideoUploads]),离开这一页也接着传,传完自动挂到这个草稿上;
/// - 表单按差量保存(只送改了的字段),已发布的稿件改内容进待审,线上一个字不动。
class VideoUploadPage extends StatefulWidget {
  const VideoUploadPage({super.key, this.vid});

  final String? vid;

  @override
  State<VideoUploadPage> createState() => _VideoUploadPageState();
}

class _VideoUploadPageState extends State<VideoUploadPage> {
  String? _vid;
  CreatorVideo? _v;

  /// 服务端的样子(算差量的基线)
  UploadForm? _base;
  UploadForm _form = UploadForm();

  bool _busy = false;
  Object? _loadError;
  List<(String, String)> _zones = _fallbackZones;
  Map<String, String> _errors = {};

  /// 刚上传的封面先画本地字节,不等签名地址
  Uint8List? _coverBytes;
  bool _coverUploading = false;

  final _title = TextEditingController();
  final _desc = TextEditingController();
  final _source = TextEditingController();
  final _tagInput = TextEditingController();

  StreamSubscription<({String type, Map<String, dynamic> data})>? _events;
  Timer? _poll;
  bool _refreshing = false;
  bool _refreshAgain = false;
  final Set<PartUpload> _seenDone = {};

  VideoUploads get _uploads => VideoUploads.instance;

  @override
  void initState() {
    super.initState();
    _vid = widget.vid;
    _uploads.addListener(_onUploads);
    // 转码完成 / 失败、审核结果、另一台设备改了稿,都会推用户事件 video(VIDEO-API 10)
    _events = ChatStore.instance.userEvents.stream.listen((e) {
      if (e.type == 'video' && e.data['vid'] == _vid) unawaited(_refresh());
    });
    unawaited(_loadZones());
    if (_vid != null) unawaited(_load());
  }

  @override
  void dispose() {
    _uploads.removeListener(_onUploads);
    _events?.cancel();
    _poll?.cancel();
    _title.dispose();
    _desc.dispose();
    _source.dispose();
    _tagInput.dispose();
    super.dispose();
  }

  // ---------------- 数据 ----------------

  Future<void> _loadZones() async {
    try {
      final z = await videoApi.zones();
      if (!mounted || z.isEmpty) return;
      setState(() => _zones = [for (final x in z) ('${x['zone']}', '${x['name']}')]);
    } catch (_) {
      // 拉不到就用兜底清单,不影响投稿
    }
  }

  Future<void> _load() async {
    setState(() => _loadError = null);
    try {
      final v = CreatorVideo.fromJson(await videoApi.creatorVideo(_vid!));
      if (mounted) _adopt(v, reset: true);
    } catch (e) {
      if (mounted) setState(() => _loadError = e);
    }
  }

  /// 悄悄拉一次最新的(事件来了、上传挂上了、转码轮询)。同时只飞一个,飞的时候又来了就再拉一次。
  Future<void> _refresh() async {
    final vid = _vid;
    if (vid == null || _v == null) return;
    if (_refreshing) {
      _refreshAgain = true;
      return;
    }
    _refreshing = true;
    try {
      do {
        _refreshAgain = false;
        final v = CreatorVideo.fromJson(await videoApi.creatorVideo(vid));
        if (mounted) _adopt(v);
      } while (_refreshAgain && mounted);
    } catch (_) {
      // 刷新失败不打扰:下一个事件或下一轮轮询还会再拉
    } finally {
      _refreshing = false;
    }
  }

  /// 换上服务端的新样子。[reset] 为假时做三方合并:我没动过的字段跟服务端,动过的留我的。
  void _adopt(CreatorVideo v, {bool reset = false}) {
    final fresh = UploadForm.fromCreator(v);
    final old = _base;
    setState(() {
      _v = v;
      _form = (reset || old == null) ? fresh.copy() : rebaseForm(old, _form, fresh);
      _base = fresh;
      _syncControllers();
    });
    if (_form.shopId != null && _form.shopName.isEmpty) unawaited(_lookupShopName(_form.shopId!));
    _schedulePoll(v);
  }

  void _syncControllers() {
    void set(TextEditingController c, String s) {
      if (c.text != s) c.text = s;
    }

    set(_title, _form.title);
    set(_desc, _form.description);
    set(_source, _form.sourceUrl);
  }

  /// 有分 P 在转码时每 5 秒兜底拉一次:实时事件是主路,断线时靠它(和聊天发媒体同一个做法)
  void _schedulePoll(CreatorVideo v) {
    final processing = v.parts.any((p) => p.status == 'processing');
    if (processing && _poll == null) {
      _poll = Timer.periodic(const Duration(seconds: 5), (_) => unawaited(_refresh()));
    } else if (!processing) {
      _poll?.cancel();
      _poll = null;
    }
  }

  void _onUploads() {
    if (!mounted) return;
    final vid = _vid;
    if (vid != null) {
      // 有一 P 刚挂上:拉一次稿件,分 P 列表里就有它了(转码中)
      final done = [for (final t in _uploads.of(vid)) if (t.state == UploadState.done && !_seenDone.contains(t)) t];
      if (done.isNotEmpty) {
        _seenDone.addAll(done);
        unawaited(_refresh().then((_) {
          for (final t in done) {
            _uploads.dismiss(t);
          }
        }));
      }
    }
    setState(() {});
  }

  Future<void> _lookupShopName(int id) async {
    try {
      final m = await rootApi.merchantDetail(id);
      if (mounted && _form.shopId == id) setState(() => _form.shopName = m.name);
    } catch (_) {
      // 查不到名字就显示编号,不影响保存
    }
  }

  bool get _withSchedule => _v?.status != 'published';

  Map<String, Object?> get _diff => _base == null ? const {} : formDiff(_base!, _form, withSchedule: _withSchedule);

  bool get _dirty => _diff.isNotEmpty;

  // ---------------- 动作 ----------------

  void _toast(String s) => vToast(context, s);

  Future<XFile?> _pickVideo() async {
    try {
      return await ImagePicker().pickVideo(source: ImageSource.gallery);
    } catch (e) {
      if (mounted) _toast('没能打开相册:$e');
      return null;
    }
  }

  /// 新投稿:选视频 → 建草稿 → 开始传。
  Future<void> _pickFirst() async {
    if (!await ensureLoggedIn(context)) return;
    final x = await _pickVideo();
    if (x == null) return;
    final size = await x.length();
    if (size > kPartMaxBytes) {
      if (mounted) _toast('单个分 P 最大 1GB');
      return;
    }
    if (!mounted) return;
    setState(() => _busy = true);
    try {
      final v = CreatorVideo.fromJson(await videoApi.createVideo(const {}));
      // 草稿已经建好了:就算这一页已经关了,选好的视频也照样传上去挂到草稿上
      _uploads.start(v.vid, x, size);
      if (!mounted) return;
      _vid = v.vid;
      _adopt(v, reset: true);
      // 预填标题:文件名去掉扩展名(和 B 站一样);算作一处改动,离开时会问要不要存
      if (_form.title.isEmpty) {
        setState(() {
          _form.title = titleFromFileName(x.name);
          _title.text = _form.title;
        });
      }
    } catch (e) {
      if (mounted) await _onError(e);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _addPart() async {
    final vid = _vid;
    if (vid == null) return;
    if (_partCount >= kPartsMax) {
      _toast('一个视频最多 $kPartsMax P');
      return;
    }
    final x = await _pickVideo();
    if (x == null) return;
    final size = await x.length();
    if (size > kPartMaxBytes) {
      if (mounted) _toast('单个分 P 最大 1GB');
      return;
    }
    _uploads.start(vid, x, size);
  }

  int get _partCount {
    final vid = _vid;
    return _form.parts.length + (vid == null ? 0 : _uploads.of(vid).where((t) => t.active).length);
  }

  Future<void> _renamePart(int i) async {
    final p = _form.parts[i];
    final t = await vPrompt(context,
        title: '这一 P 的标题',
        initial: p.title,
        maxLength: kTitleMax,
        validate: (s) => normalizeTitle(s).isEmpty ? '标题不能为空' : null);
    if (t == null || !mounted) return;
    setState(() => _form.parts[i] = PartDraft(p.id, normalizeTitle(t)));
  }

  void _movePart(int i, int d) {
    final j = i + d;
    if (j < 0 || j >= _form.parts.length) return;
    setState(() {
      final p = _form.parts.removeAt(i);
      _form.parts.insert(j, p);
    });
  }

  Future<void> _deletePart(PartDraft p) async {
    final live = _v?.partById(p.id)?.live ?? false;
    final ok = await vConfirm(context,
        title: '删掉「${p.title}」?',
        body: live ? '这一 P 在线上:删除算作改动,审核通过后才会从线上消失。' : '原片和转码结果一起清掉,不能恢复。',
        ok: '删除',
        danger: true);
    if (!ok || !mounted) return;
    await _guard(() async {
      final v = CreatorVideo.fromJson(await videoApi.deletePart(_vid!, p.id));
      if (mounted) _adopt(v);
    });
  }

  Future<void> _uploadCover() async {
    final vid = _vid;
    if (vid == null) return;
    XFile? x;
    try {
      x = await ImagePicker().pickImage(source: ImageSource.gallery, maxWidth: 1920, imageQuality: 90);
    } catch (e) {
      if (mounted) _toast('没能打开相册:$e');
    }
    if (x == null) return;
    final bytes = await x.readAsBytes();
    if (!mounted) return;
    setState(() => _coverUploading = true);
    try {
      final m = await videoApi.uploadCover(bytes, x.name.isEmpty ? 'cover.jpg' : x.name);
      if (!mounted) return;
      setState(() {
        _coverBytes = bytes;
        _form.coverMediaId = vInt(m['id']);
      });
    } catch (e) {
      if (mounted) await _onError(e);
    } finally {
      if (mounted) setState(() => _coverUploading = false);
    }
  }

  Future<void> _pickShop() async {
    final m = await szShowSheet<Merchant>(context: context, builder: (_) => const _ShopPicker());
    if (m == null || !mounted) return;
    setState(() {
      if (_form.shopId != m.id) _form.shopCollab = null; // 换了店,合作声明要重新选
      _form.shopId = m.id;
      _form.shopName = m.name;
      _errors.remove('shop');
    });
  }

  Future<void> _pickSchedule() async {
    final now = DateTime.now();
    final last = now.add(kScheduleMax);
    var init = _form.scheduledAt ?? now.add(const Duration(hours: 1));
    if (init.isAfter(last) || init.isBefore(now)) init = now.add(const Duration(hours: 1));
    final day = await showDatePicker(
      context: context,
      firstDate: DateTime(now.year, now.month, now.day),
      lastDate: last,
      initialDate: init,
      helpText: '哪天公开',
    );
    if (day == null || !mounted) return;
    final t = await showTimePicker(context: context, initialTime: TimeOfDay.fromDateTime(init), helpText: '几点公开');
    if (t == null || !mounted) return;
    final at = DateTime(day.year, day.month, day.day, t.hour, t.minute);
    final err = checkSchedule(at, DateTime.now());
    if (err != null) {
      _toast(err);
      return;
    }
    setState(() {
      _form.scheduledAt = at;
      _errors.remove('schedule');
    });
  }

  /// 存草稿 / 保存改动。返回是否成功(离开时「存草稿」要等它)。
  Future<bool> _save({bool quiet = false}) async {
    final vid = _vid, base = _base;
    if (vid == null || base == null) return false;
    final errs = validateForm(_form, now: DateTime.now(), submitting: false, base: base, withSchedule: _withSchedule);
    setState(() => _errors = errs);
    if (errs.isNotEmpty) {
      _toast(errs.values.first);
      return false;
    }
    final body = _diff;
    if (body.isEmpty) {
      if (!quiet) _toast('没有改动');
      return true;
    }
    setState(() => _busy = true);
    try {
      final v = CreatorVideo.fromJson(await videoApi.patchVideo(vid, body));
      if (!mounted) return true;
      _adopt(v, reset: true);
      if (!quiet) {
        _toast(v.isLive && v.pending?.state == 'editing' ? '改动已保存,提交之后才会送审' : '已保存');
      }
      return true;
    } catch (e) {
      if (mounted) await _onError(e);
      return false;
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  /// 提交审核(已发布的稿件是提交改动)。先把没存的改动存上,再提交。
  Future<void> _submit() async {
    final v = _v, vid = _vid, base = _base;
    if (v == null || vid == null || base == null) return;
    if (_uploads.busy(vid)) {
      _toast('还有分 P 在上传,传完再提交');
      return;
    }
    for (final p in _form.parts) {
      final part = v.partById(p.id);
      if (part != null && part.status == 'failed') {
        _toast('「${p.title}」转码失败,删掉重新上传后再提交');
        return;
      }
    }
    final errs = validateForm(_form, now: DateTime.now(), submitting: true, base: base, withSchedule: _withSchedule);
    setState(() => _errors = errs);
    if (errs.isNotEmpty) {
      _toast(errs.values.first);
      return;
    }
    setState(() => _busy = true);
    try {
      var cur = v;
      final body = _diff;
      if (body.isNotEmpty) {
        cur = CreatorVideo.fromJson(await videoApi.patchVideo(vid, body));
        // 先认下已经存上的:下面提交要是被拒了,再点一次不该把同样的改动当成没存的
        if (mounted) _adopt(cur, reset: true);
      }
      // 已发布的稿件只动了可见性、弹幕 / 评论开关:这些立即生效,没有要送审的改动
      if (cur.isLive && cur.pending?.state != 'editing') {
        if (!mounted) return;
        if (body.isEmpty) {
          _toast(cur.pending?.state == 'rejected' ? '这次改动被驳回了:改一改再提交,或者去创作中心申诉' : '没有改动');
        } else {
          _toastAndPop('已保存,可见性和弹幕、评论开关已经生效');
        }
        return;
      }
      final after = CreatorVideo.fromJson(await videoApi.submit(vid));
      if (!mounted) return;
      _adopt(after, reset: true);
      final transcoding = after.status == 'processing' || after.pending?.state == 'processing';
      _toastAndPop(transcoding ? '已提交,转码完成后自动进入审核' : '已提交审核,结果会在「互动消息 → 系统通知」里告诉你');
    } catch (e) {
      if (mounted) await _onError(e);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  void _toastAndPop(String s) {
    final m = ScaffoldMessenger.maybeOf(context);
    Navigator.of(context).pop(true);
    m?.showSnackBar(SnackBar(content: Text(s)));
  }

  Future<void> _discard() async {
    final ok = await vConfirm(context,
        title: '放弃这次改动?', body: '线上那一版不受影响;为这次改动新传的分 P 会一起删掉。', ok: '放弃改动', danger: true);
    if (!ok || !mounted) return;
    await _guard(() async {
      final v = CreatorVideo.fromJson(await videoApi.discardChanges(_vid!));
      if (!mounted) return;
      _coverBytes = null;
      _adopt(v, reset: true);
      _toast('改动已放弃');
    });
  }

  Future<void> _guard(Future<void> Function() f) async {
    setState(() => _busy = true);
    try {
      await f();
    } catch (e) {
      if (mounted) await _onError(e);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  /// 服务端的错误原样展示;没实名给「去认证」(D11);状态变了(409)顺手拉一次最新的。
  Future<void> _onError(Object e) async {
    if (e is ApiException && e.statusCode == 403 && e.message.contains('实名')) {
      await _needRealname(e.message);
      return;
    }
    if (e is ApiException && (e.statusCode == 409 || e.statusCode == 422)) unawaited(_refresh());
    if (mounted) _toast(videoErrorText(e));
  }

  Future<void> _needRealname(String detail) async {
    final go = await showDialog<bool>(
      context: context,
      builder: (ctx) => SzDialog(
        title: const Text('先完成实名认证'),
        content: Text('$detail\n\n平台对投稿要求实名(评论、弹幕不用)。认证只看姓名和身份证号,证号加密保存,不会给任何人看。'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('以后再说')),
          FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('去认证')),
        ],
      ),
    );
    if (go == true && mounted) {
      await Navigator.of(context).push(MaterialPageRoute<void>(builder: (_) => IdentityPage(api: rootApi)));
    }
  }

  /// 有没存的改动时返回先问一句:存、不存、接着改。
  Future<void> _onLeave() async {
    final v = _v;
    final uploading = _vid != null && _uploads.busy(_vid!);
    final live = v?.isLive ?? false;
    final r = await showDialog<String>(
      context: context,
      builder: (ctx) => SzDialog(
        title: const Text('有改动还没保存'),
        content: Text([
          live ? '不保存的话,这次改的内容会丢掉,线上那一版不受影响。' : '不保存的话,这次填的内容会丢掉;草稿本身留在「创作中心」。',
          if (uploading) '视频会在后台接着传,传完自动挂到这个稿件上。',
        ].join('\n')),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx), child: const Text('接着改')),
          TextButton(
            style: TextButton.styleFrom(foregroundColor: Theme.of(ctx).sz.danger),
            onPressed: () => Navigator.pop(ctx, 'discard'),
            child: const Text('不保存'),
          ),
          FilledButton(onPressed: () => Navigator.pop(ctx, 'save'), child: Text(live ? '保存改动' : '存草稿')),
        ],
      ),
    );
    if (!mounted || r == null) return;
    if (r == 'discard') {
      Navigator.of(context).pop();
    } else if (await _save(quiet: true) && mounted) {
      Navigator.of(context).pop();
    }
  }

  // ---------------- 界面 ----------------

  @override
  Widget build(BuildContext context) {
    final v = _v;
    final Widget body;
    if (_vid == null) {
      body = _pickerView();
    } else if (v == null) {
      body = _loadError != null ? videoErrorView(_loadError, _load) : const Center(child: CircularProgressIndicator());
    } else {
      final bar = _bottomBar(v);
      // 按钮条放在 body 里,不走 SzPageScaffold 的 bottomNavigationBar:宽屏下那个槽外面套的
      // SzContentWidth 是 Center,会把按钮条撑满整屏高度,表单被挤没了(1280 宽实测)
      body = Column(children: [
        Expanded(child: AbsorbPointer(absorbing: _busy, child: _formView(v))),
        if (bar != null) bar,
      ]);
    }
    return PopScope(
      canPop: !_dirty,
      onPopInvokedWithResult: (didPop, _) {
        if (!didPop) unawaited(_onLeave());
      },
      child: SzPageScaffold(
        appBar: AppBar(title: Text(_vid == null ? '投稿' : (v?.isLive ?? false) ? '编辑稿件' : '编辑投稿')),
        body: body,
      ),
    );
  }

  Widget _pickerView() {
    final sz = Theme.of(context).sz;
    Widget note(String s) => Padding(
          padding: const EdgeInsets.only(bottom: 6),
          child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text('·  ', style: TextStyle(fontSize: kFontNote, color: sz.inkMuted)),
            Expanded(child: Text(s, style: TextStyle(fontSize: kFontNote, color: sz.inkMuted, height: 1.5))),
          ]),
        );
    return ListView(padding: const EdgeInsets.all(kPagePad), children: [
      const SizedBox(height: 32),
      Icon(Icons.video_library_outlined, size: 56, color: sz.inkFaint),
      const SizedBox(height: 12),
      Text('选一个视频开始投稿', textAlign: TextAlign.center, style: TextStyle(fontSize: kFontTitle, color: sz.ink)),
      const SizedBox(height: 20),
      Center(
        child: FilledButton.icon(
          onPressed: _busy ? null : _pickFirst,
          icon: _busy
              ? const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2))
              : const Icon(Icons.upload_file),
          label: Text(_busy ? '正在建稿…' : '选择视频'),
        ),
      ),
      const SizedBox(height: 28),
      note('单个视频最大 1GB、最长 30 分钟;一个稿件最多 10 P'),
      note('每人每天最多投 10 个稿件'),
      note('发视频要先完成实名认证(评论、弹幕不用)'),
      note('所有投稿先审后发,审核通过前只有你自己看得到'),
      note('选好视频就会建一个草稿;离开这一页视频也会接着传,传完自动挂上去'),
    ]);
  }

  Color _toneColor(CreatorTone t) {
    final sz = Theme.of(context).sz;
    return switch (t) {
      CreatorTone.neutral => sz.inkMuted,
      CreatorTone.busy => sz.hold,
      CreatorTone.good => sz.earn,
      CreatorTone.bad => sz.danger,
    };
  }

  Widget _lockable(bool locked, Widget child) =>
      locked ? IgnorePointer(child: Opacity(opacity: .55, child: child)) : child;

  Widget _formView(CreatorVideo v) {
    final sz = Theme.of(context).sz;
    final locked = v.contentLocked;
    final removed = v.status == 'removed';
    return ListView(padding: const EdgeInsets.only(bottom: 32), children: [
      _statusCard(v),
      VSection('分 P', trailing: Text('$_partCount / $kPartsMax', style: TextStyle(fontSize: kFontNote, color: sz.inkMuted))),
      _lockable(locked, _partsSection(v)),
      if (_errors['parts'] case final e?) _errorLine(e),
      const VSection('封面'),
      _lockable(locked, _coverSection(v)),
      const VSection('基本信息'),
      _lockable(
        locked,
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: kPagePad),
          child: Column(children: [
            TextField(
              controller: _title,
              maxLength: kTitleMax,
              decoration: InputDecoration(labelText: '标题', hintText: '一句话说清楚视频讲什么', errorText: _errors['title']),
              onChanged: (s) => setState(() {
                _form.title = s;
                _errors.remove('title');
              }),
            ),
            const SizedBox(height: 8),
            TextField(
              controller: _desc,
              maxLength: kDescMax,
              minLines: 3,
              maxLines: 8,
              decoration: InputDecoration(labelText: '简介', hintText: '选填:拍摄背景、出现的店、用到的音乐……', errorText: _errors['description']),
              onChanged: (s) => setState(() {
                _form.description = s;
                _errors.remove('description');
              }),
            ),
          ]),
        ),
      ),
      const VSection('分区'),
      _lockable(locked, _zoneSection()),
      if (_errors['zone'] case final e?) _errorLine(e),
      VSection('标签', trailing: Text('${_form.tags.length} / $kTagsMax', style: TextStyle(fontSize: kFontNote, color: sz.inkMuted))),
      _lockable(locked, _tagSection()),
      if (_errors['tags'] case final e?) _errorLine(e),
      const VSection('类型'),
      _lockable(locked, _copyrightSection()),
      const VSection('挂店铺(探店)'),
      _lockable(locked, _shopSection()),
      if (_errors['shop'] case final e?) _errorLine(e),
      const VSection('谁能看'),
      _lockable(removed, _visibilitySection()),
      const VSection('互动'),
      _lockable(
        removed,
        Column(children: [
          SwitchListTile(
            title: const Text('允许发弹幕'),
            value: _form.allowDanmaku,
            onChanged: (b) => setState(() => _form.allowDanmaku = b),
          ),
          SwitchListTile(
            title: const Text('允许评论'),
            value: _form.allowComments,
            onChanged: (b) => setState(() => _form.allowComments = b),
          ),
        ]),
      ),
      if (_withSchedule) ...[
        const VSection('定时发布'),
        _lockable(removed, _scheduleSection(v)),
        if (_errors['schedule'] case final e?) _errorLine(e),
      ],
    ]);
  }

  Widget _errorLine(String e) {
    final sz = Theme.of(context).sz;
    return Padding(
      padding: const EdgeInsets.fromLTRB(kPagePad, 4, kPagePad, 0),
      child: Text(e, style: TextStyle(fontSize: kFontNote, color: sz.danger)),
    );
  }

  Widget _statusCard(CreatorVideo v) {
    final sz = Theme.of(context).sz;
    final tags = creatorTags(v);
    final p = v.pending;
    final lines = <Widget>[];
    void line(String s, {Color? color}) {
      if (s.isEmpty) return;
      lines.add(Padding(
        padding: const EdgeInsets.only(top: 6),
        child: Text(s, style: TextStyle(fontSize: kFontNote, height: 1.5, color: color ?? sz.inkMuted)),
      ));
    }

    for (final t in tags) {
      if (t.detail.isNotEmpty) line('${t.label}:${t.detail}', color: t.tone == CreatorTone.bad ? sz.danger : null);
    }
    if (v.status == 'removed') {
      line('稿件已下架,不能修改;有异议可以在创作中心申诉。');
    } else if (v.isLive) {
      line('改动要重新审核,审核期间线上仍是旧版。可见性、弹幕和评论开关改了立即生效。');
      if (p != null) line(pendingSummary(p));
    } else if (v.status == 'processing' || v.status == 'reviewing') {
      line('稿件正在转码 / 审核,内容暂时不能改;可见性、弹幕和评论开关可以改。');
    } else if (v.status == 'rejected' || v.status == 'failed') {
      line('改好之后重新提交就行;觉得判错了也可以在创作中心申诉。');
    }
    if (p != null && p.busy && v.status != 'removed') line('改动正在转码 / 审核,内容暂时不能改。');
    return Container(
      margin: const EdgeInsets.fromLTRB(kPagePad, 12, kPagePad, 0),
      padding: const EdgeInsets.all(kCardPad),
      decoration: BoxDecoration(
        color: sz.surface,
        borderRadius: BorderRadius.circular(kRadiusMd),
        border: Border.all(color: sz.line),
      ),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          Expanded(
            child: Wrap(spacing: 6, runSpacing: 4, children: [
              for (final t in tags) VTag(t.label, color: _toneColor(t.tone)),
            ]),
          ),
          if (p != null && p.state != 'reviewing' && v.status != 'removed')
            TextButton(onPressed: _busy ? null : _discard, child: const Text('放弃改动')),
        ]),
        ...lines,
      ]),
    );
  }

  Widget _partsSection(CreatorVideo v) {
    final sz = Theme.of(context).sz;
    final tasks = [for (final t in _uploads.of(v.vid)) if (t.state != UploadState.done) t];
    return Column(children: [
      for (var i = 0; i < _form.parts.length; i++) _partRow(v, i),
      for (final t in tasks) _uploadRow(t),
      if (_form.parts.isEmpty && tasks.isEmpty)
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: kPagePad, vertical: 8),
          child: Text('还没有视频', style: TextStyle(fontSize: kFontNote, color: sz.inkMuted)),
        ),
      if (_partCount < kPartsMax)
        ListTile(
          leading: Icon(Icons.add_circle_outline, color: sz.clay),
          title: Text('再加一 P', style: TextStyle(color: sz.clay)),
          subtitle: const Text('每 P 单独转码;全部转完、审核通过才一起上线'),
          onTap: _addPart,
        ),
    ]);
  }

  Widget _partRow(CreatorVideo v, int i) {
    final sz = Theme.of(context).sz;
    final d = _form.parts[i];
    final p = v.partById(d.id);
    final (String status, Color color) = switch (p?.status) {
      'processing' => ('转码中…', sz.hold),
      'failed' => ('转码失败:${p!.error.isEmpty ? '原因未知' : p.error}', sz.danger),
      'ready' => ('${vDuration(p!.durationMs)} · ${p.w}×${p.h}', sz.inkMuted),
      _ => ('', sz.inkMuted),
    };
    final extra = v.isLive && p != null ? (p.live ? ' · 线上' : ' · 新加的,过审后上线') : '';
    return ListTile(
      contentPadding: const EdgeInsets.only(left: kPagePad, right: 4),
      leading: CircleAvatar(
        radius: 16,
        backgroundColor: sz.surfaceAlt,
        child: Text('P${i + 1}', style: TextStyle(fontSize: kFontMicro, color: sz.ink)),
      ),
      title: Text(d.title.isEmpty ? '未命名' : d.title, maxLines: 1, overflow: TextOverflow.ellipsis),
      subtitle: Text('$status$extra', maxLines: 2, overflow: TextOverflow.ellipsis, style: TextStyle(fontSize: kFontNote, color: color)),
      onTap: () => _renamePart(i),
      trailing: Row(mainAxisSize: MainAxisSize.min, children: [
        IconButton(
          tooltip: '上移',
          visualDensity: VisualDensity.compact,
          icon: const Icon(Icons.arrow_upward, size: 18),
          onPressed: i == 0 ? null : () => _movePart(i, -1),
        ),
        IconButton(
          tooltip: '下移',
          visualDensity: VisualDensity.compact,
          icon: const Icon(Icons.arrow_downward, size: 18),
          onPressed: i == _form.parts.length - 1 ? null : () => _movePart(i, 1),
        ),
        IconButton(
          tooltip: '删除这一 P',
          visualDensity: VisualDensity.compact,
          icon: const Icon(Icons.delete_outline, size: 18),
          onPressed: () => _deletePart(d),
        ),
      ]),
    );
  }

  Widget _uploadRow(PartUpload t) {
    final sz = Theme.of(context).sz;
    final pct = '${(t.progress * 100).clamp(0, 100).toStringAsFixed(0)}%';
    final (String text, Color color) = switch (t.state) {
      UploadState.uploading => ('上传中 $pct${t.attempts > 1 ? '(网络不稳,第 ${t.attempts} 次)' : ''}', sz.hold),
      UploadState.attaching => ('传完了,正在挂到稿件上…', sz.hold),
      UploadState.failed => (t.error ?? '上传失败', sz.danger),
      _ => ('', sz.inkMuted),
    };
    return ListTile(
      contentPadding: const EdgeInsets.only(left: kPagePad, right: 4),
      leading: SizedBox(
        width: 32,
        height: 32,
        child: t.state == UploadState.failed
            ? Icon(Icons.error_outline, color: sz.danger)
            : CircularProgressIndicator(value: t.state == UploadState.attaching ? null : t.progress, strokeWidth: 3),
      ),
      title: Text(t.name, maxLines: 1, overflow: TextOverflow.ellipsis),
      subtitle: Text(text, style: TextStyle(fontSize: kFontNote, color: color)),
      trailing: t.state == UploadState.failed
          ? Row(mainAxisSize: MainAxisSize.min, children: [
              TextButton(onPressed: () => _uploads.retry(t), child: const Text('重试')),
              IconButton(tooltip: '不要了', icon: const Icon(Icons.close, size: 18), onPressed: () => _uploads.dismiss(t)),
            ])
          : IconButton(
              tooltip: '取消上传',
              icon: const Icon(Icons.close, size: 18),
              onPressed: t.state == UploadState.uploading
                  ? () async {
                      if (await vConfirm(context, title: '不传这个视频了?', ok: '取消上传', danger: true)) _uploads.cancel(t);
                    }
                  : null,
            ),
    );
  }

  Widget _coverSection(CreatorVideo v) {
    final sz = Theme.of(context).sz;
    final candidates = <Map<String, dynamic>>[
      for (final d in _form.parts)
        if (v.partById(d.id) case final p? when p.status == 'ready') ...p.coverCandidates,
    ];
    final selected = _form.coverMediaId;
    String previewUrl = '';
    if (selected != null) {
      for (final c in candidates) {
        if (vInt(c['media_id']) == selected) previewUrl = '${c['url']}';
      }
      if (previewUrl.isEmpty) {
        final pc = v.pending;
        if (pc != null && pc.coverPreview.isNotEmpty && vInt(pc.fields['cover_media_id']) == selected) {
          previewUrl = pc.coverPreview;
        } else if (v.coverMediaId == selected) {
          previewUrl = v.coverPreview;
        }
      }
    }
    final fallback = selected == null && candidates.isNotEmpty ? '${candidates.first['url']}' : '';
    Widget img(String url, int? key) => Image(
          image: szNetImageKeyed(videoResolve(url), 'vmedia:${key ?? url}'),
          fit: BoxFit.cover,
          errorBuilder: (_, __, ___) => ColoredBox(color: sz.surfaceAlt),
        );
    Widget preview;
    if (_coverBytes != null && selected != null && previewUrl.isEmpty) {
      preview = Image.memory(_coverBytes!, fit: BoxFit.cover);
    } else if (previewUrl.isNotEmpty) {
      preview = img(previewUrl, selected);
    } else if (fallback.isNotEmpty) {
      preview = img(fallback, vInt(candidates.first['media_id']));
    } else {
      preview = ColoredBox(
        color: sz.surfaceAlt,
        child: Center(child: Icon(Icons.image_outlined, color: sz.inkFaint)),
      );
    }
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: kPagePad),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          SizedBox(
            width: 176,
            child: AspectRatio(
              aspectRatio: 16 / 10,
              child: ClipRRect(borderRadius: BorderRadius.circular(kRadiusSm), child: preview),
            ),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              OutlinedButton.icon(
                onPressed: _coverUploading ? null : _uploadCover,
                icon: _coverUploading
                    ? const SizedBox(width: 16, height: 16, child: CircularProgressIndicator(strokeWidth: 2))
                    : const Icon(Icons.add_photo_alternate_outlined, size: 18),
                label: const Text('上传封面'),
              ),
              const SizedBox(height: 6),
              Text(
                selected == null
                    ? (candidates.isEmpty ? '转码完成后可以从视频里选一帧;不选就用第一 P 的第一帧' : '没选的话用第一 P 的第一帧')
                    : !v.isLive
                        ? '封面过审前只有你自己看得到'
                        : (selected == v.coverMediaId ? '线上用的就是这张' : '换封面算改动,审核通过后才换上去'),
                style: TextStyle(fontSize: kFontMicro, color: sz.inkMuted, height: 1.5),
              ),
            ]),
          ),
        ]),
        if (candidates.isNotEmpty) ...[
          const SizedBox(height: 10),
          Text('从视频里选一帧', style: TextStyle(fontSize: kFontNote, color: sz.inkMuted)),
          const SizedBox(height: 6),
          SizedBox(
            height: 64,
            child: ListView.separated(
              scrollDirection: Axis.horizontal,
              itemCount: candidates.length,
              separatorBuilder: (_, __) => const SizedBox(width: 8),
              itemBuilder: (context, i) {
                final c = candidates[i];
                final id = vInt(c['media_id']);
                final on = id == selected;
                return GestureDetector(
                  onTap: () => setState(() {
                    _form.coverMediaId = id;
                    _coverBytes = null;
                  }),
                  child: Container(
                    width: 102,
                    decoration: BoxDecoration(
                      borderRadius: BorderRadius.circular(kRadiusSm),
                      border: Border.all(color: on ? sz.clay : sz.line, width: on ? 2 : 1),
                    ),
                    clipBehavior: Clip.antiAlias,
                    child: img('${c['url']}', id),
                  ),
                );
              },
            ),
          ),
        ],
      ]),
    );
  }

  Widget _zoneSection() => Padding(
        padding: const EdgeInsets.symmetric(horizontal: kPagePad),
        child: Wrap(spacing: 8, runSpacing: 8, children: [
          for (final (key, name) in _zones)
            ChoiceChip(
              label: Text(name),
              selected: _form.zone == key,
              onSelected: (_) => setState(() {
                _form.zone = key;
                _errors.remove('zone');
              }),
            ),
        ]),
      );

  void _commitTags([String? raw]) {
    final text = raw ?? _tagInput.text;
    if (text.trim().isEmpty) return;
    final r = addTags(_form.tags, text);
    setState(() {
      _form.tags = r.tags;
      if (r.error != null) {
        _errors['tags'] = r.error!;
      } else {
        _errors.remove('tags');
      }
    });
    _tagInput.clear();
  }

  Widget _tagSection() {
    final sz = Theme.of(context).sz;
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: kPagePad),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        if (_form.tags.isNotEmpty)
          Padding(
            padding: const EdgeInsets.only(bottom: 8),
            child: Wrap(spacing: 6, runSpacing: 6, children: [
              for (final t in _form.tags)
                InputChip(
                  label: Text(t),
                  onDeleted: () => setState(() {
                    _form.tags = [..._form.tags]..remove(t);
                    _errors.remove('tags');
                  }),
                ),
            ]),
          ),
        if (_form.tags.length < kTagsMax)
          TextField(
            controller: _tagInput,
            textInputAction: TextInputAction.done,
            decoration: InputDecoration(
              hintText: '输入标签,回车添加',
              suffixIcon: IconButton(icon: const Icon(Icons.add), tooltip: '添加', onPressed: _commitTags),
            ),
            onSubmitted: _commitTags,
            onChanged: (s) {
              // 敲了逗号 / 顿号就当回车:一次粘进来一串标签也能拆开
              if (RegExp(r'[,，、;；]').hasMatch(s)) _commitTags(s);
            },
          ),
        Padding(
          padding: const EdgeInsets.only(top: 4),
          child: Text('最多 $kTagsMax 个,每个不超过 $kTagMax 字;搜索会搜到标签',
              style: TextStyle(fontSize: kFontMicro, color: sz.inkMuted)),
        ),
      ]),
    );
  }

  Widget _copyrightSection() {
    final sz = Theme.of(context).sz;
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: kPagePad),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        SegmentedButton<String>(
          segments: const [
            ButtonSegment(value: 'original', label: Text('自制')),
            ButtonSegment(value: 'repost', label: Text('转载')),
          ],
          selected: {_form.copyright},
          onSelectionChanged: (s) => setState(() {
            _form.copyright = s.first;
            _errors.remove('source');
          }),
        ),
        const SizedBox(height: 6),
        Text(
          _form.copyright == 'repost' ? '转载要写明出处;别人最多给转载视频投 1 枚硬币' : '自己拍的、剪的;别人最多能投 2 枚硬币',
          style: TextStyle(fontSize: kFontMicro, color: sz.inkMuted),
        ),
        if (_form.copyright == 'repost') ...[
          const SizedBox(height: 8),
          TextField(
            controller: _source,
            keyboardType: TextInputType.url,
            decoration: InputDecoration(labelText: '转载来源', hintText: 'https://…', errorText: _errors['source']),
            onChanged: (s) => setState(() {
              _form.sourceUrl = s;
              _errors.remove('source');
            }),
          ),
        ],
      ]),
    );
  }

  Widget _shopSection() {
    final sz = Theme.of(context).sz;
    if (_form.shopId == null) {
      return Padding(
        padding: const EdgeInsets.symmetric(horizontal: kPagePad),
        child: SzEntryGroup(
          footnote: '只能挂一家本平台正常营业的店。平台不收推广费,也不按挂没挂店给流量。',
          children: [
            SzEntryTile(title: '挂一家店', icon: Icons.storefront_outlined, hint: '探店视频可以挂上你去的那家', onTap: _pickShop),
          ],
        ),
      );
    }
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: kPagePad),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        SzEntryGroup(children: [
          SzEntryTile(
            title: _form.shopName.isEmpty ? '店铺 #${_form.shopId}' : _form.shopName,
            icon: Icons.storefront_outlined,
            value: '换一家',
            onTap: _pickShop,
          ),
          SzEntryTile(
            title: '不挂店了',
            icon: Icons.link_off,
            dense: true,
            onTap: () => setState(() {
              _form.shopId = null;
              _form.shopName = '';
              _form.shopCollab = null;
              _errors.remove('shop');
            }),
          ),
        ]),
        const SizedBox(height: 8),
        Text('和这家店有没有合作?(必选)', style: TextStyle(fontSize: kFontBody, color: sz.ink)),
        RadioGroup<bool>(
          groupValue: _form.shopCollab,
          onChanged: (b) => setState(() {
            _form.shopCollab = b;
            _errors.remove('shop');
          }),
          child: const Column(children: [
            RadioListTile<bool>(
              value: true,
              contentPadding: EdgeInsets.zero,
              title: Text('有合作'),
              subtitle: Text('商家给了钱、送了东西或者请你来拍;视频上会标「合作」'),
            ),
            RadioListTile<bool>(
              value: false,
              contentPadding: EdgeInsets.zero,
              title: Text('没有合作'),
              subtitle: Text('自己花钱去的'),
            ),
          ]),
        ),
      ]),
    );
  }

  Widget _visibilitySection() => RadioGroup<String>(
        groupValue: _form.visibility,
        onChanged: (s) => setState(() => _form.visibility = s ?? 'public'),
        child: const Column(children: [
          RadioListTile<String>(value: 'public', title: Text('公开'), subtitle: Text('审核通过后所有人都能看到')),
          RadioListTile<String>(
              value: 'unlisted', title: Text('不公开'), subtitle: Text('拿到链接的人能看,不进推荐、搜索和你的空间')),
          RadioListTile<String>(value: 'private', title: Text('私密'), subtitle: Text('只有你自己能看')),
        ]),
      );

  Widget _scheduleSection(CreatorVideo v) {
    final sz = Theme.of(context).sz;
    final at = _form.scheduledAt;
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      SwitchListTile(
        title: const Text('定时发布'),
        subtitle: Text(at == null ? '审核通过后立即公开' : '${vDateTime(at)} 公开(审核通过后到点才公开)'),
        value: at != null,
        onChanged: (on) {
          if (on) {
            unawaited(_pickSchedule());
          } else {
            setState(() {
              _form.scheduledAt = null;
              _errors.remove('schedule');
            });
          }
        },
      ),
      if (at != null)
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: 8),
          child: TextButton.icon(onPressed: _pickSchedule, icon: const Icon(Icons.schedule, size: 18), label: const Text('改时间')),
        ),
      Padding(
        padding: const EdgeInsets.symmetric(horizontal: kPagePad),
        child: Text(
          v.status == 'scheduled' ? '已经审核通过,在等定时发布;关掉定时就是马上公开。' : '可以设在 5 分钟之后、30 天之内。',
          style: TextStyle(fontSize: kFontMicro, color: sz.inkMuted),
        ),
      ),
    ]);
  }

  Widget? _bottomBar(CreatorVideo v) {
    if (v.status == 'removed') return null;
    final uploading = _uploads.busy(v.vid);
    final Widget row;
    if (v.contentLocked) {
      row = SizedBox(
        width: double.infinity,
        child: FilledButton(onPressed: _busy || !_dirty ? null : () => _save(), child: const Text('保存设置')),
      );
    } else {
      row = Row(children: [
        Expanded(
          child: OutlinedButton(onPressed: _busy ? null : () => _save(), child: Text(v.isLive ? '保存' : '存草稿')),
        ),
        const SizedBox(width: 12),
        Expanded(
          flex: 2,
          child: FilledButton(
            onPressed: _busy || uploading ? null : _submit,
            child: Text(_busy
                ? '处理中…'
                : uploading
                    ? '等上传完…'
                    : v.isLive
                        ? '提交改动'
                        : '提交审核'),
          ),
        ),
      ]);
    }
    return SafeArea(
      top: false,
      child: Padding(padding: const EdgeInsets.fromLTRB(kPagePad, 8, kPagePad, 8), child: row),
    );
  }
}

/// 挂店铺:搜本平台的商家(D16)。
class _ShopPicker extends StatefulWidget {
  const _ShopPicker();

  @override
  State<_ShopPicker> createState() => _ShopPickerState();
}

class _ShopPickerState extends State<_ShopPicker> {
  final _q = TextEditingController();
  Timer? _debounce;
  List<Merchant>? _items;
  bool _loading = false;
  Object? _error;
  int _seq = 0;

  @override
  void dispose() {
    _debounce?.cancel();
    _q.dispose();
    super.dispose();
  }

  void _onChanged(String s) {
    _debounce?.cancel();
    _debounce = Timer(const Duration(milliseconds: 350), () => _search(s));
  }

  Future<void> _search(String s) async {
    final q = s.trim();
    final seq = ++_seq;
    if (q.isEmpty) {
      setState(() {
        _items = null;
        _loading = false;
      });
      return;
    }
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final r = await rootApi.searchMerchants(q);
      if (mounted && seq == _seq) setState(() => _items = r.take(30).toList());
    } catch (e) {
      if (mounted && seq == _seq) setState(() => _error = e);
    } finally {
      if (mounted && seq == _seq) setState(() => _loading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    final items = _items;
    return SizedBox(
      height: MediaQuery.sizeOf(context).height * .7,
      child: Padding(
        padding: EdgeInsets.only(bottom: MediaQuery.viewInsetsOf(context).bottom),
        child: Column(children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(kPagePad, 8, kPagePad, 8),
            child: TextField(
              controller: _q,
              autofocus: true,
              textInputAction: TextInputAction.search,
              onChanged: _onChanged,
              onSubmitted: _search,
              decoration: InputDecoration(
                hintText: '搜店名或菜名',
                prefixIcon: const Icon(Icons.search),
                suffixIcon: _loading
                    ? const Padding(
                        padding: EdgeInsets.all(12),
                        child: SizedBox(width: 16, height: 16, child: CircularProgressIndicator(strokeWidth: 2)),
                      )
                    : null,
              ),
            ),
          ),
          Expanded(
            child: _error != null
                ? Center(child: Text(videoErrorText(_error!), style: TextStyle(color: sz.danger)))
                : items == null
                    ? Center(
                        child: Text('只能挂本平台正常营业的店', style: TextStyle(fontSize: kFontNote, color: sz.inkMuted)),
                      )
                    : items.isEmpty
                        ? Center(child: Text('没找到这家店', style: TextStyle(color: sz.inkMuted)))
                        : ListView.builder(
                            itemCount: items.length,
                            itemBuilder: (context, i) {
                              final m = items[i];
                              return ListTile(
                                leading: SzImage(
                                  url: m.logoUrl.isEmpty ? '' : videoResolve(m.logoUrl),
                                  name: m.name,
                                  size: 40,
                                ),
                                title: Text(m.name, maxLines: 1, overflow: TextOverflow.ellipsis),
                                subtitle: Text(m.address, maxLines: 1, overflow: TextOverflow.ellipsis),
                                onTap: () => Navigator.pop(context, m),
                              );
                            },
                          ),
          ),
        ]),
      ),
    );
  }
}
