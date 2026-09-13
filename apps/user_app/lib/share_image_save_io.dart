import 'dart:io';
import 'dart:typed_data';

import 'package:gal/gal.dart';
import 'package:share_plus/share_plus.dart';

/// 手机:分享图存进相册(安卓 10 起不用存储权限,和聊天存图同一个库)。
/// 存不进去(老系统没权限、桌面端没有相册插件)就交给系统分享面板,让人自己选存哪。
/// 返回给用户看的一句话;交给分享面板时返回 null(面板自己会说)。
Future<String?> saveShareImage(Uint8List png, String name) async {
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
