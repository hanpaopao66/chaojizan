import 'dart:io';
import 'dart:typed_data';

import 'package:file_selector/file_selector.dart' show XTypeGroup, getSaveLocation;
import 'package:gal/gal.dart';
import 'package:share_plus/share_plus.dart';
import 'package:superz_shared/superz_shared.dart' show szIsDesktopApp;

/// 手机:分享图存进相册(安卓 10 起不用存储权限,和聊天存图同一个库)。
/// 存不进去(老系统没权限)就交给系统分享面板,让人自己选存哪。
///
/// 电脑版:弹系统的存储对话框存成 PNG。不走 gal —— macOS 上写照片图库要单独的权限
/// 和用途说明(没配的话系统直接把 App 杀掉),Linux 上 gal 没有实现、分享面板也不收文件。
///
/// 返回给用户看的一句话;交给分享面板、或者在对话框里点了取消时返回 null(不用再说什么)。
Future<String?> saveShareImage(Uint8List png, String name) async {
  if (szIsDesktopApp) {
    final to = await getSaveLocation(
      suggestedName: '$name.png',
      acceptedTypeGroups: const [XTypeGroup(label: 'PNG 图片', extensions: ['png'])],
    );
    if (to == null) return null;
    await File(to.path).writeAsBytes(png);
    return '已保存到 ${to.path}';
  }
  try {
    await Gal.putImageBytes(png,
        album: Platform.isAndroid ? '超级赞' : null, name: name);
    return '已保存到相册';
  } catch (_) {
    await SharePlus.instance.share(ShareParams(files: [
      XFile.fromData(png, mimeType: 'image/png', name: '$name.png'),
    ]));
    return null;
  }
}
