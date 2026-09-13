import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';

/// 店铺评价列表(含商家回复)——独立页面版。
class ReviewsPage extends StatelessWidget {
  const ReviewsPage({super.key, required this.api, required this.merchant});

  final ApiClient api;
  final Merchant merchant;

  @override
  Widget build(BuildContext context) {
    return SzPageScaffold(
      appBar: AppBar(title: Text('${merchant.name} · 评价')),
      body: ReviewsList(api: api, merchantId: merchant.id, shop: merchant),
    );
  }
}

/// 评价筛选。好评 4–5 星、差评 1–2 星 —— 和透明中心「差评占比」同一口径
/// (transparency_page:1–2 星占比),3 星两边都不算。
enum ReviewFilter {
  all('全部'),
  photo('有图'),
  good('好评'),
  bad('差评'),
  append('有追评');

  const ReviewFilter(this.label);

  final String label;

  bool test(Review r) => switch (this) {
        ReviewFilter.all => true,
        ReviewFilter.photo =>
          r.imageUrls.isNotEmpty || r.appendImages.isNotEmpty,
        ReviewFilter.good => r.merchantRating >= 4,
        ReviewFilter.bad => r.merchantRating <= 2,
        ReviewFilter.append =>
          r.appendContent.isNotEmpty || r.appendImages.isNotEmpty,
      };
}

/// 评价列表主体(店铺页「评价」Tab 与独立页复用),设计稿 B。
///
/// 顶上是评分概览(大字评分 + 星级分布)和筛选,下面是一条条评价。
/// **差评照实排在里面**:按时间排,不折叠、不往后挪。
///
/// ⚠️ 公开的评价接口只给最近 50 条(reviews.py merchant_reviews),
/// 没有分布和按条件筛的接口。所以大字评分和总条数取店铺的(全量),
/// 星级分布、好评率、筛选的数只能按拿到的这些算 —— 拿到的少于总数时,
/// 概览底下明说「按最近 N 条算」,不把 50 条的分布当成全店的写。
/// 要全量的分布得先加接口。
class ReviewsList extends StatefulWidget {
  const ReviewsList({
    super.key,
    required this.api,
    required this.merchantId,
    this.shop,
  });

  final ApiClient api;
  final int merchantId;

  /// 店铺(评分和总条数取它的);不给就按拿到的评价自己算
  final Merchant? shop;

  @override
  State<ReviewsList> createState() => _ReviewsListState();
}

class _ReviewsListState extends State<ReviewsList> {
  // 原来在 build 里直接发请求:每次 rebuild 重发一遍,失败也没有重试出口
  late Future<List<Review>> _future =
      widget.api.merchantReviews(widget.merchantId);
  ApiClient get api => widget.api;

  ReviewFilter _filter = ReviewFilter.all;

  @override
  Widget build(BuildContext context) {
    return FutureBuilder(
        future: _future,
        builder: (context, snapshot) {
          if (snapshot.hasError) {
            return SzError(
                error: snapshot.error,
                // 块写法:箭头会把 Future 交给 setState(debug 包断言失败)
                onRetry: () => setState(() {
                      _future = api.merchantReviews(widget.merchantId);
                    }));
          }
          if (!snapshot.hasData) {
            return const Center(child: CircularProgressIndicator());
          }
          final reviews = snapshot.data!;
          if (reviews.isEmpty) {
            return const SzEmpty(text: '还没有评价,下单后来做第一个评价的人');
          }
          final shown = reviews.where(_filter.test).toList();
          return ListView.builder(
            // 店铺页把这个列表放在开了 extendBody 的 Scaffold 里,
            // 购物车条会盖住页尾。独立的评价页没有底栏,这里读到 0,
            // 所以两处都对
            padding: EdgeInsets.fromLTRB(kPagePad, 12, kPagePad,
                12 + MediaQuery.of(context).padding.bottom),
            itemCount: 2 + (shown.isEmpty ? 1 : shown.length),
            itemBuilder: (context, i) {
              if (i == 0) return _overview(context, reviews);
              if (i == 1) return _filters(reviews);
              if (shown.isEmpty) return _emptyFilter(context, reviews);
              final r = shown[i - 2];
              // 换筛选时换 key,入场错落重播一次;重试拉回来的是同一批 key,不重播
              return SzEnter(
                key: ValueKey('${_filter.name}-${r.id}'),
                index: i - 2,
                child: _ReviewTile(api: api, review: r),
              );
            },
          );
        });
  }

  /// 拿到的比店铺总数少:分布和筛选只按拿到的算
  bool _partial(List<Review> reviews) =>
      (widget.shop?.ratingCount ?? 0) > reviews.length;

  Widget _overview(BuildContext context, List<Review> reviews) {
    final sz = Theme.of(context).sz;
    final shop = widget.shop;
    final loaded = reviews.length;
    final avg = shop != null && shop.ratingCount > 0 && shop.ratingAvg != null
        ? shop.ratingAvg!
        : reviews.fold<int>(0, (a, r) => a + r.merchantRating) / loaded;
    final count = shop != null && shop.ratingCount > 0 ? shop.ratingCount : loaded;
    final dist = [
      for (var star = 5; star >= 1; star--)
        reviews.where((r) => r.merchantRating == star).length,
    ];
    final goodPct = ((dist[0] + dist[1]) * 100 / loaded).round();
    final label = TextStyle(fontSize: kFontMicro, color: sz.inkMuted);
    return Padding(
      padding: const EdgeInsets.only(bottom: 9),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            crossAxisAlignment: CrossAxisAlignment.end,
            children: [
              Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(avg.toStringAsFixed(1),
                      style: szMoney(
                          fontSize: kFigureHero, height: 1.05, color: sz.ink)),
                  const SizedBox(height: 3),
                  Text(_stars(avg.round()),
                      style: TextStyle(
                          fontSize: kFontNote,
                          letterSpacing: 1.5,
                          color: sz.hold)),
                  const SizedBox(height: 3),
                  Text('$count 条 · $goodPct% 好评',
                      style:
                          TextStyle(fontSize: kFontNote, color: sz.inkMuted)),
                ],
              ),
              const SizedBox(width: 18),
              Expanded(
                child: Column(
                  children: [
                    for (final (i, n) in dist.indexed)
                      Padding(
                        padding: EdgeInsets.only(top: i == 0 ? 0 : 4),
                        child: Row(children: [
                          SizedBox(width: 20, child: Text('${5 - i}★', style: label)),
                          const SizedBox(width: 8),
                          Expanded(
                            child: _Bar(
                              fraction: n / loaded,
                              // 4–5 星是琥珀,3 星及以下退成淡灰 ——
                              // 不给差评上红色:它是事实,不是警报
                              color: i < 2
                                  ? sz.hold
                                  : sz.inkFaint.withValues(alpha: .5),
                            ),
                          ),
                          const SizedBox(width: 8),
                          SizedBox(
                            width: 24,
                            child: Text('$n',
                                textAlign: TextAlign.right,
                                style: szFigure(
                                    fontSize: kFontMicro, color: sz.inkMuted)),
                          ),
                        ]),
                      ),
                  ],
                ),
              ),
            ],
          ),
          if (_partial(reviews)) ...[
            const SizedBox(height: 8),
            Text('分布、好评率和下面的筛选按最近 $loaded 条算', style: label),
          ],
        ],
      ),
    );
  }

  Widget _filters(List<Review> reviews) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 3),
      child: Wrap(
        spacing: 7,
        runSpacing: 7,
        children: [
          for (final f in ReviewFilter.values)
            SzChip(
              '${f.label} ${reviews.where(f.test).length}',
              selected: f == _filter,
              onTap: () => setState(() => _filter = f),
            ),
        ],
      ),
    );
  }

  Widget _emptyFilter(BuildContext context, List<Review> reviews) {
    final sz = Theme.of(context).sz;
    final where = _partial(reviews) ? '最近 ${reviews.length} 条里' : '';
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 36),
      child: Center(
        child: Text('$where没有${_filter.label}的评价',
            style: TextStyle(fontSize: kFontBody, color: sz.inkMuted)),
      ),
    );
  }
}

String _stars(int n) => '★' * n.clamp(0, 5) + '☆' * (5 - n.clamp(0, 5));

/// 星级分布的一根条:6 高、胶囊形,第一次出现时从 0 长到占比(base 220ms);
/// 关了动效直接画终态
class _Bar extends StatelessWidget {
  const _Bar({required this.fraction, required this.color});

  final double fraction;
  final Color color;

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    return ClipRRect(
      borderRadius: BorderRadius.circular(999),
      child: Container(
        height: 6,
        color: sz.line,
        alignment: Alignment.centerLeft,
        child: TweenAnimationBuilder<double>(
          tween: Tween(begin: SzMotion.off(context) ? fraction : 0, end: fraction),
          duration: SzMotion.of(context, SzMotion.base),
          curve: SzMotion.standard,
          builder: (context, v, _) => FractionallySizedBox(
            widthFactor: v.clamp(0.0, 1.0),
            child: Container(
              decoration: BoxDecoration(
                color: color,
                borderRadius: BorderRadius.circular(999),
              ),
            ),
          ),
        ),
      ),
    );
  }
}

/// 一条评价:名字 / 日期 / 星 / 标签 / 正文 / 图 / 追评 / 商家回复(稿子 B)。
class _ReviewTile extends StatelessWidget {
  const _ReviewTile({required this.api, required this.review});

  final ApiClient api;
  final Review review;

  /// 服务端给的是 UTC,按本地日期写(北京时间早上 7 点的评价不该算成前一天)
  String get _date {
    final t = DateTime.tryParse(review.createdAt)?.toLocal();
    if (t == null) return review.createdAt.substring(0, 10);
    String two(int n) => n.toString().padLeft(2, '0');
    return '${t.year}-${two(t.month)}-${two(t.day)}';
  }

  Widget _photos(BuildContext context, List<String> urls) => SizedBox(
        height: 72,
        child: ListView.separated(
          scrollDirection: Axis.horizontal,
          padding: EdgeInsets.zero,
          itemCount: urls.length,
          separatorBuilder: (_, __) => const SizedBox(width: 6),
          itemBuilder: (context, j) {
            final url = api.resolveUrl(urls[j]);
            return InkWell(
              onTap: () => showDialog<void>(
                context: context,
                builder: (_) => Dialog(
                  backgroundColor: Colors.transparent,
                  child: InteractiveViewer(child: Image(image: szNetImage(url))),
                ),
              ),
              child: ClipRRect(
                borderRadius: BorderRadius.circular(kRadiusSm),
                child: Image(
                    image: szNetImage(url),
                    width: 72,
                    height: 72,
                    fit: BoxFit.cover,
                    errorBuilder: (_, __, ___) => Container(
                        width: 72,
                        height: 72,
                        color: Theme.of(context).sz.surfaceAlt)),
              ),
            );
          },
        ),
      );

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    final r = review;
    final quiet = TextStyle(fontSize: kFontNote, height: 1.55, color: sz.inkMuted);
    return Container(
      margin: const EdgeInsets.only(top: 9),
      padding: const EdgeInsets.only(top: 12),
      decoration: BoxDecoration(border: Border(top: BorderSide(color: sz.line))),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            crossAxisAlignment: CrossAxisAlignment.baseline,
            textBaseline: TextBaseline.alphabetic,
            children: [
              Expanded(
                child: Text(r.customerName,
                    style: TextStyle(
                        fontSize: kFontBodyLg,
                        fontWeight: FontWeight.w600,
                        color: sz.ink)),
              ),
              Text(_date,
                  style: szFigure(fontSize: kFontNote, color: sz.inkMuted)),
            ],
          ),
          const SizedBox(height: 2),
          Text(_stars(r.merchantRating),
              style: TextStyle(
                  fontSize: kFontBody, letterSpacing: 1.5, color: sz.hold)),
          if (r.tags.isNotEmpty) ...[
            const SizedBox(height: 5),
            Wrap(
              spacing: 4,
              runSpacing: 4,
              children: [
                for (final tag in r.tags)
                  Container(
                    padding:
                        const EdgeInsets.symmetric(horizontal: 6, vertical: 1),
                    decoration: BoxDecoration(
                      color: sz.clay.withValues(alpha: .08),
                      borderRadius: BorderRadius.circular(4),
                    ),
                    child: Text(tag,
                        style: TextStyle(fontSize: kFontMicro, color: sz.clay)),
                  ),
              ],
            ),
          ],
          if (r.comment.isNotEmpty) ...[
            const SizedBox(height: 5),
            Text(r.comment,
                style: TextStyle(
                    fontSize: kFontBodyLg, height: 1.5, color: sz.ink)),
          ],
          // 图片评价:72px 横排,点开全屏查看
          if (r.imageUrls.isNotEmpty) ...[
            const SizedBox(height: 7),
            _photos(context, r.imageUrls),
          ],
          if (r.appendContent.isNotEmpty || r.appendImages.isNotEmpty) ...[
            const SizedBox(height: 6),
            if (r.appendContent.isNotEmpty)
              Text('【追评】${r.appendContent}', style: quiet),
            if (r.appendImages.isNotEmpty) ...[
              const SizedBox(height: 6),
              _photos(context, r.appendImages),
            ],
            if (r.appendReply.isNotEmpty) ...[
              const SizedBox(height: 2),
              Text('商家回复追评:${r.appendReply}', style: quiet),
            ],
          ],
          if (r.reply.isNotEmpty)
            Container(
              margin: const EdgeInsets.only(top: 7),
              padding: const EdgeInsets.fromLTRB(10, 8, 10, 8),
              width: double.infinity,
              decoration: BoxDecoration(
                color: sz.surfaceAlt,
                borderRadius: BorderRadius.circular(kRadiusSm),
              ),
              child: Text('商家回复:${r.reply}', style: quiet),
            ),
        ],
      ),
    );
  }
}
