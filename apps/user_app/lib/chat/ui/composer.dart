import 'dart:async';

import 'package:file_selector/file_selector.dart';
import 'package:flutter/foundation.dart' show defaultTargetPlatform;
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:image_picker/image_picker.dart';
import 'package:superz_shared/superz_shared.dart';

import '../models.dart';
import '../outbox.dart';
import '../pages/pickers.dart' show muteParam;
import '../store.dart';
import 'entity_controller.dart';
import 'format.dart';
import 'stickers.dart';
import 'voice.dart';

/// 输入栏要做的事,聊天页实现。
class ComposerActions {
  const ComposerActions({
    required this.onSendText,
    required this.onSendAttachments,
    required this.onSendVoice,
    required this.onSaveEdit,
    required this.onPickLocation,
    required this.onPickContact,
    required this.onCreatePoll,
    required this.onDice,
    required this.onSchedule,
    required this.onSendSticker,
  });

  final Future<void> Function(String text, List<MsgEntity> entities, {bool silent}) onSendText;
  final Future<void> Function(List<LocalAttachment> files, String caption, List<MsgEntity> entities)
      onSendAttachments;
  final Future<void> Function(LocalAttachment voice) onSendVoice;
  final Future<void> Function(ChatMessage m, String text, List<MsgEntity> entities) onSaveEdit;
  final Future<void> Function() onPickLocation;
  final Future<void> Function() onPickContact;
  final Future<void> Function() onCreatePoll;
  final Future<void> Function(String emoji) onDice;
  final Future<void> Function(String text, List<MsgEntity> entities) onSchedule;
  final Future<void> Function(StickerItem sticker) onSendSticker;
}

/// 聊天页底部的输入栏。
class Composer extends StatefulWidget {
  const Composer({
    super.key,
    required this.chat,
    required this.actions,
    required this.replyTo,
    required this.editing,
    required this.onCancelReply,
    required this.onCancelEdit,
    this.bots = const [],
    this.onOpenBotApp,
  });

  final ChatInfo chat;

  /// 会话里的机器人:有命令就能输入 `/` 联想、左边出「菜单」;菜单按钮是小程序就出那个按钮
  final List<BotInfo> bots;
  final void Function(BotInfo bot)? onOpenBotApp;
  final ComposerActions actions;
  final ChatMessage? replyTo;
  final ChatMessage? editing;
  final VoidCallback onCancelReply;
  final VoidCallback onCancelEdit;

  @override
  State<Composer> createState() => ComposerState();
}

class ComposerState extends State<Composer> {
  final EntityTextController _text = EntityTextController();
  final FocusNode _focus = FocusNode();
  final VoiceRecorder _rec = VoiceRecorder();
  bool _emoji = false;
  bool _recording = false;
  bool _locked = false;

  /// 手指还按在麦克风上。开始录音是异步的(要等权限、等设备),
  /// 等它准备好的时候人可能已经松手了 —— 那就别开始,不然录音停不下来
  bool _pressing = false;
  double _dragX = 0;
  double _dragY = 0;
  Timer? _draftTimer;
  String _savedDraft = '';

  /// @ 联想
  List<Map<String, dynamic>> _mentionHits = [];
  int _mentionStart = -1;

  ChatStore get _store => ChatStore.instance;

  @override
  void initState() {
    super.initState();
    final d = widget.chat.my.draft;
    if (d != null && '${d['text'] ?? ''}'.isNotEmpty) {
      _text.setWith('${d['text']}', [
        for (final e in (d['entities'] as List? ?? const [])) MsgEntity.fromJson(e),
      ]);
      _savedDraft = _text.text;
    }
    _text.addListener(_onChanged);
    _focus.onKeyEvent = _onKey;
  }

  @override
  void didUpdateWidget(Composer oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (widget.editing != null && widget.editing != oldWidget.editing) {
      _text.setWith(widget.editing!.text, widget.editing!.entities);
      _focus.requestFocus();
    } else if (widget.editing == null && oldWidget.editing != null) {
      _text.clearAll();
    }
    if (widget.replyTo != null && widget.replyTo != oldWidget.replyTo) _focus.requestFocus();
  }

  @override
  void dispose() {
    _saveDraftNow();
    _draftTimer?.cancel();
    _text.dispose();
    _focus.dispose();
    _rec.dispose();
    super.dispose();
  }

  void insert(String s) {
    final t = _text.text;
    final sel = _text.selection;
    final start = sel.isValid ? sel.start : t.length;
    final end = sel.isValid ? sel.end : t.length;
    _text.value = TextEditingValue(
      text: t.replaceRange(start, end, s),
      selection: TextSelection.collapsed(offset: start + s.length),
    );
  }

  void _backspace() {
    final t = _text.text;
    final sel = _text.selection;
    if (t.isEmpty) return;
    final end = sel.isValid ? sel.end : t.length;
    if (end == 0) return;
    // 按字素删:一个 emoji 可能是好几个码元
    final before = t.substring(0, end).characters;
    final cut = before.skipLast(1).toString().length;
    _text.value = TextEditingValue(
      text: t.replaceRange(cut, end, ''),
      selection: TextSelection.collapsed(offset: cut),
    );
  }

  void _onChanged() {
    setState(() {});
    if (_text.text.isNotEmpty && widget.editing == null) {
      _store.realtime.typing(widget.chat.id);
    }
    _detectMention();
    _detectCommand();
    if (widget.editing == null) {
      _draftTimer?.cancel();
      _draftTimer = Timer(const Duration(seconds: 2), _saveDraftNow);
    }
  }

  void _saveDraftNow() {
    if (widget.editing != null || !_store.started) return;
    final t = _text.text;
    if (t == _savedDraft) return;
    _savedDraft = t;
    final draft = t.trim().isEmpty
        ? null
        : {'text': t, 'entities': [for (final e in _text.outgoing()) e.toJson()]};
    widget.chat.my.draft = draft;
    unawaited(_store.api.patchDialog(widget.chat.id, {'draft': draft}).then((_) {}, onError: (_) {}));
  }

  // ---------------- 机器人命令 ----------------

  /// 输入 `/` 开头、还没打空格时的命令联想
  List<(BotInfo, BotCommand)> _cmdHits = [];

  List<(BotInfo, BotCommand)> get _allCommands => [
        for (final b in widget.bots)
          for (final c in b.commands) (b, c),
      ];

  void _detectCommand() {
    final t = _text.text;
    final hits = widget.editing != null || !t.startsWith('/') || t.contains(RegExp(r'\s'))
        ? const <(BotInfo, BotCommand)>[]
        : [
            for (final h in _allCommands)
              if ('/${h.$2.command}'.startsWith(t.toLowerCase().split('@').first)) h,
          ];
    if (hits.length != _cmdHits.length || !hits.every(_cmdHits.contains)) setState(() => _cmdHits = hits);
  }

  /// 点一条命令就直接发(和 Telegram 一样);群里有不止一个机器人时带上 `@机器人`,免得几个一起答
  Future<void> _sendCommand(BotInfo bot, BotCommand cmd) async {
    final many = widget.bots.length > 1 && bot.username != null;
    final text = many ? '/${cmd.command}@${bot.username}' : '/${cmd.command}';
    _text.clearAll();
    setState(() => _cmdHits = []);
    await widget.actions.onSendText(text, const []);
  }

  Future<void> _commandMenu() async {
    final all = _allCommands;
    final pick = await szShowSheet<(BotInfo, BotCommand)>(
      context: context,
      builder: (ctx) => SafeArea(
        child: ConstrainedBox(
          constraints: BoxConstraints(maxHeight: MediaQuery.sizeOf(ctx).height * .6),
          child: ListView(shrinkWrap: true, children: [
            for (final h in all)
              ListTile(
                dense: true,
                title: Text('/${h.$2.command}'),
                subtitle: Text(widget.bots.length > 1 ? '${h.$2.description} · ${h.$1.name}' : h.$2.description),
                onTap: () => Navigator.pop(ctx, h),
              ),
          ]),
        ),
      ),
    );
    if (pick != null && mounted) await _sendCommand(pick.$1, pick.$2);
  }

  /// 输入栏左边的「菜单」:机器人把菜单设成小程序就是那个按钮,否则有命令就列命令
  Widget? _menuButton(SzColors sz) {
    if (widget.editing != null) return null;
    final app = widget.bots.where((b) => b.menuType == 'web_app' && b.menuAppId.isNotEmpty).firstOrNull;
    if (app != null && widget.onOpenBotApp != null) {
      final label = app.menuText.isNotEmpty ? app.menuText : (app.menuAppName.isNotEmpty ? app.menuAppName : '打开');
      return Padding(
        padding: const EdgeInsets.only(left: 4, bottom: 6),
        child: FilledButton.tonal(
          style: FilledButton.styleFrom(visualDensity: VisualDensity.compact, padding: const EdgeInsets.symmetric(horizontal: 10)),
          onPressed: () => widget.onOpenBotApp!(app),
          child: Text(label, maxLines: 1, overflow: TextOverflow.ellipsis),
        ),
      );
    }
    if (_allCommands.isEmpty) return null;
    return IconButton(tooltip: '命令菜单', icon: Icon(Icons.menu, color: sz.clay), onPressed: _commandMenu);
  }

  // ---------------- @ 联想 ----------------

  Timer? _mentionTimer;

  void _detectMention() {
    if (widget.chat.isPrivate || widget.chat.isSaved || widget.chat.isChannel) return;
    final t = _text.text;
    final sel = _text.selection;
    if (!sel.isValid || !sel.isCollapsed) {
      if (_mentionHits.isNotEmpty) setState(() => _mentionHits = []);
      return;
    }
    final before = t.substring(0, sel.start);
    final m = RegExp(r'(^|\s)@([A-Za-z0-9_一-龥]{0,32})$').firstMatch(before);
    if (m == null) {
      if (_mentionHits.isNotEmpty) setState(() => _mentionHits = []);
      _mentionStart = -1;
      return;
    }
    _mentionStart = sel.start - m.group(2)!.length - 1;
    final q = m.group(2)!;
    _mentionTimer?.cancel();
    _mentionTimer = Timer(const Duration(milliseconds: 200), () async {
      try {
        final hits = await _store.api.members(widget.chat.id, q: q);
        if (!mounted) return;
        setState(() => _mentionHits = hits.where((x) => (x['user'] as Map?)?['id'] != _store.meId).take(6).toList());
      } catch (_) {}
    });
  }

  void _pickMention(Map<String, dynamic> row) {
    final u = (row['user'] as Map).cast<String, dynamic>();
    final t = _text.text;
    final end = _text.selection.start;
    final username = u['username'] as String?;
    final name = '${u['name'] ?? ''}';
    final insertText = username != null ? '@$username ' : '$name ';
    final start = _mentionStart;
    _text.value = TextEditingValue(
      text: t.replaceRange(start, end, insertText),
      selection: TextSelection.collapsed(offset: start + insertText.length),
    );
    if (username == null) {
      // 没有用户名的人:用 text_mention 实体指到他(和 Telegram 一样)
      _text.entities = [
        ..._text.entities,
        MsgEntity('text_mention', start, name.length, userId: (u['id'] as num).toInt()),
      ];
    }
    setState(() => _mentionHits = []);
  }

  // ---------------- 发送 ----------------

  /// 输入框里的内容变成要发出去的文字 + 实体:Markdown 记号换成格式,首尾空白去掉。
  (String, List<MsgEntity>) _outgoing() => parseMarkdown(_text.text, _text.outgoing());

  /// 桌面(含桌面浏览器)上回车发送、Shift+回车换行,和 Telegram 桌面版一样;
  /// 手机上回车就是换行(软键盘上的回车键本来就是换行的意思)
  bool get _enterSends =>
      defaultTargetPlatform == TargetPlatform.macOS ||
      defaultTargetPlatform == TargetPlatform.windows ||
      defaultTargetPlatform == TargetPlatform.linux;

  KeyEventResult _onKey(FocusNode node, KeyEvent e) {
    if (!_enterSends || e is! KeyDownEvent) return KeyEventResult.ignored;
    if (e.logicalKey != LogicalKeyboardKey.enter && e.logicalKey != LogicalKeyboardKey.numpadEnter) {
      return KeyEventResult.ignored;
    }
    // 输入法还在拼(中文拼音选词时按回车是「上屏」),不能当发送
    if (_text.value.composing.isValid && !_text.value.composing.isCollapsed) return KeyEventResult.ignored;
    if (HardwareKeyboard.instance.isShiftPressed) return KeyEventResult.ignored;
    if (_mentionHits.isNotEmpty) {
      _pickMention(_mentionHits.first);
      return KeyEventResult.handled;
    }
    unawaited(_send());
    return KeyEventResult.handled;
  }

  Future<void> _send({bool silent = false}) async {
    if (_text.text.trim().isEmpty) return;
    final (text, ents) = _outgoing();
    if (text.isEmpty) return;
    final editing = widget.editing;
    _text.clearAll();
    _savedDraft = '';
    setState(() => _mentionHits = []);
    if (editing != null) {
      await widget.actions.onSaveEdit(editing, text, ents);
      return;
    }
    // 超过 4096 字按段拆成几条(服务端单条上限)
    if (text.length <= 4096) {
      await widget.actions.onSendText(text, ents, silent: silent);
    } else {
      for (var i = 0; i < text.length; i += 4096) {
        await widget.actions.onSendText(text.substring(i, i + 4096 > text.length ? text.length : i + 4096), const [],
            silent: silent);
      }
    }
    unawaited(_store.api.patchDialog(widget.chat.id, {'draft': null}).then((_) {}, onError: (_) {}));
  }

  Future<void> _sendMenu() async {
    final text = _text.text;
    if (text.trim().isEmpty || widget.editing != null) return;
    final pick = await szShowSheet<String>(
      context: context,
      builder: (ctx) => SafeArea(
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          ListTile(
              leading: const Icon(Icons.notifications_off_outlined),
              title: const Text('静音发送'),
              subtitle: const Text('对方收到但不响铃'),
              onTap: () => Navigator.pop(ctx, 'silent')),
          ListTile(
              leading: const Icon(Icons.schedule_send_outlined),
              title: const Text('定时发送'),
              onTap: () => Navigator.pop(ctx, 'schedule')),
        ]),
      ),
    );
    if (pick == 'silent') {
      await _send(silent: true);
    } else if (pick == 'schedule') {
      final (t, ents) = _outgoing();
      await widget.actions.onSchedule(t, ents);
      _text.clearAll();
    }
  }

  // ---------------- 格式 ----------------

  Widget _contextMenu(BuildContext context, EditableTextState state) {
    final items = [...state.contextMenuButtonItems];
    if (!_text.selection.isCollapsed) {
      void fmt(String type) {
        _text.toggle(type);
        state.hideToolbar();
      }

      items.addAll([
        ContextMenuButtonItem(label: '粗体', onPressed: () => fmt('bold')),
        ContextMenuButtonItem(label: '斜体', onPressed: () => fmt('italic')),
        ContextMenuButtonItem(label: '下划线', onPressed: () => fmt('underline')),
        ContextMenuButtonItem(label: '删除线', onPressed: () => fmt('strike')),
        ContextMenuButtonItem(label: '剧透', onPressed: () => fmt('spoiler')),
        ContextMenuButtonItem(label: '代码', onPressed: () => fmt('code')),
        ContextMenuButtonItem(
            label: '链接',
            onPressed: () async {
              state.hideToolbar();
              final url = await _askUrl();
              if (url != null && url.isNotEmpty) _text.toggle('text_link', url: url);
            }),
      ]);
    }
    return AdaptiveTextSelectionToolbar.buttonItems(anchors: state.contextMenuAnchors, buttonItems: items);
  }

  Future<String?> _askUrl() async {
    final c = TextEditingController(text: 'https://');
    final r = await showDialog<String>(
      context: context,
      builder: (ctx) => SzDisposeWith(
        controllers: [c],
        child: SzDialog(
          title: const Text('添加链接'),
          content: TextField(controller: c, autofocus: true, keyboardType: TextInputType.url),
          actions: [
            TextButton(onPressed: () => Navigator.pop(ctx), child: const Text('取消')),
            FilledButton(onPressed: () => Navigator.pop(ctx, c.text.trim()), child: const Text('确定')),
          ],
        ),
      ),
    );
    if (r == null) return null;
    final ok = RegExp(r'^https?://[^\s]+\.[^\s]+').hasMatch(r);
    if (!ok && mounted) {
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('链接要以 http:// 或 https:// 开头')));
      return null;
    }
    return r;
  }

  // ---------------- 附件 ----------------

  Future<void> _attach() async {
    final can = widget.chat.can('send_media');
    final canPoll = widget.chat.can('send_polls') && !widget.chat.isPrivate;
    final pick = await szShowSheet<String>(
      context: context,
      builder: (ctx) => SafeArea(
        child: Padding(
          padding: const EdgeInsets.fromLTRB(12, 8, 12, 12),
          child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
            // 群里关了发媒体:相册、拍照、文件不出现,说一声为什么,免得以为功能坏了
            if (!can)
              Padding(
                padding: const EdgeInsets.fromLTRB(4, 0, 4, 10),
                child: Text('管理员关闭了这个群的图片、视频和文件',
                    style: TextStyle(fontSize: kFontNote, color: Theme.of(ctx).sz.inkMuted)),
              ),
            Wrap(spacing: 8, runSpacing: 8, children: [
              if (can) _AttachTile(icon: Icons.photo_library_outlined, label: '相册', onTap: () => Navigator.pop(ctx, 'gallery')),
              if (can) _AttachTile(icon: Icons.photo_camera_outlined, label: '拍照', onTap: () => Navigator.pop(ctx, 'camera')),
              if (can) _AttachTile(icon: Icons.videocam_outlined, label: '拍视频', onTap: () => Navigator.pop(ctx, 'record')),
              if (can) _AttachTile(icon: Icons.insert_drive_file_outlined, label: '文件', onTap: () => Navigator.pop(ctx, 'file')),
              _AttachTile(icon: Icons.location_on_outlined, label: '位置', onTap: () => Navigator.pop(ctx, 'location')),
              _AttachTile(icon: Icons.person_outline, label: '名片', onTap: () => Navigator.pop(ctx, 'contact')),
              if (canPoll || widget.chat.isSaved)
                _AttachTile(icon: Icons.poll_outlined, label: '投票', onTap: () => Navigator.pop(ctx, 'poll')),
              _AttachTile(icon: Icons.casino_outlined, label: '骰子', onTap: () => Navigator.pop(ctx, 'dice')),
            ]),
          ]),
        ),
      ),
    );
    if (!mounted || pick == null) return;
    switch (pick) {
      case 'gallery':
        final files = await ImagePicker().pickMultipleMedia(limit: 10);
        if (files.isNotEmpty) await _sendPicked(files);
      case 'camera':
        final f = await ImagePicker().pickImage(source: ImageSource.camera, imageQuality: 88);
        if (f != null) await _sendPicked([f]);
      case 'record':
        final f = await ImagePicker().pickVideo(source: ImageSource.camera, maxDuration: const Duration(minutes: 10));
        if (f != null) await _sendPicked([f], forceVideo: true);
      case 'file':
        // 官方 file_selector:手机上给路径、网页上给 blob 地址,都是 XFile,边读边传不整个读进内存
        final files = await openFiles();
        if (files.isNotEmpty) {
          final list = <LocalAttachment>[];
          for (final x in files) {
            list.add(LocalAttachment(file: x, kind: 'file', name: x.name, size: await x.length()));
          }
          await widget.actions.onSendAttachments(list, '', const []);
        }
      case 'location':
        await widget.actions.onPickLocation();
      case 'contact':
        await widget.actions.onPickContact();
      case 'poll':
        await widget.actions.onCreatePoll();
      case 'dice':
        final e = await szShowSheet<String>(
          context: context,
          builder: (ctx) => SafeArea(
            child: Wrap(alignment: WrapAlignment.center, children: [
              for (final d in const ['🎲', '🎯', '🏀', '⚽', '🎳', '🎰'])
                InkWell(
                  onTap: () => Navigator.pop(ctx, d),
                  child: Padding(padding: const EdgeInsets.all(14), child: Text(d, style: const TextStyle(fontSize: kFigureXl))),
                ),
            ]),
          ),
        );
        if (e != null) await widget.actions.onDice(e);
    }
  }

  Future<void> _sendPicked(List<XFile> files, {bool forceVideo = false}) async {
    final list = <LocalAttachment>[];
    for (final f in files) {
      final name = f.name;
      final lower = name.toLowerCase();
      final mime = (f.mimeType ?? '').toLowerCase();
      final isVideo = forceVideo || mime.startsWith('video/') ||
          RegExp(r'\.(mp4|mov|m4v|webm|mkv|3gp)$').hasMatch(lower);
      final isGif = mime == 'image/gif' || lower.endsWith('.gif');
      final size = await f.length();
      final kind = isVideo ? 'video' : (isGif ? 'gif' : 'photo');
      // 图片先读进来当预览(发送中的气泡立刻画出来);视频不读,太大
      final bytes = kind == 'photo' && size <= 20 * 1024 * 1024 ? await f.readAsBytes() : null;
      var w = 0, h = 0;
      if (bytes != null) {
        try {
          final img = await decodeImageFromList(bytes);
          w = img.width;
          h = img.height;
        } catch (_) {}
      }
      list.add(LocalAttachment(file: f, kind: kind, name: name, size: size, w: w, h: h, preview: bytes));
    }
    if (!mounted || list.isEmpty) return;
    // 带说明:把输入框里已经写的字当作说明发出去
    final (caption, ents) = _outgoing();
    _text.clearAll();
    await widget.actions.onSendAttachments(list, caption, ents);
  }

  // ---------------- 录音 ----------------

  Future<void> _startRecording() async {
    _pressing = true;
    if (!widget.chat.can('send_media')) {
      _toast('这里不能发语音');
      return;
    }
    HapticFeedback.mediumImpact();
    final ok = await _rec.start();
    if (!ok) {
      _toast('没有麦克风权限,到系统设置里打开');
      return;
    }
    if (!_pressing || !mounted) {
      await _rec.cancel();
      _toast('按住不放才能录音');
      return;
    }
    _store.realtime.typing(widget.chat.id, 'record_voice');
    setState(() {
      _recording = true;
      _locked = false;
      _dragX = 0;
      _dragY = 0;
    });
  }

  Future<void> _finishRecording({bool cancel = false}) async {
    if (!_recording) return;
    setState(() {
      _recording = false;
      _locked = false;
    });
    _store.realtime.typing(widget.chat.id, 'cancel');
    if (cancel) {
      await _rec.cancel();
      return;
    }
    final voice = await _rec.stop();
    if (voice == null) {
      _toast('录音太短了');
      return;
    }
    await widget.actions.onSendVoice(voice);
  }

  void _toast(String s) {
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(s), duration: const Duration(seconds: 2)));
  }

  // ---------------- 界面 ----------------

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    final c = widget.chat;
    if (!c.can('send_messages')) {
      return _Blocked(chat: c);
    }
    final hasText = _text.text.trim().isNotEmpty;
    // 系统返回键:表情面板开着先收面板,正在录音先取消录音,都没有才退出聊天(和 Telegram、微信一样)
    return PopScope(
      canPop: !_emoji && !_recording,
      onPopInvokedWithResult: (didPop, _) {
        if (didPop) return;
        if (_recording) {
          _finishRecording(cancel: true);
        } else if (_emoji) {
          setState(() => _emoji = false);
        }
      },
      child: Material(
        color: Theme.of(context).scaffoldBackgroundColor,
        child: SafeArea(
          top: false,
          child: Column(mainAxisSize: MainAxisSize.min, children: [
            if (_mentionHits.isNotEmpty) _MentionList(hits: _mentionHits, onPick: _pickMention),
            if (_cmdHits.isNotEmpty) _CommandList(hits: _cmdHits, many: widget.bots.length > 1, onPick: _sendCommand),
            if (widget.replyTo != null || widget.editing != null)
              _ContextBar(
                icon: widget.editing != null ? Icons.edit_outlined : Icons.reply,
                title: widget.editing != null ? '编辑消息' : '回复 ${_store.nameOf(widget.replyTo!.sender)}',
                text: previewOf(widget.editing ?? widget.replyTo!),
                onClose: widget.editing != null ? widget.onCancelEdit : widget.onCancelReply,
              ),
            Divider(height: 1, color: sz.line),
            // 录音和打字共用这一行,而且**按住说话的那个按钮始终是同一个元素**(ValueKey('mic')):
            // 录音一开始界面就变了,要是把按钮换掉,按住它的那个手势就跟着没了 ——
            // 松手收不到,录音停不下来(之前就是这样卡在「0:06 录音中」)
            Padding(
              padding: const EdgeInsets.fromLTRB(4, 4, 4, 4),
              child: Row(crossAxisAlignment: CrossAxisAlignment.end, children: [
                if (_recording)
                  Expanded(
                    child: _RecordingBar(
                      rec: _rec,
                      locked: _locked,
                      dragX: _dragX,
                      onCancel: () => _finishRecording(cancel: true),
                    ),
                  )
                else ...[
                  if (_menuButton(sz) case final menu?) menu,
                  IconButton(
                    tooltip: _emoji ? '键盘' : '表情',
                    icon: Icon(_emoji ? Icons.keyboard_outlined : Icons.emoji_emotions_outlined, color: sz.inkMuted),
                    onPressed: () {
                      setState(() => _emoji = !_emoji);
                      if (_emoji) {
                        _focus.unfocus();
                      } else {
                        _focus.requestFocus();
                      }
                    },
                  ),
                  Expanded(
                    child: ConstrainedBox(
                      constraints: const BoxConstraints(maxHeight: 140),
                      child: TextField(
                        controller: _text,
                        focusNode: _focus,
                        minLines: 1,
                        maxLines: 6,
                        textInputAction: TextInputAction.newline,
                        keyboardType: TextInputType.multiline,
                        contextMenuBuilder: _contextMenu,
                        onTap: () {
                          if (_emoji) setState(() => _emoji = false);
                        },
                        decoration: InputDecoration(
                          hintText: c.isChannel ? '发布到频道' : '发消息',
                          isDense: true,
                          border: InputBorder.none,
                          contentPadding: const EdgeInsets.symmetric(horizontal: 4, vertical: 10),
                        ),
                      ),
                    ),
                  ),
                  if (!hasText && widget.editing == null)
                    IconButton(tooltip: '附件', icon: Icon(Icons.attach_file, color: sz.inkMuted), onPressed: _attach),
                ],
                if (!_recording && (hasText || widget.editing != null))
                  // 长按(桌面上右键)出「静音发送 / 定时发送」。文字提示只给鼠标悬停(manual):
                  // IconButton 自带的提示在手机上也吃长按,手势竞技场里它在里层先到点,
                  // 这里的长按就永远轮不到 —— 手机上菜单一直出不来,网页上用鼠标测不出来
                  GestureDetector(
                    key: const ValueKey('send'),
                    onLongPress: _sendMenu,
                    onSecondaryTap: _sendMenu,
                    child: Tooltip(
                      message: widget.editing != null ? '保存' : '发送',
                      triggerMode: TooltipTriggerMode.manual,
                      child: IconButton(
                        icon: Icon(widget.editing != null ? Icons.check_circle : Icons.send, color: sz.clay),
                        onPressed: () => _send(),
                      ),
                    ),
                  )
                else if (_recording && _locked)
                  IconButton(
                    key: const ValueKey('voice-send'),
                    tooltip: '发送语音',
                    icon: Icon(Icons.send, color: sz.clay),
                    onPressed: () => _finishRecording(),
                  )
                else
                  GestureDetector(
                    key: const ValueKey('mic'),
                    // 点一下只说怎么用,按住才录
                    onTap: () => _toast('按住说话,松开发送;上滑锁定,左滑取消'),
                    onLongPressStart: (_) => _startRecording(),
                    onLongPressMoveUpdate: (d) {
                      if (!_recording || _locked) return;
                      setState(() {
                        _dragX = d.offsetFromOrigin.dx;
                        _dragY = d.offsetFromOrigin.dy;
                      });
                      if (_dragY < -70) setState(() => _locked = true); // 上滑锁定,松手也不停
                      if (_dragX < -120) _finishRecording(cancel: true); // 左滑取消
                    },
                    onLongPressEnd: (_) {
                      _pressing = false;
                      if (_recording && !_locked) _finishRecording();
                    },
                    child: _recording
                        ? Padding(padding: const EdgeInsets.all(12), child: Icon(Icons.mic, color: sz.danger))
                        : Tooltip(
                            // 同上:提示不能在手机上吃长按,不然按住说话根本开始不了录音
                            message: '按住说话',
                            triggerMode: TooltipTriggerMode.manual,
                            child: Padding(
                              padding: const EdgeInsets.all(12),
                              child: Icon(Icons.mic_none, color: sz.inkMuted),
                            ),
                          ),
                  ),
              ]),
            ),
            if (_emoji && !_recording)
              ExpressionPanel(
                onEmoji: insert,
                onBackspace: _backspace,
                onSticker: (s) => widget.actions.onSendSticker(s),
                stickersAllowed: c.can('send_stickers'),
              ),
          ]),
        ),
      ),
    );
  }
}

class _AttachTile extends StatelessWidget {
  const _AttachTile({required this.icon, required this.label, required this.onTap});

  final IconData icon;
  final String label;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    return SizedBox(
      width: 76,
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(12),
        child: Padding(
          padding: const EdgeInsets.symmetric(vertical: 8),
          child: Column(mainAxisSize: MainAxisSize.min, children: [
            CircleAvatar(radius: 24, backgroundColor: sz.claySoft, child: Icon(icon, color: sz.clay)),
            const SizedBox(height: 6),
            Text(label, style: const TextStyle(fontSize: kFontNote)),
          ]),
        ),
      ),
    );
  }
}

class _ContextBar extends StatelessWidget {
  const _ContextBar({required this.icon, required this.title, required this.text, required this.onClose});

  final IconData icon;
  final String title;
  final String text;
  final VoidCallback onClose;

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    return Padding(
      padding: const EdgeInsets.fromLTRB(12, 6, 4, 2),
      child: Row(children: [
        Icon(icon, color: sz.clay, size: 20),
        const SizedBox(width: 10),
        Container(width: 2, height: 32, color: sz.clay),
        const SizedBox(width: 8),
        Expanded(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(title, maxLines: 1, overflow: TextOverflow.ellipsis,
                style: TextStyle(fontSize: kFontNote, fontWeight: FontWeight.w600, color: sz.clay)),
            Text(text, maxLines: 1, overflow: TextOverflow.ellipsis, style: TextStyle(fontSize: kFontNote, color: sz.inkMuted)),
          ]),
        ),
        IconButton(icon: const Icon(Icons.close, size: 20), onPressed: onClose),
      ]),
    );
  }
}

/// @ 联想、/命令 联想的面板:和聊天背景同色的话看起来像飘在消息上,给一层面板底色和上边线
class _SuggestPanel extends StatelessWidget {
  const _SuggestPanel({required this.child});

  final Widget child;

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    return DecoratedBox(
      decoration: BoxDecoration(color: sz.surface, border: Border(top: BorderSide(color: sz.line))),
      child: ConstrainedBox(constraints: const BoxConstraints(maxHeight: 220), child: child),
    );
  }
}

class _CommandList extends StatelessWidget {
  const _CommandList({required this.hits, required this.many, required this.onPick});

  final List<(BotInfo, BotCommand)> hits;
  final bool many;
  final void Function(BotInfo, BotCommand) onPick;

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    return _SuggestPanel(
      child: ListView(shrinkWrap: true, padding: EdgeInsets.zero, children: [
        for (final h in hits)
          ListTile(
            dense: true,
            title: Text('/${h.$2.command}', style: const TextStyle(fontWeight: FontWeight.w600)),
            subtitle: Text(many ? '${h.$2.description} · ${h.$1.name}' : h.$2.description,
                maxLines: 1, overflow: TextOverflow.ellipsis, style: TextStyle(color: sz.inkMuted)),
            onTap: () => onPick(h.$1, h.$2),
          ),
      ]),
    );
  }
}

class _MentionList extends StatelessWidget {
  const _MentionList({required this.hits, required this.onPick});

  final List<Map<String, dynamic>> hits;
  final void Function(Map<String, dynamic>) onPick;

  @override
  Widget build(BuildContext context) {
    return _SuggestPanel(
      child: ListView(shrinkWrap: true, padding: EdgeInsets.zero, children: [
        for (final h in hits)
          ListTile(
            dense: true,
            leading: CircleAvatar(radius: 14, child: Text(szInitialOf('${(h['user'] as Map)['name'] ?? ''}'))),
            title: Text('${(h['user'] as Map)['name'] ?? ''}'),
            subtitle: (h['user'] as Map)['username'] == null ? null : Text('@${(h['user'] as Map)['username']}'),
            onTap: () => onPick(h),
          ),
      ]),
    );
  }
}

class _RecordingBar extends StatelessWidget {
  const _RecordingBar({
    required this.rec,
    required this.locked,
    required this.dragX,
    required this.onCancel,
  });

  final VoiceRecorder rec;
  final bool locked;
  final double dragX;
  final VoidCallback onCancel;

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    return SizedBox(
      height: 48,
      child: Row(children: [
        const SizedBox(width: 8),
        ValueListenableBuilder<double>(
          valueListenable: rec.level,
          builder: (_, v, __) => Container(
            width: 12 + v * 10,
            height: 12 + v * 10,
            decoration: BoxDecoration(color: sz.danger, shape: BoxShape.circle),
          ),
        ),
        const SizedBox(width: 10),
        ValueListenableBuilder<Duration>(
          valueListenable: rec.elapsed,
          builder: (_, d, __) => Text(duration(d.inMilliseconds), style: const TextStyle(fontFeatures: [FontFeature.tabularFigures()])),
        ),
        const Spacer(),
        if (locked)
          TextButton(onPressed: onCancel, child: const Text('取消'))
        else
          Opacity(
            opacity: (1 + dragX / 120).clamp(0.2, 1.0),
            child: Text('‹ 左滑取消 · 上滑锁定', style: TextStyle(color: sz.inkMuted, fontSize: kFontNote)),
          ),
        const SizedBox(width: 4),
      ]),
    );
  }
}

/// 不能发言时底部那一条:频道订阅者、被禁言、被限制。
class _Blocked extends StatelessWidget {
  const _Blocked({required this.chat});

  final ChatInfo chat;

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    final store = ChatStore.instance;
    final inChat = chat.can('in_chat');
    if (chat.isChannel && inChat) {
      final muted = chat.my.muted;
      return SafeArea(
        top: false,
        child: SizedBox(
          height: 52,
          child: TextButton.icon(
            icon: Icon(muted ? Icons.notifications_off_outlined : Icons.notifications_outlined),
            label: Text(muted ? '取消静音' : '静音'),
            onPressed: () async {
              final until = muted ? null : DateTime.now().add(const Duration(days: 3650));
              final n = await store.api.patchDialog(chat.id, {
                'muted_until': muteParam(until),
              });
              store.putChat(n);
            },
          ),
        ),
      );
    }
    if (!inChat) {
      return SafeArea(
        top: false,
        child: Padding(
          padding: const EdgeInsets.all(8),
          child: FilledButton(
            onPressed: () async {
              try {
                await store.api.joinPublic(chat.id);
                await store.refreshChat(chat.id);
              } on ApiException catch (e) {
                if (context.mounted) {
                  ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(e.message)));
                }
              }
            },
            child: Text(chat.isChannel ? '订阅频道' : '加入群组'),
          ),
        ),
      );
    }
    return SafeArea(
      top: false,
      child: Container(
        height: 52,
        alignment: Alignment.center,
        child: Text('你在这个群被禁言了', style: TextStyle(color: sz.inkMuted)),
      ),
    );
  }
}
