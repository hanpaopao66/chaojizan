import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'brand.dart';
import 'models.dart';
import 'responsive.dart';

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

  /// 初始城市:**定位解析 > 记住的选择 > 留空让他自己选**。
  ///
  /// ⚠️ 这个顺序 2026-08-23 反过来过一次。原来是「记住的优先」,理由是
  /// 「他多半在给固定的某个地方点单,每次重选是折磨」—— 但推演下来
  /// 那个顺序在两种真实场景里都是错的:
  ///
  /// - 他在西安,偶尔给北京朋友点一次 → 记住北京 → **此后一直是北京**,
  ///   而他人在西安,搜自己家又搜不到了(正是这个组件要解决的那个 bug);
  /// - 他从西安搬到北京 → 记住西安 → 定位早就变了,城市却不跟。
  ///
  /// 所以默认跟定位,记住的那个降级成**定位拿不到时的兜底**。
  /// 手动选依然管用 —— 只是它管的是「这一次」,不是「从此以后」。
  ///
  /// 留空时切换器显示「选择城市」——**不猜一个填进去**:
  /// 猜错了用户会以为已经选对,然后搜不出东西也不知道为什么。
  ///
  /// 抽到这里是因为用户端和商家端要用同一套优先级 ——
  /// 各写一遍的下场是两端行为不一致,而"为什么商家端搜不出来"
  /// 这种问题极难从表象追到根因。
  /// [lastKnown] 由调用方注入(shared 不依赖定位插件),
  /// [reverse] 是坐标 → **城市名**(不是地址串)—— 调用方传
  /// `(await api.geoReverse(lat, lng)).city`,解析在服务端做。
  static Future<String> resolve({
    Future<({double lat, double lng})?> Function()? lastKnown,
    Future<String> Function(double, double)? reverse,
  }) async {
    final saved = await load();
    if (lastKnown != null && reverse != null) {
      try {
        final me = await lastKnown();
        if (me != null) {
          // [reverse] 直接给城市名,**这里不做任何解析**。
          //
          // 以前是服务端回一串「陕西省西安市雁塔区…」、客户端用正则抠 ——
          // 而 `[\u4e00-\u9fa5]{2,8}市` 是贪婪的,从头能一路吃到
          // 「陕西省西安市」,拿它当腾讯 POI 的 city 参数搜出来是 0 条,
          // 界面上还看不出为什么(正是这个组件当初要解决的那个 bug)。
          //
          // 根治办法不是把正则写对,是**不在客户端猜**:腾讯的逆地理返回里
          // 本来就有结构化的 address_component.city,服务端 /geo/reverse
          // 现在把它透出来了,而且和商家入驻解析城市(services/geo_city.py)
          // 同一个口径 —— 两边不一致的话,用户搜的城市和商家标的城市对不上
          final located = await reverse(me.lat, me.lng);
          if (located.isNotEmpty) return located;
        }
      } catch (_) {
        // 定位/逆地理失败:落到下面的 saved 兜底
      }
    }
    return saved; // 空串也照样返回 —— 留空时切换器显示「选择城市」
  }

  static Future<void> save(String city) async {
    try {
      final sp = await SharedPreferences.getInstance();
      await sp.setString(_key, city);
      await _pushRecent(city);
    } catch (_) {
      // 存不上不影响用 —— 大不了下次再选一次
    }
  }

  static const _recentKey = 'addr_search_city_recent';
  static const _recentMax = 6;

  /// 最近选过的城市(最新在前)。
  ///
  /// 为什么要有:出差的人在两三个城市之间来回切,而全国 393 个城市
  /// 靠字母索引翻是折磨。这一栏解决的是**重复选择**,
  /// 和「记住上次选的」不是一回事 —— 那个只记一个。
  static Future<List<String>> recent() async {
    try {
      final sp = await SharedPreferences.getInstance();
      return sp.getStringList(_recentKey) ?? const [];
    } catch (_) {
      return const [];
    }
  }

  static Future<void> _pushRecent(String city) async {
    if (city.isEmpty) return;
    final sp = await SharedPreferences.getInstance();
    final list = (sp.getStringList(_recentKey) ?? <String>[]).toList()
      ..remove(city)          // 已经在里面就提到最前,不留两份
      ..insert(0, city);
    await sp.setStringList(
        _recentKey, list.take(_recentMax).toList());
  }
}

/// 顶部那个「成都市 ⌄」。点开弹出可选城市。
class SzCityChip extends StatelessWidget {
  const SzCityChip({
    super.key,
    required this.city,
    required this.loadCities,
    required this.onChanged,
    this.loadCatalog,
    this.locatedCity = '',
  });

  /// 当前城市。空串时显示「选择城市」——**不要显示一个猜的城市**,
  /// 那会让用户以为已经选对了,然后搜不出东西也不知道为什么
  final String city;

  final Future<List<({String name, int merchants})>> Function() loadCities;
  final ValueChanged<String> onChanged;

  /// 全量城市目录。给了就用全量选择器(定位/最近/热门/A–Z),
  /// 不给退回只列有店城市的旧弹层 —— 老调用方不用改
  final Future<SzCityCatalog> Function()? loadCatalog;

  /// 定位到的城市,置顶显示成「当前定位」。空 = 没定位到
  final String locatedCity;

  Future<void> _pick(BuildContext context) async {
    final loader = loadCatalog;
    final picked = loader != null
        ? await szShowSheet<String>(
            context: context,
            builder: (ctx) => _CityCatalogSheet(
                loadCatalog: loader,
                current: city,
                located: locatedCity),
          )
        : await szShowSheet<String>(
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
                style: TextStyle(fontSize: 11.5, color: sz.inkMuted)),
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
                        color: c.name == widget.current ? sz.clay : sz.inkMuted,
                      ),
                      title: Text(c.name,
                          style: TextStyle(
                              fontSize: 14.5,
                              color:
                                  c.name == widget.current ? sz.clay : sz.ink)),
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

/// 全量城市选择器:定位 / 最近访问 / 热门 / 全部(A–Z + 字母索引)。
///
/// ## 为什么要给全国城市,而不是只给有店的
///
/// 人会出差、会搬家。到了一个还没开通的城市,只列有店城市的话
/// 列表里一条都没有 —— 他连「这里到底开没开」都看不出来,
/// 只会以为 App 坏了。
///
/// 所以给全量,但**每一条都标着有几家店**:让他自己看到
/// 「这里还没有商家」,而不是让他猜。
///
/// ## 为什么不做成「按省分组」
///
/// 用户找城市时脑子里是城市名,不是省名 —— 知道「无锡」在哪个省
/// 的人远少于知道「无锡」的人。按拼音首字母分组配右侧索引,
/// 是找名字最快的路;搜索框则覆盖「我懒得翻」。
class _CityCatalogSheet extends StatefulWidget {
  const _CityCatalogSheet({
    required this.loadCatalog,
    required this.current,
    required this.located,
  });

  final Future<SzCityCatalog> Function() loadCatalog;
  final String current;
  final String located;

  @override
  State<_CityCatalogSheet> createState() => _CityCatalogSheetState();
}

class _CityCatalogSheetState extends State<_CityCatalogSheet> {
  SzCityCatalog? _catalog;
  Object? _error;
  List<String> _recent = const [];
  String _query = '';
  final _scroll = ScrollController();

  /// 每个首字母在列表里的行下标 —— 右侧索引按它跳
  final Map<String, int> _anchors = {};

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    _scroll.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    try {
      final c = await widget.loadCatalog();
      final r = await CityPref.recent();
      if (mounted) setState(() { _catalog = c; _recent = r; });
    } catch (e) {
      if (mounted) setState(() => _error = e);
    }
  }

  /// 搜索命中:短名、全名、拼音都算。
  /// 拼音也算是必须的 —— 输入法没切中文时打 "chengdu" 也该找得到
  bool _match(SzCity c) {
    if (_query.isEmpty) return true;
    final q = _query.toLowerCase();
    return c.short.contains(_query) ||
        c.name.contains(_query) ||
        c.pinyin.startsWith(q);
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
          Align(
            alignment: Alignment.centerLeft,
            child: Text('搜地址时只在选中的城市里找 —— 选错了会搜不到自己家',
                style: TextStyle(fontSize: 11.5, color: sz.inkMuted)),
          ),
          const SizedBox(height: 10),
          TextField(
            decoration: InputDecoration(
              isDense: true,
              prefixIcon: const Icon(Icons.search, size: 18),
              hintText: '城市名或拼音,如 成都 / chengdu',
              hintStyle: TextStyle(fontSize: 13, color: sz.inkFaint),
              border: const OutlineInputBorder(),
              contentPadding:
                  const EdgeInsets.symmetric(horizontal: 8, vertical: 10),
            ),
            style: const TextStyle(fontSize: 14),
            onChanged: (v) => setState(() => _query = v.trim()),
          ),
          const SizedBox(height: 8),
          if (_error != null)
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 20),
              child: Text('拿不到城市列表:$_error',
                  style: TextStyle(fontSize: 12.5, color: sz.inkMuted)),
            )
          else if (_catalog == null)
            const Padding(
              padding: EdgeInsets.symmetric(vertical: 28),
              child: CircularProgressIndicator(),
            )
          else
            Flexible(child: _body(sz)),
        ]),
      ),
    );
  }

  Widget _body(SzColors sz) {
    final cat = _catalog!;
    // 全量拿不到时(接口降级 / 没配地图 key)退回有店的那几个 ——
    // 少了全国清单不该让整个选择器不可用
    final source = cat.all.isNotEmpty ? cat.all : cat.open;
    final hits = source.where(_match).toList()
      ..sort((a, b) {
        final c = a.initial.compareTo(b.initial);
        return c != 0 ? c : a.pinyin.compareTo(b.pinyin);
      });

    final rows = <Widget>[];
    _anchors.clear();
    if (_query.isEmpty) {
      if (widget.located.isNotEmpty) {
        rows.add(_sectionTitle('当前定位', sz));
        rows.add(_cityRow(_find(source, widget.located) ??
            SzCity(
                name: widget.located,
                short: widget.located,
                province: '',
                initial: '#',
                pinyin: '',
                merchants: 0)));
      }
      if (_recent.isNotEmpty) {
        rows.add(_sectionTitle('最近访问', sz));
        rows.add(_chipWrap(
            _recent.map((n) => _find(source, n) ??
                SzCity(name: n, short: n, province: '', initial: '#',
                    pinyin: '', merchants: 0)).toList()));
      }
      if (cat.hot.isNotEmpty) {
        rows.add(_sectionTitle('已开通(有商家)', sz));
        rows.add(_chipWrap(cat.hot));
      }
      rows.add(_sectionTitle('全部城市', sz));
    }

    String? last;
    for (final c in hits) {
      if (_query.isEmpty && c.initial != last) {
        last = c.initial;
        _anchors[c.initial] = rows.length;
        rows.add(Padding(
          padding: const EdgeInsets.fromLTRB(0, 10, 0, 4),
          child: Text(c.initial,
              style: TextStyle(
                  fontSize: 12,
                  fontWeight: FontWeight.w700,
                  color: sz.inkMuted)),
        ));
      }
      rows.add(_cityRow(c));
    }
    if (hits.isEmpty) {
      rows.add(Padding(
        padding: const EdgeInsets.symmetric(vertical: 24),
        child: Text('没有匹配的城市',
            textAlign: TextAlign.center,
            style: TextStyle(fontSize: 12.5, color: sz.inkMuted)),
      ));
    }

    final letters = _anchors.keys.toList()..sort();
    return Row(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      Expanded(
        child: ListView.builder(
          controller: _scroll,
          itemCount: rows.length,
          itemExtent: null,
          itemBuilder: (_, i) => rows[i],
        ),
      ),
      // 右侧字母索引。搜索时没有分组,索引也就没有意义 —— 整条藏掉
      if (letters.isNotEmpty && _query.isEmpty)
        SizedBox(
          width: 22,
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              for (final l in letters)
                Expanded(
                  child: GestureDetector(
                    behavior: HitTestBehavior.opaque,
                    onTap: () => _jumpTo(l),
                    child: Center(
                      child: Text(l,
                          style: TextStyle(
                              fontSize: 10,
                              fontWeight: FontWeight.w600,
                              color: sz.inkMuted)),
                    ),
                  ),
                ),
            ],
          ),
        ),
    ]);
  }

  SzCity? _find(List<SzCity> list, String name) {
    for (final c in list) {
      if (c.name == name || c.short == name) return c;
    }
    return null;
  }

  /// 跳到某个首字母。行高不定,按「平均行高 × 行下标」估 ——
  /// 估得不准也没关系:落在目标附近,用户再滑一点点就到了。
  /// 真要精确得给每行装 GlobalKey,那个代价换不来对应的体验提升
  void _jumpTo(String letter) {
    final idx = _anchors[letter];
    if (idx == null || !_scroll.hasClients) return;
    const rowH = 44.0;
    final target = (idx * rowH)
        .clamp(0.0, _scroll.position.maxScrollExtent);
    _scroll.animateTo(target,
        duration: const Duration(milliseconds: 200), curve: Curves.easeOut);
  }

  Widget _sectionTitle(String t, SzColors sz) => Padding(
        padding: const EdgeInsets.fromLTRB(0, 12, 0, 6),
        child: Text(t,
            style: TextStyle(
                fontSize: 12, fontWeight: FontWeight.w700, color: sz.ink)),
      );

  Widget _chipWrap(List<SzCity> cities) => Wrap(
        spacing: 8,
        runSpacing: 8,
        children: [for (final c in cities) _cityChip(c)],
      );

  Widget _cityChip(SzCity c) {
    final sz = Theme.of(context).sz;
    final on = c.name == widget.current;
    return InkWell(
      onTap: () => Navigator.of(context).pop(c.name),
      borderRadius: BorderRadius.circular(4),
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 7),
        decoration: BoxDecoration(
          color: on ? sz.clay.withValues(alpha: 0.10) : sz.surfaceAlt,
          borderRadius: BorderRadius.circular(4),
          border: Border.all(color: on ? sz.clay : Colors.transparent),
        ),
        child: Text(c.short,
            style: TextStyle(
                fontSize: 13,
                color: on ? sz.clay : sz.ink,
                fontWeight: on ? FontWeight.w600 : FontWeight.w400)),
      ),
    );
  }

  Widget _cityRow(SzCity c) {
    final sz = Theme.of(context).sz;
    final on = c.name == widget.current;
    return ListTile(
      dense: true,
      contentPadding: EdgeInsets.zero,
      visualDensity: VisualDensity.compact,
      title: Text(c.short,
          style: TextStyle(fontSize: 14.5, color: on ? sz.clay : sz.ink)),
      subtitle: c.province.isEmpty
          ? null
          : Text(c.province,
              style: TextStyle(fontSize: 11, color: sz.inkFaint)),
      // 有几家店必须露出来:全量清单里绝大多数城市还没开通,
      // 切过去会看到空列表 —— 先告诉他,别让他以为 App 坏了
      trailing: Text(
        c.merchants > 0 ? '${c.merchants} 家店' : '暂无商家',
        style: TextStyle(
            fontSize: 11.5, color: c.merchants > 0 ? sz.inkMuted : sz.hold),
      ),
      onTap: () => Navigator.of(context).pop(c.name),
    );
  }
}
