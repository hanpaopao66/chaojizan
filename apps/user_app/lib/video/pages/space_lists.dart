import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';

import '../../chat/ui/avatar.dart';
import '../models.dart';
import '../nav.dart';
import '../widgets/cards.dart';
import '../widgets/follow_button.dart';

/// 某人的粉丝 / 关注列表(空间里点「粉丝」「关注」)。
class PeopleListPage extends StatefulWidget {
  const PeopleListPage({super.key, required this.userId, required this.fans});

  final int userId;
  final bool fans;

  @override
  State<PeopleListPage> createState() => _PeopleListPageState();
}

class _PeopleListPageState extends State<PeopleListPage> {
  final List<VPerson> _items = [];
  String? _cursor;
  bool _more = true;
  bool _loading = false;
  Object? _error;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    if (_loading || !_more) return;
    setState(() => _loading = true);
    try {
      final r = widget.fans
          ? await videoApi.fans(widget.userId, cursor: _cursor)
          : await videoApi.followingOf(widget.userId, cursor: _cursor);
      if (!mounted) return;
      setState(() {
        _items.addAll(r.items);
        _cursor = r.nextCursor;
        _more = r.nextCursor != null;
      });
    } catch (e) {
      if (mounted) setState(() => _error = e);
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    return SzPageScaffold(
      appBar: AppBar(title: Text(widget.fans ? '粉丝' : '关注')),
      body: _items.isEmpty
          ? Center(
              child: _loading
                  ? const CircularProgressIndicator()
                  : (_error != null ? SzError(error: _error, onRetry: _load) : SzEmpty(text: widget.fans ? '还没有粉丝' : '还没有关注任何人')),
            )
          : NotificationListener<ScrollNotification>(
              onNotification: (n) {
                if (n.metrics.pixels > n.metrics.maxScrollExtent - 200) _load();
                return false;
              },
              child: ListView.builder(
                itemCount: _items.length,
                itemBuilder: (context, i) {
                  final p = _items[i];
                  return ListTile(
                    leading: ChatAvatar(name: p.name, url: p.avatar, size: 44),
                    title: Text(p.name),
                    subtitle: p.bio.isEmpty ? null : Text(p.bio, maxLines: 1, overflow: TextOverflow.ellipsis,
                        style: TextStyle(fontSize: kFontNote, color: sz.inkMuted)),
                    trailing: FollowButton(person: p, dense: true, onChanged: (n) => setState(() => _items[i] = n)),
                    onTap: () => openUpSpace(context, p.id),
                  );
                },
              ),
            ),
    );
  }
}

/// 别人的公开收藏夹里的视频(空间里点收藏夹)。
class PublicFolderPage extends StatefulWidget {
  const PublicFolderPage({super.key, required this.folder});

  final FavFolder folder;

  @override
  State<PublicFolderPage> createState() => _PublicFolderPageState();
}

class _PublicFolderPageState extends State<PublicFolderPage> {
  final List<VideoCard> _items = [];
  String? _cursor;
  bool _more = true;
  bool _loading = false;
  Object? _error;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    if (_loading || !_more) return;
    setState(() => _loading = true);
    try {
      final r = await videoApi.publicFolder(widget.folder.id, cursor: _cursor);
      if (!mounted) return;
      setState(() {
        _items.addAll([for (final x in vList(r['items'])) VideoCard.fromJson(vMap(x)['video'])]);
        _cursor = r['next_cursor'] as String?;
        _more = _cursor != null;
      });
    } catch (e) {
      if (mounted) setState(() => _error = e);
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return SzPageScaffold(
      appBar: AppBar(title: Text(widget.folder.title)),
      body: _items.isEmpty
          ? Center(
              child: _loading
                  ? const CircularProgressIndicator()
                  : (_error != null ? SzError(error: _error, onRetry: _load) : const SzEmpty(text: '收藏夹是空的')),
            )
          : NotificationListener<ScrollNotification>(
              onNotification: (n) {
                if (n.metrics.pixels > n.metrics.maxScrollExtent - 200) _load();
                return false;
              },
              child: ListView(children: [for (final c in _items) VideoRowTile(card: c)]),
            ),
    );
  }
}
