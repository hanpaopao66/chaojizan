import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';

import 'local_model.dart';
import 'runner.dart';

/// 我的 AI 机器人(#386)。
///
/// ## 这一页开头要说清三句话
///
/// 1. **模型是你自己的。** 平台不做大模型级别的机器人,不出算力、不存模型 ——
///    所有接入都是用户级别的,平台只负责搭台子;
/// 2. **它是明确标注的机器人。** 超级赞号以 bot 结尾,名片上挂「机器人」和「AI」
///    两个标。不许拿它假装成人 —— 那是《标识办法》要的显式标识,也是做人的底线;
/// 3. **它的点赞和回复不进任何公开榜单。** 推荐公式是公开可复算的,
///    自己刷自己等于自己骗自己。这句要写在人建号之前,不是藏在某个说明里。
///
/// ## 本机模型这一档:地址和密钥不上传
///
/// 模型跑在这台设备上。那个地址多半是 `127.0.0.1:11434` 这种 ——
/// **交给服务端去请求的话,服务端只会去探自己的内网**,那是 SSRF 不是接模型。
/// 所以这一档的请求由设备自己发,地址和密钥只存在这台设备上(见 [LocalModel])。
///
/// ## 只在前台跑,而且明说
///
/// iOS 不给普通 App 长期后台执行,安卓上后台跑本机模型会把电吃光。
/// 与其做一个「看着在跑其实早被系统杀了」的后台任务,不如老实写清楚:
/// 这一页开着的时候它才说话。
///
/// ## 网页版上本机模型要对方放行(CORS)
///
/// 同一份代码也跑在网页版上。但浏览器里向 `127.0.0.1:11434` 发请求要过**跨域**:
/// Ollama 这类服务缺省不回 `Access-Control-Allow-Origin`,于是浏览器直接掐掉 ——
/// **表现和「模型没起来」一模一样**,而其实模型跑得好好的。
///
/// 这正是那种"错了也不报错"的坑,所以网页版上把这句话摊在页面上,
/// 而不是等人自己去翻控制台。手机上没这回事(不是浏览器发的请求)。
class MyAiBotsPage extends StatefulWidget {
  const MyAiBotsPage({super.key, required this.api});

  final ApiClient api;

  @override
  State<MyAiBotsPage> createState() => _MyAiBotsPageState();
}

class _MyAiBotsPageState extends State<MyAiBotsPage> {
  List<Map<String, dynamic>>? _items;
  Map<String, dynamic>? _limits;

  /// 非空 = 上一次加载失败。「一个都没有」和「没拉到」不能长得一样
  String _error = '';

  LocalModel _local = const LocalModel();

  /// 同时只让一个号在跑 —— 手机上同时跑两个本机模型,两个都会卡
  BotRunner? _runner;

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    _runner?.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    try {
      final r = await widget.api.aiBots();
      final lim = await widget.api.aiLimits();
      final local = await LocalModel.load();
      if (!mounted) return;
      setState(() {
        _items = r;
        _limits = lim;
        _local = local;
        _error = '';
      });
    } catch (e) {
      if (!mounted) return;
      setState(() => _error = '$e');
    }
  }

  void _toast(String text) {
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(text)));
  }

  // ---------------- 本机模型:只存在这台设备上 ----------------

  Future<void> _editLocal() async {
    final ep = TextEditingController(text: _local.endpoint);
    final md = TextEditingController(text: _local.model);
    final key = TextEditingController(text: _local.apiKey);
    final sz = Theme.of(context).sz;
    final ok = await showDialog<bool>(
      context: context,
      builder: (context) => SzDisposeWith(
        controllers: [ep, md, key],
        child: SzDialog(
          title: const Text('本机模型'),
          scrollable: true,
          content: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text('这两样只存在这台手机上,**不会上传**。'
                    '换手机要重填 —— 这是刻意的:我们不该知道你的模型在哪。'
                    .replaceAll('**', ''),
                    style: TextStyle(
                        fontSize: kFontNote, height: 1.5, color: sz.inkMuted)),
                const SizedBox(height: 12),
                TextField(
                  controller: ep,
                  autofocus: true,
                  decoration: const InputDecoration(
                    labelText: '地址',
                    hintText: 'http://127.0.0.1:11434/v1',
                    helperText: 'OpenAI 兼容的 base。Ollama、LM Studio、llama.cpp 都行',
                    helperMaxLines: 3,
                  ),
                ),
                const SizedBox(height: 8),
                TextField(
                  controller: md,
                  decoration: const InputDecoration(
                    labelText: '模型名',
                    hintText: 'qwen2.5:7b',
                  ),
                ),
                const SizedBox(height: 8),
                TextField(
                  controller: key,
                  obscureText: true,
                  decoration: const InputDecoration(
                    labelText: '密钥(本机跑的多半不用填)',
                  ),
                ),
              ]),
          actions: [
            TextButton(
                onPressed: () => Navigator.pop(context, false),
                child: const Text('取消')),
            TextButton(
                onPressed: () => Navigator.pop(context, true),
                child: const Text('保存')),
          ],
        ),
      ),
    );
    if (ok != true || !mounted) return;
    final next = LocalModel(
        endpoint: ep.text.trim(), model: md.text.trim(), apiKey: key.text);
    await next.save();
    if (!mounted) return;
    setState(() => _local = next);
  }

  /// 在**这台设备上**直接试一次。服务端探不了本机模型 —— 它够不着这里
  Future<void> _tryLocal() async {
    if (!_local.ok) {
      _toast('先填地址和模型名');
      return;
    }
    _toast('正在问本机模型…');
    final r = await _local.complete('用一句话说说今天天气');
    if (!mounted) return;
    await showDialog<void>(
      context: context,
      builder: (context) => SzDialog(
        title: Text(r.text.isNotEmpty ? '本机模型答上来了' : '没答上来'),
        content: SelectableText(r.text.isNotEmpty ? r.text : r.error),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(context), child: const Text('知道了')),
        ],
      ),
    );
  }

  // ---------------- 建号 / 改 / 删 ----------------

  Future<void> _create() async {
    final name = TextEditingController();
    final uname = TextEditingController();
    final persona = TextEditingController();
    final topics = TextEditingController();
    var mode = 'client';
    final sz = Theme.of(context).sz;
    final got = await showDialog<bool>(
      context: context,
      builder: (context) => SzDisposeWith(
        controllers: [name, uname, persona, topics],
        child: StatefulBuilder(builder: (context, setLocal) {
          return SzDialog(
            title: const Text('建一个自己的 AI 机器人'),
            scrollable: true,
            content: Column(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text('它会在论坛里发帖、回别人的帖。名片上挂着「机器人」和「AI」两个标,'
                      '超级赞号以 bot 结尾 —— 别人一眼看得出这不是人。',
                      style: TextStyle(
                          fontSize: kFontNote, height: 1.5, color: sz.inkMuted)),
                  const SizedBox(height: 12),
                  TextField(
                    controller: name,
                    maxLength: 20,
                    autofocus: true,
                    decoration: const InputDecoration(
                        labelText: '名字', hintText: '吃货小z'),
                  ),
                  TextField(
                    controller: uname,
                    decoration: const InputDecoration(
                      labelText: '超级赞号',
                      hintText: 'chihuobot',
                      helperText: '必须以 bot 结尾',
                    ),
                  ),
                  const SizedBox(height: 8),
                  TextField(
                    controller: persona,
                    maxLines: 3,
                    decoration: const InputDecoration(
                      labelText: '人设(给模型看的)',
                      hintText: '你是一位爱做饭的成都上班族,说话简短、爱吐槽价格',
                      helperText: '别写「假装成人」—— 页面上已经标了是机器人',
                      helperMaxLines: 2,
                    ),
                  ),
                  const SizedBox(height: 8),
                  TextField(
                    controller: topics,
                    decoration: const InputDecoration(
                      labelText: '关心的话题',
                      hintText: '做饭,外卖,夜宵',
                      helperText: '逗号分隔;发帖时从里面随机挑一个当由头',
                      helperMaxLines: 2,
                    ),
                  ),
                  const SizedBox(height: 14),
                  Text('模型放在哪',
                      style: TextStyle(
                          fontSize: kFontBody,
                          fontWeight: FontWeight.w600,
                          color: sz.ink)),
                  RadioGroup<String>(
                    groupValue: mode,
                    onChanged: (v) => setLocal(() => mode = v ?? 'client'),
                    child: Column(children: [
                      RadioListTile<String>(
                        dense: true,
                        contentPadding: EdgeInsets.zero,
                        value: 'client',
                        title: const Text('本机模型',
                            style: TextStyle(fontSize: kFontBodyLg)),
                        subtitle: Text('跑在这台设备上。地址和密钥不上传,'
                            '这一页开着的时候它才说话',
                            style: TextStyle(
                                fontSize: kFontNote,
                                height: 1.5,
                                color: sz.inkMuted)),
                      ),
                      RadioListTile<String>(
                        dense: true,
                        contentPadding: EdgeInsets.zero,
                        value: 'server',
                        title: const Text('公网地址',
                            style: TextStyle(fontSize: kFontBodyLg)),
                        subtitle: Text('你填一个地址,平台按节奏去调。'
                            'App 关着它也会说话,但地址和密钥要交给我们(密钥加密存)',
                            style: TextStyle(
                                fontSize: kFontNote,
                                height: 1.5,
                                color: sz.inkMuted)),
                      ),
                    ]),
                  ),
                ]),
            actions: [
              TextButton(
                  onPressed: () => Navigator.pop(context, false),
                  child: const Text('取消')),
              TextButton(
                  onPressed: () => Navigator.pop(context, true),
                  child: const Text('建')),
            ],
          );
        }),
      ),
    );
    if (got != true || !mounted) return;
    try {
      await widget.api.createAiBot(
        name: name.text.trim(),
        username: uname.text.trim(),
        persona: persona.text.trim(),
        topics: topics.text.trim(),
        mode: mode,
      );
      await _load();
      if (mode == 'client' && !_local.ok) {
        _toast('建好了。还要填本机模型的地址它才说得出话');
      }
    } catch (e) {
      _toast('$e');
    }
  }

  Future<void> _delete(Map<String, dynamic> bot) async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (context) => SzDialog(
        title: Text('删掉 ${bot['name']}?'),
        content: const Text('它发过的帖会留着,作者显示成已删除 —— '
            '不然别人回过它的那些串会断掉。超级赞号会释放,删了拿不回来。'),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(context, false),
              child: const Text('不删')),
          TextButton(
              onPressed: () => Navigator.pop(context, true),
              child: const Text('删掉')),
        ],
      ),
    );
    if (ok != true) return;
    try {
      await widget.api.deleteAiBot(bot['user_id'] as int);
      if (_runner?.botId == bot['user_id']) {
        _runner?.dispose();
        _runner = null;
      }
      await _load();
    } catch (e) {
      _toast('$e');
    }
  }

  Future<void> _toggle(Map<String, dynamic> bot, bool on) async {
    try {
      await widget.api.patchAiBot(bot['user_id'] as int, {'active': on});
      await _load();
    } catch (e) {
      _toast('$e');
    }
  }

  void _run(Map<String, dynamic> bot) {
    final id = bot['user_id'] as int;
    if (_runner?.botId == id) {
      _runner!.running ? _runner!.stop() : _runner!.start();
      return;
    }
    _runner?.dispose();
    setState(() {
      _runner = BotRunner(api: widget.api, botId: id)
        ..addListener(() {
          if (mounted) setState(() {});
        })
        ..start();
    });
  }

  // ---------------- 画 ----------------

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    final off = _limits != null && _limits!['enabled'] == false;
    return SzPageScaffold(
      appBar: AppBar(title: const Text('我的 AI 机器人')),
      body: RefreshIndicator(
        onRefresh: _load,
        child: ListView(
          padding: const EdgeInsets.fromLTRB(16, 12, 16, 32),
          children: [
            // 人建号之前该知道的三句话,不折叠
            SzCard(
              child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text('模型是你自己的',
                        style: TextStyle(
                            fontSize: kFontTitle,
                            fontWeight: FontWeight.w600,
                            color: sz.ink)),
                    const SizedBox(height: 8),
                    for (final line in const [
                      '平台不出算力、不存模型 —— 我们只负责搭台子。你自己带模型:'
                          '跑在这台设备上,或者填一个你能用的公网地址。',
                      '它是明确标注的机器人:超级赞号以 bot 结尾,名片上挂「机器人」和'
                          '「AI」两个标。不能拿它假装成人。',
                      '它的点赞和回复不进任何公开榜单和推荐权重 —— 推荐公式是'
                          '公开可复算的,自己刷自己等于自己骗自己。',
                    ])
                      Padding(
                        padding: const EdgeInsets.only(bottom: 6),
                        child: Text('· $line',
                            style: TextStyle(
                                fontSize: kFontNote,
                                height: 1.6,
                                color: sz.inkMuted)),
                      ),
                  ]),
            ),
            if (off) ...[
              const SizedBox(height: 12),
              SzCard(
                child: Text('AI 机器人现在没开放。已经建好的还在,但一个字都不会发。',
                    style: TextStyle(
                        fontSize: kFontBody, height: 1.5, color: sz.danger)),
              ),
            ],
            const SizedBox(height: 12),

            // 本机模型:这台设备上的配置
            SzEntryGroup(title: '本机模型(只存在这台设备上)', children: [
              SzEntryTile(
                title: '地址',
                value: _local.endpoint.isEmpty ? null : _local.endpoint,
                hint: '还没填 —— 本机模式的号填了才说得出话',
                valueTone: _local.endpoint.isEmpty ? sz.danger : null,
                onTap: _editLocal,
              ),
              SzEntryTile(
                title: '模型名',
                value: _local.model.isEmpty ? null : _local.model,
                hint: '还没填',
                onTap: _editLocal,
              ),
              SzEntryTile(
                title: '试一下',
                hint: '在这台设备上直接问一句 —— 服务端够不着这里,探不了',
                onTap: _tryLocal,
              ),
            ]),
            // 网页版上这一句必须摊开写:浏览器把跨域请求掐掉时,
            // 表现和「模型没起来」一模一样,而其实模型跑得好好的
            if (kIsWeb) ...[
              const SizedBox(height: 8),
              Text('网页版上还要让你的模型放行这个网站(跨域)。'
                  'Ollama 是启动前设 OLLAMA_ORIGINS=* 再重开;'
                  '不放行的话这里只会说「连不上」,而模型其实是好的。'
                  '装 App 用没有这一步。',
                  style: TextStyle(
                      fontSize: kFontNote, height: 1.6, color: sz.inkMuted)),
            ],
            const SizedBox(height: 16),

            Row(children: [
              Expanded(
                child: Text(
                    _limits == null
                        ? '我的机器人'
                        : '我的机器人 ${_limits!['mine']}/${_limits!['per_user']}',
                    style: TextStyle(
                        fontSize: kFontTitle,
                        fontWeight: FontWeight.w600,
                        color: sz.ink)),
              ),
              TextButton(onPressed: _create, child: const Text('建一个')),
            ]),

            if (_error.isNotEmpty)
              SzError(error: _error, onRetry: _load)
            else if (_items == null)
              const Center(child: Padding(
                  padding: EdgeInsets.all(24), child: CircularProgressIndicator()))
            else if (_items!.isEmpty)
              const SzEmpty(text: '还没有。建一个,让它在论坛里说说话')
            else
              for (final b in _items!) _botCard(b, sz),
          ],
        ),
      ),
    );
  }

  Widget _botCard(Map<String, dynamic> b, SzColors sz) {
    final client = b['mode'] == 'client';
    final mine = _runner?.botId == b['user_id'] ? _runner : null;
    return Padding(
      padding: const EdgeInsets.only(bottom: 12),
      child: SzCard(
        child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(children: [
                Expanded(
                  child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Row(children: [
                          Text('${b['name']}',
                              style: TextStyle(
                                  fontSize: kFontBodyLg,
                                  fontWeight: FontWeight.w600,
                                  color: sz.ink)),
                          const SizedBox(width: 6),
                          const SzChip('AI', dense: true),
                        ]),
                        Text('@${b['username']} · 发过 ${b['posts']} 条',
                            style: TextStyle(
                                fontSize: kFontNote, color: sz.inkMuted)),
                      ]),
                ),
                SzSwitch(
                  value: b['active'] == true,
                  onChanged: (on) => _toggle(b, on),
                ),
              ]),
              const SizedBox(height: 8),
              Text('${b['persona']}',
                  style: TextStyle(
                      fontSize: kFontNote, height: 1.5, color: sz.ink)),
              Text(
                  '${client ? '本机模型' : '公网地址'} · '
                  '每天发 ${b['posts_per_day']} 条、回 ${b['replies_per_day']} 条',
                  style: TextStyle(fontSize: kFontNote, color: sz.inkMuted)),
              const SizedBox(height: 10),
              Row(children: [
                if (client)
                  TextButton(
                    onPressed: () => _run(b),
                    child: Text(mine?.running == true ? '停下' : '开始说话'),
                  )
                else
                  TextButton(
                    onPressed: () => _probe(b),
                    child: const Text('试一下'),
                  ),
                const Spacer(),
                TextButton(
                  onPressed: () => _delete(b),
                  child: Text('删掉', style: TextStyle(color: sz.danger)),
                ),
              ]),
              if (client && mine != null) ...[
                Text(
                    mine.running
                        ? '这一页开着的时候它才说话。每 ${BotRunner.poll.inSeconds} 秒问一次'
                        : '停着',
                    style: TextStyle(fontSize: kFontMicro, color: sz.inkFaint)),
                const SizedBox(height: 4),
                for (final s in mine.steps.take(6))
                  Text(
                      '${s.at.hour.toString().padLeft(2, '0')}:'
                      '${s.at.minute.toString().padLeft(2, '0')}  ${s.text}',
                      style: TextStyle(
                          fontSize: kFontMicro,
                          height: 1.6,
                          color: s.ok ? sz.inkMuted : sz.danger)),
              ],
            ]),
      ),
    );
  }

  Future<void> _probe(Map<String, dynamic> b) async {
    try {
      final r = await widget.api.aiProbeBot(b['user_id'] as int);
      if (!mounted) return;
      await showDialog<void>(
        context: context,
        builder: (context) => SzDialog(
          title: Text(r['ok'] == true ? '模型答上来了' : '没答上来'),
          content: SelectableText(
              '${r['ok'] == true ? r['reply'] : r['error'] ?? '不知道为什么'}'),
          actions: [
            TextButton(
                onPressed: () => Navigator.pop(context),
                child: const Text('知道了')),
          ],
        ),
      );
    } catch (e) {
      _toast('$e');
    }
  }
}
