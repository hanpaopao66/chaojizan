import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import 'api_client.dart';
import 'models.dart';
import 'push_service.dart';
import 'ui_bits.dart';

/// 联系平台客服:三端共用的工单页。
///
/// 提交问题 → 平台管理后台回复 → 这里能看到全部往来记录。
/// 售后被驳回、发票、认证疑问等所有「找平台」的入口最终都落到这。
class SupportPage extends StatefulWidget {
  const SupportPage({super.key, required this.api, this.prefill = ''});

  final ApiClient api;

  /// 从售后驳回等场景跳进来时预填的内容
  final String prefill;

  @override
  State<SupportPage> createState() => _SupportPageState();
}

class _SupportPageState extends State<SupportPage> {
  List<Ticket>? _tickets;
  String? _error;

  @override
  void initState() {
    super.initState();
    _load();
    if (widget.prefill.isNotEmpty) {
      WidgetsBinding.instance.addPostFrameCallback((_) => _openSubmitSheet());
    }
  }

  Future<void> _load() async {
    try {
      final list = await widget.api.myTickets();
      if (mounted) setState(() => _tickets = list);
    } catch (e) {
      if (mounted) setState(() => _error = '$e');
    }
  }

  /// 提工单前先自助分流:展示 FAQ,能自助的直接看答案,仍有问题再转人工工单
  Future<void> _openHelp() async {
    List<Map<String, dynamic>> faq = [];
    try {
      faq = await widget.api.supportFaq();
    } catch (_) {}
    if (!mounted) return;
    await showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      builder: (sheetCtx) => DraggableScrollableSheet(
        expand: false,
        initialChildSize: 0.7,
        maxChildSize: 0.9,
        builder: (sheetCtx, scroll) => ListView(
          controller: scroll,
          padding: const EdgeInsets.all(16),
          children: [
            Text('常见问题',
                style: Theme.of(sheetCtx).textTheme.titleMedium,
                textAlign: TextAlign.center),
            const SizedBox(height: 4),
            const Text('大部分问题这里能直接解决,省去等待人工',
                textAlign: TextAlign.center,
                style: TextStyle(fontSize: 12, color: Colors.grey)),
            const SizedBox(height: 12),
            for (final f in faq)
              ExpansionTile(
                tilePadding: EdgeInsets.zero,
                title: Text(f['q'] as String? ?? '',
                    style: const TextStyle(fontSize: 14)),
                children: [
                  Padding(
                    padding: const EdgeInsets.only(bottom: 12),
                    child: Text(f['a'] as String? ?? '',
                        style: const TextStyle(color: Colors.black87)),
                  ),
                ],
              ),
            const SizedBox(height: 16),
            OutlinedButton.icon(
              icon: const Icon(Icons.edit_outlined),
              label: const Text('问题没解决,联系人工客服'),
              onPressed: () {
                Navigator.pop(sheetCtx);
                _openSubmitSheet();
              },
            ),
          ],
        ),
      ),
    );
  }

  Future<void> _openSubmitSheet() async {
    final contentCtrl = TextEditingController(text: widget.prefill);
    final contactCtrl = TextEditingController();
    final submitted = await showModalBottomSheet<bool>(
      context: context,
      isScrollControlled: true,
      builder: (sheetCtx) => Padding(
        padding: EdgeInsets.only(
          left: 16,
          right: 16,
          top: 16,
          bottom: MediaQuery.of(sheetCtx).viewInsets.bottom + 16,
        ),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text('提交工单',
                style: Theme.of(sheetCtx).textTheme.titleMedium,
                textAlign: TextAlign.center),
            const SizedBox(height: 12),
            TextField(
              controller: contentCtrl,
              maxLines: 4,
              maxLength: 500,
              autofocus: true,
              decoration: const InputDecoration(
                hintText: '请描述你遇到的问题(至少 4 个字)',
                border: OutlineInputBorder(),
              ),
            ),
            const SizedBox(height: 8),
            TextField(
              controller: contactCtrl,
              maxLength: 50,
              decoration: const InputDecoration(
                hintText: '联系方式(选填,默认用注册手机号)',
                border: OutlineInputBorder(),
                counterText: '',
              ),
            ),
            const SizedBox(height: 12),
            FilledButton(
              onPressed: () => Navigator.pop(sheetCtx, true),
              child: const Text('提交'),
            ),
          ],
        ),
      ),
    );
    if (submitted != true || !mounted) return;
    final content = contentCtrl.text.trim();
    if (content.length < 4) {
      ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('问题描述至少 4 个字')));
      return;
    }
    try {
      await widget.api
          .submitTicket(content, contact: contactCtrl.text.trim());
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('已提交,平台会尽快回复')));
      _load();
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('$e')));
    }
  }

  /// 注销账号(上架硬性要求):双重确认 → 服务端软删除 → 退出应用。
  Future<void> _deleteAccount() async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('注销账号'),
        content: const Text('注销后手机号解绑、资料匿名化,无法恢复;'
            '交易记录按法律要求保留。\n\n'
            '有进行中的订单、店铺或未提现余额时无法注销,请先处理。'),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(context, false),
              child: const Text('再想想')),
          TextButton(
            onPressed: () => Navigator.pop(context, true),
            child: Text('确认注销',
                style: TextStyle(color: Theme.of(context).colorScheme.error)),
          ),
        ],
      ),
    );
    if (confirmed != true || !mounted) return;
    try {
      await PushService.onLogout();
      await widget.api.deleteAccount();
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('$e')));
      return;
    }
    if (!mounted) return;
    await showDialog<void>(
      context: context,
      barrierDismissible: false,
      builder: (context) => AlertDialog(
        title: const Text('已注销'),
        content: const Text('感谢使用超级赞,应用即将关闭。'),
        actions: [
          FilledButton(
              onPressed: () => Navigator.pop(context),
              child: const Text('好的')),
        ],
      ),
    );
    SystemNavigator.pop();
  }

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return Scaffold(
      appBar: AppBar(
        title: const Text('联系平台客服'),
        actions: [
          // 注销入口按商店审核要求必须可达;放工单页菜单里,避免误触
          PopupMenuButton<String>(
            onSelected: (v) {
              if (v == 'delete') _deleteAccount();
            },
            itemBuilder: (context) => [
              PopupMenuItem(
                value: 'delete',
                child: Text('注销账号',
                    style: TextStyle(color: scheme.error)),
              ),
            ],
          ),
        ],
      ),
      floatingActionButton: FloatingActionButton.extended(
        // 先自助分流(FAQ),没解决再转人工——减少人工工单
        onPressed: _openHelp,
        icon: const Icon(Icons.help_outline),
        label: const Text('我要咨询'),
      ),
      body: _error != null
          ? EmptyState(
              icon: Icons.cloud_off,
              text: _error!,
              actionLabel: '重试',
              onAction: () {
                setState(() => _error = null);
                _load();
              })
          : _tickets == null
              ? const SkeletonList(itemCount: 4)
              : _tickets!.isEmpty
                  ? const EmptyState(
                      icon: Icons.support_agent,
                      text: '有任何问题都可以找平台\n我们承诺账目透明、有问必答')
                  : RefreshIndicator(
                      onRefresh: _load,
                      child: ListView.separated(
                        padding: const EdgeInsets.fromLTRB(16, 12, 16, 88),
                        itemCount: _tickets!.length,
                        separatorBuilder: (_, __) => const SizedBox(height: 10),
                        itemBuilder: (context, i) =>
                            _TicketCard(ticket: _tickets![i], scheme: scheme),
                      ),
                    ),
    );
  }
}

class _TicketCard extends StatelessWidget {
  const _TicketCard({required this.ticket, required this.scheme});

  final Ticket ticket;
  final ColorScheme scheme;

  Color get _statusColor => switch (ticket.status) {
        'open' => Colors.orange,
        'replied' => Colors.green,
        _ => scheme.outline,
      };

  String _fmt(String iso) {
    final t = DateTime.tryParse(iso)?.toLocal();
    if (t == null) return '';
    two(int n) => n.toString().padLeft(2, '0');
    return '${t.month}-${two(t.day)} ${two(t.hour)}:${two(t.minute)}';
  }

  @override
  Widget build(BuildContext context) {
    return Card(
      margin: EdgeInsets.zero,
      child: Padding(
        padding: const EdgeInsets.all(14),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Container(
                  padding:
                      const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                  decoration: BoxDecoration(
                    color: _statusColor.withValues(alpha: 0.12),
                    borderRadius: BorderRadius.circular(6),
                  ),
                  child: Text(ticket.statusLabel,
                      style: TextStyle(fontSize: 12, color: _statusColor)),
                ),
                const Spacer(),
                Text(_fmt(ticket.createdAt),
                    style: TextStyle(fontSize: 12, color: scheme.outline)),
              ],
            ),
            const SizedBox(height: 10),
            Text(ticket.content),
            if (ticket.reply.isNotEmpty) ...[
              const SizedBox(height: 10),
              Container(
                width: double.infinity,
                padding: const EdgeInsets.all(10),
                decoration: BoxDecoration(
                  color: scheme.surfaceContainerHighest,
                  borderRadius: BorderRadius.circular(8),
                ),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text('平台回复',
                        style: TextStyle(
                            fontSize: 12,
                            fontWeight: FontWeight.w600,
                            color: scheme.primary)),
                    const SizedBox(height: 4),
                    Text(ticket.reply),
                    if (ticket.repliedAt != null) ...[
                      const SizedBox(height: 4),
                      Text(_fmt(ticket.repliedAt!),
                          style: TextStyle(
                              fontSize: 11, color: scheme.outline)),
                    ],
                  ],
                ),
              ),
            ],
          ],
        ),
      ),
    );
  }
}
