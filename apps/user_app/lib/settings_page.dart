import 'package:flutter/material.dart';
import 'package:package_info_plus/package_info_plus.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:superz_shared/superz_shared.dart';
import 'package:url_launcher/url_launcher.dart';

/// 设置页:通知开关(本地记忆)/清除缓存/检查更新/关于我们。
class SettingsPage extends StatefulWidget {
  const SettingsPage({super.key, required this.api});

  final ApiClient api;

  @override
  State<SettingsPage> createState() => _SettingsPageState();
}

class _SettingsPageState extends State<SettingsPage> {
  static const _kOrderPush = 'notify_order_push';
  bool _orderPush = true;
  bool _checking = false;

  @override
  void initState() {
    super.initState();
    SharedPreferences.getInstance().then((prefs) {
      if (mounted) {
        setState(() => _orderPush = prefs.getBool(_kOrderPush) ?? true);
      }
    });
  }

  Future<void> _setOrderPush(bool v) async {
    setState(() => _orderPush = v);
    final prefs = await SharedPreferences.getInstance();
    await prefs.setBool(_kOrderPush, v);
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(
        content: Text(v
            ? '已开启订单通知'
            : '已关闭订单通知(仍可在 App 内查看订单状态)')));
  }

  void _clearCache() {
    final images = PaintingBinding.instance.imageCache;
    final count = images.currentSize;
    images.clear();
    images.clearLiveImages();
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(
        content: Text('已清理图片缓存(${(count / 1024 / 1024).toStringAsFixed(1)} MB)')));
  }

  Future<void> _checkUpdate() async {
    setState(() => _checking = true);
    // 无新版本时 checkForUpdate 静默返回,这里补一句反馈
    await checkForUpdate(context, baseUrl: widget.api.baseUrl, app: 'user');
    if (!mounted) return;
    setState(() => _checking = false);
    ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('已是最新版本(有新版会弹窗提示)')));
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('设置')),
      body: ListView(children: [
        SwitchListTile(
          secondary: const Icon(Icons.notifications_outlined),
          title: const Text('订单状态通知'),
          subtitle: const Text('接单/配送/送达提醒;系统权限在手机设置中管理',
              style: TextStyle(fontSize: 11)),
          value: _orderPush,
          onChanged: _setOrderPush,
        ),
        const Divider(height: 1),
        ListTile(
          leading: const Icon(Icons.cleaning_services_outlined),
          title: const Text('清除缓存'),
          subtitle: const Text('清理图片缓存,不影响账号数据',
              style: TextStyle(fontSize: 11)),
          onTap: _clearCache,
        ),
        const Divider(height: 1),
        ListTile(
          leading: const Icon(Icons.system_update_outlined),
          title: const Text('检查更新'),
          trailing: _checking
              ? const SizedBox(
                  width: 16,
                  height: 16,
                  child: CircularProgressIndicator(strokeWidth: 2))
              : const Icon(Icons.chevron_right),
          onTap: _checking ? null : _checkUpdate,
        ),
        const Divider(height: 1),
        ListTile(
          leading: const Icon(Icons.description_outlined),
          title: const Text('用户协议与隐私政策'),
          trailing: const Icon(Icons.chevron_right),
          onTap: () => showLegalSheet(context),
        ),
        const Divider(height: 1),
        ListTile(
          leading: const Icon(Icons.info_outline),
          title: const Text('关于我们'),
          trailing: const Icon(Icons.chevron_right),
          onTap: () => Navigator.of(context)
              .push(MaterialPageRoute(builder: (_) => const AboutPage())),
        ),
      ]),
    );
  }
}

/// 关于我们:版本/运营主体/联系方式/备案号——商店审核会核对这里与
/// 开发者账号主体的一致性。
class AboutPage extends StatefulWidget {
  const AboutPage({super.key});

  @override
  State<AboutPage> createState() => _AboutPageState();
}

class _AboutPageState extends State<AboutPage> {
  String _version = '';

  @override
  void initState() {
    super.initState();
    PackageInfo.fromPlatform().then((info) {
      if (mounted) {
        setState(() => _version = 'v${info.version} (${info.buildNumber})');
      }
    });
  }

  Future<void> _open(Uri uri) async {
    try {
      await launchUrl(uri, mode: LaunchMode.externalApplication);
    } catch (_) {}
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Scaffold(
      appBar: AppBar(title: const Text('关于我们')),
      body: ListView(padding: const EdgeInsets.all(24), children: [
        const Center(child: BrandLogo(size: 72)),
        const SizedBox(height: 12),
        Text('超级赞',
            textAlign: TextAlign.center,
            style: theme.textTheme.headlineSmall
                ?.copyWith(fontWeight: FontWeight.bold)),
        const SizedBox(height: 4),
        Text(_version.isEmpty ? '' : _version,
            textAlign: TextAlign.center, style: theme.textTheme.bodySmall),
        const SizedBox(height: 8),
        Text(
            RemoteCopy.text('about.tagline',
                '低抽成、账目透明的本地生活服务平台\n'
                '外卖 5% 封顶 · 配送费 100% 归骑手 · 每一单资金流向可查'),
            textAlign: TextAlign.center,
            style: theme.textTheme.bodySmall?.copyWith(height: 1.6)),
        const SizedBox(height: 24),
        Card(
          child: Column(children: [
            const ListTile(
              leading: Icon(Icons.business_outlined),
              title: Text('运营主体'),
              subtitle: Text('陕西爱卡斯科技有限公司'),
            ),
            const Divider(height: 1),
            ListTile(
              leading: const Icon(Icons.phone_outlined),
              title: const Text('客服电话'),
              subtitle: const Text('15231109698'),
              onTap: () => _open(Uri.parse('tel:15231109698')),
            ),
            const Divider(height: 1),
            ListTile(
              leading: const Icon(Icons.mail_outline),
              title: const Text('客服邮箱'),
              subtitle: const Text('support@chaojizan.cc'),
              onTap: () => _open(Uri.parse('mailto:support@chaojizan.cc')),
            ),
            const Divider(height: 1),
            ListTile(
              leading: const Icon(Icons.language_outlined),
              title: const Text('官方网站'),
              subtitle: const Text('chaojizan.cc'),
              onTap: () => _open(Uri.parse('https://chaojizan.cc')),
            ),
            const Divider(height: 1),
            ListTile(
              leading: const Icon(Icons.verified_outlined),
              title: const Text('ICP 备案号'),
              subtitle: const Text('陕ICP备2025064101号-5'),
              onTap: () => _open(Uri.parse('https://beian.miit.gov.cn')),
            ),
          ]),
        ),
        const SizedBox(height: 16),
        TextButton(
            onPressed: () => showLegalSheet(context),
            child: const Text('《用户协议》与《隐私政策》')),
      ]),
    );
  }
}
