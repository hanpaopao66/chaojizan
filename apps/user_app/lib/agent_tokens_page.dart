import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:superz_shared/superz_shared.dart';

/// AI 助手接入(MCP)。
///
/// ## 这一页要说清的一件事
///
/// 用户看到「让 AI 帮我点外卖」第一反应是「它会不会乱花我的钱」。
/// **答案是不会,而且不是靠自觉** —— 助手令牌的能力范围在服务端收口,
/// 支付路径根本不在白名单里。所以这一页把这句话放在最上面,
/// 而不是塞进某个折叠的说明里。
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
    final name = await showDialog<String>(
      context: context,
      builder: (context) => SzDialog(
        title: const Text('给这个助手起个名'),
        content: Column(mainAxisSize: MainAxisSize.min, children: [
          const Text('用来分辨以后要吊销哪一个,比如「我的 Claude」。'),
          const SizedBox(height: 12),
          TextField(
            controller: ctrl,
            maxLength: 40,
            autofocus: true,
            decoration: const InputDecoration(hintText: '我的 Claude'),
          ),
        ]),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(context),
              child: const Text('取消')),
          TextButton(
              onPressed: () => Navigator.pop(context, ctrl.text.trim()),
              child: const Text('签发')),
        ],
      ),
    );
    if (name == null || !mounted) return;
    try {
      final r = await widget.api.createAgentToken(name, 90);
      if (!mounted) return;
      await _showOnce('${r['token']}', '${r['note'] ?? ''}');
      await _load();
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text('$e')));
    }
  }

  /// 明文只显示这一次。用对话框而不是 SnackBar —— 这段要读、要复制。
  Future<void> _showOnce(String token, String note) async {
    final sz = Theme.of(context).sz;
    await showDialog<void>(
      context: context,
      barrierDismissible: false,
      builder: (context) => SzDialog(
        title: const Text('复制这串,关掉就没了'),
        content: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Container(
                width: double.infinity,
                padding: const EdgeInsets.all(10),
                decoration: BoxDecoration(
                  color: sz.surfaceAlt,
                  borderRadius: BorderRadius.circular(6),
                ),
                child: SelectableText(
                  token,
                  style: TextStyle(fontSize: kFontMicro, color: sz.ink),
                ),
              ),
              const SizedBox(height: 10),
              Text(note,
                  style: TextStyle(
                      fontSize: kFontNote, height: 1.5, color: sz.inkMuted)),
            ]),
        actions: [
          TextButton(
            onPressed: () async {
              await Clipboard.setData(ClipboardData(text: token));
              if (!context.mounted) return;
              ScaffoldMessenger.of(context).showSnackBar(
                  const SnackBar(content: Text('已复制')));
            },
            child: const Text('复制'),
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
                    Text(
                        '它能帮你找店、比价、把单创建到「待支付」为止。\n'
                        '**付款那一下在你手里** —— 助手没有支付能力,'
                        '这是平台在服务端拦住的,不是靠它自觉。\n\n'
                        '同样做不到:退款、改地址、动地址簿、提申诉、提现。\n'
                        '所以就算这串令牌泄露了,对方最多替你创建一张'
                        '15 分钟后自动关闭的待付单。',
                        style: TextStyle(
                            fontSize: kFontNote,
                            height: 1.7,
                            color: sz.inkMuted)),
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
            Text('怎么接:把令牌填进助手的 MCP 配置里,'
                '具体见开源仓库的 mcp-server/README.md。',
                style: TextStyle(fontSize: kFontMicro, color: sz.inkFaint)),
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
      margin: const EdgeInsets.only(bottom: 8),
      child: ListTile(
        title: Text('${t['name']}',
            style: TextStyle(color: revoked ? sz.inkFaint : sz.ink)),
        subtitle: Text(
          revoked
              ? '已吊销'
              : (last.isEmpty
                  // 「从没用过」值得单独说 —— 多半是配错了,
                  // 而不是助手很克制
                  ? '还没有被使用过'
                  : '最近使用 ${last.substring(0, 16).replaceFirst("T", " ")}'),
          style: TextStyle(fontSize: kFontNote, color: sz.inkMuted),
        ),
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
