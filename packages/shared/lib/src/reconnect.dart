/// WebSocket 断线重连的节奏控制。
///
/// ## 为什么要单独抽一个类
///
/// 商家端原来是这么写的:
///
/// ```dart
/// onError: (_) => _scheduleReconnect(),
/// onDone: _scheduleReconnect,
/// ```
///
/// 看着是两条互斥的路径,实际不是 —— `web_socket_channel` 在**连不上**的时候
/// 是先 `addError()` 再 `close()`,**两个回调必然都触发**。于是一次断线排两个
/// 重连定时器,每个定时器又各自排两个:5 秒后 2 个连接、30 秒后 64 个、
/// 一分钟后四千个。手机发烫、卡死,而这台手机是商家的听单机 —— 它卡住 = 漏单。
///
/// 而且活下来的那些连接**都还在收推送**,同一单会被播报好几遍。
///
/// 这个类把「一次断线只排一次重连」变成一个可以单测的不变式,
/// 不再依赖每个调用点自己记得判重。
///
/// ## 用法
///
/// ```dart
/// void _connectWs() {
///   if (!_reconnect.beginConnect()) return;   // 已经在连了,别重入
///   _reconnectTimer?.cancel();
///   _ws?.sink.close();                        // 旧连接先关掉
///   _ws = WebSocketChannel.connect(uri);
///   _ws!.ready.then((_) => _reconnect.onConnected());
///   _ws!.stream.listen(onMessage,
///       onError: (_) => _scheduleReconnect(), onDone: _scheduleReconnect);
/// }
///
/// void _scheduleReconnect() {
///   final delay = _reconnect.schedule();
///   if (delay == null) return;                // 这次断线已经排过了
///   _reconnectTimer?.cancel();
///   _reconnectTimer = Timer(delay, _connectWs);
/// }
/// ```
class ReconnectPolicy {
  ReconnectPolicy({
    this.first = const Duration(seconds: 5),
    this.max = const Duration(seconds: 60),
    this.factor = 2,
  });

  /// 第一次重连等多久
  final Duration first;

  /// 退避上限。封顶不能太大:商家端断太久就是漏单,
  /// 一分钟一次的重试成本可以忽略,而醒过来晚一分钟是真金白银
  final Duration max;

  /// 每失败一次乘几倍
  final int factor;

  int _attempt = 0;
  bool _pending = false;
  bool _connecting = false;

  /// 连续失败了几次(连上一次就归零)。退避档位就是它
  int get attempt => _attempt;

  /// 有一次重连已经排好队还没执行
  bool get pending => _pending;

  /// 正在连(握手还没有结果)
  bool get connecting => _connecting;

  /// 下一次该等多久(不推进状态,给 UI 显示用)
  Duration get nextDelay => _delayFor(_attempt);

  Duration _delayFor(int attempt) {
    var ms = first.inMilliseconds;
    for (var i = 0; i < attempt; i++) {
      ms *= factor;
      if (ms >= max.inMilliseconds) return max;
    }
    return Duration(milliseconds: ms);
  }

  /// 进入「正在连接」。
  ///
  /// 返回 false 表示已经有一个连接在建立中,这次调用应当**直接返回**,
  /// 别再开一条 —— 重入是并发连接的另一个来源(定时器和生命周期回调撞上)。
  bool beginConnect() {
    if (_connecting) return false;
    _connecting = true;
    _pending = false;
    return true;
  }

  /// 握手成功:退避归零。
  ///
  /// 归零的位置很重要 —— 要等**真的连上**才归零。如果在 [beginConnect] 里就归零,
  /// 那么「连不上 → 5 秒 → 又连不上 → 5 秒」会永远停在 5 秒,退避等于没做。
  void onConnected() {
    _attempt = 0;
    _connecting = false;
    _pending = false;
  }

  /// 排一次重连,返回该等的时长;返回 null 表示**这次断线已经排过了**,
  /// 调用方什么都不用做。
  ///
  /// onError 和 onDone 都调它,靠这里判重 —— 这正是原来那个 bug 的修法。
  Duration? schedule() {
    _connecting = false;
    if (_pending) return null;
    _pending = true;
    final delay = _delayFor(_attempt);
    _attempt++;
    return delay;
  }

  /// 定时器已经取消 / 页面销毁:回到初始状态
  void reset() {
    _attempt = 0;
    _pending = false;
    _connecting = false;
  }
}
