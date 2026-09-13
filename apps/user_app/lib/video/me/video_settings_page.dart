import 'dart:async';

import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';

import '../../session.dart';
import '../nav.dart';
import 'common.dart';
import 'history_page.dart';

/// 视频设置:个性化推荐开关(S9)、暂停记录观看历史。
class VideoSettingsPage extends StatefulWidget {
  const VideoSettingsPage({super.key});

  @override
  State<VideoSettingsPage> createState() => _VideoSettingsPageState();
}

class _VideoSettingsPageState extends State<VideoSettingsPage> {
  Map<String, dynamic>? _s;
  Object? _error;
  bool _saving = false;

  @override
  void initState() {
    super.initState();
    if (rootApi.isLoggedIn) unawaited(_load());
  }

  Future<void> _load() async {
    setState(() => _error = null);
    try {
      final s = await videoApi.settings();
      if (mounted) setState(() => _s = s);
    } catch (e) {
      if (mounted) setState(() => _error = e);
    }
  }

  Future<void> _set({bool? personalize, bool? historyPaused}) async {
    final before = _s;
    setState(() {
      _saving = true;
      // 先按拨的显示,接口失败再拨回去
      _s = {
        ...?before,
        if (personalize != null) 'personalize': personalize,
        if (historyPaused != null) 'history_paused': historyPaused,
      };
    });
    try {
      final s = await videoApi.patchSettings(personalize: personalize, historyPaused: historyPaused);
      if (mounted) setState(() => _s = s);
    } catch (e) {
      if (mounted) {
        setState(() => _s = before);
        vToast(context, e);
      }
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  Future<void> _clearHistory() async {
    final ok = await vConfirm(context, title: '清空全部观看历史?', body: '续播进度也一起清掉,不能恢复。', ok: '清空', danger: true);
    if (!ok || !mounted) return;
    try {
      await videoApi.clearHistory();
      if (mounted) vToast(context, '观看历史已清空');
    } catch (e) {
      if (mounted) vToast(context, e);
    }
  }

  @override
  Widget build(BuildContext context) {
    if (!rootApi.isLoggedIn) {
      return SzPageScaffold(
        appBar: AppBar(title: const Text('视频设置')),
        body: VideoLoginGate(text: '登录后可以关掉个性化推荐、暂停观看历史', onLoggedIn: () => _load()),
      );
    }
    final s = _s;
    return SzPageScaffold(
      appBar: AppBar(title: const Text('视频设置')),
      body: s == null
          ? (_error != null ? videoErrorView(_error, _load) : const Center(child: CircularProgressIndicator()))
          : ListView(padding: const EdgeInsets.fromLTRB(kPagePad, 4, kPagePad, 24), children: [
              SzEntryGroup(
                title: '推荐',
                footnote: '关掉后「推荐」和没登录的人看到的完全一样:不再按你关注的 UP 主、常看的分区加分,'
                    '看过的、点过「不感兴趣」的也不再过滤。排序公式是公开的,谁都能照着复算。',
                children: [
                  SzEntryTile(
                    title: '个性化推荐',
                    icon: Icons.tune,
                    trailing: Switch(
                      value: s['personalize'] != false,
                      onChanged: _saving ? null : (v) => _set(personalize: v),
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 8),
              SzEntryGroup(
                title: '观看历史',
                footnote: '暂停期间看的视频不进历史,续播进度也不记;已经记下的不受影响。',
                children: [
                  SzEntryTile(
                    title: '暂停记录观看历史',
                    icon: Icons.history_toggle_off,
                    trailing: Switch(
                      value: s['history_paused'] == true,
                      onChanged: _saving ? null : (v) => _set(historyPaused: v),
                    ),
                  ),
                  SzEntryTile(
                    title: '观看历史',
                    icon: Icons.history,
                    onTap: () => Navigator.of(context)
                        .push(MaterialPageRoute<void>(builder: (_) => const VideoHistoryPage())),
                  ),
                  SzEntryTile(title: '清空观看历史', icon: Icons.delete_sweep_outlined, onTap: _clearHistory),
                ],
              ),
            ]),
    );
  }
}
