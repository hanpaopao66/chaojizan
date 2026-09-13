import 'dart:math';

import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';

import '../models.dart';
import '../store.dart';
import 'avatar.dart';
import 'format.dart';
import 'media_views.dart';
import 'rich_text.dart';
import 'stickers.dart';
import 'voice.dart';

/// 气泡要回调的动作(由聊天页实现)。
class BubbleActions {
  const BubbleActions({
    required this.onLongPress,
    required this.onTapReply,
    required this.onReact,
    required this.onRetry,
    required this.onOpenMedia,
    required this.onOpenUser,
    required this.onVote,
    required this.handlers,
    this.onClosePoll,
    this.onShowVoters,
    this.onSwipeReply,
    this.onTapSelect,
    this.onMarkup,
    this.onCallBack,
  });

  final void Function(ChatMessage m) onLongPress;
  final void Function(int seq) onTapReply;
  final void Function(ChatMessage m, String emoji) onReact;
  final void Function(ChatMessage m) onRetry;
  final void Function(ChatMessage m, List<ChatMessage> album) onOpenMedia;
  final void Function(int userId) onOpenUser;
  final Future<void> Function(ChatMessage m, List<int> options) onVote;
  final void Function(ChatMessage m)? onClosePoll;
  final void Function(ChatMessage m)? onShowVoters;
  final void Function(ChatMessage m)? onSwipeReply;

  /// 多选模式下点一下 = 选中 / 取消
  final void Function(ChatMessage m)? onTapSelect;

  /// 机器人内联键盘按钮(回调按钮要等机器人回话,按钮上转圈直到这个 Future 结束)
  final Future<void> Function(ChatMessage m, Map<String, dynamic> button)? onMarkup;

  /// 点通话记录回拨
  final void Function(ChatMessage m)? onCallBack;
  final TextTapHandlers handlers;
}

/// 同一个人连续发的几条挤在一起:只有第一条带名字、最后一条带头像和小尾巴。
enum RunPos { single, first, middle, last }

/// 发送人名字的颜色:按 id 取一个(和 Telegram 一样,群里分得清谁是谁)。
Color nameColor(int id, bool dark) {
  const light = [
    Color(0xFFC0392B), Color(0xFFD35400), Color(0xFF8E44AD), Color(0xFF2471A3),
    Color(0xFF16A085), Color(0xFF1E8449), Color(0xFFB9770E), Color(0xFFAD1457),
  ];
  const darkC = [
    Color(0xFFFF8A80), Color(0xFFFFAB70), Color(0xFFD7A6FF), Color(0xFF82C4FF),
    Color(0xFF6EE7C8), Color(0xFF8BE39A), Color(0xFFFFD27A), Color(0xFFFF8FC4),
  ];
  final list = dark ? darkC : light;
  return list[id.abs() % list.length];
}

class MessageRow extends StatelessWidget {
  const MessageRow({
    super.key,
    required this.message,
    required this.chat,
    required this.meId,
    required this.actions,
    this.album = const [],
    this.run = RunPos.single,
    this.selecting = false,
    this.selected = false,
    this.highlighted = false,
  });

  final ChatMessage message;
  final ChatInfo chat;
  final int meId;
  final BubbleActions actions;

  /// 相册:同一 grouped_id 的全部消息(含自己);不是相册为空
  final List<ChatMessage> album;
  final RunPos run;
  final bool selecting;
  final bool selected;

  /// 从回复引用 / 搜索跳过来的那一条:闪一下
  final bool highlighted;

  bool get mine => !message.asChat && (message.sender?.id == meId || message.isLocal);

  @override
  Widget build(BuildContext context) {
    final m = message;
    if (m.isService) return _ServiceChip(message: m, meId: meId, channel: chat.isChannel);
    final dark = Theme.of(context).brightness == Brightness.dark;
    final screenW = MediaQuery.sizeOf(context).width;
    final maxW = min(screenW * .78, 420.0);
    final groupLike = chat.isGroup;
    final showAvatar = groupLike && !mine && (run == RunPos.last || run == RunPos.single);
    final avatarSlot = groupLike && !mine;
    Widget bubble = _Bubble(
      message: m,
      chat: chat,
      mine: mine,
      album: album,
      maxWidth: maxW,
      actions: actions,
      showName: groupLike && !mine && (run == RunPos.first || run == RunPos.single),
      tail: run == RunPos.last || run == RunPos.single,
    );
    if (actions.onSwipeReply != null && !selecting && !m.isLocal) {
      bubble = _SwipeToReply(onReply: () => actions.onSwipeReply!(m), child: bubble);
    }
    // 内联键盘挂在气泡下面、和气泡一样宽(Telegram 的样子),不塞进气泡里
    final keyboard = (m.markup?['inline_keyboard'] as List?) ?? const [];
    if (keyboard.isNotEmpty && actions.onMarkup != null) {
      bubble = ConstrainedBox(
        constraints: BoxConstraints(maxWidth: maxW),
        child: IntrinsicWidth(
          child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
            bubble,
            _InlineKeyboard(rows: keyboard, onTap: (b) => actions.onMarkup!(m, b)),
          ]),
        ),
      );
    }
    final row = Row(
      mainAxisAlignment: mine ? MainAxisAlignment.end : MainAxisAlignment.start,
      crossAxisAlignment: CrossAxisAlignment.end,
      children: [
        if (selecting)
          Padding(
            padding: const EdgeInsets.only(right: 6, bottom: 6),
            child: Icon(selected ? Icons.check_circle : Icons.radio_button_unchecked,
                color: selected ? Theme.of(context).sz.clay : Theme.of(context).sz.inkFaint, size: 22),
          ),
        if (avatarSlot)
          SizedBox(
            width: 38,
            child: showAvatar
                ? GestureDetector(
                    onTap: m.sender == null ? null : () => actions.onOpenUser(m.sender!.id),
                    child: ChatAvatar(name: ChatStore.instance.nameOf(m.sender), url: m.sender?.avatar ?? '', size: 32),
                  )
                : null,
          ),
        Flexible(child: bubble),
      ],
    );
    return AnimatedContainer(
      duration: const Duration(milliseconds: 600),
      color: highlighted
          ? Theme.of(context).sz.clay.withValues(alpha: dark ? .22 : .14)
          : (selected ? Theme.of(context).sz.clay.withValues(alpha: .08) : Colors.transparent),
      padding: EdgeInsets.fromLTRB(8, run == RunPos.first || run == RunPos.single ? 4 : 1, 8,
          run == RunPos.last || run == RunPos.single ? 4 : 1),
      child: GestureDetector(
        behavior: HitTestBehavior.translucent,
        onTap: selecting && actions.onTapSelect != null ? () => actions.onTapSelect!(m) : null,
        onLongPress: () => actions.onLongPress(m),
        child: AbsorbPointer(absorbing: selecting, child: row),
      ),
    );
  }
}

class _ServiceChip extends StatelessWidget {
  const _ServiceChip({required this.message, required this.meId, this.channel = false});

  final ChatMessage message;
  final int meId;
  final bool channel;

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    final actor = message.sender?.id == meId ? '你' : ChatStore.instance.nameOf(message.sender, '有人');
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 6, horizontal: 32),
      child: Center(
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
          decoration: BoxDecoration(color: sz.ink.withValues(alpha: .08), borderRadius: BorderRadius.circular(12)),
          child: Text(
            message.kind == 'call'
                ? callLabel(message.call)
                : serviceText(message, actor: actor, meId: meId, channel: channel),
            textAlign: TextAlign.center,
            style: TextStyle(fontSize: kFontNote, color: sz.inkMuted),
          ),
        ),
      ),
    );
  }
}

class _Bubble extends StatelessWidget {
  const _Bubble({
    required this.message,
    required this.chat,
    required this.mine,
    required this.album,
    required this.maxWidth,
    required this.actions,
    required this.showName,
    required this.tail,
  });

  final ChatMessage message;
  final ChatInfo chat;
  final bool mine;
  final List<ChatMessage> album;
  final double maxWidth;
  final BubbleActions actions;
  final bool showName;
  final bool tail;

  bool get _bare {
    final m = message;
    if (m.kind == 'sticker' || m.kind == 'dice' || m.kind == 'video_note') return true;
    if (m.kind == 'text' && m.replyTo == null && m.forward == null && isBigEmoji(m.text)) return true;
    return false;
  }

  bool get _mediaOnly {
    final m = message;
    final visual = m.kind == 'photo' || m.kind == 'video' || m.kind == 'gif';
    final caption = album.isEmpty ? m.text : (album.firstWhere((x) => x.text.isNotEmpty, orElse: () => m).text);
    return visual && caption.isEmpty && m.replyTo == null && m.forward == null && !showName;
  }

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    final dark = Theme.of(context).brightness == Brightness.dark;
    final m = message;
    final bg = mine ? sz.claySoft : sz.surface;
    final fg = sz.ink;
    final accent = sz.clay;
    final radius = BorderRadius.only(
      topLeft: const Radius.circular(16),
      topRight: const Radius.circular(16),
      bottomLeft: Radius.circular(!mine && tail ? 4 : 16),
      bottomRight: Radius.circular(mine && tail ? 4 : 16),
    );
    final meta = _Meta(message: m, chat: chat, mine: mine, onMedia: _mediaOnly, onRetry: () => actions.onRetry(m));

    if (_bare) {
      Widget content;
      switch (m.kind) {
        case 'sticker':
          final setId = (m.sticker?['set_id'] as num?)?.toInt();
          content = m.media.isEmpty
              ? const SizedBox(width: 128, height: 128)
              : GestureDetector(
                  // 点贴纸看整包(可以添加),和 Telegram 一样
                  onTap: setId == null || m.isLocal ? null : () => showStickerSetSheet(context, setId),
                  child: StickerView(media: m.media.first),
                );
        case 'dice':
          content = DiceView(dice: m.dice ?? const {}, fg: fg);
        case 'video_note':
          content = GestureDetector(
            onTap: () => actions.onOpenMedia(m, const []),
            child: ClipOval(
              child: SizedBox(
                width: 200,
                height: 200,
                child: m.media.isEmpty
                    ? Container(color: sz.surfaceAlt)
                    : MediaTile(message: m, media: m.media.first, index: 0, maxWidth: 200, fixed: const Size(200, 200), radius: 100),
              ),
            ),
          );
        default:
          content = Text(m.text, style: const TextStyle(fontSize: kFigureXl));
      }
      return Column(
        crossAxisAlignment: mine ? CrossAxisAlignment.end : CrossAxisAlignment.start,
        mainAxisSize: MainAxisSize.min,
        children: [
          if (m.replyTo != null) _ReplyHeader(reply: m.replyTo!, accent: accent, fg: fg, onTap: () => actions.onTapReply(m.replyTo!.seq)),
          content,
          const SizedBox(height: 2),
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
            decoration: BoxDecoration(color: sz.ink.withValues(alpha: .08), borderRadius: BorderRadius.circular(10)),
            child: meta,
          ),
          if (m.reactions.isNotEmpty) _Reactions(message: m, fg: fg, accent: accent, onReact: actions.onReact),
        ],
      );
    }

    final children = <Widget>[];
    if (showName && m.sender != null) {
      children.add(Padding(
        padding: const EdgeInsets.fromLTRB(10, 6, 10, 0),
        child: GestureDetector(
          onTap: () => actions.onOpenUser(m.sender!.id),
          child: Text(ChatStore.instance.nameOf(m.sender),
              style: TextStyle(fontWeight: FontWeight.w600, fontSize: kFontNote, color: nameColor(m.sender!.id, dark))),
        ),
      ));
    }
    if (m.asChat && chat.isChannel == false && m.senderChat != null) {
      children.add(Padding(
        padding: const EdgeInsets.fromLTRB(10, 6, 10, 0),
        child: Text('${m.senderChat!['title'] ?? ''}',
            style: TextStyle(fontWeight: FontWeight.w600, fontSize: kFontNote, color: accent)),
      ));
    }
    if (m.forward != null) {
      children.add(Padding(
        padding: const EdgeInsets.fromLTRB(10, 6, 10, 0),
        child: _ForwardHeader(forward: m.forward!, accent: accent, onOpenUser: actions.onOpenUser),
      ));
    }
    if (m.replyTo != null) {
      children.add(Padding(
        padding: const EdgeInsets.fromLTRB(8, 6, 8, 0),
        child: _ReplyHeader(reply: m.replyTo!, accent: accent, fg: fg, onTap: () => actions.onTapReply(m.replyTo!.seq)),
      ));
    }

    final caption = album.isEmpty ? m.text : album.firstWhere((x) => x.text.isNotEmpty, orElse: () => m).text;
    final captionEntities =
        album.isEmpty ? m.entities : album.firstWhere((x) => x.text.isNotEmpty, orElse: () => m).entities;
    final innerW = maxWidth;
    switch (m.kind) {
      case 'photo':
      case 'video':
      case 'gif':
        final media = album.isNotEmpty
            ? AlbumGrid(items: album, width: innerW, onTap: (x) => actions.onOpenMedia(x, album))
            : (m.media.isEmpty
                ? const SizedBox.shrink()
                : MediaTile(message: m, media: m.media.first, index: 0, maxWidth: innerW,
                    onTap: () => actions.onOpenMedia(m, const [])));
        children.add(Padding(
          padding: EdgeInsets.all(_mediaOnly ? 0 : 3),
          child: _mediaOnly ? Stack(children: [media, Positioned(right: 6, bottom: 6, child: _OnMediaMeta(child: meta))]) : media,
        ));
      case 'voice':
        if (m.media.isNotEmpty) {
          children.add(Padding(
            padding: const EdgeInsets.fromLTRB(8, 8, 10, 0),
            child: VoiceView(
                media: m.media.first,
                url: m.media.first.id == 0 ? null : resolvedMedia(m.media.first)?.url,
                fg: fg,
                accent: accent),
          ));
        }
      case 'file':
        if (m.media.isNotEmpty) {
          children.add(Padding(
            padding: const EdgeInsets.fromLTRB(8, 8, 10, 0),
            child: FileView(message: m, media: m.media.first, fg: fg, accent: accent),
          ));
        }
      case 'location':
        children.add(Padding(
          padding: const EdgeInsets.fromLTRB(6, 6, 6, 0),
          child: LocationView(location: m.location ?? const {}, fg: fg, accent: accent),
        ));
      case 'contact':
        children.add(Padding(
          padding: const EdgeInsets.fromLTRB(10, 8, 10, 0),
          child: ContactCard(contact: m.contact ?? const {}, fg: fg, onOpen: actions.onOpenUser),
        ));
      case 'poll':
        if (m.poll != null) {
          children.add(Padding(
            padding: const EdgeInsets.fromLTRB(10, 8, 10, 0),
            child: PollView(
              message: m,
              fg: fg,
              accent: accent,
              onVote: (o) => actions.onVote(m, o),
              onClose: mine && actions.onClosePoll != null ? () => actions.onClosePoll!(m) : null,
              onShowVoters: actions.onShowVoters == null ? null : () => actions.onShowVoters!(m),
            ),
          ));
        }
      case 'call':
        final missedByMe = !mine && (m.call?['state'] == 'missed' || m.call?['state'] == 'busy' ||
            m.call?['state'] == 'canceled');
        children.add(InkWell(
          // 点通话记录回拨(和 Telegram 一样)
          onTap: actions.onCallBack == null ? null : () => actions.onCallBack!(m),
          child: Padding(
            padding: const EdgeInsets.fromLTRB(10, 8, 10, 0),
            child: Row(mainAxisSize: MainAxisSize.min, children: [
              Icon(m.call?['video'] == true ? Icons.videocam_outlined : Icons.call_outlined,
                  color: missedByMe ? Theme.of(context).sz.danger : accent),
              const SizedBox(width: 8),
              Text(callLabel(m.call, mine: mine),
                  style: TextStyle(color: missedByMe ? Theme.of(context).sz.danger : fg)),
            ]),
          ),
        ));
    }

    final isText = m.kind == 'text';
    final hasCaption = caption.isNotEmpty && !isText;
    if (isText || hasCaption) {
      children.add(Padding(
        padding: const EdgeInsets.fromLTRB(10, 6, 10, 6),
        child: MessageText(
          text: isText ? m.text : caption,
          entities: isText ? m.entities : captionEntities,
          style: TextStyle(fontSize: kFontBodyLg, color: fg, height: 1.35),
          handlers: actions.handlers,
          linkColor: sz.link,
          // 时间和勾接在最后一行后面(Telegram 的排法),不单独占一行
          trailing: WidgetSpan(
            alignment: PlaceholderAlignment.bottom,
            child: Padding(padding: const EdgeInsets.only(left: 8, top: 4), child: meta),
          ),
        ),
      ));
      if (m.preview != null && isText) {
        children.add(Padding(
          padding: const EdgeInsets.fromLTRB(10, 0, 10, 6),
          child: LinkPreviewCard(
              preview: m.preview!, fg: fg, accent: accent, onOpen: (u) => actions.handlers.onUrl?.call(u)),
        ));
      }
    } else if (!_mediaOnly) {
      children.add(Padding(
        padding: const EdgeInsets.fromLTRB(10, 2, 10, 6),
        child: Align(alignment: Alignment.centerRight, widthFactor: 1, child: meta),
      ));
    }
    if (m.signature != null && m.signature!.isNotEmpty) {
      children.add(Padding(
        padding: const EdgeInsets.fromLTRB(10, 0, 10, 6),
        child: Text('— ${m.signature}', style: TextStyle(fontSize: kFontNote, color: sz.inkMuted)),
      ));
    }
    if (m.reactions.isNotEmpty) {
      children.add(Padding(
        padding: const EdgeInsets.fromLTRB(8, 0, 8, 6),
        child: _Reactions(message: m, fg: fg, accent: accent, onReact: actions.onReact),
      ));
    }

    return ConstrainedBox(
      constraints: BoxConstraints(maxWidth: maxWidth + (_mediaOnly ? 0 : 6)),
      child: DecoratedBox(
        decoration: BoxDecoration(
          color: _mediaOnly ? Colors.transparent : bg,
          borderRadius: radius,
          border: mine || _mediaOnly ? null : Border.all(color: sz.line),
        ),
        child: ClipRRect(
          borderRadius: radius,
          child: IntrinsicWidth(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              mainAxisSize: MainAxisSize.min,
              children: children,
            ),
          ),
        ),
      ),
    );
  }
}

class _OnMediaMeta extends StatelessWidget {
  const _OnMediaMeta({required this.child});

  final Widget child;

  @override
  Widget build(BuildContext context) => Container(
        padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
        decoration: BoxDecoration(color: Colors.black.withValues(alpha: .45), borderRadius: BorderRadius.circular(10)),
        child: child,
      );
}

/// 时间 + 已编辑 + 浏览量 + 勾(时钟 / 单勾 / 双勾 / 红色感叹号)
class _Meta extends StatelessWidget {
  const _Meta({required this.message, required this.chat, required this.mine, required this.onMedia, required this.onRetry});

  final ChatMessage message;
  final ChatInfo chat;
  final bool mine;
  final bool onMedia;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    final m = message;
    final c = onMedia ? Colors.white : sz.inkMuted;
    final parts = <Widget>[];
    if (m.views != null) {
      parts.addAll([
        Icon(Icons.visibility_outlined, size: 13, color: c),
        const SizedBox(width: 2),
        Text(m.views! >= 10000 ? '${(m.views! / 10000).toStringAsFixed(1)}万' : '${m.views}',
            style: TextStyle(fontSize: kFontMicro, color: c)),
        const SizedBox(width: 6),
      ]);
    }
    if (m.editedAt != null) {
      parts.add(Text('已编辑 ', style: TextStyle(fontSize: kFontMicro, color: c)));
    }
    // 通话记录的「静音」是服务端为了不响铃才标的,不是发的人选的,不画这个图标
    if (m.silent && m.kind != 'call') {
      parts.add(Icon(Icons.notifications_off_outlined, size: 12, color: c));
    }
    parts.add(Text(hm(m.createdAt), style: TextStyle(fontSize: kFontMicro, color: c)));
    if (mine && !chat.isChannel && !chat.isSaved) {
      Widget tick;
      if (m.localStatus == LocalStatus.sending) {
        tick = Icon(Icons.schedule, size: 14, color: c);
      } else if (m.localStatus == LocalStatus.failed) {
        tick = GestureDetector(onTap: onRetry, child: Icon(Icons.error, size: 16, color: sz.danger));
      } else if (m.seq > 0 && m.seq <= chat.peerReadSeq) {
        tick = Icon(Icons.done_all, size: 15, color: onMedia ? Colors.white : sz.clay);
      } else {
        tick = Icon(Icons.done, size: 15, color: c);
      }
      parts.addAll([const SizedBox(width: 3), tick]);
    }
    return Row(mainAxisSize: MainAxisSize.min, children: parts);
  }
}

class _ReplyHeader extends StatelessWidget {
  const _ReplyHeader({required this.reply, required this.accent, required this.fg, required this.onTap});

  final ReplyPreview reply;
  final Color accent;
  final Color fg;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final text = reply.deleted
        ? '消息已删除'
        : (reply.preview.isNotEmpty ? reply.preview : (kindLabels[reply.kind] ?? ''));
    return GestureDetector(
      onTap: reply.deleted ? null : onTap,
      child: Container(
        padding: const EdgeInsets.fromLTRB(8, 4, 8, 4),
        decoration: BoxDecoration(
          color: accent.withValues(alpha: .10),
          borderRadius: BorderRadius.circular(6),
          border: Border(left: BorderSide(color: accent, width: 3)),
        ),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisSize: MainAxisSize.min, children: [
          Text(reply.senderName.isEmpty ? '回复' : reply.senderName,
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: TextStyle(fontSize: kFontNote, fontWeight: FontWeight.w600, color: accent)),
          Text(text,
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: TextStyle(fontSize: kFontNote, color: fg.withValues(alpha: .8))),
        ]),
      ),
    );
  }
}

class _ForwardHeader extends StatelessWidget {
  const _ForwardHeader({required this.forward, required this.accent, required this.onOpenUser});

  final Map<String, dynamic> forward;
  final Color accent;
  final void Function(int) onOpenUser;

  @override
  Widget build(BuildContext context) {
    final u = forward['from_user'] is Map ? (forward['from_user'] as Map) : null;
    final ch = forward['from_chat'] is Map ? (forward['from_chat'] as Map) : null;
    final name = '${forward['hidden_name'] ?? ''}'.isNotEmpty
        ? '${forward['hidden_name']}'
        : ('${u?['name'] ?? ch?['title'] ?? ''}');
    final uid = (u?['id'] as num?)?.toInt();
    return GestureDetector(
      onTap: uid == null ? null : () => onOpenUser(uid),
      child: Row(mainAxisSize: MainAxisSize.min, children: [
        Icon(Icons.shortcut, size: 14, color: accent),
        const SizedBox(width: 4),
        Flexible(
          child: Text('转发自 $name',
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: TextStyle(fontSize: kFontNote, color: accent, fontWeight: FontWeight.w600)),
        ),
      ]),
    );
  }
}

class _Reactions extends StatelessWidget {
  const _Reactions({required this.message, required this.fg, required this.accent, required this.onReact});

  final ChatMessage message;
  final Color fg;
  final Color accent;
  final void Function(ChatMessage, String) onReact;

  @override
  Widget build(BuildContext context) {
    return Wrap(spacing: 4, runSpacing: 4, children: [
      for (final r in message.reactions)
        InkWell(
          onTap: () => onReact(message, r.emoji),
          borderRadius: BorderRadius.circular(12),
          child: Container(
            padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 2),
            decoration: BoxDecoration(
              color: r.me ? accent.withValues(alpha: .85) : fg.withValues(alpha: .08),
              borderRadius: BorderRadius.circular(12),
            ),
            child: Text('${r.emoji} ${r.count}',
                style: TextStyle(fontSize: kFontNote, color: r.me ? Colors.white : fg)),
          ),
        ),
    ]);
  }
}

class _InlineKeyboard extends StatefulWidget {
  const _InlineKeyboard({required this.rows, required this.onTap});

  final List rows;
  final Future<void> Function(Map<String, dynamic>) onTap;

  @override
  State<_InlineKeyboard> createState() => _InlineKeyboardState();
}

class _InlineKeyboardState extends State<_InlineKeyboard> {
  /// 正在等机器人回话的那个按钮(行, 列)
  (int, int)? _busy;

  Future<void> _press(int r, int c, Map<String, dynamic> b) async {
    if (_busy != null) return;
    setState(() => _busy = (r, c));
    try {
      await widget.onTap(b);
    } finally {
      if (mounted) setState(() => _busy = null);
    }
  }

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    return Padding(
      padding: const EdgeInsets.only(top: 2),
      child: Column(children: [
        for (var r = 0; r < widget.rows.length; r++)
          Row(children: [
            for (var c = 0; c < (widget.rows[r] as List).length; c++)
              Expanded(child: _button(sz, r, c, ((widget.rows[r] as List)[c] as Map).cast<String, dynamic>())),
          ]),
      ]),
    );
  }

  Widget _button(SzColors sz, int r, int c, Map<String, dynamic> b) {
    final busy = _busy == (r, c);
    final icon = b['url'] != null ? Icons.north_east : (b['web_app'] != null ? Icons.apps : null);
    return Padding(
      padding: const EdgeInsets.all(2),
      child: Material(
        color: sz.surface,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8), side: BorderSide(color: sz.line)),
        clipBehavior: Clip.antiAlias,
        child: InkWell(
          onTap: () => _press(r, c, b),
          child: Stack(children: [
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 9),
              child: Center(
                child: busy
                    ? SizedBox(width: 16, height: 16, child: CircularProgressIndicator(strokeWidth: 2, color: sz.link))
                    : Text('${b['text'] ?? ''}',
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: TextStyle(color: sz.link, fontWeight: FontWeight.w600, fontSize: kFontBody)),
              ),
            ),
            if (icon != null) Positioned(right: 4, top: 4, child: Icon(icon, size: 11, color: sz.inkFaint)),
          ]),
        ),
      ),
    );
  }
}

/// 气泡往左滑一截松手 = 回复这条(Telegram 的手势)。
class _SwipeToReply extends StatefulWidget {
  const _SwipeToReply({required this.onReply, required this.child});

  final VoidCallback onReply;
  final Widget child;

  @override
  State<_SwipeToReply> createState() => _SwipeToReplyState();
}

class _SwipeToReplyState extends State<_SwipeToReply> {
  double _dx = 0;
  bool _armed = false;

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onHorizontalDragUpdate: (d) {
        setState(() {
          _dx = (_dx + d.delta.dx).clamp(-80.0, 0.0);
          _armed = _dx < -56;
        });
      },
      onHorizontalDragEnd: (_) {
        if (_armed) widget.onReply();
        setState(() {
          _dx = 0;
          _armed = false;
        });
      },
      child: Stack(clipBehavior: Clip.none, alignment: Alignment.centerRight, children: [
        if (_dx < -8)
          Positioned(
            right: -34,
            child: Opacity(
              opacity: (-_dx / 56).clamp(0.0, 1.0),
              child: Icon(Icons.reply, color: _armed ? Theme.of(context).sz.clay : Theme.of(context).sz.inkFaint),
            ),
          ),
        Transform.translate(offset: Offset(_dx, 0), child: widget.child),
      ]),
    );
  }
}
