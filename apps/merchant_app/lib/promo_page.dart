import 'dart:ui' as ui;

import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter/services.dart';
import 'package:qr_flutter/qr_flutter.dart';
import 'package:share_plus/share_plus.dart';
import 'package:superz_shared/superz_shared.dart';

/// 店铺专属码与一键海报(#116)。
///
/// 平台没有补贴预算,买不来流量,商家自己带客是唯一能规模化的获客渠道 ——
/// 而商家在这里每单多留十几个点,本来就有动力把老客带过来。平台出物料不出钱。
///
/// 海报是客户端离屏渲染(RepaintBoundary 截图)的,不占服务端资源,
/// 也不需要商家会用任何设计工具。
class MerchantPromoPage extends StatefulWidget {
  const MerchantPromoPage({super.key, required this.api});

  final ApiClient api;

  @override
  State<MerchantPromoPage> createState() => _MerchantPromoPageState();
}

class _MerchantPromoPageState extends State<MerchantPromoPage> {
  final _posterKey = GlobalKey();
  Map<String, dynamic>? _promo;
  Object? _error;
  bool _sharing = false;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() => _error = null);
    try {
      final promo = await widget.api.merchantPromo();
      if (!mounted) return;
      setState(() => _promo = promo);
    } catch (e) {
      if (!mounted) return;
      setState(() => _error = e);
    }
  }

  Future<void> _sharePoster() async {
    setState(() => _sharing = true);
    try {
      final boundary =
          _posterKey.currentContext!.findRenderObject() as RenderRepaintBoundary;
      // 3x:打印出来贴在收银台/门口也不糊
      final image = await boundary.toImage(pixelRatio: 3);
      final bytes = await image.toByteData(format: ui.ImageByteFormat.png);
      await SharePlus.instance.share(ShareParams(files: [
        XFile.fromData(bytes!.buffer.asUint8List(),
            mimeType: 'image/png', name: 'superz_shop_poster.png'),
      ]));
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text('$e')));
    } finally {
      if (mounted) setState(() => _sharing = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final promo = _promo;
    return Scaffold(
      appBar: AppBar(title: const Text('专属码与海报')),
      body: _error != null
          ? SzError(error: _error!, onRetry: _load)
          : promo == null
              ? const Center(child: CircularProgressIndicator())
              : ListView(
                  padding: const EdgeInsets.all(kPagePad),
                  children: [
                    Text('把这张海报贴在店里,或发给你的老客。'
                        '他们从这里下单,你少被抽的那部分就是实打实多留下的。',
                        style: theme.textTheme.bodyMedium
                            ?.copyWith(color: theme.sz.inkMuted)),
                    const SizedBox(height: 16),
                    Center(
                      child: RepaintBoundary(
                        key: _posterKey,
                        child: _Poster(promo: promo),
                      ),
                    ),
                    const SizedBox(height: 20),
                    FilledButton.icon(
                      onPressed: _sharing ? null : _sharePoster,
                      icon: const Icon(Icons.ios_share, size: 18),
                      label: Text(_sharing ? '生成中…' : '保存 / 分享海报'),
                    ),
                    const SizedBox(height: 10),
                    OutlinedButton.icon(
                      onPressed: () async {
                        await Clipboard.setData(
                            ClipboardData(text: '${promo['url']}'));
                        if (!context.mounted) return;
                        ScaffoldMessenger.of(context).showSnackBar(
                            const SnackBar(content: Text('专属链接已复制')));
                      },
                      icon: const Icon(Icons.link, size: 18),
                      label: const Text('复制专属链接'),
                    ),
                    const SizedBox(height: 20),
                    SzCard(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          const SzSectionTitle('这张海报能带来什么'),
                          const SizedBox(height: 8),
                          _Bullet('顾客扫码先看到落地页,再下载 App —— '
                              '没装 App 的人也不会白扫一次'),
                          _Bullet('平台不做竞价排名,你的位置买不到也抢不走,'
                              '带来的客都是你自己的'),
                          _Bullet('印在海报上的费率是你这家店的真实费率,'
                              '单量上去自动降档,海报下次生成就会跟着变'),
                        ],
                      ),
                    ),
                  ],
                ),
    );
  }
}

class _Bullet extends StatelessWidget {
  const _Bullet(this.text);

  final String text;

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.only(bottom: 6),
        child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text('· ', style: TextStyle(color: Theme.of(context).sz.inkMuted)),
          Expanded(
              child: Text(text,
                  style: Theme.of(context)
                      .textTheme
                      .bodySmall
                      ?.copyWith(color: Theme.of(context).sz.inkMuted))),
        ]),
      );
}

/// 海报本体。会被离屏截图成 PNG,所以:
/// 不跟随 App 主题(深色下截出来是黑底,打印一片墨),固定取浅色令牌;
/// 不用 MediaQuery 相关尺寸,免得不同机型截出来的图不一样大。
class _Poster extends StatelessWidget {
  const _Poster({required this.promo});

  final Map<String, dynamic> promo;

  @override
  Widget build(BuildContext context) {
    final c = SzColors.light;
    final rate = ((promo['commission_rate'] as num?) ?? 0.05) * 100;
    // 5.0% 写成「5%」,4.5% 保留一位
    final rateText = rate == rate.roundToDouble()
        ? '${rate.round()}%'
        : '${rate.toStringAsFixed(1)}%';
    final off = (promo['coupon_off_cents'] as num?)?.toInt() ?? 0;
    final threshold = (promo['coupon_threshold_cents'] as num?)?.toInt() ?? 0;

    return Container(
      width: 320,
      padding: const EdgeInsets.fromLTRB(24, 26, 24, 20),
      decoration: BoxDecoration(
        color: c.paper,
        borderRadius: BorderRadius.circular(kRadiusLg),
        border: Border.all(color: c.line),
      ),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text('${promo['shop_name']}',
            maxLines: 2,
            overflow: TextOverflow.ellipsis,
            style: TextStyle(
                fontFamily: kSerifFamily,
                fontSize: 24,
                height: 1.25,
                letterSpacing: -0.4,
                fontWeight: FontWeight.w600,
                color: c.ink)),
        const SizedBox(height: 6),
        Text('已入驻超级赞',
            style: TextStyle(fontSize: 13, color: c.inkMuted)),
        const SizedBox(height: 18),
        Container(
          padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
          decoration: BoxDecoration(
              color: c.claySoft, borderRadius: BorderRadius.circular(kRadiusMd)),
          child: Row(children: [
            Text(rateText,
                style: TextStyle(
                    fontFamily: kSerifFamily,
                    fontSize: 30,
                    fontWeight: FontWeight.w600,
                    color: c.clay,
                    fontFeatures: const [FontFeature.oldstyleFigures()])),
            const SizedBox(width: 12),
            Expanded(
                child: Text('这家店在超级赞的抽成\n配送费 100% 归骑手',
                    style: TextStyle(
                        fontSize: 12, height: 1.5, color: c.ink))),
          ]),
        ),
        const SizedBox(height: 18),
        Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Container(
            padding: const EdgeInsets.all(6),
            decoration: BoxDecoration(
                color: Colors.white,
                borderRadius: BorderRadius.circular(kRadiusSm),
                border: Border.all(color: c.line)),
            child: QrImageView(
                data: '${promo['url']}',
                size: 96,
                padding: EdgeInsets.zero,
                backgroundColor: Colors.white,
                eyeStyle: QrEyeStyle(
                    eyeShape: QrEyeShape.square, color: c.ink),
                dataModuleStyle: QrDataModuleStyle(
                    dataModuleShape: QrDataModuleShape.square, color: c.ink)),
          ),
          const SizedBox(width: 14),
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text('扫码到店下单',
                  style: TextStyle(
                      fontSize: 15, fontWeight: FontWeight.w600, color: c.ink)),
              const SizedBox(height: 4),
              if (off > 0)
                Text(
                    threshold > 0
                        ? '本店优惠券:满 ${yuan(threshold)} 减 ${yuan(off)}'
                        : '本店优惠券:立减 ${yuan(off)}',
                    style: TextStyle(
                        fontSize: 12, height: 1.5, color: c.clay)),
              const SizedBox(height: 4),
              Text('店铺码 ${promo['short_code']}',
                  style: TextStyle(
                      fontSize: 12,
                      color: c.inkMuted,
                      fontFeatures: const [FontFeature.tabularFigures()])),
            ]),
          ),
        ]),
        const SizedBox(height: 16),
        Divider(height: 1, color: c.line),
        const SizedBox(height: 12),
        Text('超级赞 · 不做竞价排名 · 不杀熟 · 每一单的钱去哪了都可查',
            style: TextStyle(fontSize: 10.5, color: c.inkMuted)),
        const SizedBox(height: 2),
        Text('chaojizan.cc',
            style: TextStyle(fontSize: 10.5, color: c.inkMuted)),
      ]),
    );
  }
}
