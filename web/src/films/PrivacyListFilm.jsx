import React from 'react'

import { Caption, Ease, Film, MONO, P, SERIF, clamp, tween, useFilm, useWidth } from './kit.jsx'

/* 首页「隐私」一节的片子:我们不收集什么 —— 以及我们确实收集了什么。
 * 设计稿标的位置是「下载页三张卡的上方,或 /legal/privacy 的页头」,放在首页下载段后面(见 Home.jsx)。
 *
 * 清单式,每条都能点到源码或文档。两栏是故意的:只列「不收集」就是宣传;
 * 把「收集了什么、为什么、拒绝了会怎样」并排写出来才是交代。
 * 右栏第一条是骑手端后台定位确实有 —— 藏着不说就是骗人。
 * 最后一块是公开的自我纠错:证照和留证图片曾经无鉴权直出(DEV-PROMPTS-11 #124–126)。
 *
 * 清单文字是正文,不是动画的一部分:读屏照常读每一条、出处链接也点得到(不做 role=img)。
 *
 * 和原稿不一样(逐条对过三端的清单文件、Info.plist 和代码,宁可少说不能说错):
 * - 「第三方 SDK 只有一个(极光推送)」不对:三端从 2026-07-31 起内嵌了腾讯地图 SDK
 *   (flutter_tencent_map → tencent-map-vector-sdk / Tencent-MapSDK)。原稿照的是
 *   STORE-REVIEW 第四节,那一节写在换地图之前。改成右栏一条「第三方 SDK:极光推送、腾讯地图」,
 *   两个都等同意隐私政策之后才启动(三端 PrivacyGate.onAgreed 里才 init);左栏换成
 *   「没有第三方统计和广告」(埋点自建,analytics.dart);
 * - 「没有诱导分享」删:有「邀请好友完成首单,你俩各得券」,算不算诱导分享不由我们说;
 * - 「相册 / 相机 / 通知 / 蓝牙 …… 每一个都先用中文说清楚再调系统弹窗」:消息模块加了麦克风、
 *   相机,这两个是直接调系统授权的;通知的申请时机也没法一概说成「用到时」。改成
 *   「相机 / 麦克风 / 蓝牙,用到时才申请」,选图走系统选择器、只拿选中的那几张(读媒体权限在清单里裁掉了);
 * - 骑手定位:不止「配送中」,上线接单期间一直在定位(大厅按距离排),下线才停;
 * - 用户端位置:聊天里发位置也会用;只在前台用,后台定位权限在清单里裁掉了;
 * - 热力图:出处换成接口本身(请求参数只有星期、时段、周数),DEV-PROMPTS-17 写的时候还没做;
 * - 见证节点:上报的不止时区,还有随机节点 ID、校验到哪天、链哈希和结论 —— 跟位置沾边的只有时区;
 * - 自我纠错那块:当年直出的不只商家证照和送达留证,还有骑手身份证、健康证。 */

// @serif-cjk-begin
const TITLES = [
  '我们不收集什么。',
  '以及我们确实收集了什么。',
  '还有我们自己查出来的那次。',
]
const HEAD = ['不收集', '收集了什么，为什么', '条']
// @serif-cjk-end

/* 字幕底下那行说明(黑体,不进衬线子集) */
const DETAILS = [
  '一条一行，每条都点得到源码或文档 —— 不是「我们重视您的隐私」。',
  '只列不收集的那半边，是宣传；两边都写出来，才是交代。',
  '证照和留证图片曾经无鉴权直出 —— 缺陷、改法、为什么这么改，都写在决策记录里没删。',
]

const REPO = 'https://github.com/hanpaopao66/chaojizan/blob/main/'

/* [标题, 说明, 出处文案, 出处路径] */
const NONE = [
  ['不上传你的通讯录', '三端都不申请通讯录权限。找人只做完整手机号精确匹配，这一条还能在隐私设置里关掉', 'DEV-PROMPTS-40 · D2', 'docs/DEV-PROMPTS-40.md'],
  ['小程序拿不到你的手机号、定位、通讯录', '定位、扫码、剪贴板、手机号不在可申请清单里 —— 宿主和 SDK 里根本没有这几个方法。安全审计里「定位能直接申请」就算红', 'MINIAPP-SECURITY-AUDIT · I7', 'docs/MINIAPP-SECURITY-AUDIT.md'],
  ['没有第三方统计和广告', '埋点是自建的，只在登录后记页面浏览、搜索和分享，不采集设备指纹。没有开屏广告、摇一摇跳转，也没有自动续费', 'analytics.dart', 'packages/shared/lib/src/analytics.dart'],
  ['骑手热力图不上传骑手位置', '请求里只有星期几、几点、看几周，没有你的坐标 —— 它只看这座城过去几周哪儿出单', 'riders.py · /heatmap', 'server/app/routers/riders.py'],
  ['见证节点不收集、不上传关于你的任何信息', '上报的是随机节点 ID、校验到哪天、链哈希和结论，跟位置沾边的只有一个时区，没有坐标。也因为这句话，连 IP 定位兜底都没做', 'witness/README', 'witness/README.md'],
]

const YES = [
  ['骑手端：后台定位，有', '上线接单期间一直在定位，锁屏也定位：大厅按离你多远排单，配送中的轨迹要给顾客看。安卓是前台服务 + 一条常驻通知「超级赞接单中」，iOS 是屏幕顶上那条蓝条 —— 你随时看得见它在跑；下线就停', 'location_service.dart', 'apps/rider_app/lib/location_service.dart'],
  ['用户端：位置', '看附近商家、选收货地址、在聊天里发位置时才要；只在前台用，不申请后台定位。拒绝了就展示演示区域，App 照样能用', 'AndroidManifest.xml', 'apps/user_app/android/app/src/main/AndroidManifest.xml'],
  ['相机 / 麦克风 / 蓝牙', '用到时才申请：聊天里拍照、按住说话；商家端扫券核销、骑手端拍送达凭证；商家端连小票打印机。选图片走系统的选择器，只拿你选中的那几张', 'AndroidManifest.xml', 'apps/user_app/android/app/src/main/AndroidManifest.xml'],
  ['第三方 SDK：极光推送、腾讯地图', '推送要读设备标识（Registration ID、机型、系统版本），地图加载时会连腾讯的服务器；两个都等你同意隐私政策之后才启动', 'map_boot.dart', 'packages/shared/lib/src/map_boot.dart'],
  ['不登录也能逛', '不登录能看完整内容，只有下单、聊天这类动作才引导登录', 'STORE-REVIEW · 五 #2', 'docs/STORE-REVIEW.md'],
]

const CUE = { head: 0.3, none: 1.2, yes: 5.4, fix: 9.6, close: 12.4 }
const TOTAL = 16.4
/** 静帧:两栏全部出齐、自我纠错那块和收尾那句都在 */
const STILL = 13.4

/** 入场:淡入 + 上移 10px(清单行比别的片子密,位移小一点) */
const rowIn = (T, start, dur = 0.26) => {
  const k = tween(T, { start, end: start + dur })
  return { opacity: k, transform: `translateY(${(1 - k) * 10}px)` }
}

const Src = ({ children, to }) => (
  <a href={REPO + to} target="_blank" rel="noopener noreferrer" style={{ fontFamily: MONO, fontSize: 10.5, color: P.link }}>{children}</a>
)

function Row({ T, at, title, desc, src, to, mark, markColor }) {
  const k = tween(T, { start: at + 0.14, end: at + 0.36, ease: Ease.spring })
  return (
    <li style={{ borderTop: `1px solid ${P.line}`, padding: '10px 0', display: 'flex', gap: 10, ...rowIn(T, at) }}>
      <span aria-hidden="true" style={{
        width: 17, height: 17, borderRadius: '50%', flex: 'none', marginTop: 3,
        border: `1.5px solid ${markColor}`, color: markColor, fontSize: 10.5, lineHeight: 1,
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        opacity: clamp(k * 3, 0, 1), transform: `scale(${0.88 + 0.12 * k})`,
      }}>{mark}</span>
      <span style={{ flex: 1, minWidth: 0 }}>
        <span style={{ display: 'block', fontSize: 13.5, fontWeight: 600, lineHeight: 1.45 }}>{title}</span>
        <span style={{ display: 'block', fontSize: 12, color: P.ink2, marginTop: 2, lineHeight: 1.6 }}>{desc}</span>
        <span style={{ display: 'block', marginTop: 3 }}><Src to={to}>{src}</Src></span>
      </span>
    </li>
  )
}

function Column({ T, at, title, rows, rowAt, gap, mark, markColor }) {
  return (
    <div style={rowIn(T, at, 0.32)}>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, paddingBottom: 6 }}>
        <h3 style={{ margin: 0, fontFamily: SERIF, fontWeight: 600, fontSize: 17, flex: 1 }}>{title}</h3>
        <span style={{ fontFamily: SERIF, fontWeight: 600, fontSize: 13, color: P.ink3, fontVariantNumeric: 'tabular-nums' }}>{rows.length} {HEAD[2]}</span>
      </div>
      {/* role=list:Safari 的读屏会把去掉了项目符号的 ul 当成普通块 */}
      <ul role="list" style={{ listStyle: 'none', margin: 0, padding: 0 }}>
        {rows.map(([t, d, src, to], i) => (
          <Row key={t} T={T} at={rowAt + i * gap} title={t} desc={d} src={src} to={to} mark={mark} markColor={markColor} />
        ))}
      </ul>
    </div>
  )
}

export default function PrivacyListFilm() {
  const film = useFilm(TOTAL, { still: STILL, poster: 0.5 })
  const { T } = film
  const w = useWidth(film.box)
  const narrow = w > 0 && w < 800
  const capIdx = T >= CUE.fix ? 2 : T >= CUE.yes ? 1 : 0

  return (
    <Film film={film} label="隐私 · 清单式，每条带出处" loop="循环 · 16 秒"
      style={{ background: P.card, border: `1px solid ${P.line}`, padding: narrow ? '20px 16px' : '24px 26px' }}>
      <div style={{ display: 'grid', gridTemplateColumns: narrow ? 'minmax(0,1fr)' : '1fr 1fr', gap: 18, alignItems: 'start' }}>
        <Column T={T} at={CUE.head} title={HEAD[0]} rows={NONE} rowAt={CUE.none} gap={0.62} mark="×" markColor={P.ink2} />
        <Column T={T} at={CUE.yes - 0.4} title={HEAD[1]} rows={YES} rowAt={CUE.yes} gap={0.7} mark="·" markColor={P.hold} />
      </div>

      {/* 自我纠错 */}
      <div style={{
        borderRadius: 12, background: P.alt, padding: narrow ? '14px 16px' : '16px 18px',
        display: 'flex', gap: 13, alignItems: 'flex-start', ...rowIn(T, CUE.fix, 0.32),
      }}>
        <span aria-hidden="true" style={{
          width: 22, height: 22, borderRadius: 6, flex: 'none', background: P.claySoft, color: P.clay,
          fontSize: 13, display: 'flex', alignItems: 'center', justifyContent: 'center', marginTop: 2,
        }}>!</span>
        <span style={{ flex: 1, minWidth: 0 }}>
          <span style={{ display: 'block', fontSize: 14, fontWeight: 600 }}>我们自己查出来的那次</span>
          <span style={{ display: 'block', fontSize: 12.5, color: P.ink2, marginTop: 4, lineHeight: 1.7 }}>
            骑手身份证、健康证，商家营业执照，送达留证的照片，曾经<b style={{ fontWeight: 600, color: P.ink }}>没有鉴权就能直接访问</b>。
            起因不是容量不够，是隐私缺陷 —— 改成自建对象存储，「这张图是否私密」由它在哪个桶里决定，
            <b style={{ fontWeight: 600, color: P.ink }}>不维护一份「哪些要保护」的清单</b>（清单总会漏）。
            缺陷、改法、为什么这么改，原文没删。
          </span>
          <span style={{ display: 'block', marginTop: 5 }}>
            <Src to="docs/DEV-PROMPTS-11.md">docs/DEV-PROMPTS-11.md · #124–126</Src>
          </span>
        </span>
      </div>

      <Caption titles={TITLES} details={DETAILS} index={capIdx} narrow={narrow} detailColor={P.ink2}>
        <div style={{ fontSize: 12, color: P.ink2, marginTop: 4, opacity: tween(T, { start: CUE.close, end: CUE.close + 0.6 }), lineHeight: 1.7 }}>
          完整隐私政策 <a href="/legal/privacy" style={{ fontFamily: MONO, color: P.link }}>/legal/privacy</a>（含 SDK 公示表与权限用途附录）·
          漏洞报告方式和威胁模型在 <Src to="SECURITY.md">SECURITY.md</Src>
        </div>
      </Caption>
    </Film>
  )
}
