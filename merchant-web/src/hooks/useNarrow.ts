import { useEffect, useState } from 'react'

/** 窄屏断点。992px 是 antd 的 `lg` —— 和它的栅格保持一致,不另立标准。 */
export const NARROW_QUERY = '(max-width: 991px)'

/**
 * 当前是不是窄屏。
 *
 * ## 为什么不用 antd Sider 的 onBreakpoint
 *
 * 那个回调只在 Sider 内部触发,顶栏拿不到。而窄屏要改的不只是侧栏 ——
 * 顶栏那一排(店名 / 业态标 / 铃铛 / 忙碌 / 营业开关 / 退出)在手机上
 * 一行根本排不下,得一起换排法。一个来源两处用,比两套断点靠谱。
 *
 * ## 为什么带 SSR 兜底
 *
 * 这个后台是纯 CSR,但 `matchMedia` 在测试环境(jsdom)里可能不存在 ——
 * 直接调会抛,把整个布局炸掉。取不到就当宽屏。
 */
export function useNarrow(): boolean {
  const [narrow, setNarrow] = useState(() => {
    if (typeof window === 'undefined' || !window.matchMedia) return false
    return window.matchMedia(NARROW_QUERY).matches
  })

  useEffect(() => {
    if (typeof window === 'undefined' || !window.matchMedia) return
    const mq = window.matchMedia(NARROW_QUERY)
    const onChange = (e: MediaQueryListEvent) => setNarrow(e.matches)
    // 转屏、拖窗口都要跟上;初值在 useState 里已经取过一次
    mq.addEventListener('change', onChange)
    return () => mq.removeEventListener('change', onChange)
  }, [])

  return narrow
}
