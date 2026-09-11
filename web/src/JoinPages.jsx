import React from 'react'

import './pages.css'
import { Icon, SitePage } from './SiteChrome.jsx'

/* 商家入驻(/join/merchant,设计稿 4e)与骑手加入(/join/rider,设计稿 4g)。
 *
 * 原来两页各挂一个 three.js 画布做点缀,已删 —— 这两页真正管用的是那笔账。
 *
 * ## 和稿子不一样的地方(稿子里的事实不对,按代码改)
 *
 * 商家页:
 * - 稿子说「没有保证金」。有:¥500 从营收里留存,不用预缴,退店无纠纷全额退
 *   (routers/merchants.py 的 deposit_required_cents);
 * - 稿子右边是一张入驻表单,提交后「1 个工作日内回电」。官网没有公开的入驻表单,
 *   审核也没有承诺时限:入驻是在商家端(App 或网页版后台 /merchant)用手机号登录后
 *   提交店名、地址和证照。所以右边换成「在哪儿申请、要准备什么」,按钮直接去后台;
 * - 稿子第三步「每天的账 T+1 到你的卡」。钱是商家自己提现,T+1 到卡、零手续费;
 * - 「在别处 −¥6~8、到手 ≈¥15」这组数核不了,换成站上一直在用的那句
 *   (行业商家总负担普遍 20% 以上,菜价 ¥21 的一单就是 ¥4 多)。
 *
 * 骑手页:
 * - 稿子写「当天 22:00 结到卡」。没有这回事:订单完成钱进 App 钱包,
 *   骑手自己提现(最低 ¥10),T+1 到卡、零手续费;
 * - 稿子写「连续差评才会被约谈」,代码里没有;超时的规矩是:晚到超过 15 分钟,
 *   平台自己给顾客发 ¥3 券,不扣骑手也不扣商家;没有任何罚款;
 * - 稿子写「要求:健康证 + 实名」。要求是实名认证(18 岁以上)+ 食品安全培训,
 *   健康证只在要求的城市才要;
 * - 稿子右边是「一位骑手昨天的真实账单(脱敏)」。没有这样的公开接口,
 *   所以标成示例,每一行都能自己算得出来。 */

// ================= 商家入驻 =================

const M_STEPS = [
  ['登录商家端，提交店铺资料', '网页版后台或商家端 App，手机号收验证码登录；填店名、地址、品类，上传证照'],
  ['平台核验证照', '外卖、买菜类要食品经营许可证；住宿要营业执照和特种行业许可证'],
  ['上菜单，开门', '每一单的实收在对账页逐单可查；提现 T+1 到卡、零手续费，账单随时导出 CSV'],
]

const M_RULES = [
  ['排名买不到', '列表只按离我近、评分、月售排。没有推荐位，没有竞价，老店新店一条起跑线。'],
  ['你让利，平台少收', '你设满减、打折，佣金按折后算。平台补贴的钱不从你这扣。'],
  ['客人是你自己的', '店铺专属码和海报一键生成，扫码直达你的店。顾客的联系方式不给任何人，包括你。'],
  ['不摊派活动费', '平台没有补贴预算，也就不向你摊派。券是你自己出的钱，预算封顶、随时可停。'],
  ['住宿：离店才收', '房费的 5%，离店后才收；取消、未入住不收。没有排他条款（OTA 普遍 12%–20% 还要独家）。'],
  ['规则公开', '三端规则写在代码里，内容一变系统自动记一版，谁都能查。'],
]

export function JoinMerchant() {
  return (
    <SitePage active="merchant" title="超级赞 · 商家入驻:开店不要钱,卖出去才收 5%">
      <div className="sz-page">
        <div className="sz-cols jm-cols">
          <div>
            <div className="sz-eyebrow">商家入驻 · 不收入驻费</div>
            <h1 className="sz-h1">开店不要钱，<br />卖出去才收 5%。</h1>
            <p className="sz-lede">没有入驻费，不卖推广位；保证金不用预缴，从营收里留存 ¥500，退店无纠纷全额退。你的店在列表里的位置只看距离、评分和月售，谁都买不到排名。</p>

            <ol className="jm-steps">
              {M_STEPS.map(([t, d], i) => (
                <li key={t}>
                  <span className="num">{i + 1}</span>
                  <div><div className="t">{t}</div><div className="d">{d}</div></div>
                </li>
              ))}
            </ol>

            <div className="jm-vs">
              <div className="elsewhere">
                <div className="sz-cap">行业平台 · 同一单（示例）</div>
                <div className="ln muted"><span>商家总负担普遍 20%+</span><span className="num thin">−¥4 多</span></div>
                <div className="ln"><span>菜价 ¥21，到手</span><span className="num">不到 ¥17</span></div>
              </div>
              <div className="here">
                <div className="sz-cap">在这里 · 同一单</div>
                <div className="ln muted"><span>菜价 5%，配送费不抽</span><span className="num thin">−¥1.05</span></div>
                <div className="ln"><span>到手</span><span className="num earn">¥19.95</span></div>
              </div>
            </div>
          </div>

          <aside className="sz-card jm-apply sz-enter">
            <div className="body">
              <div className="ttl">申请入驻</div>
              <p className="muted sub">入驻在商家端里提交，电脑、手机都行。先备好这几样：</p>
              <dl>
                <div><dt>店名</dt><dd>和证照上的一致</dd></div>
                <div><dt>频道</dt><dd>点外卖、买菜买水果、住宿；开店后还能卖团购券</dd></div>
                <div><dt>地址</dt><dd>定位到门店，顾客按距离找到你</dd></div>
                <div><dt>证照</dt><dd>食品经营许可证；住宿是营业执照 + 特种行业许可证</dd></div>
                <div><dt>手机号</dt><dd>收验证码登录，也是你的商家账号</dd></div>
              </dl>
              <a className="h3-btn primary jm-go" href="/merchant">打开网页版后台申请</a>
              <a className="h3-btn ghost jm-go" href="/download">下载商家端 App</a>
              <p className="fine">不收入驻费 · 保证金退店全额退 · 账单随时导出 CSV</p>
            </div>
          </aside>
        </div>

        <section className="jm-more">
          <div className="sz-eyebrow">其余的规矩</div>
          <h2 className="sz-h2">没有隐形的刀</h2>
          <div className="sz-grid3">
            {M_RULES.map(([t, d]) => (
              <div key={t} className="sz-card"><div className="body"><div className="t">{t}</div><p className="muted">{d}</p></div></div>
            ))}
          </div>
          <p className="note">佣金怎么算、每个频道收多少，见<a href="/rates">费率页</a>；平台每天的钱去了哪，见<a href="/transparency">透明中心</a>。有疑问请在 App 里提客服工单。</p>
        </section>
      </div>
    </SitePage>
  )
}

// ================= 骑手加入 =================

const R_RULES = [
  ['hand', '抢单不派单', '大厅里的单都公开，距离、配送费一眼看完，自己挑；不接不扣分，也没有任何代价。'],
  ['clock', '超时不罚钱', '没有任何罚款。送晚超过 15 分钟，平台自己给顾客发一张 ¥3 券，不扣你的钱。'],
  ['receipt', '每单都能对账', '你的每一单在透明中心的「今日逐单」里都有一行（脱敏），和用户、商家看到的是同一份。'],
]

/* 示例账:四单,每一行都能自己算出来。帮我送那单跑腿费 ¥12,平台收 2% = ¥0.24 */
const R_DAY = [
  ['11:52', '张记面馆 → 高新路 · 1.8km', 500],
  ['12:10', '李婶砂锅粥 → 阳光花园 · 2.4km', 600],
  ['12:31', '帮我送 · 文件 · 3.2km', 1176],
  ['12:55', '川香居 → 学府街 · 1.1km', 500],
]
const yuan2 = c => `¥${(c / 100).toFixed(2)}`

export function JoinRider() {
  const total = R_DAY.reduce((s, r) => s + r[2], 0)
  return (
    <SitePage active="rider" title="超级赞 · 骑手加入:配送费 100% 归你">
      <div className="sz-page">
        <div className="sz-cols jr-cols">
          <div>
            <div className="sz-eyebrow">骑手加入</div>
            <h1 className="sz-h1">用户付的配送费，<br />一分不少到你手里。</h1>
            <p className="sz-lede">配送费和小费 100% 归你，平台不抽；只有帮我送、帮我买收跑腿费的 2%。用户付 ¥5 配送费，你的钱包里就是 ¥5：订单完成就入账，提现 T+1 到卡、零手续费。</p>

            <ul className="jr-rules">
              {R_RULES.map(([icon, t, d]) => (
                <li key={t}>
                  <Icon name={icon} size={22} color="#2B5F7A" />
                  <div><div className="t">{t}</div><div className="d">{d}</div></div>
                </li>
              ))}
            </ul>

            <div className="jr-cta">
              <a className="h3-btn primary lg" href="/download">下载骑手端</a>
              <span className="jr-req">要求：实名认证 + 食品安全培训</span>
            </div>
            <p className="note">实名认证要年满 18 岁；健康证只在要求的城市才需要。</p>
          </div>

          <aside className="sz-card jr-day sz-enter">
            <div className="bar" style={{ background: '#2B5F7A' }} />
            <div className="body">
              <div className="hd"><span className="sz-cap">示例 · 一位骑手的午高峰</span><span className="faint">不是真实账单</span></div>
              <div className="big"><span className="num earn">{yuan2(total)}</span><span className="muted">{R_DAY.length} 单 · 全部进钱包</span></div>
              <div className="sz-rows">
                {R_DAY.map(([t, d, v]) => (
                  <div key={t}><span className="num t">{t}</span><span className="k">{d}</span><span className="num earn">{yuan2(v)}</span></div>
                ))}
                <div className="muted"><span className="k">平台从配送费、小费里抽</span><span className="num thin">¥0.00</span></div>
                <div className="muted"><span className="k">帮我送那单：跑腿费 ¥12，平台收 2%</span><span className="num thin hold">¥0.24</span></div>
                <div className="muted"><span className="k">什么时候到账</span><span className="earn">订单完成即进钱包</span></div>
              </div>
              <p className="fine">提现自己点，最低 ¥10，T+1 到卡，零手续费。</p>
            </div>
          </aside>
        </div>

        <section className="jm-more">
          <div className="sz-eyebrow">其余的规矩</div>
          <h2 className="sz-h2">跑之前就能看到的规则</h2>
          <div className="sz-grid3">
            <div className="sz-card"><div className="body"><div className="t">新单推到手机</div><p className="muted">附近有单进池就推送提醒，按你自己设的接单半径过滤；不接不扣分，也不影响后面的推送。</p></div></div>
            <div className="sz-card"><div className="body"><div className="t">恶劣天气加价全归你</div><p className="muted">平台打开恶劣天气加价时，每单加的钱全部给骑手；什么时候开、为什么开，透明中心有记录。</p></div></div>
            <div className="sz-card"><div className="body"><div className="t">派单公式公开</div><p className="muted">大厅怎么排序、每一项占多少，写在透明中心；改一次记一次，不悄悄改。</p></div></div>
          </div>
          <p className="note">大厅排序的公式在<a href="/transparency#dispatch">透明中心 · 派单算法</a>；平台开关的变更记录在<a href="/transparency#governance">治理公开</a>。</p>
        </section>
      </div>
    </SitePage>
  )
}
