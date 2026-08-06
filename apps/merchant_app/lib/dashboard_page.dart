import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';

/// 经营看板(#154):打烊后坐下来看的那一屏。
///
/// ## 为什么这一页可以"满屏图表",而订单页不行
///
/// 我原先反对做图表看板,理由是「商家在收银台前扫一眼,要的是我该改什么」。
/// 这个顾虑对**订单页**成立,但看板本来就不是扫一眼的场景 ——
/// 它是**打烊后复盘**用的。两种场景要的东西不一样,不该用一个理由否掉另一个。
///
/// ## 守住的那条线:每张图都要能回答一个具体问题
///
/// 判据很硬:**看了这张图,商家会做什么决定?** 答不上来的图不放。
///
/// | 图 | 回答的问题 | 商家的动作 |
/// |---|---|---|
/// | 近 8 周趋势 | 生意在变好还是变坏 | 决定要不要调整 |
/// | 分时段热力 | 哪个时段是主力、哪个空着 | 调备货与人手 |
/// | 出餐时长分布 | 我到底多久出一单 | 改承诺值、改后厨流程 |
/// | 菜品贡献 | 哪些该主推、哪些该下架 | 调菜单 |
/// | 流失去向 | 单量掉在哪一环 | 针对性修 |
///
/// ## 呈现纪律
///
/// - **先结论后图表**:每张图上方一句话说明它说明了什么。不要让商家
///   自己从折线里读结论 —— 能一句话说清的,就不该让他猜;
/// - **环比用周不用天**:外卖周内节律强(周末 ≠ 周三),按天比会把节律
///   当趋势,得出「周一生意变差了」这种废话 —— 每个周一都比周日差;
/// - **没数据时说没数据,不画平线** —— 一条平线会被读成"生意很平稳"。
///
/// ## 不做的
///
/// 不做同行对比、不做区域排名。一旦排名影响生意,商家的动作会从
/// 「把菜做好」变成「把数字做好看」。
class DashboardPage extends StatefulWidget {
  const DashboardPage({super.key, required this.api});

  final ApiClient api;

  @override
  State<DashboardPage> createState() => _DashboardPageState();
}

class _DashboardPageState extends State<DashboardPage> {
  Map<String, dynamic>? _trend;
  Map<String, dynamic>? _today;
  Map<String, dynamic>? _funnel;
  Map<String, dynamic>? _prep;
  Map<String, dynamic>? _analytics;
  String? _error;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    // 三个来源各自独立:任何一个挂了,其余的图照常显示。
    // 看板不是事务,没有"全有或全无"的必要
    String? err;
    final results = await Future.wait([
      widget.api.merchantTrend().then<Object?>((v) => v).catchError((Object e) {
        err ??= '$e';
        return null;
      }),
      widget.api.merchantToday().then<Object?>((v) => v).catchError((Object e) {
        err ??= '$e';
        return null;
      }),
      widget.api.merchantFunnel().then<Object?>((v) => v).catchError((Object e) {
        err ??= '$e';
        return null;
      }),
      widget.api.merchantPrepTime().then<Object?>((v) => v).catchError((Object e) {
        err ??= '$e';
        return null;
      }),
      widget.api
          .merchantAnalytics(days: 30)
          .then<Object?>((v) => v)
          .catchError((Object e) {
        err ??= '$e';
        return null;
      }),
    ]);
    if (!mounted) return;
    setState(() {
      _trend = results[0] as Map<String, dynamic>?;
      _today = results[1] as Map<String, dynamic>?;
      _funnel = results[2] as Map<String, dynamic>?;
      _prep = results[3] as Map<String, dynamic>?;
      _analytics = results[4] as Map<String, dynamic>?;
      _error = (_trend == null && _prep == null && _analytics == null) ? err : null;
    });
  }

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    final loading = _trend == null && _prep == null && _analytics == null;
    return Scaffold(
      appBar: AppBar(title: const Text('经营看板')),
      body: _error != null
          ? SzError(error: _error, onRetry: _load)
          : loading
              ? const Center(child: CircularProgressIndicator())
              : RefreshIndicator(
                  onRefresh: _load,
                  child: ListView(
                    padding: const EdgeInsets.fromLTRB(kPagePad, 12, kPagePad, 32),
                    children: [
                      if (_today != null) ...[
                        _todayCard(sz),
                        const SizedBox(height: 12),
                      ],
                      if (_trend != null) ...[
                        _trendCard(sz),
                        const SizedBox(height: 14),
                      ],
                      if (_funnel != null) ...[
                        _funnelCard(sz),
                        const SizedBox(height: 14),
                      ],
                      if (_analytics != null) ...[
                        _hourlyCard(sz),
                        const SizedBox(height: 14),
                      ],
                      if (_prep != null) ...[
                        _prepCard(sz),
                        const SizedBox(height: 14),
                      ],
                      if (_analytics != null) ...[
                        _dishCard(sz),
                        const SizedBox(height: 14),
                      ],
                      if (_trend != null) ...[
                        _causesCard(sz),
                        const SizedBox(height: 14),
                      ],
                      Text(
                        '看板只给你自己看,不做同行对比、不做区域排名。'
                        '一旦排名影响生意,动作就会从「把菜做好」变成「把数字做好看」。',
                        style: TextStyle(
                            fontSize: 11.5, height: 1.6, color: sz.inkFaint),
                      ),
                    ],
                  ),
                ),
    );
  }

  // ---------------- 0. 今日实况(下单口径,与对账入账口径有别) ----------------

  Widget _todayCard(SzColors sz) {
    final today = _today!['today'] as Map<String, dynamic>? ?? const {};
    final yesterday = _today!['yesterday'] as Map<String, dynamic>?;
    Widget cell(String label, String value) => Expanded(
          child: Column(children: [
            Text(value,
                style: szFigure(
                    fontSize: 18, fontWeight: FontWeight.w700, color: sz.ink)),
            const SizedBox(height: 2),
            Text(label, style: TextStyle(fontSize: 11, color: sz.inkMuted)),
          ]),
        );
    return Container(
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: sz.surface,
        borderRadius: BorderRadius.circular(kRadiusMd),
        border: Border.all(color: sz.line),
      ),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          Text('今日实况', style: TextStyle(
              fontWeight: FontWeight.w600, color: sz.ink)),
          const Spacer(),
          if (yesterday != null)
            Text('昨日 ${yesterday['orders']} 单 · '
                '${yuan(yesterday['gmv_cents'] as int? ?? 0)}',
                style: TextStyle(fontSize: 11, color: sz.inkFaint)),
        ]),
        const SizedBox(height: 10),
        Row(children: [
          cell('订单', '${today['orders'] ?? 0}'),
          cell('营业额', yuan(today['gmv_cents'] as int? ?? 0)),
          cell('进行中', '${today['ongoing'] ?? 0}'),
          cell('已取消', '${today['cancelled'] ?? 0}'),
        ]),
        const SizedBox(height: 6),
        Text('按今日下单统计,是生意热度;对账页按结算入账,两边对不上是正常的',
            style: TextStyle(fontSize: 10.5, color: sz.inkFaint)),
      ]),
    );
  }

  // ---------------- 0.5 流量漏斗:哪一环在漏 ----------------

  Widget _funnelCard(SzColors sz) {
    final f = _funnel!;
    Widget step(String label, int value, double? rate) => Padding(
          padding: const EdgeInsets.symmetric(vertical: 3),
          child: Row(children: [
            SizedBox(
                width: 78,
                child: Text(label,
                    style: TextStyle(fontSize: 12.5, color: sz.inkMuted))),
            Text('$value',
                style: szFigure(
                    fontSize: 16, fontWeight: FontWeight.w700, color: sz.ink)),
            const Spacer(),
            if (rate != null)
              Text('转化 ${(rate * 100).toStringAsFixed(1)}%',
                  style: TextStyle(
                      fontSize: 12,
                      color: rate >= 0.3 ? sz.earn : sz.hold)),
          ]),
        );
    return Container(
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: sz.surface,
        borderRadius: BorderRadius.circular(kRadiusMd),
        border: Border.all(color: sz.line),
      ),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text('近 ${f['days']} 天流量漏斗',
            style: TextStyle(fontWeight: FontWeight.w600, color: sz.ink)),
        const SizedBox(height: 8),
        step('看到你的店', f['impression'] as int? ?? 0, null),
        step('进店看菜单', f['visit'] as int? ?? 0,
            (f['visit_rate'] as num?)?.toDouble()),
        step('进入结算', f['checkout'] as int? ?? 0,
            (f['checkout_rate'] as num?)?.toDouble()),
        step('下单', f['ordered'] as int? ?? 0,
            (f['order_rate'] as num?)?.toDouble()),
        const SizedBox(height: 6),
        Text('${f['note']}',
            style: TextStyle(fontSize: 10.5, height: 1.5, color: sz.inkFaint)),
      ]),
    );
  }

  // ---------------- 1. 近 8 周趋势:生意在变好还是变坏 ----------------

  Widget _trendCard(SzColors sz) {
    final weeks = (_trend!['weeks'] as List).cast<Map<String, dynamic>>();
    final cmp = _trend!['compare'] as Map<String, dynamic>?;

    // 先结论:一句话说清这张图说明了什么
    String verdict;
    Color verdictColor = sz.inkMuted;
    if (cmp == null) {
      verdict = '还只有一周数据,下周才比得出变化';
    } else {
      final pct = (cmp['orders']?['pct'] as num?)?.toDouble();
      final cur = cmp['orders']?['cur'] as int? ?? 0;
      final prev = cmp['orders']?['prev'] as int? ?? 0;
      // 说的是**最近一个完整周**,不是本周 —— 本周还没过完,
      // 拿它比上周整七天,每个周一都会得出"暴跌"的假结论
      if (pct == null) {
        verdict = '上一整周 $prev 单,最近一整周 $cur 单';
      } else if (pct.abs() < 5) {
        verdict = '最近一整周 $cur 单,和前一周基本持平(${_pct(pct)})';
      } else if (pct > 0) {
        verdict = '最近一整周 $cur 单,比前一周多了 ${_pct(pct)}';
        verdictColor = sz.earn;
      } else {
        verdict = '最近一整周 $cur 单,比前一周少了 ${_pct(pct.abs())} —— 往下看流失在哪一环';
        verdictColor = sz.hold;
      }
    }

    return _chartCard(
      sz,
      title: '近 ${weeks.length} 周趋势',
      question: '生意在变好还是变坏',
      verdict: verdict,
      verdictColor: verdictColor,
      child: weeks.length < 2
          ? _notEnough(sz, '至少要两周才画得出趋势')
          : Column(children: [
              _WeekBars(weeks: weeks, sz: sz),
              const SizedBox(height: 12),
              if (cmp != null) ...[
                Text(
                    '环比:${cmp['prev_week']} 那一周 → ${cmp['week']} 那一周'
                    '(都是完整周,本周还没过完不参与比较)',
                    style: TextStyle(fontSize: 10.5, color: sz.inkFaint)),
                const SizedBox(height: 8),
                _compareRow(sz, cmp),
              ],
            ]),
    );
  }

  Widget _compareRow(SzColors sz, Map<String, dynamic> cmp) => Row(children: [
        _cmpCell(sz, '单量', cmp['orders'], money: false),
        _cmpCell(sz, '营业额', cmp['food_cents'], money: true),
        _cmpCell(sz, '客单价', cmp['avg_cents'], money: true),
        _cmpCell(sz, '顾客数', cmp['customers'], money: false),
      ]);

  Widget _cmpCell(SzColors sz, String label, dynamic c, {required bool money}) {
    final m = c as Map<String, dynamic>?;
    final cur = m?['cur'] as num?;
    final pct = (m?['pct'] as num?)?.toDouble();
    return Expanded(
      child: Column(children: [
        Text(
          cur == null
              ? '—'
              : money
                  ? yuan(cur.toInt())
                  : '$cur',
          style: szMoney(
              fontSize: 15, fontWeight: FontWeight.w600, color: sz.ink),
        ),
        const SizedBox(height: 1),
        Text(label, style: TextStyle(fontSize: 11, color: sz.inkMuted)),
        const SizedBox(height: 2),
        // 变化给量级而不只给方向:「-12%」比「下降」有用得多
        Text(
          pct == null ? '—' : _signed(pct),
          style: szFigure(
            fontSize: 11.5,
            color: pct == null
                ? sz.inkFaint
                : pct > 0
                    ? sz.earn
                    : pct < 0
                        ? sz.hold
                        : sz.inkMuted,
          ),
        ),
      ]),
    );
  }

  // ---------------- 2. 分时段热力:哪个时段是主力 ----------------

  Widget _hourlyCard(SzColors sz) {
    final hourly = (_analytics!['hourly'] as List).cast<int>();
    final total = hourly.fold<int>(0, (a, b) => a + b);
    final peak = hourly.isEmpty ? 0 : hourly.reduce(math.max);
    final peakHour = hourly.indexOf(peak);

    // 找出连续的空档(营业时间里一单没有的时段)——这才是商家能动手的地方
    String verdict;
    if (total == 0) {
      verdict = '近 30 天还没有完成单';
    } else {
      final share = (peak / total * 100).round();
      verdict = '$peakHour 点最忙,一天 $share% 的单集中在这一小时';
    }

    return _chartCard(
      sz,
      title: '分时段单量(近 30 天)',
      question: '哪个时段是主力、哪个时段空着',
      verdict: verdict,
      child: total == 0
          ? _notEnough(sz, '还没有完成单')
          : Column(children: [
              _HourBars(hourly: hourly, sz: sz),
              const SizedBox(height: 8),
              Text('高峰前 30 分钟备好料,空档时段可以安排采购与打扫',
                  style: TextStyle(fontSize: 11.5, color: sz.inkMuted)),
            ]),
    );
  }

  // ---------------- 3. 出餐时长分布:我到底多久出一单 ----------------

  Widget _prepCard(SzColors sz) {
    final p = _prep!;
    final enough = p['enough'] == true;
    final p50 = (p['p50'] as num?)?.toDouble();
    final p80 = (p['p80'] as num?)?.toDouble();
    final p95 = (p['p95'] as num?)?.toDouble();
    final promised = (p['promised_minutes'] as num?)?.toDouble();
    final gap = (p['gap_minutes'] as num?)?.toDouble();

    String verdict;
    Color color = sz.inkMuted;
    if (!enough) {
      verdict = '近 30 天只有 ${p['samples']} 单,样本还不够(要 ${p['min_samples']} 单)';
    } else if (gap == null || promised == null) {
      verdict = '十单里有八单在 ${_min(p80)} 分钟内出餐';
    } else if (gap > 3) {
      verdict = '你承诺 ${_min(promised)} 分钟,实际十单里有两单要 ${_min(p80)} 分钟 —— '
          '慢了 ${_min(gap)} 分钟';
      color = sz.hold;
    } else if (gap < -3) {
      verdict = '你承诺 ${_min(promised)} 分钟,实际 ${_min(p80)} 分钟就出餐了 —— '
          '承诺值可以往下调,顾客会看到更快的送达时间';
      color = sz.earn;
    } else {
      verdict = '承诺 ${_min(promised)} 分钟,实际 ${_min(p80)} 分钟,基本吻合';
      color = sz.earn;
    }

    return _chartCard(
      sz,
      title: '出餐时长分布(近 30 天)',
      question: '我到底多久出一单',
      verdict: verdict,
      verdictColor: color,
      child: !enough
          ? _notEnough(sz, '样本不足时给出的分位数没有意义,所以先不给')
          : Column(children: [
              _PrepBar(p50: p50, p80: p80, p95: p95, promised: promised, sz: sz),
              const SizedBox(height: 14),
              Row(children: [
                _prepCell(sz, '一半的单', p50, '分钟内'),
                _prepCell(sz, '八成的单', p80, '分钟内', highlight: true),
                _prepCell(sz, '最慢那些', p95, '分钟'),
              ]),
              const SizedBox(height: 10),
              if (p['peer_median_p50'] != null)
                Text(
                    '同品类中位数 ${_min((p['peer_median_p50'] as num).toDouble())} 分钟 —— '
                    '这是参照系,不是排名',
                    style: TextStyle(fontSize: 11.5, color: sz.inkMuted)),
              const SizedBox(height: 6),
              // 红线原样显示。商家会本能地担心"这个数会不会影响我的生意",
              // 不主动说清楚,他就会开始为这个数经营(比如提前点"出餐")
              Container(
                width: double.infinity,
                padding: const EdgeInsets.all(10),
                decoration: BoxDecoration(
                  color: sz.earn.withValues(alpha: .08),
                  borderRadius: BorderRadius.circular(kRadiusSm),
                ),
                child: Text('${p['never_used_for']}',
                    style: TextStyle(
                        fontSize: 11.5, height: 1.5, color: sz.inkMuted)),
              ),
            ]),
    );
  }

  Widget _prepCell(SzColors sz, String label, double? v, String unit,
          {bool highlight = false}) =>
      Expanded(
        child: Column(children: [
          Text(_min(v),
              style: szMoney(
                  fontSize: highlight ? 22 : 18,
                  fontWeight: FontWeight.w600,
                  color: highlight ? sz.ink : sz.inkMuted)),
          const SizedBox(height: 2),
          Text(label, style: TextStyle(fontSize: 11.5, color: sz.inkMuted)),
          Text(unit, style: TextStyle(fontSize: 10.5, color: sz.inkFaint)),
        ]),
      );

  // ---------------- 4. 菜品贡献:哪些该主推、哪些该下架 ----------------

  Widget _dishCard(SzColors sz) {
    // analytics 按**份数**排序,但这张图要回答的是「哪些菜该主推」——
    // 一道卖 78 份的酸辣粉(¥936)和一道卖 35 份的套餐(¥1750),
    // 对流水的贡献完全不同。所以这里按**金额**重排。
    //
    // 不重排的话还会有个更糟的错位:底条按金额缩放、顺序按份数,
    // 看上去就是"份数递减而条长忽长忽短",而且"前三道菜撑起 X%"
    // 里的"前三"取的是份数前三,算出来的百分比对不上任何一句人话
    final dishes = (_analytics!['top_dishes'] as List)
        .cast<Map<String, dynamic>>()
        .toList()
      ..sort((a, b) =>
          (b['amount_cents'] as int).compareTo(a['amount_cents'] as int));
    final soldOut = dishes.where((d) => d['sold_out_today'] == true).length;

    String verdict;
    if (dishes.isEmpty) {
      verdict = '近 30 天还没有完成单';
    } else {
      final topAmount = dishes.take(3).fold<int>(
          0, (a, d) => a + (d['amount_cents'] as int));
      final all = dishes.fold<int>(0, (a, d) => a + (d['amount_cents'] as int));
      final share = all == 0 ? 0 : (topAmount / all * 100).round();
      verdict = '流水最高的三道菜撑起了 TOP10 里 $share%'
          '${soldOut > 0 ? ',其中 $soldOut 道今天已售罄' : ''}';
    }

    return _chartCard(
      sz,
      title: '菜品贡献(近 30 天)',
      question: '哪些菜该主推、哪些该下架',
      verdict: verdict,
      verdictColor: soldOut > 0 ? sz.hold : sz.inkMuted,
      child: dishes.isEmpty
          ? _notEnough(sz, '还没有完成单')
          : Column(children: [
              for (final d in dishes.take(8))
                _DishRow(
                  dish: d,
                  maxAmount: dishes.first['amount_cents'] as int,
                  sz: sz,
                ),
              const SizedBox(height: 6),
              Text('排在末位又长期不动的菜,占着菜单位置也占着后厨备料',
                  style: TextStyle(fontSize: 11.5, color: sz.inkMuted)),
            ]),
    );
  }

  // ---------------- 5. 流失去向:单量掉在哪一环 ----------------

  Widget _causesCard(SzColors sz) {
    final causes = (_trend!['causes'] as List).cast<Map<String, dynamic>>();
    final lost = causes.fold<int>(
        0, (a, c) => a + ((c['orders'] as int?) ?? 0));

    return _chartCard(
      sz,
      title: '流失去向(近 7 天)',
      question: '单量掉在哪一环',
      verdict: causes.isEmpty
          ? '近 7 天没有可归因的流失 —— 拒单、超时未接、出餐超时都是 0'
          : '近 7 天有 $lost 单没能做成,拆开看是这些原因',
      verdictColor: causes.isEmpty ? sz.earn : sz.hold,
      child: causes.isEmpty
          ? const SizedBox.shrink()
          : Column(children: [
              for (final c in causes)
                Padding(
                  padding: const EdgeInsets.only(bottom: 10),
                  child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    Container(
                      width: 3,
                      height: 34,
                      decoration: BoxDecoration(
                        color: sz.hold,
                        borderRadius: BorderRadius.circular(2),
                      ),
                    ),
                    const SizedBox(width: 10),
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Row(children: [
                            Text('${c['name']}',
                                style: const TextStyle(
                                    fontSize: 14, fontWeight: FontWeight.w600)),
                            const SizedBox(width: 6),
                            Text(
                                '${c['orders'] ?? c['dishes']} '
                                '${c.containsKey('dishes') ? '道菜' : '单'}',
                                style: szFigure(fontSize: 13.5, color: sz.hold)),
                            // 估算就明说是估算。给一个精确到个位的假数字,
                            // 比给"大约"更坏 —— 商家会拿它去算账
                            if (c['estimated'] == true) ...[
                              const SizedBox(width: 5),
                              Text('估算',
                                  style: TextStyle(
                                      fontSize: 10, color: sz.inkFaint)),
                            ],
                          ]),
                          const SizedBox(height: 2),
                          Text('${c['hint']}',
                              style: TextStyle(
                                  fontSize: 11.5, height: 1.45, color: sz.inkMuted)),
                        ],
                      ),
                    ),
                  ]),
                ),
              Text('${_trend!['estimate_note']}',
                  style: TextStyle(fontSize: 11, color: sz.inkFaint)),
            ]),
    );
  }

  // ---------------- 通用外壳 ----------------

  /// 每张图的统一外壳:**标题 → 它回答什么问题 → 一句话结论 → 图**。
  ///
  /// 「它回答什么问题」这一行不是装饰 —— 它是这一页的自我约束:
  /// 写不出这一行的图,就不该放进来。
  Widget _chartCard(
    SzColors sz, {
    required String title,
    required String question,
    required String verdict,
    Color? verdictColor,
    required Widget child,
  }) =>
      SzCard(
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [
            Expanded(
              child: Text(title,
                  style: const TextStyle(
                      fontSize: 15, fontWeight: FontWeight.w600)),
            ),
            Text(question,
                style: TextStyle(fontSize: 11, color: sz.inkFaint)),
          ]),
          const SizedBox(height: 6),
          // 先结论后图表:不让商家自己从折线里读结论
          Text(verdict,
              style: TextStyle(
                  fontSize: 13,
                  height: 1.45,
                  color: verdictColor ?? sz.inkMuted)),
          const SizedBox(height: 14),
          child,
        ]),
      );

  /// 没数据时明说没数据。**不画一条平线假装有** —— 平线会被读成"生意很平稳"
  Widget _notEnough(SzColors sz, String why) => Container(
        width: double.infinity,
        padding: const EdgeInsets.symmetric(vertical: 22),
        alignment: Alignment.center,
        child: Column(children: [
          Text('还没有足够数据',
              style: TextStyle(fontSize: 13.5, color: sz.inkMuted)),
          const SizedBox(height: 3),
          Text(why, style: TextStyle(fontSize: 11.5, color: sz.inkFaint)),
        ]),
      );

  String _pct(double v) => '${v.abs().toStringAsFixed(0)}%';

  String _signed(double v) =>
      '${v > 0 ? '+' : ''}${v.toStringAsFixed(0)}%';

  String _min(double? v) => v == null ? '—' : v.toStringAsFixed(0);
}

// ============ 图表原语:不引图表库,与既有 analytics_page 一脉相承 ============

/// 近 N 周单量柱。柱高按单量,金额写在下方。
///
/// **0 单的那一周画成一条贴底的细线而不是"没有柱子"** ——
/// 没有柱子会被误读成"这周的数据没加载出来",细线才是"这周确实是 0 单"。
class _WeekBars extends StatelessWidget {
  const _WeekBars({required this.weeks, required this.sz});

  final List<Map<String, dynamic>> weeks;
  final SzColors sz;

  @override
  Widget build(BuildContext context) {
    final maxOrders =
        weeks.fold<int>(1, (m, w) => math.max(m, w['orders'] as int));
    // 高度要装得下:数字 + 柱 + 日期 + 「进行中」那一行。
    // 少算了那一行会 overflow —— 实机撞过
    return SizedBox(
      height: 132,
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.end,
        children: [
          for (final (i, w) in weeks.indexed)
            Expanded(
              child: Padding(
                padding: const EdgeInsets.symmetric(horizontal: 2.5),
                child: Column(
                  mainAxisAlignment: MainAxisAlignment.end,
                  children: [
                    Text('${w['orders']}',
                        style: szFigure(
                            fontSize: 10.5,
                            color: i == weeks.length - 1
                                ? sz.ink
                                : sz.inkFaint)),
                    const SizedBox(height: 3),
                    Container(
                      height: math.max(
                          2.0, 72.0 * (w['orders'] as int) / maxOrders),
                      decoration: BoxDecoration(
                        // 最新的**完整**周实心,历史周淡。
                        // 本周(partial)描边不填实 —— 它还没过完,
                        // 画成实心柱会被当成"这周就这么点单"
                        color: w['partial'] == true
                            ? Colors.transparent
                            : i == weeks.length - 1 ||
                                    (i == weeks.length - 2 &&
                                        weeks.last['partial'] == true)
                                ? sz.earn
                                : sz.earn.withValues(alpha: .35),
                        border: w['partial'] == true
                            ? Border.all(color: sz.earn, width: 1.2)
                            : null,
                        borderRadius:
                            const BorderRadius.vertical(top: Radius.circular(3)),
                      ),
                    ),
                    const SizedBox(height: 4),
                    Text(
                      // 只给月/日,给完整日期一行放不下 8 个
                      '${w['week']}'.substring(5).replaceAll('-', '/'),
                      style: TextStyle(fontSize: 9, color: sz.inkFaint),
                    ),
                    if (w['partial'] == true)
                      Text('进行中',
                          style: TextStyle(fontSize: 8, color: sz.inkFaint)),
                  ],
                ),
              ),
            ),
        ],
      ),
    );
  }
}

/// 24 小时单量热力条。用色深浅表密度,比柱状更省纵向空间。
class _HourBars extends StatelessWidget {
  const _HourBars({required this.hourly, required this.sz});

  final List<int> hourly;
  final SzColors sz;

  @override
  Widget build(BuildContext context) {
    final peak = hourly.fold<int>(1, math.max);
    return Column(children: [
      SizedBox(
        height: 62,
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.end,
          children: [
            for (final v in hourly)
              Expanded(
                child: Padding(
                  padding: const EdgeInsets.symmetric(horizontal: .8),
                  child: Container(
                    height: math.max(2.0, 60.0 * v / peak),
                    decoration: BoxDecoration(
                      color: sz.earn.withValues(
                          alpha: v == 0 ? .12 : .35 + .65 * (v / peak)),
                      borderRadius:
                          const BorderRadius.vertical(top: Radius.circular(2)),
                    ),
                  ),
                ),
              ),
          ],
        ),
      ),
      const SizedBox(height: 4),
      Row(children: [
        for (var h = 0; h < 24; h++)
          Expanded(
            child: Text(h % 4 == 0 ? '$h' : '',
                textAlign: TextAlign.center,
                style: TextStyle(fontSize: 9, color: sz.inkFaint)),
          ),
      ]),
    ]);
  }
}

/// 出餐时长的分位刻度条:P50 / P80 / P95 三个点 + 承诺值的位置。
///
/// 用一条横轴而不是三个孤立数字,是因为商家真正要看的是
/// **承诺值落在自己实际分布的哪个位置** —— 落在 P50 左边就是"一半的单都超"。
class _PrepBar extends StatelessWidget {
  const _PrepBar({
    required this.p50,
    required this.p80,
    required this.p95,
    required this.promised,
    required this.sz,
  });

  final double? p50, p80, p95, promised;
  final SzColors sz;

  @override
  Widget build(BuildContext context) {
    final maxV = math.max(p95 ?? 0, promised ?? 0) * 1.15;
    if (maxV <= 0) return const SizedBox.shrink();
    double at(double? v) => v == null ? 0 : (v / maxV).clamp(0.0, 1.0);

    return LayoutBuilder(builder: (context, c) {
      final w = c.maxWidth;
      return SizedBox(
        height: 46,
        child: Stack(children: [
          // 底轨:0 → P95 的整体跨度
          Positioned(
            top: 18,
            left: 0,
            right: 0,
            child: Container(
              height: 8,
              decoration: BoxDecoration(
                color: sz.line,
                borderRadius: BorderRadius.circular(4),
              ),
            ),
          ),
          // 实测主区间(0 → P80):八成的单落在这段里
          Positioned(
            top: 18,
            left: 0,
            child: Container(
              width: w * at(p80),
              height: 8,
              decoration: BoxDecoration(
                color: sz.earn.withValues(alpha: .55),
                borderRadius: BorderRadius.circular(4),
              ),
            ),
          ),
          // 承诺值:一条竖线。它在 P80 左边 = 八成的单里有一部分超了承诺
          if (promised != null)
            Positioned(
              top: 8,
              left: (w * at(promised) - 1).clamp(0.0, w - 2),
              child: Container(width: 2, height: 28, color: sz.clay),
            ),
          if (promised != null)
            Positioned(
              top: 32,
              left: (w * at(promised) - 18).clamp(0.0, w - 40),
              child: Text('承诺 ${promised!.toStringAsFixed(0)}',
                  style: TextStyle(fontSize: 9.5, color: sz.clay)),
            ),
          Positioned(
            top: 0,
            left: (w * at(p80) - 14).clamp(0.0, w - 30),
            child: Text('P80', style: TextStyle(fontSize: 9.5, color: sz.earn)),
          ),
        ]),
      );
    });
  }
}

/// 菜品贡献行:名次 + 名称 + 一条按金额缩放的底条 + 份数/金额。
class _DishRow extends StatelessWidget {
  const _DishRow(
      {required this.dish, required this.maxAmount, required this.sz});

  final Map<String, dynamic> dish;
  final int maxAmount;
  final SzColors sz;

  @override
  Widget build(BuildContext context) {
    final amount = dish['amount_cents'] as int;
    final ratio = maxAmount == 0 ? 0.0 : amount / maxAmount;
    final soldOut = dish['sold_out_today'] == true;
    return Padding(
      padding: const EdgeInsets.only(bottom: 9),
      child: Column(children: [
        Row(children: [
          Expanded(
            child: Row(children: [
              Flexible(
                child: Text('${dish['name']}',
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: const TextStyle(fontSize: 13.5)),
              ),
              if (soldOut) ...[
                const SizedBox(width: 5),
                Text('今日售罄',
                    style: TextStyle(fontSize: 10, color: sz.hold)),
              ],
            ]),
          ),
          Text('${dish['qty']} 份',
              style: TextStyle(fontSize: 11.5, color: sz.inkMuted)),
          const SizedBox(width: 8),
          SizedBox(
            width: 58,
            child: Text(yuan(amount),
                textAlign: TextAlign.right,
                style: szMoney(fontSize: 13, color: sz.ink)),
          ),
        ]),
        const SizedBox(height: 3),
        Row(children: [
          Expanded(
            flex: math.max(1, (ratio * 100).round()),
            child: Container(
              height: 4,
              decoration: BoxDecoration(
                color: soldOut ? sz.hold : sz.earn.withValues(alpha: .5),
                borderRadius: BorderRadius.circular(2),
              ),
            ),
          ),
          Expanded(
            flex: math.max(1, 100 - (ratio * 100).round()),
            child: const SizedBox(height: 4),
          ),
        ]),
      ]),
    );
  }
}
