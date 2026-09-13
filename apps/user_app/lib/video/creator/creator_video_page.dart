import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:superz_shared/superz_shared.dart';

import '../../chat/store.dart';
import '../me/common.dart';
import '../models.dart';
import '../nav.dart';
import '../widgets/cards.dart';
import 'creator_models.dart';
import 'line_chart.dart';
import 'upload_page.dart';
import 'upload_tasks.dart';

/// 创作中心里的一个稿件(#358):状态、驳回 / 下架原因、审核记录、申诉、改动、编辑、删除、近 30 天数据。
class CreatorVideoPage extends StatefulWidget {
  const CreatorVideoPage(this.vid, {super.key});

  final String vid;

  @override
  State<CreatorVideoPage> createState() => _CreatorVideoPageState();
}

class _CreatorVideoPageState extends State<CreatorVideoPage> {
  CreatorVideo? _v;
  Object? _error;
  Map<String, dynamic>? _stats;
  String _metric = 'views';
  bool _busy = false;
  StreamSubscription<({String type, Map<String, dynamic> data})>? _events;

  @override
  void initState() {
    super.initState();
    _load();
    _events = ChatStore.instance.userEvents.stream.listen((e) {
      if (e.type == 'video' && e.data['vid'] == widget.vid) _load();
    });
    VideoUploads.instance.addListener(_onUploads);
  }

  @override
  void dispose() {
    _events?.cancel();
    VideoUploads.instance.removeListener(_onUploads);
    super.dispose();
  }

  void _onUploads() {
    if (mounted) setState(() {});
  }

  Future<void> _load() async {
    // 稿件和数据一起发出去;数据拉不到只是少一张图,不让整页进错误态
    final vf = videoApi.creatorVideo(widget.vid);
    final sf = videoApi.creatorStats(widget.vid, days: 30);
    final g = SzGather();
    final v = await g.take(vf);
    final s = await g.soft<Map<String, dynamic>?>(sf, null);
    if (!mounted) return;
    setState(() {
      if (v != null) {
        _v = CreatorVideo.fromJson(v);
        _error = null;
      } else if (_v == null) {
        _error = g.error;
      }
      if (s != null) _stats = s;
    });
  }

  Future<void> _act(Future<void> Function() f) async {
    setState(() => _busy = true);
    try {
      await f();
    } catch (e) {
      if (mounted) vToast(context, e);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _edit() async {
    await Navigator.of(context).push<bool>(MaterialPageRoute(builder: (_) => VideoUploadPage(vid: widget.vid)));
    if (mounted) await _load();
  }

  Future<void> _appeal() async {
    final text = await vPrompt(context,
        title: '申诉',
        hint: '说说为什么觉得判得不对(至少 5 个字)',
        maxLength: 500,
        maxLines: 4,
        ok: '提交申诉',
        validate: (s) => s.trim().runes.length < 5 ? '申诉理由至少写 5 个字' : null);
    if (text == null || !mounted) return;
    await _act(() async {
      await videoApi.appeal(widget.vid, text.trim());
      if (!mounted) return;
      vToast(context, '申诉已提交:会由另一名审核员处理,结果在「互动消息 → 系统通知」里告诉你');
      await _load();
    });
  }

  Future<void> _discard() async {
    final ok = await vConfirm(context,
        title: '放弃这次改动?', body: '线上那一版不受影响;为这次改动新传的分 P 会一起删掉。', ok: '放弃改动', danger: true);
    if (!ok || !mounted) return;
    await _act(() async {
      final v = await videoApi.discardChanges(widget.vid);
      if (!mounted) return;
      setState(() => _v = CreatorVideo.fromJson(v));
      vToast(context, '改动已放弃');
    });
  }

  Future<void> _delete() async {
    final v = _v;
    final ok = await vConfirm(context,
        title: '删除「${v?.displayTitle ?? '这个稿件'}」?',
        body: '删除后立即从所有地方消失、播放地址失效,不能恢复。收到的硬币不会退回。',
        ok: '删除',
        danger: true);
    if (!ok || !mounted) return;
    await _act(() async {
      await videoApi.deleteVideo(widget.vid);
      if (!mounted) return;
      final m = ScaffoldMessenger.maybeOf(context);
      Navigator.of(context).pop(true);
      m?.showSnackBar(const SnackBar(content: Text('稿件已删除')));
    });
  }

  Color _tone(CreatorTone t) {
    final sz = Theme.of(context).sz;
    return switch (t) {
      CreatorTone.neutral => sz.inkMuted,
      CreatorTone.busy => sz.hold,
      CreatorTone.good => sz.earn,
      CreatorTone.bad => sz.danger,
    };
  }

  @override
  Widget build(BuildContext context) {
    final v = _v;
    return SzPageScaffold(
      appBar: AppBar(title: const Text('稿件详情')),
      body: v == null
          ? (_error != null ? videoErrorView(_error, _load) : const Center(child: CircularProgressIndicator()))
          : RefreshIndicator(
              onRefresh: _load,
              child: AbsorbPointer(absorbing: _busy, child: _body(v)),
            ),
    );
  }

  Widget _body(CreatorVideo v) {
    final sz = Theme.of(context).sz;
    final tags = creatorTags(v);
    final uploading = VideoUploads.instance.progressOf(v.vid);
    final cover = VideoCard.fromJson({...v.raw, 'cover': v.card.cover.isNotEmpty ? v.card.cover : v.coverPreview});
    return ListView(padding: const EdgeInsets.only(bottom: 32), children: [
      Padding(
        padding: const EdgeInsets.fromLTRB(kPagePad, 12, kPagePad, 0),
        child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          SizedBox(
            width: 148,
            child: AspectRatio(aspectRatio: 16 / 10, child: VideoCover(card: cover, showDuration: v.card.durationMs > 0)),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(v.displayTitle,
                  maxLines: 3,
                  overflow: TextOverflow.ellipsis,
                  style: TextStyle(fontSize: kFontBodyLg, fontWeight: FontWeight.w600, color: sz.ink)),
              const SizedBox(height: 6),
              Wrap(spacing: 6, runSpacing: 4, children: [
                if (uploading != null) VTag('上传中 ${(uploading * 100).toStringAsFixed(0)}%', color: sz.hold),
                for (final t in tags) VTag(t.label, color: _tone(t.tone)),
              ]),
              const SizedBox(height: 6),
              Text(_timeLine(v), style: TextStyle(fontSize: kFontMicro, color: sz.inkMuted)),
            ]),
          ),
        ]),
      ),
      for (final t in tags)
        if (t.detail.isNotEmpty)
          Padding(
            padding: const EdgeInsets.fromLTRB(kPagePad, 10, kPagePad, 0),
            child: Text('${t.label}:${t.detail}',
                style: TextStyle(fontSize: kFontNote, height: 1.5, color: t.tone == CreatorTone.bad ? sz.danger : sz.inkMuted)),
          ),
      if (v.pending case final p?) _pendingCard(v, p),
      Padding(
        padding: const EdgeInsets.fromLTRB(kPagePad, 14, kPagePad, 0),
        child: Wrap(spacing: 8, runSpacing: 8, children: [
          if (v.status != 'removed')
            OutlinedButton.icon(onPressed: _edit, icon: const Icon(Icons.edit_outlined, size: 18), label: const Text('编辑')),
          if (v.watchable)
            OutlinedButton.icon(
              onPressed: () => openVideo(context, v.vid),
              icon: const Icon(Icons.play_circle_outline, size: 18),
              label: const Text('去看看'),
            ),
          if (v.watchable && v.link.isNotEmpty)
            OutlinedButton.icon(
              onPressed: () async {
                await Clipboard.setData(ClipboardData(text: v.link));
                if (mounted) vToast(context, '链接已复制');
              },
              icon: const Icon(Icons.link, size: 18),
              label: const Text('复制链接'),
            ),
          if (v.canAppeal)
            OutlinedButton.icon(onPressed: _appeal, icon: const Icon(Icons.gavel_outlined, size: 18), label: const Text('申诉')),
          TextButton.icon(
            style: TextButton.styleFrom(foregroundColor: sz.danger),
            onPressed: _delete,
            icon: const Icon(Icons.delete_outline, size: 18),
            label: const Text('删除'),
          ),
        ]),
      ),
      if (v.canAppeal)
        Padding(
          padding: const EdgeInsets.fromLTRB(kPagePad, 8, kPagePad, 0),
          child: Text('每个结论只能申诉一次,由另一名审核员复核(不是原来那位)。改了稿件直接重新提交就行,不用申诉。',
              style: TextStyle(fontSize: kFontMicro, color: sz.inkMuted, height: 1.5)),
        ),
      const VSection('数据'),
      _statsSection(v),
      const VSection('分 P'),
      for (final (i, p) in v.parts.indexed) _partTile(v, i, p),
      if (v.parts.isEmpty)
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: kPagePad),
          child: Text('还没有视频', style: TextStyle(fontSize: kFontNote, color: sz.inkMuted)),
        ),
      const VSection('审核记录'),
      ..._decisions(v),
    ]);
  }

  String _timeLine(CreatorVideo v) {
    final parts = <String>[
      if (v.card.publishedAt case final t?) '发布于 ${vDateTime(t)}',
      if (v.card.publishedAt == null && v.submittedAt != null) '提交于 ${vDateTime(v.submittedAt!)}',
      if (v.card.publishedAt == null && v.submittedAt == null && v.createdAt != null) '创建于 ${vDateTime(v.createdAt!)}',
      if (v.card.zoneName.isNotEmpty) v.card.zoneName,
      switch (v.visibility) { 'unlisted' => '不公开', 'private' => '私密', _ => '' },
    ];
    return parts.where((s) => s.isNotEmpty).join(' · ');
  }

  Widget _pendingCard(CreatorVideo v, PendingChange p) {
    final sz = Theme.of(context).sz;
    final reason = p.state == 'rejected'
        ? reasonText(p.rejectLabel, p.rejectNote, p.rejectCode)
        : (p.state == 'failed' ? p.failReason : '');
    return Container(
      margin: const EdgeInsets.fromLTRB(kPagePad, 12, kPagePad, 0),
      padding: const EdgeInsets.all(kCardPad),
      decoration: BoxDecoration(color: sz.surface, borderRadius: BorderRadius.circular(kRadiusMd), border: Border.all(color: sz.line)),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text('这次改动:${p.stateLabel.isEmpty ? p.state : p.stateLabel}',
            style: TextStyle(fontSize: kFontBody, fontWeight: FontWeight.w600, color: sz.ink)),
        const SizedBox(height: 4),
        Text('线上仍是改之前那一版,改动审核通过后才换上去。', style: TextStyle(fontSize: kFontNote, color: sz.inkMuted)),
        if (pendingSummary(p).isNotEmpty)
          Padding(
            padding: const EdgeInsets.only(top: 4),
            child: Text(pendingSummary(p), style: TextStyle(fontSize: kFontNote, color: sz.inkMuted)),
          ),
        if (p.submittedAt != null && p.state != 'editing')
          Padding(
            padding: const EdgeInsets.only(top: 4),
            child: Text('提交于 ${vDateTime(p.submittedAt!)}', style: TextStyle(fontSize: kFontNote, color: sz.inkMuted)),
          ),
        if (reason.isNotEmpty)
          Padding(
            padding: const EdgeInsets.only(top: 4),
            child: Text(reason, style: TextStyle(fontSize: kFontNote, color: sz.danger)),
          ),
        if (p.state != 'reviewing')
          Row(mainAxisAlignment: MainAxisAlignment.end, children: [
            TextButton(onPressed: _discard, child: const Text('放弃改动')),
            if (!p.busy) TextButton(onPressed: _edit, child: const Text('接着改')),
          ]),
      ]),
    );
  }

  Widget _statsSection(CreatorVideo v) {
    final sz = Theme.of(context).sz;
    final s = _stats;
    if (v.card.publishedAt == null) {
      // 没发布过的稿件别人看不到,七个 0 加一条贴底的线没有信息量
      return Padding(
        padding: const EdgeInsets.symmetric(horizontal: kPagePad),
        child: Text('发布之后这里会有播放、点赞、硬币这些数据', style: TextStyle(fontSize: kFontNote, color: sz.inkMuted)),
      );
    }
    if (s == null) {
      return Padding(
        padding: const EdgeInsets.symmetric(horizontal: kPagePad),
        child: Text('数据暂时没拉到,下拉刷新再试', style: TextStyle(fontSize: kFontNote, color: sz.inkMuted)),
      );
    }
    final totals = vMap(s['totals']);
    final days = [for (final d in vList(s['days'])) vMap(d)];
    final label = statMetrics.firstWhere((m) => m.$1 == _metric).$2;
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: kPagePad),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Container(
          padding: const EdgeInsets.symmetric(vertical: 10),
          decoration: BoxDecoration(color: sz.surface, borderRadius: BorderRadius.circular(kRadiusMd), border: Border.all(color: sz.line)),
          // 七项排成 4 + 3 两行:一行塞 7 个的话窄屏上「1.2万」要被挤成两行
          child: LayoutBuilder(builder: (context, box) {
            final w = box.maxWidth / 4;
            return Wrap(children: [
              for (final (key, name) in statMetrics)
                SizedBox(
                  width: w,
                  child: _cell(vCount(vInt(totals[key])), name,
                      selected: key == _metric, onTap: () => setState(() => _metric = key)),
                ),
            ]);
          }),
        ),
        const SizedBox(height: 12),
        Text('近 30 天每天新增的$label(北京日期);点上面的数换一项看', style: TextStyle(fontSize: kFontMicro, color: sz.inkMuted)),
        const SizedBox(height: 8),
        StatsLineChart(
          days: [for (final d in days) '${d['day']}'],
          values: [for (final d in days) vInt(d[_metric])],
          label: label,
        ),
      ]),
    );
  }

  Widget _cell(String value, String label, {bool selected = false, VoidCallback? onTap}) {
    final sz = Theme.of(context).sz;
    return InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(kRadiusSm),
      child: Padding(
        padding: const EdgeInsets.symmetric(vertical: 6),
        child: Column(children: [
          Text(value, style: szFigure(fontSize: kFontTitle, fontWeight: FontWeight.w600, color: selected ? sz.clay : sz.ink)),
          const SizedBox(height: 2),
          Text(label, style: TextStyle(fontSize: kFontMicro, color: selected ? sz.clay : sz.inkMuted)),
        ]),
      ),
    );
  }

  Widget _partTile(CreatorVideo v, int i, VideoPart p) {
    final sz = Theme.of(context).sz;
    final inNext = v.versionPartIds.contains(p.id);
    final (String status, Color color) = switch (p.status) {
      'processing' => ('转码中…', sz.hold),
      'failed' => ('转码失败:${p.error.isEmpty ? '原因未知' : p.error}', sz.danger),
      _ => ('${vDuration(p.durationMs)} · ${p.w}×${p.h}', sz.inkMuted),
    };
    final where = !v.isLive
        ? ''
        : p.live
            ? (inNext ? ' · 线上' : ' · 线上(改动里删掉了,过审后下线)')
            : ' · 新加的,过审后上线';
    return ListTile(
      dense: true,
      leading: CircleAvatar(
        radius: 14,
        backgroundColor: sz.surfaceAlt,
        child: Text('P${i + 1}', style: TextStyle(fontSize: kFontMicro, color: sz.ink)),
      ),
      title: Text(p.title.isEmpty ? '未命名' : p.title, maxLines: 1, overflow: TextOverflow.ellipsis),
      subtitle: Text('$status$where', style: TextStyle(fontSize: kFontNote, color: color)),
    );
  }

  List<Widget> _decisions(CreatorVideo v) {
    final sz = Theme.of(context).sz;
    final list = v.decisions.reversed.toList();
    if (list.isEmpty) {
      return [
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: kPagePad),
          child: Text('还没有审核记录。所有投稿先审后发,结果也会在「互动消息 → 系统通知」里告诉你。',
              style: TextStyle(fontSize: kFontNote, color: sz.inkMuted, height: 1.5)),
        ),
      ];
    }
    return [
      for (final d in list)
        Padding(
          padding: const EdgeInsets.fromLTRB(kPagePad, 0, kPagePad, 12),
          child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Padding(
              padding: const EdgeInsets.only(top: 5),
              child: Icon(Icons.circle, size: 8, color: d.negative ? sz.danger : (d.action == 'appeal' ? sz.hold : sz.earn)),
            ),
            const SizedBox(width: 10),
            Expanded(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Row(children: [
                  Expanded(
                    child: Text(d.actionLabel.isEmpty ? d.action : d.actionLabel,
                        style: TextStyle(fontSize: kFontBody, fontWeight: FontWeight.w600, color: sz.ink)),
                  ),
                  if (d.createdAt != null)
                    Text(vDateTime(d.createdAt!), style: TextStyle(fontSize: kFontMicro, color: sz.inkMuted)),
                ]),
                if (d.reasonCode.isNotEmpty || d.reasonLabel.isNotEmpty)
                  Text('${d.reasonCode} ${d.reasonLabel}'.trim(), style: TextStyle(fontSize: kFontNote, color: sz.inkMuted)),
                if (d.note.isNotEmpty) Text(d.note, style: TextStyle(fontSize: kFontNote, color: sz.inkMuted, height: 1.5)),
                if (d.action == 'appeal')
                  Text(d.appealState == 'resolved' ? '申诉已处理' : '申诉处理中(另一名审核员复核)',
                      style: TextStyle(fontSize: kFontNote, color: sz.hold)),
                if (v.appealTarget?.id == d.id) Text('可以申诉', style: TextStyle(fontSize: kFontNote, color: sz.clay)),
              ]),
            ),
          ]),
        ),
    ];
  }
}
