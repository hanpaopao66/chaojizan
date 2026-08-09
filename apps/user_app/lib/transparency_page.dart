/// 「平台体检」——把 /transparency/* 十个公开端点一次性摊给用户看。
///
/// 为什么要单独一页:平台最核心的差异化是「这单钱怎么分」「账目对不对得上」。
/// 这十个端点后端早就写完、无鉴权、带完整口径说明,但用户端一个都没接——
/// 也就是说这个差异化到今天为止只存在于代码里,用户在 App 里看不到。
///
/// 三条原则贯穿全页(改这个文件之前先读一遍):
///
///  1. **可验证,不是好看**。服务端给的恒等式(收入−支出=留存、
///     商家+骑手+佣金−补贴=100)在客户端**再算一遍**,对不上就亮红灯;
///     核账缺一天、探针缺一档,一律按「没有」显示,不按「正常」糊过去。
///  2. **数字难看也照实显示**。平台倒贴、赔付很多、可用率不满 100%,原样写出来。
///     这一页的价值就在于它敢难看——做成"一切正常"的汇总卡,这页就白做了。
///  3. **单点降级**。十个端点并发拉,谁挂了谁那块显示「这项暂时取不到」+ 重试,
///     不能一个失败拖白整页。
///
/// 长辈版(1.4× 字号)与深色模式:本页不写死任何文字高度,
/// 所有「标签 — 数值」行都用 Expanded/Wrap 让文字自己折行;
/// 只有色带格子是固定尺寸(那里面没有文字,放大也不会撑破)。
library;

import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';

/// 一个端点的取数状态。
///
/// 单独装盒是为了让某一个端点挂掉时**只影响它自己那一块**:
/// 页面持有十个 [_Slot],谁 error 谁降级,其余照常渲染。
class _Slot {
  Map<String, dynamic>? data;
  Object? error;
  bool loading = true;
}

/// 体检结论。红灯必须能从折叠状态下就看见,否则等于没亮。
enum _Verdict { loading, ok, warn, bad, dead }

class TransparencyPage extends StatefulWidget {
  const TransparencyPage({super.key, required this.api});

  final ApiClient api;

  @override
  State<TransparencyPage> createState() => _TransparencyPageState();
}

class _TransparencyPageState extends State<TransparencyPage> {
  final _audit = _Slot();
  final _funds = _Slot();
  final _comp = _Slot();
  final _fairness = _Slot();
  final _reports = _Slot();
  final _uptime = _Slot();
  final _dispatch = _Slot();
  final _kitchen = _Slot();
  final _gov = _Slot();
  final _changelog = _Slot();

  @override
  void initState() {
    super.initState();
    Analytics.track('view_transparency');
    _loadAll();
  }

  /// 十个请求**并发**发出去。串行的话十个 RTT 叠加,
  /// 而它们之间没有任何依赖关系,没有理由排队。
  Future<void> _loadAll() async {
    final api = widget.api;
    await Future.wait([
      _fetch(_audit, api.auditPublic),
      _fetch(_funds, api.fundsPublic),
      _fetch(_comp, api.compensationPublic),
      _fetch(_fairness, api.fairnessPublic),
      _fetch(_reports, api.reportsPublic),
      _fetch(_uptime, api.uptimePublic),
      _fetch(_dispatch, api.dispatchSpec),
      _fetch(_kitchen, api.kitchenCamSpec),
      _fetch(_gov, api.governancePublic),
      _fetch(_changelog, api.changelogPublic),
    ]);
  }

  /// 每个槽自己吞掉异常——**绝不向外抛**,否则 [Future.wait] 会因为
  /// 一个端点挂掉而整体 reject,那就又回到"一个失败整页白屏"。
  Future<void> _fetch(
      _Slot slot, Future<Map<String, dynamic>> Function() call) async {
    if (mounted) {
      setState(() {
        slot.loading = true;
        slot.error = null;
      });
    }
    try {
      final data = await call();
      if (mounted) {
        setState(() {
          slot.data = data;
          slot.loading = false;
        });
      }
    } catch (e) {
      if (mounted) {
        setState(() {
          slot.error = e;
          slot.loading = false;
        });
      }
    }
  }

  List<_Slot> get _all => [
        _audit, _funds, _comp, _fairness, _reports,
        _uptime, _dispatch, _kitchen, _gov, _changelog,
      ];

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    final settled = _all.where((s) => !s.loading).length;
    final dead = _all.where((s) => s.error != null).length;

    return Scaffold(
      appBar: AppBar(title: const Text('平台体检')),
      body: settled == 0
          // 一条都还没回来:骨架屏,不手写转圈
          ? const SkeletonList(itemCount: 6)
          : dead == _all.length
              // 十个全挂,基本是断网/服务整体不可用,这时才整页报错
              ? SzError(
                  error: '十项数据都取不到,可能是网络断了。\n${_all.first.error}',
                  onRetry: _loadAll)
              : RefreshIndicator(
                  onRefresh: _loadAll,
                  child: ListView(
                    padding: const EdgeInsets.fromLTRB(kPagePad, 6, kPagePad, 28),
                    children: [
                      _intro(sz, dead),
                      const SizedBox(height: 14),

                      // 默认展开的三块:账目对不对得上、钱去哪了、平台赔了多少。
                      // 这三件事是用户真正会追问的,其余折叠。
                      _auditSection(),
                      _fundsSection(),
                      _compensationSection(),

                      const SizedBox(height: 16),
                      const SzSectionTitle('展开看更细的'),
                      const SizedBox(height: 8),

                      _fairnessSection(),
                      _reportsSection(),
                      _uptimeSection(),
                      _dispatchSection(),
                      _kitchenSection(),
                      _governanceSection(),
                      _changelogSection(),

                      const SizedBox(height: 18),
                      Text(
                        '这一页的数字全部来自平台公开接口(/transparency/*,无需登录,'
                        '任何人都可以自己请求一遍对照)。我们不做「一切正常」的汇总:'
                        '核账差一分钱、探针缺一档、平台倒贴,都按原样显示。',
                        style: TextStyle(
                            fontSize: 11.5, height: 1.7, color: sz.inkFaint),
                      ),
                    ],
                  ),
                ),
    );
  }

  Widget _intro(SzColors sz, int dead) {
    return SzLedgerCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text('十项公开数据,逐项对照',
              style: TextStyle(
                  fontSize: 17, fontWeight: FontWeight.w600, color: sz.ink)),
          const SizedBox(height: 8),
          Text(
            '账目核对、资金去向、平台赔付、分账公平、月度财报、系统可用率、'
            '派单算法、明厨亮灶、治理留痕、版本更新。红灯不藏,数字不修饰。',
            style: TextStyle(fontSize: 12.5, height: 1.7, color: sz.inkMuted),
          ),
          if (dead > 0) ...[
            const SizedBox(height: 10),
            Text('当前有 $dead 项暂时取不到,已在对应区块单独标出。',
                style: TextStyle(
                    fontSize: 12, height: 1.6, color: sz.danger)),
          ],
        ],
      ),
    );
  }

  // ------------------------------------------------------------------
  // 一 · 每日核账:这一页的压舱石。差一分钱就要看得见
  // ------------------------------------------------------------------

  Widget _auditSection() {
    final d = _audit.data;
    final runs = _list(d?['runs']);
    // 服务端按 day 倒序给最近 90 次「运行记录」——注意是运行记录不是日历天,
    // 没跑过核账的日子根本不在这个列表里。所以下面要按 90 天日历补齐:
    // 缺的那天不能算"干净",只能算"那天没核"。
    final byDay = {for (final r in runs) '${r['day']}': r};
    final cal = _calendar(90);
    final missing = cal.where((day) => !byDay.containsKey(day)).length;
    final problemDays =
        runs.where((r) => _int(r['problems']) > 0).toList(growable: false);
    final totalProblems =
        runs.fold<int>(0, (a, r) => a + _int(r['problems']));
    final latest = _map(d?['latest']);
    final streak = _int(d?['clean_streak_days']);
    final window = _int(d?['window_days']);

    final verdict = _audit.error != null
        ? _Verdict.dead
        : _audit.loading
            ? _Verdict.loading
            : runs.isEmpty
                ? _Verdict.bad
                : totalProblems > 0
                    ? _Verdict.bad
                    : missing > 0
                        ? _Verdict.warn
                        : _Verdict.ok;

    return _Section(
      icon: Icons.rule_folder_outlined,
      title: '账目核对',
      initiallyExpanded: true,
      verdict: verdict,
      status: _audit.error != null
          ? '这项暂时取不到'
          : _audit.loading
              ? '正在取…'
              : runs.isEmpty
                  ? '近 90 天没有任何核账记录'
                  : totalProblems > 0
                      ? '${problemDays.length} 天对不上账,共 $totalProblems 笔'
                      : missing > 0
                          ? '有记录的 ${runs.length} 天全部无差错,另有 $missing 天没跑过核账'
                          : '90 天逐日核对,0 笔差错',
      slot: _audit,
      onRetry: () => _fetch(_audit, widget.api.auditPublic),
      builder: (context) {
        final sz = Theme.of(context).sz;
        if (runs.isEmpty) {
          return _bad(sz,
              '近 90 天没有任何核账运行记录。\n这本身就是问题——没跑过核账,'
              '就等于没人替你盯着账本,而不是"没发现问题"。');
        }
        return Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            _plain(sz,
                '每天自动把近 $window 天的账全部重算一遍:商家入账 = 菜钱 − 佣金、'
                '骑手入账 = 配送费(100% 归骑手)、退款汇总 = 逐笔流水之和。'
                '任意一条对不上,就记一笔差错。'),
            const SizedBox(height: 12),
            if (totalProblems > 0)
              _bad(sz,
                  '有 $totalProblems 笔账对不上,分布在 ${problemDays.length} 天。'
                  '差错不会自己消失,也不会被这一页藏起来。')
            else
              _good(sz, '有核账记录的 ${runs.length} 天里,差错笔数为 0。'),
            if (missing > 0) ...[
              const SizedBox(height: 8),
              _warn(sz,
                  '近 90 天里有 $missing 天没有核账记录。这些天按「没核」显示,'
                  '不按「没问题」显示——没查过和查过没事,不是一回事。'),
            ],
            const SizedBox(height: 14),
            _stripLegend(sz, const [
              ('干净', _Tone.good),
              ('有差错', _Tone.bad),
              ('没核账', _Tone.none),
            ]),
            const SizedBox(height: 6),
            _strip(sz, [
              for (final day in cal)
                if (!byDay.containsKey(day))
                  const _Cell(_Tone.none)
                else
                  _Cell(_int(byDay[day]!['problems']) > 0
                      ? _Tone.bad
                      : _Tone.good),
            ]),
            const SizedBox(height: 14),
            if (latest.isNotEmpty)
              _kv(sz, '最近一次核账',
                  '${latest['day']} · ${_int(latest['checked_orders'])} 笔订单 · '
                  '${_int(latest['problems'])} 笔差错',
                  danger: _int(latest['problems']) > 0),
            _kv(sz, '连续无差错', '$streak 天',
                note: missing > 0 ? '按有记录的运行日连续计,缺的天不计入' : null),
            _kv(sz, '每次核对范围', '近 $window 天全部账目'),
          ],
        );
      },
    );
  }

  // ------------------------------------------------------------------
  // 二 · 资金去向:收了多少、赔了多少、剩下多少(可能是负的)
  // ------------------------------------------------------------------

  Widget _fundsSection() {
    final d = _funds.data;
    final income = _map(d?['income']);
    final spend = _map(d?['spend']);
    final incomeTotal = _int(income['total_cents']);
    final spendTotal = _int(spend['total_cents']);
    final retained = _int(d?['retained_cents']);

    // 客户端把服务端的恒等式再算一遍:三个数对不上就是接口自己出了问题,
    // 这种时候必须报出来,而不是照着 retained 直接画饼图
    final incomeParts = _int(income['commission_cents']) +
        _int(income['voucher_fee_cents']);
    final spendParts = _int(spend['subsidy_cents']) +
        _int(spend['meal_compensation_cents']) +
        _int(spend['adjustment_cents']);
    final closes = d == null ||
        (incomeParts == incomeTotal &&
            spendParts == spendTotal &&
            incomeTotal - spendTotal == retained);

    final verdict = _funds.error != null
        ? _Verdict.dead
        : _funds.loading
            ? _Verdict.loading
            : !closes
                ? _Verdict.bad
                : retained < 0
                    ? _Verdict.warn
                    : _Verdict.ok;

    return _Section(
      icon: Icons.account_balance_wallet_outlined,
      title: '资金去向',
      initiallyExpanded: true,
      verdict: verdict,
      status: _funds.error != null
          ? '这项暂时取不到'
          : _funds.loading
              ? '正在取…'
              : !closes
                  ? '收支明细与合计对不上,接口有问题'
                  : retained < 0
                      ? '平台目前是倒贴的,净支出 ${_yuan(-retained)}'
                      : '收 ${_yuan(incomeTotal)} · 赔付支出 ${_yuan(spendTotal)}',
      slot: _funds,
      onRetry: () => _fetch(_funds, widget.api.fundsPublic),
      builder: (context) {
        final sz = Theme.of(context).sz;
        return Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            _plain(sz,
                '平台唯一的收入是商家服务费(至多 5%)和团购核销费(2%)——'
                '不卖广告位、不收推广费、不抽配送费。'
                '收进来的钱先扣掉赔出去的,剩下的才是平台留存,'
                '要覆盖服务器、支付通道、客服和审核人力。'),
            const SizedBox(height: 12),
            if (!closes)
              _bad(sz,
                  '这组数字自己对不上:收入分项合计 ${_yuan(incomeParts)}、'
                  '接口给的收入合计 ${_yuan(incomeTotal)};'
                  '支出分项合计 ${_yuan(spendParts)}、接口给的支出合计 ${_yuan(spendTotal)}。'
                  '在修好之前,下面的数字都不可信。'),
            if (!closes) const SizedBox(height: 10),
            const SzSectionTitle('收进来'),
            const SizedBox(height: 6),
            _kv(sz, '外卖商家服务费', _yuan(_int(income['commission_cents']))),
            _kv(sz, '团购核销服务费', _yuan(_int(income['voucher_fee_cents']))),
            _kv(sz, '合计', _yuan(incomeTotal), strong: true),
            const SizedBox(height: 12),
            const SzSectionTitle('赔出去 / 贴出去'),
            const SizedBox(height: 6),
            _kv(sz, '平台补贴', _yuan(_int(spend['subsidy_cents'])),
                note: '首单立减、安抚券抵扣,平台承担'),
            _kv(sz, '餐损赔付', _yuan(_int(spend['meal_compensation_cents'])),
                note: '无骑手接单被取消时,已出餐的商家按应收全额赔,佣金不收'),
            _kv(sz, '申诉改判', _yuan(_int(spend['adjustment_cents'])),
                note: '判错了改回来,平台认亏'),
            _kv(sz, '合计', _yuan(spendTotal), strong: true),
            const SizedBox(height: 12),
            SzLedgerCard(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(retained < 0 ? '平台净倒贴' : '平台留存',
                      style: TextStyle(
                          fontSize: 12, color: Theme.of(context).sz.inkMuted)),
                  const SizedBox(height: 4),
                  Text(_yuan(retained.abs()),
                      style: szMoney(
                          fontSize: 26,
                          color: retained < 0
                              ? Theme.of(context).sz.danger
                              : Theme.of(context).sz.ink)),
                  const SizedBox(height: 6),
                  Text(
                    retained < 0
                        ? '赔出去的比收进来的多。这个数是负的我们也照写——'
                            '把它藏起来,这一页就没有存在的必要了。'
                        : '收入 ${_yuan(incomeTotal)} − 支出 ${_yuan(spendTotal)}。'
                            '这不是利润:服务器、带宽、支付通道费、'
                            '客服与审核人力都还没从这里扣。',
                    style: TextStyle(
                        fontSize: 11.5,
                        height: 1.7,
                        color: Theme.of(context).sz.inkMuted),
                  ),
                ],
              ),
            ),
            if (d?['generated_at'] != null) ...[
              const SizedBox(height: 8),
              _stamp(sz, '统计时间 ${_time(d!['generated_at'])}'),
            ],
          ],
        );
      },
    );
  }

  // ------------------------------------------------------------------
  // 三 · 平台赔付:主动亮自己赔出去的钱
  // ------------------------------------------------------------------

  Widget _compensationSection() {
    final d = _comp.data;
    final eta = _map(d?['eta_coupons']);
    final meal = _map(d?['meal_compensation']);
    final refund = _map(d?['refunds']);
    int cents(Map<String, dynamic> m, String scope) =>
        _int(_map(m[scope])['cents']);

    // 平台净掏的只有前两项:退款是把用户自己的钱原路退回,不算平台赔付。
    // 这个区别必须写清楚,否则等于用退款额给赔付额充数
    final platformPaid = cents(eta, 'total') + cents(meal, 'total');
    final platformPaidMonth = cents(eta, 'month') + cents(meal, 'month');

    return _Section(
      icon: Icons.volunteer_activism_outlined,
      title: '平台赔付',
      initiallyExpanded: true,
      verdict: _comp.error != null
          ? _Verdict.dead
          : _comp.loading
              ? _Verdict.loading
              : _Verdict.ok,
      status: _comp.error != null
          ? '这项暂时取不到'
          : _comp.loading
              ? '正在取…'
              : '平台累计净掏 ${_yuan(platformPaid)},本月 ${_yuan(platformPaidMonth)}',
      slot: _comp,
      onRetry: () => _fetch(_comp, widget.api.compensationPublic),
      builder: (context) {
        final sz = Theme.of(context).sz;
        return Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            _plain(sz,
                '这里是平台**自己**赔出去的钱。承诺兑现没有,看赔付账最准:'
                '一个从不赔钱的平台,要么从不出错,要么赔的规则形同虚设。'),
            const SizedBox(height: 12),
            _compRow(sz, '超时安抚券', eta,
                '送达超时 15 分钟自动发券,平台承担,不摊给商家和骑手'),
            _compRow(sz, '餐损赔付', meal,
                '没有骑手接单被取消时,已出餐的商家按应收全额赔付'),
            _compRow(sz, '成功退款', refund,
                '缺货部分退 / 整单退 / 售后退,渠道确认到账才算数'),
            const SizedBox(height: 10),
            _plain(sz,
                '注意口径:退款是把你付的钱原路退回,不是平台的损失;'
                '真正由平台掏腰包的是前两项,累计 ${_yuan(platformPaid)}。'
                '把退款额算进「平台赔了多少」是行业常见的话术,我们不这么算。'),
            if (d?['month_since'] != null) ...[
              const SizedBox(height: 8),
              _stamp(sz, '「本月」自 ${d!['month_since']} 起'),
            ],
          ],
        );
      },
    );
  }

  Widget _compRow(SzColors sz, String label, Map<String, dynamic> m,
      String note) {
    final total = _map(m['total']);
    final month = _map(m['month']);
    return Padding(
      padding: const EdgeInsets.only(bottom: 12),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // Wrap 而不是 Row:长辈版下「标签 + 金额」放大后能自己换行,不会溢出
          Wrap(
            crossAxisAlignment: WrapCrossAlignment.end,
            spacing: 8,
            runSpacing: 2,
            children: [
              Text(label,
                  style: TextStyle(
                      fontSize: 13.5,
                      fontWeight: FontWeight.w600,
                      color: sz.ink)),
              Text(_yuan(_int(total['cents'])),
                  style: szMoney(fontSize: 15, color: sz.ink)),
              Text('${_int(total['count'])} 笔',
                  style: TextStyle(fontSize: 11.5, color: sz.inkFaint)),
            ],
          ),
          const SizedBox(height: 2),
          Text(
              '本月 ${_yuan(_int(month['cents']))} · ${_int(month['count'])} 笔',
              style: TextStyle(fontSize: 11.5, color: sz.inkMuted)),
          const SizedBox(height: 2),
          Text(note,
              style: TextStyle(fontSize: 11.5, height: 1.6, color: sz.inkFaint)),
        ],
      ),
    );
  }

  // ------------------------------------------------------------------
  // 四 · 分账公平:真实费率 vs 承诺,每 100 元的去向要闭合
  // ------------------------------------------------------------------

  Widget _fairnessSection() {
    final d = _fairness.data;
    final comm = _map(d?['commission']);
    final stay = _map(d?['stay_commission']);
    final per100 = d?['per100'] == null ? null : _map(d?['per100']);
    final rider = _map(d?['rider_income']);
    final reviews = _map(d?['reviews']);
    final window = _int(d?['window_days']);

    final real = _dbl(comm['real_rate_30d']);
    final cap = _dbl(comm['promised_cap']);
    final overCap = real != null && cap != null && real > cap;

    // 恒等式:商家 + 骑手 + 佣金 − 补贴 = 100。四个数各自四舍五入到 0.1,
    // 累计误差最多 0.2,所以容差取 0.3;超出就不是舍入,是账本身有问题
    double? closure;
    if (per100 != null) {
      closure = (_dbl(per100['merchant']) ?? 0) +
          (_dbl(per100['rider']) ?? 0) +
          (_dbl(per100['commission']) ?? 0) -
          (_dbl(per100['subsidy']) ?? 0);
    }
    final closureBad = closure != null && (closure - 100).abs() > 0.3;

    return _Section(
      icon: Icons.balance_outlined,
      title: '分账公平',
      verdict: _fairness.error != null
          ? _Verdict.dead
          : _fairness.loading
              ? _Verdict.loading
              : (overCap || closureBad)
                  ? _Verdict.bad
                  : per100 == null
                      ? _Verdict.warn
                      : _Verdict.ok,
      status: _fairness.error != null
          ? '这项暂时取不到'
          : _fairness.loading
              ? '正在取…'
              : overCap
                  ? '真实佣金率 ${_pct(real)} 已超过承诺的 ${_pct(cap)}'
                  : closureBad
                      ? '每 100 元的去向合计 ${closure.toStringAsFixed(1)},没有闭合'
                      : real == null
                          ? '近 $window 天还没有入账,算不出真实费率'
                          : '真实佣金率 ${_pct(real)}(承诺上限 ${_pct(cap)})',
      slot: _fairness,
      onRetry: () => _fetch(_fairness, widget.api.fairnessPublic),
      builder: (context) {
        final sz = Theme.of(context).sz;
        final tiers = _list(comm['tiers']);
        return Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            _plain(sz,
                '「至多 5%」这句话要能被验证,靠的不是承诺,是把真实收到的佣金'
                '除以真实的佣金基数,算出来是多少就写多少。以下均为近 $window 天口径。'),
            const SizedBox(height: 12),
            _kv(sz, '外卖真实佣金率',
                real == null ? '近 $window 天无入账,算不出' : _pct(real),
                danger: overCap, strong: true),
            _kv(sz, '承诺上限', _pct(cap)),
            if (overCap)
              _bad(sz, '真实费率高于承诺上限。这是承诺被打破,不是统计口径问题。'),
            if (tiers.isNotEmpty) ...[
              const SizedBox(height: 6),
              Text('在营商家的费率档位',
                  style: TextStyle(fontSize: 11.5, color: sz.inkFaint)),
              const SizedBox(height: 6),
              Wrap(
                spacing: 6,
                runSpacing: 6,
                children: [
                  for (final t in tiers)
                    SzChip('${_pct(_dbl(t['rate']))} × ${_int(t['merchants'])} 家',
                        dense: true),
                ],
              ),
            ],
            const SizedBox(height: 12),
            _kv(sz, '住宿真实费率',
                _dbl(stay['real_rate_30d']) == null
                    ? '近 $window 天无离店结算'
                    : _pct(_dbl(stay['real_rate_30d'])),
                note: '${stay['note'] ?? ''}'),
            const SizedBox(height: 14),
            const SzSectionTitle('你付的每 100 元去哪了'),
            const SizedBox(height: 6),
            if (per100 == null)
              _warn(sz,
                  '近 $window 天没有可复算的完成订单,这一项没有数字。'
                  '没有就是没有,不用平均值或历史值顶上。')
            else ...[
              _kv(sz, '商家实收', '¥${_fx(per100['merchant'])}'),
              _kv(sz, '骑手所得', '¥${_fx(per100['rider'])}'),
              _kv(sz, '平台佣金', '¥${_fx(per100['commission'])}'),
              _kv(sz, '平台补贴(倒贴进去)', '−¥${_fx(per100['subsidy'])}'),
              const SizedBox(height: 6),
              if (closureBad)
                _bad(sz,
                    '商家 + 骑手 + 佣金 − 补贴 = ${closure!.toStringAsFixed(1)},'
                    '不等于 100。分账没有闭合,这一组数不能当结论用。')
              else
                _good(sz,
                    '商家 + 骑手 + 佣金 − 补贴 = ${closure!.toStringAsFixed(1)} ≈ 100,'
                    '分账闭合。差的零点几来自四舍五入,不是漏账。'),
              const SizedBox(height: 6),
              _plain(sz,
                  '口径:近 $window 天无退款的完成订单。退款单的账在「平台赔付」里单列,'
                  '混进来会让这个恒等式失去意义。'),
            ],
            const SizedBox(height: 14),
            const SzSectionTitle('骑手收入'),
            const SizedBox(height: 6),
            _kv(sz, '累计到手', _yuan(_int(rider['total_cents'])),
                note: '配送费 + 小费 100% 归骑手,平台一分不抽'),
            _kv(sz, '今日到手', _yuan(_int(rider['today_cents']))),
            _kv(sz, '今日单均',
                rider['today_avg_per_order_cents'] == null
                    ? '今天还没有完成的单'
                    : _yuan(_int(rider['today_avg_per_order_cents']))),
            _kv(sz, '累计提现', _yuan(_int(rider['withdrawn_total_cents'])),
                note: '提现零手续费,按行业约 0.1% 通道费估算,'
                    '替骑手省下约 ${_yuan(_int(rider['zero_fee_saved_cents']))}'),
            const SizedBox(height: 14),
            const SzSectionTitle('评价不删'),
            const SizedBox(height: 6),
            _kv(sz, '累计评价', '${_int(reviews['total'])} 条'),
            _kv(sz, '差评占比',
                reviews['bad_ratio'] == null
                    ? '还没有评价'
                    : _pct(_dbl(reviews['bad_ratio'])),
                note: '1–2 星占比。差评不删、不折叠、不降权'),
            _kv(sz, '被标记疑似刷评', '${_int(reviews['flagged_still_visible'])} 条',
                note: '标记了但**仍然可见**——删掉就等于替商家洗白'),
          ],
        );
      },
    );
  }

  // ------------------------------------------------------------------
  // 五 · 月度财报
  // ------------------------------------------------------------------

  Widget _reportsSection() {
    final d = _reports.data;
    final months = _list(d?['months']);
    return _Section(
      icon: Icons.receipt_long_outlined,
      title: '月度财报',
      verdict: _reports.error != null
          ? _Verdict.dead
          : _reports.loading
              ? _Verdict.loading
              : months.isEmpty
                  ? _Verdict.warn
                  : _Verdict.ok,
      status: _reports.error != null
          ? '这项暂时取不到'
          : _reports.loading
              ? '正在取…'
              : months.isEmpty
                  ? '还没有可报的月份'
                  : '已公开 ${months.length} 个月(仅收入侧)',
      slot: _reports,
      onRetry: () => _fetch(_reports, widget.api.reportsPublic),
      builder: (context) {
        final sz = Theme.of(context).sz;
        if (months.isEmpty) {
          return const SzEmpty(
              art: BrandArt.receipt,
              text: '还没有完成的订单,财报没有数字可报。\n先有生意,才有账。');
        }
        return Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            _plain(sz,
                '收入侧由数据库实时聚合,不是人手填的表,所以改不了。'
                '${d?['note'] ?? ''}'),
            const SizedBox(height: 12),
            for (final m in months)
              Padding(
                padding: const EdgeInsets.only(bottom: 10),
                child: SzCard(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Wrap(
                        crossAxisAlignment: WrapCrossAlignment.end,
                        spacing: 8,
                        runSpacing: 2,
                        children: [
                          Text('${m['month']}',
                              style: szFigure(
                                  fontSize: 15,
                                  fontWeight: FontWeight.w600,
                                  color: sz.ink)),
                          Text('完成 ${_int(m['orders_completed'])} 单',
                              style:
                                  TextStyle(fontSize: 12, color: sz.inkMuted)),
                        ],
                      ),
                      const SizedBox(height: 8),
                      _kv(sz, '成交额 GMV', _yuan(_int(m['gmv_cents']))),
                      _kv(sz, '外卖服务费', _yuan(_int(m['commission_cents']))),
                      _kv(sz, '团购核销费', _yuan(_int(m['voucher_fee_cents']))),
                      _kv(sz, '骑手所得', _yuan(_int(m['rider_income_cents']))),
                      _kv(sz, '平台补贴', '−${_yuan(_int(m['subsidy_cents']))}'),
                    ],
                  ),
                ),
              ),
            _plain(sz,
                '成本侧(服务器、短信、推送账单)在各家服务商后台,'
                '没法自动聚合,随开源仓 docs/finance 手工发布。'
                '这里只列能自动算的那一半,不把估算数混进来充数。'),
          ],
        );
      },
    );
  }

  // ------------------------------------------------------------------
  // 六 · 系统可用率:缺一档探针就按不可用算
  // ------------------------------------------------------------------

  Widget _uptimeSection() {
    final d = _uptime.data;
    final days = _list(d?['days']);
    final current = _map(d?['current']);
    final today = _map(d?['today']);
    final interval = _int(d?['probe_interval_minutes']);

    final byDay = {for (final r in days) '${r['day']}': r};
    final cal = _calendar(90);
    final noRecord = cal.where((day) => !byDay.containsKey(day)).length;
    // 平均值按 90 天算,没记录的那天按 0 算——这正是「缺档按不可用计」的意思。
    // 只对有记录的天求平均,等于把停机的日子从分母里删掉,那是自欺
    final sum = cal.fold<double>(
        0, (a, day) => a + (_dbl(byDay[day]?['availability']) ?? 0));
    final avg90 = cal.isEmpty ? 0.0 : sum / cal.length;
    double? worst;
    String? worstDay;
    for (final r in days) {
      final v = _dbl(r['availability']) ?? 0;
      if (worst == null || v < worst) {
        worst = v;
        worstDay = '${r['day']}';
      }
    }
    final currentOk = current['ok'] == true;

    return _Section(
      icon: Icons.monitor_heart_outlined,
      title: '系统可用率',
      verdict: _uptime.error != null
          ? _Verdict.dead
          : _uptime.loading
              ? _Verdict.loading
              : !currentOk
                  ? _Verdict.bad
                  : (noRecord > 0 || avg90 < 0.99)
                      ? _Verdict.warn
                      : _Verdict.ok,
      status: _uptime.error != null
          ? '这项暂时取不到'
          : _uptime.loading
              ? '正在取…'
              : !currentOk
                  ? '当前有依赖不可用'
                  : '90 天平均 ${_pct(avg90, digits: 2)}'
                      '${noRecord > 0 ? ",其中 $noRecord 天完全没有探针记录" : ""}',
      slot: _uptime,
      onRetry: () => _fetch(_uptime, widget.api.uptimePublic),
      builder: (context) {
        final sz = Theme.of(context).sz;
        return Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            _plain(sz,
                '后台每 $interval 分钟自记一次探针,检查数据库和缓存通不通。'
                '一天本该有 ${interval == 0 ? 288 : 1440 ~/ interval} 次,'
                '少一次就按那段时间不可用计——**只会算低,不会虚高**。'),
            const SizedBox(height: 12),
            _kv(sz, '此刻', currentOk ? '正常' : '有依赖不可用',
                danger: !currentOk, strong: true),
            _kv(sz, '数据库', current['db'] == true ? '通' : '不通',
                danger: current['db'] != true),
            _kv(sz, '缓存 Redis', current['redis'] == true ? '通' : '不通',
                danger: current['redis'] != true),
            _kv(sz, '今日探针',
                '${_int(today['ok'])} / ${_int(today['probes'])} 次正常'
                '${today['last_at'] == null ? "" : " · 最近 ${today['last_at']}"}',
                danger: _int(today['ok']) < _int(today['probes'])),
            const SizedBox(height: 14),
            _stripLegend(sz, const [
              ('≥99.9%', _Tone.good),
              ('≥99%', _Tone.warn),
              ('更低', _Tone.bad),
              ('无记录', _Tone.none),
            ]),
            const SizedBox(height: 6),
            _strip(sz, [
              for (final day in cal)
                if (!byDay.containsKey(day))
                  const _Cell(_Tone.none)
                else
                  _Cell(_toneOfAvailability(_dbl(byDay[day]!['availability']) ?? 0)),
            ]),
            const SizedBox(height: 14),
            _kv(sz, '90 天平均可用率', _pct(avg90, digits: 2), strong: true,
                note: '缺记录的天按 0 计入分母'),
            if (worst != null)
              _kv(sz, '最差的一天', '$worstDay · ${_pct(worst, digits: 2)}',
                  danger: worst < 0.99),
            if (noRecord > 0)
              _warn(sz,
                  '90 天里有 $noRecord 天一条探针都没有。可能是那几天服务没起来,'
                  '也可能是探针本身还没上线——两种都不是「可用」,所以按 0 计。'),
            const SizedBox(height: 6),
            _stamp(sz, '${d?['note'] ?? ''}'),
          ],
        );
      },
    );
  }

  _Tone _toneOfAvailability(double v) => v >= 0.999
      ? _Tone.good
      : v >= 0.99
          ? _Tone.warn
          : _Tone.bad;

  // ------------------------------------------------------------------
  // 七 · 派单算法
  // ------------------------------------------------------------------

  Widget _dispatchSection() {
    final d = _dispatch.data;
    final weights = _list(d?['weights']);
    final labor = _map(d?['labor_guard']);
    final weather = _map(d?['weather']);
    return _Section(
      icon: Icons.alt_route_outlined,
      title: '派单算法',
      verdict: _dispatch.error != null
          ? _Verdict.dead
          : _dispatch.loading
              ? _Verdict.loading
              : _Verdict.ok,
      status: _dispatch.error != null
          ? '这项暂时取不到'
          : _dispatch.loading
              ? '正在取…'
              : '${weights.length} 个权重全部公开取值与理由',
      slot: _dispatch,
      onRetry: () => _fetch(_dispatch, widget.api.dispatchSpec),
      builder: (context) {
        final sz = Theme.of(context).sz;
        return Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            _plain(sz,
                '派单算法对骑手的意义,等同于账目对商家的意义——它决定骑手今天挣多少。'
                '下面这些数字**直接从排序代码的常量读出来**,不是另抄的一份文档,'
                '所以不会出现「说的和跑的不一样」。'),
            const SizedBox(height: 12),
            if (d?['formula'] != null) ...[
              SzLedgerCard(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text('${d!['formula']}',
                        style: TextStyle(
                            fontSize: 12.5,
                            height: 1.8,
                            color: Theme.of(context).sz.ink)),
                    const SizedBox(height: 6),
                    Text('${d['unit'] ?? ''}',
                        style: TextStyle(
                            fontSize: 11.5,
                            height: 1.7,
                            color: Theme.of(context).sz.inkMuted)),
                  ],
                ),
              ),
              const SizedBox(height: 12),
            ],
            for (final w in weights) ...[
              Wrap(
                crossAxisAlignment: WrapCrossAlignment.end,
                spacing: 8,
                runSpacing: 2,
                children: [
                  Text('${w['name']}',
                      style: TextStyle(
                          fontSize: 13.5,
                          fontWeight: FontWeight.w600,
                          color: sz.ink)),
                  Text('${w['value']}',
                      style: TextStyle(fontSize: 12.5, color: sz.inkMuted)),
                  if (w['cap'] != null)
                    Text('封顶 ${w['cap']}',
                        style: TextStyle(fontSize: 11.5, color: sz.inkFaint)),
                ],
              ),
              const SizedBox(height: 3),
              Text('${w['why']}',
                  style: TextStyle(
                      fontSize: 11.5, height: 1.65, color: sz.inkFaint)),
              const SizedBox(height: 10),
            ],
            if (labor.isNotEmpty) ...[
              const SzSectionTitle('劳动者保护红线'),
              const SizedBox(height: 6),
              _plain(sz, '${labor['principle'] ?? ''}'),
              const SizedBox(height: 6),
              _plain(sz, '${labor['why'] ?? ''}'),
              const SizedBox(height: 10),
            ],
            _bullets(sz, '我们承诺不做的事', _strs(d?['never_do'])),
            if (weather.isNotEmpty) ...[
              const SizedBox(height: 12),
              const SzSectionTitle('恶劣天气判定'),
              const SizedBox(height: 6),
              _plain(sz, '${weather['rule'] ?? ''}'),
              const SizedBox(height: 6),
              for (final t in _list(weather['thresholds']))
                _kv(sz, '${t['name']}', '${t['value']}'),
              const SizedBox(height: 4),
              _bullets(sz, '判为恶劣天气时', _strs(weather['on_severe'])),
            ],
            const SizedBox(height: 12),
            _changeLogList(sz, _list(d?['changelog']), bodyKey: 'what'),
          ],
        );
      },
    );
  }

  // ------------------------------------------------------------------
  // 八 · 明厨亮灶:难看的数字是 degraded,恰恰要放在最前面
  // ------------------------------------------------------------------

  Widget _kitchenSection() {
    final d = _kitchen.data;
    final cur = _map(d?['current']);
    final verify = _map(d?['how_we_verify']);
    final caps = _map(verify['capabilities']);
    final legal = _map(d?['legal_basis']);
    final coverage = _map(d?['coverage']);
    final degraded = _int(cur['degraded']);
    final active = _int(cur['active']);

    return _Section(
      icon: Icons.videocam_outlined,
      title: '明厨亮灶',
      verdict: _kitchen.error != null
          ? _Verdict.dead
          : _kitchen.loading
              ? _Verdict.loading
              : degraded > 0
                  ? _Verdict.warn
                  : _Verdict.ok,
      status: _kitchen.error != null
          ? '这项暂时取不到'
          : _kitchen.loading
              ? '正在取…'
              : '$active 家在线'
                  '${degraded > 0 ? ",$degraded 家装了但当前连不上" : ""}',
      slot: _kitchen,
      onRetry: () => _fetch(_kitchen, widget.api.kitchenCamSpec),
      builder: (context) {
        final sz = Theme.of(context).sz;
        return Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            _plain(sz,
                '平台在列表页给商家标「有明厨亮灶」,你据此下单——'
                '那这个标识怎么发、怎么验、什么情况下会撤,你有权知道。'),
            const SizedBox(height: 12),
            _kv(sz, '摄像头在线', '$active 家', strong: true),
            _kv(sz, '装了但连不上', '$degraded 家', danger: degraded > 0,
                note: '这些店在列表页显示的是「无明厨亮灶」'),
            _kv(sz, '待人工核验', '${_int(cur['pending'])} 家'),
            _kv(sz, '没装', '${_int(cur['none'])} 家'),
            if (cur['note'] != null) ...[
              const SizedBox(height: 6),
              _plain(sz, '${cur['note']}'),
            ],
            const SizedBox(height: 12),
            const SzSectionTitle('我们能验到哪一步'),
            const SizedBox(height: 6),
            Wrap(
              spacing: 6,
              runSpacing: 6,
              children: [
                _capChip(sz, '拉得到流', caps['reachability'] == true),
                _capChip(sz, '流还在推进', caps['stream_alive'] == true),
                _capChip(sz, '黑屏检测', caps['dark_frame'] == true),
                _capChip(sz, '画面静止检测', caps['still_frame'] == true),
              ],
            ),
            if (caps['note'] != null) ...[
              const SizedBox(height: 8),
              _plain(sz, '${caps['note']}'),
            ],
            const SizedBox(height: 8),
            _kv(sz, '探测间隔', '${_int(verify['interval_minutes'])} 分钟'),
            _kv(sz, '连续失败几次撤标',
                '${_int(verify['fail_streak_to_degrade'])} 次'),
            _kv(sz, '连续正常几次恢复',
                '${_int(verify['ok_streak_to_recover'])} 次'),
            if (verify['note'] != null) ...[
              const SizedBox(height: 6),
              _plain(sz, '${verify['note']}'),
            ],
            if (coverage.isNotEmpty) ...[
              const SizedBox(height: 12),
              const SzSectionTitle('拍什么 / 不拍什么'),
              const SizedBox(height: 6),
              _kv(sz, '应当覆盖', _strs(coverage['should_cover']).join('、')),
              _kv(sz, '一律不拍', _strs(coverage['must_not_cover']).join('、')),
              const SizedBox(height: 4),
              _plain(sz, '${coverage['why'] ?? ''}'),
            ],
            const SizedBox(height: 12),
            _bullets(sz, '我们承诺不做的事', _strs(d?['never_do'])),
            if (legal.isNotEmpty) ...[
              const SizedBox(height: 12),
              _stamp(sz,
                  '法定依据:${legal['issuer'] ?? ''}《${legal['regulation'] ?? ''}》,'
                  '${legal['effective'] ?? ''} 施行。${legal['retention'] ?? ''}'),
            ],
          ],
        );
      },
    );
  }

  Widget _capChip(SzColors sz, String label, bool on) =>
      SzChip(on ? '$label ✓' : '$label ✗',
          dense: true, color: on ? sz.earn : sz.danger);

  // ------------------------------------------------------------------
  // 九 · 治理留痕
  // ------------------------------------------------------------------

  Widget _governanceSection() {
    final d = _gov.data;
    final flags = _list(d?['flag_timeline']);
    final risk = _list(d?['risk_monthly']);
    final tickets = _list(d?['tickets_monthly']);
    final self = _map(d?['self_service_30d']);
    final anns = _list(d?['announcements']);

    return _Section(
      icon: Icons.gavel_outlined,
      title: '治理留痕',
      verdict: _gov.error != null
          ? _Verdict.dead
          : _gov.loading
              ? _Verdict.loading
              : flags.isEmpty
                  ? _Verdict.warn
                  : _Verdict.ok,
      status: _gov.error != null
          ? '这项暂时取不到'
          : _gov.loading
              ? '正在取…'
              : flags.isEmpty
                  ? '还没有开关变更记录'
                  : '${flags.length} 条规则变更 · ${anns.length} 条公告存档',
      slot: _gov,
      onRetry: () => _fetch(_gov, widget.api.governancePublic),
      builder: (context) {
        final sz = Theme.of(context).sz;
        return Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            _plain(sz,
                '规则可以改,但不能悄悄改。对你有感知的开关'
                '(天气加价、临时停运、深夜保护)每次变动都留痕并公开,'
                '记录自留痕表上线之日起,**不补历史**。'),
            const SizedBox(height: 10),
            if (flags.isEmpty)
              _warn(sz,
                  '还没有任何开关变更记录${d?['flags_since'] == null ? "" : "(留痕自 ${d!['flags_since']} 起)"}。'
                  '没记录就说没记录,不写成「运行平稳」。')
            else
              for (final f in flags.take(10))
                Padding(
                  padding: const EdgeInsets.only(bottom: 8),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Wrap(
                        crossAxisAlignment: WrapCrossAlignment.end,
                        spacing: 8,
                        runSpacing: 2,
                        children: [
                          Text('${f['label']}',
                              style: TextStyle(
                                  fontSize: 13,
                                  fontWeight: FontWeight.w600,
                                  color: sz.ink)),
                          Text('${f['old']} → ${f['new']}',
                              style: szFigure(
                                  fontSize: 12, color: sz.inkMuted)),
                          Text(_time(f['at']),
                              style:
                                  TextStyle(fontSize: 11, color: sz.inkFaint)),
                        ],
                      ),
                      if ('${f['reason'] ?? ''}'.isNotEmpty)
                        Text('${f['reason']}',
                            style: TextStyle(
                                fontSize: 11.5,
                                height: 1.6,
                                color: sz.inkFaint)),
                    ],
                  ),
                ),
            if (flags.length > 10)
              _stamp(sz, '仅显示最近 10 条,接口共下发 ${flags.length} 条'),
            if (risk.isNotEmpty) ...[
              const SizedBox(height: 12),
              const SzSectionTitle('反作弊处置(只有计数,绝无个案)'),
              const SizedBox(height: 6),
              for (final r in risk.take(6))
                _kv(sz, '${r['month']}',
                    '限制 ${_int(r['limited'])} · 冻结 ${_int(r['frozen'])} · '
                    '解除 ${_int(r['lifted'])} · 标记刷评 ${_int(r['reviews_flagged'])}'),
            ],
            if (tickets.isNotEmpty) ...[
              const SizedBox(height: 12),
              const SzSectionTitle('客服质量'),
              const SizedBox(height: 6),
              for (final t in tickets.take(6))
                _kv(sz, '${t['month']}',
                    '${_int(t['tickets'])} 单 · 首响 '
                    '${t['avg_first_reply_minutes'] == null ? "无回复记录" : "${_int(t['avg_first_reply_minutes'])} 分钟"} · '
                    '24 小时回复率 '
                    '${t['replied_24h_ratio'] == null ? "—" : _pct(_dbl(t['replied_24h_ratio']))}',
                    danger: t['replied_24h_ratio'] != null &&
                        (_dbl(t['replied_24h_ratio']) ?? 1) < 0.9),
            ],
            if (self.isNotEmpty) ...[
              const SizedBox(height: 12),
              _kv(sz, '近 30 天自助解决占比',
                  self['ratio'] == null ? '还没有工单' : _pct(_dbl(self['ratio'])),
                  note: '自助售后 ${_int(self['after_sales'])} 笔 / '
                      '人工工单 ${_int(self['tickets'])} 单'),
            ],
            const SizedBox(height: 10),
            _stamp(sz,
                '公告存档 ${anns.length} 条(含已过期)。发过的公告不会被删掉——'
                '删得掉的公示不叫公示。'),
          ],
        );
      },
    );
  }

  // ------------------------------------------------------------------
  // 十 · 版本与更新:线上跑的到底是哪一版代码
  // ------------------------------------------------------------------

  Widget _changelogSection() {
    final d = _changelog.data;
    final version = _map(d?['version']);
    final releases = _list(d?['releases']);
    final commits = _list(d?['commits']);
    final stale = d?['stale'] == true;

    return _Section(
      icon: Icons.history_outlined,
      title: '版本与更新',
      verdict: _changelog.error != null
          ? _Verdict.dead
          : _changelog.loading
              ? _Verdict.loading
              : stale
                  ? _Verdict.warn
                  : _Verdict.ok,
      status: _changelog.error != null
          ? '这项暂时取不到'
          : _changelog.loading
              ? '正在取…'
              : '线上运行 ${version['version'] ?? '未知'}'
                  '${stale ? " · 更新流是缓存的" : ""}',
      slot: _changelog,
      onRetry: () => _fetch(_changelog, widget.api.changelogPublic),
      builder: (context) {
        final sz = Theme.of(context).sz;
        return Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            _plain(sz,
                '平台的源码是公开的。这里的版本号和更新记录与源码仓一字不差——'
                '代码即承诺:说了什么规则,去仓库里能读到执行那条规则的那几行。'),
            const SizedBox(height: 12),
            _kv(sz, '线上运行版本', '${version['version'] ?? '未知'}', strong: true),
            if (version['deployed_at'] != null)
              _kv(sz, '部署时间', '${version['deployed_at']}'),
            _kv(sz, '源码仓库', '${d?['repo'] ?? '—'}'),
            if (stale)
              _warn(sz,
                  '更新流拉不到最新的(GitHub 没通),下面显示的是上一次成功的缓存。'
                  '标出来是因为:让你以为它是实时的,就是骗人。'),
            if (releases.isNotEmpty) ...[
              const SizedBox(height: 12),
              const SzSectionTitle('发版'),
              const SizedBox(height: 6),
              for (final r in releases.take(5))
                Padding(
                  padding: const EdgeInsets.only(bottom: 6),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Wrap(
                        spacing: 8,
                        runSpacing: 2,
                        crossAxisAlignment: WrapCrossAlignment.end,
                        children: [
                          Text('${r['tag']}',
                              style: szFigure(
                                  fontSize: 13,
                                  fontWeight: FontWeight.w600,
                                  color: sz.ink)),
                          Text(_time(r['published_at']),
                              style:
                                  TextStyle(fontSize: 11, color: sz.inkFaint)),
                        ],
                      ),
                      Text('${r['name']}',
                          style: TextStyle(
                              fontSize: 12, height: 1.6, color: sz.inkMuted)),
                    ],
                  ),
                ),
            ],
            if (commits.isNotEmpty) ...[
              const SizedBox(height: 12),
              const SzSectionTitle('最近提交'),
              const SizedBox(height: 6),
              for (final c in commits.take(10))
                Padding(
                  padding: const EdgeInsets.only(bottom: 6),
                  child: Row(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      // 短 sha 定宽给一点空间就够,正文用 Expanded 自己折行,
                      // 长辈版下也不会挤出屏幕
                      Text('${c['sha']}',
                          style: szFigure(fontSize: 11.5, color: sz.inkFaint)),
                      const SizedBox(width: 8),
                      Expanded(
                        child: Text('${c['message']}',
                            style: TextStyle(
                                fontSize: 12, height: 1.6, color: sz.inkMuted)),
                      ),
                    ],
                  ),
                ),
            ],
            if (d?['fetched_at'] != null) ...[
              const SizedBox(height: 8),
              _stamp(sz, '更新流拉取于 ${_time(d!['fetched_at'])}'),
            ],
          ],
        );
      },
    );
  }

  // ------------------------------------------------------------------
  // 小构件
  // ------------------------------------------------------------------

  /// 「一句人话」段落。用户不是会计,每个数字旁边都要有一句解释它意味着什么。
  Widget _plain(SzColors sz, String text) => Text(text,
      style: TextStyle(fontSize: 12, height: 1.75, color: sz.inkMuted));

  Widget _stamp(SzColors sz, String text) => Text(text,
      style: TextStyle(fontSize: 11, height: 1.6, color: sz.inkFaint));

  Widget _good(SzColors sz, String text) => _banner(sz, text, sz.earn);

  Widget _warn(SzColors sz, String text) => _banner(sz, text, sz.hold);

  Widget _bad(SzColors sz, String text) => _banner(sz, text, sz.danger);

  Widget _banner(SzColors sz, String text, Color color) => Container(
        width: double.infinity,
        padding: const EdgeInsets.all(10),
        decoration: BoxDecoration(
          color: color.withValues(alpha: .09),
          borderRadius: BorderRadius.circular(kRadiusSm),
          border: Border.all(color: color.withValues(alpha: .28)),
        ),
        child: Text(text,
            style: TextStyle(
                fontSize: 12, height: 1.7, fontWeight: FontWeight.w500,
                color: color)),
      );

  /// 「标签 — 数值」行。左侧标签用 Expanded、右侧数值用 Flexible,
  /// 两边都能折行——长辈版 1.4× 下这是不溢出的关键。
  Widget _kv(SzColors sz, String label, String value,
      {String? note, bool danger = false, bool strong = false}) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Expanded(
                child: Text(label,
                    style: TextStyle(
                        fontSize: 12.5, height: 1.5, color: sz.inkMuted)),
              ),
              const SizedBox(width: 12),
              Flexible(
                child: Text(value,
                    textAlign: TextAlign.right,
                    style: szMoney(
                        fontSize: strong ? 15 : 13,
                        fontWeight:
                            strong ? FontWeight.w700 : FontWeight.w600,
                        height: 1.5,
                        color: danger ? sz.danger : sz.ink)),
              ),
            ],
          ),
          if (note != null && note.isNotEmpty)
            Padding(
              padding: const EdgeInsets.only(top: 2),
              child: Text(note,
                  style: TextStyle(
                      fontSize: 11, height: 1.6, color: sz.inkFaint)),
            ),
        ],
      ),
    );
  }

  Widget _bullets(SzColors sz, String title, List<String> lines) {
    if (lines.isEmpty) return const SizedBox.shrink();
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        SzSectionTitle(title),
        const SizedBox(height: 6),
        for (final line in lines)
          Padding(
            padding: const EdgeInsets.only(bottom: 6),
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text('—', style: TextStyle(color: sz.inkFaint)),
                const SizedBox(width: 8),
                Expanded(
                  child: Text(line,
                      style: TextStyle(
                          fontSize: 12, height: 1.7, color: sz.inkMuted)),
                ),
              ],
            ),
          ),
      ],
    );
  }

  /// 规则变更历史。dispatch 用 `what` 键、kitchen-cam 用 `change` 键,
  /// 两边字段名没统一,所以正文键由调用方传进来。
  Widget _changeLogList(SzColors sz, List<Map<String, dynamic>> items,
      {required String bodyKey}) {
    if (items.isEmpty) return const SizedBox.shrink();
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const SzSectionTitle('规则改动留痕'),
        const SizedBox(height: 6),
        for (final c in items)
          Padding(
            padding: const EdgeInsets.only(bottom: 8),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text('${c['date']}',
                    style: szFigure(fontSize: 12, color: sz.inkFaint)),
                Text('${c[bodyKey] ?? c['change'] ?? c['what'] ?? ''}',
                    style: TextStyle(
                        fontSize: 12, height: 1.7, color: sz.ink)),
                if ('${c['why'] ?? ''}'.isNotEmpty)
                  Text('${c['why']}',
                      style: TextStyle(
                          fontSize: 11.5, height: 1.65, color: sz.inkFaint)),
              ],
            ),
          ),
      ],
    );
  }

  /// 90 格色带。格子是固定尺寸的纯色块(里面没有文字),
  /// 所以长辈版放大字号也撑不破;Wrap 保证窄屏自动换行。
  Widget _strip(SzColors sz, List<_Cell> cells) => Wrap(
        spacing: 2,
        runSpacing: 2,
        children: [
          for (final c in cells)
            Container(
              width: 7,
              height: 16,
              decoration: BoxDecoration(
                color: _colorOf(sz, c.tone),
                borderRadius: BorderRadius.circular(1.5),
              ),
            ),
        ],
      );

  Widget _stripLegend(SzColors sz, List<(String, _Tone)> items) => Wrap(
        spacing: 12,
        runSpacing: 4,
        children: [
          for (final (label, tone) in items)
            Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                Container(
                    width: 7,
                    height: 10,
                    decoration: BoxDecoration(
                        color: _colorOf(sz, tone),
                        borderRadius: BorderRadius.circular(1.5))),
                const SizedBox(width: 4),
                Text(label,
                    style: TextStyle(fontSize: 11, color: sz.inkFaint)),
              ],
            ),
        ],
      );

  Color _colorOf(SzColors sz, _Tone tone) => switch (tone) {
        _Tone.good => sz.earn,
        _Tone.warn => sz.hold,
        _Tone.bad => sz.danger,
        // 「没有记录」用一条中性灰,不用绿色——把缺档画成绿色就是撒谎
        _Tone.none => sz.line,
      };

  // ------------------------------------------------------------------
  // 取值与格式化
  // ------------------------------------------------------------------

  /// 最近 n 天的日历(含今天),YYYY-MM-DD。
  ///
  /// 服务端按北京时间分日,用户端跑在中国大陆也是 UTC+8,直接用本地日期即可;
  /// 万一时区不同,最多是首尾多一格「没记录」——宁可多报一格缺档,
  /// 也不能把没记录的那天算成正常。
  List<String> _calendar(int n) {
    final today = DateTime.now();
    String two(int v) => v.toString().padLeft(2, '0');
    return [
      for (var i = n - 1; i >= 0; i--)
        () {
          final d = today.subtract(Duration(days: i));
          return '${d.year}-${two(d.month)}-${two(d.day)}';
        }(),
    ];
  }

  int _int(dynamic v) => v is num ? v.round() : 0;

  double? _dbl(dynamic v) => v is num ? v.toDouble() : null;

  Map<String, dynamic> _map(dynamic v) =>
      v is Map ? v.cast<String, dynamic>() : const <String, dynamic>{};

  List<Map<String, dynamic>> _list(dynamic v) => v is List
      ? [for (final e in v) if (e is Map) e.cast<String, dynamic>()]
      : const [];

  List<String> _strs(dynamic v) =>
      v is List ? [for (final e in v) '$e'] : const [];

  /// 金额一律精确到分并带千分位——这一页的口号是「差一分钱都要看得见」,
  /// 取整显示会把差错抹掉。
  String _yuan(int cents) {
    final neg = cents < 0;
    final abs = cents.abs();
    final intPart = (abs ~/ 100).toString();
    final buf = StringBuffer();
    for (var i = 0; i < intPart.length; i++) {
      if (i > 0 && (intPart.length - i) % 3 == 0) buf.write(',');
      buf.write(intPart[i]);
    }
    return '${neg ? '−' : ''}¥$buf.${(abs % 100).toString().padLeft(2, '0')}';
  }

  String _pct(double? ratio, {int digits = 2}) =>
      ratio == null ? '—' : '${(ratio * 100).toStringAsFixed(digits)}%';

  /// per100 的四个数服务端已经四舍五入到 0.1,这里原样显示,不再二次加工。
  String _fx(dynamic v) => (_dbl(v) ?? 0).toStringAsFixed(1);

  /// ISO 时间 → 本地「MM-DD HH:mm」。解析不了就原样回显,不吞掉。
  String _time(dynamic iso) {
    if (iso == null) return '';
    final t = DateTime.tryParse('$iso')?.toLocal();
    if (t == null) return '$iso';
    String two(int v) => v.toString().padLeft(2, '0');
    return '${two(t.month)}-${two(t.day)} ${two(t.hour)}:${two(t.minute)}';
  }
}

enum _Tone { good, warn, bad, none }

class _Cell {
  const _Cell(this.tone);
  final _Tone tone;
}

/// 可折叠区块。
///
/// 没直接用 [ExpansionTile] 是因为它的 trailing 在长辈版 1.4× 下会把标题挤扁;
/// 这里把标题、状态、箭头拆成两行,状态文字独占整行随便折行。
class _Section extends StatefulWidget {
  const _Section({
    required this.icon,
    required this.title,
    required this.status,
    required this.verdict,
    required this.slot,
    required this.builder,
    required this.onRetry,
    this.initiallyExpanded = false,
  });

  final IconData icon;
  final String title;

  /// 折叠状态下也必须能读到的一句结论(红灯藏在里面就等于没亮)。
  final String status;
  final _Verdict verdict;
  final _Slot slot;
  final WidgetBuilder builder;
  final VoidCallback onRetry;
  final bool initiallyExpanded;

  @override
  State<_Section> createState() => _SectionState();
}

class _SectionState extends State<_Section> {
  late bool _open = widget.initiallyExpanded;

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    final color = switch (widget.verdict) {
      _Verdict.ok => sz.earn,
      _Verdict.warn => sz.hold,
      _Verdict.bad => sz.danger,
      _Verdict.dead => sz.inkFaint,
      _Verdict.loading => sz.inkFaint,
    };

    return Padding(
      padding: const EdgeInsets.only(bottom: 10),
      child: SzCard(
        padding: EdgeInsets.zero,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            InkWell(
              onTap: () => setState(() => _open = !_open),
              child: Padding(
                padding: const EdgeInsets.all(kCardPad),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(
                      children: [
                        Icon(widget.icon, size: 18, color: color),
                        const SizedBox(width: 9),
                        Expanded(
                          child: Text(widget.title,
                              style: TextStyle(
                                  fontSize: 15,
                                  fontWeight: FontWeight.w600,
                                  color: sz.ink)),
                        ),
                        const SizedBox(width: 6),
                        Icon(_open ? Icons.expand_less : Icons.expand_more,
                            size: 20, color: sz.inkFaint),
                      ],
                    ),
                    const SizedBox(height: 4),
                    Text(widget.status,
                        style: TextStyle(
                            fontSize: 12, height: 1.55, color: color)),
                  ],
                ),
              ),
            ),
            if (_open)
              Padding(
                padding: const EdgeInsets.fromLTRB(
                    kCardPad, 0, kCardPad, kCardPad),
                child: widget.slot.loading
                    // 加载中用共享库的骨架屏。SkeletonList 内部是 ListView,
                    // 放进 Column 必须给定高(每项 72)
                    ? const SizedBox(
                        height: 144, child: SkeletonList(itemCount: 2))
                    : widget.slot.error != null
                        ? SzError(
                            error: '这项暂时取不到。\n${widget.slot.error}',
                            onRetry: widget.onRetry)
                        : widget.builder(context),
              ),
          ],
        ),
      ),
    );
  }
}
