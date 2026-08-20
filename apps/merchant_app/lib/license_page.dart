import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';

import 'license_upload_field.dart';

/// 证照到期档位对应的文案与轻重。
///
/// unknown(未登记)也提醒,但语气最轻 —— 存量商家全是这个状态,
/// 目的是请他们补一次,不是吓唬人。
class LicenseNotice {
  const LicenseNotice(this.title, this.desc, this.severe);

  final String title;
  final String desc;
  final bool severe;

  static LicenseNotice? of(Merchant shop) {
    final left = shop.licenseDaysLeft;
    switch (shop.licenseStage) {
      case 'unknown':
        return const LicenseNotice(
          '还没登记食品经营许可证的有效期',
          '登记后我们会在到期前 30 / 7 / 1 天提醒你。'
              '证过期是静默失效 —— 没人提醒就只能等监管上门。',
          false,
        );
      case 'soon':
        return LicenseNotice(
          '食品经营许可证还有 $left 天到期',
          '续证要跑审批流程,建议现在就去办;拿到新证在这里提交即可。',
          false,
        );
      case 'urgent':
        return LicenseNotice(
          '食品经营许可证 $left 天后到期',
          '过期后仍可营业 7 天,之后需人工核验新证才能恢复接单。',
          true,
        );
      case 'last':
        return const LicenseNotice(
          '食品经营许可证明天到期',
          '过期后有 7 天宽限期,请尽快提交新证。',
          true,
        );
      case 'expired':
        return LicenseNotice(
          '食品经营许可证已过期${left == null ? '' : ' ${-left} 天'}',
          '目前仍可正常接单,但 7 天宽限期结束后将暂停营业。',
          true,
        );
      case 'overdue':
        return const LicenseNotice(
          '已暂停营业:食品经营许可证过期超过宽限期',
          '提交新证后由平台人工核验恢复 —— 无证经营是违法的,'
              '这一步我们不能替你跳过。',
          true,
        );
      default:
        return null;
    }
  }
}

/// 工作台顶部的证照横幅。
///
/// **常驻而不是塞进消息中心**:证过期是唯一一件"到点就自动出事"的事
/// (过期 → 7 天宽限 → 自动停业),而消息中心里的东西划一下就没了。
class LicenseBanner extends StatelessWidget {
  const LicenseBanner({super.key, required this.api, required this.shop});

  final ApiClient api;
  final Merchant shop;

  @override
  Widget build(BuildContext context) {
    // 店员不给资质入口:资质材料不是接单要用的东西
    if (shop.viewerIsStaff || !shop.viewerIsOwner) return const SizedBox();
    final n = LicenseNotice.of(shop);
    if (n == null) return const SizedBox();
    final scheme = Theme.of(context).colorScheme;
    final bg = n.severe ? scheme.errorContainer : scheme.secondaryContainer;
    final fg = n.severe ? scheme.onErrorContainer : scheme.onSecondaryContainer;
    return Material(
      color: bg,
      child: InkWell(
        onTap: () => Navigator.of(context).push(MaterialPageRoute(
            builder: (_) => LicenseRenewalPage(api: api, shop: shop))),
        child: Padding(
          padding: const EdgeInsets.fromLTRB(16, 10, 12, 10),
          child: Row(children: [
            Icon(n.severe ? Icons.error_outline : Icons.info_outline,
                size: 20, color: fg),
            const SizedBox(width: 10),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(n.title,
                      style: TextStyle(
                          fontWeight: FontWeight.w600, color: fg)),
                  const SizedBox(height: 2),
                  Text(n.desc,
                      style: TextStyle(fontSize: 12, color: fg)),
                ],
              ),
            ),
            Icon(Icons.chevron_right, color: fg),
          ]),
        ),
      ),
    );
  }
}

/// 续证:提交新证 → 人工核验 → 自动替换。核验期间照常营业。
class LicenseRenewalPage extends StatefulWidget {
  const LicenseRenewalPage({
    super.key, required this.api, required this.shop});

  final ApiClient api;
  final Merchant shop;

  @override
  State<LicenseRenewalPage> createState() => _LicenseRenewalPageState();
}

class _LicenseRenewalPageState extends State<LicenseRenewalPage> {
  Map<String, dynamic>? _renewal;
  bool _loading = true;

  /// 非空 = 换证申请状态没拉到。"没有待审申请"这句话在这一页有实际后果
  String _error = '';
  bool _busy = false;

  final _no = TextEditingController();
  final _subject = TextEditingController();
  final _bizNo = TextEditingController();
  DateTime? _expires;
  String _imageUrl = '';

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    _no.dispose();
    _subject.dispose();
    _bizNo.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    try {
      final r = await widget.api.myLicenseRenewal();
      if (mounted) {
        setState(() {
          _renewal = r['renewal'] as Map<String, dynamic>?;
          _loading = false;
        });
      }
    } catch (e) {
      // 换证申请拉不到时**不能**装作没有 —— 这一页上"没有待审申请"
      // 直接对应着「再交一份」那个按钮,商家会重复提交
      if (mounted) {
        setState(() {
          _loading = false;
          _error = e is ApiException ? e.message : '$e';
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final pending = _renewal != null && _renewal!['status'] == 'pending';
    return Scaffold(
      appBar: AppBar(title: const Text('食品经营许可证')),
      body: _loading
          ? const Center(child: CircularProgressIndicator())
          : Column(children: [
              // 证照本身的信息还在(来自 shop),只有换证申请状态缺了 ——
              // 整页打回错误态会把能看的也一起拿走,所以只加一条横幅
              if (_error.isNotEmpty)
                SzRetryBanner(
                    text: '换证申请状态没拉到,下面显示的「没有待审申请」不一定是真的。点这里重试',
                    onRetry: () {
                      setState(() => _loading = true);
                      _load();
                    }),
              Expanded(
                child: ListView(
                  padding: const EdgeInsets.all(16),
                  children: [
                    if (widget.shop.licenseExpiresAt.isNotEmpty)
                      // 日期和剩余天数都是**值**,和标题排一行(#294)。
                      // 剩余天数保持红色 —— 那是这一屏唯一要人立刻反应的数字
                      SzCard(
                        padding: EdgeInsets.zero,
                        child: SzEntryTile(
                          icon: Icons.event_available_outlined,
                          title: '当前证照有效期至',
                          value: widget.shop.licenseDaysLeft == null
                              ? widget.shop.licenseExpiresAt
                              : '${widget.shop.licenseExpiresAt} · '
                                  '${widget.shop.licenseDaysLeft! >= 0 ? "还剩 ${widget.shop.licenseDaysLeft} 天" : "已过期 ${-widget.shop.licenseDaysLeft!} 天"}',
                          valueTone: scheme.error,
                        ),
                      ),
                    if (_renewal != null && _renewal!['status'] == 'rejected')
                      Card(
                        color: scheme.errorContainer,
                        child: ListTile(
                          title: const Text('上次提交的新证未通过'),
                          subtitle: Text('${_renewal!['reject_reason']}'),
                        ),
                      ),
                    if (pending) ...[
                      Card(
                        color: scheme.secondaryContainer,
                        child: ListTile(
                          leading: const Icon(Icons.hourglass_top),
                          title: const Text('新证核验中'),
                          subtitle: Text(
                              '编号 ${_renewal!['license_no']};'
                              '核验期间照常营业,通过后自动替换。'),
                        ),
                      ),
                    ] else ...[
                      Card(
                        color: scheme.secondaryContainer,
                        child: const Padding(
                          padding: EdgeInsets.all(12),
                          child: Text(
                            '换证不用停业。提交后由平台人工核验,通过即自动替换店里的'
                            '资质,并解除因证过期造成的停业。',
                          ),
                        ),
                      ),
                      const SizedBox(height: 16),
                      TextField(
                        controller: _no,
                        maxLength: 50,
                        decoration: const InputDecoration(
                            labelText: '许可证编号', border: OutlineInputBorder()),
                      ),
                      // 没选时给解释(它回答"为什么要填"),选完就让位给日期本身
                      SzEntryTile(
                        icon: Icons.calendar_today_outlined,
                        title: '有效期至',
                        value: _expires?.toIso8601String().substring(0, 10),
                        hint: '填了才会在到期前 30 / 7 / 1 天提醒你',
                        onTap: () async {
                          final now = DateTime.now();
                          final picked = await showDatePicker(
                            context: context,
                            // 交一张已经过期的证没有意义,选都别让选
                            firstDate: now.add(const Duration(days: 1)),
                            lastDate: DateTime(now.year + 20),
                            initialDate: now.add(const Duration(days: 365)),
                          );
                          if (picked != null) setState(() => _expires = picked);
                        },
                      ),
                      TextField(
                        controller: _subject,
                        maxLength: 100,
                        decoration: const InputDecoration(
                          labelText: '证照主体名称(选填)',
                          hintText: '如:成都赞小碗餐饮管理有限公司',
                          helperText: '证上的公司/个体户全称。与店招不同很正常。',
                          border: OutlineInputBorder(),
                        ),
                      ),
                      TextField(
                        controller: _bizNo,
                        maxLength: 50,
                        decoration: const InputDecoration(
                            labelText: '营业执照统一社会信用代码(选填)',
                            border: OutlineInputBorder()),
                      ),
                      const SizedBox(height: 8),
                      LicenseUploadField(
                        api: widget.api,
                        label: '新证照片',
                        url: _imageUrl,
                        onUploaded: (u) => setState(() => _imageUrl = u),
                      ),
                      const SizedBox(height: 20),
                      FilledButton(
                        onPressed: _busy ? null : _submit,
                        child: const Text('提交核验'),
                      ),
                    ],
                  ],
                ),
              ),
            ]),
    );
  }

  Future<void> _submit() async {
    final missing = <String>[
      if (_no.text.trim().isEmpty) '许可证编号',
      if (_expires == null) '有效期至',
      if (_imageUrl.isEmpty) '许可证照片',
    ];
    if (missing.isNotEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('还差:${missing.join('、')}')));
      return;
    }
    setState(() => _busy = true);
    try {
      await widget.api.submitLicenseRenewal(
        licenseNo: _no.text.trim(),
        licenseImageUrl: _imageUrl,
        expiresAt: _expires!.toIso8601String().substring(0, 10),
        businessLicenseNo: _bizNo.text.trim(),
        licenseSubject: _subject.text.trim(),
      );
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
          content: Text('已提交,核验通过后自动替换;核验期间照常营业')));
      _load();
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text('$e')));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }
}
