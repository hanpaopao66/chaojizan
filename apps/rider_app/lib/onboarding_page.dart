import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';
import 'package:url_launcher/url_launcher.dart';

/// 食品安全培训(#167)。**先看内容,再确认;答错当场讲解,可以重来。**
///
/// ## 这是法定动作,不是平台给骑手加的规矩
///
/// 《网络餐饮服务经营者落实食品安全主体责任监督管理规定》
/// (总局令第 123 号,2026-06-01 施行)第二十九条:商家把配送委托给平台的,
/// **受托方应当对配送人员进行食品安全培训、管理,培训记录保存不少于二年**。
/// 罚则见第四十四条。
///
/// 所以这一页不能省。但法规要的是**培训**,不是考试 —— 它没说必须考 80 分。
/// 于是形态是:三分钟看完内容 → 几道确认题 → 答错当场讲清楚为什么、可以重来。
///
/// **不判他"不及格"把他挡在外面** —— 他没看懂的那两条,
/// 正是最该讲给他听的。
class RiderExamPage extends StatefulWidget {
  const RiderExamPage({super.key, required this.api});

  final ApiClient api;

  @override
  State<RiderExamPage> createState() => _RiderExamPageState();
}

class _RiderExamPageState extends State<RiderExamPage> {
  Map<String, dynamic>? _training;
  List<dynamic>? _questions;
  final Map<int, int> _answers = {};
  List<dynamic> _wrong = const [];
  bool _busy = false;
  Object? _error;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final t = await widget.api.riderTraining();
      if (mounted) setState(() => _training = t);
    } catch (e) {
      if (mounted) setState(() => _error = e);
    }
  }

  Future<void> _startQuestions() async {
    setState(() => _busy = true);
    try {
      final qs = await widget.api.riderExamQuestions();
      if (mounted) {
        setState(() {
          _questions = qs;
          _answers.clear();
          _wrong = const [];
        });
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text('$e')));
      }
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _submit() async {
    if (_answers.length < (_questions?.length ?? 0)) {
      ScaffoldMessenger.of(context)
          .showSnackBar(const SnackBar(content: Text('还有题没答')));
      return;
    }
    setState(() => _busy = true);
    try {
      final r = await widget.api.riderExamSubmit(
          _answers.map((k, v) => MapEntry('$k', v)));
      if (!mounted) return;
      final passed = r['passed'] == true;
      setState(() {
        _wrong = (r['wrong'] as List?) ?? const [];
        if (passed) _questions = null;
      });
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text('${r['message']}')));
      if (passed) await _load();
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text('$e')));
      }
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    return SzPageScaffold(
      appBar: AppBar(title: const Text('食品安全培训')),
      body: _error != null
          ? SzError(error: _error, onRetry: _load)
          : _training == null
              ? const Center(child: CircularProgressIndicator())
              : _questions == null
                  ? _contentView(sz)
                  : _quizView(sz),
    );
  }

  /// 先给内容。**内容是主体,题目只是确认他看进去了。**
  Widget _contentView(SzColors sz) {
    final t = _training!;
    final done = t['done'] == true;
    final sections = (t['sections'] as List).cast<Map<String, dynamic>>();

    return ListView(
      padding: const EdgeInsets.fromLTRB(kPagePad, 12, kPagePad, 28),
      children: [
        if (done)
          Container(
            padding: const EdgeInsets.all(12),
            decoration: BoxDecoration(
              color: sz.earn.withValues(alpha: .10),
              borderRadius: BorderRadius.circular(kRadiusSm),
            ),
            child: Row(children: [
              Icon(Icons.verified_outlined, size: 18, color: sz.earn),
              const SizedBox(width: 8),
              Expanded(
                child: Text('已完成培训,可以上线接单',
                    style: TextStyle(fontSize: 13, color: sz.ink)),
              ),
            ]),
          ),
        if (done) const SizedBox(height: 14),

        // 为什么要做这一步 —— 不说清楚,他会觉得又是平台在加规矩
        SzCard(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Row(children: [
              Icon(Icons.schedule, size: 15, color: sz.inkMuted),
              const SizedBox(width: 6),
              Text('${t['minutes']} 分钟看完',
                  style: TextStyle(fontSize: 13, color: sz.inkMuted)),
            ]),
            const SizedBox(height: 8),
            Text('${t['why']}',
                style: TextStyle(
                    fontSize: 12, height: 1.6, color: sz.inkMuted)),
          ]),
        ),
        const SizedBox(height: 14),

        for (final s in sections) ...[
          SzCard(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text('${s['title']}',
                    style: const TextStyle(
                        fontSize: 15, fontWeight: FontWeight.w600)),
                const SizedBox(height: 9),
                for (final pt in (s['points'] as List))
                  Padding(
                    padding: const EdgeInsets.only(bottom: 7),
                    child: Row(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text('· ', style: TextStyle(color: sz.inkMuted)),
                        Expanded(
                          child: Text(
                            // 服务端文案里的 ** 是给文档看的,界面不渲染 markdown
                            '$pt'.replaceAll('**', ''),
                            style: TextStyle(
                                fontSize: 13, height: 1.6, color: sz.ink),
                          ),
                        ),
                      ],
                    ),
                  ),
              ],
            ),
          ),
          const SizedBox(height: 12),
        ],

        const SizedBox(height: 6),
        SizedBox(
          width: double.infinity,
          child: FilledButton(
            onPressed: _busy ? null : _startQuestions,
            child: Text(done
                ? '再做一次(${t['question_count']} 题)'
                : '看完了,做 ${t['question_count']} 道确认题'),
          ),
        ),
        const SizedBox(height: 8),
        Text('${t['note']}',
            textAlign: TextAlign.center,
            style: TextStyle(fontSize: 11.5, color: sz.inkMuted)),
      ],
    );
  }

  Widget _quizView(SzColors sz) {
    final qs = _questions!;
    return ListView(
      padding: const EdgeInsets.fromLTRB(kPagePad, 12, kPagePad, 28),
      children: [
        // 答错的讲解放最上面 —— 这才是培训的主体部分
        if (_wrong.isNotEmpty) ...[
          Container(
            padding: const EdgeInsets.all(12),
            decoration: BoxDecoration(
              color: sz.hold.withValues(alpha: .10),
              borderRadius: BorderRadius.circular(kRadiusSm),
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text('这几题再看一眼',
                    style: TextStyle(
                        fontSize: 13.5,
                        fontWeight: FontWeight.w600,
                        color: sz.hold)),
                const SizedBox(height: 8),
                for (final w in _wrong)
                  Padding(
                    padding: const EdgeInsets.only(bottom: 8),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text('${w['q']}',
                            style: TextStyle(fontSize: 12.5, color: sz.ink)),
                        Text('正确答案:${w['answer_text']}',
                            style: TextStyle(
                                fontSize: 12.5, height: 1.5, color: sz.earn)),
                      ],
                    ),
                  ),
                Text('看完直接重答就行,不影响你接单',
                    style: TextStyle(fontSize: 11.5, color: sz.inkMuted)),
              ],
            ),
          ),
          const SizedBox(height: 14),
        ],

        for (final (i, q) in qs.indexed) ...[
          SzCard(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text('${i + 1}. ${q['q']}',
                    style: const TextStyle(fontSize: 14, height: 1.5)),
                const SizedBox(height: 6),
                RadioGroup<int>(
                  groupValue: _answers[q['id'] as int],
                  onChanged: (v) =>
                      setState(() => _answers[q['id'] as int] = v!),
                  child: Column(children: [
                    for (final (j, opt) in (q['options'] as List).indexed)
                      RadioListTile<int>(
                        value: j,
                        contentPadding: EdgeInsets.zero,
                        dense: true,
                        title: Text('$opt',
                            style: const TextStyle(fontSize: 13)),
                      ),
                  ]),
                ),
              ],
            ),
          ),
          const SizedBox(height: 10),
        ],

        SizedBox(
          width: double.infinity,
          child: FilledButton(
            onPressed: _busy ? null : _submit,
            child: Text(_busy ? '提交中…' : '提交'),
          ),
        ),
        const SizedBox(height: 8),
        TextButton(
          onPressed: () => setState(() => _questions = null),
          child: const Text('回去再看看内容'),
        ),
      ],
    );
  }
}

class RiderGearPage extends StatefulWidget {
  const RiderGearPage({super.key, required this.api});

  final ApiClient api;

  @override
  State<RiderGearPage> createState() => _RiderGearPageState();
}

class _RiderGearPageState extends State<RiderGearPage> {
  List<dynamic> _gear = [];

  static const _items = [
    ('helmet', '头盔', Icons.sports_motorsports_outlined),
    ('box', '保温餐箱', Icons.takeout_dining_outlined),
    ('raincoat', '雨衣', Icons.water_drop_outlined),
  ];

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final gear = await widget.api.riderGear();
      if (mounted) setState(() => _gear = gear);
    } catch (_) {}
  }

  Future<void> _request(String item) async {
    try {
      await widget.api.requestRiderGear(item);
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('已申领,等平台发放(会通知你领取方式)')));
      _load();
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(e.toString())));
    }
  }

  @override
  Widget build(BuildContext context) {
    return SzPageScaffold(
      appBar: AppBar(title: const Text('装备申领')),
      body: RefreshIndicator(
        onRefresh: _load,
        child: ListView(padding: const EdgeInsets.all(16), children: [
          Card(
            child: Column(children: [
              for (final (key, label, icon) in _items)
                ListTile(
                  leading: Icon(icon),
                  title: Text(label),
                  trailing: OutlinedButton(
                    onPressed: () => _request(key),
                    child: const Text('申领'),
                  ),
                ),
            ]),
          ),
          const SizedBox(height: 12),
          if (_gear.isNotEmpty) ...[
            Text('申领记录', style: Theme.of(context).textTheme.titleSmall),
            const SizedBox(height: 6),
            Card(
              child: Column(children: [
                for (final g in _gear)
                  ListTile(
                    dense: true,
                    title: Text(_items
                        .firstWhere((i) => i.$1 == g['item'],
                            orElse: () => (g['item'] as String, '${g['item']}', Icons.category))
                        .$2),
                    subtitle: Text(g['note'] == '' ? '' : '${g['note']}'),
                    trailing: Text(
                        g['status'] == 'issued' ? '已发放' : '待发放',
                        style: TextStyle(
                            color: g['status'] == 'issued'
                                ? Theme.of(context).sz.earn
                                : Theme.of(context).sz.hold)),
                  ),
              ]),
            ),
          ],
        ]),
      ),
    );
  }
}

/// 事故上报:人先安全——急救指引大按钮 + 上报表单(照片可后补)。
class RiderAccidentPage extends StatefulWidget {
  const RiderAccidentPage({super.key, required this.api, this.lastFix});

  final ApiClient api;
  final ({double lat, double lng})? lastFix;

  @override
  State<RiderAccidentPage> createState() => _RiderAccidentPageState();
}

class _RiderAccidentPageState extends State<RiderAccidentPage> {
  String _severity = 'minor';
  final _desc = TextEditingController();
  bool _submitting = false;

  Future<void> _submit() async {
    setState(() => _submitting = true);
    try {
      final r = await widget.api.reportAccident(
        severity: _severity,
        description: _desc.text.trim(),
        lat: widget.lastFix?.lat,
        lng: widget.lastFix?.lng,
      );
      if (!mounted) return;
      showDialog(
        context: context,
        builder: (_) => AlertDialog(
          title: const Text('已上报,平台马上联系你'),
          content: Text(
              '在途订单已自动处理(${r['released_orders']} 单回池、'
              '${r['issue_orders']} 单转平台仲裁),不用管订单了。\n'
              '今日保障:${r['insurance_status'] == 'insured' ? '已投保 ${r['insurance_policy_no']}' : '保障金池先行赔付'}\n'
              '现场照片稍后可在事故记录里补传;先处理伤情,注意安全。'),
          actions: [
            FilledButton(
                onPressed: () {
                  Navigator.of(context).pop();
                  Navigator.of(context).pop();
                },
                child: const Text('知道了')),
          ],
        ),
      );
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(e.toString())));
    } finally {
      if (mounted) setState(() => _submitting = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return SzPageScaffold(
      appBar: AppBar(title: const Text('事故上报')),
      body: ListView(padding: const EdgeInsets.all(16), children: [
        Row(children: [
          Expanded(
            child: FilledButton.icon(
              style: FilledButton.styleFrom(
                  backgroundColor: Theme.of(context).sz.danger, minimumSize: const Size(0, 56)),
              icon: const Icon(Icons.emergency),
              label: const Text('拨打 120'),
              onPressed: () => launchUrl(Uri.parse('tel:120')),
            ),
          ),
          const SizedBox(width: 10),
          Expanded(
            child: FilledButton.icon(
              style: FilledButton.styleFrom(
                  backgroundColor: Theme.of(context).sz.hold,
                  minimumSize: const Size(0, 56)),
              icon: const Icon(Icons.local_police_outlined),
              label: const Text('拨打 122'),
              onPressed: () => launchUrl(Uri.parse('tel:122')),
            ),
          ),
        ]),
        const SizedBox(height: 8),
        Text('人先安全!受伤先打 120,涉及车辆事故打 122 报警。\n'
            '上报后平台会立即电话回访;在途订单自动处理,不用你操心。',
            style: Theme.of(context).textTheme.bodySmall),
        const SizedBox(height: 12),
        RadioGroup<String>(
          groupValue: _severity,
          onChanged: (v) => setState(() => _severity = v!),
          child: Column(children: [
            for (final (v, label) in const [
              ('minor', '轻微(车辆剐蹭/摔倒无伤)'),
              ('injury', '受伤(需要就医)'),
              ('serious', '严重(重伤/涉第三方伤亡)'),
            ])
              RadioListTile<String>(dense: true, value: v, title: Text(label)),
          ]),
        ),
        TextField(
          controller: _desc,
          maxLength: 500,
          maxLines: 3,
          decoration: const InputDecoration(
              hintText: '简述情况(地点/经过;照片稍后可补传)',
              border: OutlineInputBorder()),
        ),
        const SizedBox(height: 8),
        SizedBox(
          width: double.infinity,
          child: FilledButton(
            style: FilledButton.styleFrom(backgroundColor: Theme.of(context).sz.danger),
            onPressed: _submitting ? null : _submit,
            child: Text(_submitting ? '上报中…' : '上报事故'),
          ),
        ),
      ]),
    );
  }
}

/// 意外保障记录:每日上线自动登记;registered=保障金池兜底,insured=已投保。
class RiderInsurancePage extends StatefulWidget {
  const RiderInsurancePage({super.key, required this.api});

  final ApiClient api;

  @override
  State<RiderInsurancePage> createState() => _RiderInsurancePageState();
}

class _RiderInsurancePageState extends State<RiderInsurancePage> {
  List<dynamic> _rows = [];

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final rows = await widget.api.riderInsurance();
      if (mounted) setState(() => _rows = rows);
    } catch (_) {}
  }

  @override
  Widget build(BuildContext context) {
    return SzPageScaffold(
      appBar: AppBar(title: const Text('意外保障')),
      body: RefreshIndicator(
        onRefresh: _load,
        child: ListView(padding: const EdgeInsets.all(16), children: [
          Card(
            child: Padding(
              padding: const EdgeInsets.all(14),
              child: Text(
                '每天首次上线自动登记当日保障,无需操作。\n'
                '「保障金池」= 平台从每单佣金计提的专项资金(公开账本可查),'
                '接入保险公司前由它先行赔付;出事故先上报,医疗票据实报实销。',
                style: Theme.of(context).textTheme.bodySmall,
              ),
            ),
          ),
          const SizedBox(height: 12),
          if (_rows.isEmpty)
            const Padding(
              padding: EdgeInsets.all(24),
              child: Center(child: Text('还没有保障记录,上线后自动登记')),
            )
          else
            Card(
              child: Column(children: [
                for (final r in _rows)
                  ListTile(
                    dense: true,
                    leading: const Icon(Icons.health_and_safety_outlined),
                    title: Text('${r['day']}'),
                    subtitle: r['status'] == 'insured'
                        ? Text('保单号:${r['policy_no']}')
                        : null,
                    trailing: Text(
                        r['status'] == 'insured' ? '已投保' : '保障金池兜底',
                        style: TextStyle(
                            color: r['status'] == 'insured'
                                ? Theme.of(context).sz.earn
                                : Theme.of(context).sz.hold)),
                  ),
              ]),
            ),
        ]),
      ),
    );
  }
}

/// 规则中心:转单/考核/结算/申诉规则全文 + 我的当日计数。
/// "规则先说清"——不搞看不见的算法考核。
class RiderRulesPage extends StatefulWidget {
  const RiderRulesPage({super.key, required this.api});

  final ApiClient api;

  @override
  State<RiderRulesPage> createState() => _RiderRulesPageState();
}

class _RiderRulesPageState extends State<RiderRulesPage> {
  Map<String, dynamic>? _d;

  static const _sections = [
    (
      '转单规则',
      '抢到的单没取餐前可以转,回抢单池他人接力,用户无感。\n'
          '· 每天前 2 次免责,超出仍可转,只计数;\n'
          '· 到店等餐超 10 分钟(先上报「未出餐」)或交通事故释放的,'
          '永不计数;\n'
          '· 同一天非免责转单达 5 次:当日暂停抢单,次日自动恢复。'
          '不罚款、不扣钱、不封号,手头的单照常送。'
    ),
    (
      '考核口径',
      '平台不派单、不罚款,考核只有统计公示与软约束:\n'
          '· 转单次数、在线时长、完成单量后台可见(仅平台与你自己);\n'
          '· 数据只用于安全培训与运力改进,不与收入挂钩;\n'
          '· 事故/伤病期间的数据全部豁免。'
    ),
    (
      '结算规则',
      '· 配送费(含夜间/恶劣天气加价)+ 小费,100% 归你,平台分文不取;\n'
          '· 订单完成即入账,T+1 提现零手续费;\n'
          '· 订单超时赔付由平台承担,不从你收入里扣。'
    ),
    (
      '申诉通道',
      '对任何判责/工单结果不服:App 内「客服工单」提交申诉,'
          '24 小时内人工回复;仲裁记录全程留痕可查。'
    ),
  ];

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final d = await widget.api.riderDiscipline();
      if (mounted) setState(() => _d = d);
    } catch (_) {}
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final d = _d;
    return SzPageScaffold(
      appBar: AppBar(title: const Text('规则中心')),
      body: ListView(padding: const EdgeInsets.all(16), children: [
        if (d != null)
          Card(
            color: (d['grab_suspended_today'] == true)
                ? Theme.of(context).sz.hold.withValues(alpha: .12)
                : null,
            child: Padding(
              padding: const EdgeInsets.all(14),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text('我的今日', style: theme.textTheme.titleSmall),
                  const SizedBox(height: 6),
                  Text('非免责转单 ${d['transfer_used_today']} 次 / '
                      '达 ${d['suspend_threshold']} 次当日暂停抢单'),
                  if (d['grab_suspended_today'] == true)
                    Padding(
                      padding: EdgeInsets.only(top: 4),
                      child: Text('今日抢单已暂停,明天自动恢复(不罚款)',
                          style: TextStyle(
                              color: Theme.of(context).sz.hold,
                              fontWeight: FontWeight.w700)),
                    ),
                ],
              ),
            ),
          ),
        const SizedBox(height: 4),
        for (final (title, body) in _sections)
          Card(
            margin: const EdgeInsets.only(top: 10),
            child: Padding(
              padding: const EdgeInsets.all(14),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(title, style: theme.textTheme.titleSmall),
                  const SizedBox(height: 6),
                  Text(body,
                      style:
                          theme.textTheme.bodySmall?.copyWith(height: 1.6)),
                ],
              ),
            ),
          ),
      ]),
    );
  }
}

/// 紧急联系人:最多 2 人,加密存储;触发 SOS 时平台会联系他们。
class EmergencyContactsPage extends StatefulWidget {
  const EmergencyContactsPage({super.key, required this.api});

  final ApiClient api;

  @override
  State<EmergencyContactsPage> createState() => _EmergencyContactsPageState();
}

class _EmergencyContactsPageState extends State<EmergencyContactsPage> {
  final _names = [TextEditingController(), TextEditingController()];
  final _phones = [TextEditingController(), TextEditingController()];
  List<dynamic> _saved = [];

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final saved = await widget.api.emergencyContacts();
      if (mounted) setState(() => _saved = saved);
    } catch (_) {}
  }

  Future<void> _save() async {
    final contacts = <Map<String, String>>[];
    for (var i = 0; i < 2; i++) {
      final name = _names[i].text.trim();
      final phone = _phones[i].text.trim();
      if (name.isNotEmpty && phone.isNotEmpty) {
        contacts.add({'name': name, 'phone': phone});
      }
    }
    try {
      await widget.api.setEmergencyContacts(contacts);
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(const SnackBar(content: Text('已保存(加密存储)')));
      for (final c in [..._names, ..._phones]) {
        c.clear();
      }
      _load();
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(e.toString())));
    }
  }

  @override
  Widget build(BuildContext context) {
    return SzPageScaffold(
      appBar: AppBar(title: const Text('紧急联系人')),
      body: ListView(padding: const EdgeInsets.all(16), children: [
        Text('触发紧急求助(SOS)时,平台会第一时间联系他们。\n'
            '加密存储,除紧急情况外不做任何用途。',
            style: Theme.of(context).textTheme.bodySmall),
        const SizedBox(height: 8),
        if (_saved.isNotEmpty)
          Card(
            child: Column(children: [
              for (final c in _saved)
                ListTile(
                    dense: true,
                    leading: const Icon(Icons.contact_phone_outlined),
                    title: Text('${c['name']}'),
                    subtitle: Text('${c['phone']}')),
            ]),
          ),
        const SizedBox(height: 8),
        for (var i = 0; i < 2; i++) ...[
          Row(children: [
            Expanded(
                child: TextField(
                    controller: _names[i],
                    decoration: InputDecoration(
                        labelText: '联系人${i + 1} 姓名',
                        border: const OutlineInputBorder()))),
            const SizedBox(width: 8),
            Expanded(
                flex: 2,
                child: TextField(
                    controller: _phones[i],
                    keyboardType: TextInputType.phone,
                    decoration: const InputDecoration(
                        labelText: '手机号',
                        border: OutlineInputBorder()))),
          ]),
          const SizedBox(height: 10),
        ],
        SizedBox(
            width: double.infinity,
            child: FilledButton(
                onPressed: _save, child: const Text('保存(覆盖原有)'))),
      ]),
    );
  }
}
