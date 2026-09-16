// 论坛设置(个性化开关、屏蔽词、书签入口)和推荐公式页(§5.7)。
import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';

import '../../session.dart';
import '../nav.dart';
import '../widgets/common.dart';

class ForumSettingsPage extends StatefulWidget {
  const ForumSettingsPage({super.key});

  @override
  State<ForumSettingsPage> createState() => _ForumSettingsPageState();
}

class _ForumSettingsPageState extends State<ForumSettingsPage> {
  bool? _personalize;
  Object? _error;
  bool _busy = false;

  @override
  void initState() {
    super.initState();
    if (rootApi.isLoggedIn) _load();
  }

  Future<void> _load() async {
    try {
      final s = await forumApi.settings();
      if (mounted) {
        setState(() {
          _personalize = s['personalize'] != false;
          _error = null;
        });
      }
    } catch (e) {
      if (mounted) setState(() => _error = e);
    }
  }

  Future<void> _set(bool on) async {
    setState(() {
      _busy = true;
      _personalize = on;
    });
    try {
      final s = await forumApi.putSettings(personalize: on);
      if (mounted) setState(() => _personalize = s['personalize'] != false);
    } on ApiException catch (e) {
      if (mounted) {
        setState(() => _personalize = !on);
        fToast(context, e.message);
      }
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    return SzPageScaffold(
      appBar: AppBar(title: const Text('论坛设置')),
      body: ListView(children: [
        if (rootApi.isLoggedIn) ...[
          if (_personalize == null && _error != null)
            forumErrorView(_error, () {
              setState(() => _error = null);
              _load();
            })
          else
            SwitchListTile(
              title: const Text('按我的兴趣推荐'),
              subtitle: Text(
                '关掉之后,推荐只按帖子本身的互动和新旧排,不看我关注了谁、点过什么话题。'
                '排法是公开的,点下面那条看得到。',
                style: TextStyle(fontSize: kFontNote, color: sz.inkMuted, height: 1.5),
              ),
              value: _personalize ?? true,
              onChanged: _busy || _personalize == null ? null : _set,
            ),
          ListTile(
            leading: const Icon(Icons.block),
            title: const Text('屏蔽词'),
            subtitle: Text('带这些词的帖子不进你的推荐',
                style: TextStyle(fontSize: kFontNote, color: sz.inkMuted)),
            trailing: const Icon(Icons.chevron_right),
            onTap: () => openMuteWords(context),
          ),
          ListTile(
            leading: const Icon(Icons.bookmark_border),
            title: const Text('书签'),
            subtitle: Text('只有你看得到', style: TextStyle(fontSize: kFontNote, color: sz.inkMuted)),
            trailing: const Icon(Icons.chevron_right),
            onTap: () => openBookmarks(context),
          ),
        ] else
          Padding(
            padding: const EdgeInsets.all(kPagePad),
            child: Text('登录后能关掉个性化推荐、设屏蔽词。',
                style: TextStyle(fontSize: kFontNote, color: sz.inkMuted)),
          ),
        ListTile(
          leading: const Icon(Icons.functions),
          title: const Text('推荐是怎么排的'),
          subtitle: Text('公式和每个参数全部公开', style: TextStyle(fontSize: kFontNote, color: sz.inkMuted)),
          trailing: const Icon(Icons.chevron_right),
          onTap: () => openForumFormula(context),
        ),
        const SizedBox(height: 24),
      ]),
    );
  }
}

/// 推荐和热门话题的公式(§5.7):服务端给什么就摊什么,页面不写死任何一个数。
class ForumFormulaPage extends StatefulWidget {
  const ForumFormulaPage({super.key});

  @override
  State<ForumFormulaPage> createState() => _ForumFormulaPageState();
}

class _ForumFormulaPageState extends State<ForumFormulaPage> {
  Map<String, dynamic>? _data;
  Object? _error;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final d = await forumApi.formula();
      if (mounted) setState(() => _data = d);
    } catch (e) {
      if (mounted) setState(() => _error = e);
    }
  }

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    final d = _data;
    final params = d?['params'];
    return SzPageScaffold(
      appBar: AppBar(title: const Text('怎么排的')),
      body: d == null
          ? (_error != null
              ? forumErrorView(_error, () {
                  setState(() => _error = null);
                  _load();
                })
              : const Center(child: CircularProgressIndicator()))
          : ListView(padding: const EdgeInsets.all(kPagePad), children: [
              Text('推荐和热门话题按下面这个式子排,每条推荐还会带算分的中间量。',
                  style: TextStyle(fontSize: kFontNote, color: sz.inkMuted, height: 1.5)),
              const SizedBox(height: 12),
              Container(
                padding: const EdgeInsets.all(12),
                decoration: BoxDecoration(
                  color: sz.surfaceAlt,
                  borderRadius: BorderRadius.circular(kRadiusMd),
                ),
                child: SelectableText('${d['formula'] ?? ''}',
                    style: szTabular(fontSize: kFontBody, color: sz.ink, height: 1.7)),
              ),
              if (params is Map && params.isNotEmpty) ...[
                const SizedBox(height: 18),
                Text('参数', style: TextStyle(fontWeight: FontWeight.w600, color: sz.clay)),
                const SizedBox(height: 6),
                for (final e in params.entries)
                  Padding(
                    padding: const EdgeInsets.symmetric(vertical: 3),
                    child: Row(children: [
                      Expanded(child: Text('${e.key}', style: const TextStyle(fontSize: kFontBody))),
                      Text('${e.value}', style: szTabular(fontSize: kFontBody, color: sz.ink)),
                    ]),
                  ),
              ],
              const SizedBox(height: 24),
            ]),
    );
  }
}
