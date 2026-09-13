import 'dart:async';

import 'package:flutter/widgets.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:superz_shared/superz_shared.dart';

import '../video/api.dart';
import '../video/nav.dart' show videoApi;
import '../video/notify/notifications_page.dart' show videoNotifyBadge, videoNotifyUnreadKinds;
import '../video/notify/notify_format.dart';
import '../video/notify/notify_prefs.dart';
import 'store.dart';

/// 「消息」底栏角标里,聊天会话以外的那几行各算一个:平台服务号、每一单的订单群、视频互动。
/// 和聊天会话一样数「有未读的行」,不数条数;静音了的视频互动不算。
final ValueNotifier<int> chatExtraBadge = ValueNotifier<int>(0);

/// 平台服务号里的一条:就是一条平台公告(`GET /announcements`)。
class ServiceNotice {
  const ServiceNotice({required this.id, required this.title, required this.content, this.createdAt});

  factory ServiceNotice.fromJson(Object? j) {
    final m = j is Map ? j.cast<String, dynamic>() : const <String, dynamic>{};
    return ServiceNotice(
      id: (m['id'] as num?)?.toInt() ?? 0,
      title: '${m['title'] ?? ''}',
      content: '${m['content'] ?? ''}',
      createdAt: DateTime.tryParse('${m['created_at'] ?? ''}')?.toLocal(),
    );
  }

  final int id;
  final String title;
  final String content;
  final DateTime? createdAt;
}

/// 订单群里最后一条(`GET /orders/chat-threads` 的 `last`)。
class OrderThreadLast {
  const OrderThreadLast({required this.from, required this.senderName, required this.kind, required this.content, this.createdAt});

  factory OrderThreadLast.fromJson(Map<String, dynamic> m) => OrderThreadLast(
        from: '${m['from'] ?? ''}',
        senderName: '${m['sender_name'] ?? ''}',
        kind: '${m['kind'] ?? 'text'}',
        content: '${m['content'] ?? ''}',
        createdAt: DateTime.tryParse('${m['created_at'] ?? ''}')?.toLocal(),
      );

  /// customer / merchant / rider
  final String from;
  final String senderName;
  final String kind;
  final String content;
  final DateTime? createdAt;
}

/// 一单一个群:你、商家、骑手。列表里一行,点进去是这一单的对话。
class OrderThread {
  const OrderThread({
    required this.orderNo,
    required this.title,
    this.merchantName = '',
    this.riderName = '',
    this.status = '',
    this.statusLabel = '',
    this.last,
    this.unread = 0,
    this.readonly = false,
    this.updatedAt,
  });

  factory OrderThread.fromJson(Object? j) {
    final m = j is Map ? j.cast<String, dynamic>() : const <String, dynamic>{};
    final last = m['last'];
    return OrderThread(
      orderNo: '${m['order_no'] ?? ''}',
      title: '${m['title'] ?? ''}',
      merchantName: '${m['merchant_name'] ?? ''}',
      riderName: '${m['rider_name'] ?? ''}',
      status: '${m['status'] ?? ''}',
      statusLabel: '${m['status_label'] ?? ''}',
      last: last is Map ? OrderThreadLast.fromJson(last.cast<String, dynamic>()) : null,
      unread: (m['unread'] as num?)?.toInt() ?? 0,
      readonly: m['readonly'] == true,
      updatedAt: DateTime.tryParse('${m['updated_at'] ?? ''}')?.toLocal(),
    );
  }

  final String orderNo;
  final String title;
  final String merchantName;
  final String riderName;
  final String status;
  final String statusLabel;
  final OrderThreadLast? last;
  final int unread;
  final bool readonly;
  final DateTime? updatedAt;

  /// 还在进行的单:置顶(设计稿里那一行垫着置顶的底色)。送完、归档了的就和别的会话一起按时间排
  bool get active => !readonly && status != 'completed' && status != 'cancelled';

  DateTime get time => last?.createdAt ?? updatedAt ?? DateTime.fromMillisecondsSinceEpoch(0);
}

/// 「消息」列表里除了聊天会话以外的几行的数据:平台服务号(公告)、订单群、视频互动的最近一条。
///
/// 设计稿 A 的「万物皆会话」:原来列表顶上那三条固定入口(通知 / 订单消息 / 互动消息)
/// 变成和聊天一样的会话行。它们的数据来自三套现有接口,不在聊天的会话表里,所以单独放在这儿:
/// 登录时由首页启动(底栏角标要准,不能等点进「消息」才拉),会话列表打开 / 下拉时再刷新。
class ChatExtras extends ChangeNotifier with WidgetsBindingObserver {
  ChatExtras._();

  static final ChatExtras instance = ChatExtras._();

  /// 和原来消息中心记「看过的最新公告」同一个键:改版前看过的,改版后不会又变成未读
  static const _kSeen = 'msg_seen_announcement_id';

  ApiClient? _api;
  bool _wired = false;
  Timer? _poll;
  Timer? _botDebounce;
  StreamSubscription<({String type, Map<String, dynamic> data})>? _events;

  List<ServiceNotice> notices = const [];
  int seenNoticeId = 0;

  List<OrderThread> orderThreads = const [];

  /// 视频互动最近的一条(四类里最新的那条),给列表那一行做预览和排序
  NotifyItem? botLast;

  /// 视频功能关着(503):这一行不显示
  bool botOff = false;
  final Map<String, NotifyItem?> _botByKind = {};

  int get noticeUnread => notices.where((n) => n.id > seenNoticeId).length;

  /// 首页在登录态变了时调;没登录也调(平台公告不用登录)。
  Future<void> start(ApiClient api) async {
    _api = api;
    if (!_wired) {
      _wired = true;
      WidgetsBinding.instance.addObserver(this);
      videoNotifyUnreadKinds.addListener(_recount);
      VideoNotifyPrefs.instance.addListener(_recount);
      _events = ChatStore.instance.userEvents.stream.listen((e) {
        if (e.type != 'notify') return;
        final kind = e.data['kind'];
        if (kind is! String || kind.isEmpty) return;
        _botDebounce?.cancel();
        _botDebounce = Timer(const Duration(milliseconds: 400), () => refreshBot(kind: kind));
      });
    }
    try {
      final p = await SharedPreferences.getInstance();
      seenNoticeId = p.getInt(_kSeen) ?? 0;
    } catch (_) {}
    if (!api.isLoggedIn) _clearPersonal();
    await Future.wait([refreshNotices(), if (api.isLoggedIn) refreshOrders()]);
  }

  /// 退出登录:订单群、视频互动是这个人的,清掉;平台公告是公开的,留着。
  void stop() {
    _clearPersonal();
    notifyListeners();
    _recount();
  }

  void _clearPersonal() {
    _poll?.cancel();
    _poll = null;
    orderThreads = const [];
    botLast = null;
    _botByKind.clear();
  }

  Future<void> refresh() => Future.wait([refreshNotices(), refreshOrders(), refreshBot()]);

  Future<void> refreshNotices() async {
    final api = _api;
    if (api == null) return;
    try {
      final data = await api.requestJson('GET', '/announcements', query: {'audience': 'user'});
      final list = [for (final x in (data is List ? data : const [])) ServiceNotice.fromJson(x)]
        ..sort((a, b) => b.id.compareTo(a.id));
      notices = list;
      notifyListeners();
      _recount();
    } catch (_) {
      // 拉不到就先按上一次的显示
    }
  }

  /// 打开服务号 = 看过了(和原来点开消息中心一样)
  Future<void> markNoticesSeen() async {
    if (notices.isEmpty) return;
    final top = notices.first.id;
    if (top <= seenNoticeId) return;
    seenNoticeId = top;
    notifyListeners();
    _recount();
    try {
      final p = await SharedPreferences.getInstance();
      await p.setInt(_kSeen, top);
    } catch (_) {}
  }

  Future<void> refreshOrders() async {
    final api = _api;
    if (api == null || !api.isLoggedIn) return;
    try {
      orderThreads = [for (final x in await api.orderChatThreads()) OrderThread.fromJson(x)];
    } on ApiException catch (e) {
      // 老服务端没有这个接口:这一段就不显示;别的错先按上一次的显示
      if (e.statusCode == 404) orderThreads = const [];
    } catch (_) {}
    notifyListeners();
    _recount();
    // 还有在送的单:一分钟看一次有没有新消息(骑手到楼下那句话不能等人自己下拉)
    final live = orderThreads.any((t) => t.active);
    if (live && _poll == null) {
      _poll = Timer.periodic(const Duration(seconds: 60), (_) => refreshOrders());
    } else if (!live) {
      _poll?.cancel();
      _poll = null;
    }
  }

  /// 视频互动最近一条。服务端只能按类拉,四类各拉第一页取最新的;[kind] 给了就只刷那一类
  /// (来了一条新的互动时)。
  Future<void> refreshBot({String? kind}) async {
    final api = _api;
    if (api == null || !api.isLoggedIn) return;
    final kinds = kind == null ? [for (final (k, _) in notifyKinds) k] : [kind];
    try {
      final pages = await Future.wait([for (final k in kinds) videoApi.notifications(k)]);
      for (var i = 0; i < kinds.length; i++) {
        final items = pages[i]['items'];
        _botByKind[kinds[i]] = items is List && items.isNotEmpty ? NotifyItem.fromJson(items.first) : null;
      }
      botOff = false;
    } catch (e) {
      if (VideoApi.isOff(e)) botOff = true;
    }
    NotifyItem? newest;
    for (final n in _botByKind.values) {
      if (n != null && (newest == null || notifyTime(n).isAfter(notifyTime(newest)))) newest = n;
    }
    botLast = newest;
    notifyListeners();
  }

  void _recount() {
    var n = 0;
    if (noticeUnread > 0) n++;
    n += orderThreads.where((t) => t.unread > 0).length;
    if (_api?.isLoggedIn == true && !VideoNotifyPrefs.instance.muted && videoNotifyBadge() > 0) n++;
    if (chatExtraBadge.value != n) chatExtraBadge.value = n;
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state != AppLifecycleState.resumed) return;
    unawaited(refreshNotices());
    unawaited(refreshOrders());
  }

  @visibleForTesting
  void debugReset() {
    _clearPersonal();
    notices = const [];
    seenNoticeId = 0;
    botOff = false;
    _api = null;
    chatExtraBadge.value = 0;
  }

  @override
  void dispose() {
    _events?.cancel();
    super.dispose();
  }
}
