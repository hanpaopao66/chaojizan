// 音乐搜索(§8.2 GET /search):单曲 / 歌手 / 专辑 / 歌单四个页签,搜索历史记在本机。
import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:superz_shared/superz_shared.dart';

import '../../video/me/common.dart';
import '../../video/models.dart';
import '../models.dart';
import '../nav.dart';
import '../widgets/common.dart';

class MusicSearchPage extends StatefulWidget {
  const MusicSearchPage({super.key, this.initial});

  final String? initial;

  @override
  State<MusicSearchPage> createState() => _MusicSearchPageState();
}

class _MusicSearchPageState extends State<MusicSearchPage> {
  static const _historyKey = 'music_search_history';
  final _q = TextEditingController();
  List<String> _history = [];
  String _searched = '';

  @override
  void initState() {
    super.initState();
    SharedPreferences.getInstance().then((sp) {
      if (mounted) setState(() => _history = sp.getStringList(_historyKey) ?? []);
    }).catchError((Object _) {});
    final initial = widget.initial;
    if (initial != null && initial.trim().isNotEmpty) {
      _q.text = initial.trim();
      _search(initial);
    }
  }

  @override
  void dispose() {
    _q.dispose();
    super.dispose();
  }

  Future<void> _search(String raw) async {
    final q = raw.trim();
    if (q.isEmpty) return;
    _q.text = q;
    setState(() => _searched = q);
    _history = [q, ..._history.where((x) => x != q)].take(20).toList();
    try {
      final sp = await SharedPreferences.getInstance();
      await sp.setStringList(_historyKey, _history);
    } catch (_) {}
  }

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    return SzPageScaffold(
      contentMaxWidth: kFeedMaxWidth,
      appBar: AppBar(
        titleSpacing: 0,
        title: TextField(
          controller: _q,
          autofocus: widget.initial == null,
          textInputAction: TextInputAction.search,
          onSubmitted: _search,
          onChanged: (v) {
            if (v.isEmpty && _searched.isNotEmpty) setState(() => _searched = '');
          },
          decoration: const InputDecoration(hintText: '搜歌曲、歌手、专辑、歌单', border: InputBorder.none),
        ),
        actions: [TextButton(onPressed: () => _search(_q.text), child: const Text('搜索'))],
      ),
      body: _searched.isNotEmpty
          ? _Results(key: ValueKey(_searched), q: _searched)
          : ListView(padding: const EdgeInsets.all(kPagePad), children: [
              if (_history.isEmpty)
                Padding(
                  padding: const EdgeInsets.only(top: 24),
                  child: Text('搜歌名、歌手名、专辑名或者歌单名', style: TextStyle(color: sz.inkFaint)),
                )
              else ...[
                Row(children: [
                  const Text('搜索历史', style: TextStyle(fontWeight: FontWeight.w600)),
                  const Spacer(),
                  TextButton(
                    onPressed: () async {
                      setState(() => _history = []);
                      try {
                        final sp = await SharedPreferences.getInstance();
                        await sp.remove(_historyKey);
                      } catch (_) {}
                    },
                    child: const Text('清空'),
                  ),
                ]),
                Wrap(spacing: 8, runSpacing: 8, children: [
                  for (final h in _history) ActionChip(label: Text(h), onPressed: () => _search(h)),
                ]),
              ],
            ]),
    );
  }
}

class _Results extends StatefulWidget {
  const _Results({super.key, required this.q});

  final String q;

  @override
  State<_Results> createState() => _ResultsState();
}

class _ResultsState extends State<_Results> with SingleTickerProviderStateMixin {
  static const _types = [
    (type: 'track', label: '单曲'),
    (type: 'artist', label: '歌手'),
    (type: 'release', label: '专辑'),
    (type: 'playlist', label: '歌单'),
  ];

  late final TabController _tc = TabController(length: _types.length, vsync: this);

  @override
  void dispose() {
    _tc.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Column(children: [
      TabBar(controller: _tc, tabs: [for (final t in _types) Tab(text: t.label)]),
      Expanded(
        child: TabBarView(
          controller: _tc,
          children: [for (final t in _types) _TypeResults(q: widget.q, type: t.type, label: t.label)],
        ),
      ),
    ]);
  }
}

class _TypeResults extends StatefulWidget {
  const _TypeResults({required this.q, required this.type, required this.label});

  final String q;
  final String type;
  final String label;

  @override
  State<_TypeResults> createState() => _TypeResultsState();
}

class _TypeResultsState extends State<_TypeResults> with AutomaticKeepAliveClientMixin {
  late final CursorPager<dynamic> _pager = CursorPager<dynamic>((cursor) async {
    final page = int.tryParse(cursor ?? '0') ?? 0;
    final r = await musicApi.search(widget.q, type: widget.type, page: page);
    return (items: r.items, next: r.hasMore ? '${page + 1}' : null, extra: r.extra);
  });

  @override
  bool get wantKeepAlive => true;

  @override
  void initState() {
    super.initState();
    _pager.refresh();
  }

  @override
  void dispose() {
    _pager.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    super.build(context);
    final sz = Theme.of(context).sz;
    return PagedListView<dynamic>(
      pager: _pager,
      divider: false,
      emptyText: '没有找到和「${widget.q}」有关的${widget.label}',
      itemBuilder: (context, raw, i) {
        switch (widget.type) {
          case 'artist':
            final a = MArtist.fromJson(raw);
            return MArtistTile(
              aid: a.aid,
              name: a.name,
              avatar: a.avatar,
              subtitle: '${vCount(a.fans)} 粉丝 · ${a.trackCount} 首歌',
            );
          case 'release':
            final r = MRelease.fromJson(raw);
            return ListTile(
              leading: MCover(url: r.cover, name: r.title, size: 48),
              title: Text(r.title, maxLines: 1, overflow: TextOverflow.ellipsis),
              subtitle: Text(
                  [mReleaseKindName(r.kind), if (r.artist != null) r.artist!.name, if (r.releaseDate.isNotEmpty) r.releaseDate]
                      .join(' · '),
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: TextStyle(fontSize: kFontNote, color: sz.inkMuted)),
              onTap: () => openRelease(context, r.rid),
            );
          case 'playlist':
            final p = MPlaylist.fromJson(raw);
            return ListTile(
              leading: MCover(url: p.cover, name: p.title, size: 48),
              title: Text(p.title, maxLines: 1, overflow: TextOverflow.ellipsis),
              subtitle: Text('${p.trackCount} 首 · ${p.owner?.name ?? ''}',
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: TextStyle(fontSize: kFontNote, color: sz.inkMuted)),
              onTap: () => openPlaylist(context, p.pid),
            );
          default:
            final tracks = [for (final x in _pager.items) MTrack.fromJson(x)];
            return MTrackTile(track: MTrack.fromJson(raw), queue: tracks, contextKey: 'search');
        }
      },
    );
  }
}
