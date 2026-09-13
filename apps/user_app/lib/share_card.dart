import 'dart:typed_data';
import 'dart:ui' as ui;

import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:qr_flutter/qr_flutter.dart';
import 'package:share_plus/share_plus.dart';
import 'package:superz_shared/superz_shared.dart';

import 'money_flow_page.dart' show SplitPart, orderSplit;
import 'share_image_save_io.dart'
    if (dart.library.js_interop) 'share_image_save_web.dart' as saver;

/// 分享卡:店铺卡片 / 订单晒单(带「钱去哪了」分账条)。
/// 客户端 Canvas 渲染(RepaintBoundary 截图),不经服务端。
///
/// 图是离屏截出来的,**底永远是白的**、颜色直接取浅色令牌,不跟随深色模式 ——
/// 跟随了反而会在深色下糊成一片。字重收到 600,价格和评分走 SzSerif 数字(设计稿 E/F)。
Future<void> showShareCard(BuildContext context, Widget card,
        {required String event, required Map<String, Object?> props}) =>
    szShowSheet<void>(
      context: context,
      isScrollControlled: true,
      builder: (context) =>
          _ShareSheet(card: (_) => card, event: event, props: props),
    );

/// 晒单:卡片下面有「金额打码」开关,拨一下卡上的金额当场变 ¥**、比例条不动。
///
/// 原来是先弹一个「晒单设置」对话框选打码,再弹分享卡 —— 选的时候看不到卡,
/// 看到卡的时候改不了。现在开关就放在卡底下。**默认仍是打码**(原来的默认值,
/// 晒到群里的图,金额是别人的隐私猜测线索)。
Future<void> showOrderShareCard(BuildContext context, Order order,
        {bool maskAmount = true}) =>
    szShowSheet<void>(
      context: context,
      isScrollControlled: true,
      builder: (context) => _ShareSheet(
        card: (mask) => orderShareCard(order, maskAmount: mask),
        maskInitial: maskAmount,
        event: 'share_order',
        props: {'order_no': order.orderNo},
      ),
    );

class _ShareSheet extends StatefulWidget {
  const _ShareSheet({
    required this.card,
    required this.event,
    required this.props,
    this.maskInitial,
  });

  final Widget Function(bool mask) card;
  final String event;
  final Map<String, Object?> props;

  /// 不给 = 这张卡没有金额,不画打码开关
  final bool? maskInitial;

  @override
  State<_ShareSheet> createState() => _ShareSheetState();
}

class _ShareSheetState extends State<_ShareSheet> {
  final _key = GlobalKey();
  late bool _mask = widget.maskInitial ?? false;
  bool _busy = false;

  Future<Uint8List> _png() async {
    final boundary =
        _key.currentContext!.findRenderObject() as RenderRepaintBoundary;
    final image = await boundary.toImage(pixelRatio: 3);
    final bytes = await image.toByteData(format: ui.ImageByteFormat.png);
    return bytes!.buffer.asUint8List();
  }

  Future<void> _run(Future<void> Function(Uint8List png) action) async {
    if (_busy) return;
    setState(() => _busy = true);
    try {
      await action(await _png());
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text(e.toString())));
      }
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  void _share() => _run((png) async {
        Analytics.track(widget.event, widget.props);
        await SharePlus.instance.share(ShareParams(files: [
          XFile.fromData(png, mimeType: 'image/png', name: 'superz_share.png'),
        ]));
      });

  void _save() => _run((png) async {
        Analytics.track('${widget.event}_save', widget.props);
        final msg = await saver.saveShareImage(
            png, 'superz_share_${DateTime.now().millisecondsSinceEpoch}');
        if (msg != null && mounted) {
          ScaffoldMessenger.of(context)
              .showSnackBar(SnackBar(content: Text(msg)));
        }
      });

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    return SafeArea(
      child: SingleChildScrollView(
        // 底部弹层顶上有拖拽条垫着;宽屏的对话框没有,自己留一截
        padding: EdgeInsets.fromLTRB(16, isSheetBottom(context) ? 0 : 20, 16, 22),
        // 底部弹层要撑满屏宽:里面都是定宽 320 的东西,不撑的话弹层按内容收窄、
        // 两边露出一截遮罩。宽屏的对话框形态照旧按内容收
        child: SizedBox(
          width: isSheetBottom(context) ? double.infinity : null,
          child: Column(mainAxisSize: MainAxisSize.min, children: [
            RepaintBoundary(key: _key, child: widget.card(_mask)),
            if (widget.maskInitial != null) ...[
              const SizedBox(height: 12),
              _maskSwitch(sz),
            ],
            const SizedBox(height: 14),
            SizedBox(
              width: kShareCardWidth,
              child: Row(children: [
                OutlinedButton.icon(
                  style: OutlinedButton.styleFrom(
                    minimumSize: const Size(0, 46),
                    padding: const EdgeInsets.symmetric(horizontal: 16),
                  ),
                  icon: const Icon(Icons.file_download_outlined, size: 17),
                  label: const Text('存图'),
                  onPressed: _busy ? null : _save,
                ),
                const SizedBox(width: 10),
                Expanded(
                  child: FilledButton.icon(
                    style:
                        FilledButton.styleFrom(minimumSize: const Size(0, 46)),
                    icon: const Icon(Icons.share_outlined, size: 18),
                    label: const Text('分享'),
                    onPressed: _busy ? null : _share,
                  ),
                ),
              ]),
            ),
            const SizedBox(height: 10),
            // 卡上本来就没有这三样(店名、菜、分账都是公开信息),这句话把它说破
            Text('图里不带你的手机号、地址和订单号',
                style: TextStyle(fontSize: kFontMicro, color: sz.inkMuted)),
          ]),
        ),
      ),
    );
  }

  Widget _maskSwitch(SzColors sz) => Container(
        width: kShareCardWidth,
        padding: const EdgeInsets.fromLTRB(12, 4, 4, 4),
        decoration: BoxDecoration(
          color: sz.surface,
          border: Border.all(color: sz.line),
          borderRadius: BorderRadius.circular(10),
        ),
        child: Row(children: [
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text('金额打码',
                    style: TextStyle(
                        fontSize: kFontBody,
                        fontWeight: FontWeight.w600,
                        color: sz.ink)),
                const SizedBox(height: 1),
                Text('打码后只留比例条,金额显示 ¥**',
                    style: TextStyle(fontSize: kFontMicro, color: sz.inkMuted)),
              ],
            ),
          ),
          SzSwitch(
            small: true,
            value: _mask,
            semanticLabel: '金额打码',
            onChanged: (v) => setState(() => _mask = v),
          ),
        ]),
      );
}

/// 分享卡的宽:320,出图 3 倍 = 960 宽,各家聊天软件都不会再压缩糊掉
const double kShareCardWidth = 320;

// 分享图没有深浅色之分,颜色一律取浅色令牌
const SzColors _c = SzColors.light;

Widget _cardShell({required List<Widget> children}) => Container(
      width: kShareCardWidth,
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: const Color(0x14000000)),
      ),
      child: DefaultTextStyle.merge(
        style: TextStyle(color: _c.ink),
        child: Column(
            crossAxisAlignment: CrossAxisAlignment.start, children: children),
      ),
    );

/// 页脚:品牌行 + 一句账 + 二维码。[pledge] 是那一句,各张卡按自己的实情给
Widget _footer(String pledge) => Row(
      crossAxisAlignment: CrossAxisAlignment.end,
      children: [
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(children: [
                const BrandLogo(size: 18),
                const SizedBox(width: 7),
                Text('超级赞外卖',
                    style: TextStyle(
                        color: _c.clay,
                        fontWeight: FontWeight.w600,
                        fontSize: kFontTitle)),
              ]),
              const SizedBox(height: 4),
              Text('$pledge\nchaojizan.cc',
                  style:
                      TextStyle(fontSize: 10, height: 1.5, color: _c.inkMuted)),
            ],
          ),
        ),
        const SizedBox(width: 12),
        QrImageView(
            data: 'https://chaojizan.cc/download?utm_source=share',
            size: 56,
            padding: EdgeInsets.zero),
      ],
    );

Widget _divider() => Container(
    height: 1,
    margin: const EdgeInsets.symmetric(vertical: 16),
    color: _c.line);

/// 店铺卡上列的一道菜。[from] = 有规格,价格后面带「起」
typedef ShareDish = ({String name, int priceCents, bool from});

/// 店铺分享卡(设计稿 E)。[dishes] 由店铺页从菜单里挑(见 MenuPage._shareDishes);
/// 不给就退回列表接口带的招牌菜
Widget shopShareCard(Merchant m, {List<ShareDish>? dishes}) {
  final list = dishes ??
      [
        for (final d in m.topDishes)
          (name: d.name, priceCents: d.priceCents, from: false),
      ];
  return _cardShell(children: [
    Text(m.name,
        style: const TextStyle(
            fontSize: kFigureMd,
            fontWeight: FontWeight.w600,
            letterSpacing: -0.2)),
    const SizedBox(height: 4),
    Row(children: [
      if (m.ratingCount > 0 && m.ratingAvg != null) ...[
        Icon(Icons.star_rounded, size: 15, color: _c.clay),
        const SizedBox(width: 3),
        Text('${m.ratingAvg}',
            style: szMoney(fontSize: kFontBodyLg, color: _c.ink)),
        const SizedBox(width: 10),
      ],
      if (m.monthlySales > 0)
        Text('月售 ${m.monthlySales}',
            style: TextStyle(fontSize: kFontNote, color: _c.inkMuted)),
    ]),
    if (list.isNotEmpty) ...[
      const SizedBox(height: 10),
      for (final d in list.take(3))
        Padding(
          padding: const EdgeInsets.only(bottom: 4),
          child: Row(children: [
            Expanded(
              child: Text('· ${d.name}',
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: const TextStyle(fontSize: kFontBody)),
            ),
            Text('${yuan(d.priceCents)}${d.from ? ' 起' : ''}',
                style: szMoney(
                    fontSize: kFontBody,
                    fontWeight: FontWeight.w400,
                    color: _c.ink)),
          ]),
        ),
    ],
    _divider(),
    // 这家店的实情:抽成按它自己的档位写;自己送的店配送费归商家,不写「全归骑手」
    _footer('商家只抽 ${m.commissionPct}%'
        '${m.selfDelivery ? '' : ' · 配送费全归骑手'} · 账目公开'),
  ]);
}

/// 比例 → 「5」「4.5」(一位小数,去掉 .0)
String _pct(num part, num whole) {
  final tenths = (part * 1000 / whole).round();
  return tenths % 10 == 0
      ? '${tenths ~/ 10}'
      : '${tenths ~/ 10}.${tenths % 10}';
}

/// 晒单分享卡(设计稿 F):钱去哪了三方分账条,金额可打码。
///
/// 分法和订单详情、「钱去哪了」页是同一个函数(money_flow_page.dart 的 orderSplit)——
/// 原来这里自己按外卖公式算,商家自送单被写成「骑手 ¥5(配送费+小费全额)」,
/// 跑腿单的「商家」是个负数。段宽按金额,金额为 0 的那段不画
/// (原来按整数百分比取 flex、最少给 1,0 元的一段也会画出一条)。
Widget orderShareCard(Order o, {required bool maskAmount}) {
  final parts = orderSplit(o).parts;
  String money(int cents) => maskAmount ? '¥**' : yuan(cents);
  Color colorOf(SplitPart p) => p.isHold
      ? _c.hold
      : p.short == '商家'
          ? _c.clay
          : p.short == '骑手'
              ? _c.earn
              : _c.inkFaint;
  String noteOf(SplitPart p) {
    if (p.short == '骑手' && !o.isErrand) {
      return o.tipCents > 0 ? '(配送费+小费全额)' : '(配送费全额)';
    }
    if (p.short == '商家' && o.selfDelivery) return '(含配送费,商家自己送)';
    return '';
  }

  final gross = o.merchantNetCents + o.commissionCents;
  final pledge = o.isErrand
      ? (o.deliveryFeeCents > 0
          ? '跑腿费平台只收 ${_pct(o.commissionCents, o.deliveryFeeCents)}% · 账目公开'
          : '账目公开')
      : '商家只抽 ${gross > 0 ? _pct(o.commissionCents, gross) : '5'}%'
          '${o.selfDelivery ? '' : ' · 配送费全归骑手'} · 账目公开';
  final shown = [
    for (final p in parts)
      if (p.cents > 0) p
  ];

  return _cardShell(children: [
    Text(o.merchantName.isEmpty ? '我在超级赞下了一单' : '我在「${o.merchantName}」点了一单',
        style: const TextStyle(
            fontSize: kFontTitle, fontWeight: FontWeight.w600, height: 1.4)),
    const SizedBox(height: 4),
    Text(o.summary,
        maxLines: 2,
        overflow: TextOverflow.ellipsis,
        style: TextStyle(fontSize: kFontBody, color: _c.inkMuted)),
    const SizedBox(height: 12),
    const Text('这单的钱去哪了(平台公开账目)',
        style: TextStyle(fontSize: kFontNote, fontWeight: FontWeight.w600)),
    const SizedBox(height: 6),
    ClipRRect(
      borderRadius: BorderRadius.circular(4),
      child: SizedBox(
        height: 8,
        // stretch 不能省:ColoredBox 没有子节点时按最小约束取高,不拉满就是 0 高、整条看不见
        child: Row(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          for (final p in shown)
            Expanded(flex: p.cents, child: ColoredBox(color: colorOf(p))),
        ]),
      ),
    ),
    const SizedBox(height: 6),
    Text.rich(
      TextSpan(children: [
        for (final (i, p) in shown.indexed) ...[
          if (i > 0) const TextSpan(text: ' · '),
          TextSpan(text: '${p.short} '),
          TextSpan(
              text: money(p.cents),
              style: szMoney(fontSize: kFontMicro, color: _c.ink)),
          if (noteOf(p).isNotEmpty) TextSpan(text: noteOf(p)),
        ],
      ]),
      style: const TextStyle(fontSize: kFontMicro, height: 1.6),
    ),
    _divider(),
    _footer(pledge),
  ]);
}
