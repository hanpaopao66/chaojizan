/// 商家判责申诉:对「判商家责任的售后」与「差评」在 72 小时内申诉。
/// 申诉成立:售后恢复被冲净额(平台认亏,不追用户款);差评隐藏并回调评分。
library;

import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';

class MerchantAppealPage extends StatefulWidget {
  const MerchantAppealPage({super.key, required this.api});

  final ApiClient api;

  @override
  State<MerchantAppealPage> createState() => _MerchantAppealPageState();
}

class _MerchantAppealPageState extends State<MerchantAppealPage> {
  List<AfterSale> _afterSales = [];
  List<Review> _badReviews = [];
  Map<String, Map<String, dynamic>> _appeals = {}; // "type:id" -> appeal
  bool _loaded = false;

  /// 非空 = 上一次加载失败。空页面和加载失败在这一页含义完全相反
  String _error = '';

  @override
  void initState() {
    super.initState();
    _load();
  }

  /// 三个请求先全部发出去再逐个 await —— 互不依赖,不必排队
  Future<void> _load() async {
    final afterSalesF = widget.api.myAfterSales();
    final reviewsF = widget.api.myReviews();
    final appealsF = widget.api.myAppeals();
    final g = SzGather();
    final afterSales = await g.take(afterSalesF);
    final reviews = await g.take(reviewsF);
    final appeals = await g.take(appealsF);

    if (!mounted) return;
    // 拉失败时**不能**装作加载成功 —— 这一页空着的含义是「没有可申诉的」,
    // 商家会当成判责已经翻篇,而实际上是没拉到
    if (g.failed) {
      setState(() {
        _error = g.message;
        _loaded = true;
      });
      return;
    }
    setState(() {
      _error = '';
      // 只列可能需要申诉的:已同意退款且非骑手责的售后 / 3 星及以下差评
      _afterSales = afterSales!
          .where((a) => a.status == 'accepted' && a.fault != 'rider')
          .toList();
      _badReviews = reviews!.where((r) => r.merchantRating <= 3).toList();
      _appeals = {
        for (final a in appeals!) '${a['target_type']}:${a['target_id']}': a,
      };
      _loaded = true;
    });
  }

  Future<void> _appeal(String targetType, int targetId, String title) async {
    final controller = TextEditingController();
    final ok = await showDialog<bool>(
      context: context,
      builder: (context) => SzDialog(
        title: Text('申诉:$title'),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text('说明理由,平台人工复核。申诉成立:售后恢复你的净额(用户退款平台承担);'
                '差评隐藏且不计入评分。',
                style: TextStyle(fontSize: 13)),
            const SizedBox(height: 12),
            TextField(
              controller: controller,
              maxLength: 200,
              maxLines: 3,
              decoration: const InputDecoration(
                  labelText: '申诉理由(必填)', border: OutlineInputBorder()),
            ),
          ],
        ),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(context, false),
              child: const Text('取消')),
          FilledButton(
              onPressed: () => Navigator.pop(context, true),
              child: const Text('提交申诉')),
        ],
      ),
    );
    if (ok != true || !mounted) return;
    try {
      await widget.api.submitAppeal(
          targetType: targetType,
          targetId: targetId,
          reason: controller.text.trim());
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('申诉已提交,平台会尽快复核并推送结果')));
      _load();
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(e.toString())));
    }
  }

  Widget _appealTrailing(String targetType, int targetId, String title) {
    final appeal = _appeals['$targetType:$targetId'];
    if (appeal != null) {
      final label = switch (appeal['status'] as String) {
        'open' => '复核中',
        'upheld' => '维持原判',
        'overturned' => '申诉成立',
        _ => appeal['status'] as String,
      };
      return Text(label, style: const TextStyle(fontSize: 12));
    }
    return OutlinedButton(
      onPressed: () => _appeal(targetType, targetId, title),
      child: const Text('申诉'),
    );
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return SzPageScaffold(
      appBar: AppBar(title: const Text('判责申诉')),
      body: !_loaded
          ? const Center(child: CircularProgressIndicator())
          : _error.isNotEmpty
          ? SzError(error: _error, onRetry: _load)
          : RefreshIndicator(
              onRefresh: _load,
              child: ListView(
                padding: const EdgeInsets.all(12),
                children: [
                  // 时限放**进门第一眼**。
                  //
                  // 它原来在这一页的最底下,而商家是从店铺页的入口进来的 ——
                  // 那个入口的 hint 写着「72 小时内申诉」,等于时限在入口上
                  // 先说了一遍。入口收进图标网格之后格子里放不下副标题,
                  // 这句话就只剩这一处了:**错过窗口就再也申诉不了**,
                  // 不能让它排在两个列表后面。
                  Container(
                    margin: const EdgeInsets.only(bottom: 12),
                    padding: const EdgeInsets.all(kCardPad),
                    decoration: BoxDecoration(
                      color: theme.colorScheme.secondaryContainer,
                      borderRadius: BorderRadius.circular(kRadiusMd),
                    ),
                    child: Row(children: [
                      Icon(Icons.timer_outlined,
                          size: 18, color: theme.colorScheme.onSecondaryContainer),
                      const SizedBox(width: 10),
                      Expanded(
                        child: Text(
                            '申诉窗口为裁决后 72 小时;每个目标只能申诉一次,'
                            '复核结果会推送给你。',
                            style: TextStyle(
                                fontSize: kFontNote,
                                height: 1.5,
                                color: theme.colorScheme.onSecondaryContainer)),
                      ),
                    ]),
                  ),
                  Text('已退款的售后(判商家责任)', style: theme.textTheme.titleSmall),
                  if (_afterSales.isEmpty)
                    const Padding(
                        padding: EdgeInsets.all(12),
                        child: Text('没有判商家责任的售后记录')),
                  for (final a in _afterSales)
                    Card(
                      child: ListTile(
                        dense: true,
                        title: Text('订单#${a.orderNo.isEmpty ? a.id : a.orderNo.substring(a.orderNo.length - 6)}'
                            ' · ${yuan(a.totalCents)}'),
                        subtitle: Text(a.reason,
                            maxLines: 2, overflow: TextOverflow.ellipsis),
                        trailing:
                            _appealTrailing('after_sale', a.id, '售后判责'),
                      ),
                    ),
                  const SizedBox(height: 16),
                  Text('差评(3 星及以下)', style: theme.textTheme.titleSmall),
                  if (_badReviews.isEmpty)
                    const Padding(
                        padding: EdgeInsets.all(12), child: Text('没有差评')),
                  for (final r in _badReviews)
                    Card(
                      child: ListTile(
                        dense: true,
                        title: Text('${r.merchantRating} 星'
                            '${r.hidden ? ' · 已隐藏' : ''}'),
                        subtitle: Text(r.comment.isEmpty ? '(无文字)' : r.comment,
                            maxLines: 2, overflow: TextOverflow.ellipsis),
                        trailing: r.hidden
                            ? null
                            : _appealTrailing('review', r.id, '差评'),
                      ),
                    ),
                ],
              ),
            ),
    );
  }
}
