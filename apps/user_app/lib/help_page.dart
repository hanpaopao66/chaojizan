import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';

import 'session.dart';

/// 帮助中心:高频问题 FAQ + 客服入口。内容与平台规则口径一致。
///
/// FAQ 支持服务端下发(#122):后台改一条不用发版。但 [_faqs] 这份
/// **完整**的本地默认值必须留着 —— 首次启动、断网、接口挂了,
/// 用户点进帮助中心看到的应该是完整内容,而不是一个空列表。
class HelpCenterPage extends StatelessWidget {
  const HelpCenterPage({super.key, required this.api});

  final ApiClient api;

  /// 本地默认值(兜底用,不能删)
  static const _faqs = [
    (
      '配送范围是多少?为什么我看不到某家店?',
      '商家配送范围按直线距离计算(一般 3-5 公里)。你看到的列表按当前定位或所选'
          '收货地址周边展示;超出范围的店铺不会出现。所在区域未开通时,会展示演示城市的商家。'
    ),
    (
      '下单后多久送达?',
      '商家承诺出餐时长在店铺页可见(一般 15 分钟内),配送时长按距离预估。'
          '订单页可以实时查看骑手位置与配送进度。'
    ),
    (
      '怎么申请退款/售后?',
      '送达后 7 天内可在订单详情页申请售后,说明原因并上传凭证;商家同意后全额原路退款。'
          '未接单前可随时自助取消,已支付金额原路退回。'
    ),
    (
      '吃出问题(异物/变质)怎么办?',
      '订单详情页有「食品安全投诉」红线通道,拍照举证后直达平台加急处理,不经商家;'
          '核实成立将全额退款,问题商家会被下架处理。'
    ),
    (
      '配送费是怎么算的?',
      '配送费按距离计价,规则公开,且 100% 归配送骑手,平台分文不取。'
          '每一单的资金流向(商家实收/骑手所得/平台留存)都可以在订单里查看。'
    ),
    (
      '团购券怎么用?能退吗?',
      '在「超值团购」购买后,到店出示券码由商家扫码核销。未使用的券随时可全额退款,'
          '过期未使用也可以退。'
    ),
    (
      '住宿订单可以取消吗?',
      '每个房型的取消政策在预订前明确展示:免费取消截止时刻前取消全额退款,'
          '之后按政策收取费用。有疑问可联系酒店前台或平台客服。'
    ),
    (
      '怎么开发票?',
      '现阶段请通过「我的-开发票」联系商家或平台客服协助开票;'
          '电子发票功能将在接入微信支付后开放。'
    ),
    (
      '商家怎么入驻?骑手怎么加入?',
      '商家:下载超级赞商家 App,提交经营资质,审核通过即可营业,服务费至多 5%。'
          '骑手:下载超级赞骑手 App,完成实名认证即可接单,配送费 100% 归骑手。'
          '详见官网 chaojizan.cc。'
    ),
    (
      '为什么说超级赞账目透明?',
      '平台只收商家至多 5% 服务费(团购核销 2%),配送费全归骑手;'
          '每笔订单的分账明细对用户、商家、骑手三方公开,'
          '平台整体账本在「我的-为什么选择超级赞」可查。'
    ),
  ];

  static List<FaqItem> get _localFaq =>
      [for (final (q, a) in _faqs) FaqItem(q, a)];

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('帮助中心')),
      body: ListView(
        padding: const EdgeInsets.symmetric(vertical: 8),
        children: [
          for (final item in RemoteCopy.faq(_localFaq))
            ExpansionTile(
              title:
                  Text(item.question, style: const TextStyle(fontSize: 14.5)),
              childrenPadding: const EdgeInsets.fromLTRB(16, 0, 16, 12),
              expandedCrossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(item.answer,
                    style: TextStyle(
                        height: 1.7,
                        color: Theme.of(context).colorScheme.onSurfaceVariant)),
              ],
            ),
          const SizedBox(height: 16),
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 16),
            child: OutlinedButton.icon(
              icon: const Icon(Icons.support_agent_outlined),
              label: const Text('仍未解决?联系平台客服'),
              onPressed: () async {
                if (!await ensureLoggedIn(context)) return;
                if (!context.mounted) return;
                await Navigator.of(context).push(MaterialPageRoute(
                    builder: (_) => SupportPage(api: api)));
              },
            ),
          ),
          const SizedBox(height: 24),
        ],
      ),
    );
  }
}

/// 意见反馈:类型 + 描述,走客服工单接口(管理后台统一处理)。
class FeedbackPage extends StatefulWidget {
  const FeedbackPage({super.key, required this.api});

  final ApiClient api;

  @override
  State<FeedbackPage> createState() => _FeedbackPageState();
}

class _FeedbackPageState extends State<FeedbackPage> {
  static const _kinds = ['功能建议', '体验问题', '商家相关', '配送相关', '其他'];
  String _kind = _kinds.first;
  final _content = TextEditingController();
  bool _busy = false;

  Future<void> _submit() async {
    final text = _content.text.trim();
    if (text.length < 4) {
      ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('请描述具体内容(至少 4 个字)')));
      return;
    }
    setState(() => _busy = true);
    try {
      await widget.api.submitTicket('【意见反馈·$_kind】$text');
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('已收到,感谢你的反馈!可在「联系平台客服」查看回复')));
      Navigator.of(context).pop();
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(e.toString())));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('意见反馈')),
      body: ListView(padding: const EdgeInsets.all(16), children: [
        Text('反馈类型', style: Theme.of(context).textTheme.titleSmall),
        const SizedBox(height: 8),
        Wrap(
          spacing: 8,
          children: [
            for (final k in _kinds)
              ChoiceChip(
                label: Text(k),
                selected: _kind == k,
                onSelected: (_) => setState(() => _kind = k),
              ),
          ],
        ),
        const SizedBox(height: 16),
        TextField(
          controller: _content,
          maxLines: 6,
          maxLength: 500,
          decoration: const InputDecoration(
              hintText: '说说你的建议或遇到的问题,我们都会看',
              border: OutlineInputBorder()),
        ),
        const SizedBox(height: 12),
        FilledButton(
          onPressed: _busy ? null : _submit,
          child: Text(_busy ? '提交中…' : '提交反馈'),
        ),
      ]),
    );
  }
}
