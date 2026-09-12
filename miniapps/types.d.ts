// 测试文件用到 node:test / node:assert;不装 @types/node,只声明用到的这一点
declare module 'node:test' {
  export function test(name: string, fn: () => void | Promise<void>): void
}
declare module 'node:assert/strict' {
  const assert: {
    (v: unknown, msg?: string): asserts v
    ok(v: unknown, msg?: string): asserts v
    equal(a: unknown, b: unknown, msg?: string): void
    notEqual(a: unknown, b: unknown, msg?: string): void
    deepEqual(a: unknown, b: unknown, msg?: string): void
    match(s: string, re: RegExp, msg?: string): void
    rejects(p: Promise<unknown> | (() => Promise<unknown>), e?: unknown, msg?: string): Promise<void>
    throws(fn: () => unknown, e?: unknown, msg?: string): void
  }
  export default assert
}
declare module '*.css'
