import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:image_picker/image_picker.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:superz_shared/superz_shared.dart';

import '../models.dart';
import '../store.dart';
import 'emoji.dart';

// 贴纸(DEV-PROMPTS-40 #351,D17):面板、贴纸包管理、点别人发的贴纸看整包。
// 贴纸是公开的 512px WebP(透明底),地址是 /img/…,直接画,不用换签名。

/// 贴纸面板要的数据:装着的包 + 最近用过的。进程内缓存一份,面板每次打开不用重拉。
class StickerCache {
  StickerCache._();

  static List<StickerSetInfo>? installed;
  static List<StickerSetInfo> created = [];
  static List<StickerItem> recent = [];
  static bool _recentLoaded = false;

  static String _recentKey() => 'chat_recent_stickers_${ChatStore.instance.meId}';

  static Future<List<StickerSetInfo>> load({bool force = false}) async {
    if (installed != null && !force) return installed!;
    final r = await ChatStore.instance.api.stickerSets();
    installed = r.installed;
    created = r.created;
    return installed!;
  }

  static Future<List<StickerItem>> loadRecent() async {
    if (_recentLoaded) return recent;
    try {
      final sp = await SharedPreferences.getInstance();
      final raw = sp.getString(_recentKey());
      if (raw != null) {
        recent = [for (final x in jsonDecode(raw) as List) StickerItem.fromJson(x)];
      }
    } catch (_) {}
    _recentLoaded = true;
    return recent;
  }

  static Future<void> used(StickerItem s) async {
    recent = [s, ...recent.where((x) => x.id != s.id)].take(24).toList();
    try {
      final sp = await SharedPreferences.getInstance();
      await sp.setString(_recentKey(), jsonEncode([for (final x in recent) x.toJson()]));
    } catch (_) {}
  }

  static void reset() {
    installed = null;
    created = [];
    recent = [];
    _recentLoaded = false;
  }
}

Widget stickerImage(StickerItem s, {double size = 64}) {
  final url = ChatStore.instance.client.resolveUrl(s.url);
  return SizedBox(
    width: size,
    height: size,
    child: url.isEmpty
        ? Center(child: Text(s.emoji, style: const TextStyle(fontSize: kFigureMd)))
        : Image(
            image: szNetImageKeyed(url, 'st${s.id}'),
            fit: BoxFit.contain,
            errorBuilder: (_, __, ___) => Center(child: Text(s.emoji, style: const TextStyle(fontSize: kFigureMd))),
          ),
  );
}

/// 表情 / 贴纸两个页签的底部面板(输入框下面)。
class ExpressionPanel extends StatefulWidget {
  const ExpressionPanel({
    super.key,
    required this.onEmoji,
    required this.onBackspace,
    required this.onSticker,
    this.stickersAllowed = true,
    this.height = 300,
  });

  final void Function(String emoji) onEmoji;
  final VoidCallback onBackspace;
  final void Function(StickerItem sticker) onSticker;
  final bool stickersAllowed;
  final double height;

  @override
  State<ExpressionPanel> createState() => _ExpressionPanelState();
}

class _ExpressionPanelState extends State<ExpressionPanel> {
  bool _stickers = false;

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    return SizedBox(
      height: widget.height,
      child: Column(children: [
        Expanded(
          child: _stickers
              ? StickerPanel(onSend: widget.onSticker)
              : EmojiPanel(onPick: widget.onEmoji, onBackspace: widget.onBackspace, height: widget.height - 44),
        ),
        SizedBox(
          height: 44,
          child: Row(mainAxisAlignment: MainAxisAlignment.center, children: [
            _Seg(label: '表情', selected: !_stickers, onTap: () => setState(() => _stickers = false)),
            const SizedBox(width: 8),
            if (widget.stickersAllowed)
              _Seg(label: '贴纸', selected: _stickers, onTap: () => setState(() => _stickers = true))
            else
              Text('这里不能发贴纸', style: TextStyle(fontSize: kFontNote, color: sz.inkFaint)),
          ]),
        ),
      ]),
    );
  }
}

class _Seg extends StatelessWidget {
  const _Seg({required this.label, required this.selected, required this.onTap});

  final String label;
  final bool selected;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    return InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(16),
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 5),
        decoration: BoxDecoration(
          color: selected ? sz.claySoft : Colors.transparent,
          borderRadius: BorderRadius.circular(16),
        ),
        child: Text(label, style: TextStyle(color: selected ? sz.clay : sz.inkMuted, fontWeight: FontWeight.w600)),
      ),
    );
  }
}

/// 贴纸面板:顶上一排包的封面(第一个是「最近」),下面是这一包的格子。
class StickerPanel extends StatefulWidget {
  const StickerPanel({super.key, required this.onSend});

  final void Function(StickerItem sticker) onSend;

  @override
  State<StickerPanel> createState() => _StickerPanelState();
}

class _StickerPanelState extends State<StickerPanel> {
  List<StickerSetInfo>? _sets;
  List<StickerItem> _recent = [];
  Object? _error;

  /// -1 = 最近;其他是 _sets 的下标
  int _tab = -1;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load({bool force = false}) async {
    try {
      final r = await StickerCache.loadRecent();
      final sets = await StickerCache.load(force: force);
      if (!mounted) return;
      setState(() {
        _recent = r;
        _sets = sets;
        _error = null;
        if (_tab == -1 && _recent.isEmpty && sets.isNotEmpty) _tab = 0;
        if (_tab >= sets.length) _tab = sets.isEmpty ? -1 : 0;
      });
    } catch (e) {
      if (mounted) setState(() => _error = e);
    }
  }

  void _send(StickerItem s) {
    widget.onSend(s);
    StickerCache.used(s);
  }

  Future<void> _manage() async {
    await Navigator.of(context).push(MaterialPageRoute<void>(builder: (_) => const StickerSetsPage()));
    await _load(force: true);
  }

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    final sets = _sets;
    if (sets == null) {
      return _error != null
          ? Center(child: TextButton(onPressed: _load, child: const Text('贴纸没加载出来,点这里重试')))
          : const Center(child: CircularProgressIndicator());
    }
    final items = _tab == -1 ? _recent : (sets.isEmpty ? const <StickerItem>[] : sets[_tab].stickers);
    return Column(children: [
      SizedBox(
        height: 48,
        child: Row(children: [
          Expanded(
            child: ListView(scrollDirection: Axis.horizontal, padding: const EdgeInsets.symmetric(horizontal: 6), children: [
              _TabIcon(
                selected: _tab == -1,
                onTap: () => setState(() => _tab = -1),
                child: Icon(Icons.history, color: _tab == -1 ? sz.clay : sz.inkMuted),
              ),
              for (var i = 0; i < sets.length; i++)
                _TabIcon(
                  selected: _tab == i,
                  onTap: () => setState(() => _tab = i),
                  child: sets[i].cover == null
                      ? Center(child: Text(sets[i].title.characters.first))
                      : stickerImage(sets[i].cover!, size: 30),
                ),
            ]),
          ),
          IconButton(tooltip: '管理贴纸', icon: Icon(Icons.tune, color: sz.inkMuted), onPressed: _manage),
        ]),
      ),
      Expanded(
        child: items.isEmpty
            ? Center(
                child: Padding(
                  padding: const EdgeInsets.all(24),
                  child: Text(
                    _tab == -1
                        ? (sets.isEmpty ? '还没有贴纸\n点右上角建一个自己的贴纸包,或者在聊天里点别人发的贴纸添加' : '最近发过的贴纸会出现在这里')
                        : '这个包还是空的',
                    textAlign: TextAlign.center,
                    style: TextStyle(color: sz.inkMuted),
                  ),
                ),
              )
            : GridView.builder(
                padding: const EdgeInsets.all(8),
                gridDelegate: const SliverGridDelegateWithMaxCrossAxisExtent(maxCrossAxisExtent: 80, mainAxisSpacing: 6, crossAxisSpacing: 6),
                itemCount: items.length,
                itemBuilder: (_, i) => InkWell(
                  borderRadius: BorderRadius.circular(8),
                  onTap: () => _send(items[i]),
                  onLongPress: () => showStickerSetSheet(context, items[i].setId),
                  child: Padding(padding: const EdgeInsets.all(4), child: stickerImage(items[i], size: 72)),
                ),
              ),
      ),
    ]);
  }
}

class _TabIcon extends StatelessWidget {
  const _TabIcon({required this.selected, required this.onTap, required this.child});

  final bool selected;
  final VoidCallback onTap;
  final Widget child;

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 2, vertical: 6),
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(8),
        child: Container(
          width: 40,
          alignment: Alignment.center,
          decoration: BoxDecoration(
            color: selected ? sz.claySoft : Colors.transparent,
            borderRadius: BorderRadius.circular(8),
          ),
          child: child,
        ),
      ),
    );
  }
}

/// 点聊天里的一张贴纸:看整包,可以添加 / 移除;自己的包可以去编辑。
Future<void> showStickerSetSheet(BuildContext context, int setId) async {
  final store = ChatStore.instance;
  StickerSetInfo set;
  try {
    set = await store.api.stickerSet(setId);
  } on ApiException catch (e) {
    if (context.mounted) {
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(e.statusCode == 404 ? '这个贴纸包已经被作者删掉了' : e.message)));
    }
    return;
  }
  if (!context.mounted) return;
  await szShowSheet<void>(
    context: context,
    builder: (ctx) => StatefulBuilder(
      builder: (ctx, setSheet) => SafeArea(
        child: SizedBox(
          height: MediaQuery.of(ctx).size.height * .6,
          child: Column(children: [
            ListTile(
              title: Text(set.title, style: const TextStyle(fontWeight: FontWeight.w600)),
              subtitle: Text('${set.count} 张${set.isOfficial ? ' · 官方' : ''}'),
            ),
            Expanded(
              child: GridView.builder(
                padding: const EdgeInsets.symmetric(horizontal: 12),
                gridDelegate: const SliverGridDelegateWithMaxCrossAxisExtent(maxCrossAxisExtent: 88, mainAxisSpacing: 6, crossAxisSpacing: 6),
                itemCount: set.stickers.length,
                itemBuilder: (_, i) => stickerImage(set.stickers[i], size: 80),
              ),
            ),
            Padding(
              padding: const EdgeInsets.all(12),
              child: SizedBox(
                width: double.infinity,
                child: set.isOfficial
                    ? const OutlinedButton(onPressed: null, child: Text('官方贴纸,所有人都能用'))
                    : set.installed
                        ? OutlinedButton(
                            onPressed: () async {
                              await store.api.uninstallStickerSet(set.id);
                              StickerCache.installed = null;
                              setSheet(() => set.installed = false);
                            },
                            child: const Text('移除这个贴纸包'),
                          )
                        : FilledButton(
                            onPressed: () async {
                              try {
                                await store.api.installStickerSet(set.id);
                                StickerCache.installed = null;
                                setSheet(() => set.installed = true);
                              } on ApiException catch (e) {
                                if (ctx.mounted) {
                                  ScaffoldMessenger.of(ctx).showSnackBar(SnackBar(content: Text(e.message)));
                                }
                              }
                            },
                            child: Text('添加 ${set.count} 张贴纸'),
                          ),
              ),
            ),
          ]),
        ),
      ),
    ),
  );
}

/// 我的贴纸:自己建的包(可以编辑)、添加了的别人的包(可以移除)。
class StickerSetsPage extends StatefulWidget {
  const StickerSetsPage({super.key});

  @override
  State<StickerSetsPage> createState() => _StickerSetsPageState();
}

class _StickerSetsPageState extends State<StickerSetsPage> {
  bool _loading = true;
  Object? _error;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      await StickerCache.load(force: true);
      if (mounted) setState(() => _loading = false);
    } catch (e) {
      if (mounted) {
        setState(() {
          _loading = false;
          _error = e;
        });
      }
    }
  }

  Future<void> _create() async {
    final c = TextEditingController();
    final title = await showDialog<String>(
      context: context,
      builder: (ctx) => SzDialog(
        title: const Text('新建贴纸包'),
        content: TextField(controller: c, autofocus: true, maxLength: 64, decoration: const InputDecoration(hintText: '起个名字')),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx), child: const Text('取消')),
          FilledButton(onPressed: () => Navigator.pop(ctx, c.text.trim()), child: const Text('建')),
        ],
      ),
    );
    c.dispose();
    if (title == null || title.isEmpty || !mounted) return;
    try {
      final s = await ChatStore.instance.api.createStickerSet(title);
      if (!mounted) return;
      await Navigator.of(context).push(MaterialPageRoute<void>(builder: (_) => StickerSetEditPage(setId: s.id)));
      await _load();
    } on ApiException catch (e) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(e.message)));
    }
  }

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    final installed = (StickerCache.installed ?? const <StickerSetInfo>[]).where((s) => !s.isMine && !s.isOfficial).toList();
    final created = StickerCache.created;
    return SzPageScaffold(
      appBar: AppBar(title: const Text('我的贴纸')),
      body: _loading
          ? const Center(child: CircularProgressIndicator())
          : _error != null
              ? SzError(error: _error, onRetry: _load)
              : ListView(children: [
                  Padding(
                    padding: const EdgeInsets.fromLTRB(kPagePad, 12, kPagePad, 4),
                    child: Text('我建的', style: TextStyle(color: sz.clay, fontWeight: FontWeight.w600)),
                  ),
                  for (final s in created)
                    ListTile(
                      leading: s.cover == null ? const Icon(Icons.image_outlined) : stickerImage(s.cover!, size: 40),
                      title: Text(s.title),
                      subtitle: Text('${s.count} 张'),
                      trailing: const Icon(Icons.chevron_right),
                      onTap: () async {
                        await Navigator.of(context).push(MaterialPageRoute<void>(builder: (_) => StickerSetEditPage(setId: s.id)));
                        await _load();
                      },
                    ),
                  ListTile(
                    leading: Icon(Icons.add_circle_outline, color: sz.clay),
                    title: Text('新建贴纸包', style: TextStyle(color: sz.clay)),
                    subtitle: const Text('用自己的图(PNG / WebP,透明底最好),一包最多 120 张'),
                    onTap: _create,
                  ),
                  const Divider(),
                  Padding(
                    padding: const EdgeInsets.fromLTRB(kPagePad, 8, kPagePad, 4),
                    child: Text('添加了的', style: TextStyle(color: sz.clay, fontWeight: FontWeight.w600)),
                  ),
                  if (installed.isEmpty)
                    Padding(
                      padding: const EdgeInsets.all(kPagePad),
                      child: Text('在聊天里点别人发的贴纸,就能把整包加进来', style: TextStyle(color: sz.inkMuted)),
                    ),
                  for (final s in installed)
                    ListTile(
                      leading: s.cover == null ? const Icon(Icons.image_outlined) : stickerImage(s.cover!, size: 40),
                      title: Text(s.title),
                      subtitle: Text('${s.count} 张'),
                      trailing: TextButton(
                        onPressed: () async {
                          await ChatStore.instance.api.uninstallStickerSet(s.id);
                          await _load();
                        },
                        child: const Text('移除'),
                      ),
                    ),
                ]),
    );
  }
}

/// 编辑自己的贴纸包:加图(从相册挑,每张配一个 emoji)、删图、改名、删包。
class StickerSetEditPage extends StatefulWidget {
  const StickerSetEditPage({super.key, required this.setId});

  final int setId;

  @override
  State<StickerSetEditPage> createState() => _StickerSetEditPageState();
}

class _StickerSetEditPageState extends State<StickerSetEditPage> {
  StickerSetInfo? _set;
  bool _busy = false;
  String _progress = '';

  ChatStore get _store => ChatStore.instance;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final s = await _store.api.stickerSet(widget.setId);
      if (mounted) setState(() => _set = s);
    } on ApiException catch (e) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(e.message)));
    }
  }

  void _toast(String s) {
    if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(s)));
  }

  Future<void> _add() async {
    final files = await ImagePicker().pickMultiImage(limit: 30);
    if (files.isEmpty || !mounted) return;
    final emoji = await _askEmoji('这几张配什么表情?(用来按表情找贴纸)');
    if (emoji == null) return;
    setState(() => _busy = true);
    var done = 0, failed = 0;
    for (final f in files) {
      setState(() => _progress = '上传中 ${done + failed + 1}/${files.length}');
      try {
        final m = await _store.client.uploadMediaBytes(await f.readAsBytes(), f.name, kind: 'sticker', purpose: 'sticker');
        await _store.api.addSticker(widget.setId, (m['id'] as num).toInt(), emoji);
        done++;
      } on ApiException catch (e) {
        failed++;
        _toast(e.message);
      }
    }
    StickerCache.installed = null;
    if (!mounted) return;
    setState(() {
      _busy = false;
      _progress = '';
    });
    if (failed > 0) _toast('加了 $done 张,$failed 张没加上');
    await _load();
  }

  Future<String?> _askEmoji(String title) async {
    const choices = ['🙂', '😂', '😍', '😭', '😡', '👍', '👌', '🙏', '🎉', '❤️', '😴', '🤔'];
    return szShowSheet<String>(
      context: context,
      builder: (ctx) => SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(kPagePad),
          child: Column(mainAxisSize: MainAxisSize.min, children: [
            Text(title),
            const SizedBox(height: 12),
            Wrap(spacing: 6, runSpacing: 6, children: [
              for (final e in choices)
                InkWell(
                  onTap: () => Navigator.pop(ctx, e),
                  borderRadius: BorderRadius.circular(8),
                  child: Padding(padding: const EdgeInsets.all(8), child: Text(e, style: const TextStyle(fontSize: kFigureMd))),
                ),
            ]),
          ]),
        ),
      ),
    );
  }

  Future<void> _rename() async {
    final s = _set;
    if (s == null) return;
    final c = TextEditingController(text: s.title);
    final t = await showDialog<String>(
      context: context,
      builder: (ctx) => SzDialog(
        title: const Text('改名'),
        content: TextField(controller: c, autofocus: true, maxLength: 64),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx), child: const Text('取消')),
          FilledButton(onPressed: () => Navigator.pop(ctx, c.text.trim()), child: const Text('保存')),
        ],
      ),
    );
    c.dispose();
    if (t == null || t.isEmpty) return;
    try {
      final n = await _store.api.renameStickerSet(s.id, t);
      StickerCache.installed = null;
      if (mounted) setState(() => _set!.title = n.title);
    } on ApiException catch (e) {
      _toast(e.message);
    }
  }

  Future<void> _deleteSet() async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => SzDialog(
        title: const Text('删除这个贴纸包?'),
        content: const Text('已经发出去的贴纸还在聊天里,只是点开看不到这个包了,别人也不能再添加。'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('取消')),
          FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('删除')),
        ],
      ),
    );
    if (ok != true) return;
    await _store.api.deleteStickerSet(widget.setId);
    StickerCache.installed = null;
    if (mounted) Navigator.pop(context);
  }

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    final s = _set;
    return SzPageScaffold(
      appBar: AppBar(
        title: Text(s?.title ?? '贴纸包'),
        actions: [
          if (s != null) IconButton(tooltip: '改名', icon: const Icon(Icons.edit_outlined), onPressed: _rename),
          if (s != null) IconButton(tooltip: '删除贴纸包', icon: const Icon(Icons.delete_outline), onPressed: _deleteSet),
        ],
      ),
      body: s == null
          ? const Center(child: CircularProgressIndicator())
          : Column(children: [
              if (_busy) LinearProgressIndicator(color: sz.clay),
              Padding(
                padding: const EdgeInsets.all(kPagePad),
                child: Text(
                  _busy ? _progress : '${s.count}/120 张 · 长按一张删掉。别人在聊天里点你的贴纸就能添加整包。',
                  style: TextStyle(fontSize: kFontNote, color: sz.inkMuted),
                ),
              ),
              Expanded(
                child: GridView.builder(
                  padding: const EdgeInsets.symmetric(horizontal: 12),
                  gridDelegate: const SliverGridDelegateWithMaxCrossAxisExtent(maxCrossAxisExtent: 96, mainAxisSpacing: 8, crossAxisSpacing: 8),
                  itemCount: s.stickers.length + (s.count < 120 ? 1 : 0),
                  itemBuilder: (_, i) {
                    if (i == s.stickers.length) {
                      return InkWell(
                        onTap: _busy ? null : _add,
                        borderRadius: BorderRadius.circular(12),
                        child: Container(
                          decoration: BoxDecoration(
                            border: Border.all(color: sz.line),
                            borderRadius: BorderRadius.circular(12),
                          ),
                          child: Icon(Icons.add_photo_alternate_outlined, color: sz.clay),
                        ),
                      );
                    }
                    final st = s.stickers[i];
                    return GestureDetector(
                      onLongPress: () async {
                        final del = await showDialog<bool>(
                          context: context,
                          builder: (ctx) => SzDialog(
                            title: const Text('删掉这张?'),
                            actions: [
                              TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('取消')),
                              FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('删掉')),
                            ],
                          ),
                        );
                        if (del != true) return;
                        await _store.api.removeSticker(s.id, st.id);
                        StickerCache.installed = null;
                        await _load();
                      },
                      child: Stack(children: [
                        Positioned.fill(child: stickerImage(st, size: 88)),
                        Positioned(right: 2, bottom: 2, child: Text(st.emoji)),
                      ]),
                    );
                  },
                ),
              ),
            ]),
    );
  }
}
