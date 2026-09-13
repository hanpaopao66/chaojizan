import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:superz_shared/superz_shared.dart';

/// 地图选点页在手机上键盘弹起、搜出一串结果时不能溢出(安卓走查 #376:聊天发位置时撞到,
/// 收货地址用的是同一个页面)。原来地图固定整屏 38%、联想结果最多整屏 34%,
/// 都按整屏高算;键盘一弹可用高度只剩一半,加上确认栏一起溢出 300 多像素。
void main() {
  Future<void> pumpPicker(WidgetTester tester, {required double keyboard}) async {
    tester.view.physicalSize = const Size(412, 915);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
    tester.view.viewInsets = FakeViewPadding(bottom: keyboard);
    await tester.pumpWidget(MaterialApp(
      theme: brandTheme(Brightness.light),
      home: MapPickerPage(
        onReverse: (lat, lng) async => (name: '梓潼正成·财富ID', district: '四川省成都市锦江区'),
        onAround: (lat, lng) async => [
          for (var i = 0; i < 12; i++)
            NearbyPlace(name: '周边地点 $i', address: '四川省成都市锦江区某路 $i 号', distanceM: i * 10, lat: 30.66, lng: 104.08),
        ],
        onSearch: (kw) async => [
          for (var i = 0; i < 10; i++)
            PoiTip(name: '$kw 搜索结果 $i', district: '四川省成都市锦江区', lat: 30.66 + i / 1000, lng: 104.08),
        ],
        city: '成都市',
      ),
    ));
    await tester.pumpAndSettle();
  }

  for (final keyboard in [0.0, 336.0]) {
    testWidgets('键盘 ${keyboard.toInt()}:搜出一串结果时不溢出,确认按钮还在', (tester) async {
      await pumpPicker(tester, keyboard: keyboard);
      await tester.enterText(find.byType(TextField), '太古里');
      await tester.pump(const Duration(milliseconds: 500)); // 联想有 400ms 防抖
      await tester.pumpAndSettle();
      expect(tester.takeException(), isNull);
      expect(find.textContaining('搜索结果 0'), findsOneWidget, reason: '联想结果没出来');
      expect(find.byType(FilledButton), findsOneWidget);
    });
  }
}
