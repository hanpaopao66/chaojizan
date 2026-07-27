import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';

/// 商家端:住宿点评列表与回复(首评未回复则回复首评,否则回复追评/修改)。
class StayReviewsPage extends StatefulWidget {
  const StayReviewsPage({super.key, required this.api});

  final ApiClient api;

  @override
  State<StayReviewsPage> createState() => _StayReviewsPageState();
}

class _StayReviewsPageState extends State<StayReviewsPage> {
  late Future<List<StayReview>> _future = widget.api.merchantStayReviews();

  Future<void> _refresh() async {
    setState(() => _future = widget.api.merchantStayReviews());
    await _future;
  }

  Future<void> _reply(StayReview review) async {
    final controller = TextEditingController(
        text: review.reply.isEmpty ? '' : review.reply);
    final text = await showDialog<String>(
      context: context,
      builder: (context) => AlertDialog(
        title: Text(review.reply.isEmpty ? '回复点评' : '回复追评 / 修改回复'),
        content: TextField(
          controller: controller,
          maxLength: 300,
          maxLines: 3,
          decoration: const InputDecoration(border: OutlineInputBorder()),
        ),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(context),
              child: const Text('取消')),
          FilledButton(
              onPressed: () => Navigator.pop(context, controller.text.trim()),
              child: const Text('发布')),
        ],
      ),
    );
    if (text == null || text.isEmpty) return;
    try {
      await widget.api.replyStayReview(review.id, text);
      _refresh();
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text(e is ApiException ? e.message : '$e')));
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('住客点评')),
      body: FutureBuilder<List<StayReview>>(
        future: _future,
        builder: (context, snapshot) {
          if (snapshot.connectionState != ConnectionState.done) {
            return const Center(child: CircularProgressIndicator());
          }
          final reviews = snapshot.data ?? const <StayReview>[];
          if (reviews.isEmpty) {
            return const Center(child: Text('还没有住客点评'));
          }
          return RefreshIndicator(
            onRefresh: _refresh,
            child: ListView.builder(
              itemCount: reviews.length,
              itemBuilder: (context, i) {
                final r = reviews[i];
                return Card(
                  margin:
                      const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
                  child: Padding(
                    padding: const EdgeInsets.all(12),
                    child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Row(children: [
                            Text(r.reviewerName,
                                style: const TextStyle(
                                    fontWeight: FontWeight.bold)),
                            const SizedBox(width: 8),
                            for (var s = 1; s <= 5; s++)
                              Icon(
                                  s <= r.rating
                                      ? Icons.star
                                      : Icons.star_border,
                                  size: 14,
                                  color: Colors.amber),
                            const Spacer(),
                            Text('单号 …${r.orderNo.length > 6 ? r.orderNo.substring(r.orderNo.length - 6) : r.orderNo}',
                                style:
                                    Theme.of(context).textTheme.bodySmall),
                          ]),
                          if (r.tags.isNotEmpty)
                            Text(r.tags.join(' · '),
                                style:
                                    Theme.of(context).textTheme.bodySmall),
                          if (r.comment.isNotEmpty) Text(r.comment),
                          if (r.reply.isNotEmpty)
                            Text('我的回复:${r.reply}',
                                style: Theme.of(context)
                                    .textTheme
                                    .bodySmall
                                    ?.copyWith(
                                        color: Theme.of(context)
                                            .colorScheme
                                            .primary)),
                          if (r.appendContent.isNotEmpty)
                            Text('追评:${r.appendContent}'),
                          if (r.appendReply.isNotEmpty)
                            Text('追评回复:${r.appendReply}',
                                style: Theme.of(context)
                                    .textTheme
                                    .bodySmall
                                    ?.copyWith(
                                        color: Theme.of(context)
                                            .colorScheme
                                            .primary)),
                          Align(
                            alignment: Alignment.centerRight,
                            child: TextButton(
                              onPressed: () => _reply(r),
                              child: Text(r.reply.isEmpty
                                  ? '回复'
                                  : (r.appendContent.isNotEmpty &&
                                          r.appendReply.isEmpty
                                      ? '回复追评'
                                      : '修改回复')),
                            ),
                          ),
                        ]),
                  ),
                );
              },
            ),
          );
        },
      ),
    );
  }
}
