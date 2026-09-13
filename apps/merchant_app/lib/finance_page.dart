import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';

import 'dart:convert';
import 'dart:typed_data';

import 'package:share_plus/share_plus.dart';

import 'analytics_page.dart';
import 'invoice_page.dart';
import 'merchant_ui.dart';

/// 提现记录一行:状态用 chip,红色只留给驳回/失败。
///
/// 对账页(只列最近几条)和「全部提现记录」页共用 —— 两处各写一遍的话,
/// 哪天改了颜色规则只改一处,同一笔提现在两页会是两种颜色。
Widget withdrawalRow(BuildContext context, Withdrawal w) {
  final sz = Theme.of(context).sz;
  final color = switch (w.status) {
    'paid' => sz.earn,
    'rejected' || 'failed' => sz.danger,
    _ => sz.hold,
  };
  return Padding(
    padding: const EdgeInsets.symmetric(horizontal: kCardPad, vertical: 11),
    child: Row(children: [
      Expanded(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(yuan(w.amountCents),
                style: szMoney(fontSize: kFontBody, color: sz.ink)),
            const SizedBox(height: 2),
            Text(
                szTimeAgo(w.createdAt) +
                    (w.rejectReason.isEmpty ? '' : ' · ${w.rejectReason}'),
                style: TextStyle(fontSize: kFontMicro, color: sz.inkMuted)),
          ],
        ),
      ),
      SzChip(w.statusLabel, color: color, dense: true),
    ]),
  );
}

/// 账本(设计稿 6g):一段时间的实收台面 + 按日结算表;下面是钱包、费率档位、
/// 对账工具、提现记录。点某一天看逐单明细。
///
/// ## 和设计稿不一样的地方
///
/// - 稿子每天一行后面有「已到卡 / 明日到卡」:服务端没有「哪一天的钱哪天到卡」
///   这个数(提现是商家自己点、按笔打款的,不按天),**不编**,那一列去掉;
/// - 稿子的第三个页签是「全部」:日账单接口最多给 90 天(服务端 min(days, 90)),
///   所以照实叫「近 90 天」。
class FinancePage extends StatefulWidget {
  const FinancePage({
    super.key,
    required this.api,
    this.title,
    this.active = true,
  });

  final ApiClient api;

  /// 标题行左边的字(外卖工作台传「账本」)。住宿工作台外层的 AppBar
  /// 已经写着「对账」,不传就只留右边的月份页签
  final String? title;

  /// 这一页是不是当前 tab。从别的 tab 切回来时悄悄刷一遍(数字从旧值滚到新值,
  /// 不从 0 重播 —— 动效规范 09)
  final bool active;

  @override
  State<FinancePage> createState() => _FinancePageState();
}

class _FinancePageState extends State<FinancePage> {
  /// 近 90 天的日账单(服务端上限),按日期倒序
  List<DayStat>? _daily;
  Wallet? _wallet;

  /// 提现打到哪张卡。拉不到只是少一行字,不拦着看账
  PayoutAccount? _payout;

  /// 按日账单默认只出 7 行(#33 4.3):一个月 30 行在真机上约 3 屏,
  /// 会把下面的钱包、提现记录挤到很远。更早的一按就出来,一条都不少
  static const _kDefaultDays = 7;
  bool _showAllDays = false;
  Map<String, dynamic>? _tier;
  List<Withdrawal> _withdrawals = [];

  /// 0 本月 / 1 上月 / 2 近 90 天
  int _period = 0;

  /// 下拉刷新时加一:台面数字、分账条从 0 再播一次(规范 09)
  int _replay = 0;

  /// 非空 = 上一次加载失败。空列表和加载失败不能长得一样
  String _error = '';

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void didUpdateWidget(covariant FinancePage old) {
    super.didUpdateWidget(old);
    if (widget.active && !old.active) _load();
  }

  /// 五块数据一起拉。
  ///
  /// 原来是五个 `await` 排成一队 —— 互不依赖却要等五个来回,
  /// 店里网不好的时候点开「财务」就是几秒白屏。
  ///
  /// **各自兜底**:钱包和流水是这一页的主角,拉不到要报错;
  /// 费率档、收款账户是附加信息,挂了不该把整页打回错误态 ——
  /// 商家来这一页多半是要看钱、要提现。
  Future<void> _load() async {
    // 先全部发出去,这一步不能 await,否则又串回去了
    final dailyF = widget.api.financeDaily(days: 90);
    final walletF = widget.api.merchantWallet();
    final withdrawalsF = widget.api.merchantWithdrawals();
    final tierF = widget.api.merchantCommissionTier();
    final payoutF = widget.api.payoutAccount();

    final g = SzGather();
    final daily = await g.take(dailyF);
    final wallet = await g.take(walletF);
    final withdrawals = await g.take(withdrawalsF);
    final tier = await g.soft(tierF, _tier);
    final payout = await g.soft<PayoutAccount?>(payoutF, _payout);

    if (!mounted) return;
    if (g.failed) {
      setState(() => _error = g.message);
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(g.message)));
      return;
    }
    setState(() {
      _error = '';
      _daily = daily;
      _wallet = wallet;
      _withdrawals = withdrawals!;
      _tier = tier;
      _payout = payout;
    });
  }

  Future<void> _pull() async {
    setState(() => _replay++);
    await _load();
  }

  /// 提现:输入金额 → 提交申请 → T+1 打款
  Future<void> _withdraw() async {
    final wallet = _wallet;
    if (wallet == null) return;
    // 没设收款账户时先去设 —— 提交了也打不出去
    if (_payout != null && !_payout!.configured) {
      await Navigator.of(context).push(MaterialPageRoute(
          builder: (_) => PayoutAccountPage(api: widget.api)));
      _load();
      return;
    }
    if (wallet.withdrawableCents < 1000) {
      ScaffoldMessenger.of(context)
          .showSnackBar(const SnackBar(content: Text('满 ¥10 可提现')));
      return;
    }
    final controller = TextEditingController(
        text: (wallet.withdrawableCents / 100).toStringAsFixed(2));
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => SzDialog(
        title: const Text('申请提现'),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('可提现 ${yuan(wallet.withdrawableCents)},今天申请明天到账,零手续费',
                style: Theme.of(context).textTheme.bodySmall),
            const SizedBox(height: 12),
            TextField(
              controller: controller,
              keyboardType:
                  const TextInputType.numberWithOptions(decimal: true),
              decoration: const InputDecoration(
                  labelText: '提现金额(元)', border: OutlineInputBorder()),
            ),
          ],
        ),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(context, false),
              child: const Text('取消')),
          FilledButton(
              onPressed: () => Navigator.pop(context, true),
              child: const Text('提交')),
        ],
      ),
    );
    if (confirmed != true || !mounted) return;
    final amount = ((double.tryParse(controller.text) ?? 0) * 100).round();
    try {
      await widget.api.requestMerchantWithdrawal(amount);
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('提现申请已提交,T+1 打款')));
      _load();
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(e.toString())));
    }
  }

  /// 导出对账单(CSV):选月份 → 拉 → 系统分享面板。
  Future<void> _exportStatement() async {
    final now = DateTime.now();
    final months = [
      for (var i = 0; i < 6; i++) DateTime(now.year, now.month - i)
    ];
    final month = await szShowSheet<String>(
      context: context,
      builder: (context) => SafeArea(
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          for (final m in months)
            ListTile(
              title: Text('${m.year}-${m.month.toString().padLeft(2, '0')}'),
              onTap: () => Navigator.pop(
                  context, '${m.year}-${m.month.toString().padLeft(2, '0')}'),
            ),
        ]),
      ),
    );
    if (month == null || !mounted) return;
    try {
      final csv = await widget.api.merchantStatementCsv(month);
      await SharePlus.instance.share(ShareParams(files: [
        XFile.fromData(Uint8List.fromList(utf8.encode(csv)),
            mimeType: 'text/csv', name: 'statement-$month.csv'),
      ]));
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(e.toString())));
    }
  }

  // ───────────────────────── 期间与口径 ─────────────────────────

  /// 这一期从哪天到哪天(本地日历日)。
  ///
  /// 「近 90 天」取**今天往前数 90 个整天**:接口按 `now() - 90 天` 滚动取数,
  /// 最早那一天只取到了一部分 —— 那一行照原样放进来,总数就小了一截还说不清,
  /// 所以直接不要它。
  (DateTime, DateTime) _rangeOf(int period) {
    final now = DateTime.now();
    final today = DateTime(now.year, now.month, now.day);
    return switch (period) {
      0 => (DateTime(now.year, now.month, 1), today),
      // DateTime(y, m, 0) = 上个月最后一天
      1 => (DateTime(now.year, now.month - 1, 1), DateTime(now.year, now.month, 0)),
      _ => (today.subtract(const Duration(days: 89)), today),
    };
  }

  List<DayStat> _daysIn(List<DayStat> all, DateTime from, DateTime to) => [
        for (final d in all)
          if (DateTime.tryParse(d.day) case final t?
              when !t.isBefore(from) && !t.isAfter(to))
            d,
      ];

  String _rangeLabel(DateTime from, DateTime to) => from.month == to.month
      ? '${from.month} 月 ${from.day} 日 — ${to.day} 日'
      : '${from.month} 月 ${from.day} 日 — ${to.month} 月 ${to.day} 日';

  /// 这一期平台实际抽了几个点:**按这一期的数算**(抽成 ÷ 菜价),
  /// 不照搬当前档位 —— 每月 1 日按上月单量重算档位,上个月的账不一定是
  /// 现在这一档;团购核销那 2% 也混在里面。没有流水时退回当前档位。
  ///
  /// 格式化不许截断:`0.045 * 100 ~/ 1 == 4`,4.5% 的店曾在这里看到「4%」。
  String _rateOf(int food, int commission) {
    final rate = food > 0
        ? commission / food
        : ((_tier?['commission_rate'] as num?) ?? 0.05).toDouble();
    return pctLabel(rate);
  }

  /// 整元就不带「.00」(表格里扫读用);有零头照原样两位,一分不省
  static String _yuanTrim(int cents) =>
      cents % 100 == 0 ? szYuanText(cents, '¥', 0) : szYuanText(cents);

  // ───────────────────────── 各块 ─────────────────────────

  /// 标题行:账本 + 月份页签(设计稿 6g)。页签是「看哪一段」,不是导航
  Widget _header() {
    final now = DateTime.now();
    final prev = DateTime(now.year, now.month - 1);
    return SizedBox(
      height: 56,
      child: Padding(
        padding: const EdgeInsets.fromLTRB(kPagePad, 0, 10, 0),
        child: Row(children: [
          Expanded(
            child: widget.title == null
                ? const SizedBox.shrink()
                : Text(widget.title!,
                    style: Theme.of(context).appBarTheme.titleTextStyle),
          ),
          SzTextTabs(
            labels: ['${now.month} 月', '${prev.month} 月', '近 90 天'],
            index: _period,
            onChanged: (i) => setState(() {
              _period = i;
              _showAllDays = false;
            }),
          ),
        ]),
      ),
    );
  }

  /// 台面:这一期的实收 + 分账条 + 菜价/平台/配送费/推广位 + 可提现。
  ///
  /// 「菜价 − 平台 = 实收」这个等式闭合在台面上 —— 账目透明的表达就是它。
  /// 配送费抽、推广位两格恒为 0 是**结构上的**:配送费全额归骑手,
  /// 平台不卖排名位。写出来是因为同行都在收这两笔。
  Widget _ledger(List<DayStat> days, DateTime from, DateTime to) {
    final food = days.fold<int>(0, (s, d) => s + d.foodCents);
    final commission = days.fold<int>(0, (s, d) => s + d.commissionCents);
    final net = days.fold<int>(0, (s, d) => s + d.netCents);
    final wallet = _wallet;
    final payout = _payout;
    return SzLedgerCard(
      padding: const EdgeInsets.fromLTRB(18, 16, 18, 10),
      // 台面在内部把 SzColors 换成了深色那一套,颜色必须在台面**里面**取
      child: Builder(builder: (context) {
        final sz = Theme.of(context).sz;
        final label = TextStyle(
            fontSize: kFontMicro, letterSpacing: 1, color: sz.inkMuted);
        Widget cell(String name, String value, {Color? tone}) => Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              mainAxisSize: MainAxisSize.min,
              children: [
                Text(name,
                    style: TextStyle(fontSize: kFontNote, color: sz.inkMuted)),
                const SizedBox(height: 2),
                Text(value,
                    style: szMoney(
                        fontSize: kFontNote,
                        fontWeight: FontWeight.w400,
                        color: tone ?? sz.ink)),
              ],
            );
        // 可提现和打到哪张卡分两行:挤成一行在 390 宽上会折得乱七八糟
        final String payoutLine;
        if (payout != null && !payout.configured) {
          payoutLine = '还没设收款账户,点这里去设';
        } else if (payout != null) {
          final bank =
              payout.bankName.isNotEmpty ? payout.bankName : payout.kindLabel;
          // 尾号和数字之间用不换行空格:开户行名字长,折行时别把「尾号」和
          // 四位数拆到两行
          payoutLine = 'T+1 到 $bank 尾号\u00a0${payout.accountTail}';
        } else {
          payoutLine = '提现 T+1 到卡';
        }
        return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text('${_rangeLabel(from, to)} · 实收', style: label),
          const SizedBox(height: 6),
          // 规范 09:0 → 终值 900ms;换月份是从上一个数滚到下一个数,
          // 下拉刷新才从 0 再滚
          SzRollingAmount(
            cents: net,
            replayKey: _replay,
            style: szMoney(
                fontSize: kFigureXl,
                fontWeight: FontWeight.w600,
                color: sz.earn,
                height: 1.15),
          ),
          const SizedBox(height: 14),
          SzSplitBar(
            parts: [
              SzSplitPart(net, sz.earn),
              SzSplitPart(commission, sz.hold),
            ],
            height: 8,
            gap: 2,
            replayKey: _replay,
          ),
          const SizedBox(height: 10),
          Wrap(spacing: 16, runSpacing: 8, children: [
            cell('菜价', _yuanTrim(food)),
            cell('平台 ${_rateOf(food, commission)}', szYuanText(commission),
                tone: sz.hold),
            cell('配送费抽', '¥0'),
            cell('推广位', '¥0'),
          ]),
          const SizedBox(height: 12),
          Divider(height: 1, color: sz.line),
          Row(children: [
            Expanded(
              child: InkWell(
                onTap: wallet == null ? null : _withdraw,
                child: Padding(
                  padding: const EdgeInsets.symmetric(vertical: 10),
                  child: Row(children: [
                    Container(
                      width: 7,
                      height: 7,
                      decoration:
                          BoxDecoration(color: sz.earn, shape: BoxShape.circle),
                    ),
                    const SizedBox(width: 8),
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text.rich(
                              TextSpan(children: [
                                const TextSpan(text: '可提现 '),
                                TextSpan(
                                    text: wallet == null
                                        ? '—'
                                        : szYuanText(wallet.withdrawableCents),
                                    style: szMoney(
                                        fontSize: kFontBody, color: sz.ink)),
                              ]),
                              style: TextStyle(
                                  fontSize: kFontNote, color: sz.inkMuted)),
                          Text(payoutLine,
                              style: TextStyle(
                                  fontSize: kFontNote, color: sz.inkMuted)),
                        ],
                      ),
                    ),
                  ]),
                ),
              ),
            ),
            TextButton(
              onPressed: _exportStatement,
              style: TextButton.styleFrom(
                foregroundColor: sz.clay,
                minimumSize: const Size(0, 40),
                padding: const EdgeInsets.symmetric(horizontal: 6),
                visualDensity: VisualDensity.standard,
                textStyle: buttonText(kFontNote, weight: FontWeight.w500),
              ),
              child: const Text('导出对账单'),
            ),
          ]),
        ]);
      }),
    );
  }

  /// 按日结算表(设计稿 6g):日期 / 菜价 · 单数 / 平台 / 实收。
  ///
  /// 表头和行用**同一组列宽**、同一个左边距 —— 稿子上表头比行靠左 15px,
  /// 扫一列数字时眼睛要错位。宽屏(≥620)把单数拆成单独一列。
  Widget _dayTable(List<DayStat> days, {required bool wide}) {
    final sz = Theme.of(context).sz;
    const inset = EdgeInsets.symmetric(horizontal: kCardPad);
    final head = TextStyle(
        fontSize: kFontMicro, letterSpacing: .5, color: sz.inkMuted);
    Widget headRow() => Padding(
          padding: const EdgeInsets.fromLTRB(1, 16, 1, 6),
          child: Padding(
            padding: inset,
            child: Row(children: [
              SizedBox(width: 56, child: Text('日期', style: head)),
              if (wide) ...[
                SizedBox(width: 64, child: Text('单数', style: head)),
                Expanded(child: Text('菜价', style: head)),
              ] else
                Expanded(child: Text('菜价 · 单数', style: head)),
              SizedBox(
                  width: 76,
                  child: Text('平台', textAlign: TextAlign.right, style: head)),
              SizedBox(
                  width: 88,
                  child: Text('实收', textAlign: TextAlign.right, style: head)),
            ]),
          ),
        );
    Widget row(DayStat d, bool last) {
      final t = DateTime.tryParse(d.day);
      return InkWell(
        onTap: () => Navigator.of(context).push(MaterialPageRoute(
            builder: (_) => DayOrdersPage(api: widget.api, stat: d))),
        child: Container(
          padding: const EdgeInsets.fromLTRB(kCardPad, 11, kCardPad, 11),
          decoration: BoxDecoration(
            border:
                last ? null : Border(bottom: BorderSide(color: sz.line)),
          ),
          child: Row(children: [
            SizedBox(
              width: 56,
              child: Text(t == null ? d.day : '${t.month}/${t.day}',
                  style: szMoney(
                      fontSize: kFontBody,
                      fontWeight: FontWeight.w600,
                      color: sz.ink)),
            ),
            if (wide) ...[
              SizedBox(
                width: 64,
                child: Text('${d.orderCount} 单',
                    style: TextStyle(fontSize: kFontNote, color: sz.inkMuted)),
              ),
              Expanded(
                child: Text(_yuanTrim(d.foodCents),
                    style: szMoney(
                        fontSize: kFontBody,
                        fontWeight: FontWeight.w400,
                        color: sz.ink)),
              ),
            ] else
              Expanded(
                child: Text('${_yuanTrim(d.foodCents)} · ${d.orderCount} 单',
                    style: TextStyle(fontSize: kFontNote, color: sz.inkMuted)),
              ),
            // 平台抽走的:和台面上一个口径,hold 琥珀,不是绿
            SizedBox(
              width: 76,
              child: Text(szYuanText(d.commissionCents),
                  textAlign: TextAlign.right,
                  style: szMoney(
                      fontSize: kFontBody,
                      fontWeight: FontWeight.w400,
                      color: sz.hold)),
            ),
            SizedBox(
              width: 88,
              child: Text(szYuanText(d.netCents),
                  textAlign: TextAlign.right,
                  style: szMoney(
                      fontSize: kFontBody,
                      fontWeight: FontWeight.w600,
                      color: sz.earn)),
            ),
          ]),
        ),
      );
    }

    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      headRow(),
      Container(
        decoration: BoxDecoration(
          color: sz.surface,
          borderRadius: BorderRadius.circular(kRadiusMd),
          border: Border.all(color: sz.line),
        ),
        clipBehavior: Clip.antiAlias,
        child: Column(children: [
          for (final (i, d) in days.indexed) row(d, i == days.length - 1),
        ]),
      ),
    ]);
  }

  Widget _walletMetric(String label, int cents) {
    final sz = Theme.of(context).sz;
    // 四格等分,一格只有七十来宽:带千分位、放不下就缩,不折行
    // (「¥176564.8」+ 下一行一个「6」是真机上见过的)
    return Expanded(
      child: Column(children: [
        FittedBox(
          fit: BoxFit.scaleDown,
          child: Text(szYuanText(cents),
              maxLines: 1,
              style: szMoney(
                  fontSize: kFontBodyLg,
                  fontWeight: FontWeight.w600,
                  color: sz.ink)),
        ),
        const SizedBox(height: 2),
        Text(label,
            textAlign: TextAlign.center,
            style: TextStyle(fontSize: kFontMicro, color: sz.inkMuted)),
      ]),
    );
  }

  /// 钱包:可提现 + 四个分项 + 提现按钮。
  ///
  /// 台面底下那一行也能点进提现;这张卡在,是因为「钱怎么变成可提现的」
  /// 那四个数(累计、提现中、已提现、保证金)只有这里有。
  Widget _walletCard(Wallet wallet) {
    final sz = Theme.of(context).sz;
    return SzCard(
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            crossAxisAlignment: CrossAxisAlignment.baseline,
            textBaseline: TextBaseline.alphabetic,
            children: [
              Expanded(
                child: Text('可提现余额',
                    style: TextStyle(fontSize: kFontNote, color: sz.inkMuted)),
              ),
              Text(szYuanText(wallet.withdrawableCents),
                  style: szMoney(
                      fontSize: kFigureLg,
                      fontWeight: FontWeight.w600,
                      color: sz.earn)),
            ],
          ),
          const SizedBox(height: 2),
          Text('外卖净额 + 团购核销净额 − 保证金留存',
              style: TextStyle(fontSize: kFontMicro, color: sz.inkMuted)),
          const SizedBox(height: 14),
          Row(
            children: [
              _walletMetric('累计收入', wallet.totalEarnedCents),
              _walletMetric('提现中', wallet.pendingWithdrawalCents),
              _walletMetric('已提现', wallet.withdrawnCents),
              _walletMetric('保证金', wallet.depositHeldCents),
            ],
          ),
          if (wallet.depositHeldCents < wallet.depositRequiredCents)
            Padding(
              padding: const EdgeInsets.only(top: 10),
              child: Text(
                  '保证金 ${yuan(wallet.depositHeldCents)}/${yuan(wallet.depositRequiredCents)}:'
                  '从营收自动留存,攒够后超出部分即可全额提现;退店无纠纷全额退还',
                  style: TextStyle(
                      fontSize: kFontMicro, height: 1.5, color: sz.inkMuted)),
            ),
          const SizedBox(height: 14),
          SizedBox(
            width: double.infinity,
            child: FilledButton(
              onPressed: wallet.withdrawableCents >= 1000 ? _withdraw : null,
              child: const Text('提现 · T+1 到账,零手续费'),
            ),
          ),
          if (wallet.withdrawableCents < 1000)
            Padding(
              padding: const EdgeInsets.only(top: 6),
              child: Text('满 ¥10 可提现',
                  textAlign: TextAlign.center,
                  style: TextStyle(fontSize: kFontMicro, color: sz.inkMuted)),
            ),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final daily = _daily;
    final sz = Theme.of(context).sz;
    if (daily == null) {
      // 拉失败就说清楚并给重试 —— 转个没头的圈,商家只能杀进程重开
      return Column(children: [
        _header(),
        Expanded(
          child: _error.isNotEmpty
              ? SzError(error: _error, onRetry: _load)
              : const Center(child: CircularProgressIndicator()),
        ),
      ]);
    }
    final (from, to) = _rangeOf(_period);
    final days = _daysIn(daily, from, to);
    final shownDays =
        _showAllDays ? days : days.take(_kDefaultDays).toList();

    // ① 台面 + ② 按日结算表(每天要问的那两件事)
    final ledgerBlock = <Widget>[
      _ledger(days, from, to),
      LayoutBuilder(builder: (context, c) {
        if (days.isEmpty) {
          return const Padding(
            padding: EdgeInsets.only(top: 12),
            child: SzEmpty(
                art: BrandArt.receipt,
                text: '这段时间还没有入账记录\n订单完成后会出现在这里'),
          );
        }
        return _dayTable(shownDays, wide: c.maxWidth >= 620);
      }),
      if (!_showAllDays && days.length > _kDefaultDays)
        Padding(
          padding: const EdgeInsets.only(top: 8),
          child: OutlinedButton(
            onPressed: () => setState(() => _showAllDays = true),
            child: Text('看更早的 ${days.length - _kDefaultDays} 天'),
          ),
        ),
      const SizedBox(height: 18),
    ];
    // ③ 钱包
    final wallet = <Widget>[
      if (_wallet != null) ...[
        _walletCard(_wallet!),
        const SizedBox(height: 12),
      ],
    ];
    // ④ 阶梯佣金
    final tier = <Widget>[
      if (_tier != null) ...[
        // 阶梯佣金:单量越大费率越低,5% 永远是上限,只降不升
        SzCard(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(children: [
                Text('阶梯佣金',
                    style: TextStyle(
                        fontSize: kFontBodyLg,
                        fontWeight: FontWeight.w600,
                        color: sz.ink)),
                const Spacer(),
                // 费率是"被抽走的",用 hold 不用强调色
                Text(pctLabel((_tier!['commission_rate'] as num).toDouble()),
                    style: szFigure(
                        fontSize: kFontLead,
                        fontWeight: FontWeight.w600,
                        color: sz.hold)),
              ]),
              const SizedBox(height: 6),
              Text(
                '上月完成 ${_tier!['last_month_completed']} 单 · '
                '本月已完成 ${_tier!['this_month_completed']} 单'
                '${_tier!['next_tier_from'] != null ? " · 本月再完成 ${_tier!['orders_to_next']} 单,下月降至 ${pctLabel((_tier!['next_tier_rate'] as num).toDouble())}" : " · 已是最低档"}',
                style: TextStyle(
                    fontSize: kFontNote, height: 1.55, color: sz.inkMuted),
              ),
              const SizedBox(height: 3),
              Text('每月 1 日按上月单量自动重算,只降不升;5% 永远是上限',
                  style: TextStyle(fontSize: kFontMicro, color: sz.inkMuted)),
            ],
          ),
        ),
        const SizedBox(height: 10),
      ],
    ];
    // ⑤ 对账工具网格
    final tools = <Widget>[
      // 经营质量(近 30 天完成 / 出餐超时率 / 拒单)在经营分析页,
      // 那三个数不是账;服务端 /me/quality 明写「只统计展示,不做处罚」。
      // 「导出对账单」在台面底下那一行,这里不再挂第二份
      const SzSectionTitle('对账工具'),
      const SizedBox(height: 9),
      SzIconGrid(items: [
        SzIconGridItem(
            icon: Icons.account_balance_outlined,
            label: '收款账户',
            onTap: () => Navigator.of(context)
                .push(MaterialPageRoute(
                    builder: (_) => PayoutAccountPage(api: widget.api)))
                .then((_) => _load())),
        SzIconGridItem(
            icon: Icons.receipt_long_outlined,
            label: '服务费发票',
            onTap: () => Navigator.of(context).push(MaterialPageRoute(
                builder: (_) => InvoicePage(api: widget.api)))),
        SzIconGridItem(
            icon: Icons.query_stats_outlined,
            label: '经营分析',
            onTap: () => Navigator.of(context).push(MaterialPageRoute(
                builder: (_) => AnalyticsPage(api: widget.api)))),
      ]),
      Padding(
        padding: const EdgeInsets.fromLTRB(kCardPad, 6, kCardPad, 0),
        child: Text('导出的对账单与钱包同源,记账可用;经营分析仅自己可见',
            style: TextStyle(
                fontSize: kFontMicro, height: 1.5, color: sz.inkMuted)),
      ),
      const SizedBox(height: 18),
    ];
    // ⑥ 提现记录
    final withdrawals = <Widget>[
      if (_withdrawals.isNotEmpty) ...[
        // 服务端 `/me/withdrawals` 是 `.limit(100)`,标题说清列了几条,
        // 并给得出「全部」—— 提现频繁的店不能永远看不到更早的
        SzSectionTitle('提现记录 · 最近 ${_withdrawals.take(3).length} 条'),
        const SizedBox(height: 9),
        SzCard(
          padding: EdgeInsets.zero,
          child: Column(children: [
            for (final (i, w) in _withdrawals.take(3).indexed) ...[
              if (i > 0) Divider(height: 1, color: sz.line),
              withdrawalRow(context, w),
            ],
            Divider(height: 1, color: sz.line),
            SzEntryTile(
              title: '全部提现记录',
              value: '${_withdrawals.length}'
                  '${_withdrawals.length >= 100 ? '+' : ''} 条',
              onTap: () => Navigator.of(context).push(MaterialPageRoute(
                  builder: (_) =>
                      MerchantWithdrawalsPage(items: _withdrawals))),
            ),
          ]),
        ),
        const SizedBox(height: 18),
      ],
    ];
    // ⑦ 承诺卡(页尾,横跨两栏)
    const pledge = PledgeCard(
      title: '超级赞承诺',
      body: '佣金只抽 5%,单量越大费率越低 · 每日 4:00 自动核账,差一分钱系统报警 · 账目写进开源代码,欢迎监督',
    );

    return Column(children: [
      _header(),
      Expanded(
        child: RefreshIndicator(
          onRefresh: _pull,
          child: LayoutBuilder(builder: (context, c) {
            // 宽屏(可用宽度 ≥1100)两栏(#33 4.3 宽屏):
            // 左列放「钱」的静态事实:钱包、费率档位、工具、提现记录;
            // 右列放台面和按日账单 —— 每天要问的那两件事在同一列里。
            // 判据是可用宽度不是平台:网页版拉宽窗口、平板横屏都算。
            if (c.maxWidth < 1100) {
              return ListView(
                padding: const EdgeInsets.fromLTRB(kPagePad, 4, kPagePad, 24),
                children: [
                  ...ledgerBlock,
                  ...wallet,
                  ...tier,
                  ...tools,
                  ...withdrawals,
                  pledge,
                ],
              );
            }
            return ListView(
              padding: const EdgeInsets.fromLTRB(kPagePad, 4, kPagePad, 24),
              children: [
                Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Expanded(
                    flex: 2,
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      children: [...wallet, ...tier, ...tools, ...withdrawals],
                    ),
                  ),
                  const SizedBox(width: 20),
                  Expanded(
                    flex: 3,
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      children: ledgerBlock,
                    ),
                  ),
                ]),
                pledge,
              ],
            );
          }),
        ),
      ),
    ]);
  }
}

/// 单日入账明细,和日汇总逐单能对上。
class DayOrdersPage extends StatefulWidget {
  const DayOrdersPage({super.key, required this.api, required this.stat});

  final ApiClient api;
  final DayStat stat;

  @override
  State<DayOrdersPage> createState() => _DayOrdersPageState();
}

class _DayOrdersPageState extends State<DayOrdersPage> {
  late Future<List<FinanceOrder>> _future =
      widget.api.financeOrders(widget.stat.day);
  ApiClient get api => widget.api;
  DayStat get stat => widget.stat;

  @override
  Widget build(BuildContext context) {
    return SzPageScaffold(
      // 限宽用宽档:对账表格挤在 720 里看不清 —— 
      // 宽度上限按**内容形态**选,不是统一限死
      contentMaxWidth: kWideMaxWidth,
      appBar: AppBar(title: Text('${stat.day} 入账明细')),
      body: FutureBuilder(
        future: _future,
        builder: (context, snapshot) {
          if (snapshot.hasError) {
            return SzError(
                error: snapshot.error,
                onRetry: () => setState(() {
                      _future = api.financeOrders(stat.day);
                    }));
          }
          if (!snapshot.hasData) {
            return const Center(child: CircularProgressIndicator());
          }
          final orders = snapshot.data!;
          final sz = Theme.of(context).sz;
          return ListView(
            padding: const EdgeInsets.fromLTRB(kPagePad, 12, kPagePad, 24),
            children: [
              SzLedgerCard(
                padding: const EdgeInsets.symmetric(
                    horizontal: kCardPad, vertical: 4),
                child: Column(children: [
                  SzFeeRow(label: '菜品流水', amountCents: stat.foodCents),
                  SzFeeRow(
                      label: '平台佣金',
                      amountCents: stat.commissionCents,
                      negative: true,
                      isHold: true),
                  // 这里必须现取 Theme:外层的 sz 是浅色态,画在深色台面上
                  // 会是一道刺眼的亮线(SzLedgerCard 只换它内部的 SzColors)
                  Builder(
                      builder: (c) => Divider(
                          color: Theme.of(c).sz.line, height: 17)),
                  SzFeeRow(
                      label: '净收入 · ${stat.orderCount} 单',
                      amountCents: stat.netCents,
                      emphasized: true),
                ]),
              ),
              const SizedBox(height: 18),
              const SzSectionTitle('逐单明细'),
              const SizedBox(height: 9),
              if (orders.isEmpty)
                const SzEmpty(art: BrandArt.receipt, text: '这一天没有入账订单')
              else
                SzCard(
                  padding: EdgeInsets.zero,
                  child: Column(children: [
                    for (final (i, o) in orders.indexed) ...[
                      if (i > 0) Divider(height: 1, color: sz.line),
                      Padding(
                        padding: const EdgeInsets.symmetric(
                            horizontal: kCardPad, vertical: 11),
                        child: Row(children: [
                          Expanded(
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Text('${o.createdAt.substring(11, 16)} · ${o.orderNo}',
                                    style: TextStyle(
                                        fontSize: kFontNote, color: sz.ink)),
                                const SizedBox(height: 2),
                                Text(
                                    '流水 ${yuan(o.foodCents)} − 佣金 ${yuan(o.commissionCents)}',
                                    style: TextStyle(
                                        fontSize: kFontMicro, color: sz.inkMuted)),
                              ],
                            ),
                          ),
                          Text(yuan(o.netCents),
                              style: szMoney(
                                  fontSize: kFontBody,
                                  fontWeight: FontWeight.w600,
                                  color: sz.earn)),
                        ]),
                      ),
                    ],
                  ]),
                ),
            ],
          );
        },
      ),
    );
  }
}

/// 全部提现记录。
///
/// 服务端 `/merchants/me/withdrawals` 是 `.limit(100)`,所以这里也只可能有
/// 100 条 —— **标题就照实说 100**,不写一个说不出上限的「全部」。
/// 更早的走对账页的「导出对账单(CSV)」。
class MerchantWithdrawalsPage extends StatelessWidget {
  const MerchantWithdrawalsPage({super.key, required this.items});

  final List<Withdrawal> items;

  @override
  Widget build(BuildContext context) {
    final capped = items.length >= 100;
    return SzPageScaffold(
      appBar:
          AppBar(title: Text('提现记录 · ${items.length}${capped ? '+' : ''} 条')),
      body: ListView(
        padding: const EdgeInsets.fromLTRB(kPagePad, 12, kPagePad, 24),
        children: [
          SzCard(
            padding: EdgeInsets.zero,
            child: Column(children: [
              for (final (i, w) in items.indexed) ...[
                if (i > 0)
                  Divider(height: 1, color: Theme.of(context).sz.line),
                withdrawalRow(context, w),
              ],
            ]),
          ),
          if (capped)
            Padding(
              padding: const EdgeInsets.fromLTRB(kCardPad, 10, kCardPad, 0),
              child: Text(
                  '只回最近 100 条。更早的提现在「导出对账单(CSV)」里,'
                  '口径与钱包同源。',
                  style: TextStyle(
                      fontSize: kFontMicro,
                      height: 1.5,
                      color: Theme.of(context).sz.inkMuted)),
            ),
        ],
      ),
    );
  }
}
