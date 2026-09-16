// 编辑历史(F3:发出后 30 分钟内最多改 5 次,每次把旧正文留下来)。
//
// 为什么要给所有人看:改完不留痕的话,「他明明写的是另一句」就永远说不清。
import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';

import '../../video/me/common.dart' show vDateTime;
import '../models.dart';
import '../nav.dart';
import '../widgets/common.dart';

class EditsPage extends StatefulWidget {
  const EditsPage({super.key, required this.pid});

  final String pid;

  @override
  State<EditsPage> createState() => _EditsPageState();
}

class _EditsPageState extends State<EditsPage> {
  List<FEdit>? _items;
  Object? _error;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final r = await forumApi.edits(widget.pid);
      if (mounted) setState(() => _items = r);
    } catch (e) {
      if (mounted) setState(() => _error = e);
    }
  }

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    final items = _items;
    return SzPageScaffold(
      appBar: AppBar(title: const Text('编辑历史')),
      body: items == null
          ? (_error != null
              ? forumErrorView(_error, () {
                  setState(() => _error = null);
                  _load();
                })
              : const Center(child: CircularProgressIndicator()))
          : ListView(children: [
              Padding(
                padding: const EdgeInsets.fromLTRB(kPagePad, 12, kPagePad, 4),
                child: Text('每次改动前的正文都留着,从旧到新。',
                    style: TextStyle(fontSize: kFontNote, color: sz.inkMuted)),
              ),
              if (items.isEmpty)
                const Padding(padding: EdgeInsets.only(top: 24), child: SzEmpty(text: '这条帖子没有改过'))
              else
                for (final e in items)
                  Padding(
                    padding: const EdgeInsets.fromLTRB(kPagePad, 8, kPagePad, 0),
                    child: Container(
                      padding: const EdgeInsets.all(12),
                      decoration: BoxDecoration(
                        border: Border.all(color: sz.line),
                        borderRadius: BorderRadius.circular(kRadiusMd),
                      ),
                      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                        if (e.createdAt != null)
                          Text(vDateTime(e.createdAt!),
                              style: TextStyle(fontSize: kFontMicro, color: sz.inkFaint)),
                        const SizedBox(height: 6),
                        // 历史版本里的 #话题、@ 不做成可点的:那是当时的字,不是当时的实体
                        SelectableText(e.text,
                            style: TextStyle(fontSize: kFontBodyLg, color: sz.ink, height: 1.55)),
                      ]),
                    ),
                  ),
              const SizedBox(height: 24),
            ]),
    );
  }
}
