import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';

import '../../chat/chat_page.dart';
import '../../chat/ui/avatar.dart';
import '../../session.dart';
import '../api.dart';
import '../models.dart';
import '../nav.dart';
import '../widgets/cards.dart';
import '../me/favorites_page.dart' show FolderPage;
import '../me/follow_list_page.dart';
import '../widgets/feed.dart';

/// UP 主空间(#366):头像、名字、签名、关注 / 粉丝 / 获赞、投稿(最新 / 最多播放)、公开收藏夹、
/// 「发消息」进私聊、关注按钮。有拉黑关系时不能关注(can_follow=false)。
class SpacePage extends StatefulWidget {
  const SpacePage({super.key, required this.userId});

  final int userId;

  @override
  State<SpacePage> createState() => _SpacePageState();
}

class _SpacePageState extends State<SpacePage> {
  Map<String, dynamic>? _s;
  Object? _error;
  String _order = 'new';
  bool _busy = false;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final s = await videoApi.space(widget.userId);
      if (mounted) setState(() => _s = s);
    } catch (e) {
      if (mounted) setState(() => _error = e);
    }
  }

  Future<void> _follow(bool follow) async {
    if (!await ensureLoggedIn(context)) return;
    setState(() => _busy = true);
    try {
      final r = await videoApi.follow(widget.userId, follow);
      if (mounted) {
        setState(() {
          _s!['followed'] = r['followed'] == true;
          vMap(_s!['stats'])['fans'] = vInt(r['fans']);
        });
      }
    } on ApiException catch (e) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(e.message)));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    final s = _s;
    if (s == null) {
      return SzPageScaffold(
        appBar: AppBar(),
        body: Center(
          child: _error != null
              ? (VideoApi.isOff(_error!) ? const SzEmpty(text: '视频功能暂未开放') : SzError(error: _error, onRetry: _load))
              : const CircularProgressIndicator(),
        ),
      );
    }
    final user = VPerson.fromJson(s['user']);
    final stats = vMap(s['stats']);
    final isSelf = s['is_self'] == true;
    final followed = s['followed'] == true;
    final folders = [for (final f in vList(s['folders'])) FavFolder.fromJson(f)];
    return DefaultTabController(
      length: 2,
      child: SzPageScaffold(
        appBar: AppBar(title: Text(user.name)),
        body: NestedScrollView(
          headerSliverBuilder: (context, _) => [
            SliverToBoxAdapter(
              child: Padding(
                padding: const EdgeInsets.fromLTRB(kPagePad, 8, kPagePad, 8),
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Row(children: [
                    ChatAvatar(name: user.name, url: user.avatar, size: 68),
                    const SizedBox(width: 14),
                    Expanded(
                      child: Row(mainAxisAlignment: MainAxisAlignment.spaceAround, children: [
                        _Num(label: '关注', value: vInt(stats['following']), onTap: () => Navigator.of(context).push(
                            MaterialPageRoute<void>(builder: (_) => FollowListPage(userId: user.id, fans: false)))),
                        _Num(label: '粉丝', value: vInt(stats['fans']), onTap: () => Navigator.of(context).push(
                            MaterialPageRoute<void>(builder: (_) => FollowListPage(userId: user.id, fans: true)))),
                        _Num(label: '获赞', value: vInt(stats['likes'])),
                      ]),
                    ),
                  ]),
                  const SizedBox(height: 10),
                  Text(user.name, style: const TextStyle(fontSize: kFontTitle, fontWeight: FontWeight.w600)),
                  if (user.username != null)
                    Text('@${user.username}', style: TextStyle(fontSize: kFontNote, color: sz.inkMuted)),
                  if (user.bio.isNotEmpty)
                    Padding(padding: const EdgeInsets.only(top: 6), child: Text(user.bio)),
                  const SizedBox(height: 12),
                  if (!isSelf)
                    Row(children: [
                      Expanded(
                        child: s['can_follow'] == false
                            ? const OutlinedButton(onPressed: null, child: Text('不能关注'))
                            : (followed
                                ? OutlinedButton(onPressed: _busy ? null : () => _follow(false), child: const Text('已关注'))
                                : FilledButton(onPressed: _busy ? null : () => _follow(true), child: const Text('+ 关注'))),
                      ),
                      const SizedBox(width: 10),
                      Expanded(
                        child: OutlinedButton.icon(
                          icon: const Icon(Icons.chat_bubble_outline, size: 18),
                          label: const Text('发消息'),
                          onPressed: () async {
                            if (!await ensureLoggedIn(context)) return;
                            if (context.mounted) await openPrivateWith(context, user.id);
                          },
                        ),
                      ),
                    ]),
                ]),
              ),
            ),
            SliverToBoxAdapter(
              child: TabBar(tabs: [Tab(text: '投稿 ${vInt(stats['videos'])}'), Tab(text: '收藏夹 ${folders.length}')]),
            ),
          ],
          body: TabBarView(children: [
            VideoFeed(
              key: ValueKey(_order),
              load: (page, _) => videoApi.userVideos(user.id, order: _order, page: page),
              emptyText: isSelf ? '还没有投稿' : 'TA 还没有公开的视频',
              header: Padding(
                padding: const EdgeInsets.fromLTRB(10, 6, 10, 0),
                child: Row(children: [
                  ChoiceChip(label: const Text('最新发布'), selected: _order == 'new', onSelected: (_) => setState(() => _order = 'new')),
                  const SizedBox(width: 8),
                  ChoiceChip(label: const Text('最多播放'), selected: _order == 'views', onSelected: (_) => setState(() => _order = 'views')),
                ]),
              ),
            ),
            folders.isEmpty
                ? Center(child: SzEmpty(text: isSelf ? '还没有收藏夹' : 'TA 没有公开的收藏夹'))
                : ListView(children: [
                    for (final f in folders)
                      ListTile(
                        leading: SizedBox(
                          width: 80,
                          height: 50,
                          child: VideoCover(
                            card: VideoCard(vid: '', title: f.title, cover: f.cover),
                            showDuration: false,
                          ),
                        ),
                        title: Text(f.title),
                        subtitle: Text('${f.count} 个视频${f.isPublic ? '' : ' · 私密'}'),
                        onTap: () => Navigator.of(context).push(MaterialPageRoute<void>(
                            builder: (_) => FolderPage(f.id, mine: isSelf))),
                      ),
                  ]),
          ]),
        ),
      ),
    );
  }
}

class _Num extends StatelessWidget {
  const _Num({required this.label, required this.value, this.onTap});

  final String label;
  final int value;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    return InkWell(
      onTap: onTap,
      child: Padding(
        padding: const EdgeInsets.all(6),
        child: Column(children: [
          Text(vCount(value), style: const TextStyle(fontSize: kFontTitle, fontWeight: FontWeight.w600)),
          Text(label, style: TextStyle(fontSize: kFontNote, color: sz.inkMuted)),
        ]),
      ),
    );
  }
}
