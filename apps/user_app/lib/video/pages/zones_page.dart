import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';

import '../models.dart';
import '../nav.dart';
import '../widgets/cards.dart';
import '../widgets/feed.dart';

/// 分区列表 + 排行榜入口(#364)。
class ZonesPage extends StatefulWidget {
  const ZonesPage({super.key});

  @override
  State<ZonesPage> createState() => _ZonesPageState();
}

class _ZonesPageState extends State<ZonesPage> {
  List<Map<String, dynamic>>? _zones;
  Object? _error;

  static const _icons = {
    'life': Icons.home_outlined,
    'food': Icons.ramen_dining_outlined,
    'shop_visit': Icons.storefront_outlined,
    'game': Icons.sports_esports_outlined,
    'knowledge': Icons.lightbulb_outline,
    'tech': Icons.memory_outlined,
    'music': Icons.music_note_outlined,
    'dance': Icons.nightlife_outlined,
    'film': Icons.movie_outlined,
    'animal': Icons.pets_outlined,
    'sports': Icons.sports_basketball_outlined,
    'car': Icons.directions_car_outlined,
    'fashion': Icons.checkroom_outlined,
    'funny': Icons.sentiment_very_satisfied_outlined,
    'travel': Icons.flight_takeoff_outlined,
  };

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final z = await videoApi.zones();
      if (mounted) setState(() => _zones = z);
    } catch (e) {
      if (mounted) setState(() => _error = e);
    }
  }

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    final zones = _zones;
    return SzPageScaffold(
      appBar: AppBar(title: const Text('分区')),
      body: zones == null
          ? (_error != null ? SzError(error: _error, onRetry: _load) : const Center(child: CircularProgressIndicator()))
          : ListView(padding: const EdgeInsets.all(kPagePad), children: [
              ListTile(
                contentPadding: EdgeInsets.zero,
                leading: CircleAvatar(backgroundColor: sz.claySoft, child: Icon(Icons.leaderboard_outlined, color: sz.clay)),
                title: const Text('排行榜', style: TextStyle(fontWeight: FontWeight.w600)),
                subtitle: const Text('按公开的互动分排,1 / 3 / 7 天'),
                trailing: const Icon(Icons.chevron_right),
                onTap: () => Navigator.of(context).push(MaterialPageRoute<void>(builder: (_) => const RankPage())),
              ),
              const SizedBox(height: 8),
              GridView.count(
                crossAxisCount: 4,
                shrinkWrap: true,
                physics: const NeverScrollableScrollPhysics(),
                mainAxisSpacing: 8,
                crossAxisSpacing: 8,
                children: [
                  for (final z in zones)
                    InkWell(
                      borderRadius: BorderRadius.circular(kRadiusMd),
                      onTap: () => Navigator.of(context).push(MaterialPageRoute<void>(
                          builder: (_) => ZonePage(zone: '${z['zone']}', name: '${z['name']}'))),
                      child: Column(mainAxisAlignment: MainAxisAlignment.center, children: [
                        Icon(_icons[z['zone']] ?? Icons.category_outlined, color: sz.clay),
                        const SizedBox(height: 4),
                        Text('${z['name']}', style: const TextStyle(fontSize: kFontBody)),
                        Text('${z['count'] ?? 0} 个', style: TextStyle(fontSize: kFontMicro, color: sz.inkFaint)),
                      ]),
                    ),
                ],
              ),
            ]),
    );
  }
}

/// 一个分区:热门 / 最新两个页签。
class ZonePage extends StatelessWidget {
  const ZonePage({super.key, required this.zone, required this.name});

  final String zone;
  final String name;

  @override
  Widget build(BuildContext context) {
    return DefaultTabController(
      length: 2,
      child: SzPageScaffold(
        appBar: AppBar(
          title: Text(name),
          actions: [
            IconButton(
              tooltip: '$name排行榜',
              icon: const Icon(Icons.leaderboard_outlined),
              onPressed: () => Navigator.of(context)
                  .push(MaterialPageRoute<void>(builder: (_) => RankPage(zone: zone, zoneName: name))),
            ),
          ],
          bottom: const TabBar(tabs: [Tab(text: '热门'), Tab(text: '最新')]),
        ),
        body: TabBarView(children: [
          VideoFeed(load: (page, _) => videoApi.zone(zone, order: 'hot', page: page), emptyText: '这个分区还没有视频'),
          VideoFeed(load: (page, _) => videoApi.zone(zone, order: 'new', page: page), emptyText: '这个分区还没有视频'),
        ]),
      ),
    );
  }
}

/// 排行榜(#364):全站 / 某分区,1 / 3 / 7 天,按「互动分」。
class RankPage extends StatefulWidget {
  const RankPage({super.key, this.zone, this.zoneName});

  final String? zone;
  final String? zoneName;

  @override
  State<RankPage> createState() => _RankPageState();
}

class _RankPageState extends State<RankPage> {
  int _days = 1;
  List<VideoCard>? _items;
  Object? _error;
  String _window = '';

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() {
      _items = null;
      _error = null;
    });
    try {
      final r = await videoApi.rank(zone: widget.zone, days: _days);
      if (!mounted) return;
      setState(() {
        _items = r.items;
        _window = '${r.extra['window_start'] ?? ''}';
      });
    } catch (e) {
      if (mounted) setState(() => _error = e);
    }
  }

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    final items = _items;
    return SzPageScaffold(
      appBar: AppBar(title: Text(widget.zoneName == null ? '全站排行榜' : '${widget.zoneName}排行榜')),
      body: Column(children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(kPagePad, 8, kPagePad, 4),
          child: Row(children: [
            for (final d in const [1, 3, 7])
              Padding(
                padding: const EdgeInsets.only(right: 8),
                child: ChoiceChip(
                  label: Text('$d 天'),
                  selected: _days == d,
                  onSelected: (_) {
                    _days = d;
                    _load();
                  },
                ),
              ),
            const Spacer(),
            TextButton(onPressed: () => showFormula(context), child: const Text('怎么排的')),
          ]),
        ),
        Expanded(
          child: items == null
              ? (_error != null ? SzError(error: _error, onRetry: _load) : const Center(child: CircularProgressIndicator()))
              : items.isEmpty
                  ? const Center(child: SzEmpty(text: '这个时间段还没有上榜的视频'))
                  : RefreshIndicator(
                      onRefresh: _load,
                      child: ListView.builder(
                        physics: const AlwaysScrollableScrollPhysics(),
                        itemCount: items.length,
                        itemBuilder: (context, i) {
                          final c = items[i];
                          final pos = c.position ?? i + 1;
                          return VideoRowTile(
                            card: c,
                            subtitle: '互动分 ${c.rank['interaction'] ?? 0} · ${vCount(c.views)} 播放',
                            trailing: SizedBox(
                              width: 30,
                              child: Text('$pos',
                                  textAlign: TextAlign.center,
                                  style: TextStyle(
                                      fontSize: kFontTitle,
                                      fontWeight: FontWeight.w700,
                                      color: pos <= 3 ? sz.clay : sz.inkMuted)),
                            ),
                          );
                        },
                      ),
                    ),
        ),
        if (_window.isNotEmpty)
          Padding(
            padding: const EdgeInsets.all(8),
            child: Text('统计窗口从 ${DateTime.tryParse(_window)?.toLocal().toString().substring(0, 16) ?? ''} 起',
                style: TextStyle(fontSize: kFontMicro, color: sz.inkFaint)),
          ),
      ]),
    );
  }
}

/// 公式原文(和 services/video_rank.py 逐字一致,S3)。
Future<void> showFormula(BuildContext context) async {
  Map<String, dynamic>? f;
  try {
    f = await videoApi.formula();
  } catch (_) {}
  if (!context.mounted) return;
  await szShowSheet<void>(
    context: context,
    builder: (ctx) => SafeArea(
      child: SingleChildScrollView(
        padding: const EdgeInsets.all(kPagePad),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          const Text('推荐、热门、排行榜怎么排', style: TextStyle(fontSize: kFontTitle, fontWeight: FontWeight.w600)),
          const SizedBox(height: 10),
          SelectableText('${f?['formula'] ?? '没取到公式,稍后再试'}',
              style: const TextStyle(fontFamily: 'monospace', fontSize: kFontNote, height: 1.5)),
          const SizedBox(height: 10),
          Text('输入只有公开的计数、发布时间、关注关系和你常看的分区;没有任何付费、商家、运营加权。'
              '代码在 ${f?['source'] ?? 'server/app/services/video_rank.py'}。',
              style: TextStyle(fontSize: kFontNote, color: Theme.of(ctx).sz.inkMuted)),
        ]),
      ),
    ),
  );
}
