import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';

/// 会话 / 人的头像:有图画图,没图画首字色块(和全站 [SzImage] 同一套占位),
/// 可选右下角的在线绿点。收藏夹画书签图标。
class ChatAvatar extends StatelessWidget {
  const ChatAvatar({
    super.key,
    required this.name,
    this.url = '',
    this.size = 44,
    this.online = false,
    this.saved = false,
    this.icon,
  });

  final String name;

  /// 服务端给的相对地址或完整地址;空串画首字
  final String url;
  final double size;
  final bool online;
  final bool saved;

  /// 固定条目用的图标(通知、订单消息……)
  final IconData? icon;

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    Widget face;
    if (saved || icon != null) {
      face = Container(
        width: size,
        height: size,
        decoration: BoxDecoration(color: sz.clay, shape: BoxShape.circle),
        child: Icon(saved ? Icons.bookmark : icon, color: Colors.white, size: size * .5),
      );
    } else {
      final resolved = url.isEmpty || url.startsWith('http') ? url : rootResolve(url);
      face = SzImage(url: resolved, name: name, size: size, circle: true);
    }
    if (!online) return face;
    final dot = size * .26;
    return SizedBox(
      width: size,
      height: size,
      child: Stack(children: [
        face,
        Positioned(
          right: 0,
          bottom: 0,
          child: Container(
            width: dot,
            height: dot,
            decoration: BoxDecoration(
              color: sz.earn,
              shape: BoxShape.circle,
              border: Border.all(color: Theme.of(context).scaffoldBackgroundColor, width: 2),
            ),
          ),
        ),
      ]),
    );
  }
}

/// 把服务端的相对地址拼成完整地址。由 [ChatStore] 在启动时注入(它拿着 ApiClient)。
String Function(String) rootResolve = (s) => s;
