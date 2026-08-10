import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';

import 'hotel_detail_page.dart';
import 'session.dart';

String fmtDate(DateTime d) =>
    '${d.year.toString().padLeft(4, '0')}-${d.month.toString().padLeft(2, '0')}-${d.day.toString().padLeft(2, '0')}';

/// 入住/离店日期区间(住宿全链路共用,默认今住明退)
class StayRange {
  StayRange(this.checkin, this.checkout);

  final DateTime checkin;
  final DateTime checkout;

  int get nights => checkout.difference(checkin).inDays;
  String get checkinStr => fmtDate(checkin);
  String get checkoutStr => fmtDate(checkout);
  String get label =>
      '${checkin.month}月${checkin.day}日 - ${checkout.month}月${checkout.day}日 · $nights 晚';

  static StayRange tonight() {
    final now = DateTime.now();
    final today = DateTime(now.year, now.month, now.day);
    return StayRange(today, today.add(const Duration(days: 1)));
  }
}

/// 日期区间选择(共享组件,列表页与详情页复用)
Future<StayRange?> pickStayRange(BuildContext context, StayRange current) async {
  final now = DateTime.now();
  final today = DateTime(now.year, now.month, now.day);
  final picked = await showDateRangePicker(
    context: context,
    firstDate: today,
    lastDate: today.add(const Duration(days: 120)),
    initialDateRange:
        DateTimeRange(start: current.checkin, end: current.checkout),
    helpText: '选择入住和离店日期',
    saveText: '确定',
  );
  if (picked == null) return null;
  if (!picked.end.isAfter(picked.start)) return null;
  if (picked.duration.inDays > 28) {
    if (context.mounted) {
      ScaffoldMessenger.of(context)
          .showSnackBar(const SnackBar(content: Text('最多连住 28 晚')));
    }
    return null;
  }
  return StayRange(picked.start, picked.end);
}

/// 酒店列表:目的地关键词 + 日期区间 + 筛选排序。
/// 排序只按距离/价格/评分等客观因子——没有竞价位,商家花钱买不到靠前。
class HotelListPage extends StatefulWidget {
  const HotelListPage(
      {super.key, required this.api, required this.lat, required this.lng});

  final ApiClient api;
  final double lat;
  final double lng;

  @override
  State<HotelListPage> createState() => _HotelListPageState();
}

class _HotelListPageState extends State<HotelListPage> {
  final _keyword = TextEditingController();
  StayRange _range = StayRange.tonight();
  String _sort = 'comprehensive';
  String? _tier;
  int? _minPriceCents;
  int? _maxPriceCents;
  List<HotelCard> _hotels = [];

  /// 定位正常但该区域没有酒店:已降级演示城市数据(审核兜底)
  bool _fellBack = false;
  bool _loading = true;
  String? _error;

  static const _sorts = [
    ('comprehensive', '综合'),
    ('distance', '距离'),
    ('price', '低价优先'),
    ('rating', '高分优先'),
  ];

  @override
  void initState() {
    super.initState();
    _search();
  }

  Future<void> _search() async {
    setState(() => _loading = true);
    try {
      Future<List<HotelCard>> query(double lat, double lng) =>
          widget.api.hotels(
            lat: lat,
            lng: lng,
            checkin: _range.checkinStr,
            checkout: _range.checkoutStr,
            q: _keyword.text.trim(),
            sort: _sort,
            tier: _tier,
            minPriceCents: _minPriceCents,
            maxPriceCents: _maxPriceCents,
          );
      var hotels = await query(widget.lat, widget.lng);
      // 审核兜底:所在区域没有酒店(如审核人员定位在外地)时降级演示城市
      var fellBack = false;
      if (hotels.isEmpty && _keyword.text.trim().isEmpty) {
        hotels = await query(demoLat, demoLng);
        fellBack = hotels.isNotEmpty;
      }
      if (mounted) {
        setState(() {
          _hotels = hotels;
          _fellBack = fellBack;
          _loading = false;
          _error = null;
        });
      }
    } catch (e) {
      if (mounted) {
        setState(() {
          _loading = false;
          _error = e is ApiException ? e.message : '$e';
        });
      }
    }
  }

  Future<void> _priceSheet() async {
    final min = TextEditingController(
        text: _minPriceCents == null ? '' : '${_minPriceCents! ~/ 100}');
    final max = TextEditingController(
        text: _maxPriceCents == null ? '' : '${_maxPriceCents! ~/ 100}');
    final ok = await showModalBottomSheet<bool>(
      context: context,
      isScrollControlled: true,
      builder: (sheetContext) => Padding(
        padding: EdgeInsets.only(
            left: 16, right: 16, top: 16,
            bottom: MediaQuery.of(sheetContext).viewInsets.bottom + 16),
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          Text('每晚价格区间(元)',
              style: Theme.of(context).textTheme.titleMedium),
          const SizedBox(height: 12),
          Row(children: [
            Expanded(
                child: TextField(
                    controller: min,
                    keyboardType: TextInputType.number,
                    decoration: const InputDecoration(
                        labelText: '最低', border: OutlineInputBorder()))),
            const Padding(
                padding: EdgeInsets.symmetric(horizontal: 8),
                child: Text('—')),
            Expanded(
                child: TextField(
                    controller: max,
                    keyboardType: TextInputType.number,
                    decoration: const InputDecoration(
                        labelText: '最高', border: OutlineInputBorder()))),
          ]),
          const SizedBox(height: 12),
          SizedBox(
              width: double.infinity,
              child: FilledButton(
                  onPressed: () => Navigator.pop(sheetContext, true),
                  child: const Text('确定'))),
        ]),
      ),
    );
    if (ok != true) return;
    setState(() {
      _minPriceCents = min.text.trim().isEmpty
          ? null
          : (int.tryParse(min.text) ?? 0) * 100;
      _maxPriceCents = max.text.trim().isEmpty
          ? null
          : (int.tryParse(max.text) ?? 0) * 100;
    });
    _search();
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Scaffold(
      appBar: AppBar(
        title: const Text('住宿'),
        bottom: const PreferredSize(
            preferredSize: Size.fromHeight(3), child: SzChannelBar('stay')),
      ),
      body: Column(children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(12, 8, 12, 0),
          child: Column(children: [
            TextField(
              controller: _keyword,
              textInputAction: TextInputAction.search,
              onSubmitted: (_) => _search(),
              decoration: InputDecoration(
                hintText: '搜酒店名 / 地标',
                prefixIcon: const Icon(Icons.search),
                border: OutlineInputBorder(
                    borderRadius: BorderRadius.circular(12)),
                isDense: true,
              ),
            ),
            const SizedBox(height: 8),
            Row(children: [
              Expanded(
                child: OutlinedButton.icon(
                  icon: const Icon(Icons.calendar_month, size: 18),
                  label: Text(_range.label),
                  onPressed: () async {
                    final picked = await pickStayRange(context, _range);
                    if (picked != null) {
                      setState(() => _range = picked);
                      _search();
                    }
                  },
                ),
              ),
              const SizedBox(width: 8),
              FilledButton(onPressed: _search, child: const Text('搜索')),
            ]),
          ]),
        ),
        SizedBox(
          height: 44,
          child: ListView(
            scrollDirection: Axis.horizontal,
            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
            children: [
              for (final (value, label) in _sorts)
                Padding(
                  padding: const EdgeInsets.only(right: 8),
                  child: ChoiceChip(
                    label: Text(label),
                    selected: _sort == value,
                    onSelected: (_) {
                      setState(() => _sort = value);
                      _search();
                    },
                  ),
                ),
              const VerticalDivider(),
              for (final e in kHotelTiers.entries)
                Padding(
                  padding: const EdgeInsets.only(left: 8),
                  child: FilterChip(
                    label: Text(e.value),
                    selected: _tier == e.key,
                    onSelected: (v) {
                      setState(() => _tier = v ? e.key : null);
                      _search();
                    },
                  ),
                ),
              Padding(
                padding: const EdgeInsets.only(left: 8),
                child: ActionChip(
                  avatar: const Icon(Icons.tune, size: 16),
                  label: Text(_minPriceCents == null && _maxPriceCents == null
                      ? '价格'
                      : '价格已筛'),
                  onPressed: _priceSheet,
                ),
              ),
            ],
          ),
        ),
        Expanded(
          child: _loading
              ? const Center(child: CircularProgressIndicator())
              : _error != null
                  ? Center(
                      child: Column(mainAxisSize: MainAxisSize.min, children: [
                      Text(_error!),
                      const SizedBox(height: 8),
                      FilledButton(
                          onPressed: _search, child: const Text('重试')),
                    ]))
                  : _hotels.isEmpty
                      ? const Center(
                          child: Text('这个日期附近还没有可订的酒店\n换个日期或关键词试试',
                              textAlign: TextAlign.center))
                      : RefreshIndicator(
                          onRefresh: _search,
                          child: ListView.builder(
                            itemCount: _hotels.length + (_fellBack ? 1 : 0),
                            itemBuilder: (context, i) {
                              if (_fellBack && i == 0) {
                                return Padding(
                                  padding: const EdgeInsets.fromLTRB(
                                      16, 8, 16, 0),
                                  child: Text('您所在区域暂未开通,正在展示演示城市酒店',
                                      style: theme.textTheme.bodySmall
                                          ?.copyWith(
                                              color: theme
                                                  .colorScheme.outline)),
                                );
                              }
                              return _hotelCard(theme,
                                  _hotels[_fellBack ? i - 1 : i]);
                            },
                          ),
                        ),
        ),
      ]),
    );
  }

  Widget _hotelCard(ThemeData theme, HotelCard hotel) {
    final photo =
        hotel.photoUrls.isNotEmpty ? hotel.photoUrls.first : hotel.logoUrl;
    return Card(
      margin: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
      clipBehavior: Clip.antiAlias,
      child: InkWell(
        onTap: () => Navigator.of(context).push(MaterialPageRoute(
            builder: (_) => HotelDetailPage(
                api: widget.api, hotelId: hotel.id, range: _range))),
        child: Opacity(
          opacity: hotel.full ? 0.55 : 1,
          child: Row(children: [
            SizedBox(
              width: 110,
              height: 110,
              child: photo.isEmpty
                  ? Container(
                      color: theme.colorScheme.surfaceContainerHighest,
                      child: const Icon(Icons.hotel, size: 36))
                  : Image(image: szNetImage(widget.api.resolveUrl(photo)),
                      fit: BoxFit.cover),
            ),
            Expanded(
              child: Padding(
                padding: const EdgeInsets.all(10),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(hotel.name,
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: theme.textTheme.titleMedium),
                    const SizedBox(height: 2),
                    Text(
                        [
                          hotel.tierLabel,
                          if (hotel.ratingAvg != null)
                            '★${hotel.ratingAvg}(${hotel.ratingCount})'
                          else
                            '暂无评价',
                          if (hotel.distanceLabel.isNotEmpty)
                            hotel.distanceLabel,
                        ].join(' · '),
                        style: theme.textTheme.bodySmall),
                    const SizedBox(height: 2),
                    Text(hotel.address,
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: theme.textTheme.bodySmall
                            ?.copyWith(color: theme.colorScheme.outline)),
                    const Spacer(),
                    hotel.full
                        ? Text('该日期已满房',
                            style: TextStyle(color: Theme.of(context).sz.inkMuted))
                        : Row(
                            crossAxisAlignment: CrossAxisAlignment.baseline,
                            textBaseline: TextBaseline.alphabetic,
                            children: [
                              Text(
                                  '¥${((hotel.minNightPriceCents ?? 0) / 100).toStringAsFixed(0)}',
                                  style: theme.textTheme.titleMedium?.copyWith(
                                      color: theme.colorScheme.primary,
                                      fontWeight: FontWeight.bold)),
                              Text(' 起/晚', style: theme.textTheme.bodySmall),
                            ],
                          ),
                  ],
                ),
              ),
            ),
          ]),
        ),
      ),
    );
  }
}
