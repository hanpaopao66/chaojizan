import 'package:flutter/material.dart';
import 'package:image_picker/image_picker.dart';
import 'package:superz_shared/superz_shared.dart';

import '../chat_page.dart';
import '../store.dart';
import '../ui/avatar.dart';

/// 建群 / 建频道:名称、简介、头像(成员在上一步选好了)。
class NewChatPage extends StatefulWidget {
  const NewChatPage({super.key, required this.type, this.memberIds = const []});

  /// group / channel
  final String type;
  final List<int> memberIds;

  @override
  State<NewChatPage> createState() => _NewChatPageState();
}

class _NewChatPageState extends State<NewChatPage> {
  final _title = TextEditingController();
  final _about = TextEditingController();
  String _photo = '';
  bool _busy = false;

  bool get _channel => widget.type == 'channel';

  @override
  void dispose() {
    _title.dispose();
    _about.dispose();
    super.dispose();
  }

  Future<void> _pickPhoto() async {
    final f = await ImagePicker().pickImage(source: ImageSource.gallery, maxWidth: 1024, imageQuality: 88);
    if (f == null) return;
    setState(() => _busy = true);
    try {
      final m = await ChatStore.instance.client
          .uploadMediaBytes(await f.readAsBytes(), f.name, kind: 'chat_photo', purpose: 'chat_photo');
      setState(() => _photo = '${m['public_url'] ?? ''}');
    } on ApiException catch (e) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(e.message)));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _create() async {
    final title = _title.text.trim();
    if (title.isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(_channel ? '给频道起个名字' : '给群起个名字')));
      return;
    }
    setState(() => _busy = true);
    final store = ChatStore.instance;
    try {
      final (chat, skipped) = await store.api.createChat(widget.type, title,
          about: _about.text.trim(), memberIds: widget.memberIds);
      var c = chat;
      if (_photo.isNotEmpty) {
        c = await store.api.patchChat(chat.id, {'photo': _photo});
      }
      store.putChat(c);
      if (!mounted) return;
      if (skipped.isNotEmpty) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(
            content: Text('有 ${skipped.length} 人设置了不让直接拉进群,在群资料里把邀请链接发给他们')));
      }
      Navigator.of(context).pop();
      await openChat(context, c.id);
    } on ApiException catch (e) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(e.message)));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    return SzPageScaffold(
      appBar: AppBar(
        title: Text(_channel ? '新建频道' : '新建群组'),
        actions: [TextButton(onPressed: _busy ? null : _create, child: const Text('创建'))],
      ),
      body: ListView(padding: const EdgeInsets.all(kPagePad), children: [
        Row(children: [
          GestureDetector(
            onTap: _busy ? null : _pickPhoto,
            child: _photo.isEmpty
                ? CircleAvatar(radius: 32, backgroundColor: sz.claySoft, child: Icon(Icons.add_a_photo_outlined, color: sz.clay))
                : ChatAvatar(name: _title.text, url: _photo, size: 64),
          ),
          const SizedBox(width: 14),
          Expanded(
            child: TextField(
              controller: _title,
              autofocus: true,
              maxLength: 128,
              decoration: InputDecoration(labelText: _channel ? '频道名称' : '群名称'),
              onChanged: (_) => setState(() {}),
            ),
          ),
        ]),
        TextField(
          controller: _about,
          maxLength: 255,
          maxLines: 3,
          decoration: const InputDecoration(labelText: '简介(可选)'),
        ),
        const SizedBox(height: 8),
        Text(
          _channel
              ? '频道只有管理员能发帖,订阅的人只能看和回应。建好之后在资料页里可以设成公开频道。'
              : '已选 ${widget.memberIds.length} 位成员。群最多 1000 人;建好之后可以生成邀请链接。',
          style: TextStyle(fontSize: kFontNote, color: sz.inkMuted),
        ),
      ]),
    );
  }
}
