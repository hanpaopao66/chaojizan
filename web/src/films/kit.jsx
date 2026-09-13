import React, { useEffect, useLayoutEffect, useRef, useState } from 'react'

import './films.css'
import { Icon, reducedMotion, useReducedMotion } from '../SiteChrome.jsx'

/* 官网动画片的公共件(设计交接「官网动画集」第二批,2026-09)。
 *
 * 八支片子的原稿每支各带一份时钟、缓动、色板,逐字相同,这里收成一份。
 * 写法同首页 FlowFilm.jsx:纯 DOM + 行内样式 + 一个 rAF 时钟,不引动画库;
 * 滚出视口、切到别的标签页就停,回来接着走;系统开了「减少动态效果」只画静帧。
 *
 * 和原稿不一样的三处:
 * - 每支片子头上多一个暂停键(同 FlowFilm)。自动播放、超过 5 秒的动画
 *   要让人能停下来,不然想读字幕的人只能等它转回来;
 * - 缓动用动效规范的三条真曲线。原稿拿 easeOutBack 近似 spring,
 *   回弹的过冲比 App 里大一截,和 SzMicroKit 那格「spring」对不上;
 * - 画面整块是 role="img" + 一句完整的话。字幕几秒换一次,读屏软件读到的
 *   应该是整件事,不是某一帧碰巧停在屏上的那几个字。
 *
 * 第三批(2026-09-13,又加了五支)补了一条:片子在一个循环里高度不能变。手机上实测
 * 十几支里有一半会随字幕换段忽高忽低 25–40 像素,下面的页面跟着跳 —— 字幕改成整组
 * 叠在同一格里(Caption 的 titles / details),到点才出现的块一开始就占着位置。 */

// ---------- 色板(= site.css 的 .h3 令牌 + 账本深台面) ----------

export const P = {
  paper: '#F0EEE6', card: '#FBFAF6', alt: '#F5F3EC', line: '#E2DED2', edge: '#D8D4C8',
  ink: '#141413', ink2: '#6B6862', ink3: '#9A968C',
  clay: '#C15F3C', claySoft: '#EFDDD3', earn: '#4E6B4F', hold: '#A6763E',
  danger: '#D03030', link: '#2C5F87', bowl: '#943F2F', run: '#2B5F7A', voucher: '#88611C',
  ledger: '#1F1E1B', dcard: '#2A2925', dline: '#37342D',
  dtext: '#F2F0E8', dmute: '#A8A49A', dfaint: '#7A766D', dearn: '#8FB08D', dbad: '#E06B6B', dgold: '#D2A86C',
}

export const SANS = '-apple-system,"PingFang SC","Noto Sans CJK SC","Microsoft YaHei",sans-serif'
/** 数字和字幕:拉丁字母、数字走 SzSerif,汉字落到 SzSerifCJK(同 site.css 的 h1)。
 *  金额里夹的汉字(「不到 ¥17」「¥4 多」)也走这一条 —— 原稿写的是
 *  'SzSerif',Georgia,serif,汉字会掉到系统宋体。
 *  ⚠️ SzSerifCJK 是子集:用这个字体显示的汉字要放进 @serif-cjk 圈里 */
export const SERIF = "'SzSerif','SzSerifCJK','PingFang SC',serif"
export const MONO = 'ui-monospace,Menlo,Consolas,monospace'

// ---------- 缓动 ----------

/** CSS cubic-bezier 的 JS 版:给 x(时间进度)求 y。牛顿迭代,不收敛就二分 */
function bezier(x1, y1, x2, y2) {
  const cx = 3 * x1
  const bx = 3 * (x2 - x1) - cx
  const ax = 1 - cx - bx
  const cy = 3 * y1
  const by = 3 * (y2 - y1) - cy
  const ay = 1 - cy - by
  const sx = t => ((ax * t + bx) * t + cx) * t
  const sy = t => ((ay * t + by) * t + cy) * t
  const dx = t => (3 * ax * t + 2 * bx) * t + cx
  const solve = x => {
    let t = x
    for (let i = 0; i < 8; i++) {
      const e = sx(t) - x
      if (Math.abs(e) < 1e-5) return t
      const d = dx(t)
      if (Math.abs(d) < 1e-6) break
      t -= e / d
    }
    let lo = 0
    let hi = 1
    t = x
    for (let i = 0; i < 30; i++) {
      const v = sx(t)
      if (Math.abs(v - x) < 1e-5) break
      if (x > v) lo = t
      else hi = t
      t = (lo + hi) / 2
    }
    return t
  }
  return x => (x <= 0 ? 0 : x >= 1 ? 1 : sy(solve(x)))
}

/* 动效规范的三条曲线(同 site.css 的 --std / --spring / --exit、motion.dart 的 SzMotion),
 * 外加一条对称的 inOut 给「走一段路」用(配送费沿轨道走、核账逐格扫过去) */
export const Ease = {
  std: bezier(0.2, 0.8, 0.2, 1),
  spring: bezier(0.34, 1.3, 0.64, 1),
  exit: bezier(0.4, 0, 1, 1),
  inOut: t => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2),
}

export const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v))

/** 铺满父元素。不写 inset: 0 —— 那是 Safari 14.1 / Chrome 87 才认的简写,
 *  微信里的老内核不认,绝对定位的块会缩成 0 */
export const FILL = { position: 'absolute', top: 0, left: 0, right: 0, bottom: 0 }

/** 单段补间:start 之前是 from,end 之后是 to */
export function tween(T, { from = 0, to = 1, start, end, ease = Ease.std }) {
  if (T <= start) return from
  if (T >= end) return to
  return from + (to - from) * ease((T - start) / (end - start))
}

/** 入场:淡入 + 上移 12px */
export const enter = (T, start, dur = 0.32) => {
  const k = tween(T, { start, end: start + dur })
  return { opacity: k, transform: `translateY(${(1 - k) * 12}px)` }
}

/** 弹出:.86 → 1,spring */
export const pop = (T, start, dur = 0.32) => {
  const k = tween(T, { start, end: start + dur, ease: Ease.spring })
  return { opacity: clamp(k * 3, 0, 1), transform: `scale(${0.86 + 0.14 * k})` }
}

/** 元 → 「¥1,846.50」(千分位是给眼睛分组用的) */
export const yuan = v => `¥${v.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`

// ---------- 时钟 ----------

/** 片子的时钟。返回 { T, box, reduced, paused, togglePause }:
 *  T 是这一刻的秒数(0 ~ total 循环),box 挂在片子最外层。
 *
 *  - 还没滚进视口时停在 poster 那一帧;
 *  - 滚出视口、切标签页、按了暂停就停,回来从停下的那一帧接着走,不从 0 重播;
 *  - 系统开了「减少动态效果」就停在 still 那一帧,不跑时钟 */
export function useFilm(total, { still, poster = 0 }) {
  const reduced = useReducedMotion()
  const box = useRef(null)
  const [T, setT] = useState(() => (reducedMotion() ? still : poster))
  const [paused, setPaused] = useState(false)
  const [seen, setSeen] = useState(false)
  const [hidden, setHidden] = useState(() => typeof document !== 'undefined' && document.hidden)
  const running = !reduced && !paused && seen && !hidden

  useEffect(() => { if (reduced) setT(still) }, [reduced, still])

  useEffect(() => {
    const el = box.current
    if (!el || typeof IntersectionObserver !== 'function') { setSeen(true); return undefined }
    const io = new IntersectionObserver(([e]) => setSeen(e.isIntersecting), { threshold: 0.12 })
    io.observe(el)
    return () => io.disconnect()
  }, [])

  useEffect(() => {
    const on = () => setHidden(document.hidden)
    document.addEventListener('visibilitychange', on)
    return () => document.removeEventListener('visibilitychange', on)
  }, [])

  useEffect(() => {
    if (!running) return undefined
    let raf = 0
    let last = null
    const tick = now => {
      if (last != null) {
        // 一帧最多走 0.1 秒:主线程卡住一下回来,画面不会一口气跳过半段。
        // dt 必须在这里算好再交给 setT —— 写进 updater 里的话,React 晚一步才调它,
        // 那时 last 已经被下一行改成 now 了,dt 变成 0 甚至负数,片子停住或倒着走
        const dt = Math.min(0.1, (now - last) / 1000)
        setT(t => (t + dt) % total)
      }
      last = now
      raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [running, total])

  return { T, box, reduced, paused, togglePause: () => setPaused(p => !p) }
}

/** 片子自己的宽度(border-box)。片子嵌在页面的栏里,窄了换单列靠的是
 *  它自己有多宽,不是屏幕有多宽。layout effect:手机上第一帧就是窄版,不先闪宽版 */
export function useWidth(ref) {
  const [w, setW] = useState(0)
  useLayoutEffect(() => {
    const el = ref.current
    if (!el) return undefined
    const measure = () => setW(el.getBoundingClientRect().width)
    measure()
    if (typeof ResizeObserver !== 'function') {
      window.addEventListener('resize', measure)
      return () => window.removeEventListener('resize', measure)
    }
    const ro = new ResizeObserver(measure)
    ro.observe(el)
    return () => ro.disconnect()
  }, [ref])
  return w
}

// ---------- 零件 ----------

/** 金额 / 数字:SzSerif 半粗,等宽数字(滚动时不跳宽) */
export const Amount = ({ v, size = 15, color, weight = 600, style }) => (
  <span style={{ fontFamily: SERIF, fontWeight: weight, fontSize: size, color, fontVariantNumeric: 'tabular-nums', ...style }}>{v}</span>
)

/** 片子的外框:头上一行「示例 · …」+ 循环时长 + 暂停键,底下是画面。
 *
 *  summary 给了,画面就是 role="img",读屏读 summary;不给(微动效那种
 *  本身就是说明文字的),画面里的字照常读,动的那部分由各格自己标 aria-hidden */
export function Film({ film, label, loop, summary, dark = false, gap = 18, style, children }) {
  return (
    <div ref={film.box} className={`sz-film${dark ? ' dark' : ''}`} style={style}>
      <div className="sz-film-hd">
        <span className="lb">{label}</span>
        {!film.reduced && loop && <span className="lp">{loop}</span>}
        {!film.reduced && (
          <button type="button" className="pp" onClick={film.togglePause}
            aria-label={film.paused ? '播放动画' : '暂停动画'}>
            <Icon name={film.paused ? 'play' : 'pause'} size={12} />
          </button>
        )}
      </div>
      <div className="sz-film-bd" style={{ gap }}
        {...(summary ? { role: 'img', 'aria-label': summary } : {})}>
        {children}
      </div>
    </div>
  )
}

/** 几段字叠在同一个格子里,只显示第 index 段:格子的高度是最高那一段的高度 */
function Stack({ list, index, style }) {
  return (
    <div style={{ display: 'grid', ...style }}>
      {list.map((x, i) => (
        <div key={i} style={{ gridArea: '1 / 1', minWidth: 0, visibility: i === index ? 'visible' : 'hidden' }}>{x}</div>
      ))}
    </div>
  )
}

/** 字幕:一句衬线大字 + 一行说明,随段落切换。高度先占住,换字时下面不跳。
 *
 *  两种给法:title / detail 只给当前这一段(高度靠 minHeight 占);
 *  或者 titles / details 整组给、index 指当前段 —— 每一段都叠在同一个格子里,
 *  格子按最长那段撑开。窄屏上说明会折成三四行,只靠 minHeight 的话换段时片子会
 *  忽高忽低,下面的页面跟着跳 */
export function Caption({ title, detail, titles, details, index = 0, narrow, color, detailColor, minDetail = 44, children }) {
  const titleStyle = {
    fontFamily: SERIF, fontWeight: 600, fontSize: narrow ? 19 : 23, lineHeight: 1.35,
    minHeight: narrow ? 26 : 32, color,
  }
  const detailStyle = { fontSize: 13, color: detailColor, marginTop: 6, minHeight: minDetail, lineHeight: 1.7 }
  return (
    <div className="sz-film-cap">
      {titles ? <Stack list={titles} index={index} style={titleStyle} /> : <div style={titleStyle}>{title}</div>}
      {details ? <Stack list={details} index={index} style={detailStyle} />
        : detail != null && <div style={detailStyle}>{detail}</div>}
      {children}
    </div>
  )
}
