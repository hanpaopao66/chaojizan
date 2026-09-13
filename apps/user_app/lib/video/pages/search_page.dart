import 'dart:async';

import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:superz_shared/superz_shared.dart';

import '../../chat/ui/avatar.dart';
import '../models.dart';
import '../nav.dart';
import '../widgets/cards.dart';
import '../widgets/follow_button.dart';

/// 视频搜索(#365):搜索历史(本机)、热搜(24 小时 ≥5 个不同的人搜过才上榜)、
/// 结果分「视频 / 用户」,视频可按综合 / 最多播放 / 最新 / 最多弹幕排,按时长、分区筛。
class VideoSearchPage extends StatefulWidget {
  const VideoSearchPage({super.key, this.initial});

  final String? initial;

  @override
  State<VideoSearchPage> createState() => _VideoSearchPageState();
}

class _VideoSearchPageState extends State<VideoSearchPage> {
  static const _historyKey = 'video_search_history';
  final _q = TextEditingController();
  List<String> _history = [];
  List<Map<String, dynamic>> _hot = [];
  String _searched = '';

  @override
  void initState() {
    super.initState();
    SharedPreferences.getInstance().then((sp) {
      if (mounted) setState(() => _history = sp.getStringList(_historyKey) ?? []);
    });
    videoApi.hotSearch().then((h) {
      if (mounted) setState(() => _hot = h);
    }).catchError((_) {});
    if (widget.initial != null && widget.initial!.isNotEmpty) {
      _q.text = widget.initial!;
      _search(widget.initial!);
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
    final sp = await SharedPreferences.getInstance();
    await sp.setStringList(_historyKey, _history);
  }

  Future<void> _clearHistory() async {
    setState(() => _history = []);
    final sp = await SharedPreferences.getInstance();
    await sp.remove(_historyKey);
  }

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    return SzPageScaffold(
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
          decoration: const InputDecoration(hintText: '搜索视频、UP 主', border: InputBorder.none),
        ),
        actions: [TextButton(onPressed: () => _search(_q.text), child: const Text('搜索'))],
      ),
      body: _searched.isNotEmpty
          ? _Results(key: ValueKey(_searched), q: _searched)
          : ListView(padding: const EdgeInsets.all(kPagePad), children: [
              if (_history.isNotEmpty) ...[
                Row(children: [
                  const Text('搜索历史', style: TextStyle(fontWeight: FontWeight.w600)),
                  const Spacer(),
                  TextButton(onPressed: _clearHistory, child: const Text('清空')),
                ]),
                Wrap(spacing: 8, runSpacing: 8, children: [
                  for (final h in _history) ActionChip(label: Text(h), onPressed: () => _search(h)),
                ]),
                const SizedBox(height: 18),
              ],
              const Text('热搜', style: TextStyle(fontWeight: FontWeight.w600)),
              const SizedBox(height: 4),
              Text('24 小时内至少 5 个不同的人搜过才上榜,刷不上去', style: TextStyle(fontSize: kFontNote, color: sz.inkMuted)),
              const SizedBox(height: 8),
              if (_hot.isEmpty)
                Padding(padding: const EdgeInsets.all(12), child: Text('暂时还没有热搜', style: TextStyle(color: sz.inkFaint))),
              for (var i = 0; i < _hot.length; i++)
                ListTile(
                  dense: true,
                  contentPadding: EdgeInsets.zero,
                  leading: SizedBox(
                    width: 22,
                    child: Text('${i + 1}',
                        style: TextStyle(fontWeight: FontWeight.w700, color: i < 3 ? sz.clay : sz.inkMuted)),
                  ),
                  title: Text('${_hot[i]['term']}'),
                  trailing: Text('${_hot[i]['users']} 人在搜', style: TextStyle(fontSize: kFontNote, color: sz.inkFaint)),
                  onTap: () => _search('${_hot[i]['term']}'),
                ),
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
  late final TabController _tc = TabController(length: 2, vsync: this);
  String _order = 'default';
  int _duration = 0;
  String _zone = '';
  List<Map<String, dynamic>> _zones = [];

  final List<VideoCard> _videos = [];
  int _page = 0;
  bool _more = true;
  bool _loading = false;
  Object? _error;
  final ScrollController _scroll = ScrollController();

  static const _orders = {'default': '综合', 'views': '最多播放', 'new': '最新', 'danmaku': '最多弹幕'};
  static const _durations = {0: '全部时长', 1: '10 分钟以下', 2: '10–30 分钟', 3: '30–60 分钟', 4: '60 分钟以上'};

  @override
  void initState() {
    super.initState();
    _scroll.addListener(() {
      if (_scroll.position.pixels > _scroll.position.maxScrollExtent - 400) _loadMore();
    });
    videoApi.zones().then((z) {
      if (mounted) setState(() => _zones = z);
    }).catchError((_) {});
    _reload();
  }

  @override
  void dispose() {
    _tc.dispose();
    _scroll.dispose();
    super.dispose();
  }

  Future<void> _reload() async {
    _videos.clear();
    _page = 0;
    _more = true;
    await _loadMore();
  }

  Future<void> _loadMore() async {
    if (_loading || !_more) return;
    setState(() => _loading = true);
    try {
      final r = await videoApi.search(widget.q, order: _order, duration: _duration, zone: _zone, page: _page);
      if (!mounted) return;
      setState(() {
        _videos.addAll(r.items);
        _more = r.hasMore;
        _page++;
        _error = null;
      });
    } catch (e) {
      if (mounted) setState(() => _error = e);
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Widget _filterChip<T>(String label, T value, Map<T, String> options, void Function(T) onPick) {
    return PopupMenuButton<T>(
      onSelected: onPick,
      itemBuilder: (_) => [for (final e in options.entries) PopupMenuItem(value: e.key, child: Text(e.value))],
      child: Chip(label: Text(options[value] ?? label), avatar: const Icon(Icons.arrow_drop_down, size: 18)),
    );
  }

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    final zoneOptions = {'': '全部分区', for (final z in _zones) '${z['zone']}': '${z['name']}'};
    return Column(children: [
      TabBar(controller: _tc, tabs: const [Tab(text: '视频'), Tab(text: '用户')]),
      Expanded(
        child: TabBarView(controller: _tc, children: [
          Column(children: [
            SizedBox(
              height: 48,
              child: ListView(scrollDirection: Axis.horizontal, padding: const EdgeInsets.symmetric(horizontal: 12), children: [
                _filterChip<String>('排序', _order, _orders, (v) {
                  setState(() => _order = v);
                  _reload();
                }),
                const SizedBox(width: 8),
                _filterChip<int>('时长', _duration, _durations, (v) {
                  setState(() => _duration = v);
                  _reload();
                }),
                const SizedBox(width: 8),
                _filterChip<String>('分区', _zone, zoneOptions, (v) {
                  setState(() => _zone = v);
                  _reload();
                }),
              ]),
            ),
            Expanded(
              child: _videos.isEmpty
                  ? Center(
                      child: _loading
                          ? const CircularProgressIndicator()
                          : (_error != null
                              ? SzError(error: _error, onRetry: _reload)
                              : SzEmpty(text: '没有找到「${widget.q}」相关的视频')),
                    )
                  : ListView.builder(
                      controller: _scroll,
                      itemCount: _videos.length + 1,
                      itemBuilder: (context, i) {
                        if (i == _videos.length) {
                          return Padding(
                            padding: const EdgeInsets.all(16),
                            child: Center(
                              child: _loading
                                  ? const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2))
                                  : Text(_more ? '' : '没有更多了', style: TextStyle(color: sz.inkFaint, fontSize: kFontNote)),
                            ),
                          );
                        }
                        final c = _videos[i];
                        return VideoRowTile(
                          card: c,
                          subtitle: '${vCount(c.views)} 播放 · ${vCount(c.danmakuCount)} 弹幕 · ${vAgo(c.publishedAt)}',
                        );
                      },
                    ),
            ),
          ]),
          _UserResults(q: widget.q),
        ]),
      ),
    ]);
  }
}

class _UserResults extends StatefulWidget {
  const _UserResults({required this.q});

  final String q;

  @override
  State<_UserResults> createState() => _UserResultsState();
}

class _UserResultsState extends State<_UserResults> with AutomaticKeepAliveClientMixin {
  List<VPerson>? _items;
  Object? _error;

  @override
  bool get wantKeepAlive => true;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final r = await videoApi.searchUsers(widget.q);
      if (mounted) setState(() => _items = r.items);
    } catch (e) {
      if (mounted) setState(() => _error = e);
    }
  }

  @override
  Widget build(BuildContext context) {
    super.build(context);
    final sz = Theme.of(context).sz;
    final items = _items;
    if (items == null) {
      return Center(child: _error != null ? SzError(error: _error, onRetry: _load) : const CircularProgressIndicator());
    }
    if (items.isEmpty) return Center(child: SzEmpty(text: '没有找到叫「${widget.q}」的人'));
    return ListView(children: [
      for (var i = 0; i < items.length; i++)
        ListTile(
          leading: ChatAvatar(name: items[i].name, url: items[i].avatar, size: 44),
          title: Text(items[i].name),
          subtitle: Text(
              '${items[i].username != null ? '@${items[i].username} · ' : ''}${vCount(items[i].fans)} 粉丝 · ${items[i].videos} 个视频',
              style: TextStyle(fontSize: kFontNote, color: sz.inkMuted)),
          trailing: FollowButton(
            person: items[i],
            onChanged: (p) => setState(() => items[i] = p),
          ),
          onTap: () => openUpSpace(context, items[i].id),
        ),
    ]);
  }
}
