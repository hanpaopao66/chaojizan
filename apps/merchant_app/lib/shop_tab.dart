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
                  const Divider(height: 24),
                  Row(
                    children: [
                      const Text('营业时间'),
                      const SizedBox(width: 12),
                      OutlinedButton(
                        onPressed: () => _pickTime(true),
                        child: Text(shop.openTime.isEmpty
                            ? '开店时间'
                            : shop.openTime),
                      ),
                      const Padding(
                          padding: EdgeInsets.symmetric(horizontal: 6),
                          child: Text('至')),
                      OutlinedButton(
                        onPressed: () => _pickTime(false),
                        child: Text(shop.closeTime.isEmpty
                            ? '打烊时间'
                            : shop.closeTime),
                      ),
                      const Spacer(),
                      if (shop.openTime.isNotEmpty || shop.closeTime.isNotEmpty)
                        TextButton(
                            onPressed: _clearTimes, child: const Text('清除')),
                    ],
                  ),
                  Text(
                    shop.openTime.isNotEmpty && shop.closeTime.isNotEmpty
                        ? '已开启自动开关店:${shop.openTime} 自动营业,${shop.closeTime} 自动打烊(临时手动开关不受影响)'
                        : '设置后到点自动开店/打烊;不设置则完全手动',
                    style: Theme.of(context).textTheme.bodySmall,
                  ),
                  const SizedBox(height: 8),
                  // 临时歇业:到点自动恢复,区别于手动关店忘了开
                  if (shop.closedUntil != null &&
                      shop.closedUntil!.isAfter(DateTime.now().toUtc()))
                    Row(children: [
                      Expanded(
                        child: Text(
                          '歇业中,${_hhmmLocal(shop.closedUntil!)} 自动恢复营业',
                          style: TextStyle(
                              color: Theme.of(context).sz.hold,
                              fontWeight: FontWeight.bold),
                        ),
                      ),
                      FilledButton.tonal(
                          onPressed: () => _endRest(),
                          child: const Text('立即恢复')),
                    ])
                  else
                    Row(children: [
                      const Text('临时歇业'),
                      const SizedBox(width: 8),
                      OutlinedButton(
                          onPressed: () => _rest(hours: 1),
                          child: const Text('1小时')),
                      const SizedBox(width: 6),
                      OutlinedButton(
                          onPressed: () => _rest(hours: 2),
                          child: const Text('2小时')),
                      const SizedBox(width: 6),
                      if (shop.closeTime.isNotEmpty)
                        OutlinedButton(
                            onPressed: () => _rest(untilClose: true),
                            child: const Text('到打烊')),
                    ]),
                  const SizedBox(height: 8),
                  Row(
                    children: [
                      const Text('节假日计划'),
                      const SizedBox(width: 12),
                      Expanded(
                        child: Text(
                          shop.holidayPlans.isEmpty
                              ? '未设置'
                              : shop.holidayPlans
                                  .map(holidayPlanLabel)
                                  .join(' · '),
                          style: TextStyle(
                              color: shop.holidayPlans.isEmpty
                                  ? null
                                  : Theme.of(context).sz.hold),
                          overflow: TextOverflow.ellipsis,
                        ),
                      ),
                      TextButton(
                          onPressed: () => editHolidayPlans(
                              context, widget.api, shop, _load),
                          child: const Text('管理')),
                    ],
                  ),
                  Text('计划优先于每日营业时间:歇业日自动关店不再自动开;特殊时段日按计划时段开关',
                      style: Theme.of(context).textTheme.bodySmall),
                  const Divider(height: 24),
                  // 运营三件套:起送价 / 打包费 / 满减(全部商家自主,平台不强制)
                  Row(
                    children: [
                      const Text('起送价'),
                      const SizedBox(width: 12),
                      OutlinedButton(
                        onPressed: () => _editAmount(
                            '起送价(元,0 为不限)', shop.minOrderCents,
                            'min_order_cents'),
                        child: Text(shop.minOrderCents > 0
                            ? '¥${shop.minOrderCents ~/ 100}'
                            : '不限'),
                      ),
                      const SizedBox(width: 16),
                      const Text('打包费'),
                      const SizedBox(width: 12),
                      OutlinedButton(
                        onPressed: () => _editAmount(
                            '每单打包费(元,0 为免收)', shop.packingFeeCents,
                            'packing_fee_cents'),
                        child: Text(shop.packingFeeCents > 0
                            ? yuan(shop.packingFeeCents)
                            : '免收'),
                      ),
                    ],
                  ),
                  const SizedBox(height: 8),
                  Row(
                    children: [
                      const Text('满减活动'),
                      const SizedBox(width: 12),
                      Expanded(
                        child: Text(
                          shop.promoLabels.isEmpty
                              ? '未设置'
                              : shop.promoLabels.join(' · '),
                          style: TextStyle(
                              color: shop.promoLabels.isEmpty
                                  ? null
                                  : Theme.of(context).sz.hold),
                        ),
                      ),
                      TextButton(
                          onPressed: () => editPromoRules(
                              context, widget.api, shop, _load),
                          child: const Text('编辑')),
                    ],
                  ),
                  Text('满减成本由商家承担,平台按满减后的实收计 5% 服务费——你让利,平台跟着少收',
                      style: Theme.of(context).textTheme.bodySmall),
                  const SizedBox(height: 8),
                  Row(
                    children: [
                      const Text('满赠活动'),
                      const SizedBox(width: 12),
                      Expanded(
                        child: Text(
                          shop.giftRules.isEmpty
                              ? '未设置'
                              : shop.giftRules
                                  .map((r) =>
                                      '满${r.thresholdCents ~/ 100}赠${r.name}')
                                  .join(' · '),
                          style: TextStyle(
                              color: shop.giftRules.isEmpty
                                  ? null
                                  : Theme.of(context).sz.hold),
                        ),
                      ),
                      TextButton(
                          onPressed: () => editGiftRules(
                              context, widget.api, shop, _load),
                          child: const Text('编辑')),
                    ],
                  ),
                  Text('满赠动货不动钱:赠品 0 元入订单、照常扣库存,佣金不含赠品;赠品没库存时该档自动失效,不影响下单',
                      style: Theme.of(context).textTheme.bodySmall),
                  const SizedBox(height: 8),
                  Row(
                    children: [
                      const Text('店铺券'),
                      const SizedBox(width: 12),
                      Expanded(
                        child: Text(
                          _shopCoupons.isEmpty
                              ? '未发券'
                              : _shopCoupons
                                  .where((b) => b['active'] == true)
                                  .map((b) =>
                                      '满${b['threshold_cents'] ~/ 100}减${b['off_cents'] ~/ 100}')
                                  .join(' · '),
                          style: TextStyle(
                              color: _shopCoupons.any((b) => b['active'] == true)
                                  ? Theme.of(context).sz.hold
                                  : null),
                          overflow: TextOverflow.ellipsis,
                        ),
                      ),
                      TextButton(
                          onPressed: () => showShopCouponSheet(
                              context, widget.api, () => _shopCoupons, _load),
                          child: const Text('管理')),
                    ],
                  ),
                  Text('店铺券成本你自己出(和满减同口径,平台按券后实收计 5%),用来引流拉复购;与满减二选其一取最优,不叠加',
                      style: Theme.of(context).textTheme.bodySmall),
                  // 子账号管理:仅店主可见(店员看不到,也无权管理)
                  if (!shop.viewerIsStaff) ...[
                    const SizedBox(height: 8),
                    Row(children: [
                      const Text('子账号(店员)'),
                      const Spacer(),
                      TextButton(
                          onPressed: () => showStaffSheet(context, widget.api),
                          child: const Text('管理')),
                    ]),
                    Text('给店员开账号只能接单/出餐/估清,提现改价改设置仍只有你能操作',
                        style: Theme.of(context).textTheme.bodySmall),
                  ] else
                    Padding(
                      padding: const EdgeInsets.only(top: 8),
                      child: Text('你是本店店员:可接单出餐估清;提现/改价/改设置请联系店主',
                          style: Theme.of(context)
                              .textTheme
                              .bodySmall
                              ?.copyWith(color: Theme.of(context).sz.hold)),
                    ),
                  const Divider(height: 24),
                  // 团购(第二增长曲线:低价引流到店,核销才收 2%)
                  Row(
                    children: [
                      const Text('团购券'),
                      const Spacer(),
                      OutlinedButton.icon(
                        icon: const Icon(Icons.local_activity_outlined,
                            size: 18),
                        label: const Text('管理'),
                        onPressed: () => Navigator.of(context).push(
                            MaterialPageRoute(
                                builder: (_) =>
                                    VoucherManagePage(api: widget.api))),
                      ),
                      const SizedBox(width: 8),
                      FilledButton.tonalIcon(
                        icon: const Icon(Icons.qr_code_scanner, size: 18),
                        label: const Text('核销'),
                        onPressed: () => Navigator.of(context).push(
                            MaterialPageRoute(
                                builder: (_) =>
                                    VoucherRedeemPage(api: widget.api))),
                      ),
                    ],
                  ),
                  const Divider(height: 24),
                  Row(
                    children: [
                      const Text('外卖品类'),
                      const SizedBox(width: 12),
                      Expanded(
                          child: Text(
                              '${kMerchantCategoryEmoji[shop.category] ?? ''} '
                              '${merchantCategoryLabel(shop.category)}',
                              style: TextStyle(color: Theme.of(context).sz.hold))),
                      TextButton(
                          onPressed: _editCategory,
                          child: const Text('修改')),
                    ],
                  ),
                  Text('品类决定你出现在用户端哪个分类里,随时可改即时生效',
                      style: Theme.of(context).textTheme.bodySmall),
                  const Divider(height: 24),
                  Row(
                    children: [
                      const Text('承诺出餐时长'),
                      const SizedBox(width: 12),
                      Expanded(
                          child: Text('${shop.promiseReadyMinutes} 分钟',
                              style: TextStyle(color: Theme.of(context).sz.hold))),
                      TextButton(
                          onPressed: _editPromiseMinutes,
                          child: const Text('编辑')),
                    ],
                  ),
                  // #150:承诺值旁边直接给实测值。
                  // 在这之前商家是**闭着眼填**的 —— 平台替他的慢出餐掏钱赔付
                  // (超时安抚券由平台承担),而他零反馈,不知道自己慢多少。
                  // 平台掏钱、商家无感、问题不改,这个闭环不通治理就无从谈起
                  _measuredPrep(),
                  Text('接单后超过承诺时长未出餐,平台会催单并统计超时率(对账页可见)',
                      style: Theme.of(context).textTheme.bodySmall),
                  const Divider(height: 24),
                  Row(
                    children: [
                      const Text('商家自配送'),
                      const Spacer(),
                      Switch(
                        value: shop.selfDelivery,
                        onChanged: (v) async {
                          try {
                            await widget.api
                                .updateShop({'self_delivery': v});
                            _load();
                          } catch (e) {
                            if (!context.mounted) return;
                            ScaffoldMessenger.of(context).showSnackBar(
                                SnackBar(content: Text(e.toString())));
                          }
                        },
                      ),
                    ],
                  ),
                  Text('开启后新订单由你自己配送(不进骑手抢单池);配送费归你,'
                      '平台照常只抽餐费佣金。只影响开启之后的新订单',
                      style: Theme.of(context).textTheme.bodySmall),
                  const Divider(height: 24),
                  Row(
                    children: [
                      const Text('自动接单'),
                      const Spacer(),
                      Switch(
                        value: shop.autoAccept,
                        onChanged: (v) async {
                          try {
                            await widget.api.updateShop({'auto_accept': v});
                            _load();
                          } catch (e) {
                            if (!context.mounted) return;
                            ScaffoldMessenger.of(context).showSnackBar(
                                SnackBar(content: Text(e.toString())));
                          }
                        },
                      ),
                    ],
                  ),
                  Text('开启后来单免确认直接进入制作(仅营业中生效);'
                      '拒单、缺货退款仍可在订单页手动操作',
                      style: Theme.of(context).textTheme.bodySmall),
                  const Divider(height: 24),
                  Row(
                    children: [
                      const Text('食安封签'),
                      const Spacer(),
                      Switch(
                        value: shop.foodSeal,
                        onChanged: (v) async {
                          try {
                            await widget.api.updateShop({'food_seal': v});
                            _load();
                          } catch (e) {
                            if (!context.mounted) return;
                            ScaffoldMessenger.of(context).showSnackBar(
                                SnackBar(content: Text(e.toString())));
                          }
                        },
                      ),
                    ],
                  ),
                  Text('打包时贴一次性封签,拆封即留痕。开启后用户端显示'
                      '「商家声明使用食安封签」—— 是你的声明不是平台认证,'
                      '请确保真的在用',
                      style: Theme.of(context).textTheme.bodySmall),
                  const Divider(height: 24),
                  // 小票打印:云打印机(服务端直推)+ 蓝牙小票机(App 直连)
                  Row(
                    children: [
                      const Text('小票打印'),
                      const Spacer(),
                      OutlinedButton.icon(
                        icon: const Icon(Icons.print_outlined, size: 18),
                        label: const Text('设置'),
                        onPressed: () => Navigator.of(context).push(
                            MaterialPageRoute(
                                builder: (_) => PrinterPage(
                                    api: widget.api,
                                    shopName: shop.name))),
                      ),
                    ],
                  ),
                  Text('云打印机来单自动出票(手机不在场也能打);也可蓝牙直连通用小票机',
                      style: Theme.of(context).textTheme.bodySmall),
                  const Divider(height: 24),
                  // 拉客物料:平台没有补贴预算,商家自己带客是唯一能规模化的获客渠道
                  Row(
                    children: [
                      const Text('专属码与海报'),
                      const Spacer(),
                      OutlinedButton.icon(
                        icon: const Icon(Icons.qr_code_2_outlined, size: 18),
                        label: const Text('生成'),
                        onPressed: () => Navigator.of(context).push(
                            MaterialPageRoute(
                                builder: (_) =>
                                    MerchantPromoPage(api: widget.api))),
                      ),
                    ],
                  ),
                  Text('一张能贴能发的海报,顾客扫码直达你的店。带来的客都是你自己的',
                      style: Theme.of(context).textTheme.bodySmall),
                  const Divider(height: 24),
                  // 老客召回:平台只给人数不给名单,发不发商家自己定
                  Row(
                    children: [
                      const Text('老客召回'),
                      const Spacer(),
                      OutlinedButton.icon(
                        icon: const Icon(Icons.replay_outlined, size: 18),
                        label: const Text('查看'),
                        onPressed: () => Navigator.of(context).push(
                            MaterialPageRoute(
                                builder: (_) =>
                                    MerchantWinbackPage(api: widget.api))),
                      ),
                    ],
                  ),
                  Text('看看有多少老客好久没来了。平台只给人数不给名单,'
                      '要叫人回来就发一批券,预算你定',
                      style: Theme.of(context).textTheme.bodySmall),
                  const Divider(height: 24),
                  // 判责申诉:售后判商家责/差评,72 小时内可申诉
                  Row(
                    children: [
                      const Text('判责申诉'),
                      const Spacer(),
                      OutlinedButton.icon(
                        icon: const Icon(Icons.gavel_outlined, size: 18),
                        label: const Text('进入'),
                        onPressed: () => Navigator.of(context).push(
                            MaterialPageRoute(
                                builder: (_) =>
                                    MerchantAppealPage(api: widget.api))),
                      ),
                    ],
                  ),
                  Text('对售后判责或差评有异议?72 小时内申诉,平台人工复核',
                      style: Theme.of(context).textTheme.bodySmall),
                  const Divider(height: 24),
                  // 明厨亮灶(#155)。放在「判责申诉」之后、「经营看板」之前 ——
                  // 它属于"对外怎么呈现这家店"这一类,和看板那种自用工具不同
                  Row(
                    children: [
                      const Text('明厨亮灶'),
                      const SizedBox(width: 10),
                      Expanded(child: _kitchenCamBadge()),
                      OutlinedButton.icon(
                        icon: const Icon(Icons.videocam_outlined, size: 18),
                        label: const Text('设置'),
                        onPressed: () async {
                          await Navigator.of(context).push(MaterialPageRoute(
                              builder: (_) =>
                                  KitchenCamSetupPage(api: widget.api)));
                          _load();
                        },
                      ),
                    ],
                  ),
                  Text('把后厨实时画面开放给顾客看。用你现有的摄像头就行,'
                      '平台不卖硬件也不挑品牌',
                      style: Theme.of(context).textTheme.bodySmall),
                  const Divider(height: 24),
                  // 堂食标识(#187)。紧挨明厨亮灶:两个都是总局令第 123 号
                  // 要求在列表页公示的标识,商家该在同一个地方管
                  Row(
                    children: [
                      const Text('堂食标识'),
                      const SizedBox(width: 10),
                      Expanded(
                          child: Text(shop.dineInLabel,
                              style: TextStyle(
                                  color: shop.dineInStatus == 'unknown'
                                      ? Theme.of(context).colorScheme.error
                                      : Theme.of(context).sz.hold))),
                      TextButton(
                          onPressed: _editDineIn,
                          child: const Text('填报')),
                    ],
                  ),
                  Text('监管要求公示「有堂食/无堂食」,会显示在用户端列表和店铺页。'
                      '没填报就照实显示「未填报」—— 平台不替你猜一个填上去',
                      style: Theme.of(context).textTheme.bodySmall),
                  const Divider(height: 24),
                  // #154 经营看板:打烊后坐下来复盘的那一屏
                  Row(
                    children: [
                      const Text('经营看板'),
                      const Spacer(),
                      OutlinedButton.icon(
                        icon: const Icon(Icons.insights_outlined, size: 18),
                        label: const Text('查看'),
                        onPressed: () => Navigator.of(context).push(
                            MaterialPageRoute(
                                builder: (_) =>
                                    DashboardPage(api: widget.api))),
                      ),
                    ],
                  ),
                  Text('趋势、时段、出餐时长、菜品贡献、流失去向 —— 打烊后坐下来看',
                      style: Theme.of(context).textTheme.bodySmall),
                  const Divider(height: 24),
                  // #153 平台承诺:和骑手端那份对称,每条都能自己验
                  Row(
                    children: [
                      const Text('平台对你的承诺'),
                      const Spacer(),
                      OutlinedButton.icon(
                        icon: const Icon(Icons.verified_outlined, size: 18),
                        label: const Text('查看'),
                        onPressed: () => Navigator.of(context).push(
                            MaterialPageRoute(
                                builder: (_) => MerchantPromisesPage(
                                    api: widget.api,
                                    onOpenFinance: widget.onOpenFinance))),
                      ),
                    ],
                  ),
                  Text('佣金封顶只降不升、配送费不抽成、券未核销不收费…… 每条写了在哪儿验',
                      style: Theme.of(context).textTheme.bodySmall),
                ],
              ),
            ),
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
