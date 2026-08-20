import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

/// 店铺页设置区的密度(#294)。**直接读源码断言**。
///
/// ## 这个测试防的是什么
///
/// 改之前那一整块是一张卡里塞 24 条,每条是
/// 「标题 + 一个 OutlinedButton + 两行说明 + Divider(height: 24)」——
/// 一条两百多像素,商家要滑很久才找得到「起送价」。
///
/// 改完之后拆成四个分组,条目走 SzEntryTile:能给当前值的给值
/// (起送价「不限」、营业时间「09:00 – 21:00」、堂食标识「有堂食」),
/// 给不出值又不需要解释的就只有标题。
///
/// 密度退化没有报错 —— 功能全对、测试全绿,只是难用。所以在源码层面锁住。
void main() {
  final src = File('lib/shop_tab.dart').readAsStringSync();

  test('大按钮基本清光了', () {
    // 改前 16 个 OutlinedButton(每个都是「进入/设置/查看/管理」这种次级动作)。
    // 次级动作用 chevron 就够,不该和「保存」一样重
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

  test('设置项走 SzEntryTile,不是手搓 Row', () {
    expect(RegExp(r'SzEntryTile').allMatches(src).length, greaterThan(25),
        reason: '有人绕过 SzEntryTile 手搓入口了');
    expect(RegExp(r'SzEntryGroup').allMatches(src).length, greaterThanOrEqualTo(4),
        reason: '四个分组(营业/价格与活动/门店与合规/工具)少了');
  });

  test('实测出餐时长没被当成解释删掉', () {
    // 它是**数据**不是解释:商家改承诺时长时唯一该看的东西。
    // 而且它自己会判断样本够不够,塞不进只放一句话的 hint
    expect(src, contains('_measuredPrep()'),
        reason: '实测出餐时长丢了 —— 那不是解释,是商家改承诺值的唯一依据');
  });

  test('公告输入框留在页面里,没被塞进弹窗', () {
    // 这一整块里唯一真需要内联输入的东西:它是一段自由文本,
    // 不是"点开改个值"。塞进弹窗反而多一次点击
    expect(src, contains('controller: _announcement'));
  });
}
