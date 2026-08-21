import 'package:flutter_test/flutter_test.dart';
import 'package:superz_shared/superz_shared.dart';

/// 一个假的「连接器」:每一轮把 onError 和 onDone **都**触发一遍 ——
/// 这正是 `web_socket_channel` 连不上时的真实行为(先 addError 再 close),
/// 也正是原来那个 bug 的触发条件。
class _FakeSocket {
  _FakeSocket(this.policy);

  final ReconnectPolicy policy;

  /// 一共发起过多少次连接。指数爆炸就体现在这个数上
  int connects = 0;

  /// 每一次排队的重连等了多久
  final List<Duration> delays = [];

  /// 排队中的重连次数(定时器数量)。真实代码里每个都是一个 Timer
  int queued = 0;

  void connect() {
    if (!policy.beginConnect()) return; // 防重入
    connects++;
  }

  /// 一次失败的完整回调序列
  void failOnce() {
    _onEvent(); // onError
    _onEvent(); // onDone —— 紧接着一定会来
  }

  void _onEvent() {
    final delay = policy.schedule();
    if (delay == null) return; // 这次断线已经排过了
    delays.add(delay);
    queued++;
  }

  /// 定时器到点:把排队的重连全部执行
  void fireTimers() {
    final n = queued;
    queued = 0;
    for (var i = 0; i < n; i++) {
      connect();
    }
  }
}

void main() {
  group('ReconnectPolicy', () {
    test('onError + onDone 连着来,只排一次重连', () {
      final policy = ReconnectPolicy();
      final sock = _FakeSocket(policy);

      sock.connect();
      sock.failOnce();

      expect(sock.queued, 1, reason: '两个回调只能排出一个重连');
    });

    test('连续失败 10 轮,发起的连接数是线性的(不是 2^n)', () {
      final policy = ReconnectPolicy();
      final sock = _FakeSocket(policy);

      sock.connect(); // 第 1 次
      for (var round = 0; round < 10; round++) {
        sock.failOnce();
        sock.fireTimers();
      }

      // 线性:每轮恰好一条。旧代码这里是 2^10 = 1024 条并发连接
      expect(sock.connects, 11);
      expect(sock.queued, 0);
    });

    test('旧写法(不判重)会指数爆炸 —— 作为对照', () {
      // 不走 policy,直接模拟「onError 排一个 + onDone 排一个」
      var pending = 1;
      var connects = 0;
      for (var round = 0; round < 10; round++) {
        connects += pending;
        pending *= 2; // 每条连接的两个回调各排一个重连
      }
      expect(connects, greaterThan(1000), reason: '这就是修之前的行为:10 轮之后上千条连接');
    });

    test('退避:5s → 10s → 20s → 40s → 封顶 60s', () {
      final policy = ReconnectPolicy();
      final sock = _FakeSocket(policy);

      sock.connect();
      for (var round = 0; round < 6; round++) {
        sock.failOnce();
        sock.fireTimers();
      }

      expect(sock.delays, const [
        Duration(seconds: 5),
        Duration(seconds: 10),
        Duration(seconds: 20),
        Duration(seconds: 40),
        Duration(seconds: 60),
        Duration(seconds: 60),
      ]);
    });

    test('连上之后退避归零', () {
      final policy = ReconnectPolicy();
      final sock = _FakeSocket(policy);

      sock.connect();
      for (var round = 0; round < 3; round++) {
        sock.failOnce();
        sock.fireTimers();
      }
      expect(sock.delays.last, const Duration(seconds: 20));

      policy.onConnected(); // 握手成功
      sock.failOnce(); // 之后又断了
      expect(sock.delays.last, const Duration(seconds: 5),
          reason: '成功连过一次,下一次断线要从 5 秒重新开始');
    });

    test('重入被挡住:已经在连的时候再调 connect 不会多开一条', () {
      final policy = ReconnectPolicy();
      final sock = _FakeSocket(policy);

      sock.connect();
      sock.connect();
      sock.connect();

      expect(sock.connects, 1);
    });

    test('schedule 之后 connecting 归位,重连能真正连上', () {
      final policy = ReconnectPolicy();
      expect(policy.beginConnect(), isTrue);
      expect(policy.connecting, isTrue);

      policy.schedule();
      expect(policy.connecting, isFalse);
      expect(policy.pending, isTrue);

      expect(policy.beginConnect(), isTrue, reason: '排队的重连必须连得动');
      expect(policy.pending, isFalse);
    });

    test('reset 回到初始状态', () {
      final policy = ReconnectPolicy();
      policy.beginConnect();
      policy.schedule();
      policy.reset();

      expect(policy.attempt, 0);
      expect(policy.pending, isFalse);
      expect(policy.connecting, isFalse);
      expect(policy.nextDelay, const Duration(seconds: 5));
    });
  });
}
