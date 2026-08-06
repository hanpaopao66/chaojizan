/// 商家评价管理(独立页)。
///
/// 原先评价塞在店铺 tab 最底部:无筛选、无分页、不显示图片和追评 ——
/// 商家要滚过 23 个区块才看得到,差评回应慢一天,挽回余地就少一分。
/// 这里拆成独立页面:筛选(全部/差评/待回复)、图片、追评、回复/追评回复、
/// ≤3 星带申诉入口;差评横幅(main.dart 的 WS bad_review)直达本页。
library;

import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';

import 'appeal_page.dart';

class MerchantReviewsPage extends StatefulWidget {
  const MerchantReviewsPage({
    super.key,
    required this.api,
    this.initialFilter = 0,
  });

  final ApiClient api;

  /// 0 全部 / 1 差评 / 2 待回复。待办里点「差评待回复」进来就该落在差评页,
  /// 不然商家还得自己再点一次筛选
  final int initialFilter;

  @override
  State<MerchantReviewsPage> createState() => _MerchantReviewsPageState();
}

class _MerchantReviewsPageState extends State<MerchantReviewsPage> {
  late int _filter = widget.initialFilter; // 0 全部 / 1 差评(≤3星) / 2 待回复
  List<Review> _reviews = [];
  bool _loaded = false;
  bool _loadingMore = false;
  bool _hasMore = true;

  // 近 30 天负向标签聚合:"送得慢×8"比翻 50 条评价更快看清问题在哪一环
  Map<String, dynamic>? _tagStats;

  // 回复模板(平台预置的起手式,商家改完再发)
  Map<String, dynamic>? _templates;
  // 评分概览:商家最盯的数字,但光一个总分看不出是被几条差评拉的
  Map<String, dynamic>? _overview;

  @override
  void initState() {
    super.initState();
    _reload();
    widget.api.myReviewTagStats().then((stats) {
      if (mounted) setState(() => _tagStats = stats);
    }).catchError((_) {/* 聚合拉不到不影响列表 */});
    widget.api.replyTemplates().then((t) {
      if (mounted) setState(() => _templates = t);
    }).catchError((_) {/* 模板拉不到照样能手写 */});
    widget.api.ratingOverview().then((o) {
      if (mounted) setState(() => _overview = o);
    }).catchError((_) {/* 同上 */});
  }

  /// 评分概览条:总分 + 星级分布 + 近 30 天走势
  Widget _overviewBar() {
    final data = _overview;
    if (data == null) return const SizedBox.shrink();
    final all = data['all_time'] as Map<String, dynamic>? ?? const {};
    final d30 = data['last_30d'] as Map<String, dynamic>? ?? const {};
    final avg = all['avg'];
    if (avg == null) return const SizedBox.shrink();
    final dist = (all['dist'] as Map?)?.cast<String, dynamic>() ?? const {};
    final count = all['count'] as int? ?? 0;
    final trend = data['trend_30d_vs_earlier'] as num?;
    final sz = Theme.of(context).sz;

    return Container(
      margin: const EdgeInsets.fromLTRB(12, 8, 12, 0),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: sz.surface,
        borderRadius: BorderRadius.circular(kRadiusMd),
        border: Border.all(color: sz.line),
      ),
      child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text('$avg',
              style: szFigure(
                  fontSize: 26, fontWeight: FontWeight.w700, color: sz.ink)),
          Text('$count 条评价',
              style: TextStyle(fontSize: 11, color: sz.inkMuted)),
          if (trend != null)
            Text(
                trend > 0
                    ? '近 30 天 ↑${trend.toStringAsFixed(2)}'
                    : trend < 0
                        ? '近 30 天 ↓${(-trend).toStringAsFixed(2)}'
                        : '近 30 天持平',
                style: TextStyle(
                    fontSize: 11,
                    color: trend > 0
                        ? sz.earn
                        : trend < 0
                            ? sz.danger
                            : sz.inkMuted)),
        ]),
        const SizedBox(width: 16),
        Expanded(
          child: Column(children: [
            for (var star = 5; star >= 1; star--)
              Padding(
                padding: const EdgeInsets.symmetric(vertical: 1),
                child: Row(children: [
                  Text('$star★',
                      style: TextStyle(fontSize: 10, color: sz.inkMuted)),
                  const SizedBox(width: 4),
                  Expanded(
                    child: ClipRRect(
                      borderRadius: BorderRadius.circular(2),
                      child: LinearProgressIndicator(
                        minHeight: 6,
                        value: count == 0
                            ? 0
                            : (dist['$star'] as int? ?? 0) / count,
                        backgroundColor: sz.line,
                        valueColor: AlwaysStoppedAnimation(
                            star <= 3 ? sz.danger : sz.hold),
                      ),
                    ),
                  ),
                  const SizedBox(width: 4),
                  SizedBox(
                    width: 26,
                    child: Text('${dist['$star'] ?? 0}',
                        textAlign: TextAlign.right,
                        style: TextStyle(fontSize: 10, color: sz.inkMuted)),
                  ),
                ]),
              ),
            if ((d30['bad_unreplied'] as int? ?? 0) > 0)
              Padding(
                padding: const EdgeInsets.only(top: 4),
                child: Text('近 30 天还有 ${d30['bad_unreplied']} 条差评没回',
                    style: TextStyle(fontSize: 11, color: sz.danger)),
              ),
          ]),
        ),
      ]),
    );
  }

  /// 标签聚合条:商家组(自己能改的)红色,配送组(平台的责任)灰色注明不计分
  Widget _tagStatsBar() {
    final stats = _tagStats;
    if (stats == null) return const SizedBox.shrink();
    final merchantNeg =
        (stats['merchant_neg'] as List? ?? const []).cast<Map>();
    final deliveryNeg =
        (stats['delivery_neg'] as List? ?? const []).cast<Map>();
    if (merchantNeg.isEmpty && deliveryNeg.isEmpty) {
      return const SizedBox.shrink();
    }
    final sz = Theme.of(context).sz;
    return Padding(
      padding: const EdgeInsets.fromLTRB(12, 4, 12, 0),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text('近 ${stats['days']} 天问题归因',
            style: TextStyle(fontSize: 12, color: sz.inkMuted)),
        const SizedBox(height: 4),
        Wrap(spacing: 6, runSpacing: 4, children: [
          for (final e in merchantNeg)
            SzChip('${e['tag']} ×${e['count']}', color: sz.danger, dense: true),
          for (final e in deliveryNeg)
            SzChip('${e['tag']} ×${e['count']}(配送,不计入你的评分)',
                color: sz.inkFaint, dense: true),
        ]),
      ]),
    );
  }

  Future<List<Review>> _fetch({int? before}) {
    return widget.api.myReviews(
      maxRating: _filter == 1 ? 3 : null,
      unreplied: _filter == 2,
      before: before,
    );
  }

  Future<void> _reload() async {
    // 弱网下快速切筛选:先发后至的旧筛选响应不能覆盖新筛选的列表
    final filterAtStart = _filter;
    try {
      final list = await _fetch();
      if (mounted && _filter == filterAtStart) {
        setState(() {
          _reviews = list;
          _loaded = true;
          _hasMore = list.length >= 100;
        });
      }
    } catch (e) {
      if (mounted && _filter == filterAtStart) {
        setState(() => _loaded = true);
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text('$e')));
      }
    }
  }

  Future<void> _loadMore() async {
    if (_loadingMore || !_hasMore || _reviews.isEmpty) return;
    final filterAtStart = _filter;
    setState(() => _loadingMore = true);
    try {
      final more = await _fetch(before: _reviews.last.id);
      // 在途时切了筛选:旧筛选的下一页不能 append 进新筛选的列表
      if (mounted && _filter == filterAtStart) {
        setState(() {
          _reviews.addAll(more);
          _hasMore = more.length >= 100;
        });
      }
    } catch (_) {/* 上拉失败不打扰,下次滚动再试 */} finally {
      if (mounted) setState(() => _loadingMore = false);
    }
  }

  Future<void> _reply(Review review, {required bool append}) async {
    final controller =
        TextEditingController(text: append ? review.appendReply : review.reply);
    // 模板按星级给:差评给道歉+方案的起手式,好评给感谢
    final group = review.merchantRating <= 3 ? 'bad' : 'good';
    final text = await showDialog<String>(
      context: context,
      builder: (dialog) => AlertDialog(
        // 内容区必须可滚动:模板 chip 折两三行 + autofocus 弹键盘后,
        // 小屏可用高度只剩百来点,固定 Column 会直接溢出
        scrollable: true,
        title: Text(append ? '回复追评' : '回复评价'),
        content: StatefulBuilder(
          // 模板在 builder 里现读:initState 的请求还没回来时打开弹窗,
          // 之前的写法会永远没有 chip
          builder: (dialog, setDialog) {
            final tpls = ((_templates?['templates']
                        as Map<String, dynamic>?)?[group] as List? ??
                    const [])
                .cast<Map<String, dynamic>>();
            return Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                if (tpls.isNotEmpty) ...[
                  Text('套用模板(改成自家的话再发)',
                      style: TextStyle(
                          fontSize: 11, color: Theme.of(context).sz.inkMuted)),
                  const SizedBox(height: 4),
                  Wrap(spacing: 6, runSpacing: 2, children: [
                    for (final t in tpls)
                      ActionChip(
                        label: Text('${t['label']}',
                            style: const TextStyle(fontSize: 12)),
                        visualDensity: VisualDensity.compact,
                        onPressed: () => setDialog(() {
                          // 直接赋 text 会把光标置为 -1,后续编辑跳到开头
                          final v = '${t['text']}';
                          controller.value = TextEditingValue(
                            text: v,
                            selection:
                                TextSelection.collapsed(offset: v.length),
                          );
                        }),
                      ),
                  ]),
                  const SizedBox(height: 8),
                ],
                TextField(
                  controller: controller,
                  maxLength: 300,
                  maxLines: 4,
                  autofocus: true,
                  decoration: const InputDecoration(
                      helperText: '回复对所有用户可见;先道歉再给方案,别争对错',
                      border: OutlineInputBorder()),
                ),
              ],
            );
          },
        ),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(dialog), child: const Text('取消')),
          FilledButton(
              onPressed: () => Navigator.pop(dialog, controller.text.trim()),
              child: const Text('发布')),
        ],
      ),
    );
    if (text == null || text.isEmpty) return;
    try {
      final updated = append
          ? await widget.api.replyAppendReview(review.id, text)
          : await widget.api.replyReview(review.id, text);
      if (!mounted) return;
      setState(() {
        final i = _reviews.indexWhere((r) => r.id == review.id);
        if (i >= 0) _reviews[i] = updated;
      });
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text(e is ApiException ? e.message : '$e')));
    }
  }

  String _stars(int n) => '★' * n + '☆' * (5 - n);

  Widget _images(List<String> urls) {
    if (urls.isEmpty) return const SizedBox.shrink();
    return Padding(
      padding: const EdgeInsets.only(top: 6),
      child: Wrap(spacing: 6, runSpacing: 6, children: [
        for (final url in urls)
          GestureDetector(
            onTap: () => showDialog<void>(
              context: context,
              builder: (_) => Dialog(
                insetPadding: const EdgeInsets.all(12),
                child: InteractiveViewer(
                  child: Image(
                      image: szNetImage(widget.api.resolveUrl(url)),
                      fit: BoxFit.contain),
                ),
              ),
            ),
            child: ClipRRect(
              borderRadius: BorderRadius.circular(6),
              child: Image(
                  image: szNetImage(widget.api.resolveUrl(url)),
                  width: 72,
                  height: 72,
                  fit: BoxFit.cover),
            ),
          ),
      ]),
    );
  }

  Widget _replyBox(String label, String text) {
    return Container(
      margin: const EdgeInsets.only(top: 6),
      padding: const EdgeInsets.all(8),
      width: double.infinity,
      decoration: BoxDecoration(
        color: Theme.of(context)
            .colorScheme
            .surfaceContainerHighest
            .withValues(alpha: 0.5),
        borderRadius: BorderRadius.circular(8),
      ),
      child: Text('$label:$text', style: Theme.of(context).textTheme.bodySmall),
    );
  }

  Widget _card(Review review) {
    final sz = Theme.of(context).sz;
    final bad = review.merchantRating <= 3;
    return Card(
      margin: const EdgeInsets.symmetric(horizontal: 12, vertical: 4),
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [
            Text(review.customerName,
                style: Theme.of(context).textTheme.titleSmall),
            const SizedBox(width: 8),
            Text(_stars(review.merchantRating),
                style: TextStyle(color: bad ? sz.danger : sz.hold)),
            const Spacer(),
            Text(review.createdAt.substring(0, 10),
                style: Theme.of(context).textTheme.bodySmall),
          ]),
          if (review.tags.isNotEmpty)
            Padding(
              padding: const EdgeInsets.only(top: 4),
              child: Wrap(spacing: 6, runSpacing: 4, children: [
                for (final tag in review.tags)
                  SzChip(tag, color: sz.inkFaint, dense: true),
              ]),
            ),
          if (review.comment.isNotEmpty) ...[
            const SizedBox(height: 4),
            Text(review.comment),
          ],
          _images(review.imageUrls),
          if (review.reply.isNotEmpty) _replyBox('我的回复', review.reply),
          if (review.appendAt != null) ...[
            const SizedBox(height: 6),
            Text('用户追评',
                style: TextStyle(
                    fontSize: 12,
                    fontWeight: FontWeight.w600,
                    color: sz.inkMuted)),
            if (review.appendContent.isNotEmpty) Text(review.appendContent),
            _images(review.appendImages),
            if (review.appendReply.isNotEmpty)
              _replyBox('追评回复', review.appendReply),
          ],
          Row(mainAxisAlignment: MainAxisAlignment.end, children: [
            // 差评申诉:恶意/配送责任的差评走复核,不该商家硬扛
            if (bad)
              TextButton(
                onPressed: () => Navigator.of(context).push(MaterialPageRoute(
                    builder: (_) => MerchantAppealPage(api: widget.api))),
                child: const Text('申诉'),
              ),
            if (review.appendAt != null)
              TextButton(
                onPressed: () => _reply(review, append: true),
                child: Text(review.appendReply.isEmpty ? '回复追评' : '改追评回复'),
              ),
            TextButton(
              onPressed: () => _reply(review, append: false),
              child: Text(review.reply.isEmpty ? '回复' : '修改回复'),
            ),
          ]),
        ]),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('顾客评价')),
      body: Column(children: [
        _overviewBar(),
        Padding(
          padding: const EdgeInsets.fromLTRB(12, 8, 12, 4),
          child: SegmentedButton<int>(
            segments: const [
              ButtonSegment(value: 0, label: Text('全部')),
              ButtonSegment(value: 1, label: Text('差评')),
              ButtonSegment(value: 2, label: Text('待回复')),
            ],
            selected: {_filter},
            onSelectionChanged: (s) {
              setState(() {
                _filter = s.first;
                _loaded = false;
                _reviews = [];
                _hasMore = true; // 上个筛选翻到底不该锁死新筛选的分页
              });
              _reload();
            },
          ),
        ),
        _tagStatsBar(),
        Expanded(
          child: !_loaded
              ? const Center(child: CircularProgressIndicator())
              : RefreshIndicator(
                  onRefresh: _reload,
                  child: _reviews.isEmpty
                      ? ListView(children: const [
                          Padding(
                              padding: EdgeInsets.all(32),
                              child: Center(child: Text('这一栏没有评价')))
                        ])
                      : NotificationListener<ScrollNotification>(
                          onNotification: (n) {
                            if (n.metrics.pixels >
                                n.metrics.maxScrollExtent - 400) {
                              _loadMore();
                            }
                            return false;
                          },
                          child: ListView.builder(
                            itemCount: _reviews.length + (_loadingMore ? 1 : 0),
                            itemBuilder: (context, i) => i < _reviews.length
                                ? _card(_reviews[i])
                                : const Padding(
                                    padding: EdgeInsets.all(16),
                                    child: Center(
                                        child: CircularProgressIndicator())),
                          ),
                        ),
                ),
        ),
      ]),
    );
  }
}
