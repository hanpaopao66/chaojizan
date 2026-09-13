import 'package:flutter/widgets.dart';
import 'package:url_launcher/url_launcher.dart';

import '../models.dart';

/// 网页:浏览器自己会下载、自己会问存到哪
Future<void> fetchThen(BuildContext context, String url, MediaInfo media, {required bool open}) async {
  await launchUrl(Uri.parse(url), mode: LaunchMode.externalApplication);
}
