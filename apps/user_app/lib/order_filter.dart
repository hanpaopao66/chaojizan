import 'package:superz_shared/superz_shared.dart';

/// 订单按状态分流。
///
/// ## 为什么「我的」页要有订单入口,而底部已经有一个订单 tab
///
/// 底部那个 tab 是**全部订单**的入口。「我的」页给的是**按状态直达** ——
/// 待支付、进行中、待评价各自一格,带数字角标。
///
/// **数字是它区别于那个 tab 的全部理由。** 四个不带数字的格子只是四个
/// 通往同一个列表的重复入口,那还不如没有。
///
/// ## 状态取自服务端状态机,不自造
///
/// 外卖走 `state_machine.py` 的 `OrderStatus`,住宿走 `StayOrderStatus` ——
/// **两套平行的状态机,互不共享**。所以这里分成两个 matches:
/// 拿外卖的 `paid` 去匹配住宿的 `paid` 只是字面碰巧一样,语义不同
/// (外卖的 paid 是"等商家接单",住宿的 paid 是"等商家确认")。
enum OrderFilter {
  all('全部'),
  pendingPayment('待支付'),
  active('进行中'),
  toReview('待评价'),
  refund('退款售后');

  const OrderFilter(this.label);

  final String label;

  /// 这一格该不该挂角标。
  ///
  /// 角标的意思是「你还有事要做」。退款到账、售后已受理都不是待办 ——
  /// 给它们挂个红数字,用户点进去发现什么也不用做,下次就不信这个角标了。
  bool get badged => this == pendingPayment ||
      this == active ||
      this == toReview;

  bool matchesFood(Order o) => switch (this) {
        OrderFilter.all => true,
        OrderFilter.pendingPayment => o.status == OrderStatus.pendingPayment,
        OrderFilter.active => const {
            OrderStatus.paid,
            OrderStatus.accepted,
            OrderStatus.ready,
            OrderStatus.pickedUp,
            // delivered 也算进行中:骑手放下了,但用户还没「确认收货」,
            // 而确认收货是**用户要做的事**(订单详情里那个按钮)。
            // 漏掉它的话这一单在四格和筛选里全都找不到,
            // 只能在「全部」里翻 —— 这是 order_filter_test 的覆盖率断言抓到的
            OrderStatus.delivered,
          }.contains(o.status),
        // delivered 还没确认收货,评价接口那边是 409 —— 别把它算成待评价,
        // 用户点进去会发现评不了
        OrderFilter.toReview =>
          o.status == OrderStatus.completed && !o.hasReview,
        OrderFilter.refund =>
          o.status == OrderStatus.cancelled || o.refundCents > 0,
      };

  bool matchesStay(StayOrder o) => switch (this) {
        OrderFilter.all => true,
        // created = 已下单待支付,**15 分钟不付就自动关闭**。
        // 漏数它不是密度问题,是用户真金白银的损失
        OrderFilter.pendingPayment => o.status == 'created',
        OrderFilter.active =>
          const {'paid', 'confirmed', 'checked_in'}.contains(o.status),
        // 住宿评价是另一条线(见 e2e_stays_review),这里不认领 ——
        // 认领了就得给一个算不出来的数字
        OrderFilter.toReview => false,
        OrderFilter.refund =>
          const {'cancelled', 'rejected', 'noshow'}.contains(o.status) ||
              o.refundCents > 0,
      };
}
