import React from 'react'

import { Caption, Ease, Film, P, SERIF, clamp, enter, pop, tween, useFilm, useWidth } from './kit.jsx'

/* 功能页「消息」一节的片子:同一单,别处要在三个地方说话,这里是一个群。
 *
 * 讲的是用户端「消息」的做法:万物皆会话 —— 平台通知是带认证标的「超级赞」服务号,
 * 视频互动是一个机器人会话,每一单是一个群(你 + 商家 + 骑手),列表只有一种行;
 * 群在送达 24 小时后自动归档:还能翻,不能再发。
 *
 * 左边那栏是行业现状的通用描述(要在几个地方分别找人),不点名、不画具体产品的界面。
 *
 * 和原稿不一样:
 * - 原稿收尾写「号码互相看不到,走平台中转」。隐私中间号还没接(services/privacy_phone.py
 *   是占位),商家、骑手拨出去的仍是顾客的号码 —— 能照实说的只有「群里不出现手机号」;
 * - 左栏「要打骑手电话,号码还互相看得见」:大平台多用中间号,这半句说别人说过了头,
 *   只留「要单独给骑手打电话」;
 * - 三类会话的图标原稿是 ✓ ◍ ⌘ 三个字符,⌘ 在不同系统上长得不一样,也和「群」不沾边,
 *   换成同一套线框画法的小图标;
 * - 原稿群里的消息到点才插进来,片子会一条一条长高;这里三条一开始就占着位置。 */

// @serif-cjk-begin
const TITLES = [
  '同一单，三个地方说话。',
  '这里是一个群。',
  '列表只有一种行。',
]
const AVATAR = { me: '我', shop: '张', rider: '赵' }
// @serif-cjk-end

/* 字幕底下那行说明(黑体,不进衬线子集) */
const DETAILS = [
  '催出餐、问送到哪了、说不通了找人评理 —— 每换一个地方，前面的话都要再讲一遍。',
  '你、商家、骑手在同一屏里。谁说的、什么时候说的，三个人看到的是同一份记录。',
  '通知是带认证标的服务号，互动是机器人，每一单是一个群 —— 万物皆会话，没有第二种入口。',
]

const CUE = { split: 0.3, pain: 2.0, merge: 5.2, group: 6.2, msgs: 7.0, pin: 10.4, kinds: 11.6, close: 14.2 }
const TOTAL = 17.4
/** 静帧:群里三条消息、置顶条、三类会话和收尾那句都已出 */
const STILL = 15.0

/** 左栏:同一单,你要在几个地方分别找人 */
const AWAY = [
  ['催出餐', '要在点单那边找商家'],
  ['问送到哪了', '要单独给骑手打电话'],
  ['说不通了找人评理', '要另开客服入口，把前面的话再讲一遍'],
]

/** 右栏:一个群里三条消息 [发的人, 内容, 名字颜色, 头像字, 头像底, 头像字色] */
const MSGS = [
  ['张记面馆', '出餐了，卤蛋多给了一个', P.bowl, AVATAR.shop, P.claySoft, P.clay],
  ['赵师傅 · 骑手', '取到餐了，路上有点堵，大概 12:41 到', P.run, AVATAR.rider, '#E6E3DA', P.ink2],
  ['赵师傅 · 骑手', '到楼下了，放门口还是您下来拿？', P.run, AVATAR.rider, '#E6E3DA', P.ink2],
]

/* 三类会话的小图标(线框,同 SiteChrome 的 Icon 画法) */
const KindIcon = ({ kind }) => (
  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"
    strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    {kind === 'official' && <><path d="M12 3 19 6v5c0 4.5-3 8.2-7 10-4-1.8-7-5.5-7-10V6z" /><path d="m9 12 2 2 4-4" /></>}
    {kind === 'bot' && <><rect x="5" y="8" width="14" height="11" rx="3" /><path d="M12 4.5V8" /><path d="M9.5 13h.01M14.5 13h.01M10 16h4" /></>}
    {kind === 'group' && <><circle cx="9" cy="9" r="3" /><path d="M3.5 19c.6-2.9 2.8-4.5 5.5-4.5s4.9 1.6 5.5 4.5" /><circle cx="16.5" cy="8.5" r="2.5" /><path d="M16 13.8c2.3-.2 4 1.1 4.6 3.7" /></>}
  </svg>
)

const KINDS = [
  ['official', '服务号', '平台通知 · 带认证标'],
  ['bot', '机器人', '视频互动 · 回复和赞'],
  ['group', '群', '每一单 · 你 + 商家 + 骑手'],
]

const Avatar = ({ ch, bg, color, style }) => (
  <span style={{
    width: 26, height: 26, borderRadius: '50%', flex: 'none', background: bg, color,
    fontFamily: "'SzSerifCJK','PingFang SC',serif", fontWeight: 600, fontSize: 12,
    display: 'flex', alignItems: 'center', justifyContent: 'center', ...style,
  }}>{ch}</span>
)

export default function ChatOneGroupFilm() {
  const film = useFilm(TOTAL, { still: STILL, poster: 0.5 })
  const { T } = film
  const w = useWidth(film.box)
  const narrow = w > 0 && w < 760
  const pull = tween(T, { start: CUE.merge, end: CUE.merge + 0.7 })
  const capIdx = T >= CUE.kinds ? 2 : T >= CUE.group ? 1 : 0

  return (
    <Film film={film} label="示例 · 订单 #44 的全部对话" loop="循环 · 17 秒"
      summary="示例动画：同一单，在别处要在三个地方分别说话：找商家催出餐、给骑手打电话问送到哪了、另开客服入口找人评理。在这里一单就是一个群，你、商家、骑手在同一屏里，三个人看到的是同一份记录，群里不出现手机号。消息列表只有一种行：平台通知是带认证标的服务号，视频互动是机器人，每一单是一个群。群在送达 24 小时后自动归档，还能翻，不能再发。"
      style={{ background: P.card, border: `1px solid ${P.line}`, padding: narrow ? '20px 16px' : '24px 26px' }}>
      <div style={{ display: 'grid', gridTemplateColumns: narrow ? 'minmax(0,1fr)' : '1fr 1fr', gap: 16, alignItems: 'start' }}>

        {/* 别处:三个孤岛 */}
        <div style={{ background: P.alt, borderRadius: 12, padding: '16px 18px', display: 'flex', flexDirection: 'column', gap: 12, ...enter(T, CUE.split) }}>
          <div>
            <div style={{ fontSize: 11, letterSpacing: 1.2, color: P.ink2 }}>别处 · 同一单</div>
            <div style={{ fontSize: 13, color: P.ink2, marginTop: 5 }}>三件事，三个地方</div>
          </div>
          {AWAY.map(([t, d], i) => {
            const k = tween(T, { start: CUE.pain + i * 0.5, end: CUE.pain + i * 0.5 + 0.32 })
            return (
              <div key={t} style={{
                border: '1px dashed #CFCABD', borderRadius: 10, padding: '10px 12px', background: P.card,
                opacity: k * (1 - pull * 0.55),
                transform: `translateX(${(1 - k) * -10}px) translateY(${pull * 6 * (i - 1)}px)`,
              }}>
                <div style={{ fontSize: 13.5, fontWeight: 600 }}>{t}</div>
                <div style={{ fontSize: 12, color: P.ink2, marginTop: 2, lineHeight: 1.55 }}>{d}</div>
              </div>
            )
          })}
          <div style={{ fontSize: 11.5, color: P.ink3, lineHeight: 1.6 }}>这一栏说的是普遍情形，不指某一家的界面。</div>
        </div>

        {/* 这里:一个群 */}
        <div style={{ border: `1px solid ${P.line}`, borderRadius: 12, overflow: 'hidden', background: P.card, ...enter(T, CUE.group - 0.4) }}>
          <div style={{ height: 3, background: P.clay }} />
          <div style={{ padding: '12px 14px', borderBottom: `1px solid ${P.line}`, display: 'flex', alignItems: 'center', gap: 10 }}>
            <span style={{ display: 'flex', flex: 'none' }}>
              {[[AVATAR.me, P.claySoft, P.clay], [AVATAR.shop, P.claySoft, P.bowl], [AVATAR.rider, '#E6E3DA', P.ink2]].map(([ch, bg, color], i) => (
                <Avatar key={ch} ch={ch} bg={bg} color={color}
                  style={{ border: `1.5px solid ${P.card}`, marginLeft: i ? -8 : 0, ...pop(T, CUE.group + i * 0.18) }} />
              ))}
            </span>
            <span style={{ flex: 1, minWidth: 0 }}>
              <span style={{ display: 'block', fontSize: 14, fontWeight: 600 }}>订单 #44 · 张记面馆</span>
              <span style={{ display: 'block', fontSize: 11.5, color: P.ink2 }}>你、张记面馆、赵师傅</span>
            </span>
          </div>

          {/* 置顶的订单状态 */}
          <div style={{
            padding: '9px 14px', borderBottom: `1px solid ${P.line}`, display: 'flex', gap: 10, alignItems: 'center',
            opacity: tween(T, { start: CUE.pin, end: CUE.pin + 0.4 }),
          }}>
            <span style={{ width: 2, alignSelf: 'stretch', background: P.clay, borderRadius: 2, flex: 'none' }} />
            <span style={{ flex: 1, minWidth: 0 }}>
              <span style={{ display: 'block', fontSize: 11, color: P.clay, fontWeight: 600 }}>置顶消息</span>
              <span style={{ display: 'block', fontSize: 12.5 }}>
                配送中 · 预计 <span style={{ fontFamily: SERIF, fontWeight: 600, fontVariantNumeric: 'tabular-nums' }}>12:41</span> 送达
              </span>
            </span>
          </div>

          {/* 消息:三条一开始就占着位置(透明),冒出来时片子不长高 —— 手机上两栏竖排,
              长高一截会把整页往下推 */}
          <div style={{ padding: '12px 14px', display: 'flex', flexDirection: 'column', gap: 9 }}>
            {MSGS.map(([who, text, color, ch, bg, fg], i) => {
              const at = CUE.msgs + i * 1.0
              const k = tween(T, { start: at, end: at + 0.3, ease: Ease.spring })
              return (
                <div key={i} style={{
                  display: 'flex', gap: 8, alignItems: 'flex-end',
                  opacity: clamp(k * 1.6, 0, 1), transform: `translateY(${(1 - k) * 8}px)`,
                }}>
                  <Avatar ch={ch} bg={bg} color={fg} />
                  <span style={{
                    maxWidth: 250, minWidth: 0, background: P.card, border: `1px solid ${P.line}`,
                    borderRadius: '12px 12px 12px 4px', padding: '7px 11px 8px', fontSize: 13.5, lineHeight: 1.5,
                  }}>
                    <span style={{ display: 'block', fontSize: 11.5, fontWeight: 600, color, marginBottom: 1 }}>{who}</span>
                    {text}
                  </span>
                </div>
              )
            })}
          </div>
        </div>
      </div>

      {/* 三类会话:列表里是同一种行 */}
      <div style={{ display: 'grid', gridTemplateColumns: narrow ? 'minmax(0,1fr)' : 'repeat(3, minmax(0,1fr))', gap: 10 }}>
        {KINDS.map(([kind, t, d], i) => (
          <div key={kind} style={{
            border: `1px solid ${P.line}`, borderRadius: 10, padding: '11px 13px',
            display: 'flex', alignItems: 'center', gap: 10, ...enter(T, CUE.kinds + i * 0.35, 0.28),
          }}>
            <span style={{
              width: 26, height: 26, borderRadius: 8, flex: 'none', background: P.claySoft, color: P.clay,
              display: 'flex', alignItems: 'center', justifyContent: 'center',
            }}><KindIcon kind={kind} /></span>
            <span style={{ flex: 1, minWidth: 0 }}>
              <span style={{ display: 'block', fontSize: 13.5, fontWeight: 600 }}>{t}</span>
              <span style={{ display: 'block', fontSize: 11.5, color: P.ink2 }}>{d}</span>
            </span>
          </div>
        ))}
      </div>

      <Caption titles={TITLES} details={DETAILS} index={capIdx} narrow={narrow} detailColor={P.ink2}>
        <div style={{ fontSize: 12.5, color: P.ink2, marginTop: 2, opacity: tween(T, { start: CUE.close, end: CUE.close + 0.6 }) }}>
          群在送达 24 小时后自动归档：还能翻，不能再发。群里不出现手机号。
        </div>
      </Caption>
    </Film>
  )
}
