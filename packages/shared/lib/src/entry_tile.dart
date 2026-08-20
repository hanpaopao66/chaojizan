import 'package:flutter/material.dart';

import 'brand.dart';

/// 设置类入口的统一样式。三端的「我的 / 店铺」页共用。
///
/// ## 为什么要有它(#294)
///
/// 真机截图上看出来的:这些页面**一屏只放得下 4~6 条**,而每条其实
/// 只是一个入口。翻半天翻不到要找的那个。
///
/// 原因不是"字太多",是**三种不同的副标题被按同一种方式摆了**:
///
/// | 类型 | 例子 | 该怎么放 |
/// |---|---|---|
/// | **状态值** | 「满30减1」「未设置」「有堂食」 | 和标题同一行右对齐,**零额外高度** |
/// | **一次性解释** | 「登记后到期前 30/7/1 天提醒你」 | 只在**还没配好**时显示 |
/// | **立场表达** | 「平台不卖硬件也不挑品牌」 | 收进分组头,不是每行都说 |
///
/// 之前全都塞进 `ListTile.subtitle`,于是每条都吃掉 72dp 的最小高度
/// (Material 对带 subtitle 的 ListTile 的规定),还各自带一条
/// `Divider(height: 24)`。
///
/// ## 解释为什么"配好了就不显示"
///
/// 那句解释是给**第一次看见、还不知道要干什么**的人的。
/// 配置完之后他已经知道了,再占一行就是纯噪音 —— 而这时候他真正想看的是
/// **现在是什么值**。所以让位给状态,不是删掉。
///
/// 这不是"为了紧凑砍文案"。产品的解释是刻意的,只是不该每一行都说一遍。
class SzEntryTile extends StatelessWidget {
  const SzEntryTile({
    super.key,
    required this.title,
    this.icon,
    this.value,
    this.hint,
    this.valueTone,
    this.trailing,
    this.onTap,
    this.dense = false,
  });

  final String title;
  final IconData? icon;

  /// 当前值/状态。**和标题同一行**,右对齐,不额外占高度。
  /// 空 = 这个入口没有状态可言(比如「联系客服」)。
  final String? value;

  /// 一次性解释。**只在 [value] 为空时显示** —— 见类文档。
  final String? hint;

  /// 状态的语气:待办用 hold、异常用 danger、正常留空。
  final Color? valueTone;

  /// 右侧自定义控件(开关之类)。给了就不画 chevron。
  final Widget? trailing;

  final VoidCallback? onTap;

  /// 更紧的一档:分组里条目很多时用。
  final bool dense;

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    // hint 只在没有状态值时出现。两者同时给的话,状态优先 ——
    // 用户已经配过了,他要看的是"现在是什么"
    final showHint = (value == null || value!.isEmpty) &&
        hint != null &&
        hint!.isNotEmpty;

    return InkWell(
      onTap: onTap,
      child: Padding(
        padding: EdgeInsets.symmetric(
            horizontal: kCardPad, vertical: dense ? 9 : 12),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.center,
          children: [
            if (icon != null) ...[
              Icon(icon, size: 20, color: sz.inkFaint),
              const SizedBox(width: 12),
            ],
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                mainAxisSize: MainAxisSize.min,
                children: [
                  Text(title,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: TextStyle(
                          fontSize: dense ? kFontBody : kFontBodyLg,
                          color: sz.ink)),
                  if (showHint) ...[
                    const SizedBox(height: 2),
                    // **一行**,多了切掉。
                    //
                    // 量出来才发现:hint 给两行的话,这套改造等于白做 ——
                    // 九个入口从 641px 变成 664px,反而更长。因为九条里
                    // 只有两条有状态值,其余照旧顶着两行说明。
                    //
                    // 需要两行才说得清的东西**不是提示,是文档** ——
                    // 它该在点进去的那一页里,不该占着入口列表。
                    // 入口列表回答「这是什么」,目的页回答「为什么重要」。
                    Text(hint!,
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: TextStyle(
                            fontSize: kFontMicro,
                            height: 1.35,
                            color: sz.inkMuted)),
                  ],
                ],
              ),
            ),
            if (value != null && value!.isNotEmpty) ...[
              const SizedBox(width: 10),
              // 状态值收窄:它是个值不是段落,长了就省略 ——
              // 让它换行会把这一行的高度顶回去,那就白改了
              Flexible(
                child: Text(value!,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    textAlign: TextAlign.right,
                    style: TextStyle(
                        fontSize: kFontNote,
                        fontWeight: FontWeight.w500,
                        color: valueTone ?? sz.inkMuted)),
              ),
            ],
            if (trailing != null) ...[
              const SizedBox(width: 8),
              trailing!,
            ] else if (onTap != null) ...[
              const SizedBox(width: 4),
              Icon(Icons.chevron_right, size: 18, color: sz.inkFaint),
            ],
          ],
        ),
      ),
    );
  }
}

/// 一组入口。分组头 + 一张卡,组内用发丝线分隔。
///
/// **不要每个入口一张卡** —— 卡片的外边距、圆角、描边各占一份,
/// 十个入口就是十份。分组本来就是"这几件事是一类",一张卡正好表达它。
class SzEntryGroup extends StatelessWidget {
  const SzEntryGroup({
    super.key,
    required this.children,
    this.title,
    this.footnote,
  });

  final List<Widget> children;

  /// 分组名。
  final String? title;

  /// 整组共用的一句话。**立场表达放这里,不要塞进每一行** ——
  /// 「平台不卖硬件也不挑品牌」这种话说一次就够。
  final String? footnote;

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    return Column(
      // ⚠️ 必须 min。不写的话 Column 默认 max,高度不受限时(比如放在
      // Align 或 Center 里)它会**吃满整屏** —— 六条入口撑成 844px。
      // 放在 ListView 里看不出来,换个容器就塌
      mainAxisSize: MainAxisSize.min,
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        if (title != null)
          Padding(
            padding: const EdgeInsets.fromLTRB(kCardPad, 14, kCardPad, 6),
            child: Text(title!,
                style: TextStyle(fontSize: kFontNote, color: sz.inkMuted)),
          ),
        Container(
          decoration: BoxDecoration(
            color: sz.surface,
            borderRadius: BorderRadius.circular(kRadiusMd),
            border: Border.all(color: sz.line),
          ),
          child: Column(mainAxisSize: MainAxisSize.min, children: [
            for (var i = 0; i < children.length; i++) ...[
              if (i > 0) Divider(height: 1, thickness: 1, color: sz.line),
              children[i],
            ],
          ]),
        ),
        if (footnote != null)
          Padding(
            padding: const EdgeInsets.fromLTRB(kCardPad, 6, kCardPad, 0),
            child: Text(footnote!,
                style: TextStyle(
                    fontSize: kFontMicro, height: 1.5, color: sz.inkMuted)),
          ),
      ],
    );
  }
}
