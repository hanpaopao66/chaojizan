import 'dart:async';
import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';

import '../extras.dart';
import '../ui/conv_row.dart';
import '../ui/format.dart' show dayLabel, hm, sameDay;

/// 「超级赞」平台服务号(设计稿 A「万物皆会话」):原来右上角铃铛里的消息中心,换成一个只读的会话。
///
/// 一条公告 = 一条消息,最新的在最底下;打开前没看过的上面画「以下为新消息」。
/// 服务号不收消息,所以没有输入框。内容就是现有的 `GET /announcements`:
/// 服务端只给**当前生效**的公告、最多 3 条 —— 过期的公告不在这儿留档。
class ServiceAccountPage extends StatefulWidget {
  const ServiceAccountPage({super.key});

  @override
  State<ServiceAccountPage> createState() => _ServiceAccountPageState();
}

class _ServiceAccountPageState extends State<ServiceAccountPage> {
  ChatExtras get _x => ChatExtras.instance;

  /// 打开时看到哪了:「以下为新消息」画在比它新的最旧那条上面。打开之后就记成全看过
  late final int _seenAtOpen = _x.seenNoticeId;
  bool _loading = true;

  @override
  void initState() {
    super.initState();
    _x.addListener(_on);
    unawaited(_load());
  }

  @override
  void dispose() {
    _x.removeListener(_on);
    super.dispose();
  }

  void _on() {
    if (mounted) setState(() {});
  }

  Future<void> _load() async {
    await _x.refreshNotices();
    await _x.markNoticesSeen();
    if (mounted) setState(() => _loading = false);
  }

  @override
  Widget build(BuildContext context) {
    final list = _x.notices; // 新的在前
    return SzPageScaffold(
      appBar: AppBar(
        titleSpacing: 0,
        title: const ConvHeaderTitle(
          avatar: IconAvatar(soft: true, size: 34, child: BrandMark(size: 18)),
          title: '超级赞',
          suffix: [VerifiedMark(size: 14)],
          subtitle: '平台公告',
        ),
      ),
      body: list.isEmpty
          ? (_loading ? const Center(child: CircularProgressIndicator()) : const SzEmpty(text: '暂时没有平台公告'))
          : LayoutBuilder(builder: (context, box) {
              final w = math.min(300.0, box.maxWidth - 28);
              DateTime? day(ServiceNotice n) => n.createdAt;
              // 最旧的那条没看过的:分隔线画在它上面
              final firstNew = list.lastWhere((n) => n.id > _seenAtOpen, orElse: () => const ServiceNotice(id: -1, title: '', content: ''));
              final entries = <Widget>[const _FootNote()];
              for (var i = 0; i < list.length; i++) {
                final n = list[i];
                entries.add(Padding(
                  padding: const EdgeInsets.fromLTRB(14, 5, 14, 5),
                  child: Align(alignment: Alignment.centerLeft, child: SizedBox(width: w, child: _NoticeBubble(notice: n))),
                ));
                if (n.id == firstNew.id) entries.add(const UnreadDivider());
                final older = i + 1 < list.length ? list[i + 1] : null;
                final a = day(n), b = older == null ? null : day(older);
                if (a != null && (b == null || !sameDay(a, b))) entries.add(_DayLabel(a));
              }
              return ListView.builder(
                reverse: true,
                // 没有输入条托着:最底下那句说明自己让开手机底部的手势条
                padding: EdgeInsets.only(top: 4, bottom: MediaQuery.paddingOf(context).bottom),
                itemCount: entries.length,
                itemBuilder: (_, i) => entries[i],
              );
            }),
    );
  }
}

class _NoticeBubble extends StatelessWidget {
  const _NoticeBubble({required this.notice});

  final ServiceNotice notice;

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    const radius = BorderRadius.only(
      topLeft: Radius.circular(kRadiusMd),
      topRight: Radius.circular(kRadiusMd),
      bottomRight: Radius.circular(kRadiusMd),
      bottomLeft: Radius.circular(4),
    );
    final t = notice.createdAt;
    return Container(
      padding: const EdgeInsets.fromLTRB(12, 9, 12, 8),
      decoration: BoxDecoration(color: sz.surface, borderRadius: radius, border: Border.all(color: sz.line)),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        if (notice.title.isNotEmpty)
          Text(notice.title, style: TextStyle(fontSize: kFontBodyLg, fontWeight: FontWeight.w600, color: sz.ink, height: 1.45)),
        if (notice.content.isNotEmpty)
          Padding(
            padding: EdgeInsets.only(top: notice.title.isEmpty ? 0 : 4),
            child: SelectableText(notice.content, style: TextStyle(fontSize: kFontBodyLg, color: sz.ink, height: 1.5)),
          ),
        if (t != null)
          Align(
            alignment: Alignment.centerRight,
            child: Padding(
              padding: const EdgeInsets.only(top: 2),
              child: Text(hm(t), style: szTabular(fontSize: kFontMicro, color: sz.inkMuted)),
            ),
          ),
      ]),
    );
  }
}

class _FootNote extends StatelessWidget {
  const _FootNote();

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(14, 10, 14, 12),
      child: Text('这里只发平台公告,只能看、不能回复。订单的进度和对话在各自的订单群里。',
          style: TextStyle(fontSize: kFontMicro, color: Theme.of(context).sz.inkMuted, height: 1.7)),
    );
  }
}

class _DayLabel extends StatelessWidget {
  const _DayLabel(this.day);

  final DateTime day;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(top: 10, bottom: 4),
      child: Center(
        child: Text(dayLabel(day), style: TextStyle(fontSize: kFontMicro, color: Theme.of(context).sz.inkMuted)),
      ),
    );
  }
}
