import React from 'react'

import Home from './Home.jsx'

// 大屏/透明中心单独成 chunk:echarts + 地图数据不拖累官网首页
const ScreenPage = React.lazy(() => import('./screen/ScreenPage.jsx'))
const TransparencyPage = React.lazy(
  () => import('./transparency/TransparencyPage.jsx'))

/* 子页面拆成独立 chunk。
 *
 * 原本是直接 import 的,虽然只有对应路由才渲染,但代码照样打进首屏主包。
 *
 * 首页的三个 3D 装饰件(背景火星 Embers、3D 地球 ChinaNodes、
 * 滚动驱动的金币动画 CoinFlow)已经**整个删掉** —— 它们一起把 three.js
 * 拖进首屏,gzip 282 KB,而人在微信里点开这个链接,要等这 282 KB
 * 下完才看得到第一行字。买到的只是背景上的火星和一个转动的地球。
 * 首页的流程动画(FlowFilm.jsx)是纯 DOM + 行内样式,不引任何动画库。
 */
const BrandPage = React.lazy(() => import('./BrandPage.jsx'))
const RatesPage = React.lazy(() => import('./RatesPage.jsx'))
const OpenSourcePage = React.lazy(() => import('./OpenSourcePage.jsx'))
const ChannelPage = React.lazy(() => import('./ChannelPage.jsx'))
const JoinMerchant = React.lazy(
  () => import('./JoinPages.jsx').then(m => ({ default: m.JoinMerchant })))
const JoinRider = React.lazy(
  () => import('./JoinPages.jsx').then(m => ({ default: m.JoinRider })))

export default function App() {
  // 极简路由:官网只有几条路径,不值得为此引一个路由库。
  // vite dev 下路径带 /site 前缀(base 配置),先剥掉,与生产行为一致。
  //
  // ⚠️ 深色 / 浅色的判断在 index.html 的内联脚本里还有一份(它决定首屏底色,
  // 必须在 JS 包之前跑,引不到这里):除了 /screen 都是浅色。
  // 再加深色页要两处一起改,漏了的话新页会先闪一下骨白底
  const raw = typeof location !== 'undefined' ? location.pathname : '/'
  const path = raw.replace(/^\/site/, '') || '/'
  const lazyPage = node => (
    <React.Suspense fallback={null}>{node}</React.Suspense>)
  if (path.startsWith('/join/merchant')) return lazyPage(<JoinMerchant />)
  if (path.startsWith('/join/rider')) return lazyPage(<JoinRider />)
  if (path.startsWith('/brand')) return lazyPage(<BrandPage />)
  if (path.startsWith('/rates')) return lazyPage(<RatesPage />)
  if (path.startsWith('/opensource')) return lazyPage(<OpenSourcePage />)
  if (path.startsWith('/channel')) {
    // /channel/stay → stay;认不出的 key 由 ChannelPage 回退到「点外卖」
    const key = decodeURIComponent(path.split('/')[2] || '')
    return lazyPage(<ChannelPage channelKey={key} />)
  }
  if (path.startsWith('/screen')) return lazyPage(<ScreenPage />)
  if (path.startsWith('/transparency') || path.startsWith('/status')) {
    return lazyPage(<TransparencyPage />)
  }
  return <Home />
}
