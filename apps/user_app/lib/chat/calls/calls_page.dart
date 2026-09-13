import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';

import '../chat_page.dart';
import '../store.dart';
import '../ui/avatar.dart';
import '../ui/format.dart';
import 'call_controller.dart';

/// 通话记录(我打的、打给我的),点右边回拨,点整行进和他的聊天。
class CallsPage extends StatefulWidget {
  const CallsPage({super.key});

  @override
  State<CallsPage> createState() => _CallsPageState();
}

class _CallsPageState extends State<CallsPage> {
  List<Map<String, dynamic>>? _items;
  Object? _error;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final r = await ChatStore.instance.api.callHistory();
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
      appBar: AppBar(title: const Text('通话记录')),
      body: items == null
          ? (_error != null ? SzError(error: _error, onRetry: _load) : const Center(child: CircularProgressIndicator()))
          : items.isEmpty
              ? SzRefreshableEmpty(onRefresh: _load, child: const SzEmpty(text: '还没有通话\n在私聊右上角点电话图标就能打'))
              : RefreshIndicator(
                  onRefresh: _load,
                  child: ListView.builder(
                    itemCount: items.length,
                    itemBuilder: (context, i) {
                      final r = items[i];
                      final peer = (r['peer'] as Map?)?.cast<String, dynamic>() ?? const {};
                      final name = '${peer['contact_alias'] ?? ''}'.isNotEmpty ? '${peer['contact_alias']}' : '${peer['name'] ?? ''}';
                      final outgoing = r['outgoing'] == true;
                      final video = r['video'] == true;
                      final state = '${r['state']}';
                      final missed = !outgoing && (state == 'missed' || state == 'busy' || state == 'canceled');
                      final at = DateTime.tryParse('${r['started_at'] ?? ''}')?.toLocal();
                      final dur = (r['duration'] as num?)?.toInt() ?? 0;
                      return ListTile(
                        leading: ChatAvatar(name: name, url: '${peer['avatar'] ?? ''}', size: 44),
                        title: Text(name, style: TextStyle(color: missed ? sz.danger : null)),
                        subtitle: Row(children: [
                          Icon(outgoing ? Icons.call_made : Icons.call_received, size: 14, color: missed ? sz.danger : sz.inkMuted),
                          const SizedBox(width: 4),
                          Flexible(
                            child: Text(
                              [
                                callLabel({'video': video, 'state': state, 'duration': dur}, mine: outgoing),
                                if (at != null) listTime(at),
                              ].join(' · '),
                              maxLines: 1,
                              overflow: TextOverflow.ellipsis,
                              style: TextStyle(fontSize: kFontNote, color: sz.inkMuted),
                            ),
                          ),
                        ]),
                        trailing: IconButton(
                          tooltip: video ? '视频回拨' : '回拨',
                          icon: Icon(video ? Icons.videocam_outlined : Icons.call_outlined, color: sz.clay),
                          onPressed: () async {
                            final id = (peer['id'] as num?)?.toInt();
                            if (id == null) return;
                            final ok = await CallController.instance.start(id, name, '${peer['avatar'] ?? ''}', video: video);
                            if (!ok && context.mounted) {
                              ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('正在通话中,先挂掉这一通')));
                            }
                          },
                        ),
                        onTap: () {
                          final id = (peer['id'] as num?)?.toInt();
                          if (id != null) openPrivateWith(context, id);
                        },
                      );
                    },
                  ),
                ),
    );
  }
}
