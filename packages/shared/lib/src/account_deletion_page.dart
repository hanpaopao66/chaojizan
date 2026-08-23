/// 注销账号页(三端共用)。
///
/// 应用商店硬性要求(苹果 5.1.1(v)):App 内可发起注销。
/// 流程:后果说明 → 勾选确认 → 倒计时按钮二次确认 → 调 DELETE /auth/me。
/// 服务端对在途订单/店铺资质/未提余额返回 409,中文 detail 原样展示。
library;

import 'dart:async';

import 'package:flutter/material.dart';

import 'brand.dart';

import 'api_client.dart';
import 'legal.dart';
import 'push_service.dart';
import 'responsive.dart';
import 'sz_widgets.dart';

/// 「账号与协议」区块(商家端/骑手端复用;用户端我的页自有布局,单独嵌入)。
/// 包含:用户协议与隐私政策 / 退出登录 / 注销账号 —— 应用商店审核三件套。
class AccountLegalSection extends StatelessWidget {
  const AccountLegalSection({
    super.key,
    required this.api,
    required this.onLoggedOut,
    required this.onDeleted,
  });

  final ApiClient api;

  /// 退出登录后的去向(会话已清)
  final void Function(BuildContext context) onLoggedOut;

  /// 注销成功后的去向(会话已清)
  final void Function(BuildContext context) onDeleted;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Card(
      child: Column(children: [
        ListTile(
          leading: const Icon(Icons.description_outlined),
          title: const Text('用户协议与隐私政策'),
          trailing: const Icon(Icons.chevron_right),
          onTap: () => showLegalSheet(context),
        ),
        const Divider(height: 1),
        ListTile(
          leading: const Icon(Icons.logout),
          title: const Text('退出登录'),
          onTap: () async {
            PushService.onLogout(); // 解绑推送别名,失败静默
            await api.clearSession();
            if (!context.mounted) return;
            onLoggedOut(context);
          },
        ),
        const Divider(height: 1),
        ListTile(
          leading:
              Icon(Icons.person_off_outlined, color: theme.colorScheme.error),
          title: Text('注销账号', style: TextStyle(color: theme.colorScheme.error)),
          trailing: const Icon(Icons.chevron_right),
          onTap: () => Navigator.of(context).push(MaterialPageRoute(
              builder: (_) =>
                  AccountDeletionPage(api: api, onDeleted: onDeleted))),
        ),
      ]),
    );
  }
}

/// 协议选择弹层:审核员两步内可达两份文件全文。
void showLegalSheet(BuildContext context) {
  szShowSheet<void>(
    context: context,
    builder: (sheetContext) => SafeArea(
      child: Column(mainAxisSize: MainAxisSize.min, children: [
        ListTile(
          leading: const Icon(Icons.article_outlined),
          title: Text('《用户协议》',
              style: TextStyle(color: Theme.of(context).sz.link)),
          onTap: () {
            Navigator.pop(sheetContext);
            LegalPage.showTerms(context);
          },
        ),
        ListTile(
          leading: const Icon(Icons.privacy_tip_outlined),
          title: Text('《隐私政策》',
              style: TextStyle(color: Theme.of(context).sz.link)),
          onTap: () {
            Navigator.pop(sheetContext);
            LegalPage.showPrivacy(context);
          },
        ),
      ]),
    ),
  );
}

class AccountDeletionPage extends StatefulWidget {
  const AccountDeletionPage(
      {super.key, required this.api, required this.onDeleted});

  final ApiClient api;

  /// 注销成功(会话已清)后的去向,由各端决定:
  /// 用户端回游客首页,商家/骑手端回登录页。
  final void Function(BuildContext context) onDeleted;

  @override
  State<AccountDeletionPage> createState() => _AccountDeletionPageState();
}

class _AccountDeletionPageState extends State<AccountDeletionPage> {
  bool _acknowledged = false;
  bool _busy = false;

  Future<void> _confirmAndDelete() async {
    var countdown = 5;
    Timer? timer;
    final sure = await showDialog<bool>(
      context: context,
      builder: (context) => StatefulBuilder(
        builder: (context, setDialog) {
          timer ??= Timer.periodic(const Duration(seconds: 1), (t) {
            if (countdown <= 0) {
              t.cancel();
            } else {
              setDialog(() => countdown--);
            }
          });
          return SzDialog(
            title: const Text('确认注销账号?'),
            content: const Text('注销后账号将被匿名化,无法恢复。\n此操作不可撤销,请再次确认。',
                style: TextStyle(height: 1.6)),
            actions: [
              FilledButton(
                  onPressed: () => Navigator.pop(context, false),
                  child: const Text('我再想想')),
              TextButton(
                onPressed:
                    countdown > 0 ? null : () => Navigator.pop(context, true),
                child: Text(countdown > 0 ? '确认注销($countdown)' : '确认注销'),
              ),
            ],
          );
        },
      ),
    );
    timer?.cancel();
    if (sure != true || !mounted) return;

    setState(() => _busy = true);
    try {
      await widget.api.deleteAccount();
      PushService.onLogout(); // 解绑推送别名,失败静默
      await widget.api.clearSession();
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(const SnackBar(content: Text('账号已注销,感谢你曾经的支持')));
      widget.onDeleted(context);
    } on ApiException catch (e) {
      if (!mounted) return;
      // 409:在途订单/店铺资质/未提余额,中文原因直接给用户看
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(e.message)));
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
    final theme = Theme.of(context);
    return SzPageScaffold(
      appBar: AppBar(title: const Text('注销账号')),
      body: ListView(
        padding: const EdgeInsets.all(20),
        children: [
          Icon(Icons.warning_amber_rounded,
              size: 48, color: theme.colorScheme.error),
          const SizedBox(height: 12),
          Text('注销前请确认你已了解:',
              style: theme.textTheme.titleMedium
                  ?.copyWith(fontWeight: FontWeight.bold)),
          const SizedBox(height: 12),
          const Text(
            '· 账号将被匿名化删除,无法恢复,手机号可重新注册;\n'
            // 未核销的团购券是**用户的钱**(核销前不属于商家,平台也没收
            // 服务费),所以注销时自动全额退款,不作废(#33 已拍板)。
            // 平台自己发的优惠券没有付过钱,那个才是作废
            '· 未核销的团购券会自动全额原路退款;平台发的优惠券作废;\n'
            '· 使用行为记录立即删除,实名信息一并删除;\n'
            '· 交易与账务记录按法律要求留存(不再与你的身份关联);\n'
            '· 有进行中的订单或未结清款项时无法注销,需先完结;\n'
            '· 商家账号涉及店铺资质与结算,需通过客服工单办理。',
            style: TextStyle(height: 1.9),
          ),
          const SizedBox(height: 8),
          TextButton(
            onPressed: () => LegalPage.showPrivacy(context),
            style: TextButton.styleFrom(
                foregroundColor: Theme.of(context).sz.link),
            child: const Text('查看《隐私政策》中关于注销的完整说明'),
          ),
          const SizedBox(height: 8),
          CheckboxListTile(
            value: _acknowledged,
            onChanged: (v) => setState(() => _acknowledged = v ?? false),
            title: const Text('我已了解上述后果,确认要注销账号'),
            controlAffinity: ListTileControlAffinity.leading,
          ),
          const SizedBox(height: 16),
          FilledButton(
            style: FilledButton.styleFrom(
                backgroundColor: theme.colorScheme.error),
            onPressed: _acknowledged && !_busy ? _confirmAndDelete : null,
            child: Text(_busy ? '注销中…' : '注销账号'),
          ),
          const SizedBox(height: 12),
          OutlinedButton(
            onPressed: () => Navigator.of(context).maybePop(),
            child: const Text('我再想想,继续使用'),
          ),
        ],
      ),
    );
  }
}
