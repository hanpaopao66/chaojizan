import React, { useState } from 'react'

/* 透明中心 · 信用分怎么算(#credit)。顾客、商家、骑手三种角色,同一套机制。
 *
 * 数据来自 /transparency/credit?role= —— 服务端直接读算分用的那几个常量
 * (server/app/services/credit.py 的 public_spec),本人明细页、规则页用的也是它。
 * 这里**一个分值都不写死**:改了常量,这一栏跟着变;抄一份在这里,迟早和真实的算法对不上。
 *
 * 三种角色的公式、窗口、等级、申诉规矩一模一样(服务端单测钉着),所以那些只说一遍;
 * 按角色不同的只有「什么算扣分」「什么不扣分」「谁看得到」「不用来做什么」,用那排按钮切。
 *
 * 单独放一个文件,是为了不和透明中心别的栏目挤在一处改。 */

const ROLES = [['customer', '顾客'], ['merchant', '商家'], ['rider', '骑手']]

const rich = text => String(text ?? '').split('**').map((part, i) => (i % 2 ? <b key={i}>{part}</b> : part))

const days = d => (d == null ? '—' : `${d} 天`)
const signed = p => (p > 0 ? `+${p}` : `${p}`.replace('-', '−'))

function Rows({ c }) {
  const plus = c.plus ?? []
  const minus = c.minus ?? []
  const rows = [
    ...plus.map(p => ({ key: p.key, name: p.label, each: signed(p.points), cap: `最多 +${p.cap}`, win: p.window_days, what: p.counts, extra: p.not_counted?.length ? `不算:${p.not_counted.join('、')}` : '' })),
    ...minus.flatMap(m => (m.items?.length
      ? m.items.map(it => ({ key: `${m.key}-${it.kind}`, name: `${m.label}:${it.label}`, each: signed(it.points), cap: '不设上限', win: m.window_days, what: `平台规则的处置目录里定为「${it.severity_label}」`, extra: m.appeal ? `申诉:${m.appeal}` : '' }))
      : [{ key: m.key, name: m.label, each: signed(m.points), cap: '不设上限', win: m.window_days, what: m.counts, extra: m.appeal ? `申诉:${m.appeal}` : '' }])),
  ]
  return (
    <div className="sz-table-wrap">
      <div className="sz-table-scroll">
        <table className="sz-table tp-wide">
          <thead><tr><th>项</th><th>每次</th><th>上限</th><th>看多久</th><th>什么算</th></tr></thead>
          <tbody>
            {rows.map(r => (
              <tr key={r.key}>
                <td>{r.name}</td>
                <td className="num nowrap">{r.each}</td>
                <td className="nowrap">{r.cap}</td>
                <td className="nowrap">{days(r.win)}</td>
                <td className="tp-why">{rich(r.what)}{r.extra && <span className="tp-reason">({r.extra})</span>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

/** specs:{customer, merchant, rider},各是一份 /transparency/credit?role= 的响应;还没到的是 null */
export default function CreditSection({ specs }) {
  const [role, setRole] = useState('customer')
  const c = specs?.[role]
  const levels = c?.levels ?? []
  return (
    <section className="tp-sec" id="credit">
      <div className="sec">信用分</div>
      <h2>信用分怎么算，谁能看到</h2>
      <p className="tp-lede">
        顾客、商家、骑手都有一个信用分，用的是同一套算法。它只算平台判定成立、而且当事人能申诉的事，每一分都指得出是哪一单、哪一条记录；取消、退款、拒单、转单、差评、慢这些一律不扣分。只有这一单的交易对方、而且在接单之后，才看得到分数和等级，看不到明细；店铺页、搜索、抢单大厅里都没有它，也不能拿它派单、排序、定价、处置。下面的数就是服务端算分用的那几个常量，不是另写的一份说明。
      </p>
      <div className="tp-seg" role="group" aria-label="看哪一种角色的信用分">
        {ROLES.map(([k, label]) => (
          <button key={k} type="button" className={role === k ? 'on' : undefined}
            aria-pressed={role === k} onClick={() => setRole(k)}>{label}</button>
        ))}
      </div>
      {c ? (
        <>
          <div className="tp-formula">{c.formula}</div>
          {/* 起算日:之前的裁决不扣分。老服务端没有这个字段 */}
          {c.count_from_why && <p className="tp-note">{rich(c.count_from_why)}。</p>}
          <p className="tp-note">{rich(c.base_why)}</p>
          <Rows c={c} />
          {c.minus_cap && <p className="tp-note">{c.minus_cap}。</p>}

          <h3 className="tp-sub">等级</h3>
          <p className="tp-lede">
            {levels.map((lv, i) => (i === 0 ? `${lv.label} ≥ ${lv.min}` : `${lv.label} ${lv.min}–${levels[i - 1].min - 1}`)).join(' · ')}。{c.level_rule}。
          </p>

          <h3 className="tp-sub">不扣分的事</h3>
          <ul className="tp-never">
            {(c.not_counted ?? []).map((n, i) => <li key={i}><b>{n.what}</b>：{rich(n.why)}</li>)}
          </ul>

          <h3 className="tp-sub">谁能看到</h3>
          <div className="sz-table-wrap">
            <div className="sz-table-scroll">
              <table className="sz-table tp-wide">
                <thead><tr><th>谁</th><th>看得到什么</th></tr></thead>
                <tbody>
                  {(c.visibility ?? []).map(v => (
                    <tr key={v.who}><td className="nowrap">{v.who}</td><td className="tp-why">{rich(v.what)}</td></tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          <h3 className="tp-sub">不用来做的事</h3>
          <ul className="tp-never">
            {(c.never_used_for ?? []).map((n, i) => <li key={i}>{rich(n)}</li>)}
          </ul>

          <h3 className="tp-sub">判错了怎么办</h3>
          <p className="tp-lede">{rich(c.appeal?.summary)}。{rich(c.appeal?.once)}。</p>
          {c.refresh && <p className="tp-note">{c.refresh}。</p>}
        </>
      ) : <p className="tp-note">读取中…</p>}
    </section>
  )
}
