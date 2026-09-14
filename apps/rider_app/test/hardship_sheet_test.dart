import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:rider_app/hardship_sheet.dart';
import 'package:superz_shared/superz_shared.dart';

import 'rider_fake_api.dart';

/// 「这单不好送」反馈:2026-09-14 起**反馈的这一单不当场补钱**(平台不出这笔钱)。
///
/// 钱只进以后的单:同一个地方两个骑手说过之后,新单下单时把难度费算进配送费(顾客付、
/// 全归骑手)。第一句就得照实说 —— 原来写的是「说了这一单当场补钱(平台出)」,
/// 服务端停了之后这句就成了骗人填表。
void main() {
  setUpRiderTest();

  ApiClient fakeApi(List<String> posted) => ApiClient(
        baseUrl: 'http://test.local',
        httpClient: MockClient((req) async {
          final Object payload;
          if (req.url.path == '/orders/hardship-rules') {
            payload = {
              'items': [
                {
                  'kind': 'no_vehicle',
                  'name': '车辆禁入',
                  'desc': '电动车进不去',
                  'cents': 200,
                  'rule': '固定 ¥2',
                },
              ],
              'funder': 'customer',
              'paid_now': false,
            };
          } else {
            posted.add(req.url.path);
            payload = {
              'comp_cents': 0,
              'paid_now': false,
              'lines': ['车辆禁入,只能推行 +¥2'],
              'duplicate': false,
              'message': '谢谢,已记下。这一单不当场补钱',
            };
          }
          return http.Response(jsonEncode(payload), 200,
              headers: {'content-type': 'application/json; charset=utf-8'});
        }),
      );

  testWidgets('第一句照实说:这一单不当场补钱,钱进以后的配送费', (t) async {
    setPhoneViewport(t, const Size(390, 844));
    final posted = <String>[];
    final api = fakeApi(posted);
    // 和线上一样从底部弹出来:提交后关掉这一层,回执落在下面那页的 SnackBar 上
    await t.pumpWidget(MaterialApp(
      theme: brandTheme(Brightness.light),
      home: Scaffold(
        body: Builder(
          builder: (ctx) => TextButton(
            onPressed: () => HardshipSheet.show(ctx, api, 'a' * 20),
            child: const Text('送达了'),
          ),
        ),
      ),
    ));
    await t.tap(find.text('送达了'));
    await t.pumpAndSettle();

    expect(find.textContaining('这一单不当场补钱'), findsOneWidget);
    expect(find.textContaining('算进配送费'), findsOneWidget);
    expect(find.textContaining('当场补钱(平台出'), findsNothing,
        reason: '服务端已经不当场补钱了,这句会让骑手以为填了就有钱');

    await t.tap(find.text('车辆禁入'));
    await t.pump();
    await t.tap(find.widgetWithText(FilledButton, '提交'));
    await t.pumpAndSettle();
    expect(posted, ['/orders/${'a' * 20}/hardship']);
    expect(find.textContaining('这一单不当场补钱'), findsOneWidget,
        reason: '提交后的回执用服务端的 message');
  });
}
