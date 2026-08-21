import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';

import 'appeal_page.dart';
import 'dispatch_spec_page.dart';
import 'heatmap_page.dart';
import 'messages_page.dart';
import 'onboarding_page.dart';
import 'reviews_page.dart';
import 'verify_page.dart';
import 'weekly_page.dart';

/// 骑手「我的」中心(#147,密度重排 #297)。
///
/// ## 为什么要有这一页
///
/// 对照竞品(蜂鸟众包/美团骑手)发现:**我们的空白不在能力,在入口**。
/// 服务端有 24 个骑手端点、客户端 API 方法也齐全,但入口散落各处 ——
/// 工时埋在钱包页、违规申诉埋在「异常上报」、转单纪律埋在入驻页。
///
/// ## 刻意不做的:评分与段位
///
/// 竞品这一页最显眼的是**服务分 70.0 / 安全分 70 / 派单分 200 / 一星青铜**。
///
/// 我们**一个都不做**。那是「算法困住人」的核心机制:把骑手的收入与一个
/// 平台单方面控制的分数绑定,于是骑手不敢拒单、不敢休息、不敢跟顾客理论。
/// **那不是激励,是绳索。** 而且 /transparency/dispatch 的 never_do 里
/// 已经公开承诺「不按骑手评分或等级差别对待」—— 抄了就是当众违背承诺。
///
/// ## #297 改了什么
///
/// **① 16 个入口里有 8 个不去它说的地方。** 6 个走 `_toWallet()`(切到钱包
/// tab 再弹一句「相关入口在『保障与规则』」叫他自己翻),2 个只弹 SnackBar。
/// 而这 8 个的目标页全都现成。最糟的是**事故上报**:骑手出了事故点它,
/// App 把他扔到钱包页 —— 那不是密度问题,是安全问题。判据锁在
/// `test/profile_routes_test.dart`。
///
/// **② 黄金位那两个数字对每个骑手每一天都是 0。** 老代码从主页传进来的
/// `todayOrders`/`todayCents` 由 `_todayDone` 算,而 `_todayDone` 从 `_mine`
/// 里筛 `completed||delivered` —— `_mine` 却只留 `accepted/ready/pickedUp`。
/// **两个集合不相交,恒为空。** 就算筛对了也还是错的:它的源头
/// `myOrders()` 默认 `limit=20`,是「拿一页列表求和却安一个更大的名字」,
/// 和用户端刚删掉的「累计优惠」同一个错误。
/// 现在三个数全部改用 `/riders/me/worklog` —— 服务端 `func.count()` +
/// `func.sum()` 全量聚合,无 limit。
///
/// **③「在线时长」量的不是今天。** `/riders/me/fatigue` 服务端注释写着
/// 「本次连续在线:取最近一条还没下线的会话」,没有开着的会话返回 0。
/// 中午下线吃个饭再上线,读数归零;收工回家打开写着 0.0 小时。
/// 改用 `worklog.today_minutes`(服务端按北京自然日算)。
/// `fatigue` 只留着出休息提醒。
///
/// ## 黄金位为什么放「今日」不放承诺
///
/// 候选是今日收入卡 / 保障状态卡 / 配送费透明卡。
///
/// - **保障状态卡**只在坏掉的时候有信息量,而它绝大多数时候是好的。
///   一张常年写着「一切正常」的卡占的是这页最贵的 110px ——
///   所以它改成了[_readyGroup]:**只在真有事要做时才存在**。
/// - **配送费透明卡**在这个 App 里已经有三份(钱包页的 PledgeCard、
///   本页底部的承诺卡、今日卡的口径行)。放黄金位是第四份。
///   而且承诺是读一遍就记住的东西,黄金位该给**值会变**的东西。
/// - **今日**是这页上唯一每 20 分钟就变一次的数,
///   也是骑手跑单间隙打开这个 tab 的原因。
///
/// 和钱包 tab 的分工:**钱包答「有多少钱能拿走」**(可提现余额是它的
/// hero),**这里答「今天这几个小时跑得怎么样」**。所以这张卡里
/// 不出现余额、不出现提现按钮,整卡点进去是**周报**不是钱包 ——
/// 「今天」→「这周」是自然下钻,而周报里有时薪和配送费构成。
class RiderProfilePage extends StatefulWidget {
  const RiderProfilePage({
    super.key,
    required this.api,
    this.onOpenWallet,
    this.onOpenOrders,
  });

  final ApiClient api;

  final VoidCallback? onOpenWallet;
  final VoidCallback? onOpenOrders;

  @override
  State<RiderProfilePage> createState() => _RiderProfilePageState();
}

class _RiderProfilePageState extends State<RiderProfilePage> {
  /// 本次连续在线 + 疲劳档位。**只用来出休息提醒** ——
  /// 它的 online_minutes 是会话时长不是今天,别拿去当「今日在线」
  Map<String, dynamic>? _fatigue;

  /// 今日/本周在线时长、完成单、入账。服务端 SQL 全量聚合
  Map<String, dynamic>? _worklog;

  int _unread = 0;

  // 开工准备三件套。取不到就当没问题 ——
  // 拉不到状态而误报「你没认证」,比不报更糟
  RiderProfile? _verify;
  PayoutAccount? _payout;
  bool? _examPassed;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    // 六个请求各自失败静默:入口本身才是这页的主体,
    // 为了一个状态值把整页搞崩不值得
    await Future.wait([
      _try(() async => _fatigue = await widget.api.riderFatigue()),
      _try(() async => _worklog = await widget.api.riderWorklog()),
      _loadUnread(),
      _try(() async => _verify = await widget.api.riderProfile()),
      _try(() async => _payout = await widget.api.payoutAccount()),
      _try(() async => _examPassed =
          (await widget.api.riderExamStatus())['passed'] as bool?),
    ]);
    if (mounted) setState(() {});
  }

  Future<void> _try(Future<void> Function() f) async {
    try {
      await f();
    } catch (_) {}
  }

  /// 未读数取不到就当 0:入口照常在,只是不显角标
  Future<void> _loadUnread() => _try(() async {
        final m = await widget.api.riderMessages();
        _unread = (m['unread'] as num?)?.toInt() ?? 0;
      });

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    // 不套 AppBar:外层 Scaffold 已经有一个,套两层会出现
    // 「我的钱包 / 我的」两个标题叠在一起(实机撞过)。
    //
    // 也**不往 AppBar 右上角加东西**:那里已经是 SOS(leading)+ GPS +
    // 「接单中/已下线」+ Switch。上线开关是骑手端唯一一个比任何入口
    // 都重要的控件,不该为了腾位置给「客服」「设置」而让它变窄 ——
    // 「高频动作提到 AppBar」这条在另外两端成立,在这一端位置已经占满了
    return RefreshIndicator(
      onRefresh: _load,
      child: ListView(
        padding: const EdgeInsets.fromLTRB(kPagePad, 12, kPagePad, 28),
        children: [
          _todayCard(sz),
          // 块之间用留白分,不用分隔线也不用分组头 ——
          // 原来四个 SzSectionTitle 一共吃掉 104px(4 × 26),
          // 那是两个多入口的地方,而卡片边界本来就已经把组分开了
          const SizedBox(height: 12),
          ..._readyGroup(sz),
          // 网格:标题两三个字就说清、给不出状态值、彼此平级的那一档。
          // **不套 SzCard** —— 卡的 14px 横向内边距会把每格从 88.5 压到
          // 81.5,高度从 82 涨到 110,为了一个边框付 28px 不划算
          SzIconGrid(items: [
            SzIconGridItem(
                icon: Icons.receipt_long_outlined,
                label: '我的订单',
                onTap: widget.onOpenOrders),
            // 只给历史,不预测、不推荐去哪跑 —— 后者是软性派单
            SzIconGridItem(
                icon: Icons.map_outlined,
                label: '哪儿有单',
                onTap: () => _push(RiderHeatmapPage(api: widget.api))),
            SzIconGridItem(
                icon: Icons.reviews_outlined,
                label: '顾客评价',
                onTap: () => _push(RiderReviewsPage(api: widget.api))),
            // 全页唯一一个数字角标。unread 是服务端 COUNT,
            // 和 page_size 无关 —— 别的候选见类文档下面那段
            SzIconGridItem(
                icon: Icons.notifications_none,
                label: '消息',
                badge: _unread,
                onTap: () async {
                  await _push(RiderMessagesPage(api: widget.api));
                  await _loadUnread();
                  if (mounted) setState(() {});
                }),
          ]),
          const SizedBox(height: 12),
          _group([
            // **不给它状态值。** /riders/insurance 是按天的列表,
            // 今天没有行意味着「今天还没上过线」,不是「没保障」——
            // 挂个「今日未投保」会在每个骑手每天早上误报一次
            _Item('意外保障', '每日上线自动登记,出险有兜底', Icons.health_and_safety_outlined,
                () => _push(RiderInsurancePage(api: widget.api))),
            _Item('紧急联系人', '', Icons.contact_phone_outlined,
                () => _push(EmergencyContactsPage(api: widget.api))),
            // 这一条的 hint 不许砍。它是这页唯一的紧急动作,
            // 需要整行热区、需要 danger 色、需要那句话摆在外面 ——
            // 压成一个 22px 图标 + 四个字的网格格子是反的
            _Item('事故上报', '人先安全;在途订单自动处理', Icons.report_outlined,
                () => _push(RiderAccidentPage(api: widget.api)),
                tone: sz.danger),
            // 「头盔 / 保温餐箱 / 雨衣」是**内容**不是解释,留着 ——
            // 它回答的是"能领什么",不是"这个入口是干嘛的"
            _Item('装备申领', '头盔 / 保温餐箱 / 雨衣', Icons.backpack_outlined,
                () => _push(RiderGearPage(api: widget.api))),
          ]),
          const SizedBox(height: 12),
          _group([
            _Item('我的钱包', '', Icons.account_balance_wallet_outlined,
                widget.onOpenWallet),
            // 状态值白来的:_payout 已经为[_readyGroup]拉过了
            _Item('收款账户', '提现打款到这里', Icons.credit_card_outlined,
                () => _push(PayoutAccountPage(api: widget.api)),
                value: _payout == null || !_payout!.configured
                    ? null
                    : '尾号 ${_payout!.accountTail}'),
            _Item('联系平台客服', '', Icons.support_agent_outlined,
                () => _push(SupportPage(api: widget.api))),
          ]),
          const SizedBox(height: 12),
          SzEntryGroup(
            // 立场表达收进脚注,不塞进每一行 —— 原来这三句分别挂在
            // 三条的 hint 上,各付 17px
            footnote: '派单公式与每个权重全部公开;申诉一律人工复核;'
                '你提的意见一定有人看。',
            children: [
              for (final it in [
                _Item('抢单怎么排的', '', Icons.help_outline,
                    () => _push(DispatchSpecPage(api: widget.api))),
                _Item('规则中心', '', Icons.menu_book_outlined,
                    () => _push(RiderRulesPage(api: widget.api))),
                // RiderAppealPage 的构造函数注释写着「从「我的」进来时为
                // null(只看列表)」—— 这个页当初就是为这个入口写的,
                // 线一直没接上,老代码只弹一句「去『配送』页的异常上报里发起」
                _Item('违规申诉', '', Icons.gavel_outlined,
                    () => _push(RiderAppealPage(api: widget.api))),
                _Item('上岗培训', '', Icons.school_outlined,
                    () => _push(RiderExamPage(api: widget.api)),
                    value: _examPassed == null
                        ? null
                        : (_examPassed! ? '已通过' : '未通过')),
                // 平台自己也得有个挨骂的地方。与申诉分开:
                // 申诉是"这一单不怪我",这里是"你们这东西不好用"
                _Item('给平台提意见', '', Icons.forum_outlined,
                    () => _push(RiderFeedbackPage(api: widget.api))),
              ])
                _tile(it),
            ],
          ),
          const SizedBox(height: 12),
          _promises(),
          const SizedBox(height: 12),
          // 商店审核三件套。钱包页那份**先不删** ——
          // 审核路径突然变了比多一份更麻烦,下一轮再清
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

  /// 今日战报。**不放任何分数、等级、段位** —— 见类文档的红线。
  ///
  /// 三个数全部来自 `worklog` 一个来源,不再和订单列表各算各的。
  Widget _todayCard(SzColors sz) {
    final level = _fatigue?['level'] as String?;
    final tired = level == 'throttle' || level == 'remind';
    final msg = _fatigue?['message'] as String?;
    return SzCard(
      onTap: () => _push(RiderWeeklyPage(api: widget.api)),
      child: Column(children: [
        Row(children: [
          _stat(sz, '今日完成', _int(_worklog?['today_orders']), '单'),
          _divider(sz),
          _stat(sz, '今日在线', _hours(_worklog?['today_minutes']), '小时'),
          _divider(sz),
          _stat(sz, '今日收入', _yuan(_worklog?['today_earned_cents']), '元'),
        ]),
        const SizedBox(height: 8),
        Row(children: [
          Expanded(
            // 一行放得下:原来那句「收入按已完成订单统计,不含在途单;
            // 配送费与小费 100% 归你」要 348.8px,盒子只有 326,一直折两行
            child: Text('配送费 100% 归你 · 看周报 →',
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: TextStyle(fontSize: 11, color: sz.inkMuted)),
          ),
        ]),
        if (tired && msg != null && msg.isNotEmpty) ...[
          const SizedBox(height: 8),
          Row(children: [
            Expanded(
                child:
                    Text(msg, style: TextStyle(fontSize: 12, color: sz.hold))),
          ]),
        ],
      ]),
    );
  }

  /// 开工准备:**只在真有事要做时才存在**,全通过时整块(连同间距)不渲染。
  ///
  /// 这是「保障状态卡」的正确形态。三个信号全部是服务端算好的扁平值,
  /// 没有一个是客户端凑的:
  ///
  /// | 行 | 判据 | 来源 |
  /// |---|---|---|
  /// | 实名认证 | `status ∈ {unsubmitted, rejected}` | `GET /riders/profile` |
  /// | 收款账户 | `configured == false` | `GET /payout-account` |
  /// | 上岗培训 | `passed == false` | `GET /riders/exam/status` |
  ///
  /// 这是全页仅有的三件**能让骑手跑不了单或拿不到钱**的事。
  /// 现在收款账户没登记,骑手要到点「提现」被顶回来才知道。
  ///
  /// **不用红点角标用带色 value** —— 这三条是「状态」不是「几件待办」,
  /// 「未登记」比一个红点有信息量。
  ///
  /// ⚠️ 拉不到一律当"没问题"。宁可漏报,不可误报 ——
  /// 挂一个假的「你没实名」会让骑手白跑一趟认证页。
  List<Widget> _readyGroup(SzColors sz) {
    final v = _verify;
    final rows = <Widget>[
      if (v != null && v.status != 'approved' && v.status != 'pending')
        _tile(_Item('实名认证', '', Icons.badge_outlined,
            () => _pushThenReload(RiderVerifyFlowPage(api: widget.api)),
            value: v.status == 'rejected' ? '被驳回' : '去提交', tone: sz.danger)),
      if (_payout != null && !_payout!.configured)
        _tile(_Item('收款账户', '', Icons.credit_card_outlined,
            () => _pushThenReload(PayoutAccountPage(api: widget.api)),
            value: '未登记', tone: sz.hold)),
      if (_examPassed == false)
        _tile(_Item('上岗培训', '', Icons.school_outlined,
            () => _pushThenReload(RiderExamPage(api: widget.api)),
            value: '未通过', tone: sz.hold)),
    ];
    if (rows.isEmpty) return const [];
    return [SzEntryGroup(children: rows), const SizedBox(height: 12)];
  }

  Widget _stat(SzColors sz, String label, String value, String unit) =>
      Expanded(
        child: Column(children: [
          // ⚠️ 溢出护栏。每格只有 108px,而「86.00」在 szMoney 22px 下
          // 要 111.3px —— 加上「元」和间距是 124.6,老代码在这里
          // `RenderFlex overflowed by 17 pixels`,1.4× 下溢出 65px。
          // **只要日收入 ≥ ¥10 就溢出。** 之前没人报,是因为上面那个
          // 恒为 0 的 bug 让它永远显示「0.00」(4 字符,刚好塞得下)——
          // 修了数据源就会当场暴露这个。判据锁在 profile_today_card_test.dart
          FittedBox(
            fit: BoxFit.scaleDown,
            child: Row(mainAxisSize: MainAxisSize.min, children: [
              Text(value,
                  maxLines: 1,
                  style: szMoney(
                      fontSize: 22,
                      fontWeight: FontWeight.w600,
                      color: sz.ink)),
              const SizedBox(width: 2),
              Text(unit, style: TextStyle(fontSize: 11, color: sz.inkMuted)),
            ]),
          ),
          const SizedBox(height: 2),
          Text(label,
              maxLines: 1, style: TextStyle(fontSize: 12, color: sz.inkMuted)),
        ]),
      );

  Widget _divider(SzColors sz) =>
      Container(width: 1, height: 30, color: sz.line);

  /// 一组入口。用 shared 的 SzEntryGroup / SzEntryTile(#294)。
  Widget _group(List<_Item> items) =>
      SzEntryGroup(children: [for (final it in items) _tile(it)]);

  Widget _tile(_Item it) => SzEntryTile(
        icon: it.icon,
        title: it.title,
        value: it.value,
        hint: it.sub,
        valueTone: it.tone,
        onTap: it.onTap,
      );

  /// 竞品这个位置放活动 banner。我们放**平台对骑手的承诺**。
  ///
  /// **刻意在折叠线以下**:它是身份声明不是入口,滚到底看见一次就够。
  /// 承诺是读一遍就记住的东西,不该占黄金位那 110px。
  Widget _promises() => SzLedgerCard(
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
              child:
                  Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
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

  /// 还没加载出来给「—」不给 0 —— **0 是一个看起来像真值的数**,
  /// 骑手会读它("我今天怎么才跑 0 单"),然后它又自己变了。
  ///
  /// 加载完之后的 0 是**真的 0**(今天还没跑单),照写不误。
  /// 这两种 0 现在分得开,因为 worklog 的字段要么有要么整个对象是 null。
  String _int(dynamic v) => v == null ? '—' : '${(v as num).toInt()}';

  String _hours(dynamic minutes) {
    final m = (minutes as num?)?.toDouble();
    return m == null ? '—' : (m / 60).toStringAsFixed(1);
  }

  String _yuan(dynamic cents) {
    final c = (cents as num?)?.toInt();
    return c == null ? '—' : (c / 100).toStringAsFixed(2);
  }

  Future<void> _push(Widget page) => Navigator.of(context)
      .push<void>(MaterialPageRoute<void>(builder: (_) => page));

  /// 办完一件待办回来要重拉 —— 不然他刚登记完收款账户,
  /// 返回一看「未登记」还挂在那儿
  Future<void> _pushThenReload(Widget page) async {
    await _push(page);
    await _load();
  }
}

class _Item {
  const _Item(this.title, this.sub, this.icon, this.onTap,
      {this.value, this.tone});

  final String title;

  /// 一次性解释。**只在 [value] 为空时显示** —— 见 SzEntryTile 的类文档。
  /// 标题已经说清是什么的(「我的钱包」「规则中心」)就传空串,
  /// 别为了"看起来完整"硬凑一句 —— 那一行只省 12%,还占着屏幕。
  final String sub;

  /// 当前值。和标题同一行,零额外高度。
  final String? value;

  /// 状态的语气:待办用 hold、异常用 danger、正常留空。
  final Color? tone;

  final IconData icon;
  final VoidCallback? onTap;
}
