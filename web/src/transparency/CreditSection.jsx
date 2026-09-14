import React from 'react'

/* 透明中心 · 顾客信用分怎么算(#credit)。
 *
 * 数据来自 /transparency/credit —— 服务端直接读算分用的那几个常量
 * (server/app/services/customer_credit.py 的 public_spec),本人明细页、规则页用的也是它。
 * 这里**一个分值都不写死**:改了常量,这一栏跟着变;抄一份在这里,迟早和真实的算法对不上。
 *
 * 单独放一个文件,是为了不和透明中心别的栏目挤在一处改。 */

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

export default function CreditSection({ c }) {
  const levels = c?.levels ?? []
  return (
    <section className="tp-sec" id="credit">
      <div className="sec">信用分</div>
      <h2>顾客信用分怎么算，谁能看到</h2>
      <p className="tp-lede">
        顾客有一个信用分。它只算平台判定成立、而且当事人能申诉的事，每一分都指得出是哪一单、哪一条记录；取消、退款、售后、差评这些正常的权利一律不扣分。商家接单之后、骑手接到单之后才看得到分数和等级，看不到明细，也不能拿它拒单、排单、定价。下面的数就是服务端算分用的那几个常量，不是另写的一份说明。
      </p>
      {c ? (
        <>
          <div className="tp-formula">{c.formula}</div>
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
