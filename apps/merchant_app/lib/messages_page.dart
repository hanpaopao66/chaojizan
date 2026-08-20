import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';

/// 消息中心(商家端)。
///
/// 收拢两类内容:平台公告(置顶,横幅只显示最新一条,这里能看全)+
/// 触达记录(评价/系统,按分类筛选)。**订单类消息不进这里** ——
/// 订单页本身就是它们的家,再堆一份只会淹掉真正需要看的。
/// 进入即记已读水位,店铺 tab 和待办卡的未读角标随之清零。
class MerchantMessagesPage extends StatefulWidget {
  const MerchantMessagesPage({super.key, required this.api});

  final ApiClient api;

  @override
  State<MerchantMessagesPage> createState() => _MerchantMessagesPageState();
}

class _MerchantMessagesPageState extends State<MerchantMessagesPage> {
  String? _category; // null 全部 / review / system
  List<Map<String, dynamic>> _announcements = [];
  List<Map<String, dynamic>> _messages = [];
  bool _loaded = false;
  bool _loadingMore = false;
  bool _hasMore = true;

  /// 非空 = 首屏没拉到。「这一栏没有消息」和「没拉到」不能长得一样 ——
  /// 差评通知看不到,商家就错过了申诉窗口
  String _error = '';

  @override
  void initState() {
    super.initState();
    _reload();
    // 进来就算看过:水位记到现在,角标清零
    widget.api.merchantMessagesRead().catchError((_) {});
  }

  Future<void> _reload() async {
    final categoryAtStart = _category;
    try {
      final data = await widget.api.merchantMessages(category: _category);
      if (mounted && _category == categoryAtStart) {
        setState(() {
          _announcements = (data['announcements'] as List? ?? const [])
              .cast<Map<String, dynamic>>();
          _messages = (data['messages'] as List? ?? const [])
              .cast<Map<String, dynamic>>();
          _loaded = true;
          // 页大小以服务端为准:写死的阈值一旦和服务端不一致,
          // 就会在"刚好不满一页"时误判成没有下一页
          _hasMore =
              _messages.length >= (data['page_size'] as int? ?? 50);
          _error = '';
        });
      }
    } catch (e) {
      if (mounted && _category == categoryAtStart) {
        setState(() {
          _loaded = true;
          _error = e is ApiException ? e.message : '$e';
        });
      }
    }
  }

  Future<void> _loadMore() async {
    if (_loadingMore || !_hasMore || _messages.isEmpty) return;
    final categoryAtStart = _category;
    setState(() => _loadingMore = true);
    try {
      final data = await widget.api.merchantMessages(
          category: _category, before: _messages.last['id'] as int);
      if (mounted && _category == categoryAtStart) {
        final more = (data['messages'] as List? ?? const [])
            .cast<Map<String, dynamic>>();
        setState(() {
          _messages.addAll(more);
          _hasMore = more.isNotEmpty;
        });
      }
    } catch (_) {/* 下次滚动再试 */} finally {
      if (mounted) setState(() => _loadingMore = false);
    }
  }

  String _dateLabel(String? iso) {
    if (iso == null) return '';
    final dt = DateTime.tryParse(iso)?.toLocal();
    if (dt == null) return '';
    return '${dt.month}-${dt.day} '
        '${dt.hour.toString().padLeft(2, '0')}:'
        '${dt.minute.toString().padLeft(2, '0')}';
  }

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    return SzPageScaffold(
      appBar: AppBar(title: const Text('消息中心')),
      body: !_loaded
          ? const Center(child: CircularProgressIndicator())
          : _error.isNotEmpty
          ? SzError(error: _error, onRetry: _reload)
          : RefreshIndicator(
              onRefresh: _reload,
              child: NotificationListener<ScrollNotification>(
                onNotification: (n) {
                  if (n.metrics.pixels > n.metrics.maxScrollExtent - 400) {
                    _loadMore();
                  }
                  return false;
                },
                child: _list(sz),
              ),
            ),
    );
  }

  /// 通知是**翻页加载**的,越滚越长 —— 必须按需构建。
  /// 顶部公告和分段选择器数量固定,先建出来当固定头部
  Widget _list(SzColors sz) {
    final leading = <Widget>[
      if (_announcements.isNotEmpty) ...[
        Text('平台公告', style: Theme.of(context).textTheme.titleSmall),
        const SizedBox(height: 6),
        for (final a in _announcements)
          Card(
            color: Theme.of(context)
                .colorScheme
                .tertiaryContainer
                .withValues(alpha: 0.4),
            child: Padding(
              padding: const EdgeInsets.all(12),
              child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(children: [
                      Icon(Icons.campaign, size: 16, color: sz.hold),
                      const SizedBox(width: 6),
                      Expanded(
                          child: Text(a['title'] as String? ?? '',
                              style: const TextStyle(
                                  fontWeight: FontWeight.w600))),
                      Text(_dateLabel(a['created_at'] as String?),
                          style:
                              TextStyle(fontSize: 11, color: sz.inkMuted)),
                    ]),
                    const SizedBox(height: 4),
                    Text(a['content'] as String? ?? ''),
                  ]),
            ),
          ),
        const SizedBox(height: 12),
      ],
      Row(children: [
        Text('通知', style: Theme.of(context).textTheme.titleSmall),
        const Spacer(),
        SegmentedButton<String?>(
          segments: const [
            ButtonSegment(value: null, label: Text('全部')),
            ButtonSegment(value: 'review', label: Text('评价')),
            ButtonSegment(value: 'system', label: Text('系统')),
          ],
          selected: {_category},
          showSelectedIcon: false,
          onSelectionChanged: (s) {
            setState(() {
              _category = s.first;
              _messages = [];
              _loaded = false;
              _hasMore = true;
            });
            _reload();
          },
        ),
      ]),
      const SizedBox(height: 6),
      if (_messages.isEmpty)
        const Padding(
            padding: EdgeInsets.all(32),
            child: Center(child: Text('这一栏没有消息'))),
    ];

    return ListView.builder(
      padding: const EdgeInsets.all(12),
      // 尾部那一格留给「加载中」,没在加载就是零高
      itemCount: leading.length + _messages.length + 1,
      itemBuilder: (context, i) {
        if (i < leading.length) return leading[i];
        final j = i - leading.length;
        if (j >= _messages.length) {
          return _loadingMore
              ? const Padding(
                  padding: EdgeInsets.all(12),
                  child: Center(child: CircularProgressIndicator()))
              : const SizedBox.shrink();
        }
        final m = _messages[j];
        return Card(
          margin: const EdgeInsets.symmetric(vertical: 3),
          child: ListTile(
            dense: true,
            leading: Icon(
              m['kind'] == 'review'
                  ? Icons.rate_review_outlined
                  : Icons.notifications_none,
              color: m['kind'] == 'review' ? sz.danger : sz.inkMuted,
            ),
            title: Text(m['title'] as String? ?? ''),
            subtitle: Text(m['content'] as String? ?? '',
                maxLines: 2, overflow: TextOverflow.ellipsis),
            trailing: Text(_dateLabel(m['created_at'] as String?),
                style: TextStyle(fontSize: 11, color: sz.inkMuted)),
          ),
        );
      },
    );
  }
}
