import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';

/// 骑手实名认证:**姓名 + 身份证号,核验通过当场生效**。
///
/// ## 这一页以前是什么样
///
/// 传身份证照片 + 传健康证 → 提交 → 等管理员看照片审批。
/// **真正的门槛从来不是填资料,是等审批** —— 而人工看一眼照片
/// 判断不了真伪,还不如查公安人口库准。
///
/// 现在是:填两个字段 → 二要素核验(查国家人口基础信息库)→ 当场通过。
///
/// ## 为什么不做人脸
///
/// 《人脸识别技术应用安全管理办法》(网信办+公安部,2025-06-01 施行)明写:
/// **存在其他非人脸方式能达到同等业务要求的,不得将人脸识别作为唯一验证方式**;
/// 并鼓励优先使用国家人口基础信息库,以减少人脸信息的收集与存储。
///
/// 二要素核验正是那个"其他方式"。所以这里没有人脸,也不该有。
///
/// ## 为什么不要健康证
///
/// 国家层面并不要求送餐员持健康证 —— 法规要求餐食封装、避免送餐人员
/// 直接接触食品,送餐员因此不属于"直接接触入口食品的人员"。四川已明确取消。
///
/// 所以这里是选填,只有地方另有要求的城市才需要。
class RiderVerifyFlowPage extends StatefulWidget {
  const RiderVerifyFlowPage({super.key, required this.api});

  final ApiClient api;

  @override
  State<RiderVerifyFlowPage> createState() => _RiderVerifyFlowPageState();
}

class _RiderVerifyFlowPageState extends State<RiderVerifyFlowPage> {
  RiderProfile? _profile;
  bool _loaded = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final p = await widget.api.riderProfile();
      if (mounted) {
        setState(() {
          _profile = p;
          _loaded = true;
          _error = null;
        });
      }
    } catch (e) {
      if (mounted) {
        setState(() {
          _loaded = true;
          _error = '$e';
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    if (!_loaded) {
      return const Scaffold(body: Center(child: CircularProgressIndicator()));
    }
    if (_error != null) {
      return SzPageScaffold(
        appBar: AppBar(title: const Text('实名认证')),
        body: SzError(error: _error, onRetry: _load),
      );
    }
    final p = _profile!;
    if (p.isApproved) {
      final sz = Theme.of(context).sz;
      return SzPageScaffold(
        appBar: AppBar(title: const Text('实名认证')),
        body: Center(
          child: Padding(
            padding: const EdgeInsets.all(32),
            child: Column(mainAxisSize: MainAxisSize.min, children: [
              Icon(Icons.verified, size: 56, color: sz.earn),
              const SizedBox(height: 16),
              Text('${p.realName} · 已实名',
                  style: Theme.of(context).textTheme.titleLarge),
              const SizedBox(height: 8),
              Text(
                p.idVerified
                    ? '姓名与身份证号已通过国家人口库核验'
                    : '认证已通过',
                textAlign: TextAlign.center,
                style: TextStyle(fontSize: 12.5, color: sz.inkMuted),
              ),
              const SizedBox(height: 20),
              FilledButton(
                  onPressed: () => Navigator.of(context).pop(),
                  child: const Text('去接单')),
            ]),
          ),
        ),
      );
    }

    // pending 只可能是历史数据(旧流程留下的);新流程核验通过即 approved
    if (p.status == 'pending') {
      return SzPageScaffold(
        appBar: AppBar(title: const Text('实名认证')),
        body: Center(
          child: Padding(
            padding: const EdgeInsets.all(32),
            child: Column(mainAxisSize: MainAxisSize.min, children: [
              const Icon(Icons.verified_user_outlined, size: 56),
              const SizedBox(height: 16),
              Text('资料审核中', style: Theme.of(context).textTheme.titleLarge),
              const SizedBox(height: 8),
              const Text('这是旧流程留下的记录。现在实名只要姓名和身份证号,'
                  '核验通过当场生效 —— 如果一直没动静,重新提交一次就行',
                  textAlign: TextAlign.center),
              const SizedBox(height: 20),
              OutlinedButton(onPressed: _load, child: const Text('刷新状态')),
            ]),
          ),
        ),
      );
    }

    return VerifyFormPage(api: widget.api, existing: p, onDone: _load);
  }
}

class VerifyFormPage extends StatefulWidget {
  const VerifyFormPage({
    super.key,
    required this.api,
    required this.existing,
    required this.onDone,
  });

  final ApiClient api;
  final RiderProfile existing;
  final VoidCallback onDone;

  @override
  State<VerifyFormPage> createState() => _VerifyFormPageState();
}

class _VerifyFormPageState extends State<VerifyFormPage> {
  final _name = TextEditingController();
  final _idCard = TextEditingController();
  bool _busy = false;

  @override
  void dispose() {
    _name.dispose();
    _idCard.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    final name = _name.text.trim();
    final id = _idCard.text.trim().toUpperCase();
    if (name.length < 2 || !RegExp(r'^\d{17}[\dXx]$').hasMatch(id)) {
      ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('请填写真实姓名和 18 位身份证号')));
      return;
    }
    setState(() => _busy = true);
    try {
      await widget.api.submitRiderProfile(realName: name, idCardNo: id);
      widget.onDone();
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text('$e')));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    return SzPageScaffold(
      appBar: AppBar(title: const Text('实名认证')),
      body: ListView(
        padding: const EdgeInsets.fromLTRB(kPagePad, 14, kPagePad, 28),
        children: [
          if (widget.existing.status == 'rejected' &&
              widget.existing.rejectReason.isNotEmpty) ...[
            Container(
              padding: const EdgeInsets.all(12),
              decoration: BoxDecoration(
                color: sz.hold.withValues(alpha: .10),
                borderRadius: BorderRadius.circular(kRadiusSm),
              ),
              child: Text('上次没通过:${widget.existing.rejectReason}',
                  style: TextStyle(fontSize: 12.5, color: sz.hold)),
            ),
            const SizedBox(height: 14),
          ],

          Text('填两样就行', style: Theme.of(context).textTheme.titleLarge),
          const SizedBox(height: 6),
          Text('姓名和身份证号会跟国家人口库核对一次,通过就能接单 —— 不用等审核。',
              style: TextStyle(fontSize: 12.5, height: 1.5, color: sz.inkMuted)),
          const SizedBox(height: 18),

          TextField(
            controller: _name,
            decoration: const InputDecoration(
              labelText: '真实姓名',
              border: OutlineInputBorder(),
            ),
          ),
          const SizedBox(height: 14),
          TextField(
            controller: _idCard,
            keyboardType: TextInputType.text,
            textCapitalization: TextCapitalization.characters,
            decoration: const InputDecoration(
              labelText: '身份证号',
              helperText: '18 位,末位是 X 也可以',
              border: OutlineInputBorder(),
            ),
          ),
          const SizedBox(height: 18),

          SizedBox(
            width: double.infinity,
            child: FilledButton(
              onPressed: _busy ? null : _submit,
              child: Text(_busy ? '核验中…' : '提交'),
            ),
          ),
          const SizedBox(height: 22),

          // ---- 把"我们不要什么"写出来。骑手在别的平台被要求过这些,
          //      不说清楚他会以为是我们漏了,或者以为后面还有 ----
          SzCard(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text('我们不要的东西',
                    style: TextStyle(
                        fontSize: 14, fontWeight: FontWeight.w600)),
                const SizedBox(height: 9),
                _no(sz, '不要身份证照片',
                    '核验查的是国家人口库,不需要照片。照片是敏感信息,不收就不会泄露'),
                _no(sz, '不要人脸',
                    '法规明写:有别的方式能达到同样目的时,不得把人脸作为唯一验证方式'),
                if (widget.existing.healthCertRequired)
                  _yes(sz, '${widget.existing.city}需要健康证',
                      '国家层面不要求送餐员持健康证,但你所在的城市另有规定 —— '
                      '实名可以先做完,健康证在这一页补传即可')
                else
                  _no(sz, '不要健康证',
                      '送餐员不属于「直接接触入口食品的人员」,国家层面不要求 —— '
                      '四川已经取消了。只有个别城市另有规定时才会让你补'),
                const SizedBox(height: 4),
                Text('身份证号加密保存,任何接口都不会把它发出去。',
                    style: TextStyle(fontSize: 11.5, color: sz.inkMuted)),
              ],
            ),
          ),
          const SizedBox(height: 12),

          // 培训是法定的,提前说清楚,别让他提交完才发现还有一步
          Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Icon(Icons.school_outlined, size: 14, color: sz.inkFaint),
            const SizedBox(width: 7),
            Expanded(
              child: Text(
                '实名之后还有一次三分钟的食品安全培训 —— 那是监管对平台的硬要求,'
                '我们已经把它压到最短。看完就能上线。',
                style: TextStyle(
                    fontSize: 11.5, height: 1.5, color: sz.inkMuted),
              ),
            ),
          ]),
        ],
      ),
    );
  }

  /// 本市另有规定时用这个 —— 和「我们不要的东西」并排,
  /// 但视觉上要一眼能区分,否则骑手会以为这条也是"不要"
  Widget _yes(SzColors sz, String title, String why) => Padding(
        padding: const EdgeInsets.only(bottom: 9),
        child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Icon(Icons.info_outline, size: 14, color: sz.hold),
          const SizedBox(width: 7),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(title, style: TextStyle(fontSize: 13, color: sz.hold)),
                Text(why,
                    style: TextStyle(
                        fontSize: 11.5, height: 1.45, color: sz.inkMuted)),
              ],
            ),
          ),
        ]),
      );

  Widget _no(SzColors sz, String title, String why) => Padding(
        padding: const EdgeInsets.only(bottom: 9),
        child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Icon(Icons.remove_circle_outline, size: 14, color: sz.earn),
          const SizedBox(width: 7),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(title, style: const TextStyle(fontSize: 13)),
                Text(why,
                    style: TextStyle(
                        fontSize: 11.5, height: 1.45, color: sz.inkMuted)),
              ],
            ),
          ),
        ]),
      );
}
