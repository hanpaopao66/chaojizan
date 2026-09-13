import 'dart:js_interop';
import 'dart:typed_data';

import 'package:web/web.dart' as web;

/// 网页:浏览器里没有相册,「存图」就是下载一张 PNG。
Future<String?> saveShareImage(Uint8List png, String name) async {
  final blob =
      web.Blob([png.toJS].toJS, web.BlobPropertyBag(type: 'image/png'));
  final url = web.URL.createObjectURL(blob);
  final a = web.HTMLAnchorElement()
    ..href = url
    ..download = '$name.png';
  web.document.body?.append(a);
  a.click();
  a.remove();
  // 马上撤掉的话,有的浏览器下载还没开始就拿不到这张图了
  Future<void>.delayed(
      const Duration(seconds: 2), () => web.URL.revokeObjectURL(url));
  return '已下载图片';
}
