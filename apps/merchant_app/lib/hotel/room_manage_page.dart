import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';

/// 房型房价 tab(骨架,#74 完成房型管理与房价房态日历)。
class RoomManagePage extends StatelessWidget {
  const RoomManagePage({super.key, required this.api});

  final ApiClient api;

  @override
  Widget build(BuildContext context) {
    return const Center(
      child: Column(mainAxisSize: MainAxisSize.min, children: [
        Icon(Icons.bed_outlined, size: 48),
        SizedBox(height: 12),
        Text('房型与房价房态管理即将就绪'),
      ]),
    );
  }
}
