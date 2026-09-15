import 'dart:math';

import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';

import '../models.dart';
import '../store.dart';
import 'avatar.dart';
import 'format.dart';
import 'media_save.dart';

/// 媒体的完整地址(签名过的);还没换到签名时返回 null,调用方先画占位。
({String url, String? thumb})? resolvedMedia(MediaInfo m) {
  final s = ChatStore.instance.signedMedia(m);
  if (s == null) return null;
  final c = ChatStore.instance.client;
  return (url: c.resolveUrl(s.url), thumb: s.thumb == null ? null : c.resolveUrl(s.thumb!));
}

/// 同上,但没换过签名就当场换(保存、打开文件这种点了就要用的);换不到返回 null。
Future<({String url, String? thumb})?> resolveMediaNow(MediaInfo m) async {
  final s = await ChatStore.instance.signMediaNow(m);
  if (s == null) return null;
  final c = ChatStore.instance.client;
  return (url: c.resolveUrl(s.url), thumb: s.thumb == null ? null : c.resolveUrl(s.thumb!));
}

/// 图 / 视频 / GIF 的格子:按原图比例,限最大宽高;视频画播放键和时长。
class MediaTile extends StatelessWidget {
  const MediaTile({
    super.key,
    required this.message,
    required this.media,
    required this.index,
    required this.maxWidth,
    this.maxHeight = 320,
    this.fixed,
    this.onTap,
    this.radius = 12,
  });

  final ChatMessage message;
  final MediaInfo media;
  final int index;
  final double maxWidth;
  final double maxHeight;

  /// 相册格子里用固定尺寸(不按原图比例)
  final Size? fixed;
  final VoidCallback? onTap;
  final double radius;

  Size _size() {
    if (fixed != null) return fixed!;
    final double w = media.w > 0 ? media.w.toDouble() : 4.0;
    final double h = media.h > 0 ? media.h.toDouble() : 3.0;
    var dw = min(maxWidth, max(120.0, w));
    var dh = dw * h / w;
    if (dh > maxHeight) {
      dh = maxHeight;
      dw = max(120.0, dh * w / h);
    }
    return Size(min(dw, maxWidth), dh);
  }

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    final size = _size();
    final local = ChatStore.instance.outbox.previewFor(message.randomId, index);
    Widget img;
    if (local != null && media.kind == 'photo') {
      img = Image.memory(local, fit: BoxFit.cover, width: size.width, height: size.height);
    } else {
      final r = media.id == 0 ? null : resolvedMedia(media);
      final thumb = r?.thumb ?? (media.kind == 'photo' ? r?.url : null);
      img = thumb == null
          ? Container(color: sz.surfaceAlt)
          : Image(
              image: szNetImageKeyed(thumb, 'm${media.id}t'),
              fit: BoxFit.cover,
              width: size.width,
              height: size.height,
              errorBuilder: (_, __, ___) => Container(
                  color: sz.surfaceAlt, child: Icon(Icons.broken_image_outlined, color: sz.inkFaint)),
            );
      // 图片:缩略图先出,点开看原图;在气泡里直接用原图会把流量浪费在列表上
    }
    final isVideo = media.kind == 'video' || media.kind == 'gif' || media.kind == 'video_note';
    final progress = message.isLocal ? message.progress : null;
    return GestureDetector(
      onTap: onTap,
      child: ClipRRect(
        borderRadius: BorderRadius.circular(radius),
        child: SizedBox(
          width: size.width,
          height: size.height,
          child: Stack(fit: StackFit.expand, children: [
            img,
            if (isVideo && progress == null)
              Center(
                child: Container(
                  width: 44,
                  height: 44,
                  decoration: BoxDecoration(color: Colors.black.withValues(alpha: .45), shape: BoxShape.circle),
                  child: Icon(media.kind == 'gif' ? Icons.gif_box_outlined : Icons.play_arrow,
                      color: Colors.white, size: 28),
                ),
              ),
            if (isVideo && media.durationMs > 0 && media.kind != 'gif')
              Positioned(
                left: 6,
                top: 6,
                child: _Pill(text: duration(media.durationMs)),
              ),
            if (media.kind == 'gif')
              const Positioned(left: 6, top: 6, child: _Pill(text: 'GIF')),
            if (progress != null)
              Container(
                color: Colors.black.withValues(alpha: .25),
                child: Center(
                  child: SizedBox(
                    width: 40,
                    height: 40,
                    child: CircularProgressIndicator(
                        value: progress <= 0 ? null : progress, strokeWidth: 3, color: Colors.white),
                  ),
                ),
              ),
          ]),
        ),
      ),
    );
  }
}

class _Pill extends StatelessWidget {
  const _Pill({required this.text});

  final String text;

  @override
  Widget build(BuildContext context) => Container(
        padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
        decoration: BoxDecoration(color: Colors.black.withValues(alpha: .5), borderRadius: BorderRadius.circular(8)),
        child: Text(text, style: const TextStyle(color: Colors.white, fontSize: kFontMicro)),
      );
}

/// 相册:同一个 grouped_id 的几条消息拼成一个格子(Telegram 的排法:1 张原比例,2 张并排,
/// 3 张一大两小,4 张及以上每行两到三张)。
class AlbumGrid extends StatelessWidget {
  const AlbumGrid({super.key, required this.items, required this.width, required this.onTap});

  final List<ChatMessage> items;
  final double width;
  final void Function(ChatMessage m) onTap;

  @override
  Widget build(BuildContext context) {
    final n = items.length;
    const gap = 2.0;
    if (n == 1) {
      final m = items.first;
      return MediaTile(
          message: m, media: m.media.first, index: 0, maxWidth: width, onTap: () => onTap(m));
    }
    final rows = <List<ChatMessage>>[];
    if (n == 2) {
      rows.add(items);
    } else if (n == 3) {
      rows
        ..add([items[0]])
        ..add(items.sublist(1));
    } else {
      var i = 0;
      while (i < n) {
        final left = n - i;
        final take = left == 4 ? 2 : (left >= 3 ? 3 : left);
        rows.add(items.sublist(i, i + take));
        i += take;
      }
    }
    return Column(mainAxisSize: MainAxisSize.min, children: [
      for (var r = 0; r < rows.length; r++) ...[
        if (r > 0) const SizedBox(height: gap),
        Row(mainAxisSize: MainAxisSize.min, children: [
          for (var c = 0; c < rows[r].length; c++) ...[
            if (c > 0) const SizedBox(width: gap),
            MediaTile(
              message: rows[r][c],
              media: rows[r][c].media.first,
              index: 0,
              maxWidth: width,
              radius: 6,
              fixed: Size((width - gap * (rows[r].length - 1)) / rows[r].length,
                  rows[r].length == 1 ? width * .6 : width / rows[r].length),
              onTap: () => onTap(rows[r][c]),
            ),
          ],
        ]),
      ],
    ]);
  }
}

/// 文件:图标 + 文件名 + 大小,点一下交给系统下载 / 打开。
class FileView extends StatelessWidget {
  const FileView({super.key, required this.message, required this.media, required this.fg, required this.accent});

  final ChatMessage message;
  final MediaInfo media;
  final Color fg;
  final Color accent;

  IconData _icon() {
    final n = media.name.toLowerCase();
    if (n.endsWith('.pdf')) return Icons.picture_as_pdf_outlined;
    if (RegExp(r'\.(zip|rar|7z|tar|gz)$').hasMatch(n)) return Icons.folder_zip_outlined;
    if (RegExp(r'\.(doc|docx|txt|md|pages)$').hasMatch(n)) return Icons.description_outlined;
    if (RegExp(r'\.(xls|xlsx|csv|numbers)$').hasMatch(n)) return Icons.table_chart_outlined;
    if (RegExp(r'\.(ppt|pptx|key)$').hasMatch(n)) return Icons.slideshow_outlined;
    if (RegExp(r'\.(mp3|m4a|wav|flac|aac|ogg)$').hasMatch(n)) return Icons.audio_file_outlined;
    if (RegExp(r'\.(apk)$').hasMatch(n)) return Icons.android;
    return Icons.insert_drive_file_outlined;
  }

  @override
  Widget build(BuildContext context) {
    final progress = message.isLocal ? message.progress : null;
    return InkWell(
      // 手机上在 App 里下载、交给系统应用打开;网页上交给浏览器(见 media_save.dart)
      onTap: media.id == 0 ? null : () => openChatFile(context, media),
      borderRadius: BorderRadius.circular(8),
      child: Padding(
        padding: const EdgeInsets.symmetric(vertical: 2),
        child: Row(mainAxisSize: MainAxisSize.min, children: [
          SizedBox(
            width: 44,
            height: 44,
            child: Stack(alignment: Alignment.center, children: [
              Container(
                decoration: BoxDecoration(color: accent, shape: BoxShape.circle),
              ),
              if (progress != null)
                CircularProgressIndicator(
                    value: progress <= 0 ? null : progress, strokeWidth: 3, color: Colors.white)
              else
                Icon(_icon(), color: Colors.white),
            ]),
          ),
          const SizedBox(width: 10),
          Flexible(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisSize: MainAxisSize.min, children: [
              Text(media.name.isEmpty ? '文件' : media.name,
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                  style: TextStyle(fontWeight: FontWeight.w600, color: fg)),
              const SizedBox(height: 2),
              Text(
                  progress != null
                      ? '${fileSize((media.size * progress).round())} / ${fileSize(media.size)}'
                      : fileSize(media.size),
                  style: TextStyle(fontSize: kFontNote, color: fg.withValues(alpha: .65))),
            ]),
          ),
        ]),
      ),
    );
  }
}

/// 贴纸:不画气泡,128 见方的透明图。
class StickerView extends StatelessWidget {
  const StickerView({super.key, required this.media, this.size = 128});

  final MediaInfo media;
  final double size;

  @override
  Widget build(BuildContext context) {
    // 贴纸用原图不用缩略图:缩略图是 JPEG,透明底会变成一块白
    final r = resolvedMedia(media);
    final url = r?.url;
    return SizedBox(
      width: size,
      height: size,
      child: url == null
          ? const SizedBox.shrink()
          : Image(image: szNetImageKeyed(url, 'm${media.id}s'), fit: BoxFit.contain),
    );
  }
}

/// 位置:地址卡 + 「导航」。点开看地图。
class LocationView extends StatelessWidget {
  const LocationView({super.key, required this.location, required this.fg, required this.accent});

  final Map<String, dynamic> location;
  final Color fg;
  final Color accent;

  @override
  Widget build(BuildContext context) {
    final lat = (location['lat'] as num?)?.toDouble() ?? 0;
    final lng = (location['lng'] as num?)?.toDouble() ?? 0;
    final title = '${location['title'] ?? ''}'.trim();
    final addr = '${location['address'] ?? ''}'.trim();
    return InkWell(
      onTap: () => Navigator.of(context).push(MaterialPageRoute<void>(
          builder: (_) => LocationPage(lat: lat, lng: lng, title: title, address: addr))),
      child: SizedBox(
        width: 240,
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisSize: MainAxisSize.min, children: [
          Container(
            height: 110,
            decoration: BoxDecoration(
              color: accent.withValues(alpha: .12),
              borderRadius: BorderRadius.circular(10),
            ),
            child: Stack(children: [
              CustomPaint(size: const Size(240, 110), painter: _GridPainter(fg.withValues(alpha: .08))),
              Center(child: Icon(Icons.location_on, color: accent, size: 40)),
            ]),
          ),
          const SizedBox(height: 6),
          Text(title.isEmpty ? '位置' : title,
              maxLines: 1, overflow: TextOverflow.ellipsis, style: TextStyle(fontWeight: FontWeight.w600, color: fg)),
          if (addr.isNotEmpty)
            Text(addr,
                maxLines: 2,
                overflow: TextOverflow.ellipsis,
                style: TextStyle(fontSize: kFontNote, color: fg.withValues(alpha: .7))),
        ]),
      ),
    );
  }
}

class _GridPainter extends CustomPainter {
  _GridPainter(this.color);

  final Color color;

  @override
  void paint(Canvas canvas, Size size) {
    final p = Paint()
      ..color = color
      ..strokeWidth = 1;
    for (var x = 0.0; x < size.width; x += 18) {
      canvas.drawLine(Offset(x, 0), Offset(x, size.height), p);
    }
    for (var y = 0.0; y < size.height; y += 18) {
      canvas.drawLine(Offset(0, y), Offset(size.width, y), p);
    }
  }

  @override
  bool shouldRepaint(_GridPainter old) => old.color != color;
}

/// 看一个位置:地图 + 导航。
class LocationPage extends StatelessWidget {
  const LocationPage({super.key, required this.lat, required this.lng, this.title = '', this.address = ''});

  final double lat;
  final double lng;
  final String title;
  final String address;

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    return SzPageScaffold(
      appBar: AppBar(title: Text(title.isEmpty ? '位置' : title)),
      body: Column(children: [
        Expanded(
          child: DeliveryMapView(points: [
            MapPoint(lat: lat, lng: lng, label: title.isEmpty ? '位置' : title, icon: Icons.location_on, color: sz.clay),
          ]),
        ),
        SafeArea(
          top: false,
          child: Padding(
            padding: const EdgeInsets.all(kPagePad),
            child: Row(children: [
              Expanded(
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Text(title.isEmpty ? '位置' : title,
                      style: const TextStyle(fontSize: kFontTitle, fontWeight: FontWeight.w600)),
                  if (address.isNotEmpty)
                    Text(address, style: TextStyle(color: sz.inkMuted, fontSize: kFontNote)),
                ]),
              ),
              FilledButton.icon(
                onPressed: () => navigateTo(context, lat: lat, lng: lng, name: title.isEmpty ? '目的地' : title),
                icon: const Icon(Icons.navigation_outlined),
                label: const Text('导航'),
              ),
            ]),
          ),
        ),
      ]),
    );
  }
}

/// 名片。
class ContactCard extends StatelessWidget {
  const ContactCard({super.key, required this.contact, required this.fg, required this.onOpen});

  final Map<String, dynamic> contact;
  final Color fg;
  final void Function(int userId) onOpen;

  @override
  Widget build(BuildContext context) {
    final uid = (contact['user_id'] as num?)?.toInt() ?? 0;
    final name = '${contact['name'] ?? ''}';
    final username = contact['username'] as String?;
    return InkWell(
      onTap: uid == 0 ? null : () => onOpen(uid),
      child: SizedBox(
        width: 220,
        child: Row(children: [
          ChatAvatar(name: name, size: 44),
          const SizedBox(width: 10),
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(name, maxLines: 1, overflow: TextOverflow.ellipsis, style: TextStyle(fontWeight: FontWeight.w600, color: fg)),
              Text(username == null ? '名片' : '@$username',
                  style: TextStyle(fontSize: kFontNote, color: fg.withValues(alpha: .65))),
            ]),
          ),
          Icon(Icons.chevron_right, color: fg.withValues(alpha: .5)),
        ]),
      ),
    );
  }
}

/// 骰子:一个大表情 + 点数。
class DiceView extends StatelessWidget {
  const DiceView({super.key, required this.dice, required this.fg});

  final Map<String, dynamic> dice;
  final Color fg;

  @override
  Widget build(BuildContext context) {
    final e = '${dice['emoji'] ?? '🎲'}';
    final v = dice['value'];
    return Column(mainAxisSize: MainAxisSize.min, children: [
      TweenAnimationBuilder<double>(
        tween: Tween(begin: 0, end: 1),
        duration: const Duration(milliseconds: 700),
        curve: Curves.elasticOut,
        builder: (_, t, child) => Transform.rotate(angle: (1 - t) * 6.28, child: Transform.scale(scale: .6 + .4 * t, child: child)),
        child: Text(e, style: const TextStyle(fontSize: kFigureHero)),
      ),
      Text('$v 点', style: TextStyle(fontSize: kFontBody, fontWeight: FontWeight.w600, color: fg)),
    ]);
  }
}

/// 链接预览卡(正文下面)。
class LinkPreviewCard extends StatelessWidget {
  const LinkPreviewCard({super.key, required this.preview, required this.fg, required this.accent, required this.onOpen});

  final Map<String, dynamic> preview;
  final Color fg;
  final Color accent;
  final void Function(String url) onOpen;

  @override
  Widget build(BuildContext context) {
    final site = '${preview['site'] ?? ''}';
    final title = '${preview['title'] ?? ''}';
    final desc = '${preview['description'] ?? ''}';
    final url = '${preview['url'] ?? ''}';
    final image = '${preview['image'] ?? ''}';
    if (title.isEmpty && desc.isEmpty) return const SizedBox.shrink();
    return InkWell(
      onTap: url.isEmpty ? null : () => onOpen(url),
      child: Container(
        margin: const EdgeInsets.only(top: 6),
        padding: const EdgeInsets.only(left: 8),
        decoration: BoxDecoration(border: Border(left: BorderSide(color: accent, width: 3))),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisSize: MainAxisSize.min, children: [
          if (site.isNotEmpty)
            Text(site, style: TextStyle(fontSize: kFontNote, fontWeight: FontWeight.w600, color: accent)),
          if (title.isNotEmpty)
            Text(title,
                maxLines: 2, overflow: TextOverflow.ellipsis, style: TextStyle(fontWeight: FontWeight.w600, color: fg)),
          if (desc.isNotEmpty)
            Text(desc,
                maxLines: 3, overflow: TextOverflow.ellipsis, style: TextStyle(fontSize: kFontNote, color: fg.withValues(alpha: .8))),
          if (image.startsWith('http'))
            Padding(
              padding: const EdgeInsets.only(top: 6),
              child: ClipRRect(
                borderRadius: BorderRadius.circular(8),
                child: Image(
                    image: szNetImage(image),
                    height: 120,
                    width: 240,
                    fit: BoxFit.cover,
                    errorBuilder: (_, __, ___) => const SizedBox.shrink()),
              ),
            ),
        ]),
      ),
    );
  }
}

/// 分享卡片(DEV-PROMPTS-41 §5.9):歌曲 / 歌单 / 专辑 / 音乐人 / 动态 / 视频。
///
/// 卡片里的字和封面是**服务端存下的快照** —— 发的时候客户端只给 `{type, id}`,
/// 由服务端查出来写死在消息里。这样两件事都成立:别人改了标题这条消息还是当时那句,
/// 谁也发不出一张「超级赞官方」的假卡片。点开走 `url`(站内链接)。
class ShareCardView extends StatelessWidget {
  const ShareCardView(
      {super.key, required this.card, required this.fg, required this.accent, required this.onOpen});

  final Map<String, dynamic> card;
  final Color fg;
  final Color accent;
  final void Function(String url) onOpen;

  @override
  Widget build(BuildContext context) {
    final type = '${card['type'] ?? ''}';
    final what = cardKindLabels[type] ?? '分享';
    final title = '${card['title'] ?? ''}';
    final subtitle = '${card['subtitle'] ?? ''}';
    final cover = '${card['cover'] ?? ''}';
    final url = '${card['url'] ?? ''}';
    final unavailable = card['unavailable'] == true || title.isEmpty;
    return InkWell(
      onTap: unavailable || url.isEmpty ? null : () => onOpen(url),
      child: Container(
        margin: const EdgeInsets.only(top: 6),
        padding: const EdgeInsets.only(left: 8),
        decoration: BoxDecoration(border: Border(left: BorderSide(color: accent, width: 3))),
        child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          if (cover.isNotEmpty && !unavailable)
            Padding(
              padding: const EdgeInsets.only(right: 8, top: 2),
              child: ClipRRect(
                borderRadius: BorderRadius.circular(6),
                child: Image(
                    image: szNetImage(cover),
                    width: 44,
                    height: 44,
                    fit: BoxFit.cover,
                    errorBuilder: (_, __, ___) => const SizedBox(width: 44, height: 44)),
              ),
            ),
          Flexible(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisSize: MainAxisSize.min, children: [
              Text(what, style: TextStyle(fontSize: kFontNote, fontWeight: FontWeight.w600, color: accent)),
              Text(unavailable ? '内容已不可见' : title,
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                  style: TextStyle(fontWeight: FontWeight.w600, color: unavailable ? fg.withValues(alpha: .6) : fg)),
              if (subtitle.isNotEmpty && !unavailable)
                Text(subtitle,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: TextStyle(fontSize: kFontNote, color: fg.withValues(alpha: .8))),
            ]),
          ),
        ]),
      ),
    );
  }
}

/// 投票 / 测验。
class PollView extends StatefulWidget {
  const PollView({super.key, required this.message, required this.fg, required this.accent, required this.onVote,
      this.onClose, this.onShowVoters});

  final ChatMessage message;
  final Color fg;
  final Color accent;
  final Future<void> Function(List<int> options) onVote;
  final VoidCallback? onClose;
  final VoidCallback? onShowVoters;

  @override
  State<PollView> createState() => _PollViewState();
}

class _PollViewState extends State<PollView> {
  final Set<int> _picked = {};
  bool _busy = false;

  Future<void> _vote(List<int> opts) async {
    setState(() => _busy = true);
    try {
      await widget.onVote(opts);
      _picked.clear();
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final p = widget.message.poll!;
    final fg = widget.fg;
    final showResults = p.voted || p.closed;
    final total = max(1, p.totalVoters);
    final kind = [
      if (p.quiz) '测验' else '投票',
      if (p.anonymous) '匿名' else '公开',
      if (p.multiple) '多选',
      if (p.closed) '已截止',
    ].join(' · ');
    return SizedBox(
      width: 260,
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisSize: MainAxisSize.min, children: [
        Text(p.question, style: TextStyle(fontWeight: FontWeight.w700, color: fg, fontSize: kFontBodyLg)),
        const SizedBox(height: 2),
        Text(kind, style: TextStyle(fontSize: kFontNote, color: fg.withValues(alpha: .6))),
        const SizedBox(height: 8),
        for (var i = 0; i < p.options.length; i++)
          Padding(
            padding: const EdgeInsets.only(bottom: 6),
            child: showResults
                ? _ResultRow(
                    text: p.options[i].text,
                    votes: p.options[i].votes ?? 0,
                    total: total,
                    mine: p.myVotes.contains(i),
                    correct: p.quiz ? (p.correct == i ? true : (p.myVotes.contains(i) ? false : null)) : null,
                    fg: fg,
                    accent: widget.accent,
                  )
                : InkWell(
                    onTap: _busy
                        ? null
                        : () {
                            if (p.multiple) {
                              setState(() => _picked.contains(i) ? _picked.remove(i) : _picked.add(i));
                            } else {
                              _vote([i]);
                            }
                          },
                    child: Row(children: [
                      Icon(
                          p.multiple
                              ? (_picked.contains(i) ? Icons.check_box : Icons.check_box_outline_blank)
                              : Icons.radio_button_unchecked,
                          size: 20,
                          color: widget.accent),
                      const SizedBox(width: 8),
                      Expanded(child: Text(p.options[i].text, style: TextStyle(color: fg))),
                    ]),
                  ),
          ),
        if (!showResults && p.multiple)
          Align(
            alignment: Alignment.centerRight,
            child: TextButton(
              onPressed: _picked.isEmpty || _busy ? null : () => _vote(_picked.toList()..sort()),
              child: const Text('投票'),
            ),
          ),
        if (p.quiz && showResults && p.explanation.isNotEmpty)
          Container(
            margin: const EdgeInsets.only(top: 4),
            padding: const EdgeInsets.all(8),
            decoration: BoxDecoration(color: widget.accent.withValues(alpha: .1), borderRadius: BorderRadius.circular(8)),
            child: Text('解析:${p.explanation}', style: TextStyle(fontSize: kFontNote, color: fg)),
          ),
        Row(children: [
          Text('${p.totalVoters} 人参与', style: TextStyle(fontSize: kFontNote, color: fg.withValues(alpha: .6))),
          const Spacer(),
          if (!p.anonymous && widget.onShowVoters != null && showResults)
            TextButton(onPressed: widget.onShowVoters, child: const Text('查看投票人')),
          if (widget.onClose != null && !p.closed)
            TextButton(onPressed: widget.onClose, child: const Text('截止')),
        ]),
      ]),
    );
  }
}

class _ResultRow extends StatelessWidget {
  const _ResultRow({
    required this.text,
    required this.votes,
    required this.total,
    required this.mine,
    required this.correct,
    required this.fg,
    required this.accent,
  });

  final String text;
  final int votes;
  final int total;
  final bool mine;
  final bool? correct;
  final Color fg;
  final Color accent;

  @override
  Widget build(BuildContext context) {
    final pct = (votes * 100 / total).round();
    final bar = correct == false ? Theme.of(context).sz.danger : (correct == true ? Theme.of(context).sz.earn : accent);
    return Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisSize: MainAxisSize.min, children: [
      Row(children: [
        SizedBox(
            width: 40,
            child: Text('$pct%', style: TextStyle(fontWeight: FontWeight.w700, color: fg, fontSize: kFontNote))),
        Expanded(child: Text(text, style: TextStyle(color: fg))),
        if (mine) Icon(correct == false ? Icons.cancel : Icons.check_circle, size: 16, color: bar),
      ]),
      const SizedBox(height: 3),
      ClipRRect(
        borderRadius: BorderRadius.circular(3),
        child: LinearProgressIndicator(
            value: votes / total, minHeight: 5, color: bar, backgroundColor: fg.withValues(alpha: .1)),
      ),
    ]);
  }
}
