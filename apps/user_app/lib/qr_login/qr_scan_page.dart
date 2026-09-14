import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:mobile_scanner/mobile_scanner.dart';
import 'package:superz_shared/superz_shared.dart';
import 'package:url_launcher/url_launcher.dart';

import '../chat/api.dart' show ChatApi;
import '../chat/links.dart' show cardRefOf, openAppLink;
import '../chat/models.dart' show ChatUser;
import '../chat/pages/pickers.dart' show openPublicChat;
import '../chat/pages/user_profile_page.dart' show UserProfilePage;
import 'qr_confirm_page.dart';
import 'qr_login.dart';

/// 「扫一扫」入口:先说明为什么要相机(商店合规:先告知、后申请),同意了才打开扫码页。
Future<void> openQrScanner(BuildContext context, ApiClient api) async {
  if (!await PermissionRationale.ensure(context, AppPermissionKind.camera,
      reason: '用于「扫一扫」:扫网页版、电脑版上的登录二维码,或者别人的名片二维码。\n拒绝不影响其他功能。')) {
    return;
  }
  if (!context.mounted) return;
  await Navigator.of(context)
      .push(MaterialPageRoute<void>(builder: (_) => QrScanPage(api: api)));
}

/// 扫一扫(手机 App)。扫到超级赞的登录码 → 确认页;扫到本站的名片码(`chaojizan.cc/@超级赞号`、
/// `chaojizan.cc/u/名片编号`,**只认本站域名**,见 [cardRefOf])→ 直接打开对方的资料页,页上有「加为联系人」;
/// 扫到别的 → 把内容摆出来,**不自动打开**,让人自己决定。
///
/// 取景用仓库里 vendor 的 mobile_scanner(和商家端核销团购券同一个):
/// 安卓上是 Google ML Kit 条码识别,iOS 上是系统自带的 Vision。画面只在手机上识别,不上传。
class QrScanPage extends StatefulWidget {
  const QrScanPage({super.key, required this.api, this.scannerBuilder});

  final ApiClient api;

  /// 取景器。不给就是 MobileScanner;测试里换成一个能「假装扫到」的东西
  final Widget Function(BuildContext context, void Function(String raw) onCode)?
      scannerBuilder;

  @override
  State<QrScanPage> createState() => _QrScanPageState();
}

class _QrScanPageState extends State<QrScanPage> {
  /// 正在处理扫到的那一个。同一张码会连着回调好几次,处理完之前一律不理
  bool _handling = false;

  Future<void> _onCode(String raw) async {
    final value = raw.trim();
    if (_handling || value.isEmpty) return;
    setState(() => _handling = true);
    final sid = loginSidOf(value, apiBase: widget.api.baseUrl);
    if (sid != null) {
      try {
        final info = await widget.api.scanQrLogin(sid);
        if (!mounted) return;
        // 扫码页换成确认页:确认完直接回到打开扫一扫之前的地方
        await Navigator.of(context).pushReplacement(MaterialPageRoute<void>(
            builder: (_) => QrConfirmPage(api: widget.api, request: info)));
        return;
      } on ApiException catch (e) {
        if (!mounted) return;
        await _cannot('登录不了', e.message);
      }
    } else if (cardRefOf(value) case final card?) {
      if (await _openCard(card)) return;
    } else {
      await showScannedContent(context, value);
    }
    if (mounted) setState(() => _handling = false);
  }

  Future<void> _cannot(String title, String message) => showDialog<void>(
        context: context,
        builder: (ctx) => SzDialog(
          title: Text(title),
          content: Text(message),
          actions: [
            TextButton(onPressed: () => Navigator.pop(ctx), child: const Text('继续扫')),
          ],
        ),
      );

  /// 名片码:问服务端这是谁,打开他的资料页(扫码页换成资料页,返回就回到打开扫一扫之前的地方)。
  /// 返回 true = 已经离开扫码页。
  ///
  /// `/@号` 也可能是公开群 / 频道的链接:那就先给看群资料,进不进自己点(不自动加入)。
  /// 对方关了「按超级赞号找到我」时 `/@号` 找不到人 —— 照实说,他本人现在给出去的名片码是 `/u/…`,扫那个能打开。
  Future<bool> _openCard(({String? username, String? publicId}) card) async {
    final chatApi = ChatApi(widget.api);
    try {
      if (card.publicId != null) {
        final u = await chatApi.resolvePublicId(card.publicId!);
        return await _showProfile(u.id);
      }
      final r = await chatApi.resolve(card.username!);
      if (r['type'] == 'user') return await _showProfile(ChatUser.fromJson(r['user']).id);
      if (!mounted) return true;
      await openPublicChat(context, (r['chat'] as Map).cast<String, dynamic>());
      return false;
    } on ApiException catch (e) {
      if (mounted) await _cannot('打不开这张名片', e.message);
      return false;
    }
  }

  Future<bool> _showProfile(int userId) async {
    if (!mounted) return true;
    await Navigator.of(context)
        .pushReplacement(MaterialPageRoute<void>(builder: (_) => UserProfilePage(userId: userId)));
    return true;
  }

  Widget _scanner(BuildContext context) {
    final custom = widget.scannerBuilder;
    if (custom != null) return custom(context, _onCode);
    return MobileScanner(
      onDetect: (capture) {
        final v = capture.barcodes.firstOrNull?.rawValue;
        if (v != null) _onCode(v);
      },
      // 放在取景框下面,不压着框线
      errorBuilder: (context, e) => Align(
        alignment: const Alignment(0, 0.5),
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 32),
          child: Text(
            e.errorCode == MobileScannerErrorCode.permissionDenied
                ? '没有相机权限。可以在手机的系统设置里给超级赞打开相机权限'
                : '相机没打开,退出去再试一次',
            textAlign: TextAlign.center,
            style: const TextStyle(fontSize: kFontBody, color: Colors.white, height: 1.6),
          ),
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    // 整页黑底、没有 AppBar:状态栏图标要自己改成白的,不然沿用上一页的深色图标,黑底上看不见
    return AnnotatedRegion<SystemUiOverlayStyle>(
      value: SystemUiOverlayStyle.light,
      child: SzPageScaffold(
      backgroundColor: Colors.black,
      body: Stack(fit: StackFit.expand, children: [
        _scanner(context),
        // 取景框:只是告诉人往哪对,识别是整个画面。不接手势,别挡住下面的取景器
        IgnorePointer(
          child: Center(
            child: Container(
              width: 240,
              height: 240,
              decoration: BoxDecoration(
                borderRadius: BorderRadius.circular(kRadiusMd),
                border: Border.all(color: Colors.white70, width: 2),
              ),
            ),
          ),
        ),
        SafeArea(
          child: Column(children: [
            Row(children: [
              const BackButton(color: Colors.white),
              const Text('扫一扫',
                  style: TextStyle(
                      fontSize: kFontTitle, fontWeight: FontWeight.w600, color: Colors.white)),
              const Spacer(),
              if (_handling)
                const Padding(
                  padding: EdgeInsets.only(right: 16),
                  child: SizedBox(
                      width: 18,
                      height: 18,
                      child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white)),
                ),
            ]),
            const Spacer(),
            const Padding(
              padding: EdgeInsets.fromLTRB(24, 0, 24, 32),
              child: Text('对准登录二维码或名片二维码。\n登录码只扫你自己面前那台电脑上的,别人发来的不要扫',
                  textAlign: TextAlign.center,
                  style: TextStyle(fontSize: kFontNote, color: Colors.white, height: 1.6)),
            ),
          ]),
        ),
      ]),
      ),
    );
  }
}

/// 扫到的不是登录码、也不是本站的名片码:把内容摆出来,复制、打开都由人自己点。**不自动打开任何链接** ——
/// 二维码里可以是任何网址,扫一下就跳过去等于替别人点了链接。
Future<void> showScannedContent(BuildContext context, String raw) async {
  final uri = Uri.tryParse(raw);
  final isLink = uri != null &&
      (uri.scheme == 'http' || uri.scheme == 'https') &&
      uri.host.isNotEmpty;
  final picked = await szShowSheet<String>(
    context: context,
    builder: (ctx) {
      final sz = Theme.of(ctx).sz;
      return SafeArea(
        child: Padding(
          padding: const EdgeInsets.fromLTRB(20, 8, 20, 16),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Text('扫到的内容',
                  style: TextStyle(
                      fontSize: kFontTitle, fontWeight: FontWeight.w600, color: sz.ink)),
              const SizedBox(height: 4),
              Text(isLink ? '这不是超级赞的登录码或名片码,是一个链接。要不要打开,你自己决定' : '这不是超级赞的登录码或名片码',
                  style: TextStyle(fontSize: kFontNote, color: sz.inkMuted)),
              const SizedBox(height: 12),
              Container(
                padding: const EdgeInsets.all(12),
                constraints: const BoxConstraints(maxHeight: 200),
                decoration: BoxDecoration(
                    color: sz.surfaceAlt, borderRadius: BorderRadius.circular(kRadiusSm)),
                child: SingleChildScrollView(
                  child: SelectableText(raw,
                      style: TextStyle(fontSize: kFontBody, color: sz.ink, height: 1.5)),
                ),
              ),
              const SizedBox(height: 14),
              Row(children: [
                Expanded(
                  child: OutlinedButton(
                      onPressed: () => Navigator.pop(ctx, 'copy'), child: const Text('复制')),
                ),
                if (isLink) ...[
                  const SizedBox(width: 10),
                  Expanded(
                    child: FilledButton(
                        onPressed: () => Navigator.pop(ctx, 'open'),
                        child: const Text('打开链接')),
                  ),
                ],
              ]),
              TextButton(
                  onPressed: () => Navigator.pop(ctx), child: const Text('继续扫')),
            ],
          ),
        ),
      );
    },
  );
  if (!context.mounted) return;
  if (picked == 'copy') {
    await Clipboard.setData(ClipboardData(text: raw));
    if (context.mounted) {
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('已复制')));
    }
  } else if (picked == 'open' && uri != null) {
    // 站内链接(个人名片、群邀请、视频)在 App 里打开;别的交给浏览器
    if (await openAppLink(context, uri)) return;
    await launchUrl(uri, mode: LaunchMode.externalApplication);
  }
}
