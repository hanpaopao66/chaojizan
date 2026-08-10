/**
 * 金额显示。
 *
 * **全程用「分」的整数,客户端不做浮点运算。** 服务端所有金额字段都是
 * `*_cents`,一旦在客户端转成 double 就会出现 0.1+0.2 那个经典问题 ——
 * 而这是一个把「每一单的账都可查」写在首页的平台,显示的数字和账单
 * 对不上是原则问题,不是显示瑕疵。
 */

/** 12345 → "¥123.45";整元省掉小数,"¥5" 比 "¥5.00" 好读 */
export function yuan(cents: number): string {
  const negative: boolean = cents < 0;
  const abs: number = Math.abs(Math.round(cents));
  const whole: number = Math.floor(abs / 100);
  const frac: number = abs % 100;
  const sign: string = negative ? '-' : '';
  if (frac === 0) {
    return `${sign}¥${whole}`;
  }
  const fracText: string = frac < 10 ? `0${frac}` : `${frac}`;
  return `${sign}¥${whole}.${fracText}`;
}

/** 不带货币符号的版本,用在"共 12.30 元"这类句子里 */
export function yuanPlain(cents: number): string {
  return yuan(cents).replace('¥', '');
}

/** 距离:1000 米以内给米,以上给公里一位小数 */
export function distanceText(meters: number): string {
  if (meters < 1000) {
    return `${Math.round(meters)}m`;
  }
  return `${(Math.round(meters / 100) / 10).toFixed(1)}km`;
}
