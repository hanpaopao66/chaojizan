import React, { useEffect, useRef, useState } from 'react'
import docs from 'virtual:miniapp-docs'

import { Icon, SitePage, bjParts, copyText, useJson } from '../SiteChrome.jsx'
import './developers.css'

/* 开发者中心(/developers)与文档站(/developers/<页>),DEV-PROMPTS-39 #333。
 *
 * 文档的源头是仓库里的 docs/miniapp/*.md,构建时由 web/scripts/miniapp-docs.mjs 转成 HTML
 * (`virtual:miniapp-docs`),浏览器里不带 Markdown 解析器。页面顺序、侧栏名称都读 README 的目录。
 * 文档之间切页不整页刷新:所有页都在这一个包里,只换内容。
 *
 * 平台数据不另算,读透明中心那一栏的同一个接口(/transparency/miniapps)。
 * 「开发者规则」(/developers/rules)不是 Markdown,是 /rules/developer 实时生成的 ——
 * 每个数字都读自代码常量,改了自动记一版。
 *
 * 文档正文的标题用黑体不用衬线:官网的中文衬线是按 JSX 里写死的 h1/h2 切的子集
 * (scripts/gen_font_subset.py),Markdown 里的标题扫不到,用衬线会一行里字形打架。 */

const REPO = 'https://github.com/hanpaopao66/chaojizan'
const editUrl = file => `${REPO}/edit/main/docs/miniapp/${file}`
const sourceUrl = file => `${REPO}/blob/main/docs/miniapp/${file}`

/** /developers/quickstart → 'quickstart';/developers → '' */
const currentPage = () => decodeURIComponent(
  location.pathname.replace(/^\/site/, '').replace(/^\/developers\/?/, '').replace(/\/+$/, ''))

/* 全站 html 是 scroll-behavior: smooth(styles.css)。换页时要像打开新页面一样直接到位
 * —— 平滑滚过七千像素的 SDK 参考既慢又晃;同一页里点目录才让它平滑 */
function scrollToHash(instant = true) {
  const id = decodeURIComponent(location.hash.slice(1))
  const el = id ? document.getElementById(id) : null
  const behavior = instant ? 'instant' : 'auto'
  if (el) el.scrollIntoView({ behavior, block: 'start' })
  else window.scrollTo({ top: 0, left: 0, behavior })
}

function copyCode(btn) {
  copyText(btn.parentElement?.querySelector('pre')?.textContent ?? '').then(ok => {
    btn.textContent = ok ? '已复制' : '复制失败，请手动选中'
    setTimeout(() => { btn.textContent = '复制' }, 1500)
  })
}

export default function DevelopersPage() {
  const [page, setPage] = useState(currentPage)
  useEffect(() => {
    const on = () => { setPage(currentPage()); setTimeout(() => scrollToHash(), 0) }
    window.addEventListener('popstate', on)
    return () => window.removeEventListener('popstate', on)
  }, [])
  // 换了页(或带着锚点进来):effect 跑的时候新内容已经在 DOM 里了
  useEffect(() => scrollToHash(), [page])

  const onClick = e => {
    const copy = e.target.closest?.('.dv-copy')
    if (copy) { copyCode(copy); return }
    if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return
    const a = e.target.closest?.('a[href]')
    if (!a || a.target) return
    const url = new URL(a.getAttribute('href'), location.href)
    if (url.origin !== location.origin || !/^\/developers(\/|$)/.test(url.pathname)) return
    e.preventDefault()
    const same = url.pathname === location.pathname
    history.pushState(null, '', url.pathname + url.hash)
    // 同一页只换锚点:从搜索结果点进来的,正文要等这一轮渲染回来,所以下一轮再滚
    if (same) setTimeout(() => scrollToHash(a.dataset.jump === 'instant'), 0)
    else setPage(currentPage())
  }

  let body
  if (!page) body = <DevHome />
  else if (page === 'rules') body = <DocLayout page="rules"><RulesDoc /></DocLayout>
  else body = <DocLayout page={page} doc={docs.find(d => d.slug === page)} />
  return <div onClick={onClick}>{body}</div>
}

// ---------------------------------------------------------------- 开发者中心首页

const STEPS = [
  { t: '注册，建应用', d: '用手机号登录开发者后台就是注册（目前是邀请制）。建一个应用，拿到 AppID 和只显示一次的 AppSecret。', href: '/developers/quickstart#1-注册' },
  { t: '用模板跑通', d: '下载最小模板，打包上传开发版。后台模拟器里的 initData 是真签名，可以直接拿去你的后端验签。', href: '/developers/quickstart#3-下载模板' },
  { t: '认证，送审，发布', d: '个人实名或企业认证后提交审核，按清单逐项过。通过后一键发布，出了问题一键回滚到任一版本。', href: '/developers/quickstart#8-提交审核' },
]

function DevHome() {
  const t = useJson('/transparency/miniapps')
  const m = t?.month
  const doorways = [
    { icon: 'doc', t: '文档', d: `概览、核心概念、SDK 参考、服务端验签、云存储、设计与审核规范，共 ${docs.length} 页`, href: '/developers/overview' },
    { icon: 'phone', t: '开发者后台', d: '建应用、传版本、模拟器、体验者、审核进度、数据', href: '/dev/' },
    { icon: 'repo', t: '示例源码', d: '记事本、2048 和最小模板。平台上跑的就是这份源码构建出来的，SHA-256 对得上', href: `${REPO}/tree/main/miniapps`, external: true },
    { icon: 'rules', t: '审核与运营规范', d: '允许与禁止、原因代码逐条解释、排序规则、处罚与申诉', href: '/developers/review' },
  ]
  return (
    <SitePage title="超级赞 · 开发者中心" note="平台数据与透明中心同源">
      <div className="sz-page dv-home">
        <div className="sz-eyebrow">开发者中心</div>
        <h1 className="sz-h1">用普通网页，<br />做超级赞里的小程序。</h1>
        <p className="sz-lede">HTML、CSS、JavaScript 打成 zip 上传，平台托管、审核、发布；用户在超级赞 App 里下拉就能打开。技术路线对标 Telegram Mini Apps，写过 TG 小程序的几乎可以照搬。发布免费，也没有可以花钱买的曝光。</p>
        <div className="h3-cta dv-cta">
          <a className="h3-btn primary" href="/developers/quickstart">十分钟快速开始</a>
          <a className="h3-btn ghost" href="/dev/">进入开发者后台</a>
        </div>

        <section className="dv-sec">
          <h2 className="sz-h2">三步上线</h2>
          <ol className="dv-steps">
            {STEPS.map((s, i) => (
              <li key={s.t} className="sz-card">
                <span className="num k">{i + 1}</span>
                <div className="t">{s.t}</div>
                <p className="muted">{s.d}</p>
                <a className="lnk" href={s.href}>快速开始的这一步</a>
              </li>
            ))}
          </ol>
        </section>

        <section className="dv-sec">
          <h2 className="sz-h2">从这里进</h2>
          <div className="dv-doors">
            {doorways.map(x => (
              <a key={x.t} className="sz-card dv-door" href={x.href}
                {...(x.external ? { target: '_blank', rel: 'noreferrer' } : {})}>
                <Icon name={x.icon} size={20} color="#6B6862" />
                <div className="tx"><div className="t">{x.t}</div><div className="muted d">{x.d}</div></div>
                <Icon name="arrow" size={18} color="#9A968C" />
              </a>
            ))}
          </div>
        </section>

        <section className="dv-sec">
          <h2 className="sz-h2">平台数据</h2>
          <p className="muted dv-sub">和透明中心「小程序」一栏读同一个接口，不另算。</p>
          <div className="dv-stats">
            <div className="sz-card"><div className="num v">{t?.verified_developers ?? '–'}</div><div className="k">已认证开发者</div></div>
            <div className="sz-card">
              <div className="num v">{t ? t.online_apps.app + t.online_apps.game : '–'}</div>
              <div className="k">在线{t ? `：${t.online_apps.app} 个应用、${t.online_apps.game} 个小游戏` : ''}</div>
            </div>
            <div className="sz-card">
              <div className="num v">{m ? `${m.approved} / ${m.submitted}` : '–'}</div>
              <div className="k">本月通过 / 提交{m ? `，驳回 ${m.rejected}` : ''}</div>
            </div>
            <div className="sz-card">
              <div className="num v">{m?.median_review_hours != null ? m.median_review_hours : '–'}<small> 小时</small></div>
              <div className="k">{m?.median_review_hours != null ? '本月审核时长中位数' : '本月还没有审核结论'}</div>
            </div>
          </div>
          <p className="note">下架记录、精选名单和每次变动的理由，在<a href="/transparency#miniapps">透明中心 · 小程序</a>。审核不承诺时限，时长照实公示。</p>
        </section>

        <section className="dv-sec">
          <h2 className="sz-h2">全部文档</h2>
          <div className="dv-index">
            {docs.map(d => (
              <a key={d.slug} href={`/developers/${d.slug}`}>
                <span className="t">{d.label}</span>
                {d.desc && <span className="muted">{d.desc}</span>}
              </a>
            ))}
            <a href="/developers/rules">
              <span className="t">开发者规则</span>
              <span className="muted">由服务端代码实时生成，每个数字读自代码常量，改了自动记一版</span>
            </a>
          </div>
          <p className="note">文档就在开源仓的 <a href={`${REPO}/tree/main/docs/miniapp`} target="_blank" rel="noreferrer">docs/miniapp/</a>，写错了、没写清楚，每页底下都能直接去 GitHub 上改。</p>
        </section>
      </div>
    </SitePage>
  )
}

// ---------------------------------------------------------------- 文档页

function DocLayout({ page, doc, children }) {
  const [q, setQ] = useState('')
  const [menu, setMenu] = useState(false)
  useEffect(() => { setMenu(false) }, [page])
  const isRules = page === 'rules'
  const title = doc ? doc.title : isRules ? '开发者规则' : '没有这一页'
  const label = doc ? doc.label : isRules ? '开发者规则' : '文档目录'
  const idx = doc ? docs.indexOf(doc) : -1
  const searching = q.trim() !== ''
  // 开始搜的时候正文换成结果列表,结果比正文短得多 —— 停在原处的话看到的是页脚
  useEffect(() => { if (searching) window.scrollTo({ top: 0, left: 0, behavior: 'instant' }) }, [searching])
  return (
    <SitePage title={`${title} · 超级赞开发者文档`}>
      <div className={`dv ${doc?.headings.length && !searching ? 'has-toc' : ''}`}>
        <aside className={`dv-side ${menu ? 'open' : ''}`}>
          <a className="dv-back" href="/developers">开发者中心</a>
          <SearchBox q={q} setQ={setQ} />
          <button type="button" className="dv-menu" aria-expanded={menu} onClick={() => setMenu(v => !v)}>
            <span>{label}</span><span className="muted">{menu ? '收起' : '全部文档'}</span>
          </button>
          <nav className="dv-nav" aria-label="文档目录">
            {docs.map(d => (
              <a key={d.slug} href={`/developers/${d.slug}`} className={d.slug === page ? 'on' : undefined}
                aria-current={d.slug === page ? 'page' : undefined}>{d.label}</a>
            ))}
            <a href="/developers/rules" className={isRules ? 'on' : undefined}
              aria-current={isRules ? 'page' : undefined}>开发者规则</a>
          </nav>
          <div className="dv-side-foot">
            <a href="/dev/">开发者后台 ↗</a>
            <a href={`${REPO}/tree/main/miniapps`} target="_blank" rel="noreferrer">示例源码 ↗</a>
          </div>
        </aside>

        <div className="dv-main">
          {searching ? <SearchResults q={q} onPick={() => setQ('')} /> : (
            <>
              {children ?? (doc
                ? <article className="dv-md" dangerouslySetInnerHTML={{ __html: doc.html }} />
                : (
                  <article className="dv-md">
                    <h1>没有这一页</h1>
                    <p>文档可能改了名字。从左边的目录找，或者用上面的搜索。</p>
                  </article>
                ))}
              {doc && (
                <div className="dv-foot">
                  <div className="dv-edit">
                    <a href={editUrl(doc.file)} target="_blank" rel="noreferrer">在 GitHub 上编辑这一页</a>
                    <span className="muted"> · 源文件 <a className="mono" href={sourceUrl(doc.file)} target="_blank" rel="noreferrer">docs/miniapp/{doc.file}</a></span>
                  </div>
                  <div className="dv-pn">
                    {idx > 0 ? (
                      <a href={`/developers/${docs[idx - 1].slug}`}><span className="muted">上一页</span>{docs[idx - 1].label}</a>
                    ) : <span />}
                    {idx < docs.length - 1 ? (
                      <a className="next" href={`/developers/${docs[idx + 1].slug}`}><span className="muted">下一页</span>{docs[idx + 1].label}</a>
                    ) : <span />}
                  </div>
                </div>
              )}
            </>
          )}
        </div>

        {doc && doc.headings.length > 0 && !searching && (
          <aside className="dv-toc" aria-label="本页目录">
            <div className="cap">本页</div>
            {doc.headings.filter(h => h.level <= 3).map(h => (
              <a key={h.id} href={`#${h.id}`} className={h.level === 3 ? 'l3' : undefined}>{h.text}</a>
            ))}
          </aside>
        )}
      </div>
    </SitePage>
  )
}

// ---------------------------------------------------------------- 站内搜索

/* 索引第一次搜的时候才建:把每页的 HTML 按 h2–h4 切成小节,记下标题和纯文字 */
let INDEX = null

/** 一块的纯文字。列表项、表格格子之间补空格(textContent 会把「错误码」「服务端」粘成一个词) */
function textOf(el) {
  if (el.classList.contains('dv-code')) return el.querySelector('pre')?.textContent ?? ''
  const parts = []
  const walk = n => {
    if (n.nodeType === 3) parts.push(n.nodeValue)
    if (n.nodeType !== 1) return
    for (const c of n.childNodes) walk(c)
    if (/^(LI|TD|TH|TR|P)$/.test(n.tagName)) parts.push(' ')
  }
  walk(el)
  return parts.join('')
}
function searchIndex() {
  if (INDEX) return INDEX
  const parser = new DOMParser()
  INDEX = []
  for (const d of docs) {
    const body = parser.parseFromString(d.html, 'text/html').body
    let cur = { doc: d, id: '', title: d.title, text: '' }
    INDEX.push(cur)
    for (const el of body.children) {
      if (/^H[2-4]$/.test(el.tagName)) {
        cur = { doc: d, id: el.id, title: el.textContent, text: '' }
        INDEX.push(cur)
      } else if (el.tagName !== 'H1') {
        cur.text += `${textOf(el)}\n`
      }
    }
  }
  for (const s of INDEX) {
    s.text = s.text.replace(/\s+/g, ' ').trim()
    s.hay = `${s.title}\n${s.text}`.toLowerCase()
  }
  return INDEX
}

const MAX_HITS = 40
function search(q) {
  const terms = q.toLowerCase().split(/\s+/).filter(Boolean)
  if (!terms.length) return { terms, hits: [] }
  const hits = []
  for (const s of searchIndex()) {
    if (!terms.every(t => s.hay.includes(t))) continue
    const title = s.title.toLowerCase()
    let score = 0
    for (const t of terms) {
      if (title.includes(t)) score += 10
      if (s.doc.label.toLowerCase().includes(t)) score += 3
    }
    hits.push({ s, score })
  }
  // 排序是稳定的:同分的按文档目录顺序
  hits.sort((a, b) => b.score - a.score)
  return { terms, hits: hits.slice(0, MAX_HITS) }
}

function snippet(text, terms) {
  const low = text.toLowerCase()
  let at = -1
  for (const t of terms) {
    const k = low.indexOf(t)
    if (k >= 0 && (at < 0 || k < at)) at = k
  }
  if (at < 0) return text.slice(0, 90)
  const from = Math.max(0, at - 30)
  return `${from > 0 ? '…' : ''}${text.slice(from, at + 70)}${at + 70 < text.length ? '…' : ''}`
}

function Mark({ text, terms }) {
  const re = new RegExp(`(${terms.map(t => t.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|')})`, 'gi')
  return text.split(re).map((p, i) => (i % 2 ? <mark key={i}>{p}</mark> : <React.Fragment key={i}>{p}</React.Fragment>))
}

function SearchBox({ q, setQ }) {
  const ref = useRef(null)
  useEffect(() => {
    // 「/」聚焦搜索(正在输入的时候不抢)
    const on = e => {
      if (e.key !== '/' || e.metaKey || e.ctrlKey || e.altKey) return
      const tag = document.activeElement?.tagName
      if (tag === 'INPUT' || tag === 'TEXTAREA' || document.activeElement?.isContentEditable) return
      e.preventDefault()
      ref.current?.focus()
    }
    window.addEventListener('keydown', on)
    return () => window.removeEventListener('keydown', on)
  }, [])
  return (
    <label className="dv-search">
      <span className="sr">搜索文档</span>
      <input ref={ref} type="search" value={q} placeholder="搜索文档" title="电脑上按 / 键直接到这里" autoComplete="off"
        onChange={e => setQ(e.target.value)}
        onKeyDown={e => { if (e.key === 'Escape') setQ('') }} />
    </label>
  )
}

function SearchResults({ q, onPick }) {
  const { terms, hits } = search(q)
  return (
    <div className="dv-results" role="region" aria-label="搜索结果">
      <div className="head">
        「{q.trim()}」{hits.length ? `找到 ${hits.length}${hits.length === MAX_HITS ? '+' : ''} 处` : '没有找到'}
        <button type="button" className="h3-btn sm ghost" onClick={onPick}>清空</button>
      </div>
      {hits.length === 0 && <p className="muted">换个词试试：方法名（如 requestProfile）、错误码（如 4001）、中文关键词（如 验签、配额）。</p>}
      {hits.map(({ s }) => (
        <a key={`${s.doc.slug}#${s.id}`} className="dv-hit" data-jump="instant"
          href={`/developers/${s.doc.slug}${s.id ? `#${s.id}` : ''}`} onClick={onPick}>
          <div className="where">{s.doc.label}{s.id && <span className="muted"> › <Mark text={s.title} terms={terms} /></span>}</div>
          {s.text && <div className="snip muted"><Mark text={snippet(s.text, terms)} terms={terms} /></div>}
        </a>
      ))}
    </div>
  )
}

// ---------------------------------------------------------------- 开发者规则(实时生成)

/** 规则条目里的 **粗体** → <strong> */
function bold(text) {
  return String(text).split(/\*\*(.+?)\*\*/g).map((p, i) => (i % 2 ? <strong key={i}>{p}</strong> : p))
}

function RulesDoc() {
  const rules = useJson('/rules/developer')
  const revs = useJson('/rules/developer/revisions?limit=5')
  const latest = revs?.items?.[0]
  return (
    <article className="dv-md">
      <h1>开发者规则{rules?.draft ? '（草案）' : ''}</h1>
      <p>
        这一页由服务端代码实时生成（<a href={`${REPO}/blob/main/server/app/services/miniapp_rules.py`} target="_blank" rel="noreferrer"><code>services/miniapp_rules.py</code></a>），每个数字都读自代码常量，和文档、后台、审核用的是同一份。内容一变，系统自动记一版，开发者要接受最新一版才能继续提交审核。
        {latest && <>当前是第 {latest.revision} 版（{bjParts(latest.at)?.day ?? ''} 起），内容哈希 <code>{String(latest.content_hash).slice(0, 12)}</code>。</>}
        每一版改了什么见<a href="/opensource#changes">开源仓 · 规则变更留痕</a>。
      </p>
      {!rules && <p className="muted">读取中…</p>}
      {rules?.sections.map(sec => (
        <section key={sec.title}>
          <h2 id={sec.title}>{sec.title}</h2>
          <ul>
            {sec.items.map((it, i) => {
              const sub = /^[\s　]*·/.test(it)
              return <li key={i} className={sub ? 'sub' : undefined}>{bold(it.replace(/^[\s　]*·\s*/, ''))}</li>
            })}
          </ul>
        </section>
      ))}
    </article>
  )
}
