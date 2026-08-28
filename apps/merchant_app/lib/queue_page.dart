import 'dart:async';

import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';

/// 叫号台:每条队的队头、已叫号待到店的、以及四个动作。
///
/// ## 为什么长这样
///
/// 这是**干活页**,不是看板。用的人是迎宾,一手拿着号一手点屏幕,
/// 高峰期一分钟点十几次 —— 所以按钮要大、状态要一眼看清、
/// 点错的代价要小(过号不是作废,是顺延)。
///
/// ## 有一处是故意「不方便」的
///
/// 叫号后不到宽限期,「过号」按钮是灰的,还带着倒计时。这不是没做完 ——
/// 用户过号有代价(顺延、两次转待恢复),商家叫完就点过号也不能零成本,
/// 否则「过号」会变成一个随手清队列的按钮。规则和秒数由平台定,
/// 商家改不了,公示上也写着。
class QueuePage extends StatefulWidget {
  const QueuePage({super.key, required this.api});

  final ApiClient api;

  @override
  State<QueuePage> createState() => _QueuePageState();
}

class _QueuePageState extends State<QueuePage> {
  Map<String, dynamic>? _desk;
  Map<String, dynamic>? _settings;

  /// 非空 = 上一次加载失败。「今天还没人取号」和「没拉到」不能长得一样
  String _error = '';
  Timer? _tick;

  @override
  void initState() {
    super.initState();
    _load();
    // 每 10 秒刷一次:队列在变(有人取号、有人不等了),
    // 而迎宾不会想起来下拉。同时让「过号」的倒计时走起来
    _tick = Timer.periodic(const Duration(seconds: 10), (_) => _load());
  }

  @override
  void dispose() {
    _tick?.cancel();
    super.dispose();
  }

  Future<void> _load() async {
    try {
      final desk = await widget.api.queueDesk();
      final st = await widget.api.queueSettings();
      if (!mounted) return;
      setState(() {
        _desk = desk;
        _settings = st;
        _error = '';
      });
    } catch (e) {
      if (!mounted) return;
      setState(() => _error = '$e');
    }
  }

  Future<void> _act(String ticketNo, String action) async {
    try {
      final r = await widget.api.queueAction(ticketNo, action);
      if (!mounted) return;
      final note = r['result'] as String?;
      if (note != null) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text('$ticketNo:$note')));
      }
      await _load();
    } catch (e) {
      if (!mounted) return;
      // 宽限期内点过号会被服务端拒 —— 把那句话原样给出来,
      // 它已经写清了「再等几秒」
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('$e')));
    }
  }

  @override
  Widget build(BuildContext context) {
    final enabled = _settings?['enabled'] == true;
    return SzPageScaffold(
      appBar: AppBar(
        title: const Text('叫号台'),
        actions: [
          IconButton(
            tooltip: '排队设置',
            icon: const Icon(Icons.tune),
            onPressed: () => Navigator.of(context)
                .push(MaterialPageRoute<void>(
                    builder: (_) => QueueSettingsPage(api: widget.api)))
                .then((_) => _load()),
          ),
        ],
      ),
      body: RefreshIndicator(
        onRefresh: _load,
        child: _error.isNotEmpty
            ? _centered(_error, retry: true)
            : _desk == null
                ? const Center(child: CircularProgressIndicator())
                : !enabled
                    ? _centered('排队还没开。到「排队设置」里打开,'
                        '并至少配一个桌型。')
                    : _body(),
      ),
    );
  }

  Widget _centered(String text, {bool retry = false}) {
    final sz = Theme.of(context).sz;
    return ListView(children: [
      const SizedBox(height: 80),
      Padding(
        padding: const EdgeInsets.symmetric(horizontal: 32),
        child: Column(children: [
          Text(text,
              textAlign: TextAlign.center,
              style: TextStyle(fontSize: kFontBody, color: sz.inkMuted)),
          if (retry) ...[
            const SizedBox(height: 12),
            OutlinedButton(onPressed: _load, child: const Text('重试')),
          ],
        ]),
      ),
    ]);
  }

  Widget _body() {
    final queues =
        (_desk!['queues'] as List? ?? []).cast<Map<String, dynamic>>();
    if (queues.isEmpty) {
      return _centered('还没有可用的桌型。到「排队设置」里加一个 ——\n'
          '2人/4人/6人/包间各自排一条队,混在一起预估等待必然是错的。');
    }
    return ListView(
      padding: const EdgeInsets.fromLTRB(12, 12, 12, 32),
      children: [for (final q in queues) _queueBlock(q)],
    );
  }

  Widget _queueBlock(Map<String, dynamic> q) {
    final sz = Theme.of(context).sz;
    final tt = (q['table_type'] as Map).cast<String, dynamic>();
    final called = (q['called'] as List? ?? []).cast<Map<String, dynamic>>();
    final waiting = (q['waiting'] as List? ?? []).cast<Map<String, dynamic>>();

    return Card(
      margin: const EdgeInsets.only(bottom: 14),
      child: Padding(
        padding: const EdgeInsets.all(14),
        child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(children: [
                Text('${tt['name']}',
                    style: TextStyle(
                        fontSize: kFontTitle,
                        fontWeight: FontWeight.w700,
                        color: sz.ink)),
                const SizedBox(width: 8),
                Text('${tt['table_count']} 张桌 · 排队 ${waiting.length}',
                    style:
                        TextStyle(fontSize: kFontNote, color: sz.inkMuted)),
              ]),
              if (called.isNotEmpty) ...[
                const SizedBox(height: 12),
                Text('已叫号,等人到店',
                    style: TextStyle(
                        fontSize: kFontNote, color: sz.inkMuted)),
                const SizedBox(height: 6),
                for (final t in called) _calledRow(t),
              ],
              const SizedBox(height: 12),
              Text('排队中',
                  style:
                      TextStyle(fontSize: kFontNote, color: sz.inkMuted)),
              const SizedBox(height: 6),
              if (waiting.isEmpty)
                Padding(
                  padding: const EdgeInsets.symmetric(vertical: 8),
                  child: Text('这条队现在没人',
                      style: TextStyle(
                          fontSize: kFontNote, color: sz.inkFaint)),
                )
              else
                for (final t in waiting) _waitingRow(t, waiting.first == t),
            ]),
      ),
    );
  }

  /// 已叫号的一行:入座 / 过号 / 恢复
  Widget _calledRow(Map<String, dynamic> t) {
    final sz = Theme.of(context).sz;
    final no = '${t['ticket_no']}';
    final short = no.split('-').last;
    final pending = t['status'] == 'pending_restore';
    final canPass = t['can_pass'] == true;

    return Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: Row(children: [
        SizedBox(
          width: 64,
          child: Text(short,
              style: TextStyle(
                  fontSize: kFontBodyLg,
                  fontWeight: FontWeight.w800,
                  color: sz.ink)),
        ),
        Expanded(
          child: Text(
              pending
                  ? '两次没到,待恢复'
                  : '${t['party_size']} 位'
                      '${(t['passed_count'] as int? ?? 0) > 0 ? " · 已过号 ${t['passed_count']} 次" : ""}',
              style: TextStyle(fontSize: kFontNote, color: sz.inkMuted)),
        ),
        if (pending)
          TextButton(
              onPressed: () => _act(no, 'restore'), child: const Text('恢复'))
        else ...[
          TextButton(
            // 宽限期内是灰的。这是平台规则,不是没做完 ——
            // 见文件头的注释
            onPressed: canPass ? () => _act(no, 'pass') : null,
            child: Text(canPass ? '过号' : '过号(等一下)'),
          ),
          FilledButton(
              onPressed: () => _act(no, 'seat'), child: const Text('入座')),
        ],
      ]),
    );
  }

  /// 排队中的一行。只有队头那个给「叫号」主按钮 ——
  /// 每一行都给的话,高峰期很容易点到第三行,而队头那位就白等了。
  Widget _waitingRow(Map<String, dynamic> t, bool isHead) {
    final sz = Theme.of(context).sz;
    final no = '${t['ticket_no']}';
    return Padding(
      padding: const EdgeInsets.only(bottom: 6),
      child: Row(children: [
        SizedBox(
          width: 64,
          child: Text(no.split('-').last,
              style: TextStyle(
                  fontSize: kFontBody,
                  fontWeight: isHead ? FontWeight.w800 : FontWeight.w400,
                  color: isHead ? sz.ink : sz.inkMuted)),
        ),
        Expanded(
          child: Text('${t['party_size']} 位'
              '${(t['passed_count'] as int? ?? 0) > 0 ? " · 已过号 ${t['passed_count']} 次" : ""}',
              style: TextStyle(fontSize: kFontNote, color: sz.inkMuted)),
        ),
        if (isHead)
          FilledButton(
              onPressed: () => _act(no, 'call'), child: const Text('叫号')),
      ]),
    );
  }
}

/// 排队设置:桌型、放号上限、顺延桌数、提醒。
///
/// 页面上会**明写哪些是平台规则、商家改不了** —— 藏着不说的话,
/// 商家会以为是漏了功能,然后去找客服要一个「立即过号」的开关。
class QueueSettingsPage extends StatefulWidget {
  const QueueSettingsPage({super.key, required this.api});

  final ApiClient api;

  @override
  State<QueueSettingsPage> createState() => _QueueSettingsPageState();
}

class _QueueSettingsPageState extends State<QueueSettingsPage> {
  Map<String, dynamic>? _s;
  List<Map<String, dynamic>> _types = [];
  String _error = '';

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final s = await widget.api.queueSettings();
      final t = await widget.api.queueTableTypes();
      if (!mounted) return;
      setState(() {
        _s = s;
        _types = t;
        _error = '';
      });
    } catch (e) {
      if (!mounted) return;
      setState(() => _error = '$e');
    }
  }

  Future<void> _save(Map<String, dynamic> patch) async {
    try {
      final s = await widget.api.saveQueueSettings({
        'enabled': _s!['enabled'],
        'cap_multiplier': _s!['cap_multiplier'],
        'defer_tables': _s!['defer_tables'],
        'notify_ahead': _s!['notify_ahead'],
        ...patch,
      });
      if (!mounted) return;
      setState(() => _s = s);
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text('$e')));
    }
  }

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    return SzPageScaffold(
      appBar: AppBar(title: const Text('排队设置')),
      body: _s == null
          ? Center(
              child: _error.isEmpty
                  ? const CircularProgressIndicator()
                  : Text(_error))
          : ListView(
              padding: const EdgeInsets.fromLTRB(16, 12, 16, 32),
              children: [
                SwitchListTile(
                  contentPadding: EdgeInsets.zero,
                  title: const Text('开启到店排队'),
                  subtitle: const Text('开了之后店铺页会出现取号入口'),
                  value: _s!['enabled'] == true,
                  onChanged: (v) => _save({'enabled': v}),
                ),
                const Divider(height: 28),
                _numberRow('放号上限倍数', 'cap_multiplier', 1, 10,
                    '每档最多放「桌数 × 这个数」个号。不封顶的话队尾的人'
                    '等两小时也坐不上 —— 取了号比不让取更生气。'),
                _numberRow('过号顺延桌数', 'defer_tables', 1, 8,
                    '叫到号没来,往后排这么多桌,号还在。'),
                _numberRow('临近提醒', 'notify_ahead', 1, 10,
                    '前方还剩这么多桌时给客人推一条,让他往店里走。'),
                const Divider(height: 28),
                Text('桌型',
                    style: TextStyle(
                        fontSize: kFontTitle,
                        fontWeight: FontWeight.w700,
                        color: sz.ink)),
                const SizedBox(height: 4),
                Text('2人/4人/6人/包间各自排一条队。混成一条的话,'
                    '预估等待必然是错的 —— 而客人就是照着那个数字'
                    '决定要不要等。',
                    style: TextStyle(
                        fontSize: kFontNote, height: 1.5, color: sz.inkMuted)),
                const SizedBox(height: 10),
                for (final t in _types) _typeTile(t),
                const SizedBox(height: 8),
                OutlinedButton.icon(
                  onPressed: () => _editType(null),
                  icon: const Icon(Icons.add),
                  label: const Text('加一个桌型'),
                ),
                const Divider(height: 32),
                _platformRules(),
              ],
            ),
    );
  }

  Widget _numberRow(String label, String key, int lo, int hi, String note) {
    final sz = Theme.of(context).sz;
    final v = _s![key] as int? ?? lo;
    return Padding(
      padding: const EdgeInsets.only(bottom: 14),
      child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(children: [
              Expanded(
                  child: Text(label,
                      style: TextStyle(fontSize: kFontBody, color: sz.ink))),
              IconButton(
                  onPressed:
                      v > lo ? () => _save({key: v - 1}) : null,
                  icon: const Icon(Icons.remove_circle_outline)),
              SizedBox(
                width: 32,
                child: Text('$v',
                    textAlign: TextAlign.center,
                    style: TextStyle(
                        fontSize: kFontBodyLg,
                        fontWeight: FontWeight.w700,
                        color: sz.ink)),
              ),
              IconButton(
                  onPressed:
                      v < hi ? () => _save({key: v + 1}) : null,
                  icon: const Icon(Icons.add_circle_outline)),
            ]),
            Text(note,
                style: TextStyle(
                    fontSize: kFontNote, height: 1.5, color: sz.inkMuted)),
          ]),
    );
  }

  Widget _typeTile(Map<String, dynamic> t) {
    final sz = Theme.of(context).sz;
    final active = t['is_active'] == true;
    return ListTile(
      contentPadding: EdgeInsets.zero,
      title: Text('${t['name']}',
          style: TextStyle(color: active ? sz.ink : sz.inkFaint)),
      subtitle: Text('${t['seats_min']}-${t['seats_max']} 位 · '
          '${t['table_count']} 张桌 · 翻台 ${t['turn_minutes']} 分钟'
          '${active ? "" : " · 已停用"}'),
      trailing: IconButton(
          icon: const Icon(Icons.edit_outlined),
          onPressed: () => _editType(t)),
    );
  }

  Future<void> _editType(Map<String, dynamic>? t) async {
    final saved = await szShowSheet<bool>(
      context: context,
      builder: (context) => _TableTypeSheet(api: widget.api, existing: t),
    );
    if (saved == true) _load();
  }

  /// 平台规则:**明写出来,而且明说商家改不了**。
  Widget _platformRules() {
    final sz = Theme.of(context).sz;
    final rules = (_s!['platform_rules'] as List? ?? []).cast<String>();
    return Container(
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: sz.surfaceAlt,
        borderRadius: BorderRadius.circular(10),
      ),
      child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('这几条是平台规则,不在你这儿改',
                style: TextStyle(
                    fontSize: kFontBody,
                    fontWeight: FontWeight.w700,
                    color: sz.ink)),
            const SizedBox(height: 8),
            for (final r in rules)
              Padding(
                padding: const EdgeInsets.only(bottom: 6),
                child: Text('· $r',
                    style: TextStyle(
                        fontSize: kFontNote,
                        height: 1.5,
                        color: sz.inkMuted)),
              ),
            const SizedBox(height: 4),
            Text('客人在店铺页看得到同样的规则,也查得到自己那个号的完整流水。',
                style: TextStyle(fontSize: kFontMicro, color: sz.inkFaint)),
          ]),
    );
  }
}

class _TableTypeSheet extends StatefulWidget {
  const _TableTypeSheet({required this.api, this.existing});

  final ApiClient api;
  final Map<String, dynamic>? existing;

  @override
  State<_TableTypeSheet> createState() => _TableTypeSheetState();
}

class _TableTypeSheetState extends State<_TableTypeSheet> {
  late final _name =
      TextEditingController(text: '${widget.existing?['name'] ?? ''}');
  late int _lo = widget.existing?['seats_min'] as int? ?? 1;
  late int _hi = widget.existing?['seats_max'] as int? ?? 4;
  late int _count = widget.existing?['table_count'] as int? ?? 4;
  late int _turn = widget.existing?['turn_minutes'] as int? ?? 45;
  late bool _active = widget.existing?['is_active'] as bool? ?? true;
  bool _busy = false;

  @override
  void dispose() {
    _name.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    if (_name.text.trim().isEmpty) return;
    if (_lo > _hi) {
      ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('最少人数不能大于最多人数')));
      return;
    }
    setState(() => _busy = true);
    final body = {
      'name': _name.text.trim(),
      'seats_min': _lo,
      'seats_max': _hi,
      'table_count': _count,
      'turn_minutes': _turn,
      'is_active': _active,
    };
    try {
      if (widget.existing == null) {
        await widget.api.createQueueTableType(body);
      } else {
        await widget.api
            .updateQueueTableType(widget.existing!['id'] as int, body);
      }
      if (!mounted) return;
      Navigator.pop(context, true);
    } catch (e) {
      if (!mounted) return;
      setState(() => _busy = false);
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text('$e')));
    }
  }

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    return Padding(
      padding: EdgeInsets.fromLTRB(
          20, 8, 20, MediaQuery.of(context).viewInsets.bottom + 24),
      child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(widget.existing == null ? '加一个桌型' : '改桌型',
                style: Theme.of(context).textTheme.titleLarge),
            const SizedBox(height: 14),
            TextField(
              controller: _name,
              maxLength: 20,
              decoration: const InputDecoration(
                  labelText: '名字', hintText: '如 四人桌 / 包间'),
            ),
            _spin('容纳人数下限', _lo, 1, 50, (v) => setState(() => _lo = v)),
            _spin('容纳人数上限', _hi, 1, 50, (v) => setState(() => _hi = v)),
            _spin('这一档有几张桌', _count, 1, 200,
                (v) => setState(() => _count = v)),
            _spin('预计用餐时长(分钟)', _turn, 5, 240,
                (v) => setState(() => _turn = v), step: 5),
            const SizedBox(height: 4),
            Text('用餐时长直接决定客人看到的「最多等多久」。'
                '填得比实际短,客人会白等;填长了实际更快,是惊喜。',
                style: TextStyle(
                    fontSize: kFontNote, height: 1.5, color: sz.inkMuted)),
            SwitchListTile(
              contentPadding: EdgeInsets.zero,
              title: const Text('启用'),
              value: _active,
              onChanged: (v) => setState(() => _active = v),
            ),
            const SizedBox(height: 8),
            SizedBox(
              width: double.infinity,
              child: FilledButton(
                onPressed: _busy ? null : _submit,
                child: Text(_busy ? '保存中…' : '保存'),
              ),
            ),
          ]),
    );
  }

  Widget _spin(String label, int v, int lo, int hi, ValueChanged<int> onChanged,
      {int step = 1}) {
    final sz = Theme.of(context).sz;
    return Padding(
      padding: const EdgeInsets.only(top: 4),
      child: Row(children: [
        Expanded(
            child: Text(label,
                style: TextStyle(fontSize: kFontBody, color: sz.ink))),
        IconButton(
            onPressed: v - step >= lo ? () => onChanged(v - step) : null,
            icon: const Icon(Icons.remove_circle_outline)),
        SizedBox(
          width: 40,
          child: Text('$v',
              textAlign: TextAlign.center,
              style: TextStyle(
                  fontSize: kFontBodyLg,
                  fontWeight: FontWeight.w700,
                  color: sz.ink)),
        ),
        IconButton(
            onPressed: v + step <= hi ? () => onChanged(v + step) : null,
            icon: const Icon(Icons.add_circle_outline)),
      ]),
    );
  }
}
