import 'dart:async';

import 'package:flutter/material.dart';

import 'api_client.dart';
import 'brand.dart';
import 'net_image.dart';
import 'responsive.dart';
import 'sz_widgets.dart' show yuanOf;

/// 订单群(三端共用):一单一个群,你、商家、骑手都在里面。
///
/// 以前是「和商家」「和骑手」两条分开的私聊:出餐和配送本来是同一件事,用户却要在两个窗口里来回复述,
/// 商家和骑手之间也说不上话。现在照 Telegram 的群来:顶上一条置顶的订单条(左侧竖线 + 一行摘要 + 看订单),
/// 发言人名字按角色带色,服务消息是灰药丸,底下四个快捷回复 —— 骑手在电动车上、用户单手拿手机,都不该打字。
///
/// 群里不出现任何手机号;订单结束 24 小时后归档:还能翻,不能再发(服务端 `_CHAT_READONLY_HOURS`)。
/// 3 秒轮询兜底。老版本客户端发的私聊(带 to 的)服务端只给那两方,这里标一句「只有你们两个看得到」。
class OrderChatPage extends StatefulWidget {
  const OrderChatPage({
    super.key,
    required this.api,
    required this.orderNo,
    this.title = '',
    this.quickReplies = const [],
    this.onOpenOrder,
  });

  final ApiClient api;
  final String orderNo;

  /// 服务端没回来之前先显示的标题;回来以后用服务端的「订单 #尾号 · 店名」
  final String title;
  final List<String> quickReplies;

  /// 置顶条上的「看订单」:各端自己的订单详情页。不给就不显示这个按钮
  final VoidCallback? onOpenOrder;

  @override
  State<OrderChatPage> createState() => _OrderChatPageState();
}

class _OrderChatPageState extends State<OrderChatPage> {
  List<Map<String, dynamic>> _messages = [];
  List<Map<String, dynamic>> _members = [];
  Map<String, dynamic>? _order;
  String _title = '';
  bool _readonly = false;
  bool _loaded = false;
  final _input = TextEditingController();
  final _scroll = ScrollController();
  Timer? _timer;

  @override
  void initState() {
    super.initState();
    _title = widget.title;
    _load();
    _timer = Timer.periodic(const Duration(seconds: 3), (_) => _load());
  }

  @override
  void dispose() {
    _timer?.cancel();
    _input.dispose();
    _scroll.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    try {
      final r = await widget.api.orderMessages(widget.orderNo);
      if (!mounted) return;
      final msgs = (r['messages'] as List).cast<Map<String, dynamic>>();
      final grew = msgs.length != _messages.length;
      setState(() {
        _messages = msgs;
        _members = ((r['members'] as List?) ?? const []).cast<Map<String, dynamic>>();
        _order = r['order'] as Map<String, dynamic>?;
        _readonly = r['readonly'] == true;
        final t = '${r['title'] ?? ''}';
        if (t.isNotEmpty) _title = t;
        _loaded = true;
      });
      if (grew) {
        WidgetsBinding.instance.addPostFrameCallback((_) {
          if (_scroll.hasClients) _scroll.jumpTo(_scroll.position.maxScrollExtent);
        });
      }
    } catch (_) {}
  }

  Future<void> _send(String content, {String kind = 'text'}) async {
    final text = content.trim();
    if (text.isEmpty) return;
    try {
      await widget.api.sendOrderMessage(widget.orderNo, text, to: 'group', kind: kind);
      if (kind == 'text') _input.clear();
      await _load();
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(e.toString())));
    }
  }

  String _nameOf(String role) =>
      '${_members.firstWhere((m) => m['role'] == role, orElse: () => const {})['name'] ?? ''}';

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    final names = [for (final m in _members) '${m['name']}'];
    return SzPageScaffold(
      appBar: AppBar(
        titleSpacing: 0,
        title: Row(children: [
          Container(
            width: 34,
            height: 34,
            decoration: BoxDecoration(color: sz.claySoft, shape: BoxShape.circle),
            child: Icon(Icons.receipt_long_outlined, size: 18, color: sz.clay),
          ),
          const SizedBox(width: 10),
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(_title.isEmpty ? '订单群' : _title,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: TextStyle(fontSize: kFontTitle, fontWeight: FontWeight.w600, color: sz.ink)),
              if (names.isNotEmpty)
                Text(names.join('、'),
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: TextStyle(fontSize: kFontMicro, color: sz.inkMuted)),
            ]),
          ),
        ]),
      ),
      body: Column(children: [
        if (_order != null) _PinnedOrder(order: _order!, onOpen: widget.onOpenOrder),
        Expanded(
          child: ListView(
            controller: _scroll,
            padding: const EdgeInsets.fromLTRB(12, 4, 12, 8),
            children: [
              if (_loaded) _ServicePill(text: _serviceLine()),
              for (var i = 0; i < _messages.length; i++) ...[
                if (_timeBreak(i))
                  Padding(
                    padding: const EdgeInsets.only(top: 10, bottom: 2),
                    child: Center(
                      child: Text(_dayTime('${_messages[i]['created_at']}'),
                          style: TextStyle(fontSize: kFontMicro, color: sz.inkFaint)),
                    ),
                  ),
                _Bubble(message: _messages[i]),
              ],
              if (!_readonly && widget.quickReplies.isNotEmpty)
                Padding(
                  padding: const EdgeInsets.only(top: 10),
                  child: Wrap(spacing: 7, runSpacing: 7, children: [
                    for (final q in widget.quickReplies)
                      _QuickReply(text: q, onTap: () => _send(q, kind: 'quick')),
                  ]),
                ),
              Padding(
                padding: const EdgeInsets.only(top: 14, bottom: 2),
                child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Padding(
                    padding: const EdgeInsets.only(top: 2),
                    child: Icon(Icons.lock_outline, size: 13, color: sz.inkFaint),
                  ),
                  const SizedBox(width: 7),
                  Expanded(
                    child: Text('群里不出现手机号;订单结束 24 小时后自动归档,还能翻,不能再发。',
                        style: TextStyle(fontSize: kFontMicro, height: 1.6, color: sz.inkFaint)),
                  ),
                ]),
              ),
            ],
          ),
        ),
        if (_readonly)
          Container(
            width: double.infinity,
            padding: const EdgeInsets.fromLTRB(16, 12, 16, 12),
            decoration: BoxDecoration(
              color: sz.surfaceAlt,
              border: Border(top: BorderSide(color: sz.line)),
            ),
            child: SafeArea(
              top: false,
              child: Text('这一单的群已归档:还能翻,不能再发。有问题请走售后或客服工单',
                  textAlign: TextAlign.center,
                  style: TextStyle(fontSize: kFontNote, color: sz.inkMuted)),
            ),
          )
        else
          Container(
            decoration: BoxDecoration(
              color: sz.paper,
              border: Border(top: BorderSide(color: sz.line)),
            ),
            padding: const EdgeInsets.fromLTRB(12, 8, 8, 8),
            child: SafeArea(
              top: false,
              child: Row(children: [
                Expanded(
                  child: TextField(
                    controller: _input,
                    maxLength: 200,
                    textInputAction: TextInputAction.send,
                    onSubmitted: _send,
                    style: TextStyle(fontSize: kFontBodyLg, color: sz.ink),
                    decoration: InputDecoration(
                      hintText: '说点什么…',
                      counterText: '',
                      isDense: true,
                      filled: true,
                      fillColor: sz.surface,
                      contentPadding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
                      border: OutlineInputBorder(
                          borderRadius: BorderRadius.circular(19), borderSide: BorderSide(color: sz.line)),
                      enabledBorder: OutlineInputBorder(
                          borderRadius: BorderRadius.circular(19), borderSide: BorderSide(color: sz.line)),
                      focusedBorder: OutlineInputBorder(
                          borderRadius: BorderRadius.circular(19), borderSide: BorderSide(color: sz.clay)),
                    ),
                  ),
                ),
                IconButton(
                  tooltip: '发送',
                  onPressed: () => _send(_input.text),
                  icon: Icon(Icons.send_rounded, color: sz.clay),
                ),
              ]),
            ),
          ),
      ]),
    );
  }

  /// 群头下面那颗灰药丸:谁接的单、谁抢到的,和归档规则
  String _serviceLine() {
    final status = '${_order?['status'] ?? ''}';
    final parts = <String>[];
    final merchant = _nameOf('merchant');
    if (merchant.isNotEmpty && !const ['paid', 'pending_payment', 'cancelled'].contains(status)) {
      parts.add(merchant == '你' ? '你接了这一单' : '$merchant接单');
    }
    final rider = _nameOf('rider');
    if (rider.isNotEmpty) parts.add(rider == '你' ? '你抢到了这一单' : '$rider抢到这一单');
    parts.add('群在送达 24 小时后自动归档');
    return parts.join(' · ');
  }

  /// 和上一条隔了 5 分钟以上(或者是第一条)就插一行时间
  bool _timeBreak(int i) {
    if (i == 0) return true;
    final a = DateTime.tryParse('${_messages[i - 1]['created_at']}');
    final b = DateTime.tryParse('${_messages[i]['created_at']}');
    if (a == null || b == null) return false;
    return b.difference(a).inMinutes >= 5;
  }
}

String _two(int n) => n.toString().padLeft(2, '0');

String _hm(DateTime t) => '${_two(t.hour)}:${_two(t.minute)}';

/// 「今天 12:26」「昨天 21:03」「9-10 08:15」
String _dayTime(String iso) {
  final t = DateTime.tryParse(iso)?.toLocal();
  if (t == null) return '';
  final now = DateTime.now();
  final today = DateTime(now.year, now.month, now.day);
  final day = DateTime(t.year, t.month, t.day);
  final diff = today.difference(day).inDays;
  if (diff == 0) return '今天 ${_hm(t)}';
  if (diff == 1) return '昨天 ${_hm(t)}';
  return '${t.month}-${t.day} ${_hm(t)}';
}

/// 发言人名字的颜色按角色固定:商家砖红、骑手靛青(取自品牌色板里区分度最高的两个),顾客黏土
Color _roleColor(SzColors sz, String role) => switch (role) {
      'merchant' => sz.channelTones[0],
      'rider' => sz.channelTones[3],
      _ => sz.clay,
    };

/// TG 的置顶条:左侧竖线 + 「置顶消息 · 菜 · 金额」+ 状态和预计送达 + 看订单;下面一条四段进度
class _PinnedOrder extends StatelessWidget {
  const _PinnedOrder({required this.order, this.onOpen});

  final Map<String, dynamic> order;
  final VoidCallback? onOpen;

  static const _steps = ['accepted', 'ready', 'picked_up', 'delivered'];

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    final status = '${order['status'] ?? ''}';
    final label = '${order['status_label'] ?? ''}';
    final eta = DateTime.tryParse('${order['eta_at'] ?? ''}')?.toLocal();
    final summary = '${order['items_summary'] ?? ''}';
    final total = (order['total_cents'] as num?)?.toInt();
    final showEta = eta != null && const ['paid', 'accepted', 'ready', 'picked_up'].contains(status);
    final done = switch (status) {
      'accepted' => 1,
      'ready' => 2,
      'picked_up' => 3,
      'delivered' || 'completed' => 4,
      _ => 0,
    };
    final head = [if (summary.isNotEmpty) summary, if (total != null) yuanOf(total)].join(' · ');
    return Column(children: [
      Container(
        padding: const EdgeInsets.fromLTRB(14, 9, 12, 9),
        decoration: BoxDecoration(border: Border(bottom: BorderSide(color: sz.line))),
        child: IntrinsicHeight(
          child: Row(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
            Container(
                width: 2,
                decoration: BoxDecoration(color: sz.clay, borderRadius: BorderRadius.circular(2))),
            const SizedBox(width: 11),
            Expanded(
              child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  mainAxisAlignment: MainAxisAlignment.center,
                  children: [
                    Text.rich(
                      TextSpan(children: [
                        TextSpan(
                            text: '置顶消息',
                            style: TextStyle(color: sz.clay, fontWeight: FontWeight.w600)),
                        if (head.isNotEmpty)
                          TextSpan(text: '  $head', style: TextStyle(color: sz.inkMuted)),
                      ]),
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: const TextStyle(fontSize: kFontMicro),
                    ),
                    const SizedBox(height: 1),
                    Text.rich(
                      TextSpan(children: [
                        TextSpan(text: label),
                        if (showEta) ...[
                          const TextSpan(text: ' · 预计 '),
                          TextSpan(
                              text: _hm(eta),
                              style: szMoney(fontSize: kFontBody, color: sz.ink)),
                          const TextSpan(text: ' 送达'),
                        ],
                      ]),
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: TextStyle(fontSize: kFontBody, color: sz.ink),
                    ),
                  ]),
            ),
            if (onOpen != null)
              Center(
                child: Material(
                  color: sz.earn.withValues(alpha: .12),
                  shape: const StadiumBorder(),
                  child: InkWell(
                    customBorder: const StadiumBorder(),
                    onTap: onOpen,
                    child: Padding(
                      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
                      child: Text('看订单',
                          style: TextStyle(
                              fontSize: kFontMicro, fontWeight: FontWeight.w600, color: sz.earn)),
                    ),
                  ),
                ),
              ),
          ]),
        ),
      ),
      if (status != 'cancelled')
        Padding(
          padding: const EdgeInsets.fromLTRB(14, 8, 14, 6),
          child: Row(children: [
            for (var i = 0; i < _steps.length; i++) ...[
              if (i > 0)
                Expanded(child: Container(height: 2, color: i < done ? sz.earn : sz.line)),
              Container(
                width: 7,
                height: 7,
                decoration: BoxDecoration(color: i < done ? sz.earn : sz.line, shape: BoxShape.circle),
              ),
            ],
          ]),
        ),
    ]);
  }
}

class _ServicePill extends StatelessWidget {
  const _ServicePill({required this.text});

  final String text;

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    return Padding(
      padding: const EdgeInsets.only(top: 6),
      child: Center(
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 5),
          decoration: BoxDecoration(color: sz.line.withValues(alpha: .7), borderRadius: BorderRadius.circular(999)),
          child: Text(text,
              textAlign: TextAlign.center,
              style: TextStyle(fontSize: kFontMicro, height: 1.5, color: sz.inkMuted)),
        ),
      ),
    );
  }
}

class _Bubble extends StatelessWidget {
  const _Bubble({required this.message});

  final Map<String, dynamic> message;

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    final mine = message['mine'] == true;
    final role = '${message['from'] ?? ''}';
    final name = '${message['sender_name'] ?? ''}';
    final label = role == 'rider' && name != '骑手' ? '$name · 骑手' : name;
    final time = DateTime.tryParse('${message['created_at']}')?.toLocal();
    final content = message['kind'] == 'image'
        ? ClipRRect(
            borderRadius: BorderRadius.circular(8),
            child: Image(image: szNetImage('${message['content']}'), width: 180, fit: BoxFit.cover),
          )
        : Text('${message['content']}',
            style: TextStyle(fontSize: kFontBodyLg, height: 1.5, color: sz.ink));
    final timeText = time == null
        ? const SizedBox.shrink()
        : Padding(
            padding: const EdgeInsets.only(bottom: 2),
            child: Text(_hm(time), style: szMoney(fontSize: kFontMicro, fontWeight: FontWeight.w400, color: sz.inkFaint)),
          );
    final private = message['private'] == true;
    final bubble = Container(
      constraints: const BoxConstraints(maxWidth: 250),
      padding: EdgeInsets.fromLTRB(12, mine ? 9 : 8, 12, 9),
      decoration: BoxDecoration(
        color: mine ? sz.claySoft : sz.surface,
        border: mine ? null : Border.all(color: sz.line),
        borderRadius: BorderRadius.only(
          topLeft: const Radius.circular(12),
          topRight: const Radius.circular(12),
          bottomLeft: Radius.circular(mine ? 12 : 4),
          bottomRight: Radius.circular(mine ? 4 : 12),
        ),
      ),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisSize: MainAxisSize.min, children: [
        if (!mine && label.isNotEmpty)
          Padding(
            padding: const EdgeInsets.only(bottom: 1),
            child: Text(label,
                style: TextStyle(fontSize: kFontNote, fontWeight: FontWeight.w600, color: _roleColor(sz, role))),
          ),
        content,
        if (private)
          Padding(
            padding: const EdgeInsets.only(top: 2),
            child: Text('只有你们两个看得到', style: TextStyle(fontSize: kFontMicro, color: sz.inkFaint)),
          ),
      ]),
    );
    return Padding(
      padding: const EdgeInsets.only(top: 10),
      child: Row(
        mainAxisAlignment: mine ? MainAxisAlignment.end : MainAxisAlignment.start,
        crossAxisAlignment: CrossAxisAlignment.end,
        children: mine
            ? [timeText, const SizedBox(width: 8), Flexible(child: bubble)]
            : [
                _Avatar(name: name, role: role),
                const SizedBox(width: 8),
                Flexible(child: bubble),
                const SizedBox(width: 8),
                timeText,
              ],
      ),
    );
  }
}

class _Avatar extends StatelessWidget {
  const _Avatar({required this.name, required this.role});

  final String name;
  final String role;

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    final merchant = role == 'merchant';
    final initial = name.isEmpty ? '?' : name.characters.first;
    return Container(
      width: 30,
      height: 30,
      alignment: Alignment.center,
      decoration: BoxDecoration(color: merchant ? sz.claySoft : sz.line, shape: BoxShape.circle),
      child: Text(initial,
          style: szDisplay(
              fontSize: kFontNote, color: merchant ? sz.clay : sz.inkMuted, height: 1)),
    );
  }
}

class _QuickReply extends StatelessWidget {
  const _QuickReply({required this.text, required this.onTap});

  final String text;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    return Material(
      color: sz.surface,
      shape: StadiumBorder(side: BorderSide(color: sz.line)),
      child: InkWell(
        customBorder: const StadiumBorder(),
        onTap: onTap,
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
          child: Text(text, style: TextStyle(fontSize: kFontBody, color: sz.ink)),
        ),
      ),
    );
  }
}

/// 各端预设快捷语。用户端照设计稿:骑手问「放门口还是下来拿」时一下就能回
const kCustomerQuickReplies = ['放门口就行', '我下来拿', '稍等两分钟', '谢谢'];
const kRiderQuickReplies = ['已到店等出餐', '已取餐,马上到', '到楼下了', '已放门口,注意查收'];
const kMerchantQuickReplies = ['收到,马上做', '今天有点忙,稍等', '已出餐'];
