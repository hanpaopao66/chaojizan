import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:superz_shared/superz_shared.dart';

import '../../session.dart';
import '../models.dart';
import '../player/player_logic.dart';
import '../player/sz_video_controller.dart';
import 'danmaku_controller.dart';
import 'engine.dart';
import 'settings.dart';

void _toast(BuildContext context, String s) =>
    ScaffoldMessenger.maybeOf(context)?.showSnackBar(SnackBar(content: Text(s), duration: const Duration(seconds: 2)));

/// 弹幕里不许有的「换行类」字符(和服务端 video_talk._LINE_BREAKS 同一组):弹幕只能一行
final RegExp _lineBreaks = RegExp('[\r\n\t  ]');

/// 弹幕最多 100 字。按码点数(和服务端的 Python len 一致),一个表情算一个字
const int kDanmakuMaxChars = 100;

Color _rgb(int c) => Color(0xFF000000 | (c & 0xFFFFFF));

// ---------------------------------------------------------------- 发送

/// 发弹幕的面板:文字(≤ 100 字单行)、颜色、模式(滚动 / 顶部 / 底部)、字号(小 18 / 标准 25)。
/// 发出去的那条立即上屏、带边框;失败把接口的 detail 显示在面板里,已经打的字留着。
/// UP 主关了弹幕时不弹面板,提示一句。
Future<void> showDanmakuSender(BuildContext context, SzVideoController c) async {
  if (!c.danmaku.allowDanmaku) {
    _toast(context, 'UP 主关闭了弹幕');
    return;
  }
  if (!await ensureLoggedIn(context)) return;
  if (!context.mounted) return;
  await szShowSheet<void>(context: context, builder: (_) => _SenderSheet(controller: c));
}

/// 上次发弹幕选的样式,这次打开面板接着用(只在本次打开 App 期间记着)
int _lastColor = kDanmakuWhite;
int _lastMode = Danmaku.scroll;
int _lastSize = DanmakuEngine.standardSize;

class _SenderSheet extends StatefulWidget {
  const _SenderSheet({required this.controller});

  final SzVideoController controller;

  @override
  State<_SenderSheet> createState() => _SenderSheetState();
}

class _SenderSheetState extends State<_SenderSheet> {
  final _text = TextEditingController();
  int _color = _lastColor;
  int _mode = _lastMode;
  int _size = _lastSize;
  bool _sending = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    _text.addListener(() => setState(() {}));
  }

  @override
  void dispose() {
    _text.dispose();
    super.dispose();
  }

  Future<void> _send() async {
    final t = _text.text.replaceAll(_lineBreaks, ' ').trim();
    if (t.isEmpty || _sending) return;
    if (t.runes.length > kDanmakuMaxChars) {
      setState(() => _error = '弹幕最多 $kDanmakuMaxChars 字');
      return;
    }
    final c = widget.controller;
    // 上限按服务端记的这一 P 时长(转码时量的),不按播放器量的:两边能差出几十毫秒,
    // 播完停在最后一帧时发弹幕,按播放器的算会比服务端的长,被当成「超出视频长度」拒掉
    final dur = c.part.durationMs > 0 ? c.part.durationMs : c.duration.inMilliseconds;
    var at = c.position.inMilliseconds;
    if (dur > 0 && at > dur) at = dur;
    setState(() => (_sending = true, _error = null));
    try {
      await c.danmaku.send(timeMs: at < 0 ? 0 : at, text: t, mode: _mode, color: _color, size: _size);
      _lastColor = _color;
      _lastMode = _mode;
      _lastSize = _size;
      if (mounted) Navigator.of(context).pop();
    } on ApiException catch (e) {
      if (mounted) setState(() => (_sending = false, _error = e.message));
    } catch (_) {
      if (mounted) setState(() => (_sending = false, _error = '没发出去,稍后再试'));
    }
  }

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    final empty = _text.text.trim().isEmpty;
    return Padding(
      padding: EdgeInsets.fromLTRB(kPagePad, 4, kPagePad, kPagePad + MediaQuery.viewInsetsOf(context).bottom),
      child: SingleChildScrollView(
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisSize: MainAxisSize.min, children: [
          Row(children: [
            Expanded(
              child: TextField(
                controller: _text,
                autofocus: true,
                maxLines: 1,
                maxLength: kDanmakuMaxChars,
                textInputAction: TextInputAction.send,
                inputFormatters: [FilteringTextInputFormatter.deny(_lineBreaks, replacementString: ' ')],
                onSubmitted: (_) => _send(),
                decoration: const InputDecoration(hintText: '发个友善的弹幕见证当下', counterText: ''),
              ),
            ),
            const SizedBox(width: 8),
            FilledButton(
              onPressed: empty || _sending ? null : _send,
              child: Text(_sending ? '发送中' : '发送'),
            ),
          ]),
          if (_error != null)
            Padding(
              padding: const EdgeInsets.only(top: 6),
              child: Text(_error!, style: TextStyle(color: sz.danger, fontSize: kFontNote)),
            ),
          const SizedBox(height: 12),
          Text('颜色', style: TextStyle(fontSize: kFontNote, color: sz.inkMuted)),
          const SizedBox(height: 6),
          Wrap(spacing: 10, runSpacing: 8, children: [
            for (final col in kDanmakuColors)
              Semantics(
                button: true,
                selected: col == _color,
                label: col == kDanmakuWhite ? '白色' : '颜色',
                child: GestureDetector(
                  onTap: () => setState(() => _color = col),
                  child: Container(
                    width: 28,
                    height: 28,
                    decoration: BoxDecoration(
                      color: _rgb(col),
                      shape: BoxShape.circle,
                      border: Border.all(
                        color: col == _color ? sz.clay : sz.line,
                        width: col == _color ? 3 : 1,
                      ),
                    ),
                  ),
                ),
              ),
          ]),
          const SizedBox(height: 12),
          Text('模式', style: TextStyle(fontSize: kFontNote, color: sz.inkMuted)),
          const SizedBox(height: 4),
          Wrap(spacing: 8, children: [
            for (final (m, label) in const [(Danmaku.scroll, '滚动'), (Danmaku.top, '顶部'), (Danmaku.bottom, '底部')])
              ChoiceChip(label: Text(label), selected: _mode == m, onSelected: (_) => setState(() => _mode = m)),
          ]),
          const SizedBox(height: 8),
          Text('字号', style: TextStyle(fontSize: kFontNote, color: sz.inkMuted)),
          const SizedBox(height: 4),
          Wrap(spacing: 8, children: [
            for (final (s, label) in const [(18, '小'), (25, '标准')])
              ChoiceChip(label: Text(label), selected: _size == s, onSelected: (_) => setState(() => _size = s)),
          ]),
        ]),
      ),
    );
  }
}

/// 详情页播放器下面那一条:弹幕开关、「点我发弹幕」、弹幕设置。UP 主关了弹幕时显示「UP 主关闭了弹幕」,点了没反应。
class DanmakuSendBar extends StatelessWidget {
  const DanmakuSendBar({super.key, required this.controller});

  final SzVideoController controller;

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    return ListenableBuilder(
      listenable: controller.danmaku,
      builder: (context, _) {
        final d = controller.danmaku;
        final allow = d.allowDanmaku;
        final on = d.settings.enabled;
        return Padding(
          padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 6),
          child: Row(children: [
            IconButton(
              tooltip: on ? '关闭弹幕' : '打开弹幕',
              onPressed: allow ? () => d.setEnabled(!on) : null,
              icon: Icon(allow && on ? Icons.subtitles_outlined : Icons.subtitles_off_outlined,
                  color: allow && on ? sz.clay : sz.inkMuted),
            ),
            Expanded(
              child: Material(
                color: sz.surfaceAlt,
                borderRadius: BorderRadius.circular(18),
                child: InkWell(
                  borderRadius: BorderRadius.circular(18),
                  onTap: allow ? () => showDanmakuSender(context, controller) : null,
                  child: Container(
                    height: 36,
                    alignment: Alignment.centerLeft,
                    padding: const EdgeInsets.symmetric(horizontal: 14),
                    child: Text(
                      allow ? (on ? '点我发弹幕' : '弹幕已关闭,点我发弹幕') : 'UP 主关闭了弹幕',
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: TextStyle(fontSize: kFontBody, color: sz.inkMuted),
                    ),
                  ),
                ),
              ),
            ),
            IconButton(
              tooltip: '弹幕设置',
              onPressed: allow ? () => showDanmakuSettings(context, d) : null,
              icon: Icon(Icons.tune, color: sz.inkMuted),
            ),
          ]),
        );
      },
    );
  }
}

// ---------------------------------------------------------------- 设置

/// 弹幕设置:开关、不透明度 20–100%、字号 50–150%、速度 0.5–2、显示区域、屏蔽类型、屏蔽词、屏蔽的人。
/// 改了立刻生效(弹幕层听着同一份设置),存 SharedPreferences,全 App 通用。
Future<void> showDanmakuSettings(BuildContext context, DanmakuController d) =>
    szShowSheet<void>(context: context, builder: (_) => _SettingsSheet(controller: d));

class _SettingsSheet extends StatefulWidget {
  const _SettingsSheet({required this.controller});

  final DanmakuController controller;

  @override
  State<_SettingsSheet> createState() => _SettingsSheetState();
}

class _SettingsSheetState extends State<_SettingsSheet> {
  final _word = TextEditingController();

  DanmakuController get d => widget.controller;

  @override
  void dispose() {
    _word.dispose();
    super.dispose();
  }

  Future<void> _addWord() async {
    final w = _word.text.trim();
    if (w.isEmpty) return;
    final ok = await d.addBlockWord(w);
    if (!mounted) return;
    if (ok) {
      _word.clear();
    } else {
      _toast(context, d.settings.blockWords.length >= DanmakuSettings.maxBlockWords
          ? '屏蔽词最多 ${DanmakuSettings.maxBlockWords} 个'
          : '已经有这个屏蔽词了');
    }
  }

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    return ListenableBuilder(
      listenable: d,
      builder: (context, _) {
        final s = d.settings;
        Widget label(String t) => Padding(
              padding: const EdgeInsets.fromLTRB(kPagePad, 14, kPagePad, 4),
              child: Text(t, style: TextStyle(fontSize: kFontNote, color: sz.inkMuted)),
            );
        Widget slider(String title, String value, double v, double lo, double hi, int divisions,
                DanmakuSettings Function(double) apply) =>
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: kPagePad - 8),
              child: Row(children: [
                SizedBox(width: 64, child: Padding(
                  padding: const EdgeInsets.only(left: 8),
                  child: Text(title, style: const TextStyle(fontSize: kFontBody)),
                )),
                Expanded(
                  child: Slider(
                    value: v.clamp(lo, hi),
                    min: lo,
                    max: hi,
                    divisions: divisions,
                    onChanged: s.enabled ? (x) => d.updateSettings(apply(x), persist: false) : null,
                    onChangeEnd: (x) => d.updateSettings(apply(x)),
                  ),
                ),
                SizedBox(
                  width: 48,
                  child: Text(value, textAlign: TextAlign.end, style: TextStyle(fontSize: kFontNote, color: sz.inkMuted)),
                ),
              ]),
            );
        return Padding(
          padding: EdgeInsets.only(bottom: MediaQuery.viewInsetsOf(context).bottom),
          child: SzSheetScrollable(
            initialSize: 0.75,
            builder: (context, sc) => ListView(
              controller: sc,
              shrinkWrap: sc == null,
              padding: const EdgeInsets.only(bottom: kPagePad),
              children: [
                SwitchListTile(
                  title: const Text('显示弹幕'),
                  subtitle: d.allowDanmaku ? null : const Text('UP 主关闭了这个视频的弹幕'),
                  value: s.enabled,
                  onChanged: (v) => d.setEnabled(v),
                ),
                slider('不透明度', '${(s.opacity * 100).round()}%', s.opacity, DanmakuSettings.minOpacity, 1, 16,
                    (x) => s.copyWith(opacity: x)),
                slider('字号', '${(s.fontScale * 100).round()}%', s.fontScale, DanmakuSettings.minFontScale,
                    DanmakuSettings.maxFontScale, 10, (x) => s.copyWith(fontScale: x)),
                slider('速度', '${s.speed.toStringAsFixed(2).replaceFirst(RegExp(r'0$'), '')}x', s.speed,
                    DanmakuSettings.minSpeed, DanmakuSettings.maxSpeed, 6, (x) => s.copyWith(speed: x)),
                label('显示区域'),
                Padding(
                  padding: const EdgeInsets.symmetric(horizontal: kPagePad),
                  child: Wrap(spacing: 8, children: [
                    for (final a in kDanmakuAreas)
                      ChoiceChip(
                        label: Text(danmakuAreaLabel(a)),
                        selected: s.area == a,
                        onSelected: (_) => d.updateSettings(s.copyWith(area: a)),
                      ),
                  ]),
                ),
                label('屏蔽类型'),
                Padding(
                  padding: const EdgeInsets.symmetric(horizontal: kPagePad),
                  child: Wrap(spacing: 8, runSpacing: 4, children: [
                    FilterChip(
                      label: const Text('顶部'),
                      selected: s.blockTop,
                      onSelected: (v) => d.updateSettings(s.copyWith(blockTop: v)),
                    ),
                    FilterChip(
                      label: const Text('底部'),
                      selected: s.blockBottom,
                      onSelected: (v) => d.updateSettings(s.copyWith(blockBottom: v)),
                    ),
                    FilterChip(
                      label: const Text('滚动'),
                      selected: s.blockScroll,
                      onSelected: (v) => d.updateSettings(s.copyWith(blockScroll: v)),
                    ),
                    FilterChip(
                      label: const Text('彩色'),
                      selected: s.blockColored,
                      onSelected: (v) => d.updateSettings(s.copyWith(blockColored: v)),
                    ),
                  ]),
                ),
                label('屏蔽词(包含就不显示,不分大小写)'),
                Padding(
                  padding: const EdgeInsets.symmetric(horizontal: kPagePad),
                  child: Row(children: [
                    Expanded(
                      child: TextField(
                        controller: _word,
                        maxLength: 20,
                        decoration: const InputDecoration(hintText: '输入要屏蔽的词', counterText: ''),
                        onSubmitted: (_) => _addWord(),
                      ),
                    ),
                    const SizedBox(width: 8),
                    OutlinedButton(onPressed: _addWord, child: const Text('添加')),
                  ]),
                ),
                if (s.blockWords.isNotEmpty)
                  Padding(
                    padding: const EdgeInsets.fromLTRB(kPagePad, 8, kPagePad, 0),
                    child: Wrap(spacing: 6, runSpacing: 4, children: [
                      for (final w in s.blockWords)
                        InputChip(label: Text(w), onDeleted: () => d.removeBlockWord(w)),
                    ]),
                  ),
                label('屏蔽的人(${s.blockUsers.length})'),
                if (s.blockUsers.isEmpty)
                  Padding(
                    padding: const EdgeInsets.symmetric(horizontal: kPagePad),
                    child: Text('点一条弹幕,选「屏蔽此人」,TA 的弹幕就不会再出现',
                        style: TextStyle(fontSize: kFontNote, color: sz.inkMuted)),
                  )
                else
                  for (final h in s.blockUsers.reversed)
                    ListTile(
                      dense: true,
                      title: Text('弹幕用户 $h', style: const TextStyle(fontSize: kFontBody)),
                      trailing: TextButton(onPressed: () => d.unblockUser(h), child: const Text('解除')),
                    ),
                const SizedBox(height: 8),
                Center(
                  child: TextButton(
                    // 只恢复显示相关的几项;屏蔽词和屏蔽的人是用户一条条攒的,不跟着清
                    onPressed: () => d.updateSettings(const DanmakuSettings()
                        .copyWith(blockWords: s.blockWords, blockUsers: s.blockUsers)),
                    child: const Text('恢复默认'),
                  ),
                ),
              ],
            ),
          ),
        );
      },
    );
  }
}

// ---------------------------------------------------------------- 点一条弹幕

/// 举报弹幕能选的原因(VIDEO-API 0.8 的 C 类;V 类是视频专属的不给弹幕用)。X999 要写说明。
const List<(String, String)> kDanmakuReportReasons = [
  ('C101', '骚扰、辱骂'),
  ('C102', '垃圾广告、引流'),
  ('C103', '诈骗'),
  ('C104', '色情、低俗'),
  ('C105', '暴力、血腥'),
  ('C106', '违法违规'),
  ('C107', '侵犯隐私'),
  ('C108', '冒充他人或官方'),
  ('C109', '未成年人不宜'),
  ('X999', '其他'),
];

/// 点了一条弹幕:复制 / 屏蔽此人 / 举报;自己发的(或者我是 UP 主)还能删。
Future<void> showDanmakuActions(BuildContext context, SzVideoController c, Danmaku item) async {
  final d = c.danmaku;
  final pick = await szShowSheet<String>(
    context: context,
    builder: (ctx) {
      final sz = Theme.of(ctx).sz;
      return SafeArea(
        child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(kPagePad, 4, kPagePad, 8),
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(item.text, maxLines: 3, overflow: TextOverflow.ellipsis,
                  style: const TextStyle(fontSize: kFontBodyLg, fontWeight: FontWeight.w600)),
              const SizedBox(height: 2),
              Text('${playerClock(item.timeMs)}${item.mine ? ' · 我发的' : ''}',
                  style: TextStyle(fontSize: kFontNote, color: sz.inkMuted)),
            ]),
          ),
          ListTile(leading: const Icon(Icons.copy_outlined), title: const Text('复制'), onTap: () => Navigator.pop(ctx, 'copy')),
          if (!item.mine && item.userHash.isNotEmpty)
            ListTile(
              leading: const Icon(Icons.person_off_outlined),
              title: const Text('屏蔽此人'),
              subtitle: const Text('TA 在所有视频里的弹幕都不再显示,可以在弹幕设置里解除'),
              onTap: () => Navigator.pop(ctx, 'block'),
            ),
          if (!item.mine)
            ListTile(leading: const Icon(Icons.flag_outlined), title: const Text('举报'), onTap: () => Navigator.pop(ctx, 'report')),
          if (d.canDelete(item))
            ListTile(
              leading: Icon(Icons.delete_outline, color: sz.danger),
              title: Text('删除', style: TextStyle(color: sz.danger)),
              onTap: () => Navigator.pop(ctx, 'delete'),
            ),
        ]),
      );
    },
  );
  if (!context.mounted || pick == null) return;
  switch (pick) {
    case 'copy':
      await Clipboard.setData(ClipboardData(text: item.text));
      if (context.mounted) _toast(context, '已复制');
    case 'block':
      await d.blockUser(item.userHash);
      if (context.mounted) _toast(context, '已屏蔽,TA 的弹幕不会再出现');
    case 'report':
      if (!await ensureLoggedIn(context) || !context.mounted) return;
      await szShowSheet<void>(context: context, builder: (_) => _ReportSheet(controller: d, item: item));
    case 'delete':
      try {
        await d.delete(item);
        if (context.mounted) _toast(context, '已删除');
      } on ApiException catch (e) {
        if (context.mounted) _toast(context, e.message);
      }
  }
}

class _ReportSheet extends StatefulWidget {
  const _ReportSheet({required this.controller, required this.item});

  final DanmakuController controller;
  final Danmaku item;

  @override
  State<_ReportSheet> createState() => _ReportSheetState();
}

class _ReportSheetState extends State<_ReportSheet> {
  String? _reason;
  final _note = TextEditingController();
  bool _sending = false;
  String? _error;

  @override
  void dispose() {
    _note.dispose();
    super.dispose();
  }

  Future<void> _send() async {
    final code = _reason;
    if (code == null) return;
    final note = _note.text.trim();
    if (code == 'X999' && note.runes.length < 5) {
      setState(() => _error = '选了「其他」要写明是什么情况(至少 5 个字)');
      return;
    }
    setState(() => (_sending = true, _error = null));
    try {
      await widget.controller.report(widget.item, code, note: note);
      if (!mounted) return;
      final messenger = ScaffoldMessenger.maybeOf(context);
      Navigator.of(context).pop();
      messenger?.showSnackBar(const SnackBar(content: Text('已收到举报,会尽快处理;对方不会知道是谁举报的')));
    } on ApiException catch (e) {
      if (mounted) setState(() => (_sending = false, _error = e.message));
    } catch (_) {
      if (mounted) setState(() => (_sending = false, _error = '没提交上,稍后再试'));
    }
  }

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    return Padding(
      padding: EdgeInsets.fromLTRB(kPagePad, 4, kPagePad, kPagePad + MediaQuery.viewInsetsOf(context).bottom),
      child: SingleChildScrollView(
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisSize: MainAxisSize.min, children: [
          Text('举报弹幕', style: TextStyle(fontSize: kFontTitle, fontWeight: FontWeight.w600, color: sz.ink)),
          const SizedBox(height: 4),
          Text('「${widget.item.text}」', maxLines: 2, overflow: TextOverflow.ellipsis,
              style: TextStyle(fontSize: kFontNote, color: sz.inkMuted)),
          const SizedBox(height: 10),
          Wrap(spacing: 8, runSpacing: 4, children: [
            for (final (code, label) in kDanmakuReportReasons)
              ChoiceChip(label: Text(label), selected: _reason == code, onSelected: (_) => setState(() => _reason = code)),
          ]),
          const SizedBox(height: 10),
          TextField(
            controller: _note,
            maxLength: 200,
            maxLines: 2,
            decoration: InputDecoration(hintText: _reason == 'X999' ? '选了「其他」,请写明是什么情况' : '补充说明(可选)'),
          ),
          if (_error != null) Text(_error!, style: TextStyle(color: sz.danger, fontSize: kFontNote)),
          const SizedBox(height: 6),
          SizedBox(
            width: double.infinity,
            child: FilledButton(
              onPressed: _reason == null || _sending ? null : _send,
              child: Text(_sending ? '提交中…' : '提交举报'),
            ),
          ),
        ]),
      ),
    );
  }
}
