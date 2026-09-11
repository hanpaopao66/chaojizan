import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';

import 'alert_prefs.dart';
import 'appeal_page.dart';
import 'dispatch_spec_page.dart';
import 'heatmap_page.dart';
import 'issues_page.dart';
import 'messages_page.dart';
import 'onboarding_page.dart';
import 'reviews_page.dart';
import 'verify_page.dart';
import 'weekly_page.dart';
import 'witness_page.dart';

/// 骑手「我的」(设计稿 5i):身份卡 + 两项认证 + 结算卡 + 三个数 + 设置列表。
///
/// ## 刻意不做的:评分与段位
///
/// 竞品这一页最显眼的是**服务分 70.0 / 安全分 70 / 派单分 200 / 一星青铜**。
/// 我们**一个都不做**:把骑手的收入和一个平台单方面控制的分数绑在一起,
/// 他就不敢拒单、不敢休息、不敢跟顾客理论。/transparency/dispatch 的
/// never_do 里公开承诺过「不按骑手评分或等级差别对待」。
/// 三个数里的「用户评价」是**顾客打的分的平均**,不参与任何排序和派单。
///
/// ## 稿子上有、代码里没有的
///
/// - 健康证「2026-11-02 到期 · 提前 30 天提醒」:骑手的健康证只存了一张照片,
///   没有到期日(国家层面不要求送餐员持证,只有部分城市要求)。这一行写的是
///   「上传了没有 / 本市要不要求」,不编到期日;
/// - 结算卡「每日 22:00」:没有定时结算,提现 T+1;
/// - 「骑手互助会」:平台没有这个组织,那一行只留见证节点;
/// - 「罚款 · 永远是 0」:平台确实没有任何罚款项,但「永远」是一句承诺,
///   不是代码里的事实 —— 写「没有这项」。
///
/// ## 稿子上没画、但一个都不能少的入口
///
/// 稿子只画了首屏。原来这一页上的保障(意外保障、紧急联系人、**事故上报**、
/// 装备申领)、申诉、培训、客服、协议全部排在设置列表下面,
/// 一条都没删 —— 入口去哪由 test/profile_routes_test.dart 盯着。
class RiderProfilePage extends StatefulWidget {
  const RiderProfilePage({
    super.key,
    required this.api,
    this.onOpenWallet,
    this.onOpenOrders,
    this.alerts = const RiderAlertPrefs(),
    this.onAlertsChanged,
  });

  final ApiClient api;

  final VoidCallback? onOpenWallet;
  final VoidCallback? onOpenOrders;

  /// 新单提醒的声音 / 震动(主页持有,改完回写)
  final RiderAlertPrefs alerts;
  final ValueChanged<RiderAlertPrefs>? onAlertsChanged;

  @override
  State<RiderProfilePage> createState() => _RiderProfilePageState();
}

class _RiderProfilePageState extends State<RiderProfilePage> {
  /// 今日/本周/本月在线时长、完成单、入账,以及累计单数。服务端 SQL 全量聚合
  Map<String, dynamic>? _worklog;

  /// 本次连续在线 + 疲劳档位。**只用来出休息提醒** —— 它的 online_minutes
  /// 是会话时长不是今天,别拿去当「今日在线」
  Map<String, dynamic>? _fatigue;
  UserProfile? _me;
  RiderProfile? _verify;
  PayoutAccount? _payout;
  bool? _examPassed;
  double? _rating;
  int _ratingCount = 0;
  int _unread = 0;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    // 各自失败静默:入口本身才是这页的主体,为了一个状态值把整页搞崩不值得。
    // 拉不到的一律当「没问题」—— 挂一个假的「你没实名」会让骑手白跑一趟认证页
    await Future.wait([
      _try(() async => _worklog = await widget.api.riderWorklog()),
      _try(() async => _fatigue = await widget.api.riderFatigue()),
      _try(() async => _me = await widget.api.me()),
      _try(() async => _verify = await widget.api.riderProfile()),
      _try(() async => _payout = await widget.api.payoutAccount()),
      _try(() async => _examPassed =
          (await widget.api.riderExamStatus())['passed'] as bool?),
      _try(() async {
        final r = await widget.api.riderReviews();
        _ratingCount = (r['count'] as num?)?.toInt() ?? 0;
        _rating = _ratingCount == 0 ? null : (r['average'] as num?)?.toDouble();
      }),
      _loadUnread(),
    ]);
    if (mounted) setState(() {});
  }

  Future<void> _try(Future<void> Function() f) async {
    try {
      await f();
    } catch (_) {}
  }

  Future<void> _loadUnread() => _try(() async {
        final m = await widget.api.riderMessages();
        _unread = (m['unread'] as num?)?.toInt() ?? 0;
      });

  Future<void> _push(Widget page) => Navigator.of(context)
      .push<void>(MaterialPageRoute<void>(builder: (_) => page));

  /// 办完一件事回来要重拉 —— 不然他刚登记完收款账户,返回一看还是「未登记」
  Future<void> _pushThenReload(Widget page) async {
    await _push(page);
    await _load();
  }

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    // 这一 tab 不带标题栏(稿子上身份卡就是页头),顶部安全区自己让
    final top = MediaQuery.paddingOf(context).top;
    return RefreshIndicator(
      onRefresh: _load,
      child: ListView(
        padding: EdgeInsets.fromLTRB(kPagePad, top + 20, kPagePad, 28),
        children: [
          SzEnter(index: 0, child: _identity(sz)),
          const SizedBox(height: 18),
          SzEnter(index: 1, child: _certs(sz)),
          const SizedBox(height: 12),
          SzEnter(index: 2, child: _stats(sz)),
          ..._restHint(sz),
          const SizedBox(height: 12),
          SzEnter(
            index: 3,
            child: SzEntryGroup(children: [
              // 「接单区域」落到热力图:只给历史单量,不预测、不推荐去哪跑 ——
              // 后者是软性派单
              SzEntryTile(
                icon: Icons.location_on_outlined,
                title: _verify == null || _verify!.city.isEmpty
                    ? '接单区域'
                    : '接单区域 · ${_verify!.city}',
                onTap: () => _push(RiderHeatmapPage(api: widget.api)),
              ),
              SzEntryTile(
                icon: Icons.notifications_none,
                title: '新单提醒 · ${widget.alerts.label}',
                onTap: () => _push(RiderAlertPrefsPage(
                    initial: widget.alerts, onChanged: widget.onAlertsChanged)),
              ),
              SzEntryTile(
                icon: Icons.groups_outlined,
                title: '见证节点 · 自己复算账本',
                onTap: () => _push(RiderWitnessPage(api: widget.api)),
              ),
              SzEntryTile(
                icon: Icons.gavel_outlined,
                title: '规则与费率 · 开源可查',
                onTap: () => _push(RiderRulesPage(api: widget.api)),
              ),
            ]),
          ),
          const SizedBox(height: 12),
          SzEntryGroup(children: [
            SzEntryTile(
              icon: Icons.notifications_none,
              title: '消息',
              // 超过 20 就写 20+:消息中心一页只拉 20 条,再往上的数是猜的
              value: _unread <= 0
                  ? null
                  : (_unread > 20 ? '20+ 条未读' : '$_unread 条未读'),
              valueTone: sz.clay,
              onTap: () async {
                await _push(RiderMessagesPage(api: widget.api));
                await _loadUnread();
                if (mounted) setState(() {});
              },
            ),
            SzEntryTile(
              icon: Icons.reviews_outlined,
              title: '顾客评价',
              onTap: () => _push(RiderReviewsPage(api: widget.api)),
            ),
            SzEntryTile(
              icon: Icons.bar_chart_outlined,
              title: '我的周报',
              hint: '每天跑了多少、时薪、配送费构成',
              onTap: () => _push(RiderWeeklyPage(api: widget.api)),
            ),
          ]),
          const SizedBox(height: 12),
          SzEntryGroup(children: [
            // 不给状态值:/riders/insurance 是按天的列表,今天没有行只说明
            // 今天还没上过线,不是「没保障」
            SzEntryTile(
              icon: Icons.health_and_safety_outlined,
              title: '意外保障',
              hint: '每日上线自动登记,出险有兜底',
              onTap: () => _push(RiderInsurancePage(api: widget.api)),
            ),
            SzEntryTile(
              icon: Icons.contact_phone_outlined,
              title: '紧急联系人',
              onTap: () => _push(EmergencyContactsPage(api: widget.api)),
            ),
            // 这一条的 hint 不许砍:这页唯一的紧急动作,整行热区 + danger 色
            SzEntryTile(
              icon: Icons.report_outlined,
              title: '事故上报',
              hint: '人先安全;在途订单自动处理',
              valueTone: sz.danger,
              onTap: () => _push(RiderAccidentPage(api: widget.api)),
            ),
            SzEntryTile(
              icon: Icons.backpack_outlined,
              title: '装备申领',
              hint: '头盔 / 保温餐箱 / 雨衣',
              onTap: () => _push(RiderGearPage(api: widget.api)),
            ),
          ]),
          const SizedBox(height: 12),
          SzEntryGroup(
            footnote: '派单公式与每个权重全部公开;申诉一律人工复核;'
                '你提的意见一定有人看。',
            children: [
              SzEntryTile(
                icon: Icons.help_outline,
                title: '抢单怎么排的',
                onTap: () => _push(DispatchSpecPage(api: widget.api)),
              ),
              SzEntryTile(
                icon: Icons.report_problem_outlined,
                title: '配送异常与申诉',
                onTap: () => _push(RiderIssuesPage(api: widget.api)),
              ),
              SzEntryTile(
                icon: Icons.policy_outlined,
                title: '违规申诉',
                onTap: () => _push(RiderAppealPage(api: widget.api)),
              ),
              SzEntryTile(
                icon: Icons.school_outlined,
                title: '上岗培训',
                value: _examPassed == null
                    ? null
                    : (_examPassed! ? '已通过' : '未通过'),
                valueTone: _examPassed == false ? sz.hold : null,
                onTap: () => _pushThenReload(RiderExamPage(api: widget.api)),
              ),
              SzEntryTile(
                icon: Icons.forum_outlined,
                title: '给平台提意见',
                onTap: () => _push(RiderFeedbackPage(api: widget.api)),
              ),
              SzEntryTile(
                icon: Icons.support_agent_outlined,
                title: '联系平台客服',
                onTap: () => _push(SupportPage(api: widget.api)),
              ),
            ],
          ),
          const SizedBox(height: 12),
          _promises(),
          const SizedBox(height: 12),
          // 商店审核三件套
          AccountLegalSection(
            api: widget.api,
            onLoggedOut: (ctx) {
              Navigator.of(ctx).popUntil((route) => route.isFirst);
              ApiClient.onUnauthorized?.call();
            },
            onDeleted: (ctx) {
              Navigator.of(ctx).popUntil((route) => route.isFirst);
              ApiClient.onUnauthorized?.call();
            },
          ),
        ],
      ),
    );
  }

  /// 身份卡:头像、名字、实名标,「骑手 · 哪年哪月加入 · 累计多少单」。
  Widget _identity(SzColors sz) {
    final name = (_me?.name.isNotEmpty ?? false)
        ? _me!.name
        : (widget.api.userName ?? '骑手');
    final joined = _me?.createdAt;
    final total = (_worklog?['total_orders'] as num?)?.toInt();
    final sub = [
      '骑手',
      if (joined != null) '${joined.year} 年 ${joined.month} 月加入',
      if (total != null) '${_thousands(total)} 单',
    ].join(' · ');
    final avatar = _me?.avatarUrl ?? '';
    return InkWell(
      borderRadius: BorderRadius.circular(kRadiusMd),
      onTap: () => _pushThenReload(RiderVerifyFlowPage(api: widget.api)),
      child: Row(children: [
        ClipOval(
          child: SizedBox(
            width: 56,
            height: 56,
            child: avatar.isNotEmpty
                ? SzImage(url: avatar, name: name, size: 56, radius: 28)
                : ColoredBox(
                    color: sz.line,
                    child: Center(
                      child: Text(szInitialOf(name),
                          style: szDisplay(fontSize: kFigureMd, color: sz.inkMuted)),
                    ),
                  ),
          ),
        ),
        const SizedBox(width: 14),
        Expanded(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Row(children: [
              Flexible(
                child: Text(name,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: TextStyle(
                        fontSize: kFontLead,
                        fontWeight: FontWeight.w600,
                        color: sz.ink)),
              ),
              if (_verify?.isApproved ?? false) ...[
                const SizedBox(width: 8),
                Container(
                  padding: const EdgeInsets.fromLTRB(6, 2, 8, 2),
                  decoration: BoxDecoration(
                    color: sz.earn.withValues(alpha: .12),
                    borderRadius: BorderRadius.circular(999),
                  ),
                  child: Row(mainAxisSize: MainAxisSize.min, children: [
                    Icon(Icons.verified_outlined, size: 13, color: sz.earn),
                    const SizedBox(width: 4),
                    Text('已实名',
                        style: TextStyle(
                            fontSize: kFontMicro,
                            fontWeight: FontWeight.w600,
                            color: sz.earn)),
                  ]),
                ),
              ],
            ]),
            const SizedBox(height: 2),
            Text(sub, style: TextStyle(fontSize: kFontNote, color: sz.inkMuted)),
          ]),
        ),
        Icon(Icons.chevron_right, size: 22, color: sz.inkFaint),
      ]),
    );
  }

  /// 认证台面:实名 / 健康证 / 结算卡(+ 培训没过时多一行)。
  Widget _certs(SzColors sz) {
    final v = _verify;
    final rows = <Widget>[
      _certRow(
        sz,
        icon: Icons.badge_outlined,
        iconColor: v == null
            ? sz.inkMuted
            : (v.isApproved ? sz.earn : (v.status == 'pending' ? sz.hold : sz.danger)),
        title: '实名认证',
        sub: switch (v?.status) {
          'approved' => '身份证 · 已通过',
          'pending' => '已提交,平台审核中',
          'rejected' => '被驳回:${v!.rejectReason}',
          null => '—',
          _ => '跑单前要先实名(身份证,满 18 岁)',
        },
        status: switch (v?.status) {
          'approved' => ('有效', sz.earn),
          'pending' => ('审核中', sz.hold),
          'rejected' => ('被驳回', sz.danger),
          null => null,
          _ => ('去提交', sz.danger),
        },
        onTap: () => _pushThenReload(RiderVerifyFlowPage(api: widget.api)),
      ),
      // 副标题说「本市要不要求」,右边说「传了没有」—— 两处不说同一句话。
      // 图标颜色和实名那行同一套:齐了 earn、要补 hold、可选 inkMuted
      _certRow(
        sz,
        icon: Icons.health_and_safety_outlined,
        iconColor: v == null
            ? sz.inkMuted
            : v.healthCertPhotoUrl.isNotEmpty
                ? sz.earn
                : (v.healthCertRequired ? sz.hold : sz.inkMuted),
        title: '健康证',
        sub: v == null
            ? '—'
            : v.healthCertRequired
                ? '你所在城市要求持证'
                : '你所在城市目前不要求,可选上传',
        status: v == null
            ? null
            : v.healthCertPhotoUrl.isNotEmpty
                ? ('已上传', sz.earn)
                : (v.healthCertRequired ? ('待上传', sz.hold) : ('可选', sz.inkMuted)),
        onTap: () => _pushThenReload(RiderVerifyFlowPage(api: widget.api)),
      ),
      _certRow(
        sz,
        icon: Icons.account_balance_outlined,
        iconColor: sz.inkMuted,
        title: '结算卡',
        sub: _payout == null
            ? '—'
            : _payout!.configured
                ? '${_payout!.bankName.isNotEmpty ? _payout!.bankName : _payout!.kindLabel}'
                    ' · 尾号 ${_payout!.accountTail} · 提现 T+1 到账'
                : '还没登记 · 提现前要先登记',
        status: _payout != null && !_payout!.configured ? ('未登记', sz.hold) : null,
        onTap: () => _pushThenReload(PayoutAccountPage(api: widget.api)),
      ),
      if (_examPassed == false)
        _certRow(
          sz,
          icon: Icons.school_outlined,
          iconColor: sz.hold,
          title: '上岗培训',
          sub: '食品安全培训,三分钟看完',
          status: ('未通过', sz.hold),
          onTap: () => _pushThenReload(RiderExamPage(api: widget.api)),
        ),
    ];
    return Material(
      color: sz.surface,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(kRadiusMd),
        side: BorderSide(color: sz.line),
      ),
      clipBehavior: Clip.antiAlias,
      child: Column(children: [
        for (final (i, r) in rows.indexed) ...[
          if (i > 0) Divider(height: 1, color: sz.line),
          r,
        ],
      ]),
    );
  }

  Widget _certRow(SzColors sz,
      {required IconData icon,
      required Color iconColor,
      required String title,
      required String sub,
      required (String, Color)? status,
      required VoidCallback onTap}) {
    return InkWell(
      onTap: onTap,
      child: Padding(
        padding: const EdgeInsets.all(14),
        child: Row(children: [
          Icon(icon, size: 22, color: iconColor),
          const SizedBox(width: 12),
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(title,
                  style: TextStyle(
                      fontSize: kFontBodyLg,
                      fontWeight: FontWeight.w600,
                      color: sz.ink)),
              Text(sub,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: TextStyle(fontSize: kFontNote, color: sz.inkMuted)),
            ]),
          ),
          const SizedBox(width: 8),
          if (status != null)
            Text(status.$1,
                style: TextStyle(
                    fontSize: kFontNote,
                    fontWeight: FontWeight.w600,
                    color: status.$2))
          else
            Icon(Icons.chevron_right, size: 20, color: sz.inkFaint),
        ]),
      ),
    );
  }

  /// 连续在线太久的休息提醒。**只提醒不断单**,也不给关 ——
  /// 这是安全提示,可以被关掉的容器不该装它
  List<Widget> _restHint(SzColors sz) {
    final level = _fatigue?['level'] as String?;
    final msg = _fatigue?['message'] as String?;
    if ((level != 'remind' && level != 'throttle') || msg == null || msg.isEmpty) {
      return const [];
    }
    return [
      const SizedBox(height: 10),
      Row(children: [
        Icon(Icons.bedtime_outlined, size: 17, color: sz.hold),
        const SizedBox(width: 8),
        Expanded(
          child: Text(msg,
              style: TextStyle(fontSize: kFontNote, height: 1.4, color: sz.hold)),
        ),
      ]),
    ];
  }

  /// 三个数:用户评价 / 本月所得 / 罚款。整卡点进周报。
  Widget _stats(SzColors sz) {
    final month = (_worklog?['month_earned_cents'] as num?)?.toInt();
    // 数和标签都缩放不折行:三格等分,320 屏 1.4× 下一格只有九十来宽
    Widget cell(String value, String label) => Expanded(
          child: Column(children: [
            FittedBox(
              fit: BoxFit.scaleDown,
              child: Text(value,
                  maxLines: 1,
                  style: szMoney(fontSize: kFigureMd, color: sz.ink)),
            ),
            const SizedBox(height: 2),
            FittedBox(
              fit: BoxFit.scaleDown,
              child: Text(label,
                  maxLines: 1,
                  style: TextStyle(fontSize: kFontMicro, color: sz.inkMuted)),
            ),
          ]),
        );
    Widget bar() => Container(width: 1, height: 34, color: sz.line);
    return SzCard(
      onTap: () => _push(RiderWeeklyPage(api: widget.api)),
      child: Row(children: [
        cell(_rating == null ? '—' : _rating!.toStringAsFixed(1),
            _ratingCount == 0 ? '用户评价' : '用户评价 · $_ratingCount 条'),
        bar(),
        cell(month == null ? '—' : szYuanText(month, '¥', 0), '本月所得'),
        bar(),
        cell('0', '罚款 · 没有这项'),
      ]),
    );
  }

  /// 平台对骑手的承诺。**刻意在折叠线以下**:它是身份声明不是入口。
  Widget _promises() => SzLedgerCard(
        onTap: () => _push(DispatchSpecPage(api: widget.api)),
        child: Builder(builder: (context) {
          final s = Theme.of(context).sz;
          return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text('平台对你的承诺',
                style: TextStyle(
                    fontSize: kFontBodyLg,
                    fontWeight: FontWeight.w600,
                    color: s.ink)),
            const SizedBox(height: 8),
            for (final p in const [
              '外卖配送费与小费 100% 归你,平台分文不取;跑腿费平台收 2%',
              '派单算法完整公开,你可以拿自己的单代进去算',
              '不按评分或等级差别对待 —— 我们没有服务分,也不会有',
              '不用你的实际速度反过来缩短配送时限',
              '连续在线过久会提醒你休息,但不会断你的单',
            ])
              Padding(
                padding: const EdgeInsets.only(bottom: 5),
                child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Text('· ', style: TextStyle(fontSize: kFontNote, color: s.ink)),
                  Expanded(
                    child: Text(p,
                        style: TextStyle(
                            fontSize: kFontNote, height: 1.5, color: s.ink)),
                  ),
                ]),
              ),
            const SizedBox(height: 4),
            Text('点这里看完整算法与权重 →',
                style: TextStyle(fontSize: kFontNote, color: s.clay)),
          ]);
        }),
      );

  String _thousands(int n) {
    final s = '$n';
    final b = StringBuffer();
    for (var i = 0; i < s.length; i++) {
      if (i > 0 && (s.length - i) % 3 == 0) b.write(',');
      b.write(s[i]);
    }
    return b.toString();
  }
}
