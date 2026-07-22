import { Canvas, useFrame } from '@react-three/fiber'
import React, { useEffect, useMemo, useRef, useState } from 'react'
import * as THREE from 'three'

import { REDUCED, makeGlowTexture } from '../three-utils.js'

/* 3D 中国地图:省份 GeoJSON 挤出成板块,城市按累计订单立光柱,
   新订单落点扩散涟漪。投影与 ChinaNodes 同一套:经纬度线性缩放。 */

const S = 8                    // 经纬度 → 世界单位
const C = [104, 35.5]          // 画面中心(经度,纬度)
const px = lon => (lon - C[0]) / S
const pz = lat => -(lat - C[1]) / S
const DEPTH = 0.14             // 板块厚度

/* 省份板块 + 顶面描边 */
function Provinces({ geo }) {
  const { geometries, lines } = useMemo(() => {
    const geometries = []
    const linePts = []
    for (const f of geo.features) {
      const polys = f.geometry.type === 'Polygon'
        ? [f.geometry.coordinates] : f.geometry.coordinates
      for (const rings of polys) {
        const shape = new THREE.Shape(
          rings[0].map(([lon, lat]) => new THREE.Vector2(px(lon), -pz(lat))))
        for (const hole of rings.slice(1)) {
          shape.holes.push(new THREE.Path(
            hole.map(([lon, lat]) => new THREE.Vector2(px(lon), -pz(lat)))))
        }
        geometries.push(new THREE.ExtrudeGeometry(shape,
          { depth: DEPTH, bevelEnabled: false }))
        // 顶面描边(相邻点成对入线段表)
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
    return { geometries, lines }
  }, [geo])
  useEffect(() => () => {
    geometries.forEach(g => g.dispose()); lines.dispose()
  }, [geometries, lines])

  return (
    <group>
      {/* -90° 绕 X 放平:shape 平面(x=东, y=北) → 地面(x=东, -z=北),挤出朝上 */}
      {geometries.map((g, i) => (
        <mesh key={i} geometry={g} rotation={[-Math.PI / 2, 0, 0]}>
          {/* 顶/底面亮色,侧壁暗色(ExtrudeGeometry 材质组 0/1) */}
          <meshLambertMaterial attach="material-0" color="#16274A"
            emissive="#0B1730" />
          <meshLambertMaterial attach="material-1" color="#0A1428"
            emissive="#050B18" />
        </mesh>
      ))}
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

function Rig({ children }) {
  const ref = useRef()
  useFrame(({ clock }) => {
    if (REDUCED || !ref.current) return
    const t = clock.elapsedTime
    ref.current.rotation.y = Math.sin(t * 0.14) * 0.055
    ref.current.position.y = Math.sin(t * 0.4) * 0.02
  })
  return <group ref={ref}>{children}</group>
}

export default function ChinaMap3D({ cities, pulses }) {
  const [geo, setGeo] = useState(null)
  useEffect(() => {
    fetch(`${import.meta.env.BASE_URL}geo/china.json`)
      .then(r => r.json()).then(setGeo).catch(() => {})
  }, [])
  return (
    <Canvas dpr={[1, 2]} camera={{ position: [0, 4.6, 4.4], fov: 42 }}
      onCreated={({ camera }) => camera.lookAt(0, -0.3, -0.3)}
      gl={{ antialias: true, alpha: true }}>
      <ambientLight intensity={0.85} />
      <directionalLight position={[3, 6, 4]} intensity={0.9} color="#BFD4FF" />
      <directionalLight position={[-4, 3, -2]} intensity={0.4} color="#FF8C50" />
      <Rig>
        <Stars />
        {geo && <Provinces geo={geo} />}
        <CityPillars cities={cities} />
        <Pulses pulses={pulses} />
      </Rig>
    </Canvas>
  )
}
