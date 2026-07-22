import { Canvas, useFrame, useThree } from '@react-three/fiber'
import React, { useEffect, useMemo, useRef, useState } from 'react'
import * as THREE from 'three'

import { REDUCED, makeGlowTexture } from '../three-utils.js'

/* 3D 中国地图:省份 GeoJSON 挤出成板块,城市按累计订单立光柱,
   新订单落点扩散涟漪。投影与 ChinaNodes 同一套:经纬度线性缩放。
   交互:拖拽旋转/俯仰、滚轮或双指缩放、省份悬停高亮+数据浮层;
   松手 5 秒后缓速回正并恢复自动摆动(投屏无人值守不跑丢)。 */

const S = 8                    // 经纬度 → 世界单位
const C = [104, 35.5]          // 画面中心(经度,纬度)
const px = lon => (lon - C[0]) / S
const pz = lat => -(lat - C[1]) / S
const DEPTH = 0.14             // 板块厚度

const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v))

/* 射线法:点是否在多边形环内(经纬度坐标) */
function pointInRing(lng, lat, ring) {
  let inside = false
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const [xi, yi] = ring[i]
    const [xj, yj] = ring[j]
    if ((yi > lat) !== (yj > lat) &&
        lng < ((xj - xi) * (lat - yi)) / (yj - yi) + xi) {
      inside = !inside
    }
  }
  return inside
}

/* 每省累计订单:城市点(来自 /screen/stats)归属到省份多边形,前端聚合 */
function provinceOrders(geo, cities) {
  const sums = {}
  if (!geo) return sums
  for (const f of geo.features) {
    const name = f.properties.name
    const polys = f.geometry.type === 'Polygon'
      ? [f.geometry.coordinates] : f.geometry.coordinates
    let total = 0
    for (const c of cities) {
      for (const rings of polys) {
        if (pointInRing(c.lng, c.lat, rings[0])) { total += c.orders; break }
      }
    }
    sums[name] = total
  }
  return sums
}

/* 省份板块 + 顶面描边;悬停省高亮并上报(浮层在外层渲染) */
function Provinces({ geo, hovered, onHover }) {
  const { items, lines } = useMemo(() => {
    const items = []
    const linePts = []
    for (const f of geo.features) {
      const name = f.properties.name
      const polys = f.geometry.type === 'Polygon'
        ? [f.geometry.coordinates] : f.geometry.coordinates
      for (const rings of polys) {
        const shape = new THREE.Shape(
          rings[0].map(([lon, lat]) => new THREE.Vector2(px(lon), -pz(lat))))
        for (const hole of rings.slice(1)) {
          shape.holes.push(new THREE.Path(
            hole.map(([lon, lat]) => new THREE.Vector2(px(lon), -pz(lat)))))
        }
        items.push({
          name,
          geom: new THREE.ExtrudeGeometry(shape,
            { depth: DEPTH, bevelEnabled: false }),
        })
        const top = rings[0]
        for (let i = 0; i < top.length; i++) {
          const [a1, b1] = top[i]
          const [a2, b2] = top[(i + 1) % top.length]
          linePts.push(px(a1), DEPTH + 0.004, pz(b1),
                       px(a2), DEPTH + 0.004, pz(b2))
        }
      }
    }
    const lines = new THREE.BufferGeometry()
    lines.setAttribute('position',
      new THREE.Float32BufferAttribute(linePts, 3))
    return { items, lines }
  }, [geo])
  useEffect(() => () => {
    items.forEach(it => it.geom.dispose()); lines.dispose()
  }, [items, lines])

  return (
    <group>
      {/* -90° 绕 X 放平:shape 平面(x=东, y=北) → 地面(x=东, -z=北),挤出朝上 */}
      {items.map((it, i) => {
        const hot = hovered === it.name
        return (
          <mesh key={i} geometry={it.geom} rotation={[-Math.PI / 2, 0, 0]}
            onPointerMove={e => {
              e.stopPropagation()
              onHover(it.name, e.nativeEvent)
            }}
            onPointerOut={() => onHover(null)}>
            {/* 顶/底面亮色,侧壁暗色(ExtrudeGeometry 材质组 0/1) */}
            <meshLambertMaterial attach="material-0"
              color={hot ? '#2E5CA8' : '#16274A'}
              emissive={hot ? '#3A1B08' : '#0B1730'} />
            <meshLambertMaterial attach="material-1"
              color={hot ? '#132648' : '#0A1428'} emissive="#050B18" />
          </mesh>
        )
      })}
      {/* 描边点直接按世界坐标生成,无需旋转 */}
      <lineSegments geometry={lines}>
        <lineBasicMaterial color="#3D6BB3" transparent opacity={0.75} />
      </lineSegments>
    </group>
  )
}

/* 城市文字标签(canvas 贴图 sprite,只给 TOP5 城市挂) */
function makeLabelTexture(name, count) {
  const c = document.createElement('canvas')
  c.width = 256; c.height = 96
  const ctx = c.getContext('2d')
  ctx.textAlign = 'center'
  ctx.font = '600 30px -apple-system, "PingFang SC", sans-serif'
  ctx.fillStyle = 'rgba(235,241,250,.95)'
  ctx.fillText(name, 128, 38)
  ctx.font = '28px -apple-system, "PingFang SC", sans-serif'
  ctx.fillStyle = 'rgba(255,140,80,.95)'
  ctx.fillText(count, 128, 74)
  const t = new THREE.CanvasTexture(c)
  t.anisotropy = 4
  return t
}

const fmtWan = v => (v >= 1e4 ? `${(v / 1e4).toFixed(1)}万单` : `${v}单`)

function CityPillars({ cities }) {
  const glow = useMemo(makeGlowTexture, [])
  const max = Math.max(1, ...cities.map(c => c.orders))
  const items = useMemo(() => cities.map((c, i) => ({
    ...c,
    x: px(c.lng), z: pz(c.lat),
    h: 0.18 + Math.sqrt(c.orders / max) * 0.85,
    labeled: i < 5,
  })), [cities, max])
  const labels = useMemo(
    () => items.filter(c => c.labeled)
      .map(c => ({ ...c, tex: makeLabelTexture(c.city, fmtWan(c.orders)) })),
    [items])
  useEffect(() => () => labels.forEach(l => l.tex.dispose()), [labels])

  return (
    <group>
      {items.map(c => (
        <group key={c.city} position={[c.x, 0, c.z]}>
          <mesh position={[0, DEPTH + c.h / 2, 0]}>
            <cylinderGeometry args={[0.022, 0.034, c.h, 6]} />
            <meshBasicMaterial color="#FF5A1F" transparent opacity={0.85} />
          </mesh>
          <sprite position={[0, DEPTH + c.h + 0.05, 0]} scale={[0.22, 0.22, 1]}>
            <spriteMaterial map={glow} color="#FF8C50" transparent
              depthWrite={false} blending={THREE.AdditiveBlending} />
          </sprite>
          {/* 底座光环 */}
          <mesh position={[0, DEPTH + 0.006, 0]} rotation={[-Math.PI / 2, 0, 0]}>
            <ringGeometry args={[0.05, 0.085, 32]} />
            <meshBasicMaterial color="#FF5A1F" transparent opacity={0.35}
              side={THREE.DoubleSide} depthWrite={false} />
          </mesh>
        </group>
      ))}
      {labels.map(c => (
        <sprite key={c.city} position={[c.x, DEPTH + c.h + 0.3, c.z]}
          scale={[0.82, 0.31, 1]}>
          <spriteMaterial map={c.tex} transparent depthWrite={false} />
        </sprite>
      ))}
    </group>
  )
}

/* 新订单涟漪:落点处一圈扩散光环,2 秒淡出 */
function Pulses({ pulses }) {
  const group = useRef()
  useFrame(() => {
    const now = performance.now()
    group.current?.children.forEach(m => {
      const age = (now - m.userData.born) / 2000
      if (age >= 1) { m.visible = false; return }
      const s = 0.15 + age * 1.4
      m.scale.set(s, s, s)
      m.material.opacity = 0.7 * (1 - age)
    })
  })
  return (
    <group ref={group}>
      {pulses.map(p => (
        <mesh key={p.key} position={[px(p.lng), DEPTH + 0.01, pz(p.lat)]}
          rotation={[-Math.PI / 2, 0, 0]}
          userData={{ born: p.born }}>
          <ringGeometry args={[0.42, 0.5, 48]} />
          <meshBasicMaterial color="#FFB84D" transparent opacity={0.7}
            side={THREE.DoubleSide} depthWrite={false} />
        </mesh>
      ))}
    </group>
  )
}

/* 背景星点 */
function Stars() {
  const glow = useMemo(makeGlowTexture, [])
  const positions = useMemo(() => {
    const n = 320
    const a = new Float32Array(n * 3)
    for (let i = 0; i < n; i++) {
      a[i * 3] = (Math.random() - 0.5) * 16
      a[i * 3 + 1] = -1.2 + Math.random() * 0.9
      a[i * 3 + 2] = (Math.random() - 0.5) * 12
    }
    return a
  }, [])
  return (
    <points>
      <bufferGeometry>
        <bufferAttribute attach="attributes-position"
          count={positions.length / 3} array={positions} itemSize={3} />
      </bufferGeometry>
      <pointsMaterial size={0.045} map={glow} color="#3D5A96" transparent
        opacity={0.55} depthWrite={false} sizeAttenuation />
    </points>
  )
}

/* 交互:拖拽(单指)旋转/俯仰、滚轮与双指缩放;只改共享状态,应用在 Rig */
function InteractionControls({ inter }) {
  const { gl } = useThree()
  useEffect(() => {
    const el = gl.domElement
    el.style.touchAction = 'none'
    const pointers = new Map()
    let lastPinch = null

    const down = e => {
      pointers.set(e.pointerId, [e.clientX, e.clientY])
      inter.last = performance.now()
    }
    const move = e => {
      if (pointers.size > 0) inter.last = performance.now()
      if (!pointers.has(e.pointerId)) return
      const prev = pointers.get(e.pointerId)
      pointers.set(e.pointerId, [e.clientX, e.clientY])
      if (pointers.size === 1) {
        inter.yaw += (e.clientX - prev[0]) * 0.004
        inter.pitch = clamp(inter.pitch + (e.clientY - prev[1]) * 0.002,
          -0.25, 0.35)
      } else if (pointers.size === 2) {
        const pts = [...pointers.values()]
        const d = Math.hypot(pts[0][0] - pts[1][0], pts[0][1] - pts[1][1])
        if (lastPinch) inter.zoom = clamp(inter.zoom * (lastPinch / d), 0.55, 2.0)
        lastPinch = d
      }
    }
    const up = e => { pointers.delete(e.pointerId); lastPinch = null }
    const wheel = e => {
      e.preventDefault()
      inter.last = performance.now()
      inter.zoom = clamp(inter.zoom * (1 + e.deltaY * 0.001), 0.55, 2.0)
    }
    el.addEventListener('pointerdown', down)
    window.addEventListener('pointermove', move)
    window.addEventListener('pointerup', up)
    window.addEventListener('pointercancel', up)
    el.addEventListener('wheel', wheel, { passive: false })
    return () => {
      el.removeEventListener('pointerdown', down)
      window.removeEventListener('pointermove', move)
      window.removeEventListener('pointerup', up)
      window.removeEventListener('pointercancel', up)
      el.removeEventListener('wheel', wheel)
    }
  }, [gl, inter])
  return null
}

/* 摆动 + 用户操作合成:操作时自动摆动淡出;空闲 5 秒后用户偏移缓速归零 */
function Rig({ inter, children }) {
  const ref = useRef()
  const { camera } = useThree()
  const base = useMemo(() => camera.position.clone(), [camera])
  useFrame(({ clock }) => {
    const g = ref.current
    if (!g) return
    const idle = performance.now() - inter.last > 5000
    if (idle) {
      inter.yaw *= 0.97
      inter.pitch *= 0.97
      inter.zoom += (1 - inter.zoom) * 0.03
      inter.swayW = clamp(inter.swayW + 0.01, 0, 1)
    } else {
      inter.swayW = clamp(inter.swayW - 0.12, 0, 1)
    }
    const t = clock.elapsedTime
    const sway = REDUCED ? 0 : inter.swayW
    g.rotation.y = Math.sin(t * 0.14) * 0.055 * sway + inter.yaw
    g.rotation.x = inter.pitch
    g.position.y = Math.sin(t * 0.4) * 0.02 * sway
    camera.position.copy(base).multiplyScalar(inter.zoom)
    camera.lookAt(0, -0.3, -0.3)
  })
  return <group ref={ref}>{children}</group>
}

export default function ChinaMap3D({ cities, pulses }) {
  const [geo, setGeo] = useState(null)
  const [hover, setHover] = useState(null)   // {name, orders, x, y}
  const interRef = useRef({ yaw: 0, pitch: 0, zoom: 1, last: -1e9, swayW: 1 })
  const orders = useMemo(() => provinceOrders(geo, cities), [geo, cities])

  useEffect(() => {
    fetch(`${import.meta.env.BASE_URL}geo/china.json`)
      .then(r => r.json()).then(setGeo).catch(() => {})
  }, [])

  const onHover = (name, ev) => {
    if (!name) { setHover(null); return }
    // offsetX/Y 在画布未缩放坐标系,与整屏 transform 缩放同空间,可直接定位
    setHover({ name, orders: orders[name] ?? 0,
      x: ev?.offsetX ?? 0, y: ev?.offsetY ?? 0 })
  }

  return (
    <div style={{ position: 'absolute', inset: 0 }}>
      <Canvas dpr={[1, 2]} camera={{ position: [0, 4.6, 4.4], fov: 42 }}
        onCreated={({ camera }) => camera.lookAt(0, -0.3, -0.3)}
        gl={{ antialias: true, alpha: true }}>
        <ambientLight intensity={0.85} />
        <directionalLight position={[3, 6, 4]} intensity={0.9} color="#BFD4FF" />
        <directionalLight position={[-4, 3, -2]} intensity={0.4} color="#FF8C50" />
        <InteractionControls inter={interRef.current} />
        <Rig inter={interRef.current}>
          <Stars />
          {geo && <Provinces geo={geo} hovered={hover?.name} onHover={onHover} />}
          <CityPillars cities={cities} />
          <Pulses pulses={pulses} />
        </Rig>
      </Canvas>
      {hover && (
        <div className="sc-map-tip"
          style={{ left: clamp(hover.x, 70, 970), top: Math.max(hover.y, 60) }}>
          <b>{hover.name}</b>
          {hover.orders > 0
            ? <span className="n">{hover.orders >= 1e4
                ? `${(hover.orders / 1e4).toFixed(1)}万单`
                : `累计 ${hover.orders} 单`}</span>
            : <span className="empty">虚位以待 · 商家入驻中</span>}
        </div>
      )}
    </div>
  )
}
