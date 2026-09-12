/// 小程序的几张页面(#326):全部小程序(目录)、详情、投诉、授权与数据、直达链接落地。
///
/// 目录的排序**客户端一概不动**:服务端的纯函数排好了就照着画(精选在前,其余按首次上架时间),
/// 页脚照抄服务端给的排序规则原文 —— 规则只写一处,抄两份迟早对不上。
library;

import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:superz_shared/superz_shared.dart';

import '../session.dart';
import 'container.dart';

// ---------------------------------------------------------------- 目录

class MiniAppCatalogPage extends StatefulWidget {
  const MiniAppCatalogPage({super.key, required this.api});

  final ApiClient api;

  @override
  State<MiniAppCatalogPage> createState() => _MiniAppCatalogPageState();
}

class _MiniAppCatalogPageState extends State<MiniAppCatalogPage> {
  final _q = TextEditingController();
  MiniAppCatalog? _data;
  String? _category;
  String? _error;
  bool _loading = false;

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    _q.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    setState(() => _loading = true);
    try {
      final d = await widget.api.miniAppCatalog(
          kind: _category == 'game' ? 'game' : null,
          category: _category == null || _category == 'game' ? null : _category,
          q: _q.text,
          limit: 100);
      if (mounted) setState(() => (_data = d, _error = null));
    } catch (e) {
      if (mounted) setState(() => _error = '$e');
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    final d = _data;
    final tabs = <({String? key, String label})>[
      (key: null, label: '全部'),
      (key: 'game', label: '小游戏'),
      for (final c in d?.categories ?? const <({String key, String label})>[]) (key: c.key, label: c.label),
    ];
    return SzPageScaffold(
      appBar: AppBar(title: const Text('全部小程序')),
      body: RefreshIndicator(
        onRefresh: _load,
        child: ListView(padding: const EdgeInsets.fromLTRB(kPagePad, 8, kPagePad, kPagePad), children: [
          TextField(
            controller: _q,
            textInputAction: TextInputAction.search,
            onSubmitted: (_) => _load(),
            decoration: InputDecoration(
              hintText: '搜索小程序',
              prefixIcon: const Icon(Icons.search),
              suffixIcon: _q.text.isEmpty
                  ? null
                  : IconButton(icon: const Icon(Icons.clear), onPressed: () {
                      _q.clear();
                      _load();
                    }),
              isDense: true,
            ),
            onChanged: (_) => setState(() {}),
          ),
          const SizedBox(height: 10),
          SingleChildScrollView(
            scrollDirection: Axis.horizontal,
            child: Row(children: [
              for (final t in tabs)
                Padding(
                  padding: const EdgeInsets.only(right: 8),
                  child: ChoiceChip(
                    label: Text(t.label),
                    selected: _category == t.key,
                    onSelected: (_) {
                      setState(() => _category = t.key);
                      _load();
                    },
                  ),
                ),
            ]),
          ),
          const SizedBox(height: 8),
          if (_error != null)
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 32),
              child: Text(_error!, textAlign: TextAlign.center, style: TextStyle(color: sz.inkMuted)),
            )
          else if (d == null || _loading && d.items.isEmpty)
            const Padding(padding: EdgeInsets.all(40), child: Center(child: CircularProgressIndicator()))
          else if (d.items.isEmpty)
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 40),
              child: Text(_q.text.isEmpty ? '这个分类下还没有小程序' : '没有找到「${_q.text}」',
                  textAlign: TextAlign.center, style: TextStyle(color: sz.inkMuted)),
            )
          else
            for (final a in d.items) MiniAppRow(api: widget.api, card: a),
          const SizedBox(height: 18),
          // 排序规则照抄服务端原文,并链到规则页
          Text(d?.sortRule ?? '', style: TextStyle(fontSize: kFontMicro, color: sz.inkFaint, height: 1.5)),
          const SizedBox(height: 4),
          Text('规则全文见官网「开发者 → 运营规范」;每次精选变动的理由在透明中心公示。',
              style: TextStyle(fontSize: kFontMicro, color: sz.inkFaint)),
        ]),
      ),
    );
  }
}

/// 目录里的一行:图标、名称、一句话、开发者。点整行进详情,右边「打开」直接打开。
class MiniAppRow extends StatelessWidget {
  const MiniAppRow({super.key, required this.api, required this.card});

  final ApiClient api;
  final MiniAppCard card;

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    return InkWell(
      onTap: () => Navigator.of(context)
          .push(MaterialPageRoute(builder: (_) => MiniAppDetailPage(api: api, appid: card.appid, card: card))),
      child: Padding(
        padding: const EdgeInsets.symmetric(vertical: 10),
        child: Row(children: [
          MiniAppIcon(card: card, api: api, size: 48),
          const SizedBox(width: 12),
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Row(children: [
                Flexible(
                  child: Text(card.name,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: TextStyle(fontSize: kFontBodyLg, fontWeight: FontWeight.w600, color: sz.ink)),
                ),
                if (card.curated) ...[
                  const SizedBox(width: 6),
                  Text('精选', style: TextStyle(fontSize: kFontMicro, color: sz.clay)),
                ],
                if (card.isGame) ...[
                  const SizedBox(width: 6),
                  Text('小游戏', style: TextStyle(fontSize: kFontMicro, color: sz.inkFaint)),
                ],
              ]),
              if (card.tagline.isNotEmpty)
                Text(card.tagline,
                    maxLines: 1, overflow: TextOverflow.ellipsis, style: TextStyle(fontSize: kFontNote, color: sz.inkMuted)),
              Text('${card.developer.name} · ${card.developer.label}',
                  maxLines: 1, overflow: TextOverflow.ellipsis, style: TextStyle(fontSize: kFontMicro, color: sz.inkFaint)),
            ]),
          ),
          const SizedBox(width: 8),
          OutlinedButton(
            style: OutlinedButton.styleFrom(visualDensity: VisualDensity.compact),
            onPressed: () => openMiniApp(context, api, appid: card.appid, card: card),
            child: const Text('打开'),
          ),
        ]),
      ),
    );
  }
}

// ---------------------------------------------------------------- 详情

class MiniAppDetailPage extends StatefulWidget {
  const MiniAppDetailPage({super.key, required this.api, required this.appid, this.card});

  final ApiClient api;
  final String appid;
  final MiniAppCard? card;

  @override
  State<MiniAppDetailPage> createState() => _MiniAppDetailPageState();
}

class _MiniAppDetailPageState extends State<MiniAppDetailPage> {
  MiniAppDetail? _d;
  String? _error;

  static const _capLabels = {
    'initData': '识别你是谁(按应用隔离的编号,不含手机号)',
    'storage': '云存储(只存你在这个小程序里的数据)',
    'share': '系统分享',
    'haptics': '触感反馈',
    'popup': '弹窗',
    'openLink': '打开外部链接(先问你)',
    'fullscreen': '全屏',
    'orientation': '锁定屏幕方向',
    'profile': '昵称和头像(要你同意)',
  };

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final d = await widget.api.miniAppDetail(widget.appid);
      if (mounted) setState(() => (_d = d, _error = null));
    } catch (e) {
      if (mounted) setState(() => _error = '$e');
    }
  }

  Future<void> _star(bool on) async {
    if (!await ensureLoggedIn(context)) return;
    try {
      await widget.api.miniAppStar(widget.appid, starred: on);
      await _load();
    } catch (e) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('$e')));
    }
  }

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    final d = _d;
    final card = d?.card ?? widget.card;
    Widget section(String title, List<Widget> children) => Padding(
          padding: const EdgeInsets.only(top: 18),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(title, style: TextStyle(fontSize: kFontBodyLg, fontWeight: FontWeight.w600, color: sz.ink)),
            const SizedBox(height: 6),
            ...children,
          ]),
        );
    TextStyle body = TextStyle(fontSize: kFontBody, color: sz.inkMuted, height: 1.55);
    return SzPageScaffold(
      appBar: AppBar(title: Text(card?.name ?? '小程序')),
      body: _error != null && d == null
          ? Center(child: Text(_error!, style: TextStyle(color: sz.inkMuted)))
          : card == null
              ? const Center(child: CircularProgressIndicator())
              : ListView(padding: const EdgeInsets.all(kPagePad), children: [
                  Row(children: [
                    MiniAppIcon(card: card, api: widget.api, size: 64),
                    const SizedBox(width: 14),
                    Expanded(
                      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                        Text(card.name, style: szDisplay(fontSize: kFontLead, color: sz.ink)),
                        if (card.tagline.isNotEmpty) Text(card.tagline, style: body),
                        Text('${card.developer.name} · ${card.developer.label}',
                            style: TextStyle(fontSize: kFontNote, color: sz.inkFaint)),
                      ]),
                    ),
                  ]),
                  const SizedBox(height: 16),
                  if (d != null && !d.available)
                    Text(d.status == 'suspended' ? '这个小程序已被平台暂停' : '这个小程序暂时下架了(${d.statusLabel})',
                        style: TextStyle(color: sz.danger)),
                  Row(children: [
                    Expanded(
                      child: FilledButton(
                        onPressed: d == null || !d.available
                            ? null
                            : () => openMiniApp(context, widget.api, appid: card.appid, card: card),
                        child: const Text('打开'),
                      ),
                    ),
                    const SizedBox(width: 10),
                    OutlinedButton.icon(
                      onPressed: d == null ? null : () => _star(!d.starred),
                      icon: Icon(d?.starred == true ? Icons.star : Icons.star_border),
                      label: Text(d?.starred == true ? '已添加' : '添加到我的'),
                    ),
                  ]),
                  Row(children: [
                    TextButton.icon(
                      onPressed: d == null
                          ? null
                          : () async {
                              await Clipboard.setData(ClipboardData(text: d.link));
                              if (context.mounted) {
                                ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('链接已复制')));
                              }
                            },
                      icon: const Icon(Icons.link),
                      label: const Text('复制链接'),
                    ),
                    TextButton.icon(
                      onPressed: () => showMiniAppReportSheet(context, widget.api, card),
                      icon: const Icon(Icons.flag_outlined),
                      label: const Text('投诉'),
                    ),
                  ]),
                  if (d != null && d.description.isNotEmpty) section('介绍', [Text(d.description, style: body)]),
                  if (d?.version != null)
                    section('版本', [
                      Text('${d!.version!.version}(build ${d.version!.build})'
                          '${d.version!.releasedAt == null ? '' : ' · ${_date(d.version!.releasedAt!)} 发布'}',
                          style: body),
                      const SizedBox(height: 4),
                      // 当前版本的 SHA-256:任何人都能拿开源仓的构建产物来对
                      SelectableText('SHA-256 ${d.version!.sha256}',
                          style: TextStyle(fontSize: kFontMicro, color: sz.inkFaint, fontFamily: 'monospace')),
                    ]),
                  if (d != null)
                    section('用到的能力', [
                      for (final c in d.capabilities) Text('· ${_capLabels[c] ?? c}', style: body),
                    ]),
                  if (d != null)
                    section('收集哪些信息', [
                      if (d.dataDeclaration.isEmpty) Text('开发者声明:不收集任何信息', style: body),
                      for (final x in d.dataDeclaration) Text('· ${x.field}:${x.purpose}', style: body),
                    ]),
                  if (d != null && d.requestDomains.isNotEmpty)
                    section('会连接的服务器', [for (final x in d.requestDomains) Text('· $x', style: body)]),
                  if (d != null && d.privacyPolicy.isNotEmpty)
                    section('隐私政策', [Text(d.privacyPolicy, style: body)]),
                  const SizedBox(height: 24),
                ]),
    );
  }
}

String _date(DateTime t) {
  final l = t.toLocal();
  return '${l.year}-${l.month.toString().padLeft(2, '0')}-${l.day.toString().padLeft(2, '0')}';
}

// ---------------------------------------------------------------- 投诉

/// 用户能选的原因(§5.9 的子集:用户看得出来的那些)。说明原文只给审核员,不给开发者。
const kUserReportReasons = <(String, String)>[
  ('R101', '打不开或功能用不了'),
  ('R102', '和介绍说的不一样'),
  ('R204', '要我分享、关注、下载才能用'),
  ('R205', '虚假宣传'),
  ('R201', '违法违规内容'),
  ('R202', '色情低俗'),
  ('R203', '赌博'),
  ('R501', '仿冒超级赞或别的品牌'),
  ('R303', '没经我同意拿我的信息'),
  ('R207', '引导我去别处交易'),
  ('R701', '其他'),
];

Future<void> showMiniAppReportSheet(BuildContext context, ApiClient api, MiniAppCard card) async {
  if (!await ensureLoggedIn(context)) return;
  if (!context.mounted) return;
  final done = await szShowSheet<bool>(context: context, builder: (_) => _ReportSheet(api: api, card: card));
  if (done == true && context.mounted) {
    ScaffoldMessenger.maybeOf(context)?.showSnackBar(
        const SnackBar(content: Text('收到了。审核结果会写进这个小程序的处理记录;你的身份不会给开发者')));
  }
}

class _ReportSheet extends StatefulWidget {
  const _ReportSheet({required this.api, required this.card});

  final ApiClient api;
  final MiniAppCard card;

  @override
  State<_ReportSheet> createState() => _ReportSheetState();
}

class _ReportSheetState extends State<_ReportSheet> {
  String? _reason;
  final _detail = TextEditingController();
  bool _sending = false;
  String? _error;

  @override
  void dispose() {
    _detail.dispose();
    super.dispose();
  }

  Future<void> _send() async {
    if (_reason == null) return;
    setState(() => (_sending = true, _error = null));
    try {
      await widget.api.miniAppReport(widget.card.appid, reasonCode: _reason!, detail: _detail.text.trim());
      if (mounted) Navigator.pop(context, true);
    } catch (e) {
      if (mounted) setState(() => (_sending = false, _error = '$e'));
    }
  }

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    return Padding(
      padding: EdgeInsets.fromLTRB(kPagePad, 4, kPagePad, kPagePad + MediaQuery.viewInsetsOf(context).bottom),
      child: SingleChildScrollView(
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisSize: MainAxisSize.min, children: [
          Text('投诉「${widget.card.name}」', style: TextStyle(fontSize: kFontTitle, fontWeight: FontWeight.w600, color: sz.ink)),
          const SizedBox(height: 4),
          Text('直达平台,开发者看得到原因和处理结果,看不到是谁投诉的。',
              style: TextStyle(fontSize: kFontNote, color: sz.inkMuted)),
          const SizedBox(height: 10),
          Wrap(spacing: 8, runSpacing: 4, children: [
            for (final (code, label) in kUserReportReasons)
              ChoiceChip(label: Text(label), selected: _reason == code, onSelected: (_) => setState(() => _reason = code)),
          ]),
          const SizedBox(height: 10),
          TextField(
            controller: _detail,
            maxLength: 500,
            maxLines: 3,
            decoration: InputDecoration(
              hintText: _reason == 'R701' ? '选了「其他」,请写明是什么情况' : '补充说明(可选)',
            ),
          ),
          if (_error != null) Text(_error!, style: TextStyle(color: sz.danger, fontSize: kFontNote)),
          const SizedBox(height: 6),
          SizedBox(
            width: double.infinity,
            child: FilledButton(
              onPressed: _reason == null || _sending ? null : _send,
              child: Text(_sending ? '提交中…' : '提交投诉'),
            ),
          ),
        ]),
      ),
    );
  }
}

// ---------------------------------------------------------------- 授权与数据(我的 → 设置)

class MiniAppDataPage extends StatefulWidget {
  const MiniAppDataPage({super.key, required this.api});

  final ApiClient api;

  @override
  State<MiniAppDataPage> createState() => _MiniAppDataPageState();
}

class _MiniAppDataPageState extends State<MiniAppDataPage> {
  List<MiniAppDataItem>? _items;
  String? _error;
  bool _tester = false;
  bool _debug = false;

  @override
  void initState() {
    super.initState();
    _load();
    SharedPreferences.getInstance().then((p) {
      if (mounted) {
        setState(() {
          _tester = p.getBool(kMiniAppTesterPref) ?? false;
          _debug = p.getBool(kMiniAppDebugPref) ?? false;
        });
      }
    });
  }

  Future<void> _load() async {
    try {
      final items = await widget.api.miniAppDataList();
      if (mounted) setState(() => (_items = items, _error = null));
    } catch (e) {
      if (mounted) setState(() => _error = '$e');
    }
  }

  String _size(int bytes) =>
      bytes < 1024 ? '$bytes B' : bytes < 1024 * 1024 ? '${(bytes / 1024).toStringAsFixed(1)} KB' : '${(bytes / 1048576).toStringAsFixed(2)} MB';

  Future<void> _export(MiniAppDataItem it) async {
    try {
      final data = await widget.api.miniAppExport(it.card.appid);
      final text = const JsonEncoder.withIndent('  ').convert(data);
      await Clipboard.setData(ClipboardData(text: text));
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(content: Text('「${it.card.name}」的数据已复制为 JSON(${_size(text.length)}),可以粘贴保存')));
      }
    } catch (e) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('$e')));
    }
  }

  Future<void> _clear(MiniAppDataItem it, {required bool all}) async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => SzDialog(
        title: Text(all ? '移除「${it.card.name}」?' : '清空「${it.card.name}」的云存储?'),
        content: Text(all
            ? '清空它的云存储、撤回全部授权,并从最近使用和我的小程序里移除。删了找不回来。'
            : '它存在云端的数据会全部删掉,删了找不回来。'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('取消')),
          TextButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('确定')),
        ],
      ),
    );
    if (ok != true) return;
    try {
      await widget.api.miniAppClearData(it.card.appid, all: all);
      await _load();
    } catch (e) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('$e')));
    }
  }

  Future<void> _revoke(MiniAppDataItem it, String scope) async {
    try {
      await widget.api.miniAppRevokeGrant(it.card.appid, scope);
      await _load();
    } catch (_) {}
  }

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    final items = _items;
    return SzPageScaffold(
      appBar: AppBar(title: const Text('小程序授权与数据')),
      body: RefreshIndicator(
        onRefresh: _load,
        child: ListView(padding: const EdgeInsets.all(kPagePad), children: [
          Text('每个小程序的数据按「应用 + 你的账号」隔离,开发者不能从服务端读取。'
              '你可以随时导出、清空;注销账号时全部删除。',
              style: TextStyle(fontSize: kFontNote, color: sz.inkMuted, height: 1.5)),
          const SizedBox(height: 12),
          if (_error != null) Text(_error!, style: TextStyle(color: sz.inkMuted)),
          if (items == null && _error == null) const Center(child: CircularProgressIndicator()),
          if (items != null && items.isEmpty)
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 32),
              child: Text('还没用过小程序', textAlign: TextAlign.center, style: TextStyle(color: sz.inkMuted)),
            ),
          for (final it in items ?? const <MiniAppDataItem>[])
            Card(
              margin: const EdgeInsets.only(bottom: 10),
              child: Padding(
                padding: const EdgeInsets.all(12),
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Row(children: [
                    MiniAppIcon(card: it.card, api: widget.api, size: 36),
                    const SizedBox(width: 10),
                    Expanded(
                      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                        Text(it.card.name, style: TextStyle(fontSize: kFontBodyLg, fontWeight: FontWeight.w600, color: sz.ink)),
                        Text('云存储 ${_size(it.bytes)} / 5 MB · ${it.keys} 条'
                            '${it.status == 'online' ? '' : ' · ${it.statusLabel}'}',
                            style: TextStyle(fontSize: kFontNote, color: sz.inkMuted)),
                      ]),
                    ),
                  ]),
                  if (it.grants.contains('profile'))
                    Row(children: [
                      Expanded(child: Text('已授权:昵称和头像', style: TextStyle(fontSize: kFontNote, color: sz.ink))),
                      TextButton(onPressed: () => _revoke(it, 'profile'), child: const Text('撤回')),
                    ]),
                  Wrap(spacing: 4, children: [
                    TextButton(onPressed: () => _export(it), child: const Text('导出')),
                    TextButton(onPressed: () => _clear(it, all: false), child: const Text('清空云存储')),
                    TextButton(
                      onPressed: () => _clear(it, all: true),
                      child: Text('移除', style: TextStyle(color: sz.danger)),
                    ),
                  ]),
                ]),
              ),
            ),
          // 开发者选项:只对当过体验者的人显示(扫过体验版二维码)
          if (_tester) ...[
            const SizedBox(height: 18),
            SzEntryGroup(title: '开发者选项', children: [
              SwitchListTile(
                title: const Text('小程序调试'),
                subtitle: const Text('安卓可在电脑 chrome://inspect 里调试页面;菜单里多一项桥调用日志'),
                value: _debug,
                onChanged: (v) async {
                  final p = await SharedPreferences.getInstance();
                  await p.setBool(kMiniAppDebugPref, v);
                  if (mounted) setState(() => _debug = v);
                },
              ),
            ]),
          ],
        ]),
      ),
    );
  }
}

// ---------------------------------------------------------------- 直达链接

/// `https://chaojizan.cc/m/<appid>[?startapp=…][&v=trial]` 拉起 App 之后落在这里。
class MiniAppLinkPage extends StatefulWidget {
  const MiniAppLinkPage({super.key, required this.api, required this.uri});

  final ApiClient api;
  final Uri uri;

  /// 从一条路由名里认出直达链接;认不出返回 null
  static ({String appid, String? startParam, bool trial})? parse(Uri uri) {
    final seg = uri.pathSegments;
    if (seg.length != 2 || seg[0] != 'm' || !RegExp(r'^sz[0-9a-f]{16}$').hasMatch(seg[1])) return null;
    final start = uri.queryParameters['startapp'];
    return (
      appid: seg[1],
      startParam: start != null && RegExp(r'^[A-Za-z0-9_-]{1,64}$').hasMatch(start) ? start : null,
      trial: uri.queryParameters['v'] == 'trial',
    );
  }

  @override
  State<MiniAppLinkPage> createState() => _MiniAppLinkPageState();
}

class _MiniAppLinkPageState extends State<MiniAppLinkPage> {
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _go());
  }

  Future<void> _go() async {
    final link = MiniAppLinkPage.parse(widget.uri);
    // 没同意隐私政策之前什么都不做 —— 直达链接不能绕过隐私门
    final prefs = await SharedPreferences.getInstance();
    final agreed = prefs.getString('privacy_agreed_version') == kLegalVersion;
    if (!mounted) return;
    if (link == null || !agreed) {
      Navigator.of(context).maybePop();
      return;
    }
    // 冷启动从直达链接进来(安卓 App Links、网页版带着 #/m/… 打开):这一页比 AuthGate 先跑,
    // 本地存着的会话还没恢复 —— 不先恢复的话,登录着的人也会被带去登录页
    if (!widget.api.isLoggedIn) await widget.api.restoreSession(expectRole: 'customer');
    if (!mounted) return;
    await openMiniApp(context, widget.api, appid: link.appid, trial: link.trial, startParam: link.startParam);
    if (mounted) Navigator.of(context).maybePop();
  }

  @override
  Widget build(BuildContext context) =>
      const Scaffold(body: Center(child: CircularProgressIndicator()));
}
