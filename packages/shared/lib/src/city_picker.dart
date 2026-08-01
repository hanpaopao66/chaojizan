import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'brand.dart';

/// 地址搜索的城市切换器(#172)。
///
/// ## 为什么必须有它
///
/// 服务端的 POI 搜索用腾讯的 `region_fix=1`,把结果**限死在指定城市** ——
/// 不加的话搜「一号店」会把全国同名地点都返回,用户很容易选中外地那个,
/// 下单后才发现超出配送范围。
///
/// 但代价是:**城市选错,用户搜自己家会一条都搜不到**。
/// 实测西安的「紫薇臻品」在 city=成都 时返回 0 条 ——
/// 而客户端此前一直传写死的「成都」。成都以外的用户根本搜不出自己的地址,
/// 界面上还看不出为什么。
///
/// 所以这个切换器不是锦上添花,是那个 bug 的正解。
///
/// ## 城市从哪来
///
/// 服务端给的是**实际有商家的城市**(或管理员配置的开城清单)——
/// 列一个没有商家的城市,用户切过去只会看到空列表。
///
/// ## 记住选择
///
/// 用户切过一次就记住(SharedPreferences)。他多半是在给固定的某个地方
/// 点单(家/公司),每次都要重选是折磨。
class CityPref {
  static const _key = 'addr_search_city';

  /// 读记住的城市。没记过返回空 —— 调用方该退回定位解析出来的城市。
  static Future<String> load() async {
    try {
      final sp = await SharedPreferences.getInstance();
      return sp.getString(_key) ?? '';
    } catch (_) {
      return '';
    }
  }

  static Future<void> save(String city) async {
    try {
      final sp = await SharedPreferences.getInstance();
      await sp.setString(_key, city);
    } catch (_) {
      // 存不上不影响用 —— 大不了下次再选一次
    }
  }
}

/// 顶部那个「成都市 ⌄」。点开弹出可选城市。
class SzCityChip extends StatelessWidget {
  const SzCityChip({
    super.key,
    required this.city,
    required this.loadCities,
    required this.onChanged,
  });

  /// 当前城市。空串时显示「选择城市」——**不要显示一个猜的城市**,
  /// 那会让用户以为已经选对了,然后搜不出东西也不知道为什么
  final String city;

  final Future<List<({String name, int merchants})>> Function() loadCities;
  final ValueChanged<String> onChanged;

  Future<void> _pick(BuildContext context) async {
    final picked = await showModalBottomSheet<String>(
      context: context,
      builder: (ctx) => _CitySheet(loadCities: loadCities, current: city),
    );
    if (picked != null && picked != city) onChanged(picked);
  }

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    return InkWell(
      onTap: () => _pick(context),
      borderRadius: BorderRadius.circular(4),
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 4, vertical: 6),
        child: Row(mainAxisSize: MainAxisSize.min, children: [
          Text(city.isEmpty ? '选择城市' : city,
              style: TextStyle(
                  fontSize: 14,
                  fontWeight: FontWeight.w600,
                  color: city.isEmpty ? sz.clay : sz.ink)),
          Icon(Icons.expand_more, size: 17, color: sz.inkMuted),
        ]),
      ),
    );
  }
}

class _CitySheet extends StatefulWidget {
  const _CitySheet({required this.loadCities, required this.current});

  final Future<List<({String name, int merchants})>> Function() loadCities;
  final String current;

  @override
  State<_CitySheet> createState() => _CitySheetState();
}

class _CitySheetState extends State<_CitySheet> {
  List<({String name, int merchants})>? _list;
  Object? _error;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final l = await widget.loadCities();
      if (mounted) setState(() => _list = l);
    } catch (e) {
      if (mounted) setState(() => _error = e);
    }
  }

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    return SafeArea(
      child: Padding(
        padding: const EdgeInsets.fromLTRB(kPagePad, 14, kPagePad, 10),
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          Row(children: [
            const Text('选择城市',
                style: TextStyle(fontSize: 16, fontWeight: FontWeight.w600)),
            const Spacer(),
            IconButton(
              icon: const Icon(Icons.close, size: 20),
              onPressed: () => Navigator.of(context).pop(),
            ),
          ]),
          const SizedBox(height: 2),
          Align(
            alignment: Alignment.centerLeft,
            child: Text('搜地址时只在选中的城市里找 —— 选错了会搜不到自己家',
                style: TextStyle(fontSize: 11.5, color: sz.inkFaint)),
          ),
          const SizedBox(height: 10),
          if (_error != null)
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 20),
              child: Text('拿不到城市列表:$_error',
                  style: TextStyle(fontSize: 12.5, color: sz.inkMuted)),
            )
          else if (_list == null)
            const Padding(
              padding: EdgeInsets.symmetric(vertical: 28),
              child: CircularProgressIndicator(),
            )
          else if (_list!.isEmpty)
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 20),
              child: Text('还没有开通的城市',
                  style: TextStyle(fontSize: 12.5, color: sz.inkMuted)),
            )
          else
            Flexible(
              child: ListView(
                shrinkWrap: true,
                children: [
                  for (final c in _list!)
                    ListTile(
                      dense: true,
                      contentPadding: EdgeInsets.zero,
                      leading: Icon(
                        c.name == widget.current
                            ? Icons.radio_button_checked
                            : Icons.radio_button_unchecked,
                        size: 18,
                        color: c.name == widget.current ? sz.clay : sz.inkFaint,
                      ),
                      title: Text(c.name,
                          style: TextStyle(
                              fontSize: 14.5,
                              color: c.name == widget.current
                                  ? sz.clay
                                  : sz.ink)),
                      // 商家数要露出来:**开城清单里可能有还没商家的城市**,
                      // 用户切过去会看到空列表 —— 先告诉他
                      trailing: Text(
                        c.merchants > 0 ? '${c.merchants} 家店' : '暂无商家',
                        style: TextStyle(
                            fontSize: 11.5,
                            color: c.merchants > 0 ? sz.inkMuted : sz.hold),
                      ),
                      onTap: () => Navigator.of(context).pop(c.name),
                    ),
                ],
              ),
            ),
        ]),
      ),
    );
  }
}
