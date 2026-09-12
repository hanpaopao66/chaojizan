import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';

import '../messages_page.dart';
import '../session.dart';
import 'order_chats_page.dart';

/// 底部「消息」tab 的角标:有未读的会话数。**免打扰的会话不计** ——
/// 静音的群不该在底栏上一直喊你(Telegram 也是这么算的)。
/// 会话列表每次拉到数据、每收到一个事件都会更新它
final ValueNotifier<int> chatUnreadBadge = ValueNotifier<int>(0);

/// 「消息」tab。
///
/// 顶部固定三行(DEV-PROMPTS-40 D24):「通知」是原来右上角铃铛里的消息中心,
/// 「订单消息」是进行中订单里和商家、骑手的对话,「互动消息」是视频的回复 / @ / 赞。
/// 下面是聊天会话。
class ChatTab extends StatefulWidget {
  const ChatTab({super.key, required this.api});

  final ApiClient api;

  @override
  State<ChatTab> createState() => _ChatTabState();
}

class _ChatTabState extends State<ChatTab> {
  /// 有新公告(和原来铃铛红点同一个判据:最新公告 id 比本地看过的新)
  bool _noticeUnread = false;

  @override
  void initState() {
    super.initState();
    authTick.addListener(_onAuth);
    _refreshNotice();
  }

  @override
  void dispose() {
    authTick.removeListener(_onAuth);
    super.dispose();
  }

  void _onAuth() {
    if (mounted) setState(() {});
  }

  Future<void> _refreshNotice() async {
    final v = await MessageCenterPage.hasUnread(widget.api);
    if (mounted && v != _noticeUnread) setState(() => _noticeUnread = v);
  }

  Future<void> _openNotice() async {
    setState(() => _noticeUnread = false); // 打开即已读(和原铃铛一样)
    await Navigator.of(context).push(MaterialPageRoute<void>(
        builder: (_) => MessageCenterPage(api: widget.api)));
  }

  Future<void> _openOrderChats() async {
    if (!await ensureLoggedIn(context)) return;
    if (!mounted) return;
    await Navigator.of(context).push(MaterialPageRoute<void>(
        builder: (_) => OrderChatsPage(api: widget.api)));
  }

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    return Column(children: [
      AppBar(title: const Text('消息')),
      Expanded(
        child: RefreshIndicator(
          onRefresh: _refreshNotice,
          child: ListView(children: [
            _PinnedRow(
              icon: Icons.campaign_outlined,
              title: '通知',
              subtitle: '平台公告和订单状态',
              dot: _noticeUnread,
              onTap: _openNotice,
            ),
            _PinnedRow(
              icon: Icons.receipt_long_outlined,
              title: '订单消息',
              subtitle: '和商家、骑手的对话',
              onTap: _openOrderChats,
            ),
            Divider(height: 1, color: sz.line),
            if (!widget.api.isLoggedIn)
              Padding(
                padding: const EdgeInsets.only(top: 48),
                child: SzEmpty(
                  text: '登录后和朋友聊天、建群、订阅频道',
                  actionLabel: '登录 / 注册',
                  onAction: () => ensureLoggedIn(context),
                ),
              ),
          ]),
        ),
      ),
    ]);
  }
}

/// 列表顶部固定的一行:圆形图标 + 标题 + 一句说明 + 红点。
class _PinnedRow extends StatelessWidget {
  const _PinnedRow({
    required this.icon,
    required this.title,
    required this.subtitle,
    required this.onTap,
    this.dot = false,
  });

  final IconData icon;
  final String title;
  final String subtitle;
  final VoidCallback onTap;
  final bool dot;

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    return ListTile(
      leading: Badge(
        isLabelVisible: dot,
        smallSize: 9,
        child: CircleAvatar(
          backgroundColor: sz.claySoft,
          child: Icon(icon, color: sz.clay),
        ),
      ),
      title: Text(title, style: const TextStyle(fontWeight: FontWeight.w600)),
      subtitle: Text(subtitle,
          maxLines: 1,
          overflow: TextOverflow.ellipsis,
          style: TextStyle(fontSize: kFontNote, color: sz.inkMuted)),
      trailing: Icon(Icons.chevron_right, color: sz.inkFaint),
      onTap: onTap,
    );
  }
}
