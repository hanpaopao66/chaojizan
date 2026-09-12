import React, { useEffect, useState } from 'react'

import { Icon, SitePage, bjParts, copyText } from '../SiteChrome.jsx'
import './miniapps.css'

/* 小程序公开目录(/miniapps)与直达链接的兜底页(/m/<appid>),DEV-PROMPTS-39 #326、§5.7。
 *
 * 装了 App 的安卓手机点 https://chaojizan.cc/m/<appid> 会被 App Links 直接拉起,根本到不了这页;
 * 到了这页的是:没装 App、在微信里、在电脑上,或者系统没认下 App Links。所以这页要讲清楚
 * 这是什么、谁做的、怎么打开,而不是只有一个按钮。
 *
 * 目录的顺序由服务端的纯函数决定(services/miniapp_catalog.py),这里原样照排,不做二次排序。
 * 名称、介绍都是开发者写的,一律当文字渲染(React 默认转义),不拼 HTML。 */

const REPO = 'https://github.com/hanpaopao66/chaojizan'
const PACKAGE = 'com.chaojizan.user'
const START_PARAM = /^[A-Za-z0-9_-]{1,64}$/

/* 和用户端详情页的能力说明是同一套话(apps/user_app/lib/miniapp/pages.dart) */
const CAP_LABELS = {
  initData: '识别你是谁（按应用隔离的编号，不含手机号）',
  storage: '云存储（只存你在这个小程序里的数据）',
  share: '系统分享',
  haptics: '触感反馈',
  popup: '弹窗',
  openLink: '打开外部链接（先问你）',
  fullscreen: '全屏',
  orientation: '锁定屏幕方向',
  profile: '昵称和头像（要你同意）',
}

const KINDS = [['', '全部'], ['app', '应用'], ['game', '小游戏']]

export default function MiniAppsPage({ appid }) {
  return appid ? <Detail appid={appid} /> : <Catalog />
}

/** 图标:一个字画在淡底上,或者开发者上传的图(只收平台自己的 /img/ 地址) */
function AppIcon({ a, size = 48 }) {
  const style = { width: size, height: size, borderRadius: Math.round(size * 0.24) }
  if (typeof a.icon === 'string' && a.icon.startsWith('/img/')) {
    return <img className="ma-icon" src={a.icon} alt="" style={style} loading="lazy" />
  }
  const chars = Array.from(a.icon || '')
  const glyph = chars.length === 1 ? chars[0] : Array.from(a.name || '?')[0]
  return (
    <span className={`ma-icon ${a.kind === 'game' ? 'game' : ''}`} aria-hidden="true"
      style={{ ...style, fontSize: Math.round(size * 0.46) }}>{glyph}</span>
  )
}

function Tags({ a }) {
  return (
    <>
      {a.curated && <span className="sz-tag warn">精选</span>}
      {a.kind === 'game' && <span className="sz-tag info">小游戏</span>}
    </>
  )
}

// ---------------------------------------------------------------- 目录

function Catalog() {
  const [q, setQ] = useState(() => new URLSearchParams(location.search).get('q') || '')
  const [kind, setKind] = useState('')
  const [cat, setCat] = useState('')
  const [items, setItems] = useState([])
  const [resp, setResp] = useState(null)
  const [state, setState] = useState('loading') // loading | ok | error
  const [more, setMore] = useState(false)

  const query = cursor => {
    const p = new URLSearchParams()
    if (q.trim()) p.set('q', q.trim())
    if (kind) p.set('kind', kind)
    if (cat) p.set('category', cat)
    if (cursor) p.set('cursor', String(cursor))
    return `/mini-apps/catalog?${p}`
  }

  useEffect(() => {
    const ctl = new AbortController()
    // 打字的时候不每个字母打一次
    const t = setTimeout(() => {
      setState('loading')
      fetch(query(0), { signal: ctl.signal })
        .then(r => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
        .then(d => { setResp(d); setItems(d.items); setState('ok') })
        .catch(e => { if (e.name !== 'AbortError') setState('error') })
    }, q ? 250 : 0)
    return () => { clearTimeout(t); ctl.abort() }
  }, [q, kind, cat]) // eslint-disable-line react-hooks/exhaustive-deps

  const loadMore = () => {
    if (resp?.next_cursor == null || more) return
    setMore(true)
    fetch(query(resp.next_cursor))
      .then(r => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then(d => { setResp(d); setItems(xs => xs.concat(d.items)) })
      .catch(() => {})
      .finally(() => setMore(false))
  }

  const searching = q.trim() !== ''
  return (
    <SitePage title="超级赞 · 小程序" note="目录顺序由公开的排序函数决定">
      <div className="sz-page ma">
        <div className="sz-eyebrow">小程序</div>
        <h1 className="sz-h1">下拉就能打开的小程序，<br />怎么排序也写在明处。</h1>
        <p className="sz-lede">这里是超级赞 App 里全部上架的小程序和小游戏。精选在前（人工挑选，理由公示），其余按首次上架时间从新到旧——没有竞价，没有付费位置。</p>

        <div className="ma-bar">
          <label className="ma-search">
            <span className="sr">搜索小程序</span>
            <input type="search" value={q} placeholder="搜名称、介绍或开发者" autoComplete="off"
              onChange={e => setQ(e.target.value)} />
          </label>
          <div className="ma-seg" role="group" aria-label="类型">
            {KINDS.map(([k, label]) => (
              <button key={k || 'all'} type="button" className={kind === k ? 'on' : undefined}
                aria-pressed={kind === k} onClick={() => setKind(k)}>{label}</button>
            ))}
          </div>
        </div>
        {(resp?.categories?.length ?? 0) > 0 && (
          <div className="ma-cats" role="group" aria-label="分类">
            <button type="button" className={cat === '' ? 'on' : undefined} aria-pressed={cat === ''} onClick={() => setCat('')}>全部分类</button>
            {resp.categories.map(c => (
              <button key={c.key} type="button" className={cat === c.key ? 'on' : undefined}
                aria-pressed={cat === c.key} onClick={() => setCat(c.key)}>{c.label}</button>
            ))}
          </div>
        )}

        <div className="ma-meta muted">
          {state === 'loading' && '读取中…'}
          {state === 'error' && '目录暂时读不到，稍后再试。'}
          {state === 'ok' && (searching
            ? `「${q.trim()}」找到 ${resp.total} 个`
            : `共 ${resp.total} 个${kind === 'game' ? '小游戏' : kind === 'app' ? '应用' : ''}`)}
        </div>

        {state === 'ok' && items.length === 0 && (
          <div className="ma-empty muted">
            {searching ? '没有找到。搜索按名称精确命中、前缀、包含，再到一句话介绍和开发者名。' : '这个分类下还没有上架的小程序。'}
          </div>
        )}
        <div className="ma-list">
          {items.map((a, i) => (
            <a key={a.appid} className="ma-row sz-enter" style={{ '--i': Math.min(i, 6) }} href={`/m/${a.appid}`}>
              <AppIcon a={a} />
              <div className="tx">
                <div className="nm"><span className="name">{a.name}</span><Tags a={a} /></div>
                {a.tagline && <div className="tg">{a.tagline}</div>}
                <div className="by muted">{a.developer.name} · {a.developer.label}{a.category_label ? ` · ${a.category_label}` : ''}</div>
              </div>
              <Icon name="arrow" size={18} color="#9A968C" />
            </a>
          ))}
        </div>
        {resp?.next_cursor != null && (
          <div className="ma-more">
            <button type="button" className="h3-btn ghost" onClick={loadMore} disabled={more}>{more ? '读取中…' : '再看一些'}</button>
          </div>
        )}

        <div className="ma-rule">
          <div className="sec">排序规则</div>
          <p>{resp?.sort_rule || '精选位在前（人工挑选，每次变动的理由在透明中心公示）；其余按首次上架时间从新到旧。没有竞价、没有付费位置。'}</p>
          <p className="note">
            排序是一段公开的纯函数（<a href={`${REPO}/blob/main/server/app/services/miniapp_catalog.py`} target="_blank" rel="noreferrer">services/miniapp_catalog.py</a>），打开次数、评分、付费这类字段根本不进这个函数，有测试守着。精选名单和每次变动的理由在<a href="/transparency#miniapps">透明中心</a>，完整规则见<a href="/developers/operations">运营规范</a>。想做一个？看<a href="/developers">开发者中心</a>。
          </p>
        </div>
      </div>
    </SitePage>
  )
}

// ---------------------------------------------------------------- 详情 / 直达链接兜底页

const ua = typeof navigator !== 'undefined' ? navigator.userAgent : ''
const IN_WECHAT = /MicroMessenger|QQ\//i.test(ua)
const ANDROID = /Android/i.test(ua)

function Detail({ appid }) {
  const params = new URLSearchParams(location.search)
  const rawStart = params.get('startapp') || ''
  const startapp = START_PARAM.test(rawStart) ? rawStart : ''
  const trial = params.get('v') === 'trial'
  const [d, setD] = useState(undefined) // undefined 读取中 · null 没有 · false 读不到
  const [copied, setCopied] = useState('')

  useEffect(() => {
    if (!/^sz[0-9a-f]{16}$/.test(appid)) { setD(null); return undefined }
    const ctl = new AbortController()
    fetch(`/mini-apps/${appid}`, { signal: ctl.signal })
      .then(r => (r.status === 404 ? null : r.ok ? r.json() : false))
      .then(setD)
      .catch(e => { if (e.name !== 'AbortError') setD(false) })
    return () => ctl.abort()
  }, [appid])

  const qs = new URLSearchParams()
  if (startapp) qs.set('startapp', startapp)
  if (trial) qs.set('v', 'trial')
  const link = `https://chaojizan.cc/m/${appid}${qs.toString() ? `?${qs}` : ''}`
  // 安卓浏览器里:intent 链接强制交给 App;没装的话落到下载页
  const intent = `intent://chaojizan.cc/m/${appid}${qs.toString() ? `?${qs}` : ''}#Intent;scheme=https;package=${PACKAGE};`
    + `S.browser_fallback_url=${encodeURIComponent('https://chaojizan.cc/download')};end`
  const copy = () => copyText(link).then(ok => {
    setCopied(ok ? '已复制' : '复制失败')
    setTimeout(() => setCopied(''), 1500)
  })

  if (d === undefined) {
    return <SitePage title="超级赞 · 小程序"><div className="sz-page ma"><p className="muted">读取中…</p></div></SitePage>
  }
  if (!d) {
    return (
      <SitePage title="超级赞 · 没有找到这个小程序">
        <div className="sz-page ma">
          <div className="sz-eyebrow"><a href="/miniapps">小程序</a></div>
          <h1 className="sz-h1">{d === null ? '没有找到这个小程序' : '暂时读不到'}</h1>
          <p className="sz-lede">{d === null
            ? '它可能还没上架，或者已经被移除。移除和暂停的记录在透明中心公示。'
            : '网络或服务出了点问题，稍后刷新再试。'}</p>
          <div className="h3-cta ma-cta">
            <a className="h3-btn primary" href="/miniapps">看全部小程序</a>
            <a className="h3-btn ghost" href="/transparency#miniapps">透明中心 · 小程序</a>
          </div>
        </div>
      </SitePage>
    )
  }

  const v = d.version
  const released = v?.released_at ? bjParts(v.released_at) : null
  const first = d.first_released_at ? bjParts(d.first_released_at) : null
  return (
    <SitePage title={`${d.name} · 超级赞小程序`}>
      <div className="sz-page ma ma-detail">
        <div className="sz-eyebrow"><a href="/miniapps">小程序</a> · {d.kind === 'game' ? '小游戏' : '应用'}{d.category_label ? ` · ${d.category_label}` : ''}</div>
        <div className="ma-head">
          <AppIcon a={d} size={72} />
          <div className="tx">
            <h1 className="ma-name">{d.name}</h1>
            {d.tagline && <p className="ma-tagline">{d.tagline}</p>}
            <div className="ma-by"><span>{d.developer.name}</span><span className={`sz-tag ${d.developer.official ? 'warn' : d.developer.verified ? 'ok' : 'plain'}`}>{d.developer.label}</span><Tags a={d} /></div>
          </div>
        </div>

        {trial && <div className="ma-notice">这是<b>体验版</b>链接：只有开发者加进「体验者」的手机号，登录超级赞 App 后才能打开。</div>}
        {!d.available && <div className="ma-notice">这个小程序现在打不开（{d.status_label}）。</div>}

        <div className="ma-open">
          {IN_WECHAT ? (
            <p className="ma-wx">微信里拉不起 App：点右上角<b>「…」</b>，选<b>「在浏览器打开」</b>，再点这页的「在 App 里打开」。</p>
          ) : (
            <div className="h3-cta">
              {ANDROID && d.available && <a className="h3-btn primary" href={intent}>在超级赞 App 里打开</a>}
              <a className={`h3-btn ${ANDROID && d.available ? 'ghost' : 'primary'}`} href="/download">下载超级赞 App</a>
              <button type="button" className="h3-btn ghost" onClick={copy}>{copied || '复制链接'}</button>
            </div>
          )}
          <p className="note">
            {ANDROID
              ? '装了 App 的话，点这个小程序的链接会直接在 App 里打开；打不开时用上面的按钮。'
              : '小程序在超级赞 App 里打开（目前是安卓版）。用手机打开这个链接，或者在 App 里下拉、搜名字。'}
            {startapp && <>链接带着参数 <code className="mono">{startapp}</code>，会原样交给小程序。</>}
          </p>
        </div>

        <div className="ma-cols">
          <div className="ma-body">
            {d.description && (
              <section>
                <h2 className="ma-h">介绍</h2>
                <p className="ma-desc">{d.description}</p>
              </section>
            )}
            {(d.screenshots?.length ?? 0) > 0 && (
              <section>
                <h2 className="ma-h">截图</h2>
                <div className="ma-shots">
                  {d.screenshots.map(s => <img key={s} src={s} alt={`${d.name} 截图`} loading="lazy" />)}
                </div>
              </section>
            )}
            <section>
              <h2 className="ma-h">用到的能力</h2>
              <ul className="ma-caps">
                {(d.capabilities || []).map(c => <li key={c}>{CAP_LABELS[c] ?? c}</li>)}
              </ul>
              <p className="note">能力是宿主每次调用时当场查的：平台收回某项能力，小程序下一次调用就失败，不用等它更新。</p>
            </section>
            <section>
              <h2 className="ma-h">收集哪些数据</h2>
              {(d.data_declaration?.length ?? 0) > 0 ? (
                <div className="sz-table-wrap"><div className="sz-table-scroll">
                  <table className="sz-table">
                    <thead><tr><th>数据</th><th>用来做什么</th></tr></thead>
                    <tbody>{d.data_declaration.map((x, i) => <tr key={i}><td>{x.field}</td><td>{x.purpose}</td></tr>)}</tbody>
                  </table>
                </div></div>
              ) : <p className="muted">开发者声明不收集个人数据。</p>}
              <p className="note">
                {(d.request_domains?.length ?? 0) > 0
                  ? <>页面只能连这些服务器（写进了浏览器的安全策略，连别处会被拦下）：{d.request_domains.map(x => <code key={x} className="mono ma-dom">{x}</code>)}</>
                  : '页面不连任何外部服务器（浏览器的安全策略只放行平台自己）。'}
              </p>
            </section>
            {d.privacy_policy && (
              <section>
                <h2 className="ma-h">隐私政策</h2>
                <div className="ma-policy">{d.privacy_policy}</div>
              </section>
            )}
          </div>

          <aside className="ma-side">
            <div className="sz-card ma-facts">
              <div className="row"><span className="k">开发者</span><span>{d.developer.name}<br /><span className="muted">{d.developer.label}</span></span></div>
              {first && <div className="row"><span className="k">首次上架</span><span className="num">{first.day}</span></div>}
              {v ? (
                <>
                  <div className="row"><span className="k">当前版本</span><span><span className="num">{v.version}</span> <span className="muted">（第 {v.build} 次构建）</span></span></div>
                  {released && <div className="row"><span className="k">发布时间</span><span className="num">{released.day} {released.hm}</span></div>}
                  <div className="row"><span className="k">包大小</span><span><span className="num">{(v.size / 1024).toFixed(1)}</span> KB · {v.file_count} 个文件</span></div>
                  <div className="sha">
                    <div className="k">当前版本 SHA-256</div>
                    <code className="mono">{v.sha256}</code>
                    <p className="muted">平台存的是开发者上传的原始字节，审核看的、你打开的都是这一份，文件只写一次、不能事后替换。开源的小程序可以自己构建一遍来对这串数。</p>
                    {d.is_official && <p className="muted">官方小程序的源码在 <a className="lnk" href={`${REPO}/tree/main/miniapps`} target="_blank" rel="noreferrer">miniapps/</a>，构建方法见<a className="lnk" href="/developers/examples">示例导读</a>。</p>}
                  </div>
                </>
              ) : d.entry_url && (
                <div className="row"><span className="k">页面</span><span>平台自家页面，不走托管：<a className="lnk" href={d.entry_url}>{d.entry_url.replace(/^https?:\/\//, '')}</a></span></div>
              )}
            </div>
            <div className="ma-report muted">
              觉得这个小程序有问题？在 App 里它的详情页点「投诉」。平台按<a className="lnk" href="/developers/review#原因代码">原因代码</a>处理，处罚记录在<a className="lnk" href="/transparency#miniapps">透明中心</a>公示。
            </div>
          </aside>
        </div>
      </div>
    </SitePage>
  )
}
