import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';

/// 送达后的「这单不好送」反馈(#301)。
///
/// ## 为什么在送达之后
///
/// 送达前弹这个,是在他赶时间的时候加手续。**先把餐送到,再说钱的事。**
///
/// ## 为什么值得占他十秒钟
///
/// 因为平台不知道这些事,而他知道:
///
/// - 配送费里的上门难度费取决于用户自己填的楼层/电梯 ——
///   大多数人不填(那就是 0,他爬六层白爬),填了也没人核实;
/// - 「要步行进小区 300 米」「车进不去」「门禁要等保安」
///   根本没有字段。
///
/// 所以第一屏就把**能拿多少钱**摆出来。不给出金额的补贴等于施舍,
/// 而施舍是不会有人认真填的。
///
/// ## 可以直接关掉
///
/// 没有强制、没有红点、不填不影响任何东西。
/// 这个入口的价值全部来自"他愿意说",一旦有压力就只剩敷衍。
class HardshipSheet extends StatefulWidget {
  const HardshipSheet({super.key, required this.api, required this.orderNo});

  final ApiClient api;
  final String orderNo;

  /// 送达成功后调用。**返回值没人用** —— 填不填都不影响主流程。
  static Future<void> show(
      BuildContext context, ApiClient api, String orderNo) async {
    // 统一走 szShowSheet:SafeArea、拖拽条、键盘避让、宽屏限宽,
    // 这个 helper 自己吸收(check_wide_layout.sh 盯着这一条)
    await szShowSheet<void>(
      context: context,
      builder: (_) => HardshipSheet(api: api, orderNo: orderNo),
    );
  }

  @override
  State<HardshipSheet> createState() => _HardshipSheetState();
}

class _HardshipSheetState extends State<HardshipSheet> {
  final _picked = <String>{};
  final _floors = TextEditingController();
  final _walkM = TextEditingController();
  final _note = TextEditingController();
  Map<String, dynamic>? _rules;
  bool _sending = false;
  String _error = '';

  @override
  void initState() {
    super.initState();
    _loadRules();
  }

  @override
  void dispose() {
    _floors.dispose();
    _walkM.dispose();
    _note.dispose();
    super.dispose();
  }

  Future<void> _loadRules() async {
    try {
      final r = await widget.api.hardshipRules();
      if (mounted) setState(() => _rules = r);
    } catch (_) {
      // 拉不到规则就只显示选项、不显示金额。**不拦着他填** ——
      // 服务端照样会补钱,金额只是让他判断值不值得填
      if (mounted) setState(() => _rules = null);
    }
  }

  List<Map<String, dynamic>> get _items =>
      ((_rules?['items'] as List?) ?? const [])
          .cast<Map<String, dynamic>>();

  Future<void> _submit() async {
    if (_picked.isEmpty || _sending) return;
    setState(() {
      _sending = true;
      _error = '';
    });
    try {
      final res = await widget.api.reportHardship(
        widget.orderNo,
        kinds: _picked.toList(),
        floors: int.tryParse(_floors.text.trim()),
        walkM: int.tryParse(_walkM.text.trim()),
        note: _note.text.trim(),
      );
      if (!mounted) return;
      Navigator.of(context).pop();
      ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('${res['message']}')));
    } catch (e) {
      if (mounted) {
        setState(() {
          _error = '$e';
          _sending = false;
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final sz = theme.sz;
    final needFloors = _picked.contains('no_elevator');
    final needWalk = _picked.contains('walk_in');
    return Padding(
      padding: EdgeInsets.fromLTRB(
          16, 0, 16, MediaQuery.of(context).viewInsets.bottom + 16),
      child: SingleChildScrollView(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          mainAxisSize: MainAxisSize.min,
          children: [
            Text('这单不好送?说一声',
                style: theme.textTheme.titleMedium
                    ?.copyWith(fontWeight: FontWeight.w600)),
            const SizedBox(height: 4),
            // 第一句就说清楚这不是投诉、也不是考核,是补钱
            Text(
              '平台不知道哪栋楼没电梯、哪个小区车进不去 —— 你知道。\n'
              '说了这一单当场补钱(平台出,不从顾客和商家身上要);'
              '同一个地方两个人说过之后,后来的单一开始就按真实情况算。',
              style: TextStyle(fontSize: kFontNote, color: sz.inkMuted),
            ),
            const SizedBox(height: 12),
            for (final item in _items)
              CheckboxListTile(
                dense: true,
                contentPadding: EdgeInsets.zero,
                controlAffinity: ListTileControlAffinity.leading,
                value: _picked.contains(item['kind']),
                onChanged: (v) => setState(() => v == true
                    ? _picked.add('${item['kind']}')
                    : _picked.remove('${item['kind']}')),
                title: Text('${item['name']}'),
                // 金额和规则直接写在选项下面 ——
                // 不给出金额的补贴等于施舍,而施舍没人会认真填
                subtitle: Text('${item['desc']} · ${item['rule']}',
                    style: TextStyle(fontSize: kFontMicro, color: sz.inkMuted)),
              ),
            if (_items.isEmpty)
              Padding(
                padding: const EdgeInsets.symmetric(vertical: 12),
                child: Text('规则没拉到,先勾也行 —— 补贴照算',
                    style: TextStyle(fontSize: kFontNote, color: sz.inkMuted)),
              ),
            if (needFloors)
              TextField(
                controller: _floors,
                keyboardType: TextInputType.number,
                decoration: const InputDecoration(
                    labelText: '爬到几楼', suffixText: '楼', isDense: true),
              ),
            if (needWalk)
              TextField(
                controller: _walkM,
                keyboardType: TextInputType.number,
                decoration: const InputDecoration(
                    labelText: '大概走了多远', suffixText: '米', isDense: true),
              ),
            const SizedBox(height: 8),
            TextField(
              controller: _note,
              maxLength: 100,
              decoration: const InputDecoration(
                  labelText: '还有什么要说的(可不填)',
                  isDense: true,
                  border: OutlineInputBorder()),
            ),
            if (_error.isNotEmpty)
              Padding(
                padding: const EdgeInsets.only(bottom: 8),
                child: Text(_error,
                    style: TextStyle(fontSize: kFontNote, color: theme.colorScheme.error)),
              ),
            Row(children: [
              // 「不用了」放在左边、样式最轻:这是个可以直接关掉的东西,
              // 不填不影响任何事 —— 有压力就只剩敷衍
              TextButton(
                  onPressed: _sending ? null : () => Navigator.of(context).pop(),
                  child: const Text('不用了')),
              const Spacer(),
              FilledButton(
                onPressed: _picked.isEmpty || _sending ? null : _submit,
                child: Text(_sending ? '提交中…' : '提交'),
              ),
            ]),
            const SizedBox(height: 4),
            Text('这条反馈不影响你的评分、派单和接单资格',
                style: TextStyle(fontSize: kFontMicro, color: sz.inkMuted)),
          ],
        ),
      ),
    );
  }
}
