import { promptAction } from '@kit.ArkUI';
import { UserApi } from './UserApi';
import { ApiException } from './Api';
import { Order, OrderStatus, WechatPrepay } from '../model/Models';

/**
 * 支付统一入口。
 *
 * 语义和 Flutter 端的 `payment_service.dart` 保持一致(那边刚在 #190 改过):
 * **支付不成时不抛异常,而是原样返回状态仍为 pending_payment 的订单**,
 * 由调用方判状态。这样"待支付"的单永远能从订单列表回来重付,
 * 而不是丢在那儿等 15 分钟后被自动清扫。
 *
 * ## 接入微信鸿蒙 SDK 时改这里
 *
 * 1. 从微信开放平台下鸿蒙 NEXT 的 OpenSDK(≥1.0.5)HAR 包,
 *    放进 `entry/libs/` 并在 `oh-package.json5` 里声明依赖;
 * 2. 在应用启动时注册 appId;
 * 3. 把下面 TODO 处换成 SDK 的调起支付调用,参数就是 prepay 返回的那几个字段;
 * 4. **支付结果以服务端回调为准**,客户端返回值只做展示 ——
 *    回调 `/payments/wechat/notify` 才是入账的唯一入口。
 */
export async function payOrder(api: UserApi, order: Order): Promise<Order> {
  try {
    const params: WechatPrepay = await api.wechatPrepay(order.order_no);
    // TODO(联调): 调微信鸿蒙 OpenSDK 拉起支付,参数:
    //   appid / partnerid / prepayid / package / noncestr / timestamp / sign
    // 然后轮询 getOrder 确认服务端已入账。
    //
    // **在 SDK 接上之前不许假装成功。** 商户参数已经配好却骗用户说付好了,
    // 比"暂时不能付"糟糕得多:他会以为订单已支付,坐等送餐
    if (params.prepayid !== undefined) {
      promptAction.showToast({
        message: '微信支付客户端尚未接入,订单已保留为「待支付」,可稍后继续支付',
        duration: 4000,
      });
      return order;
    }
    return order;
  } catch (e) {
    const err: ApiException = e as ApiException;
    if (err.statusCode === 503) {
      // 商户号未配置:开发模式,走模拟支付。**要明确标注是模拟的**
      try {
        const paid: Order = await api.mockPay(order.order_no);
        promptAction.showToast({
          message: '本单为模拟支付(开发模式),没有真实扣款',
          duration: 3000,
        });
        return paid;
      } catch (e2) {
        const err2: ApiException = e2 as ApiException;
        if (err2.statusCode === 403) {
          promptAction.showToast({
            message: '支付暂不可用:微信支付尚未接入,模拟支付也已关闭',
            duration: 4000,
          });
          return order;
        }
        promptAction.showToast({ message: err2.message });
        return order;
      }
    }
    promptAction.showToast({ message: err.message });
    return order;
  }
}

/** 付成功了没。**不要"拿到订单就当成功"**,要看状态 */
export function isPaid(order: Order): boolean {
  return order.status !== OrderStatus.PENDING_PAYMENT;
}
