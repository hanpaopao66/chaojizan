-- 生产库脏数据核查（全部只读 SELECT，不改任何数据）
--
-- 用法（在部署机上）：
--   docker exec -i deploy-db-1 psql -U superz -d superz -f - < docs/PROD-INTEGRITY-CHECK.sql
--
-- 先跑 #1 #2 #3 #4 —— 这四条直接决定要不要写退款数据修复脚本，
-- 是唯一涉及真金白银流出的。#3 决定 #4 是否已经在发作。

-- ============ 退款 ============
-- refunds 表自 0107 起装三条业务线,用 biz_type + biz_id 区分;
-- order_id / order_no 只有外卖行有(券和住宿是 NULL)。
--
-- ⚠️ 迁移到 0107 之后,券和住宿的历史退款**一条流水都没有**
--    (接渠道之前它们只改了个状态字段)。先跑 #1b #1c 看存量,
--    再执行一次 POST /admin/audit/backfill 把历史流水补录进去,
--    否则每日自检会对每一笔历史退款报一条。

-- #1 外卖:退款汇总与流水明细不恒等
SELECT o.id, o.order_no, o.total_cents, o.refund_cents, COALESCE(r.s,0) AS refunds_sum
FROM orders o
LEFT JOIN (SELECT biz_id, SUM(amount_cents) s FROM refunds
           WHERE biz_type = 'food' AND status <> 'failed' GROUP BY 1) r
       ON r.biz_id = o.id
WHERE o.refund_cents <> COALESCE(r.s,0)
ORDER BY abs(o.refund_cents - COALESCE(r.s,0)) DESC LIMIT 50;

-- #1b 团购券:标着已退款,但流水之和 ≠ 售价(应退额只有"全额退"一种口径)
SELECT p.id, p.purchase_no, p.sell_price_cents, COALESCE(r.s,0) AS refunds_sum
FROM voucher_purchases p
LEFT JOIN (SELECT biz_id, SUM(amount_cents) s FROM refunds
           WHERE biz_type = 'voucher' AND status <> 'failed' GROUP BY 1) r
       ON r.biz_id = p.id
WHERE p.status = 'refunded' AND p.sell_price_cents <> COALESCE(r.s,0)
ORDER BY p.id DESC LIMIT 50;

-- #1c 住宿:流水之和 ≠ **能原路退回去**的部分 = least(refund_cents, total_cents)。
--     不是 refund_cents —— 到店无房的退款额含商家违约金,本来就超过用户实付
SELECT o.id, o.order_no, o.status, o.total_cents, o.refund_cents,
       least(o.refund_cents, o.total_cents) AS channel_due,
       COALESCE(r.s,0) AS refunds_sum
FROM stay_orders o
LEFT JOIN (SELECT biz_id, SUM(amount_cents) s FROM refunds
           WHERE biz_type = 'stay' AND status <> 'failed' GROUP BY 1) r
       ON r.biz_id = o.id
WHERE o.status IN ('cancelled','noshow','rejected') AND o.refund_cents > 0
  AND least(o.refund_cents, o.total_cents) <> COALESCE(r.s,0)
ORDER BY o.id DESC LIMIT 50;

-- #1d 到店无房的违约金:超过用户实付、退款通道退不了,等转账到零钱接入。
--     这不是错账,是**挂着的负债**(商家余额已扣、用户没拿到)
SELECT count(*) AS n, COALESCE(SUM(o.refund_cents - o.total_cents),0) AS owed_cents
FROM stay_orders o
JOIN stay_after_sales a ON a.stay_order_id = o.id
WHERE o.refund_cents > o.total_cents
  AND a.kind = 'no_room' AND a.status IN ('accepted','auto_accepted');

-- #2 同一单既有 accepted 售后又有 confirmed 食安投诉 = 极可能双重退款
SELECT o.id, o.order_no, o.total_cents, o.refund_cents
FROM orders o
JOIN after_sales a         ON a.order_id = o.id AND a.status = 'accepted'
JOIN food_safety_reports f ON f.order_id = o.id AND f.status = 'confirmed';

-- #3 微信通道是否真的在用（全 '' 说明还是模拟通道，则 #4 尚未发作）
SELECT count(*) FILTER (WHERE wx_transaction_id <> '') AS with_txid,
       count(*) FILTER (WHERE wx_transaction_id = '')  AS without_txid
FROM orders WHERE status NOT IN ('pending_payment','cancelled');

-- #4 退款发起失败（三条业务线一起看：钱没退出去，业务表却写着已退）
SELECT r.id, r.biz_type, r.biz_id, r.order_no, r.amount_cents, r.status, r.error
FROM refunds r WHERE r.status = 'failed' ORDER BY r.id DESC LIMIT 50;

-- #5 退款额超过订单金额（超退粗筛）
SELECT id, order_no, status, total_cents, refund_cents
FROM orders WHERE refund_cents > total_cents AND status <> 'cancelled';

-- #6 total_cents 为负（满减+缺货退款那条 bug 的存量面）
SELECT id, order_no, status, food_cents, discount_cents, total_cents, refund_cents
FROM orders WHERE total_cents < 0;

-- ============ 账号注销 ============
-- #7 已注销账号总数
SELECT count(*) FROM users WHERE phone LIKE 'del%';
-- #8 已注销骑手仍标记在线（污染在线数与派单广播）
SELECT count(*) FROM users WHERE phone LIKE 'del%' AND is_online;
-- #9 已注销账号的邀请码仍可解析
SELECT count(*) FROM users WHERE phone LIKE 'del%' AND ref_code IS NOT NULL;
-- #10 已注销账号还挂着待打款的提现
SELECT w.id, w.amount_cents, w.status FROM withdrawals w JOIN users u ON u.id = w.user_id
WHERE u.phone LIKE 'del%' AND w.status = 'pending';
-- #11 已注销用户仍在商家员工名单里（手机号会渲染成 del****xxxx）
SELECT s.merchant_id, s.user_id FROM merchant_staff s JOIN users u ON u.id = s.user_id
WHERE u.phone LIKE 'del%';
-- #12 已注销骑手的实名信息仍在库（与注销页文案冲突）
SELECT count(*) FROM rider_profiles p JOIN users u ON u.id = p.rider_id
WHERE u.phone LIKE 'del%' AND (p.real_name <> '' OR p.id_no_encrypted <> '');

-- ============ 迁移回填遗留 ============
-- #13 0031：终态单被写上了无意义的 rider_pool_since
SELECT count(*) FROM orders
WHERE rider_pool_since = created_at AND status IN ('cancelled','completed');
-- #14 0094：fee_parts 只剩 base（夜间/天气/上门分项永久丢失）
SELECT count(*) FROM orders
WHERE delivery_fee_cents > 0 AND jsonb_exists(fee_parts,'base')
  AND (fee_parts->>'base')::int = delivery_fee_cents AND NOT jsonb_exists(fee_parts,'door');
-- #15 0069：已完成/已送达但 delivered_at 仍为空
SELECT count(*) FROM orders WHERE status IN ('delivered','completed') AND delivered_at IS NULL;
-- #16 0069 漏网：实际送达过但状态是 cancelled，delivered_at 永久为空
SELECT count(*) FROM orders
WHERE status = 'cancelled' AND picked_up_at IS NOT NULL AND delivered_at IS NULL;
-- #17 0025：accepted_at 为空 → 反悔窗口永久打开 + 超时率恒算准时
SELECT count(*) FILTER (WHERE status = 'accepted') AS live_risk,
       count(*) FILTER (WHERE status IN ('ready','picked_up','delivered','completed')) AS stat_skew
FROM orders WHERE accepted_at IS NULL;

-- ============ 缺失唯一约束导致的实际重复 ============
-- #18 一个订单多条食安投诉（每条都能触发一次全额退款）
SELECT order_id, count(*) FROM food_safety_reports GROUP BY 1 HAVING count(*) > 1;
-- #19 同一商家同一 SN 的重复打印机（每单会打多张票）
SELECT merchant_id, sn, count(*) FROM merchant_printers GROUP BY 1,2 HAVING count(*) > 1;
-- #20 撞车的商家短码（/s/{code} 会解析到错误的店）
SELECT short_code, count(*) FROM merchants WHERE short_code <> '' GROUP BY 1 HAVING count(*) > 1;
-- #21 一个用户多个默认地址
SELECT user_id, count(*) FROM addresses WHERE is_default GROUP BY 1 HAVING count(*) > 1;
-- #22 同一用户对同一张券的重复购买（每人限购被绕过）
SELECT voucher_id, customer_id, count(*) FROM voucher_purchases
WHERE status IN ('pending_payment','paid','redeemed') GROUP BY 1,2 HAVING count(*) > 1;

-- ============ 时区 ============
-- #23 入住日期早于下单日（UTC 容器上 date.today() 放行的单）
SELECT id, order_no, checkin_date, created_at FROM stay_orders
WHERE checkin_date < (created_at AT TIME ZONE 'Asia/Shanghai')::date;
-- #24 房价日历被改到过去的日期
SELECT count(*) FROM room_calendar
WHERE date < (now() AT TIME ZONE 'Asia/Shanghai')::date - 1;

-- ============ 其它 ============
-- #25 代码不认识的订单状态（预期 0；非 0 则 /screen/latest 正在 500）
SELECT status, count(*) FROM orders WHERE status NOT IN
  ('pending_payment','paid','accepted','ready','picked_up','delivered','completed','cancelled')
GROUP BY 1;
-- #26 会被商家对账 CSV 误标成「外卖冲账」的申诉补回行
SELECT count(*), sum(net_cents) FROM merchant_earnings WHERE kind = 'adjustment';
-- #27 孤儿行（字符串关联，无外键保护）
SELECT 'order_flags' t, count(*) FROM order_flags f
  LEFT JOIN orders o ON o.order_no=f.order_no WHERE o.id IS NULL
UNION ALL SELECT 'rider_appeals', count(*) FROM rider_appeals a
  LEFT JOIN orders o ON o.order_no=a.order_no WHERE o.id IS NULL
UNION ALL SELECT 'coupons.used_order_no', count(*) FROM coupons c
  LEFT JOIN orders o ON o.order_no=c.used_order_no WHERE c.used_order_no<>'' AND o.id IS NULL
UNION ALL SELECT 'push_logs.user_id', count(*) FROM push_logs p
  LEFT JOIN users u ON u.id=p.user_id WHERE u.id IS NULL;
-- #28 分账挂起与已放弃（这两类审计告警不带订单号，测试的过滤器看不见）
SELECT status, count(*), sum(amount_cents) FROM profit_sharing_records
WHERE status IN ('pending','failed') GROUP BY 1;
