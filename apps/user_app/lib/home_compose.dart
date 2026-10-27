import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';

/// 首页右上角「+」菜单里的一项。
enum HomeComposeAction { scan, card, group, addContact }

/// 弹首页「+」菜单。返回选中的项;取消返回 null。
///
/// 和「消息」tab 的「+」是同一类动作(发起),但那边是聊天上下文
/// (新建频道、收藏夹、通话记录都在那儿);这里只放**从哪儿发起都成立**的
/// 四件事。收付款没上(微信支付还没联调),不放一个点了没用的入口;
/// 发视频、发帖各自的 tab 里有主入口,也不在这里重复摆一份。
///
/// [canScan] 由调用方给(只有手机 App 能扫):桌面、网页上没有相机,
/// 摆一个点进去就报错的入口不如不摆。测试里也不用去改平台开关。
Future<HomeComposeAction?> showHomeComposeSheet(BuildContext context,
        {required bool canScan}) =>
    szShowSheet<HomeComposeAction>(
      context: context,
      builder: (ctx) => SafeArea(
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          // 扫一扫:扫网页版、电脑版的登录码,别人的名片码,小程序直达链接。
          // 没登录也能扫公开内容,登录码那条路自己会要求先登录
          if (canScan)
            ListTile(
                leading: const Icon(Icons.qr_code_scanner),
                title: const Text('扫一扫'),
                onTap: () => Navigator.pop(ctx, HomeComposeAction.scan)),
          // 我的名片:二维码 + 链接。和扫一扫配成一对 ——
          // 原来它埋在「聊天设置 → 我的名片」里,当面加好友的人找不到
          ListTile(
              leading: const Icon(Icons.qr_code_2),
              title: const Text('我的名片'),
              onTap: () => Navigator.pop(ctx, HomeComposeAction.card)),
          ListTile(
              leading: const Icon(Icons.group_add_outlined),
              title: const Text('发起群聊'),
              onTap: () => Navigator.pop(ctx, HomeComposeAction.group)),
          ListTile(
              leading: const Icon(Icons.person_add_alt_1_outlined),
              title: const Text('添加联系人'),
              onTap: () => Navigator.pop(ctx, HomeComposeAction.addContact)),
        ]),
      ),
    );
