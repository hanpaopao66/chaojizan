import 'dart:async';

import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';

import '../../session.dart';
import '../models.dart';
import '../nav.dart';
import 'common.dart';
import 'me_format.dart';

/// 我的硬币(#366,D13):余额、今天领没领、流水。
///
/// 硬币是纯积分:只能投给视频,不能充值、提现、兑换(S4)。这句话放在最上面,
/// 不藏在说明里 —— 「硬币」两个字很容易让人以为能换钱。
class CoinsPage extends StatefulWidget {
  const CoinsPage({super.key});

  @override
  State<CoinsPage> createState() => _CoinsPageState();
}

class _CoinsPageState extends State<CoinsPage> {
  late final CursorPager<Map<String, dynamic>> _pager = CursorPager((cursor) async {
    final m = await videoApi.coins(cursor: cursor);
    return (items: [for (final x in vList(m['items'])) vMap(x)], next: m['next_cursor'] as String?, extra: m);
  });

  bool _claiming = false;

  @override
  void initState() {
    super.initState();
    if (rootApi.isLoggedIn) unawaited(_pager.refresh());
  }

  @override
  void dispose() {
    _pager.dispose();
    super.dispose();
  }

  Future<void> _claim() async {
    setState(() => _claiming = true);
    try {
      final r = await videoApi.claimDailyCoin();
      await _pager.refresh();
      if (mounted) vToast(context, r['granted'] == true ? '领到 1 枚硬币' : '今天已经领过了');
    } catch (e) {
      if (mounted) vToast(context, e);
    } finally {
      if (mounted) setState(() => _claiming = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    if (!rootApi.isLoggedIn) {
      return SzPageScaffold(
        appBar: AppBar(title: const Text('我的硬币')),
        body: VideoLoginGate(text: '登录后领硬币、给喜欢的视频投币', onLoggedIn: () => setState(() => _pager.refresh())),
      );
    }
    return SzPageScaffold(
      appBar: AppBar(title: const Text('我的硬币')),
      body: PagedListView<Map<String, dynamic>>(
        pager: _pager,
        header: [_head(), const VSection('明细')],
        emptyText: '还没有硬币流水',
        itemBuilder: (context, it, _) => _row(it),
      ),
    );
  }

  Widget _head() {
    return AnimatedBuilder(
      animation: _pager,
      builder: (context, _) {
        final sz = Theme.of(context).sz;
        final loaded = _pager.loaded;
        final coins = vInt(_pager.extra['coins']);
        final claimed = _pager.extra['today_claimed'] == true;
        return Padding(
          padding: const EdgeInsets.fromLTRB(kPagePad, 12, kPagePad, 0),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            const PledgeCard(
              title: '硬币只能投给视频,不能充值、提现、兑换',
              body: '它买不了任何东西,也换不成钱。来源只有两个:每天第一次打开视频 +1;投稿审核通过 +2(每天最多 10 枚)。'
                  '投出去的硬币归那个视频的 UP 主;自制视频每人最多投 2 枚、转载 1 枚。',
            ),
            const SizedBox(height: 12),
            SzCard(
              child: Row(children: [
                Expanded(
                  child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    Text('余额', style: TextStyle(fontSize: kFontNote, color: sz.inkMuted)),
                    const SizedBox(height: 2),
                    Text(loaded ? '$coins' : '—', style: szFigure(fontSize: kFigureLg, fontWeight: FontWeight.w600, color: sz.ink)),
                    const SizedBox(height: 2),
                    Text(!loaded ? '' : (claimed ? '今天的 1 枚已经领了' : '今天的 1 枚还没领'),
                        style: TextStyle(fontSize: kFontNote, color: sz.inkMuted)),
                  ]),
                ),
                if (loaded && !claimed)
                  FilledButton(onPressed: _claiming ? null : _claim, child: Text(_claiming ? '领取中…' : '领今天的')),
              ]),
            ),
          ]),
        );
      },
    );
  }

  Widget _row(Map<String, dynamic> it) {
    final sz = Theme.of(context).sz;
    final d = vInt(it['delta']);
    final video = it['video'] is Map ? vMap(it['video']) : null;
    final at = DateTime.tryParse('${it['created_at'] ?? ''}')?.toLocal();
    final sub = [
      if (video != null) '《${video['title'] ?? ''}》',
      if (at != null) vDateTime(at),
    ].join(' · ');
    return ListTile(
      title: Text(coinReason(it)),
      subtitle: sub.isEmpty ? null : Text(sub, maxLines: 1, overflow: TextOverflow.ellipsis),
      onTap: video == null || '${video['vid'] ?? ''}'.isEmpty ? null : () => openVideo(context, '${video['vid']}'),
      trailing: Column(mainAxisAlignment: MainAxisAlignment.center, crossAxisAlignment: CrossAxisAlignment.end, children: [
        Text(coinDelta(d), style: szMoney(fontSize: kFigureSm, color: d > 0 ? sz.earn : sz.ink)),
        Text('余 ${vInt(it['balance'])}', style: TextStyle(fontSize: kFontMicro, color: sz.inkMuted)),
      ]),
    );
  }
}
