import 'dart:async';
import 'dart:convert';
import 'dart:math';

import 'package:flutter/widgets.dart';
import 'package:web_socket_channel/web_socket_channel.dart';

import 'store.dart';

/// 实时连接 `/ws/v2`(DEV-PROMPTS-40 §5.3)。
///
/// - 连上之后第一帧发 auth(**token 不放 URL**);
/// - 25 秒一次 ping;60 秒没收到任何东西就当断了;
/// - 断了按 1、2、4 … 30 秒退避重连,重连上先补齐(ChatStore.sync);
/// - App 进后台发 `state: foreground=false` —— 后台的连接不算在线,新消息要走推送。
class ChatRealtime with WidgetsBindingObserver {
  ChatRealtime(this.store);

  final ChatStore store;

  WebSocketChannel? _ch;
  StreamSubscription? _sub;
  Timer? _ping;
  Timer? _retry;
  Timer? _watchdog;
  int _attempt = 0;
  bool _running = false;
  bool _foreground = true;
  DateTime _lastFrame = DateTime.now();

  /// 通话信令等其他模块的帧(#354)
  final List<void Function(Map<String, dynamic>)> _listeners = [];

  void addListener(void Function(Map<String, dynamic>) f) => _listeners.add(f);
  void removeListener(void Function(Map<String, dynamic>) f) => _listeners.remove(f);

  void onOtherFrame(Map<String, dynamic> f) {
    for (final l in [..._listeners]) {
      l(f);
    }
  }

  void start() {
    if (_running) return;
    _running = true;
    WidgetsBinding.instance.addObserver(this);
    _connect();
  }

  void stop() {
    _running = false;
    WidgetsBinding.instance.removeObserver(this);
    _teardown();
    _retry?.cancel();
    _attempt = 0;
  }

  void _teardown() {
    _ping?.cancel();
    _watchdog?.cancel();
    _sub?.cancel();
    _sub = null;
    try {
      _ch?.sink.close();
    } catch (_) {}
    _ch = null;
  }

  void _connect() {
    if (!_running || !store.started) return;
    final token = store.client.token;
    if (token == null) return;
    store.onConnState(ConnState.connecting);
    final uri = Uri.parse('${store.client.wsBaseUrl}/ws/v2');
    try {
      _ch = WebSocketChannel.connect(uri);
    } catch (_) {
      _scheduleRetry();
      return;
    }
    // 握手失败时错误同时走 ready 和 stream:重连靠下面 stream 的 onError / onDone;
    // ready 这边也得接住,不然断网时每次重连失败都是一条「未处理的异常」
    unawaited(_ch!.ready.then((_) {}, onError: (Object _) {}));
    _ch!.sink.add(jsonEncode({
      't': 'auth',
      'token': token,
      'device': 'user-app',
      'app': 'user',
      'foreground': _foreground,
    }));
    _lastFrame = DateTime.now();
    _sub = _ch!.stream.listen(_onData, onDone: _onClosed, onError: (_) => _onClosed());
    _ping = Timer.periodic(const Duration(seconds: 25), (_) => send({'t': 'ping'}));
    _watchdog = Timer.periodic(const Duration(seconds: 10), (_) {
      if (DateTime.now().difference(_lastFrame) > const Duration(seconds: 60)) _onClosed();
    });
  }

  void _onData(dynamic raw) {
    _lastFrame = DateTime.now();
    Map<String, dynamic> f;
    try {
      f = (jsonDecode(raw as String) as Map).cast<String, dynamic>();
    } catch (_) {
      return;
    }
    if (f['t'] == 'ready') {
      _attempt = 0;
      store.onConnState(ConnState.online);
      if (store.viewing != null) send({'t': 'view', 'chat_id': store.viewing});
      store.onReady((f['user_pts'] as num?)?.toInt() ?? 0);
      return;
    }
    if (f['t'] == 'pong') return;
    store.handleFrame(f);
  }

  void _onClosed() {
    if (_ch == null) return;
    _teardown();
    store.onConnState(ConnState.offline);
    _scheduleRetry();
  }

  void _scheduleRetry() {
    if (!_running) return;
    _retry?.cancel();
    final secs = min(30, 1 << min(_attempt, 5));
    _attempt++;
    // 退避加抖动(0.5–1.5 倍):服务端一重启,所有人同一秒断线;不抖的话大家又在同一秒一起重连,
    // 一波一波砸在 1、2、4、8 秒上(压测里 2000 条同时重连有 5% 握手超时)
    final ms = (secs * 1000 * (0.5 + _jitter.nextDouble())).round();
    _retry = Timer(Duration(milliseconds: ms), _connect);
  }

  static final _jitter = Random();

  /// 网络恢复、回到前台时立刻重连,不等退避计时器
  void reconnectNow() {
    if (!_running) return;
    if (_ch != null) return;
    _retry?.cancel();
    _attempt = 0;
    _connect();
  }

  bool send(Map<String, dynamic> frame) {
    final ch = _ch;
    if (ch == null) return false;
    try {
      ch.sink.add(jsonEncode(frame));
      return true;
    } catch (_) {
      return false;
    }
  }

  final Map<int, DateTime> _lastTyping = {};

  /// 正在输入 / 录音 / 上传(同一个会话 3 秒最多发一次,和服务端的节流一致)
  void typing(int chatId, [String action = 'typing']) {
    final now = DateTime.now();
    final last = _lastTyping[chatId];
    if (action != 'cancel' && last != null && now.difference(last).inMilliseconds < 3000) return;
    _lastTyping[chatId] = now;
    send({'t': 'typing', 'chat_id': chatId, 'action': action});
  }

  void view(int? chatId) => send({'t': 'view', 'chat_id': chatId});

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    final fg = state == AppLifecycleState.resumed;
    if (fg == _foreground) return;
    _foreground = fg;
    send({'t': 'state', 'foreground': fg});
    if (fg) {
      reconnectNow();
      store.sync();
    }
  }
}
