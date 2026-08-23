import 'package:flutter/material.dart';
import 'package:geolocator/geolocator.dart';
import 'package:superz_shared/superz_shared.dart';

import 'address_pages.dart';
import 'identity_page.dart';
import 'main.dart' show OrderDetailPage;
import 'payment_service.dart';

/// 结算确认页(替代原来的确认弹窗):
/// 地址卡 + 送达时间(尽快/预约) + 商品明细 + 餐具/备注 + 透明分账预览 + 提交支付。
class CheckoutPage extends StatefulWidget {
  const CheckoutPage({
    super.key,
    required this.api,
    required this.merchant,
    required this.cart,
    this.groupCode = '',
  });

  final ApiClient api;
  final Merchant merchant;
  final List<CartLine> cart;
  final String groupCode; // 拼单码:发起人结算时带上,服务端原子关车

  @override
  State<CheckoutPage> createState() => _CheckoutPageState();
}

class _CheckoutPageState extends State<CheckoutPage> {
  bool _pickup = false; // 到店自取:免配送费,凭取餐码取餐

  /// 自取要走多远(#298)。null = 还没拉到 / 拉不到。
  ///
  /// 「到店自取(免配送费)」省的那几块钱,和"我得走二十分钟过去"
  /// 是同一个决定的两半。只说省钱不说路程,是把好处摊开、把代价藏起来。
  ({int distanceM, int? minutes, String source})? _walk;
  bool _walkLoading = false;
  int _tipCents = 0; // 小费:100% 归骑手,平台不抽不计佣
  Address? _address;
  bool _loadingAddress = true;
  int _tableware = 1;
  final _remark = TextEditingController();
  bool _submitting = false;
  DateTime? _scheduledAt; // null = 尽快送达
  // 券包里适用本店的券(未使用未过期)。**未达门槛的也留着**——
  // 置灰写明还差多少,比直接藏起来有用:用户要判断值不值得再加一道菜
  List<Map<String, dynamic>> _coupons = [];
  // 用户手动点过的券。null = 没手动干预过,走自动比价;
  // _couponOptOut = 用户主动点掉了,尊重他,别再自动选回来
  int? _pickedCouponId;
  bool _couponOptOut = false;

  @override
  void initState() {
    super.initState();
    _loadDefaultAddress();
    _loadCoupons();
    Analytics.track('checkout_view', {'merchant_id': widget.merchant.id});
  }

  Future<void> _loadCoupons() async {
    try {
      final list = await widget.api.myCoupons();
      final mine = list
          .cast<Map<String, dynamic>>()
          // 服务端的 usable 只判「未使用且未过期」(orders.py:674),**不含门槛**;
          // 门槛按本单金额现算,见 _judge —— 这里再筛一次就把话说死了
          .where((c) => c['usable'] == true)
          // 店铺券(funder=merchant)只在发券商家可用,平台券不限店
          .where((c) =>
              c['funder'] != 'merchant' ||
              c['merchant_id'] == widget.merchant.id)
          .toList()
        ..sort((a, b) =>
            (b['amount_cents'] as int).compareTo(a['amount_cents'] as int));
      if (mounted) setState(() => _coupons = mine);
    } catch (_) {}
  }

  Future<void> _loadDefaultAddress() async {
    try {
      final list = await widget.api.addresses();
      if (mounted) {
        setState(() {
          _address = list.where((a) => a.isDefault).firstOrNull ??
              list.firstOrNull;
          _loadingAddress = false;
        });
        await _refreshFee();
      }
    } catch (_) {
      if (mounted) setState(() => _loadingAddress = false);
    }
  }

  Future<void> _pickAddress() async {
    final picked = await Navigator.of(context).push<Address>(MaterialPageRoute(
        builder: (_) => AddressBookPage(api: widget.api, selectMode: true)));
    if (picked != null && mounted) {
      setState(() => _address = picked);
      await _refreshFee();
    }
  }

  int get _foodCents => widget.cart
      .fold(0, (sum, line) => sum + line.unitCents * line.quantity);

  /// 打包费 = 店铺「每单打包费」+ 菜品级打包费(按份数另加)。
  /// 与 server/app/routers/orders.py:299-306、:429 同口径。
  /// 券门槛判的就是这个数,客户端少算一分,能用的券就会被误判成不能用
  int get _packingCents =>
      widget.merchant.packingFeeCents +
      widget.cart.fold(
          0, (sum, l) => sum + (l.dish.packingFeeCents ?? 0) * l.quantity);

  /// 券门槛与抵扣的计算基数:餐费 + 打包费(orders.py:480 的 food_cents + packing)
  int get _couponBasis => _foodCents + _packingCents;

  /// 满减(与后端同规则:门槛按餐费判、封顶按餐费+打包,取满足门槛的最大一档)。
  /// 服务端是最终口径,这里仅预估展示
  int get _manjianCents {
    var off = 0;
    final basis = _couponBasis;
    final rules = [...widget.merchant.promoRules]
      ..sort((a, b) => a.thresholdCents.compareTo(b.thresholdCents));
    for (final r in rules) {
      if (_foodCents >= r.thresholdCents && r.thresholdCents > 0) {
        off = r.offCents < basis ? r.offCents : basis; // orders.py:437 的封顶
      }
    }
    return off;
  }

  /// 判一张券在本单能不能用、能减多少。
  ///
  /// **必须与 server/app/routers/orders.py:474-501 同口径**,差一点就是提交时 409:
  /// 结算页写着"已省 10 元",付款那一刻被打回「未达券的使用门槛」——
  /// 这种事发生一次,用户就不信第二次了。
  _CouponVerdict _judge(Map<String, dynamic> c) {
    final basis = _couponBasis;
    final manjian = _manjianCents;
    final amount = c['amount_cents'] as int;
    final minSpend = c['min_spend_cents'] as int? ?? 0;
    if (c['funder'] == 'merchant') {
      // 店铺券:门槛按 餐费+打包 判(orders.py:480)
      if (basis < minSpend) {
        return _CouponVerdict.no('还差${_money(minSpend - basis)}');
      }
      final shopOff = amount < basis ? amount : basis;
      // 店铺券与满减二选其一取最优,不叠加;不优于满减的服务端直接 409(orders.py:485)
      if (shopOff <= manjian) return const _CouponVerdict.beaten();
      return _CouponVerdict.ok(merchantOff: shopOff, platformOff: 0);
    }
    // 平台券:门槛按 餐费+打包-满减 判 —— orders.py:493 里的 discount
    // 走到这一步就是满减档本身(店铺券分支没被走到)
    final left = basis - manjian;
    if (left < minSpend) {
      return _CouponVerdict.no('还差${_money(minSpend - left)}');
    }
    final off = amount < left ? amount : left;
    // 服务端还会再扣掉首单立减(orders.py:498 的 subsidy),那笔平台补贴客户端判不了。
    // 所以这里给的是抵扣**上限**:真实抵扣只会更少,不会因此 409
    if (off <= 0) return const _CouponVerdict.no('本单无可抵扣');
    return _CouponVerdict.ok(merchantOff: manjian, platformOff: off);
  }

  /// 本单实际生效的券。**每次取用时现算** —— 金额一变(改数量、删菜、
  /// 切自取/配送、改小费)结论跟着变,不会停在初始化那一刻
  Map<String, dynamic>? get _activeCoupon {
    if (_couponOptOut) return null;
    final picked =
        _coupons.where((c) => c['id'] == _pickedCouponId).firstOrNull;
    // 手选的券若因金额变化不再可用,让位给最优的那张 ——
    // 不能带着一张必然 409 的券去提交
    if (picked != null && _judge(picked).usable) return picked;
    return _bestCoupon();
  }

  /// 自动选券:和满减比价,选**用户实际省得最多**的那张。
  ///
  /// 不能再按面额倒序取第一张 —— 面额大 ≠ 省得多。一张 10 元店铺券碰上 12 元满减,
  /// 服务端 orders.py:485 会直接 409「本单满减已优于该店铺券」。
  /// 基准线取满减额、只在**严格更优**时才换券,判的就和服务端是同一件事;
  /// 打平也不换,白烧一张券换不来一分钱。
  Map<String, dynamic>? _bestCoupon() {
    Map<String, dynamic>? best;
    var bestOff = _manjianCents; // 基准线:不用券也有满减
    for (final c in _coupons) {
      final v = _judge(c);
      if (v.usable && v.totalOff > bestOff) {
        best = c;
        bestOff = v.totalOff;
      }
    }
    return best;
  }

  /// 生效的优惠拆分:没券可用时就是满减本身
  _CouponVerdict _verdictOf(Map<String, dynamic>? coupon) => coupon == null
      ? _CouponVerdict.ok(merchantOff: _manjianCents, platformOff: 0)
      : _judge(coupon);

  /// 展示顺序:能用的在前(面额大的优先),不能用的沉底 ——
  /// 排序按**当前金额**算,加减菜之后顺序自己会变
  List<Map<String, dynamic>> get _sortedCoupons {
    final list = [..._coupons];
    list.sort((a, b) {
      final ua = _judge(a).usable, ub = _judge(b).usable;
      if (ua != ub) return ua ? -1 : 1;
      return (b['amount_cents'] as int).compareTo(a['amount_cents'] as int);
    });
    return list;
  }

  Widget _couponChip(
      ThemeData theme, Map<String, dynamic> c, int? activeId) {
    final v = _judge(c);
    final minSpend = c['min_spend_cents'] as int? ?? 0;
    // 「无门槛」以前是写死的文案,现在按券的真实门槛写。
    // 一张满 50 减 10 的券被标成"无门槛",用户到付款时才知道用不了
    final gate = minSpend > 0 ? '满${_money(minSpend)}可用' : '无门槛';
    return ChoiceChip(
      label: Text(
        '${_money(c['amount_cents'] as int)} $gate'
        '${v.usable ? '' : ' · ${v.reason}'}',
        style: v.usable ? null : TextStyle(color: theme.sz.inkMuted),
      ),
      selected: activeId == c['id'],
      // onSelected 传 null 就是 Flutter 的禁用态(置灰);不可用的券留在原位
      // 但点不动 —— 藏起来用户就不知道自己差多少
      onSelected: v.usable
          ? (sel) => setState(() {
                _pickedCouponId = sel ? c['id'] as int : null;
                _couponOptOut = !sel;
              })
          : null,
    );
  }

  String _couponHint(Map<String, dynamic>? active) {
    if (active != null) {
      // 自动选的和用户手选的要分开说 —— 把用户自己的选择说成"帮你选的"很讨嫌
      return active['id'] == _pickedCouponId
          ? '按你选的这张算,点一下可取消'
          : '已按本单金额比过价,自动选了最省的一张,点一下可取消';
    }
    if (_couponOptOut) return '已取消用券,点上面的券可以重新选';
    // 走到这儿说明一张都用不上:要么没够门槛,要么满减本来就更划算
    return _coupons.any((c) => _judge(c).beatenByManjian)
        ? '本单满减比手上的券更划算,券先留着'
        : '本单暂无可用券 —— 灰掉的券上写着还差多少';
  }

  /// 满赠(与后端同规则:取满足门槛的最高一档)。库存不足时服务端会自动跳过
  GiftRule? get _giftRule {
    GiftRule? hit;
    final rules = [...widget.merchant.giftRules]
      ..sort((a, b) => a.thresholdCents.compareTo(b.thresholdCents));
    for (final r in rules) {
      if (_foodCents >= r.thresholdCents) hit = r;
    }
    return hit;
  }

  bool get _belowMinOrder => _foodCents < widget.merchant.minOrderCents;

  /// 服务端算好的配送费与拆分。
  ///
  /// **不在客户端复算**。原先这里照抄了 pricing.py 的距离公式,
  /// 但夜间加价、恶劣天气、上门难度都在服务端判 —— 客户端算的那个数
  /// 在晚上九点之后和下雨天**是错的**,用户到付款那一步才发现变贵了。
  Map<String, dynamic>? _feePreview;
  bool _toDoor = true;

  int? get _feeCents {
    if (_pickup) return 0; // 自取免配送费
    if (_address == null) return null;
    final p = _feePreview;
    return p == null ? null : p['fee_cents'] as int?;
  }

  /// 拉一次配送费预览。地址、自取、送上门开关任一变化都要重拉。
  Future<void> _refreshFee() async {
    final a = _address;
    if (_pickup || a == null) {
      if (mounted) setState(() => _feePreview = null);
      return;
    }
    try {
      final p = await widget.api.previewDeliveryFee(
        merchantId: widget.merchant.id,
        lat: a.lat, lng: a.lng,
        floor: a.floor, hasElevator: a.hasElevator, toDoor: _toDoor,
      );
      if (mounted) setState(() => _feePreview = p);
    } catch (_) {
      // 拉不到就不显示,别拿一个可能错的数糊弄用户
      if (mounted) setState(() => _feePreview = null);
    }
  }

  /// 拉一次「走过去要多远」。只在**切到自取那一刻**拉:
  /// 每次进结算页都拉是白费配额 —— 大多数人选的是配送。
  Future<void> _refreshWalk() async {
    if (_walk != null || _walkLoading) return; // 同一家店只拉一次
    setState(() => _walkLoading = true);
    try {
      final me = await Geolocator.getLastKnownPosition() ??
          await Geolocator.getCurrentPosition();
      final gcj = wgs84ToGcj02(me.latitude, me.longitude);
      final r = await widget.api.geoRoute(
        fromLat: gcj.lat,
        fromLng: gcj.lng,
        toLat: widget.merchant.lat,
        toLng: widget.merchant.lng,
        mode: 'walk',
      );
      if (mounted) setState(() => _walk = r);
    } catch (_) {
      // 没给定位权限、定位超时、接口挂了 —— 都只是"这行不显示",
      // 不弹窗、不拦下单。他本来就知道自己要去哪家店
    } finally {
      if (mounted) setState(() => _walkLoading = false);
    }
  }

  /// 从现在起 [minutes] 分钟后是几点几分,形如 `18:40`。
  String _clockAfter(int minutes) {
    final t = DateTime.now().add(Duration(minutes: minutes));
    return '${t.hour.toString().padLeft(2, '0')}:'
        '${t.minute.toString().padLeft(2, '0')}';
  }

  /// 自取卡上那句「走过去大概多远」。
  String? get _walkLine {
    final w = _walk;
    if (w == null) return null;
    final about = w.source == 'straight' ? '约' : '';
    // 时长拿不到就只说距离 —— 编一个时间出来,用户照着它出门,迟到的是他
    return w.minutes == null
        ? '离你$about ${distanceLabel(w.distanceM.toDouble())},走过去'
        : '走过去$about ${w.minutes} 分钟'
            '(${distanceLabel(w.distanceM.toDouble())})';
  }

  /// 配送费拆分的逐行展示。基础项不重复列(上面那行就是总额),
  /// 只把**加价的原因**摊开 —— 顾客要知道多出来的钱是为什么。
  List<Widget> _feeBreakdownRows(ThemeData theme) {
    final p = _feePreview;
    if (p == null) return const [];
    final parts = (p['parts'] as Map?)?.cast<String, dynamic>() ?? const {};
    final labels = (p['labels'] as Map?)?.cast<String, dynamic>() ?? const {};
    final rows = <Widget>[];
    for (final key in parts.keys) {
      final v = parts[key] as int? ?? 0;
      if (key == 'base' || v <= 0) continue;
      rows.add(Padding(
        padding: const EdgeInsets.only(left: 12, bottom: 2),
        child: Row(children: [
          Expanded(child: Text('· ${labels[key] ?? key}',
              style: TextStyle(fontSize: 12, color: theme.sz.inkMuted))),
          const SizedBox(width: 10),
          Text('¥${(v / 100).toStringAsFixed(2)}',
              style: TextStyle(fontSize: 12, color: theme.sz.inkMuted)),
        ]),
      ));
    }
    return rows;
  }

  /// 送上门 / 送到楼下。只在**这个地址真的会产生上门难度费**时才出现 ——
  /// 1 楼或有电梯的地址不该被问这个问题。
  Widget? _toDoorCard(ThemeData theme) {
    final p = _feePreview;
    if (_pickup || p == null) return null;
    final doorFee = p['door_fee_cents'] as int? ?? 0;
    if (doorFee <= 0) return null;
    final a = _address;
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('${a?.floor} 楼无电梯,要送上门吗?',
                style: theme.textTheme.titleSmall),
            const SizedBox(height: 2),
            Text('这笔钱**全额归骑手** —— 背着餐爬 ${a?.floor} 层楼,'
                '不该由他自己承担。选送到楼下则不收。',
                style: TextStyle(fontSize: 12, color: theme.sz.inkMuted)),
            const SizedBox(height: 8),
            SegmentedButton<bool>(
              segments: [
                ButtonSegment(
                    value: true,
                    label: Text('送上门 +¥${(doorFee / 100).toStringAsFixed(0)}')),
                const ButtonSegment(value: false, label: Text('送到楼下 免费')),
              ],
              selected: {_toDoor},
              showSelectedIcon: false,
              onSelectionChanged: (v) {
                setState(() => _toDoor = v.first);
                _refreshFee();
              },
            ),
          ],
        ),
      ),
    );
  }

  /// 预计送达分钟数,**由服务端给**(#295)。
  ///
  /// 这里原本是自己算的:直线距离 × 一个常量速度。而下单成功后订单详情
  /// 显示的是服务端算的数(腾讯骑行路网 + 商家出餐分位数 + 忙碌模式)——
  /// 于是结算页说 30 分钟、付完款变成 42 分钟。
  ///
  /// 新用户不会想到这是两套算法,他只会记住这个 App 说话不算数。
  /// 同一件事在同一分钟内给出两个答案,是最伤信任的一种不一致。
  ///
  /// 拿不到就返回 null、**整行不显示** —— 而不是退回直线自己编一个。
  /// 「大概 30 分钟」和「不知道」的区别新手分不出来,但他会记住你说错了。
  int? get _etaMin {
    if (_pickup) return null;
    return _feePreview?['eta_minutes'] as int?;
  }

  Future<void> _submit() async {
    final address = _address;
    if (!_pickup && address == null) {
      ScaffoldMessenger.of(context)
          .showSnackBar(const SnackBar(content: Text('请先选择收货地址')));
      return;
    }
    setState(() => _submitting = true);
    try {
      final remark = [
        if (_remark.text.trim().isNotEmpty) _remark.text.trim(),
        '餐具 $_tableware 份',
      ].join(';');
      final order = await widget.api.createOrder(
        merchantId: widget.merchant.id,
        items: widget.cart.map((l) => l.toOrderItem()).toList(),
        address: _pickup ? null : address,
        pickup: _pickup,
        remark: remark,
        scheduledAt: _scheduledAt,
        tipCents: _pickup ? 0 : _tipCents,
        // 顾客选的送上门/送楼下要跟着下单一起走 —— 只在预览里选了不算数
        toDoor: _toDoor,
        // 提交的是**此刻**判定生效的那张券,不是初始化时挑的
        couponId: _activeCoupon?['id'] as int?,
        groupCode: widget.groupCode,
      );
      if (!mounted) return;
      final paid = await payOrder(widget.api, order, context);
      if (!mounted) return;
      // 下单成功:清掉该店云端购物车(已成单,不该再恢复)
      widget.api.putCart(widget.merchant.id, const []).catchError((_) {});
      // 支付完成:栈收敛为 首页 → 订单详情
      Navigator.of(context).pushAndRemoveUntil(
        MaterialPageRoute(
            builder: (_) =>
                OrderDetailPage(api: widget.api, orderNo: paid.orderNo)),
        (route) => route.isFirst,
      );
    } catch (e) {
      if (!mounted) return;
      final msg = e.toString();
      // 酒类需实名:直接给去认证的入口,别让用户自己找
      if (msg.contains('实名认证')) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(
          content: Text(msg),
          duration: const Duration(seconds: 6),
          action: SnackBarAction(
            label: '去实名',
            onPressed: () => Navigator.of(context).push(MaterialPageRoute(
                builder: (_) => IdentityPage(api: widget.api))),
          ),
        ));
      } else {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text(msg)));
      }
    } finally {
      if (mounted) setState(() => _submitting = false);
    }
  }

  /// 预约送达时间选择:今天/明天 + 时刻;至少提前 30 分钟(与服务端一致)
  Future<void> _pickScheduledTime() async {
    final now = DateTime.now();
    final date = await showDatePicker(
      context: context,
      initialDate: now,
      firstDate: now,
      lastDate: now.add(const Duration(days: 2)),
      helpText: '选择送达日期',
    );
    if (date == null || !mounted) return;
    final time = await showTimePicker(
      context: context,
      initialTime: TimeOfDay.fromDateTime(now.add(const Duration(hours: 1))),
      helpText: '选择送达时刻',
    );
    if (time == null || !mounted) return;
    final picked =
        DateTime(date.year, date.month, date.day, time.hour, time.minute);
    if (picked.isBefore(now.add(const Duration(minutes: 30)))) {
      ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('预约时间至少要在 30 分钟之后')));
      return;
    }
    setState(() => _scheduledAt = picked);
  }

  String get _scheduleLabel {
    final t = _scheduledAt;
    if (t == null) return '尽快送达';
    final now = DateTime.now();
    final day =
        (t.day == now.day && t.month == now.month) ? '今天' : '${t.month}/${t.day}';
    return '预约 $day ${t.hour.toString().padLeft(2, '0')}:${t.minute.toString().padLeft(2, '0')}';
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final fee = _feeCents;
    final eta = _etaMin;
    final packing = _packingCents;
    // 券与满减的取舍在这里定,下面所有金额都从这一份拆分里取,不各算各的
    final coupon = _activeCoupon;
    final verdict = _verdictOf(coupon);
    // 商家承担:满减,或取代了满减的店铺券(服务端 orders.py:490 就是取代不叠加)
    final merchantOff = verdict.merchantOff;
    final platformOff = verdict.platformOff; // 平台承担:平台券
    final shopCoupon = coupon != null && coupon['funder'] == 'merchant';
    // 首单立减由服务端判定,这里不预估(下单后订单明细会显示)
    final tip = _pickup ? 0 : _tipCents;
    final total = fee == null
        ? null
        : _foodCents + packing - merchantOff + fee + tip - platformOff;
    final commission =
        ((_foodCents + packing - merchantOff) * widget.merchant.commissionRate)
            .round();

    return SzPageScaffold(
      appBar: AppBar(title: const Text('确认订单')),
      body: ListView(
        padding: const EdgeInsets.all(12),
        children: [
          // 配送方式:外卖配送 / 到店自取(免配送费)
          Card(
            child: Padding(
              padding: const EdgeInsets.all(12),
              child: SegmentedButton<bool>(
                segments: const [
                  ButtonSegment(
                      value: false,
                      icon: Icon(Icons.electric_moped_outlined),
                      label: Text('外卖配送')),
                  ButtonSegment(
                      value: true,
                      icon: Icon(Icons.storefront_outlined),
                      label: Text('到店自取(免配送费)')),
                ],
                selected: {_pickup},
                onSelectionChanged: (v) {
                  setState(() => _pickup = v.first);
                  _refreshFee();
                  if (v.first) _refreshWalk();
                },
              ),
            ),
          ),
          const SizedBox(height: 8),
          // 地址卡(配送) / 门店卡(自取)
          if (_pickup)
            Card(
              child: ListTile(
                leading: Icon(Icons.storefront,
                    color: theme.colorScheme.primary),
                title: Text(widget.merchant.name),
                subtitle: Text([
                  widget.merchant.address,
                  // 走多远放在取餐码说明**之前**:他先要决定去不去,
                  // 才轮到怎么取。(SDK ^3.4 没有 `?expr`,用 if 判空)
                  if (_walkLine != null) _walkLine!,
                  '出餐后凭订单页的取餐码到店取餐',
                ].join('\n')),
                isThreeLine: true,
              ),
            )
          else
            Card(
              child: _loadingAddress
                  ? const Padding(
                      padding: EdgeInsets.all(20),
                      child: Center(child: CircularProgressIndicator()))
                  : ListTile(
                      leading: Icon(Icons.place,
                          color: theme.colorScheme.primary),
                      title: Text(_address == null
                          ? '选择收货地址'
                          : _address!.fullAddress),
                      subtitle: _address == null
                          ? const Text('还没有地址,点击新建')
                          : Text(
                              '${_address!.contactName} ${_address!.contactPhone}'),
                      trailing: const Icon(Icons.chevron_right),
                      onTap: _pickAddress,
                    ),
            ),
          if (eta != null && _scheduledAt == null)
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 4, 16, 0),
              child: Text(
                // 分钟数 + 几点几分**都给**。
                //
                // 「30 分钟」要用户自己加一遍才知道是几点,而他这会儿
                // 想的是"我 7 点要出门,来不来得及";「18:40」又看不出
                // 是快还是慢。两个一起给,两种问法都答得上(#296)
                '🕐 预计 $eta 分钟送达(约 ${_clockAfter(eta)})',
                style: TextStyle(
                    color: theme.colorScheme.primary,
                    fontWeight: FontWeight.w600),
              ),
            ),
          const SizedBox(height: 8),
          // 送达时间:尽快 / 预约(预约单商家可从容备餐,接单超时豁免)
          Card(
            child: ListTile(
              leading: Icon(Icons.schedule, color: theme.colorScheme.primary),
              title: Text(_scheduleLabel),
              subtitle: _scheduledAt == null
                  ? Text(_pickup
                      ? '点击可预约取餐时间(最多提前 48 小时)'
                      : '点击可预约送达时间(最多提前 48 小时)')
                  : null,
              trailing: _scheduledAt == null
                  ? const Icon(Icons.chevron_right)
                  : TextButton(
                      onPressed: () => setState(() => _scheduledAt = null),
                      child: const Text('改为尽快')),
              onTap: _pickScheduledTime,
            ),
          ),
          const SizedBox(height: 8),

          // 优惠券:未达门槛的**不藏起来**,置灰写明还差多少 ——
          // 用户得知道差在哪儿,才谈得上决定要不要再加一道菜
          if (_coupons.isNotEmpty)
            Card(
              child: Padding(
                padding: const EdgeInsets.all(12),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text('优惠券', style: theme.textTheme.titleSmall),
                    const SizedBox(height: 8),
                    Wrap(
                      spacing: 8,
                      runSpacing: 4,
                      children: [
                        for (final c in _sortedCoupons)
                          _couponChip(theme, c, coupon?['id'] as int?),
                      ],
                    ),
                    const SizedBox(height: 6),
                    Text(_couponHint(coupon),
                        style: TextStyle(
                            fontSize: 11.5, color: theme.sz.inkMuted)),
                  ],
                ),
              ),
            ),
          if (_toDoorCard(theme) != null) _toDoorCard(theme)!,
          // 小费:可选,全归骑手(自取单无配送环节不显示)
          if (!_pickup)
            Card(
              child: Padding(
                padding: const EdgeInsets.all(12),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text('给骑手加个小费(可选,100% 归骑手)',
                        style: theme.textTheme.titleSmall),
                    const SizedBox(height: 8),
                    Wrap(spacing: 8, children: [
                      for (final c in const [0, 200, 500, 1000])
                        ChoiceChip(
                          label: Text(c == 0 ? '不加' : '¥${c ~/ 100}'),
                          selected: _tipCents == c,
                          onSelected: (_) => setState(() => _tipCents = c),
                        ),
                    ]),
                  ],
                ),
              ),
            ),
          if (!_pickup) const SizedBox(height: 8),

          // 商品明细。每一行都写清"谁承担"——结算页最容易被质疑,
          // 在这里把话讲透,比事后解释便宜
          const SzSectionTitle('费用'),
          const SizedBox(height: 8),
          SzCard(
            padding: const EdgeInsets.symmetric(
                horizontal: kCardPad, vertical: 4),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                for (final line in widget.cart)
                  SzFeeRow(
                      label: '${line.label} ×${line.quantity}',
                      amountCents: line.unitCents * line.quantity),
                if (packing > 0)
                  SzFeeRow(label: '打包费', amountCents: packing),
                // 店铺券是**取代**满减而不是叠加,所以这一行要么是满减、
                // 要么是店铺券,写两行就是把同一笔钱数了两遍
                if (merchantOff > 0)
                  SzFeeRow(
                      label: shopCoupon ? '店铺券抵扣' : '满减优惠',
                      note: shopCoupon ? '商家承担 · 已取代满减' : '商家承担',
                      amountCents: merchantOff,
                      negative: true),
                if (_giftRule != null)
                  SzFeeRow(
                      label: '满${_giftRule!.thresholdCents ~/ 100}'
                          '赠${_giftRule!.name}',
                      note: '商家承担',
                      amountCents: 0),
                if (_pickup)
                  const SzFeeRow(
                      label: '配送费', note: '到店自取,免', amountCents: 0)
                else if (fee == null)
                  Padding(
                    padding: const EdgeInsets.symmetric(vertical: 8),
                    child: Row(children: [
                      Text('配送费',
                          style:
                              TextStyle(fontSize: 13, color: theme.sz.inkMuted)),
                      const Spacer(),
                      Text('选地址后计算',
                          style:
                              TextStyle(fontSize: 12, color: theme.sz.inkMuted)),
                    ]),
                  )
                else ...[
                  SzFeeRow(
                      label: '配送费', note: '全额归骑手', amountCents: fee),
                  // 拆分逐行列出:夜间、恶劣天气、上门难度此前都是
                  // "悄悄加上去的",顾客只看到总数变了
                  ..._feeBreakdownRows(theme),
                ],
                if (!_pickup && tip > 0)
                  SzFeeRow(label: '小费', note: '全额归骑手', amountCents: tip),
                if (platformOff > 0)
                  SzFeeRow(
                      label: '平台券抵扣',
                      note: '平台承担',
                      amountCents: platformOff,
                      negative: true),
                Divider(color: theme.sz.line, height: 17),
                SzFeeRow(
                    label: '实付',
                    amountCents: total ?? 0,
                    emphasized: true),
              ],
            ),
          ),
          const SizedBox(height: 8),
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 2),
            child: Text('没有配送费浮动、没有会员价差、没有隐藏服务费。你看到的就是全部。',
                style: TextStyle(
                    fontSize: 11.5, height: 1.55, color: theme.sz.inkMuted)),
          ),
          const SizedBox(height: 8),

          // 餐具 + 备注
          Card(
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 4),
              child: Column(
                children: [
                  Row(
                    children: [
                      const Text('餐具份数'),
                      const Spacer(),
                      IconButton(
                        tooltip: '减少',
                        icon: const Icon(Icons.remove_circle_outline),
                        onPressed: _tableware > 0
                            ? () => setState(() => _tableware--)
                            : null,
                      ),
                      Text('$_tableware'),
                      IconButton(
                        tooltip: '增加',
                        icon: const Icon(Icons.add_circle_outline),
                        onPressed: _tableware < 20
                            ? () => setState(() => _tableware++)
                            : null,
                      ),
                    ],
                  ),
                  TextField(
                    controller: _remark,
                    maxLength: 100,
                    decoration: const InputDecoration(
                      labelText: '订单备注',
                      hintText: '口味偏好、放门口等(选填)',
                      border: OutlineInputBorder(),
                    ),
                  ),
                  const SizedBox(height: 8),
                ],
              ),
            ),
          ),
          const SizedBox(height: 8),

          // 透明分账预览。占比按用户实付算,平台留存那行同时写商家侧口径——
          // 只写一个数会被当成玩数字(见 docs/DEV-PROMPTS-8.md 拍板)
          if (total != null && total > 0) ...[
            const SzSectionTitle('这一单的钱会去哪'),
            const SizedBox(height: 8),
            SzCard(
              padding: const EdgeInsets.symmetric(
                  horizontal: kCardPad, vertical: 2),
              child: SzMoneyFlow(items: [
                SzFlowItem(
                  name: '商家实收',
                  amountCents: _foodCents + packing - merchantOff - commission,
                  fraction:
                      (_foodCents + packing - merchantOff - commission) / total,
                  note: '菜品 + 打包 − ${shopCoupon ? '店铺券' : '满减'},只扣 '
                      '${(widget.merchant.commissionRate * 100).toStringAsFixed(0)}% 服务费',
                ),
                if (!_pickup)
                  SzFlowItem(
                    name: '骑手所得',
                    amountCents: fee! + tip,
                    fraction: (fee + tip) / total,
                    note: tip > 0
                        ? '配送费 + 小费 100% 归骑手,平台分文不取'
                        : '配送费 100% 归骑手,平台分文不取',
                  ),
                SzFlowItem(
                  name: '平台留存',
                  amountCents: commission,
                  fraction: commission / total,
                  note: '服务器、客服与赔付池 · 按商家侧口径 '
                      '${yuan(commission)} / ${yuan(_foodCents + packing - merchantOff)}'
                      ' = ${(widget.merchant.commissionRate * 100).toStringAsFixed(0)}%',
                  isHold: true,
                ),
              ]),
            ),
          ],
          const SizedBox(height: 80),
        ],
      ),
      bottomNavigationBar: SafeArea(
        child: Container(
          padding: const EdgeInsets.fromLTRB(16, 10, 16, 12),
          decoration: BoxDecoration(
            color: theme.sz.surface,
            border: Border(top: BorderSide(color: theme.sz.line)),
          ),
          child: Row(
            children: [
              Expanded(
                // 合计变化时轻微上滚过渡,给"价格在响应我的操作"的反馈
                child: AnimatedSwitcher(
                  duration: const Duration(milliseconds: 200),
                  transitionBuilder: (child, animation) => FadeTransition(
                    opacity: animation,
                    child: SlideTransition(
                      position: Tween(
                              begin: const Offset(0, 0.4), end: Offset.zero)
                          .animate(animation),
                      child: child,
                    ),
                  ),
                  child: Column(
                    key: ValueKey('$_belowMinOrder-$total-${verdict.totalOff}'),
                    crossAxisAlignment: CrossAxisAlignment.start,
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Text(
                        total == null ? '—' : yuan(total),
                        style: szMoney(
                            fontSize: 20,
                            fontWeight: FontWeight.w600,
                            color: theme.sz.ink),
                      ),
                      const SizedBox(height: 1),
                      Text(
                        _belowMinOrder
                            ? '差 ${yuan(widget.merchant.minOrderCents - _foodCents)} 起送'
                            : total == null
                                ? '请先选择地址'
                                // 「已省」= 满减/店铺券 + 平台券,取的就是提交时
                                // 用的那份拆分 —— 显示得出来的,提交就付得掉
                                : verdict.totalOff > 0
                                    ? '已省 ${yuan(verdict.totalOff)}'
                                    : (_pickup ? '到店自取' : '含配送费'),
                        style: TextStyle(
                            fontSize: 10.5, color: theme.sz.inkMuted),
                      ),
                    ],
                  ),
                ),
              ),
              const SizedBox(width: 10),
              FilledButton(
                onPressed: _submitting || total == null || _belowMinOrder
                    ? null
                    : _submit,
                child: Text(_belowMinOrder
                    ? '未达起送价'
                    : _submitting
                        ? '下单中…'
                        : '提交订单'),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

/// 券门槛/差额用紧凑写法:整元不带小数(「满¥50」比「满¥50.00」好读),
/// 有零头才带 —— 券的门槛几乎都是整元,小数点纯属噪音
String _money(int cents) =>
    cents % 100 == 0 ? '¥${cents ~/ 100}' : yuan(cents);

/// 一张券在本单的判定结果。
///
/// 拆成"商家承担 / 平台承担"两笔,是因为服务端就是这么记账的:
/// 店铺券取代满减走 discount(orders.py:490,商家出),平台券走 subsidy
/// (orders.py:500,平台出)。结算页的实付金额、佣金基数、分账预览三处
/// 都依赖这个拆分,合成一个数就没法如实展示"这笔钱是谁掏的"。
class _CouponVerdict {
  const _CouponVerdict.ok({required this.merchantOff, required this.platformOff})
      : reason = '',
        beatenByManjian = false;

  const _CouponVerdict.no(this.reason)
      : merchantOff = 0,
        platformOff = 0,
        beatenByManjian = false;

  /// 够得着门槛,但满减本来就更划算 —— 服务端会以 409 拒收这张券
  const _CouponVerdict.beaten()
      : reason = '满减更划算',
        merchantOff = 0,
        platformOff = 0,
        beatenByManjian = true;

  /// 商家承担:店铺券会**取代**满减(取最优不叠加);没用店铺券时就是满减本身
  final int merchantOff;

  /// 平台承担:平台券抵扣
  final int platformOff;

  /// 不能用的原因(人话,直接印在券上);空串 = 能用
  final String reason;

  final bool beatenByManjian;

  bool get usable => reason.isEmpty;

  /// 用户实际省下的总额 —— 自动选券比的就是这个数,不是券面额
  int get totalOff => merchantOff + platformOff;
}
