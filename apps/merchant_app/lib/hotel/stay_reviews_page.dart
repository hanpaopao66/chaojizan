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
      builder: (context) => SzDialog(
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
    return SzPageScaffold(
      appBar: AppBar(title: const Text('住客点评')),
      body: FutureBuilder<List<StayReview>>(
        future: _future,
        builder: (context, snapshot) {
          if (snapshot.connectionState != ConnectionState.done) {
            return const Center(child: CircularProgressIndicator());
          }
          final reviews = snapshot.data ?? const <StayReview>[];
          if (reviews.isEmpty) {
            return const SzEmpty(
                art: BrandArt.receipt, text: '还没有住客点评\n客人离店后可以评价');
          }
          return RefreshIndicator(
            onRefresh: _refresh,
            child: ListView.builder(
              itemCount: reviews.length,
              itemBuilder: (context, i) {
                final r = reviews[i];
                final sz = Theme.of(context).sz;
                // 我的回复用次级块底衬出来,比换个字色更容易区分"谁说的"
                Widget quoted(String label, String text) => Container(
                      width: double.infinity,
                      margin: const EdgeInsets.only(top: 7),
                      padding: const EdgeInsets.symmetric(
                          horizontal: 10, vertical: 8),
                      decoration: BoxDecoration(
                        color: sz.surfaceAlt,
                        borderRadius: BorderRadius.circular(kRadiusSm),
                      ),
                      child: Text('$label:$text',
                          style: TextStyle(
                              fontSize: 12, height: 1.55, color: sz.inkMuted)),
                    );
                return Container(
                  margin:
                      const EdgeInsets.symmetric(horizontal: 12, vertical: 5),
                  decoration: BoxDecoration(
                    color: sz.surface,
                    borderRadius: BorderRadius.circular(kRadiusMd),
                    border: Border.all(color: sz.line),
                  ),
                  child: Padding(
                    padding: const EdgeInsets.all(kCardPad),
                    child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Row(children: [
                            Text(r.reviewerName,
                                style: TextStyle(
                                    fontSize: 13.5,
                                    fontWeight: FontWeight.w600,
                                    color: sz.ink)),
                            const SizedBox(width: 8),
                            for (var s = 1; s <= 5; s++)
                              Icon(
                                  s <= r.rating
                                      ? Icons.star
                                      : Icons.star_border,
                                  size: 13,
                                  color:
                                      s <= r.rating ? sz.hold : sz.inkMuted),
                            const Spacer(),
                            Text(
                                '…${r.orderNo.length > 6 ? r.orderNo.substring(r.orderNo.length - 6) : r.orderNo}',
                                style: szFigure(
                                    fontSize: 11, color: sz.inkMuted)),
                          ]),
                          if (r.tags.isNotEmpty) ...[
                            const SizedBox(height: 5),
                            Wrap(
                              spacing: 6,
                              runSpacing: 4,
                              children: [
                                for (final t in r.tags)
                                  SzChip(t, color: sz.inkMuted, dense: true),
                              ],
                            ),
                          ],
                          if (r.comment.isNotEmpty) ...[
                            const SizedBox(height: 7),
                            Text(r.comment,
                                style: TextStyle(
                                    fontSize: 13, height: 1.6, color: sz.ink)),
                          ],
                          if (r.reply.isNotEmpty) quoted('我的回复', r.reply),
                          if (r.appendContent.isNotEmpty) ...[
                            const SizedBox(height: 7),
                            Text('追评:${r.appendContent}',
                                style: TextStyle(
                                    fontSize: 12.5,
                                    height: 1.6,
                                    color: sz.ink)),
                          ],
                          if (r.appendReply.isNotEmpty)
                            quoted('追评回复', r.appendReply),
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
