// 探索:搜索框 + 热门话题(§5.7)+ 公式页入口。
import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';

import '../../video/me/common.dart' show vDateTime;
import '../models.dart';
import '../nav.dart';
import '../widgets/common.dart';

class ExplorePage extends StatefulWidget {
  const ExplorePage({super.key});

  @override
  State<ExplorePage> createState() => _ExplorePageState();
}

class _ExplorePageState extends State<ExplorePage> {
  List<FTrendingTag>? _tags;
  DateTime? _updatedAt;
  Object? _error;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final r = await forumApi.trending();
      if (mounted) {
        setState(() {
          _tags = r.items;
          _updatedAt = r.updatedAt;
          _error = null;
        });
      }
    } catch (e) {
      if (mounted) setState(() => _error = e);
    }
  }

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    final tags = _tags;
    return SzPageScaffold(
      appBar: AppBar(title: const Text('探索')),
      body: RefreshIndicator(
        onRefresh: _load,
        child: ListView(children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(kPagePad, 12, kPagePad, 4),
            child: GestureDetector(
              onTap: () => openForumSearch(context),
              child: Container(
                padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
                decoration: BoxDecoration(
                  color: sz.surfaceAlt,
                  borderRadius: BorderRadius.circular(kRadiusLg),
                  border: Border.all(color: sz.line),
                ),
                child: Row(children: [
                  Icon(Icons.search, size: 18, color: sz.inkMuted),
                  const SizedBox(width: 8),
                  Text('搜帖子、人、话题', style: TextStyle(fontSize: kFontBody, color: sz.inkMuted)),
                ]),
              ),
            ),
          ),
          FSection('热门话题',
              trailing: _updatedAt == null
                  ? null
                  : Text('${vDateTime(_updatedAt!)} 更新',
                      style: TextStyle(fontSize: kFontMicro, color: sz.inkFaint))),
          if (tags == null)
            _error != null
                ? forumErrorView(_error, () {
                    setState(() => _error = null);
                    _load();
                  })
                : const Padding(
                    padding: EdgeInsets.all(40), child: Center(child: CircularProgressIndicator()))
          else if (tags.isEmpty)
            const Padding(padding: EdgeInsets.only(top: 12), child: SzEmpty(text: '这会儿还没有热起来的话题'))
          else
            for (var i = 0; i < tags.length; i++)
              ListTile(
                leading: Text('${i + 1}',
                    style: szTabular(fontSize: kFontBodyLg, color: sz.inkMuted, fontWeight: FontWeight.w700)),
                title: Text('#${tags[i].display}', style: const TextStyle(fontWeight: FontWeight.w600)),
                subtitle: Text('近 24 小时 ${tags[i].authors24h} 人用过,近 3 小时 ${tags[i].authors3h} 人',
                    style: TextStyle(fontSize: kFontNote, color: sz.inkMuted)),
                onTap: () => openTag(context, tags[i].tag, display: tags[i].display),
              ),
          const SizedBox(height: 8),
          ListTile(
            leading: const Icon(Icons.functions),
            title: const Text('推荐和热门话题是怎么排的'),
            subtitle: Text('公式和参数全部公开', style: TextStyle(fontSize: kFontNote, color: sz.inkMuted)),
            trailing: const Icon(Icons.chevron_right),
            onTap: () => openForumFormula(context),
          ),
          const SizedBox(height: 24),
        ]),
      ),
    );
  }
}
