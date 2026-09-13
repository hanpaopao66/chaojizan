import React, { useCallback, useMemo, useRef, useState } from 'react'

import { geo, project, provinceAt, shortCity } from './geo.js'

/* 中央地图:平面省界 + 城市点 + 新单涟漪(设计稿「超级赞运营大屏」的中央区)。
 *
 * 原来这里是 three.js 的 3D 地图(拖拽旋转、光柱、星点)。稿子换成了平面图:
 * 省份一个色、城市点按累计单量定大小、新订单进来在那座城泛一圈涟漪。
 *
 * 和稿子不一样的地方:
 * - 稿子自带的省界(sz-anim/sz-china-geo.js)少了上海、澳门,也没有南海诸岛。
 *   这里用仓库里的 films/chinaGeo.js:34 个省级行政区,岛礁画进右下角附图,
 *   南海断续线十段全在附图里、落在主图画幅里的三段主图也画;
 * - 稿子在前三座城上一直循环涟漪。这里**一单一圈**:只在轮询拿到新订单时,
 *   在那一单的城市泛一次 —— 没有新单,地图就是静的。循环的涟漪看着像单子
 *   一直在进来,那是拿动画替运营数据说话;
 * - 悬停省份给一个浮层:这个省在城市 TOP10 里有哪几座城、各多少单。
 *   接口只给 TOP10 城市,所以浮层只说 TOP10 里的事,不说「这个省没有单」。 */

/* 城市名只标第一名(同稿子):点的右边,出画幅就放左边 */
function topLabel(dots) {
  const d = dots[0]
  if (!d) return null
  const name = shortCity(d.city)
  const right = d.x + d.r + 5.5 + name.length * 15 <= geo.w
  return { key: d.city, name, x: right ? d.x + d.r + 5.5 : d.x - d.r - 5.5,
    y: d.y + 5.5, anchor: right ? 'start' : 'end' }
}

/* 南海诸岛附图:同一个投影缩小,贴右下角;岛礁太小,画成点;南海断续线十段全画 */
const Inset = React.memo(function Inset() {
  const { x, y, w, h, k, ox, oy } = geo.inset
  return (
    <g className="sc-inset" aria-hidden="true">
      <defs>
        <clipPath id="sc-scs-clip"><rect x={x} y={y} width={w} height={h} /></clipPath>
      </defs>
      <rect className="frame" x={x} y={y} width={w} height={h} />
      <g clipPath="url(#sc-scs-clip)">
        <g transform={`translate(${x} ${y}) scale(${k}) translate(${-ox} ${-oy})`}>
          {geo.provinces.map(p => <path key={p.n} d={p.d} />)}
          {geo.islands.map(([cx, cy]) => <circle key={`${cx},${cy}`} cx={cx} cy={cy} r="2.4" />)}
          {geo.dashes.map(d => <path key={d} className="dash" d={d} />)}
        </g>
      </g>
      <text x={x + w - 8} y={y + h - 10} textAnchor="end">南海诸岛</text>
    </g>
  )
})

export default function ChinaMap({ cities, pulses }) {
  const boxRef = useRef(null)
  const [tip, setTip] = useState(null)   // {name, x, y},在地图容器的布局坐标里

  const dots = useMemo(() => {
    const placed = (cities || []).filter(c => c.lat != null && c.lng != null)
    const max = Math.max(1, ...placed.map(c => c.orders))
    return placed.map(c => {
      const [x, y] = project(c.lng, c.lat)
      return { ...c, x, y, r: 3 + 4.5 * Math.sqrt(c.orders / max), prov: provinceAt(x, y) }
    })
  }, [cities])
  const label = useMemo(() => topLabel(dots), [dots])

  /* 落点:有坐标用坐标;跑腿单接口不给坐标(服务主体的 (0,0) 是占位),
     按城市名找 TOP10 里那座城的点;都找不到就不泛 */
  const rings = useMemo(() => (pulses || []).map(p => {
    let xy = p.lat != null && p.lng != null ? project(p.lng, p.lat) : null
    if (!xy) {
      const d = dots.find(c => c.city === p.city)
      if (d) xy = [d.x, d.y]
    }
    return xy && { key: p.key, x: xy[0], y: xy[1], delay: p.delay }
  }).filter(Boolean), [pulses, dots])

  const onMove = useCallback(e => {
    const name = e.target.getAttribute('data-name')
    const box = boxRef.current
    if (!name || !box) return
    // 整屏是 transform: scale 缩放的:鼠标在视口坐标里,浮层要放回未缩放的布局坐标
    const r = box.getBoundingClientRect()
    const k = r.width / box.offsetWidth || 1
    setTip({ name, x: (e.clientX - r.left) / k, y: (e.clientY - r.top) / k })
  }, [])

  // 省界 34 条路径不随数据变,悬停只改浮层,不重画它们(高亮走 CSS :hover)
  const provinces = useMemo(() => (
    <g className="sc-provinces" onMouseMove={onMove}>
      {geo.provinces.map(p => <path key={p.n} d={p.d} data-name={p.n} />)}
    </g>
  ), [onMove])

  const inProv = tip ? dots.filter(d => d.prov === tip.name) : []

  return (
    <div className="sc-map" ref={boxRef} onMouseLeave={() => setTip(null)}>
      <svg viewBox={geo.viewBox} role="img"
        aria-label="全国订单分布示意图:城市点按累计订单数定大小,新订单进来时在所在城市泛一圈涟漪">
        {provinces}
        {/* 南海断续线在主图画幅里的那几段(台湾以东、巴士海峡、东沙以东);十段全在附图里 */}
        <g className="sc-dashline" aria-hidden="true">
          {geo.dashMain.map(i => <path key={i} d={geo.dashes[i]} />)}
        </g>
        <Inset />
        <g className="sc-dots">
          {dots.map(d => <circle key={d.city} cx={d.x} cy={d.y} r={d.r} />)}
        </g>
        <g className="sc-ripples">
          {rings.map(p => (
            <circle key={p.key} className="sc-ripple" cx={p.x} cy={p.y} r="58"
              style={{ animationDelay: `${p.delay}s` }} />
          ))}
        </g>
        {/* 只标第一名:关中几座城在图上只隔几毫米,标多了叠成一团;
            哪座城多少单,右栏 TOP10 逐行写着,地图只管「在哪儿」(稿子原话) */}
        {label && (
          <text className="sc-city-name" x={label.x} y={label.y} textAnchor={label.anchor}>{label.name}</text>
        )}
      </svg>
      {tip && (
        <div className="sc-map-tip" style={{ left: tip.x, top: tip.y }}>
          <b>{tip.name}</b>
          {inProv.length
            ? inProv.map(d => (
              <span key={d.city} className="row">
                {shortCity(d.city)} <span className="n">{d.orders.toLocaleString('zh-CN')}</span> 单
              </span>))
            : <span className="row muted">城市累计订单 TOP10 里暂无这里的城市</span>}
        </div>
      )}
    </div>
  )
}
