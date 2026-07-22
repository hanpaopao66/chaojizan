import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import 'api_client.dart';
import 'brand.dart';
import 'legal.dart';
import 'push_service.dart';

/// 三端统一:仅验证码登录(密码登录已下线,管理后台网页除外)。
/// 配合 AuthGate:冷启动恢复会话免登录;401 静默回到登录页。

/// 登录门禁:冷启动先恢复本地会话,有效直接进主界面;无效展示验证码登录。
/// token 30 天 + 客户端自动续期,活跃用户理论上永不掉线。
class AuthGate extends StatefulWidget {
  const AuthGate({
    super.key,
    required this.api,
    required this.title,
    required this.role, // customer / merchant / rider(新号自动注册的角色)
    required this.homeBuilder,
  });

  final ApiClient api;
  final String title;
  final String role;
  final Widget Function(BuildContext context, ApiClient api) homeBuilder;

  @override
  State<AuthGate> createState() => _AuthGateState();
}

class _AuthGateState extends State<AuthGate> {
  bool? _authed; // null = 恢复中

  @override
  void initState() {
    super.initState();
    ApiClient.onUnauthorized = () {
      // token 真失效:静默回登录页(清栈,不弹报错)
      if (mounted) setState(() => _authed = false);
    };
    widget.api.restoreSession().then((ok) {
      if (mounted) setState(() => _authed = ok);
    });
  }

  @override
  Widget build(BuildContext context) {
    if (_authed == null) {
      return const Scaffold(body: Center(child: CircularProgressIndicator()));
    }
    if (_authed == true) {
      return widget.homeBuilder(context, widget.api);
    }
    return SmsLoginPage(
      title: widget.title,
      role: widget.role,
      api: widget.api,
      onLoggedIn: (_, __) => setState(() => _authed = true),
    );
  }
}

/// 验证码登录页(三端唯一登录方式)。
/// 短信服务未配置时,服务端返回开发模式验证码并自动填入。
class SmsLoginPage extends StatefulWidget {
  const SmsLoginPage({
    super.key,
    required this.title,
    required this.onLoggedIn,
    this.role = 'customer',
    this.api,
  });

  final String title;
  final String role;
  final ApiClient? api;
  final void Function(BuildContext context, ApiClient api) onLoggedIn;

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
  late final ApiClient _api = widget.api ?? ApiClient();

  @override
  void dispose() {
    _countdownTimer?.cancel();
    super.dispose();
  }

  void _toast(String msg) {
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(msg)));
  }

  Future<void> _sendCode({String ticket = '', int? slide}) async {
    final phone = _phone.text.trim();
    if (!RegExp(r'^1\d{10}$').hasMatch(phone)) {
      _toast('请输入 11 位手机号');
      return;
    }
    try {
      final devCode = await _api.sendSmsCode(phone, ticket: ticket, slide: slide);
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
        _toast('开发模式:验证码 $devCode 已自动填入');
      } else {
        _toast('验证码已发送');
      }
    } on ApiException catch (e) {
      if (!mounted) return;
      if (e.statusCode == 409 && e.message.contains('captcha_required')) {
        await _showSlider(); // 频繁发码:过滑块后自动重发
      } else {
        _toast(e.message);
      }
    } catch (e) {
      _toast(e.toString());
    }
  }

  /// 轻量滑块验证:拖到目标位置(±4)后自动重发验证码
  Future<void> _showSlider() async {
    Map<String, dynamic> challenge;
    try {
      challenge = await _api.sliderChallenge();
    } catch (e) {
      _toast(e.toString());
      return;
    }
    if (!mounted) return;
    final target = challenge['target'] as int;
    double value = 0;
    final ok = await showDialog<bool>(
      context: context,
      builder: (context) => StatefulBuilder(
        builder: (context, setDialog) => AlertDialog(
          title: const Text('安全验证'),
          content: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Text('请把滑块拖到高亮刻度处(${target}%)',
                  style: Theme.of(context).textTheme.bodySmall),
              const SizedBox(height: 8),
              // 目标刻度示意条
              LayoutBuilder(builder: (context, box) {
                return Stack(children: [
                  Container(
                      height: 6,
                      margin: const EdgeInsets.symmetric(vertical: 6),
                      decoration: BoxDecoration(
                          color: Theme.of(context)
                              .colorScheme
                              .surfaceContainerHighest,
                          borderRadius: BorderRadius.circular(3))),
                  Positioned(
                    left: box.maxWidth * target / 100 - 8,
                    child: Icon(Icons.arrow_drop_down,
                        color: Theme.of(context).colorScheme.primary),
                  ),
                ]);
              }),
              Slider(
                value: value,
                min: 0,
                max: 100,
                onChanged: (v) => setDialog(() => value = v),
              ),
              Text('当前 ${value.round()}%',
                  textAlign: TextAlign.center,
                  style: Theme.of(context).textTheme.bodySmall),
            ],
          ),
          actions: [
            TextButton(
                onPressed: () => Navigator.pop(context, false),
                child: const Text('取消')),
            FilledButton(
                onPressed: () => Navigator.pop(context, true),
                child: const Text('确认')),
          ],
        ),
      ),
    );
    if (ok == true && mounted) {
      await _sendCode(
          ticket: challenge['ticket'] as String, slide: value.round());
    }
  }

  Future<void> _login() async {
    final phone = _phone.text.trim();
    final code = _code.text.trim();
    if (!RegExp(r'^1\d{10}$').hasMatch(phone)) {
      _toast('请输入 11 位手机号');
      return;
    }
    if (!RegExp(r'^\d{6}$').hasMatch(code)) {
      _toast('请输入 6 位数字验证码');
      return;
    }
    if (!_agreed) {
      _toast('请先阅读并勾选同意《用户协议》和《隐私政策》');
      return;
    }
    setState(() => _busy = true);
    try {
      await _api.smsLogin(phone, code, role: widget.role);
      PushService.onLogin(_api.userId!); // 绑定推送别名,失败静默
      if (!mounted) return;
      widget.onLoggedIn(context, _api);
    } catch (e) {
      if (!mounted) return;
      _toast(e.toString());
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
                  maxLength: 11,
                  inputFormatters: [FilteringTextInputFormatter.digitsOnly],
                  decoration: const InputDecoration(
                      labelText: '手机号',
                      counterText: '',
                      border: OutlineInputBorder()),
                ),
                const SizedBox(height: 12),
                Row(
                  children: [
                    Expanded(
                      child: TextField(
                        controller: _code,
                        keyboardType: TextInputType.number,
                        maxLength: 6,
                        inputFormatters: [
                          FilteringTextInputFormatter.digitsOnly
                        ],
                        decoration: const InputDecoration(
                            labelText: '验证码',
                            counterText: '',
                            border: OutlineInputBorder()),
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
