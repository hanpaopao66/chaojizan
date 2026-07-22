import React from 'react'

import Embers from './Embers.jsx'

/* 品牌物料页:标志/用色/海报传单/社媒背景,全部开放下载。
   立场:欢迎任何人拿去转发传播——唯一要求是别改数字承诺。 */

const B = '/site/brand'

function Asset({ src, label, links, light = false }) {
  return (
    <figure className={`asset ${light ? 'on-light' : ''}`}>
      <div className="asset-preview"><img src={src} alt={label} loading="lazy" /></div>
      <figcaption>
        <span>{label}</span>
        <span className="asset-links">
          {links.map(([text, href]) => (
            <a key={href} href={href} download>{text}</a>
          ))}
        </span>
      </figcaption>
    </figure>
  )
}

export default function BrandPage() {
  return (
    <>
      <header className="join-hero">
        <Embers />
        <div className="hero-inner">
          <img className="brand-logo-lg" src={`${B}/logo_horizontal_dark.png`}
            alt="超级赞 Super-Z · 群众帮群众" />
          <h1>品牌物料,随便拿。</h1>
          <p className="lede">
            标志、海报、传单、社媒背景图,全部开放下载。贴店里、发群里、印出来都欢迎——
            这场运动的传播不需要授权。<b>唯一的要求:数字承诺(5% / 100% / 2%)一个字都别改。</b>
          </p>
        </div>
      </header>
      <main className="join-main brand-main">
        <section className="reveal visible">
          <h2>标志</h2>
          <div className="asset-grid">
            <Asset src={`${B}/icon_1024.png`} label="App 图标"
              links={[['SVG', `${B}/icon.svg`], ['PNG', `${B}/icon_1024.png`]]} />
            <Asset src={`${B}/logo_horizontal_dark.png`} label="横版标志 · 深色背景用"
              links={[['SVG', `${B}/logo_horizontal_dark.svg`], ['PNG', `${B}/logo_horizontal_dark.png`]]} />
            <Asset src={`${B}/logo_horizontal_light.png`} label="横版标志 · 浅色背景用" light
              links={[['SVG', `${B}/logo_horizontal_light.svg`], ['PNG', `${B}/logo_horizontal_light.png`]]} />
          </div>
        </section>

        <section className="reveal visible">
          <h2>品牌色</h2>
          <div className="swatches">
            <div className="swatch" style={{ background: 'linear-gradient(135deg,#FF7A45,#E1251B)' }}>
              <b>品牌渐变</b><span>#FF7A45 → #E1251B</span></div>
            <div className="swatch" style={{ background: '#FFD34D', color: '#5C3A00' }}>
              <b>点赞黄</b><span>#FFD34D</span></div>
            <div className="swatch" style={{ background: '#FF5A1F' }}>
              <b>炉火橙(App 行动色)</b><span>#FF5A1F</span></div>
            <div className="swatch" style={{ background: '#0E8A5F' }}>
              <b>账目绿(钱的颜色)</b><span>#0E8A5F</span></div>
          </div>
        </section>

        <section className="reveal visible">
          <h2>海报与传单</h2>
          <p className="section-lede">A5 传单有 300dpi 打印版 PDF,直接拿去印;
            桌贴贴收银台,海报贴店门口。</p>
          <div className="asset-grid">
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
          <div className="cta">
            <a className="btn primary" href={`${B}/flyers_print_a5_300dpi.pdf`} download>
              下载传单打印版 PDF(A5 · 300dpi)</a>
          </div>
        </section>

        <section className="reveal visible">
          <h2>社媒背景图</h2>
          <p className="section-lede">给自媒体账号主页用的封面/背景,按各平台尺寸出好了。</p>
          <div className="asset-grid">
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
      </main>
      <footer>
        <div><a href="/">← 回超级赞首页</a></div>
        <div className="muted">物料可自由转发传播;商用印刷请保持数字承诺原样</div>
        <div className="muted">
          <a href="https://beian.miit.gov.cn" target="_blank" rel="noreferrer">陕ICP备2025064101号-2</a>
        </div>
      </footer>
    </>
  )
}
