import 'package:flutter/material.dart';
import 'package:image_picker/image_picker.dart';
import 'package:superz_shared/superz_shared.dart';

import 'appeal_page.dart';
import 'applyment_page.dart';
import 'dashboard_page.dart';
import 'messages_page.dart';
import 'reviews_page.dart';
import 'chain_page.dart';
import 'health_certs_page.dart';
import 'purchases_page.dart';
import 'license_page.dart';
import 'rules_page.dart';
import 'shop_album_page.dart';
import 'holiday_plans_dialog.dart';
import 'promo_rules_sheets.dart';
import 'staff_sheet.dart';
import 'kitchen_cam_page.dart';
import 'printer_page.dart';
import 'promises_page.dart';
import 'promo_page.dart';
import 'voucher_manage_page.dart';
import 'winback_page.dart';

/// 店铺 Tab:门头照、公告编辑、评价管理(查看 + 回复)。
class ShopTabPage extends StatefulWidget {
  const ShopTabPage({super.key, required this.api, this.onOpenFinance});

  final ApiClient api;

  /// 承诺页里「去对账页验」由外层切底部 tab
  final VoidCallback? onOpenFinance;

  @override
  State<ShopTabPage> createState() => _ShopTabPageState();
}

class _ShopTabPageState extends State<ShopTabPage> {
  Merchant? _shop;
  List<AfterSale> _afterSales = [];
  List<Map<String, dynamic>> _shopCoupons = [];
  final _announcement = TextEditingController();

  /// 非空 = 店铺信息没拉到
  String _error = '';
  bool _savingAnnouncement = false;
  bool _uploadingLogo = false;

  /// 实测出餐时长(#150)。拿不到不影响这一页 —— 承诺值该能改还是能改
  Map<String, dynamic>? _prepTime;

  /// 明厨亮灶状态(#155)。
  ///
  /// **不能改用 `shop.kitchenCam`。** `MerchantOut.kitchen_cam` 的默认值是
  /// `False`,而 `/merchants/me` 走的是 `model_validate(shop)` —— 没有那一步
  /// 聚合填充的话,装了摄像头的店会被安静地显示成「无明厨亮灶」。
  /// 这个字段是法定公示项,宁可多一个来回。
  Map<String, dynamic>? _cam;

  /// 服务端算好的待办数(`/merchants/me/todos`)。
  ///
  /// **待办数字一律从这里取,不在客户端数列表。** 评价列表服务端是
  /// `.limit(100)`(reviews.py:334),拿 `_reviews.length` 当总数,
  /// 一家 312 条评价的店会永远显示「100 条」—— 而且错得悄无声息。
  /// 这和用户端刚修掉的 `myOrders()` 默认 `limit=20` 算「累计」是同一形状。
  ///
  /// 顺带省掉一个来回:这一页原本为了在入口上显示一个数字,要拉 100 条评价。
  Map<String, dynamic> _todos = const {};

  int _todo(String key) => (_todos[key] as int?) ?? 0;

  /// 阶梯佣金(黄金位那张卡)。费率与单量都由服务端按真实时间窗聚合
  /// (`completed_counts`,auto_flow.py:1005),不是客户端拿一页列表求和。
  Map<String, dynamic>? _tier;

  @override
  void initState() {
    super.initState();
    _load();
  }

  /// 七个请求**先全部发出去**,再逐个 await —— 它们互不依赖,在网络上是并发的。
  /// 原来排成一队,店里网不好时点开「店铺」要等七个来回。
  ///
  /// 后四个是附加信息,用 [SzGather.soft] 各自兜底:拉不到只是少显示一块,
  /// 不该把整页打回错误态。
  Future<void> _load() async {
    final shopF = widget.api.myShop();
    final afterSalesF = widget.api.myAfterSales(status: 'pending');
    final couponsF = widget.api.myShopCouponBatches();
    final prepF = widget.api.merchantPrepTime();
    final camF = widget.api.merchantKitchenCam();
    final todosF = widget.api.merchantTodos();
    final tierF = widget.api.merchantCommissionTier();

    final g = SzGather();
    final shop = await g.take(shopF);
    final afterSales = await g.take(afterSalesF);
    final coupons = await g.soft(couponsF, _shopCoupons);
    final prep = await g.soft(prepF, _prepTime);
    final cam = await g.soft(camF, _cam);
    final todos = await g.soft(todosF, _todos);
    final tier = await g.soft(tierF, _tier);

    if (!mounted) return;
    if (g.failed) {
      setState(() => _error = g.message);
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(g.message)));
      return;
    }
    setState(() {
      _error = '';
      _shop = shop;
      _afterSales = afterSales!;
      _shopCoupons = coupons;
      _prepTime = prep;
      _cam = cam;
      _todos = todos;
      _tier = tier;
      if (_announcement.text.isEmpty) {
        _announcement.text = shop?.announcement ?? '';
      }
    });
  }

  Future<void> _pickLogo() async {
    if (!await PermissionRationale.ensure(context, AppPermissionKind.photos)) {
      return;
    }
    final picked = await ImagePicker().pickImage(
        source: ImageSource.gallery, maxWidth: 512, imageQuality: 85);
    if (picked == null) return;
    setState(() => _uploadingLogo = true);
    try {
      final url = await widget.api
          .uploadImage(await picked.readAsBytes(), picked.name,
              purpose: 'shop');
      await widget.api.updateShop({'logo_url': url});
      _load();
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(e.toString())));
    } finally {
      if (mounted) setState(() => _uploadingLogo = false);
    }
  }

  Future<void> _saveAnnouncement() async {
    setState(() => _savingAnnouncement = true);
    try {
      await widget.api.updateShop({'announcement': _announcement.text.trim()});
      // 存完必须重拉:入口那一行的 value 显示的是**顾客现在看到的那句话**,
      // 不重拉的话保存成功了行上还是旧文字
      await _load();
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(const SnackBar(content: Text('公告已更新')));
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(e.toString())));
    } finally {
      if (mounted) setState(() => _savingAnnouncement = false);
    }
  }

  /// 改店铺的布尔开关(自配送 / 自动接单 / 食安封签)。
  ///
  /// 这三处原本各写了一遍同样的 try-catch-toast-reload,一模一样 ——
  /// 抽出来之后加第四个开关不用再抄一次。
  Future<void> _toggleShopFlag(String field, bool value) async {
    try {
      await widget.api.updateShop({field: value});
      await _load();
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(e.toString())));
    }
  }

  /// 营业时间与歇业:一个弹层里改开门、打烊、清除,以及临时歇业。
  ///
  /// 原本是三个并排的大按钮直接摊在设置卡里 —— 每天要看的是"几点到几点",
  /// 而不是三个按钮。改成入口之后那一行只显示时间,要改才点开。
  ///
  /// **临时歇业也收进来了。** 它在正文里常驻了一条 46px,而这一页自己的注释
  /// 就写着「没歇业时显示一条『临时歇业』等于每天都在提醒一件不该常做的事」——
  /// 注释和代码打架,按注释办。歇业中时列表首条会出现「临时歇业中 + 立即恢复」,
  /// 那才是它该出现的时候(那是**当前状态**,不是入口)。
  Future<void> _editBusinessHours() async {
    await szShowSheet<void>(
      context: context,
      builder: (ctx) => SafeArea(
        child: SingleChildScrollView(
          child: Column(mainAxisSize: MainAxisSize.min, children: [
            const SizedBox(height: 8),
            const SzSectionTitle('营业时间'),
            SzEntryTile(
              icon: Icons.wb_sunny_outlined,
              title: '每天开门',
              value: _shop?.openTime.isEmpty ?? true ? '未设置' : _shop!.openTime,
              onTap: () async {
                Navigator.of(ctx).pop();
                await _pickTime(true);
              },
            ),
            const Divider(height: 1),
            SzEntryTile(
              icon: Icons.nightlight_outlined,
              title: '每天打烊',
              value:
                  _shop?.closeTime.isEmpty ?? true ? '未设置' : _shop!.closeTime,
              onTap: () async {
                Navigator.of(ctx).pop();
                await _pickTime(false);
              },
            ),
            const Divider(height: 1),
            SzEntryTile(
              icon: Icons.clear,
              title: '清除自动开关店',
              valueTone: Theme.of(ctx).sz.danger,
              value: '改回手动',
              onTap: () async {
                Navigator.of(ctx).pop();
                await _clearTimes();
              },
            ),
            const SizedBox(height: 8),
            const SzSectionTitle('临时歇业'),
            Padding(
              padding: const EdgeInsets.fromLTRB(kCardPad, 0, kCardPad, 8),
              child: Text('到点自动恢复营业 —— 不用记着回来开店',
                  style: TextStyle(
                      fontSize: kFontNote, color: Theme.of(ctx).sz.inkMuted)),
            ),
            for (final (label, h, untilClose) in const [
              ('歇 1 小时', 1, false),
              ('歇 2 小时', 2, false),
              ('歇到今天打烊', 0, true),
            ]) ...[
              const Divider(height: 1),
              SzEntryTile(
                icon: Icons.pause_circle_outline,
                title: label,
                onTap: () async {
                  Navigator.of(ctx).pop();
                  await _rest(
                      hours: untilClose ? null : h, untilClose: untilClose);
                },
              ),
            ],
            const SizedBox(height: 12),
          ]),
        ),
      ),
    );
  }

  /// 店铺公告:点开才编辑。
  ///
  /// ## 为什么收进弹层
  ///
  /// 内联输入框实测 167px(两行 TextField + 200 字 counter + 保存按钮),
  /// 而公告一个月改几次 —— 那 167px 每次打开这一页都要付。
  ///
  /// 更要紧的是旧版那两个静默的歧义:
  ///
  /// 1. `_load()` 里 `if (_announcement.text.isEmpty)` 会把**清空但没保存**
  ///    的公告用服务端旧值填回来 —— 商家看到的是「我删了它,它自己又回来了」;
  /// 2. 改完不点「保存公告」直接切 tab,内容无声丢失,没有任何提示。
  ///
  /// 弹层里保存点唯一、明确;取消就是取消。入口那一行的 `value` 显示的是
  /// **顾客此刻真正看到的那句话** —— 「元旦放假」挂到三月还没撤,这样才看得见。
  Future<void> _editAnnouncement() async {
    final shop = _shop;
    if (shop == null) return;
    // 每次打开都从服务端的当前值起步,不复用上一次没保存的草稿 ——
    // 草稿留着只会让"我到底存没存"更难判断
    _announcement.text = shop.announcement;
    await szShowSheet<void>(
      context: context,
      builder: (ctx) => SafeArea(
        child: Padding(
          padding: EdgeInsets.fromLTRB(
              kCardPad, 8, kCardPad, MediaQuery.viewInsetsOf(ctx).bottom + 12),
          child: Column(mainAxisSize: MainAxisSize.min, children: [
            const SzSectionTitle('店铺公告'),
            TextField(
              controller: _announcement,
              maxLength: 200,
              maxLines: 3,
              autofocus: true,
              decoration: const InputDecoration(
                  helperText: '显示在用户点单页顶部',
                  border: OutlineInputBorder()),
            ),
            Row(mainAxisAlignment: MainAxisAlignment.end, children: [
              TextButton(
                  onPressed: () => Navigator.of(ctx).pop(),
                  child: const Text('取消')),
              const SizedBox(width: 8),
              FilledButton(
                onPressed: _savingAnnouncement
                    ? null
                    : () async {
                        Navigator.of(ctx).pop();
                        await _saveAnnouncement();
                      },
                child: const Text('保存公告'),
              ),
            ]),
          ]),
        ),
      ),
    );
  }

  Future<void> _pickTime(bool isOpenTime) async {
    final shop = _shop!;
    final current = isOpenTime ? shop.openTime : shop.closeTime;
    TimeOfDay initial = isOpenTime
        ? const TimeOfDay(hour: 9, minute: 0)
        : const TimeOfDay(hour: 21, minute: 0);
    if (current.contains(':')) {
      final parts = current.split(':');
      initial = TimeOfDay(
          hour: int.parse(parts[0]), minute: int.parse(parts[1]));
    }
    final picked = await showTimePicker(context: context, initialTime: initial);
    if (picked == null) return;
    final hhmm =
        '${picked.hour.toString().padLeft(2, '0')}:${picked.minute.toString().padLeft(2, '0')}';
    try {
      await widget.api
          .updateShop({isOpenTime ? 'open_time' : 'close_time': hhmm});
      _load();
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(e.toString())));
    }
  }

  Future<void> _clearTimes() async {
    try {
      await widget.api.updateShop({'open_time': '', 'close_time': ''});
      _load();
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(e.toString())));
    }
  }

  /// 外卖品类:底部弹层选择,选了即改(不是资质项,即时生效)
  Future<void> _editCategory() async {
    final shop = _shop!;
    final picked = await szShowSheet<String>(
      context: context,
      showDragHandle: true,
      builder: (context) => ListView(
        children: [
          for (final entry in kMerchantCategories.entries)
            ListTile(
              leading: Text(kMerchantCategoryEmoji[entry.key] ?? '',
                  style: const TextStyle(fontSize: 22)),
              title: Text(entry.value),
              trailing: shop.category == entry.key
                  ? Icon(Icons.check, color: Theme.of(context).sz.hold)
                  : null,
              onTap: () => Navigator.pop(context, entry.key),
            ),
        ],
      ),
    );
    if (picked == null || picked == shop.category || !mounted) return;
    try {
      await widget.api.updateShop({'category': picked});
      _load();
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(e.toString())));
    }
  }

  /// 实测出餐时长条(#150):承诺值旁边的那一行。
  ///
  /// 展示口径用 **P80** 而不是平均或中位数,和骑手抢单时看到的等待预期
  /// 是**同一个数** —— 商家看到的和骑手看到的必须一致,不然商家会觉得
  /// 「我明明 15 分钟就出餐了,骑手凭什么说要等 22 分钟」。
  ///
  /// 样本不足时明说样本少,不给假装精确的数。
  Widget _measuredPrep() {
    final p = _prepTime;
    final sz = Theme.of(context).sz;
    if (p == null) return const SizedBox(height: 4);

    if (p['enough'] != true) {
      return Padding(
        padding: const EdgeInsets.only(top: 4, bottom: 2),
        child: Text(
            '近 ${p['window_days']} 天完成 ${p['samples']} 单,'
            '还不够算实测值(要 ${p['min_samples']} 单)',
            style: TextStyle(fontSize: 11.5, color: sz.inkMuted)),
      );
    }

    final p80 = (p['p80'] as num).toDouble();
    final gap = (p['gap_minutes'] as num?)?.toDouble();
    final peer = (p['peer_median_p50'] as num?)?.toDouble();

    String line;
    Color color;
    if (gap == null) {
      line = '实测:十单里有八单在 ${p80.toStringAsFixed(0)} 分钟内出餐';
      color = sz.inkMuted;
    } else if (gap > 3) {
      // 慢了就直说慢了多少。含糊其辞("略有超出")商家不会当回事
      line = '实测 ${p80.toStringAsFixed(0)} 分钟(八成的单)—— '
          '比你承诺的慢 ${gap.toStringAsFixed(0)} 分钟';
      color = sz.hold;
    } else if (gap < -3) {
      // 比承诺快也要说:承诺值调低,用户端看到的送达时间就更短,
      // 这是白拿的转化率 —— 商家自己往往想不到这一层
      line = '实测 ${p80.toStringAsFixed(0)} 分钟(八成的单)—— '
          '比承诺快 ${gap.abs().toStringAsFixed(0)} 分钟,承诺值可以往下调';
      color = sz.earn;
    } else {
      line = '实测 ${p80.toStringAsFixed(0)} 分钟(八成的单),与承诺基本吻合';
      color = sz.earn;
    }

    return Padding(
      padding: const EdgeInsets.only(top: 6, bottom: 2),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          Icon(Icons.timer_outlined, size: 14, color: color),
          const SizedBox(width: 5),
          Expanded(
            child: Text(line,
                style: TextStyle(fontSize: 12.5, height: 1.4, color: color)),
          ),
        ]),
        const SizedBox(height: 3),
        Text(
          [
            'P50 ${(p['p50'] as num).toStringAsFixed(0)} / '
                'P80 ${p80.toStringAsFixed(0)} / '
                'P95 ${(p['p95'] as num).toStringAsFixed(0)} 分钟',
            if (peer != null) '同品类中位 ${peer.toStringAsFixed(0)} 分钟(参照系,不是排名)',
          ].join(' · '),
          style: TextStyle(fontSize: 11, color: sz.inkMuted),
        ),
        const SizedBox(height: 3),
        // 红线原样显示。不写清楚,商家会担心这个数影响生意,
        // 然后开始为它经营 —— 比如菜还没好就先点「出餐」,数据反而失真
        Text('${p['never_used_for']}',
            style: TextStyle(fontSize: 11, height: 1.4, color: sz.inkMuted)),
      ]),
    );
  }

  /// 打开「平台对你的承诺」。
  ///
  /// ⚠️ **`onOpenFinance` 必须往下传。** 承诺页里那五条每条都写着「自己验:
  /// 在哪儿看得到」,其中两条(佣金封顶、配送费不抽成)的验证入口就是对账页,
  /// 而对账是底部 tab —— push 一个 FinancePage 进来会顶掉底部导航,
  /// 所以由外层切 tab。
  ///
  /// 之前这里没传:`ShopTabPage` 收下了 `onOpenFinance` 却一次没用,
  /// 于是 `promises_page.dart` 的 `widget.onOpenFinance?.call()` 是空操作 ——
  /// 商家点「去对账页验」只会把承诺页关掉,然后什么也不发生。
  /// **一个把「承诺可自验」当立身之本的平台,自验按钮是坏的。**
  void _openPromises() {
    Navigator.of(context).push(MaterialPageRoute(
        builder: (_) => MerchantPromisesPage(
            api: widget.api, onOpenFinance: widget.onOpenFinance)));
  }

  /// 顾客评价入口。
  ///
  /// **两个数字都来自服务端,一个都不在客户端数。**
  ///
  /// - 总数走 `shop.ratingCount`(身份行的 `ratingLabel` 用的就是它);
  /// - 待回复走 `todos.bad_reviews_unreplied`(近 7 天 ≤3 星未回,
  ///   与订单页待办行同一口径、同一个服务端查询)。
  ///
  /// 旧版是 `_reviews.where(...).length` 和 `_reviews.length` —— 而
  /// `/merchants/me/reviews` 服务端是 `.limit(100)`。一家 312 条评价的店
  /// 永远显示「100 条」,更早的未回复评价则根本数不到。
  Widget _reviewsTile() {
    final shop = _shop!;
    final unreplied = _todo('bad_reviews_unreplied');
    final overdue = _todo('bad_reviews_overdue');
    return SzEntryTile(
      icon: Icons.rate_review_outlined,
      title: '顾客评价',
      value: unreplied > 0
          // 超 24 小时的把紧迫性写进同一行(与订单页待办行同口径)——
          // overdue 是 unreplied 的子集,不能分两处显示成两件事
          ? (overdue > 0
              ? '$unreplied 条待回复(超24h $overdue)'
              : '$unreplied 条待回复')
          : '${shop.ratingCount} 条评价',
      valueTone: unreplied > 0 ? Theme.of(context).sz.hold : null,
      onTap: () => Navigator.of(context)
          .push(MaterialPageRoute(
              builder: (_) => MerchantReviewsPage(
                  api: widget.api, initialFilter: unreplied > 0 ? 1 : 0)))
          .then((_) => _load()),
    );
  }

  /// 堂食标识填报(#187,总局令第 123 号第十二条)。
  ///
  /// 三选一而不是开关:**「未填报」必须是个能停留的状态**,
  /// 开关只有开和关两态,做成开关就等于替没填的商家答了「无堂食」。
  /// 填了之后照样能改回未填报 —— 商家自己拿不准时,如实说不知道
  /// 比随便勾一个更好。
  Future<void> _editDineIn() async {
    final shop = _shop!;
    const options = [
      ('yes', '有堂食', '店里有餐位,顾客可以坐下来吃'),
      ('no', '无堂食', '只做外卖/自取,店里不设餐位'),
      ('unknown', '未填报', '暂不说明。用户端会照实显示「未填报」'),
    ];
    final picked = await szShowSheet<String>(
      context: context,
      showDragHandle: true,
      builder: (context) => SafeArea(
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          const Padding(
            padding: EdgeInsets.fromLTRB(16, 0, 16, 8),
            child: Text('这是市场监管总局令第 123 号要求公示的信息,'
                '会展示在用户端的商家列表和店铺页。请照实填',
                style: TextStyle(fontSize: 12.5, height: 1.4)),
          ),
          for (final (value, title, hint) in options)
            ListTile(
              title: Text(title),
              subtitle: Text(hint),
              trailing: shop.dineInStatus == value
                  ? Icon(Icons.check, color: Theme.of(context).sz.hold)
                  : null,
              onTap: () => Navigator.pop(context, value),
            ),
        ]),
      ),
    );
    if (picked == null || picked == shop.dineInStatus || !mounted) return;
    try {
      await widget.api.updateShop({'dine_in_status': picked});
      _load();
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(e.toString())));
    }
  }

  /// 承诺出餐时长(5-60 分钟)
  Future<void> _editPromiseMinutes() async {
    final shop = _shop!;
    final controller =
        TextEditingController(text: '${shop.promiseReadyMinutes}');
    final saved = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('承诺出餐时长(分钟)'),
        content: Column(mainAxisSize: MainAxisSize.min, children: [
          TextField(
            controller: controller,
            autofocus: true,
            keyboardType: TextInputType.number,
            decoration: const InputDecoration(
                helperText: '5-60 分钟;定得实在比定得短更重要',
                border: OutlineInputBorder()),
          ),
          // 填的这一刻最需要看到实测值 —— 否则他还是在闭着眼填
          if (_prepTime?['enough'] == true) ...[
            const SizedBox(height: 12),
            Text(
              '你近 ${_prepTime!['window_days']} 天的实测:'
              '八成的单在 ${(_prepTime!['p80'] as num).toStringAsFixed(0)} 分钟内出餐',
              style: TextStyle(
                  fontSize: 12.5, color: Theme.of(context).sz.inkMuted),
            ),
          ],
        ]),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(context, false),
              child: const Text('取消')),
          FilledButton(
              onPressed: () => Navigator.pop(context, true),
              child: const Text('保存')),
        ],
      ),
    );
    if (saved != true || !mounted) return;
    final minutes = int.tryParse(controller.text.trim());
    if (minutes == null || minutes < 5 || minutes > 60) {
      ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('请输入 5~60 之间的分钟数')));
      return;
    }
    try {
      await widget.api.updateShop({'promise_ready_minutes': minutes});
      _load();
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(e.toString())));
    }
  }

  /// 编辑金额类设置(起送价/打包费),输入以元为单位,存储为分。
  Future<void> _editAmount(String label, int currentCents, String field) async {
    final controller = TextEditingController(
        text: currentCents > 0 ? (currentCents / 100).toStringAsFixed(
            currentCents % 100 == 0 ? 0 : 2) : '');
    final saved = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: Text(label),
        content: TextField(
          controller: controller,
          autofocus: true,
          keyboardType: const TextInputType.numberWithOptions(decimal: true),
          decoration: const InputDecoration(
              prefixText: '¥ ', border: OutlineInputBorder()),
        ),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(context, false),
              child: const Text('取消')),
          FilledButton(
              onPressed: () => Navigator.pop(context, true),
              child: const Text('保存')),
        ],
      ),
    );
    if (saved != true || !mounted) return;
    final val = double.tryParse(controller.text.trim());
    if (val == null || val < 0 || val > 1000) {
      ScaffoldMessenger.of(context)
          .showSnackBar(const SnackBar(content: Text('请输入 0~1000 之间的金额')));
      return;
    }
    try {
      await widget.api.updateShop({field: (val * 100).round()});
      _load();
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(e.toString())));
    }
  }

  String _hhmmLocal(DateTime utc) {
    final t = utc.toLocal();
    return '${t.hour.toString().padLeft(2, '0')}:${t.minute.toString().padLeft(2, '0')}';
  }

  /// 临时歇业:关店 + 到点自动恢复(区别于手动关店忘了开)
  Future<void> _rest({int? hours, bool untilClose = false}) async {
    try {
      final shop = await widget.api.restShop(
          hours: hours, untilClose: untilClose);
      _load();
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(
          content: Text(
              '已歇业,${_hhmmLocal(shop.closedUntil!)} 自动恢复营业')));
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(e.toString())));
    }
  }

  /// 提前结束歇业 = 直接开店(服务端开店动作会清歇业标记)
  Future<void> _endRest() async {
    try {
      await widget.api.updateShop({'is_open': true});
      _load();
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(e.toString())));
    }
  }

  /// 处理售后:同意(退餐费,同意即认责从结算款扣)或拒绝,都必须给用户一句话回复
  Future<void> _processAfterSale(AfterSale sale, bool accept) async {
    final controller = TextEditingController(
        text: accept ? '非常抱歉给您带来不好的体验,已退您餐费' : '');
    final reply = await showDialog<String>(
      context: context,
      builder: (context) => AlertDialog(
        title: Text(accept ? '同意售后(退餐费,配送费已履约不退)' : '拒绝售后'),
        content: TextField(
          controller: controller,
          maxLength: 300,
          maxLines: 3,
          decoration: InputDecoration(
            labelText: '回复用户(必填)',
            hintText: accept ? '' : '说明拒绝原因,用户可向平台申诉',
            border: const OutlineInputBorder(),
          ),
        ),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(context), child: const Text('取消')),
          FilledButton(
              onPressed: () => Navigator.pop(context, controller.text.trim()),
              child: Text(accept ? '确认退款' : '确认拒绝')),
        ],
      ),
    );
    if (reply == null || reply.length < 2) return;
    try {
      await widget.api.processAfterSale(sale.id, accept: accept, reply: reply);
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(
          content: Text(accept ? '已退款并回复用户' : '已拒绝并回复用户')));
      _load();
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(e.toString())));
    }
  }


  /// 门店相册:降级成网格里的一格 + 一个独立页。
  ///
  /// 原来是内联卡:空态就要 196px,九张图更高 —— 而它是**开店时传一次**
  /// 的东西。一次性的事不该天天占着首屏。
  void _openAlbum() {
    Navigator.of(context)
        .push(MaterialPageRoute(
            builder: (_) => ShopAlbumPage(api: widget.api, shop: _shop!)))
        .then((_) => _load());
  }

  // ──────────────────────────────────────────────────────────────
  //  自上而下的分块
  // ──────────────────────────────────────────────────────────────

  /// 黄金位:**平台与你的账**。
  ///
  /// ## 为什么不是「今日营业数据」
  ///
  /// `main.dart` 的 `_todayCard()` 已经在**订单 tab**(商家开 App 的落地页)
  /// 显示「今日 N 单 · ¥X / 昨日 N 单 · ¥X」。同一个数字放两处,
  /// 迟早两处口径不一样,而这一页离数据源更远。
  ///
  /// ## 为什么不是照搬用户端的「账目透明卡」
  ///
  /// 用户端把账目提到黄金位的理由是「它没有常驻入口,埋在第 5 块」。
  /// 商家端**对账是一个底部 tab**,天然常驻 —— 那条理由在这里不成立。
  ///
  /// 所以这里放的是**对账 tab 答不了的那一半**:费率的承诺(只降不升、
  /// 5% 封顶)和规则。这两份文件原本一个在第三屏、一个在第四屏。
  ///
  /// ## 数字放什么、不放什么
  ///
  /// - **费率与本月单量:放。** 来自 `GET /merchants/me/commission-tier`,
  ///   `completed_counts` 是服务端按真实时间窗对 order_events 做的聚合,
  ///   不是客户端拿一页列表求和。费率与对账页「阶梯佣金」读同一个字段。
  /// - **「本月被抽了多少钱」:不放。** 客户端只有近 30 天日账单,按日求和
  ///   得到的是「近 30 天」却要标成「本月」—— 那正是用户端 `myOrders()`
  ///   默认 `limit=20` 算「累计」那个 bug 的形状。要放金额,
  ///   得服务端先给一个「本月服务费合计」字段。
  Widget _goldCard(Merchant shop) {
    final sz = Theme.of(context).sz;
    // 连锁的区域经理与店员进不了对账 tab(main.dart 给的是一块占位页),
    // 费率与单量也不是给他们看的 —— 但「平台对你的承诺」是这段关系本身,给
    final showMoney = shop.viewerIsOwner && !shop.viewerIsStaff;
    final rate = (_tier?['commission_rate'] as num?)?.toDouble();
    final thisMonth = _tier?['this_month_completed'] as int?;
    final toNext = _tier?['orders_to_next'] as int?;
    final nextRate = (_tier?['next_tier_rate'] as num?)?.toDouble();

    Widget entry(String label, VoidCallback onTap, {bool last = false}) =>
        Expanded(
          child: Padding(
            padding: EdgeInsets.only(right: last ? 0 : 8),
            child: Material(
              color: sz.surface,
              borderRadius: BorderRadius.circular(kRadiusSm),
              child: InkWell(
                onTap: onTap,
                borderRadius: BorderRadius.circular(kRadiusSm),
                child: Padding(
                  padding: const EdgeInsets.symmetric(vertical: 9),
                  child: Text(label,
                      maxLines: 2,
                      textAlign: TextAlign.center,
                      style: TextStyle(
                          fontSize: kFontNote,
                          height: 1.2,
                          fontWeight: FontWeight.w500,
                          color: sz.ink)),
                ),
              ),
            ),
          ),
        );

    final headline = showMoney && rate != null
        ? '${(rate * 100).toStringAsFixed(1)}%'
        : '5%';
    final headlineNote = showMoney && rate != null ? '本月费率 · 只降不升' : '封顶,只降不升';
    final sub = showMoney && thisMonth != null
        ? (toNext != null && nextRate != null
            ? '本月已完成 $thisMonth 单 · 再完成 $toNext 单,'
                '下月降至 ${(nextRate * 100).toStringAsFixed(1)}%'
            : '本月已完成 $thisMonth 单 · 已是最低档')
        : '配送费 100% 归骑手;服务费按满减后的实收计';

    return Container(
      // 全页唯一一张有色卡:和用户端「我的」页那张账目卡同一套视觉语言,
      // 「这两处说的是同一件事」不用写出来
      decoration: BoxDecoration(
        color: sz.claySoft,
        borderRadius: BorderRadius.circular(kRadiusMd),
      ),
      padding: const EdgeInsets.all(kCardPad),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
              crossAxisAlignment: CrossAxisAlignment.baseline,
              textBaseline: TextBaseline.alphabetic,
              children: [
                Text(headline,
                    style: szFigure(
                        fontSize: 20,
                        fontWeight: FontWeight.w600,
                        color: sz.clay)),
                const SizedBox(width: 8),
                Flexible(
                  child: Text(headlineNote,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: TextStyle(
                          fontSize: 15,
                          fontWeight: FontWeight.w600,
                          color: sz.ink)),
                ),
              ]),
          const SizedBox(height: 4),
          Text(sub,
              style:
                  TextStyle(fontSize: kFontNote, height: 1.4, color: sz.inkMuted)),
          const SizedBox(height: 12),
          Row(children: [
            if (showMoney)
              entry('钱怎么分的', () => widget.onOpenFinance?.call()),
            entry('平台对你的承诺', _openPromises),
            entry(
                '平台规则',
                () => Navigator.of(context).push(MaterialPageRoute(
                    builder: (_) => MerchantRulesPage(api: widget.api))),
                last: true),
          ]),
        ],
      ),
    );
  }

  /// 身份卡:门头照 + 店名 + 公告 + 顾客评价。
  ///
  /// 评价放在这张卡里,是因为身份行本来就显示「4.8 分 · 312 条评价」——
  /// 评价详情就是同一件事的下一层,不该隔着三张卡。
  Widget _identityCard(Merchant shop) {
    final theme = Theme.of(context);
    return Card(
      child: Column(mainAxisSize: MainAxisSize.min, children: [
        ListTile(
          // 门头照:缺图时是 SzImage(店名首字),右下角压相机角标 ——
          // 商家这一侧要的是"提醒你补图",所以提示不能丢
          leading: InkWell(
            onTap: _uploadingLogo ? null : _pickLogo,
            borderRadius: BorderRadius.circular(26),
            child: _uploadingLogo
                ? const SizedBox(
                    width: 52,
                    height: 52,
                    child: Center(child: CircularProgressIndicator()))
                : Stack(clipBehavior: Clip.none, children: [
                    SzImage(
                        url: shop.logoUrl.isEmpty
                            ? ''
                            : widget.api.resolveUrl(shop.logoUrl),
                        name: shop.name,
                        size: 52,
                        circle: true,
                        categoryIcon: merchantCategoryIcon(shop.category)),
                    Positioned(
                      right: -2,
                      bottom: -2,
                      child: Container(
                        padding: const EdgeInsets.all(3),
                        decoration: BoxDecoration(
                          color: theme.sz.surface,
                          shape: BoxShape.circle,
                          border: Border.all(color: theme.sz.line),
                        ),
                        child: Icon(Icons.photo_camera_outlined,
                            size: 11, color: theme.sz.inkMuted),
                      ),
                    ),
                  ]),
          ),
          title: Text(shop.name, style: theme.textTheme.titleLarge),
          subtitle: Text('${shop.ratingLabel} · ${shop.address}',
              maxLines: 1, overflow: TextOverflow.ellipsis),
        ),
        Divider(height: 1, thickness: 1, color: theme.sz.line),
        // 公告收成一条带状态值的入口。**value 显示的是顾客此刻真正看到的
        // 那句话** —— 「元旦放假」挂到三月还没撤,这样才看得见。
        //
        // 原来是内联输入框:167px(两行 TextField + 字数 counter + 保存按钮),
        // 而公告一个月改几次。更要紧的是旧版那个静默歧义 —— `_load()` 里
        // `if (_announcement.text.isEmpty)` 会把清空但没保存的公告用服务端旧值
        // 填回来,商家看到的是「我删了它,它自己又回来了」;改完不点保存直接切
        // tab 也是无声丢失。收进弹层之后保存点唯一、明确。
        SzEntryTile(
          icon: Icons.campaign_outlined,
          title: '店铺公告',
          value: shop.announcement.isEmpty ? '未设置' : shop.announcement,
          onTap: _editAnnouncement,
        ),
        Divider(height: 1, thickness: 1, color: theme.sz.line),
        _reviewsTile(),
      ]),
    );
  }

  /// 常用工具:10 个跳转型入口。
  ///
  /// 这些入口两样都给不出 —— 标题两三个字就说清了,也没有"当前是什么值"
  /// 可言。排成竖列一条 46px 只放一个词;网格四格一行 82px,
  /// **合下来 16~20px 一个,密度是列表条的两三倍。**
  ///
  /// 宽屏合成一行:`SzIconGrid` 的列数等于 items 长度,不写 [SzIconGrid.columns]
  /// 的话 5 格在 1080 下每格 216px,一个 40px 的图标居中飘着。
  Widget _toolsGrid(Merchant shop) {
    final wide = szWidthOf(context).hasSideNav;
    final items = <SzIconGridItem>[
      SzIconGridItem(
          icon: Icons.qr_code_scanner_outlined,
          label: '券核销',
          onTap: () => Navigator.of(context).push(MaterialPageRoute(
              builder: (_) => VoucherRedeemPage(api: widget.api)))),
      SzIconGridItem(
          icon: Icons.confirmation_number_outlined,
          label: '店铺券',
          badge: _todo('coupon_batches_low'),
          onTap: () => showShopCouponSheet(
              context, widget.api, () => _shopCoupons, _load)),
      SzIconGridItem(
          icon: Icons.local_activity_outlined,
          label: '团购券',
          onTap: () => Navigator.of(context).push(MaterialPageRoute(
              builder: (_) => VoucherManagePage(api: widget.api)))),
      SzIconGridItem(
          icon: Icons.print_outlined,
          label: '小票打印',
          onTap: () => Navigator.of(context).push(MaterialPageRoute(
              builder: (_) =>
                  PrinterPage(api: widget.api, shopName: shop.name)))),
      SzIconGridItem(
          icon: Icons.insights_outlined,
          label: '经营看板',
          onTap: () => Navigator.of(context).push(
              MaterialPageRoute(builder: (_) => DashboardPage(api: widget.api)))),
      SzIconGridItem(
          icon: Icons.group_outlined,
          label: '老客召回',
          onTap: () => Navigator.of(context).push(MaterialPageRoute(
              builder: (_) => MerchantWinbackPage(api: widget.api)))),
      SzIconGridItem(
          icon: Icons.qr_code_2_outlined,
          label: '专属码',
          onTap: () => Navigator.of(context).push(
              MaterialPageRoute(builder: (_) => MerchantPromoPage(api: widget.api)))),
      SzIconGridItem(
          icon: Icons.notifications_none,
          label: '消息',
          badge: _todo('messages_unread'),
          onTap: () => Navigator.of(context)
              .push(MaterialPageRoute(
                  builder: (_) => MerchantMessagesPage(api: widget.api)))
              .then((_) => _load())),
      SzIconGridItem(
          icon: Icons.support_agent_outlined,
          label: '客服',
          onTap: () => Navigator.of(context).push(
              MaterialPageRoute(builder: (_) => SupportPage(api: widget.api)))),
      SzIconGridItem(
          icon: Icons.gavel_outlined,
          label: '判责申诉',
          // 有得申诉才亮角标 —— 「有异议可申诉」不是待办,
          // 「你有 2 单还在 72 小时窗口里」才是
          badge: _todo('appealable'),
          onTap: () => Navigator.of(context)
              .push(MaterialPageRoute(
                  builder: (_) => MerchantAppealPage(api: widget.api)))
              .then((_) => _load())),
    ];
    return Card(
      child: wide
          ? SzIconGrid(items: items, columns: items.length)
          : Column(mainAxisSize: MainAxisSize.min, children: [
              SzIconGrid(items: items.sublist(0, 5)),
              SzIconGrid(items: items.sublist(5)),
            ]),
    );
  }

  /// 营业与出餐。**不加分组头** —— 卡片边界 + 12px 留白已经把分区表达完了,
  /// 六个分组头是 246px,一屏的一半。
  Widget _bizList(Merchant shop) {
    final resting = shop.closedUntil != null &&
        shop.closedUntil!.isAfter(DateTime.now().toUtc());
    return SzEntryGroup(children: [
      // 歇业中才出现,而且排**第一条**:这是当前状态,不是常驻入口。
      //
      // AppBar 那个开关只说得出「已打烊」,说不出「14:00 会自动恢复」——
      // 这两件事对商家完全不同(一个要他记着回来开店,一个不用)。
      //
      // 反过来:**没歇业时一条都不占**。旧版这里的注释就写着
      // 「没歇业时显示一条『临时歇业』等于每天都在提醒一件不该常做的事」,
      // 而下面的 else 分支恰恰在每天显示 —— 注释和代码打架。歇业选项收进
      // 「营业时间与歇业」的弹层,该有的一个没少。
      if (resting)
        SzEntryTile(
          icon: Icons.pause_circle_outline,
          title: '临时歇业中',
          value: '${_hhmmLocal(shop.closedUntil!)} 自动恢复',
          valueTone: Theme.of(context).sz.hold,
          trailing:
              TextButton(onPressed: _endRest, child: const Text('立即恢复')),
        ),
      SzEntryTile(
        icon: Icons.schedule_outlined,
        title: '营业时间与歇业',
        value: (shop.openTime.isEmpty || shop.closeTime.isEmpty)
            ? '未设置'
            : '${shop.openTime} – ${shop.closeTime}',
        valueTone: (shop.openTime.isEmpty || shop.closeTime.isEmpty)
            ? Theme.of(context).sz.hold
            : null,
        hint: '设置后到点自动开关店,临时手动开关不受影响',
        onTap: _editBusinessHours,
      ),
      SzEntryTile(
        icon: Icons.event_outlined,
        title: '节假日计划',
        value: shop.holidayPlans.isEmpty ? null : '${shop.holidayPlans.length} 条',
        // 这句留着:它讲的是两套规则谁赢,不是"这个入口是干嘛的"
        hint: '计划优先于每日营业时间',
        onTap: () => editHolidayPlans(context, widget.api, shop, _load),
      ),
      SzEntryTile(
        icon: Icons.timer_outlined,
        title: '承诺出餐时长',
        value: shop.promiseReadyMinutes > 0
            ? '${shop.promiseReadyMinutes} 分钟'
            : null,
        // hint「不设就按平台默认估算」砍掉 —— 紧接在下面的 103px 实测块
        // 才是这一条真正的说明
        onTap: _editPromiseMinutes,
      ),
      // 三条开关:**hint 一句都不砍**。实测带 Switch 的条无论有没有副标题
      // 都是 72px(那 72 是 Switch 的 48px 触控区撑的)——
      // 在这一档 hint 是免费的,砍了一分不省,只是把"商家不看就不敢开"
      // 的那句话删掉了。
      SzEntryTile(
        icon: Icons.flash_on_outlined,
        title: '自动接单',
        trailing: Switch(
          value: shop.autoAccept,
          onChanged: (v) => _toggleShopFlag('auto_accept', v),
        ),
        onTap: () => _toggleShopFlag('auto_accept', !shop.autoAccept),
        hint: '来单免确认直接进制作,拒单和缺货退款仍可手动',
      ),
      SzEntryTile(
        icon: Icons.delivery_dining_outlined,
        title: '商家自配送',
        trailing: Switch(
          value: shop.selfDelivery,
          onChanged: (v) => _toggleShopFlag('self_delivery', v),
        ),
        onTap: () => _toggleShopFlag('self_delivery', !shop.selfDelivery),
        hint: '自己送的单不进骑手池,配送费全归你',
      ),
    ]);
  }

  /// 价格与活动。券类三条已经进网格,这里只剩四条有状态值的。
  Widget _priceList(Merchant shop) => SzEntryGroup(
        // 立场表达进脚注:它讲的是平台怎么收费,是整组的前提。
        // 留着 —— 商家做满减前最会犹豫的就是「按打折前还是打折后抽」
        footnote: '满减、满赠的成本都由商家承担,'
            '而平台按满减后的实收计 5% 服务费 —— 你让利,平台跟着少收。',
        children: [
          SzEntryTile(
            icon: Icons.shopping_basket_outlined,
            title: '起送价',
            value: shop.minOrderCents > 0 ? '¥${shop.minOrderCents ~/ 100}' : '不限',
            onTap: () => _editAmount(
                '起送价(元,0 为不限)', shop.minOrderCents, 'min_order_cents'),
          ),
          SzEntryTile(
            icon: Icons.inventory_outlined,
            title: '打包费',
            value:
                shop.packingFeeCents > 0 ? yuan(shop.packingFeeCents) : '免收',
            onTap: () => _editAmount('每单打包费(元,0 为免收)',
                shop.packingFeeCents, 'packing_fee_cents'),
          ),
          SzEntryTile(
            icon: Icons.percent_outlined,
            title: '满减活动',
            value: shop.promoLabels.isEmpty
                ? '未设置'
                : shop.promoLabels.join(' · '),
            onTap: () => editPromoRules(context, widget.api, shop, _load),
          ),
          SzEntryTile(
            icon: Icons.card_giftcard_outlined,
            title: '满赠活动',
            value: shop.giftRules.isEmpty ? null : '${shop.giftRules.length} 档',
            // 「动货不动钱」是这个功能最容易被误解的地方,留着
            hint: '赠品 0 元入订单、照常扣库存,佣金不含赠品',
            onTap: () => editGiftRules(context, widget.api, shop, _load),
          ),
        ],
      );

  /// 合规与证照:五条有状态值的 + 一行门店资料网格,同一张卡。
  ///
  /// 网格作为 [SzEntryGroup] 的最后一个 child —— 组内自带发丝线,
  /// 正好表达「这几样是同一类东西的详情页」。
  Widget _complianceCard(Merchant shop) {
    final theme = Theme.of(context);
    final cam = _cam;
    final resources = <SzIconGridItem>[
      SzIconGridItem(
          icon: Icons.photo_library_outlined,
          label: '门店相册',
          onTap: _openAlbum),
      if (!shop.viewerIsStaff)
        SzIconGridItem(
            icon: Icons.badge_outlined,
            label: '店员',
            onTap: () => showStaffSheet(context, widget.api)),
      SzIconGridItem(
          icon: Icons.health_and_safety_outlined,
          label: '健康证',
          badge: _todo('health_certs_expiring'),
          onTap: () => Navigator.of(context)
              .push(MaterialPageRoute(
                  builder: (_) => HealthCertsPage(api: widget.api)))
              .then((_) => _load())),
      SzIconGridItem(
          icon: Icons.inventory_2_outlined,
          label: '进货台账',
          onTap: () => Navigator.of(context).push(
              MaterialPageRoute(builder: (_) => PurchasesPage(api: widget.api)))),
      // 店员不给连锁入口:开店、看跨店营业额都是老板的事,
      // 而且这些接口本来就按品牌所有者判权,给了也只会报错
      if (!shop.viewerIsStaff)
        SzIconGridItem(
            icon: Icons.store_mall_directory_outlined,
            label: '连锁店群',
            onTap: () => Navigator.of(context)
                .push(MaterialPageRoute(
                    builder: (_) =>
                        MerchantChainPage(api: widget.api, shop: shop)))
                .then((_) => _load())),
    ];

    return SzEntryGroup(
      // 免责立场进脚注,不是每行都说一遍
      footnote: '这几样都是监管会查的。平台只做提醒和留档,不替你担责。',
      children: [
        if (!shop.viewerIsStaff)
          SzEntryTile(
            icon: Icons.badge_outlined,
            title: '食品经营许可证',
            // 有有效期就显示它 —— 这才是商家点进来想知道的
            value: shop.licenseExpiresAt.isEmpty
                ? null
                : (shop.licenseDaysLeft != null && shop.licenseDaysLeft! <= 30
                    ? '${shop.licenseExpiresAt} 到期(还剩 ${shop.licenseDaysLeft} 天)'
                    : '${shop.licenseExpiresAt} 到期'),
            valueTone:
                shop.licenseDaysLeft != null && shop.licenseDaysLeft! <= 30
                    ? theme.sz.danger
                    : null,
            hint: '还没登记有效期 —— 登记后到期前会提醒你',
            onTap: () => Navigator.of(context)
                .push(MaterialPageRoute(
                    builder: (_) =>
                        LicenseRenewalPage(api: widget.api, shop: shop)))
                .then((_) => _load()),
          ),
        SzEntryTile(
          icon: Icons.restaurant_outlined,
          title: '堂食标识',
          value: shop.dineInLabel,
          // 未填报标红:监管要求公示,而平台不替商家猜一个填上去
          valueTone:
              shop.dineInStatus == 'unknown' ? theme.sz.danger : theme.sz.hold,
          onTap: _editDineIn,
        ),
        SzEntryTile(
          icon: Icons.videocam_outlined,
          title: '明厨亮灶',
          // 顾客看到的那个词就是这里的值。chip 换成 value:同一行右对齐、
          // 零额外高度,颜色照样区分(有=earn),但省掉容器,也不再和
          // chevron 在 trailing 里挤
          value: cam == null ? null : '${cam['listed_label']}',
          valueTone: cam != null && cam['status'] == 'active'
              ? theme.sz.earn
              : theme.sz.inkMuted,
          hint: '用你现有的摄像头就行',
          onTap: () async {
            await Navigator.of(context).push(MaterialPageRoute(
                builder: (_) => KitchenCamSetupPage(api: widget.api)));
            _load();
          },
        ),
        SzEntryTile(
          icon: Icons.verified_user_outlined,
          title: '食安封签',
          trailing: Switch(
            value: shop.foodSeal,
            onChanged: (v) => _toggleShopFlag('food_seal', v),
          ),
          onTap: () => _toggleShopFlag('food_seal', !shop.foodSeal),
          hint: '标注已贴封签,顾客收餐时能核对',
        ),
        SzEntryTile(
          icon: Icons.category_outlined,
          title: '外卖品类',
          value: '${kMerchantCategoryEmoji[shop.category] ?? ''} '
              '${merchantCategoryLabel(shop.category)}',
          onTap: _editCategory,
        ),
        SzIconGrid(
            items: resources,
            columns: szWidthOf(context).hasSideNav ? resources.length : null),
      ],
    );
  }

  /// 账号与店铺。
  ///
  /// 商店审核三件套(协议全文 / 退出登录 / 注销账号)从 `AccountLegalSection`
  /// 的三条 `ListTile`(182px)换成三条 `SzEntryTile`(141px)——
  /// 省 41px,更要紧的是**样式统一**:这一页上面全是 SzEntryTile,
  /// 底下三条却是 Material 的 ListTile,两套。
  Widget _accountList(Merchant shop) => SzEntryGroup(children: [
        // 收款资料(#204):只给店主本人 —— 接口走 money_shop 判权
        // (和提现同一口径),品牌 manager 也进不去
        if (shop.viewerIsOwner && !shop.viewerIsStaff)
          SzEntryTile(
            icon: Icons.account_balance_wallet_outlined,
            title: '收款资料',
            // 开没开通这个状态**客户端模型里没有** —— 别为了填个状态就编一个。
            // 给不出值就留解释,那正是 hint 存在的意义
            hint: '开通后货款直接进你自己的账户,不再经平台的手',
            onTap: () => Navigator.of(context).push(MaterialPageRoute(
                builder: (_) => ApplymentPage(api: widget.api, shop: shop))),
          ),
        SzEntryTile(
          icon: Icons.description_outlined,
          title: '用户协议与隐私政策',
          onTap: () => showLegalSheet(context),
        ),
        SzEntryTile(
          icon: Icons.logout,
          title: '退出登录',
          onTap: () async {
            PushService.onLogout(); // 解绑推送别名,失败静默
            await widget.api.clearSession();
            if (!mounted) return;
            Navigator.of(context).popUntil((route) => route.isFirst);
            ApiClient.onUnauthorized?.call(); // AuthGate 切回登录页
          },
        ),
        SzEntryTile(
          icon: Icons.person_off_outlined,
          title: '注销账号',
          valueTone: Theme.of(context).sz.danger,
          onTap: () => Navigator.of(context).push(MaterialPageRoute(
              builder: (_) => AccountDeletionPage(
                    api: widget.api,
                    onDeleted: (ctx) {
                      Navigator.of(ctx).popUntil((route) => route.isFirst);
                      ApiClient.onUnauthorized?.call();
                    },
                  ))),
        ),
      ]);

  /// 售后待处理。**有就置顶。**
  ///
  /// 订单页的待办行「售后待处理 N」点了就切到这一页(main.dart:788)。
  /// 改版前这一块在 y≈2170 —— 商家点了待办,落地要再滚两千多像素才找得到。
  ///
  /// 不收成一个角标:售后要的是「看到用户说了什么 + 当场同意/拒绝」,
  /// 收成角标等于多两跳。
  List<Widget> _afterSaleBlock() {
    if (_afterSales.isEmpty) return const [];
    final theme = Theme.of(context);
    return [
      Text('售后待处理(${_afterSales.length})',
          style: theme.textTheme.titleMedium
              ?.copyWith(color: theme.colorScheme.error)),
      const SizedBox(height: 4),
      for (final sale in _afterSales)
        Card(
          margin: const EdgeInsets.symmetric(vertical: 4),
          child: Padding(
            padding: const EdgeInsets.all(12),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              mainAxisSize: MainAxisSize.min,
              children: [
                Text(sale.orderSummary, style: theme.textTheme.titleSmall),
                Text('订单 ${sale.orderNo} · ${yuan(sale.totalCents)}',
                    style: theme.textTheme.bodySmall),
                const SizedBox(height: 4),
                Text('用户反馈:${sale.reason}'),
                if (sale.images.isNotEmpty)
                  Padding(
                    padding: const EdgeInsets.only(top: 6),
                    child: Wrap(spacing: 6, children: [
                      for (final img in sale.images)
                        ClipRRect(
                          borderRadius: BorderRadius.circular(6),
                          child: Image(
                              image: szNetImage(widget.api.resolveUrl(img)),
                              width: 64,
                              height: 64,
                              fit: BoxFit.cover),
                        ),
                    ]),
                  ),
                const SizedBox(height: 8),
                Row(mainAxisAlignment: MainAxisAlignment.end, children: [
                  OutlinedButton(
                    onPressed: () => _processAfterSale(sale, false),
                    child: const Text('拒绝'),
                  ),
                  const SizedBox(width: 8),
                  FilledButton(
                    onPressed: () => _processAfterSale(sale, true),
                    child: const Text('同意退款'),
                  ),
                ]),
              ],
            ),
          ),
        ),
      const SizedBox(height: 12),
    ];
  }

  @override
  Widget build(BuildContext context) {
    final shop = _shop;
    if (shop == null) {
      // 店铺信息没拉到就转圈到天荒地老,商家只能杀进程重开
      return _error.isNotEmpty
          ? SzError(error: _error, onRetry: _load)
          : const Center(child: CircularProgressIndicator());
    }
    final sz = Theme.of(context).sz;
    return RefreshIndicator(
      onRefresh: _load,
      child: ListView(
        padding: const EdgeInsets.all(16),
        // 块与块之间**只留白,不画分隔线** —— 卡片自己的 1px 描边已经在分区了,
        // 再加横线就是同一件事说两遍。发丝线只出现在同一张卡内部
        children: [
          // 有钱、有时限、且平台在等你表态的事,排在一切之前
          ..._afterSaleBlock(),
          _goldCard(shop),
          const SizedBox(height: 12),
          _identityCard(shop),
          const SizedBox(height: 12),
          _toolsGrid(shop),
          const SizedBox(height: 12),
          _bizList(shop),
          // 实测出餐时长(近 N 天的 p80 与同行对照)。
          //
          // **这不是解释,是数据** —— 商家改承诺时长时唯一该看的东西就是它。
          // 它自己会判断样本够不够,不够就照实说"还不够算实测值",
          // 所以不能塞进 hint(那一行只放得下一句话,而且配好值就不显示了)
          Padding(
            padding: const EdgeInsets.fromLTRB(kCardPad, 2, kCardPad, 0),
            child: _measuredPrep(),
          ),
          const SizedBox(height: 12),
          _priceList(shop),
          const SizedBox(height: 12),
          _complianceCard(shop),
          const SizedBox(height: 12),
          _accountList(shop),
          const SizedBox(height: 12),
          // 「电脑上管店」不是入口(点不动),是一条说明。
          //
          // 旧版给它套了一个 0 条子项的 SzEntryGroup:分组头 41 +
          // 一个 0 高度的描边空卡 + 脚注 40 = 98px,只为了说一句话
          // (而且那个空卡在屏幕上就是一条无内容的描边框)。裸文本 51px。
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: kCardPad),
            child: Text(
                '电脑上管店:网页版商家后台 chaojizan.cc/merchant,'
                '批量改菜、对账导出、大屏接单更顺手,与 App 同一账号。',
                style: TextStyle(
                    fontSize: kFontMicro, height: 1.5, color: sz.inkMuted)),
          ),
        ],
      ),
    );
  }
}
