import 'dart:async';

import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:superz_shared/superz_shared.dart';

import 'main.dart' show MenuPage, OrdersPage, OrdersTab, ProfileView;
import 'order_filter.dart';
import 'session.dart';
import 'settings_page.dart';

/// 单门店版(应用商店包,见 packages/shared/lib/src/edition.dart)显示的那家店。
///
/// 店是谁由后台「平台开关」的 `single_store_merchant_id` 定(/config 的 single_store 下发),
/// 换店不用重新打包。[id] 在首页外壳拉到之后才有;订单列表、「我的」页的计数按它只数这一家的单
class SingleStore {
  SingleStore._();

  static const _key = 'single_store_id';

  /// 这家店的商家 id。null = 还没拉到(或者后台没配)
  static int? id;

  /// 先读上次拉到的(冷启动立刻能画),再问 /config;两样都没有就是 null。
  /// **拉不到不猜一家顶上** —— 猜错就是把别人的店当成这个 App 的店
  static Future<int?> resolve(ApiClient api) async {
    SharedPreferences? sp;
    try {
      sp = await SharedPreferences.getInstance();
      id ??= sp.getInt(_key);
    } catch (_) {}
    try {
      final cfg = await api.platformConfig();
      final fresh = (cfg['single_store'] as Map?)?['merchant_id'];
      id = fresh is num ? fresh.toInt() : null;
      if (id == null) {
        await sp?.remove(_key);
      } else {
        await sp?.setInt(_key, id!);
      }
    } catch (_) {
      // 断网就用缓存的那一家
    }
    return id;
  }
}

/// 单门店版的首页外壳:点餐 / 订单 / 我的。
///
/// 完整版的首页([HomePage])是「附近的店 + 金刚区 + 视频 + 聊天」,它一起动的还有聊天长连接、
/// 音乐播放器、扫码登录、通话这些模块。单门店版不进那个外壳,另起这一个 —— 那些模块连初始化都不做,
/// 不是藏起入口但后台照跑。
///
/// 点餐那一格就是这家店的 [MenuPage](看菜、加购、结算、评价、商家信息和证照公示都在里面)。
class SingleStoreHome extends StatefulWidget {
  const SingleStoreHome({super.key, required this.api});

  final ApiClient api;

  @override
  State<SingleStoreHome> createState() => _SingleStoreHomeState();
}

const int _kTabMenu = 0;
const int _kTabOrders = 1;
const int _kTabMe = 2;

class _SingleStoreHomeState extends State<SingleStoreHome> {
  int _tab = _kTabMenu;
  final Set<int> _visited = {_kTabMenu};

  Merchant? _shop;
  bool _loading = true;

  /// 拉不到店时说的话(没配 / 断网 / 店没了)。null = 没出错
  String? _error;

  @override
  void initState() {
    super.initState();
    Analytics.instance.init(widget.api);
    _load();
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    final id = await SingleStore.resolve(widget.api);
    if (!mounted) return;
    if (id == null) {
      setState(() {
        _loading = false;
        _error = '门店信息加载失败,请检查网络后重试';
      });
      return;
    }
    try {
      final shop = await widget.api.merchantDetail(id);
      if (!mounted) return;
      setState(() {
        _shop = shop;
        _loading = false;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _loading = false;
        _error = e is ApiException ? e.message : '门店信息加载失败,请检查网络后重试';
      });
    }
  }

  void _openOrders(OrderFilter filter) {
    Navigator.of(context).push(MaterialPageRoute<void>(
        builder: (_) => OrdersPage(api: widget.api, filter: filter)));
  }

  Widget _menuTab() {
    final shop = _shop;
    if (shop != null) {
      // key 跟着店走:后台换了店,点菜页整个重建,不留上一家的购物车
      return MenuPage(key: ValueKey(shop.id), api: widget.api, merchant: shop);
    }
    return SzPageScaffold(
      appBar: AppBar(title: const Text('点餐')),
      body: Center(
        child: _loading
            ? const CircularProgressIndicator()
            : Padding(
                padding: const EdgeInsets.all(32),
                child: Column(mainAxisSize: MainAxisSize.min, children: [
                  Icon(Icons.storefront_outlined,
                      size: 48, color: Theme.of(context).sz.inkFaint),
                  const SizedBox(height: 12),
                  Text(_error ?? '', textAlign: TextAlign.center),
                  const SizedBox(height: 16),
                  FilledButton(onPressed: _load, child: const Text('重试')),
                ]),
              ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return SzNavScaffold(
      selectedIndex: _tab,
      contentMaxWidth: _tab == _kTabMenu ? kFeedMaxWidth : kContentMaxWidth,
      onSelected: (i) => setState(() {
        _tab = i;
        _visited.add(i);
      }),
      items: const [
        SzNavItem(
            icon: Icons.restaurant_menu_outlined,
            selectedIcon: Icons.restaurant_menu,
            label: '点餐'),
        SzNavItem(
            icon: Icons.receipt_long_outlined,
            selectedIcon: Icons.receipt_long,
            label: '订单'),
        SzNavItem(
            icon: Icons.person_outline, selectedIcon: Icons.person, label: '我的'),
      ],
      // 点餐那一格自己有标题栏(店名);订单、我的由外壳给
      appBar: switch (_tab) {
        _kTabOrders => AppBar(title: const Text('我的订单')),
        _kTabMe => AppBar(title: const Text('我的'), actions: [
            IconButton(
              icon: const Icon(Icons.support_agent_outlined),
              tooltip: '联系客服',
              onPressed: () async {
                if (!await ensureLoggedIn(context)) return;
                if (!context.mounted) return;
                await Navigator.of(context).push(MaterialPageRoute<void>(
                    builder: (_) => SupportPage(api: widget.api)));
              },
            ),
            IconButton(
              icon: const Icon(Icons.settings_outlined),
              tooltip: '设置',
              onPressed: () => Navigator.of(context).push(MaterialPageRoute<void>(
                  builder: (_) => SettingsPage(api: widget.api))),
            ),
          ]),
        _ => null,
      },
      body: IndexedStack(index: _tab, children: [
        _menuTab(),
        // 订单 tab 要等店拉到才建:列表按这家店过滤,id 还没有的时候建出来就是全部的单
        _visited.contains(_kTabOrders) && SingleStore.id != null
            ? OrdersTab(api: widget.api)
            : const SizedBox.shrink(),
        _visited.contains(_kTabMe)
            ? ProfileView(api: widget.api, onOpenOrders: _openOrders)
            : const SizedBox.shrink(),
      ]),
    );
  }
}
