import 'package:flutter/material.dart';
import 'package:image_picker/image_picker.dart';
import 'package:superz_shared/superz_shared.dart';

/// 骑手实名认证:未提交/被驳回 → 填表提交;待审核 → 等待页;通过 → 门禁放行。
/// 作为接单前的强制门禁,套在抢单/配送/钱包之外。
class RiderVerifyGate extends StatefulWidget {
  const RiderVerifyGate({super.key, required this.api, required this.child});

  final ApiClient api;

  /// 认证通过后展示的主界面
  final Widget child;

  @override
  State<RiderVerifyGate> createState() => _RiderVerifyGateState();
}

class _RiderVerifyGateState extends State<RiderVerifyGate> {
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
      if (mounted) setState(() { _loaded = true; _error = e.toString(); });
    }
  }

  @override
  Widget build(BuildContext context) {
    if (!_loaded) {
      return const Scaffold(body: Center(child: CircularProgressIndicator()));
    }
    if (_error != null) {
      return Scaffold(
        body: Center(
          child: Column(mainAxisSize: MainAxisSize.min, children: [
            Text(_error!),
            const SizedBox(height: 12),
            FilledButton(onPressed: _load, child: const Text('重试')),
          ]),
        ),
      );
    }
    final p = _profile!;
    if (p.isApproved) return widget.child;

    if (p.status == 'pending') {
      return Scaffold(
        appBar: AppBar(title: const Text('实名认证审核中')),
        body: Center(
          child: Padding(
            padding: const EdgeInsets.all(32),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                const Icon(Icons.verified_user_outlined, size: 56),
                const SizedBox(height: 16),
                Text('资料已提交,等待平台审核',
                    style: Theme.of(context).textTheme.titleLarge),
                const SizedBox(height: 8),
                const Text('平台正在核对你的身份证与健康证,通过后即可上线接单',
                    textAlign: TextAlign.center),
                const SizedBox(height: 20),
                OutlinedButton(onPressed: _load, child: const Text('刷新状态')),
              ],
            ),
          ),
        ),
      );
    }

    // unsubmitted / rejected → 表单
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
  late final _name = TextEditingController(text: widget.existing.realName);
  late final _idCard = TextEditingController(text: widget.existing.idCardNo);
  late String _idPhoto = widget.existing.idCardPhotoUrl;
  late String _healthPhoto = widget.existing.healthCertPhotoUrl;
  bool _busy = false;

  Future<void> _pick(bool isIdCard) async {
    final picked = await ImagePicker().pickImage(
        source: ImageSource.gallery, maxWidth: 1280, imageQuality: 85);
    if (picked == null) return;
    try {
      final url =
          await widget.api.uploadImage(await picked.readAsBytes(), picked.name);
      if (mounted) {
        setState(() => isIdCard ? _idPhoto = url : _healthPhoto = url);
      }
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(e.toString())));
    }
  }

  Future<void> _submit() async {
    if (_name.text.trim().length < 2 ||
        !RegExp(r'^\d{17}[\dXx]$').hasMatch(_idCard.text.trim()) ||
        _idPhoto.isEmpty ||
        _healthPhoto.isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
          content: Text('请填写真实姓名、正确身份证号,并上传身份证和健康证照片')));
      return;
    }
    setState(() => _busy = true);
    try {
      await widget.api.submitRiderProfile(
        realName: _name.text.trim(),
        idCardNo: _idCard.text.trim().toUpperCase(),
        idCardPhotoUrl: _idPhoto,
        healthCertPhotoUrl: _healthPhoto,
      );
      widget.onDone();
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(e.toString())));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Widget _photoBox(String label, String url, bool isIdCard) {
    return Expanded(
      child: Column(
        children: [
          InkWell(
            onTap: () => _pick(isIdCard),
            borderRadius: BorderRadius.circular(10),
            child: Container(
              height: 110,
              decoration: BoxDecoration(
                color: Theme.of(context).colorScheme.surfaceContainerHighest,
                borderRadius: BorderRadius.circular(10),
              ),
              clipBehavior: Clip.antiAlias,
              child: url.isEmpty
                  ? const Icon(Icons.add_a_photo, size: 30)
                  : Image.network(widget.api.resolveUrl(url),
                      fit: BoxFit.cover, width: double.infinity),
            ),
          ),
          const SizedBox(height: 4),
          Text(label, style: Theme.of(context).textTheme.bodySmall),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final rejected = widget.existing.status == 'rejected';
    return Scaffold(
      appBar: AppBar(title: const Text('骑手实名认证')),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          if (rejected)
            Card(
              color: Theme.of(context).colorScheme.errorContainer,
              child: Padding(
                padding: const EdgeInsets.all(12),
                child: Text('上次审核被驳回:${widget.existing.rejectReason}\n请修改后重新提交'),
              ),
            ),
          Card(
            color: Theme.of(context).colorScheme.tertiaryContainer,
            child: const Padding(
              padding: EdgeInsets.all(12),
              child: Text('按国家规定,配送员须实名认证并持有效健康证方可上岗。'
                  '你的证件仅用于平台审核,不对外公开。'),
            ),
          ),
          const SizedBox(height: 12),
          TextField(
              controller: _name,
              decoration: const InputDecoration(
                  labelText: '真实姓名 *', border: OutlineInputBorder())),
          const SizedBox(height: 12),
          TextField(
              controller: _idCard,
              maxLength: 18,
              decoration: const InputDecoration(
                  labelText: '身份证号 *', border: OutlineInputBorder())),
          const SizedBox(height: 8),
          Row(children: [
            _photoBox('身份证人像面', _idPhoto, true),
            const SizedBox(width: 12),
            _photoBox('健康证', _healthPhoto, false),
          ]),
          const SizedBox(height: 24),
          FilledButton(
            onPressed: _busy ? null : _submit,
            child: Text(_busy ? '提交中…' : (rejected ? '重新提交审核' : '提交认证')),
          ),
        ],
      ),
    );
  }
}
