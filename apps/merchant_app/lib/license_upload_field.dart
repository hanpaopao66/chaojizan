import 'dart:async';
import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:image_picker/image_picker.dart';
import 'package:superz_shared/superz_shared.dart';

/// 证照上传框(入驻表单专用)。
///
/// 一个框把上传的完整生命周期都装进去:
/// - 空态:拍照/相册二选一,旁边给「怎么拍才合格」的示例与文案;
/// - 上传中:进度圈 + 文案,期间不可重复点;
/// - 失败:**把原因说出来**(格式/超大/网络),给「重试」按钮 ——
///   重试直接复用上次选的图,不用回相册再翻一遍;
/// - 成功:缩略图回显(带鉴权头,私密桶的图不带头是 401 破图),
///   点击看大图,可重拍替换。
///
/// 上传成功后如果服务端配了 OCR,自动识别证照号回填表单(识别不可用时
/// 静默跳过,商家无感)。
class LicenseUploadField extends StatefulWidget {
  const LicenseUploadField({
    super.key,
    required this.api,
    required this.label,
    required this.url,
    required this.onUploaded,
    this.onOcr,
    this.purpose = 'license',
    this.tip = '证照四角完整、文字清晰、无反光,审核一次就能过',
  });

  final ApiClient api;
  final String label;

  /// 已上传证照的相对 URL;空串 = 还没传
  final String url;
  final ValueChanged<String> onUploaded;

  /// OCR 识别结果回调(仅在服务端启用且识别成功时调用),
  /// 入参形如 {license_no: '...', name: '...'}
  final void Function(Map<String, dynamic> fields)? onOcr;

  /// 上传用途,决定落哪个桶。默认 `license`(经营证照)。
  /// 进件要传身份证正反面,那是 `id_card` —— 两个 purpose 服务端都已是私密桶
  /// (`services/storage.py` 的 `PURPOSES`),这里只是把选择权交给调用方,
  /// **不要**为了传身份证再复制一份上传组件出来。
  final String purpose;

  /// 框底下那行拍摄提示。不同证件该提醒的点不一样
  /// (执照要看清信用代码,身份证要看清号码和有效期)。
  final String tip;

  @override
  State<LicenseUploadField> createState() => _LicenseUploadFieldState();
}

class _LicenseUploadFieldState extends State<LicenseUploadField> {
  bool _uploading = false;
  String? _error;

  // 上次选的图留着:失败重试不用回相册再翻一遍
  Uint8List? _lastBytes;
  String _lastName = '';

  Future<void> _pick() async {
    final source = await showModalBottomSheet<ImageSource>(
      context: context,
      builder: (sheet) => SafeArea(
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          ListTile(
            leading: const Icon(Icons.photo_camera_outlined),
            title: const Text('拍照'),
            subtitle: const Text('对准证照,四角完整、文字清晰'),
            onTap: () => Navigator.pop(sheet, ImageSource.camera),
          ),
          ListTile(
            leading: const Icon(Icons.photo_library_outlined),
            title: const Text('从相册选择'),
            onTap: () => Navigator.pop(sheet, ImageSource.gallery),
          ),
        ]),
      ),
    );
    if (source == null || !mounted) return;

    final kind = source == ImageSource.camera
        ? AppPermissionKind.camera
        : AppPermissionKind.photos;
    if (!await PermissionRationale.ensure(context, kind,
        reason: '用于拍摄/选取经营证照图片并上传。\n拒绝不影响其他功能。')) {
      return;
    }
    final picked = await ImagePicker().pickImage(
      source: source,
      maxWidth: 1600, // 证照要能看清文字,分辨率比菜品图高
      imageQuality: 90,
    );
    if (picked == null) return;
    final bytes = await picked.readAsBytes();
    _lastBytes = bytes;
    _lastName = picked.name;
    await _upload();
  }

  Future<void> _upload() async {
    final bytes = _lastBytes;
    if (bytes == null) return;
    setState(() {
      _uploading = true;
      _error = null;
    });
    try {
      // 经营证照/身份证:都是私密桶,只有店主和管理员看得到(#124)。
      // 证照图比菜品图大,弱网下 30 秒不够,放宽到 60 秒
      final url = await widget.api.uploadImage(bytes, _lastName,
          purpose: widget.purpose, timeout: const Duration(seconds: 60));
      if (!mounted) return;
      widget.onUploaded(url);
      unawaited(_tryOcr(url));
    } on ApiException catch (e) {
      if (mounted) setState(() => _error = e.message);
    } catch (e) {
      if (mounted) setState(() => _error = '$e');
    } finally {
      if (mounted) setState(() => _uploading = false);
    }
  }

  /// OCR 只是省几下手输:服务端没配识别模型、识别失败都静默跳过
  Future<void> _tryOcr(String url) async {
    if (widget.onOcr == null) return;
    try {
      final result = await widget.api.ocrLicense(url);
      if (!mounted) return;
      if (result['enabled'] == true && result['ok'] == true) {
        widget.onOcr!(result);
      }
    } catch (_) {/* 识别不可用不打扰商家 */}
  }

  void _preview() {
    showDialog<void>(
      context: context,
      builder: (_) => Dialog(
        insetPadding: const EdgeInsets.all(12),
        child: InteractiveViewer(
          child: Image(
            image: szAuthedImage(widget.api.resolveUrl(widget.url),
                token: widget.api.token),
            fit: BoxFit.contain,
          ),
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final sz = Theme.of(context).sz;

    Widget inner;
    if (_uploading) {
      inner = const Column(mainAxisAlignment: MainAxisAlignment.center,
          children: [
            CircularProgressIndicator(),
            SizedBox(height: 10),
            Text('上传中…', style: TextStyle(fontSize: 12)),
          ]);
    } else if (_error != null) {
      inner = Padding(
        padding: const EdgeInsets.all(12),
        child: Column(mainAxisAlignment: MainAxisAlignment.center, children: [
          Icon(Icons.error_outline, size: 28, color: sz.danger),
          const SizedBox(height: 6),
          Text(_error!,
              maxLines: 2,
              overflow: TextOverflow.ellipsis,
              textAlign: TextAlign.center,
              style: TextStyle(fontSize: 12, color: sz.danger)),
          const SizedBox(height: 6),
          FilledButton.tonalIcon(
            icon: const Icon(Icons.refresh, size: 16),
            label: const Text('重试'),
            onPressed: _upload,
          ),
        ]),
      );
    } else if (widget.url.isEmpty) {
      inner = Column(mainAxisAlignment: MainAxisAlignment.center, children: [
        const Icon(Icons.add_a_photo_outlined, size: 32),
        const SizedBox(height: 8),
        Text(widget.label, style: Theme.of(context).textTheme.bodySmall),
        const SizedBox(height: 4),
        Text('拍照或从相册选择',
            style: TextStyle(fontSize: 11, color: sz.inkMuted)),
      ]);
    } else {
      inner = Stack(fit: StackFit.expand, children: [
        Image(
          image: szAuthedImage(widget.api.resolveUrl(widget.url),
              token: widget.api.token),
          fit: BoxFit.cover,
        ),
        Positioned(
          right: 6,
          bottom: 6,
          child: Row(mainAxisSize: MainAxisSize.min, children: [
            _thumbChip(Icons.zoom_in, '看大图', _preview),
            const SizedBox(width: 6),
            _thumbChip(Icons.photo_camera_outlined, '重拍', _pick),
          ]),
        ),
      ]);
    }

    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      InkWell(
        onTap: _uploading
            ? null
            : (widget.url.isEmpty && _error == null ? _pick : null),
        borderRadius: BorderRadius.circular(8),
        child: Container(
          height: 150,
          width: double.infinity,
          decoration: BoxDecoration(
            border: Border.all(
                color: _error != null ? sz.danger : scheme.outline),
            borderRadius: BorderRadius.circular(8),
          ),
          clipBehavior: Clip.antiAlias,
          child: inner,
        ),
      ),
      Padding(
        padding: const EdgeInsets.only(top: 6),
        child: Row(children: [
          Icon(Icons.tips_and_updates_outlined, size: 14, color: sz.inkFaint),
          const SizedBox(width: 4),
          Expanded(
            child: Text(widget.tip,
                style: TextStyle(fontSize: 11, color: sz.inkMuted)),
          ),
        ]),
      ),
    ]);
  }

  Widget _thumbChip(IconData icon, String label, VoidCallback onTap) {
    return Material(
      color: Colors.black.withValues(alpha: 0.55),
      borderRadius: BorderRadius.circular(14),
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(14),
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
          child: Row(mainAxisSize: MainAxisSize.min, children: [
            Icon(icon, size: 14, color: Colors.white),
            const SizedBox(width: 3),
            Text(label,
                style: const TextStyle(fontSize: 11, color: Colors.white)),
          ]),
        ),
      ),
    );
  }
}
