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

  group('hint 的成本 —— 这一条是踩出来的', () {
    testWidgets('只有 hint 的条目省得很少,别当成免费的', (t) async {
      final withValue = await heightOf(
          t, SzEntryTile(icon: Icons.circle, title: '入口', value: '值', onTap: () {}));
      final withHint = await heightOf(
          t, SzEntryTile(icon: Icons.circle, title: '入口', hint: '一句说明', onTap: () {}));
      const oldListTile = 72.0;

      // 有状态值:72 → 46,省 36%
      expect(withValue / oldListTile, lessThan(0.7));
      // 只有 hint:72 → 63,只省 12% —— **几乎等于没改**
      expect(withHint / oldListTile, greaterThan(0.8),
          reason: 'hint 看着便宜,其实只省一成 —— '
              '这个断言是提醒:别以为加了 hint 还能省地方');
    });

    testWidgets('分组头 + 脚注的开销要算进去', (t) async {
      final one = await heightOf(
          t, SzEntryTile(title: 'x', value: 'y', onTap: () {}));
      final grp = await heightOf(t,
          SzEntryGroup(title: '分组',
              children: [SzEntryTile(title: 'x', value: 'y', onTap: () {})]));
      final grpFoot = await heightOf(t,
          SzEntryGroup(title: '分组', footnote: '一句脚注',
              children: [SzEntryTile(title: 'x', value: 'y', onTap: () {})]));

      // 分组头约 41px、脚注约 23px。两个分组 + 一条脚注就是 105px ——
      // 第一版改造正是栽在这儿:九个入口大多只有 hint,
      // 省下的还不够付分组的开销,改完反而**长了 4%**。
      //
      // 判据:分组和脚注是有价格的,别为了"看起来有结构"随手加。
      expect(grp - one, lessThan(50), reason: '分组头太贵了');
      expect(grpFoot - grp, lessThan(30), reason: '脚注太贵了');
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

  /// 字号跟密度走(#33 第 5 节遗留,已拍板做掉)。
  ///
  /// `SzDensity.fontBump` 的注释写着「商家端在油烟和光线不好的后厨看,
  /// 骑手在阳光下看」,而这两个组件此前写死常量 —— 商家端最常盯的
  /// 「店铺」页恰恰全是它们(46 处),分化在最需要的地方是空的:
  /// 同一屏里按钮文字 +1 了,入口条的字没有。
  ///
  /// 锁字号不锁高度:flutter_test 的回退字体把字符画成 fontSize 见方,
  /// 高度在这里量不出真机的差别(实测两档都是 159)。
  group('字号跟密度走', () {
    // ⚠️ 两次 pump 之间必须先清场。
    //
    // `home: const Scaffold(...)` 在两次 pumpWidget 里是**同一个 const 实例**
    // (Dart 会把相同的 const 规范化成一个对象),Flutter 认为 widget 没变
    // 就不重建 —— 换了 theme 也照样量到上一次的字号,于是这条测试会
    // "证明"分化没生效,而实际上是测试自己没刷新。
    Future<void> clear(WidgetTester t) async {
      await t.pumpWidget(const SizedBox());
      await t.pump();
    }

    Future<double?> titleSize(WidgetTester t, SzDensity d) async {
      await clear(t);
      await t.pumpWidget(MaterialApp(
        theme: brandTheme(Brightness.light, density: d),
        home: const Scaffold(
            body: SzEntryGroup(children: [SzEntryTile(title: '收款账户')])),
      ));
      return t.widget<Text>(find.text('收款账户')).style?.fontSize;
    }

    Future<double?> gridLabelSize(WidgetTester t, SzDensity d) async {
      await clear(t);
      await t.pumpWidget(MaterialApp(
        theme: brandTheme(Brightness.light, density: d),
        home: const Scaffold(
            body: SzIconGrid(items: [
          SzIconGridItem(icon: Icons.star, label: '优惠券'),
        ])),
      ));
      return t.widget<Text>(find.text('优惠券')).style?.fontSize;
    }

    testWidgets('入口条:操作态比浏览态大一档', (t) async {
      final browse = await titleSize(t, SzDensity.browse);
      final operate = await titleSize(t, SzDensity.operate);
      expect(browse, kFontBodyLg);
      expect(operate, kFontBodyLg + SzDensity.operate.fontBump,
          reason: '商家端/骑手端的入口条没跟着密度加大 —— '
              '同一屏里按钮文字已经 +1 了,两套字号');
    });

    testWidgets('图标网格:同一条口径', (t) async {
      expect(await gridLabelSize(t, SzDensity.browse), kFontNote);
      expect(await gridLabelSize(t, SzDensity.operate),
          kFontNote + SzDensity.operate.fontBump);
    });

    testWidgets('用户端(浏览态)一个像素都不动', (t) async {
      // 这条是这次改动的安全边界:user_app 走 browse,
      // 它的入口页不该因为"给商家端加大"而跟着变样
      expect(await titleSize(t, SzDensity.browse), kFontBodyLg);
      expect(await gridLabelSize(t, SzDensity.browse), kFontNote);
    });

    testWidgets('没挂主题扩展时按浏览态,不炸', (t) async {
      await t.pumpWidget(const MaterialApp(
        home: Scaffold(
            body: SzEntryGroup(children: [SzEntryTile(title: '裸主题')])),
      ));
      expect(t.widget<Text>(find.text('裸主题')).style?.fontSize, kFontBodyLg);
    });
  });
}
