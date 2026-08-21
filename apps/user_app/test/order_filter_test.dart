import 'package:flutter_test/flutter_test.dart';
import 'package:superz_shared/superz_shared.dart';
import 'package:user_app/order_filter.dart';

/// 订单状态分流(#296)。
///
/// 「我的」页四格和订单 tab 的筛选共用这一份判断。它的风险是**悄悄漏单**:
/// 状态机加一个新状态,而这里没人跟上 —— 那个状态的订单就从此不属于任何
/// 一格,用户在哪个筛选下都找不到它,而测试全绿。
///
/// 所以这里锁的不是"某个状态归哪一格",是**覆盖率**:
/// 每一个 OrderStatus 都得至少被一个筛选认领。
void main() {
  Order order({
    OrderStatus status = OrderStatus.completed,
    bool hasReview = false,
    int refund = 0,
  }) =>
      Order.fromJson({
        'order_no': 'SZ1',
        'merchant_id': 1,
        'status': status.value,
        'items': const [],
        'food_cents': 2000,
        'delivery_fee_cents': 300,
        'total_cents': 2300,
        'refund_cents': refund,
        'has_review': hasReview,
        'address': 'x',
        'lat': 30.0,
        'lng': 104.0,
        'created_at': '2026-08-20T12:00:00+08:00',
      });

  StayOrder stay(String status) => StayOrder.fromJson({
        'order_no': 'ST1',
        'checkin_date': '2026-09-01',
        'checkout_date': '2026-09-02',
        'status': status,
      });

  test('每个外卖状态都被某一格认领,一个都不漏', () {
    for (final s in OrderStatus.values) {
      final o = order(status: s);
      final hit = OrderFilter.values
          .where((f) => f != OrderFilter.all && f.matchesFood(o))
          .toList();
      expect(hit, isNotEmpty,
          reason: '「${s.label}」不属于任何一格 —— '
              '这个状态的订单在四格和筛选里都找不到');
    }
  });

  test('每个住宿状态都被某一格认领', () {
    // 与 state_machine.py 的 StayOrderStatus 一一对应
    const all = [
      'created', 'closed', 'paid', 'confirmed', 'checked_in',
      'completed', 'cancelled', 'rejected', 'noshow',
    ];
    for (final s in all) {
      // closed(超时关闭)和 completed(已离店)只在「全部」里 ——
      // 它们既不是待办也不是退款,这是**故意的**,所以单独放行
      if (s == 'closed' || s == 'completed') continue;
      final hit = OrderFilter.values
          .where((f) => f != OrderFilter.all && f.matchesStay(stay(s)))
          .toList();
      expect(hit, isNotEmpty, reason: '住宿状态「$s」不属于任何一格');
    }
  });

  test('已评价的完成单不再算待评价', () {
    expect(
        OrderFilter.toReview
            .matchesFood(order(status: OrderStatus.completed, hasReview: true)),
        isFalse);
    expect(
        OrderFilter.toReview.matchesFood(
            order(status: OrderStatus.completed, hasReview: false)),
        isTrue);
  });

  test('已送达但没确认收货的单不算待评价 —— 那时评价接口是 409', () {
    expect(OrderFilter.toReview.matchesFood(order(status: OrderStatus.delivered)),
        isFalse,
        reason: '算进去的话用户点开发现评不了');
  });

  test('住宿的 created 属于待支付 —— 15 分钟不付就自动关闭,漏数是真损失', () {
    expect(OrderFilter.pendingPayment.matchesStay(stay('created')), isTrue);
  });

  test('外卖和住宿的 paid 语义不同,别混用', () {
    // 外卖 paid = 等商家接单(进行中);住宿 paid = 等商家确认(也进行中)
    // 两者恰好都算进行中,但**判断走各自的 matches**,不是同一张表
    expect(OrderFilter.active.matchesFood(order(status: OrderStatus.paid)), isTrue);
    expect(OrderFilter.active.matchesStay(stay('paid')), isTrue);
    // 而住宿没有「待评价」这一说(评价走另一条线),不能靠外卖那套推
    expect(OrderFilter.toReview.matchesStay(stay('completed')), isFalse);
  });

  test('有退款金额的单进退款售后,即使状态是已完成', () {
    expect(
        OrderFilter.refund
            .matchesFood(order(status: OrderStatus.completed, refund: 500)),
        isTrue,
        reason: '部分退款的单也得找得到');
  });

  test('「全部」认领所有状态', () {
    for (final s in OrderStatus.values) {
      expect(OrderFilter.all.matchesFood(order(status: s)), isTrue);
    }
  });
}
