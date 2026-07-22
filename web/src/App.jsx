import React, { useEffect, useRef, useState } from 'react'

import BrandPage from './BrandPage.jsx'
import { BrandIcon, BrandWordmark } from './BrandSvg.jsx'
import ChinaNodes from './ChinaNodes.jsx'
import CoinFlow from './CoinFlow.jsx'
import Embers from './Embers.jsx'
import { JoinMerchant, JoinRider } from './JoinPages.jsx'

// 大屏/透明中心单独成 chunk:echarts + 地图数据不拖累官网首页
const ScreenPage = React.lazy(() => import('./screen/ScreenPage.jsx'))
const TransparencyPage = React.lazy(
  () => import('./transparency/TransparencyPage.jsx'))

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
  if (path.startsWith('/join/merchant')) return <JoinMerchant />
  if (path.startsWith('/join/rider')) return <JoinRider />
  if (path.startsWith('/brand')) return <BrandPage />
  if (path.startsWith('/screen')) {
    return <React.Suspense fallback={null}><ScreenPage /></React.Suspense>
  }
  if (path.startsWith('/transparency') || path.startsWith('/status')) {
    return <React.Suspense fallback={null}><TransparencyPage /></React.Suspense>
  }
  return <Home />
}

function Home() {
  const stats = useStats()
  return (
    <>
      <nav className="topnav">
        <a className="brand-link" href="/"><BrandIcon size={34} /> 超级赞</a>
        <div className="links">
          <a href="#principles">三原则</a>
          <a href="#coinflow">钱去哪了</a>
          <a href="#trust">验证我们</a>
          <a href="/transparency">透明中心</a>
          <a href="/join/merchant">商家入驻</a>
          <a href="/join/rider">骑手加入</a>
          <a href="/brand">品牌物料</a>
          <a href="#faq">常见问题</a>
        </div>
        <a className="dl" href="#download">下载 App</a>
      </nav>
      <header className="hero">
        <Embers />
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

      <CoinFlow />

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
        <ChinaNodes />
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
        <div className="live">
          <div className="live-item"><div className="n green">{stats ? stats.nodes.online : '–'}</div>
            <div className="l">社区见证节点在线</div></div>
          <div className="live-item"><div className="n">{stats ? stats.chain.anchors : '–'}</div>
            <div className="l">每日账本锚点相链</div></div>
          <div className="live-item"><div className="n orange">{stats ? stats.today.orders : '–'}</div>
            <div className="l">今日订单</div></div>
          <div className="live-item"><div className="n green">¥{stats ? yuan(stats.today.rider_cents) : '–'}</div>
            <div className="l">骑手今日所得</div></div>
        </div>
        {stats?.chain?.latest_hash && (
          <div className="hash">最新锚点 {stats.chain.latest_day} · {stats.chain.latest_hash}</div>
        )}
        <div className="cta">
          <a className="btn ghost" href="/transparency">进透明中心看细账</a>
          <a className="btn ghost" href="/nodes">运行你自己的见证节点</a>
          <a className="btn ghost" href="/ledger/anchors">查看账本原文</a>
        </div>
      </Reveal>

      <Reveal className="download" id="download">
        <h2>下载超级赞</h2>
        <p className="section-lede">Android 三端安装包,内置更新检查;iOS 与 H5 版在路上。</p>
        <div className="dl-grid">
          <div className="qrbox">
            <img src="/site/brand/qr_download.svg" alt="扫码打开下载页" />
            <div className="cap">手机扫码下载</div>
            <div className="url">aikas.com.cn/download</div>
          </div>
          <div className="apps">
            <div className="app"><span className="emoji">🍜</span>
              <div><b>用户端</b><p>点外卖,每一单分账可查</p></div>
              <a className="get" href="/appdist/superz-user-arm64.apk">下载 APK</a></div>
            <div className="app"><span className="emoji">🏪</span>
              <div><b>商家端</b><p>入驻免费,总负担 5% 封顶,每日对账</p></div>
              <a className="get" href="/appdist/superz-merchant-arm64.apk">下载 APK</a></div>
            <div className="app"><span className="emoji">🛵</span>
              <div><b>骑手端</b><p>配送费 100% 归你,提现零手续费</p></div>
              <a className="get" href="/appdist/superz-rider-arm64.apk">下载 APK</a></div>
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
          <div className="bcard"><h3>打车 · 跑腿 · 家政 <span className="tag">筹备中</span></h3>
            <p>凡是抽成不透明的行当,都值得重做一遍。低抽成,账目公开,一个一个来。</p></div>
        </div>
      </Reveal>

      <Reveal className="faq" id="faq">
        <h2>问得最多的几件事</h2>
        <p className="section-lede">评论区问什么,我们就答什么。原话放在这里,不装、不画饼。</p>
        <div className="faq-list">
          <details>
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
          <a href="https://beian.miit.gov.cn" target="_blank" rel="noreferrer">陕ICP备2025064101号-2</a>
        </div>
      </footer>
    </>
  )
}
