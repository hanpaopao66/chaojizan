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
  List<Review> _reviews = [];
  List<AfterSale> _afterSales = [];
  List<Map<String, dynamic>> _shopCoupons = [];
  final _announcement = TextEditingController();

  /// 非空 = 店铺信息没拉到
  String _error = '';
  bool _savingAnnouncement = false;
  bool _uploadingLogo = false;
  bool _uploadingPhoto = false;

  /// 实测出餐时长(#150)。拿不到不影响这一页 —— 承诺值该能改还是能改
  Map<String, dynamic>? _prepTime;

  /// 明厨亮灶状态(#155)
  Map<String, dynamic>? _cam;

  @override
  void initState() {
    super.initState();
    _load();
  }

  /// 六个请求**先全部发出去**,再逐个 await —— 它们互不依赖,在网络上是并发的。
  /// 原来排成一队,店里网不好时点开「店铺」要等六个来回。
  ///
  /// 后三个是附加信息,用 [SzGather.soft] 各自兜底:拉不到只是少显示一块,
  /// 不该把整页打回错误态。
  Future<void> _load() async {
    final shopF = widget.api.myShop();
    final reviewsF = widget.api.myReviews();
    final afterSalesF = widget.api.myAfterSales(status: 'pending');
    final couponsF = widget.api.myShopCouponBatches();
    final prepF = widget.api.merchantPrepTime();
    final camF = widget.api.merchantKitchenCam();

    final g = SzGather();
    final shop = await g.take(shopF);
    final reviews = await g.take(reviewsF);
    final afterSales = await g.take(afterSalesF);
    final coupons = await g.soft(couponsF, _shopCoupons);
    final prep = await g.soft(prepF, _prepTime);
    final cam = await g.soft(camF, _cam);

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
      _reviews = reviews!;
      _afterSales = afterSales!;
      _shopCoupons = coupons;
      _prepTime = prep;
      _cam = cam;
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

  Future<void> _addShopPhoto() async {
    final shop = _shop;
    if (shop == null || shop.photoUrls.length >= 9) return;
    if (!await PermissionRationale.ensure(context, AppPermissionKind.photos)) {
      return;
    }
    final picked = await ImagePicker().pickImage(
        source: ImageSource.gallery, maxWidth: 1280, imageQuality: 85);
    if (picked == null) return;
    setState(() => _uploadingPhoto = true);
    try {
      final url = await widget.api
          .uploadImage(await picked.readAsBytes(), picked.name,
              purpose: 'gallery');
      await widget.api
          .updateShop({'photo_urls': [...shop.photoUrls, url]});
      await _load();
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(e.toString())));
    } finally {
      if (mounted) setState(() => _uploadingPhoto = false);
    }
  }

  Future<void> _removeShopPhoto(String url) async {
    final shop = _shop;
    if (shop == null) return;
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('删除这张照片?'),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(context, false),
              child: const Text('取消')),
          FilledButton(
              onPressed: () => Navigator.pop(context, true),
              child: const Text('删除')),
        ],
      ),
    );
    if (confirmed != true || !mounted) return;
    try {
      await widget.api.updateShop(
          {'photo_urls': shop.photoUrls.where((u) => u != url).toList()});
      await _load();
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(e.toString())));
    }
  }

  Future<void> _saveAnnouncement() async {
    setState(() => _savingAnnouncement = true);
    try {
      await widget.api.updateShop({'announcement': _announcement.text.trim()});
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

  /// 营业时间:一个弹窗里改开门、关门、清除。
  ///
  /// 原本是三个并排的大按钮直接摊在设置卡里 —— 每天要看的是"几点到几点",
  /// 而不是三个按钮。改成入口之后那一行只显示时间,要改才点开。
  Future<void> _editBusinessHours() async {
    await showModalBottomSheet<void>(
      context: context,
      builder: (ctx) => SafeArea(
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
            value: _shop?.closeTime.isEmpty ?? true ? '未设置' : _shop!.closeTime,
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
          const SizedBox(height: 12),
        ]),
      ),
    );
  }

  /// 临时歇业:选歇多久。
  ///
  /// 原本三个大按钮(1小时 / 2小时 / 到打烊)常驻在设置卡里 ——
  /// 而临时歇业是**偶尔**才做的事,天天摆在那儿等于每天提醒一次。
  Future<void> _pickRest() async {
    await showModalBottomSheet<void>(
      context: context,
      builder: (ctx) => SafeArea(
        child: Column(mainAxisSize: MainAxisSize.min, children: [
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
    final picked = await showModalBottomSheet<String>(
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

  /// 店铺 tab 里的明厨亮灶状态徽章。显示的是**顾客看到的那个标识** ——
  /// 商家最该知道的是"顾客现在看到我是有还是无",不是内部状态词
  Widget _kitchenCamBadge() {
    final c = _cam;
    if (c == null) return const SizedBox.shrink();
    return Align(
      alignment: Alignment.centerLeft,
      child: SzKitchenCamChip(
          has: c['status'] == 'active', label: '${c['listed_label']}'),
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
    final picked = await showModalBottomSheet<String>(
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

  @override
  Widget build(BuildContext context) {
    final shop = _shop;
    if (shop == null) {
      // 店铺信息没拉到就转圈到天荒地老,商家只能杀进程重开
      return _error.isNotEmpty
          ? SzError(error: _error, onRetry: _load)
          : const Center(child: CircularProgressIndicator());
    }
    return RefreshIndicator(
      onRefresh: _load,
      child: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          // 店铺信息卡
          Card(
            child: Padding(
              padding: const EdgeInsets.all(16),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      InkWell(
                        onTap: _uploadingLogo ? null : _pickLogo,
                        borderRadius: BorderRadius.circular(32),
                        // 店铺 logo:缺图时是 SzImage(店名首字),右下角压相机角标——
                        // 商家这一侧要的是"提醒你补图",所以提示不能丢
                        child: _uploadingLogo
                            ? const SizedBox(
                                width: 64,
                                height: 64,
                                child: Center(
                                    child: CircularProgressIndicator()))
                            : Stack(clipBehavior: Clip.none, children: [
                                SzImage(
                                    url: shop.logoUrl.isEmpty
                                        ? ''
                                        : widget.api.resolveUrl(shop.logoUrl),
                                    name: shop.name,
                                    size: 64,
                                    circle: true,
                                    categoryIcon:
                                        merchantCategoryIcon(shop.category)),
                                Positioned(
                                  right: -2,
                                  bottom: -2,
                                  child: Container(
                                    padding: const EdgeInsets.all(3),
                                    decoration: BoxDecoration(
                                      color: Theme.of(context).sz.surface,
                                      shape: BoxShape.circle,
                                      border: Border.all(
                                          color: Theme.of(context).sz.line),
                                    ),
                                    child: Icon(Icons.photo_camera_outlined,
                                        size: 12,
                                        color: Theme.of(context).sz.inkMuted),
                                  ),
                                ),
                              ]),
                      ),
                      const SizedBox(width: 12),
                      Expanded(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(shop.name,
                                style:
                                    Theme.of(context).textTheme.titleLarge),
                            Text(shop.ratingLabel,
                                style: Theme.of(context).textTheme.bodySmall),
                            Text(shop.address,
                                style: Theme.of(context).textTheme.bodySmall),
                          ],
                        ),
                      ),
                    ],
                  ),
                  const SizedBox(height: 16),
                  // 店铺公告是这一整块里**唯一真需要内联输入**的东西:
                  // 它是一段自由文本,不是"点开改个值"。其余 23 条都换成了
                  // SzEntryTile —— 原本每条是「标题 + 一个 OutlinedButton +
                  // 两行说明 + Divider(24)」,一条就要 200 多像素(#294)
                  TextField(
                    controller: _announcement,
                    maxLength: 200,
                    maxLines: 2,
                    decoration: const InputDecoration(
                        labelText: '店铺公告(显示在用户点单页顶部)',
                        border: OutlineInputBorder()),
                  ),
                  Align(
                    alignment: Alignment.centerRight,
                    child: FilledButton.tonal(
                      onPressed: _savingAnnouncement ? null : _saveAnnouncement,
                      child: Text(_savingAnnouncement ? '保存中…' : '保存公告'),
                    ),
                  ),
                ],
              ),
            ),
          ),
          const SizedBox(height: 4),

          // ── 营业 ────────────────────────────────────────────────
          SzEntryGroup(
            title: '营业',
            children: [
              SzEntryTile(
                icon: Icons.schedule_outlined,
                title: '营业时间',
                // 值就是营业时间本身 —— 商家点进来最想知道的就是它
                value: (shop.openTime.isEmpty || shop.closeTime.isEmpty)
                    ? '未设置'
                    : '${shop.openTime} – ${shop.closeTime}',
                valueTone: (shop.openTime.isEmpty || shop.closeTime.isEmpty)
                    ? Theme.of(context).sz.hold
                    : null,
                hint: '设置后到点自动开关店,临时手动开关不受影响',
                onTap: _editBusinessHours,
              ),
              // 歇业中才出现:这是**当前状态**,不是常驻入口。
              // 没歇业时显示一条「临时歇业」等于每天都在提醒一件不该常做的事
              if (shop.closedUntil != null &&
                  shop.closedUntil!.isAfter(DateTime.now().toUtc()))
                SzEntryTile(
                  icon: Icons.pause_circle_outline,
                  title: '临时歇业中',
                  value: '${_hhmmLocal(shop.closedUntil!)} 自动恢复',
                  valueTone: Theme.of(context).sz.hold,
                  trailing: TextButton(
                      onPressed: _endRest, child: const Text('立即恢复')),
                )
              else
                SzEntryTile(
                  icon: Icons.pause_circle_outline,
                  title: '临时歇业',
                  onTap: _pickRest,
                ),
              SzEntryTile(
                icon: Icons.event_outlined,
                title: '节假日计划',
                value: shop.holidayPlans.isEmpty
                    ? null
                    : '${shop.holidayPlans.length} 条',
                hint: '计划优先于每日营业时间',
                onTap: () => editHolidayPlans(context, widget.api, shop, _load),
              ),
              SzEntryTile(
                icon: Icons.delivery_dining_outlined,
                title: '商家自配送',
                trailing: Switch(
                  value: shop.selfDelivery,
                  onChanged: (v) => _toggleShopFlag('self_delivery', v),
                ),
                hint: '自己送的单不进骑手池,配送费全归你',
              ),
              SzEntryTile(
                icon: Icons.flash_on_outlined,
                title: '自动接单',
                trailing: Switch(
                  value: shop.autoAccept,
                  onChanged: (v) => _toggleShopFlag('auto_accept', v),
                ),
                hint: '来单免确认直接进制作,拒单和缺货退款仍可手动',
              ),
              SzEntryTile(
                icon: Icons.timer_outlined,
                title: '承诺出餐时长',
                value: shop.promiseReadyMinutes > 0
                    ? '${shop.promiseReadyMinutes} 分钟'
                    : null,
                hint: '不设就按平台默认估算',
                onTap: _editPromiseMinutes,
              ),
            ],
          ),
          // 实测出餐时长(近 N 天的 p80 与同行对照)。
          //
          // **这不是解释,是数据** —— 商家改承诺时长时唯一该看的东西就是它。
          // 它自己会判断样本够不够,不够就照实说"还不够算实测值",
          // 所以不能塞进 hint(那一行只放得下一句话,而且配好值就不显示了)
          Padding(
            padding: const EdgeInsets.fromLTRB(kCardPad, 2, kCardPad, 0),
            child: _measuredPrep(),
          ),
          const SizedBox(height: 4),

          // ── 价格与活动 ──────────────────────────────────────────
          SzEntryGroup(
            title: '价格与活动',
            // 立场表达进脚注:原本这句挂在「满减活动」那一条下面,
            // 但它讲的是平台怎么收费,是整组的前提
            footnote: '满减、满赠的成本都由商家承担,'
                '而平台按满减后的实收计 5% 服务费 —— 你让利,平台跟着少收。',
            children: [
              SzEntryTile(
                icon: Icons.shopping_basket_outlined,
                title: '起送价',
                value: shop.minOrderCents > 0
                    ? '¥${shop.minOrderCents ~/ 100}'
                    : '不限',
                onTap: () => _editAmount(
                    '起送价(元,0 为不限)', shop.minOrderCents, 'min_order_cents'),
              ),
              SzEntryTile(
                icon: Icons.inventory_outlined,
                title: '打包费',
                value: shop.packingFeeCents > 0
                    ? yuan(shop.packingFeeCents)
                    : '免收',
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
                value: shop.giftRules.isEmpty ? '未设置' : '${shop.giftRules.length} 档',
                // 「动货不动钱」是这个功能最容易被误解的地方,留着
                hint: '赠品 0 元入订单、照常扣库存,佣金不含赠品',
                onTap: () => editGiftRules(context, widget.api, shop, _load),
              ),
              SzEntryTile(
                icon: Icons.confirmation_number_outlined,
                title: '店铺券',
                onTap: () => showShopCouponSheet(
                    context, widget.api, () => _shopCoupons, _load),
              ),
              SzEntryTile(
                icon: Icons.local_activity_outlined,
                title: '团购券',
                onTap: () => Navigator.of(context).push(MaterialPageRoute(
                    builder: (_) => VoucherManagePage(api: widget.api))),
              ),
              SzEntryTile(
                icon: Icons.qr_code_scanner_outlined,
                title: '团购券核销',
                onTap: () => Navigator.of(context).push(MaterialPageRoute(
                    builder: (_) => VoucherRedeemPage(api: widget.api))),
              ),
            ],
          ),
          const SizedBox(height: 4),

          // ── 门店与合规 ──────────────────────────────────────────
          SzEntryGroup(
            title: '门店与合规',
            children: [
              SzEntryTile(
                icon: Icons.category_outlined,
                title: '外卖品类',
                value: '${kMerchantCategoryEmoji[shop.category] ?? ''} '
                    '${merchantCategoryLabel(shop.category)}',
                onTap: _editCategory,
              ),
              SzEntryTile(
                icon: Icons.videocam_outlined,
                title: '明厨亮灶',
                // 顾客看到的那个标识就是这里的值
                // _kitchenCamBadge 画的就是顾客看到的那个标识,直接放 trailing
                trailing: Row(mainAxisSize: MainAxisSize.min, children: [
                  _kitchenCamBadge(),
                  Icon(Icons.chevron_right,
                      size: 18, color: Theme.of(context).sz.inkFaint),
                ]),
                hint: '用你现有的摄像头就行',
                onTap: () async {
                  await Navigator.of(context).push(MaterialPageRoute(
                      builder: (_) => KitchenCamSetupPage(api: widget.api)));
                  _load();
                },
              ),
              SzEntryTile(
                icon: Icons.restaurant_outlined,
                title: '堂食标识',
                value: shop.dineInLabel,
                // 未填报标红:监管要求公示,而平台不替商家猜一个填上去
                valueTone: shop.dineInStatus == 'unknown'
                    ? Theme.of(context).sz.danger
                    : Theme.of(context).sz.hold,
                onTap: _editDineIn,
              ),
              SzEntryTile(
                icon: Icons.verified_user_outlined,
                title: '食安封签',
                trailing: Switch(
                  value: shop.foodSeal,
                  onChanged: (v) => _toggleShopFlag('food_seal', v),
                ),
                hint: '标注已贴封签,顾客收餐时能核对',
              ),
              if (!shop.viewerIsStaff)
                SzEntryTile(
                  icon: Icons.badge_outlined,
                  title: '子账号(店员)',
                  hint: '店员只能接单出餐估清,提现改价改设置仍只有你能操作',
                  onTap: () => showStaffSheet(context, widget.api),
                ),
            ],
          ),
          const SizedBox(height: 4),

          // ── 工具 ────────────────────────────────────────────────
          SzEntryGroup(
            title: '工具',
            children: [
              SzEntryTile(
                icon: Icons.print_outlined,
                title: '小票打印',
                hint: '云打印机来单自动出票,也可蓝牙直连',
                onTap: () => Navigator.of(context).push(MaterialPageRoute(
                    builder: (_) => PrinterPage(
                        api: widget.api, shopName: shop.name))),
              ),
              SzEntryTile(
                icon: Icons.qr_code_2_outlined,
                title: '专属码与海报',
                hint: '顾客扫码直达你的店,带来的客都是你自己的',
                onTap: () => Navigator.of(context).push(MaterialPageRoute(
                    builder: (_) => MerchantPromoPage(api: widget.api))),
              ),
              SzEntryTile(
                icon: Icons.group_outlined,
                title: '老客召回',
                hint: '平台只给人数不给名单,发不发券你定',
                onTap: () => Navigator.of(context).push(MaterialPageRoute(
                    builder: (_) => MerchantWinbackPage(api: widget.api))),
              ),
              SzEntryTile(
                icon: Icons.insights_outlined,
                title: '经营看板',
                hint: '趋势、时段、出餐时长、菜品贡献、流失去向',
                onTap: () => Navigator.of(context).push(MaterialPageRoute(
                    builder: (_) => DashboardPage(api: widget.api))),
              ),
              SzEntryTile(
                icon: Icons.gavel_outlined,
                title: '判责申诉',
                hint: '对售后判责或差评有异议?72 小时内申诉',
                onTap: () => Navigator.of(context).push(MaterialPageRoute(
                    builder: (_) => MerchantAppealPage(api: widget.api))),
              ),
              SzEntryTile(
                icon: Icons.verified_outlined,
                title: '平台对你的承诺',
                hint: '佣金封顶只降不升、配送费不抽成、券未核销不收费',
                onTap: () => Navigator.of(context).push(MaterialPageRoute(
                    builder: (_) => MerchantPromisesPage(api: widget.api))),
              ),
            ],
          ),
          const SizedBox(height: 16),
          // 门店相册:环境/后厨/证照实拍是最好的信任素材,展示在用户点单页「商家」标签
          Card(
            child: Padding(
              padding: const EdgeInsets.all(16),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      Text('门店相册(${shop.photoUrls.length}/9)',
                          style: Theme.of(context).textTheme.titleMedium),
                      const Spacer(),
                      TextButton.icon(
                        icon: _uploadingPhoto
                            ? const SizedBox(
                                width: 16,
                                height: 16,
                                child:
                                    CircularProgressIndicator(strokeWidth: 2))
                            : const Icon(Icons.add_photo_alternate_outlined,
                                size: 20),
                        label: Text(_uploadingPhoto ? '上传中…' : '添加'),
                        onPressed: _uploadingPhoto ||
                                shop.photoUrls.length >= 9
                            ? null
                            : _addShopPhoto,
                      ),
                    ],
                  ),
                  Text('店面环境、后厨、食材实拍,展示在用户点单页「商家」标签——真实门店是最好的信任素材',
                      style: Theme.of(context).textTheme.bodySmall),
                  const SizedBox(height: 8),
                  if (shop.photoUrls.isEmpty)
                    Container(
                      width: double.infinity,
                      padding: const EdgeInsets.symmetric(vertical: 20),
                      decoration: BoxDecoration(
                        color: Theme.of(context)
                            .colorScheme
                            .surfaceContainerHighest
                            .withValues(alpha: 0.4),
                        borderRadius: BorderRadius.circular(10),
                      ),
                      child: const Center(
                          child: Text('还没有照片,点右上角「添加」传第一张')),
                    )
                  else
                    Wrap(
                      spacing: 8,
                      runSpacing: 8,
                      children: [
                        for (final url in shop.photoUrls)
                          Stack(
                            children: [
                              ClipRRect(
                                borderRadius: BorderRadius.circular(8),
                                child: Image(image: szNetImage(widget.api.resolveUrl(url)),
                                  width: 92,
                                  height: 92,
                                  fit: BoxFit.cover,
                                  errorBuilder: (_, __, ___) => Container(
                                      width: 92,
                                      height: 92,
                                      color: Theme.of(context)
                                          .colorScheme
                                          .surfaceContainerHighest,
                                      child: const Icon(
                                          Icons.broken_image_outlined)),
                                ),
                              ),
                              Positioned(
                                top: 2,
                                right: 2,
                                child: InkWell(
                                  onTap: () => _removeShopPhoto(url),
                                  child: Container(
                                    padding: const EdgeInsets.all(2),
                                    decoration: BoxDecoration(
                                      color: Colors.black.withValues(
                                          alpha: 0.55),
                                      shape: BoxShape.circle,
                                    ),
                                    child: const Icon(Icons.close,
                                        size: 14, color: Colors.white),
                                  ),
                                ),
                              ),
                            ],
                          ),
                      ],
                    ),
                ],
              ),
            ),
          ),
          const SizedBox(height: 16),
          // 售后处理(待处理的排最前,拖着不处理伤信任)
          if (_afterSales.isNotEmpty) ...[
            Text('售后待处理(${_afterSales.length})',
                style: Theme.of(context)
                    .textTheme
                    .titleMedium
                    ?.copyWith(color: Theme.of(context).colorScheme.error)),
            const SizedBox(height: 4),
            for (final sale in _afterSales)
              Card(
                margin: const EdgeInsets.symmetric(vertical: 4),
                child: Padding(
                  padding: const EdgeInsets.all(12),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(sale.orderSummary,
                          style: Theme.of(context).textTheme.titleSmall),
                      Text('订单 ${sale.orderNo} · ${yuan(sale.totalCents)}',
                          style: Theme.of(context).textTheme.bodySmall),
                      const SizedBox(height: 4),
                      Text('用户反馈:${sale.reason}'),
                      if (sale.images.isNotEmpty)
                        Padding(
                          padding: const EdgeInsets.only(top: 6),
                          child: Wrap(spacing: 6, children: [
                            for (final img in sale.images)
                              ClipRRect(
                                borderRadius: BorderRadius.circular(6),
                                child: Image(image: szNetImage(widget.api.resolveUrl(img)),
                                    width: 64, height: 64, fit: BoxFit.cover),
                              ),
                          ]),
                        ),
                      const SizedBox(height: 8),
                      Row(
                        mainAxisAlignment: MainAxisAlignment.end,
                        children: [
                          OutlinedButton(
                            onPressed: () => _processAfterSale(sale, false),
                            child: const Text('拒绝'),
                          ),
                          const SizedBox(width: 8),
                          FilledButton(
                            onPressed: () => _processAfterSale(sale, true),
                            child: const Text('同意退款'),
                          ),
                        ],
                      ),
                    ],
                  ),
                ),
              ),
            const SizedBox(height: 12),
          ],
          // 评价升级为独立页(reviews_page.dart):筛选/图片/追评/申诉都在那边,
          // 这里只留入口。待回复数比总数更该被看到 —— 那是欠着顾客的话
          // 九张独立卡片改成两个分组(#294)。
          //
          // 之前是每个入口一张 Card + 一个带 subtitle 的 ListTile ——
          // 每条吃掉 Material 的 72dp 最小高度,外加卡片的外边距和描边,
          // 一屏只放得下 6 条。而每条其实只是一个跳转。
          //
          // 现在:能给出**当前值**的就给值(有效期、几人在册、几条未读),
          // 值和标题同一行、零额外高度;给不出值的才留一句解释。
          // 解释没删,只是挪到它真正有用的时候 —— 见 SzEntryTile 的类文档。
          SzEntryGroup(
            title: '经营',
            children: [
              SzEntryTile(
                icon: Icons.rate_review_outlined,
                title: '顾客评价',
                value: () {
                  final unreplied =
                      _reviews.where((r) => r.reply.isEmpty).length;
                  return unreplied > 0
                      ? '$unreplied 条待回复'
                      : '${_reviews.length} 条';
                }(),
                valueTone: _reviews.any((r) => r.reply.isEmpty)
                    ? Theme.of(context).sz.hold
                    : null,
                onTap: () => Navigator.of(context)
                    .push(MaterialPageRoute(
                        builder: (_) => MerchantReviewsPage(api: widget.api)))
                    .then((_) => _load()),
              ),
              SzEntryTile(
                icon: Icons.gavel_outlined,
                title: '平台规则',
                onTap: () => Navigator.of(context).push(MaterialPageRoute(
                    builder: (_) => MerchantRulesPage(api: widget.api))),
              ),
              if (!shop.viewerIsStaff)
                SzEntryTile(
                  icon: Icons.notifications_none,
                  title: '消息中心',
                  onTap: () => Navigator.of(context).push(MaterialPageRoute(
                      builder: (_) => MerchantMessagesPage(api: widget.api))),
                ),
              SzEntryTile(
                icon: Icons.support_agent_outlined,
                title: '联系平台客服',
                onTap: () => Navigator.of(context).push(MaterialPageRoute(
                    builder: (_) => SupportPage(api: widget.api))),
              ),
            ],
          ),
          if (!shop.viewerIsStaff) ...[
            const SizedBox(height: 4),
            SzEntryGroup(
              title: '证照与台账',
              // 立场表达进脚注,不是每行都说一遍
              footnote: '这几样都是监管会查的。平台只做提醒和留档,不替你担责。',
              children: [
                // 收款资料(#204):独立一页,**不进入驻流程** —— 进件资料是
                // 「能收钱之前」要的,不是「能开店之前」要的,
                // 塞进入驻只会多劝退一批人。
                //
                // 只给店主本人:接口走 money_shop 判权(和提现同一口径),
                // 品牌 manager 也进不去 —— 运营授权不等于可以改这家店的收款账户
                if (shop.viewerIsOwner)
                  SzEntryTile(
                    icon: Icons.account_balance_wallet_outlined,
                    title: '收款资料',
                    // 开没开通这个状态**客户端模型里没有** ——
                    // 别为了填个状态就编一个。给不出值就留解释,
                    // 那正是 hint 存在的意义
                    hint: '开通后货款直接进你自己的账户,不再经平台的手',
                    onTap: () => Navigator.of(context).push(MaterialPageRoute(
                        builder: (_) =>
                            ApplymentPage(api: widget.api, shop: shop))),
                  ),
                SzEntryTile(
                  icon: Icons.badge_outlined,
                  title: '食品经营许可证',
                  // 有有效期就显示它 —— 这才是商家点进来想知道的
                  value: shop.licenseExpiresAt.isEmpty
                      ? null
                      : '${shop.licenseExpiresAt} 到期',
                  hint: '还没登记有效期 —— 登记后到期前会提醒你',
                  onTap: () => Navigator.of(context)
                      .push(MaterialPageRoute(
                          builder: (_) =>
                              LicenseRenewalPage(api: widget.api, shop: shop)))
                      .then((_) => _load()),
                ),
                SzEntryTile(
                  icon: Icons.health_and_safety_outlined,
                  title: '从业人员健康证',
                  onTap: () => Navigator.of(context)
                      .push(MaterialPageRoute(
                          builder: (_) => HealthCertsPage(api: widget.api)))
                      .then((_) => _load()),
                ),
                SzEntryTile(
                  icon: Icons.inventory_2_outlined,
                  title: '进货查验台账',
                  onTap: () => Navigator.of(context).push(MaterialPageRoute(
                      builder: (_) => PurchasesPage(api: widget.api))),
                ),
                // 店员不给连锁入口:开店、看跨店营业额都是老板的事,
                // 而且这些接口本来就按品牌所有者判权,给了也只会报错
                SzEntryTile(
                  icon: Icons.store_mall_directory_outlined,
                  title: '连锁店群',
                  onTap: () => Navigator.of(context)
                      .push(MaterialPageRoute(
                          builder: (_) =>
                              MerchantChainPage(api: widget.api, shop: shop)))
                      .then((_) => _load()),
                ),
              ],
            ),
          ],
          const SizedBox(height: 4),
          // 「电脑上管店」不是入口(点不动),是一条说明 —— 用脚注而不是占一条
          SzEntryGroup(
            title: '其他',
            footnote: '电脑上管店:网页版商家后台 chaojizan.cc/merchant,'
                '批量改菜、对账导出、大屏接单更顺手,与 App 同一账号。',
            children: const [],
          ),
          const SizedBox(height: 12),
          // 商店审核三件套:协议全文 / 退出登录 / 注销账号
          AccountLegalSection(
            api: widget.api,
            onLoggedOut: (ctx) {
              Navigator.of(ctx).popUntil((route) => route.isFirst);
              ApiClient.onUnauthorized?.call(); // AuthGate 切回登录页
            },
            onDeleted: (ctx) {
              Navigator.of(ctx).popUntil((route) => route.isFirst);
              ApiClient.onUnauthorized?.call();
            },
          ),
        ],
      ),
    );
  }
}
