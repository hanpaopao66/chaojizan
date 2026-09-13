import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';

/// UP 主空间(#366)。
class SpacePage extends StatefulWidget {
  const SpacePage({super.key, required this.userId});

  final int userId;

  @override
  State<SpacePage> createState() => _SpacePageState();
}

class _SpacePageState extends State<SpacePage> {
  @override
  Widget build(BuildContext context) {
    return SzPageScaffold(appBar: AppBar(title: const Text('空间')), body: Center(child: Text('${widget.userId}')));
  }
}
