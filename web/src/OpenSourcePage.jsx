import React from 'react'

import './pages.css'
import { Icon, SitePage, bjParts, useJson } from './SiteChrome.jsx'
import LedgerChainFilm from './films/LedgerChainFilm.jsx'
import OpenCityMapFilm from './films/OpenCityMapFilm.jsx'

/* 开源仓 · 规则变更留痕(/opensource,设计稿 4i)。
 *
 * 左边是仓库里几处「规矩所在」的真实路径,右边是规则改动的时间线。
 *
 * 和稿子不一样的地方:
 * - 稿子画了四个子仓(super-z/rules、super-z/reconcile……)。没有子仓,
 *   整个平台就是一个仓库 hanpaopao66/chaojizan(AGPL-3.0),所以卡片指向
 *   这个仓库里的真实文件;
 * - 稿子写「任何一次改动都要经过公开评审,生效日期提前 14 天公示」。
 *   这两件事都没有:代码里有的是**规则内容一变,系统自动记一版**
 *   (/rules/{customer|merchant|rider}/revisions,带内容哈希和逐条增删),
 *   派单算法另有带日期的改动记录(/transparency/dispatch 的 changelog)。
 *   接口自己的注释也写着:这里回答「改过什么、什么时候改的」,不是公示期;
 * - 稿子的时间线是示例数据,这里是接口里的真记录;只有第一版时照实说。
 *
 * 官网动画集第二批(2026-09)加了两支片子:页头和「规则变更留痕」之间是
 * 哈希链片(films/LedgerChainFilm.jsx),页底是开城地图(films/OpenCityMapFilm.jsx)。
 * 片子要整页宽,页头因此从左栏里提出来,两栏只剩「规矩所在」和留痕。 */

const REPO = 'https://github.com/hanpaopao66/chaojizan'
const PATHS = [
  { icon: 'rules', name: 'services/rules.py', desc: '用户 / 商家 / 骑手三端规则的原文', href: `${REPO}/blob/main/server/app/services/rules.py` },
  { icon: 'calc', name: 'services/audit.py', desc: '每天 04:00 核账：近 30 天逐笔核对', href: `${REPO}/blob/main/server/app/services/audit.py` },
  { icon: 'shield', name: 'services/ledger.py · witness/', desc: '公开账本锚点 + 见证节点脚本，可本地复算', href: `${REPO}/tree/main/witness` },
  { icon: 'phone', name: 'apps/', desc: '用户端 / 商家端 / 骑手端 · Flutter', href: `${REPO}/tree/main/apps` },
  { icon: 'doc', name: 'docs/LEDGER-SPEC.md', desc: '账本格式与复算方法；其余规格也在 docs/', href: `${REPO}/blob/main/docs/LEDGER-SPEC.md` },
]

const AUD = [
  { key: 'customer', label: '用户', rules: '用户规则', tag: 'info' },
  { key: 'merchant', label: '商家', rules: '商家规则', tag: 'warn' },
  { key: 'rider', label: '骑手', rules: '骑手规则', tag: 'ok' },
]

/* 一条增删 → 一句话。规则条目里带 markdown 的 ** 和全角缩进,去掉 */
const clean = s => String(s || '').replace(/\*\*/g, '').replace(/^[\s　·•-]+/, '').trim()
const cut = (s, n) => (s.length > n ? `${s.slice(0, n)}…` : s)
function describe(changes) {
  const added = changes.flatMap(c => c.added || []).map(clean).filter(Boolean)
  const removed = changes.flatMap(c => c.removed || []).map(clean).filter(Boolean)
  const parts = []
  if (added.length) parts.push(`新增 ${added.length} 条：${cut(added[0], 38)}`)
  if (removed.length) parts.push(`删去 ${removed.length} 条${added.length ? '' : `：${cut(removed[0], 38)}`}`)
  return parts.join('；') || '内容有改动'
}

function useTimeline() {
  const c = useJson('/rules/customer/revisions?limit=20')
  const m = useJson('/rules/merchant/revisions?limit=20')
  const r = useJson('/rules/rider/revisions?limit=20')
  const dispatch = useJson('/transparency/dispatch')
  const byAud = { customer: c, merchant: m, rider: r }
  const loaded = !!(c || m || r)
  const entries = []
  const firsts = []
  for (const a of AUD) {
    for (const it of byAud[a.key]?.items ?? []) {
      const when = bjParts(it.at)
      if (it.is_first || !(it.changes?.length)) {
        if (it.is_first) firsts.push({ aud: a, day: when?.day })
        continue
      }
      entries.push({
        key: `${a.key}-${it.revision}`, day: when?.day ?? '', at: it.at,
        sha: String(it.content_hash || '').slice(0, 7),
        title: `${a.rules} 第 ${it.revision} 版 · ${clean(it.changes[0]?.title) || '条目调整'}`,
        desc: describe(it.changes), tag: a.label, tone: a.tag,
      })
    }
  }
  for (const [i, e] of (dispatch?.changelog ?? []).entries()) {
    // 改动说明常常是一长句:第一个分句当标题,其余当说明;分不开就截断
    const what = clean(e.what)
    const m = /^(.{4,24}?)[:：；;，,。](.+)$/.exec(what)
    entries.push({
      key: `d-${i}`, day: e.date, at: e.date, sha: '',
      title: `派单算法 · ${m ? m[1] : cut(what, 24)}`,
      desc: m ? cut(m[2].trim(), 64) : `原因：${cut(clean(e.why), 56)}`,
      tag: '派单', tone: 'plain',
    })
  }
  entries.sort((x, y) => String(y.at).localeCompare(String(x.at)))
  return { loaded, entries, firsts }
}

export default function OpenSourcePage() {
  const { loaded, entries, firsts } = useTimeline()
  return (
    <SitePage active="opensource" title="超级赞 · 开源仓与规则变更留痕">
      <div className="sz-page">
        <div className="sz-eyebrow">开源仓</div>
        <h1 className="sz-h1 os-h1">规矩写在代码里，<br />改了就有记录。</h1>
        <p className="sz-lede os-lede">费率、分账、排序、核账，全部在同一个仓库，AGPL-3.0 开源。三端规则的内容一变，系统就自动记一版；派单算法另有带日期的改动记录。</p>
        <a className="os-repo" href={REPO} target="_blank" rel="noreferrer">
          <Icon name="repo" size={18} /> github.com/hanpaopao66/chaojizan
        </a>

        <div className="sz-film-slot"><LedgerChainFilm /></div>

        <div className="sz-cols os-cols">
          <div>
            <h2 className="sz-h2">规矩在哪几个文件里</h2>
            <div className="os-paths">
              {PATHS.map((p, i) => (
                <a key={p.name} className="sz-card os-path sz-enter" style={{ '--i': i }} href={p.href} target="_blank" rel="noreferrer">
                  <Icon name={p.icon} size={20} color="#6B6862" />
                  <div className="tx"><div className="mono nm">{p.name}</div><div className="muted ds">{p.desc}</div></div>
                  <Icon name="arrow" size={18} color="#9A968C" />
                </a>
              ))}
            </div>
          </div>

          <div id="changes">
            <div className="os-head">
              <h2 className="sz-h2">规则变更留痕</h2>
              <span className="muted">{loaded ? `共 ${entries.length} 次变更 · 内容一变就自动记一版` : '读取中…'}</span>
            </div>
            <div className="os-log">
              {entries.map((e, i) => (
                <div key={e.key} className="row sz-enter" style={{ '--i': Math.min(i, 6) }}>
                  <div><div className="num dt">{e.day}</div>{e.sha && <div className="mono sha">{e.sha}</div>}</div>
                  <div><div className="t">{e.title}</div><div className="muted d">{e.desc}</div></div>
                  <span className={`sz-tag ${e.tone}`}>{e.tag}</span>
                </div>
              ))}
              {loaded && entries.length === 0 && (
                <div className="os-empty muted">
                  {firsts.length
                    ? `还没有改动：${firsts.map(f => `${f.aud.rules}（${f.day} 起记录）`).join('、')}都还是第 1 版。之后内容一变就会出现在这里。`
                    : '还没有规则改动的记录。规则内容第一次变化后，这里会出现第一条。'}
                </div>
              )}
            </div>
            <p className="note">每一版带内容哈希（左边那串）和逐条增删；同一版规则内容，哈希就一样。平台开关的变更（恶劣天气加价、停运、开城……）另记在<a href="/transparency#governance">透明中心 · 治理公开</a>。</p>
          </div>
        </div>

        <section className="os-city" id="city">
          <div className="sz-eyebrow">开城</div>
          <h2 className="sz-h2">一个行当一个行当地打，一座城一座城地开。</h2>
          <p className="sz-lede os-lede">开城手册在开源仓的 docs/OPEN-A-CITY.md：从零起一套自己的实例，每一步花什么钱、办什么证、错了怎么看出来。</p>
          <div className="sz-film-slot"><OpenCityMapFilm /></div>
        </section>
      </div>
    </SitePage>
  )
}
