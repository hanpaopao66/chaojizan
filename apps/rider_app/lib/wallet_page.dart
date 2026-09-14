import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';
import 'package:url_launcher/url_launcher.dart';

import 'weekly_page.dart';

/// 判骑手责任的三种账本行(服务端 EarningKind 的 fault_*)在流水里的说法
const Map<String, String> _kFaultKinds = {
  'fault_reversal': '骑手责任 · 这单收入不计',
  'fault_charge': '骑手责任 · 商家那份餐钱(保障金池不够的部分)',
  'fault_refund': '申诉成立 · 扣的钱退回',
};

/// 骑手账本(设计稿 5g):深台面 + 逐单。
///
/// 台面答「这一段挣了多少、平台拿走多少」,逐单答「是哪几单」。
/// 时段(今天 / 本周 / 本月)在标题栏右边切,状态由主页持有([period])。
///
/// ## 和设计稿不一样的两处,都是因为稿子上的事不存在
///
/// - 稿子写「22:00 结算到 尾号 6210」。**没有定时结算**:钱在订单完成时
///   进钱包,骑手自己点提现,平台 T+1 打款。所以台面底下那一块是
///   「可提现 ¥x」+「提现 T+1 到尾号 xxxx」两行,点它就是提现。
/// - 稿子写「平台抽 ¥0」常显。外卖配送费确实一分不抽,但**跑腿单平台收
///   跑腿费的 2%** —— 这个数由服务端按这一段的跑腿单算好(worklog 的
///   `*_platform_cut_cents`),是多少写多少,没接跑腿单就是真的 ¥0。
///
/// 「罚款 ¥0」照写:平台没有任何罚款项。判为骑手责任的那一单另算(服务端
/// services/rider_fault:这单收入不计,商家那份餐钱先由保障金池出、不够的从收入里扣)——
/// 那是赔商家那份餐钱,不是罚款,逐单里单独一行写明([_kFaultKinds]),不混进台面的「罚款」。
class WalletPage extends StatefulWidget {
  const WalletPage({super.key, required this.api, this.period = 0});

  final ApiClient api;

  /// 0 今天 / 1 本周 / 2 本月
  final int period;

  static const periods = ['今天', '本周', '本月'];

  @override
  State<WalletPage> createState() => _WalletPageState();
}

class _WalletPageState extends State<WalletPage> {
  Wallet? _wallet;
  Map<String, dynamic>? _worklog;
  PayoutAccount? _payout;
  List<Earning> _earnings = [];
  List<Withdrawal> _withdrawals = [];

  /// 拉钱包失败的原因;空串 = 上一次是成功的。
  ///
  /// 之前只弹一条 SnackBar 就完了,而 `_wallet` 还是 null ——
  /// 于是这一页**永久转圈**,连下拉自救的路都没有。钱的那一页不该是这样。
  String _error = '';

  /// 下拉刷新时换一个值,台面数字和分账条从 0 再滚一次;
  /// 轮询、切时段、切 tab 回来都不重播(动效规范 09)
  int _replay = 0;

  String get _periodKey => const ['today', 'week', 'month'][widget.period];

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void didUpdateWidget(covariant WalletPage old) {
    super.didUpdateWidget(old);
    if (old.period != widget.period) _loadEarnings();
  }

  Future<void> _load({bool replay = false}) async {
    try {
      final wallet = await widget.api.wallet();
      final withdrawals = await widget.api.withdrawals();
      Map<String, dynamic>? worklog;
      PayoutAccount? payout;
      try {
        worklog = await widget.api.riderWorklog();
      } catch (_) {}
      try {
        payout = await widget.api.payoutAccount();
      } catch (_) {}
      final earnings = await widget.api.earnings(period: _periodKey);
      if (!mounted) return;
      setState(() {
        _wallet = wallet;
        _withdrawals = withdrawals;
        _worklog = worklog;
        _payout = payout;
        _earnings = earnings;
        _error = '';
        if (replay) _replay++;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() => _error = e is ApiException ? e.message : e.toString());
    }
  }

  Future<void> _loadEarnings() async {
    try {
      final earnings = await widget.api.earnings(period: _periodKey);
      if (mounted) setState(() => _earnings = earnings);
    } catch (_) {}
  }

  Future<void> _withdraw() async {
    final wallet = _wallet;
    if (wallet == null) return;
    final controller = TextEditingController(
        text: (wallet.withdrawableCents / 100).toStringAsFixed(2));
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => SzDialog(
        title: const Text('申请提现'),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Text('可提现 ${yuan(wallet.withdrawableCents)},最低 ¥10;'
                'T+1 到账,零手续费'),
            const SizedBox(height: 12),
            TextField(
              controller: controller,
              keyboardType: const TextInputType.numberWithOptions(decimal: true),
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
      await widget.api.requestWithdrawal(amount);
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('提现申请已提交,平台确认后 T+1 打款')));
      _load();
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(e.toString())));
    }
  }

  int? _num(String key) => (_worklog?[key] as num?)?.toInt();

  String _periodTitle() {
    final now = DateTime.now();
    return switch (widget.period) {
      0 => '${now.month} 月 ${now.day} 日',
      1 => '本周 · ${now.subtract(Duration(days: now.weekday - 1)).month} 月 '
          '${now.subtract(Duration(days: now.weekday - 1)).day} 日起',
      _ => '${now.month} 月',
    };
  }

  @override
  Widget build(BuildContext context) {
    final wallet = _wallet;
    if (wallet == null) {
      // 转圈 / 失败要分开,而且失败态也得能下拉重试
      return RefreshIndicator(
        onRefresh: _load,
        child: ListView(children: [
          SizedBox(
            height: 420,
            child: _error.isEmpty
                ? const Center(child: CircularProgressIndicator())
                : SzError(
                    error: '账本没能加载出来:$_error\n余额和流水都还在,只是这会儿读不到',
                    onRetry: _load),
          ),
        ]),
      );
    }
    final sz = Theme.of(context).sz;
    final p = const ['today', 'week', 'month'][widget.period];
    final earned = _num('${p}_earned_cents');
    final orders = _num('${p}_orders');
    final minutes = _num('${p}_minutes');
    final cut = _num('${p}_platform_cut_cents');

    return RefreshIndicator(
      onRefresh: () => _load(replay: true),
      child: ListView(
        padding: const EdgeInsets.fromLTRB(kPagePad, 4, kPagePad, 28),
        children: [
          if (_error.isNotEmpty) ...[
            SzRetryBanner(
                text: '账本没刷新成功($_error),下面是上一次的数。点这里重试',
                onRetry: _load),
            const SizedBox(height: 8),
          ],
          _ledgerCard(wallet, earned, orders, minutes, cut),
          const SizedBox(height: 16),
          Row(children: [
            Expanded(
              child: Text('逐单',
                  style: TextStyle(
                      fontSize: kFontNote, letterSpacing: 1, color: sz.inkMuted)),
            ),
            Text('配送费一分不抽 · 跑腿费扣 2%',
                style: TextStyle(fontSize: kFontNote, color: sz.inkMuted)),
          ]),
          const SizedBox(height: 6),
          _earningsCard(sz),
          if (widget.period == 1) ...[
            const SizedBox(height: 8),
            Align(
              alignment: Alignment.centerRight,
              child: TextButton(
                onPressed: () => Navigator.of(context).push(MaterialPageRoute(
                    builder: (_) => RiderWeeklyPage(api: widget.api))),
                child: const Text('看周报:每天明细、时薪、配送费构成 →'),
              ),
            ),
          ],
          const SizedBox(height: 18),
          Row(children: [
            Expanded(
              child: Text('提现记录',
                  style: TextStyle(
                      fontSize: kFontNote, letterSpacing: 1, color: sz.inkMuted)),
            ),
          ]),
          const SizedBox(height: 6),
          _withdrawalsCard(sz, wallet),
          const SizedBox(height: 12),
          const PledgeCard(
            title: '配送费 100% 归骑手',
            body: '外卖配送费和小费平台分文不取,跑腿费平台收 2%;提现零手续费。\n'
                '配送收入属劳务报酬,请依法申报个税;'
                '平台接入灵活用工代发后将自动完税并另行通知。',
          ),
          const SizedBox(height: 18),
          // 商店审核三件套:协议全文 / 退出登录 / 注销账号。
          // 「我的」页也有一份;这里先不删 —— 审核路径突然变了比多一份更麻烦
          AccountLegalSection(
            api: widget.api,
            onLoggedOut: (ctx) {
              Navigator.of(ctx).popUntil((route) => route.isFirst);
              ApiClient.onUnauthorized?.call();
            },
            onDeleted: (ctx) {
              Navigator.of(ctx).popUntil((route) => route.isFirst);
              ApiClient.onUnauthorized?.call();
            },
          ),
        ],
      ),
    );
  }

  Widget _ledgerCard(
      Wallet wallet, int? earned, int? orders, int? minutes, int? cut) {
    return SzLedgerCard(
      padding: const EdgeInsets.fromLTRB(18, 16, 18, 16),
      child: Builder(builder: (context) {
        // 台面里取色要在台面里取(SzLedgerCard 把 SzColors 换成了深色态)
        final s = Theme.of(context).sz;
        final dim = TextStyle(fontSize: kFontNote, color: s.inkMuted);
        final fig = szFigure(fontSize: kFontNote, color: s.ink);
        final canWithdraw = wallet.withdrawableCents >= 1000;
        // 两行:余额一行、去向一行。挤成一行的话余额上了四位数就从
        // 「尾号」中间折开(390 宽实测)
        final tail = !canWithdraw
            ? '满 ¥10 可提'
            : (_payout != null && _payout!.configured
                ? '提现 T+1 到尾号 ${_payout!.accountTail}'
                : '提现前先登记收款账户');
        return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text('${_periodTitle()} · 配送费全额',
              style: TextStyle(
                  fontSize: kFontMicro, letterSpacing: 1, color: s.inkMuted)),
          const SizedBox(height: 6),
          earned == null
              ? Text('—',
                  style: szMoney(fontSize: kFigureHero, color: s.earn, height: 1.1))
              : SzRollingAmount(
                  cents: earned,
                  replayKey: _replay,
                  style: szMoney(
                      fontSize: kFigureHero, color: s.earn, height: 1.1)),
          const SizedBox(height: 12),
          Wrap(spacing: 18, runSpacing: 4, children: [
            Text.rich(TextSpan(children: [
              TextSpan(text: orders == null ? '—' : '$orders', style: fig),
              TextSpan(text: ' 单', style: dim),
            ])),
            Text.rich(TextSpan(children: [
              TextSpan(
                  text: minutes == null
                      ? '—'
                      : (minutes / 60).toStringAsFixed(1),
                  style: fig),
              TextSpan(text: ' 小时在线', style: dim),
            ])),
            Text.rich(TextSpan(children: [
              TextSpan(text: '平台抽 ', style: dim),
              // 整元不带小数(稿子上是「¥0」);跑腿单那 2% 有零头才带
              TextSpan(
                  text: cut == null
                      ? '—'
                      : szYuanText(cut, '¥', cut % 100 == 0 ? 0 : 2),
                  style: fig),
            ])),
            Text.rich(TextSpan(children: [
              TextSpan(text: '罚款 ', style: dim),
              TextSpan(text: '¥0', style: fig),
            ])),
          ]),
          const SizedBox(height: 14),
          Container(height: 1, color: s.line),
          const SizedBox(height: 12),
          // 判骑手责任扣过钱、余额是负的:之后的收入先抵,抵完才能提现(服务端按余额挡)
          if (wallet.balanceCents < 0) ...[
            Text('待抵扣 ${szYuanText(-wallet.balanceCents)}:判为骑手责任的那几单扣的钱,'
                '之后的收入先抵,抵完才能提现',
                style: TextStyle(fontSize: kFontMicro, color: s.hold)),
            const SizedBox(height: 8),
          ],
          Row(children: [
            Container(
              width: 7,
              height: 7,
              decoration: BoxDecoration(color: s.earn, shape: BoxShape.circle),
            ),
            const SizedBox(width: 8),
            Expanded(
              child: InkWell(
                onTap: canWithdraw ? _withdraw : null,
                child: Padding(
                  padding: const EdgeInsets.symmetric(vertical: 4),
                  child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text.rich(TextSpan(children: [
                          TextSpan(text: '可提现 ', style: dim),
                          TextSpan(
                              text: szYuanText(wallet.withdrawableCents),
                              style: fig),
                        ])),
                        Text(tail,
                            maxLines: 1,
                            overflow: TextOverflow.ellipsis,
                            style: TextStyle(
                                fontSize: kFontMicro, color: s.inkMuted)),
                      ]),
                ),
              ),
            ),
            InkWell(
              onTap: () => launchUrl(
                  Uri.parse('https://chaojizan.cc/transparency'),
                  mode: LaunchMode.externalApplication),
              child: Padding(
                padding: const EdgeInsets.symmetric(vertical: 4),
                child: Text('在透明中心核对 →',
                    style: TextStyle(fontSize: kFontNote, color: s.clay)),
              ),
            ),
          ]),
        ]);
      }),
    );
  }

  Widget _earningsCard(SzColors sz) {
    if (_earnings.isEmpty) {
      return SzCard(
        child: Padding(
          padding: const EdgeInsets.symmetric(vertical: 18),
          child: Center(
            child: Text(
                const ['今天还没有入账的单', '这周还没有入账的单', '这个月还没有入账的单']
                    [widget.period],
                style: TextStyle(fontSize: kFontBody, color: sz.inkMuted)),
          ),
        ),
      );
    }
    return Material(
      color: sz.surface,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(kRadiusMd),
        side: BorderSide(color: sz.line),
      ),
      clipBehavior: Clip.antiAlias,
      child: Column(children: [
        for (final (i, e) in _earnings.indexed) ...[
          if (i > 0) Divider(height: 1, color: sz.line),
          _earningRow(sz, e),
        ],
      ]),
    );
  }

  Widget _earningRow(SzColors sz, Earning e) {
    final t = DateTime.tryParse(e.createdAt)?.toLocal();
    String two(int n) => n.toString().padLeft(2, '0');
    final time = t == null
        ? ''
        : (widget.period == 0
            ? '${two(t.hour)}:${two(t.minute)}'
            : '${t.month}/${t.day}');
    final channel = e.isErrand
        ? 'errand'
        : (channelOfBizType(e.bizType)?.key ?? 'food');
    final title = e.fromName.isEmpty && e.toArea.isEmpty
        ? '订单 ${e.orderNo.substring(e.orderNo.length - 6)}'
        : '${e.isErrand ? "帮我送 · " : ""}${e.fromName} → ${e.toArea}';
    final sub = [
      if (e.distanceM != null) distanceLabelShort(e.distanceM!.toDouble()),
      if (e.isErrand && e.platformCutCents > 0)
        '${yuan(e.feeCents)} − 2%',
      if (e.kind == 'adjustment') '调整',
      // 判骑手责任(服务端 services/rider_fault):这单收入冲回、保障金池不够的部分另扣、申诉成立退回
      if (_kFaultKinds[e.kind] != null) _kFaultKinds[e.kind]!,
    ].join(' · ');
    return Padding(
      padding: const EdgeInsets.fromLTRB(14, 11, 14, 11),
      child: Row(children: [
        SizedBox(
          width: 40,
          child: Text(time,
              style: szFigure(fontSize: kFontNote, color: sz.inkMuted)),
        ),
        Container(
          width: 3,
          height: 26,
          decoration: BoxDecoration(
            color: channelColor(context, channel),
            borderRadius: BorderRadius.circular(2),
          ),
        ),
        const SizedBox(width: 10),
        Expanded(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(title,
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: TextStyle(
                    fontSize: kFontBody,
                    fontWeight: FontWeight.w600,
                    color: sz.ink)),
            if (sub.isNotEmpty)
              Text(sub,
                  style: TextStyle(fontSize: kFontMicro, color: sz.inkMuted)),
          ]),
        ),
        const SizedBox(width: 8),
        Text(szYuanText(e.amountCents),
            style: szMoney(
                fontSize: kFontBodyLg,
                color: e.amountCents < 0 ? sz.hold : sz.earn)),
      ]),
    );
  }

  Widget _metric(SzColors sz, String label, int cents) => Expanded(
        child: Column(children: [
          Text(szYuanText(cents),
              style: szMoney(fontSize: kFigureSm, color: sz.ink)),
          const SizedBox(height: 2),
          Text(label, style: TextStyle(fontSize: kFontMicro, color: sz.inkMuted)),
        ]),
      );

  Widget _withdrawalsCard(SzColors sz, Wallet wallet) {
    final metrics = Padding(
      padding: const EdgeInsets.fromLTRB(8, 12, 8, 12),
      child: Row(children: [
        _metric(sz, '累计入账', wallet.totalEarnedCents),
        _metric(sz, '提现中', wallet.pendingWithdrawalCents),
        _metric(sz, '已提现', wallet.withdrawnCents),
      ]),
    );
    if (_withdrawals.isEmpty) {
      return SzCard(
        padding: EdgeInsets.zero,
        child: Column(children: [
          metrics,
          Divider(height: 1, color: sz.line),
          Padding(
            padding: const EdgeInsets.symmetric(vertical: 14),
            child: Center(
              child: Text('还没有提现记录',
                  style: TextStyle(fontSize: kFontBody, color: sz.inkMuted)),
            ),
          ),
        ]),
      );
    }
    return Material(
      color: sz.surface,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(kRadiusMd),
        side: BorderSide(color: sz.line),
      ),
      clipBehavior: Clip.antiAlias,
      child: Column(children: [
        metrics,
        for (final w in _withdrawals.take(10)) ...[
          Divider(height: 1, color: sz.line),
          Padding(
            padding: const EdgeInsets.fromLTRB(14, 11, 14, 11),
            child: Row(children: [
              Expanded(
                child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text('提现 ${yuan(w.amountCents)}',
                          style: TextStyle(
                              fontSize: kFontBody,
                              fontWeight: FontWeight.w600,
                              color: sz.ink)),
                      Text(
                          w.rejectReason.isNotEmpty
                              ? '原因:${w.rejectReason}'
                              : szTimeAgo(w.createdAt),
                          style: TextStyle(
                              fontSize: kFontMicro, color: sz.inkMuted)),
                    ]),
              ),
              Text(w.statusLabel,
                  style: TextStyle(
                      fontSize: kFontNote,
                      fontWeight: FontWeight.w600,
                      color: switch (w.status) {
                        'paid' => sz.earn,
                        'rejected' || 'failed' => sz.danger,
                        _ => sz.hold,
                      })),
            ]),
          ),
        ],
      ]),
    );
  }
}
