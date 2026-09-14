import 'package:flutter/foundation.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:superz_shared/superz_shared.dart';

/// 桌面版(Windows / macOS / Ubuntu)对外发之后,几处插件按平台保护的判据(platform_caps.dart)。
///
/// 这张表就是「哪个平台上哪项能力有实现」—— 按插件的 pubspec 平台声明核过:
/// video_player 只有 android / ios / macos / web;image_picker 在桌面上不能拍照;
/// share_plus 在 Linux 上分享不了文件。以后给哪个平台接上了实现(比如 Windows 的播放器),
/// 改判据的同时改这张表。网页(kIsWeb)在 VM 测试里取不到,这里只测原生包。
void main() {
  tearDown(() => debugDefaultTargetPlatformOverride = null);

  const table = <TargetPlatform, ({bool desktop, bool video, bool camera, bool shareFiles, bool scan})>{
    TargetPlatform.android: (desktop: false, video: true, camera: true, shareFiles: true, scan: true),
    TargetPlatform.iOS: (desktop: false, video: true, camera: true, shareFiles: true, scan: true),
    TargetPlatform.macOS: (desktop: true, video: true, camera: false, shareFiles: true, scan: false),
    TargetPlatform.windows: (desktop: true, video: false, camera: false, shareFiles: true, scan: false),
    TargetPlatform.linux: (desktop: true, video: false, camera: false, shareFiles: false, scan: false),
  };

  for (final MapEntry(key: platform, value: want) in table.entries) {
    test('${platform.name}:桌面 ${want.desktop} / 视频 ${want.video} / 拍照 ${want.camera} / '
        '分享文件 ${want.shareFiles} / 扫码入口 ${want.scan}', () {
      debugDefaultTargetPlatformOverride = platform;
      expect(szIsDesktopApp, want.desktop);
      expect(szCanPlayVideo, want.video);
      expect(szCanUseCamera, want.camera);
      expect(szCanShareFiles, want.shareFiles);
      expect(szShowScanEntry, want.scan);
    });
  }

  test('地图 SDK 只有安卓和 iOS(桌面上走文字兜底)', () {
    for (final p in TargetPlatform.values) {
      debugDefaultTargetPlatformOverride = p;
      expect(mapSdkSupported, p == TargetPlatform.android || p == TargetPlatform.iOS, reason: p.name);
    }
  });

  group('versions.json 里桌面版的条目(desktopReleaseOf)', () {
    const entry = {'version': '0.19.0', 'build': 2061, 'page': 'https://chaojizan.cc/download#desktop'};

    test('新格式:desktop 键下按端取', () {
      final all = {
        'user': {'version': '0.19.0', 'build': 2061, 'url': 'x.apk'},
        'desktop': {'user': entry},
      };
      expect(desktopReleaseOf(all, 'user'), entry);
      expect(desktopReleaseOf(all, 'merchant'), isNull, reason: '只有用户端出了桌面版');
    });

    test('老 versions.json 没有 desktop 键:回 null,绝不能拿 APK 那一条当桌面版', () {
      expect(desktopReleaseOf({'user': {'build': 2061, 'url': 'x.apk'}}, 'user'), isNull);
      expect(desktopReleaseOf(null, 'user'), isNull);
      expect(desktopReleaseOf('<html>', 'user'), isNull);
      expect(desktopReleaseOf({'desktop': 'x'}, 'user'), isNull);
      expect(desktopReleaseOf({'desktop': {'user': 3}}, 'user'), isNull);
    });
  });
}
