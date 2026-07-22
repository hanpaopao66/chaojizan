import React from 'react'

import CityGrid from './CityGrid.jsx'
import Embers from './Embers.jsx'

/* 入驻/加入子页:转化导向,3D 只做点缀,重点是把账算给对方看。 */

function JoinShell({ hero, children }) {
  return (
    <>
      <header className="join-hero">
        {hero}
      </header>
      <main className="join-main">{children}</main>
      <footer>
        <div><a href="/">← 回超级赞首页</a></div>
        <div className="muted">数字与公开账本同源 · 有疑问请通过 App 内客服工单联系</div>
        <div className="muted">
          <a href="https://beian.miit.gov.cn" target="_blank" rel="noreferrer">陕ICP备2025064101号-2</a>
        </div>
      </footer>
    </>
  )
}

export function JoinMerchant() {
  return (
    <JoinShell hero={
      <>
        <Embers />
        <div className="hero-inner">
          <div className="brand">超级赞 · 商家入驻</div>
          <h1>同一碗面,<br />多挣四块五。</h1>
          <p className="lede">
            一碗 ¥30 的面:高抽成平台拿走 ¥6 以上,超级赞只收 ¥1.50。
            差出来的钱,是你的面粉、房租和利润。
          </p>
          <div className="cta">
            <a className="btn primary" href="/download">下载商家端,开始入驻</a>
            <a className="btn ghost" href="/screen">看平台实时账目</a>
          </div>
        </div>
      </>
    }>
      <section className="reveal visible compare">
        <h2>把账摊开算</h2>
        <div className="cmp-table">
          <div className="cmp-row head"><div>一碗 ¥30 的面</div><div>高抽成平台</div><div className="hl">超级赞</div></div>
          <div className="cmp-row"><div>平台佣金</div><div>¥6.00+(20%+)</div><div className="hl">¥1.50(5%)</div></div>
          <div className="cmp-row"><div>你的实收</div><div>¥24 上下</div><div className="hl">¥28.50</div></div>
          <div className="cmp-row"><div>月售 600 单</div><div>—</div><div className="hl">多挣约 ¥2,700/月</div></div>
        </div>
        <p className="fineprint">佣金基数为菜品+打包费−你设置的满减(你让利,平台跟着少收);
          数字可在商家端对账页逐单核对,也可在公开账本复算。</p>
      </section>
      <section className="reveal visible">
        <h2>没有隐形的刀</h2>
        <div className="cards3">
          <div className="bcard"><h3>不竞价排名</h3><p>排序只看距离、评分、销量。不存在"买流量",老店新店同一条起跑线。</p></div>
          <div className="bcard"><h3>当日对账,一分不差</h3><p>每一单实收、佣金、到账,对账页逐单可查,月度 CSV 一键导出。</p></div>
          <div className="bcard"><h3>你让利,我少收</h3><p>你设满减、搞折扣,平台按折后实收计佣——不做"商家打折平台照抽"的事。</p></div>
        </div>
      </section>
      <section className="reveal visible">
        <h2>超级赞对商家的承诺</h2>
        <ul className="promise-list">
          <li>✅ 佣金只抽 5%,写进开源代码,全网可查</li>
          <li>✅ 入驻免费,证照齐全即可(需食品经营许可证)</li>
          <li>✅ 每日自动对账:净额 = 流水 − 5% 佣金,逐单明细一分不差</li>
          <li>✅ 新订单实时响铃,接单 / 出餐 / 估清一部手机搞定</li>
          <li>✅ 拒单、退款、售后,规则透明,不吃暗亏</li>
        </ul>
        <p className="fineprint">我们不承诺大流量——我们承诺不吸血。多一个渠道,多一条活路。</p>
      </section>
    </JoinShell>
  )
}

export function JoinRider() {
  return (
    <JoinShell hero={
      <>
        <div className="grid-bg"><CityGrid /></div>
        <div className="hero-inner">
          <div className="brand">超级赞 · 骑手加入</div>
          <h1>你跑的每一米,<br />都算你的。</h1>
          <p className="lede">
            用户付的配送费,100% 进你的钱包。平台不抽成、提现零手续费,
            每一笔收入逐单可查——这不是口号,是写进公开账本的规则。
          </p>
          <div className="cta">
            <a className="btn primary" href="/download">下载骑手端,开始接单</a>
            <a className="btn ghost" href="/nodes">不信?看看谁在监督我们</a>
          </div>
        </div>
      </>
    }>
      <section className="reveal visible">
        <h2>规则先说清</h2>
        <div className="cards3">
          <div className="bcard"><h3>配送费全归你</h3><p>按距离明码计价,用户付多少你收多少。公开账本里"骑手行只进不冲"是任何人都能验证的恒等式。</p></div>
          <div className="bcard"><h3>提现零手续费</h3><p>钱包余额随时提,平台一分不扣。到账进度在 App 里全程可见。</p></div>
          <div className="bcard"><h3>不玩派单惩罚</h3><p>抢单自愿、超时豁免规则公开。恶劣天气不强派,你的安全比时效值钱。</p></div>
        </div>
      </section>
    </JoinShell>
  )
}
