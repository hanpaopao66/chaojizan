import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';

import '../finance_page.dart';
import 'hotel_tab.dart';
import 'room_manage_page.dart';
import 'stay_orders_page.dart';

/// 酒店业态工作台:与外卖工作台平行的另一套 4 tab。
/// 单 APK 业态分叉(拍板见 docs/HOTEL_PLAN.md):登录后按 biz_type 整体切换,
/// 基础设施(登录/推送/钱包/发票/客服)与外卖共用,业务页面收在 hotel/ 目录,
/// 将来要拆独立 APK 时把本目录拎出去即可。
class HotelHomePage extends StatefulWidget {
  const HotelHomePage({
    super.key,
    required this.api,
    required this.shop,
    required this.onShopChanged,
  });

  final ApiClient api;
  final Merchant shop;
  final VoidCallback onShopChanged;

  @override
  State<HotelHomePage> createState() => _HotelHomePageState();
}

class _HotelHomePageState extends State<HotelHomePage> {
  int _tab = 0;
  late bool _isOpen = widget.shop.isOpen;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      checkForUpdate(context, baseUrl: widget.api.baseUrl, app: 'merchant');
    });
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: Text(switch (_tab) {
          1 => '房型房价',
          2 => '对账',
          3 => '酒店',
          _ => '住宿订单',
        }),
        actions: [
          Row(children: [
            Text(_isOpen ? '营业中' : '已停业'),
            Switch(
              value: _isOpen,
              onChanged: (v) async {
                setState(() => _isOpen = v);
                try {
                  await widget.api.setShopOpen(v);
                } catch (e) {
                  setState(() => _isOpen = !v);
                  if (context.mounted) {
                    ScaffoldMessenger.of(context).showSnackBar(SnackBar(
                        content: Text(
                            e is ApiException ? e.message : e.toString())));
                  }
                }
              },
            ),
            const SizedBox(width: 8),
          ]),
        ],
      ),
      body: switch (_tab) {
        1 => RoomManagePage(api: widget.api),
        2 => FinancePage(api: widget.api),
        3 => HotelTab(api: widget.api, shop: widget.shop),
        _ => StayOrdersPage(api: widget.api, shop: widget.shop),
      },
      bottomNavigationBar: NavigationBar(
        selectedIndex: _tab,
        onDestinationSelected: (i) => setState(() => _tab = i),
        destinations: const [
          NavigationDestination(icon: Icon(Icons.receipt_long), label: '订单'),
          NavigationDestination(icon: Icon(Icons.bed_outlined), label: '房型房价'),
          NavigationDestination(icon: Icon(Icons.bar_chart), label: '对账'),
          NavigationDestination(icon: Icon(Icons.hotel), label: '酒店'),
        ],
      ),
    );
  }
}
