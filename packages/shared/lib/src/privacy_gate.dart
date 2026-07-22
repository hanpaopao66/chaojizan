/// 首次启动隐私弹窗(应用商店上架审核硬性要求)。
///
/// 规则:
///  - 首次启动(或协议版本更新后)弹窗,同意前不进入应用、
///    不初始化任何收集类 SDK(推送等由 onAgreed 回调延迟启动);
///  - 不同意 → 退出应用;
///  - 同意记录本地留存,版本变更(kLegalVersion)会重新征求。
library;

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'legal.dart';

const String _kAgreedKey = 'privacy_agreed_version';

class PrivacyGate extends StatefulWidget {
  const PrivacyGate({super.key, required this.child, this.onAgreed});

  final Widget child;

  /// 用户同意后执行(每次启动一次):放推送等收集类 SDK 的初始化。
  final Future<void> Function()? onAgreed;

  @override
  State<PrivacyGate> createState() => _PrivacyGateState();
}

class _PrivacyGateState extends State<PrivacyGate> {
  bool _checked = false;
  bool _agreed = false;

  @override
  void initState() {
    super.initState();
    _check();
  }

  Future<void> _check() async {
    final prefs = await SharedPreferences.getInstance();
    final agreed = prefs.getString(_kAgreedKey) == kLegalVersion;
    if (!mounted) return;
    setState(() {
      _checked = true;
      _agreed = agreed;
    });
    if (agreed) {
      widget.onAgreed?.call();
    } else {
      WidgetsBinding.instance.addPostFrameCallback((_) => _prompt());
    }
  }

  Future<void> _prompt() async {
    final agree = await showDialog<bool>(
      context: context,
      barrierDismissible: false,
      builder: (context) => PopScope(
        canPop: false,
        child: AlertDialog(
          title: const Text('用户协议与隐私政策'),
          content: SingleChildScrollView(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text(
                  '超级赞(Super-Z)是劳动者互助外卖平台。我们只收集提供服务所必需的'
                  '最少信息(手机号、收货位置等),不出售你的任何个人信息。\n\n'
                  '请阅读并同意以下文件后开始使用:',
                  style: TextStyle(height: 1.6),
                ),
                const SizedBox(height: 8),
                TextButton(
                    onPressed: () => LegalPage.showTerms(context),
                    child: const Text('《用户协议》全文')),
                TextButton(
                    onPressed: () => LegalPage.showPrivacy(context),
                    child: const Text('《隐私政策》全文')),
              ],
            ),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(context, false),
              child: const Text('不同意并退出'),
            ),
            FilledButton(
              onPressed: () => Navigator.pop(context, true),
              child: const Text('同意'),
            ),
          ],
        ),
      ),
    );
    if (agree == true) {
      final prefs = await SharedPreferences.getInstance();
      await prefs.setString(_kAgreedKey, kLegalVersion);
      if (mounted) setState(() => _agreed = true);
      widget.onAgreed?.call();
    } else {
      SystemNavigator.pop(); // 不同意:退出应用(商店审核的标准行为)
    }
  }

  @override
  Widget build(BuildContext context) {
    if (!_checked) {
      return const Scaffold(body: SizedBox.shrink());
    }
    if (!_agreed) {
      // 弹窗期间的底层页面:只放品牌名,不加载任何业务
      return const Scaffold(
          body: Center(
              child: Text('超级赞',
                  style: TextStyle(fontSize: 32, fontWeight: FontWeight.bold))));
    }
    return widget.child;
  }
}
