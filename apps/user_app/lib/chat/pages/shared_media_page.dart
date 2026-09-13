import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';
import 'package:url_launcher/url_launcher.dart';

import '../chat_page.dart';
import '../models.dart';
import '../store.dart';
import '../ui/format.dart';
import '../ui/media_views.dart';
import '../ui/voice.dart';
import 'media_viewer.dart';

/// 共享媒体:图片视频 / 文件 / 链接 / 语音 四个页签(Telegram 的「共享媒体」)。
class SharedMediaPage extends StatelessWidget {
  const SharedMediaPage({super.key, required this.chatId});

  final int chatId;

  @override
  Widget build(BuildContext context) {
    return DefaultTabController(
      length: 4,
      child: SzPageScaffold(
        appBar: AppBar(
          title: const Text('图片、文件和链接'),
          bottom: const TabBar(tabs: [
            Tab(text: '图片视频'),
            Tab(text: '文件'),
            Tab(text: '链接'),
            Tab(text: '语音'),
          ]),
        ),
        body: TabBarView(children: [
          _MediaTab(chatId: chatId, kind: 'photo'),
          _MediaTab(chatId: chatId, kind: 'file'),
          _MediaTab(chatId: chatId, kind: 'link'),
          _MediaTab(chatId: chatId, kind: 'voice'),
        ]),
      ),
    );
  }
}

class _MediaTab extends StatefulWidget {
  const _MediaTab({required this.chatId, required this.kind});

  final int chatId;
  final String kind;

  @override
  State<_MediaTab> createState() => _MediaTabState();
}

class _MediaTabState extends State<_MediaTab> with AutomaticKeepAliveClientMixin {
  final List<ChatMessage> _items = [];
  bool _more = true;
  bool _loading = false;
  Object? _error;

  @override
  bool get wantKeepAlive => true;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    if (_loading || !_more) return;
    setState(() => _loading = true);
    try {
      final r = await ChatStore.instance.api.searchIn(widget.chatId,
          kind: widget.kind, before: _items.isEmpty ? null : _items.last.seq);
      if (!mounted) return;
      setState(() {
        _items.addAll(r.items);
        _more = r.hasMore;
      });
    } catch (e) {
      if (mounted) setState(() => _error = e);
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    super.build(context);
    final sz = Theme.of(context).sz;
    if (_error != null && _items.isEmpty) {
      return SzError(error: _error, onRetry: () {
        setState(() => _error = null);
        _load();
      });
    }
    if (_items.isEmpty) {
      return _loading
          ? const Center(child: CircularProgressIndicator())
          : Center(child: Text('还没有', style: TextStyle(color: sz.inkMuted)));
    }
    return NotificationListener<ScrollNotification>(
      onNotification: (n) {
        if (n.metrics.extentAfter < 400) _load();
        return false;
      },
      child: widget.kind == 'photo' ? _grid() : _list(),
    );
  }

  Widget _grid() => GridView.builder(
        padding: const EdgeInsets.all(2),
        gridDelegate: const SliverGridDelegateWithMaxCrossAxisExtent(
            maxCrossAxisExtent: 130, mainAxisSpacing: 2, crossAxisSpacing: 2),
        itemCount: _items.length,
        itemBuilder: (context, i) {
          final m = _items[i];
          if (m.media.isEmpty) return const SizedBox.shrink();
          return LayoutBuilder(
            builder: (context, c) => MediaTile(
              message: m,
              media: m.media.first,
              index: 0,
              maxWidth: c.maxWidth,
              fixed: Size(c.maxWidth, c.maxHeight),
              radius: 0,
              onTap: () => openMediaViewer(context, m, _items.where((x) => x.media.isNotEmpty).toList()),
            ),
          );
        },
      );

  Widget _list() {
    final sz = Theme.of(context).sz;
    return ListView.separated(
      itemCount: _items.length,
      separatorBuilder: (_, __) => Divider(height: 1, color: sz.line),
      itemBuilder: (context, i) {
        final m = _items[i];
        final sub = '${ChatStore.instance.nameOf(m.sender)} · ${listTime(m.createdAt)}';
        switch (widget.kind) {
          case 'file':
            final f = m.media.isEmpty ? null : m.media.first;
            return ListTile(
              leading: const Icon(Icons.insert_drive_file_outlined),
              title: Text(f?.name ?? '文件', maxLines: 1, overflow: TextOverflow.ellipsis),
              subtitle: Text('${fileSize(f?.size ?? 0)} · $sub'),
              onTap: () => openChat(context, widget.chatId, jumpTo: m.seq),
            );
          case 'voice':
            return Padding(
              padding: const EdgeInsets.symmetric(horizontal: kPagePad, vertical: 8),
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                if (m.media.isNotEmpty)
                  VoiceView(media: m.media.first, url: resolvedMedia(m.media.first)?.url, fg: sz.ink, accent: sz.clay),
                Text(sub, style: TextStyle(fontSize: kFontNote, color: sz.inkMuted)),
              ]),
            );
          default:
            final urls = [
              for (final e in m.entities)
                if (e.type == 'text_link' && e.url != null)
                  e.url!
                else if (e.type == 'url' && e.offset + e.length <= m.text.length)
                  m.text.substring(e.offset, e.offset + e.length)
            ];
            return ListTile(
              leading: const Icon(Icons.link),
              title: Text(urls.isEmpty ? m.text : urls.first, maxLines: 1, overflow: TextOverflow.ellipsis,
                  style: TextStyle(color: sz.link)),
              subtitle: Text(sub),
              onTap: urls.isEmpty
                  ? null
                  : () => launchUrl(Uri.parse(urls.first.startsWith('http') ? urls.first : 'https://${urls.first}'),
                      mode: LaunchMode.externalApplication),
              onLongPress: () => openChat(context, widget.chatId, jumpTo: m.seq),
            );
        }
      },
    );
  }
}
