import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:rider_app/face_check_page.dart';
import 'package:superz_shared/superz_shared.dart';

import 'rider_fake_api.dart';

/// 人脸核验页(防代送)。
///
/// 守三件事:
/// - 第一次要**单独同意**:不勾选,按钮点不了;勾了,发起时带上 consent;
/// - 过期时要说清楚「手上的单照常送完」,不然他会以为单子也被收走了;
/// - 结果以服务端 finish 的返回为准,过了才返回 true。
void main() {
  setUpRiderTest();

  ApiClient fakeApi(Map<String, dynamic> status, List<String> calls,
          {bool pass = true}) =>
      ApiClient(
        baseUrl: 'http://test.local',
        httpClient: MockClient((req) async {
          final p = req.url.path;
          Object payload;
          if (p == '/riders/face/status') {
            payload = status;
          } else if (p == '/riders/face/start') {
            calls.add('start ${req.body}');
            payload = {
              'check_id': 7,
              'purpose': 'enroll',
              'provider': 'fake',
              'verify_url': '',
              'client_token': '',
            };
          } else {
            calls.add('finish ${req.body}');
            payload = {
              ...status,
              'due': pass ? '' : status['due'],
              'passed': pass,
              'reason': pass ? '' : '光线太暗',
            };
          }
          return http.Response(jsonEncode(payload), 200,
              headers: {'content-type': 'application/json; charset=utf-8'});
        }),
      );

  Map<String, dynamic> status({bool consented = false, String due = 'enroll'}) =>
      {
        'required': true,
        'interval_hours': 4,
        'consented': consented,
        'enrolled': due != 'enroll',
        'verified_at': null,
        'expires_at': null,
        'due': due,
      };

  /// 从一个按钮打开核验页;页面关掉后的返回值写进 [onResult]
  Future<void> pumpPage(WidgetTester t, ApiClient api,
      {void Function(bool)? onResult}) async {
    setPhoneViewport(t, const Size(390, 844));
    await t.pumpWidget(MaterialApp(
      theme: brandTheme(Brightness.light),
      home: Builder(
        builder: (ctx) => TextButton(
          onPressed: () async {
            final ok = await FaceCheckPage.open(ctx, api);
            onResult?.call(ok);
          },
          child: const Text('打开'),
        ),
      ),
    ));
    await t.tap(find.text('打开'));
    await t.pumpAndSettle();
  }

  testWidgets('第一次:不勾同意按不了;勾了发起时带 consent,过了返回 true',
      (t) async {
    final calls = <String>[];
    bool? result;
    await pumpPage(t, fakeApi(status(), calls), onResult: (r) => result = r);

    final button = find.widgetWithText(FilledButton, '开始核验');
    expect(t.widget<FilledButton>(button).onPressed, isNull,
        reason: '人脸要单独同意,没勾就不能发起');
    expect(find.textContaining('不保存你的人脸照片'), findsOneWidget);

    await t.tap(find.byType(Checkbox));
    await t.pump();
    await t.tap(button);
    await t.pumpAndSettle();

    expect(calls.first, contains('"consent":true'));
    expect(calls.last, contains('"check_id":7'));
    expect(result, isTrue);
  });

  testWidgets('过期复核:说清楚手上的单照常送;没过就留在页上并给原因', (t) async {
    final calls = <String>[];
    await pumpPage(t, fakeApi(status(consented: true, due: 'expired'), calls,
        pass: false));

    expect(find.textContaining('手上的单照常送完'), findsWidgets);
    expect(find.byType(Checkbox), findsNothing, reason: '同意过就不再问');

    await t.tap(find.widgetWithText(FilledButton, '开始核验'));
    await t.pumpAndSettle();

    expect(calls.first, isNot(contains('consent')));
    expect(find.textContaining('光线太暗'), findsOneWidget);
    expect(find.widgetWithText(FilledButton, '再试一次'), findsOneWidget);
  });
}
