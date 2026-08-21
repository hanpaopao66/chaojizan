import 'dart:async';
import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:superz_shared/superz_shared.dart';

/// header 立刻回来,**body 永远不来**。
///
/// 这不是编出来的场景:弱网切换基站、代理半死、服务端写了一半卡住,
/// 都是这个样子。原来的代码只给 `request.send()` 加了超时(只管到 header),
/// 于是这条请求**永远不 resolve** —— 上层 `finally` 里的
/// `_grabbing.remove(...)` / `_acting = false` 永远不执行,
/// 「抢单」按钮永久停在「抢单中…」,不重启 App 这一单再也接不了。
class _StalledBodyClient extends http.BaseClient {
  final controllers = <StreamController<List<int>>>[];

  /// 底层连接有没有被掐掉。超时之后必须为 true,
  /// 否则这条 socket 会一直挂在连接池里等一个不会来的字节
  bool get cancelled => controllers.every((c) => !c.hasListener);

  @override
  Future<http.StreamedResponse> send(http.BaseRequest request) async {
    final controller = StreamController<List<int>>();
    controllers.add(controller);
    return http.StreamedResponse(controller.stream, 200);
  }
}

/// 正常回一份 JSON,并把收到的请求头记下来
class _EchoClient extends http.BaseClient {
  final headers = <String, String>{};

  @override
  Future<http.StreamedResponse> send(http.BaseRequest request) async {
    headers.addAll(request.headers);
    final body = utf8.encode(jsonEncode({
      'balance_cents': 0,
      'total_earned_cents': 0,
      'pending_withdrawal_cents': 0,
      'withdrawn_cents': 0,
    }));
    return http.StreamedResponse(Stream.value(body), 200);
  }
}

/// header 回来了,body 只发了一半就断
class _BrokenBodyClient extends http.BaseClient {
  @override
  Future<http.StreamedResponse> send(http.BaseRequest request) async {
    final controller = StreamController<List<int>>();
    controller.add(utf8.encode('{"balance_cents":'));
    controller.addError(http.ClientException('connection reset'));
    return http.StreamedResponse(controller.stream, 200);
  }
}

void main() {
  group('body 读取超时', () {
    test('body 卡住时 future 会完成(而不是永远挂着)', () async {
      final fake = _StalledBodyClient();
      final api = ApiClient(
        baseUrl: 'http://example.test',
        httpClient: fake,
        timeout: const Duration(milliseconds: 80),
      );

      // 关键断言不是"抛了什么",而是**它到底会不会返回**。
      // 修之前这一句会一直挂到测试超时
      Object? thrown;
      try {
        await api.wallet();
      } catch (e) {
        thrown = e;
      }

      expect(thrown, isA<ApiException>());
      expect((thrown! as ApiException).isNetwork, isTrue,
          reason: '超时属于网络层问题,页面据此给重试按钮');
      expect((thrown as ApiException).message, contains('超时'));
    });

    test('超时之后底层连接被掐掉,不留在连接池里', () async {
      final fake = _StalledBodyClient();
      final api = ApiClient(
        baseUrl: 'http://example.test',
        httpClient: fake,
        timeout: const Duration(milliseconds: 60),
      );

      await expectLater(api.wallet(), throwsA(isA<ApiException>()));
      expect(fake.cancelled, isTrue);
    });

    test('body 读到一半断了也不会挂住,报的是人话', () async {
      final api = ApiClient(
        baseUrl: 'http://example.test',
        httpClient: _BrokenBodyClient(),
        timeout: const Duration(seconds: 5),
      );

      await expectLater(
          api.wallet(),
          throwsA(isA<ApiException>()
              .having((e) => e.isNetwork, 'isNetwork', isTrue)
              .having((e) => e.message, 'message', contains('网络'))));
    });

    test('正常响应照旧', () async {
      final api = ApiClient(
        baseUrl: 'http://example.test',
        httpClient: _EchoClient(),
        timeout: const Duration(seconds: 5),
      );
      final wallet = await api.wallet();
      expect(wallet.balanceCents, 0);
    });
  });

  group('X-App-Build', () {
    test('取不到版本号时不发这个头(缺了不能让请求失败)', () async {
      final echo = _EchoClient();
      final api = ApiClient(
        baseUrl: 'http://example.test',
        httpClient: echo,
        timeout: const Duration(seconds: 5),
      );
      await api.wallet();
      // 测试环境没有平台通道,PackageInfo 拿不到 —— 头就该不存在,
      // 而不是发一个空串或者让整个请求挂掉
      expect(
          echo.headers.containsKey('X-App-Build'), ApiClient.appBuild != null);
    });

    test('有版本号时带上', () async {
      final echo = _EchoClient();
      ApiClient.appBuild = '123';
      addTearDown(() => ApiClient.appBuild = null);
      final api = ApiClient(
        baseUrl: 'http://example.test',
        httpClient: echo,
        timeout: const Duration(seconds: 5),
      );
      await api.wallet();
      expect(echo.headers['X-App-Build'], '123');
    });
  });
}
