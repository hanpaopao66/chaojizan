import { Canvas, useFrame } from '@react-three/fiber'
import React, { useMemo, useRef } from 'react'
import * as THREE from 'three'

/* 骑手页:夜色城市网格上,几束配送光点沿街巷穿行。
   平缓——匀速、低亮度,像凌晨两点还在跑单的人。 */

const REDUCED = typeof matchMedia !== 'undefined' &&
  matchMedia('(prefers-reduced-motion: reduce)').matches

const BLUE = '#4DA3FF'
const ORANGE = '#FF5A1F'

/* 曼哈顿路径:在网格上横平竖直地走 */
function makeRoute(rng) {
  const pts = []
  let x = Math.floor(rng() * 16) - 8
  let z = Math.floor(rng() * 16) - 8
  pts.push([x, z])
  for (let i = 0; i < 10; i++) {
    if (rng() > 0.5) x = Math.floor(rng() * 16) - 8
    else z = Math.floor(rng() * 16) - 8
    pts.push([x, z])
  }
  return pts
}

function Riders({ n = 5 }) {
  const group = useRef()
  const routes = useMemo(() => {
    let seed = 7
    const rng = () => (seed = (seed * 16807) % 2147483647) / 2147483647
    return Array.from({ length: n }, (_, i) => ({
      pts: makeRoute(rng),
      speed: 0.5 + rng() * 0.5,
      offset: rng() * 10,
      color: i === 0 ? ORANGE : BLUE, // 头一束是炉火橙,其余账目蓝
    }))
  }, [n])
  useFrame((state) => {
    if (!group.current) return
    const t = REDUCED ? 2 : state.clock.elapsedTime
    group.current.children.forEach((m, i) => {
      const r = routes[i]
      const total = r.pts.length - 1
      const u = ((t * r.speed + r.offset) % (total * 2)) / 2
      const seg = Math.min(Math.floor(u), total - 1)
      const f = u - seg
      const [x1, z1] = r.pts[seg]
      const [x2, z2] = r.pts[seg + 1]
      m.position.set(x1 + (x2 - x1) * f, 0.12, z1 + (z2 - z1) * f)
    })
  })
  return (
    <group ref={group}>
      {routes.map((r, i) => (
        <mesh key={i}>
          <sphereGeometry args={[0.14, 8, 8]} />
          <meshBasicMaterial color={r.color} transparent opacity={0.95} />
        </mesh>
      ))}
    </group>
  )
}

export default function CityGrid() {
  return (
    <div className="citygrid" aria-hidden="true">
      <Canvas camera={{ position: [0, 7.5, 11], fov: 50 }} dpr={[1, 1.8]}
        gl={{ antialias: false, powerPreference: 'low-power' }}
        onCreated={({ camera }) => camera.lookAt(0, 0, 0)}>
        <gridHelper args={[18, 18, '#2A3446', '#1A2029']} />
        <Riders />
        <fog attach="fog" args={['#0B0E14', 10, 24]} />
      </Canvas>
    </div>
  )
}
