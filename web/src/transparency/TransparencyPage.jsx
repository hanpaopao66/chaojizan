import React, { useEffect, useState } from 'react'

import { BrandIcon } from '../BrandSvg.jsx'
import './transparency.css'

/* 透明中心(/transparency):核账公示 / 佣金去向 / 赔付记录 / 分账公平 / 月度财报。
   所有数字来自公开接口,口径注释随数字展示——透明的透明。 */

function useFetch(url) {
  const [data, setData] = useState(null)
  useEffect(() => {
    let alive = true
    fetch(url).then(r => (r.ok ? r.json() : null))
      .then(d => alive && setData(d)).catch(() => {})
    return () => { alive = false }
  }, [url])
  return data
}

const yuan = c => (c == null ? '–'
  : (c / 100).toLocaleString('zh-CN', { maximumFractionDigits: 0 }))
const yuanF = c => (c == null ? '–' : `¥${yuan(c)}`)
const pct = r => (r == null ? '–' : `${(r * 100).toFixed(2)}%`)

/* 90 天核账格子:绿=当日核账差错 0,红=有差错,灰=未运行 */
function AuditDays({ runs }) {
  const byDay = Object.fromEntries((runs ?? []).map(r => [r.day, r]))
  const days = []
  const today = new Date()
  for (let i = 89; i >= 0; i--) {
    const d = new Date(today.getTime() - i * 86400e3)
    const key = d.toISOString().slice(0, 10)
    const run = byDay[key]
    days.push(
      <span key={key}
        className={`d ${run ? (run.problems > 0 ? 'bad' : '') : 'blank'}`}
        title={run
          ? `${key} 核账 ${run.checked_orders} 笔,差错 ${run.problems}`
          : `${key} 未运行`} />,
    )
  }
  return <div className="tp-days">{days}</div>
}

const SPLIT_COLORS = {
  merchant: '#1FA878', rider: '#3E8EE0', commission: '#F04E12',
}

/* 90 天可用率格子:绿 ≥99.9% / 琥珀 ≥99% / 红 <99% / 灰 = 无探针记录 */
function UptimeDays({ days }) {
  const byDay = Object.fromEntries((days ?? []).map(d => [d.day, d]))
  const cells = []
  const today = new Date()
  for (let i = 89; i >= 0; i--) {
    const key = new Date(today.getTime() - i * 86400e3).toISOString().slice(0, 10)
    const d = byDay[key]
    const cls = !d ? 'blank'
      : d.availability >= 0.999 ? '' : d.availability >= 0.99 ? 'warn' : 'bad'
    cells.push(<span key={key} className={`d ${cls}`}
      title={d ? `${key} 可用率 ${(d.availability * 100).toFixed(2)}%` : `${key} 无记录`} />)
  }
  return <div className="tp-days">{cells}</div>
}

export default function TransparencyPage() {
  useEffect(() => { document.title = '超级赞 · 透明中心' }, [])
  const audit = useFetch('/transparency/audit')
  const funds = useFetch('/transparency/funds')
  const comp = useFetch('/transparency/compensation')
  const fair = useFetch('/transparency/fairness')
  const reports = useFetch('/transparency/reports')
  const uptime = useFetch('/transparency/uptime')
  const changelog = useFetch('/transparency/changelog')
  const gov = useFetch('/transparency/governance')
  useEffect(() => {   // /status 直达系统状态区
    if (location.pathname.replace(/^\/site/, '').startsWith('/status')) {
      setTimeout(() => document.getElementById('status')
        ?.scrollIntoView({ behavior: 'instant' }), 100)
    }
  }, [uptime])

  const latest = audit?.latest
  const per = fair?.per100
  const rate = fair?.commission

  return (
    <>
      <nav className="topnav">
        <a className="brand-link" href="/"><BrandIcon size={34} /> 超级赞</a>
        <div className="links">
          <a href="#audit">核账公示</a>
          <a href="#funds">钱去哪了</a>
          <a href="#fairness">分账公平</a>
          <a href="#compensation">赔付记录</a>
          <a href="#reports">月度财报</a>
          <a href="#governance">治理公开</a>
          <a href="#status">系统状态</a>
          <a href="#changelog">最近更新</a>
        </div>
        <a className="dl" href="/screen">运营大屏</a>
      </nav>

      <div className="tp-page">
        <header className="tp-hero" id="audit">
          <div className="eyebrow">透 明 中 心</div>
          <div className="big">
            {latest
              ? <>昨日核账 <b>{latest.checked_orders.toLocaleString()}</b> 笔,
                  差错 <b>{latest.problems}</b> 笔</>
              : '核账数据加载中…'}
          </div>
          {audit?.clean_streak_days > 0 &&
            <div className="streak">已连续 {audit.clean_streak_days} 天差错为 0</div>}
          <p className="sub">
            系统每天凌晨自动核对近 {audit?.window_days ?? 30} 天每一笔账:
            商家入账 = 菜钱 − 佣金、骑手入账 = 配送费(100% 归骑手)、
            退款汇总 = 逐笔流水之和。差一分钱都会在这里亮红灯——绿格子是干净的一天。
          </p>
          <AuditDays runs={audit?.runs} />
        </header>

        <h2 id="funds">平台赚的钱,<b>去哪了</b></h2>
        <p className="tp-lede">
          收入只有两笔:外卖佣金(≤5%)和团购核销服务费(2%)。支出全是回到用户和商家
          身上的钱。剩下的要养支付通道、服务器、短信、地图和客服——细账见月度财报。
          数据与<a href="/ledger/anchors"> 公开账本锚点 </a>同源,可用见证节点复算。
        </p>
        <div className="tp-funds">
          <div className="col">
            <h4>收入(累计)</h4>
            <div className="row"><span>外卖佣金(对账本求和,冲账自动抵扣)</span>
              <span className="amt">{yuanF(funds?.income.commission_cents)}</span></div>
            <div className="row"><span>团购核销服务费(2%,核销才收)</span>
              <span className="amt">{yuanF(funds?.income.voucher_fee_cents)}</span></div>
            <div className="row total"><span><b>合计</b></span>
              <span className="amt">{yuanF(funds?.income.total_cents)}</span></div>
          </div>
          <div className="col">
            <h4>支出去向(累计)</h4>
            <div className="row"><span>用户补贴(首单立减 + 超时安抚券抵扣)</span>
              <span className="amt">{yuanF(funds?.spend.subsidy_cents)}</span></div>
            <div className="row"><span>商家餐损赔付(无人接单,平台背锅)</span>
              <span className="amt">{yuanF(funds?.spend.meal_compensation_cents)}</span></div>
            <div className="row"><span>申诉改判调整(误伤的账,平台认亏)</span>
              <span className="amt">{yuanF(funds?.spend.adjustment_cents)}</span></div>
            <div className="row total"><span><b>合计</b></span>
              <span className="amt">{yuanF(funds?.spend.total_cents)}</span></div>
          </div>
          <div className="tp-retained">
            留存 <b>{yuanF(funds?.retained_cents)}</b> —— 用来付"电费"
            (支付通道/服务器/短信/地图/审核客服),盈余不分红:降费率、补骑手、扶小店。
          </div>
        </div>

        <h2 id="fairness">每 100 元订单,<b>分给了谁</b></h2>
        <p className="tp-lede">
          近 {fair?.window_days ?? 30} 天正常履约且无退款的完成订单,按公开账本实算
          (不是示意图)。商家 + 骑手 + 平台佣金 − 平台补贴 = 100,恒等式由每日核账背书。
        </p>
        {per && (
          <>
            <div className="tp-split">
              <div className="seg" style={{
                width: `${per.merchant}%`, background: SPLIT_COLORS.merchant }}>
                商家 ¥{per.merchant}
              </div>
              <div className="seg" style={{
                width: `${per.rider}%`, background: SPLIT_COLORS.rider }}>
                骑手 ¥{per.rider}
              </div>
              <div className="seg" style={{
                width: `${per.commission}%`, background: SPLIT_COLORS.commission }}>
                {per.commission}
              </div>
            </div>
            <div className="tp-split-legend">
              <span><i style={{ background: SPLIT_COLORS.merchant }} />商家实收 ¥{per.merchant}</span>
              <span><i style={{ background: SPLIT_COLORS.rider }} />骑手所得 ¥{per.rider}(配送费+小费,一分不截留)</span>
              <span><i style={{ background: SPLIT_COLORS.commission }} />平台佣金 ¥{per.commission}</span>
              <span>另:平台倒贴补贴 ¥{per.subsidy}</span>
            </div>
            <p className="tp-note">四项各自四舍五入到角,合计可能有 ±0.1 的取整尾差。</p>
          </>
        )}

        <h2>5% 是上限,<b>不是实收</b></h2>
        <p className="tp-lede">
          阶梯佣金按商家上月单量自动降档(500 单 4.5%、1000 单 4%),
          所以全平台实际平均佣金率一直低于承诺上限——这是算出来的,不是说出来的。
        </p>
        <div className="tp-rate">
          <div>
            <div className="now">{pct(rate?.real_rate_30d)}</div>
            <div className="cap">近 30 天实际平均佣金率 · 承诺上限 <b>{pct(rate?.promised_cap)}</b></div>
          </div>
          <div className="tp-tiers">
            {(rate?.tiers ?? []).map(t => {
              const max = Math.max(...rate.tiers.map(x => x.merchants), 1)
              return (
                <div className="t" key={t.rate}>
                  <span style={{ width: 44 }}>{(t.rate * 100).toFixed(1)}%</span>
                  <div className="bar" style={{ width: `${(t.merchants / max) * 100}%`, maxWidth: '70%' }} />
                  <span>{t.merchants} 家</span>
                </div>
              )
            })}
          </div>
        </div>

        <h2>骑手的钱,<b>一分不截留</b></h2>
        <div className="tp-cards">
          <div className="tp-card green">
            <div className="v">{yuanF(fair?.rider_income.total_cents)}</div>
            <div className="k">骑手累计所得(配送费 + 小费,100% 归骑手)</div>
            <div className="m">今日 {yuanF(fair?.rider_income.today_cents)}</div>
          </div>
          <div className="tp-card">
            <div className="v">{fair?.rider_income.today_avg_per_order_cents != null
              ? `¥${(fair.rider_income.today_avg_per_order_cents / 100).toFixed(2)}`
              : '–'}</div>
            <div className="k">今日平均每单实得</div>
          </div>
          <div className="tp-card amber">
            <div className="v">{yuanF(fair?.rider_income.zero_fee_saved_cents)}</div>
            <div className="k">提现零手续费,累计为骑手商家省下
              (按行业约 0.1% 通道费保守估算)</div>
            <div className="m">累计提现 {yuanF(fair?.rider_income.withdrawn_total_cents)}</div>
          </div>
        </div>

        <h2 id="compensation">平台的<b>赔钱记录</b></h2>
        <p className="tp-lede">
          没有平台愿意亮自己的赔付账,我们把它当承诺兑现的凭据:
          超时了就赔、运力不足取消了就替商家兜餐损、该退的钱一分不少。
        </p>
        <div className="tp-cards">
          <div className="tp-card orange">
            <div className="v">{comp?.eta_coupons.total.count ?? '–'}<small> 张</small></div>
            <div className="k">超时安抚券(送达超 ETA 15 分钟自动发,平台承担)</div>
            <div className="m">累计 {yuanF(comp?.eta_coupons.total.cents)} ·
              本月 {comp?.eta_coupons.month.count ?? '–'} 张</div>
          </div>
          <div className="tp-card">
            <div className="v">{yuanF(comp?.meal_compensation.total.cents)}</div>
            <div className="k">商家餐损赔付(无人接单取消,已出餐按应收全额赔,佣金不收)</div>
            <div className="m">累计 {comp?.meal_compensation.total.count ?? '–'} 笔 ·
              本月 {comp?.meal_compensation.month.count ?? '–'} 笔</div>
          </div>
          <div className="tp-card">
            <div className="v">{yuanF(comp?.refunds.total.cents)}</div>
            <div className="k">退款(缺货部分退 / 整单退 / 售后退,渠道确认成功口径)</div>
            <div className="m">累计 {comp?.refunds.total.count ?? '–'} 笔 ·
              本月 {comp?.refunds.month.count ?? '–'} 笔</div>
          </div>
        </div>

        <h2>评价<b>不删</b></h2>
        <div className="tp-cards">
          <div className="tp-card">
            <div className="v">{fair?.reviews.total?.toLocaleString() ?? '–'}</div>
            <div className="k">全量评价,一条不藏</div>
          </div>
          <div className="tp-card">
            <div className="v">{fair?.reviews.bad_ratio != null
              ? `${(fair.reviews.bad_ratio * 100).toFixed(1)}%` : '–'}</div>
            <div className="k">差评占比(≤2 星)——好看不好看,都摆在这</div>
          </div>
          <div className="tp-card amber">
            <div className="v">{fair?.reviews.flagged_still_visible ?? '–'}<small> 条</small></div>
            <div className="k">刷评嫌疑标记待复核——只标记,不隐藏不删除</div>
          </div>
        </div>

        <h2 id="reports">月度财报<b>(收入侧实时)</b></h2>
        <p className="tp-lede">
          {reports?.note ?? '收入侧自动聚合;成本侧(服务器/短信/推送账单)随开源仓发布。'}
        </p>
        <div className="tp-table-wrap">
          <table className="tp-table">
            <thead><tr>
              <th>月份</th><th>完成订单</th><th>交易额</th><th>外卖佣金</th>
              <th>骑手所得</th><th>平台补贴</th><th>团购服务费</th>
            </tr></thead>
            <tbody>
              {(reports?.months ?? []).map(m => (
                <tr key={m.month}>
                  <td>{m.month}</td>
                  <td>{m.orders_completed.toLocaleString()}</td>
                  <td>{yuanF(m.gmv_cents)}</td>
                  <td>{yuanF(m.commission_cents)}</td>
                  <td>{yuanF(m.rider_income_cents)}</td>
                  <td>{yuanF(m.subsidy_cents)}</td>
                  <td>{yuanF(m.voucher_fee_cents)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <h2 id="governance">规则怎么改的,<b>都留痕</b></h2>
        <p className="tp-lede">
          对用户有感知的平台开关(天气加价、停运、深夜保护……)每次变更都记录在案:
          何时、改成什么、为什么。
          {gov?.flags_since
            ? <>自 {gov.flags_since} 起记录,不补历史——没记录的就说没记录。</>
            : <>留痕表刚上线,第一次变更后这里就会有记录。</>}
        </p>
        {(gov?.flag_timeline?.length ?? 0) > 0 ? (
          <div className="tp-log">
            {gov.flag_timeline.slice(0, 12).map((f, i) => (
              <div className="row" key={i}>
                <span className="tag">{f.new === 'on' ? '开启' : f.new === 'off' ? '关闭' : '调整'}</span>
                <span className="msg">{f.label}
                  {f.key === 'open_cities' && f.new && <>:{f.new}</>}
                  {f.reason && <span className="tp-reason">(原因:{f.reason})</span>}
                </span>
                <span className="date">{f.at.slice(0, 10)}</span>
              </div>
            ))}
          </div>
        ) : <p className="tp-note">暂无变更记录。</p>}

        <h2>反作弊处置,<b>只有计数没有个案</b></h2>
        <p className="tp-lede">
          处置分级克制:限制只暂停领券补贴(下单照常)、冻结待人工复核、误伤申诉即解除;
          刷评只标记待复核,绝不静默删除。这里按月公示处置量——接受监督。
        </p>
        {(gov?.risk_monthly?.length ?? 0) > 0 ? (
          <div className="tp-table-wrap">
            <table className="tp-table">
              <thead><tr>
                <th>月份</th><th>限制(领券补贴)</th><th>冻结(待复核)</th>
                <th>解除/恢复</th><th>刷评标记(仍公开可见)</th>
              </tr></thead>
              <tbody>
                {gov.risk_monthly.map(m => (
                  <tr key={m.month}>
                    <td>{m.month}</td><td>{m.limited}</td><td>{m.frozen}</td>
                    <td>{m.lifted}</td><td>{m.reviews_flagged}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : <p className="tp-note">处置留痕自上线起记录,暂无记录。</p>}

        <h2>客服<b>回得快不快</b></h2>
        <div className="tp-cards">
          <div className="tp-card green">
            <div className="v">{gov?.tickets_monthly?.[0]?.avg_first_reply_minutes != null
              ? `${gov.tickets_monthly[0].avg_first_reply_minutes}`
              : '–'}<small> 分钟</small></div>
            <div className="k">本月工单平均首次响应({gov?.tickets_monthly?.[0]?.tickets ?? 0} 单)</div>
          </div>
          <div className="tp-card">
            <div className="v">{gov?.tickets_monthly?.[0]?.replied_24h_ratio != null
              ? `${(gov.tickets_monthly[0].replied_24h_ratio * 100).toFixed(0)}%` : '–'}</div>
            <div className="k">24 小时内回复率</div>
          </div>
          <div className="tp-card amber">
            <div className="v">{gov?.self_service_30d?.ratio != null
              ? `${(gov.self_service_30d.ratio * 100).toFixed(0)}%` : '–'}</div>
            <div className="k">问题自助解决占比(近30天:自助售后
              {gov?.self_service_30d?.after_sales ?? 0} vs 人工工单
              {gov?.self_service_30d?.tickets ?? 0})</div>
          </div>
        </div>

        {(gov?.announcements?.length ?? 0) > 0 && (
          <>
            <h2>公告<b>归档</b></h2>
            <p className="tp-lede">发过的全体公告全部留档(含已过期),不悄悄撤回。</p>
            <div className="tp-log">
              {gov.announcements.slice(0, 10).map((a, i) => (
                <div className="row" key={i}>
                  <span className="tag">{a.active ? '生效中' : '已归档'}</span>
                  <span className="msg"><b>{a.title}</b> {a.content}</span>
                  <span className="date">{a.created_at.slice(0, 10)}</span>
                </div>
              ))}
            </div>
          </>
        )}

        <h2 id="status">系统<b>状态</b></h2>
        <p className="tp-lede">
          后台每 {uptime?.probe_interval_minutes ?? 5} 分钟自记一次数据库与缓存健康。
          缺一次探针就按不可用计——可用率只会算低,不会虚高。
          {uptime?.note && <>({uptime.note})</>}
        </p>
        <div className="tp-status-now">
          {uptime && (uptime.current.ok
            ? <span className="tp-ok">● 全部服务正常</span>
            : <span className="tp-bad">● 服务异常:
                {!uptime.current.db && ' 数据库'}{!uptime.current.redis && ' 缓存'}</span>)}
        </div>
        <UptimeDays days={uptime?.days} />

        <h2 id="changelog">最近<b>更新</b></h2>
        <p className="tp-lede">
          与 GitHub 仓库同源:平台刚刚改了什么,一字不差。
          线上运行版本 <b className="tp-ver">{changelog?.version?.version ?? '…'}</b>
          {changelog?.version?.deployed_at &&
            <> · 部署于 {changelog.version.deployed_at.slice(0, 10)}</>}
          ,与仓库 tag 对得上号——代码即承诺。
          {changelog?.stale && <>(GitHub 暂不可达,展示缓存)</>}
        </p>
        {(changelog?.releases?.length ?? 0) > 0 && (
          <div className="tp-log">
            {changelog.releases.slice(0, 6).map(r => (
              <div className="row" key={r.tag}>
                <span className="tag">{r.tag}</span>
                <span className="msg">{r.name}</span>
                <span className="date">{(r.published_at ?? '').slice(0, 10)}</span>
              </div>
            ))}
          </div>
        )}
        {(changelog?.commits?.length ?? 0) > 0 && (
          <div className="tp-log">
            {changelog.commits.slice(0, 8).map(c => (
              <div className="row" key={c.sha}>
                <span className="tag mono">{c.sha}</span>
                <span className="msg">{c.message}</span>
                <span className="date">{(c.date ?? '').slice(0, 10)}</span>
              </div>
            ))}
          </div>
        )}
        {!changelog?.releases?.length && !changelog?.commits?.length && (
          <p className="tp-note">更新记录暂不可达,可直接访问
            <a href={`https://github.com/${changelog?.repo ?? 'hanpaopao66/chaojizan'}`}> GitHub 仓库</a>。</p>
        )}

        <div className="tp-footer-links">
          <a className="btn ghost" href="/screen">全国运营大屏</a>
          <a className="btn ghost" href="/nodes">运行见证节点,自己复算</a>
          <a className="btn ghost" href="/ledger/anchors">账本锚点原文</a>
          <a className="btn ghost" href="https://github.com/hanpaopao66/chaojizan">GitHub 源码</a>
        </div>
      </div>
    </>
  )
}
