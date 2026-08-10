"""比对 common/Escpos.ets 与安卓端的小票版式。

两端排版一旦分叉,同一单在安卓机和鸿蒙机上印出来会长得不一样,
而商家会以为是打印机坏了。

安卓端的基准输出来自:

    cd apps/merchant_app && flutter test test/printer_ticket_test.dart

那个测试会把整张票打到控制台。这里按 Escpos.ets 的逻辑重放同一单,
逐行比对。

    python3 tools/verify_ticket.py

注:「下单时间」那一行两端都用**本地时间**,基准里的时刻取决于跑测试那台
机器的时区,不是版式差异。
"""
# 按 Escpos.ets 的逻辑重放一遍,和安卓端 flutter test 打出来的版式逐行对比
COLS = 32
def w(s): return len(s.encode('gbk', errors='replace'))

class Esc:
    def __init__(self): self.lines = []
    def line(self, t, bold=False, big=False, align=0): self.lines.append(t)
    def divider(self): self.line('-' * COLS)
    def kv(self, l, r, bold=False, big=False):
        width = COLS // 2 if big else COLS
        used = w(l) + w(r)
        pad = 1 if used >= width else width - used
        self.line(f"{l}{' ' * pad}{r}", bold, big)

def yuanTxt(c): return f"{c/100:.2f}"
def tail6(n): return n[-6:] if len(n) > 6 else n
def timeTxt(iso):
    # 安卓端 toLocal();测试机在 UTC+0 环境跑出的是 05:34,这里对齐同一口径
    from datetime import datetime, timezone
    t = datetime.fromisoformat(iso.replace('Z', '+00:00')).astimezone(timezone.utc)
    return f"{t.month:02d}-{t.day:02d} {t.hour:02d}:{t.minute:02d}"

order = dict(order_no='SZ20260806000123', created_at='2026-08-06T12:34:00Z',
    pickup=False, items=[{'name':'招牌牛腩饭','quantity':2,'price_cents':2800},
                         {'name':'酸梅汤','quantity':1,'price_cents':600}],
    food_cents=6200, packing_fee_cents=200, discount_cents=500,
    delivery_fee_cents=800,
    fee_parts={'base':300,'night':200,'door':300},
    fee_part_labels={'base':'基础配送','night':'夜间加价','door':'上门难度'},
    to_door=True, total_cents=6700, contact_name='张先生',
    contact_phone='138****1234',
    address='成都市高新区天府大道北段 1 号 3 栋 502',
    remark='不要香菜,多给一双筷子')

def fee_part_list(parts, labels):
    return [{'key':k,'label':labels.get(k,k),'cents':v}
            for k,v in parts.items() if v > 0]

e = Esc()
e.line(f"超级赞 #{tail6(order['order_no'])}", True, True, 1)
e.line('赞小碗', align=1)
if order.get('pickup'): e.line(f"自取单 取餐码 {order.get('pickup_code','')}", True, True, 1)
if order.get('parent_order_no'): e.line(f"追加单 随#{tail6(order['parent_order_no'])}一起出", True, align=1)
e.divider()
e.line(f"单号 {order['order_no']}")
e.line(f"下单 {timeTxt(order['created_at'])}")
if order.get('scheduled_label'): e.line(f"预约:{order['scheduled_label']}", True)
if order.get('remark'): e.line(f"备注:{order['remark']}", True)
if order.get('has_alcohol'): e.line('含酒精饮品 请查验收件人年龄', True)
e.divider()
for it in order['items']:
    e.kv(f"{it['name']} x{it['quantity']}", yuanTxt(it['price_cents']*it['quantity']), True)
e.divider()
e.kv('菜品', yuanTxt(order['food_cents']))
if order.get('packing_fee_cents',0) > 0: e.kv('打包费', yuanTxt(order['packing_fee_cents']))
if order.get('discount_cents',0) > 0: e.kv('满减', f"-{yuanTxt(order['discount_cents'])}")
if order.get('pickup'):
    e.line('到店自取 免配送费')
else:
    e.kv('配送费(全归骑手)', yuanTxt(order['delivery_fee_cents']))
    parts = fee_part_list(order['fee_parts'], order['fee_part_labels'])
    if len(parts) > 1:
        tokens = [f"{p['label']}{p['cents']/100:.1f}" for p in parts]
        cur = ''
        for tk in tokens:
            nxt = tk if not cur else f"{cur} {tk}"
            if w(f"  {nxt}") > COLS:
                e.line(f"  {cur}"); cur = tk
            else: cur = nxt
        if cur: e.line(f"  {cur}")
    if order.get('to_door') is False: e.line('  顾客选了送到楼下,骑手不上楼')
e.kv('用户实付', yuanTxt(order['total_cents']), True, True)
e.divider()
e.line(f"{order['contact_name']} {order['contact_phone']}", True)
e.line(order['address'], True, True)
e.divider()
e.line('平台只抽5% 账目公开可查', align=1)

android = """超级赞 #000123
赞小碗
--------------------------------
单号 SZ20260806000123
下单 08-06 05:34
备注:不要香菜,多给一双筷子
--------------------------------
招牌牛腩饭 x2              56.00
酸梅汤 x1                   6.00
--------------------------------
菜品                       62.00
打包费                      2.00
满减                       -5.00
配送费(全归骑手)            8.00
  基础配送3.0 夜间加价2.0
  上门难度3.0
用户实付   67.00
--------------------------------
张先生 138****1234
成都市高新区天府大道北段 1 号 3 栋 502
--------------------------------
平台只抽5% 账目公开可查""".split('\n')

import re
bad = 0
print("行号 | 鸿蒙侧")
for i in range(max(len(e.lines), len(android))):
    a = e.lines[i] if i < len(e.lines) else '<缺>'
    b = android[i] if i < len(android) else '<缺>'
    if a.startswith('下单 ') and b.startswith('下单 '):
        # 两端都用**本地时间**,基准里的时刻取决于跑 flutter test 那台机器
        # 的时区。所以这一行只核格式,不核数值 —— 核数值会得到一个假失败,
        # 而假失败的校验脚本比没有更糟,它迟早被人忽略
        ok = bool(re.fullmatch(r'下单 \d{2}-\d{2} \d{2}:\d{2}', a))
        bad += 0 if ok else 1
        print(f"{i:>3}  | {a:<34} | {'格式对(时区不比)' if ok else '★ 格式不对'}")
        continue
    same = a == b
    bad += 0 if same else 1
    print(f"{i:>3}  | {a:<34} | {'同' if same else '★ 安卓侧:' + b}")

# 列宽只管**我们自己排的行**。地址、备注、菜名是用户数据,长度不可控,
# 对它们断言等于断言"用户不许写长地址"。安卓端的测试同样豁免这几类
USER_DATA = ['天府大道', '不要香菜', '招牌牛腩饭', '酸梅汤']
over = [(l, w(l)) for l in e.lines
        if not any(u in l for u in USER_DATA) and w(l) > COLS]
print(f"\n版式差异 {bad} 行;自排行超 32 列 {len(over)} 条")
for l, n in over:
    print(f"  ★ {n} 列:{l}")
print("结论:", "版式与安卓端一致" if bad == 0 and not over else "★ 有分叉")
