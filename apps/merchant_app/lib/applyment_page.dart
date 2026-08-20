/// 收款资料 —— 微信特约商户进件(#204 资料采集 / #206 状态展示)。
///
/// ## 为什么是独立一页,不是入驻流程里的第四步
///
/// 入驻要快,多一步就多一批人放弃;而进件资料是「能收钱之前」要的,
/// 不是「能开店之前」要的。所以入口在「店铺」页,商家什么时候准备好
/// 什么时候来填,不挡开店。
///
/// ## 文案是这一页的一半工作量
///
/// 这一页要商家交**法人身份证号**和**银行账号**,是所有页面里要得最狠的一次。
/// 不把下面三件事讲清楚,商家的正常反应就是关掉:
///
/// 1. 资料是交给**微信支付**的,平台只是按微信的格式代传;
/// 2. 交了之后货款**直接进商家自己的账户**,不再经平台的手 —— 对商家是变好;
/// 3. 平台看得到什么(尾 4 位)、看不到什么(完整号码),谁看了会留痕。
///
/// 所以顶部那几张卡不是可以删的"说明文字",它和表单本身一样重要。
/// 写法照 promises_page / rules_page 的调子:直白、讲清代价、不吹。
///
/// ## 状态(#206)
///
/// 微信的进件是异步的,中间「待账户验证」和「待签约」两步**要商家本人操作**
/// (查小额打款金额、超级管理员本人微信扫码)。不把这两步显式画出来,
/// 商家会以为提交完就没事了,然后一直开不了通。
library;

import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:superz_shared/superz_shared.dart';

import 'license_upload_field.dart';

/// 字段名 → 中文标签。**这不是必填清单** —— 缺哪些字段一律以服务端返回的
/// `missing` 为准(个体工商户和企业要交的东西不一样,客户端再写一份迟早分叉)。
/// 这里只负责把服务端给的字段名显示成人话,服务端自带 label 时优先用它的。
const _kFieldLabels = <String, String>{
  'subject_type': '主体类型',
  'business_license_image_url': '营业执照照片',
  'legal_person_name': '法人姓名',
  'legal_person_id_no': '法人身份证号',
  'legal_person_id_front_url': '身份证人像面',
  'legal_person_id_back_url': '身份证国徽面',
  'admin_contact_name': '超级管理员姓名',
  'admin_contact_phone': '超级管理员手机号',
  'admin_contact_email': '超级管理员邮箱',
  // 标签短一点:它会被塞进「还差 N 项」的 chip 里,chip 不换行,
  // 大字号下长标签会横着溢出
  'settle_account_type': '账户类型',
  'settle_account_name': '开户名',
  'settle_bank_name': '开户银行',
  'settle_bank_branch': '开户支行',
  'settle_account_no': '银行账号',
};

/// 敏感字段在库里是 `*_encrypted` + `*_tail` 两列、入参又是第三个名字
/// (`legal_person_id_no`),而表单上只有一个输入框。都归到入参那个名字上,
/// 不然会出现"还差 2 项"但只有 1 个框的怪事。
///
/// 规范名 = **写入用的字段名**(`ApplymentIn` 里的),因为提交时要照它拼 body。
const _kCanonical = <String, String>{
  'legal_person_id_encrypted': 'legal_person_id_no',
  'legal_person_id_tail': 'legal_person_id_no',
  'legal_person_id': 'legal_person_id_no',
  'settle_account_no_encrypted': 'settle_account_no',
  'settle_account_tail': 'settle_account_no',
};

/// 微信那边已经在按提交时那一版办事的状态:改库里的没用,报上去的是当时那版。
/// 服务端对这几个状态的 PUT 直接 409(`APPLYMENT_LOCKED_STATUSES`),
/// 客户端也就别把表单摆出来让商家白填一遍。
const _kLockedStatuses = {'need_sign', 'need_account_verify', 'finished'};

String _canon(String field) => _kCanonical[field] ?? field;

String _labelOf(String field) => _kFieldLabels[_canon(field)] ?? field;

/// 一条"还差的资料"。
class _Missing {
  const _Missing(this.field, this.label);

  final String field;
  final String label;
}

class ApplymentPage extends StatefulWidget {
  const ApplymentPage({super.key, required this.api, required this.shop});

  final ApiClient api;

  /// 用来取真实佣金率(文案里要说"平台分走多少",不能写个假数)
  /// 和门店 id(草稿按门店存 —— 连锁老板在 A 店填一半切到 B 店,
  /// 草稿串店会让他把 A 店的银行卡填进 B 店)。
  final Merchant shop;

  @override
  State<ApplymentPage> createState() => _ApplymentPageState();
}

class _ApplymentPageState extends State<ApplymentPage> {
  bool _loading = true;
  bool _saving = false;
  String? _error;

  /// 服务端返回的原始资料(含状态、单号、尾号)
  Map<String, dynamic> _data = const {};
  List<_Missing> _missing = const [];

  /// 草稿是从本机恢复的(顶部提示一下,并给"用平台上的版本"的退路)
  bool _draftRestored = false;

  Timer? _draftTimer;

  /// 上一次重建时"还空着的缺项"有几个。见 [_onFieldChanged]
  int _missingLeft = -1;

  final _legalName = TextEditingController();
  final _legalId = TextEditingController();
  final _adminName = TextEditingController();
  final _adminPhone = TextEditingController();
  final _adminEmail = TextEditingController();
  final _settleName = TextEditingController();
  final _bankName = TextEditingController();
  final _bankBranch = TextEditingController();
  final _settleNo = TextEditingController();

  String _subjectType = '';
  String _settleType = '';
  String _licenseImage = '';
  String _idFront = '';
  String _idBack = '';

  /// 服务端这次实际操作的是哪家店。
  ///
  /// `GET/PUT /merchants/me/applyment` 的门店是**服务端**按 owner 解出来的
  /// (`money_shop`),客户端没把 merchant_id 传过去。连锁老板有好几家店时,
  /// 服务端解出来的不一定就是他刚才在看的那家 —— 所以草稿、店名一律
  /// 认服务端回的这个 id,别拿本页进来时的那家店去猜。
  int? get _serverMerchantId => _data['merchant_id'] as int?;

  /// 草稿按门店存:连锁老板在 A 店填一半切到 B 店,草稿串店会让他
  /// 把 A 店的银行卡填进 B 店 —— 而这类错误要等货款打错了才发现
  String get _draftKey =>
      'applyment_draft_v1_${_serverMerchantId ?? widget.shop.id}';

  String get _status =>
      '${_data['applyment_status'] ?? 'not_submitted'}'.trim();

  bool get _editable => !_kLockedStatuses.contains(_status);

  @override
  void initState() {
    super.initState();
    for (final c in _controllers) {
      c.addListener(_onFieldChanged);
    }
    _load();
  }

  /// 还该提示的缺项。
  ///
  /// **缺哪些字段一律以服务端为准**(个体工商户和企业要交的不一样,
  /// 客户端不自己维护一份必填清单);这里只做一件事:把"商家刚敲进去、
  /// 还没保存"的那几项从提示里摘掉,别让他盯着自己刚填的字看红字。
  ///
  /// 摘的条件要卡准:服务端那份**本来就是空的**才算"他刚补上了"。
  /// 服务端有值却还报缺,说明报的是取值约束(比如企业主体必须用对公账户),
  /// 那种要一直显示到真的改对并保存为止。
  List<_Missing> get _stillMissing => _missing
      .where((m) => _serverValue(m.field).isNotEmpty ||
          _localValue(m.field).isEmpty)
      .toList();

  /// 服务端那一份里这个字段的值(敏感字段看尾号)。
  String _serverValue(String field) {
    switch (field) {
      case 'legal_person_id_no':
        return '${_data['legal_person_id_tail'] ?? ''}'.trim();
      case 'settle_account_no':
        return '${_data['settle_account_tail'] ?? ''}'.trim();
      default:
        return '${_data[field] ?? ''}'.trim();
    }
  }

  /// 输入框变化:存草稿 + 必要时重建。
  ///
  /// 不能每敲一个字就 setState 整页(这页很长),但「还差这项」要在填上的
  /// 那一刻消失 —— 折中成:只有缺项个数真的变了才重建。
  void _onFieldChanged() {
    _scheduleDraftSave();
    final n = _stillMissing.length;
    if (n != _missingLeft) {
      _missingLeft = n;
      if (mounted) setState(() {});
    }
  }

  List<TextEditingController> get _controllers => [
        _legalName, _legalId, _adminName, _adminPhone, _adminEmail,
        _settleName, _bankName, _bankBranch, _settleNo,
      ];

  @override
  void dispose() {
    _draftTimer?.cancel();
    for (final c in _controllers) {
      c.removeListener(_onFieldChanged);
      c.dispose();
    }
    super.dispose();
  }

  // -------------------------------------------------------------------------
  // 读取
  // -------------------------------------------------------------------------

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      // 显式带上正在看的这家店。不传的话服务端按 owner 解出"某一家",
      // 连锁老板会在一张长得一模一样的页面上填**另一家店**的结算账户
      final raw = await widget.api.myApplyment(merchantId: widget.shop.id);
      if (!mounted) return;
      // 服务端可能把资料平铺在根上,也可能包一层 applyment。两种都认 ——
      // 这一版的契约还会随微信类目动,为一次形状变化让商家端报错不值当
      final inner = raw['applyment'];
      final data = inner is Map
          ? <String, dynamic>{...raw, ...Map<String, dynamic>.from(inner)}
          : raw;
      setState(() {
        _data = data;
        _missing = _parseMissing(data);
        _loading = false;
      });
      _fillFromServer(data);
      await _restoreDraft(data);
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _error = e is ApiException ? e.message : '$e';
        _loading = false;
      });
    }
  }

  List<_Missing> _parseMissing(Map<String, dynamic> data) {
    final raw = data['missing'] ??
        data['missing_fields'] ??
        data['incomplete_fields'];
    if (raw is! List) return const [];
    final out = <_Missing>[];
    final seen = <String>{};
    for (final e in raw) {
      String field;
      String label;
      if (e is Map) {
        field = _canon('${e['field'] ?? e['name'] ?? ''}');
        label = '${e['label'] ?? ''}'.isEmpty ? _labelOf(field) : '${e['label']}';
      } else {
        field = _canon('$e');
        label = _labelOf(field);
      }
      if (field.isEmpty || !seen.add(field)) continue;
      out.add(_Missing(field, label));
    }
    return out;
  }

  void _fillFromServer(Map<String, dynamic> d) {
    String s(String k) => '${d[k] ?? ''}';
    // 监听器会把回填也当成"商家改了东西",先摘掉再装回去,
    // 否则一进页面就写一份和服务端一模一样的草稿
    for (final c in _controllers) {
      c.removeListener(_onFieldChanged);
    }
    _subjectType = s('subject_type');
    _settleType = s('settle_account_type');
    _licenseImage = s('business_license_image_url');
    _idFront = s('legal_person_id_front_url');
    _idBack = s('legal_person_id_back_url');
    _legalName.text = s('legal_person_name');
    _adminName.text = s('admin_contact_name');
    _adminPhone.text = s('admin_contact_phone');
    _adminEmail.text = s('admin_contact_email');
    _settleName.text = s('settle_account_name');
    _bankName.text = s('settle_bank_name');
    _bankBranch.text = s('settle_bank_branch');
    // 身份证号和银行账号服务端只回尾 4 位,回填不了 —— 输入框留空,
    // 用 hint 告诉商家"已经填过了,不动它就不会变"
    _legalId.clear();
    _settleNo.clear();
    for (final c in _controllers) {
      c.addListener(_onFieldChanged);
    }
    _missingLeft = _stillMissing.length;
    if (mounted) setState(() {});
  }

  // -------------------------------------------------------------------------
  // 草稿:商家填这个要翻抽屉找证件,一次填不完是常态
  // -------------------------------------------------------------------------

  void _scheduleDraftSave() {
    if (!_editable) return;
    _draftTimer?.cancel();
    // 每敲一个字写一次 prefs 太浪费,停手半秒再落盘
    _draftTimer = Timer(const Duration(milliseconds: 500), _saveDraft);
  }

  Future<void> _saveDraft() async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(
      _draftKey,
      jsonEncode({
        'saved_at': DateTime.now().millisecondsSinceEpoch,
        'subject_type': _subjectType,
        'business_license_image_url': _licenseImage,
        'legal_person_name': _legalName.text,
        // 身份证号和银行账号也进草稿。**这是一个有代价的选择**:
        // 它们会以明文躺在 App 私有目录里,直到提交成功后被清掉。
        // 不存的话商家每次回来都要重敲 18 位身份证 + 19 位卡号,
        // 而这一页本来就是"填一半去翻抽屉"的典型 —— 那才是真正会让人放弃的地方。
        'legal_person_id_no': _legalId.text,
        'legal_person_id_front_url': _idFront,
        'legal_person_id_back_url': _idBack,
        'admin_contact_name': _adminName.text,
        'admin_contact_phone': _adminPhone.text,
        'admin_contact_email': _adminEmail.text,
        'settle_account_type': _settleType,
        'settle_account_name': _settleName.text,
        'settle_bank_name': _bankName.text,
        'settle_bank_branch': _bankBranch.text,
        'settle_account_no': _settleNo.text,
      }),
    );
  }

  Future<void> _restoreDraft(Map<String, dynamic> server) async {
    if (!_editable) return;
    final prefs = await SharedPreferences.getInstance();
    final raw = prefs.getString(_draftKey);
    if (raw == null || !mounted) return;
    try {
      final d = jsonDecode(raw) as Map<String, dynamic>;
      // 同一份资料网页端(#205)也能改。服务端的更新时间比草稿新,
      // 说明老板已经在电脑前填过了 —— 这时候拿手机上的旧草稿盖回去,
      // 等于把他刚填对的银行卡改回错的。宁可丢草稿
      final serverAt = DateTime.tryParse('${server['applyment_updated_at']}');
      final draftAt =
          DateTime.fromMillisecondsSinceEpoch(d['saved_at'] as int? ?? 0);
      if (serverAt != null && serverAt.isAfter(draftAt)) {
        await prefs.remove(_draftKey);
        return;
      }
      String s(String k) => '${d[k] ?? ''}';
      // 和 _fillFromServer 一样先摘监听器:恢复草稿不是"商家又改了一次",
      // 不该顺手再写一遍盘,也不该在一次 setState 里套一堆 setState
      for (final c in _controllers) {
        c.removeListener(_onFieldChanged);
      }
      _subjectType = s('subject_type');
      _settleType = s('settle_account_type');
      _licenseImage = s('business_license_image_url');
      _idFront = s('legal_person_id_front_url');
      _idBack = s('legal_person_id_back_url');
      _legalName.text = s('legal_person_name');
      _legalId.text = s('legal_person_id_no');
      _adminName.text = s('admin_contact_name');
      _adminPhone.text = s('admin_contact_phone');
      _adminEmail.text = s('admin_contact_email');
      _settleName.text = s('settle_account_name');
      _bankName.text = s('settle_bank_name');
      _bankBranch.text = s('settle_bank_branch');
      _settleNo.text = s('settle_account_no');
      for (final c in _controllers) {
        c.addListener(_onFieldChanged);
      }
      _missingLeft = _stillMissing.length;
      setState(() => _draftRestored = true);
    } catch (_) {
      // 草稿坏了就当没有,别让一段坏 JSON 把整页卡死
      await prefs.remove(_draftKey);
    }
  }

  Future<void> _dropDraft() async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove(_draftKey);
    if (!mounted) return;
    setState(() => _draftRestored = false);
    _fillFromServer(_data);
  }

  // -------------------------------------------------------------------------
  // 提交
  // -------------------------------------------------------------------------

  /// 只查格式,不查"填没填全" —— 填一半就存是这一页的设计,
  /// 而"齐没齐"由服务端说了算(见 _missing)
  String? _formatError() {
    final id = _legalId.text.trim();
    // 这里只查形状。**校验位由服务端真算**(GB 11643 加权模 11),
    // 不在客户端复制一份算法 —— 两份实现迟早有一份是错的,
    // 而错的那份会把对的号码拦下来
    if (id.isNotEmpty && !RegExp(r'^\d{17}[\dXx]$').hasMatch(id)) {
      return '身份证号是 18 位,最后一位可能是 X';
    }
    final phone = _adminPhone.text.trim();
    if (phone.isNotEmpty && !RegExp(r'^1\d{10}$').hasMatch(phone)) {
      return '超级管理员手机号填 11 位手机号 —— 微信的通知和签约短信都发到这里';
    }
    final email = _adminEmail.text.trim();
    // 正则和服务端 ApplymentIn.check_formats 逐字一致(#205 要求三端同一套规则)。
    // 松一点点就会出现"这边过了那边不过",商家只看到一句莫名其妙的报错
    if (email.isNotEmpty &&
        !RegExp(r'^[^@\s]+@[^@\s.]+(\.[^@\s.]+)+$').hasMatch(email)) {
      return '邮箱格式不对,再看一眼';
    }
    final acct = _settleNo.text.trim();
    if (acct.isNotEmpty && !RegExp(r'^\d{8,32}$').hasMatch(acct)) {
      return '银行账号是 8~32 位数字,别带空格和横杠';
    }
    return null;
  }

  Future<void> _submit() async {
    final bad = _formatError();
    if (bad != null) {
      _toast(bad);
      return;
    }
    setState(() => _saving = true);
    try {
      final body = <String, dynamic>{
        'subject_type': _subjectType,
        'business_license_image_url': _licenseImage,
        'legal_person_name': _legalName.text.trim(),
        'legal_person_id_front_url': _idFront,
        'legal_person_id_back_url': _idBack,
        'admin_contact_name': _adminName.text.trim(),
        'admin_contact_phone': _adminPhone.text.trim(),
        'admin_contact_email': _adminEmail.text.trim(),
        'settle_account_type': _settleType,
        'settle_account_name': _settleName.text.trim(),
        'settle_bank_name': _bankName.text.trim(),
        'settle_bank_branch': _bankBranch.text.trim(),
      };
      // 敏感字段:只在商家这次真的输入了才发。空着代表"不动已存的那份" ——
      // 服务端只回尾号,客户端回填不了完整值,不这样处理一保存就会把它清空
      final id = _legalId.text.trim();
      if (id.isNotEmpty) body['legal_person_id_no'] = id;
      final acct = _settleNo.text.trim();
      if (acct.isNotEmpty) body['settle_account_no'] = acct;

      final result =
          await widget.api.saveApplyment(body, merchantId: widget.shop.id);
      if (!mounted) return;

      // 存到服务端了,本机那份明文草稿没有留着的理由。
      // 放在刷新之前:后面万一 setState 顺手又存了一次,清了也白清
      _draftTimer?.cancel();
      final prefs = await SharedPreferences.getInstance();
      await prefs.remove(_draftKey);
      if (!mounted) return;
      setState(() => _draftRestored = false);

      final inner = result['applyment'];
      final data = inner is Map
          ? <String, dynamic>{...result, ...Map<String, dynamic>.from(inner)}
          : result;
      // PUT 的响应里不一定带完整度和状态(契约只写了"提交/更新资料")。
      // 带了就直接用;没带就重新拉一次 —— 宁可多一个请求,
      // 也不能因为响应里恰好没有 missing 就跟商家说"资料齐了,已提交"
      if (data.containsKey('applyment_status') ||
          data.containsKey('missing') ||
          data.containsKey('missing_fields')) {
        setState(() {
          _data = data;
          _missing = _parseMissing(data);
        });
        _fillFromServer(data);
      } else {
        await _load();
        if (!mounted) return;
      }
      _toast(_missing.isEmpty
          ? '资料齐了,已提交'
          : '已保存,还差 ${_missing.length} 项 —— 齐了才会提交');
    } catch (e) {
      if (!mounted) return;
      _toast(e is ApiException ? e.message : '$e');
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  void _toast(String message) {
    if (!mounted) return;
    ScaffoldMessenger.of(context)
        .showSnackBar(SnackBar(content: Text(message)));
  }

  // -------------------------------------------------------------------------
  // 构建
  // -------------------------------------------------------------------------

  @override
  Widget build(BuildContext context) {
    return SzPageScaffold(
      appBar: AppBar(title: const Text('收款资料')),
      body: _error != null
          ? SzError(error: _error, onRetry: _load)
          : _loading
              ? const Center(child: CircularProgressIndicator())
              : ListView(
                  padding:
                      const EdgeInsets.fromLTRB(kPagePad, 14, kPagePad, 40),
                  children: [
                    if (_serverMerchantId != null &&
                        _serverMerchantId != widget.shop.id) ...[
                      _wrongShopBanner(),
                      const SizedBox(height: 14),
                    ],
                    _statusCard(),
                    const SizedBox(height: 14),
                    _whyBlock(),
                    const SizedBox(height: 18),
                    if (_editable) ...[
                      if (_draftRestored) ...[
                        _draftBanner(),
                        const SizedBox(height: 14),
                      ],
                      if (_stillMissing.isNotEmpty) ...[
                        _missingCard(),
                        const SizedBox(height: 14),
                      ],
                      ..._form(),
                    ] else
                      _readOnlySummary(),
                  ],
                ),
    );
  }

  /// 服务端解出来的店和商家刚才在看的那家不是同一家。
  ///
  /// 不静悄悄地画下去:连锁每家店的结算账户可以不一样,填错店的后果是
  /// **货款打到另一家店的卡上**,而这种错要等钱到账了才看得出来。
  Widget _wrongShopBanner() {
    final scheme = Theme.of(context).colorScheme;
    final name = '${_data['merchant_name'] ?? ''}'.trim();
    return Material(
      color: scheme.errorContainer,
      borderRadius: BorderRadius.circular(kRadiusMd),
      child: Padding(
        padding: const EdgeInsets.all(kCardPad),
        child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Icon(Icons.warning_amber_outlined,
              size: 19, color: scheme.onErrorContainer),
          const SizedBox(width: 8),
          Expanded(
            child: Text(
              '这一份是「${name.isEmpty ? '另一家门店' : name}」的收款资料,'
              '不是你刚才打开的「${widget.shop.name}」。\n'
              '连锁每家店的结算账户可以不一样 —— 先确认是不是要填这家,'
              '别把这家的卡填成另一家的。',
              style: TextStyle(
                  fontSize: 12.5,
                  height: 1.6,
                  color: scheme.onErrorContainer),
            ),
          ),
        ]),
      ),
    );
  }

  // ---- 状态(#206) ----

  Widget _statusCard() {
    final scheme = Theme.of(context).colorScheme;
    final sz = Theme.of(context).sz;
    final v = _statusView();

    final bg = v.severe
        ? scheme.errorContainer
        : (v.onYou ? scheme.secondaryContainer : sz.surface);
    final fg = v.severe
        ? scheme.onErrorContainer
        : (v.onYou ? scheme.onSecondaryContainer : sz.ink);
    final sub = v.severe || v.onYou ? fg.withValues(alpha: 0.86) : sz.inkMuted;

    return Material(
      color: bg,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(kRadiusMd),
        side: BorderSide(color: v.severe || v.onYou ? Colors.transparent : sz.line),
      ),
      child: Padding(
        padding: const EdgeInsets.all(kCardPad),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Icon(v.icon, size: 19, color: fg),
            const SizedBox(width: 8),
            // Expanded 是必须的:大字号下标题会换行,不给约束就是溢出
            Expanded(
              child: Text(v.title,
                  style: TextStyle(
                      fontSize: 15, fontWeight: FontWeight.w600, color: fg)),
            ),
          ]),
          const SizedBox(height: 8),
          // ** ** 是写文案时标重点用的记号,渲染前去掉(同 promises_page)
          Text(v.what.replaceAll('**', ''),
              style: TextStyle(fontSize: 12.8, height: 1.6, color: sub)),
          if (v.todo.isNotEmpty) ...[
            const SizedBox(height: 10),
            Text('你要做的',
                style: TextStyle(
                    fontSize: 11, letterSpacing: 1.2, color: sub)),
            const SizedBox(height: 5),
            for (final t in v.todo)
              Padding(
                padding: const EdgeInsets.only(bottom: 4),
                child: Row(crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text('· ', style: TextStyle(color: sub)),
                      Expanded(
                        child: Text(t,
                            style: TextStyle(
                                fontSize: 12.8, height: 1.55, color: fg)),
                      ),
                    ]),
              ),
          ],
        ]),
      ),
    );
  }

  _StatusView _statusView() {
    final no = '${_data['applyment_no'] ?? ''}'.trim();
    final phone = '${_data['admin_contact_phone'] ?? ''}'.trim();
    final phoneText = phone.isEmpty ? '你填的超级管理员手机号' : phone;
    final bank = '${_data['settle_bank_name'] ?? ''}'.trim();
    final tail = '${_data['settle_account_tail'] ?? ''}'.trim();
    final bankText = tail.isEmpty ? '你填的那张卡' : '$bank 尾号 $tail';

    switch (_status) {
      case 'submitted':
        return _StatusView(
          icon: Icons.hourglass_top,
          title: '资料已提交',
          // 有没有微信侧单号,是"平台还收着"和"微信在审"的分界。
          // 用数据说,不写死"这一版不调微信" —— 接口一接上这句话就成了假话
          what: no.isEmpty
              ? '资料已经存到平台。等平台按微信的格式递上去之后,这里会出现'
                  '微信侧的申请单号,同时给超级管理员发通知。\n\n'
                  '在那之前收款方式不变:货款仍然先到平台账户,再由平台打给你。'
              : '微信已经受理,申请单号 $no。审核结果会通知超级管理员;'
                  '如果需要你去验证打款金额或扫码签约,这一页也会变。',
          todo: [
            '现在不用你做什么,等通知就行',
            '通知发到 $phoneText —— 号码不对的话你会一直等不到,'
                '改掉重新提交就行',
          ],
        );
      case 'need_account_verify':
        return _StatusView(
          icon: Icons.account_balance_outlined,
          title: '卡在你这儿了:要验证打款金额',
          onYou: true,
          what: '微信已经往 $bankText 打了一笔**小额随机金额**(通常几分到一块多),'
              '用来确认这张卡确实是你的。这笔钱不用退,也不用你付。',
          todo: const [
            '去手机银行或网银,查这笔到账的准确金额(精确到分)',
            '在微信支付商户平台按提示把这个金额填回去',
            '一般 1 个工作日内到账;超过 3 天没看到,先回来核对下面的银行账号有没有填错',
            '这一步不做,后面的签约和收款都开始不了',
          ],
        );
      case 'need_sign':
        return _StatusView(
          icon: Icons.qr_code_scanner,
          title: '卡在你这儿了:等超级管理员扫码签约',
          onYou: true,
          what: '微信那边户已经开好了,就差最后一步:超级管理员本人用**自己的微信**'
              '扫码签署协议。签完才算开通。',
          todo: [
            '签约链接以短信发到 $phoneText,微信支付商户平台里也找得到',
            '必须是超级管理员本人的微信扫 —— 换个人扫签不了',
            '没签约就收不了钱,单子照常来但结算开不了',
          ],
        );
      case 'rejected':
        final reason = '${_data['applyment_reject_reason'] ?? ''}'.trim();
        return _StatusView(
          icon: Icons.error_outline,
          title: '被驳回了',
          severe: true,
          what: reason.isEmpty
              ? '没拿到具体原因。别反复提交同一份,先找客服问清楚要改哪儿。'
              : '原因照原文抄给你:\n$reason',
          todo: const [
            '按上面的原因改掉对应的资料,改完重新提交',
            '看不懂驳回原因就找客服 —— 同一份资料反复提交只会反复被驳',
          ],
        );
      case 'finished':
        return _StatusView(
          icon: Icons.verified_outlined,
          title: '已开通:货款直接进你的账户',
          what: '从现在起,用户付的钱由微信支付直接结算到 $bankText,不在平台账上停留。'
              '平台的佣金走分账,在对账页一笔一笔看得到。',
          todo: const [
            '要换银行卡或改法人信息,先联系客服 —— 变更期间收款会暂停,'
                '别挑生意最忙的时候改',
          ],
        );
      default:
        return const _StatusView(
          icon: Icons.edit_note_outlined,
          title: '还没提交',
          what: '提交之前收款方式不变:货款先到平台账户,再由平台打给你。'
              '这一页填齐并提交后,才会换成"直接进你自己的账户"。',
          todo: ['把下面的资料填齐,拉到底点提交'],
        );
    }
  }

  // ---- 为什么要这些资料(#204 的重点) ----

  Widget _whyBlock() {
    // 第一次来(还没提交)默认展开:这时候他最需要一个交材料的理由。
    // 之后再来是看状态的,收起来别挡路
    final first = _status == 'not_submitted';
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      _moneyFlowCard(),
      const SizedBox(height: 12),
      Theme(
        // ExpansionTile 默认带一条上下分隔线,和卡片描边撞在一起很脏
        data: Theme.of(context).copyWith(dividerColor: Colors.transparent),
        child: SzCard(
          padding: const EdgeInsets.symmetric(horizontal: 4),
          child: ExpansionTile(
            initiallyExpanded: first,
            tilePadding: const EdgeInsets.symmetric(horizontal: 10),
            childrenPadding: const EdgeInsets.fromLTRB(10, 0, 10, 12),
            expandedCrossAxisAlignment: CrossAxisAlignment.start,
            title: const Text('这些东西交给谁、平台能看到多少',
                style: TextStyle(fontSize: 14, fontWeight: FontWeight.w600)),
            children: [
              _fact(
                '① 资料是交给微信支付的,平台只是代传',
                '这一页填的东西,最终提交给微信支付,给你开一个「特约商户」。'
                '平台在中间只做一件事:按微信要求的格式转交过去。\n\n'
                '审不审得过、什么时候过,是微信说了算 —— 我们催不动,'
                '也不会替你改材料。',
              ),
              _fact(
                '② 开通之后,货款直接进你自己的账户',
                '现在:用户的钱先进平台的商户号,再由平台打给你。\n'
                '开通后:用户的钱由微信支付直接结算到你填的银行账户,'
                '平台的佣金通过分账拿走。\n\n'
                '对你实际的变化是两件:到账不用再等平台打款;'
                '「平台要是出事,我的货款怎么办」这个问题不存在了 —— '
                '货款根本不经过平台。',
              ),
              _fact(
                '③ 平台看得到什么、看不到什么',
                '身份证号和银行账号:提交后在平台库里是**密文**,这一页和网页后台'
                '再打开都只显示尾 4 位 —— 你自己也看不到完整的,要改只能重填一遍。\n\n'
                '证件照:存在私密空间,不进公开图库,每次打开都要过一次鉴权,'
                '店铺详情页上不会出现。门头照那种本来就给顾客看的图不在此列,'
                '它照旧是公开的。\n\n'
                '平台的人如果因为审核需要解密查看完整号码,'
                '**会留下一条记录**:谁、什么时候、看了哪家店的哪个字段。',
              ),
              const SizedBox(height: 2),
              Builder(builder: (context) {
                final sz = Theme.of(context).sz;
                return Text(
                  '店员看不到这一页 —— 入口只对店主开。',
                  style: TextStyle(
                      fontSize: 11.5, height: 1.6, color: sz.inkMuted),
                );
              }),
            ],
          ),
        ),
      ),
    ]);
  }

  /// 钱的流向:用账目台面托出来,和对账页是同一种"这块是账"的视觉。
  Widget _moneyFlowCard() {
    return SzLedgerCard(
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        const Text('为什么要你的身份证和银行卡',
            style: TextStyle(fontSize: 15, fontWeight: FontWeight.w600)),
        const SizedBox(height: 8),
        Text(
          '因为收款要换个走法:让用户的钱**直接进你自己的账户**,不再先经过平台。\n\n'
          '要走通这条路,微信支付得先认识你这家店 —— 营业执照、法人身份证、'
          '你要收款的银行账户,一样都不能少。这是微信开户的硬要求,'
          '不是平台加的门槛。',
          style: TextStyle(
              fontSize: 12.8, height: 1.65, color: SzColors.dark.inkMuted),
        ),
        const SizedBox(height: 12),
        _flowLine('现在', '用户付款 → 平台账户 → 平台打款给你', false),
        const SizedBox(height: 6),
        _flowLine('开通后', '用户付款 → 你的银行账户(平台按 '
            '${(widget.shop.commissionRate * 100).toStringAsFixed(1)}% 分账取佣金)',
            true),
      ]),
    );
  }

  Widget _flowLine(String tag, String text, bool good) {
    // 台面内部换掉了 SzColors,颜色必须在台面内取 —— 在外面取会拿到浅色态,
    // 画出来是一道刺眼的亮线(见 SzLedgerCard 的注释)
    final dark = SzColors.dark;
    return Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
      // minWidth 而不是固定 width:正常字号下两行对齐好看,
      // 系统字号调大时标签自己撑开,不会被压到溢出
      ConstrainedBox(
        constraints: const BoxConstraints(minWidth: 52),
        child: Text('$tag  ',
            style: TextStyle(
                fontSize: 11.5,
                height: 1.5,
                color: good ? dark.earn : dark.inkFaint)),
      ),
      Expanded(
        child: Text(text,
            style: TextStyle(
                fontSize: 12.3,
                height: 1.5,
                color: good ? dark.earn : dark.inkMuted)),
      ),
    ]);
  }

  Widget _fact(String title, String body) {
    final sz = Theme.of(context).sz;
    return Padding(
      padding: const EdgeInsets.only(bottom: 14),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text(title,
            style: TextStyle(
                fontSize: 13.2, fontWeight: FontWeight.w600, color: sz.ink)),
        const SizedBox(height: 5),
        // ** ** 是写文案时标重点用的,渲染前去掉 —— 和 promises_page 一个做法
        Text(body.replaceAll('**', ''),
            style: TextStyle(fontSize: 12.5, height: 1.65, color: sz.inkMuted)),
      ]),
    );
  }

  // ---- 草稿提示 / 缺项 ----

  Widget _draftBanner() {
    final sz = Theme.of(context).sz;
    return SzCard(
      child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Icon(Icons.history, size: 17, color: sz.inkMuted),
        const SizedBox(width: 8),
        Expanded(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text('接着上次填',
                    style: TextStyle(
                        fontSize: 13.5,
                        fontWeight: FontWeight.w600,
                        color: sz.ink)),
                const SizedBox(height: 3),
                Text('上次没填完的内容还留在这台手机上,已经帮你放回去了。',
                    style: TextStyle(
                        fontSize: 12, height: 1.5, color: sz.inkMuted)),
              ]),
        ),
        TextButton(
          onPressed: _dropDraft,
          child: const Text('用平台上的'),
        ),
      ]),
    );
  }

  Widget _missingCard() {
    final sz = Theme.of(context).sz;
    final left = _stillMissing;
    // 进度用服务端下发的 filled/total,不在客户端数 ——
    // 客户端数出来的分母是客户端那份必填清单,那正是这里不该有的东西
    final filled = _data['filled_count'] as int?;
    final total = _data['required_total'] as int?;
    return SzCard(
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          Expanded(
            child: Text('还差 ${left.length} 项',
                style: TextStyle(
                    fontSize: 13.5, fontWeight: FontWeight.w600, color: sz.ink)),
          ),
          if (filled != null && total != null && total > 0)
            Text('已填 $filled/$total',
                style: TextStyle(fontSize: 11.5, color: sz.inkMuted)),
        ]),
        const SizedBox(height: 4),
        Text('齐了才会提交给微信。缺哪些是平台按你选的主体类型算的 —— '
            '个体工商户和企业要交的东西不完全一样。',
            style: TextStyle(fontSize: 11.8, height: 1.55, color: sz.inkMuted)),
        const SizedBox(height: 9),
        // Wrap 而不是 Row:大字号下一行放不下会自动折行,不会溢出
        Wrap(spacing: 6, runSpacing: 6, children: [
          for (final m in left) SzChip(m.label, color: sz.hold, dense: true),
        ]),
      ]),
    );
  }

  // ---- 表单 ----

  bool _isMissing(String field) => _stillMissing.any((m) => m.field == field);

  String _localValue(String field) {
    switch (field) {
      case 'subject_type':
        return _subjectType;
      case 'business_license_image_url':
        return _licenseImage;
      case 'legal_person_name':
        return _legalName.text.trim();
      case 'legal_person_id_no':
        // 输入框空 + 服务端有尾号 = 之前存过了,不算缺。
        // 这两个框刻意不回填(服务端只回尾 4 位),不这样判会一直显示"还差这项"
        return _legalId.text.trim().isNotEmpty
            ? _legalId.text.trim()
            : '${_data['legal_person_id_tail'] ?? ''}'.trim();
      case 'legal_person_id_front_url':
        return _idFront;
      case 'legal_person_id_back_url':
        return _idBack;
      case 'admin_contact_name':
        return _adminName.text.trim();
      case 'admin_contact_phone':
        return _adminPhone.text.trim();
      case 'admin_contact_email':
        return _adminEmail.text.trim();
      case 'settle_account_type':
        return _settleType;
      case 'settle_account_name':
        return _settleName.text.trim();
      case 'settle_bank_name':
        return _bankName.text.trim();
      case 'settle_bank_branch':
        return _bankBranch.text.trim();
      case 'settle_account_no':
        return _settleNo.text.trim().isNotEmpty
            ? _settleNo.text.trim()
            : '${_data['settle_account_tail'] ?? ''}'.trim();
      default:
        return '';
    }
  }

  List<Widget> _form() {
    final sz = Theme.of(context).sz;
    final idTail = '${_data['legal_person_id_tail'] ?? ''}'.trim();
    final acctTail = '${_data['settle_account_tail'] ?? ''}'.trim();

    return [
      // ---- 主体类型 ----
      _section('主体类型', '按营业执照上写的选。选错了微信会驳回,'
          '而且两种要交的材料不一样。'),
      Wrap(spacing: 8, runSpacing: 8, children: [
        SzChip('个体工商户',
            selected: _subjectType == 'individual',
            onTap: () => _pickSubject('individual')),
        SzChip('企业',
            selected: _subjectType == 'enterprise',
            onTap: () => _pickSubject('enterprise')),
      ]),
      const SizedBox(height: 6),
      Text(
        _subjectType == 'enterprise'
            ? '有限公司、股份公司、合伙企业这些。结算一般只能用公户。'
            : _subjectType == 'individual'
                ? '营业执照「类型」那一栏写的就是个体工商户,经营者即法人。'
                    '结算可以用法人的个人卡。'
                : '营业执照上「类型」那一栏怎么写的,这里就怎么选。',
        style: TextStyle(fontSize: 11.5, height: 1.55, color: sz.inkMuted),
      ),
      if (_isMissing('subject_type'))
        _missingHint('subject_type', '还没选主体类型'),
      const SizedBox(height: 20),

      // ---- 营业执照 ----
      _section('营业执照', '整张拍进来。统一社会信用代码和主体名称这两行'
          '一定要看得清 —— 微信是照着这两行核的。'),
      LicenseUploadField(
        api: widget.api,
        label: '营业执照照片',
        url: _licenseImage,
        purpose: 'license',
        tip: '拍全、别反光;复印件加盖公章也可以',
        onUploaded: (u) {
          setState(() => _licenseImage = u);
          _scheduleDraftSave();
        },
      ),
      if (_isMissing('business_license_image_url'))
        _missingHint('business_license_image_url', '还没传营业执照'),
      const SizedBox(height: 20),

      // ---- 法人 ----
      _section('法定代表人', '必须是营业执照上那个人。个体工商户就是经营者本人。'),
      TextField(
        controller: _legalName,
        maxLength: 50,
        textInputAction: TextInputAction.next,
        decoration: _dec('法人姓名', 'legal_person_name',
            hint: '和身份证上一模一样,别用简称'),
      ),
      TextField(
        controller: _legalId,
        maxLength: 18,
        keyboardType: TextInputType.visiblePassword,
        inputFormatters: [
          // 身份证只可能是数字和末位的 X,在输入的时候就挡掉别的字符,
          // 比提交时报错友好
          FilteringTextInputFormatter.allow(RegExp(r'[0-9Xx]')),
        ],
        decoration: _dec('法人身份证号', 'legal_person_id_no',
            hint: idTail.isEmpty ? '18 位' : '已保存,尾号 $idTail',
            helper: idTail.isEmpty
                ? '提交后只会显示尾 4 位,平台库里存的是密文'
                : '不动它就不会变;要改就重新输入完整 18 位'),
      ),
      const SizedBox(height: 12),
      LicenseUploadField(
        api: widget.api,
        // 标签放在固定高度的取景框里,长文案在大字号下会把框撑破 ——
        // 解释性的话一律挪到框底下的 tip(那行随便换行)
        label: '身份证人像面',
        url: _idFront,
        purpose: 'id_card',
        tip: '有照片那一面。四角拍全、号码清楚,别用美颜和滤镜',
        onUploaded: (u) {
          setState(() => _idFront = u);
          _scheduleDraftSave();
        },
      ),
      if (_isMissing('legal_person_id_front_url'))
        _missingHint('legal_person_id_front_url', '还没传身份证人像面'),
      const SizedBox(height: 12),
      LicenseUploadField(
        api: widget.api,
        label: '身份证国徽面',
        url: _idBack,
        purpose: 'id_card',
        tip: '有有效期那一面。有效期那行要看得清 —— 证快过期微信会驳回',
        onUploaded: (u) {
          setState(() => _idBack = u);
          _scheduleDraftSave();
        },
      ),
      if (_isMissing('legal_person_id_back_url'))
        _missingHint('legal_person_id_back_url', '还没传身份证国徽面'),
      const SizedBox(height: 20),

      // ---- 超级管理员 ----
      _section('超级管理员',
          '微信把进件通知发给他,签约也是他本人扫码。填错了你收不到'
          '「该你签约了」,进件会一直卡着没人知道。\n'
          '一般就填老板自己;填别人的话,那个人得随叫随到。'),
      TextField(
        controller: _adminName,
        maxLength: 50,
        textInputAction: TextInputAction.next,
        decoration: _dec('姓名', 'admin_contact_name'),
      ),
      TextField(
        controller: _adminPhone,
        maxLength: 11,
        keyboardType: TextInputType.phone,
        inputFormatters: [FilteringTextInputFormatter.digitsOnly],
        decoration: _dec('手机号', 'admin_contact_phone',
            helper: '签约短信发到这个号,必须能收短信'),
      ),
      TextField(
        controller: _adminEmail,
        maxLength: 100,
        keyboardType: TextInputType.emailAddress,
        decoration: _dec('邮箱', 'admin_contact_email',
            hint: '微信的开户结果邮件发这里'),
      ),
      const SizedBox(height: 20),

      // ---- 结算账户 ----
      _section('结算账户', '这就是以后货款直接到账的那张卡。'
          '**开户名和证件对不上是驳回的第一大原因** —— 填之前拿卡和证核一遍。'),
      Wrap(spacing: 8, runSpacing: 8, children: [
        SzChip('对公账户',
            selected: _settleType == 'corporate',
            onTap: () => _pickSettle('corporate')),
        SzChip('对私账户',
            selected: _settleType == 'personal',
            onTap: () => _pickSettle('personal')),
      ]),
      const SizedBox(height: 6),
      Text(
        _settleType == 'corporate'
            ? '公户。开户名必须和营业执照上的主体名称一模一样,一个字都不能差。'
            : _settleType == 'personal'
                ? '个人卡。开户名必须是法定代表人本人 —— 填家里人的卡过不了。'
                : '企业一般走对公;个体工商户可以用法人的个人卡。',
        style: TextStyle(fontSize: 11.5, height: 1.55, color: sz.inkMuted),
      ),
      if (_isMissing('settle_account_type'))
        _missingHint('settle_account_type', '还没选账户类型'),
      const SizedBox(height: 12),
      TextField(
        controller: _settleName,
        maxLength: 80,
        textInputAction: TextInputAction.next,
        decoration: _dec('开户名', 'settle_account_name',
            hint: _settleType == 'corporate' ? '营业执照上的主体全称' : '法人姓名'),
      ),
      TextField(
        controller: _bankName,
        maxLength: 80,
        textInputAction: TextInputAction.next,
        decoration: _dec('开户银行', 'settle_bank_name',
            hint: '如:中国工商银行'),
      ),
      TextField(
        controller: _bankBranch,
        maxLength: 120,
        textInputAction: TextInputAction.next,
        decoration: _dec('开户支行', 'settle_bank_branch',
            hint: '如:中国工商银行成都天府大道支行',
            helper: '支行全称,不确定就翻开户许可证或打银行客服问'),
      ),
      TextField(
        controller: _settleNo,
        maxLength: 32,
        keyboardType: TextInputType.number,
        inputFormatters: [FilteringTextInputFormatter.digitsOnly],
        decoration: _dec('银行账号', 'settle_account_no',
            hint: acctTail.isEmpty ? '只填数字,别带空格和横杠' : '已保存,尾号 $acctTail',
            helper: acctTail.isEmpty
                ? '提交后只会显示尾 4 位,平台库里存的是密文'
                : '不动它就不会变;要改就重新输入完整卡号'),
      ),

      const SizedBox(height: 26),
      // 已提交但还没进微信流程时,资料仍然能改 —— 但要说清代价:
      // 改到不齐,服务端会把状态退回「还没提交」(next_applyment_status 的第二条),
      // 商家不知道的话就会以为自己还在排队,其实早掉出队列了
      if (_status == 'submitted')
        Padding(
          padding: const EdgeInsets.only(bottom: 12),
          child: Text(
            '资料已经齐了,在等平台报送。现在还能改 —— '
            '但要是改着改着空了一项,状态会退回「还没提交」,得补齐了才重新排队。',
            style: TextStyle(fontSize: 12, height: 1.6, color: sz.hold),
          ),
        ),
      FilledButton(
        onPressed: _saving ? null : _submit,
        child: Text(_saving
            ? '保存中…'
            : (_stillMissing.isEmpty
                ? '保存并提交'
                : '保存进度(还差 ${_stillMissing.length} 项)')),
      ),
      const SizedBox(height: 10),
      Text(
        '填一半可以直接退出:改一处存一次草稿,存在这台手机上、不上传,'
        '下次进来接着填。提交成功后草稿自动清掉。',
        style: TextStyle(fontSize: 11.5, height: 1.6, color: sz.inkMuted),
      ),
    ];
  }

  void _pickSubject(String v) {
    setState(() => _subjectType = _subjectType == v ? '' : v);
    _scheduleDraftSave();
  }

  void _pickSettle(String v) {
    setState(() => _settleType = _settleType == v ? '' : v);
    _scheduleDraftSave();
  }

  Widget _section(String title, String desc) {
    final sz = Theme.of(context).sz;
    return Padding(
      padding: const EdgeInsets.only(bottom: 10),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        SzSectionTitle(title),
        const SizedBox(height: 5),
        Text(desc.replaceAll('**', ''),
            style: TextStyle(fontSize: 12.2, height: 1.6, color: sz.inkMuted)),
      ]),
    );
  }

  /// 缺项提示。用 hold(琥珀)不用 danger:红色是报错,而"还没填"不是错 ——
  /// 商家本来就是分几次填完的。
  ///
  /// 服务端那份**已经有值**却还报缺,说明它报的不是"没填"而是**取值约束**
  /// (企业主体必须用对公账户)。这种要原样显示服务端的说法 ——
  /// 本地写死的"还没选账户类型"会把商家指到完全错的方向。
  /// 其余情况用 [fallback],因为服务端的 label 是名词("结算账户类型"),
  /// 挂在框底下当提示读起来不像句话。
  Widget _missingHint(String field, String fallback) {
    final sz = Theme.of(context).sz;
    final constraint = _serverValue(field).isNotEmpty
        ? _stillMissing
            .where((m) => m.field == field)
            .map((m) => m.label)
            .firstOrNull
        : null;
    final text = constraint ?? fallback;
    return Padding(
      padding: const EdgeInsets.only(top: 6),
      child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Icon(Icons.pending_outlined, size: 14, color: sz.hold),
        const SizedBox(width: 5),
        Expanded(
          child: Text(text,
              style: TextStyle(fontSize: 11.5, height: 1.45, color: sz.hold)),
        ),
      ]),
    );
  }

  InputDecoration _dec(String label, String field,
      {String? hint, String? helper}) {
    final sz = Theme.of(context).sz;
    final missing = _isMissing(field);
    final helperText = missing
        ? (helper == null ? '还差这项' : '还差这项 · $helper')
        : helper;
    return InputDecoration(
      labelText: label,
      hintText: hint,
      helperText: helperText,
      // 两行:大字号下 helper 一行放不下会被截掉,截掉的往往正是"要改就重新输入"
      helperMaxLines: 3,
      helperStyle: missing ? TextStyle(color: sz.hold) : null,
      border: const OutlineInputBorder(),
    );
  }

  // ---- 已开通:只读 ----

  Widget _readOnlySummary() {
    final sz = Theme.of(context).sz;
    String s(String k) => '${_data[k] ?? ''}'.trim();
    final idTail = s('legal_person_id_tail');
    final acctTail = s('settle_account_tail');
    String subject(String v) => switch (v) {
          'enterprise' => '企业',
          'individual' => '个体工商户',
          _ => '',
        };
    String settle(String v) => switch (v) {
          'corporate' => '对公',
          'personal' => '对私',
          _ => '',
        };
    final rows = <(String, String)>[
      ('主体类型', subject(s('subject_type'))),
      ('法人姓名', s('legal_person_name')),
      ('法人身份证号', idTail.isEmpty ? '' : '**** **** **** $idTail'),
      ('超级管理员', '${s('admin_contact_name')} ${s('admin_contact_phone')}'.trim()),
      ('结算账户', settle(s('settle_account_type'))),
      ('开户名', s('settle_account_name')),
      ('开户银行', '${s('settle_bank_name')} ${s('settle_bank_branch')}'.trim()),
      ('银行账号', acctTail.isEmpty ? '' : '**** **** **** $acctTail'),
    ];
    return SzCard(
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text('已提交的资料',
            style: TextStyle(
                fontSize: 13.5, fontWeight: FontWeight.w600, color: sz.ink)),
        const SizedBox(height: 4),
        // 为什么这里不给改:报上去的是提交时那一版,改库里的这份没用 ——
        // 让商家以为"我已经改好了"比不让他改更糟
        Text(
          _status == 'finished'
              ? '已经开通了,这份资料不在这里改。要换银行卡或改法人信息先联系客服 —— '
                  '变更期间收款会暂停,别挑生意最忙的时候改。\n\n'
                  '身份证号和银行账号只显示尾 4 位,这一页看不到完整的;'
                  '平台的人要解密查看会留一条记录。'
              : '微信那边已经在按这一版办了,现在改库里的这份没用 —— '
                  '报上去的是提交时那一版。真要改先联系客服撤回。\n\n'
                  '身份证号和银行账号只显示尾 4 位,这一页看不到完整的;'
                  '平台的人要解密查看会留一条记录。',
          style: TextStyle(fontSize: 11.8, height: 1.55, color: sz.inkMuted),
        ),
        const SizedBox(height: 12),
        // 名称列跟着系统字号一起放大(上限 1.7 倍),不然「法人身份证号」
        // 在大字号下会被挤成三行。用固定宽度而不是 min 约束是为了各行对齐
        for (final (k, v) in rows)
          Padding(
            padding: const EdgeInsets.only(bottom: 8),
            child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
              SizedBox(
                width: MediaQuery.textScalerOf(context)
                    .scale(96)
                    .clamp(96.0, 164.0),
                child: Text(k,
                    style: TextStyle(
                        fontSize: 12.3, height: 1.5, color: sz.inkMuted)),
              ),
              // Expanded:开户支行全称很长,大字号下要能换行
              Expanded(
                child: Text(v.isEmpty ? '—' : v,
                    style: TextStyle(fontSize: 12.8, height: 1.5, color: sz.ink)),
              ),
            ]),
          ),
      ]),
    );
  }
}

/// 一个进件状态在页面上长什么样。
///
/// [onYou] 是这一版最要紧的一位:微信进件卡在「待账户验证」和「待签约」时,
/// **要商家本人去操作**,平台干瞪眼也没用。这两种状态必须一眼看出
/// 「球在你脚下」,而不是和「审核中」长得一样。
class _StatusView {
  const _StatusView({
    required this.icon,
    required this.title,
    required this.what,
    this.todo = const [],
    this.onYou = false,
    this.severe = false,
  });

  final IconData icon;
  final String title;
  final String what;
  final List<String> todo;
  final bool onYou;
  final bool severe;
}
