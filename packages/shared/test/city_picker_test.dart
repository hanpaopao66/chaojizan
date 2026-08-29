import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:superz_shared/superz_shared.dart';

/// 全量城市选择器(#308)。
///
/// ## 这里锁的两件事
///
/// 1. **全国城市都要能选到**,而不是只有开通的那几个 —— 人会出差、
///    会搬家,到了没开通的城市列表空空如也,他只会以为 App 坏了;
/// 2. 每一条都要**标着有几家店**。全量清单里绝大多数城市还没开通,
///    不标的话用户切过去看到空列表,同样以为坏了。
///
/// 这两条都不会报错,只会让人困惑 —— 所以只能靠测试钉住。
void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  setUp(() => SharedPreferences.setMockInitialValues({}));

  SzCity city(String short, {int merchants = 0, String initial = 'C',
      String province = '四川', String pinyin = 'chengdu'}) =>
      SzCity(
        name: '$short市',
        short: short,
        province: province,
        initial: initial,
        pinyin: pinyin,
        merchants: merchants,
      );

  SzCityCatalog catalog() => SzCityCatalog(
        open: [city('成都', merchants: 12)],
        hot: [city('成都', merchants: 12)],
        all: [
          city('成都', merchants: 12),
          city('北京', initial: 'B', province: '北京', pinyin: 'beijing'),
          city('无锡', initial: 'W', province: '江苏', pinyin: 'wuxi'),
        ],
      );

  Future<void> open(WidgetTester tester,
      {SzCityCatalog? cat, String located = ''}) async {
    await tester.pumpWidget(MaterialApp(
      theme: brandTheme(Brightness.light),
      home: Scaffold(
        body: SzCityChip(
          city: '成都市',
          locatedCity: located,
          loadCities: () async => const [],
          loadCatalog: () async => cat ?? catalog(),
          onChanged: (_) {},
        ),
      ),
    ));
    await tester.tap(find.text('成都市'));
    await tester.pumpAndSettle();
  }

  testWidgets('没开通的城市也列出来 —— 否则用户以为 App 坏了', (tester) async {
    await open(tester);
    expect(find.text('无锡'), findsWidgets,
        reason: '全国城市里没有无锡 —— 出差到没开通的城市会看到空列表');
    expect(find.text('北京'), findsWidgets);
  });

  testWidgets('每条都标着有几家店', (tester) async {
    await open(tester);
    expect(find.text('暂无商家'), findsWidgets,
        reason: '没开通的城市不标出来,用户切过去看到空列表会以为坏了');
    expect(find.text('12 家店'), findsWidgets);
  });

  testWidgets('定位到的城市置顶', (tester) async {
    await open(tester, located: '北京市');
    expect(find.text('当前定位'), findsOneWidget);
  });

  testWidgets('拼音也能搜 —— 输入法没切中文时也该找得到', (tester) async {
    await open(tester);
    await tester.enterText(find.byType(TextField), 'wuxi');
    await tester.pumpAndSettle();
    expect(find.text('无锡'), findsWidgets);
    expect(find.text('北京'), findsNothing);
  });

  testWidgets('全量拿不到时退回有店的城市,选择器不能整个不可用',
      (tester) async {
    await open(tester,
        cat: SzCityCatalog(
            open: [city('成都', merchants: 12)],
            hot: [city('成都', merchants: 12)],
            all: const []));
    expect(find.text('成都'), findsWidgets,
        reason: '全国清单拿不到就整个空了 —— 少一份数据不该让功能不可用');
  });
}
