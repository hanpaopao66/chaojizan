import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';

/// 子账号(店员)管理面板。
///
/// 从 `shop_tab.dart` 里搬出来的:它是一段自成一体的交互流程,
/// 只要 `api` 和一个 context,不碰店铺 Tab 的任何状态。
/// 留在那个 2100 行的 State 里,只是让所有人多滚 120 行。
///
/// 权限边界写在面板上,不写在这段注释里 —— 店主要在点之前就看见。
Future<void> showStaffSheet(BuildContext context, ApiClient api) async {
  List<Map<String, dynamic>> staff;
  try {
    staff = await api.myStaff();
  } catch (e) {
    // **不能吞**:拉不到就照原样开面板的话,店主看到的是一份空名单,
    // 会以为店员已经清光了 —— 而实际上那些账号还能听单、还能改菜单
    if (!context.mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(
        content: Text('店员名单没拉到:${e is ApiException ? e.message : e}')));
    return;
  }
  if (!context.mounted) return;

  await showModalBottomSheet(
    context: context,
    isScrollControlled: true,
    builder: (context) => StatefulBuilder(
      builder: (context, setSheet) => SafeArea(
        child: Padding(
          padding: EdgeInsets.only(
              left: 16,
              right: 16,
              top: 16,
              bottom: MediaQuery.of(context).viewInsets.bottom + 16),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text('子账号(店员)',
                  style: Theme.of(context).textTheme.titleMedium),
              Text('店员能接单/出餐/估清,不能提现/改价/改设置。',
                  style: TextStyle(
                      fontSize: 12, color: Theme.of(context).sz.inkMuted)),
              const SizedBox(height: 8),
              if (staff.isEmpty)
                const Padding(
                  padding: EdgeInsets.symmetric(vertical: 8),
                  child: Text('还没有店员'),
                ),
              for (final s in staff)
                ListTile(
                  dense: true,
                  contentPadding: EdgeInsets.zero,
                  title: Text(s['name'] as String? ?? ''),
                  subtitle: Text(s['phone'] as String? ?? ''),
                  trailing: IconButton(
                    tooltip: '移除店员',
                    // 读屏只念"按钮"的话,店主不知道移的是谁 ——
                    // 移错人 = 那个人当场听不到单
                    icon: Semantics(
                      label: '移除店员 ${s['name'] ?? ''}',
                      child: const Icon(Icons.person_remove_outlined),
                    ),
                    onPressed: () async {
                      final messenger = ScaffoldMessenger.of(context);
                      try {
                        await api.removeStaff(s['user_id'] as int);
                        staff = await api.myStaff();
                        setSheet(() {});
                      } catch (e) {
                        messenger.showSnackBar(
                            SnackBar(content: Text(e.toString())));
                      }
                    },
                  ),
                ),
              const Divider(),
              FilledButton.icon(
                icon: const Icon(Icons.person_add_alt),
                label: const Text('添加店员'),
                onPressed: () async {
                  final added = await _addStaffDialog(context, api);
                  if (added == true) {
                    staff = await api.myStaff();
                    setSheet(() {});
                  }
                },
              ),
            ],
          ),
        ),
      ),
    ),
  );
}

Future<bool?> _addStaffDialog(BuildContext context, ApiClient api) async {
  final phone = TextEditingController();
  final name = TextEditingController();
  try {
    return await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('添加店员'),
        content: Column(mainAxisSize: MainAxisSize.min, children: [
          TextField(
              controller: phone,
              keyboardType: TextInputType.phone,
              decoration: const InputDecoration(
                  labelText: '手机号', helperText: '对方需先下载 App 登录一次')),
          TextField(
              controller: name,
              decoration: const InputDecoration(labelText: '备注名(如:小王)')),
        ]),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(context, false),
              child: const Text('取消')),
          FilledButton(
            onPressed: () async {
              final messenger = ScaffoldMessenger.of(context);
              final nav = Navigator.of(context);
              try {
                await api.addStaff(phone.text.trim(), name.text.trim());
                nav.pop(true);
              } catch (e) {
                messenger.showSnackBar(SnackBar(content: Text(e.toString())));
              }
            },
            child: const Text('添加'),
          ),
        ],
      ),
    );
  } finally {
    // 原来这两个 controller 没人 dispose,每开一次对话框漏一对
    phone.dispose();
    name.dispose();
  }
}
