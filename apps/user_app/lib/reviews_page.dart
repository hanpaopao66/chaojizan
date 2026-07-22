import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';

/// 店铺评价列表(含商家回复)——独立页面版。
class ReviewsPage extends StatelessWidget {
  const ReviewsPage({super.key, required this.api, required this.merchant});

  final ApiClient api;
  final Merchant merchant;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: Text('${merchant.name} · 评价')),
      body: ReviewsList(api: api, merchantId: merchant.id),
    );
  }
}

/// 评价列表主体(店铺页「评价」Tab 与独立页复用)。
class ReviewsList extends StatelessWidget {
  const ReviewsList({super.key, required this.api, required this.merchantId});

  final ApiClient api;
  final int merchantId;

  String _stars(int n) => '★' * n + '☆' * (5 - n);

  @override
  Widget build(BuildContext context) {
    return FutureBuilder(
        future: api.merchantReviews(merchantId),
        builder: (context, snapshot) {
          if (snapshot.hasError) {
            return Center(child: Text('${snapshot.error}'));
          }
          if (!snapshot.hasData) {
            return const Center(child: CircularProgressIndicator());
          }
          final reviews = snapshot.data!;
          if (reviews.isEmpty) {
            return const Center(child: Text('还没有评价,下单后来做第一个评价的人'));
          }
          return ListView.separated(
            padding: const EdgeInsets.all(12),
            itemCount: reviews.length,
            separatorBuilder: (_, __) => const Divider(),
            itemBuilder: (context, i) {
              final review = reviews[i];
              return Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      Text(review.customerName,
                          style: Theme.of(context).textTheme.titleSmall),
                      const Spacer(),
                      Text(review.createdAt.substring(0, 10),
                          style: Theme.of(context).textTheme.bodySmall),
                    ],
                  ),
                  const SizedBox(height: 2),
                  Text(_stars(review.merchantRating),
                      style: const TextStyle(color: Colors.amber)),
                  if (review.tags.isNotEmpty) ...[
                    const SizedBox(height: 4),
                    Wrap(
                      spacing: 4,
                      children: [
                        for (final tag in review.tags)
                          Container(
                            padding: const EdgeInsets.symmetric(
                                horizontal: 6, vertical: 1),
                            decoration: BoxDecoration(
                              color: Theme.of(context)
                                  .colorScheme
                                  .primary
                                  .withValues(alpha: 0.08),
                              borderRadius: BorderRadius.circular(4),
                            ),
                            child: Text(tag,
                                style: TextStyle(
                                    fontSize: 11,
                                    color: Theme.of(context)
                                        .colorScheme
                                        .primary)),
                          ),
                      ],
                    ),
                  ],
                  if (review.comment.isNotEmpty) ...[
                    const SizedBox(height: 4),
                    Text(review.comment),
                  ],
                  // 图片评价:72px 横排,点开全屏查看
                  if (review.imageUrls.isNotEmpty) ...[
                    const SizedBox(height: 6),
                    SizedBox(
                      height: 72,
                      child: ListView.separated(
                        scrollDirection: Axis.horizontal,
                        itemCount: review.imageUrls.length,
                        separatorBuilder: (_, __) =>
                            const SizedBox(width: 6),
                        itemBuilder: (context, j) {
                          final url =
                              api.resolveUrl(review.imageUrls[j]);
                          return InkWell(
                            onTap: () => showDialog<void>(
                              context: context,
                              builder: (_) => Dialog(
                                backgroundColor: Colors.transparent,
                                child: InteractiveViewer(
                                    child: Image.network(url)),
                              ),
                            ),
                            child: ClipRRect(
                              borderRadius: BorderRadius.circular(8),
                              child: Image.network(url,
                                  width: 72,
                                  height: 72,
                                  fit: BoxFit.cover,
                                  errorBuilder: (_, __, ___) =>
                                      const SizedBox(width: 72)),
                            ),
                          );
                        },
                      ),
                    ),
                  ],
                  if (review.appendContent.isNotEmpty ||
                      review.appendImages.isNotEmpty)
                    Padding(
                      padding: const EdgeInsets.only(top: 6),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text('【追评】${review.appendContent}',
                              style: Theme.of(context).textTheme.bodySmall),
                          if (review.appendReply.isNotEmpty)
                            Text('商家回复追评:${review.appendReply}',
                                style: Theme.of(context)
                                    .textTheme
                                    .bodySmall
                                    ?.copyWith(color: Colors.grey)),
                        ],
                      ),
                    ),
                  if (review.reply.isNotEmpty)
                    Container(
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
                      child: Text('商家回复:${review.reply}',
                          style: Theme.of(context).textTheme.bodySmall),
                    ),
                ],
              );
            },
          );
        });
  }
}
