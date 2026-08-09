import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';

/// 三条业务线(外卖/跑腿、住宿、团购)的统一支付入口。
///
/// 这里只允许两种结局,因为只有这两种是**真话**:
///   · 模拟通道走通了(商户号没配 = 开发环境):算付款成功,但界面必须写明是模拟支付;
///   · 没走通:订单原样留在「待支付」,并告诉用户去哪儿接着付。
///
/// 被删掉的是第三种 —— 拿到微信 prepay 参数后偷偷回退 `mockPay`。
/// 生产 `MOCK_PAY_ENABLED=false`(server/app/config.py:49),那条路的终点是
/// `orders.py:703` 抛的 403「模拟支付已关闭」;而在开发库里它更糟:
/// 用户一分钱没付,订单却被记成已支付。拿不准的时候,宁可让单子挂着。
///
/// ## fluwx 接入清单(要正式商户号 + appId,属外部依赖,不在本批次)
/// 1. `pubspec.yaml` 加 fluwx;`main()` 里 `registerWxApi(appId: WX_APP_ID)`;
/// 2. 把 [payOrder] 里 `_sdkNotWired(...)` 那一行换成:
///    `await fluwx.payWithWeChat(appId: p['appid'], partnerId: p['partnerid'],`
///    `  prepayId: p['prepayid'], packageValue: p['package'],`
///    `  nonceStr: p['noncestr'], timeStamp: int.parse(p['timestamp']),`
///    `  sign: p['sign']);`
/// 3. SDK 回调**不能**直接当成功:轮询 `api.getOrder(order.orderNo)` 到状态离开
///    `pending_payment` 为止 —— 以服务端收到的微信回调为准,客户端结果只做展示;
/// 4. 住宿/团购要同等待遇,得先给 `stays.py` / `vouchers.py` 补统一下单接口
///    (现在两边都只有 `pay/mock`,见 [payStayOrder] 的注释)。
/// 具体步骤见 docs/INTEGRATIONS.md
Future<Order> payOrder(ApiClient api, Order order, BuildContext context) async {
  // 先把 messenger 抓在手里:await 之后页面可能已经被 pop 掉,
  // 但"这一单到底付没付"必须让用户看见,不能因为路由变了就静默吞掉
  final messenger = ScaffoldMessenger.of(context);
  final Map<String, dynamic> prepay;
  try {
    prepay = await api.wechatPrepay(order.orderNo);
  } on ApiException catch (e) {
    if (e.statusCode == 503) {
      // 商户号未配置 = 开发环境。这是唯一允许的降级
      return _mockPayOrder(api, order, messenger);
    }
    // 409 是「订单不是待支付状态」(多半已经付过了),这时候再说"已保留为待支付"
    // 就是自相矛盾;其余情况(下单失败、断网)才提示单子还留着
    if (e.statusCode == 409) {
      _say(messenger, e.message);
    } else {
      _keepPending(messenger, e.message);
    }
    return order;
  }
  // 能拿到 prepay 参数,说明商户号是好的、微信那边已经挂上了这笔单。
  // 此时再回退模拟支付,就是"用户没掏钱、系统记已付" —— 绝不能做
  _sdkNotWired(messenger, prepay);
  return order;
}

/// 住宿单支付。
///
/// **住宿线没有微信统一下单接口**:`/orders/{no}/pay/wechat`
/// (server/app/routers/payments.py:20)只认外卖订单表,`stays.py` 那边只有
/// `pay/mock`。所以这里没得选,只剩模拟通道 —— 付成了也必须标明是模拟的。
/// 付不成返回 null,单子留在「待支付」,由调用方如实告诉用户。
///
/// 顺带记一笔:`stays.py:602` / `vouchers.py:206` 的 mock 支付**没有**
/// `orders.py:703` 那道 `MOCK_PAY_ENABLED` 闸门,生产环境等于白送订单。
/// 那是服务端的口子,本批次动不了,已写进报告。
Future<StayOrder?> payStayOrder(
    ApiClient api, StayOrder order, BuildContext context) async {
  final messenger = ScaffoldMessenger.of(context);
  try {
    final paid = await api.payStayMock(order.orderNo);
    _mockNotice(messenger);
    return paid;
  } on ApiException catch (e) {
    _keepPending(messenger, _payChannelReason(e), where: '「订单」页');
    return null;
  }
}

/// 团购券购买支付。与 [payStayOrder] 同处境:`vouchers.py` 只有 `pay/mock`。
/// 付不成返回 null,购买记录留在「待支付」,不许显示"抢购成功"。
Future<VoucherTicket?> payVoucherTicket(
    ApiClient api, VoucherTicket ticket, BuildContext context) async {
  final messenger = ScaffoldMessenger.of(context);
  try {
    final paid = await api.payVoucherMock(ticket.purchaseNo);
    _mockNotice(messenger);
    return paid;
  } on ApiException catch (e) {
    _keepPending(messenger, _payChannelReason(e), where: '「我的券包」');
    return null;
  }
}

Future<Order> _mockPayOrder(
    ApiClient api, Order order, ScaffoldMessengerState messenger) async {
  try {
    final paid = await api.mockPay(order.orderNo);
    _mockNotice(messenger);
    return paid;
  } on ApiException catch (e) {
    _keepPending(messenger, _payChannelReason(e));
    return order; // 仍是 pending_payment,调用方据此判断没付成
  }
}

/// `mockPay` 的 403 原文是「模拟支付已关闭,请使用微信支付」——
/// 可用户偏偏是因为微信支付还没接好才走到这条路上的,原样甩给他等于让他自己猜。
String _payChannelReason(ApiException e) => e.statusCode == 403
    ? '支付暂不可用:微信支付尚未接入,模拟支付也已关闭'
    : e.message;

/// 模拟支付的提示短一些:SnackBar 是排队显示的,调用方紧接着还要报下单结果,
/// 这条占太久会把真正要点的那条(带「去查看」)压在后面
void _mockNotice(ScaffoldMessengerState messenger) =>
    _say(messenger, '本单为模拟支付(开发模式),没有真实扣款', seconds: 3);

/// 商户参数齐了但客户端 SDK 还没接。不假装成功,把单子留给用户自己决定什么时候付。
void _sdkNotWired(
    ScaffoldMessengerState messenger, Map<String, dynamic> prepay) {
  // 参数只在调试日志里落一次,方便联调时核对字段;界面上不出现这些内部字段
  debugPrint('微信 prepay 参数已就绪(${prepay.keys.join(",")}),等待 SDK 接入');
  _keepPending(messenger, '微信支付客户端尚未接入');
}

void _keepPending(ScaffoldMessengerState messenger, String reason,
        {String where = '订单列表'}) =>
    _say(messenger, '$reason。订单已保留为「待支付」,可稍后在$where继续支付');

void _say(ScaffoldMessengerState messenger, String text, {int seconds = 6}) =>
    messenger.showSnackBar(SnackBar(
      content: Text(text),
      duration: Duration(seconds: seconds),
    ));
