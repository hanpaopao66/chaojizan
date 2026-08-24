import React, { useEffect, useRef, useState } from 'react'

import { BrandIcon, BrandWordmark } from './BrandSvg.jsx'

// 大屏/透明中心单独成 chunk:echarts + 地图数据不拖累官网首页
const ScreenPage = React.lazy(() => import('./screen/ScreenPage.jsx'))
const TransparencyPage = React.lazy(
  () => import('./transparency/TransparencyPage.jsx'))

/* 3D 装饰件和子页面也全部拆出去 —— 它们一起把 three.js 拖进了首屏主包。
 *
 * 改之前:首页主包 gzip **282 KB**,其中绝大部分是 three.js。
 * 一个人在微信里点开这个链接,要等这 282 KB 下完,才看得到
 * 「这不是生意,是一场把钱分公平的运动」这行字 —— 而那 282 KB
 * 买到的只是背景火星、一个 3D 地球和一段滚动动画。
 *
 * 这是个靠转发传播的落地页:白屏三秒,人就退回聊天窗口了。
 * **文字先出来,装饰后到。**
 *
 * 子页面(入驻/骑手/品牌)原本是直接 import 的,虽然只有对应路由才渲染,
 * 但代码照样打进首屏主包,而且它们各自也 import 了 Embers。
 */
const ChinaNodes = React.lazy(() => import('./ChinaNodes.jsx'))
const CoinFlow = React.lazy(() => import('./CoinFlow.jsx'))
const Embers = React.lazy(() => import('./Embers.jsx'))
const BrandPage = React.lazy(() => import('./BrandPage.jsx'))
const JoinMerchant = React.lazy(
  () => import('./JoinPages.jsx').then(m => ({ default: m.JoinMerchant })))
const JoinRider = React.lazy(
  () => import('./JoinPages.jsx').then(m => ({ default: m.JoinRider })))

/* 滚动渐现:进入视口加 .visible,CSS 负责平缓的位移+淡入 */
function Reveal({ children, className = '', as: Tag = 'section', id }) {
  const ref = useRef()
  useEffect(() => {
    const el = ref.current
    const io = new IntersectionObserver(
      ([e]) => e.isIntersecting && (el.classList.add('visible'), io.disconnect()),
      { threshold: 0.18 })
    io.observe(el)
    return () => io.disconnect()
  }, [])
  return <Tag ref={ref} id={id} className={`reveal ${className}`}>{children}</Tag>
}

function useStats() {
  const [stats, setStats] = useState(null)
  useEffect(() => {
    let alive = true
    const load = () => fetch('/stats/overview')
      .then(r => r.json()).then(d => alive && setStats(d)).catch(() => {})
    load()
    const t = setInterval(load, 60000)
    return () => { alive = false; clearInterval(t) }
  }, [])
  return stats
}

const yuan = c => ((c ?? 0) / 100).toLocaleString('zh-CN', { maximumFractionDigits: 0 })

export default function App() {
  // 极简路由:官网只有几条路径,不值得为此引一个路由库。
  // vite dev 下路径带 /site 前缀(base 配置),先剥掉,与生产行为一致
  const raw = typeof location !== 'undefined' ? location.pathname : '/'
  const path = raw.replace(/^\/site/, '') || '/'
  const lazyPage = node => (
    <React.Suspense fallback={null}>{node}</React.Suspense>)
  if (path.startsWith('/join/merchant')) return lazyPage(<JoinMerchant />)
  if (path.startsWith('/join/rider')) return lazyPage(<JoinRider />)
  if (path.startsWith('/brand')) return lazyPage(<BrandPage />)
  if (path.startsWith('/screen')) {
    return <React.Suspense fallback={null}><ScreenPage /></React.Suspense>
  }
  if (path.startsWith('/transparency') || path.startsWith('/status')) {
    return <React.Suspense fallback={null}><TransparencyPage /></React.Suspense>
  }
  return <Home />
}

function useAudit() {
  const [audit, setAudit] = useState(null)
  useEffect(() => {
    let alive = true
    fetch('/transparency/audit')
      .then(r => r.json()).then(d => alive && setAudit(d)).catch(() => {})
    return () => { alive = false }
  }, [])
  return audit
}

/** 一格实时数字。
 *
 * ## 「0」和「坏了」在用户眼里长得一样
 *
 * 拿不到数据显示「–」,真的是 0 就显示 0 —— 这两件事本来就分开了。
 * 但**观感**上还差一层:一个大大的橙色 `0` 长得像警报,
 * 而事实常常只是"今天才刚开始"。
 *
 * 所以 0 的时候不高亮,并在下面补一句话说清这是真的 0。
 * 不改数字本身:难看的真话也是真话,只是别让它被读成别的意思。
 */
function LiveItem({ value, label, tone, zeroHint, render }) {
  const loading = value === undefined || value === null
  const zero = !loading && Number(value) === 0
  return (
    <div className="live-item">
      <div className={loading || zero ? 'n' : `n ${tone || ''}`}>
        {loading ? '–' : (render ? render(value) : value)}
      </div>
      <div className="l">{label}</div>
      {zero && zeroHint && <div className="l zero-hint">{zeroHint}</div>}
    </div>
  )
}

function Home() {
  const stats = useStats()
  const audit = useAudit()
  return (
    <>
      <nav className="topnav">
        <a className="brand-link" href="/"><BrandIcon size={34} /> 超级赞</a>
        {/* 锚点链接标 `jump`:窄屏隐掉。
            它们只是页内跳转,手机上往下滑一样到得了;而把它们留着,
            会把「商家入驻」「骑手加入」这些**真页面**挤出屏幕 ——
            那才是手机用户唯一到不了的东西。 */}
        <div className="links">
          <a className="jump" href="#principles">三原则</a>
          <a className="jump" href="#coinflow">钱去哪了</a>
          <a className="jump" href="#trust">验证我们</a>
          <a href="/transparency">透明中心</a>
          <a href="/join/merchant">商家入驻</a>
          <a href="/join/rider">骑手加入</a>
          <a href="/brand">品牌物料</a>
          <a className="jump" href="#faq">常见问题</a>
        </div>
        <a className="dl" href="#download">下载 App</a>
      </nav>
      <header className="hero">
        <React.Suspense fallback={null}><Embers /></React.Suspense>
        <div className="hero-inner">
          <div className="hlogo"><BrandWordmark width={360} /></div>
          <h1>这不是生意,<br />是一场把钱分公平的运动。</h1>
          <p className="lede">
            资本平台的玩法是抽水:商家多交、骑手少拿、用户多付,中间的差价养肥了谁,谁也不许问。
            我们把这套玩法倒过来——白花花的银子,回到干活的人和吃饭的人手里,账本摊开给所有人看。
          </p>
          <p className="lede"><b>第一战:外卖——只抽 5%,账目全公开。打穿一个,再打下一个。</b></p>
          <div className="cta">
            <a className="btn primary" href="#download">下载 App</a>
            <a className="btn ghost" href="/screen">看实时账目大屏</a>
          </div>
          <div className="scroll-hint">往下,慢慢说 ↓</div>
        </div>
      </header>

      <Reveal className="principles" id="principles">
        <h2>公平,公平,还是公平</h2>
        <p className="section-lede">口号谁都会喊。我们把公平写成三个改不了的数字——
          写进代码、写进公开账本、由社区盯着,不随融资轮次改变。</p>
        <div className="cards3">
          <div className="pcard orange"><div className="big">5%</div>
            <h3>商家总负担封顶</h3>
            <p>大平台嘴上的佣金也只有 6%–8%,但那只是"技术服务费";加上配送履约费和竞价推广,
              商家实际上交普遍超过 20%。我们的 5% 是全部:没有履约费、没有竞价排名、没有保底费,
              商家省下的每一分,都能变成你碗里的分量。
              <b>5% 是上限,不是目标——哪天 3% 能活,我们就降到 3%,这句话写在这里当立字据。</b></p></div>
          <div className="pcard green"><div className="big">100%</div>
            <h3>配送费归骑手</h3>
            <p>你付的配送费,一分不截留,原封不动到骑手账上;骑手的意外保障由平台从佣金里计提
              (账本里的"骑手保障金"一行,逐日可查),不从骑手工资里扣。我们不变"免配送费"的
              魔术——那笔钱从来没免过,只是藏进了菜价。</p></div>
          <div className="pcard amber"><div className="big">2%</div>
            <h3>团购核销才收费</h3>
            <p>到店核销才收 2%,没到店就一分不收。未使用的券,随时、全额、无理由退,
              不靠"过期不退"从你兜里摸钱。</p></div>
        </div>
      </Reveal>

      {/* 占位和真身同一个 class,高度一致 —— 不占位的话它一到就把页面
          顶长,正在往下滑的人会被硬生生推走 */}
      <React.Suspense
        fallback={<section className="coinflow" id="coinflow" aria-hidden="true" />}>
        <CoinFlow />
      </React.Suspense>

      <Reveal className="cycle">
        <h2>平台赚的钱,去哪儿了</h2>
        <p className="section-lede">
          资本平台的循环是抽血:抽成越狠 → 商家越难 → 价格越高 → 大家越不敢消费 → 再加抽成。
          我们把循环拧回正向:
        </p>
        <div className="cycle-chain">
          <span>抽成低</span><i>→</i>
          <span>商家活得下去,价格降得下来</span><i>→</i>
          <span>大家吃得起、常点单</span><i>→</i>
          <span>单量涨,平台按 5% 也能活</span><i>→</i>
          <span>赚到的钱不进资本口袋:降费率、补贴骑手商家、投给社区</span>
        </div>
        <p className="section-lede">
          大家兜里钱越多,消费越旺;消费越旺,平台越稳。每一笔去向,月度财报公开可查——
          <b>平台的利益第一次和你的利益站在同一边。</b>
        </p>
      </Reveal>

      <Reveal className="trust" id="trust">
        <h2>不要相信我们,验证我们</h2>
        <React.Suspense fallback={null}><ChinaNodes /></React.Suspense>
        <p className="section-lede">
          说要散银子的人多了,兑现的少。所以别信表态——平台每天把全部账务流水
          (匿名化,无个人信息)生成哈希锚点,首尾相链;全世界志愿者的机器持续复算、
          留存、示警。改历史上任何一分钱,全网都会知道。<b>我们想赖账,数学不答应。</b>
        </p>
        <p className="section-lede">
          账本之外还有内审:系统每天凌晨 4 点自动核对近 30 天每一笔账——商家入账等不等于菜钱减佣金、
          骑手入账等不等于配送费,差一分钱,管理后台直接红条报警。
          我们在自动化测试里故意篡改过 1 分钱,系统当场抓了出来。
        </p>
        {/* 这一节问的是「账目可不可验证」,所以先摆能回答这个问题的数:
            节点、锚点、连续零差错、累计核对笔数。
            今日业务数照常留着 —— 难看的真话也是真话,一个都不删。 */}
        <div className="live">
          <LiveItem value={stats?.nodes.online} tone="green"
            label="社区见证节点在线"
            zeroHint="暂时没有节点在线,锚点仍在逐日生成" />
          <LiveItem value={stats?.chain.anchors} label="每日账本锚点相链" />
          <LiveItem value={audit?.clean_streak_days} tone="green"
            label="连续核账零差错(天)"
            zeroHint="最近一次核账发现了差错,细节在透明中心" />
          <LiveItem
            value={audit?.runs ? audit.runs.reduce((a, r) => a + r.checked_orders, 0) : null}
            label="已逐笔核对(笔)"
            render={v => v.toLocaleString()} />
          <LiveItem value={stats?.today.orders} tone="orange"
            label="今日订单" zeroHint="今天还没有订单" />
          <LiveItem value={stats?.today.rider_cents} tone="green"
            label="骑手今日所得" render={v => `¥${yuan(v)}`}
            zeroHint="今天还没有配送单" />
        </div>
        {/* 一串 64 位十六进制,不解释就只是一坨乱码。
            解释一句它是什么、改了会怎样,它才从"技术装饰"变成证据。 */}
        {stats?.chain?.latest_hash && (
          <>
            <div className="hash-note">
              下面这串是 {stats.chain.latest_day} 那天全部账目的「指纹」。
              账目里改动任何一分钱,这串字符都会完全变样,而它已经被
              各地的见证节点抄走了 —— 这就是我们赖不掉账的原因。
            </div>
            <div className="hash">{stats.chain.latest_hash}</div>
          </>
        )}
        <div className="cta">
          <a className="btn ghost" href="/transparency">进透明中心看细账</a>
          <a className="btn ghost" href="/nodes">运行你自己的见证节点</a>
          {/* 这个链接直接甩出一屏 JSON。**留着**,因为要自己复算的人
              需要的正是原始数据;但要提前说清楚点开是什么,
              别让不懂的人点进去被一屏乱码吓走、以为网站坏了。 */}
          <a className="btn ghost" href="/ledger/anchors"
             title="点开是给程序读的原始数据(JSON)">
            账本原始数据(给会看的人)
          </a>
        </div>
      </Reveal>

      <Reveal className="download" id="download">
        <h2>下载超级赞</h2>
        <p className="section-lede">Android 三端安装包,内置更新检查;iOS 与 H5 版在路上。</p>
        <div className="dl-grid">
          <div className="qrbox">
            <img src="/site/brand/qr_download.svg" alt="扫码打开下载页" />
            <div className="cap">手机扫码下载</div>
            <div className="url">chaojizan.cc/download</div>
          </div>
          <div className="apps">
            <div className="app"><span className="emoji">🍜</span>
              <div><b>用户端</b><p>点外卖,每一单分账可查</p></div>
              <a className="get" href="/appdist/chaojizan-user-arm64.apk">下载 APK</a></div>
            <div className="app"><span className="emoji">🏪</span>
              <div><b>商家端</b><p>入驻免费,总负担 5% 封顶,每日对账
                <br /><a href="/merchant">电脑管店:网页版商家后台 →</a></p></div>
              <a className="get" href="/appdist/chaojizan-merchant-arm64.apk">下载 APK</a></div>
            <div className="app"><span className="emoji">🛵</span>
              <div><b>骑手端</b><p>配送费 100% 归你,提现零手续费</p></div>
              <a className="get" href="/appdist/chaojizan-rider-arm64.apk">下载 APK</a></div>
          </div>
        </div>
      </Reveal>

      <Reveal className="biz">
        <h2>从一碗面开始</h2>
        <p className="section-lede">先把外卖做公平,再一个行当一个行当做下去。
          凡是抽成不透明、靠信息差吸血的行当,都值得用这三个数字重做一遍。</p>
        <div className="cards3">
          <div className="bcard"><h3>外卖 <span className="tag on">运营中</span></h3>
            <p>点餐、配送、售后全流程。每一单的资金流向,用户、商家、骑手三方都看得见。</p></div>
          <div className="bcard"><h3>到店团购 <span className="tag on">运营中</span></h3>
            <p>低价引流到店,核销才收 2%。扫码核销、当日对账,未使用随时全额退。</p></div>
          <div className="bcard"><h3>酒店住宿 <span className="tag on">运营中</span></h3>
            <p>佣金 5%,离店才收;取消、未入住分文不取。无排他、无竞价排名、无年费。</p></div>
          <div className="bcard"><h3>跑腿 <span className="tag on">运营中</span></h3>
            <p>帮送与帮买,平台只收 2%,账单上单列不藏。帮买的商品款一分不抽,
              按小票实付结给骑手,多退少补。</p></div>
          <div className="bcard"><h3>打车 · 家政 · 维修 <span className="tag">筹备中</span></h3>
            <p>凡是抽成不透明的行当,都值得重做一遍。低抽成,账目公开,一个一个来。</p></div>
        </div>
      </Reveal>

      <Reveal className="faq" id="faq">
        <h2>问得最多的几件事</h2>
        <p className="section-lede">评论区问什么,我们就答什么。原话放在这里,不装、不画饼。</p>
        <div className="faq-list">
          {/* 第一条默认展开。
              五个折叠标题一字排开、一个答案都不露,看着像"问题列在这儿
              但懒得答" —— 而这一节恰恰是想证明"我们真的正面回答"。
              露出第一条,读者才知道点开有东西。 */}
          <details open>
            <summary>5% 也是抽成,你们不还是在赚钱?</summary>
            <p>5% 基本是这个平台的"电费":支付通道手续费、服务器带宽、短信、地图接口、
              证照审核与客服,都从这里出。我们不卖用户数据、不做竞价排名、不收商家推广费、
              不抽配送费——5% 是唯一收入。平台自身的收支也会定期公示:赚没赚、赚了多少,大家盯着。</p>
          </details>
          <details>
            <summary>为什么不干脆 0 佣金?</summary>
            <p>说实话,0 佣金的平台你才要小心——它一定在别处挣你的钱:广告、竞价排名、卖数据,
              或者烧完补贴就涨价。我们宁可明着收一笔能活下去的小钱,
              也不暗地里挣一笔你看不见的大钱。</p>
          </details>
          <details>
            <summary>现在 5%,做大了迟早涨价?</summary>
            <p>所以代码开源、账目公开——变没变质,不用信我们的嘴,随时可以查。
              而且我们的承诺是反着来的:5% 是上限,不是目标;规模上来、成本摊薄,就降佣。
              哪天 3% 能活,我们就降到 3%。</p>
          </details>
          <details>
            <summary>你们图什么?</summary>
            <p>图外卖不该是现在这样。我们改变不了行业,但可以写一个"利润不留在平台手里"的样本出来。
              它能跑通,就会有人跟着做——这就够了。</p>
          </details>
          <details>
            <summary>5% 花不完呢?</summary>
            <p>盈余不分红。优先三件事:给骑手上保障(意外险、恶劣天气补贴)、扶持小商家、降低费率。
              花在哪,公示。</p>
          </details>
        </div>
        <p className="section-lede">
          <b>行业平台的抽成,进的是财报;超级赞的 5%,进的是公开账本。</b>
        </p>
      </Reveal>

      <Reveal className="open">
        <h2>底牌,全部摊在桌上</h2>
        <p className="section-lede">
          平台代码 AGPL-3.0 开源,月度财报公开。有人拿这套代码在别的城市再做一个
          不吸血的平台——那是这场运动的胜利,不是我们的损失。
        </p>
        <div className="cta">
          <a className="btn ghost" href="https://github.com/hanpaopao66/chaojizan">GitHub 源码</a>
          <a className="btn ghost" href="/legal/terms">用户协议</a>
          <a className="btn ghost" href="/legal/privacy">隐私政策</a>
        </div>
      </Reveal>

      <Reveal as="section" className="section" id="contact">
        <h2>关于我们 · 联系我们</h2>
        <p className="lead">
          超级赞(Super-Z)由陕西爱卡斯科技有限公司运营,是低抽成、账目透明的
          本地生活服务平台:外卖佣金 5% 封顶、团购核销 2%、跑腿 2%、配送费 100% 归骑手,
          每一单的资金流向对用户、商家、骑手三方公开可查。
        </p>
        <p className="lead">
          商务合作、商家入驻、骑手加入或任何问题,欢迎联系:
        </p>
        <div className="cta">
          <a className="btn ghost" href="tel:15231109698">电话 15231109698</a>
          <a className="btn ghost" href="mailto:support@chaojizan.cc">邮箱 support@chaojizan.cc</a>
        </div>
      </Reveal>

      <div className="pledge-band">
        <div className="q">5% 是上限,不是目标。</div>
        <div className="s">成本摊薄就降佣 · 盈余不分红 · 第一战:外卖,打穿一个再打下一个</div>
      </div>

      <footer>
        <div>超级赞 Super-Z · 群众帮群众 —— 让利于民,取之有道,账目为证</div>
        <div className="muted">本页数据与公开账本同源,接口公开可查
          {stats?.version?.version && <> · 线上版本 {stats.version.version}
            (与 <a href="https://github.com/hanpaopao66/chaojizan" target="_blank"
              rel="noreferrer">开源仓</a> tag 对应)</>}
        </div>
        <div className="muted">
          运营主体:陕西爱卡斯科技有限公司 ·{' '}
          <a href="tel:15231109698">15231109698</a> ·{' '}
          <a href="mailto:support@chaojizan.cc">support@chaojizan.cc</a>
        </div>
        <div className="muted">
          <a href="https://beian.miit.gov.cn" target="_blank" rel="noreferrer">陕ICP备2025064101号-5</a>
        </div>
      </footer>
    </>
  )
}
