import { Canvas, useFrame, useThree } from '@react-three/fiber'
import React, { useMemo, useRef } from 'react'
import * as THREE from 'three'

import { REDUCED, makeGlowTexture, useInView } from './three-utils.js'

/* 炉火余烬:品牌"炉火橙"的 3D 化。
   一片缓慢旋转、微微上浮的暖色粒子——像灶台上方的余烬,安静、有温度。
   叙述平缓:无跳动、无闪烁,尊重 prefers-reduced-motion。
   滚出视口即暂停渲染,不跟下面的滚动动画抢帧。 */

function EmberField({ count = 1600 }) {
  const points = useRef()
  const glow = useMemo(makeGlowTexture, [])
  const { positions, colors, seeds } = useMemo(() => {
    const positions = new Float32Array(count * 3)
    const colors = new Float32Array(count * 3)
    const seeds = new Float32Array(count)
    const palette = [
      new THREE.Color('#FF5A1F'), // 炉火橙
      new THREE.Color('#FFB84D'), // 促销琥珀(亮)
      new THREE.Color('#B3400F'), // 深炭橙
      new THREE.Color('#0E8A5F'), // 一点账目绿,克制地混入
    ]
    for (let i = 0; i < count; i++) {
      // 扁平的宽碟形分布,中心留空给标题呼吸
      const r = 6 + Math.pow(Math.random(), 0.6) * 22
      const theta = Math.random() * Math.PI * 2
      positions[i * 3] = Math.cos(theta) * r
      positions[i * 3 + 1] = (Math.random() - 0.35) * 9
      positions[i * 3 + 2] = Math.sin(theta) * r - 6
      const c = palette[Math.random() < 0.06 ? 3 : Math.floor(Math.random() * 3)]
      const dim = 0.35 + Math.random() * 0.65
      colors[i * 3] = c.r * dim
      colors[i * 3 + 1] = c.g * dim
      colors[i * 3 + 2] = c.b * dim
      seeds[i] = Math.random() * Math.PI * 2
    }
    return { positions, colors, seeds }
  }, [count])

  useFrame((state, delta) => {
    if (REDUCED || !points.current) return
    points.current.rotation.y += delta * 0.018
    // 余烬缓慢上浮,浮出视野的从底部回来
    const pos = points.current.geometry.attributes.position
    const t = state.clock.elapsedTime
    for (let i = 0; i < count; i++) {
      let y = pos.getY(i) + delta * (0.12 + 0.1 * Math.sin(seeds[i]))
      if (y > 6) y = -4
      pos.setY(i, y + Math.sin(t * 0.4 + seeds[i]) * 0.002)
    }
    pos.needsUpdate = true
  })

  return (
    <points ref={points}>
      <bufferGeometry>
        <bufferAttribute attach="attributes-position" count={count}
          array={positions} itemSize={3} />
        <bufferAttribute attach="attributes-color" count={count}
          array={colors} itemSize={3} />
      </bufferGeometry>
      <pointsMaterial size={0.3} vertexColors transparent opacity={0.9}
        map={glow} sizeAttenuation depthWrite={false}
        blending={THREE.AdditiveBlending} />
    </points>
  )
}

function ParallaxCamera() {
  const { camera, pointer } = useThree()
  useFrame(() => {
    if (REDUCED) return
    camera.position.x += (pointer.x * 1.2 - camera.position.x) * 0.02
    camera.position.y += (pointer.y * 0.6 + 1 - camera.position.y) * 0.02
    camera.lookAt(0, 0, -6)
  })
  return null
}

export default function Embers() {
  const wrap = useRef()
  const active = useInView(wrap)
  return (
    <div ref={wrap} className="embers">
      <Canvas frameloop={active ? 'always' : 'never'}
        camera={{ position: [0, 1, 14], fov: 55 }}
        dpr={[1, 1.8]} gl={{ antialias: false, powerPreference: 'low-power' }}>
        <ParallaxCamera />
        <EmberField />
        <fog attach="fog" args={['#0B0E14', 26, 52]} />
      </Canvas>
    </div>
  )
}
