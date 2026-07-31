import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';

/// 派单算法说明(#141)。
///
/// 为什么骑手端要有这一页:**派单算法对骑手的意义,等同于账目对商家的意义**
/// —— 它决定你今天挣多少。资本平台的算法是黑箱,骑手只能猜"为什么好单不给我"。
///
/// 这页的数据来自 `/transparency/dispatch`,而那个接口**从排序代码的常量
/// 直接读**,不是另抄一份 —— 抄的那份迟早和真实算法对不上,
/// 那时公开的就是假的,比不公开更坏。服务端有测试钉着这件事。
///
/// 公开给外人看却不给骑手看,是本末倒置,所以抢单页上直接给入口。
class DispatchSpecPage extends StatefulWidget {
  const DispatchSpecPage({super.key, required this.api});

  final ApiClient api;

  @override
  State<DispatchSpecPage> createState() => _DispatchSpecPageState();
}

class _DispatchSpecPageState extends State<DispatchSpecPage> {
  Map<String, dynamic>? _spec;
  String? _error;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final d = await widget.api.dispatchSpec();
      if (mounted) setState(() => _spec = d);
    } catch (e) {
      if (mounted) setState(() => _error = '$e');
    }
  }

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    return Scaffold(
      appBar: AppBar(title: const Text('抢单怎么排的')),
      body: _error != null
          ? Center(
              child: Padding(
                padding: const EdgeInsets.all(kPagePad),
                child: Text('拿不到算法说明:$_error',
                    style: TextStyle(color: sz.inkMuted)),
              ),
            )
          : _spec == null
              ? const Center(child: CircularProgressIndicator())
              : _content(sz),
    );
  }

  Widget _content(SzColors sz) {
    final s = _spec!;
    final weights = (s['weights'] as List).cast<Map<String, dynamic>>();
    final never = (s['never_do'] as List).cast<String>();
    final sw = s['same_way_definition'] as Map<String, dynamic>;
    final dist = s['distance'] as Map<String, dynamic>;
    final log = (s['changelog'] as List).cast<Map<String, dynamic>>();

    return ListView(
      padding: const EdgeInsets.fromLTRB(kPagePad, 12, kPagePad, 32),
      children: [
        Text('这一页就是抢单池的排序规则本身。',
            style: TextStyle(
                fontSize: 15, fontWeight: FontWeight.w600, color: sz.ink)),
        const SizedBox(height: 4),
        Text('不是简化版说明 —— 下面的数字就是代码里正在跑的那几个,'
            '改了会立刻反映在这里。你可以拿自己的单代进去算。',
            style: TextStyle(fontSize: 12.5, color: sz.inkMuted)),
        const SizedBox(height: 16),

        SzLedgerCard(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text('${s['formula']}',
                style: const TextStyle(fontSize: 13.5, height: 1.6)),
            const SizedBox(height: 8),
            Text('${s['unit']}',
                style: TextStyle(fontSize: 11.5, color: SzColors.dark.inkMuted)),
          ]),
        ),
        const SizedBox(height: 18),

        const SzSectionTitle('每一项是多少,以及为什么'),
        const SizedBox(height: 8),
        for (final w in weights) ...[
          SzCard(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(children: [
                  Expanded(
                    child: Text('${w['name']}',
                        style: TextStyle(
                            fontSize: 14.5,
                            fontWeight: FontWeight.w600,
                            color: sz.ink)),
                  ),
                  if (w['cap'] != null)
                    SzChip('封顶 ${w['cap']}', color: sz.hold, dense: true),
                ]),
                const SizedBox(height: 4),
                Text('${w['value']}',
                    style: TextStyle(fontSize: 13, color: sz.clay)),
                const SizedBox(height: 6),
                Text('${w['why']}',
                    style: TextStyle(
                        fontSize: 12, height: 1.55, color: sz.inkMuted)),
              ],
            ),
          ),
          const SizedBox(height: 8),
        ],

        const SizedBox(height: 10),
        const SzSectionTitle('「顺路」是怎么算的'),
        const SizedBox(height: 8),
        SzCard(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text('${sw['formula']}',
                style: TextStyle(fontSize: 12.5, height: 1.6, color: sz.ink)),
            const SizedBox(height: 8),
            Text('${sw['why']}',
                style: TextStyle(
                    fontSize: 12, height: 1.55, color: sz.inkMuted)),
          ]),
        ),

        const SizedBox(height: 18),
        const SzSectionTitle('距离是怎么来的'),
        const SizedBox(height: 8),
        SzCard(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text('${dist['source']}',
                style: TextStyle(fontSize: 12.5, color: sz.ink)),
            const SizedBox(height: 6),
            Text('${dist['why']}',
                style: TextStyle(
                    fontSize: 12, height: 1.55, color: sz.inkMuted)),
          ]),
        ),

        const SizedBox(height: 18),
        const SzSectionTitle('平台承诺不做的事'),
        const SizedBox(height: 8),
        SzCard(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              for (final n in never) ...[
                Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Text('✕ ', style: TextStyle(color: sz.earn, fontSize: 13)),
                  Expanded(
                    child: Text(n,
                        style: TextStyle(
                            fontSize: 12.5, height: 1.55, color: sz.ink)),
                  ),
                ]),
                const SizedBox(height: 8),
              ],
            ],
          ),
        ),

        const SizedBox(height: 18),
        const SzSectionTitle('改过什么'),
        const SizedBox(height: 4),
        Text('算法可以改,但不会悄悄改 —— 悄悄改就等于从没公开过。',
            style: TextStyle(fontSize: 11.5, color: sz.inkMuted)),
        const SizedBox(height: 8),
        for (final e in log) ...[
          SzCard(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text('${e['date']}',
                    style: szFigure(fontSize: 12, color: sz.inkMuted)),
                const SizedBox(height: 4),
                Text('${e['what']}',
                    style: TextStyle(
                        fontSize: 12.5, height: 1.55, color: sz.ink)),
                const SizedBox(height: 6),
                Text('为什么改:${e['why']}',
                    style: TextStyle(
                        fontSize: 12, height: 1.5, color: sz.inkMuted)),
              ],
            ),
          ),
          const SizedBox(height: 8),
        ],
      ],
    );
  }
}
