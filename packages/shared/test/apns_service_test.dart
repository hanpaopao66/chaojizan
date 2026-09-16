/// 苹果推送直连的客户端这一半(src/apns_service.dart,#384)。
///
/// 守的是「拿到 token 就报上去、退出登录就下线、报不上去也不崩」这三件事。
/// 原生那半(AppDelegate.swift)在这里测不了,但**通道两头的形状**要对得上:
/// 原生发的是 `onToken` + `{token, sandbox}`,这里就按这个形状收。
library;

import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:superz_shared/superz_shared.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  setUp(ApnsService.resetForTest);
  tearDown(ApnsService.resetForTest);

  test('拿到 token 就报给服务端,沙箱标记原样带上', () async {
    final reported = <List<Object>>[];
    ApnsService.onRegister = (ch, tok, sandbox) async {
      reported.add([ch, tok, sandbox]);
    };

    await ApnsService.handleForTest(const MethodCall('onToken', {
      'token': 'abc123',
      'sandbox': true,
    }));

    expect(reported, [
      ['apns', 'abc123', true]
    ]);
    expect(ApnsService.token, 'abc123');
  });

  test('生产包的 sandbox 是 false —— 发错服务器是收不到推送的头号原因', () async {
    final reported = <bool>[];
    ApnsService.onRegister = (ch, tok, sandbox) async => reported.add(sandbox);
    await ApnsService.handleForTest(
        const MethodCall('onToken', {'token': 't', 'sandbox': false}));
    expect(reported, [false]);
  });

  test('报不上去不崩:下次启动会重新注册一遍', () async {
    ApnsService.onRegister = (ch, tok, sandbox) async => throw Exception('网络炸了');
    await expectLater(
        ApnsService.handleForTest(const MethodCall('onToken', {'token': 't'})),
        completes);
    expect(ApnsService.token, 't', reason: '本地还是记着,下次能再报');
  });

  test('没接 onRegister 也不崩(还没登录就来了 token)', () async {
    await expectLater(
        ApnsService.handleForTest(const MethodCall('onToken', {'token': 't'})),
        completes);
  });

  test('退出登录:把这台设备下线', () async {
    final removed = <List<String>>[];
    ApnsService.onRegister = (ch, tok, sandbox) async {};
    ApnsService.onUnregister = (ch, tok) async => removed.add([ch, tok]);

    await ApnsService.handleForTest(const MethodCall('onToken', {'token': 'tok9'}));
    await ApnsService.onLogout();

    // 非 iOS 的测试环境下 supported 是 false,onLogout 直接返回 —— 这也是对的:
    // 安卓 / 桌面上根本没有 APNs 设备要下线
    expect(removed, ApnsService.supported ? [
      ['apns', 'tok9']
    ] : isEmpty);
  });

  test('下线失败不崩', () async {
    ApnsService.onRegister = (ch, tok, sandbox) async {};
    ApnsService.onUnregister = (ch, tok) async => throw Exception('炸了');
    await ApnsService.handleForTest(const MethodCall('onToken', {'token': 't'}));
    await expectLater(ApnsService.onLogout(), completes);
  });

  test('哪个端是可设的 —— 服务端按它选 bundle id', () {
    ApnsService.app = 'rider';
    expect(ApnsService.app, 'rider');
    ApnsService.app = 'user';
  });
}
