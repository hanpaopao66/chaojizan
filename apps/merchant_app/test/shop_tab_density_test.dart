import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

/// 店铺页设置区的**源码层**残留检查(#294)。
///
/// ## 这个文件只剩下"确认某种写法没长回来"
///
/// 密度、首屏入口数、公告收进弹层、分组头砍掉这些**行为**判据,
/// 一律搬到 `shop_tab_page_test.dart` 真渲染去量。
///
/// 搬家的理由就在这个文件自己身上:它原本有一条
///
/// ```dart
/// test('公告输入框留在页面里,没被塞进弹窗', () {
///   expect(src, contains('controller: _announcement'));
/// });
/// ```
///
/// 公告搬进弹层之后,那行文本**照样在**(弹层里用的是同一个 controller),
/// 断言照样绿 —— 而它要守的那件事已经反过来了。**文本在,行为没了。**
/// 这就是"假绿"最典型的样子:测试通过、需求作废,谁也不会发现。
///
/// 下面留的三条是真正只能在源码层看的:它们查的是"某种更贵的写法有没有
/// 重新出现",而不是"页面现在长什么样"。
void main() {
  final src = File('lib/shop_tab.dart').readAsStringSync();

  test('大按钮基本清光了', () {
    // 改前 16 个 OutlinedButton(每个都是「进入/设置/查看/管理」这种次级动作)。
    // 次级动作用 chevron 就够,不该和「保存」一样重。
    // 现在只剩售后卡上的「拒绝」—— 那是真动作,该是按钮
    final n = RegExp(r'OutlinedButton').allMatches(src).length;
    expect(n, lessThanOrEqualTo(3),
        reason: '又长回 $n 个大按钮 —— 次级动作用 chevron,别用按钮');
  });

  test('24px 分隔线一条不剩', () {
    // 改前 16 条 Divider(height: 24) —— 光分隔线就吃掉 384px
    expect(src, isNot(contains('Divider(height: 24)')),
        reason: '设置项之间又塞回 24px 的分隔线了');
  });

  test('两行说明收敛到个位数', () {
    // 改前 23 处 textTheme.bodySmall 说明。留下的必须是**内容或立场**,
    // 不是"这个入口是干嘛的"(标题已经答了)
    final n = RegExp(r'textTheme\.bodySmall').allMatches(src).length;
    expect(n, lessThan(10),
        reason: '说明文字涨回 $n 处 —— 先问它回答的是哪个问题:'
            '"这是干嘛的"删掉,"现在什么值"走 value,'
            '"规则/立场"才留');
  });

  test('入口走 SzEntryTile / SzIconGrid,不是手搓 Row', () {
    // 33 个入口里 15 个进了网格,所以 SzEntryTile 的数量本来就该降下来。
    // 这一条只防"有人绕过组件手搓一个入口"
    final tiles = RegExp(r'SzEntryTile').allMatches(src).length;
    final grids = RegExp(r'SzIconGrid').allMatches(src).length;
    expect(tiles + grids, greaterThan(20),
        reason: '有人绕过 SzEntryTile / SzIconGrid 手搓入口了');
  });

  test('实测出餐时长没被当成解释删掉', () {
    // 它是**数据**不是解释:商家改承诺时长时唯一该看的东西。
    // 而且它自己会判断样本够不够,塞不进只放一句话的 hint。
    //
    // (它显示的三行文字有没有真的渲染出来,由 shop_tab_page_test.dart 验)
    expect(src, contains('_measuredPrep()'),
        reason: '实测出餐时长丢了 —— 那不是解释,是商家改承诺值的唯一依据');
  });
}
