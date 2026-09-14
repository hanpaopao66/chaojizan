import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';
import 'package:url_launcher/url_launcher.dart';

import '../../session.dart';
import '../models.dart';
import '../ui/tags_badges.dart';

/// 「标签和勋章」(消息设置 → 我的资料):改标签;整组标签、每一枚勋章能不能被别人看到。
///
/// 勋章那一组把**全部**勋章都列出来,拿到没拿到都在,每一枚写着服务端给的发放条件
/// (`GET /social/v1/me/tags-badges`,和透明中心是同一份定义),这里不另写一份。
///
/// 开关一律「打开 = 别人看得到」:标签那一个、每枚勋章各一个,方向一致,不用每个都想一遍。
class TagsBadgesPage extends StatefulWidget {
  const TagsBadgesPage({super.key, this.client});

  /// 测试里传一个假的;缺省用全局那个(登录态在它身上)
  final ApiClient? client;

  @override
  State<TagsBadgesPage> createState() => _TagsBadgesPageState();
}

class _TagsBadgesPageState extends State<TagsBadgesPage> {
  final _input = TextEditingController();
  Map<String, dynamic>? _data;
  Object? _error;
  bool _busy = false;

  ApiClient get _api => widget.client ?? rootApi;

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    _input.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    try {
      final d = (await _api.requestJson('GET', '/social/v1/me/tags-badges') as Map).cast<String, dynamic>();
      if (mounted) {
        setState(() {
          _data = d;
          _error = null;
        });
      }
    } catch (e) {
      if (mounted) setState(() => _error = e);
    }
  }

  /// 成功返回 true。服务端不收(屏蔽词、像平台标志)时把它那句话原样提示出来
  Future<bool> _patch(Map<String, dynamic> body) async {
    setState(() => _busy = true);
    try {
      final d = (await _api.requestJson('PATCH', '/social/v1/me/tags-badges', body: body) as Map)
          .cast<String, dynamic>();
      if (mounted) setState(() => _data = d);
      return true;
    } on ApiException catch (e) {
      _toast(e.message);
      return false;
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  /// 连着试几个都不行时,新的一句顶掉旧的,不排队等上一条消失
  void _toast(String s) {
    if (!mounted) return;
    ScaffoldMessenger.of(context)
      ..hideCurrentSnackBar()
      ..showSnackBar(SnackBar(content: Text(s)));
  }

  List<String> get _tags => [for (final t in (_data?['tags'] as List? ?? const [])) '$t'];
  int get _max => (_data?['tags_max'] as num?)?.toInt() ?? 5;
  int get _maxLen => (_data?['tag_max_len'] as num?)?.toInt() ?? 8;

  /// 和服务端同一个规整:去掉首尾空白、中间连续空白并成一个;重复不分大小写
  static String _norm(String s) => s.trim().split(RegExp(r'\s+')).where((x) => x.isNotEmpty).join(' ');

  /// 本地先挡掉一眼能看出来的(空、重复、满了),省一个来回;屏蔽词、冒充平台标志由服务端判
  Future<void> _addTag() async {
    final t = _norm(_input.text);
    String? problem;
    if (t.isEmpty) {
      problem = '先写一个标签';
    } else if (t.length > _maxLen) {
      problem = '每个标签最多 $_maxLen 个字';
    } else if (_tags.any((x) => x.toLowerCase() == t.toLowerCase())) {
      problem = '已经有「$t」了';
    } else if (_tags.length >= _max) {
      problem = '标签最多 $_max 个';
    }
    if (problem != null) {
      _toast(problem);
      return;
    }
    if (await _patch({'tags': [..._tags, t]})) _input.clear();
  }

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    final d = _data;
    if (d == null) {
      return SzPageScaffold(
        appBar: AppBar(title: const Text('标签和勋章')),
        body: _error != null
            ? SzError(error: _error, onRetry: () {
                setState(() => _error = null);
                _load();
              })
            : const Center(child: CircularProgressIndicator()),
      );
    }
    final tags = _tags;
    final tagsHidden = d['tags_hidden'] == true;
    final badges = [for (final b in (d['badges'] as List? ?? const [])) ProfileBadge.fromJson(b)];
    return SzPageScaffold(
      appBar: AppBar(title: const Text('标签和勋章')),
      body: ListView(padding: const EdgeInsets.symmetric(horizontal: kPagePad, vertical: 8), children: [
        SzEntryGroup(
          title: '标签',
          footnote: '自己写,最多 $_max 个、每个 1–$_maxLen 个字。和昵称、签名一样,别人在你的资料页和 UP 主空间里都看得到。',
          children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(kCardPad, 12, kCardPad, 4),
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                if (tags.isEmpty)
                  Text('还没有标签', style: TextStyle(fontSize: kFontNote, color: sz.inkMuted))
                else
                  Wrap(spacing: 6, runSpacing: 4, children: [
                    for (final t in tags)
                      InputChip(
                        label: Text(t),
                        onDeleted: _busy ? null : () => _patch({'tags': [for (final x in tags) if (x != t) x]}),
                        deleteButtonTooltipMessage: '删掉「$t」',
                      ),
                  ]),
                if (tags.length < _max)
                  Row(children: [
                    Expanded(
                      child: TextField(
                        controller: _input,
                        maxLength: _maxLen,
                        decoration: const InputDecoration(hintText: '加一个标签,比如:川菜、夜猫子', counterText: ''),
                        onSubmitted: (_) => _addTag(),
                      ),
                    ),
                    const SizedBox(width: 8),
                    OutlinedButton(onPressed: _busy ? null : _addTag, child: const Text('添加')),
                  ])
                else
                  Padding(
                    padding: const EdgeInsets.symmetric(vertical: 8),
                    child: Text('已经 $_max 个了,删掉一个才能再加',
                        style: TextStyle(fontSize: kFontNote, color: sz.inkMuted)),
                  ),
              ]),
            ),
            SzEntryTile(
              title: '别人看得到我的标签',
              hint: tagsHidden ? '已隐藏,只有你自己看得到' : null,
              dense: true,
              trailing: Switch(
                value: !tagsHidden,
                onChanged: _busy ? null : (v) => _patch({'tags_hidden': !v}),
              ),
            ),
          ],
        ),
        SzEntryGroup(
          title: '勋章',
          footnote: '平台按公开的条件自动发,不能买、不能申请;条件不再满足就不再显示。'
              '开关打开的,别人在你的资料页和 UP 主空间里看得到。',
          children: [
            for (final b in badges)
              _BadgeRow(
                badge: b,
                onTap: () => showBadgeCondition(context, b),
                onShow: _busy ? null : (show) => _patch({'hidden_badges': {b.key: !show}}),
              ),
            SzEntryTile(
              title: '勋章怎么发',
              icon: Icons.open_in_new,
              hint: '透明中心:每一枚的条件、按什么算、哪些不算',
              dense: true,
              onTap: () => launchUrl(Uri.parse('${_api.baseUrl}/transparency#badges'),
                  mode: LaunchMode.externalApplication),
            ),
          ],
        ),
        const SizedBox(height: 12),
        Text('隐藏了的只有你自己在资料页上看得到(标着「已隐藏」);别人看到的和没有一样,看不出你藏了什么。',
            style: TextStyle(fontSize: kFontMicro, height: 1.5, color: sz.inkMuted)),
      ]),
    );
  }
}

/// 勋章一行:小方块字、名字、发放条件;拿到了的右边是「别人看得到」开关,没拿到的写「还没有」。
///
/// 条件是**判断依据**不是说明(还没拿到的人正是要看它),所以给两行,不收成一行 hint。
class _BadgeRow extends StatelessWidget {
  const _BadgeRow({required this.badge, required this.onTap, required this.onShow});

  final ProfileBadge badge;
  final VoidCallback onTap;
  final ValueChanged<bool>? onShow;

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    return InkWell(
      onTap: onTap,
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: kCardPad, vertical: 10),
        child: Row(children: [
          ExcludeSemantics(child: BadgeGlyph(badge.icon, size: 28, muted: !badge.earned)),
          const SizedBox(width: 12),
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisSize: MainAxisSize.min, children: [
              Text(badge.earned && badge.hidden ? '${badge.name} · 已隐藏' : badge.name,
                  style: TextStyle(fontSize: kFontBodyLg, color: badge.earned ? sz.ink : sz.inkMuted)),
              const SizedBox(height: 2),
              Text(badge.condition,
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                  style: TextStyle(fontSize: kFontNote, height: 1.4, color: sz.inkMuted)),
            ]),
          ),
          const SizedBox(width: 8),
          if (badge.earned)
            Switch(value: !badge.hidden, onChanged: onShow)
          else
            Text('还没有', style: TextStyle(fontSize: kFontNote, color: sz.inkMuted)),
        ]),
      ),
    );
  }
}
