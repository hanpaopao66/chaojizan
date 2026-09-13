import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';

import '../store.dart';

/// 处罚与申诉(S6):平台对我(或我当群主的群)的处罚,原因、到期时间、申诉进度;每个处罚能申诉一次,
/// 由另一名管理员复核。封号期间也打得开这一页(服务端单独放行)。
class SanctionsPage extends StatefulWidget {
  const SanctionsPage({super.key, this.focusId});

  /// 从「你被禁言了」的提示点进来时,那一条放最前、直接展开申诉
  final int? focusId;

  @override
  State<SanctionsPage> createState() => _SanctionsPageState();
}

class _SanctionsPageState extends State<SanctionsPage> {
  final _store = ChatStore.instance;
  List<Map<String, dynamic>> _active = [];
  List<Map<String, dynamic>> _history = [];
  bool _loading = true;
  Object? _error;
  bool _autoOpened = false;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final r = await _store.api.mySanctions();
      if (!mounted) return;
      List<Map<String, dynamic>> list(Object? v) => [for (final x in (v as List? ?? const [])) (x as Map).cast()];
      setState(() {
        _active = list(r['active']);
        _history = list(r['history']);
        _loading = false;
        _error = null;
      });
      final f = widget.focusId;
      if (f != null && !_autoOpened) {
        _autoOpened = true;
        final s = [..._active, ..._history].where((x) => x['id'] == f).firstOrNull;
        if (s != null && s['can_appeal'] == true) WidgetsBinding.instance.addPostFrameCallback((_) => _appeal(s));
      }
    } catch (e) {
      if (mounted) {
        setState(() {
          _loading = false;
          _error = e;
        });
      }
    }
  }

  Future<void> _appeal(Map<String, dynamic> s) async {
    final text = TextEditingController();
    final ok = await szShowSheet<bool>(
      context: context,
      builder: (ctx) => Padding(
        padding: EdgeInsets.fromLTRB(kPagePad, 12, kPagePad, 12 + MediaQuery.viewInsetsOf(ctx).bottom),
        child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text('申诉「${s['action_label'] ?? ''}」', style: const TextStyle(fontSize: kFontTitle, fontWeight: FontWeight.w600)),
          const SizedBox(height: 6),
          Text('会由另一名管理员复核,结果在「互动消息 → 系统通知」里告诉你。每个处罚只能申诉一次。',
              style: TextStyle(fontSize: kFontNote, color: Theme.of(ctx).sz.inkMuted)),
          const SizedBox(height: 10),
          TextField(
            controller: text,
            maxLength: 500,
            minLines: 3,
            maxLines: 6,
            autofocus: true,
            decoration: const InputDecoration(hintText: '说说为什么觉得处理得不对(至少 5 个字)', border: OutlineInputBorder()),
          ),
          const SizedBox(height: 8),
          SizedBox(
            width: double.infinity,
            child: FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('提交申诉')),
          ),
        ]),
      ),
    );
    if (ok != true || !mounted) return;
    try {
      await _store.api.appealSanction((s['id'] as num).toInt(), text.text.trim());
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('申诉已提交')));
      await _load();
    } on ApiException catch (e) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(e.message)));
    }
  }

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    return SzPageScaffold(
      appBar: AppBar(title: const Text('处罚与申诉')),
      body: _loading
          ? const Center(child: CircularProgressIndicator())
          : _error != null
              ? Center(child: SzError(error: _error, onRetry: _load))
              : (_active.isEmpty && _history.isEmpty)
                  ? const Center(child: SzEmpty(text: '没有处罚记录'))
                  : ListView(padding: const EdgeInsets.all(kPagePad), children: [
                      if (_active.isNotEmpty) ...[
                        Text('生效中', style: TextStyle(fontWeight: FontWeight.w600, color: sz.danger)),
                        const SizedBox(height: 8),
                        for (final s in _active) _card(s, sz),
                      ],
                      if (_history.isNotEmpty) ...[
                        const SizedBox(height: 12),
                        Text('历史', style: TextStyle(fontWeight: FontWeight.w600, color: sz.inkMuted)),
                        const SizedBox(height: 8),
                        for (final s in _history) _card(s, sz),
                      ],
                      const SizedBox(height: 12),
                      Text('每条处罚都带原因代码和说明;处置记录(不含个人信息)在透明中心「社区」栏公示。',
                          style: TextStyle(fontSize: kFontNote, color: sz.inkFaint)),
                    ]),
    );
  }

  Widget _card(Map<String, dynamic> s, SzColors sz) {
    final appeal = (s['appeal'] as Map?)?.cast<String, dynamic>() ?? const {};
    final chatId = (s['chat_id'] as num?)?.toInt();
    final chatTitle = chatId == null ? null : _store.chats[chatId]?.title;
    final until = DateTime.tryParse('${s['until'] ?? ''}')?.toLocal();
    final focus = widget.focusId != null && s['id'] == widget.focusId;
    return Container(
      margin: const EdgeInsets.only(bottom: 10),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: sz.surface,
        borderRadius: BorderRadius.circular(kRadiusMd),
        border: Border.all(color: focus ? sz.clay : sz.line),
      ),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          Text('${s['action_label'] ?? ''}', style: const TextStyle(fontWeight: FontWeight.w600)),
          const SizedBox(width: 8),
          if ('${s['duration'] ?? ''}'.isNotEmpty)
            Text('${s['duration']}', style: TextStyle(fontSize: kFontNote, color: sz.inkMuted)),
          const Spacer(),
          Text('${s['status_label'] ?? ''}', style: TextStyle(fontSize: kFontNote, color: s['status'] == 'active' ? sz.danger : sz.inkMuted)),
        ]),
        const SizedBox(height: 6),
        Text('原因:${s['reason_code'] ?? ''} ${s['reason_label'] ?? ''}'),
        if ('${s['note'] ?? ''}'.isNotEmpty)
          Padding(padding: const EdgeInsets.only(top: 4), child: Text('说明:${s['note']}', style: TextStyle(color: sz.inkMuted))),
        if (chatTitle != null && chatTitle.isNotEmpty)
          Padding(padding: const EdgeInsets.only(top: 4), child: Text('会话:$chatTitle', style: TextStyle(fontSize: kFontNote, color: sz.inkMuted))),
        if (s['permanent'] == true)
          Padding(padding: const EdgeInsets.only(top: 4), child: Text('永久', style: TextStyle(fontSize: kFontNote, color: sz.danger)))
        else if (until != null)
          Padding(
            padding: const EdgeInsets.only(top: 4),
            child: Text('到 ${until.year}-${until.month.toString().padLeft(2, '0')}-${until.day.toString().padLeft(2, '0')} '
                '${until.hour.toString().padLeft(2, '0')}:${until.minute.toString().padLeft(2, '0')}',
                style: TextStyle(fontSize: kFontNote, color: sz.inkMuted)),
          ),
        if ('${appeal['status'] ?? ''}'.isNotEmpty) ...[
          const Divider(height: 18),
          Text('申诉:${appeal['status_label'] ?? ''}', style: const TextStyle(fontWeight: FontWeight.w600)),
          if ('${appeal['note'] ?? ''}'.isNotEmpty)
            Padding(padding: const EdgeInsets.only(top: 4), child: Text('复核意见:${appeal['note']}', style: TextStyle(color: sz.inkMuted))),
        ] else if (s['can_appeal'] == true)
          Align(
            alignment: Alignment.centerRight,
            child: TextButton(onPressed: () => _appeal(s), child: const Text('申诉')),
          ),
      ]),
    );
  }
}
