/// 网络图片的统一入口:带磁盘缓存。
///
/// Flutter 自带的 `Image.network` 只有内存缓存,杀进程就没了。外卖首页整屏
/// 是图,用户一天开三次就重下三次——用户流量、加载速度、平台带宽三头都亏
/// (带宽正是平台留存那 5% 里的一项开支)。
///
/// 这里只返回 [ImageProvider],不返回 Widget:这样 cached_network_image
/// 这个依赖只落在 shared,三端 App 不用各自加一遍依赖,调用点也只是把
/// `Image.network(u, ...)` 换成 `Image(image: szNetImage(u), ...)`,
/// 其余参数一个不用改。
///
/// 缓存只落本地磁盘,不上报任何数据。
library;

import 'package:cached_network_image/cached_network_image.dart';
import 'package:flutter/widgets.dart';

ImageProvider szNetImage(String url) => CachedNetworkImageProvider(url);
