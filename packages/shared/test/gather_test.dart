import 'dart:async';

import 'package:flutter_test/flutter_test.dart';
import 'package:superz_shared/superz_shared.dart';

/// SzGather 存在的理由只有一条:**并发拉数据时别丢异常、别丢类型、别丢人话**。
/// 这三条各有一组用例。
void main() {
  test('全成功时按原类型返回,failed 为 false', () async {
    final g = SzGather();
    final a = await g.take(Future.value(1));
    final b = await g.take(Future.value('x'));
    expect(a, 1);
    expect(b, 'x');
    expect(g.failed, isFalse);
    expect(g.message, '');
  });

  test('第一个失败后,后面的 Future 仍然被 await —— 不留未处理异步错误', () async {
    // 这是它最要紧的一条。裸写 `await a; await b;` 时 a 抛异常会跳进 catch,
    // b 就没人接了 —— Flutter 会往控制台刷红,测试里直接算失败。
    // 这里用 runZonedGuarded 把"漏网的异步错误"抓出来,断言一条都没有。
    final leaked = <Object>[];
    await runZonedGuarded(() async {
      final fa = Future<int>.error(StateError('a 挂了'));
      final fb = Future<int>.error(StateError('b 也挂了'));
      final g = SzGather();
      expect(await g.take(fa), isNull);
      expect(await g.take(fb), isNull);
      expect(g.failed, isTrue);
    }, (e, _) => leaked.add(e));
    // 给未处理异步错误一个上报的机会
    await Future<void>.delayed(Duration.zero);
    expect(leaked, isEmpty, reason: '有 Future 没被 await:$leaked');
  });

  test('记住的是第一条错误,不是最后一条', () async {
    final g = SzGather();
    await g.take(Future<int>.error(ApiException(401, '登录已过期')));
    await g.take(Future<int>.error(ApiException(0, '网络不给力')));
    expect(g.message, '登录已过期');
  });

  test('ApiException 直接用它的人话,别的兜底成通用说法', () async {
    final api = SzGather();
    await api.take(Future<int>.error(ApiException(400, '这一天没有账单')));
    expect(api.message, '这一天没有账单');

    final raw = SzGather();
    await raw.take(Future<int>.error(
        // 内部异常不能直接甩给商家看,里面常带接口地址和参数
        FormatException('Unexpected character (at line 1)')));
    expect(raw.message, '加载失败,请重试');
    expect(raw.message, isNot(contains('line 1')));
  });

  test('soft 失败退回兜底值,且不让整页进错误态', () async {
    final g = SzGather();
    final ok = await g.take(Future.value('主数据'));
    final side = await g.soft(Future<String>.error(StateError('挂了')), '上一次的值');
    expect(ok, '主数据');
    expect(side, '上一次的值');
    expect(g.failed, isFalse, reason: '次要数据挂了不该把整页打回错误态');
  });

  test('soft 成功时返回真实值,不是兜底值', () async {
    final g = SzGather();
    expect(await g.soft(Future.value('新值'), '兜底'), '新值');
  });

  test('并发:先全部发出去再逐个 take,总耗时按最慢的一个算', () async {
    Future<int> slow(int ms, int v) =>
        Future.delayed(Duration(milliseconds: ms), () => v);
    final sw = Stopwatch()..start();
    final f1 = slow(120, 1);
    final f2 = slow(120, 2);
    final f3 = slow(120, 3);
    final g = SzGather();
    await g.take(f1);
    await g.take(f2);
    await g.take(f3);
    sw.stop();
    // 串行是 360ms,并发是 120ms。留足余量,只要没退化成串行就行
    expect(sw.elapsedMilliseconds, lessThan(300),
        reason: '退化成串行了,Future 大概是在 take 里才创建的');
  });
}
