import { Canvas, useFrame } from '@react-three/fiber'
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import * as THREE from 'three'

import { REDUCED, makeGlowTexture, useInView } from './three-utils.js'

/* "一单钱的去向":滚动驱动的资金分流。
   一份 ¥35 的订单(菜品 30 + 配送 5)化作一枚粒子硬币,随滚动分成三股:
   绿 → 商家 ¥28.50(95%),蓝 → 骑手 ¥5.00(100% 配送费),橙 → 平台 ¥1.50(5%)。
   粒子数量严格按金额比例——画面本身就是账本。
   滚动只更新目标进度,真正的位移在帧循环里做指数阻尼逼近:
   滚轮的台阶式输入被抹平,钱是"淌"过去的,不是一格一格蹦。 */

const STREAMS = [
  { key: 'merchant', cents: 2850, color: '#2FBF8F', to: [-4.6, -2.4, 0] },
  { key: 'rider', cents: 500, color: '#4DA3FF', to: [4.6, -2.4, 0] },
  { key: 'platform', cents: 150, color: '#FF5A1F', to: [0, -3.1, 0] },
]
const TOTAL = STREAMS.reduce((s, x) => s + x.cents, 0)
const COUNT = 900

const easeInOut = t => (t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2)

function SplitScene({ progressRef, onPhase }) {
  const points = useRef()
  const smooth = useRef(REDUCED ? 1 : 0)
  const { positions, colors, meta } = useMemo(() => {
    const positions = new Float32Array(COUNT * 3)
    const colors = new Float32Array(COUNT * 3)
    const meta = []
    let i = 0
    for (const stream of STREAMS) {
      const n = Math.round((stream.cents / TOTAL) * COUNT)
      const c = new THREE.Color(stream.color)
      for (let k = 0; k < n && i < COUNT; k++, i++) {
        // 起点:顶部一枚"硬币"(扁圆盘,压低避开标题文字)
        const r = Math.sqrt(Math.random()) * 1.6
        const a = Math.random() * Math.PI * 2
        const from = [Math.cos(a) * r, 2.9 + Math.sin(a) * r * 0.3,
                      (Math.random() - 0.5) * 0.6]
        // 终点:各自钱堆(小圆盘)
        const r2 = Math.sqrt(Math.random()) * (1.1 + stream.cents / TOTAL)
        const a2 = Math.random() * Math.PI * 2
        const to = [stream.to[0] + Math.cos(a2) * r2,
                    stream.to[1] + Math.sin(a2) * r2 * 0.4,
                    stream.to[2] + (Math.random() - 0.5) * 0.8]
        // 控制点:向外抛的弧线
        const ctrl = [(from[0] + to[0]) / 2 + (to[0] === 0 ? 0 : Math.sign(to[0]) * 2.2),
                      1.2 + Math.random() * 1.2, 0]
        meta.push({ from, ctrl, to, stagger: Math.random() })
        const dim = 0.55 + Math.random() * 0.45
        colors[(i) * 3] = c.r * dim
        colors[(i) * 3 + 1] = c.g * dim
        colors[(i) * 3 + 2] = c.b * dim
        positions[i * 3] = from[0]
        positions[i * 3 + 1] = from[1]
        positions[i * 3 + 2] = from[2]
      }
    }
    return { positions, colors, meta }
  }, [])

  const glow = useMemo(makeGlowTexture, [])

  useFrame((state, delta) => {
    if (!points.current) return
    const target = REDUCED ? 1 : progressRef.current
    // 指数阻尼:约 0.4s 追平滚动目标,滚轮台阶感被完全抹掉
    smooth.current += (target - smooth.current) * (1 - Math.exp(-delta * 7))
    const p = smooth.current
    onPhase(p < 0.12 ? 0 : p < 0.72 ? 1 : 2)
    const t = state.clock.elapsedTime
    const pos = points.current.geometry.attributes.position
    for (let i = 0; i < meta.length; i++) {
      const m = meta[i]
      // 每个粒子带一点错峰,钱是"淌"过去的,不是瞬移
      const local = easeInOut(Math.min(1, Math.max(0,
        (p * 1.45 - m.stagger * 0.45))))
      const u = 1 - local
      const x = u * u * m.from[0] + 2 * u * local * m.ctrl[0] + local * local * m.to[0]
      const y = u * u * m.from[1] + 2 * u * local * m.ctrl[1] + local * local * m.to[1]
      const z = u * u * m.from[2] + 2 * u * local * m.ctrl[2] + local * local * m.to[2]
      // 静止时的微浮动:硬币和钱堆都是"活"的,不是定格的贴图
      const idle = REDUCED ? 0 : Math.sin(t * 1.3 + m.stagger * 12.57) * 0.04
      pos.setXYZ(i, x, y + idle, z)
    }
    pos.needsUpdate = true
  })

  return (
    <points ref={points}>
      <bufferGeometry>
        <bufferAttribute attach="attributes-position" count={COUNT}
          array={positions} itemSize={3} />
        <bufferAttribute attach="attributes-color" count={COUNT}
          array={colors} itemSize={3} />
      </bufferGeometry>
      <pointsMaterial size={0.24} vertexColors transparent opacity={0.95}
        map={glow} sizeAttenuation depthWrite={false}
        blending={THREE.AdditiveBlending} />
    </points>
  )
}

export default function CoinFlow() {
  const section = useRef()
  const progressRef = useRef(0)
  const [phase, setPhase] = useState(0) // 0 硬币 1 分流中 2 落定,驱动文字
  const active = useInView(section)

  useEffect(() => {
    // 滚动监听只记录目标进度(一次 getBoundingClientRect,无 setState),
    // 平滑与渲染全部交给 Canvas 帧循环
    const onScroll = () => {
      const el = section.current
      if (!el) return
      const r = el.getBoundingClientRect()
      const total = r.height - innerHeight
      progressRef.current = Math.min(1, Math.max(0, -r.top / Math.max(1, total)))
    }
    addEventListener('scroll', onScroll, { passive: true })
    onScroll()
    return () => removeEventListener('scroll', onScroll)
  }, [])

  const onPhase = useCallback(p => setPhase(p), [])
  const done = REDUCED || phase === 2
  return (
    <section ref={section} className="coinflow" id="coinflow" aria-label="一单钱的去向">
      <div className="cf-sticky">
        <div className="cf-head">
          <h2>三十五块钱,去了哪里</h2>
          <p className="section-lede">
            一份 ¥30 的餐,加 ¥5 配送费。往下滚,看它怎么分。
          </p>
        </div>
        <Canvas camera={{ position: [0, 0, 13], fov: 50 }} dpr={[1, 1.8]}
          frameloop={active ? 'always' : 'never'}
          gl={{ antialias: false, powerPreference: 'low-power' }}>
          <SplitScene progressRef={progressRef} onPhase={onPhase} />
        </Canvas>
        <div className={`cf-label merchant ${done ? 'show' : ''}`}>
          <div className="amt green">¥28.50</div>
          <div className="who">商家</div>
          <div className="how">¥30 − 5% 佣金</div>
        </div>
        <div className={`cf-label rider ${done ? 'show' : ''}`}>
          <div className="amt blue">¥5.00</div>
          <div className="who">骑手</div>
          <div className="how">配送费,一分不少</div>
        </div>
        <div className={`cf-label platform ${done ? 'show' : ''}`}>
          <div className="amt orange">¥1.50</div>
          <div className="who">平台</div>
          <div className="how">5% · 只有这些</div>
        </div>
        <div className={`cf-note ${done ? 'show' : ''}`}>
          比例即真实分账规则,每一单都能在订单里查到同样的明细。
        </div>
      </div>
    </section>
  )
}
