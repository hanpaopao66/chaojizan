/// 平台公告横幅(三端共用):运营发通知不用发版。
///
/// 启动时拉一次 /announcements,展示第一条未读过的;
/// 用户点关闭后记住 id(本地),同一条不再打扰。
/// 拉取失败静默隐藏 —— 公告是锦上添花,不能变成打扰。
library;

import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'api_client.dart';
import 'brand.dart';
import 'models.dart';

class AnnouncementBanner extends StatefulWidget {
  const AnnouncementBanner(
      {super.key, required this.api, required this.audience});

  /// user / merchant / rider
  final String audience;
  final ApiClient api;

  @override
  State<AnnouncementBanner> createState() => _AnnouncementBannerState();
}

class _AnnouncementBannerState extends State<AnnouncementBanner> {
  static const _kDismissedKey = 'dismissed_announcement_ids';

  PlatformAnnouncement? _current;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final list = await widget.api.announcements(widget.audience);
      if (list.isEmpty || !mounted) return;
      final prefs = await SharedPreferences.getInstance();
      final dismissed = prefs.getStringList(_kDismissedKey) ?? const [];
      final fresh =
          list.where((a) => !dismissed.contains('${a.id}')).toList();
      if (fresh.isEmpty || !mounted) return;
      setState(() => _current = fresh.first);
    } catch (_) {
      // 静默:拉不到公告就不展示
    }
  }

  Future<void> _dismiss() async {
    final ann = _current;
    if (ann == null) return;
    setState(() => _current = null);
    final prefs = await SharedPreferences.getInstance();
    final dismissed = prefs.getStringList(_kDismissedKey) ?? [];
    // 只留最近 20 条已读记录,防止无限膨胀
    final next = [...dismissed, '${ann.id}'];
    await prefs.setStringList(
        _kDismissedKey, next.sublist(next.length > 20 ? next.length - 20 : 0));
  }

  @override
  Widget build(BuildContext context) {
    final ann = _current;
    if (ann == null) return const SizedBox.shrink();
    return AnimatedSize(
      duration: const Duration(milliseconds: 200),
      child: Container(
        margin: const EdgeInsets.fromLTRB(16, 8, 16, 4),
        padding: const EdgeInsets.fromLTRB(12, 10, 4, 10),
        decoration: BoxDecoration(
          color: kPromoAmber.withValues(alpha: .08),
          borderRadius: BorderRadius.circular(12),
          border: Border.all(color: kPromoAmber.withValues(alpha: .25)),
        ),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Padding(
              padding: EdgeInsets.only(top: 1),
              child: Icon(Icons.campaign_rounded, size: 18, color: kPromoAmber),
            ),
            const SizedBox(width: 8),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(ann.title,
                      style: const TextStyle(
                          fontSize: 13,
                          fontWeight: FontWeight.w600,
                          color: kPromoAmber)),
                  if (ann.content.isNotEmpty)
                    Padding(
                      padding: const EdgeInsets.only(top: 2),
                      child: Text(ann.content,
                          style: TextStyle(
                              fontSize: 12,
                              height: 1.4,
                              color: Theme.of(context)
                                  .colorScheme
                                  .onSurfaceVariant)),
                    ),
                ],
              ),
            ),
            IconButton(
              onPressed: _dismiss,
              icon: const Icon(Icons.close_rounded, size: 16),
              color: Theme.of(context).colorScheme.outline,
              visualDensity: VisualDensity.compact,
              tooltip: '关闭',
            ),
          ],
        ),
      ),
    );
  }
}
