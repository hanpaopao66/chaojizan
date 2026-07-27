import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';

/// 住宿订单 tab(骨架,#75 完成确认/拒单/入住/离店与新单语音)。
class StayOrdersPage extends StatelessWidget {
  const StayOrdersPage({super.key, required this.api, required this.shop});

  final ApiClient api;
  final Merchant shop;

  @override
  Widget build(BuildContext context) {
    return const Center(
      child: Column(mainAxisSize: MainAxisSize.min, children: [
        Icon(Icons.receipt_long, size: 48),
        SizedBox(height: 12),
        Text('住宿订单管理即将就绪'),
      ]),
    );
  }
}
