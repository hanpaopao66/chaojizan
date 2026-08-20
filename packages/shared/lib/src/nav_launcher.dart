/// 唤起外部地图导航(#137)。
///
/// 为什么给选择而不是写死一个:骑手装哪个地图是他自己的习惯,
/// 强制跳一个他不用的 App,他就只能手输地址 —— 那比不给导航还慢。
/// 原先写死跳高德,骑手没装高德就掉进网页版,骑行导航几乎不可用。
///
/// **只用公开的跳转协议(URL Scheme),不接任何地图 SDK**,
/// 所以不需要 key、不增加包体积、不引入新的第三方 SDK 公示义务。
library;

import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';

import 'brand.dart';
import 'coord_utils.dart';
import 'responsive.dart';

/// 出行方式。骑手送餐是骑行,用户看店是驾车/步行。
enum NavMode { ride, drive, walk }

@immutable
class _MapApp {
  const _MapApp({
    required this.name,
    required this.scheme,
    required this.build,
    required this.web,
  });

  final String name;

  /// 用来探测「装没装」的 scheme 前缀
  final String scheme;

  /// 入参一律 GCJ-02;需要别的坐标系由各自内部转
  final Uri Function(double lat, double lng, String name, NavMode mode) build;

  /// 没装 App 时的网页兜底
  final Uri Function(double lat, double lng, String name, NavMode mode) web;
}

String _amapT(NavMode m) => switch (m) {
      NavMode.ride => '3',
      NavMode.drive => '0',
      NavMode.walk => '2',
    };

String _qqType(NavMode m) => switch (m) {
      NavMode.ride => 'bike',
      NavMode.drive => 'drive',
      NavMode.walk => 'walk',
    };

String _bdMode(NavMode m) => switch (m) {
      NavMode.ride => 'riding',
      NavMode.drive => 'driving',
      NavMode.walk => 'walking',
    };

final List<_MapApp> _apps = [
  _MapApp(
    name: '腾讯地图',
    scheme: 'qqmap://',
    build: (lat, lng, n, m) =>
        Uri.parse('qqmap://map/routeplan?type=${_qqType(m)}'
            '&tocoord=$lat,$lng&to=${Uri.encodeComponent(n)}'
            '&referer=superz'),
    web: (lat, lng, n, m) =>
        Uri.parse('https://apis.map.qq.com/uri/v1/routeplan?type=${_qqType(m)}'
            '&to=${Uri.encodeComponent(n)}&tocoord=$lat,$lng&referer=superz'),
  ),
  _MapApp(
    name: '高德地图',
    // iOS 与 Android 的 scheme 不同,这里只用来探测,真正的地址在 build 里分平台
    scheme: 'iosamap://',
    build: (lat, lng, n, m) =>
        Uri.parse(defaultTargetPlatform == TargetPlatform.iOS
            // dev=0 表示传入的已经是 GCJ-02,别让它再纠偏一次
            ? 'iosamap://path?sourceApplication=superz'
                '&dlat=$lat&dlon=$lng&dname=${Uri.encodeComponent(n)}'
                '&dev=0&t=${_amapT(m)}'
            : 'amapuri://route/plan/?sourceApplication=superz'
                '&dlat=$lat&dlon=$lng&dname=${Uri.encodeComponent(n)}'
                '&dev=0&t=${_amapT(m)}'),
    web: (lat, lng, n, m) => Uri.parse(
        'https://uri.amap.com/navigation?to=$lng,$lat,'
        '${Uri.encodeComponent(n)}&mode=${m == NavMode.ride ? "ride" : "car"}'
        '&src=superz'),
  ),
  _MapApp(
    name: '百度地图',
    scheme: 'baidumap://',
    // 百度吃 BD-09。直接传 GCJ-02 会偏几百米 —— 骑手照着导航跑到隔壁街
    build: (lat, lng, n, m) {
      final bd = gcj02ToBd09(lat, lng);
      return Uri.parse('baidumap://map/direction?destination=name:'
          '${Uri.encodeComponent(n)}|latlng:${bd.lat},${bd.lng}'
          '&coord_type=bd09ll&mode=${_bdMode(m)}&src=superz');
    },
    web: (lat, lng, n, m) {
      final bd = gcj02ToBd09(lat, lng);
      return Uri.parse(
          'https://api.map.baidu.com/direction?destination=${bd.lat},${bd.lng}'
          '&mode=${_bdMode(m)}&coord_type=bd09ll&output=html&src=superz');
    },
  ),
];

/// 探测装了哪些地图。全都没装时返回空列表(调用方直接走网页兜底)。
///
/// Android 11+ 要在 AndroidManifest 里声明 `<queries>` 才查得到别的 App,
/// 没声明的话这里一律返回 false —— 表现为"明明装了却不给选"。
Future<List<String>> installedMapApps() async {
  final out = <String>[];
  for (final a in _apps) {
    try {
      if (await canLaunchUrl(Uri.parse(a.scheme))) out.add(a.name);
    } catch (_) {
      // 探测失败按没装处理:少一个选项,不至于卡住导航
    }
  }
  return out;
}

/// 弹出地图选择并唤起导航。坐标一律传 **GCJ-02**。
///
/// 只装了一个(或一个都没装)时**不弹选择**,直接走 —— 为了一个选项让人多点
/// 一次,是把"给选择"做成了"加一步"。
Future<void> navigateTo(
  BuildContext context, {
  required double lat,
  required double lng,
  required String name,
  NavMode mode = NavMode.ride,
}) async {
  final installed = await installedMapApps();
  if (!context.mounted) return;

  Future<void> go(_MapApp a) async {
    final uri = a.build(lat, lng, name, mode);
    if (await canLaunchUrl(uri)) {
      await launchUrl(uri);
      return;
    }
    await launchUrl(a.web(lat, lng, name, mode),
        mode: LaunchMode.externalApplication);
  }

  if (installed.isEmpty) {
    // 一个都没装:走腾讯网页版,不再弹一个只有一项的选择框
    await launchUrl(_apps.first.web(lat, lng, name, mode),
        mode: LaunchMode.externalApplication);
    return;
  }
  if (installed.length == 1) {
    await go(_apps.firstWhere((a) => a.name == installed.first));
    return;
  }

  final sz = Theme.of(context).sz;
  await szShowSheet<void>(
    context: context,
    builder: (sheetCtx) => SafeArea(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(kPagePad, 14, kPagePad, 6),
            child: Row(children: [
              Text('用哪个地图导航',
                  style: TextStyle(
                      fontSize: 15,
                      fontWeight: FontWeight.w600,
                      color: sz.ink)),
              const Spacer(),
              Text(name, style: TextStyle(fontSize: 12, color: sz.inkMuted)),
            ]),
          ),
          for (final a in _apps.where((a) => installed.contains(a.name)))
            ListTile(
              leading: Icon(Icons.navigation_outlined, color: sz.clay),
              title: Text(a.name),
              onTap: () {
                Navigator.pop(sheetCtx);
                go(a);
              },
            ),
          const SizedBox(height: 6),
        ],
      ),
    ),
  );
}
