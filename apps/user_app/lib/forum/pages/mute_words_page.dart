// 屏蔽词(§7.2:每人最多 100 个)。带这些词的帖子不进我的推荐(§5.7)。
import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';

import '../../session.dart';
import '../../video/me/common.dart' show VideoLoginGate, vConfirm, vPrompt;
import '../models.dart';
import '../nav.dart';
import '../widgets/common.dart';

class MuteWordsPage extends StatefulWidget {
  const MuteWordsPage({super.key});

  @override
  State<MuteWordsPage> createState() => _MuteWordsPageState();
}

class _MuteWordsPageState extends State<MuteWordsPage> {
  List<String>? _words;
  Object? _error;
  bool _busy = false;

  @override
  void initState() {
    super.initState();
    if (rootApi.isLoggedIn) _load();
  }

  Future<void> _load() async {
    try {
      final w = await forumApi.muteWords();
      if (mounted) {
        setState(() {
          _words = w;
          _error = null;
        });
      }
    } catch (e) {
      if (mounted) setState(() => _error = e);
    }
  }

  Future<void> _add() async {
    final w = await vPrompt(context,
        title: '加一个屏蔽词',
        hint: '带这个词的帖子不进你的推荐',
        maxLength: 30,
        validate: (t) => t.trim().isEmpty ? '写点什么' : null);
    if (w == null || w.trim().isEmpty || !mounted) return;
    setState(() => _busy = true);
    try {
      final next = await forumApi.addMuteWord(w.trim());
      if (mounted) setState(() => _words = next);
    } on ApiException catch (e) {
      if (mounted) fToast(context, e.message);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _remove(String w) async {
    final ok = await vConfirm(context, title: '不再屏蔽「$w」?', ok: '去掉');
    if (!ok || !mounted) return;
    setState(() => _busy = true);
    try {
      final next = await forumApi.removeMuteWord(w);
      if (mounted) setState(() => _words = next);
    } on ApiException catch (e) {
      if (mounted) fToast(context, e.message);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    final words = _words;
    if (!rootApi.isLoggedIn) {
      return SzPageScaffold(
        appBar: AppBar(title: const Text('屏蔽词')),
        body: VideoLoginGate(text: '登录后能设屏蔽词', onLoggedIn: _load),
      );
    }
    return SzPageScaffold(
      appBar: AppBar(
        title: const Text('屏蔽词'),
        actions: [
          IconButton(
            tooltip: '加一个',
            onPressed: _busy || (words != null && words.length >= kMuteWordsMax) ? null : _add,
            icon: const Icon(Icons.add),
          ),
        ],
      ),
      body: words == null
          ? (_error != null
              ? forumErrorView(_error, () {
                  setState(() => _error = null);
                  _load();
                })
              : const Center(child: CircularProgressIndicator()))
          : ListView(children: [
              Padding(
                padding: const EdgeInsets.fromLTRB(kPagePad, 12, kPagePad, 4),
                child: Text(
                  '带这些词的帖子不会出现在你的推荐里。最多 $kMuteWordsMax 个,'
                  '已经用了 ${words.length} 个。屏蔽词只影响你自己看到什么,不影响别人。',
                  style: TextStyle(fontSize: kFontNote, color: sz.inkMuted, height: 1.5),
                ),
              ),
              if (words.isEmpty)
                const Padding(padding: EdgeInsets.only(top: 24), child: SzEmpty(text: '还没有设屏蔽词'))
              else
                for (final w in words)
                  ListTile(
                    title: Text(w),
                    trailing: IconButton(
                      tooltip: '去掉',
                      onPressed: _busy ? null : () => _remove(w),
                      icon: const Icon(Icons.close, size: 18),
                    ),
                  ),
              const SizedBox(height: 24),
            ]),
    );
  }
}
