import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:package_info_plus/package_info_plus.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:superz_shared/superz_shared.dart';

/// 视听许可证编号从 `/config` 的 licenses.av 来(后台「平台开关」里填),
/// 「关于我们」读 [RemoteCopy.avLicense]:填了显示、空着不显示、老服务端没有这个字段也不出错。
void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  setUpAll(() => PackageInfo.setMockInitialValues(
      appName: 'superz_shared',
      packageName: 'com.superz.shared',
      version: '0.1.0',
      buildNumber: '1',
      buildSignature: ''));
  setUp(() {
    ApiClient.resetAppBuildForTest();
    SharedPreferences.setMockInitialValues({});
    RemoteCopy.avLicense = '';
  });

  ApiClient serving(Map<String, dynamic> config) => ApiClient(
        baseUrl: 'http://example.test',
        httpClient: MockClient((req) async => http.Response(
            jsonEncode(config), 200,
            headers: {'content-type': 'application/json; charset=utf-8'})),
      );

  test('填了编号就读到', () async {
    await RemoteCopy.refresh(serving({
      'licenses': {'av': ' 测试字第 0001 号 '},
      'features': {'video': true},
      'copy': {},
      'faq': [],
    }));
    expect(RemoteCopy.avLicense, '测试字第 0001 号');
  });

  test('清空之后不显示', () async {
    RemoteCopy.avLicense = '旧编号';
    await RemoteCopy.refresh(serving({'licenses': {'av': ''}, 'copy': {}, 'faq': []}));
    expect(RemoteCopy.avLicense, '');
  });

  test('老服务端没有 licenses 字段:不出错,保持原样', () async {
    await RemoteCopy.refresh(serving({'copy': {}, 'faq': []}));
    expect(RemoteCopy.avLicense, '');
  });
}
