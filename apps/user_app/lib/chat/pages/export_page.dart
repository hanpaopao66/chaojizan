import 'dart:async';

import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';
import 'package:url_launcher/url_launcher.dart';

import '../store.dart';

/// 导出我的数据(S5):聊天记录(JSON + 媒体)和自己的投稿。服务端后台打包,这里只看进度、下载。
class ExportPage extends StatefulWidget {
  const ExportPage({super.key});

  @override
  State<ExportPage> createState() => _ExportPageState();
}

class _ExportPageState extends State<ExportPage> {
  final _store = ChatStore.instance;
  Map<String, dynamic>? _st;
  Object? _error;
  bool _busy = false;
  Timer? _poll;
  StreamSubscription? _events;

  @override
  void initState() {
    super.initState();
    _load();
    // 做好了服务端发一条 export 用户事件:不用死等轮询
    _events = _store.userEvents.stream.listen((e) {
      if (e.type == 'export') _load();
    });
  }

  @override
  void dispose() {
    _poll?.cancel();
    _events?.cancel();
    super.dispose();
  }

  Future<void> _load() async {
    try {
      final st = await _store.api.exportStatus();
      if (!mounted) return;
      setState(() {
        _st = st;
        _error = null;
      });
      _poll?.cancel();
      if (st['state'] == 'running') _poll = Timer(const Duration(seconds: 2), _load);
    } catch (e) {
      if (mounted) setState(() => _error = e);
    }
  }

  Future<void> _start() async {
    setState(() => _busy = true);
    try {
      final st = await _store.api.startExport();
      if (mounted) setState(() => _st = {...?_st, ...st});
      _poll?.cancel();
      _poll = Timer(const Duration(seconds: 2), _load);
    } on ApiException catch (e) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(e.message)));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _download(String url) async {
    final uri = Uri.parse(_store.api.api.resolveUrl(url));
    await launchUrl(uri, mode: LaunchMode.externalApplication);
  }

  static String _size(int b) {
    if (b < 1024 * 1024) return '${(b / 1024).toStringAsFixed(0)} KB';
    if (b < 1024 * 1024 * 1024) return '${(b / 1024 / 1024).toStringAsFixed(1)} MB';
    return '${(b / 1024 / 1024 / 1024).toStringAsFixed(2)} GB';
  }

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    final st = _st;
    final state = '${st?['state'] ?? ''}';
    final last = st?['last'] is Map ? (st!['last'] as Map).cast<String, dynamic>() : null;
    // 24 小时一次:没到点就把按钮置灰、告诉他几点能再导(别让他点了才看到 429)
    final nextAt = DateTime.tryParse('${last?['next_at'] ?? ''}')?.toLocal();
    final cooling = nextAt != null && nextAt.isAfter(DateTime.now());
    return SzPageScaffold(
      appBar: AppBar(title: const Text('导出我的数据')),
      body: st == null
          ? Center(child: _error != null ? SzError(error: _error, onRetry: _load) : const CircularProgressIndicator())
          : ListView(padding: const EdgeInsets.all(kPagePad), children: [
              Text('会导出什么', style: const TextStyle(fontSize: kFontTitle, fontWeight: FontWeight.w600)),
              const SizedBox(height: 8),
              Text(
                '· 你现在还能看到的全部聊天记录,每个会话一个 JSON 文件\n'
                '· 消息里的图片、视频、语音、文件(总量最多 2GB,超出的只列名字)\n'
                '· 你的资料、联系人、拉黑名单\n'
                '· 你的投稿:标题简介等信息,和每 P 最高清晰度的视频文件\n\n'
                '你清空过的、入群前看不到的、自己隐藏掉的消息不会出现在里面。24 小时内只能导出一次。',
                style: TextStyle(color: sz.inkMuted, height: 1.6),
              ),
              const SizedBox(height: 20),
              if (state == 'running')
                Row(children: [
                  const SizedBox(width: 20, height: 20, child: CircularProgressIndicator(strokeWidth: 2)),
                  const SizedBox(width: 12),
                  Expanded(child: Text('正在打包:${st['progress'] ?? ''}。可以先离开这一页,做好了会通知你。')),
                ])
              else ...[
                if (state == 'failed')
                  Padding(
                    padding: const EdgeInsets.only(bottom: 12),
                    child: Text('${st['error'] ?? '导出失败'}', style: TextStyle(color: sz.danger)),
                  ),
                FilledButton(
                  onPressed: _busy || cooling ? null : _start,
                  child: Text(last == null ? '开始导出' : '重新导出'),
                ),
                if (cooling)
                  Padding(
                    padding: const EdgeInsets.only(top: 6),
                    child: Text(
                        '${nextAt.month} 月 ${nextAt.day} 日 ${nextAt.hour.toString().padLeft(2, '0')}:${nextAt.minute.toString().padLeft(2, '0')} 之后可以再导出',
                        textAlign: TextAlign.center,
                        style: TextStyle(fontSize: kFontNote, color: sz.inkMuted)),
                  ),
              ],
              if (last != null) ...[
                const SizedBox(height: 24),
                const Divider(),
                ListTile(
                  contentPadding: EdgeInsets.zero,
                  leading: const Icon(Icons.folder_zip_outlined),
                  title: Text('${last['name'] ?? '导出文件'}'),
                  subtitle: Text([
                    _size((last['size'] as num? ?? 0).toInt()),
                    if (last['summary'] is Map) ...[
                      '${(last['summary'] as Map)['chats'] ?? 0} 个会话',
                      '${(last['summary'] as Map)['messages'] ?? 0} 条消息',
                      '${(last['summary'] as Map)['media'] ?? 0} 个文件',
                      if (((last['summary'] as Map)['videos'] ?? 0) != 0) '${(last['summary'] as Map)['videos']} 个投稿',
                    ],
                  ].join(' · ')),
                  trailing: FilledButton.tonal(
                    onPressed: last['url'] == null ? null : () => _download('${last['url']}'),
                    child: const Text('下载'),
                  ),
                ),
                Text('下载地址只对你自己有效。', style: TextStyle(fontSize: kFontNote, color: sz.inkFaint)),
              ],
            ]),
    );
  }
}
