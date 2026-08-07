import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';

import 'dispatch_spec_page.dart';
import 'heatmap_page.dart';
import 'messages_page.dart';
import 'reviews_page.dart';
import 'weekly_page.dart';

/// 骑手「我的」中心(#147)。
///
/// ## 为什么要有这一页
///
/// 对照竞品(蜂鸟众包/美团骑手)发现:**我们的空白不在能力,在入口**。
/// 服务端有 24 个骑手端点、客户端 API 方法也齐全,但入口散落各处 ——
/// 工时埋在钱包页、违规申诉埋在「异常上报」、转单纪律埋在入驻页。
/// 骑手要找「我的违规申诉」得先想到点「异常上报」。
///
/// 竞品都有的那一层「我的」中心,我们没有。骑手打开 App 只有抢单/配送/钱包,
/// 没有一个地方能回答「我在这个平台上是什么状态」。
///
/// ## 刻意不做的:评分与段位
///
/// 竞品这一页最显眼的是**服务分 70.0 / 安全分 70 / 派单分 200 / 一星青铜**。
///
/// 我们**一个都不做**。那是「算法困住人」的核心机制:把骑手的收入与一个
/// 平台单方面控制的分数绑定,分数由接单率/超时率/差评率构成 ——
/// 于是骑手不敢拒单、不敢休息、不敢跟顾客理论。**那不是激励,是绳索。**
///
/// 而且 /transparency/dispatch 的 never_do 里已经公开承诺
/// 「不按骑手评分或等级差别对待」—— 抄了就是当众违背自己刚公开的承诺。
///
/// 这一页底部放的不是活动 banner,是**平台对骑手的承诺**,每条都链到可验证处。
class RiderProfilePage extends StatefulWidget {
  const RiderProfilePage({
    super.key,
    required this.api,
    required this.todayOrders,
    required this.todayCents,
    this.onOpenWallet,
    this.onOpenOrders,
  });

  final ApiClient api;

  /// 今日数据由主页传入(它本来就在轮询,不必再拉一遍)
  final int todayOrders;
  final int todayCents;

  final VoidCallback? onOpenWallet;
  final VoidCallback? onOpenOrders;

  @override
  State<RiderProfilePage> createState() => _RiderProfilePageState();
}

class _RiderProfilePageState extends State<RiderProfilePage> {
  Map<String, dynamic>? _fatigue;
  Map<String, dynamic>? _worklog;
  int _unread = 0;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    // 两个都失败也不影响这一页可用 —— 入口本身才是这页的主体
    try {
      final f = await widget.api.riderFatigue();
      if (mounted) setState(() => _fatigue = f);
    } catch (_) {}
    try {
      final w = await widget.api.riderWorklog();
      if (mounted) setState(() => _worklog = w);
    } catch (_) {}
    await _loadUnread();
  }

  /// 未读数取不到就当 0:入口照常在,只是不显角标 ——
  /// 为了一个数字把整页搞崩不值得
  Future<void> _loadUnread() async {
    try {
      final m = await widget.api.riderMessages();
      if (mounted) setState(() => _unread = (m['unread'] as num?)?.toInt() ?? 0);
    } catch (_) {}
  }

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    // 不套 AppBar:外层 Scaffold 已经有一个,套两层会出现「我的钱包 / 我的」
    // 两个标题叠在一起(实机撞过)
    return RefreshIndicator(
        onRefresh: _load,
        child: ListView(
          padding: const EdgeInsets.fromLTRB(kPagePad, 12, kPagePad, 28),
          children: [
            _todayCard(sz),
            const SizedBox(height: 18),
            const SzSectionTitle('跑单'),
            const SizedBox(height: 8),
            _group(sz, [
              _Item('我的订单', '进行中与历史订单', Icons.receipt_long_outlined,
                  widget.onOpenOrders),
              // 只给历史,不预测、不推荐去哪跑 —— 后者是软性派单
              _Item('哪儿有单', '过去几周各时段的实际单量(是历史不是预测)',
                  Icons.map_outlined,
                  () => _push(RiderHeatmapPage(api: widget.api))),
              _Item('我的周报', '每天跑了多少、钱是怎么来的(只统计不考核)',
                  Icons.insights_outlined,
                  () => _push(RiderWeeklyPage(api: widget.api))),
              _Item(
                  '工时统计',
                  _worklog == null
                      ? '在线时长逐日可查'
                      : '本周在线 ${_hours(_worklog!["week_minutes"])} 小时',
                  Icons.schedule_outlined,
                  () => _snack('工时明细在钱包页「工时」区块')),
              _Item('顾客评价', '看看顾客怎么说(不影响派单)',
                  Icons.reviews_outlined, () => _push(RiderReviewsPage(api: widget.api))),
              // 推送弹出来那一下没看到就永远找不回来了 ——
              // 而发给骑手的偏偏是申诉结果、提现到账、极端天气这几类
              _Item(
                  '消息',
                  _unread > 0 ? '$_unread 条未读' : '申诉结果、到账、天气预警',
                  Icons.notifications_none,
                  () async {
                    await _push(RiderMessagesPage(api: widget.api));
                    _loadUnread();
                  }),
            ]),
            const SizedBox(height: 18),
            const SzSectionTitle('保障'),
            const SizedBox(height: 8),
            _group(sz, [
              _Item('意外保障', '每日上线自动登记,出险有兜底',
                  Icons.health_and_safety_outlined, () => _toWallet()),
              _Item('紧急联系人', 'SOS 时平台第一时间联系',
                  Icons.contact_phone_outlined, () => _toWallet()),
              _Item('事故上报', '人先安全;在途订单自动处理',
                  Icons.report_outlined, () => _toWallet()),
              _Item('装备申领', '头盔 / 保温餐箱 / 雨衣',
                  Icons.backpack_outlined, () => _toWallet()),
            ]),
            const SizedBox(height: 18),
            const SzSectionTitle('账目'),
            const SizedBox(height: 8),
            _group(sz, [
              _Item('我的钱包', '收入明细、提现', Icons.account_balance_wallet_outlined,
                  widget.onOpenWallet),
              _Item('收款账户', '提现打款到这里', Icons.credit_card_outlined,
                  () => _toWallet()),
            ]),
            const SizedBox(height: 18),
            const SzSectionTitle('规则'),
            const SizedBox(height: 8),
            _group(sz, [
              _Item('抢单怎么排的', '完整公式与每个权重的理由,全部公开',
                  Icons.help_outline,
                  () => _push(DispatchSpecPage(api: widget.api))),
              _Item('违规申诉', '有异议就申诉,平台人工复核',
                  Icons.gavel_outlined,
                  () => _snack('在「配送」页的异常上报里发起申诉')),
              _Item('上岗培训', '80 分通过,可重考', Icons.school_outlined,
                  () => _toWallet()),
              // 平台自己也得有个挨骂的地方。与申诉分开:
              // 申诉是"这一单不怪我",这里是"你们这东西不好用"
              _Item('给平台提意见', '哪不好用、哪条规则不合理,一定有人看',
                  Icons.forum_outlined,
                  () => _push(RiderFeedbackPage(api: widget.api))),
            ]),
            const SizedBox(height: 22),
            _promises(sz),
          ],
      ),
    );
  }

  /// 今日数据。**不放任何分数、等级、段位** —— 见类文档的红线。
  Widget _todayCard(SzColors sz) {
    final level = _fatigue?['level'] as String?;
    // 没加载完时给「—」而不是 0.0 ——
    // 0 是一个**看起来像真值**的数,骑手会读它("我今天怎么才在线 0 小时"),
    // 然后它又自己变了。占位符不会被误读
    final onlineMin = (_fatigue?['online_minutes'] as num?)?.toDouble();
    return SzCard(
      child: Column(children: [
        Row(children: [
          _stat(sz, '今日完成', '${widget.todayOrders}', '单'),
          _divider(sz),
          _stat(sz, '今日收入',
              (widget.todayCents / 100).toStringAsFixed(2), '元'),
          _divider(sz),
          _stat(sz, '在线时长',
              onlineMin == null ? '—' : _hours(onlineMin), '小时'),
        ]),
        const SizedBox(height: 8),
        // 口径要写清楚:不写的话骑手会以为平台少算了
        Text('收入按已完成订单统计,不含在途单;配送费与小费 100% 归你',
            style: TextStyle(fontSize: 11, color: sz.inkMuted)),
        if (level == 'throttle' || level == 'remind') ...[
          const SizedBox(height: 8),
          Text('${_fatigue?["message"] ?? ""}',
              style: TextStyle(fontSize: 12, color: sz.hold)),
        ],
      ]),
    );
  }

  Widget _stat(SzColors sz, String label, String value, String unit) => Expanded(
        child: Column(children: [
          Row(mainAxisAlignment: MainAxisAlignment.center, children: [
            Text(value,
                style: szMoney(
                    fontSize: 22, fontWeight: FontWeight.w600, color: sz.ink)),
            const SizedBox(width: 2),
            Text(unit, style: TextStyle(fontSize: 11, color: sz.inkMuted)),
          ]),
          const SizedBox(height: 2),
          Text(label, style: TextStyle(fontSize: 12, color: sz.inkMuted)),
        ]),
      );

  Widget _divider(SzColors sz) =>
      Container(width: 1, height: 30, color: sz.line);

  Widget _group(SzColors sz, List<_Item> items) => SzCard(
        padding: EdgeInsets.zero,
        child: Column(children: [
          for (final (i, it) in items.indexed) ...[
            if (i > 0) Divider(height: 1, color: sz.line),
            ListTile(
              leading: Icon(it.icon, size: 21, color: sz.inkFaint),
              title: Text(it.title, style: const TextStyle(fontSize: 14.5)),
              subtitle: Text(it.sub, style: TextStyle(fontSize: 11.5, color: sz.inkMuted)),
              trailing: Icon(Icons.chevron_right, size: 18, color: sz.inkFaint),
              onTap: it.onTap,
            ),
          ],
        ]),
      );

  /// 竞品这个位置放活动 banner。我们放**平台对骑手的承诺** ——
  /// 每条都链到可验证的地方,不是标语。
  Widget _promises(SzColors sz) => SzLedgerCard(
        onTap: () => _push(DispatchSpecPage(api: widget.api)),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          const Text('平台对你的承诺',
              style: TextStyle(fontSize: 14.5, fontWeight: FontWeight.w600)),
          const SizedBox(height: 8),
          for (final p in const [
            '配送费与小费 100% 归你,平台分文不取',
            '派单算法完整公开,你可以拿自己的单代进去算',
            '不按评分或等级差别对待 —— 我们没有服务分,也不会有',
            '不用你的实际速度反过来缩短配送时限',
            '连续在线过久会提醒你休息,但不会断你的单',
          ])
            Padding(
              padding: const EdgeInsets.only(bottom: 5),
              child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                const Text('· ', style: TextStyle(fontSize: 12.5)),
                Expanded(
                  child: Text(p,
                      style: const TextStyle(fontSize: 12.5, height: 1.5)),
                ),
              ]),
            ),
          const SizedBox(height: 4),
          Text('点这里看完整算法与权重 →',
              style: TextStyle(fontSize: 12, color: SzColors.dark.clay)),
        ]),
      );

  /// 分钟 → 小时。**没数据时给「—」不给 0** ——
  /// 0 会被当成真值读,而它随后还会自己变
  String _hours(dynamic minutes) {
    final m = (minutes as num?)?.toDouble();
    return m == null ? '—' : (m / 60).toStringAsFixed(1);
  }

  Future<void> _push(Widget page) => Navigator.of(context)
      .push<void>(MaterialPageRoute<void>(builder: (_) => page));

  void _toWallet() {
    widget.onOpenWallet?.call();
    _snack('已跳到钱包页,相关入口在「保障与规则」');
  }

  void _snack(String msg) => ScaffoldMessenger.of(context)
      .showSnackBar(SnackBar(content: Text(msg)));
}

class _Item {
  const _Item(this.title, this.sub, this.icon, this.onTap);

  final String title;
  final String sub;
  final IconData icon;
  final VoidCallback? onTap;
}
