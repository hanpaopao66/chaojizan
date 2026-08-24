import React from 'react'

/* 一单钱的去向。
 *
 * ## 这里原来是一段 3D 滚动动画
 *
 * 一个 260svh 高的滚动区,里面一个 three.js 画布,金币随滚动分成三堆。
 * 它和背景火星、3D 地球一起,把 three.js 拖进首屏主包 —— gzip 282 KB,
 * 而人在微信里点开这个链接,要等这 282 KB 下完才看得到第一行字。
 *
 * 换成一条按比例分段的横条:**同样的数字,一眼看完,零 KB**。
 * 而且它比动画更容易懂 —— 动画要滚三屏才看得到结论,
 * 横条是"谁拿走多少"直接摆在那儿,这正是这一节要回答的问题。
 *
 * 宽度就是真实比例(28.5 : 5 : 1.5),不是示意 ——
 * 一张比例失真的图,比没有图更糟。
 */

const FOOD = 3000          // 一份 ¥30 的餐(分)
const DELIVERY = 500       // 配送费 ¥5(分)
const RATE = 0.05          // 佣金 5%

const COMMISSION = Math.round(FOOD * RATE)      // 150
const MERCHANT = FOOD - COMMISSION              // 2850
const TOTAL = FOOD + DELIVERY                   // 3500

// 整数不带小数:「¥30 的面」比「¥30.00 的面」像人话,
// 而 28.50 / 1.50 该保留的两位一位不少
const yuan = c => (c / 100).toFixed(2).replace(/\.00$/, '')

const PARTS = [
  { key: 'merchant', cents: MERCHANT, who: '商家',
    how: `餐费 ¥${yuan(FOOD)} 减 5% 佣金` },
  { key: 'rider', cents: DELIVERY, who: '骑手',
    how: '配送费,一分不少' },
  { key: 'platform', cents: COMMISSION, who: '平台',
    how: '只有这 5%' },
]

export default function CoinFlow() {
  return (
    <section className="coinflow" id="coinflow" aria-label="一单钱的去向">
      <h2>三十五块钱,去了哪里</h2>
      {/* ⚠️ 中文标点后面**不能断行**:JSX 会把换行加缩进压成一个空格,
          渲染出来就是「配送费, 你一共付」——中间凭空多一个空格。
          英文里那是正常词距,中文里是排版错误 */}
      <p className="section-lede">
        {`一份 ¥${yuan(FOOD)} 的餐,加 ¥${yuan(DELIVERY)} 配送费,`}
        {`你一共付 ¥${yuan(TOTAL)}。这笔钱是这样分的:`}
      </p>

      {/* 条的宽度就是钱的比例。看一眼就知道谁拿走了大头 */}
      <div className="cf-bar" role="img"
        aria-label={PARTS.map(p => `${p.who} ${yuan(p.cents)} 元`).join(',')}>
        {PARTS.map(p => (
          <div key={p.key} className={`cf-seg ${p.key}`}
            style={{ flexGrow: p.cents }} />
        ))}
      </div>

      <div className="cf-legend">
        {PARTS.map(p => (
          <div key={p.key} className="cf-item">
            <div className={`cf-dot ${p.key}`} />
            <div>
              <div className={`amt ${p.key}`}>¥{yuan(p.cents)}</div>
              <div className="who">{p.who}</div>
              <div className="how">{p.how}</div>
            </div>
          </div>
        ))}
      </div>

      <p className="cf-note">
        这就是真实的分账规则,不是示意图 ——
        每一单都能在订单详情里查到同样的明细。
      </p>
    </section>
  )
}
