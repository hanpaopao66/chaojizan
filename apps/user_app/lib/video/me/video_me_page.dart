import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';

import '../../chat/ui/avatar.dart';
import '../../session.dart';
import '../api.dart';
import '../creator/creator_center_page.dart';
import '../models.dart';
import '../nav.dart';
import '../notify/notifications_page.dart';
import '../pages/upload_entry.dart';
import 'coins_page.dart';
import 'favorites_page.dart';
import 'follow_list_page.dart';
import 'history_page.dart';
import 'video_settings_page.dart';
import 'watch_later_page.dart';

/// 视频里的「我的」(B 站首页左上角那个头像点进来的地方):
/// 我的空间和关注 / 粉丝 / 获赞,下面是历史、稍后再看、收藏、硬币,再下面是投稿、创作中心、互动消息、设置。
class VideoMePage extends StatefulWidget {
  const VideoMePage({super.key});

  @override
  State<VideoMePage> createState() => _VideoMePageState();
}

class _VideoMePageState extends State<VideoMePage> {
  Map<String, dynamic>? _space;
  Object? _error;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    final uid = rootApi.userId;
    if (uid == null) return;
    try {
      final s = await videoApi.space(uid);
      if (mounted) setState(() => _space = s);
    } catch (e) {
      if (mounted) setState(() => _error = e);
    }
  }

  Future<void> _open(Widget page) async {
    await Navigator.of(context).push(MaterialPageRoute<void>(builder: (_) => page));
    _load(); // 回来时刷新一下关注数、获赞
  }

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    final s = _space;
    final user = s == null ? null : VPerson.fromJson(s['user']);
    final stats = vMap(s?['stats']);
    final uid = rootApi.userId ?? 0;
    return SzPageScaffold(
      appBar: AppBar(title: const Text('我的视频')),
      body: ListView(padding: const EdgeInsets.fromLTRB(kPagePad, 8, kPagePad, 24), children: [
        if (_error != null && s == null)
          VideoApi.isOff(_error!)
              ? const SzEmpty(text: '视频功能暂未开放')
              : SzError(error: _error, onRetry: _load)
        else
          InkWell(
            borderRadius: BorderRadius.circular(kRadiusMd),
            onTap: () => openUpSpace(context, uid),
            child: Padding(
              padding: const EdgeInsets.symmetric(vertical: 8),
              child: Row(children: [
                ChatAvatar(name: user?.name ?? rootApi.userName ?? '我', url: user?.avatar ?? '', size: 56),
                const SizedBox(width: 14),
                Expanded(
                  child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    Text(user?.name ?? rootApi.userName ?? '',
                        style: const TextStyle(fontSize: kFontTitle, fontWeight: FontWeight.w600)),
                    const SizedBox(height: 2),
                    Text('我的空间', style: TextStyle(fontSize: kFontNote, color: sz.inkMuted)),
                  ]),
                ),
                Icon(Icons.chevron_right, color: sz.inkFaint),
              ]),
            ),
          ),
        const SizedBox(height: 8),
        Row(children: [
          _Num(label: '关注', value: vInt(stats['following']),
              onTap: () => _open(FollowListPage(userId: uid, fans: false))),
          _Num(label: '粉丝', value: vInt(stats['fans']),
              onTap: () => _open(FollowListPage(userId: uid, fans: true))),
          _Num(label: '获赞', value: vInt(stats['likes'])),
          _Num(label: '投稿', value: vInt(stats['videos']), onTap: () => openUpSpace(context, uid)),
        ]),
        const SizedBox(height: 12),
        Card(
          child: SzIconGrid(columns: 4, items: [
            SzIconGridItem(icon: Icons.history, label: '历史记录', onTap: () => _open(const VideoHistoryPage())),
            SzIconGridItem(icon: Icons.watch_later_outlined, label: '稍后再看', onTap: () => _open(const WatchLaterPage())),
            SzIconGridItem(icon: Icons.star_outline, label: '我的收藏', onTap: () => _open(const FavoritesPage())),
            SzIconGridItem(icon: Icons.monetization_on_outlined, label: '我的硬币', onTap: () => _open(const CoinsPage())),
          ]),
        ),
        const SizedBox(height: 12),
        SzEntryGroup(children: [
          SzEntryTile(
            icon: Icons.add_circle_outline,
            title: '投稿',
            hint: '横屏竖屏都行,审核通过后发布',
            onTap: () => openUpload(context),
          ),
          SzEntryTile(
            icon: Icons.video_camera_back_outlined,
            title: '创作中心',
            hint: '稿件状态、数据、审核结果和申诉',
            onTap: () => _open(const CreatorCenterPage()),
          ),
          ValueListenableBuilder<int>(
            valueListenable: videoNotifyUnread,
            builder: (context, n, _) => SzEntryTile(
              icon: Icons.favorite_border,
              title: '互动消息',
              value: n > 0 ? '$n 条未读' : null,
              valueTone: n > 0 ? sz.hold : null,
              hint: '回复我的、@我的、收到的赞',
              onTap: () => _open(const VideoNotificationsPage()),
            ),
          ),
          SzEntryTile(
            icon: Icons.tune,
            title: '视频设置',
            hint: '个性化推荐、观看历史记录',
            onTap: () => _open(const VideoSettingsPage()),
          ),
        ]),
      ]),
    );
  }
}

/// 打开「我的视频」:要登录。
Future<void> openVideoMe(BuildContext context) async {
  if (!await ensureLoggedIn(context)) return;
  if (!context.mounted) return;
  await Navigator.of(context).push(MaterialPageRoute<void>(builder: (_) => const VideoMePage()));
}

class _Num extends StatelessWidget {
  const _Num({required this.label, required this.value, this.onTap});

  final String label;
  final int value;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    return Expanded(
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(kRadiusSm),
        child: Padding(
          padding: const EdgeInsets.symmetric(vertical: 6),
          child: Column(children: [
            Text(vCount(value), style: const TextStyle(fontSize: kFontTitle, fontWeight: FontWeight.w600)),
            Text(label, style: TextStyle(fontSize: kFontNote, color: sz.inkMuted)),
          ]),
        ),
      ),
    );
  }
}
