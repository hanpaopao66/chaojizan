import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';

/// 支付统一入口:优先微信支付,商户号未配置(503)自动降级到模拟支付。
///
/// 联调微信支付时:
///   1. pubspec 加 fluwx 依赖,main() 里 registerWxApi(appId: WX_APP_ID)
///   2. 把下面 TODO 处换成 fluwx 的 payWithWeChat(...),参数就是 prepay 返回的字段
///   3. 支付结果回调后轮询订单状态确认(以服务端回调为准,客户端结果只做展示)
/// 具体步骤见 docs/INTEGRATIONS.md
Future<Order> payOrder(ApiClient api, Order order, BuildContext context) async {
  try {
    final params = await api.wechatPrepay(order.orderNo);
    // TODO(联调): fluwx.payWithWeChat(
    //   appId: params['appid'], partnerId: params['partnerid'],
    //   prepayId: params['prepayid'], packageValue: params['package'],
    //   nonceStr: params['noncestr'], timeStamp: int.parse(params['timestamp']),
    //   sign: params['sign'],
    // ) 然后等服务端回调把订单置为已支付,轮询 getOrder 确认。
    // 商户参数已配置但客户端 SDK 还没接时,先提示并回退模拟支付,保证流程不断:
    debugPrint('微信 prepay 参数已就绪: $params');
    if (context.mounted) {
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
          content: Text('微信支付参数已就绪,客户端 SDK 待接入,本单走模拟支付')));
    }
    return api.mockPay(order.orderNo);
  } on ApiException catch (e) {
    if (e.statusCode == 503) {
      // 商户号未配置:开发模式,模拟支付
      return api.mockPay(order.orderNo);
    }
    rethrow;
  }
}
