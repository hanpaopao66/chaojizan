/// 设计令牌与共享组件走查页(第八辑视觉重构)。
///
/// 跑法:cd packages/shared/example && flutter run -d chrome
/// 这页不随三端发布,只用来核对令牌与组件、出走查截图。
///
/// 走 superz_shared/design.dart 这个轻入口,不引 superz_shared.dart——
/// 后者会带出 jpush 等平台插件,web 编不过。
library;

import 'package:flutter/material.dart';
import 'package:superz_shared/design.dart';

void main() => runApp(const GalleryApp());

class GalleryApp extends StatefulWidget {
  const GalleryApp({super.key});

  @override
  State<GalleryApp> createState() => _GalleryAppState();
}

class _GalleryAppState extends State<GalleryApp> {
  // ?dark=1 直接以深色启动:出截图时无需点按钮,一条命令一张图
  Brightness _brightness = Uri.base.queryParameters['dark'] == '1'
      ? Brightness.dark
      : Brightness.light;

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: '超级赞 · 设计令牌走查',
      debugShowCheckedModeBanner: false,
      theme: brandTheme(_brightness),
      home: GalleryPage(
        brightness: _brightness,
        onToggle: () => setState(() => _brightness =
            _brightness == Brightness.light
                ? Brightness.dark
                : Brightness.light),
      ),
    );
  }
}

class GalleryPage extends StatelessWidget {
  const GalleryPage({
    super.key,
    required this.brightness,
    required this.onToggle,
  });

  final Brightness brightness;
  final VoidCallback onToggle;

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    final text = Theme.of(context).textTheme;

    return Scaffold(
      appBar: AppBar(
        title: const Text('设计令牌走查'),
        actions: [
          TextButton(
            onPressed: onToggle,
            child: Text(brightness == Brightness.light ? '切深色' : '切浅色'),
          ),
          const SizedBox(width: 8),
        ],
      ),
      body: SingleChildScrollView(
        padding: const EdgeInsets.fromLTRB(kPagePad, 4, kPagePad, 40),
        child: Center(
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 520),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                _title(context, '色板'),
                _Swatches(sz: sz),

                _title(context, '字阶'),
                Card(
                  child: Padding(
                    padding: const EdgeInsets.all(kCardPad),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text('页面大标题 26', style: text.headlineSmall),
                        const SizedBox(height: 6),
                        Text('卡片标题 21', style: text.titleLarge),
                        const SizedBox(height: 6),
                        Text('小节标题 17', style: text.titleMedium),
                        const SizedBox(height: 6),
                        Text('正文 15:配送费 100% 归骑手,平台分文不取。',
                            style: text.bodyMedium),
                        const SizedBox(height: 6),
                        Text('辅助 12.5:账目对用户、商家、骑手三方公开。',
                            style: text.bodySmall),
                      ],
                    ),
                  ),
                ),

                _title(context, '数字 szFigure(正文,旧式数字)'),
                Card(
                  child: Padding(
                    padding: const EdgeInsets.all(kCardPad),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text.rich(TextSpan(children: [
                          TextSpan(text: '4.8', style: szFigure(fontSize: 14)),
                          TextSpan(text: ' 分 · 月售 ', style: text.bodyMedium),
                          TextSpan(text: '302', style: szFigure(fontSize: 14)),
                          TextSpan(text: ' 单 · ', style: text.bodyMedium),
                          TextSpan(text: '1.2', style: szFigure(fontSize: 14)),
                          TextSpan(text: 'km', style: text.bodyMedium),
                        ])),
                        const SizedBox(height: 8),
                        Text('中文不会被带成宋体——子集里没有 CJK,系统自动回落',
                            style: text.bodySmall),
                      ],
                    ),
                  ),
                ),

                _title(context, '金额 szMoney(等宽对齐)'),
                Card(
                  child: Padding(
                    padding: const EdgeInsets.symmetric(
                        horizontal: kCardPad, vertical: 4),
                    child: Column(
                      children: [
                        _fee(context, '红烧牛肉面 ×1', '¥18.00'),
                        _fee(context, '酸辣土豆丝 ×1', '¥12.00'),
                        _fee(context, '打包费', '¥1.00'),
                        _fee(context, '配送费  全额归骑手', '¥3.00',
                            noteColor: sz.earn),
                        _fee(context, '满 30 减 3  商家承担', '−¥3.00',
                            valueColor: sz.earn),
                        Divider(color: sz.line, height: 17),
                        _fee(context, '实付', '¥33.00', bold: true),
                      ],
                    ),
                  ),
                ),

                _title(context, '语义色:到手的钱 / 平台留存'),
                Card(
                  child: Padding(
                    padding: const EdgeInsets.all(kCardPad),
                    child: Column(
                      children: [
                        _flow(context, '商家实收', '¥28.50', .864, sz.earn),
                        const SizedBox(height: 12),
                        _flow(context, '骑手所得', '¥3.00', .091, sz.earn),
                        const SizedBox(height: 12),
                        _flow(context, '平台留存', '¥1.50', .045, sz.hold),
                      ],
                    ),
                  ),
                ),

                _title(context, '按钮:一屏只有一个 clay 实底'),
                Card(
                  child: Padding(
                    padding: const EdgeInsets.all(kCardPad),
                    child: Wrap(
                      spacing: 10,
                      runSpacing: 10,
                      crossAxisAlignment: WrapCrossAlignment.center,
                      children: [
                        FilledButton(
                            onPressed: () {}, child: const Text('提交订单')),
                        OutlinedButton(
                            onPressed: () {}, child: const Text('催一下')),
                        TextButton(
                            onPressed: () {}, child: const Text('这钱怎么算的')),
                      ],
                    ),
                  ),
                ),

                _title(context, '输入与开关'),
                Card(
                  child: Padding(
                    padding: const EdgeInsets.all(kCardPad),
                    child: Column(children: [
                      const TextField(
                        decoration: InputDecoration(hintText: '搜店铺、搜菜名'),
                      ),
                      const SizedBox(height: 12),
                      Row(children: [
                        Text('接单提醒', style: text.bodyMedium),
                        const Spacer(),
                        Switch(value: true, onChanged: (_) {}),
                      ]),
                    ]),
                  ),
                ),

                _title(context, '承诺卡(claySoft,全屏唯一一处)'),
                const PledgeCard(
                  title: '商家总负担 5% 封顶',
                  body: '配送费与小费 100% 归骑手,平台分文不取;账目对用户、商家、骑手三方公开。',
                ),

                _title(context, '大数卡'),
                const MoneyHeroCard(
                  label: '今日实收',
                  amountCents: 128650,
                  subtitle: '已完成 23 单 · 平台服务费 ¥64.33',
                ),

                const _ComponentSection(),
              ],
            ),
          ),
        ),
      ),
    );
  }

  Widget _title(BuildContext context, String s) => Padding(
        padding: const EdgeInsets.fromLTRB(2, 22, 2, 9),
        child: Text(s,
            style: Theme.of(context)
                .textTheme
                .labelSmall
                ?.copyWith(letterSpacing: 1.2)),
      );

  Widget _fee(BuildContext context, String k, String v,
      {bool bold = false, Color? valueColor, Color? noteColor}) {
    final sz = Theme.of(context).sz;
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 8),
      child: Row(children: [
        Expanded(
          child: Text(k,
              style: TextStyle(
                  fontSize: 13,
                  color: bold ? sz.ink : (noteColor ?? sz.inkMuted),
                  fontWeight: bold ? FontWeight.w600 : null)),
        ),
        Text(v,
            style: szMoney(
                fontSize: bold ? 18 : 14,
                fontWeight: bold ? FontWeight.w600 : FontWeight.w500,
                color: valueColor ?? sz.ink)),
      ]),
    );
  }

  Widget _flow(
      BuildContext context, String name, String amount, double pct, Color c) {
    final sz = Theme.of(context).sz;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(children: [
          Text(name, style: const TextStyle(fontSize: 13)),
          const SizedBox(width: 8),
          Text('${(pct * 100).toStringAsFixed(1)}%',
              style: szFigure(fontSize: 11, color: sz.inkMuted)),
          const Spacer(),
          Text(amount, style: szMoney(fontSize: 15, color: c)),
        ]),
        const SizedBox(height: 7),
        ClipRRect(
          borderRadius: BorderRadius.circular(2),
          child: LinearProgressIndicator(
            value: pct,
            minHeight: 4,
            color: c,
            backgroundColor: sz.surfaceAlt,
          ),
        ),
      ],
    );
  }
}

/// 共享组件层走查(任务 102):八个组件各渲染一遍,深浅都要看。
class _ComponentSection extends StatefulWidget {
  const _ComponentSection();

  @override
  State<_ComponentSection> createState() => _ComponentSectionState();
}

class _ComponentSectionState extends State<_ComponentSection> {
  String _sort = 'near';
  int _qty = 2;

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    Widget label(String s) => Padding(
          padding: const EdgeInsets.fromLTRB(2, 22, 2, 9),
          child: Text(s,
              style: Theme.of(context)
                  .textTheme
                  .labelSmall
                  ?.copyWith(letterSpacing: 1.2)),
        );

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        label('SzCard / SzSectionTitle'),
        const SzSectionTitle('费用'),
        const SizedBox(height: 9),
        SzCard(
          onTap: () {},
          child: Row(children: [
            Text('可点的卡片', style: Theme.of(context).textTheme.bodyMedium),
            const Spacer(),
            Text('→', style: TextStyle(color: sz.inkMuted)),
          ]),
        ),

        label('SzChip:筛选态 / 状态标'),
        SzCard(
          child: Wrap(spacing: 8, runSpacing: 8, children: [
            for (final (v, t) in [
              ('near', '离我近'),
              ('rating', '评分优先'),
              ('sales', '月售优先'),
            ])
              SzChip(t,
                  selected: _sort == v, onTap: () => setState(() => _sort = v)),
            SzChip('已售罄', color: sz.inkMuted, dense: true),
            SzChip('超时', color: sz.danger, dense: true),
            SzChip('已接单', color: sz.earn, dense: true),
          ]),
        ),

        label('SzStepper'),
        SzCard(
          child: Row(children: [
            Text('红烧牛肉面', style: Theme.of(context).textTheme.bodyMedium),
            const Spacer(),
            SzStepper(
              quantity: _qty,
              onAdd: () => setState(() => _qty++),
              onRemove: () => setState(() => _qty = _qty > 0 ? _qty - 1 : 0),
            ),
          ]),
        ),

        label('SzFeeRow'),
        SzCard(
          padding: const EdgeInsets.symmetric(horizontal: kCardPad, vertical: 4),
          child: Column(children: [
            const SzFeeRow(label: '打包费', amountCents: 100),
            const SzFeeRow(
                label: '配送费', note: '全额归骑手', amountCents: 300),
            const SzFeeRow(
                label: '满 30 减 3', note: '商家承担', amountCents: 300,
                negative: true),
            Divider(color: sz.line, height: 17),
            const SzFeeRow(label: '实付', amountCents: 3300, emphasized: true),
          ]),
        ),

        label('SzMoneyFlow(双口径:留存那行写清商家侧 5%)'),
        SzCard(
          padding: const EdgeInsets.symmetric(horizontal: kCardPad, vertical: 2),
          child: SzMoneyFlow(items: [
            const SzFlowItem(
                name: '商家实收',
                amountCents: 2850,
                fraction: 2850 / 3300,
                note: '菜品 + 打包 − 满减,只扣 5% 服务费'),
            const SzFlowItem(
                name: '骑手所得',
                amountCents: 300,
                fraction: 300 / 3300,
                note: '配送费 100% 归骑手,平台分文不取'),
            SzFlowItem(
              name: '平台留存',
              amountCents: 150,
              fraction: 150 / 3300,
              note: '服务器、客服与赔付池 · 按商家侧口径 ¥1.50 / ¥30.00 = 5%',
              isHold: true,
              onWhy: () {},
            ),
          ]),
        ),

        label('SzTimeline'),
        SzCard(
          child: const SzTimeline(steps: [
            SzStep('已支付', subtitle: '09:12', state: SzStepState.done),
            SzStep('商家接单',
                subtitle: '09:13 · 老陈牛肉面', state: SzStepState.done),
            SzStep('骑手取餐', subtitle: '09:26', state: SzStepState.done),
            SzStep('配送中', subtitle: '距你 1.4km', state: SzStepState.now),
            SzStep('已送达', subtitle: '预计 09:53'),
          ]),
        ),

        label('SzEmpty'),
        SzCard(
          child: SizedBox(
            height: 260,
            child: SzEmpty(
              text: '这个品类还没有商家入驻\n总负担 5% 封顶 · 入驻免费 · 没有竞价排名',
              actionLabel: '我有店,去入驻',
              onAction: () {},
            ),
          ),
        ),

        label('SzImage · 缺图占位(列表尺寸 58/62)'),
        SzCard(
          padding: EdgeInsets.zero,
          child: Column(children: [
            for (final (i, (n, c)) in const [
              ('老陈牛肉面', 'noodles'),
              ('川小妹家常菜', 'sichuan_hunan'),
              ('粤记烧腊饭', 'braised_duck'),
              ('麦香早点铺', 'baozi_congee'),
              ('云南小锅米线', 'noodles'),
              ('KFC 肯德基', 'burger_pizza'),
            ].indexed) ...[
              if (i > 0) Divider(height: 1, color: sz.line),
              Padding(
                padding: const EdgeInsets.symmetric(
                    horizontal: kCardPad, vertical: 11),
                child: Row(children: [
                  SzImage(
                      url: '',
                      name: n,
                      size: 62,
                      categoryIcon: merchantCategoryIcon(c)),
                  const SizedBox(width: 12),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(n,
                            style: TextStyle(
                                fontSize: 14.5,
                                fontWeight: FontWeight.w600,
                                color: sz.ink)),
                        const SizedBox(height: 3),
                        Text.rich(
                          TextSpan(children: [
                            TextSpan(text: '4.8', style: szFigure(fontSize: 11.5)),
                            const TextSpan(text: ' 分 · 月售 '),
                            TextSpan(text: '302', style: szFigure(fontSize: 11.5)),
                            const TextSpan(text: ' 单'),
                          ]),
                          style:
                              TextStyle(fontSize: 11.5, color: sz.inkMuted),
                        ),
                      ],
                    ),
                  ),
                ]),
              ),
            ],
          ]),
        ),

        label('SzImage · 菜品(58)与头像(48,圆形)'),
        SzCard(
          child: Wrap(spacing: 10, runSpacing: 10, children: [
            for (final n in const ['红烧牛肉面', '酸辣土豆丝', '卤蛋', '冰峰汽水'])
              SzImage(url: '', name: n, size: 58),
            for (final n in const ['杜先生', '王师傅'])
              SzImage(url: '', name: n, size: 48, circle: true),
          ]),
        ),

        label('SzCover · 店铺头图 / 房型大图(132,带品类底纹)'),
        ClipRRect(
          borderRadius: BorderRadius.circular(kRadiusMd),
          child: SzCover(
              url: '',
              name: '老陈牛肉面',
              categoryIcon: merchantCategoryIcon('noodles')),
        ),
        const SizedBox(height: 8),
        ClipRRect(
          borderRadius: BorderRadius.circular(kRadiusMd),
          child: SzCover(
              url: '',
              name: '云顶大床房',
              height: 110,
              categoryIcon: Icons.bed_outlined),
        ),

        label('SkeletonList(骨架色改用 surfaceAlt)'),
        SzCard(
          padding: EdgeInsets.zero,
          child: SizedBox(
              height: 200, child: SkeletonList(itemCount: 2)),
        ),
      ],
    );
  }
}

class _Swatches extends StatelessWidget {
  const _Swatches({required this.sz});

  final SzColors sz;

  @override
  Widget build(BuildContext context) {
    final items = <(String, Color)>[
      ('paper', sz.paper),
      ('surface', sz.surface),
      ('surfaceAlt', sz.surfaceAlt),
      ('line', sz.line),
      ('ink', sz.ink),
      ('inkMuted', sz.inkMuted),
      ('inkFaint', sz.inkFaint),
      ('clay', sz.clay),
      ('claySoft', sz.claySoft),
      ('earn', sz.earn),
      ('hold', sz.hold),
      ('danger', sz.danger),
    ];
    return Wrap(
      spacing: 8,
      runSpacing: 8,
      children: [
        for (final (name, color) in items)
          SizedBox(
            width: 76,
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Container(
                  height: 40,
                  decoration: BoxDecoration(
                    color: color,
                    border: Border.all(color: sz.line),
                    borderRadius: BorderRadius.circular(kRadiusSm),
                  ),
                ),
                const SizedBox(height: 4),
                Text(name, style: TextStyle(fontSize: 10, color: sz.inkMuted)),
                Text(
                  '#${(color.toARGB32() & 0xFFFFFF).toRadixString(16).padLeft(6, '0').toUpperCase()}',
                  style: szFigure(fontSize: 9.5, color: sz.inkMuted),
                ),
              ],
            ),
          ),
      ],
    );
  }
}
