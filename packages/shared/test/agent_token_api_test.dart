import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:package_info_plus/package_info_plus.dart';
import 'package:superz_shared/superz_shared.dart';

/// 签发 AI 助手令牌的请求体(服务端 POST /auth/agent-tokens)。
///
/// scopes 不传就不带这个字段:服务端按「只点餐」签,分权限之前的服务端也照旧认。
void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  setUpAll(() => PackageInfo.setMockInitialValues(
      appName: 'superz_shared',
      packageName: 'com.superz.shared',
      version: '0.1.0',
      buildNumber: '1',
      buildSignature: ''));
  setUp(ApiClient.resetAppBuildForTest);

  /// 调一次 [call],返回发出去的请求体
  Future<Map<String, dynamic>> sent(
      Future<void> Function(ApiClient api) call) async {
    Map<String, dynamic>? body;
    final api = ApiClient(
      baseUrl: 'http://example.test',
      httpClient: MockClient((req) async {
        body = jsonDecode(req.body) as Map<String, dynamic>;
        return http.Response(jsonEncode({'token': 't', 'note': ''}), 200,
            headers: {'content-type': 'application/json'});
      }),
    );
    await call(api);
    return body!;
  }

  test('不传 scopes 就不带这个字段', () async {
    final body = await sent((api) => api.createAgentToken('我的 Claude', 90));
    expect(body, {'name': '我的 Claude', 'days': 90});
  });

  test('传了就原样带上', () async {
    final body = await sent((api) =>
        api.createAgentToken('投稿助手', 30, scopes: ['order', 'video']));
    expect(body, {
      'name': '投稿助手',
      'days': 30,
      'scopes': ['order', 'video'],
    });
  });
}
