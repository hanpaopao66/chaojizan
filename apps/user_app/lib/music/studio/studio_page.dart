// 音乐人中心(§8.2 /music/v1/studio)。
//
// 没开通时整页是开通表单:艺名、简介、曲风。**不要求实名**(§4 M2,用户拍板)——
// 这里不问身份证、不审主页,冒充走举报。表单上写明「上传的必须是原创或已获授权」,
// 因为这才是真正的门槛:平台不接商业曲库,也不做搬运平台(§4 M1)。
//
// 开通之后是数据卡 + 按状态分组的作品列表。
import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';

import '../../session.dart';
import '../../video/me/common.dart';
import '../../video/models.dart';
import '../models.dart';
import '../nav.dart';
import '../widgets/common.dart';
import 'artist_edit_page.dart';
import 'release_edit_page.dart';
import 'studio_rules.dart';

class MusicStudioPage extends StatefulWidget {
  const MusicStudioPage({super.key});

  @override
  State<MusicStudioPage> createState() => _MusicStudioPageState();
}

class _MusicStudioPageState extends State<MusicStudioPage> {
  final _key = GlobalKey<MLoaderState<MArtist?>>();

  @override
  Widget build(BuildContext context) {
    if (!rootApi.isLoggedIn) {
      return SzPageScaffold(
        appBar: AppBar(title: const Text('音乐人中心')),
        body: SzRefreshableEmpty(
          onRefresh: () async => setState(() {}),
          child: VideoLoginGate(text: '登录后可以开通音乐人,发自己的歌', onLoggedIn: () => setState(() {})),
        ),
      );
    }
    return SzPageScaffold(
      contentMaxWidth: kFeedMaxWidth,
      appBar: AppBar(title: const Text('音乐人中心')),
      body: MLoader<MArtist?>(
        key: _key,
        load: () => musicApi.studioMe(),
        builder: (context, artist, reload) =>
            artist == null ? _OpenForm(onOpened: reload) : _StudioBody(artist: artist, onChanged: reload),
      ),
    );
  }
}

/// 开通音乐人的表单。
class _OpenForm extends StatefulWidget {
  const _OpenForm({required this.onOpened});

  final Future<void> Function() onOpened;

  @override
  State<_OpenForm> createState() => _OpenFormState();
}

class _OpenFormState extends State<_OpenForm> {
  final _name = TextEditingController();
  final _bio = TextEditingController();
  final Set<String> _genres = {};
  List<MGenre> _all = [];
  bool _agreed = false;
  bool _busy = false;
  String? _nameError;
  String? _bioError;

  @override
  void initState() {
    super.initState();
    musicApi.genres().then((g) {
      if (mounted) setState(() => _all = g);
    }).catchError((Object _) {
      // 曲风表拉不到不挡着开通:曲风本来就是可选的
    });
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
    return ListView(
      padding: const EdgeInsets.all(kPagePad),
      children: [
        Text('开通音乐人', style: TextStyle(fontSize: kFontLead, color: sz.ink, fontWeight: FontWeight.w600)),
        const SizedBox(height: 6),
        Text('用你现在的超级赞账号就行,不要求实名。开通之后可以传自己的歌、发单曲 / EP / 专辑。',
            style: TextStyle(fontSize: kFontBody, color: sz.inkMuted, height: 1.6)),
        const SizedBox(height: 18),
        TextField(
          controller: _name,
          maxLength: 30,
          decoration: InputDecoration(
            labelText: '艺名',
            hintText: '别人在歌曲下面看到的名字',
            errorText: _nameError,
            border: const OutlineInputBorder(),
          ),
          onChanged: (v) {
            final e = validateArtistName(v);
            if (e != _nameError) setState(() => _nameError = e);
          },
        ),
        const SizedBox(height: 12),
        TextField(
          controller: _bio,
          maxLength: 300,
          minLines: 3,
          maxLines: 6,
          decoration: InputDecoration(
            labelText: '简介(可以不填)',
            errorText: _bioError,
            border: const OutlineInputBorder(),
          ),
          onChanged: (v) {
            final e = validateArtistBio(v);
            if (e != _bioError) setState(() => _bioError = e);
          },
        ),
        const SizedBox(height: 14),
        Text('你做的是哪几类(可以不选)', style: TextStyle(fontSize: kFontBodyLg, color: sz.ink)),
        const SizedBox(height: 8),
        if (_all.isEmpty)
          Text('曲风表还没拉到,开通之后在资料里也能补', style: TextStyle(fontSize: kFontNote, color: sz.inkFaint))
        else
          Wrap(spacing: 8, runSpacing: 8, children: [
            for (final g in _all)
              SzChip(
                g.name,
                selected: _genres.contains(g.key),
                onTap: () => setState(() => _genres.contains(g.key) ? _genres.remove(g.key) : _genres.add(g.key)),
              ),
          ]),
        const SizedBox(height: 18),
        Container(
          padding: const EdgeInsets.all(kCardPad),
          decoration: BoxDecoration(
            color: sz.surfaceAlt,
            borderRadius: BorderRadius.circular(kRadiusMd),
            border: Border.all(color: sz.line),
          ),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text('上传的必须是原创或已获授权的作品',
                style: TextStyle(fontSize: kFontBodyLg, color: sz.ink, fontWeight: FontWeight.w600)),
            const SizedBox(height: 6),
            Text(
              '这里不接商业曲库,也不做搬运平台。每首歌上传时都要勾「原创」或「已获授权」;'
              '被举报侵权会下架并留记录,反复侵权会停用音乐人身份。',
              style: TextStyle(fontSize: kFontNote, color: sz.inkMuted, height: 1.6),
            ),
          ]),
        ),
        CheckboxListTile(
          value: _agreed,
          onChanged: (v) => setState(() => _agreed = v == true),
          contentPadding: EdgeInsets.zero,
          controlAffinity: ListTileControlAffinity.leading,
          title: Text('我确认,我上传的作品是我原创的或者我已获得授权',
              style: TextStyle(fontSize: kFontBody, color: sz.ink)),
        ),
        const SizedBox(height: 6),
        SizedBox(
          width: double.infinity,
          child: FilledButton(
            onPressed: _busy ? null : _submit,
            child: _busy
                ? const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2))
                : const Text('开通'),
          ),
        ),
      ],
    );
  }

  Future<void> _submit() async {
    final nameError = validateArtistName(_name.text);
    final bioError = validateArtistBio(_bio.text);
    setState(() {
      _nameError = nameError;
      _bioError = bioError;
    });
    if (nameError != null || bioError != null) return;
    if (!_agreed) {
      mToast(context, '请先确认作品是原创或已获授权');
      return;
    }
    setState(() => _busy = true);
    try {
      await musicApi.openArtist(name: _name.text.trim(), bio: _bio.text.trim(), genres: _genres.toList());
      await widget.onOpened();
    } catch (e) {
      if (mounted) {
        // 艺名撞车这类由服务端判,原话摆在输入框下面比弹一下更容易看见
        setState(() => _nameError = musicErrorText(e));
      }
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }
}

/// 开通之后:数据卡 + 按状态分组的作品列表。
class _StudioBody extends StatefulWidget {
  const _StudioBody({required this.artist, required this.onChanged});

  final MArtist artist;
  final Future<void> Function() onChanged;

  @override
  State<_StudioBody> createState() => _StudioBodyState();
}

class _StudioBodyState extends State<_StudioBody> {
  MStudioStats? _stats;
  List<MRelease>? _releases;
  Object? _error;

  /// 状态分组的顺序:要动手的排前面(被驳回的、草稿),已发布的排后面
  static const _groups = [
    (status: 'rejected', name: '未通过'),
    (status: 'draft', name: '草稿'),
    (status: 'reviewing', name: '审核中'),
    (status: 'published', name: '已发布'),
    (status: 'withdrawn', name: '已下架'),
    (status: 'removed', name: '被下架'),
  ];

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final r = await Future.wait<Object>([musicApi.studioStats(), musicApi.studioReleases()]);
      if (!mounted) return;
      setState(() {
        _stats = r[0] as MStudioStats;
        _releases = r[1] as List<MRelease>;
        _error = null;
      });
    } catch (e) {
      if (mounted) setState(() => _error = e);
    }
  }

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    final a = widget.artist;
    final releases = _releases;
    return ListView(
      padding: const EdgeInsets.only(bottom: 24),
      children: [
        ListTile(
          leading: SzImage(url: a.avatar.isEmpty ? '' : musicResolve(a.avatar), name: a.name, size: 48, circle: true),
          title: Row(children: [
            Flexible(child: Text(a.name, maxLines: 1, overflow: TextOverflow.ellipsis)),
            if (a.suspended) ...[const SizedBox(width: 6), VTag('已停用', color: sz.danger)],
          ]),
          subtitle: Text('${vCount(a.fans)} 粉丝 · ${a.trackCount} 首歌',
              style: TextStyle(fontSize: kFontNote, color: sz.inkMuted)),
          trailing: TextButton(
            onPressed: () async {
              await Navigator.of(context).push(MaterialPageRoute<void>(builder: (_) => MusicArtistEditPage(artist: a)));
              await widget.onChanged();
            },
            child: const Text('改资料'),
          ),
          onTap: () => openArtist(context, a.aid),
        ),
        if (a.suspended)
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: kPagePad),
            child: SzRetryBanner(
              text: '音乐人身份已被停用,现在不能提交新作品。如果你认为判错了,在被下架的作品里申诉。',
              onRetry: () => setState(() {}),
            ),
          ),
        if (_stats != null) _StatsCard(stats: _stats!),
        if (_error != null && releases == null)
          Padding(padding: const EdgeInsets.only(top: 24), child: musicErrorView(_error, _load))
        else if (releases == null)
          const Padding(padding: EdgeInsets.all(40), child: Center(child: CircularProgressIndicator()))
        else ...[
          MSection('我的作品', onMore: a.suspended ? null : () => _create(), moreLabel: '建新作品'),
          if (releases.isEmpty)
            Padding(
              padding: const EdgeInsets.fromLTRB(kPagePad, 8, kPagePad, 8),
              child: Text('还没有作品。点右上角建一个,传上歌、加封面,就能提交审核。',
                  style: TextStyle(fontSize: kFontNote, color: sz.inkMuted, height: 1.6)),
            ),
          for (final g in _groups) ...[
            if (releases.any((r) => r.status == g.status)) ...[
              Padding(
                padding: const EdgeInsets.fromLTRB(kPagePad, 14, kPagePad, 4),
                child: Text(g.name, style: TextStyle(fontSize: kFontNote, color: sz.inkMuted)),
              ),
              for (final r in releases.where((r) => r.status == g.status)) _ReleaseRow(release: r, onChanged: _reloadAll),
            ],
          ],
          // 状态是空的或者对不上分组的(服务端加了新状态)也要露出来,不能凭空消失
          for (final r in releases.where((r) => !_groups.any((g) => g.status == r.status)))
            _ReleaseRow(release: r, onChanged: _reloadAll),
        ],
      ],
    );
  }

  Future<void> _reloadAll() async {
    await _load();
    await widget.onChanged();
  }

  Future<void> _create() async {
    final made = await Navigator.of(context).push<bool>(
      MaterialPageRoute<bool>(builder: (_) => const MusicReleaseEditPage()),
    );
    if (made == true) await _reloadAll();
  }
}

class _StatsCard extends StatelessWidget {
  const _StatsCard({required this.stats});

  final MStudioStats stats;

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    Widget cell(String label, int value) => Expanded(
          child: Column(children: [
            Text(vCount(value), style: szFigure(fontSize: kFigureMd, fontWeight: FontWeight.w600, color: sz.ink)),
            const SizedBox(height: 2),
            Text(label, style: TextStyle(fontSize: kFontMicro, color: sz.inkMuted)),
          ]),
        );
    return Padding(
      padding: const EdgeInsets.fromLTRB(kPagePad, 6, kPagePad, 0),
      child: SzCard(
        child: Padding(
          padding: const EdgeInsets.all(kCardPad),
          child: Column(children: [
            Row(children: [
              cell('近 30 天播放', stats.plays),
              cell('听过的人', stats.listeners),
              cell('喜欢', stats.likes),
              cell('粉丝', stats.fans),
            ]),
            if (stats.topTracks.isNotEmpty) ...[
              const SizedBox(height: 10),
              Divider(height: 1, color: sz.line),
              const SizedBox(height: 8),
              Align(
                alignment: Alignment.centerLeft,
                child: Text('播放最多', style: TextStyle(fontSize: kFontNote, color: sz.inkMuted)),
              ),
              for (final t in stats.topTracks.take(3))
                Padding(
                  padding: const EdgeInsets.symmetric(vertical: 2),
                  child: Row(children: [
                    Expanded(
                      child: Text(t.title,
                          maxLines: 1, overflow: TextOverflow.ellipsis, style: TextStyle(fontSize: kFontBody, color: sz.ink)),
                    ),
                    Text('${vCount(t.plays)} 次', style: TextStyle(fontSize: kFontNote, color: sz.inkMuted)),
                  ]),
                ),
            ],
          ]),
        ),
      ),
    );
  }
}

class _ReleaseRow extends StatelessWidget {
  const _ReleaseRow({required this.release, required this.onChanged});

  final MRelease release;
  final Future<void> Function() onChanged;

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    final bad = release.status == 'rejected' || release.status == 'removed';
    return ListTile(
      leading: MCover(url: release.cover, name: release.title, size: 48),
      title: Row(children: [
        Flexible(child: Text(release.title, maxLines: 1, overflow: TextOverflow.ellipsis)),
        const SizedBox(width: 6),
        VTag(mReleaseStatusName(release.status), color: bad ? sz.danger : null),
      ]),
      subtitle: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text('${mReleaseKindName(release.kind)} · ${release.trackCount} 首',
            style: TextStyle(fontSize: kFontNote, color: sz.inkMuted)),
        if (bad && (release.rejectNote.isNotEmpty || release.rejectCode.isNotEmpty))
          Text(
            // 驳回 / 下架的原因摆在列表里就能看见,不用点进去才知道为什么
            [release.rejectCode, release.rejectNote].where((s) => s.isNotEmpty).join(' '),
            maxLines: 2,
            overflow: TextOverflow.ellipsis,
            style: TextStyle(fontSize: kFontNote, color: sz.danger, height: 1.5),
          ),
      ]),
      onTap: () async {
        await Navigator.of(context)
            .push<bool>(MaterialPageRoute<bool>(builder: (_) => MusicReleaseEditPage(rid: release.rid)));
        await onChanged();
      },
    );
  }
}
