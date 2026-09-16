import 'package:flutter/widgets.dart';
import 'package:url_launcher/url_launcher.dart';

import '../models.dart';

/// 网页:浏览器自己会下载、自己会问存到哪
/// 网页版:交给浏览器下载。文件落在浏览器的下载目录里,**App 碰不到**,
/// 所以回空串而不是路径 ——「下载内容」那一格照样记一行(什么文件、从哪来、什么时候),
/// 只是点开时只能重新下一次,不能直接打开本机那份。
Future<String?> fetchThen(BuildContext context, String url, MediaInfo media,
    {required bool open}) async {
  await launchUrl(Uri.parse(url), mode: LaunchMode.externalApplication);
  return '';
}

/// 网页版没有「本机那份」:文件在浏览器的下载目录里,App 碰不到,只能让用户自己去删
Future<void> deleteLocal(String path) async {}
