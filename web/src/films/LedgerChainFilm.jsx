import React from 'react'

import { Caption, Film, MONO, P, SERIF, enter, pop, tween, useFilm, useWidth } from './kit.jsx'

/* 开源仓页(/opensource)的哈希链片:改历史上任何一分钱,都藏不住。
 * 账本专属深台面(brand.dart 的 ledger #1F1E1B)—— 全站只有账本用这个底色。
 *
 * 讲的是仓库里真有的两件事(docs/LEDGER-SPEC.md 第 0 节「能抓什么」):
 * - services/ledger.py 每天零点过后为前一天的全部账目生成锚点,链哈希前后相扣;
 * - witness/ 是见证节点,谁都能在自己机器上把整条链复算一遍。平台改写历史上
 *   任何一分钱,那天和之后每一天的链哈希都会变,留存过锚点的节点立刻对不上。
 * 日期、笔数、指纹都是示例(标了「示例」),不拿真指纹配假单。
 *
 * 和原稿不一样:原稿最后一段是「改动被拒绝 · 历史没改成」,账目回到 ¥1.05。
 * 这套机制做不到拒绝 —— 它能做的是**改了藏不住**:节点报「对不上」,
 * 挂在公开的节点页上。所以最后一段停在「三个节点都对不上」,不演回滚;
 * 「账本在所有人手上」也往回收成「谁都可以抄一份」(节点数本身只是参考,
 * 规格里写着真正的保证来自你自己跑的那一个)。 */

// @serif-cjk-begin
// 字幕大字(衬线显示,这个圈里的字才会进官网的衬线子集)
const TITLES = [
  '公开账本 · 每天一个锚点',
  '社区见证节点抄走',
  '有人想改历史',
  '改历史上任何一分钱，都藏不住。',
  '所以不用相信我们',
]
// @serif-cjk-end

/* 字幕底下那行说明(黑体,不进衬线子集) */
const DETAILS = [
  '每天零点过后，前一天的全部账目算出一个指纹，和前一天的首尾相扣成链。',
  '谁都可以跑一个见证节点，把每天的锚点抄走、在自己机器上复算一遍。',
  '把 9-07 那天平台留存的 ¥1.05 偷偷改成 ¥1.04 —— 一分钱。',
  '那天的指纹变了，它之后的全部指纹跟着变，留存过锚点的节点复算立刻对不上。',
  '锚点算法 services/ledger.py、复算脚本 witness/，都在开源仓里，AGPL-3.0。',
]

const CUE = { blocks: 0.3, chain: 3.4, nodes: 4.6, tamper: 7.0, rehash: 7.7, cascade: 8.3, bad: 10.0, caption: 11.4, flag: 14.6 }
const TOTAL = 17.8
/** 静帧:改动、连锁变样、三个节点都对不上,字幕是「藏不住」那一句 */
const STILL = 12.4

/* 五天的示例账目块。块 i 的指纹由块 i−1 的指纹和当天全部流水一起算出来,
 * 所以第 3 块一变,后面两块必然跟着变 */
const BLOCKS = [
  { day: '9-05', n: 96, sha: '4c1f8a2' },
  { day: '9-06', n: 128, sha: 'b7e0d13' },
  { day: '9-07', n: 141, sha: '2a95f60', tamper: true, bad: 'a10c7b9' },
  { day: '9-08', n: 117, sha: 'e38b471', bad: '5d2e0f8' },
  { day: '9-09', n: 133, sha: '9f4c2de', bad: '70b3ac1' },
]
const NODES = ['节点 · 甲', '节点 · 乙', '节点 · 丙']
const HEX = '0123456789abcdef'

/** 指纹落定前先滚一串十六进制(跟着帧走,不用随机数 —— 重播一致,能对帧校对) */
function shaAt(b, T, settleAt, rehashAt) {
  if (rehashAt != null && T >= rehashAt) {
    if (T < rehashAt + 0.5) return b.sha.split('').map((_, i) => HEX[(Math.floor(T * 24) + i * 5) % 16]).join('')
    return b.bad
  }
  if (T >= settleAt) return b.sha
  if (T < settleAt - 0.9) return '·······'
  return b.sha.split('').map((_, i) => HEX[(Math.floor(T * 20) + i * 7) % 16]).join('')
}

export default function LedgerChainFilm() {
  const film = useFilm(TOTAL, { still: STILL, poster: 0.5 })
  const { T } = film
  const w = useWidth(film.box)
  const narrow = w > 0 && w < 760

  const tampered = T >= CUE.tamper
  const badNode = i => T >= CUE.bad + i * 0.45
  const capIdx = T >= CUE.flag ? 4 : T >= CUE.caption ? 3 : T >= CUE.tamper ? 2 : T >= CUE.nodes ? 1 : 0

  return (
    <Film film={film} dark label="示例 · 公开账本的哈希链" loop="循环 · 18 秒"
      summary="示例动画：公开账本每天为前一天的全部账目算一个指纹，和前一天的首尾相扣成链，见证节点把锚点抄走、各自复算。有人把某一天平台留存的 1.05 元改成 1.04 元，那一天和之后每一天的指纹都跟着变，三个见证节点复算全部对不上。锚点算法和复算脚本都在开源仓里。"
      gap={20} style={{ background: P.ledger, padding: narrow ? '20px 16px' : '26px 28px' }}>
      {/* 链上的五天。窄屏竖着排:五块横排在手机上只剩五六十像素宽,
          折行的话连接线会挂在行尾,看着像链断了 */}
      <div style={{ display: 'flex', flexDirection: narrow ? 'column' : 'row', alignItems: 'stretch' }}>
        {BLOCKS.map((b, i) => {
          const at = CUE.blocks + i * 0.45
          const isTampered = tampered && b.tamper
          const cascaded = tampered && i > 2
          const bad = isTampered || cascaded
          const rehashAt = isTampered ? CUE.rehash : cascaded ? CUE.cascade + (i - 3) * 0.5 : null
          const linkK = tween(T, { start: CUE.chain + i * 0.3, end: CUE.chain + i * 0.3 + 0.32 })
          const sha = (
            <div style={{ fontFamily: MONO, fontSize: 12, marginTop: narrow ? 0 : 8, letterSpacing: 0.2, color: bad ? P.dbad : P.dearn }}>
              {shaAt(b, T, at + 1.0, rehashAt)}
            </div>
          )
          return (
            <React.Fragment key={b.day}>
              {i > 0 && (narrow ? (
                <div style={{ height: 14, paddingLeft: 22 }}>
                  <span style={{
                    display: 'block', width: 2, height: '100%', background: bad ? P.dbad : P.dgold, opacity: 0.75,
                    transformOrigin: 'top', transform: `scaleY(${linkK})`,
                  }} />
                </div>
              ) : (
                <div style={{ flex: '0 0 26px', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                  <span style={{
                    height: 2, width: '100%', background: bad ? P.dbad : P.dgold, opacity: 0.75,
                    transformOrigin: 'left', transform: `scaleX(${linkK})`,
                  }} />
                </div>
              ))}
              <div style={{
                flex: narrow ? 'none' : '1 1 0', minWidth: 0,
                background: P.dcard, border: `1px solid ${bad ? P.dbad : P.dline}`, borderRadius: 10,
                padding: narrow ? '9px 12px' : '12px 12px 11px', ...enter(T, at),
              }}>
                <div style={{ display: narrow ? 'flex' : 'block', alignItems: 'baseline', gap: 12 }}>
                  <div style={{ fontSize: 12, color: P.dmute, fontFamily: SERIF, fontVariantNumeric: 'tabular-nums' }}>{b.day}</div>
                  <div style={{ fontSize: 12.5, marginTop: narrow ? 0 : 2, flex: narrow ? 1 : 'none' }}>
                    <span style={{ fontFamily: SERIF, fontWeight: 600 }}>{b.n}</span>
                    <span style={{ color: P.dmute }}> 笔</span>
                  </div>
                  {sha}
                </div>
                {b.tamper && (
                  <div style={{
                    marginTop: 8, paddingTop: 8, borderTop: `1px solid ${P.dline}`,
                    fontSize: 11.5, color: P.dmute, display: 'flex', justifyContent: 'space-between', gap: 6,
                  }}>
                    <span>平台留存</span>
                    <span style={{
                      fontFamily: SERIF, fontWeight: 600, color: isTampered ? P.dbad : P.dgold,
                      textDecoration: isTampered ? 'line-through' : 'none',
                    }}>{isTampered ? '¥1.04' : '¥1.05'}</span>
                  </div>
                )}
              </div>
            </React.Fragment>
          )
        })}
      </div>

      {/* 见证节点 */}
      <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'center', borderTop: `1px solid ${P.dline}`, paddingTop: 16 }}>
        <span style={{ fontSize: 11.5, color: P.dmute, marginRight: 4 }}>社区见证节点 · 各自复算</span>
        {NODES.map((n, i) => {
          const bad = badNode(i)
          return (
            <span key={n} style={{
              display: 'inline-flex', alignItems: 'center', gap: 7, padding: '5px 11px',
              borderRadius: 999, border: `1px solid ${bad ? P.dbad : P.dline}`,
              fontSize: 12, color: bad ? P.dbad : P.dtext, ...pop(T, CUE.nodes + i * 0.3),
            }}>
              <span style={{
                width: 7, height: 7, borderRadius: '50%', background: bad ? P.dbad : P.dearn,
                boxShadow: bad ? '0 0 0 4px rgba(224,107,107,.18)' : 'none',
              }} />
              {n}
              <span style={{ color: bad ? P.dbad : P.dfaint, fontSize: 11.5 }}>{bad ? '对不上' : '一致'}</span>
            </span>
          )
        })}
        {T >= CUE.flag && (
          <span style={{
            display: 'inline-flex', alignItems: 'center', padding: '5px 11px', borderRadius: 999,
            background: 'rgba(224,107,107,.14)', color: P.dbad, fontSize: 12, ...pop(T, CUE.flag),
          }}>节点页上公开挂着「对不上」· 谁都查得到是哪一天</span>
        )}
      </div>

      <Caption title={TITLES[capIdx]} detail={DETAILS[capIdx]} narrow={narrow}
        color={capIdx === 3 ? P.dgold : P.dtext} detailColor={P.dmute}>
        <div style={{ fontFamily: MONO, fontSize: 12, color: P.dfaint, marginTop: 6 }}>
          server/app/services/ledger.py · witness/ · docs/LEDGER-SPEC.md
        </div>
      </Caption>
    </Film>
  )
}
