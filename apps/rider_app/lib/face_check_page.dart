import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';
import 'package:url_launcher/url_launcher.dart';

/// 人脸核验(防代送)。做完返回 true,没做/没过返回 false。
///
/// ## 为什么实名了还要这一步
///
/// 实名(姓名 + 身份证号查人口库)只证明这个身份是真的,证明不了拿手机跑单的
/// 是不是本人。账号借给别人、几个人轮着跑一个号,顾客就把餐交给了一个平台
/// 不认识的人。所以实名之后做一次人脸核验,在线期间每隔几个小时复核一次。
///
/// ## 合规口径
///
/// - 第一次要**单独同意**(勾选框),和实名、隐私政策那些分开问;
/// - 平台**不保存人脸照片**:照片在手机和核验服务商之间传,平台只拿结果;
/// - 过期了只是不能接新单,**手上的单照常送完** —— 这句话要说出来,
///   不然他会以为单子也被收走了。
class FaceCheckPage extends StatefulWidget {
  const FaceCheckPage({super.key, required this.api});

  final ApiClient api;

  /// 拉起核验页,返回这次是否通过。
  static Future<bool> open(BuildContext context, ApiClient api) async {
    final ok = await Navigator.of(context).push<bool>(
        MaterialPageRoute(builder: (_) => FaceCheckPage(api: api)));
    return ok == true;
  }

  @override
  State<FaceCheckPage> createState() => _FaceCheckPageState();
}

class _FaceCheckPageState extends State<FaceCheckPage> {
  RiderFaceStatus? _status;
  String? _error;
  bool _agreed = false;
  bool _busy = false;

  /// 上一次没过的原因,显示在按钮上方
  String _failReason = '';

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final s = await widget.api.riderFaceStatus();
      if (mounted) {
        setState(() {
          _status = s;
          _error = null;
        });
      }
    } catch (e) {
      if (mounted) setState(() => _error = '$e');
    }
  }

  Future<void> _start() async {
    final s = _status!;
    setState(() => _busy = true);
    try {
      final session =
          await widget.api.startRiderFace(consent: !s.consented && _agreed);
      if (session.verifyUrl.isNotEmpty) {
        // 服务商的 H5 活体页。做完回来再由服务端去查结果 ——
        // 页面说自己过了不算,改一下客户端就能绕过
        await launchUrl(Uri.parse(session.verifyUrl),
            mode: LaunchMode.inAppBrowserView);
        if (!mounted) return;
        final done = await showDialog<bool>(
          context: context,
          builder: (context) => SzDialog(
            title: const Text('做完了吗?'),
            content: const Text('在刚才的页面里做完了,就点「查看结果」'),
            actions: [
              TextButton(
                  onPressed: () => Navigator.pop(context, false),
                  child: const Text('还没有')),
              FilledButton(
                  onPressed: () => Navigator.pop(context, true),
                  child: const Text('查看结果')),
            ],
          ),
        );
        if (done != true) return;
      }
      final res = await widget.api.finishRiderFace(session.checkId);
      if (!mounted) return;
      if (res.passed == true) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(
            content: Text('核验通过,${_fmtHours(res.intervalHours)}内不用再做')));
        Navigator.of(context).pop(true);
        return;
      }
      setState(() {
        _status = res;
        _failReason = res.reason.isEmpty ? '没有通过,换个光线好的地方再试一次' : res.reason;
      });
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text('$e')));
      _load(); // 同意时刻可能已经记下了,刷新一下免得再让他勾
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  static String _fmtHours(double h) =>
      h == h.roundToDouble() ? '${h.toInt()} 小时' : '$h 小时';

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    final s = _status;
    if (_error != null) {
      return SzPageScaffold(
        appBar: AppBar(title: const Text('人脸核验')),
        body: SzError(error: _error, onRetry: _load),
      );
    }
    if (s == null) {
      return const Scaffold(body: Center(child: CircularProgressIndicator()));
    }
    final needConsent = !s.consented;
    final hours = _fmtHours(s.intervalHours);
    final lead = switch (s.due) {
      'expired' => '上次核验已过 $hours,复核一次才能接新单。手上的单照常送完,不受影响。',
      _ when !s.enrolled => '跑单前做一次人脸核验,确认是你本人在跑。大约 10 秒。',
      _ => '核验还在有效期内,也可以现在提前复核。',
    };
    return SzPageScaffold(
      appBar: AppBar(title: const Text('人脸核验')),
      body: ListView(
        padding: const EdgeInsets.fromLTRB(kPagePad, 14, kPagePad, 28),
        children: [
          Icon(Icons.face_retouching_natural, size: 56, color: sz.earn),
          const SizedBox(height: 12),
          Text(lead,
              textAlign: TextAlign.center,
              style: const TextStyle(fontSize: kFontBodyLg, height: 1.5)),
          const SizedBox(height: 18),
          SzCard(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text('为什么要做',
                    style: TextStyle(
                        fontSize: kFontBodyLg, fontWeight: FontWeight.w600)),
                const SizedBox(height: 8),
                _line(sz, Icons.how_to_reg_outlined,
                    '实名只能证明身份是真的,证明不了拿手机的是你本人。'
                    '人脸核验防的是账号被别人借去代送'),
                _line(sz, Icons.schedule_outlined,
                    '在线时每 $hours复核一次。到点没做只是不能接新单,'
                    '手上的单照常送完'),
                _line(sz, Icons.no_photography_outlined,
                    '平台不保存你的人脸照片,只记录核验通过没有'),
              ],
            ),
          ),
          const SizedBox(height: 14),
          if (needConsent)
            CheckboxListTile(
              value: _agreed,
              onChanged: _busy ? null : (v) => setState(() => _agreed = v ?? false),
              controlAffinity: ListTileControlAffinity.leading,
              contentPadding: EdgeInsets.zero,
              title: const Text(
                  '我同意平台为确认本人跑单,在上线和接单时对我进行人脸核验',
                  style: TextStyle(fontSize: kFontBody)),
            ),
          if (_failReason.isNotEmpty) ...[
            Container(
              padding: const EdgeInsets.all(12),
              decoration: BoxDecoration(
                color: sz.hold.withValues(alpha: .10),
                borderRadius: BorderRadius.circular(kRadiusSm),
              ),
              child: Text('这次没通过:$_failReason',
                  style: TextStyle(fontSize: kFontNote, color: sz.hold)),
            ),
            const SizedBox(height: 12),
          ],
          SizedBox(
            width: double.infinity,
            child: FilledButton(
              onPressed: _busy || (needConsent && !_agreed) ? null : _start,
              child: Text(_busy
                  ? '核验中…'
                  : _failReason.isEmpty ? '开始核验' : '再试一次'),
            ),
          ),
        ],
      ),
    );
  }

  Widget _line(SzColors sz, IconData icon, String text) => Padding(
        padding: const EdgeInsets.only(bottom: 8),
        child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Icon(icon, size: 14, color: sz.inkMuted),
          const SizedBox(width: 7),
          Expanded(
            child: Text(text,
                style: TextStyle(
                    fontSize: kFontNote, height: 1.45, color: sz.inkMuted)),
          ),
        ]),
      );
}
