import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';

/// 店铺证照公示(亮照经营,电商法要求)。
///
/// 图由服务端加水印后公开下发 —— 公示是义务,但公示出去的图
/// 不该能被原样拿去冒充资质。老库存量商家可能只有证号没有图。
class ShopLicensesPage extends StatefulWidget {
  const ShopLicensesPage({
    super.key,
    required this.api,
    required this.merchantId,
    required this.shopName,
  });

  final ApiClient api;
  final int merchantId;
  final String shopName;

  @override
  State<ShopLicensesPage> createState() => _ShopLicensesPageState();
}

class _ShopLicensesPageState extends State<ShopLicensesPage> {
  List<Map<String, dynamic>>? _items;
  String? _error;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final items = await widget.api.merchantLicenses(widget.merchantId);
      if (mounted) setState(() => _items = items);
    } catch (e) {
      if (mounted) {
        setState(() => _error = e is ApiException ? e.message : '$e');
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    final items = _items;
    return Scaffold(
      appBar: AppBar(title: const Text('证照信息')),
      body: _error != null
          ? Center(
              child: Column(mainAxisSize: MainAxisSize.min, children: [
              Text(_error!),
              const SizedBox(height: 12),
              FilledButton(onPressed: _load, child: const Text('重试')),
            ]))
          : items == null
              ? const Center(child: CircularProgressIndicator())
              : ListView(
                  padding: const EdgeInsets.all(16),
                  children: [
                    Text(widget.shopName,
                        style: Theme.of(context).textTheme.titleMedium),
                    const SizedBox(height: 4),
                    Text('以下证照已由平台人工审核;公示图带水印,仅供查验',
                        style:
                            TextStyle(fontSize: 12, color: sz.inkMuted)),
                    const SizedBox(height: 12),
                    if (items.isEmpty)
                      const Padding(
                          padding: EdgeInsets.all(24),
                          child: Center(child: Text('证照信息整理中'))),
                    for (final item in items) ...[
                      Card(
                        child: Padding(
                          padding: const EdgeInsets.all(12),
                          child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Text(item['label'] as String? ?? '',
                                    style: const TextStyle(
                                        fontWeight: FontWeight.w600)),
                                if ((item['no'] as String? ?? '')
                                    .isNotEmpty) ...[
                                  const SizedBox(height: 4),
                                  Text('证号:${item['no']}',
                                      style: TextStyle(
                                          fontSize: 13, color: sz.inkMuted)),
                                ],
                                if ((item['image_url'] as String? ?? '')
                                    .isNotEmpty) ...[
                                  const SizedBox(height: 8),
                                  ClipRRect(
                                    borderRadius: BorderRadius.circular(8),
                                    child: Image(
                                      image: szNetImage(widget.api.resolveUrl(
                                          item['image_url'] as String)),
                                      width: double.infinity,
                                      fit: BoxFit.contain,
                                      errorBuilder: (_, __, ___) => Padding(
                                        padding: const EdgeInsets.all(16),
                                        child: Text('证照图暂时加载不出来',
                                            style: TextStyle(
                                                fontSize: 12,
                                                color: sz.inkFaint)),
                                      ),
                                    ),
                                  ),
                                ],
                              ]),
                        ),
                      ),
                      const SizedBox(height: 8),
                    ],
                  ],
                ),
    );
  }
}
