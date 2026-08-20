import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';

/// 平台规则中心。
///
/// 页面本身没什么特别的,特别的是**数字的来源**:服务端从代码里的常量
/// 算出来下发,不是后台可编辑的运营文案。公示"30 天 3 起自动停业"、
/// 代码里写的却是 5 起 —— 这种事只要可能发生就迟早会发生。
class MerchantRulesPage extends StatefulWidget {
  const MerchantRulesPage({super.key, required this.api});

  final ApiClient api;

  @override
  State<MerchantRulesPage> createState() => _MerchantRulesPageState();
}

class _MerchantRulesPageState extends State<MerchantRulesPage> {
  Map<String, dynamic>? _rules;
  String? _error;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final r = await widget.api.merchantRules();
      if (mounted) setState(() => _rules = r);
    } catch (e) {
      if (mounted) {
        setState(() => _error = e is ApiException ? e.message : '$e');
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    final rules = _rules;
    return SzPageScaffold(
      appBar: AppBar(title: const Text('平台规则')),
      body: _error != null
          ? SzError(error: _error, onRetry: _load)
          : rules == null
              ? const Center(child: CircularProgressIndicator())
              : ListView(
                  padding: const EdgeInsets.fromLTRB(
                      kPagePad, 12, kPagePad, 32),
                  children: [
                    for (final section
                        in (rules['sections'] as List? ?? const []))
                      Padding(
                        padding: const EdgeInsets.only(bottom: 14),
                        child: SzCard(
                          child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Text(section['title'] as String? ?? '',
                                    style: TextStyle(
                                        fontWeight: FontWeight.w600,
                                        color: sz.ink)),
                                const SizedBox(height: 8),
                                for (final item
                                    in (section['items'] as List? ?? const []))
                                  Padding(
                                    padding:
                                        const EdgeInsets.only(bottom: 6),
                                    child: Row(
                                        crossAxisAlignment:
                                            CrossAxisAlignment.start,
                                        children: [
                                          Text('· ',
                                              style: TextStyle(
                                                  color: sz.inkMuted)),
                                          Expanded(
                                            child: Text('$item',
                                                style: TextStyle(
                                                    fontSize: 13,
                                                    height: 1.6,
                                                    color: sz.ink)),
                                          ),
                                        ]),
                                  ),
                              ]),
                        ),
                      ),
                    Text('${rules['note']}',
                        style: TextStyle(
                            fontSize: 11.5, height: 1.6, color: sz.inkMuted)),
                  ],
                ),
    );
  }
}
