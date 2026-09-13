import React from 'react'

import FlowFilm from './FlowFilm.jsx'
import {
  CHANNELS, Glyph, STATE_LABEL, SiteFooter, SiteNav, useChannelState, useCountUp, useFeatures, useJson,
} from './SiteChrome.jsx'

/* 官网动画集的片子各自成 chunk,不拖首屏:首屏之下那支「一个 App 干完这些事」,
 * 下载段那支「一笔单,三端各看到什么」和紧跟下载段的隐私清单 */
const SuperAppFilm = React.lazy(() => import('./films/SuperAppFilm.jsx'))
const ThreeAppsFilm = React.lazy(() => import('./films/ThreeAppsFilm.jsx'))
const PrivacyListFilm = React.lazy(() => import('./films/PrivacyListFilm.jsx'))

/* 官网首页 v3(设计稿 1g):讲「聚合平台」,不讲「外卖」。
 *
 * 首屏左边一句话 + 右边就是 App 里的服务台(频道),
 * 首屏之下先是「一个 App 干完这些事」(films/SuperAppFilm.jsx:先说清这是个什么东西),
 * 接着一段 30 秒的流程动画(一笔 ¥26 的外卖单,钱怎么走 —— FlowFilm.jsx),
 * 然后一张费率表把每个频道「抽多少、什么时候抽」说完,
 * 再往下是实时账目、下载、隐私清单(films/PrivacyListFilm.jsx)。
 * 三原则不再单独成卡 —— 它们已经是表里的行。
 *
 * 颜色取 brand.dart 产品层,令牌在 site.css 的 .h3 上;顶栏、页脚在 SiteChrome.jsx,
 * 和其他子页共用一份。
 *
 * ## 类名一律不和 styles.css 重名
 *
 * styles.css 原来是老首页和各子页共用的**全局**样式:`.brand` 带 18px 下边距和
 * 入场动画、`.cta` 居中、`.btn` 是橙色胶囊、`.app` 是深色卡片。这一页只要
 * 用了同名的类,那些规则就原样漏进来 —— 实测过:logo 和导航错位、
 * 首屏两个按钮被居中到标题底下。所以这里的类名要么带 h3- 前缀、
 * 要么是 styles.css 里没有的词。(2026-09 子页全部换成浅色版后,styles.css
 * 已删到只剩重置和 /screen 要用的几条,但这条规矩照旧。)
 *
 * ## 小程序不在这一页
 *
 * App 里的小程序清单(/mini-apps)要登录才给,匿名访问是 401,
 * 官网拿不到就只能整块藏着。等清单有了不需要登录的只读版本再加回来。 */

/* 这一页的频道文案。频道本身(字、颜色)在 SiteChrome 的 CHANNELS;
 * **开没开不写在这里**,读 /channels —— 和 App 首页金刚区是同一份后台配置。
 * 写死成「5 个频道运营中」的话,生产上只开了外卖和团购时,
 * 官网就在替另外三个频道撒谎。 */
const COPY = {
  food: { sub: '商家负担 5% 封顶', rate: '5%', when: '订单完成；配送费一分不抽', industry: '商家实际负担普遍 20%+' },
  retail: { sub: '同一套配送', rate: '5%', when: '同外卖', industry: '—' },
  stay: { sub: '5%，离店才收', rate: '5%', when: '离店才收；取消、未入住不收', industry: 'OTA 12%–20%，另有排他条款' },
  voucher: { sub: '核销才收 2%', rate: '2%', when: '到店核销才收；未用随时全退', industry: '靠「过期不退」摸钱' },
  errand: { sub: '也能帮买 · 收 2%', rate: '2%', when: '只收跑腿费的 2%，账单单列一行；商品款不抽', industry: '骑手垫钱、小票看不到' },
  ride: { sub: '筹备中', rate: '筹备中', when: '计价规则公开，同一套账本', industry: '司机每单被抽两三成' },
}

const yuan = c => ((c ?? 0) / 100).toLocaleString('zh-CN', { maximumFractionDigits: 0 })

/** 一格实时数字。
 *
 * 拿不到显示「–」,真的是 0 就显示 0 —— 这两件事分开。0 的时候不高亮,
 * 并补一句话说清这是真的 0:一个大大的彩色 0 长得像警报,
 * 而事实常常只是「今天才刚开始」。难看的真话也是真话,只是别让它被读成别的意思。
 * 数字第一次拿到时从 0 滚上去(900ms),之后轮询刷新从旧值滚到新值 */
function Num({ value, label, tone, zeroHint, render }) {
  const shown = useCountUp(value == null ? null : Number(value))
  const loading = value === undefined || value === null
  const zero = !loading && Number(value) === 0
  return (
    <div className="h3-num">
      <div className={`n ${loading || zero ? '' : (tone || '')}`}>
        {loading ? '–' : (render ? render(Math.round(shown)) : Math.round(shown).toLocaleString())}
      </div>
      <div className="l">{label}</div>
      {zero && zeroHint && <div className="l zero">{zeroHint}</div>}
    </div>
  )
}

/** 首屏那句「N 天核账零差错」。
 *
 * streak 为 0 不是「刚开始」,是**最近一次核账查出了差错**
 * (transparency.clean_streak_days 从最近一天往回数)。
 * 绿色的「0 天零差错」会被读成好消息,所以 0 的时候换成一句实话。 */
function Streak({ audit }) {
  if (!audit?.latest) return <span><b>–</b> 天核账零差错</span>
  if (audit.clean_streak_days > 0) {
    return <span><b className="earn">{audit.clean_streak_days}</b> 天核账零差错</span>
  }
  return <span><a className="bad" href="/transparency#audit">最近一次核账发现了差错，细节在透明中心 →</a></span>
}

export default function Home() {
  const stats = useJson('/stats/overview', 60000)
  const audit = useJson('/transparency/audit')
  const { loaded, stateOf } = useChannelState()
  const features = useFeatures()
  const rows = CHANNELS.map(ch => ({ ...ch, ...COPY[ch.key], state: stateOf(ch.key) }))
  const openCount = rows.filter(r => r.state === 'open').length

  return (
    <div className="h3">
      <SiteNav home />

      <header className="h3-hero" id="services">
        <div className="copy">
          <div className="eyebrow">超级赞 · 群众帮群众</div>
          <h1>一个 App，<br />装下所有不吸血的服务。</h1>
          {/* 不写成「外卖、买菜、住宿……以后还有打车」:那等于说前五个都开着。
              哪些开着由后台配置,右边服务台读的是实时状态,这句话不该和它打架 */}
          <p className="h3-lede">外卖、买菜、住宿、团购、跑腿、打车，一个频道一个频道地开。每个频道只有一条规矩：抽成写在明面上，账目谁都能查。</p>
          <div className="h3-cta">
            <a className="h3-btn primary lg" href="#download">下载 App</a>
            <a className="h3-btn ghost lg" href="#ledger">看今天的账</a>
          </div>
          <div className="facts">
            <span><b>{loaded ? openCount : '–'}</b> 个频道运营中</span>
            <Streak audit={audit} />
          </div>
        </div>

        {/* 右侧:就是 App 里的服务台,不是示意图。格子点进去是各频道的规矩页 */}
        <div className="desk">
          <div className="sec">平台频道</div>
          <div className="chgrid">
            {rows.map(ch => (
              <a key={ch.key} href={`/channel/${ch.key}`} className={`chcard ${ch.state === 'open' ? '' : 'off'}`}>
                <Glyph ch={ch} off={ch.state !== 'open'} fontSize={19} />
                <div>
                  <div className="nm">{ch.name}</div>
                  <div className="sb">{ch.state === 'open' ? ch.sub : STATE_LABEL[ch.state]}</div>
                </div>
              </a>
            ))}
          </div>
        </div>
      </header>

      {/* 首屏之下的第一支:先说清「这是个什么东西」,再往下是流程片、费率和账本 */}
      <section className="h3-sec h3-super-sec" id="superapp">
        <div className="sec">超级聚合 · 一个 App 干完这些事</div>
        <h2>聚合不是把图标堆在一起，<br />是底下只有一份账。</h2>
        <div className="h3-super-film">
          <React.Suspense fallback={<div className="h3-film-hold" />}>
            <SuperAppFilm stateOf={stateOf} features={features} />
          </React.Suspense>
        </div>
        <p className="note">消息、视频这两个 tab 怎么用，见<a href="/features">消息与视频</a>；每个频道抽多少，往下看费率表。</p>
      </section>

      <section className="h3-sec h3-film-sec" aria-label="示例：一笔外卖单的钱怎么走">
        <div className="sec">示例 · 一单的钱怎么走</div>
        <FlowFilm />
      </section>

      <section className="h3-sec" id="rates">
        <div className="sec">费率，一张表说完</div>
        <h2>每个频道抽多少，什么时候抽</h2>
        <div className="rates">
          <div className="row head"><div>频道</div><div>平台收</div><div>什么时候收</div><div>行业现状</div></div>
          {rows.map(ch => (
            <div key={ch.key} className={`row ${ch.state === 'open' ? '' : 'off'}`}>
              <div className="ch">
                <span className="sz-dot" style={{ background: ch.state === 'open' ? ch.color : '#E2DED2' }} />
                {ch.fullName ?? ch.name}
                {ch.state === 'closed' && <span className="h3-tag">{STATE_LABEL.closed}</span>}
              </div>
              <div className={ch.coming ? '' : 'rate'}>{ch.rate}</div>
              <div data-k="什么时候收">{ch.when}</div>
              <div className="muted" data-k="行业现状">{ch.industry}</div>
            </div>
          ))}
        </div>
        <p className="note">这些数字写在代码里，改动会留痕：<a href="/opensource#changes">开源仓的「规则变更留痕」</a>能查到每一次，每一项怎么算见<a href="/rates">费率页</a>。5% 是上限，不是目标。</p>
      </section>

      <section className="h3-sec" id="ledger">
        <div className="sec">今天的账，实时</div>
        <h2>不要相信我们，先看账</h2>
        <div className="ledger">
          <div className="nums">
            <Num value={stats?.today?.orders} label="今日订单" tone="clay"
              zeroHint="今天还没有订单" />
            {/* rider_cents 是今天的有效单里归骑手的那部分:配送费 + 小费,
                跑腿单扣掉 2% 服务费,商家自送单不算(口径在 routers/ledger.py)。
                它原来是「全部配送费之和」,那时这里只敢叫「今日配送费」 */}
            <Num value={stats?.today?.rider_cents} label="骑手今日所得" tone="earn"
              render={v => `¥${yuan(v)}`} zeroHint="今天还没有配送单" />
            <Num value={stats?.nodes?.online} label="社区见证节点在线" tone="earn"
              zeroHint="暂时没有节点在线，锚点仍在逐日生成" />
            {/* 只取最近一次。每次核账核的是近 30 天全部订单,把 90 次运行的笔数
                加起来,同一单会被数最多 30 次(老首页就是这么算的,虚高约 30 倍)。
                透明中心那页用的也是最近一次 */}
            <Num value={audit?.latest?.checked_orders} label="最近一次核账 · 近 30 天（笔）"
              zeroHint="近 30 天还没有完成的订单" />
          </div>
          {stats?.chain?.latest_hash && (
            <div className="hashrow">
              <span>{stats.chain.latest_day} 全部账目的指纹</span>
              <code>{stats.chain.latest_hash.slice(0, 4)}…{stats.chain.latest_hash.slice(-4)}</code>
              <span>改动任何一分钱这串就会变样，而它已被各地见证节点抄走</span>
              <a href="/transparency">进透明中心看细账 →</a>
            </div>
          )}
        </div>
      </section>

      <section className="h3-sec" id="download">
        <div className="sec">下载</div>
        <h2>Android 三端安装包，内置更新检查</h2>
        <div className="h3-dl-film">
          <React.Suspense fallback={null}><ThreeAppsFilm /></React.Suspense>
        </div>
        <div className="dl">
          <div className="dlcard"><b>用户端</b><p>点外卖、订酒店、买券、叫跑腿，每一单分账可查</p><a className="h3-btn ghost" href="/appdist/chaojizan-user-arm64.apk">下载 APK</a></div>
          <div className="dlcard"><b>商家端</b><p>入驻免费，总负担 5% 封顶，每日对账 · <a href="/merchant">网页版后台</a></p><a className="h3-btn ghost" href="/appdist/chaojizan-merchant-arm64.apk">下载 APK</a></div>
          <div className="dlcard"><b>骑手端</b><p>配送费 100% 归你，提现零手续费</p><a className="h3-btn ghost" href="/appdist/chaojizan-rider-arm64.apk">下载 APK</a></div>
        </div>
        <p className="note">iOS 与 H5 版在路上。手机上打开 <a href="/download">chaojizan.cc/download</a> 也能下载。装之前想知道 App 收集什么，<a href="#privacy">往下看隐私清单</a>。</p>
      </section>

      {/* 隐私清单:稿子标的位置是「下载页三张卡的上方」。三张卡上方已经是三端片,
          两支叠在一起下载按钮要往下翻两屏,所以接在下载段后面,单独一段 */}
      <section className="h3-sec" id="privacy">
        <div className="sec">隐私</div>
        <h2>不收集什么，<br />和确实收集了什么。</h2>
        <p className="h3-sec-lede">只列「不收集」的那半边是宣传，两边都写出来才是交代。所以骑手端的后台定位明写着有，末尾那块是我们自己查出来的缺陷。每条都点得到源码或文档。</p>
        <div className="h3-privacy-film">
          <React.Suspense fallback={null}><PrivacyListFilm /></React.Suspense>
        </div>
      </section>

      {/* 应用商店整改反馈第 ⑩ 条要求的版块(公司简介 / 电话 / 邮箱),
          只留页脚那一行不够。内容是过审时的原文,改之前先想想要不要重新提审 */}
      <section className="h3-sec" id="contact">
        <div className="sec">运营主体</div>
        <h2>关于我们 · 联系我们</h2>
        <p className="h3-about">超级赞（Super-Z）由陕西爱卡斯科技有限公司运营，是低抽成、账目透明的本地生活服务平台：外卖佣金 5% 封顶、团购核销 2%、跑腿 2%、配送费 100% 归骑手，每一单的资金流向对用户、商家、骑手三方公开可查。</p>
        <p className="h3-about">商务合作、商家入驻、骑手加入或任何问题，欢迎联系：</p>
        <div className="h3-cta">
          <a className="h3-btn ghost" href="tel:15231109698">电话 15231109698</a>
          <a className="h3-btn ghost" href="mailto:support@chaojizan.cc">邮箱 support@chaojizan.cc</a>
        </div>
      </section>

      <SiteFooter note="本页数据与公开账本同源" />
    </div>
  )
}
