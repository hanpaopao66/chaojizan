/* 大屏地图的投影和「这个点在哪个省」—— 纯函数,verify_map.mjs 在 node 里也直接用。
 *
 * 省界用 films/chinaGeo.js(scripts/gen_site_geo.py 从 web/public/geo/china.json 生成:
 * 34 个省级行政区一个不少,北纬 17.5° 以南的岛礁画进「南海诸岛」附图)。这里只读引用,
 * 不另存一份 —— 设计稿自带的 sz-china-geo.js 少了上海、澳门,也没有南海诸岛。
 *
 * 投影和生成脚本同一套:等距圆柱,经度按北纬 36° 压缩,画幅宽 1000。
 * 常数是脚本从 china.json 算出来的画幅范围(北纬 17.5° 以北全部多边形的外包框),
 * 城市点、订单落点都用它投到省界同一个坐标系里。verify_map.mjs 会拿 china.json 里
 * 34 个省的标注点(cp)投一遍,和 chinaGeo.js 里的 cp 逐个比 —— 常数改了对不上会报。 */
import geo from '../films/chinaGeo.js'

export { geo }

const K = Math.cos((36 * Math.PI) / 180)
const LON0 = 73.5
const LON1 = 135.1
const LAT1 = 53.56
const S = geo.w / ((LON1 - LON0) * K)

/** 经纬度 → 省界画幅坐标 [x, y] */
export function project(lng, lat) {
  return [(lng - LON0) * K * S, (LAT1 - lat) * S]
}

/* 路径只有 M / L / Z 三种命令(生成脚本就这么写的),拆成一圈圈的点 */
function ringsOf(d) {
  return d.split('M').filter(Boolean).map(seg => seg.replace(/Z/g, '').split('L')
    .map(pt => pt.trim().split(/\s+/).map(Number)))
}

function inRing(x, y, ring) {
  let inside = false
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const [xi, yi] = ring[i]
    const [xj, yj] = ring[j]
    if ((yi > y) !== (yj > y) && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) inside = !inside
  }
  return inside
}

const area = ring => Math.abs(ring.reduce((s, [x, y], i) => {
  const [x2, y2] = ring[(i + 1) % ring.length]
  return s + x * y2 - x2 * y
}, 0)) / 2

const SHAPES = geo.provinces.map(p => {
  const rings = ringsOf(p.d)
  return { n: p.n, rings, area: rings.reduce((s, r) => s + area(r), 0) }
})

/** 画幅坐标落在哪个省;都不在(海上、境外)回 null。
 *  抽稀过的省界在交界处可能有一丝重叠,重叠时取面积小的那个 —— 小省不会被大省吞掉 */
export function provinceAt(x, y) {
  let hit = null
  for (const s of SHAPES) {
    if (s.rings.some(r => inRing(x, y, r)) && (!hit || s.area < hit.area)) hit = s
  }
  return hit ? hit.n : null
}

/** 「西安市」→「西安」;「锡林郭勒盟」这类不是「X市」的原样留着 */
export const shortCity = name => (name && name.length > 2 && name.endsWith('市')
  ? name.slice(0, -1) : name || '')
