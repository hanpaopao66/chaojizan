import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';

import 'address_pages.dart';

/// 跑腿·帮送:东西是你自己的,A 点取、B 点送。
///
/// ## 这一页必须说清楚的一件事
///
/// **跑腿平台收 2%,而外卖的配送费我们一分不抽。**
///
/// 两个口径同时存在,不写清楚就是"你不是说配送费不抽吗"。
/// 说法要给到根上:外卖那边平台收入来自商家佣金,配送费不碰;
/// 跑腿没有商家,这 2% 是这条业务上唯一的收入。
/// 所以它在费用明细里**单独占一行**,不藏在总价里。
///
/// ## 禁运不是免责话术
///
/// 危险品、活体、现金、处方药服务端硬拦,命中会告诉你是哪一类。
/// 这里的勾选不是为了免责,是让人在按下单之前真的想一遍。
class ErrandPage extends StatefulWidget {
  const ErrandPage({super.key, required this.api});

  final ApiClient api;

  @override
  State<ErrandPage> createState() => _ErrandPageState();
}

class _ErrandPageState extends State<ErrandPage> {
  ({String address, double lat, double lng, String name, String phone})?
      _from;
  ({String address, double lat, double lng, String name, String phone})? _to;
  final _note = TextEditingController();
  final _remark = TextEditingController();
  bool _noForbidden = false;
  bool _toDoor = true;
  int? _floor;
  bool? _hasElevator;

  Map<String, dynamic>? _quote;
  bool _quoting = false;
  bool _submitting = false;

  /// 帮送 / 帮买。**共用一套地址与报价逻辑** —— 两者只差
  /// "东西是你的" 还是 "东西要骑手去买",没必要做成两个页面
  bool _buyMode = false;
  final _budget = TextEditingController(text: '30');
  int get _budgetCents =>
      ((double.tryParse(_budget.text) ?? 0) * 100).round();

  @override
  void dispose() {
    _note.dispose();
    _remark.dispose();
    _budget.dispose();
    super.dispose();
  }

  Map<String, dynamic>? _body() {
    final f = _from, t = _to;
    if (f == null || t == null) return null;
    return {
      'pickup_address': f.address,
      'pickup_lat': f.lat,
      'pickup_lng': f.lng,
      'pickup_contact_name': f.name,
      'pickup_contact_phone': f.phone,
      'address': t.address,
      'lat': t.lat,
      'lng': t.lng,
      'contact_name': t.name,
      'contact_phone': t.phone,
      'floor': _floor,
      'has_elevator': _hasElevator,
      'to_door': _toDoor,
      'errand_note': _note.text.trim().isEmpty ? '物品' : _note.text.trim(),
      'remark': _remark.text.trim(),
      'no_forbidden': _noForbidden,
      if (_buyMode) 'goods_budget_cents': _budgetCents,
    };
  }

  /// 两头地址都选好就自动报价 —— 让他在填完的那一刻就看到多少钱,
  /// 而不是填完一堆再点一下"算钱"
  Future<void> _refreshQuote() async {
    final body = _body();
    if (body == null) return;
    setState(() => _quoting = true);
    try {
      final q = _buyMode
          ? await widget.api.errandBuyQuote(body)
          : await widget.api.errandQuote(body);
      if (mounted) setState(() { _quote = q; _quoting = false; });
    } catch (e) {
      if (!mounted) return;
      setState(() { _quote = null; _quoting = false; });
      ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text(e is ApiException ? e.message : '$e')));
    }
  }

  Future<void> _pick(bool isFrom) async {
    // 复用地址簿的选址模式:跑腿的取件点和送达点都是"用户的某个地址",
    // 没理由另做一套输入(另做一套就等于两处地址格式迟早不一致)
    final picked = await Navigator.of(context).push<Address>(
        MaterialPageRoute(builder: (_) => AddressBookPage(
            api: widget.api, selectMode: true)));
    if (picked == null || !mounted) return;
    final v = (
      address: picked.detail.isEmpty
          ? picked.address
          : '${picked.address} ${picked.detail}',
      lat: picked.lat,
      lng: picked.lng,
      name: picked.contactName,
      phone: picked.contactPhone,
    );
    setState(() {
      if (isFrom) {
        _from = v;
      } else {
        _to = v;
        _floor = picked.floor;
        _hasElevator = picked.hasElevator;
      }
    });
    _refreshQuote();
  }

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    final q = _quote;
    final ready = _from != null && _to != null && _noForbidden &&
        _note.text.trim().length >= 2 && q != null;

    return SzPageScaffold(
      appBar: AppBar(title: Text(_buyMode ? '帮我买' : '帮我送')),
      body: ListView(
        padding: const EdgeInsets.all(12),
        children: [
          SegmentedButton<bool>(
            segments: const [
              ButtonSegment(value: false, label: Text('帮我送'),
                  icon: Icon(Icons.send_outlined, size: 17)),
              ButtonSegment(value: true, label: Text('帮我买'),
                  icon: Icon(Icons.shopping_basket_outlined, size: 17)),
            ],
            selected: {_buyMode},
            onSelectionChanged: (v) {
              setState(() {
                _buyMode = v.first;
                _quote = null;
              });
              _refreshQuote();
            },
          ),
          const SizedBox(height: 10),
          SzCard(
            child: Column(children: [
              _addrRow(sz, true, _buyMode ? '去哪买' : '从哪取', _from),
              Divider(height: 18, color: sz.line),
              _addrRow(sz, false, '送到哪', _to),
            ]),
          ),
          const SizedBox(height: 12),
          SzCard(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                TextField(
                  controller: _note,
                  maxLength: 60,
                  onChanged: (_) => setState(() {}),
                  decoration: InputDecoration(
                    labelText: _buyMode ? '买什么' : '寄什么',
                    hintText: _buyMode
                        ? '如:两瓶矿泉水和一包纸巾'
                        : '如:一个文件袋 / 一把钥匙 / 一箱牛奶',
                    helperText: _buyMode
                        ? '只做包装商品与商超日用;现做的饭菜请走外卖'
                        : '骑手取件时要照着核对,写具体一点',
                    border: const OutlineInputBorder(),
                  ),
                ),
                if (_buyMode)
                  TextField(
                    controller: _budget,
                    keyboardType: const TextInputType.numberWithOptions(
                        decimal: true),
                    onChanged: (_) => _refreshQuote(),
                    decoration: const InputDecoration(
                      labelText: '大概要花多少钱(元)',
                      helperText: '这笔钱你先付给平台,骑手不用自己垫;'
                          '按小票实付结算,多退少补',
                      border: OutlineInputBorder(),
                    ),
                  ),
                TextField(
                  controller: _remark,
                  maxLength: 60,
                  decoration: const InputDecoration(
                    labelText: '备注(选填)',
                    hintText: '如:放门口的鞋柜上',
                    border: OutlineInputBorder(),
                  ),
                ),
                const SizedBox(height: 6),
                SwitchListTile(
                  contentPadding: EdgeInsets.zero,
                  value: _toDoor,
                  onChanged: (v) {
                    setState(() => _toDoor = v);
                    _refreshQuote();
                  },
                  title: const Text('送上门'),
                  subtitle: Text(
                      _toDoor
                          ? '高楼层无电梯会收上门难度费,下面明细里看得到'
                          : '选了送到楼下就不收上门难度费,骑手也不上楼',
                      style: TextStyle(fontSize: 12, color: sz.inkMuted)),
                ),
                CheckboxListTile(
                  contentPadding: EdgeInsets.zero,
                  value: _noForbidden,
                  onChanged: (v) => setState(() => _noForbidden = v ?? false),
                  title: Text(_buyMode ? '我确认不在不支持的范围内' : '我确认不含违禁品'),
                  subtitle: Text(
                      _buyMode
                          ? '不做即食餐饮、烟、酒、药 —— 代购现做的食品需要'
                              '食品经营许可,我们不给无证经营导流;'
                              '想吃现做的走外卖,那边的商家都有证'
                          : '危险化学品、易燃易爆、活体动物、现金与贵重金属、'
                              '管制刀具、药品都不能寄 —— 这几类平台一律不承运,'
                              '不是走个流程',
                      style: TextStyle(fontSize: 11.5, color: sz.inkMuted)),
                ),
              ],
            ),
          ),
          const SizedBox(height: 12),
          if (_quoting)
            const Center(child: Padding(
                padding: EdgeInsets.all(12),
                child: CircularProgressIndicator())),
          if (q != null) _quoteCard(sz, q),
          const SizedBox(height: 16),
          SizedBox(
            height: 48,
            child: FilledButton(
              onPressed: ready && !_submitting ? _submit : null,
              child: Text(_submitting
                  ? '提交中…'
                  : q == null
                      ? '先选好取送地址'
                      : '下单 ${(q['total_cents'] / 100).toStringAsFixed(2)} 元'),
            ),
          ),
          const SizedBox(height: 8),
          Text(
              _buyMode
                  ? '买不到的话商品款全额退给你,跑腿费只收到店那一段的距离费 ——'
                      '骑手确实跑了这一趟,而你也确实没拿到东西。'
                      '这条我们提前写在这里,不藏在协议里。'
                  : '贵重物品请勿使用本服务 —— 我们不做保价,'
                      '出了问题赔不了你真实损失,与其事后争执不如提前说清楚。',
              style: TextStyle(fontSize: 11.5, color: sz.inkMuted)),
        ],
      ),
    );
  }

  Widget _addrRow(SzColors sz, bool isFrom, String label,
      ({String address, double lat, double lng, String name, String phone})? v) =>
      InkWell(
        onTap: () => _pick(isFrom),
        child: Row(children: [
          Icon(isFrom ? Icons.trip_origin : Icons.place,
              size: 18, color: isFrom ? sz.earn : sz.clay),
          const SizedBox(width: 10),
          Expanded(
            child: v == null
                ? Text(label, style: TextStyle(color: sz.inkMuted))
                : Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(v.address,
                          maxLines: 2, overflow: TextOverflow.ellipsis,
                          style: const TextStyle(
                              fontSize: 14, fontWeight: FontWeight.w600)),
                      if (v.name.isNotEmpty || v.phone.isNotEmpty)
                        Text('${v.name} ${v.phone}',
                            style: TextStyle(
                                fontSize: 12, color: sz.inkMuted)),
                    ],
                  ),
          ),
          Icon(Icons.chevron_right, size: 18, color: sz.inkFaint),
        ]),
      );

  /// 费用明细。**平台服务费单独一行** —— 藏在总价里就等于没说,
  /// 而我们对外讲的是"账目公开"
  Widget _quoteCard(SzColors sz, Map<String, dynamic> q) {
    final parts = ((q['parts'] as Map?) ?? const {})
        .map((k, v) => MapEntry('$k', (v as num).toInt()));
    final labels = ((q['labels'] as Map?) ?? const {})
        .map((k, v) => MapEntry('$k', '$v'));
    final fee = (q['service_fee_cents'] as num).toInt();
    return SzCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          if (_buyMode) ...[
            Row(children: [
              Expanded(child: const Text('商品款(预付)',
                  style: TextStyle(fontWeight: FontWeight.w600))),
              const SizedBox(width: 10),
              Text('¥${((q['goods_budget_cents'] as num? ?? 0) / 100)
                  .toStringAsFixed(2)}',
                  style: szMoney(fontSize: 16, color: sz.ink)),
            ]),
            Text('平台一分不抽,按小票实付结给骑手',
                style: TextStyle(fontSize: 11.5, color: sz.inkMuted)),
            const SizedBox(height: 8),
          ],
          Row(children: [
            Expanded(child: const Text('跑腿费', style: TextStyle(fontWeight: FontWeight.w600))),
            const SizedBox(width: 10),
            Text('¥${((q['fee_cents'] as num) / 100).toStringAsFixed(2)}',
                style: szMoney(fontSize: 16, color: sz.ink)),
          ]),
          Text('全程 ${((q['distance_m'] as num) / 1000).toStringAsFixed(1)} 公里',
              style: TextStyle(fontSize: 11.5, color: sz.inkMuted)),
          const SizedBox(height: 6),
          for (final e in parts.entries.where((x) => x.value > 0))
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 1),
              child: Row(children: [
                Expanded(child: Text(labels[e.key] ?? e.key,
                    style: TextStyle(fontSize: 12, color: sz.inkMuted))),
                const SizedBox(width: 10),
                Text('¥${(e.value / 100).toStringAsFixed(2)}',
                    style: TextStyle(fontSize: 12, color: sz.inkMuted)),
              ]),
            ),
          Divider(height: 14, color: sz.line),
          Row(children: [
            Expanded(child: Text('其中平台服务费', style: TextStyle(fontSize: 12, color: sz.inkMuted))),
            const SizedBox(width: 10),
            Text('¥${(fee / 100).toStringAsFixed(2)}',
                style: TextStyle(fontSize: 12, color: sz.inkMuted)),
          ]),
          const SizedBox(height: 4),
          Text('${q['note']}',
              style: TextStyle(fontSize: 11.5, height: 1.5, color: sz.inkMuted)),
        ],
      ),
    );
  }

  Future<void> _submit() async {
    final body = _body();
    if (body == null) return;
    setState(() => _submitting = true);
    try {
      final order = _buyMode
          ? await widget.api.createErrandBuy(body)
          : await widget.api.createErrand(body);
      if (!mounted) return;
      Navigator.of(context).pop(order);
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(
          content: Text(e is ApiException ? e.message : '$e'),
          duration: const Duration(seconds: 6)));
    } finally {
      if (mounted) setState(() => _submitting = false);
    }
  }
}
