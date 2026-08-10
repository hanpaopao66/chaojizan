import { util } from '@kit.ArkTS';

/**
 * GBK 编码器。
 *
 * ## 为什么需要它
 *
 * 热敏小票机的字库不认 UTF-8 —— 这是行业约定,不是我们的选择。
 * 市面上几十块的 58mm 蓝牙小票机,你给它发 UTF-8 的中文,印出来是乱码。
 *
 * ## 为什么要自己写
 *
 * 鸿蒙的 `util.TextEncoder` **只能编 UTF-8 和 UTF-16**,给不了 GBK。
 * 但 `util.TextDecoder` **能解 GBK**。
 *
 * 于是有这条路子:开机时把 GBK 所有合法双字节码位摆成一个大 buffer,
 * 用 TextDecoder 一次性解成字符串,再反查回去 ——
 * 就得到一张 `Unicode → GBK 双字节` 的表。
 *
 * 一次解码、一趟遍历,建表 21791 条,几毫秒的事,而且只做一次。
 * 比往仓库里塞一张几十 KB 的静态码表干净得多。
 *
 * ## ⚠️ 必须插分隔符,不能靠位置一一对应
 *
 * 第一版是把码位连着摆、按下标对应解出来的字符。**错的。**
 * 非法码位在 `fatal: false` 下会解成「替换字符 + 尾字节」**两个**字符
 * (比如 0x81 0x40 出 `�@`),从那里开始整条对应关系全体错位。
 * 实测 23940 个码位解出 24728 个字符,而后面每个字的编码都是错的 ——
 * 这种错不会抛异常,只会让小票整张印成乱码。
 *
 * 修法:每个码位后面跟一个 `\n`。0x0A 不在 GBK 次字节范围(0x40–0xFE)内,
 * **永远不会被当成双字节的一部分吞掉**,所以它一定活得下来。
 * 按 `\n` 切开,每段恰好对应一个码位;段长不为 1 的就是非法码位,跳过。
 *
 * 这套算法拿 Python 的 cp936 全量对拍过:21887 个可编码 BMP 字符
 * (含 96 个 ASCII 走单字节分支),逐字节一致,零差异。
 *
 * ## 边界
 *
 * - 单字节区(0x00–0x7F)就是 ASCII,直接过;
 * - 双字节区首字节 0x81–0xFE,次字节 0x40–0xFE 且不等于 0x7F;
 * - 表里查不到的字符(生僻字、emoji、繁体某些字)按 `?` 出。
 *   **不能抛异常** —— 顾客备注里打个 emoji 就打不出小票,
 *   那是把一单饭砸在打印机上。
 */
export class Gbk {
  /** Unicode 码点 → GBK 双字节(高位 << 8 | 低位)。懒加载,只建一次 */
  private static table: Map<number, number> | null = null;

  /** 查不到的字符用它顶替。半角问号,任何字库都有 */
  private static readonly FALLBACK: number = 0x3F;

  /** 码位分隔符。选 0x0A 的理由见类注释 —— 它不可能被当成次字节吞掉 */
  private static readonly SEP: number = 0x0A;

  /** 建表。整片摆进一个 buffer 一次解完,每个码位后跟一个分隔符 */
  private static build(): Map<number, number> {
    const codes: number[] = [];
    const bytes: number[] = [];
    for (let hi: number = 0x81; hi <= 0xFE; hi++) {
      for (let lo: number = 0x40; lo <= 0xFE; lo++) {
        if (lo === 0x7F) {
          continue; // 0x7F 不在 GBK 次字节范围内
        }
        codes.push((hi << 8) | lo);
        bytes.push(hi);
        bytes.push(lo);
        bytes.push(Gbk.SEP);
      }
    }

    const buf: Uint8Array = new Uint8Array(bytes.length);
    for (let i: number = 0; i < bytes.length; i++) {
      buf[i] = bytes[i];
    }

    const decoder: util.TextDecoder = util.TextDecoder.create('gbk', {
      fatal: false,
      ignoreBOM: true,
    });
    const segments: string[] = decoder.decodeToString(buf).split('\n');

    const map: Map<number, number> = new Map<number, number>();
    const n: number = Math.min(segments.length, codes.length);
    for (let i: number = 0; i < n; i++) {
      const seg: string = segments[i];
      if (seg.length !== 1) {
        continue; // 非法码位:解成了「替换字符 + 尾字节」两个字符
      }
      const ch: number = seg.charCodeAt(0);
      if (ch === 0xFFFD) {
        continue;
      }
      // 同一个字符可能对应多个码位(GBK 里确实有重复映射),
      // **保留第一个** —— 靠前的是常用区,打印机字库更可能有
      if (!map.has(ch)) {
        map.set(ch, codes[i]);
      }
    }
    return map;
  }

  private static ensure(): Map<number, number> {
    if (Gbk.table === null) {
      Gbk.table = Gbk.build();
    }
    return Gbk.table;
  }

  /**
   * 把一段文本编成 GBK 字节。
   *
   * 结果直接喂给 `sppWrite`。ASCII 一字节,汉字两字节 ——
   * 小票排版的列宽计算依赖这个规则(见 Escpos.ets 的 kv 对齐)。
   */
  static encode(text: string): number[] {
    const table: Map<number, number> = Gbk.ensure();
    const out: number[] = [];
    for (let i: number = 0; i < text.length; i++) {
      const ch: number = text.charCodeAt(i);
      if (ch < 0x80) {
        out.push(ch);
        continue;
      }
      const code: number | undefined = table.get(ch);
      if (code === undefined) {
        // 生僻字/emoji:出个问号,别让整张小票打不出来。
        // 代理对(emoji 占两个 UTF-16 单元)会出两个问号,认了
        out.push(Gbk.FALLBACK);
        continue;
      }
      out.push((code >> 8) & 0xFF);
      out.push(code & 0xFF);
    }
    return out;
  }

  /**
   * 这段文本占几列。
   *
   * 58mm 纸只有 32 列,汉字占 2 列 —— 排版全靠这个数。
   * 直接用 `encode().length` 而不是 `text.length`:
   * 后者把汉字算成 1 列,排出来会短一半。
   */
  static width(text: string): number {
    return Gbk.encode(text).length;
  }
}
