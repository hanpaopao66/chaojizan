import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';

/// 视频详情页(#361)。
class VideoDetailPage extends StatefulWidget {
  const VideoDetailPage({super.key, required this.vid, this.commentId, this.partIdx});

  final String vid;
  final int? commentId;
  final int? partIdx;

  @override
  State<VideoDetailPage> createState() => _VideoDetailPageState();
}

class _VideoDetailPageState extends State<VideoDetailPage> {
  @override
  Widget build(BuildContext context) {
    return SzPageScaffold(appBar: AppBar(title: const Text('视频')), body: Center(child: Text(widget.vid)));
  }
}
