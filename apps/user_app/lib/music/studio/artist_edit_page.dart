// 音乐人资料:艺名、简介、曲风、头像、横幅(§8.2 PATCH /studio/artist)。
import 'package:flutter/material.dart';
import 'package:image_picker/image_picker.dart';
import 'package:superz_shared/superz_shared.dart';

import '../models.dart';
import '../nav.dart';
import '../widgets/common.dart';
import 'studio_rules.dart';

class MusicArtistEditPage extends StatefulWidget {
  const MusicArtistEditPage({super.key, required this.artist});

  final MArtist artist;

  @override
  State<MusicArtistEditPage> createState() => _MusicArtistEditPageState();
}

class _MusicArtistEditPageState extends State<MusicArtistEditPage> {
  late final TextEditingController _name = TextEditingController(text: widget.artist.name);
  late final TextEditingController _bio = TextEditingController(text: widget.artist.bio);
  late final Set<String> _genres = {...widget.artist.genres};
  late String _avatar = widget.artist.avatar;
  late String _cover = widget.artist.cover;
  List<MGenre> _all = [];
  bool _busy = false;
  String? _nameError;
  String? _bioError;

  @override
  void initState() {
    super.initState();
    musicApi.genres().then((g) {
      if (mounted) setState(() => _all = g);
    }).catchError((Object _) {});
  }

  @override
  void dispose() {
    _name.dispose();
    _bio.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    return SzPageScaffold(
      appBar: AppBar(
        title: const Text('音乐人资料'),
        actions: [
          TextButton(onPressed: _busy ? null : _save, child: const Text('保存')),
        ],
      ),
      body: ListView(
        padding: const EdgeInsets.all(kPagePad),
        children: [
          Row(children: [
            InkWell(
              onTap: () => _pickImage(avatar: true),
              child: Stack(alignment: Alignment.bottomRight, children: [
                SzImage(
                    url: _avatar.isEmpty ? '' : musicResolve(_avatar),
                    name: _name.text.isEmpty ? widget.artist.name : _name.text,
                    size: 72,
                    circle: true),
                CircleAvatar(radius: 12, backgroundColor: sz.clay, child: Icon(Icons.edit, size: 13, color: sz.paper)),
              ]),
            ),
            const SizedBox(width: 14),
            Expanded(
              child: OutlinedButton.icon(
                onPressed: () => _pickImage(avatar: false),
                icon: const Icon(Icons.image_outlined, size: 18),
                label: Text(_cover.isEmpty ? '设置主页横幅' : '换一张横幅'),
              ),
            ),
          ]),
          const SizedBox(height: 18),
          TextField(
            controller: _name,
            maxLength: 30,
            decoration: InputDecoration(labelText: '艺名', errorText: _nameError, border: const OutlineInputBorder()),
            onChanged: (v) {
              final e = validateArtistName(v);
              setState(() => _nameError = e);
            },
          ),
          const SizedBox(height: 12),
          TextField(
            controller: _bio,
            maxLength: 300,
            minLines: 3,
            maxLines: 6,
            decoration: InputDecoration(labelText: '简介', errorText: _bioError, border: const OutlineInputBorder()),
            onChanged: (v) => setState(() => _bioError = validateArtistBio(v)),
          ),
          const SizedBox(height: 14),
          Text('曲风', style: TextStyle(fontSize: kFontBodyLg, color: sz.ink)),
          const SizedBox(height: 8),
          Wrap(spacing: 8, runSpacing: 8, children: [
            for (final g in _all)
              SzChip(
                g.name,
                selected: _genres.contains(g.key),
                onTap: () => setState(() => _genres.contains(g.key) ? _genres.remove(g.key) : _genres.add(g.key)),
              ),
          ]),
          const SizedBox(height: 18),
          Text('这里不要求实名。别人怀疑你冒充,走举报核实。',
              style: TextStyle(fontSize: kFontNote, color: sz.inkFaint, height: 1.6)),
        ],
      ),
    );
  }

  Future<void> _pickImage({required bool avatar}) async {
    try {
      final x = await ImagePicker().pickImage(
        source: ImageSource.gallery,
        maxWidth: avatar ? 720 : 1600,
        imageQuality: 85,
      );
      if (x == null || !mounted) return;
      setState(() => _busy = true);
      final url = await musicApi.uploadPublicImage(await x.readAsBytes(), x.name);
      if (!mounted) return;
      setState(() {
        if (avatar) {
          _avatar = url;
        } else {
          _cover = url;
        }
      });
    } catch (e) {
      if (mounted) mToast(context, e);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _save() async {
    final nameError = validateArtistName(_name.text);
    final bioError = validateArtistBio(_bio.text);
    setState(() {
      _nameError = nameError;
      _bioError = bioError;
    });
    if (nameError != null || bioError != null) return;
    setState(() => _busy = true);
    try {
      await musicApi.patchArtist(
        name: _name.text.trim(),
        bio: _bio.text.trim(),
        genres: _genres.toList(),
        avatarUrl: _avatar,
        coverUrl: _cover,
      );
      if (mounted) Navigator.pop(context);
    } catch (e) {
      if (mounted) setState(() => _nameError = musicErrorText(e));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }
}
