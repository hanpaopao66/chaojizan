import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:superz_shared/superz_shared.dart';

import 'text_fit.dart';

/// 设置类入口的密度(#294)。
///
/// ## 这个测试防的是什么
///
/// 真机截图上看出来的问题:「我的 / 店铺」页一屏只放得下 4~6 条,
/// 而每条其实只是一个入口 —— 翻半天翻不到要找的那个。
///
/// 根因不是"字太多",是三种不同的副标题被按同一种方式摆了
/// (状态值 / 一次性解释 / 立场表达),全塞进 `ListTile.subtitle`,
/// 于是每条吃掉 Material 规定的 72dp 最小高度。
///
/// 密度这种事**没有报错**:功能全对、测试全绿,只是难用。
/// 所以拿数字锁住,别让它慢慢长回去。
void main() {
  Future<double> heightOf(WidgetTester t, Widget w,
      {double scale = 1.0}) async {
    setPhoneViewport(t, const Size(390, 844));
    await t.pumpWidget(MediaQuery(
      data: MediaQueryData(textScaler: TextScaler.linear(scale)),
      child: MaterialApp(
        theme: brandTheme(Brightness.light),
        home: Scaffold(
            body: Align(alignment: Alignment.topCenter, child: w)),
      ),
    ));
    await t.pumpAndSettle();
    return t.getSize(find.byWidget(w)).height;
  }

  group('单条的高度', () {
    testWidgets('已配置的条目不超过 50px —— 比 ListTile+subtitle 的 72 省三成',
        (t) async {
      final h = await heightOf(
          t,
          SzEntryTile(
              icon: Icons.badge_outlined,
              title: '食品经营许可证',
              value: '2027-03-15 到期',
              onTap: () {}));
      expect(h, lessThanOrEqualTo(50),
          reason: '入口条又长回去了(当前 ${h.toStringAsFixed(0)}px)');
    });

    testWidgets('状态值和标题同一行,不额外占高度', (t) async {
      final bare =
          await heightOf(t, SzEntryTile(title: '起送价', onTap: () {}));
      final withValue = await heightOf(
          t, SzEntryTile(title: '起送价', value: '不限', onTap: () {}));
      expect(withValue, bare,
          reason: '加了状态值就变高 —— 说明它没和标题排在同一行');
    });

    testWidgets('解释只在没配好时出现,配好了让位给状态', (t) async {
      // 这一条是整个设计的核心:解释是给"还不知道要干什么"的人的,
      // 配完之后他要看的是"现在是什么值"
      final unset = await heightOf(
          t,
          SzEntryTile(
              title: '满减活动',
              hint: '满减成本由商家承担,平台按满减后实收计费',
              onTap: () {}));
      final set = await heightOf(
          t,
          SzEntryTile(
              title: '满减活动',
              value: '满30减1',
              hint: '满减成本由商家承担,平台按满减后实收计费',
              onTap: () {}));
      expect(set, lessThan(unset), reason: '配好了之后解释还占着位置');
      expect(set, lessThanOrEqualTo(50));
    });
  });

  group('分组比"每项一张卡"省', () {
    List<Widget> six() => [
          for (var i = 0; i < 6; i++)
            SzEntryTile(
                icon: Icons.circle_outlined,
                title: '入口 $i',
                value: '值 $i',
                onTap: () {}),
        ];

    testWidgets('六条入口一屏放得下', (t) async {
      final h = await heightOf(t, SzEntryGroup(title: '合规', children: six()));
      // 390×844 的屏,去掉状态栏/标题栏/底部导航大约剩 684
      expect(h, lessThan(684 * 0.55),
          reason: '六条入口占了大半屏(${h.toStringAsFixed(0)}px)—— '
              '那这一页还是翻不完');
    });

    testWidgets('组内用发丝线,不是每条一张卡', (t) async {
      await heightOf(t, SzEntryGroup(children: six()));
      // 六条之间五条分隔线;每条一张卡的话会有六个带描边的容器
      expect(find.byType(Divider), findsNWidgets(5));
    });
  });

  group('长辈版下也不塌', () {
    testWidgets('1.4× 字号下状态值不换行把行顶高', (t) async {
      final h = await heightOf(
          t,
          SzEntryTile(
              icon: Icons.badge_outlined,
              title: '食品经营许可证',
              value: '2027-03-15 到期',
              onTap: () {}),
          scale: 1.4);
      // 允许变高(字确实大了),但不能因为状态值换行而翻倍
      expect(h, lessThan(70),
          reason: '1.4× 下涨到 ${h.toStringAsFixed(0)}px —— '
              '多半是状态值换行了');
    });

    testWidgets('1.4× 下不画出界', (t) async {
      setPhoneViewport(t, const Size(320, 780));
      await t.pumpWidget(MediaQuery(
        data: const MediaQueryData(textScaler: TextScaler.linear(1.4)),
        child: MaterialApp(
          theme: brandTheme(Brightness.light),
          home: Scaffold(
            body: SzEntryGroup(title: '合规', children: [
              SzEntryTile(
                  icon: Icons.badge_outlined,
                  title: '食品经营许可证',
                  value: '2027-03-15 到期',
                  onTap: () {}),
            ]),
          ),
        ),
      ));
      await t.pumpAndSettle();
      expect(t.takeException(), isNull);
      expect(textsPaintingOutside(t), isEmpty);
    });
  });
}
