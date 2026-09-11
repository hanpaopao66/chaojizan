import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';
import 'package:url_launcher/url_launcher.dart';

/// 见证节点:骑手自己复算平台账本(「我的 → 见证节点」)。
///
/// 和用户端「账目透明」页用的是同一套 [PhoneWitness]:把公开账本的哈希链
/// 在这台手机上从头算一遍,和平台给的锚点逐天比对。愿意的话匿名上报,
/// 成为公开节点之一。
///
/// 设计稿这一行写的是「骑手互助会 · 见证节点」—— 平台没有「骑手互助会」
/// 这个组织,不能凭空写一个,所以只留见证节点这件真事。
class RiderWitnessPage extends StatefulWidget {
  const RiderWitnessPage({super.key, required this.api});

  final ApiClient api;

  @override
  State<RiderWitnessPage> createState() => _RiderWitnessPageState();
}

class _RiderWitnessPageState extends State<RiderWitnessPage> {
  WitnessResult? _result;
  Map<String, dynamic>? _nodes;
  bool _running = true;
  bool _on = false;
  String _error = '';

  @override
  void initState() {
    super.initState();
    _run();
  }

  Future<void> _run() async {
    setState(() {
      _running = true;
      _error = '';
    });
    try {
      final on = await PhoneWitness.enabled();
      final nodes = await widget.api.nodesSummary();
      final r = await PhoneWitness(widget.api).runCycle(heartbeat: on);
      if (!mounted) return;
      setState(() {
        _on = on;
        _nodes = nodes;
        _result = r;
        _running = false;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _running = false;
        _error = e is ApiException ? e.message : '$e';
      });
    }
  }

  Future<void> _join(bool on) async {
    await PhoneWitness.setEnabled(on,
        name: on ? '骑手${(widget.api.userName ?? '').isEmpty ? '' : '·${widget.api.userName}'}的手机' : '');
    await _run();
  }

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    final r = _result;
    final online = (_nodes?['online'] as num?)?.toInt();
    final total = (_nodes?['total'] as num?)?.toInt();
    return SzPageScaffold(
      appBar: AppBar(title: const Text('见证节点')),
      body: RefreshIndicator(
        onRefresh: _run,
        child: ListView(
          padding: const EdgeInsets.fromLTRB(kPagePad, 12, kPagePad, 28),
          children: [
            SzLedgerCard(
              child: Builder(builder: (context) {
                final s = Theme.of(context).sz;
                return Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text('这台手机刚复算的结果',
                          style: TextStyle(
                              fontSize: kFontMicro,
                              letterSpacing: 1,
                              color: s.inkMuted)),
                      const SizedBox(height: 6),
                      if (_running)
                        Text('正在从头算账本…',
                            style: TextStyle(fontSize: kFontTitle, color: s.ink))
                      else if (r == null)
                        Text('没算成:$_error',
                            style: TextStyle(fontSize: kFontBody, color: s.danger))
                      else ...[
                        Text(r.ok ? '账对得上' : '发现 ${r.problems.length} 处对不上',
                            style: szDisplay(
                                fontSize: kFigureMd,
                                color: r.ok ? s.earn : s.danger)),
                        const SizedBox(height: 6),
                        Text('核到 ${r.verifiedDay} · 共 ${r.daysVerified} 天',
                            style: TextStyle(fontSize: kFontNote, color: s.inkMuted)),
                        for (final p in r.problems.take(5))
                          Text(p,
                              style: TextStyle(
                                  fontSize: kFontNote, color: s.danger)),
                      ],
                    ]);
              }),
            ),
            const SizedBox(height: 12),
            SzEntryGroup(
              footnote: 'App 是平台发的,完全独立的核验请在电脑上跑见证脚本 '
                  '(chaojizan.cc/nodes);手机核验的意义在于:算发生在你自己的手机上,'
                  '平台没法只对你一个人造假。',
              children: [
                SzEntryTile(
                  icon: Icons.hub_outlined,
                  title: '全网见证节点',
                  value: online == null ? null : '在线 $online / 共 $total',
                ),
                SzEntryTile(
                  icon: Icons.cell_tower,
                  title: '让这台手机也当一个节点',
                  hint: '匿名上报复算结果,不带任何个人信息',
                  trailing: SzSwitch(
                      small: true, value: _on, onChanged: (v) => _join(v)),
                ),
                SzEntryTile(
                  icon: Icons.open_in_new,
                  title: '在电脑上跑见证脚本',
                  onTap: () => launchUrl(
                      Uri.parse('https://chaojizan.cc/nodes'),
                      mode: LaunchMode.externalApplication),
                ),
              ],
            ),
            const SizedBox(height: 12),
            Text('见证节点做的事只有一件:每天把公开账本的哈希链自己算一遍。'
                '哪一天的锚点被改了或者消失了,节点会在公开页上示警 —— '
                '改历史上任何一分钱,全网都会知道。',
                style: TextStyle(fontSize: kFontNote, height: 1.6, color: sz.inkMuted)),
          ],
        ),
      ),
    );
  }
}
