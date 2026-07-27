import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';
import 'package:url_launcher/url_launcher.dart';

import 'hotel_pages.dart';
import 'stay_checkout_page.dart';

/// 酒店详情:图集/设施/位置 + 房型报价卡片(取消政策明示)。
/// 顶部日期条改日期即重新报价;满房房型仍展示(置灰)。
class HotelDetailPage extends StatefulWidget {
  const HotelDetailPage(
      {super.key, required this.api, required this.hotelId, required this.range});

  final ApiClient api;
  final int hotelId;
  final StayRange range;

  @override
  State<HotelDetailPage> createState() => _HotelDetailPageState();
}

class _HotelDetailPageState extends State<HotelDetailPage> {
  late StayRange _range = widget.range;
  HotelDetail? _hotel;
  String? _error;

  static const _facilityLabels = {
    'wifi': '免费 WiFi',
    'parking': '停车场',
    'breakfast': '含早餐',
    'luggage': '行李寄存',
    'front_desk_24h': '24h 前台',
    'elevator': '电梯',
  };

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final hotel = await widget.api.hotelDetail(widget.hotelId,
          checkin: _range.checkinStr, checkout: _range.checkoutStr);
      if (mounted) {
        setState(() {
          _hotel = hotel;
          _error = null;
        });
      }
    } catch (e) {
      if (mounted) {
        setState(() => _error = e is ApiException ? e.message : '$e');
      }
    }
  }

  Color _policyColor(String policy) => switch (policy) {
        'limited_free' => const Color(0xFF0E8A5F), // 账目绿:对用户友好的政策
        'first_night' => Colors.grey.shade700,
        _ => Colors.deepOrange,
      };

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final hotel = _hotel;
    if (hotel == null) {
      return Scaffold(
        appBar: AppBar(title: const Text('酒店详情')),
        body: Center(
          child: _error == null
              ? const CircularProgressIndicator()
              : Column(mainAxisSize: MainAxisSize.min, children: [
                  Text(_error!),
                  const SizedBox(height: 8),
                  FilledButton(onPressed: _load, child: const Text('重试')),
                ]),
        ),
      );
    }
    final photos = hotel.photoUrls.isNotEmpty
        ? hotel.photoUrls
        : [if (hotel.logoUrl.isNotEmpty) hotel.logoUrl];
    return Scaffold(
      appBar: AppBar(title: Text(hotel.name)),
      body: ListView(children: [
        if (photos.isNotEmpty)
          SizedBox(
            height: 200,
            child: PageView(children: [
              for (final url in photos)
                Image.network(widget.api.resolveUrl(url), fit: BoxFit.cover),
            ]),
          ),
        Padding(
          padding: const EdgeInsets.all(12),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Row(children: [
              Expanded(
                  child: Text(hotel.name,
                      style: theme.textTheme.titleLarge)),
              Chip(label: Text(hotel.tierLabel)),
            ]),
            const SizedBox(height: 4),
            Text(hotel.ratingAvg != null
                ? '★ ${hotel.ratingAvg}(${hotel.ratingCount} 条评价)'
                : '暂无足够评价'),
            const SizedBox(height: 4),
            Row(children: [
              const Icon(Icons.location_on_outlined, size: 16),
              const SizedBox(width: 4),
              Expanded(child: Text(hotel.address)),
              if (hotel.frontDeskPhone.isNotEmpty)
                IconButton(
                  icon: const Icon(Icons.phone_outlined, size: 18),
                  tooltip: '联系前台',
                  onPressed: () =>
                      launchUrl(Uri.parse('tel:${hotel.frontDeskPhone}')),
                ),
            ]),
            Text('${hotel.checkinFrom} 后入住 · ${hotel.checkoutUntil} 前退房',
                style: theme.textTheme.bodySmall),
            if (hotel.facilities.isNotEmpty) ...[
              const SizedBox(height: 8),
              Wrap(spacing: 8, runSpacing: 4, children: [
                for (final f in hotel.facilities)
                  Chip(
                      label: Text(_facilityLabels[f] ?? f,
                          style: const TextStyle(fontSize: 12)),
                      visualDensity: VisualDensity.compact),
              ]),
            ],
            if (hotel.description.isNotEmpty) ...[
              const SizedBox(height: 8),
              Text(hotel.description, style: theme.textTheme.bodyMedium),
            ],
            const Divider(height: 24),
            // 日期条:改日期即重新报价
            OutlinedButton.icon(
              icon: const Icon(Icons.calendar_month, size: 18),
              label: Text(_range.label),
              onPressed: () async {
                final picked = await pickStayRange(context, _range);
                if (picked != null) {
                  setState(() {
                    _range = picked;
                    _hotel = null;
                  });
                  _load();
                }
              },
            ),
            const SizedBox(height: 8),
            for (final quote in hotel.rooms) _roomCard(theme, hotel, quote),
            if (hotel.rooms.isEmpty)
              const Padding(
                  padding: EdgeInsets.all(24),
                  child: Center(child: Text('该酒店暂未开放房型'))),
          ]),
        ),
      ]),
    );
  }

  Widget _roomCard(ThemeData theme, HotelDetail hotel, RoomQuote quote) {
    final rt = quote.roomType;
    final bookable = quote.bookable;
    return Card(
      margin: const EdgeInsets.symmetric(vertical: 6),
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Opacity(
          opacity: bookable ? 1 : 0.55,
          child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
            ClipRRect(
              borderRadius: BorderRadius.circular(8),
              child: SizedBox(
                width: 84,
                height: 84,
                child: rt.imageUrls.isEmpty
                    ? Container(
                        color: theme.colorScheme.surfaceContainerHighest,
                        child: const Icon(Icons.bed_outlined, size: 32))
                    : Image.network(
                        widget.api.resolveUrl(rt.imageUrls.first),
                        fit: BoxFit.cover),
              ),
            ),
            const SizedBox(width: 12),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(rt.name, style: theme.textTheme.titleMedium),
                  Text(
                      [
                        if (rt.bedType.isNotEmpty) rt.bedType,
                        if (rt.areaM2 > 0) '${rt.areaM2}㎡',
                        '可住 ${rt.maxGuests} 人',
                      ].join(' · '),
                      style: theme.textTheme.bodySmall),
                  const SizedBox(height: 4),
                  Text(quote.cancelPolicyText,
                      style: TextStyle(
                          fontSize: 12,
                          color: _policyColor(rt.cancelPolicy),
                          fontWeight: FontWeight.w500)),
                  if (quote.leftQty != null)
                    Text('仅剩 ${quote.leftQty} 间',
                        style: const TextStyle(
                            fontSize: 12,
                            color: Colors.deepOrange,
                            fontWeight: FontWeight.bold)),
                  const SizedBox(height: 6),
                  Row(children: [
                    if (bookable && quote.totalCents != null) ...[
                      Text(yuan(quote.totalCents!),
                          style: theme.textTheme.titleMedium?.copyWith(
                              color: theme.colorScheme.primary,
                              fontWeight: FontWeight.bold)),
                      Text(' /${_range.nights}晚',
                          style: theme.textTheme.bodySmall),
                    ] else
                      const Text('该日期订不了',
                          style: TextStyle(color: Colors.grey)),
                    const Spacer(),
                    FilledButton(
                      onPressed: bookable
                          ? () => Navigator.of(context).push(MaterialPageRoute(
                              builder: (_) => StayCheckoutPage(
                                  api: widget.api,
                                  hotel: hotel,
                                  quote: quote,
                                  range: _range)))
                          : null,
                      child: Text(bookable ? '订' : '满房'),
                    ),
                  ]),
                ],
              ),
            ),
          ]),
        ),
      ),
    );
  }
}
