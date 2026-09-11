import React from 'react'

import './pages.css'
import { SitePage } from './SiteChrome.jsx'

/* 品牌物料页:标志/用色/海报传单/社媒背景,全部开放下载。
   立场:欢迎任何人拿去转发传播——唯一要求是别改数字承诺。

   2026-09 换成官网浅色外壳(没有单独的设计稿,套 4x 的页头、卡片)。
   物料和链接一个没动;「品牌色」一栏原来写的 App 行动色(炉火橙 #FF5A1F)和
   账目绿(#0E8A5F)是改版前的,现在 App 和官网用的是 brand.dart 产品层那一套,
   所以分成「传播层 / 产品层」两组照实列。 */

const B = '/site/brand'

function Asset({ src, label, links, dark = false }) {
  return (
    <figure className={`sz-card br-asset ${dark ? 'dark' : ''}`}>
      <div className="pv"><img src={src} alt={label} loading="lazy" /></div>
      <figcaption>
        <span>{label}</span>
        <span className="lk">
          {links.map(([text, href]) => (
            <a key={href} href={href} download>{text}</a>
          ))}
        </span>
      </figcaption>
    </figure>
  )
}

const SWATCH_SPREAD = [
  ['品牌渐变', '#FF7A45 → #E1251B', 'linear-gradient(135deg,#FF7A45,#E1251B)', '#FFFFFF', '标志与海报'],
  ['点赞黄', '#FFD34D', '#FFD34D', '#5C3A00', '标志和传单里的点缀'],
]
const SWATCH_PRODUCT = [
  ['骨白', '#F0EEE6', '#F0EEE6', '#141413', '页面底色'],
  ['黏土', '#C15F3C', '#C15F3C', '#FBFAF6', '行动色，一屏一个实底按钮'],
  ['苔绿', '#4E6B4F', '#4E6B4F', '#FBFAF6', '到手的钱：商家实收、骑手所得'],
  ['赭', '#A6763E', '#A6763E', '#FBFAF6', '平台收的那一份'],
  ['墨', '#141413', '#141413', '#F0EEE6', '正文'],
]

function Swatches({ list }) {
  return (
    <div className="br-swatches">
      {list.map(([name, hex, bg, fg, use]) => (
        <div key={name} className="sz-card br-swatch">
          <div className="chip" style={{ background: bg, color: fg }}><b>{name}</b><span className="mono">{hex}</span></div>
          <div className="use muted">{use}</div>
        </div>
      ))}
    </div>
  )
}

export default function BrandPage() {
  return (
    <SitePage title="超级赞 · 品牌物料(开放下载)" note="物料可自由转发传播；商用印刷请保持数字承诺原样">
      <div className="sz-page br">
        <div className="sz-eyebrow">品牌物料 · 开放下载</div>
        <h1 className="sz-h1">品牌物料，随便拿。</h1>
        <p className="sz-lede br-lede">
          标志、海报、传单、社媒背景图，全部开放下载。贴店里、发群里、印出来都欢迎——这场运动的传播不需要授权。<b>唯一的要求：数字承诺（5% / 100% / 2%）一个字都别改。</b>
        </p>
        <img className="br-logo" src={`${B}/logo_horizontal_light.png`} alt="超级赞 Super-Z · 群众帮群众" />

        <section className="br-sec">
          <h2 className="sz-h2">标志</h2>
          <div className="br-grid">
            <Asset src={`${B}/icon_1024.png`} label="App 图标"
              links={[['SVG', `${B}/icon.svg`], ['PNG', `${B}/icon_1024.png`]]} />
            <Asset src={`${B}/logo_horizontal_dark.png`} label="横版标志 · 深色背景用" dark
              links={[['SVG', `${B}/logo_horizontal_dark.svg`], ['PNG', `${B}/logo_horizontal_dark.png`]]} />
            <Asset src={`${B}/logo_horizontal_light.png`} label="横版标志 · 浅色背景用"
              links={[['SVG', `${B}/logo_horizontal_light.svg`], ['PNG', `${B}/logo_horizontal_light.png`]]} />
          </div>
        </section>

        <section className="br-sec">
          <h2 className="sz-h2">品牌色</h2>
          <p className="br-p muted">传播层：标志、海报、传单用。</p>
          <Swatches list={SWATCH_SPREAD} />
          <p className="br-p muted">产品层：App 和官网的界面用，页面本身不用渐变。</p>
          <Swatches list={SWATCH_PRODUCT} />
        </section>

        <section className="br-sec">
          <h2 className="sz-h2">海报与传单</h2>
          <p className="br-p muted">A5 传单有 300dpi 打印版 PDF，直接拿去印；桌贴贴收银台，海报贴店门口。</p>
          <div className="br-grid">
            <Asset src={`${B}/flyer_merchant_a5_front.png`} label="商家传单 A5 · 正面"
              links={[['PNG', `${B}/flyer_merchant_a5_front.png`]]} />
            <Asset src={`${B}/flyer_merchant_a5_back.png`} label="商家传单 A5 · 反面"
              links={[['PNG', `${B}/flyer_merchant_a5_back.png`]]} />
            <Asset src={`${B}/flyer_rider_a5.png`} label="骑手传单 A5"
              links={[['PNG', `${B}/flyer_rider_a5.png`]]} />
            <Asset src={`${B}/table_sticker_1080.png`} label="店内桌贴 1080×1080"
              links={[['PNG', `${B}/table_sticker_1080.png`]]} />
            <Asset src={`${B}/poster_vertical_1080x1920.png`} label="通用竖版海报 1080×1920"
              links={[['PNG', `${B}/poster_vertical_1080x1920.png`]]} />
          </div>
          <div className="h3-cta br-cta">
            <a className="h3-btn primary" href={`${B}/flyers_print_a5_300dpi.pdf`} download>
              下载传单打印版 PDF（A5 · 300dpi）</a>
          </div>
        </section>

        <section className="br-sec">
          <h2 className="sz-h2">社媒背景图</h2>
          <p className="br-p muted">给自媒体账号主页用的封面 / 背景，按各平台尺寸出好了。</p>
          <div className="br-grid">
            <Asset src={`${B}/bg_github_1280x640.png`} label="GitHub 社交卡 1280×640"
              links={[['PNG', `${B}/bg_github_1280x640.png`]]} />
            <Asset src={`${B}/bg_douyin_1125x633.png`} label="抖音 1125×633"
              links={[['PNG', `${B}/bg_douyin_1125x633.png`]]} />
            <Asset src={`${B}/bg_xiaohongshu_1080x1280.png`} label="小红书 1080×1280"
              links={[['PNG', `${B}/bg_xiaohongshu_1080x1280.png`]]} />
            <Asset src={`${B}/bg_kuaishou_1200x400.png`} label="快手 1200×400"
              links={[['PNG', `${B}/bg_kuaishou_1200x400.png`]]} />
            <Asset src={`${B}/bg_bilibili_1920x400.png`} label="B站 1920×400"
              links={[['PNG', `${B}/bg_bilibili_1920x400.png`]]} />
            <Asset src={`${B}/bg_shipinhao_1080x1260.png`} label="视频号 1080×1260"
              links={[['PNG', `${B}/bg_shipinhao_1080x1260.png`]]} />
          </div>
        </section>
      </div>
    </SitePage>
  )
}
