import 'package:flutter/material.dart';

import '../session.dart';
import 'api.dart';
import 'pages/detail_page.dart';
import 'pages/space_page.dart';

/// 视频模块的入口:接口单例、地址补全、打开详情页 / UP 主空间。
/// 视频接口没登录也能调(浏览类),所以绑的是全局的 rootApi(登录后同一个对象带上 token)。
VideoApi get videoApi => _api ??= VideoApi(rootApi);
VideoApi? _api;

/// `/img/…`、`/video/v1/vod/…` 这类相对地址补成完整的
String videoResolve(String path) => rootApi.resolveUrl(path);

/// 打开视频详情。[commentId] 给了就打开评论页签并定位到那条(互动消息跳过来);
/// 那条是楼里的回复时要同时给 [rootCommentId](楼主那条),好直接打开那一楼。
Future<void> openVideo(BuildContext context, String vid, {int? commentId, int? rootCommentId, int? partIdx}) =>
    Navigator.of(context).push(MaterialPageRoute<void>(
      settings: RouteSettings(name: '/v/$vid'),
      builder: (_) => VideoDetailPage(vid: vid, commentId: commentId, rootCommentId: rootCommentId, partIdx: partIdx),
    ));

/// 打开 UP 主空间。
Future<void> openUpSpace(BuildContext context, int userId) =>
    Navigator.of(context).push(MaterialPageRoute<void>(builder: (_) => SpacePage(userId: userId)));
