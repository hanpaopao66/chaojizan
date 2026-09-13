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
      body: ReviewsList(api: api, merchantId: merchant.id),
    );
  }
}

/// 评价筛选。名字就是服务端 /reviews?filter= 的取值(reviews.py REVIEW_FILTERS)。
/// 好评 4–5 星、差评 1–2 星 —— 和透明中心「差评占比」同一口径,3 星两边都不算。
enum ReviewFilter {
  all('全部'),
  photo('有图'),
  good('好评'),
  bad('差评'),
  append('有追评');

  const ReviewFilter(this.label);

  final String label;

  /// 概览里这个筛选有几条(全店)
  int countIn(ReviewOverview o) => switch (this) {
        ReviewFilter.all => o.count,
        ReviewFilter.photo => o.photo,
        ReviewFilter.good => o.good,
        ReviewFilter.bad => o.bad,
        ReviewFilter.append => o.append,
      };
}

/// 评价列表主体(店铺页「评价」Tab 与独立页复用),设计稿 B。
///
/// 顶上是评分概览(大字评分 + 星级分布)和筛选,下面是一条条评价。
/// **差评照实排在里面**:按时间排,不折叠、不往后挪。
///
/// 概览、筛选的条数都来自服务端的全店概览(/reviews/overview),和店铺页顶上的
/// 「4.8 分 · 268 条」是同一批评价;列表按筛选向服务端要,滑到底再翻下一页。
/// 原来公开接口只给最近 50 条,分布和筛选只能按那 50 条算。
class ReviewsList extends StatefulWidget {
  const ReviewsList({super.key, required this.api, required this.merchantId});

  final ApiClient api;
  final int merchantId;

  @override
  State<ReviewsList> createState() => _ReviewsListState();
}

class _ReviewsListState extends State<ReviewsList> {
  static const _pageSize = 20;

  ApiClient get api => widget.api;

  ReviewOverview? _overview;
  final List<Review> _items = [];
  ReviewFilter _filter = ReviewFilter.all;

  /// 有一页正在路上
  bool _loading = false;
  bool _hasMore = true;

  /// 第一次(概览 + 第一页)没拉到:整页出错页
  String? _error;

  /// 往后翻页没拉到:只在页尾说一声,点了再试
  String? _moreError;

  /// 换筛选之后,还在路上的旧请求回来了要丢掉
  int _generation = 0;

  @override
  void initState() {
    super.initState();
    _reload();
  }

  /// 概览和第一页一起拉(并发);出错页点「重试」也走这里
  Future<void> _reload() async {
    final gen = ++_generation;
    setState(() {
      _loading = true;
      _error = null;
      _moreError = null;
    });
    try {
      final results = await Future.wait<Object>([
        api.merchantReviewOverview(widget.merchantId),
        api.merchantReviews(widget.merchantId,
            filter: _filter.name, limit: _pageSize),
      ]);
      if (!mounted || gen != _generation) return;
      final page = results[1] as List<Review>;
      // 拉成功要把上次的错清掉:出错页排在最前面判断,不清的话重试回不来
      setState(() {
        _overview = results[0] as ReviewOverview;
        _items
          ..clear()
          ..addAll(page);
        _hasMore = page.length == _pageSize;
        _loading = false;
        _error = null;
      });
    } catch (e) {
      if (!mounted || gen != _generation) return;
      setState(() {
        _loading = false;
        _error = '$e';
      });
    }
  }

  /// 换筛选:清掉列表从第一页拉起(概览不用重拉,它本来就是全店的)
  void _setFilter(ReviewFilter f) {
    if (f == _filter) return;
    setState(() {
      _filter = f;
      _generation++;
      _items.clear();
      _hasMore = true;
      _moreError = null;
      // 旧筛选那一页若还在路上,回来会因为 generation 对不上被丢掉;
      // 这里先把「在路上」放下,不然新筛选的第一页永远等不到开始
      _loading = false;
    });
    _loadMore();
  }

  Future<void> _loadMore() async {
    if (_loading || !_hasMore) return;
    final gen = _generation;
    setState(() {
      _loading = true;
      _moreError = null;
    });
    try {
      final page = await api.merchantReviews(widget.merchantId,
          filter: _filter.name,
          before: _items.isEmpty ? null : _items.last.id,
          limit: _pageSize);
      if (!mounted || gen != _generation) return;
      setState(() {
        _items.addAll(page);
        _hasMore = page.length == _pageSize;
        _loading = false;
      });
    } catch (e) {
      if (!mounted || gen != _generation) return;
      setState(() {
        _loading = false;
        _moreError = '$e';
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final overview = _overview;
    if (_error != null) {
      return SzError(error: _error, onRetry: _reload);
    }
    if (overview == null) {
      return const Center(child: CircularProgressIndicator());
    }
    if (overview.count == 0) {
      return const SzEmpty(text: '还没有评价,下单后来做第一个评价的人');
    }
    return ListView.builder(
      // 挂外面给的 PrimaryScrollController:在店铺页里是 NestedScrollView 的内层
      // 控制器,往上滑时店头跟着收起。别给它另挂控制器 —— 内外就联动不起来了
      // (primary 和 controller 同时给,构造时就会断言失败)
      primary: true,
      // 店铺页把这个列表放在开了 extendBody 的 Scaffold 里,
      // 购物车条会盖住页尾。独立的评价页没有底栏,这里读到 0,
      // 所以两处都对
      padding: EdgeInsets.fromLTRB(
          kPagePad, 12, kPagePad, 12 + MediaQuery.of(context).padding.bottom),
      itemCount: 3 + _items.length,
      itemBuilder: (context, i) {
        if (i == 0) return _overviewBlock(context, overview);
        if (i == 1) return _filters(overview);
        if (i == 2 + _items.length) return _footer(context);
        final r = _items[i - 2];
        // 换筛选时换 key,入场错落重播一次;翻页接上来的只在前 8 条里错落
        return SzEnter(
          key: ValueKey('${_filter.name}-${r.id}'),
          index: i - 2,
          child: _ReviewTile(api: api, review: r),
        );
      },
    );
  }

  /// 页尾:还有就去拉下一页(滑到这里才拉),拉不到说一声,拉完了什么都不画
  Widget _footer(BuildContext context) {
    final sz = Theme.of(context).sz;
    if (_moreError != null) {
      return Center(
        child: TextButton(
          onPressed: _loadMore,
          child: Text('没加载出来,点这里重试',
              style: TextStyle(fontSize: kFontNote, color: sz.inkMuted)),
        ),
      );
    }
    if (_hasMore) {
      if (!_loading) {
        WidgetsBinding.instance.addPostFrameCallback((_) {
          if (mounted) _loadMore();
        });
      }
      return const Padding(
        padding: EdgeInsets.symmetric(vertical: 20),
        child: Center(
            child: SizedBox(
                width: 20,
                height: 20,
                child: CircularProgressIndicator(strokeWidth: 2))),
      );
    }
    if (_items.isEmpty) {
      return Padding(
        padding: const EdgeInsets.symmetric(vertical: 36),
        child: Center(
          child: Text('还没有${_filter.label}的评价',
              style: TextStyle(fontSize: kFontBody, color: sz.inkMuted)),
        ),
      );
    }
    return const SizedBox(height: 12);
  }

  Widget _overviewBlock(BuildContext context, ReviewOverview o) {
    final sz = Theme.of(context).sz;
    final avg = o.avg ?? 0;
    final goodPct = (o.good * 100 / o.count).round();
    final label = TextStyle(fontSize: kFontMicro, color: sz.inkMuted);
    return Padding(
      padding: const EdgeInsets.only(bottom: 9),
      child: Row(
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
                      fontSize: kFontNote, letterSpacing: 1.5, color: sz.hold)),
              const SizedBox(height: 3),
              Text('${o.count} 条 · $goodPct% 好评',
                  style: TextStyle(fontSize: kFontNote, color: sz.inkMuted)),
            ],
          ),
          const SizedBox(width: 18),
          Expanded(
            child: Column(
              children: [
                for (var star = 5; star >= 1; star--)
                  Padding(
                    padding: EdgeInsets.only(top: star == 5 ? 0 : 4),
                    child: Row(children: [
                      SizedBox(width: 20, child: Text('$star★', style: label)),
                      const SizedBox(width: 8),
                      Expanded(
                        child: _Bar(
                          fraction: (o.stars[star] ?? 0) / o.count,
                          // 4–5 星是琥珀,3 星及以下退成淡灰 ——
                          // 不给差评上红色:它是事实,不是警报
                          color: star >= 4
                              ? sz.hold
                              : sz.inkFaint.withValues(alpha: .5),
                        ),
                      ),
                      const SizedBox(width: 8),
                      SizedBox(
                        width: 28,
                        child: Text('${o.stars[star] ?? 0}',
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
    );
  }

  Widget _filters(ReviewOverview o) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 3),
      child: Wrap(
        spacing: 7,
        runSpacing: 7,
        children: [
          for (final f in ReviewFilter.values)
            SzChip(
              '${f.label} ${f.countIn(o)}',
              selected: f == _filter,
              onTap: () => _setFilter(f),
            ),
        ],
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
          tween:
              Tween(begin: SzMotion.off(context) ? fraction : 0, end: fraction),
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
                  child:
                      InteractiveViewer(child: Image(image: szNetImage(url))),
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
    final quiet =
        TextStyle(fontSize: kFontNote, height: 1.55, color: sz.inkMuted);
    return Container(
      margin: const EdgeInsets.only(top: 9),
      padding: const EdgeInsets.only(top: 12),
      decoration:
          BoxDecoration(border: Border(top: BorderSide(color: sz.line))),
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
