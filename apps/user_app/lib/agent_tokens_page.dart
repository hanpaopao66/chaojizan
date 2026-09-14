import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:superz_shared/superz_shared.dart';
import 'package:url_launcher/url_launcher.dart';

/// AI 助手接入(MCP)。
///
/// ## 这一页要说清的一件事
///
/// 用户看到「让 AI 帮我点外卖」第一反应是「它会不会乱花我的钱」。
/// **答案是不会,而且不是靠自觉** —— 助手令牌的能力范围在服务端收口,
/// 支付路径根本不在白名单里。所以这一页把这句话放在最上面,
/// 而不是塞进某个折叠的说明里。
///
/// ## 签发时勾权限
///
/// 一个令牌能做哪几件事由人勾(服务端 security.AGENT_SCOPES,每项一张白名单)。
/// 默认只勾「点餐」—— 和分权限之前签出来的令牌一样大,多给一项得人自己勾。
/// 勾得越少,令牌丢了损失越小。每项旁边写清能做什么、做不到什么:
/// 人勾之前该知道边界在哪,而不是签完了去翻文档。
///
/// ## 明文只显示一次
///
/// 签发之后明文不再存任何地方。这不是为了麻烦用户,是因为**能再看一次
/// 的凭证等于长期挂在那儿的凭证** —— 谁拿到这台手机都能取走。
/// 所以给一个大大的复制按钮,并且说清关掉就没了。
class AgentTokensPage extends StatefulWidget {
  const AgentTokensPage({super.key, required this.api});

  final ApiClient api;

  @override
  State<AgentTokensPage> createState() => _AgentTokensPageState();
}

/// 用户端账号能勾的权限(服务端 security.AGENT_SCOPES_BY_ROLE 的 customer),顺序照服务端的表。
///
/// [what] 只写服务端白名单里真有的事(security.AGENT_ORDER / AGENT_VIDEO),
/// 做不到的那半句一起写。[needs] 是勾了之后还得人自己先办的事。
const _kScopes = <({String key, String label, String what, String? needs})>[
  (
    key: 'order',
    label: '点餐',
    what: '找店、比价、创建待支付订单;付不了款,付款在 App 里你自己点',
    needs: null,
  ),
  (
    key: 'video',
    label: '发视频',
    what: '把电脑上的视频投成稿件、提交审核,停在「审核中」,审核由平台的人做;'
        '删不了稿,不能点赞评论',
    needs: '需要先完成实名认证',
  ),
];

/// 这个令牌能做哪几件事(给人看的名字)。
///
/// 分权限之前的服务端不返回 scopes / scope_labels —— 那时候的令牌只能点餐,
/// 所以缺省按「点餐」显示。不能空着:空着会被读成「什么都不能做」,或者更糟,「什么都能做」。
List<String> _scopeLabelsOf(Map<String, dynamic> t) {
  final labels = t['scope_labels'];
  if (labels is List && labels.isNotEmpty) return [for (final l in labels) '$l'];
  final keys = t['scopes'];
  if (keys is List && keys.isNotEmpty) {
    return [
      for (final k in keys)
        _kScopes.where((s) => s.key == '$k').firstOrNull?.label ?? '$k'
    ];
  }
  return const ['点餐'];
}

/// 贴进 MCP 客户端的那段配置,和 mcp-server/README.md「怎么接」里的一样。
///
/// SUPERZ_API 填 App 自己正连着的服务端:令牌是这台服务端签的,换一台认不出来。
/// 脚本路径没法替人填 —— mcp-server 放在他电脑上哪儿,手机不知道。
String _mcpConfig(String api, String token) =>
    const JsonEncoder.withIndent('  ').convert({
      'mcpServers': {
        'superz': {
          'command': 'python3',
          'args': ['/绝对路径/mcp-server/server.py'],
          'env': {'SUPERZ_API': api, 'SUPERZ_AGENT_TOKEN': token},
        },
      },
    });

/// 操作说明:开源仓库里的 mcp-server/README.md(怎么接、有哪些工具)
const _guideUrl =
    'https://github.com/hanpaopao66/chaojizan/blob/main/mcp-server/README.md';

class _AgentTokensPageState extends State<AgentTokensPage> {
  List<Map<String, dynamic>>? _items;

  /// 非空 = 上一次加载失败。「一个都没有」和「没拉到」不能长得一样
  String _error = '';

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final r = await widget.api.agentTokens();
      if (!mounted) return;
      setState(() {
        _items = r;
        _error = '';
      });
    } catch (e) {
      if (!mounted) return;
      setState(() => _error = '$e');
    }
  }

  Future<void> _create() async {
    final ctrl = TextEditingController();
    // 默认只勾「点餐」:和分权限之前签出来的令牌一样大
    final picked = <String>{'order'};
    final pick = await showDialog<({String name, List<String> scopes})>(
      context: context,
      builder: (context) => SzDisposeWith(
        controllers: [ctrl],
        child: StatefulBuilder(builder: (context, setLocal) {
          final sz = Theme.of(context).sz;
          return SzDialog(
            title: const Text('签发一个新令牌'),
            scrollable: true,
            content: Column(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Text('起个名,用来分辨以后要吊销哪一个,比如「我的 Claude」。'),
                  const SizedBox(height: 12),
                  TextField(
                    controller: ctrl,
                    maxLength: 40,
                    autofocus: true,
                    decoration: const InputDecoration(hintText: '我的 Claude'),
                  ),
                  const SizedBox(height: 4),
                  Text('它能做哪几件事',
                      style: TextStyle(fontSize: kFontNote, color: sz.inkMuted)),
                  for (final s in _kScopes)
                    CheckboxListTile(
                      dense: true,
                      contentPadding: EdgeInsets.zero,
                      controlAffinity: ListTileControlAffinity.leading,
                      value: picked.contains(s.key),
                      onChanged: (v) => setLocal(() =>
                          v == true ? picked.add(s.key) : picked.remove(s.key)),
                      title: Text(s.label,
                          style: TextStyle(
                              fontSize: kFontBodyLg,
                              fontWeight: FontWeight.w600,
                              color: sz.ink)),
                      subtitle: Column(
                          mainAxisSize: MainAxisSize.min,
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(s.what,
                                style: TextStyle(
                                    fontSize: kFontNote,
                                    height: 1.5,
                                    color: sz.inkMuted)),
                            if (s.needs != null)
                              Text(s.needs!,
                                  style: TextStyle(
                                      fontSize: kFontNote,
                                      height: 1.5,
                                      color: sz.ink)),
                          ]),
                    ),
                  // 按钮灰掉要说为什么,不然像是坏了
                  if (picked.isEmpty)
                    Text('至少勾一项',
                        style: TextStyle(fontSize: kFontNote, color: sz.danger)),
                ]),
            actions: [
              TextButton(
                  onPressed: () => Navigator.pop(context),
                  child: const Text('取消')),
              TextButton(
                  onPressed: picked.isEmpty
                      ? null
                      : () => Navigator.pop(context, (
                            name: ctrl.text.trim(),
                            scopes: [
                              for (final s in _kScopes)
                                if (picked.contains(s.key)) s.key
                            ],
                          )),
                  child: const Text('签发')),
            ],
          );
        }),
      ),
    );
    if (pick == null || !mounted) return;
    try {
      final r = await widget.api
          .createAgentToken(pick.name, 90, scopes: pick.scopes);
      if (!mounted) return;
      // 显示服务端实际签出来的权限,不是刚才勾的 —— 老服务端不认 scopes,只会签「点餐」
      await _showOnce('${r['token']}', '${r['note'] ?? ''}', _scopeLabelsOf(r));
      await _load();
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text('$e')));
    }
  }

  /// 明文只显示这一次。用对话框而不是 SnackBar —— 这段要读、要复制。
  ///
  /// MCP 配置也放在这里:令牌就在配置里,关掉之后这段同样拼不出来了。
  Future<void> _showOnce(String token, String note, List<String> labels) async {
    final sz = Theme.of(context).sz;
    final config = _mcpConfig(widget.api.baseUrl, token);
    Future<void> copy(BuildContext context, String text, String what) async {
      await Clipboard.setData(ClipboardData(text: text));
      if (!context.mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text('已复制$what')));
    }

    Widget box(String text, {bool mono = false}) => Container(
          width: double.infinity,
          padding: const EdgeInsets.all(10),
          decoration: BoxDecoration(
            color: sz.surfaceAlt,
            borderRadius: BorderRadius.circular(6),
          ),
          child: SelectableText(
            text,
            style: TextStyle(
                fontSize: kFontMicro,
                height: mono ? 1.5 : null,
                fontFamily: mono ? 'monospace' : null,
                color: sz.ink),
          ),
        );

    await showDialog<void>(
      context: context,
      barrierDismissible: false,
      builder: (context) => SzDialog(
        title: const Text('复制这串,关掉就没了'),
        scrollable: true,
        content: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Wrap(
                spacing: 6,
                runSpacing: 6,
                crossAxisAlignment: WrapCrossAlignment.center,
                children: [
                  Text('能做',
                      style: TextStyle(fontSize: kFontNote, color: sz.inkMuted)),
                  for (final l in labels) SzChip(l, dense: true),
                ],
              ),
              const SizedBox(height: 10),
              box(token),
              const SizedBox(height: 10),
              // 服务端的 note 用 ** 标重点,这里是纯文本,星号原样印出来只是噪音
              Text(note.replaceAll('**', ''),
                  style: TextStyle(
                      fontSize: kFontNote, height: 1.5, color: sz.inkMuted)),
              const SizedBox(height: 14),
              Row(children: [
                Expanded(
                  child: Text('MCP 配置',
                      style: TextStyle(
                          fontSize: kFontBody,
                          fontWeight: FontWeight.w600,
                          color: sz.ink)),
                ),
                TextButton(
                  onPressed: () => copy(context, config, '配置'),
                  child: const Text('复制配置'),
                ),
              ]),
              Text('贴进电脑上助手的 MCP 配置里,把 /绝对路径/ 换成 mcp-server '
                  '在你电脑上的位置。步骤见这一页的「操作说明」。',
                  style: TextStyle(
                      fontSize: kFontNote, height: 1.5, color: sz.inkMuted)),
              const SizedBox(height: 6),
              box(config, mono: true),
            ]),
        actions: [
          TextButton(
            onPressed: () => copy(context, token, '令牌'),
            child: const Text('复制令牌'),
          ),
          TextButton(
              onPressed: () => Navigator.pop(context),
              child: const Text('我存好了')),
        ],
      ),
    );
  }

  Future<void> _revoke(Map<String, dynamic> t) async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (context) => SzDialog(
        title: Text('吊销「${t['name']}」?'),
        content: const Text('这个助手下一次调用就会失败。已经创建但还没付款的'
            '订单不受影响 —— 它们本来也要你自己确认。'),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(context, false),
              child: const Text('再想想')),
          TextButton(
              onPressed: () => Navigator.pop(context, true),
              child: const Text('吊销')),
        ],
      ),
    );
    if (ok != true || !mounted) return;
    try {
      await widget.api.revokeAgentToken(t['id'] as int);
      await _load();
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text('$e')));
    }
  }

  /// 外部浏览器打开,和「关于我们」里的外链一样。打不开的话至少告诉人去哪儿找
  Future<void> _openGuide() async {
    var ok = false;
    try {
      ok = await launchUrl(Uri.parse(_guideUrl),
          mode: LaunchMode.externalApplication);
    } catch (_) {}
    if (ok || !mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
        content: Text('没能打开浏览器。说明在开源仓库 hanpaopao66/chaojizan 的 '
            'mcp-server/README.md')));
  }

  /// 助手做过什么。
  ///
  /// 只有方法、路径、状态码、时间 —— **没有请求体**,那里面是用户自己的
  /// 地址和手机号,为了让他看得清而多存一份没有道理。
  Future<void> _showActivity() async {
    Map<String, dynamic> data;
    try {
      data = await widget.api.agentActivity();
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text('$e')));
      return;
    }
    if (!mounted) return;
    final items = (data['items'] as List? ?? []).cast<Map<String, dynamic>>();
    await szShowSheet<void>(
      context: context,
      builder: (context) {
        final sz = Theme.of(context).sz;
        return Padding(
          padding: const EdgeInsets.fromLTRB(20, 8, 20, 24),
          child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text('助手做过什么',
                    style: Theme.of(context).textTheme.titleLarge),
                const SizedBox(height: 6),
                Text('${data['note'] ?? ''}',
                    style: TextStyle(
                        fontSize: kFontNote, height: 1.5, color: sz.inkMuted)),
                const SizedBox(height: 14),
                if (items.isEmpty)
                  Text('还没有记录',
                      style: TextStyle(
                          fontSize: kFontBody, color: sz.inkFaint))
                else
                  for (final it in items.take(30))
                    Padding(
                      padding: const EdgeInsets.only(bottom: 8),
                      child: Row(children: [
                        SizedBox(
                          width: 44,
                          child: Text(
                              '${it['at']}'.substring(11, 16),
                              style: TextStyle(
                                  fontSize: kFontNote, color: sz.inkFaint)),
                        ),
                        Expanded(
                          child: Text('${it['method']} ${it['path']}',
                              style: TextStyle(
                                  fontSize: kFontNote, color: sz.ink)),
                        ),
                        Text('${it['status']}',
                            style: TextStyle(
                                fontSize: kFontNote,
                                color: (it['status'] as int? ?? 0) >= 400
                                    ? sz.danger
                                    : sz.inkMuted)),
                      ]),
                    ),
              ]),
        );
      },
    );
  }

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    return SzPageScaffold(
      appBar: AppBar(title: const Text('AI 助手')),
      body: RefreshIndicator(
        onRefresh: _load,
        child: ListView(
          padding: const EdgeInsets.fromLTRB(16, 12, 16, 32),
          children: [
            // 用户看到这一页第一个念头就是「它会不会乱花我的钱」,
            // 所以答案放最上面,不折叠
            Container(
              padding: const EdgeInsets.all(14),
              decoration: BoxDecoration(
                color: sz.surfaceAlt,
                borderRadius: BorderRadius.circular(10),
              ),
              child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text('助手花不掉你的钱',
                        style: TextStyle(
                            fontSize: kFontBodyLg,
                            fontWeight: FontWeight.w700,
                            color: sz.ink)),
                    const SizedBox(height: 8),
                    Text.rich(
                      TextSpan(children: [
                        const TextSpan(
                            text: '签发令牌时勾它能做哪几件事:「点餐」能找店、比价、'
                                '把单创建到「待支付」为止;「发视频」能把视频投成稿件、提交审核。\n'),
                        TextSpan(
                            text: '付款那一下在你手里',
                            style: TextStyle(
                                fontWeight: FontWeight.w600, color: sz.ink)),
                        const TextSpan(
                            text: ' —— 不管勾了哪几项,助手都没有支付能力,'
                                '这是平台在服务端拦住的,不是靠它自觉。\n\n'
                                '同样做不到:退款、改地址、动地址簿、提申诉、提现。\n'
                                '所以就算这串令牌泄露了,对方最多替你创建一张'
                                ' 15 分钟后自动关闭的待付单;勾了「发视频」的,'
                                '还能以你的名义投稿,但要平台的人审过才发得出去,'
                                '也删不了你的稿。'),
                      ]),
                      style: TextStyle(
                          fontSize: kFontNote, height: 1.7, color: sz.inkMuted),
                    ),
                  ]),
            ),
            const SizedBox(height: 16),
            if (_error.isNotEmpty)
              Padding(
                padding: const EdgeInsets.only(bottom: 12),
                child: Text(_error, style: TextStyle(color: sz.danger)),
              ),
            if (_items == null)
              const Center(child: Padding(
                  padding: EdgeInsets.only(top: 40),
                  child: CircularProgressIndicator()))
            else ...[
              if (_items!.isEmpty)
                Padding(
                  padding: const EdgeInsets.symmetric(vertical: 24),
                  child: Text('还没有接入任何助手',
                      textAlign: TextAlign.center,
                      style: TextStyle(
                          fontSize: kFontBody, color: sz.inkFaint)),
                ),
              for (final t in _items!) _row(t),
              const SizedBox(height: 12),
              SizedBox(
                width: double.infinity,
                child: OutlinedButton.icon(
                  onPressed: _create,
                  icon: const Icon(Icons.add),
                  label: const Text('签发一个新令牌'),
                ),
              ),
            ],
            if (_items != null && _items!.isNotEmpty) ...[
              const SizedBox(height: 8),
              // 「花不掉你的钱」是一句承诺,而承诺该能被本人核对 ——
              // 所以给一条通往「它做过什么」的路,而不是让人信一句话
              Align(
                alignment: Alignment.centerLeft,
                child: TextButton(
                  onPressed: _showActivity,
                  child: Text('看看助手做过什么',
                      style: TextStyle(fontSize: kFontNote, color: sz.link)),
                ),
              ),
            ],
            const SizedBox(height: 20),
            SzEntryGroup(children: [
              SzEntryTile(
                icon: Icons.menu_book_outlined,
                title: '操作说明',
                hint: '怎么把令牌接进你的助手(在浏览器里打开)',
                onTap: _openGuide,
              ),
            ]),
          ],
        ),
      ),
    );
  }

  Widget _row(Map<String, dynamic> t) {
    final sz = Theme.of(context).sz;
    final revoked = t['revoked'] == true;
    final last = '${t['last_used_at'] ?? ''}';
    return Card(
      key: ValueKey('agent-token-${t['id']}'),
      margin: const EdgeInsets.only(bottom: 8),
      child: ListTile(
        title: Text('${t['name']}',
            style: TextStyle(color: revoked ? sz.inkFaint : sz.ink)),
        subtitle: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const SizedBox(height: 6),
              // 这把令牌能做哪几件事 —— 要吊销哪一把,先得分得清
              Wrap(spacing: 6, runSpacing: 6, children: [
                for (final l in _scopeLabelsOf(t))
                  SzChip(l, dense: true, textColor: revoked ? sz.inkMuted : null),
              ]),
              const SizedBox(height: 6),
              Text(
                revoked
                    ? '已吊销'
                    : (last.isEmpty
                        // 「从没用过」值得单独说 —— 多半是配错了,
                        // 而不是助手很克制
                        ? '还没有被使用过'
                        : '最近使用 ${last.substring(0, 16).replaceFirst("T", " ")}'),
                style: TextStyle(fontSize: kFontNote, color: sz.inkMuted),
              ),
            ]),
        trailing: revoked
            ? null
            : TextButton(
                onPressed: () => _revoke(t),
                child: Text('吊销', style: TextStyle(color: sz.danger)),
              ),
      ),
    );
  }
}
