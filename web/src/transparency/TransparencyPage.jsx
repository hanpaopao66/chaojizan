import React, { useEffect, useRef, useState } from 'react'

import {
  SitePage, SplitBar, bjDay, bjParts, kw, mdOf, money, useCountUp, useJson,
} from '../SiteChrome.jsx'
import AuditLampFilm from '../films/AuditLampFilm.jsx'
import DispatchOpenFilm from '../films/DispatchOpenFilm.jsx'
import './transparency.css'

/* 透明中心(/transparency,/status 直达系统状态区)。
 *
 * 首屏是设计稿 4a「今天的每一分钱,去了哪」:四个数 + 分账条 + 今日逐单表
 * (谁都能下 CSV)+ 账本指纹 + 见证节点。往下是原有的各栏:核账日历、钱去哪了、
 * 分账公平、赔付记录、月度财报、派单算法、判责分摊、治理公开、系统状态、最近更新。
 * 所有数字来自公开接口,口径注释随数字展示 —— 透明的透明。
 *
 * 和 4a 稿子不一样的地方:
 * - 稿子写「今日账本指纹 · 每天 04:00 由核账脚本生成」。锚点是每天零点过后为
 *   **前一天**生成的,所以这里写「最新账本指纹」并标出是哪一天;04:00 跑的是核账,
 *   两件事分开说;
 * - 稿子的「差额 ¥0.00」:核账给的是差错笔数,没有金额差额,就写差错笔数;
 * - 「骑手所得 · 配送费全额」:骑手那份是配送费 + 小费,跑腿单扣 2%,写成
 *   「配送费 + 小费」;
 * - 单号那一列是单号指纹(sha256 前 6 位,和账本锚点同一个算法),不是单号。
 *
 * 核账那一栏的开场是「差一分钱都亮红灯」那支示例片(films/AuditLampFilm.jsx,
 * 官网动画集第二批),真的数和 90 格紧跟在它下面。派单算法那一栏(第 8 节)同理:
 * 开场是「谁排在前面,凭什么」那支示例片(films/DispatchOpenFilm.jsx,第三批),
 * 把三张候选单按旧公式、新公式各排一遍,真的公式和权重表紧跟其后。 */

const CH_COLOR = {
  food: '#943F2F', retail: '#01756C', errand_send: '#2B5F7A', errand_buy: '#2B5F7A',
  voucher: '#88611C', stay: '#4E7054',
}
const EARN = '#4E6B4F'
const HOLD = '#A6763E'

const yuanF = c => (c == null ? '–' : `¥${(c / 100).toLocaleString('zh-CN', { maximumFractionDigits: 0 })}`)
const pct = r => (r == null ? '–' : `${(r * 100).toFixed(2)}%`)
/* 大字的小数位按终值定,滚动途中不换格式:过百元写到元,不到一百写到分 */
const bigMoney = (v, fin) => (fin === 0 ? '¥0' : money(v, Math.abs(fin ?? v) >= 10000 ? 0 : 2))

/* ================= 4a:今天的账 ================= */

function Big({ value, fmt, tone, label, hint }) {
  const shown = useCountUp(value)
  const zero = value === 0
  return (
    <div className="tp-big">
      <div className={`num n ${zero || value == null ? '' : tone || ''}`}>
        {value == null ? '–' : fmt(Math.round(shown), value)}
      </div>
      <div className="l">{label}</div>
      {zero && hint && <div className="l hint">{hint}</div>}
    </div>
  )
}

function AuditPill({ audit }) {
  const latest = audit?.latest
  if (!audit) return null
  if (!latest) return <span className="tp-pill off"><span className="sz-led off" />还没有核账记录</span>
  if (latest.problems > 0) {
    return (
      <a className="tp-pill bad" href="#audit">
        <span className="sz-led bad" />{mdOf(latest.day)} 核账发现 {latest.problems} 笔差错 →
      </a>
    )
  }
  return <span className="tp-pill"><span className="sz-led" />{mdOf(latest.day)} 04:00 核账通过 · 差错 0 笔</span>
}

const cellMoney = (c, dash) => (dash ? '—' : money(c))

/* 服务端的说明文字里用 **…** 标重点(派单、判责接口直接从代码注释取的)。
 * 原来是原样显示,页面上一排星号;这里转成加粗 */
const rich = text => String(text ?? '').split('**').map((part, i) => (i % 2 ? <b key={i}>{part}</b> : part))

function TodayTable({ today }) {
  const [all, setAll] = useState(false)
  const items = today?.items ?? []
  const rows = all ? items : items.slice(0, 12)
  return (
    <>
      <div className="sz-table-wrap">
        <div className="sz-table-scroll">
          <table className={`sz-table tp-today ${items.length ? '' : 'empty'}`}>
            <thead>
              <tr><th className="c-t">时间</th><th>频道 · 单号指纹</th><th className="r c-m">用户付</th><th className="r c-m">商家</th><th className="r c-m">骑手</th><th className="r c-p">平台</th></tr>
            </thead>
            <tbody>
              {rows.map((r, i) => (
                <tr key={`${r.id}-${i}`}>
                  <td className="num t">{r.t}</td>
                  <td className="ch">
                    <span className="sz-dot" style={{ background: CH_COLOR[r.ch] || '#9A968C' }} />
                    {r.label}<span className="mono id">{r.id}</span>
                  </td>
                  <td className="num r">{money(r.paid)}</td>
                  <td className="num r earn">{cellMoney(r.merchant, r.merchant === 0 && String(r.ch).startsWith('errand'))}</td>
                  <td className="num r earn">{cellMoney(r.rider, r.rider === 0)}</td>
                  <td className="num r hold" title={r.platform < 0 ? '平台补贴:这一单平台倒贴了钱' : undefined}>{money(r.platform)}</td>
                </tr>
              ))}
              {today && items.length === 0 && (
                <tr><td colSpan={6} className="tp-empty">今天还没有成交。第一笔成交后会出现在这里，页面每分钟刷新一次。</td></tr>
              )}
              {!today && (
                <tr><td colSpan={6} className="tp-empty">读取中…</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
      {items.length > 12 && (
        <button type="button" className="h3-btn ghost sm tp-more" onClick={() => setAll(a => !a)}>
          {all ? '收起' : `显示今天全部 ${items.length} 笔`}
        </button>
      )}
      {today && today.count > items.length && (
        <p className="tp-note">页面上只列最近 {items.length} 笔，今天全部 {today.count} 笔在 CSV 里。</p>
      )}
    </>
  )
}

function Fingerprint({ nodes, stats }) {
  const day = nodes?.latest_anchor?.day ?? stats?.chain?.latest_day
  const hash = nodes?.latest_anchor?.chain_hash ?? stats?.chain?.latest_hash
  const yesterday = bjDay(1)
  return (
    <div className="sz-card tp-side sz-enter">
      <div className="body">
        <div className="sz-cap">最新账本指纹{day ? ` · ${mdOf(day)}` : ''}</div>
        {hash
          ? <div className="mono tp-hash">{hash.match(/.{1,4}/g).join(' ')}</div>
          : <div className="tp-hash muted">{nodes || stats ? '还没有生成过锚点' : '读取中…'}</div>}
        {day && day < yesterday && (
          <p className="tp-warn">{mdOf(yesterday)}的锚点还没有生成。</p>
        )}
        <p className="muted tp-side-p">每天零点过后，为前一天的全部账目生成锚点，和再前一天的首尾相链；改动任何一分钱，这串就会变样。任何人都能用开源仓里的见证脚本复算。<a className="lnk" href="/nodes">自己复算 →</a></p>
      </div>
    </div>
  )
}

function Witnesses({ nodes }) {
  const day = nodes?.latest_anchor?.day
  const done = (nodes?.nodes ?? []).filter(n => day && n.verified_day === day && n.ok)
  const shown = done.slice(0, 5)
  const today = bjDay(0)
  const when = iso => {
    const p = bjParts(iso)
    if (!p) return ''
    return p.day === today ? p.hm : `${p.day.slice(5)} ${p.hm}`
  }
  return (
    <div className="sz-card tp-side sz-enter" style={{ '--i': 1 }}>
      <div className="body">
        <div className="sz-cap tp-wit-cap">
          {done.length ? `见证节点 · ${done.length} 个已复算到 ${mdOf(day)}` : '见证节点'}
        </div>
        {shown.map((n, i) => (
          <div key={`${n.name}-${i}`} className="tp-wit">
            <span className={`sz-led ${n.online ? '' : 'off'}`} title={n.online ? '在线' : '离线'} />
            <span className="nm">{n.name}</span>
            <span className="num at">{when(n.last_seen)}</span>
          </div>
        ))}
        {nodes && done.length === 0 && (
          <p className="muted tp-side-p">{day ? `暂时没有节点复算到 ${mdOf(day)} 的锚点。` : '暂时没有节点在复算。'}谁都可以跑一个见证节点，把每天的账抄走、自己算一遍。</p>
        )}
        {!nodes && <p className="muted tp-side-p">读取中…</p>}
        {nodes?.divergent > 0 && (
          <p className="tp-warn bad">另有 {nodes.divergent} 个节点报告复算结果和我们的对不上，<a href="/nodes">看是哪一天 →</a></p>
        )}
        <a className="lnk tp-wit-more" href="/nodes">{done.length > shown.length ? `全部 ${done.length} 个节点 · ` : ''}运行一个见证节点 →</a>
      </div>
    </div>
  )
}

function TodayBlock({ audit }) {
  const today = useJson('/transparency/today', 60000)
  const nodes = useJson('/nodes/summary', 60000)
  const stats = useJson('/stats/overview')
  const t = today?.totals
  const paid = t?.paid ?? 0
  const platPct = t && paid > 0 ? `${((t.platform / paid) * 100).toFixed(1)}%` : null
  const streak = audit?.clean_streak_days
  return (
    <header className="tp-today-block">
      <div className="tp-eyebrow">
        <span>透明中心 · {today?.day ?? bjDay(0)}</span>
        <AuditPill audit={audit} />
      </div>
      <h1 className="sz-h1">{kw('今天的每一分钱，去了哪。')}</h1>

      <div className="tp-bigs">
        <Big value={today ? today.count : null} fmt={v => v.toLocaleString()} label="今日订单" hint="今天还没有成交" />
        <Big value={t ? t.merchant : null} fmt={bigMoney} tone="earn" label="商家实收" />
        <Big value={t ? t.rider : null} fmt={bigMoney} tone="earn" label="骑手所得 · 配送费 + 小费" />
        <Big value={t ? t.platform : null} fmt={bigMoney} tone="hold"
          label={t && t.platform < 0 ? '平台留存（补贴后为负）' : `平台留存${platPct ? ` · ${platPct}` : ''}`} />
      </div>
      <SplitBar className="tp-todaybar" label={t ? `商家 ${money(t.merchant)}，骑手 ${money(t.rider)}，平台 ${money(t.platform)}` : '今天的分账'}
        segments={[
          { key: 'm', value: t?.merchant ?? 0, color: EARN },
          { key: 'r', value: t?.rider ?? 0, color: EARN, opacity: 0.5 },
          { key: 'p', value: Math.max(0, t?.platform ?? 0), color: HOLD },
        ]} />
      {today && paid === 0 && <p className="tp-note">今天还没有成交，第一单进来以后，这条按商家、骑手、平台三份的金额分段。</p>}

      <div className="sz-cols tp-today-cols">
        <div>
          <div className="tp-list-head">
            <h2 className="sz-h2">今日逐单</h2>
            <span className="muted">脱敏后全部公开{today ? ` · ${today.count} 单` : ''}</span>
            <a className="h3-btn ghost sm" href="/transparency/today.csv">下载 CSV</a>
          </div>
          <TodayTable today={today} />
        </div>
        <div className="tp-side-col">
          <Fingerprint nodes={nodes} stats={stats} />
          <Witnesses nodes={nodes} />
          <p className="tp-streak">
            {streak > 0 && <>连续 <b className="num">{streak}</b> 天核账零差错 · </>}
            {audit?.latest && streak === 0 && <><a className="bad" href="#audit">最近一次核账发现 {audit.latest.problems} 笔差错，见核账日历</a> · </>}
            <a className="lnk" href="/opensource#changes">规则变更留痕 →</a>
          </p>
        </div>
      </div>
    </header>
  )
}

/* ================= 原有各栏 ================= */

/* 90 天核账格子:绿 = 当日核账差错 0,红 = 有差错,灰 = 未运行。日期按北京时间 */
function AuditDays({ runs }) {
  const byDay = Object.fromEntries((runs ?? []).map(r => [r.day, r]))
  const days = []
  for (let i = 89; i >= 0; i--) {
    const key = bjDay(i)
    const run = byDay[key]
    days.push(
      <span key={key}
        className={`d ${run ? (run.problems > 0 ? 'bad' : '') : 'blank'}`}
        title={run
          ? `${key} 核账 ${run.checked_orders} 笔，差错 ${run.problems}`
          : `${key} 未运行`} />,
    )
  }
  return <div className="tp-days">{days}</div>
}

/* 90 天可用率格子:绿 ≥99.9% / 琥珀 ≥99% / 红 <99% / 灰 = 无探针记录 */
function UptimeDays({ days }) {
  const byDay = Object.fromEntries((days ?? []).map(d => [d.day, d]))
  const cells = []
  for (let i = 89; i >= 0; i--) {
    const key = bjDay(i)
    const d = byDay[key]
    const cls = !d ? 'blank'
      : d.availability >= 0.999 ? '' : d.availability >= 0.99 ? 'warn' : 'bad'
    cells.push(<span key={key} className={`d ${cls}`}
      title={d ? `${key} 可用率 ${(d.availability * 100).toFixed(2)}%` : `${key} 无记录`} />)
  }
  return <div className="tp-days">{cells}</div>
}

/** 账本纪元公告:每一次「链被重新起头」都在这里说清楚。
 *
 * 从 /ledger/epochs 渲染,不是写死的文案 —— 写死的话下一次重置又得有人
 * 记得回来改这个文件,而「忘了公告」正是上一次留下 9000 次节点警报的原因。
 *
 * 这段话是给**怀疑我们的人**看的,所以不利的部分也要写出来:
 * 消失了哪几天、链尾哈希有没有留存。没留就直说没留 ——
 * 含糊过去只会让人更确信我们在藏东西。
 * **刻意不是红色**:它不是异常,是一条已经说明过的事实。
 */
function EpochNotice() {
  const list = useJson('/ledger/epochs')
  // 只公告"抹掉过历史"的纪元;链从头没断过的话没什么可说的
  const resets = (Array.isArray(list) ? list : []).filter(e => e.prev_first_day)
  if (!resets.length) return null
  return (
    <div className="tp-epoch">
      {resets.map(e => (
        <div key={e.epoch} className="tp-epoch-card">
          <h3>账本曾于此处重新起链（第 {e.epoch} 纪元）</h3>
          <p>{e.reason}</p>
          <div className="meta mono">
            消失的锚点：{e.prev_first_day} ~ {e.prev_last_day || '（新链起点前一天）'}
            <br />新链起点：{e.started_day || '—'}
            <br />{e.prev_tip_hash
              ? `上一条链的链尾哈希：${e.prev_tip_hash}`
              : '上一条链的链尾哈希没有保留——这是当时的疏漏，保存过旧锚点的人'
                + '无法与我们对账。此后的重置一律先冻结链尾再动手。'}
          </div>
        </div>
      ))}
    </div>
  )
}

const TOC = [
  ['audit', '核账日历'], ['funds', '钱去哪了'], ['fairness', '分账公平'], ['rider', '骑手收入'],
  ['compensation', '赔付记录'], ['reviews', '评价'], ['reports', '月度财报'], ['dispatch', '派单算法'],
  ['liability', '判责分摊'], ['governance', '治理公开'], ['miniapps', '小程序'], ['community', '社区'], ['support', '客服'], ['status', '系统状态'],
  ['changelog', '最近更新'],
]

/* 一栏:小字眉题 + 衬线 h2 + 内容。h2 写在每一栏里而不是当参数传进来 ——
 * scripts/gen_font_subset.py 按 <h2>…</h2> 里的字切衬线子集,参数它扫不到 */
function Sec({ id, eyebrow, children }) {
  return (
    <section className="tp-sec" id={id}>
      {eyebrow && <div className="sec">{eyebrow}</div>}
      {children}
    </section>
  )
}

/* 社区栏(#371):视频审核、对人和群的处置、管理员查看私聊的次数(S8)、推荐公式。
 * 数据来自 /transparency/community,只有类型、原因代码、时长、申诉结果和计数 ——
 * 谁被处罚、群名、消息内容接口里根本没有(服务端取数就不读那些列)。 */
const TARGET_TYPE = { user: '账号', chat: '群 / 频道', video: '视频' }
const hrs = h => (h == null ? '–' : h < 1 ? `${Math.round(h * 60)} 分钟` : `${h.toFixed(1)} 小时`)

function CommunitySection({ c }) {
  const r30 = c?.video_review?.last_30d
  const views = c?.admin_chat_views
  return (
    <Sec id="community" eyebrow="社区">
      <h2>消息和视频怎么管，处置和查看都公示</h2>
      <p className="tp-lede">
        视频先审后发；对账号、群和频道的每一次处罚都带原因代码，当事人能申诉一次，由另一名审核员复核，申诉成立立即解除。平台技术上能读到消息（服务端存储，不做端到端加密），所以把规矩写死：管理员只能在处理举报时查看举报单里的那几条和前后各 5 条，不带举报单一律拒绝，每次查看都留痕，次数按月公示在这里。
      </p>
      <div className="tp-cards four">
        <div className="tp-card">
          <div className="num v">{r30 ? r30.reviewed : '–'}</div>
          <div className="k">近 30 天审核的稿件{r30 ? `：通过 ${r30.approved}、驳回 ${r30.rejected}` : ''}</div>
        </div>
        <div className="tp-card">
          <div className="num v">{r30 && r30.reject_rate != null ? `${(r30.reject_rate * 100).toFixed(1)}%` : '–'}</div>
          <div className="k">{r30 && r30.reviewed === 0 ? '近 30 天还没有审核结论' : '近 30 天驳回率'}</div>
        </div>
        <div className="tp-card">
          <div className="num v">{r30 ? hrs(r30.median_review_hours) : '–'}</div>
          <div className="k">审核时长中位数（提交到结论，含转码）</div>
        </div>
        <div className="tp-card hold">
          <div className="num v">{views ? views.last_30d : '–'}<small> 次</small></div>
          <div className="k">近 30 天管理员查看被举报的消息</div>
          {views && <div className="m">累计 {views.total} 次</div>}
        </div>
      </div>

      {(c?.video_review?.monthly?.length ?? 0) > 0 && (
        <div className="sz-table-wrap">
          <div className="sz-table-scroll">
            <table className="sz-table tp-wide">
              <thead><tr><th>月份</th><th className="r">审核</th><th className="r">通过</th><th className="r">驳回</th>
                <th className="r">驳回率</th><th className="r">审核时长中位数</th></tr></thead>
              <tbody>
                {c.video_review.monthly.map(m => (
                  <tr key={m.month}>
                    <td className="num">{m.month}</td><td className="num r">{m.reviewed}</td>
                    <td className="num r">{m.approved}</td><td className="num r">{m.rejected}</td>
                    <td className="num r">{m.reject_rate == null ? '–' : `${(m.reject_rate * 100).toFixed(1)}%`}</td>
                    <td className="num r">{hrs(m.median_review_hours)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      <h3 className="tp-sub">处置记录</h3>
      <p className="tp-lede">
        删消息、禁言、封群 / 频道、封号、警告和视频下架逐条列出：处置了什么、多久、因为什么（原因代码）、申诉结果。
        {c ? `近 30 天共 ${c.sanctions.last_30d.total} 次：` : ''}
        {c && c.sanctions.last_30d.by_action.filter(a => a.count > 0).map(a => `${a.label} ${a.count}`).join('、')}
        {c && c.sanctions.last_30d.total === 0 ? '没有处置。' : '。'}
        近 30 天申诉 {c ? c.appeals.last_30d.filed : '–'} 次，维持 {c ? c.appeals.last_30d.upheld : '–'}、撤销 {c ? c.appeals.last_30d.overturned : '–'}。
      </p>
      {(c?.sanctions?.records?.length ?? 0) > 0 ? (
        <div className="sz-table-wrap">
          <div className="sz-table-scroll">
            <table className="sz-table tp-wide">
              <thead><tr><th>日期</th><th>对象</th><th>处置</th><th>原因</th><th>申诉</th></tr></thead>
              <tbody>
                {c.sanctions.records.slice(0, 50).map((x, i) => (
                  <tr key={i}>
                    <td className="num nowrap">{x.date}</td>
                    <td className="nowrap">{TARGET_TYPE[x.target_type] ?? x.target_type}</td>
                    <td className="nowrap">{x.action_label}{x.duration && <span className="tp-reason">{x.duration}</span>}
                      {x.revoked && <span className="tp-reason">已撤销</span>}</td>
                    <td>{x.reason_code}<span className="tp-reason">{x.reason_label}</span></td>
                    <td className="nowrap">{x.appeal ? x.appeal_label : '未申诉'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ) : <p className="tp-note">{c ? '还没有处置记录。' : '读取中…'}</p>}

      <h3 className="tp-sub">管理员查看私聊，按月</h3>
      <p className="tp-lede">{views?.rule ?? '管理员只能在处理举报时查看举报单里的那几条和前后各 5 条。'}</p>
      {(views?.monthly?.length ?? 0) > 0 ? (
        <div className="tp-log">
          {views.monthly.map(m => (
            <div className="row" key={m.month}>
              <span className="sz-tag plain">{m.month}</span>
              <span className="msg">查看被举报的消息 <b className="num">{m.views}</b> 次</span>
            </div>
          ))}
        </div>
      ) : <p className="tp-note">{c ? '还没有管理员查看过。' : '读取中…'}</p>}

      <h3 className="tp-sub">推荐和热门怎么排</h3>
      <p className="tp-lede">
        推荐、热门、排行榜、竖屏流是同一段公开的纯函数（<a href={c?.formula?.source_url ?? 'https://github.com/hanpaopao66/chaojizan/blob/main/server/app/services/video_rank.py'}>services/video_rank.py</a>），输入只有公开的互动计数、发布时间、关注关系和常看分区；没有付费、商家、运营加权。个性化推荐可以在 App 里一键关掉，关掉之后和没登录的人看到的完全一样。
      </p>
      {c?.formula?.text && (
        <div className="tp-formula" style={{ whiteSpace: 'pre', fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace', fontSize: 13 }}>
          {c.formula.text}
        </div>
      )}
      {c?.not_public && <p className="tp-note">不公开：{c.not_public.join('、')}。</p>}
    </Sec>
  )
}

export default function TransparencyPage() {
  const audit = useJson('/transparency/audit')
  const funds = useJson('/transparency/funds')
  const comp = useJson('/transparency/compensation')
  const fair = useJson('/transparency/fairness')
  const reports = useJson('/transparency/reports')
  // 状态区自动刷新(与服务端 60s 缓存节奏对齐),其余区块一次性加载
  const uptime = useJson('/transparency/uptime', 60000)
  const changelog = useJson('/transparency/changelog')
  const gov = useJson('/transparency/governance')
  const dispatch = useJson('/transparency/dispatch')
  const liability = useJson('/transparency/liability')
  const mini = useJson('/transparency/miniapps')
  const comm = useJson('/transparency/community')
  // /status 直达系统状态区。上面各栏的数据是陆续到的,每到一份页面就变长一截,
  // 只在 uptime 到的那一刻滚一次的话,后到的栏目会把状态区往下顶。所以每到一份
  // 就重新对齐一次 —— 直到用户自己动了滚轮 / 手指 / 键盘为止
  const userMoved = useRef(false)
  useEffect(() => {
    const stop = () => { userMoved.current = true }
    const evs = ['wheel', 'touchstart', 'keydown']
    evs.forEach(e => window.addEventListener(e, stop, { passive: true }))
    return () => evs.forEach(e => window.removeEventListener(e, stop))
  }, [])
  useEffect(() => {
    if (!location.pathname.replace(/^\/site/, '').startsWith('/status') || userMoved.current) return undefined
    const t = setTimeout(() => {
      if (!userMoved.current) document.getElementById('status')?.scrollIntoView({ behavior: 'auto' })
    }, 60)
    return () => clearTimeout(t)
  }, [uptime, audit, funds, comp, fair, reports, changelog, gov, dispatch, liability, mini, comm])

  const latest = audit?.latest
  const per = fair?.per100
  const rate = fair?.commission

  return (
    <SitePage active="ledger" title="超级赞 · 透明中心:今天的每一分钱去了哪" note="本页数据与公开账本同源">
      <div className="sz-page tp">
        <TodayBlock audit={audit} />

        <nav className="tp-toc" aria-label="透明中心各栏">
          {TOC.map(([id, label]) => <a key={id} href={`#${id}`}>{label}</a>)}
        </nav>

        <EpochNotice />

        <Sec id="audit" eyebrow="核账公示">
          <h2>每天 04:00，把近 30 天的账核一遍</h2>
          <div className="tp-film"><AuditLampFilm /></div>
          <div className="tp-audit-line">
            {/* 差错数**有值时必须是红的**。这里原来两个数都吃同一个绿色 ——
                于是有差错的那天,页面用一个让人安心的绿色写着「差错 10 笔」。
                这是整页唯一一个不能看起来令人安心的数字。 */}
            {latest
              ? <>最近一次核账（{mdOf(latest.day)}）核对 <b className="num">{latest.checked_orders.toLocaleString()}</b> 笔，差错 <b className={`num ${latest.problems > 0 ? 'bad' : 'earn'}`}>{latest.problems}</b> 笔</>
              : (audit ? '还没有核账记录' : '核账数据读取中…')}
          </div>
          {audit?.clean_streak_days > 0 &&
            <div className="tp-audit-streak">已连续 {audit.clean_streak_days} 天差错为 0</div>}
          <p className="tp-lede">
            系统每天 04:00 自动核对近 {audit?.window_days ?? 30} 天每一笔账：商家入账 = 菜钱 − 佣金、骑手入账 = 配送费（100% 归骑手）、退款汇总 = 逐笔流水之和。差一分钱都会在这里亮红灯——绿格子是干净的一天，灰格子是那天没跑成、没有结论。
          </p>
          <AuditDays runs={audit?.runs} />
          <div className="tp-legend"><span><i className="ok" />零差错</span><span><i className="bad" />有差错</span><span><i className="blank" />没跑成</span><span className="muted">每格一天，最右是今天</span></div>
        </Sec>

        <Sec id="funds" eyebrow="钱去哪了">
          <h2>平台赚的钱，去哪了</h2>
          <p className="tp-lede">
            收入只有两笔：外卖佣金（≤5%）和团购核销服务费（2%）。支出全是回到用户和商家身上的钱。剩下的要养支付通道、服务器、短信、地图和客服——细账见月度财报。数据与<a href="/ledger/anchors">公开账本锚点</a>同源，可用见证节点复算。
          </p>
          <div className="tp-funds">
            <div className="col">
              <h4>收入（累计）</h4>
              <div className="row"><span>外卖佣金（对账本求和，冲账自动抵扣）</span>
                <span className="num">{yuanF(funds?.income.commission_cents)}</span></div>
              <div className="row"><span>团购核销服务费（2%，核销才收）</span>
                <span className="num">{yuanF(funds?.income.voucher_fee_cents)}</span></div>
              <div className="row total"><span>合计</span>
                <span className="num">{yuanF(funds?.income.total_cents)}</span></div>
            </div>
            <div className="col">
              <h4>支出去向（累计）</h4>
              <div className="row"><span>用户补贴（首单立减 + 超时安抚券抵扣）</span>
                <span className="num">{yuanF(funds?.spend.subsidy_cents)}</span></div>
              <div className="row"><span>商家餐损赔付（无人接单，平台背锅）</span>
                <span className="num">{yuanF(funds?.spend.meal_compensation_cents)}</span></div>
              <div className="row"><span>申诉改判调整（误伤的账，平台认亏）</span>
                <span className="num">{yuanF(funds?.spend.adjustment_cents)}</span></div>
              <div className="row total"><span>合计</span>
                <span className="num">{yuanF(funds?.spend.total_cents)}</span></div>
            </div>
            <div className="tp-retained">
              留存 <b className="num">{yuanF(funds?.retained_cents)}</b>——用来付“电费”（支付通道 / 服务器 / 短信 / 地图 / 审核客服），盈余不分红：降费率、补骑手、扶小店。
            </div>
          </div>
        </Sec>

        <Sec id="fairness" eyebrow="分账公平">
          <h2>每 100 元订单，分给了谁</h2>
          <p className="tp-lede">
            近 {fair?.window_days ?? 30} 天正常履约且无退款的完成订单，按公开账本实算（不是示意图）。商家 + 骑手 + 平台佣金 − 平台补贴 = 100，恒等式由每日核账背书。
          </p>
          {per ? (
            <>
              <SplitBar className="tp-per100" height={14} label={`商家 ${per.merchant}，骑手 ${per.rider}，平台佣金 ${per.commission}`}
                segments={[
                  { key: 'm', value: per.merchant, color: EARN },
                  { key: 'r', value: per.rider, color: EARN, opacity: 0.5 },
                  { key: 'p', value: per.commission, color: HOLD },
                ]} />
              <div className="tp-split-legend">
                <span><i style={{ background: EARN }} />商家实收 <b className="num">¥{per.merchant}</b></span>
                <span><i style={{ background: EARN, opacity: 0.5 }} />骑手所得 <b className="num">¥{per.rider}</b>（配送费 + 小费，一分不截留）</span>
                <span><i style={{ background: HOLD }} />平台佣金 <b className="num">¥{per.commission}</b></span>
                <span className="muted">另：平台倒贴补贴 ¥{per.subsidy}</span>
              </div>
              <p className="tp-note">四项各自四舍五入到角，合计可能有 ±0.1 的取整尾差。</p>
            </>
          ) : <p className="tp-note">{fair ? '近 30 天还没有可以算的完成订单。' : '读取中…'}</p>}

          <h3 className="tp-sub">5% 是上限，不是实收</h3>
          <p className="tp-lede">
            阶梯佣金按商家上月单量自动降档（500 单 4.5%、1000 单 4%），只降不升，所以全平台实际平均佣金率一直低于承诺上限——这是算出来的，不是说出来的。
          </p>
          <div className="tp-rate">
            <div>
              <div className="num now">{pct(rate?.real_rate_30d)}</div>
              <div className="cap">近 30 天实际平均佣金率 · 承诺上限 <b className="num">{pct(rate?.promised_cap)}</b></div>
            </div>
            <div className="tp-tiers">
              {(rate?.tiers ?? []).map(t => {
                const max = Math.max(...rate.tiers.map(x => x.merchants), 1)
                return (
                  <div className="t" key={t.rate}>
                    <span className="num r">{(t.rate * 100).toFixed(1)}%</span>
                    <div className="bar" style={{ width: `${(t.merchants / max) * 70}%` }} />
                    <span>{t.merchants} 家</span>
                  </div>
                )
              })}
            </div>
          </div>
        </Sec>

        <Sec id="rider" eyebrow="骑手收入">
          <h2>骑手的钱，一分不截留</h2>
          <div className="tp-cards">
            <div className="tp-card earn">
              <div className="num v">{yuanF(fair?.rider_income.total_cents)}</div>
              <div className="k">骑手累计所得（配送费 + 小费，100% 归骑手）</div>
              <div className="m">今日 {yuanF(fair?.rider_income.today_cents)}</div>
            </div>
            <div className="tp-card">
              <div className="num v">{fair?.rider_income.today_avg_per_order_cents != null
                ? `¥${(fair.rider_income.today_avg_per_order_cents / 100).toFixed(2)}`
                : '–'}</div>
              <div className="k">今日平均每单实得{fair && fair.rider_income.today_avg_per_order_cents == null ? '（今天还没有完成的配送单）' : ''}</div>
            </div>
            <div className="tp-card hold">
              <div className="num v">{yuanF(fair?.rider_income.zero_fee_saved_cents)}</div>
              <div className="k">提现零手续费，累计为骑手商家省下（按行业约 0.1% 通道费保守估算）</div>
              <div className="m">累计提现 {yuanF(fair?.rider_income.withdrawn_total_cents)}</div>
            </div>
          </div>
        </Sec>

        <Sec id="compensation" eyebrow="赔付记录">
          <h2>平台的赔钱记录</h2>
          <p className="tp-lede">
            没有平台愿意亮自己的赔付账，我们把它当承诺兑现的凭据：超时了就赔、运力不足取消了就替商家兜餐损、该退的钱一分不少。
          </p>
          <div className="tp-cards">
            <div className="tp-card hold">
              <div className="num v">{comp?.eta_coupons.total.count ?? '–'}<small> 张</small></div>
              <div className="k">超时安抚券（送达超 ETA 15 分钟自动发，平台承担）</div>
              <div className="m">累计 {yuanF(comp?.eta_coupons.total.cents)} · 本月 {comp?.eta_coupons.month.count ?? '–'} 张</div>
            </div>
            <div className="tp-card">
              <div className="num v">{yuanF(comp?.meal_compensation.total.cents)}</div>
              <div className="k">商家餐损赔付（无人接单取消，已出餐按应收全额赔，佣金不收）</div>
              <div className="m">累计 {comp?.meal_compensation.total.count ?? '–'} 笔 · 本月 {comp?.meal_compensation.month.count ?? '–'} 笔</div>
            </div>
            <div className="tp-card">
              <div className="num v">{yuanF(comp?.refunds.total.cents)}</div>
              <div className="k">退款（缺货部分退 / 整单退 / 售后退，渠道确认成功口径）</div>
              <div className="m">累计 {comp?.refunds.total.count ?? '–'} 笔 · 本月 {comp?.refunds.month.count ?? '–'} 笔</div>
            </div>
          </div>
        </Sec>

        <Sec id="reviews" eyebrow="评价">
          <h2>评价平台不删，被隐藏的也报出来</h2>
          <p className="tp-lede">
            这里原来只写「一条不藏」，而店铺页其实会滤掉被隐藏的评价——于是「删了一成」和「一条没删」在这份公示上长得一模一样。证据按不可能证伪的方式算，那就不是证据。现在隐藏数一起摆出来。
          </p>
          <div className="tp-cards four">
            <div className="tp-card">
              <div className="num v">{fair?.reviews.visible?.toLocaleString() ?? '–'}</div>
              <div className="k">店铺页实际可见，共 {fair?.reviews.total?.toLocaleString() ?? '–'} 条</div>
            </div>
            <div className="tp-card">
              <div className="num v">{fair?.reviews.bad_ratio != null
                ? `${(fair.reviews.bad_ratio * 100).toFixed(1)}%` : '–'}</div>
              <div className="k">差评占比（≤2 星）——好看不好看，都摆在这</div>
            </div>
            <div className="tp-card hold">
              <div className="num v">{fair?.reviews.hidden ?? '–'}<small> 条</small></div>
              <div className="k">
                被隐藏{fair?.reviews.hidden_ratio != null
                  ? `（${(fair.reviews.hidden_ratio * 100).toFixed(1)}%）` : ''}
                ——只有商家申诉成立这一条路
              </div>
            </div>
            <div className="tp-card hold">
              <div className="num v">{fair?.reviews.flagged_still_visible ?? '–'}<small> 条</small></div>
              <div className="k">刷评嫌疑标记待复核——只标记，不隐藏不删除</div>
            </div>
          </div>
          {fair?.reviews.hidden_rule && <p className="tp-note">{fair.reviews.hidden_rule}</p>}
          {fair?.reviews.hidden_recourse && <p className="tp-note">{fair.reviews.hidden_recourse}</p>}
        </Sec>

        <Sec id="reports" eyebrow="月度财报">
          <h2>月度财报（收入侧实时）</h2>
          <p className="tp-lede">
            {reports?.note ?? '收入侧自动聚合；成本侧（服务器 / 短信 / 推送账单）随开源仓发布。'}
          </p>
          {(reports?.months?.length ?? 0) > 0 ? (
            <div className="sz-table-wrap">
              <div className="sz-table-scroll">
                <table className="sz-table tp-wide">
                  <thead><tr>
                    <th>月份</th><th className="r">完成订单</th><th className="r">交易额</th><th className="r">外卖佣金</th>
                    <th className="r">骑手所得</th><th className="r">平台补贴</th><th className="r">团购服务费</th>
                  </tr></thead>
                  <tbody>
                    {reports.months.map(m => (
                      <tr key={m.month}>
                        <td className="num">{m.month}</td>
                        <td className="num r">{m.orders_completed.toLocaleString()}</td>
                        <td className="num r">{yuanF(m.gmv_cents)}</td>
                        <td className="num r hold">{yuanF(m.commission_cents)}</td>
                        <td className="num r earn">{yuanF(m.rider_income_cents)}</td>
                        <td className="num r">{yuanF(m.subsidy_cents)}</td>
                        <td className="num r hold">{yuanF(m.voucher_fee_cents)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          ) : <p className="tp-note">{reports ? '还没有完成的月份。' : '读取中…'}</p>}
        </Sec>

        <Sec id="dispatch" eyebrow="派单算法">
          <h2>骑手抢单怎么排的，公式全公开</h2>
          <p className="tp-lede">
            派单算法对骑手的意义，等同于账目对商家的意义——它决定骑手今天挣多少。别家的算法是黑箱，骑手只能猜“为什么好单不给我”。下面这些数字就是代码里正在跑的那几个：接口从排序代码的常量直接读，不是另写一份说明，改了会立刻反映在这里。
          </p>
          <div className="tp-film"><DispatchOpenFilm /></div>
          {dispatch ? (
            <>
              <div className="tp-formula">{dispatch.formula}</div>
              <div className="sz-table-wrap">
                <div className="sz-table-scroll">
                  <table className="sz-table tp-wide">
                    <thead><tr><th>项</th><th>权重</th><th>上限</th><th>为什么是这个数</th></tr></thead>
                    <tbody>
                      {dispatch.weights.map(w => (
                        <tr key={w.key}>
                          <td className="nowrap">{w.name}</td>
                          <td className="nowrap">{w.value}</td>
                          <td className="nowrap">{w.cap || '—'}</td>
                          <td className="tp-why">{rich(w.why)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
              <h3 className="tp-sub">「顺路」是怎么算的</h3>
              <code className="tp-code">{dispatch.same_way_definition.formula}</code>
              <p className="tp-note">{rich(dispatch.same_way_definition.why)}</p>
              <h3 className="tp-sub">平台承诺不做的事</h3>
              <ul className="tp-never">
                {dispatch.never_do.map((n, i) => <li key={i}>{rich(n)}</li>)}
              </ul>
              <h3 className="tp-sub">算法改过什么</h3>
              <p className="tp-note">算法可以改，但不会悄悄改——悄悄改就等于从没公开过。</p>
              <div className="tp-log">
                {dispatch.changelog.map((e, i) => (
                  <div className="row" key={i}>
                    <span className="sz-tag plain">调整</span>
                    <span className="msg">{rich(e.what)}<span className="tp-reason">（原因：{rich(e.why)}）</span></span>
                    <span className="num date">{e.date}</span>
                  </div>
                ))}
              </div>
            </>
          ) : <p className="tp-note">读取中…</p>}
        </Sec>

        <Sec id="liability" eyebrow="判责分摊">
          <h2>一单出了问题，钱怎么分</h2>
          <p className="tp-lede">
            原则一句话：<b>谁的问题，谁负责；平台不出补贴。</b>
            这是三方都会被它扣钱的规则——用户想取消、商家做了餐、骑手跑了路，一单出岔子总有人要承担。别家把它写在几十页协议里、实际由客服临场判，同一种情况两个人问出两个答案。下面这张表是代码里正在跑的那一套：接口从分摊函数真的跑一遍取结果，不是另写一份说明。
          </p>
          {liability ? (
            <>
              <h3 className="tp-sub">分界线是「成本发生的时刻」，不是客服的判断</h3>
              <p className="tp-note">
                订单每往前走一步，就有一笔成本真实发生且不可回收。判据是平台看得见的事实（订单状态、骑手有没有到店），所以同一种情况永远是同一个答案。
              </p>
              <div className="sz-table-wrap">
                <div className="sz-table-scroll">
                  <table className="sz-table tp-wide">
                    <thead><tr><th>取消发生在</th><th>此时已经发生的成本</th><th>钱怎么分</th></tr></thead>
                    <tbody>
                      {liability.stages.map(st => (
                        <tr key={st.stage}>
                          <td className="nowrap">{st.label}</td>
                          <td className="tp-why">{rich(st.cost_incurred)}</td>
                          <td className="tp-why">
                            {st.rules.map((r, i) => (
                              <div key={i}>
                                {r.name} → <b>{liability.to_labels[r.to]}</b>
                                {r.to === 'platform' && <>（0 元）</>}
                              </div>
                            ))}
                            {st.food_to && <div className="tp-reason">{rich(st.food_to)}</div>}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>

              <h3 className="tp-sub">平台自己承担的部分，和「补贴」不是一回事</h3>
              <p className="tp-lede">{liability.what_platform_bears.rule}。
                {rich(liability.what_platform_bears.why_not_subsidy)}</p>
              <ul className="tp-never">
                {liability.what_platform_bears.examples.map((e, i) => <li key={i}>{rich(e)}</li>)}
              </ul>

              <h3 className="tp-sub">有一条例外，而且写明了边界</h3>
              <p className="tp-lede">
                {rich(liability.the_one_exception.case)}——{rich(liability.the_one_exception.why)}
              </p>
              <p className="tp-note">{rich(liability.the_one_exception.scope)}</p>

              <h3 className="tp-sub">
                骑手白跑一趟拿多少：配送费的 {Math.round(liability.idle_trip_share.value * 100)}%
              </h3>
              <p className="tp-note">{rich(liability.idle_trip_share.why)}</p>

              <h3 className="tp-sub">平台承诺不做的事</h3>
              <ul className="tp-never">
                {liability.promises.map((n, i) => <li key={i}>{rich(n)}</li>)}
              </ul>

              <h3 className="tp-sub">判错了怎么办</h3>
              <p className="tp-lede">
                {liability.appeal.who}，{liability.appeal.window_hours} 小时内提出。
                {rich(liability.appeal.what_happens)}
              </p>
              <p className="tp-note">
                自动判责必须配一个能找人的口子，否则「谁的问题」就成了系统单方面说了算。
              </p>
            </>
          ) : <p className="tp-note">读取中…</p>}
        </Sec>

        <Sec id="governance" eyebrow="治理公开">
          <h2>平台开关怎么改的，都留痕</h2>
          <p className="tp-lede">
            对用户有感知的平台开关（天气加价、停运、深夜保护……）每次变更都记录在案：何时、改成什么、为什么。三端规则条文的改动另记在<a href="/opensource#changes">开源仓 · 规则变更留痕</a>。
            {gov?.flags_since
              ? <>自 {gov.flags_since} 起记录，不补历史——没记录的就说没记录。</>
              : <>留痕表刚上线，第一次变更后这里就会有记录。</>}
          </p>
          {(gov?.flag_timeline?.length ?? 0) > 0 ? (
            <div className="tp-log">
              {gov.flag_timeline.slice(0, 12).map((f, i) => (
                <div className="row" key={i}>
                  <span className={`sz-tag ${f.new === 'on' ? 'ok' : f.new === 'off' ? 'plain' : 'info'}`}>{f.new === 'on' ? '开启' : f.new === 'off' ? '关闭' : '调整'}</span>
                  <span className="msg">{f.label}
                    {f.key === 'open_cities' && f.new && <>：{f.new}</>}
                    {f.reason && <span className="tp-reason">（原因：{f.reason}）</span>}
                  </span>
                  <span className="num date">{bjParts(f.at)?.day ?? f.at.slice(0, 10)}</span>
                </div>
              ))}
            </div>
          ) : <p className="tp-note">{gov ? '暂无变更记录。' : '读取中…'}</p>}

          <h3 className="tp-sub">反作弊处置，只有计数没有个案</h3>
          <p className="tp-lede">
            处置分级克制：限制只暂停领券补贴（下单照常）、冻结待人工复核、误伤申诉即解除；刷评只标记待复核，绝不静默删除。这里按月公示处置量——接受监督。
          </p>
          {(gov?.risk_monthly?.length ?? 0) > 0 ? (
            <div className="sz-table-wrap">
              <div className="sz-table-scroll">
                <table className="sz-table tp-wide">
                  <thead><tr>
                    <th>月份</th><th className="r">限制（领券补贴）</th><th className="r">冻结（待复核）</th>
                    <th className="r">解除 / 恢复</th><th className="r">刷评标记（仍公开可见）</th>
                  </tr></thead>
                  <tbody>
                    {gov.risk_monthly.map(m => (
                      <tr key={m.month}>
                        <td className="num">{m.month}</td><td className="num r">{m.limited}</td><td className="num r">{m.frozen}</td>
                        <td className="num r">{m.lifted}</td><td className="num r">{m.reviews_flagged}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          ) : <p className="tp-note">处置留痕自上线起记录，暂无记录。</p>}
        </Sec>

        <Sec id="miniapps" eyebrow="小程序">
          <h2>小程序怎么审、下架了谁，都公示</h2>
          <p className="tp-lede">
            小程序由第三方开发者提交，平台审核、托管。目录不卖位置：精选在前（人工挑选，理由写在下面），其余按首次上架时间从新到旧——排序是一段公开的纯函数（<a href="https://github.com/hanpaopao66/chaojizan/blob/main/server/app/services/miniapp_catalog.py">services/miniapp_catalog.py</a>），打开次数、评分、付费都不进这个函数。审核不承诺时限，时长的中位数照实写在这里。平台规则见<a href="/developers/rules">开发者规则</a>，全部小程序见<a href="/miniapps">公开目录</a>。
          </p>
          <div className="tp-cards four">
            <div className="tp-card">
              <div className="num v">{mini?.verified_developers ?? '–'}</div>
              <div className="k">已认证开发者（个人实名或企业认证）</div>
            </div>
            <div className="tp-card">
              <div className="num v">{mini ? mini.online_apps.app + mini.online_apps.game : '–'}</div>
              <div className="k">在线{mini ? `：${mini.online_apps.app} 个应用、${mini.online_apps.game} 个小游戏` : ''}</div>
            </div>
            <div className="tp-card">
              <div className="num v">{mini?.month.submitted ?? '–'}</div>
              <div className="k">{mini ? `${mini.month.label} 提交审核，通过 ${mini.month.approved}、驳回 ${mini.month.rejected}` : '本月提交审核'}</div>
              {mini && <div className="m">此刻审核中 {mini.reviewing_now} 个版本</div>}
            </div>
            <div className="tp-card">
              <div className="num v">{mini?.month.median_review_hours ?? '–'}<small> 小时</small></div>
              <div className="k">{mini && mini.month.median_review_hours == null ? '本月还没有审核结论' : '本月审核时长中位数（提交到结论）'}</div>
            </div>
          </div>
          {mini && Object.keys(mini.month.reject_by_category || {}).length > 0 && (
            <p className="tp-note">本月驳回按原因类别：{Object.entries(mini.month.reject_by_category).map(([k, n]) => `${k} ${n} 个`).join('、')}。原因代码逐条解释见<a href="/developers/review#原因代码">审核规范</a>。</p>
          )}

          <h3 className="tp-sub">下架记录</h3>
          <p className="tp-lede">平台作出的暂停、移除、紧急隔离逐条列出（开发者自己下架不算处罚，不列）。每条都有原因代码；开发者 7 天内可以申诉一次，由另一名审核员复核。</p>
          {(mini?.takedowns?.length ?? 0) > 0 ? (
            <div className="sz-table-wrap">
              <div className="sz-table-scroll">
                <table className="sz-table tp-wide">
                  <thead><tr><th>日期</th><th>应用</th><th>处置</th><th>原因</th><th>申诉</th></tr></thead>
                  <tbody>
                    {mini.takedowns.slice(0, 30).map((t, i) => (
                      <tr key={i}>
                        <td className="num nowrap">{t.date}</td>
                        <td>{t.app_name}</td>
                        <td className="nowrap">{t.action}</td>
                        <td>{t.reason_category}<span className="tp-reason">{t.reason_code}{t.reason_label ? ` ${t.reason_label}` : ''}</span></td>
                        <td className="nowrap">{t.appealed ? `已申诉 · ${t.appeal_result ?? '处理中'}` : '未申诉'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          ) : <p className="tp-note">{mini ? '还没有下架记录。' : '读取中…'}</p>}

          <h3 className="tp-sub">精选名单</h3>
          <p className="tp-lede">精选是人工挑的，位置有限，排在目录最前面。每次进出都写理由，记在下面。</p>
          {(mini?.curation?.length ?? 0) > 0 ? (
            <div className="tp-log">
              {mini.curation.map(c => (
                <div className="row" key={c.appid}>
                  <span className="sz-tag warn">第 {c.position} 位</span>
                  <span className="msg"><a className="lnk" href={`/m/${c.appid}`}>{c.name}</a>{c.reason && <span className="tp-reason">（理由：{c.reason}）</span>}</span>
                </div>
              ))}
            </div>
          ) : <p className="tp-note">{mini ? '目前没有精选。' : '读取中…'}</p>}
          {(mini?.curation_changes?.length ?? 0) > 0 && (
            <div className="tp-log">
              {mini.curation_changes.slice(0, 12).map((c, i) => (
                <div className="row" key={i}>
                  <span className={`sz-tag ${c.action === '进入精选' ? 'ok' : 'plain'}`}>{c.action}</span>
                  <span className="msg">{c.app_name}{c.reason && <span className="tp-reason">（理由：{c.reason}）</span>}</span>
                  <span className="num date">{c.date}</span>
                </div>
              ))}
            </div>
          )}
          {mini?.not_public && <p className="tp-note">不公开：{mini.not_public.join('、')}。</p>}
        </Sec>

        <CommunitySection c={comm} />

        <Sec id="support" eyebrow="客服">
          <h2>客服回得快不快</h2>
          <div className="tp-cards">
            <div className="tp-card earn">
              <div className="num v">{gov?.tickets_monthly?.[0]?.avg_first_reply_minutes != null
                ? `${gov.tickets_monthly[0].avg_first_reply_minutes}`
                : '–'}<small> 分钟</small></div>
              <div className="k">本月工单平均首次响应（{gov?.tickets_monthly?.[0]?.tickets ?? 0} 单）</div>
            </div>
            <div className="tp-card">
              <div className="num v">{gov?.tickets_monthly?.[0]?.replied_24h_ratio != null
                ? `${(gov.tickets_monthly[0].replied_24h_ratio * 100).toFixed(0)}%` : '–'}</div>
              <div className="k">24 小时内回复率</div>
            </div>
            <div className="tp-card hold">
              <div className="num v">{gov?.self_service_30d?.ratio != null
                ? `${(gov.self_service_30d.ratio * 100).toFixed(0)}%` : '–'}</div>
              <div className="k">问题自助解决占比（近 30 天：自助售后 {gov?.self_service_30d?.after_sales ?? 0} vs 人工工单 {gov?.self_service_30d?.tickets ?? 0}）</div>
            </div>
          </div>

          {(gov?.announcements?.length ?? 0) > 0 && (
            <>
              <h3 className="tp-sub">公告归档</h3>
              <p className="tp-note">发过的全体公告全部留档（含已过期），不悄悄撤回。</p>
              <div className="tp-log">
                {gov.announcements.slice(0, 10).map((a, i) => (
                  <div className="row" key={i}>
                    <span className={`sz-tag ${a.active ? 'ok' : 'plain'}`}>{a.active ? '生效中' : '已归档'}</span>
                    <span className="msg"><b>{a.title}</b> {a.content}</span>
                    <span className="num date">{a.created_at.slice(0, 10)}</span>
                  </div>
                ))}
              </div>
            </>
          )}
        </Sec>

        <Sec id="status" eyebrow="可用率">
          <h2>系统状态</h2>
          <p className="tp-lede">
            后台每 {uptime?.probe_interval_minutes ?? 5} 分钟自记一次数据库与缓存健康，下方格子按<b>天</b>汇总（90 天 · 每格一天）。缺一次探针就按不可用计——可用率只会算低，不会虚高。{uptime?.note && <>（{uptime.note}）</>}
          </p>
          <div className="tp-status-now">
            {uptime && (uptime.current.ok
              ? <span className="earn"><span className="sz-led" /> 全部服务正常</span>
              : <span className="bad"><span className="sz-led bad" /> 服务异常：
                  {!uptime.current.db && ' 数据库'}{!uptime.current.redis && ' 缓存'}</span>)}
            {uptime?.today && uptime.today.probes > 0 && (
              <span className="muted tp-today-probes">
                今日已记录 {uptime.today.probes} 次探针
                {uptime.today.ok === uptime.today.probes
                  ? '，全部正常' : `，异常 ${uptime.today.probes - uptime.today.ok} 次`}
                {uptime.today.last_at && <> · 最近 {uptime.today.last_at}</>}
              </span>
            )}
          </div>
          <UptimeDays days={uptime?.days} />
          <div className="tp-legend"><span><i className="ok" />≥ 99.9%</span><span><i className="warn" />≥ 99%</span><span><i className="bad" />{'< 99%'}</span><span><i className="blank" />无记录</span></div>
        </Sec>

        <Sec id="changelog" eyebrow="发版与提交">
          <h2>最近更新</h2>
          <p className="tp-lede">
            与 GitHub 仓库同源：平台刚刚改了什么，一字不差。线上运行版本 <b className="num">{changelog?.version?.version ?? '…'}</b>
            {changelog?.version?.deployed_at &&
              <> · 部署于 {changelog.version.deployed_at.slice(0, 10)}</>}
            ，与仓库 tag 对得上号——代码即承诺。
            {changelog?.stale && <>（GitHub 暂不可达，展示缓存）</>}
          </p>
          {(changelog?.releases?.length ?? 0) > 0 && (
            <div className="tp-log">
              {changelog.releases.slice(0, 6).map(r => (
                <div className="row" key={r.tag}>
                  <span className="sz-tag info mono">{r.tag}</span>
                  <span className="msg">{r.name}</span>
                  <span className="num date">{(r.published_at ?? '').slice(0, 10)}</span>
                </div>
              ))}
            </div>
          )}
          {(changelog?.commits?.length ?? 0) > 0 && (
            <div className="tp-log">
              {changelog.commits.slice(0, 8).map(c => (
                <div className="row" key={c.sha}>
                  <span className="mono tp-sha">{c.sha}</span>
                  <span className="msg">{c.message}</span>
                  <span className="num date">{(c.date ?? '').slice(0, 10)}</span>
                </div>
              ))}
            </div>
          )}
          {changelog && !changelog.releases?.length && !changelog.commits?.length && (
            <p className="tp-note">更新记录暂不可达，可直接访问
              <a href={`https://github.com/${changelog?.repo ?? 'hanpaopao66/chaojizan'}`}> GitHub 仓库</a>。</p>
          )}
        </Sec>

        <div className="tp-footer-links">
          <a className="h3-btn ghost" href="/screen">全国运营大屏</a>
          <a className="h3-btn ghost" href="/nodes">运行见证节点，自己复算</a>
          <a className="h3-btn ghost" href="/ledger/anchors">账本锚点原文</a>
          <a className="h3-btn ghost" href="https://github.com/hanpaopao66/chaojizan">GitHub 源码</a>
        </div>
      </div>
    </SitePage>
  )
}
