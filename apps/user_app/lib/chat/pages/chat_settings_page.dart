import 'dart:async';

import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';

import '../models.dart';
import '../store.dart';
import '../ui/avatar.dart';
import 'export_page.dart';
import 'my_card_page.dart';
import 'sanctions_page.dart';
import 'folders_page.dart';
import 'tags_badges_page.dart';
import 'user_profile_page.dart';

/// 「消息」的设置:我的资料(超级赞号、签名、名片)、隐私、通知、拉黑名单、会话分组、本地缓存。
class ChatSettingsPage extends StatefulWidget {
  const ChatSettingsPage({super.key});

  @override
  State<ChatSettingsPage> createState() => _ChatSettingsPageState();
}

const privacyLabels = {
  'last_seen': '最后上线时间',
  'avatar': '头像',
  'phone_search': '按手机号找到我',
  'group_invite': '直接拉我进群',
  'calls': '给我打电话',
  'forwards': '转发时附带我的链接',
};

const privacyValueLabels = {'everyone': '所有人', 'contacts': '我的联系人', 'nobody': '没有人'};

class _ChatSettingsPageState extends State<ChatSettingsPage> {
  Map<String, dynamic>? _me;
  Object? _error;

  ChatStore get _store => ChatStore.instance;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final m = await _store.api.me();
      if (mounted) setState(() => _me = m);
    } catch (e) {
      if (mounted) setState(() => _error = e);
    }
  }

  Future<void> _patch(Map<String, dynamic> body) async {
    try {
      final m = await _store.api.patchMe(body);
      if (mounted) setState(() => _me = m);
    } on ApiException catch (e) {
      _toast(e.message);
    }
  }

  void _toast(String s) {
    if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(s)));
  }

  Future<void> _editBio() async {
    final c = TextEditingController(text: '${_me?['bio'] ?? ''}');
    final r = await showDialog<String>(
      context: context,
      builder: (ctx) => SzDisposeWith(
        controllers: [c],
        child: SzDialog(
          title: const Text('签名'),
          content: TextField(
            controller: c,
            autofocus: true,
            maxLength: 140,
            maxLines: 3,
            decoration: const InputDecoration(hintText: '一句话介绍自己,资料页上所有人都看得到'),
          ),
          actions: [
            TextButton(onPressed: () => Navigator.pop(ctx), child: const Text('取消')),
            FilledButton(onPressed: () => Navigator.pop(ctx, c.text), child: const Text('保存')),
          ],
        ),
      ),
    );
    if (r != null) await _patch({'bio': r.trim()});
  }

  Future<void> _pickPrivacy(String key) async {
    final cur = '${(_me?['privacy'] as Map?)?[key] ?? 'everyone'}';
    final r = await szShowSheet<String>(
      context: context,
      builder: (ctx) => SafeArea(
        child: RadioGroup<String>(
          groupValue: cur,
          onChanged: (v) => Navigator.pop(ctx, v),
          child: Column(mainAxisSize: MainAxisSize.min, children: [
            ListTile(title: Text('谁可以看到「${privacyLabels[key]}」', style: const TextStyle(fontWeight: FontWeight.w600))),
            for (final e in privacyValueLabels.entries)
              RadioListTile<String>(value: e.key, title: Text(e.value)),
            Padding(
              padding: const EdgeInsets.fromLTRB(kPagePad, 0, kPagePad, 12),
              child: Text(_privacyNote(key), style: TextStyle(fontSize: kFontNote, color: Theme.of(ctx).sz.inkMuted)),
            ),
          ]),
        ),
      ),
    );
    if (r != null && r != cur) await _patch({'privacy': {key: r}});
  }

  static String _privacyNote(String key) => switch (key) {
        'last_seen' => '看不到你的人,也看不到你「在线」;你同样看不到他们的(对等)。',
        'phone_search' => '只能用完整手机号精确找,找到了也不会显示你的号码。',
        'group_invite' => '不允许的人拉你进群时,会改成发一个邀请链接给你,进不进你说了算。',
        'calls' => '不允许的人打给你,对方看到的是「对方忙线」。',
        'forwards' => '关掉之后,别人转发你的消息只显示你的名字,点不进你的资料。',
        'avatar' => '看不到的人只看到你名字的首字。',
        _ => '',
      };

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    final me = _me;
    if (me == null) {
      return SzPageScaffold(
        appBar: AppBar(title: const Text('消息设置')),
        body: _error != null ? SzError(error: _error, onRetry: _load) : const Center(child: CircularProgressIndicator()),
      );
    }
    final privacy = (me['privacy'] as Map? ?? const {}).cast<String, dynamic>();
    final notify = (me['notify'] as Map? ?? const {}).cast<String, dynamic>();
    final username = me['username'] as String?;
    final nextChange = DateTime.tryParse('${me['username_next_change_at'] ?? ''}');
    final bio = '${me['bio'] ?? ''}';
    return SzPageScaffold(
      appBar: AppBar(title: const Text('消息设置')),
      body: ListView(padding: const EdgeInsets.symmetric(vertical: 8), children: [
        ListTile(
          leading: ChatAvatar(name: '${me['name'] ?? ''}', url: '${me['avatar'] ?? ''}', size: 56),
          title: Text('${me['name'] ?? ''}', style: const TextStyle(fontWeight: FontWeight.w600)),
          subtitle: Text(username != null ? '超级赞号:@$username' : '还没有超级赞号', style: TextStyle(color: sz.inkMuted)),
          onTap: () => openUserProfile(context, (me['id'] as num).toInt()),
        ),
        SzEntryGroup(title: '我的资料', children: [
          SzEntryTile(
            title: '超级赞号',
            icon: Icons.alternate_email,
            value: username != null ? '@$username' : null,
            hint: '相当于微信号,别人输入它就能找到你',
            onTap: () async {
              final r = await Navigator.of(context).push<Map<String, dynamic>>(MaterialPageRoute(
                  builder: (_) => UsernamePage(current: username, nextChangeAt: nextChange)));
              if (r != null && mounted) setState(() => _me = r);
            },
          ),
          SzEntryTile(
            title: '签名',
            icon: Icons.short_text,
            value: bio.isEmpty ? null : (bio.length > 12 ? '${bio.substring(0, 12)}…' : bio),
            hint: '一句话介绍自己',
            onTap: _editBio,
          ),
          SzEntryTile(
            title: '标签和勋章',
            icon: Icons.sell_outlined,
            hint: '资料页上别人看得到,每一项都能隐藏',
            onTap: () => Navigator.of(context).push(MaterialPageRoute<void>(builder: (_) => const TagsBadgesPage())),
          ),
          SzEntryTile(
            title: '我的名片',
            icon: Icons.qr_code_2,
            hint: '二维码和链接,发给别人加你',
            onTap: () => Navigator.of(context).push(MaterialPageRoute<void>(builder: (_) => const MyCardPage())),
          ),
        ]),
        SzEntryGroup(
          title: '隐私',
          footnote: '消息存在平台的服务器上(没有端到端加密)。平台只在处理举报时查看被举报的那几条,'
              '每次查看都留记录,次数在透明中心按月公示。',
          children: [
            for (final k in privacyLabels.keys) ...[
              SzEntryTile(
                title: privacyLabels[k]!,
                value: privacyValueLabels['${privacy[k] ?? 'everyone'}'],
                dense: true,
                onTap: () => _pickPrivacy(k),
              ),
              // 按号找和按手机号找挨着放。它只有开 / 关两档(服务端不收「联系人」):
              // 能按号找到我的联系人,本来就已经在他的联系人里了
              if (k == 'phone_search')
                SzEntryTile(
                  title: '按超级赞号找到我',
                  dense: true,
                  trailing: Switch(
                    value: privacy['username_search'] != 'nobody',
                    onChanged: (v) => _patch({
                      'privacy': {'username_search': v ? 'everyone' : 'nobody'}
                    }),
                  ),
                ),
            ],
            SzEntryTile(
              title: '已拉黑的人',
              dense: true,
              onTap: () => Navigator.of(context).push(MaterialPageRoute<void>(builder: (_) => const BlockedPage())),
            ),
          ],
        ),
        SzEntryGroup(title: '通知', children: [
          SzEntryTile(
            title: '通知里显示内容',
            dense: true,
            trailing: Switch(value: notify['preview'] != false, onChanged: (v) => _patch({'notify': {'preview': v}})),
          ),
          SzEntryTile(
            title: '私聊',
            dense: true,
            trailing: Switch(value: notify['private'] != false, onChanged: (v) => _patch({'notify': {'private': v}})),
          ),
          SzEntryTile(
            title: '群组',
            dense: true,
            trailing: Switch(value: notify['group'] != false, onChanged: (v) => _patch({'notify': {'group': v}})),
          ),
          SzEntryTile(
            title: '频道',
            dense: true,
            trailing: Switch(value: notify['channel'] != false, onChanged: (v) => _patch({'notify': {'channel': v}})),
          ),
        ]),
        SzEntryGroup(title: '聊天', children: [
          SzEntryTile(
            title: '会话分组',
            icon: Icons.folder_outlined,
            value: _store.folders.isEmpty ? null : '${_store.folders.length} 个',
            hint: '按私聊、群、频道分开看',
            onTap: () => Navigator.of(context).push(MaterialPageRoute<void>(builder: (_) => const FoldersPage())),
          ),
          SzEntryTile(
            title: '处罚与申诉',
            icon: Icons.gavel_outlined,
            hint: '平台对你的处罚、原因和申诉进度',
            onTap: () => Navigator.of(context).push(MaterialPageRoute<void>(builder: (_) => const SanctionsPage())),
          ),
          SzEntryTile(
            title: '导出我的数据',
            icon: Icons.download_outlined,
            hint: '聊天记录(含图片文件)和投稿,打包成一个压缩包',
            onTap: () => Navigator.of(context).push(MaterialPageRoute<void>(builder: (_) => const ExportPage())),
          ),
          SzEntryTile(
            title: '清除本机的聊天缓存',
            icon: Icons.cleaning_services_outlined,
            hint: '只清这台设备上存的会话列表,聊天记录还在服务器上',
            onTap: () async {
              await ChatStore.clearCacheFor(_store.meId);
              await _store.refresh();
              _toast('已清除');
            },
          ),
        ]),
      ]),
    );
  }
}

/// 超级赞号的规则说明。**照服务端写的**(services/social.py 的 validate_username 和改名规则),
/// 那边改了这里要一起改 —— server/tests/unit/test_custom_id.py 对着查位数和天数。
const usernameRulesText = '超级赞号相当于微信号:别人输入它就能找到你、加你为联系人,不用知道你的手机号。\n'
    '· 5–32 位,以英文字母开头,只能用英文字母、数字和下划线;下划线不能放在最后,也不能两个连着\n'
    '· 不区分大小写;不能以 bot 结尾(留给机器人);带 admin、kefu、official、chaojizan 这类字样的,'
    '和 support、help 这类保留词不能用\n'
    '· 第一次设置随时能设;之后一年只能改一次,从上次设置或修改那天算,满 365 天才能再改;只改大小写不算\n'
    '· 改掉或清空的旧号冷冻 180 天,这期间别人不能注册;你自己想用回来也算一次修改\n'
    '· 不想被人按号找到:消息设置 → 隐私 →「按超级赞号找到我」';

/// 按北京时间写日期。服务端的「下次可修改」按北京时间的日期算(那天零点起能改),拒绝时的提示也写北京日期;
/// 手机时区不是北京的话按本地时间写,会差出一天,和服务端那句话对不上
String _ymd(DateTime t) {
  final b = t.toUtc().add(const Duration(hours: 8));
  return '${b.year}-${b.month.toString().padLeft(2, '0')}-${b.day.toString().padLeft(2, '0')}';
}

/// 设置 / 修改 / 清空超级赞号,边输边检查。一年只能改一次:改不了的时候写明下次哪天能改。
class UsernamePage extends StatefulWidget {
  const UsernamePage({super.key, this.current, this.nextChangeAt});

  final String? current;

  /// 现在改不了的话,哪天能改(/social/v1/me 的 username_next_change_at);null = 现在就能设 / 改
  final DateTime? nextChangeAt;

  @override
  State<UsernamePage> createState() => _UsernamePageState();
}

class _UsernamePageState extends State<UsernamePage> {
  late final _c = TextEditingController(text: widget.current ?? '');
  Timer? _t;
  String _reason = '';
  bool _ok = false;
  bool _checking = false;
  bool _saving = false;

  /// 一年一次的名额还没到(只改大小写不受这个限制)
  bool get _locked => widget.nextChangeAt != null && DateTime.now().isBefore(widget.nextChangeAt!);

  bool _sameIgnoringCase(String name) =>
      widget.current != null && name.toLowerCase() == widget.current!.toLowerCase();

  @override
  void initState() {
    super.initState();
    if ((widget.current ?? '').isNotEmpty) _ok = true;
  }

  @override
  void dispose() {
    _t?.cancel();
    _c.dispose();
    super.dispose();
  }

  void _onChanged(String v) {
    _t?.cancel();
    final name = v.trim().replaceFirst('@', '');
    if (name.isEmpty || name == widget.current) {
      setState(() {
        _reason = '';
        _ok = name.isNotEmpty;
        _checking = false;
      });
      return;
    }
    if (_sameIgnoringCase(name)) {
      // 只改大小写:号还是这个号,不算修改,不用问服务端占没占
      setState(() {
        _reason = '只改大小写,不算修改';
        _ok = true;
        _checking = false;
      });
      return;
    }
    if (_locked) {
      setState(() {
        _reason = '一年只能改一次,下次可修改:${_ymd(widget.nextChangeAt!)}';
        _ok = false;
        _checking = false;
      });
      return;
    }
    setState(() => _checking = true);
    _t = Timer(const Duration(milliseconds: 350), () async {
      try {
        final r = await ChatStore.instance.api.checkUsername(name);
        if (!mounted || _c.text.trim().replaceFirst('@', '') != name) return;
        setState(() {
          _ok = r.ok;
          _reason = r.ok ? '可以用' : r.reason;
          _checking = false;
        });
      } catch (_) {
        if (mounted) setState(() => _checking = false);
      }
    });
  }

  /// 改号、清空号都不能随手撤回(一年一次、旧号冷冻),先把后果说清楚再动
  Future<bool> _confirm({required String title, required String body, required String ok}) async {
    final r = await showDialog<bool>(
      context: context,
      builder: (ctx) => SzDialog(
        title: Text(title),
        content: Text(body, style: const TextStyle(height: 1.6)),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('取消')),
          FilledButton(onPressed: () => Navigator.pop(ctx, true), child: Text(ok)),
        ],
      ),
    );
    return r == true;
  }

  Future<void> _save({bool clear = false}) async {
    final name = clear ? '' : _c.text.trim().replaceFirst('@', '');
    final current = widget.current;
    if (clear && current != null) {
      final go = await _confirm(
        title: '不用超级赞号了?',
        body: '清空之后,别人输入 @$current 找不到你,你的名片码改用一串随机编号。\n'
            '@$current 会冷冻 180 天,这期间别人不能注册它。\n'
            '${_locked ? '再设超级赞号算一次修改,要等到 ${_ymd(widget.nextChangeAt!)}。' : '以后再设超级赞号算一次修改,设好后 365 天内不能再改。'}',
        ok: '清空',
      );
      if (!go) return;
    } else if (!clear && !_sameIgnoringCase(name)) {
      final go = await _confirm(
        title: '用 @$name 作超级赞号?',
        body: [
          '保存后 365 天内不能再改(只改大小写不算)。',
          if (current != null) '原来的 @$current 会冷冻 180 天,这期间别人不能注册它。',
        ].join('\n'),
        ok: '保存',
      );
      if (!go) return;
    }
    if (!mounted) return;
    setState(() => _saving = true);
    try {
      final me = await ChatStore.instance.api.setUsername(name);
      ChatStore.instance.myUsername = me['username'] as String?;
      if (mounted) Navigator.pop(context, me);
    } on ApiException catch (e) {
      if (mounted) {
        setState(() {
          _reason = e.message;
          _ok = false;
        });
      }
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    final name = _c.text.trim().replaceFirst('@', '');
    final canSave = !_saving && !_checking && name.isNotEmpty && _ok && name != widget.current;
    return SzPageScaffold(
      appBar: AppBar(
        title: const Text('超级赞号'),
        actions: [TextButton(onPressed: canSave ? _save : null, child: const Text('保存'))],
      ),
      body: ListView(padding: const EdgeInsets.all(kPagePad), children: [
        TextField(
          controller: _c,
          autofocus: !_locked,
          maxLength: 32,
          onChanged: _onChanged,
          decoration: InputDecoration(
            prefixText: '@',
            labelText: '超级赞号',
            suffixIcon: _checking
                ? const Padding(padding: EdgeInsets.all(14), child: SizedBox(width: 16, height: 16, child: CircularProgressIndicator(strokeWidth: 2)))
                : null,
          ),
        ),
        if (_reason.isNotEmpty)
          Text(_reason, style: TextStyle(fontSize: kFontNote, color: _ok ? sz.clay : sz.danger)),
        // 改不了的时候一进来就说清楚,不用等人输了再被拒
        if (_locked && _reason.isEmpty)
          Text('下次可修改:${_ymd(widget.nextChangeAt!)}', style: TextStyle(fontSize: kFontNote, color: sz.inkMuted)),
        const SizedBox(height: 12),
        Text(usernameRulesText, style: TextStyle(fontSize: kFontNote, color: sz.inkMuted, height: 1.6)),
        if ((widget.current ?? '').isNotEmpty) ...[
          const SizedBox(height: 28),
          OutlinedButton(
            onPressed: _saving ? null : () => _save(clear: true),
            child: const Text('不用超级赞号了'),
          ),
        ],
      ]),
    );
  }
}

/// 我拉黑的人。
class BlockedPage extends StatefulWidget {
  const BlockedPage({super.key});

  @override
  State<BlockedPage> createState() => _BlockedPageState();
}

class _BlockedPageState extends State<BlockedPage> {
  List<ChatUser>? _items;
  Object? _error;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final r = await ChatStore.instance.api.blocks();
      if (mounted) setState(() => _items = r);
    } catch (e) {
      if (mounted) setState(() => _error = e);
    }
  }

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    final items = _items;
    return SzPageScaffold(
      appBar: AppBar(title: const Text('已拉黑的人')),
      body: items == null
          ? (_error != null ? SzError(error: _error, onRetry: _load) : const Center(child: CircularProgressIndicator()))
          : items.isEmpty
              ? const Center(child: SzEmpty(text: '没有拉黑任何人\n在对方的资料页可以拉黑'))
              : ListView(children: [
                  Padding(
                    padding: const EdgeInsets.all(kPagePad),
                    child: Text('被拉黑的人不能给你发私信、不能拉你进群、看不到你的在线状态和头像更新,'
                        '也不能评论你的视频;他发的评论和弹幕你看不到。',
                        style: TextStyle(fontSize: kFontNote, color: sz.inkMuted)),
                  ),
                  for (final u in items)
                    ListTile(
                      leading: ChatAvatar(name: u.displayName, url: u.avatar, size: 44),
                      title: Text(u.displayName),
                      subtitle: u.username != null ? Text('@${u.username}') : null,
                      onTap: () => openUserProfile(context, u.id),
                      trailing: TextButton(
                        onPressed: () async {
                          try {
                            await ChatStore.instance.api.unblock(u.id);
                            await _load();
                          } on ApiException catch (e) {
                            if (context.mounted) {
                              ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(e.message)));
                            }
                          }
                        },
                        child: const Text('解除'),
                      ),
                    ),
                ]),
    );
  }
}
