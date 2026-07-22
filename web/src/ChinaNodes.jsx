import { Canvas, useFrame } from '@react-three/fiber'
import React, { useMemo, useRef } from 'react'
import * as THREE from 'three'

import { REDUCED, makeGlowTexture, useInView } from './three-utils.js'
import { CHINA } from './china-dots.js'

/* 见证节点图:中国地界点阵地图,34 个省级行政区省会/首府全部有节点,
   坐标钉死。节点间的弧线是账本数据的复算与校验:绿色为相邻省会互证,
   橙色为干线长线互证,光点沿弧线往返传递。
   节点位置是示意;真实在线数量以 /stats/overview 的数字为准(不虚标)。 */

const GREEN = '#2FBF8F'
const ORANGE = '#FF5A1F'
const S = 8                  // 经纬度 → 世界单位缩放
const C = [104, 35]          // 画面中心(经度,纬度)
const P = (lon, lat, y = 0) =>
  new THREE.Vector3((lon - C[0]) / S, y, -(lat - C[1]) / S)

/* 节点钉死在 34 个省级行政区省会/首府的真实坐标(经度,纬度):
   0北京 1天津 2石家庄 3太原 4呼和浩特 5沈阳 6长春 7哈尔滨
   8上海 9南京 10杭州 11合肥 12福州 13南昌 14济南 15郑州
   16武汉 17长沙 18广州 19南宁 20海口 21重庆 22成都 23贵阳
   24昆明 25拉萨 26西安 27兰州 28西宁 29银川 30乌鲁木齐
   31台北 32香港 33澳门 */
const CITIES = [
  [116.41, 39.90], [117.20, 39.08], [114.51, 38.04], [112.55, 37.87],
  [111.75, 40.84], [123.43, 41.80], [125.32, 43.82], [126.53, 45.80],
  [121.47, 31.23], [118.80, 32.06], [120.15, 30.29], [117.23, 31.82],
  [119.30, 26.08], [115.86, 28.68], [117.12, 36.65], [113.63, 34.75],
  [114.31, 30.59], [112.94, 28.23], [113.26, 23.13], [108.37, 22.82],
  [110.20, 20.04], [106.55, 29.56], [104.07, 30.57], [106.63, 26.65],
  [102.83, 24.88], [91.11, 29.65], [108.94, 34.34], [103.83, 36.06],
  [101.78, 36.62], [106.23, 38.49], [87.62, 43.83],
  [121.56, 25.03], [114.17, 22.32], [113.55, 22.19],
]
/* 互证连线 [节点a, 节点b, 是否干线长线(橙色)]:
   相邻省会织成网,再叠 5 条标志性长线(京沪/京广/兰新/成拉/跨海峡) */
const LINKS = [
  [7, 6, 0], [6, 5, 0], [5, 0, 0],
  [0, 1, 0], [0, 2, 0], [2, 3, 0], [3, 4, 0],
  [1, 14, 0], [14, 15, 0], [15, 16, 0], [15, 26, 0],
  [8, 9, 0], [8, 10, 0], [9, 11, 0], [11, 16, 0],
  [10, 13, 0], [13, 16, 0], [10, 12, 0],
  [16, 17, 0], [17, 18, 0],
  [18, 19, 0], [19, 20, 0], [18, 32, 0], [32, 33, 0],
  [21, 22, 0], [21, 23, 0], [23, 24, 0], [24, 25, 0],
  [26, 27, 0], [27, 28, 0], [27, 29, 0], [29, 4, 0],
  [0, 8, 1], [0, 18, 1], [27, 30, 1], [22, 25, 1], [12, 31, 1],
]

/* 中国地界点阵,带一点确定性的明暗肌理 */
function LandDots() {
  const glow = useMemo(makeGlowTexture, [])
  const { positions, colors } = useMemo(() => {
    const n = CHINA.length / 2
    const positions = new Float32Array(n * 3)
    const colors = new Float32Array(n * 3)
    const base = new THREE.Color('#5A6D96')
    for (let i = 0; i < n; i++) {
      const v = P(CHINA[i * 2], CHINA[i * 2 + 1])
      positions[i * 3] = v.x
      positions[i * 3 + 1] = v.y
      positions[i * 3 + 2] = v.z
      const dim = 0.72 + ((i * 7) % 10) / 28
      colors[i * 3] = base.r * dim
      colors[i * 3 + 1] = base.g * dim
      colors[i * 3 + 2] = base.b * dim
    }
    return { positions, colors }
  }, [])
  return (
    <points>
      <bufferGeometry>
        <bufferAttribute attach="attributes-position"
          count={positions.length / 3} array={positions} itemSize={3} />
        <bufferAttribute attach="attributes-color"
          count={colors.length / 3} array={colors} itemSize={3} />
      </bufferGeometry>
      <pointsMaterial size={0.075} vertexColors transparent opacity={0.95}
        map={glow} sizeAttenuation depthWrite={false}
        blending={THREE.AdditiveBlending} />
    </points>
  )
}

/* 见证节点:绿色光标,呼吸错峰,位置钉死 */
function Beacons() {
  const group = useRef()
  const glow = useMemo(makeGlowTexture, [])
  useFrame((state) => {
    if (!group.current || REDUCED) return
    const t = state.clock.elapsedTime
    group.current.children.forEach((spr, i) => {
      const s = 0.19 + 0.05 * Math.sin(t * 1.6 + i * 1.9)
      spr.scale.set(s, s, 1)
      spr.material.opacity = 0.65 + 0.3 * Math.sin(t * 1.6 + i * 1.9)
    })
  })
  return (
    <group ref={group}>
      {CITIES.map(([lon, lat], i) => (
        <sprite key={i} position={P(lon, lat, 0.02)} scale={[0.19, 0.19, 1]}>
          <spriteMaterial map={glow} color={GREEN} transparent opacity={0.8}
            blending={THREE.AdditiveBlending} depthWrite={false} />
        </sprite>
      ))}
    </group>
  )
}

/* 互证弧线 + 沿线往返的光点 */
function Arcs() {
  const pulses = useRef()
  const glow = useMemo(makeGlowTexture, [])
  const arcs = useMemo(() => LINKS.map(([a, b, far], i) => {
    const from = P(...CITIES[a], 0.02)
    const to = P(...CITIES[b], 0.02)
    const mid = from.clone().add(to).multiplyScalar(0.5)
    mid.y += from.distanceTo(to) * 0.28 + 0.08
    const curve = new THREE.QuadraticBezierCurve3(from, mid, to)
    return {
      curve,
      pts: curve.getPoints(40),
      far: !!far,
      offset: i * 0.83,          // 错峰,不齐步走
      period: 5 + (i % 4) * 1.3, // 周期不一,像真实心跳
    }
  }), [])
  useFrame((state) => {
    if (!pulses.current || REDUCED) return
    const t = state.clock.elapsedTime
    pulses.current.children.forEach((spr, i) => {
      const a = arcs[i]
      const phase = ((t + a.offset) % a.period) / a.period
      const u = phase < 0.5 ? phase * 2 : (1 - phase) * 2 // 沿弧线往返
      a.curve.getPoint(u, spr.position)
      spr.material.opacity = 0.9 * Math.sin(Math.PI * Math.min(1, phase * 4))
    })
  })
  return (
    <group>
      {arcs.map((a, i) => (
        <line key={i}>
          <bufferGeometry
            onUpdate={g => g.setFromPoints(a.pts)} />
          <lineBasicMaterial color={a.far ? ORANGE : GREEN} transparent
            opacity={a.far ? 0.35 : 0.22}
            blending={THREE.AdditiveBlending} depthWrite={false} />
        </line>
      ))}
      <group ref={pulses}>
        {arcs.map((a, i) => (
          <sprite key={i} scale={[0.2, 0.2, 1]}>
            <spriteMaterial map={glow} color={a.far ? ORANGE : GREEN}
              transparent opacity={0} blending={THREE.AdditiveBlending}
              depthWrite={false} />
          </sprite>
        ))}
      </group>
    </group>
  )
}

export default function ChinaNodes() {
  const wrap = useRef()
  const active = useInView(wrap)
  return (
    <div ref={wrap} className="chain3d" aria-hidden="true">
      <Canvas frameloop={active ? 'always' : 'never'}
        camera={{ position: [0, 5.8, 2.1], fov: 40 }} dpr={[1, 1.8]}
        gl={{ antialias: true, powerPreference: 'low-power' }}
        onCreated={({ camera }) => camera.lookAt(0, 0, -0.15)}>
        <LandDots />
        <Beacons />
        <Arcs />
      </Canvas>
    </div>
  )
}
