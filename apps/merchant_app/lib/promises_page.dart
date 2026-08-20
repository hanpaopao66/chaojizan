import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';

import 'dashboard_page.dart';

/// 平台对商家的承诺(#153)。
///
/// ## 为什么要有这一页
///
/// 骑手端的「我的」中心底部已经放了平台承诺(配送费 100% 归骑手、算法公开、
/// 不按评分差别对待……),每条都链到可验证处。**商家端没有对应的东西** ——
/// 而商家最关心的承诺同样具体,而且同样可验证。
///
/// ## 这不是营销文案
///
/// 下面每一条在写进来之前都逐条对着代码核过,包括对我们不利的那条:
/// 评价**是**能被隐藏的(申诉改判路径),所以那一条没有写成
/// 「评价不删除、不隐藏」—— 写了就是假承诺。写的是真实边界:
/// 商家自己删不了、花钱也删不了,唯一路径是人工复核判申诉成立。
///
/// 一份有一条假话的承诺,比没有承诺更糟 —— 商家一旦撞见那一条,
/// 其余四条也不会再信。
class MerchantPromisesPage extends StatefulWidget {
  const MerchantPromisesPage({super.key, required this.api, this.onOpenFinance});

  final ApiClient api;

  /// 「去对账页看」由外层切底部 tab —— push 一个 FinancePage 进来会顶掉
  /// 底部导航,商家返回时找不着北
  final VoidCallback? onOpenFinance;

  @override
  State<MerchantPromisesPage> createState() => _MerchantPromisesPageState();
}

class _MerchantPromisesPageState extends State<MerchantPromisesPage> {
  Map<String, dynamic>? _tier;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final t = await widget.api.merchantCommissionTier();
      if (mounted) setState(() => _tier = t);
    } catch (_) {
      // 拿不到费率不影响这一页 —— 承诺本身不依赖这次请求成功
    }
  }

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    final rate = (_tier?['commission_rate'] as num?)?.toDouble();

    return SzPageScaffold(
      appBar: AppBar(title: const Text('平台对你的承诺')),
      body: ListView(
        padding: const EdgeInsets.fromLTRB(kPagePad, 14, kPagePad, 32),
        children: [
          SzLedgerCard(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              const Text('这五条都能自己验',
                  style: TextStyle(fontSize: 15, fontWeight: FontWeight.w600)),
              const SizedBox(height: 6),
              Text('每条后面都写了在哪儿看得到。代码是开源的,写不出来的承诺我们不写。',
                  style: TextStyle(
                      fontSize: 12.5,
                      height: 1.55,
                      color: SzColors.dark.inkMuted)),
            ]),
          ),
          const SizedBox(height: 16),

          _promise(
            sz,
            '佣金 5% 封顶,而且只降不升',
            rate == null
                ? '单量越大费率越低,最低 4%。月度重算时取「档位费率」和「你现在的费率」'
                    '里更低的那个 —— 手工给你调低过的店,重算绝不会把它调回去。'
                : '你现在是 ${(rate * 100).toStringAsFixed(1)}%。'
                    '月度重算时取「档位费率」和「你现在的费率」里更低的那个 —— '
                    '手工给你调低过的店,重算绝不会把它调回去。',
            verify: '对账页「阶梯佣金」看你的真实费率与下一档还差多少单',
            onTap: _toFinance,
          ),

          _promise(
            sz,
            '配送费不抽成',
            '佣金只按**餐费**计。配送费、打包费不进佣金基数 —— '
            '配送费全额归骑手,平台一分不留。',
            verify: '对账页每一单都拆开列:餐费 / 佣金 / 到手,自己加一遍',
            onTap: _toFinance,
          ),

          _promise(
            sz,
            '券没核销就不收费',
            '团购券的佣金在**核销那一刻**才计算。用户买了没来吃、'
            '或者退款了,平台不收你一分钱。',
            verify: '券管理页里未核销的券,佣金一栏是空的',
          ),

          _promise(
            sz,
            '评价不删除,也不能花钱删',
            // 这一条最容易写成假话。真实边界照实写:
            // 商家自己删不了(reviews 路由只有回复与追评),没有任何付费删评路径;
            // 唯一能隐藏的是申诉被人工复核判成立(刷评/辱骂那种),
            // 而且隐藏后店铺评分会同步扣回,不是"删了还留着好评分"
            '你能做的只有回复和追评,删不了。平台也没有任何付费删评的口子。\n\n'
            '唯一的例外是**申诉**:遇到刷评、辱骂这类,你可以申诉,'
            '人工复核判成立才会隐藏 —— 而且隐藏后这条评分会从店铺总分里扣回去,'
            '不存在"删了差评还留着好评分"。',
            verify: '评价页只有「回复」按钮;申诉入口在「异常申诉」',
          ),

          _promise(
            sz,
            '出餐时长不用于排名,不影响曝光',
            '我们统计你的实测出餐时长,只用来三件事:给你自己看、'
            '让骑手知道大概等多久、给用户更准的送达时间。\n\n'
            '**不排名、不扣分、不影响你在用户端的曝光。** '
            '理由很实在:一旦这个数影响生意,你就会开始为它经营 —— '
            '比如菜还没好先点「出餐」—— 那这个数就废了,骑手和用户也跟着倒霉。',
            verify: '看板「出餐时长分布」里这条红线原样写着',
            onTap: () => Navigator.of(context).push(MaterialPageRoute<void>(
                builder: (_) => DashboardPage(api: widget.api))),
          ),

          _promise(
            sz,
            '配送的锅不用商家背',
            '配送由平台负责。用户评价时,配送方面的标签(送得慢/餐洒了等)'
            '只挂在骑手评分上,**从结构上就进不了你的店铺评分**。\n\n'
            '如果差评明明是配送超时导致的,你发起申诉时,系统会自动把这单的'
            '接单/出餐/送达时间线附给审核员 —— 出餐正常而配送晚了,证据替你说话。',
            verify: '评价页的「问题归因」里,配送类标签标着"不计入你的评分"',
          ),

          const SizedBox(height: 8),
          Text(
            '这几条写进代码里,不是写在这一页上。'
            '哪天我们自己违背了,你在对账页和看板上会先看出来。',
            style: TextStyle(fontSize: 11.5, height: 1.6, color: sz.inkMuted),
          ),
        ],
      ),
    );
  }

  Widget _promise(SzColors sz, String title, String body,
          {String? verify, VoidCallback? onTap}) =>
      Padding(
        padding: const EdgeInsets.only(bottom: 12),
        child: SzCard(
          onTap: onTap,
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Row(children: [
              Icon(Icons.check_circle_outline, size: 17, color: sz.earn),
              const SizedBox(width: 7),
              Expanded(
                child: Text(title,
                    style: const TextStyle(
                        fontSize: 14.5, fontWeight: FontWeight.w600)),
              ),
              if (onTap != null)
                Icon(Icons.chevron_right, size: 18, color: sz.inkFaint),
            ]),
            const SizedBox(height: 7),
            Text(body.replaceAll('**', ''),
                style: TextStyle(fontSize: 12.8, height: 1.6, color: sz.inkMuted)),
            if (verify != null) ...[
              const SizedBox(height: 8),
              Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Icon(Icons.visibility_outlined, size: 13, color: sz.link),
                const SizedBox(width: 5),
                Expanded(
                  child: Text('自己验:$verify',
                      style: TextStyle(
                          fontSize: 11.5, height: 1.45, color: sz.link)),
                ),
              ]),
            ],
          ]),
        ),
      );

  void _toFinance() {
    Navigator.of(context).pop();
    widget.onOpenFinance?.call();
  }
}

