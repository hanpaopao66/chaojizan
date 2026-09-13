import React, { useEffect, useMemo, useState } from 'react'

import { Caption, Ease, Film, MONO, P, SANS, SERIF, clamp, enter, tween, useFilm, useWidth } from './kit.jsx'

/* 开城地图:一个省一个省点亮 —— 配 docs/OPEN-A-CITY.md(开城手册)。放在开源仓页底部。
 *
 * 省界不是画的:chinaGeo.js 由 scripts/gen_site_geo.py 从大屏在用的
 * web/public/geo/china.json 投影、抽稀而来,点位是那份数据里的省级标注点(cp)。
 * 数据是动态 import 的(gzip 约 15KB),不进开源仓页的主 chunk。
 *
 * ⚠️ 口径:点亮**不代表已开城**,画面上写明「示意」。真开了哪些城得读后台;
 * 拿动画替运营数据撒谎,和做这个平台的理由相反。
 * 成本那一栏逐项取自开城手册第 0 节(2026-08 口径)。
 *
 * 和原稿不一样:
 * - 原稿的省界数据少了上海和澳门,也没有南海诸岛。这里 34 个省级行政区一个不少,
 *   北纬 17.5° 以南的岛礁画在右下角「南海诸岛」附图里;原稿也没有南海断续线,
 *   这里十段全画在附图里,落在主图画幅里的三段主图也画(数据见 scripts/gen_site_geo.py);
 * - 原稿在陕西标「第一座城」。仓库里查不到「第一座城在哪」的记录,
 *   查得到的是运营主体在陕西(页脚、备案号)—— 标成「官方实例」;
 * - 手册自己写着「截至 2026-08 还没有第三方照着走通过」,这句也放进来。 */

// @serif-cjk-begin
// 字幕大字(衬线显示,这个圈里的字才会进官网的衬线子集)
const TITLES = [
  '这不是一张「已开城」地图。',
  '官方实例，由陕西的一家公司运营。',
  '开一座城，每月一百多块钱。',
  '开城手册在仓库里。你的城市，你自己开。',
]
const HOME_LABEL = '官方实例'
const COST_AMOUNT = ['¥60–100/月', '¥30–60/年', '约 ¥0.045/条', '¥0', '¥0']
const SUM = '¥100 +'
// @serif-cjk-end

/* 开城成本,逐项取自开城手册第 0 节;金额那一列在上面的衬线圈里 */
const COST = [
  ['服务器', '一台 2C4G VPS'],
  ['域名', 'ICP 备案免费，1–3 周'],
  ['短信', '阿里云，验证码'],
  ['地图', '腾讯位置服务，个人开发者免费额度够起步'],
  ['TLS 证书', "Let's Encrypt，脚本自动续期"],
].map((c, i) => [...c, COST_AMOUNT[i]])

/* 字幕底下那行说明(黑体,不进衬线子集) */
const DETAILS = [
  '是一张「谁都能开」的地图 —— 省界来自官网大屏在用的那份地理数据。',
  '业务跑在家用宽带的旧电脑上，云端只买了最便宜的一台机器做入口。',
  '服务器、域名、短信、地图、证书，逐项写在开城手册里 —— 这个数字本身就是「5% 能活」的证据之一。',
  'docs/OPEN-A-CITY.md：从零起一套实例，每一步花什么钱、办什么证、错了怎么看出来。',
]

const CUE = { draw: 0.3, home: 3.4, spread: 5.0, cost: 6.0, sum: 11.4, close: 13.2 }
const TOTAL = 17.4
const STILL = 12.6

/* 先亮的是运营主体所在的陕西;其余按这个顺序一个个脉冲,不随机 ——
 * 随机的话每次重播都不一样,没法对帧校对 */
const HOME = '陕西省'
const ORDER = ['四川省', '河南省', '湖北省', '广东省', '江苏省', '浙江省', '上海市', '山东省', '湖南省',
  '福建省', '河北省', '安徽省', '江西省', '重庆市', '云南省', '贵州省', '山西省', '辽宁省',
  '广西壮族自治区', '黑龙江省', '吉林省', '甘肃省', '新疆维吾尔自治区', '内蒙古自治区', '北京市',
  '天津市', '海南省', '宁夏回族自治区', '青海省', '西藏自治区', '台湾省', '香港特别行政区', '澳门特别行政区']

export default function OpenCityMapFilm() {
  const film = useFilm(TOTAL, { still: STILL, poster: 0.5 })
  const { T } = film
  const w = useWidth(film.box)
  const narrow = w > 0 && w < 780
  const [geo, setGeo] = useState(null)
  useEffect(() => {
    let alive = true
    import('./chinaGeo.js').then(m => { if (alive) setGeo(m.default) }).catch(() => {})
    return () => { alive = false }
  }, [])

  // 手机上地图只有三百来像素宽(画幅 1000 缩到 0.3 倍),点和字按画幅单位画会小到看不见
  const u = narrow ? 1.9 : 1

  // 附图里的东西不随时间变,每帧重建 160 多个节点不值当
  const inset = useMemo(() => geo && (
    <>
      <rect x={geo.inset.x} y={geo.inset.y} width={geo.inset.w} height={geo.inset.h}
        fill={P.paper} stroke={P.ink3} strokeWidth="1.2" />
      <g clipPath="url(#sz-scs-clip)">
        <g transform={`translate(${geo.inset.x} ${geo.inset.y}) scale(${geo.inset.k}) translate(${-geo.inset.ox} ${-geo.inset.oy})`}>
          {geo.provinces.map(p => (
            <path key={p.n} d={p.d} fill={P.alt} stroke={P.line} strokeWidth="1" vectorEffect="non-scaling-stroke" />
          ))}
          {geo.islands.map(([x, y]) => (
            <circle key={`${x},${y}`} cx={x} cy={y} r={2.4 * u * u} fill={P.ink3} />
          ))}
          {/* 南海断续线十段:细长多边形缩小后不到一像素,靠不随缩放的描边画出线宽 */}
          {geo.dashes.map(d => (
            <path key={d} d={d} fill={P.ink2} stroke={P.ink2} strokeWidth={1.2 * u} vectorEffect="non-scaling-stroke" />
          ))}
        </g>
      </g>
      <text x={geo.inset.x + geo.inset.w - 8} y={geo.inset.y + geo.inset.h - 10} textAnchor="end"
        fontSize={15 * u} fill={P.ink2} fontFamily={SANS}>南海诸岛</text>
    </>
  ), [geo, u])

  const byName = {}
  for (const p of geo?.provinces ?? []) byName[p.n] = p
  const home = byName[HOME]
  const drawEnd = CUE.draw + (geo ? geo.provinces.length : 34) * 0.06 + 0.4

  const capIdx = T >= CUE.close ? 3 : T >= CUE.cost ? 2 : T >= CUE.home ? 1 : 0

  return (
    <Film film={film} label="示意 · 点位是省级标注点，不代表已开城" loop="循环 · 17 秒"
      summary="示意动画：一张中国省界图，省级标注点一个个亮起，意思是谁都能在自己的城市开一套实例，不代表已经开城。官方实例由陕西的一家公司运营。开一座城每月一百多块钱：服务器每月 60 到 100 元，域名每年 30 到 60 元，短信约 0.045 元一条，地图和证书不要钱，逐项写在开源仓的开城手册里。"
      style={{ background: P.card, border: `1px solid ${P.line}`, padding: narrow ? '20px 16px' : '24px 26px' }}>
      <div style={{ display: 'grid', gridTemplateColumns: narrow ? 'minmax(0,1fr)' : 'minmax(0,1fr) 300px', gap: 20, alignItems: 'start' }}>
        {/* 地图 */}
        <div style={{ background: P.paper, borderRadius: 12, padding: 12 }}>
          {geo ? (
            <svg viewBox={geo.viewBox} width="100%" style={{ display: 'block', overflow: 'visible' }}>
              <defs>
                <clipPath id="sz-scs-clip"><rect x={geo.inset.x} y={geo.inset.y} width={geo.inset.w} height={geo.inset.h} /></clipPath>
              </defs>
              {/* 省界:逐个淡入 */}
              {geo.provinces.map((p, i) => (
                <path key={p.n} d={p.d} fill={P.alt} stroke={P.line} strokeWidth="1.4" strokeLinejoin="round"
                  style={{ opacity: tween(T, { start: CUE.draw + i * 0.06, end: CUE.draw + i * 0.06 + 0.4 }) }} />
              ))}
              {/* 南海断续线在主图画幅里的那几段(台湾以东、巴士海峡、东沙以东),和省界一起出来 */}
              <g style={{ opacity: tween(T, { start: drawEnd - 0.4, end: drawEnd }) }}>
                {geo.dashMain.map(i => (
                  <path key={i} d={geo.dashes[i]} fill={P.ink2} stroke={P.ink2} strokeWidth={1.2 * u} vectorEffect="non-scaling-stroke" />
                ))}
              </g>
              {/* 南海诸岛附图:同一个投影缩小,岛礁太小,画成点;断续线十段全在这里 */}
              <g style={{ opacity: tween(T, { start: drawEnd - 0.4, end: drawEnd }) }}>{inset}</g>
              {/* 其余省份的点:一个个脉冲亮起,又落回虚态 */}
              {ORDER.map((name, i) => {
                const p = byName[name]
                if (!p) return null
                const start = CUE.spread + i * 0.22
                const k = tween(T, { start, end: start + 0.5, ease: Ease.spring })
                const fade = tween(T, { from: 1, to: 0.45, start: start + 1.0, end: start + 2.2 })
                return (
                  <g key={name} style={{ opacity: clamp(k, 0, 1) }}>
                    <circle cx={p.cp[0]} cy={p.cp[1]} r={(5 + 3 * (1 - fade)) * u} fill={P.clay} opacity={0.32 * fade} />
                    <circle cx={p.cp[0]} cy={p.cp[1]} r={3.4 * u} fill={P.clay} opacity={0.55 + 0.45 * fade} />
                  </g>
                )
              })}
              {/* 官方实例:三圈波纹 + 实点 */}
              {home && (
                <g>
                  {[0, 1, 2].map(i => {
                    const start = CUE.home + i * 0.55
                    if (T < start) return null
                    const k = tween(T, { start, end: start + 1.6 })
                    return (
                      <circle key={i} cx={home.cp[0]} cy={home.cp[1]} r={(6 + k * 46) * u}
                        fill="none" stroke={P.clay} strokeWidth="1.6" opacity={0.5 * (1 - k)} />
                    )
                  })}
                  <circle cx={home.cp[0]} cy={home.cp[1]} r={10 * u} fill={P.claySoft}
                    style={{ opacity: tween(T, { start: CUE.home, end: CUE.home + 0.4 }) }} />
                  <circle cx={home.cp[0]} cy={home.cp[1]} r={5 * u} fill={P.clay}
                    style={{ opacity: tween(T, { start: CUE.home, end: CUE.home + 0.3 }) }} />
                  <text x={home.cp[0] + 16 * u} y={home.cp[1] + 7 * u} fontSize={22 * u} fontWeight="600" fill={P.ink}
                    fontFamily={SERIF} style={{ opacity: tween(T, { start: CUE.home + 0.3, end: CUE.home + 0.8 }) }}>
                    {HOME_LABEL}
                  </text>
                </g>
              )}
            </svg>
          ) : (
            // 数据到之前先把地图的高度占住(padding 撑比例:aspect-ratio 在 iOS 15 以前不认)
            <div style={{ paddingTop: '71.1%' }} />
          )}
        </div>

        {/* 开城成本 */}
        <div style={{ border: `1px solid ${P.line}`, borderRadius: 12, overflow: 'hidden', ...enter(T, CUE.cost - 0.5) }}>
          <div style={{ height: 3, background: P.hold }} />
          <div style={{ padding: '14px 16px' }}>
            <div style={{ fontSize: 11, letterSpacing: 1.2, color: P.ink2 }}>开一座城要花多少 · 2026-08 口径</div>
            <div style={{ display: 'flex', flexDirection: 'column', fontSize: 13, marginTop: 4 }}>
              {COST.map((c, i) => {
                const k = tween(T, { start: CUE.cost + i * 0.45, end: CUE.cost + i * 0.45 + 0.4 })
                return (
                  <div key={c[0]} style={{
                    borderTop: `1px solid ${P.line}`, padding: '9px 0', display: 'flex', gap: 8, alignItems: 'baseline',
                    opacity: k, transform: `translateY(${(1 - k) * 6}px)`,
                  }}>
                    <span style={{ flex: 1, minWidth: 0 }}>
                      <span style={{ fontWeight: 600 }}>{c[0]}</span>
                      <span style={{ display: 'block', fontSize: 11.5, color: P.ink3 }}>{c[1]}</span>
                    </span>
                    <span style={{ fontFamily: SERIF, fontWeight: 600, fontVariantNumeric: 'tabular-nums', whiteSpace: 'nowrap', color: c[2] === '¥0' ? P.earn : P.ink }}>{c[2]}</span>
                  </div>
                )
              })}
            </div>
            <div style={{ marginTop: 12, padding: '12px 14px', borderRadius: 10, background: P.claySoft, opacity: tween(T, { start: CUE.sum, end: CUE.sum + 0.5 }) }}>
              <div style={{ fontSize: 12, color: P.ink2 }}>合计</div>
              <div style={{ fontFamily: SERIF, fontWeight: 600, fontSize: 24, fontVariantNumeric: 'tabular-nums' }}>
                {SUM}<span style={{ fontFamily: SANS, fontSize: 14, fontWeight: 400, color: P.ink2 }}> / 月 · 一个城市</span>
              </div>
            </div>
            <div style={{ fontSize: 11.5, color: P.ink3, marginTop: 10, lineHeight: 1.7 }}>
              微信支付商户号 ¥0（收单 0.6% 另算，不在平台 5% 里）。ICP 备案、短信签名要资质，手册里写了办多久。
              手册截至 2026-08 还没有第三方照着走通过 —— 卡在哪一步，都算手册的 bug。
            </div>
          </div>
        </div>
      </div>

      <Caption titles={TITLES} details={DETAILS} index={capIdx} narrow={narrow} detailColor={P.ink2}>
        <div style={{ fontFamily: MONO, fontSize: 12, color: P.ink3, marginTop: 4 }}>docs/OPEN-A-CITY.md · web/public/geo/china.json</div>
      </Caption>
    </Film>
  )
}
