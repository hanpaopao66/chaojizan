import { Gbk } from './Gbk';
import { FeePart, MerchantOrder, OrderItem } from '../model/Models';

/**
 * ESC/POS 小票排版。
 *
 * **这一层从安卓端 `printer_service.dart` 逐行搬过来,刻意不做改进。**
 * 它是纯字节拼装,没有任何平台依赖;两端排版一旦分叉,同一单在安卓机和
 * 鸿蒙机上印出来会长得不一样,而商家会以为是打印机坏了。
 *
 * 58mm 纸宽 = 32 个 ASCII 列,汉字占 2 列。列宽一律用 [Gbk.width] 算,
 * 不能用 `text.length` —— 后者把汉字算成 1 列,排出来短一半。
 */
const COLS: number = 32;

/** 一张小票的字节流构造器 */
export class EscBuilder {
  private out: number[] = [0x1B, 0x40]; // 初始化

  private align(n: number): void {
    this.out.push(0x1B, 0x61, n);
  }

  private bold(on: boolean): void {
    this.out.push(0x1B, 0x45, on ? 1 : 0);
  }

  private size(big: boolean): void {
    this.out.push(0x1D, 0x21, big ? 0x11 : 0x00);
  }

  /** 一行。align: 0 左 / 1 中 / 2 右 */
  line(text: string, bold: boolean = false, big: boolean = false,
       align: number = 0): void {
    this.align(align);
    this.bold(bold);
    this.size(big);
    const bytes: number[] = Gbk.encode(text);
    for (let i: number = 0; i < bytes.length; i++) {
      this.out.push(bytes[i]);
    }
    this.out.push(0x0A);
    if (big) {
      this.size(false);
    }
    if (bold) {
      this.bold(false);
    }
  }

  divider(): void {
    this.line('-'.repeat(COLS));
  }

  /** 左右两端对齐(按 GBK 字节宽度补空格;放大字体时每列占双宽) */
  kv(left: string, right: string, bold: boolean = false,
     big: boolean = false): void {
    const width: number = big ? Math.floor(COLS / 2) : COLS;
    const used: number = Gbk.width(left) + Gbk.width(right);
    const pad: number = used >= width ? 1 : width - used;
    this.line(`${left}${' '.repeat(pad)}${right}`, bold, big);
  }

  done(): number[] {
    this.out.push(0x1B, 0x64, 3); // 走纸 3 行
    this.out.push(0x1D, 0x56, 0x42, 0x00); // 半切(不支持切刀的机器忽略)
    return this.out;
  }
}

/**
 * 小票上的金额:`48.00`,两位小数、不带货币符号。
 *
 * **不能复用 Money.ets 的 `yuan()`** —— 那个给界面用,整元省小数、带 ¥,
 * 而小票要的是能对齐成一列的定宽数字,且 `¥` 在部分打印机字库里缺字
 */
function yuanTxt(cents: number): string {
  return (cents / 100).toFixed(2);
}

function timeTxt(iso: string): string {
  const t: Date = new Date(iso);
  if (isNaN(t.getTime())) {
    return '';
  }
  const two = (n: number): string => n < 10 ? `0${n}` : `${n}`;
  return `${two(t.getMonth() + 1)}-${two(t.getDate())} ` +
      `${two(t.getHours())}:${two(t.getMinutes())}`;
}

function tail6(no: string): string {
  return no.length > 6 ? no.substring(no.length - 6) : no;
}

/**
 * 订单小票的字节流。
 *
 * **给测试用的也是这个函数** —— 没有真机也要能核版式。58mm 只有 32 列,
 * 一行排不下就会折行,而折行的地址在店里读起来是灾难。
 * 让版式能被断言,比印出来才发现串行强。
 */
export function orderTicket(order: MerchantOrder, shopName: string): number[] {
  const e: EscBuilder = new EscBuilder();
  e.line(`超级赞 #${tail6(order.order_no)}`, true, true, 1);
  e.line(shopName, false, false, 1);
  if (order.pickup === true) {
    e.line(`自取单 取餐码 ${order.pickup_code ?? ''}`, true, true, 1);
  }
  const parent: string = order.parent_order_no ?? '';
  if (parent.length > 0) {
    e.line(`追加单 随#${tail6(parent)}一起出`, true, false, 1);
  }
  e.divider();
  e.line(`单号 ${order.order_no}`);
  e.line(`下单 ${timeTxt(order.created_at)}`);
  const scheduled: string = order.scheduled_label ?? '';
  if (scheduled.length > 0) {
    e.line(`预约:${scheduled}`, true);
  }
  const remark: string = order.remark ?? '';
  if (remark.length > 0) {
    e.line(`备注:${remark}`, true);
  }
  if (order.has_alcohol === true) {
    e.line('含酒精饮品 请查验收件人年龄', true);
  }
  e.divider();

  const items: OrderItem[] = order.items ?? [];
  for (let i: number = 0; i < items.length; i++) {
    const it: OrderItem = items[i];
    e.kv(`${it.name} x${it.quantity}`,
        yuanTxt(it.price_cents * it.quantity), true);
  }
  e.divider();

  e.kv('菜品', yuanTxt(order.food_cents ?? 0));
  if ((order.packing_fee_cents ?? 0) > 0) {
    e.kv('打包费', yuanTxt(order.packing_fee_cents ?? 0));
  }
  if ((order.discount_cents ?? 0) > 0) {
    e.kv('满减', `-${yuanTxt(order.discount_cents ?? 0)}`);
  }

  if (order.pickup === true) {
    e.line('到店自取 免配送费');
  } else {
    e.kv('配送费(全归骑手)', yuanTxt(order.delivery_fee_cents ?? 0));
    // 配送费构成印在票上:顾客当面问"怎么这么贵"时,商家能直接指给他看。
    // 这笔钱商家一分不拿,却总要替我们解释 —— 印出来比让他背话术实在
    writeFeeParts(e, order);
    // to_door 服务端有默认值,不会缺;这里与安卓端口径一致
    if (order.to_door === false) {
      e.line('  顾客选了送到楼下,骑手不上楼');
    }
  }
  e.kv('用户实付', yuanTxt(order.total_cents), true, true);
  e.divider();

  if (order.pickup === true) {
    e.line(`顾客到店自取,核对取餐码 ${order.pickup_code ?? ''}`, true);
    const phone: string = order.contact_phone ?? '';
    if (phone.length > 0) {
      e.line(`${order.contact_name ?? ''} ${phone}`);
    }
  } else {
    e.line(`${order.contact_name ?? ''} ${order.contact_phone ?? ''}`, true);
    e.line(order.address ?? '', true, true);
  }
  e.divider();
  e.line('平台只抽5% 账目公开可查', false, false, 1);
  return e.done();
}

/**
 * 配送费构成,缩进两格单独成行。
 *
 * **按纸宽分行**:三项拆分连起来是 37 列,58mm 只有 32,直接印会折行,
 * 折出来的半截词在店里读着莫名其妙。宁可多占一行。
 */
function writeFeeParts(e: EscBuilder, order: MerchantOrder): void {
  const parts: FeePart[] = (order.fee_parts ?? []).filter(
      (p: FeePart) => p.cents > 0);
  if (parts.length <= 1) {
    return;
  }
  const labels: Record<string, string> = order.fee_part_labels ?? {};
  const tokens: string[] = parts.map((p: FeePart) => {
    const name: string = labels[p.key] ?? p.key;
    return `${name}${(p.cents / 100).toFixed(1)}`;
  });
  let cur: string = '';
  for (let i: number = 0; i < tokens.length; i++) {
    const next: string = cur.length === 0 ? tokens[i] : `${cur} ${tokens[i]}`;
    if (Gbk.width(`  ${next}`) > COLS) {
      e.line(`  ${cur}`);
      cur = tokens[i];
    } else {
      cur = next;
    }
  }
  if (cur.length > 0) {
    e.line(`  ${cur}`);
  }
}

/** 测试页:商家连好打印机后先打一张,确认通路 */
export function testTicket(shopName: string): number[] {
  const e: EscBuilder = new EscBuilder();
  e.line('超级赞 测试页', true, true, 1);
  e.line(shopName, false, false, 1);
  e.divider();
  e.line('看到这张小票,说明蓝牙打印一切正常。');
  e.line('新订单到达时会自动出票。');
  e.divider();
  e.line('平台只抽5% 账目公开可查', false, false, 1);
  return e.done();
}
