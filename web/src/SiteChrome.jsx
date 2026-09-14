import React, { useEffect, useRef, useState } from 'react'

import { BrandIcon } from './BrandSvg.jsx'

/* 官网浅色版的公共件:顶栏、页脚、取数、金额/北京时间格式化、频道注册表、
 * 分账条、数字滚动、线框图标。除 /screen 以外的每一页都从这里拿。
 *
 * 类名规矩同 Home.jsx 顶部注释:要么带 h3- / sz- 前缀,要么是 styles.css
 * 里没有的词。样式在 site.css。 */

// ---------- 取数 ----------

/* 同一个接口在一页里常被两处要(首页的账目台面和页脚都要 /stats/overview),
 * 30 秒内的重复请求共用一个 promise,不重复打 */
const inflight = new Map()
function load(url, fresh) {
  const hit = inflight.get(url)
  if (!fresh && hit && Date.now() - hit.at < 30000) return hit.p
  const p = fetch(url).then(r => (r.ok ? r.json() : null)).catch(() => null)
  inflight.set(url, { at: Date.now(), p })
  return p
}

/** 取一个公开接口。拿不到(网络错、非 2xx)就一直是 null —— 页面据此显示「–」,
 *  和「真的是 0」分开。every 毫秒轮询一次 */
export function useJson(url, every) {
  const [data, setData] = useState(null)
  useEffect(() => {
    if (!url) return undefined
    let alive = true
    const run = fresh => load(url, fresh).then(d => { if (alive && d != null) setData(d) })
    run(false)
    const t = every ? setInterval(() => run(true), every) : null
    return () => { alive = false; if (t) clearInterval(t) }
  }, [url, every])
  return data
}

/** 复制一段文字,成功回 true。先用 Clipboard API;拿不到(老的微信内核、非安全上下文、
 *  页面没焦点)就退回隐藏 textarea + execCommand */
export function copyText(text) {
  const legacy = () => {
    const ta = document.createElement('textarea')
    ta.value = text
    ta.setAttribute('readonly', '')
    ta.style.cssText = 'position:fixed;top:0;left:0;opacity:0'
    document.body.appendChild(ta)
    ta.select()
    let ok = false
    try { ok = document.execCommand('copy') } catch { ok = false }
    ta.remove()
    return ok
  }
  if (!navigator.clipboard?.writeText) return Promise.resolve(legacy())
  return navigator.clipboard.writeText(text).then(() => true, () => legacy())
}

// ---------- 频道注册表 ----------

/* 与 packages/shared/lib/src/channels.dart 对齐。颜色是设计定稿的频道色
 * (字块画在自身 12% 淡底上)。**开没开不写在这里**,读 /channels ——
 * 和 App 首页金刚区是同一份后台配置。 */
export const CHANNELS = [
  { key: 'food', glyph: '碗', name: '点外卖', color: '#943F2F', tint: 'rgba(148,63,47,.12)' },
  { key: 'retail', glyph: '果', name: '买菜买水果', color: '#01756C', tint: 'rgba(1,117,108,.12)' },
  { key: 'stay', glyph: '宿', name: '住宿', color: '#4E7054', tint: 'rgba(78,112,84,.12)' },
  { key: 'voucher', glyph: '券', name: '超值团购', color: '#88611C', tint: 'rgba(136,97,28,.12)' },
  // 服务台格子只有六七个字宽,「帮我送 / 帮我买」会折成两行;表格里放得下全称
  { key: 'errand', glyph: '跑', name: '帮我送', fullName: '帮我送 / 帮我买', color: '#2B5F7A', tint: 'rgba(43,95,122,.12)' },
  { key: 'ride', glyph: '车', name: '打车', coming: true, color: '#9A968C', tint: '#F5F3EC' },
]
export const channelOf = key => CHANNELS.find(c => c.key === key)

/* /channels 拿不到时按这个画,和服务端 services/flags.py 的 CHANNELS_FALLBACK 一致。
 * 取保守值的道理同 App:「读不到就显示全部」会让已经关掉的频道在官网上复活。 */
const CHANNELS_FALLBACK = ['food', 'voucher']

/* 频道三种状态。「暂未开放」和「筹备中」要分开说:
 * 前者代码和费率都在、只是后台没开;后者还没做。 */
export const STATE_LABEL = { closed: '暂未开放', coming: '筹备中' }

/** 频道开没开:{ loaded, stateOf(key) → 'open' | 'closed' | 'coming' } */
export function useChannelState() {
  const resp = useJson('/channels')
  const enabled = Array.isArray(resp?.enabled) ? resp.enabled : CHANNELS_FALLBACK
  const stateOf = key => {
    const ch = channelOf(key)
    if (ch?.coming) return 'coming'
    return enabled.includes(key) ? 'open' : 'closed'
  }
  return { loaded: !!resp, enabled, stateOf }
}

/* App 的功能开关:读 /config 的 features —— 和 App 收起入口用的是同一份后台开关
 * (services/flags.py)。拿不到时按生产缺省:消息开;视频、投稿、通话、机器人关。
 * 道理同 CHANNELS_FALLBACK:读不到就当开着,关着的功能会在官网上复活。
 * 视频要等《信息网络传播视听节目许可证》,生产上缺省关着(docs/LAUNCH-40.md §1) */
const FEATURES_FALLBACK = { chat: true, video: false, video_upload: false, calls: false, bots: false }

/** 功能开没开:{ loaded, chat, video, video_upload, calls, bots } */
export function useFeatures() {
  const resp = useJson('/config')
  const f = resp && typeof resp.features === 'object' && resp.features ? resp.features : null
  return { loaded: !!f, ...FEATURES_FALLBACK, ...(f || {}) }
}

/** 频道字块:一个汉字画在自身 12% 淡底上(同 SzChannelGrid.glyph) */
export function Glyph({ ch, off, size = 40, radius, fontSize }) {
  const style = {
    width: size, height: size, fontSize: fontSize ?? Math.round(size * 0.48),
    borderRadius: radius ?? (size >= 44 ? 10 : 8),
    color: off ? '#9A968C' : ch.color, background: off ? '#F5F3EC' : ch.tint,
  }
  return <span className="glyph" style={style} aria-hidden="true">{ch.glyph}</span>
}

// ---------- 标题断行 ----------

/** 中文标题按短语断行:在「，、：；」后面切开,每段是一个 inline-block,
 *  窄屏上只会在短语之间换行,不会把「去了哪」拆成「去 / 了哪」。
 *  (不用正则后行断言切:iOS 16.4 以前不认,整个包会解析失败) */
export function kw(text) {
  const out = []
  let cur = ''
  for (const c of String(text)) {
    cur += c
    if ('，、：；'.includes(c)) { out.push(cur); cur = '' }
  }
  if (cur) out.push(cur)
  return out.map((p, i) => <span key={i} className="kw">{p}</span>)
}

// ---------- 金额与时间 ----------

/** 分 → 「¥1,846.00」。负数写成「−¥3.00」(平台倒贴的那一份) */
export function money(cents, digits = 2) {
  if (cents == null || Number.isNaN(cents)) return '–'
  const v = Math.abs(cents) / 100
  const s = v.toLocaleString('zh-CN', { minimumFractionDigits: digits, maximumFractionDigits: digits })
  return `${cents < 0 ? '−' : ''}¥${s}`
}

const BJ = 8 * 3600e3
/** ISO 时间 → 北京时间的各段(服务端存 UTC,公示按北京时间说) */
export function bjParts(iso) {
  const ms = typeof iso === 'number' ? iso : Date.parse(iso)
  if (Number.isNaN(ms)) return null
  const d = new Date(ms + BJ)
  const p2 = n => String(n).padStart(2, '0')
  return {
    day: `${d.getUTCFullYear()}-${p2(d.getUTCMonth() + 1)}-${p2(d.getUTCDate())}`,
    md: `${d.getUTCMonth() + 1} 月 ${d.getUTCDate()} 日`,
    hm: `${p2(d.getUTCHours())}:${p2(d.getUTCMinutes())}`,
  }
}
/** 北京时间的「今天」往前 back 天,YYYY-MM-DD */
export const bjDay = (back = 0) => bjParts(Date.now() - back * 86400e3).day
/** 「2026-09-11」→「9 月 11 日」 */
export const mdOf = day => {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(day || '')
  return m ? `${Number(m[2])} 月 ${Number(m[3])} 日` : day
}

// ---------- 动效 ----------

/* 动效规范:四个时长 120/220/320/900ms,三条曲线。账本数字和分账条是唯一
 * 允许的慢动作(900ms standard,分账条段间 120ms)。系统开了「减少动态效果」
 * 就一律不动,直接给终值 */
export const reducedMotion = () => typeof window !== 'undefined'
  && !!window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
const easeOutCubic = t => 1 - Math.pow(1 - t, 3)

/** 同 reducedMotion(),但系统开关在页面开着的时候被拨了,会跟着变 */
export function useReducedMotion() {
  const [r, setR] = useState(reducedMotion)
  useEffect(() => {
    const mq = window.matchMedia?.('(prefers-reduced-motion: reduce)')
    if (!mq) return undefined
    const on = () => setR(mq.matches)
    if (mq.addEventListener) mq.addEventListener('change', on)
    else mq.addListener(on)
    return () => {
      if (mq.removeEventListener) mq.removeEventListener('change', on)
      else mq.removeListener(on)
    }
  }, [])
  return r
}

/** 数字从上一次的值滚到新值(第一次从 0 起),900ms。轮询刷新时从旧值滚过去,
 *  不从 0 重播 */
export function useCountUp(target, dur = 900) {
  const [v, setV] = useState(target)
  const last = useRef(null)
  useEffect(() => {
    if (target == null) { setV(target); return undefined }
    const from = last.current ?? 0
    last.current = target
    if (reducedMotion() || from === target) { setV(target); return undefined }
    let raf = 0
    let t0 = null
    const tick = now => {
      if (t0 == null) t0 = now
      const k = Math.min(1, (now - t0) / dur)
      setV(from + (target - from) * easeOutCubic(k))
      if (k < 1) raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [target, dur])
  return v
}

/** 分账条:段宽 = 金额(flex-grow),挂载后从 0 长到占比,段间错开 120ms。
 *  比例失真的图比没有图更糟,所以段宽直接用金额,不做「最小可见宽度」 */
export function SplitBar({ segments, height = 10, gap = 3, className = '', label }) {
  const total = segments.reduce((s, x) => s + Math.max(0, x.value || 0), 0)
  const hasData = total > 0
  const [grown, setGrown] = useState(false)
  // 数据到了才长:透明中心的条是先画空轨、接口回来才有数,挂载时就长的话那一下是空的
  useEffect(() => {
    if (!hasData) return undefined
    if (reducedMotion()) { setGrown(true); return undefined }
    // 两帧:先把 0 宽画出来,再给终值,过渡才有起点
    let r2 = 0
    const r1 = requestAnimationFrame(() => { r2 = requestAnimationFrame(() => setGrown(true)) })
    return () => { cancelAnimationFrame(r1); cancelAnimationFrame(r2) }
  }, [hasData])
  return (
    <div className={`sz-split ${hasData ? '' : 'empty'} ${className}`} style={{ height, gap }}
      role="img" aria-label={label}>
      {hasData && segments.map((s, i) => (
        <span key={s.key ?? i} style={{
          flexGrow: grown ? Math.max(0, s.value || 0) : 0,
          background: s.color, opacity: s.opacity ?? 1,
          transitionDelay: `${i * 120}ms`,
        }} />
      ))}
    </div>
  )
}

// ---------- 线框图标(不用 Material Symbols:谷歌字体在国内打不开) ----------

const ICONS = {
  hand: <><path d="M18 11V6a2 2 0 0 0-4 0" /><path d="M14 10V4a2 2 0 0 0-4 0v2" /><path d="M10 10.5V6a2 2 0 0 0-4 0v8" /><path d="M18 8a2 2 0 1 1 4 0v6a8 8 0 0 1-8 8h-2c-2.8 0-4.5-.9-6-2.3l-3.6-3.6a2 2 0 0 1 2.8-2.8L7 15" /></>,
  clock: <><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" /></>,
  receipt: <><path d="M5 3h14v18l-2.3-1.5L14.3 21 12 19.5 9.7 21l-2.4-1.5L5 21z" /><path d="M9 8h6M9 12h6M9 16h3" /></>,
  arrow: <path d="M7 17 17 7M9 7h8v8" />,
  rules: <><path d="M9 6h11M9 12h11M9 18h11" /><circle cx="4.5" cy="6" r="1" /><circle cx="4.5" cy="12" r="1" /><circle cx="4.5" cy="18" r="1" /></>,
  calc: <><rect x="5" y="3" width="14" height="18" rx="2" /><path d="M8.5 7h7M8.5 12h.01M12 12h.01M15.5 12h.01M8.5 16h.01M12 16h.01M15.5 16h.01" /></>,
  shield: <><path d="M12 3 19 6v5c0 4.5-3 8.2-7 10-4-1.8-7-5.5-7-10V6z" /><path d="m9 12 2 2 4-4" /></>,
  phone: <><rect x="6.5" y="2.5" width="11" height="19" rx="2" /><path d="M11 18h2" /></>,
  doc: <><path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z" /><path d="M14 3v5h5M9 13h6M9 17h6" /></>,
  repo: <><path d="M5 4.5A1.5 1.5 0 0 1 6.5 3H19v15H6.5A1.5 1.5 0 0 0 5 19.5z" /><path d="M5 19.5A1.5 1.5 0 0 0 6.5 21H19v-3" /></>,
  play: <path d="M8 5.5v13l10.5-6.5z" fill="currentColor" stroke="none" />,
  pause: <path d="M7 5h3.5v14H7zM13.5 5H17v14h-3.5z" fill="currentColor" stroke="none" />,
}
export function Icon({ name, size = 22, color, className = '' }) {
  return (
    <svg className={`sz-icon ${className}`} width={size} height={size} viewBox="0 0 24 24"
      fill="none" stroke={color || 'currentColor'} strokeWidth="1.7"
      strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      {ICONS[name]}
    </svg>
  )
}

// ---------- 顶栏 ----------

/* 顶栏七个链接。首页上「服务 / 费率 / 账本」是页内锚点(1g 稿),
 * 其余页面上它们指向各自的独立页。「消息与视频」是用户端底部新加的两个 tab 的介绍页 */
const NAV = [
  { key: 'services', label: '服务', href: '/channel/food', jump: '#services' },
  { key: 'features', label: '消息与视频', href: '/features' },
  { key: 'rates', label: '费率', href: '/rates', jump: '#rates' },
  { key: 'ledger', label: '账本', href: '/transparency', jump: '#ledger' },
  { key: 'merchant', label: '商家入驻', href: '/join/merchant' },
  { key: 'rider', label: '骑手加入', href: '/join/rider' },
  { key: 'opensource', label: '开源仓', href: '/opensource' },
]

/** 吸顶顶栏。窄屏时链接那一行横向滚动 —— **不是隐藏**:
 *  老官网在手机上把链接整行藏了,入驻页在手机上一个入口都没有(见 home.css) */
export function SiteNav({ active, home = false }) {
  return (
    <nav className="h3-nav" aria-label="主导航">
      <a className="h3-brand" href="/"><BrandIcon size={28} /> 超级赞</a>
      <div className="links">
        {NAV.map(n => {
          const jump = home ? n.jump : null
          const on = active === n.key
          return (
            <a key={n.key} href={jump || n.href}
              className={[jump ? 'h3-jump' : '', on ? 'on' : ''].join(' ').trim() || undefined}
              aria-current={on ? 'page' : undefined}>{n.label}</a>
          )
        })}
      </div>
      {home && <a className="h3-btn ghost" href="/transparency">透明中心</a>}
      <a className="h3-btn primary" href={home ? '#download' : '/download'}>下载 App</a>
    </nav>
  )
}

// ---------- 页脚 ----------

/* 应用商店整改反馈要求的运营主体信息(公司 / 电话 / 邮箱)在这里,
 * 每一页都有;备案号链到工信部。note 是第二行开头的一句(首页写「本页数据与
 * 公开账本同源」,没有实时数据的页面不写这句) */
export function SiteFooter({ note }) {
  const stats = useJson('/stats/overview')
  const ver = stats?.version?.version
  // 视听许可证编号:后台「平台开关」里填,空着不显示(开视频要公示,见 docs/LAUNCH-40.md)
  const av = useJson('/config')?.licenses?.av
  return (
    <footer className="h3-foot">
      <div>超级赞 Super-Z · 群众帮群众 · 让利于民，取之有道，账目为证</div>
      <div className="muted">
        {note}{note && ver && ' · '}
        {ver && <>线上版本 {ver}（与 <a href="https://github.com/hanpaopao66/chaojizan" target="_blank" rel="noreferrer">开源仓</a> tag 对应）</>}
      </div>
      <div className="muted">运营主体：陕西爱卡斯科技有限公司 · <a href="tel:15231109698">15231109698</a> · <a href="mailto:support@chaojizan.cc">support@chaojizan.cc</a></div>
      <div className="muted"><a href="https://beian.miit.gov.cn" target="_blank" rel="noreferrer">陕ICP备2025064101号-5</a>{av && <> · 信息网络传播视听节目许可证 {av}</>} · <a href="/legal/terms">用户协议</a> · <a href="/legal/privacy">隐私政策</a> · <a href="/features">消息与视频</a> · <a href="/brand">品牌物料</a> · <a href="/miniapps">小程序</a> · <a href="/developers">开发者</a></div>
    </footer>
  )
}

/** 子页外壳:顶栏 + 正文 + 页脚,并设这一页自己的 title
 *  (转发到微信群、加书签、出现在搜索结果里,都要认得出是哪一页) */
export function SitePage({ active, title, note, children }) {
  useEffect(() => { if (title) document.title = title }, [title])
  return (
    <div className="h3">
      <SiteNav active={active} />
      <main>{children}</main>
      <SiteFooter note={note} />
    </div>
  )
}
