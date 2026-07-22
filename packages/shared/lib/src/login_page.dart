import 'dart:async';

import 'package:flutter/material.dart';

import 'api_client.dart';
import 'brand.dart';
import 'legal.dart';
import 'push_service.dart';

/// 三端共用的登录页。MVP 用手机号 + 密码,后续换成验证码/微信登录。
class LoginPage extends StatefulWidget {
  const LoginPage({
    super.key,
    required this.title,
    required this.defaultPhone,
    required this.onLoggedIn,
  });

  final String title;
  final String defaultPhone; // 开发期预填演示账号,省得每次手输
  final void Function(BuildContext context, ApiClient api) onLoggedIn;

  @override
  State<LoginPage> createState() => _LoginPageState();
}

class _LoginPageState extends State<LoginPage> {
  bool _agreed = false;
  late final _phone = TextEditingController(text: widget.defaultPhone);
  final _password = TextEditingController(text: '123456');
  bool _busy = false;

  Future<void> _login() async {
    if (!_agreed) {
      ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('请先阅读并勾选同意《用户协议》和《隐私政策》')));
      return;
    }
    setState(() => _busy = true);
    final api = ApiClient();
    try {
      await api.login(_phone.text.trim(), _password.text);
      PushService.onLogin(api.userId!); // 绑定推送别名,失败静默
      if (!mounted) return;
      widget.onLoggedIn(context, api);
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(e.toString())));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 360),
          child: SingleChildScrollView(
            padding: const EdgeInsets.all(24),
            child: Column(
              mainAxisAlignment: MainAxisAlignment.center,
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                const Center(child: BrandLogo(size: 72)),
                const SizedBox(height: 12),
                Text('超级赞',
                    textAlign: TextAlign.center,
                    style: Theme.of(context).textTheme.headlineMedium?.copyWith(
                        fontWeight: FontWeight.bold,
                        color: Theme.of(context).colorScheme.primary)),
                const SizedBox(height: 4),
                Text(widget.title,
                    textAlign: TextAlign.center,
                    style: Theme.of(context).textTheme.titleMedium),
                const SizedBox(height: 32),
                TextField(
                  controller: _phone,
                  keyboardType: TextInputType.phone,
                  decoration: const InputDecoration(
                      labelText: '手机号', border: OutlineInputBorder()),
                ),
                const SizedBox(height: 12),
                TextField(
                  controller: _password,
                  obscureText: true,
                  decoration: const InputDecoration(
                      labelText: '密码', border: OutlineInputBorder()),
                ),
                const SizedBox(height: 12),
                AgreementRow(
                    agreed: _agreed,
                    onChanged: (v) => setState(() => _agreed = v)),
                const SizedBox(height: 12),
                FilledButton(
                  onPressed: _busy ? null : _login,
                  child: Text(_busy ? '登录中…' : '登录'),
                ),
                const IcpFooter(),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

/// 验证码登录页(用户端主入口)。
/// 短信服务未配置时,服务端返回开发模式验证码并自动填入。
class SmsLoginPage extends StatefulWidget {
  const SmsLoginPage({
    super.key,
    required this.title,
    required this.onLoggedIn,
    this.passwordLoginBuilder,
  });

  final String title;
  final void Function(BuildContext context, ApiClient api) onLoggedIn;

  /// 提供后显示「密码登录」切换入口(商家/骑手/老账号用)
  final WidgetBuilder? passwordLoginBuilder;

  @override
  State<SmsLoginPage> createState() => _SmsLoginPageState();
}

class _SmsLoginPageState extends State<SmsLoginPage> {
  bool _agreed = false;
  final _phone = TextEditingController();
  final _code = TextEditingController();
  Timer? _countdownTimer;
  int _countdown = 0;
  bool _busy = false;

  @override
  void dispose() {
    _countdownTimer?.cancel();
    super.dispose();
  }

  Future<void> _sendCode() async {
    final phone = _phone.text.trim();
    if (!RegExp(r'^1\d{10}$').hasMatch(phone)) {
      ScaffoldMessenger.of(context)
          .showSnackBar(const SnackBar(content: Text('请输入正确的手机号')));
      return;
    }
    final api = ApiClient();
    try {
      final devCode = await api.sendSmsCode(phone);
      if (!mounted) return;
      setState(() => _countdown = 60);
      _countdownTimer?.cancel();
      _countdownTimer = Timer.periodic(const Duration(seconds: 1), (t) {
        if (_countdown <= 1) t.cancel();
        if (mounted) setState(() => _countdown -= 1);
      });
      if (devCode != null) {
        // 开发模式:短信服务未配置,验证码自动填入
        _code.text = devCode;
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(
            content: Text('开发模式:验证码 $devCode 已自动填入')));
      } else {
        ScaffoldMessenger.of(context)
            .showSnackBar(const SnackBar(content: Text('验证码已发送')));
      }
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(e.toString())));
    }
  }

  Future<void> _login() async {
    if (!_agreed) {
      ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('请先阅读并勾选同意《用户协议》和《隐私政策》')));
      return;
    }
    setState(() => _busy = true);
    final api = ApiClient();
    try {
      await api.smsLogin(_phone.text.trim(), _code.text.trim());
      PushService.onLogin(api.userId!); // 绑定推送别名,失败静默
      if (!mounted) return;
      widget.onLoggedIn(context, api);
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(e.toString())));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 360),
          child: SingleChildScrollView(
            padding: const EdgeInsets.all(24),
            child: Column(
              mainAxisAlignment: MainAxisAlignment.center,
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                const Center(child: BrandLogo(size: 72)),
                const SizedBox(height: 12),
                Text('超级赞',
                    textAlign: TextAlign.center,
                    style: Theme.of(context).textTheme.headlineMedium?.copyWith(
                        fontWeight: FontWeight.bold,
                        color: Theme.of(context).colorScheme.primary)),
                const SizedBox(height: 4),
                Text(widget.title,
                    textAlign: TextAlign.center,
                    style: Theme.of(context).textTheme.titleMedium),
                const SizedBox(height: 32),
                TextField(
                  controller: _phone,
                  keyboardType: TextInputType.phone,
                  decoration: const InputDecoration(
                      labelText: '手机号', border: OutlineInputBorder()),
                ),
                const SizedBox(height: 12),
                Row(
                  children: [
                    Expanded(
                      child: TextField(
                        controller: _code,
                        keyboardType: TextInputType.number,
                        decoration: const InputDecoration(
                            labelText: '验证码', border: OutlineInputBorder()),
                      ),
                    ),
                    const SizedBox(width: 8),
                    SizedBox(
                      height: 56,
                      child: OutlinedButton(
                        onPressed: _countdown > 0 ? null : _sendCode,
                        child: Text(
                            _countdown > 0 ? '${_countdown}s' : '获取验证码'),
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 12),
                AgreementRow(
                    agreed: _agreed,
                    onChanged: (v) => setState(() => _agreed = v)),
                const SizedBox(height: 12),
                FilledButton(
                  onPressed: _busy ? null : _login,
                  child: Text(_busy ? '登录中…' : '登录 / 注册'),
                ),
                if (widget.passwordLoginBuilder != null)
                  TextButton(
                    onPressed: () => Navigator.of(context).pushReplacement(
                        MaterialPageRoute(
                            builder: widget.passwordLoginBuilder!)),
                    child: const Text('密码登录'),
                  ),
                const IcpFooter(),
              ],
            ),
          ),
        ),
      ),
    );
  }
}


/// ICP 备案号(工信部要求 App 内展示)。构建时注入:
/// flutter build apk --dart-define=SUPERZ_ICP=蜀ICP备XXXXXXXX号-1A
/// 未注入时不显示(开发期)。
class IcpFooter extends StatelessWidget {
  const IcpFooter({super.key});

  static const String _icp = String.fromEnvironment('SUPERZ_ICP');

  @override
  Widget build(BuildContext context) {
    if (_icp.isEmpty) return const SizedBox.shrink();
    return Padding(
      padding: const EdgeInsets.only(top: 24),
      child: Text(_icp,
          textAlign: TextAlign.center,
          style: TextStyle(
              fontSize: 11, color: Theme.of(context).colorScheme.outline)),
    );
  }
}


/// 用户协议/隐私政策勾选行(上架审核硬要求)。
class AgreementRow extends StatelessWidget {
  const AgreementRow({super.key, required this.agreed, required this.onChanged});

  final bool agreed;
  final ValueChanged<bool> onChanged;

  @override
  Widget build(BuildContext context) {
    final primary = Theme.of(context).colorScheme.primary;
    // 整行可点切换勾选(大 tap target),协议名单独可点查看全文
    return InkWell(
      onTap: () => onChanged(!agreed),
      borderRadius: BorderRadius.circular(8),
      child: Padding(
        padding: const EdgeInsets.symmetric(vertical: 4),
        child: Row(
          children: [
            IgnorePointer(
              child: Checkbox(
                value: agreed,
                onChanged: (_) {},
                visualDensity: VisualDensity.compact,
              ),
            ),
            Expanded(
              child: Wrap(
                crossAxisAlignment: WrapCrossAlignment.center,
                children: [
                  const Text('已阅读并同意', style: TextStyle(fontSize: 12)),
                  GestureDetector(
                    onTap: () => LegalPage.showTerms(context),
                    child: Text('《用户协议》',
                        style: TextStyle(fontSize: 12, color: primary)),
                  ),
                  const Text('和', style: TextStyle(fontSize: 12)),
                  GestureDetector(
                    onTap: () => LegalPage.showPrivacy(context),
                    child: Text('《隐私政策》',
                        style: TextStyle(fontSize: 12, color: primary)),
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}
