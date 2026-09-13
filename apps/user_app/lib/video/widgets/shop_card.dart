import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:flutter/material.dart';
import 'package:geolocator/geolocator.dart';
import 'package:superz_shared/superz_shared.dart';

import '../../locate.dart';
import '../../main.dart' show MenuPage;
import '../../session.dart';
import '../models.dart';
import '../nav.dart';

/// 视频挂的那家店(D16):只能挂本平台的店;UP 主声明了「有合作」就标「合作」;平台不收推广费。
///
/// 服务端给 `shop: {id, name, logo, biz_type, is_open, lat, lng, commission_rate}`。
/// 费率照这家店的真实费率写(阶梯费率 5% / 4.5% / 4%,不是写死的 5%),和店铺页那句「这家店在超级赞只被抽 N%」同一个数。
double? shopRate(Map<String, dynamic> shop) => (shop['commission_rate'] as num?)?.toDouble();

/// 0.05 → 「5」,0.045 → 「4.5」(按一位小数取整,浮点的 4.4999… 也写成 4.5)
String ratePct(double rate) {
  final v = rate * 100;
  final r = (v * 10).round() / 10;
  return r == r.roundToDouble() ? '${r.round()}' : r.toStringAsFixed(1);
}

/// 进这家店的店铺页(用户端现有的 MenuPage)。
Future<void> openVideoShop(BuildContext context, int shopId) async {
  try {
    final m = await rootApi.merchantDetail(shopId);
    if (!context.mounted) return;
    await Navigator.of(context)
        .push(MaterialPageRoute<void>(builder: (_) => MenuPage(api: rootApi, merchant: m)));
  } on ApiException catch (e) {
    if (context.mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(e.message)));
  }
}

({double lat, double lng})? _here;
DateTime? _hereAt;

/// 用户现在在哪(只在**已经给过定位权限**时才取,不为了算个距离在视频页弹权限框)。拿不到就是 null,
/// 卡片上就不写距离。取到的留 5 分钟,连着点几个视频不用每次都定位。
Future<({double lat, double lng})?> knownLocation() async {
  final at = _hereAt;
  if (_here != null && at != null && DateTime.now().difference(at) < const Duration(minutes: 5)) return _here;
  try {
    final p = await Geolocator.checkPermission();
    if (p != LocationPermission.always && p != LocationPermission.whileInUse) return null;
    Position? pos;
    if (!kIsWeb) {
      try {
        pos = await deviceLastKnownPosition();
      } catch (_) {}
    }
    pos ??= await deviceCurrentPosition(accuracy: LocationAccuracy.low, timeLimit: const Duration(seconds: 5));
    final g = wgs84ToGcj02(pos.latitude, pos.longitude);
    _here = (lat: g.lat, lng: g.lng);
    _hereAt = DateTime.now();
    return _here;
  } catch (_) {
    return null;
  }
}

/// 「合作」小标:hold 实底白字(和卡片封面上的那个一样)。
class CollabTag extends StatelessWidget {
  const CollabTag({super.key});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 5, vertical: 1),
      decoration: BoxDecoration(color: Theme.of(context).sz.hold, borderRadius: BorderRadius.circular(4)),
      child: const Text('合作', style: TextStyle(color: Colors.white, fontSize: kFontMicro, height: 1.3)),
    );
  }
}

/// 视频详情里的店铺卡(设计稿 E):顶上一道这家店频道色的细条;店名 +「合作」;
/// 「视频里这家 · 距离 · 只被抽 N%」;右边「去点单」,店没营业是「休息中」,照样能进店看。整张卡都能点。
class VideoShopCard extends StatefulWidget {
  const VideoShopCard({super.key, required this.shop, required this.collab});

  final Map<String, dynamic> shop;
  final bool collab;

  @override
  State<VideoShopCard> createState() => _VideoShopCardState();
}

class _VideoShopCardState extends State<VideoShopCard> {
  double? _distance;

  @override
  void initState() {
    super.initState();
    _locate();
  }

  Future<void> _locate() async {
    final lat = (widget.shop['lat'] as num?)?.toDouble(), lng = (widget.shop['lng'] as num?)?.toDouble();
    if (lat == null || lng == null) return;
    final here = await knownLocation();
    if (here == null || !mounted) return;
    setState(() => _distance = distanceMeters(here.lat, here.lng, lat, lng));
  }

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    final s = widget.shop;
    final id = vInt(s['id']);
    final name = '${s['name'] ?? ''}';
    final logo = '${s['logo'] ?? ''}';
    final open = s['is_open'] != false;
    final rate = shopRate(s);
    final tone = channelOfBizType('${s['biz_type'] ?? ''}')?.tone;
    final bar = tone != null && tone < sz.channelTones.length ? sz.channelTones[tone] : sz.clay;
    final sub = [
      '视频里这家',
      if (_distance != null) distanceLabel(_distance!),
      if (rate != null) '只被抽 ${ratePct(rate)}%',
    ].join(' · ');
    void go() => openVideoShop(context, id);
    return Material(
      color: sz.surface,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(kRadiusMd), side: BorderSide(color: sz.line)),
      clipBehavior: Clip.antiAlias,
      child: InkWell(
        onTap: id == 0 ? null : go,
        child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          Container(height: 3, color: bar),
          Padding(
            padding: const EdgeInsets.fromLTRB(kCardPad, 12, 12, 12),
            child: Row(children: [
              SzImage(url: logo.isEmpty ? '' : videoResolve(logo), name: name, size: 40, radius: kRadiusSm),
              const SizedBox(width: 11),
              Expanded(
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Row(children: [
                    Flexible(
                      child: Text(name,
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: TextStyle(fontSize: kFontBodyLg, fontWeight: FontWeight.w600, color: sz.ink)),
                    ),
                    if (widget.collab) const Padding(padding: EdgeInsets.only(left: 6), child: CollabTag()),
                  ]),
                  const SizedBox(height: 2),
                  Text(sub,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: TextStyle(fontSize: kFontNote, color: sz.inkMuted)),
                ]),
              ),
              const SizedBox(width: 8),
              open
                  ? FilledButton(
                      style: FilledButton.styleFrom(
                        minimumSize: const Size(0, 32),
                        padding: const EdgeInsets.symmetric(horizontal: 14),
                        textStyle: const TextStyle(fontSize: kFontBody, fontWeight: FontWeight.w600),
                      ),
                      onPressed: id == 0 ? null : go,
                      child: const Text('去点单'),
                    )
                  : OutlinedButton(
                      style: OutlinedButton.styleFrom(
                        foregroundColor: sz.inkMuted,
                        minimumSize: const Size(0, 32),
                        padding: const EdgeInsets.symmetric(horizontal: 14),
                        textStyle: const TextStyle(fontSize: kFontBody, fontWeight: FontWeight.w500),
                      ),
                      onPressed: id == 0 ? null : go,
                      child: const Text('休息中'),
                    ),
            ]),
          ),
        ]),
      ),
    );
  }
}

/// 竖屏流底部信息区里的店名(D16:挂了店、有合作就要标出来;竖屏原来没标,是合规缺口)。点了进店。
class VideoShopChip extends StatelessWidget {
  const VideoShopChip({super.key, required this.shop, required this.collab});

  final Map<String, dynamic> shop;
  final bool collab;

  @override
  Widget build(BuildContext context) {
    final id = vInt(shop['id']);
    final name = '${shop['name'] ?? ''}';
    return GestureDetector(
      onTap: id == 0 ? null : () => openVideoShop(context, id),
      child: Container(
        padding: const EdgeInsets.fromLTRB(8, 4, 8, 4),
        decoration: BoxDecoration(color: Colors.black.withValues(alpha: .38), borderRadius: BorderRadius.circular(kRadiusSm)),
        child: Row(mainAxisSize: MainAxisSize.min, children: [
          const Icon(Icons.storefront_outlined, size: 14, color: Colors.white),
          const SizedBox(width: 4),
          Flexible(
            child: Text(name,
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: const TextStyle(color: Colors.white, fontSize: kFontNote, fontWeight: FontWeight.w600)),
          ),
          if (collab) const Padding(padding: EdgeInsets.only(left: 6), child: CollabTag()),
          const SizedBox(width: 2),
          const Icon(Icons.chevron_right, size: 14, color: Colors.white70),
        ]),
      ),
    );
  }
}
