import 'dart:ui' as ui;

import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:qr_flutter/qr_flutter.dart';
import 'package:share_plus/share_plus.dart';
import 'package:superz_shared/superz_shared.dart';

/// 分享卡:店铺卡片 / 订单晒单(带「钱去哪了」分账条,全网独一份)。
/// 客户端 Canvas 渲染(RepaintBoundary 截图),不依赖服务端。
Future<void> showShareCard(BuildContext context, Widget card,
    {required String event, required Map<String, Object?> props}) async {
  final key = GlobalKey();
  await showModalBottomSheet<void>(
    context: context,
    isScrollControlled: true,
    builder: (context) => SafeArea(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          RepaintBoundary(key: key, child: card),
          const SizedBox(height: 12),
          SizedBox(
            width: double.infinity,
            child: FilledButton.icon(
              icon: const Icon(Icons.share),
              label: const Text('分享'),
              onPressed: () async {
                try {
                  Analytics.track(event, props);
                  final boundary = key.currentContext!.findRenderObject()
                      as RenderRepaintBoundary;
                  final image = await boundary.toImage(pixelRatio: 3);
                  final bytes = await image.toByteData(
                      format: ui.ImageByteFormat.png);
                  await SharePlus.instance.share(ShareParams(files: [
                    XFile.fromData(bytes!.buffer.asUint8List(),
                        mimeType: 'image/png', name: 'superz_share.png'),
                  ]));
                } catch (e) {
                  if (!context.mounted) return;
                  ScaffoldMessenger.of(context).showSnackBar(
                      SnackBar(content: Text(e.toString())));
                }
              },
            ),
          ),
        ]),
      ),
    ),
  );
}

Widget _cardShell({required List<Widget> children}) => Container(
      width: 320,
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: const Color(0x14000000)),
      ),
      child: Column(
          crossAxisAlignment: CrossAxisAlignment.start, children: children),
    );

Widget _footer() => Row(children: [
      Expanded(
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          const Text('超级赞外卖',
              style: TextStyle(
                  color: kBrandOrange,
                  fontWeight: FontWeight.w900,
                  fontSize: 16)),
          Text('商家只抽5% · 配送费全归骑手 · 账目公开',
              style: TextStyle(fontSize: 10, color: Colors.grey.shade600)),
          Text('aikas.com.cn',
              style: TextStyle(fontSize: 10, color: Colors.grey.shade600)),
        ]),
      ),
      QrImageView(
          data: 'https://aikas.com.cn/download?utm_source=share',
          size: 56,
          padding: EdgeInsets.zero),
    ]);

/// 店铺分享卡
Widget shopShareCard(Merchant m) => _cardShell(children: [
      Text(m.name,
          style: const TextStyle(fontSize: 20, fontWeight: FontWeight.w800)),
      const SizedBox(height: 4),
      Row(children: [
        if (m.ratingAvg != null) ...[
          const Icon(Icons.star, size: 14, color: kBrandOrange),
          Text(' ${m.ratingAvg}  ',
              style: const TextStyle(fontWeight: FontWeight.w700)),
        ],
        if (m.monthlySales > 0)
          Text('月售 ${m.monthlySales}',
              style: TextStyle(fontSize: 12, color: Colors.grey.shade600)),
      ]),
      if (m.topDishes.isNotEmpty) ...[
        const SizedBox(height: 8),
        for (final d in m.topDishes.take(3))
          Text('· ${d.name}  ${yuan(d.priceCents)}',
              style: const TextStyle(fontSize: 13)),
      ],
      const Divider(height: 20),
      _footer(),
    ]);

/// 晒单分享卡:钱去哪了三方分账条(金额可打码)
Widget orderShareCard(Order o, {required bool maskAmount}) {
  final merchantPart =
      o.foodCents + o.packingFeeCents - o.discountCents - o.commissionCents;
  final riderPart = o.deliveryFeeCents + o.tipCents;
  final platformPart = o.commissionCents;
  final total = merchantPart + riderPart + platformPart;
  String money(int cents) => maskAmount ? '¥**' : yuan(cents);
  Widget seg(Color c, int part) => Expanded(
        flex: total > 0 ? (part * 100 ~/ total).clamp(1, 100) : 1,
        child: Container(height: 8, color: c),
      );
  return _cardShell(children: [
    Text('我在「${o.merchantName}」点了一单',
        style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w800)),
    const SizedBox(height: 4),
    Text(o.summary,
        maxLines: 2,
        overflow: TextOverflow.ellipsis,
        style: TextStyle(fontSize: 13, color: Colors.grey.shade700)),
    const SizedBox(height: 12),
    const Text('这单的钱去哪了(平台公开账目)',
        style: TextStyle(fontSize: 12, fontWeight: FontWeight.w700)),
    const SizedBox(height: 6),
    ClipRRect(
      borderRadius: BorderRadius.circular(4),
      child: Row(children: [
        seg(kBrandOrange, merchantPart),
        seg(kMoneyGreen, riderPart),
        seg(Colors.blueGrey, platformPart),
      ]),
    ),
    const SizedBox(height: 6),
    Text('商家 ${money(merchantPart)} · 骑手 ${money(riderPart)}'
        '(配送费+小费全额)· 平台 ${money(platformPart)}',
        style: const TextStyle(fontSize: 11)),
    const Divider(height: 20),
    _footer(),
  ]);
}
