import 'dart:io' show Platform;

import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:flutter/material.dart';
import 'package:mobile_scanner/mobile_scanner.dart';
import 'package:superz_shared/superz_shared.dart';

import 'merchant_ui.dart';

/// 团购券管理:发布 / 上下架 / 销量一览。核销服务费 2%,只在核销时收。
class VoucherManagePage extends StatefulWidget {
  const VoucherManagePage({super.key, required this.api});

  final ApiClient api;

  @override
  State<VoucherManagePage> createState() => _VoucherManagePageState();
}

class _VoucherManagePageState extends State<VoucherManagePage> {
  List<VoucherDeal>? _deals;

  /// 非空 = 上一次加载失败。「还没发布团购券」和「没拉到」不能长得一样
  String _error = '';

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final deals = await widget.api.myVoucherDeals();
      if (mounted) setState(() { _deals = deals; _error = ''; });
    } catch (e) {
      if (!mounted) return;
      setState(() => _error = e is ApiException ? e.message : '$e');
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(_error)));
    }
  }

  Future<void> _create() async {
    final title = TextEditingController();
    final sell = TextEditingController();
    final face = TextEditingController();
    final count = TextEditingController(text: '100');
    final saved = await showDialog<bool>(
      context: context,
      builder: (context) => SzDialog(
        title: const Text('发布代金券'),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            TextField(
                controller: title,
                decoration: const InputDecoration(
                    labelText: '标题(如 50元代金券)', isDense: true)),
            Row(children: [
              Expanded(
                child: TextField(
                    controller: sell,
                    keyboardType: const TextInputType.numberWithOptions(
                        decimal: true),
                    decoration: const InputDecoration(
                        labelText: '售价(元)', isDense: true)),
              ),
              const SizedBox(width: 8),
              Expanded(
                child: TextField(
                    controller: face,
                    keyboardType: const TextInputType.numberWithOptions(
                        decimal: true),
                    decoration: const InputDecoration(
                        labelText: '面值(元)', isDense: true)),
              ),
            ]),
            TextField(
                controller: count,
                keyboardType: TextInputType.number,
                decoration: const InputDecoration(
                    labelText: '发行数量', isDense: true)),
            const SizedBox(height: 8),
            const Text('用户核销后到账「售价 - 2% 服务费」;券未被使用平台分文不收',
                style: TextStyle(fontSize: kFontNote)),
          ],
        ),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(context, false),
              child: const Text('取消')),
          FilledButton(
              onPressed: () => Navigator.pop(context, true),
              child: const Text('发布')),
        ],
      ),
    );
    if (saved != true || !mounted) return;
    final sellCents = ((double.tryParse(sell.text) ?? 0) * 100).round();
    final faceCents = ((double.tryParse(face.text) ?? 0) * 100).round();
    final total = int.tryParse(count.text) ?? 0;
    if (title.text.trim().length < 2 ||
        sellCents <= 0 ||
        faceCents <= sellCents ||
        total <= 0) {
      ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('请检查:标题至少 2 字,售价 < 面值,数量 > 0')));
      return;
    }
    try {
      await widget.api.createVoucher({
        'title': title.text.trim(),
        'sell_price_cents': sellCents,
        'face_value_cents': faceCents,
        'total_count': total,
      });
      _load();
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text('$e')));
    }
  }

  @override
  Widget build(BuildContext context) {
    final deals = _deals;
    return SzPageScaffold(
      appBar: AppBar(title: const Text('团购券管理')),
      floatingActionButton: FloatingActionButton.extended(
        onPressed: _create,
        icon: const Icon(Icons.add),
        label: const Text('发布'),
      ),
      body: deals == null
          ? (_error.isNotEmpty
              ? SzError(error: _error, onRetry: _load)
              : const Center(child: CircularProgressIndicator()))
          : deals.isEmpty
              ? SzRefreshableEmpty(
                  onRefresh: _load,
                  child: const Text('还没发布团购券\n低价引流,核销才收 2% 服务费',
                      textAlign: TextAlign.center))
              : RefreshIndicator(
                  onRefresh: _load,
                  child: ListView.separated(
                    padding: const EdgeInsets.all(12),
                    itemCount: deals.length,
                    separatorBuilder: (_, __) => const SizedBox(height: 8),
                    itemBuilder: (context, i) {
                      final d = deals[i];
                      return Card(
                        child: ListTile(
                          title: Text(d.title),
                          subtitle: Text(
                              '${yuan(d.sellPriceCents)} 售 / 面值 ${yuan(d.faceValueCents)}'
                              ' · 已售 ${d.soldCount} · 剩 ${d.totalCount}'),
                          trailing: Switch(
                            value: d.isActive,
                            onChanged: (v) async {
                              try {
                                await widget.api
                                    .updateVoucher(d.id, {'is_active': v});
                                _load();
                              } catch (e) {
                                if (!context.mounted) return;
                                ScaffoldMessenger.of(context).showSnackBar(
                                    SnackBar(content: Text('$e')));
                              }
                            },
                          ),
                        ),
                      );
                    },
                  ),
                ),
    );
  }
}

/// 团购券核销(设计稿 6k):扫码为主、输码兜底,下面是今天核销过的券。
///
/// 扫码框就在页面上(手机上点一下开相机,取景就在这个框里),核销成功是一张
/// 浅色的成功态(规范 08:圆环 → 勾 → 文字 → 三格),把「售价 / 你实收 /
/// 平台 2%」三个数摆出来 —— 平台 2% 是按**售价**抽的,不是面额。
///
/// 券码只露后 4 位:完整券码就是那张券本身,这一页的列表会被旁人看到。
class VoucherRedeemPage extends StatefulWidget {
  const VoucherRedeemPage({super.key, required this.api});

  final ApiClient api;

  @override
  State<VoucherRedeemPage> createState() => _VoucherRedeemPageState();
}

class _VoucherRedeemPageState extends State<VoucherRedeemPage> {
  final _code = TextEditingController();
  final _codeFocus = FocusNode();
  bool _busy = false;

  /// 相机开着没有。**开的时候才建 MobileScanner** —— 关掉就是把它从树上拿掉,
  /// 相机跟着释放;核销、成功态期间不取景
  bool _scanning = false;

  /// 今天核销过的券(`/vouchers/redeemed-today`)
  Map<String, dynamic>? _today;
  String _todayError = '';

  bool get _canScan => !kIsWeb && (Platform.isAndroid || Platform.isIOS);

  @override
  void initState() {
    super.initState();
    _loadToday();
  }

  @override
  void dispose() {
    _code.dispose();
    _codeFocus.dispose();
    super.dispose();
  }

  Future<void> _loadToday() async {
    try {
      final t = await widget.api.vouchersRedeemedToday();
      if (mounted) {
        setState(() {
          _today = t;
          _todayError = '';
        });
      }
    } catch (e) {
      if (mounted) {
        setState(() => _todayError = e is ApiException ? e.message : '$e');
      }
    }
  }

  void _snack(String message) {
    if (!mounted) return;
    ScaffoldMessenger.of(context)
        .showSnackBar(SnackBar(content: Text(message)));
  }

  /// 点扫码框:先说明为什么要相机(商店合规),同意了才开
  Future<void> _startScan() async {
    if (!await PermissionRationale.ensure(context, AppPermissionKind.camera,
        reason: '用于扫描顾客的团购券二维码完成核销。\n拒绝可改用手动输码。')) {
      return;
    }
    if (mounted) setState(() => _scanning = true);
  }

  void _onDetect(BarcodeCapture capture) {
    if (_busy || !_scanning) return;
    final value = capture.barcodes.firstOrNull?.rawValue?.trim();
    if (value == null || value.isEmpty) return;
    // 认到第一个码就关相机:同一张码会连着回调好几次,不能核销好几遍
    setState(() => _scanning = false);
    _redeem(value);
  }

  Future<void> _redeem([String? scanned]) async {
    final code = (scanned ?? _code.text).replaceAll(' ', '');
    if (code.length < 6) {
      _snack('请输入完整券码');
      return;
    }
    setState(() => _busy = true);
    VoucherTicket? ticket;
    try {
      ticket = await widget.api.redeemVoucher(code);
    } catch (e) {
      _snack(e is ApiException ? e.message : '$e');
    }
    if (!mounted) return;
    // 核销请求回来就解锁按钮 —— 成功态弹层盖在上面时,
    // 下面那颗按钮不该还写着「核销中…」
    setState(() => _busy = false);
    if (ticket == null) return;
    _code.clear();
    _loadToday();
    await _showSuccess(ticket);
  }

  Future<void> _showSuccess(VoucherTicket t) async {
    final next = await szShowSheet<bool>(
      context: context,
      builder: (ctx) => _RedeemSuccess(
        ticket: t,
        nextLabel: _canScan ? '继续扫下一张' : '继续核销下一张',
        onNext: () => Navigator.pop(ctx, true),
      ),
    );
    if (!mounted || next != true) return;
    if (_canScan) {
      setState(() => _scanning = true);
    } else {
      _codeFocus.requestFocus();
    }
  }

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    final count = (_today?['count'] as num?)?.toInt();
    return SzPageScaffold(
      appBar: AppBar(
        title: const Text('团购券核销'),
        actions: [
          if (count != null)
            Padding(
              padding: const EdgeInsets.only(right: 16),
              child: Center(
                child: Text('今日 $count 张',
                    style: TextStyle(fontSize: kFontBody, color: sz.inkMuted)),
              ),
            ),
        ],
      ),
      body: RefreshIndicator(
        onRefresh: _loadToday,
        child: ListView(
          padding: const EdgeInsets.fromLTRB(kPagePad, 4, kPagePad, 24),
          children: [
            _scanBox(),
            const SizedBox(height: 14),
            _inputRow(sz),
            Padding(
              padding: const EdgeInsets.fromLTRB(0, 18, 0, 6),
              child: Text('今日已核销',
                  style: TextStyle(
                      fontSize: kFontNote,
                      letterSpacing: 1,
                      color: sz.inkMuted)),
            ),
            _todayList(sz),
            Padding(
              padding: const EdgeInsets.only(top: 10),
              // 两句都有出处:核销时才落 2% 服务费(vouchers.redeem),
              // 未使用的券随时全额退(vouchers.refund_purchase)
              child: Text('未核销的券平台一分不收;用户随时可全额退',
                  textAlign: TextAlign.center,
                  style: TextStyle(fontSize: kFontNote, color: sz.inkMuted)),
            ),
          ],
        ),
      ),
    );
  }

  /// 扫码框(深色台面)。手机上点一下开相机,取景就在框里;
  /// 网页、电脑上没有相机可用,框里照实说「手机上可扫码」,下面输码
  Widget _scanBox() {
    return SizedBox(
      height: 300,
      child: SzLedgerCard(
        padding: EdgeInsets.zero,
        onTap: _canScan && !_scanning && !_busy ? _startScan : null,
        // 台面在内部把 SzColors 换成了深色那一套,颜色要在里面取
        child: Builder(builder: (context) {
          final sz = Theme.of(context).sz;
          final caption =
              TextStyle(fontSize: kFontNote, color: sz.inkMuted, height: 1.4);
          Widget frame({Widget? child}) => Container(
                width: 200,
                height: 200,
                alignment: Alignment.center,
                decoration: BoxDecoration(
                  borderRadius: BorderRadius.circular(kRadiusMd),
                  border:
                      Border.all(color: sz.ink.withValues(alpha: .7), width: 2),
                ),
                child: child,
              );
          if (_scanning && _canScan) {
            return Stack(fit: StackFit.expand, children: [
              MobileScanner(
                onDetect: _onDetect,
                errorBuilder: (context, e) => Center(
                  child: Padding(
                    padding: const EdgeInsets.all(24),
                    child: Text(
                        e.errorCode == MobileScannerErrorCode.permissionDenied
                            ? '没有相机权限。可以在系统设置里打开,或者直接在下面输入券码'
                            : '相机没打开。可以直接在下面输入券码',
                        textAlign: TextAlign.center,
                        style: caption),
                  ),
                ),
              ),
              Center(child: frame()),
              Positioned(
                left: 0,
                right: 0,
                bottom: 16,
                child: Text('对准用户的券码',
                    textAlign: TextAlign.center, style: caption),
              ),
            ]);
          }
          final idle = _canScan
              ? Column(mainAxisSize: MainAxisSize.min, children: [
                  Icon(Icons.qr_code_scanner, size: 40, color: sz.ink),
                  const SizedBox(height: 8),
                  Text(_busy ? '核销中…' : '点一下开始扫码',
                      style: TextStyle(fontSize: kFontBodyLg, color: sz.ink)),
                ])
              : Column(mainAxisSize: MainAxisSize.min, children: [
                  Icon(Icons.qr_code_2, size: 40, color: sz.inkMuted),
                  const SizedBox(height: 8),
                  Text('手机上可扫码',
                      style: TextStyle(fontSize: kFontBodyLg, color: sz.ink)),
                ]);
          return Stack(alignment: Alignment.center, children: [
            frame(child: idle),
            Positioned(
              left: 0,
              right: 0,
              bottom: 16,
              child: Text(_canScan ? '对准用户出示的券码二维码' : '这台设备上直接在下面输入券码',
                  textAlign: TextAlign.center, style: caption),
            ),
          ]);
        }),
      ),
    );
  }

  Widget _inputRow(SzColors sz) {
    final border = OutlineInputBorder(
      borderRadius: BorderRadius.circular(10),
      borderSide: BorderSide(color: sz.line),
    );
    // 输入框和「核销」都是 46 高(设计稿)
    return Row(children: [
      Expanded(
        child: SizedBox(
          height: 46,
          child: TextField(
            controller: _code,
            focusNode: _codeFocus,
            // 撑满 46 高、文字竖直居中:不写的话输入框按自己的行高长,和旁边的按钮不齐
            expands: true,
            maxLines: null,
            textAlignVertical: TextAlignVertical.center,
            keyboardType: TextInputType.number,
            textInputAction: TextInputAction.done,
            onSubmitted: (_) => _busy ? null : _redeem(),
            style: szMoney(
                fontSize: kFontBodyLg,
                fontWeight: FontWeight.w400,
                color: sz.ink),
            decoration: InputDecoration(
              hintText: '或输入 12 位券码',
              // 提示字用正文字族:输入框本身是衬线等宽数字(券码好核对),
              // 提示会跟着继承过去
              hintStyle: buttonText(kFontBodyLg, weight: FontWeight.w400)
                  .copyWith(color: sz.inkMuted),
              filled: true,
              fillColor: sz.surface,
              isDense: true,
              contentPadding: const EdgeInsets.symmetric(horizontal: 14),
              enabledBorder: border,
              border: border,
              focusedBorder: border.copyWith(
                  borderSide: BorderSide(
                      color: Theme.of(context).colorScheme.primary,
                      width: 1.5)),
            ),
          ),
        ),
      ),
      const SizedBox(width: 8),
      SzPressScale(
        enabled: !_busy,
        child: FilledButton(
          onPressed: _busy ? null : () => _redeem(),
          // 稿子上这颗是墨色实底:核销是这一页唯一的动作,但它不是「接单」
          // 那种频道主动作,用墨色和扫码框的深色台面成一组
          style: FilledButton.styleFrom(
            backgroundColor: sz.ink,
            foregroundColor: sz.paper,
            minimumSize: const Size(0, 46),
            padding: const EdgeInsets.symmetric(horizontal: 18),
            tapTargetSize: MaterialTapTargetSize.shrinkWrap,
            shape:
                RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
            textStyle: buttonText(kFontBodyLg),
          ),
          child: Text(_busy ? '核销中…' : '核销'),
        ),
      ),
    ]);
  }

  Widget _todayList(SzColors sz) {
    final today = _today;
    if (today == null) {
      return Padding(
        padding: const EdgeInsets.symmetric(vertical: 16),
        child: _todayError.isEmpty
            ? const Center(child: CircularProgressIndicator())
            // 拉不到的时候不能说「今天还没有核销」—— 那是在替未知状态下结论
            : SzRetryBanner(
                text: '今日核销记录没拉到:$_todayError。点这里重试', onRetry: _loadToday),
      );
    }
    final items =
        ((today['items'] as List?) ?? const []).cast<Map<String, dynamic>>();
    final bar = channelColor(context, 'voucher');
    return Container(
      decoration: BoxDecoration(
        color: sz.surface,
        borderRadius: BorderRadius.circular(kRadiusMd),
        border: Border.all(color: sz.line),
      ),
      clipBehavior: Clip.antiAlias,
      child: items.isEmpty
          ? Padding(
              padding: const EdgeInsets.all(18),
              child: Text('今天还没有核销过券',
                  textAlign: TextAlign.center,
                  style: TextStyle(fontSize: kFontBody, color: sz.inkMuted)),
            )
          : Column(children: [
              for (final (i, it) in items.indexed)
                EnterOnce(
                  gate: _listEnter,
                  index: i,
                  child: _todayRow(sz, it, bar, last: i == items.length - 1),
                ),
            ]),
    );
  }

  /// 今日列表的入场:第一次拉到时播一次
  late final EnterGate _listEnter = EnterGate()..open();

  Widget _todayRow(SzColors sz, Map<String, dynamic> it, Color bar,
      {required bool last}) {
    final at = localTimeOf(it['redeemed_at'] as String?);
    final sell = (it['sell_price_cents'] as num?)?.toInt() ?? 0;
    final commission = (it['commission_cents'] as num?)?.toInt() ?? 0;
    final net = (it['net_cents'] as num?)?.toInt() ?? 0;
    return Container(
      padding: const EdgeInsets.fromLTRB(kCardPad, 11, kCardPad, 11),
      decoration: BoxDecoration(
        border: last ? null : Border(bottom: BorderSide(color: sz.line)),
      ),
      child: Row(children: [
        Container(
          width: 3,
          height: 30,
          decoration:
              BoxDecoration(color: bar, borderRadius: BorderRadius.circular(2)),
        ),
        const SizedBox(width: 12),
        Expanded(
          child:
              Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text('${it['title'] ?? ''}',
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: TextStyle(
                    fontSize: kFontBodyLg,
                    fontWeight: FontWeight.w600,
                    color: sz.ink)),
            const SizedBox(height: 2),
            Text(
                [
                  if (at != null) hhmm(at),
                  '券码 …${it['code_tail'] ?? ''}',
                ].join(' · '),
                style: TextStyle(fontSize: kFontNote, color: sz.inkMuted)),
          ]),
        ),
        const SizedBox(width: 8),
        Column(crossAxisAlignment: CrossAxisAlignment.end, children: [
          Text(yuan(net),
              style: szMoney(
                  fontSize: kFontTitle,
                  fontWeight: FontWeight.w600,
                  color: sz.earn)),
          const SizedBox(height: 2),
          // 平台那 2% 是按**售价**抽的(vouchers.redeem),不是面额 ——
          // 稿子上写的「面额 ¥68 · 平台 2%」会让人以为按 68 算
          Text(
              '售价 ${yuanShort(sell)} · 平台 '
              '${sell > 0 ? pctLabel(commission / sell) : '2%'}',
              style: TextStyle(fontSize: kFontMicro, color: sz.inkMuted)),
        ]),
      ]),
    );
  }
}

/// 核销成功(规范 08):圆环 → 勾 → 「核销成功」→ 三格错落,总长约 800ms。
///
/// 设计稿 6l 是深色的成功页;这里照浅色定稿画成一张弹层,内容照 6l:
/// 成功、券名与券码尾号与时刻、三个数、继续下一张。
class _RedeemSuccess extends StatelessWidget {
  const _RedeemSuccess({
    required this.ticket,
    required this.nextLabel,
    required this.onNext,
  });

  final VoucherTicket ticket;
  final String nextLabel;
  final VoidCallback onNext;

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    final code = ticket.code;
    final tail = code.length > 4 ? code.substring(code.length - 4) : code;
    final at = localTimeOf(ticket.redeemedAt) ?? DateTime.now();
    final rate = ticket.sellPriceCents > 0
        ? pctLabel(ticket.commissionCents / ticket.sellPriceCents)
        : '2%';
    Widget tile(int i, String label, int cents, Color color) => Expanded(
          child: SzDelayedIn(
            delay: SzCheckDraw.tileDelay(i),
            child: Padding(
              padding: const EdgeInsets.all(kCardPad),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  FittedBox(
                    fit: BoxFit.scaleDown,
                    alignment: Alignment.centerLeft,
                    child: Text(yuan(cents),
                        style: szMoney(
                            fontSize: kFigureMd,
                            fontWeight: FontWeight.w600,
                            color: color,
                            height: 1.1)),
                  ),
                  const SizedBox(height: 4),
                  Text(label,
                      style:
                          TextStyle(fontSize: kFontMicro, color: sz.inkMuted)),
                ],
              ),
            ),
          ),
        );
    return SafeArea(
      child: Padding(
        padding: const EdgeInsets.fromLTRB(kPagePad, 4, kPagePad, 16),
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          const SzCheckDraw(size: 64),
          const SizedBox(height: 12),
          SzDelayedIn(
            delay: SzCheckDraw.textDelay,
            child: Text('核销成功', style: Theme.of(context).textTheme.titleLarge),
          ),
          const SizedBox(height: 4),
          SzDelayedIn(
            delay: SzCheckDraw.textDelay,
            child: Text(
                [
                  if (ticket.title.isNotEmpty) ticket.title,
                  '券码 …$tail',
                  hhmm(at),
                ].join(' · '),
                textAlign: TextAlign.center,
                style: TextStyle(fontSize: kFontBody, color: sz.inkMuted)),
          ),
          const SizedBox(height: 20),
          Container(
            decoration: BoxDecoration(
              color: sz.surface,
              borderRadius: BorderRadius.circular(kRadiusMd),
              border: Border.all(color: sz.line),
            ),
            clipBehavior: Clip.antiAlias,
            child: IntrinsicHeight(
              child: Row(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    tile(0, '售价', ticket.sellPriceCents, sz.ink),
                    VerticalDivider(width: 1, thickness: 1, color: sz.line),
                    // 实收进钱包,提现时 T+1 到卡;不是核销当下就到
                    tile(1, '你实收 · 进钱包', ticket.netCents, sz.earn),
                    VerticalDivider(width: 1, thickness: 1, color: sz.line),
                    tile(2, '平台 $rate', ticket.commissionCents, sz.hold),
                  ]),
            ),
          ),
          const SizedBox(height: 12),
          SizedBox(
            width: double.infinity,
            height: 52,
            child: SzPressScale(
              child: FilledButton(
                onPressed: onNext,
                style: FilledButton.styleFrom(
                  shape: RoundedRectangleBorder(
                      borderRadius: BorderRadius.circular(kRadiusMd)),
                  textStyle: buttonText(kFontTitle),
                ),
                child: Text(nextLabel),
              ),
            ),
          ),
        ]),
      ),
    );
  }
}
