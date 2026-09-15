import { Button, Card, Col, Empty, InputNumber, Modal, Radio, Row, Select, Space, Switch, Tag, Typography, message } from 'antd'
import { useCallback, useEffect, useRef, useState } from 'react'

import { ApiError, LaunchPayload, Version, api } from '../api'

/**
 * 在线模拟器(#331):设备外框 + iframe + 一个**模拟宿主**。
 *
 * 模拟宿主和 App 的 web 版宿主是**同一套 postMessage 协议**(DEV-PROMPTS-39 §5.4):
 * hello → init(带会话令牌)→ call / reply / event;只认 iframe 自己发来的、origin 对得上的消息。
 * initData 是**真签名**的(env=sim,用你自己的开发者身份),拿去你的后端验签能过;
 * 云存储走开发者自己的命名空间,不碰任何真实用户的数据。
 */

// 模拟宿主实现的桥协议版本(和 App 的 kBridgeProtocolVersion 同一个数)
const PROTOCOL_VERSION = '2.1'

// 启动片段里的 szWebAppVersion 换成宿主自己的版本(服务端只知道写最低的 2.0);别的参数一个字节不动
function withHostVersion(url: string): string {
  const i = url.indexOf('#')
  if (i < 0) return url
  const frag = url.slice(i + 1)
  const re = /(^|&)szWebAppVersion=[^&]*/
  return url.slice(0, i + 1) + (re.test(frag)
    ? frag.replace(re, `$1szWebAppVersion=${PROTOCOL_VERSION}`) : `${frag}&szWebAppVersion=${PROTOCOL_VERSION}`)
}

// 桥方法 → 能力(和 App 的 miniapp/bridge.dart 的 kMethodCapability 同一张表)
const CAP: Record<string, string | null> = {
  ready: null, expand: null, close: null, setHeaderColor: null, setBackgroundColor: null, setBottomBarColor: null,
  setClosingConfirmation: null, mainButton: null, secondaryButton: null, backButton: null, settingsButton: null,
  haptic: 'haptics', showPopup: 'popup', openLink: 'openLink', share: 'share',
  'CloudStorage.getItems': 'storage', 'CloudStorage.setItem': 'storage', 'CloudStorage.removeItems': 'storage',
  'CloudStorage.getKeys': 'storage', requestFullscreen: 'fullscreen', exitFullscreen: 'fullscreen',
  lockOrientation: 'orientation', unlockOrientation: 'orientation', requestProfile: 'profile',
  'legacy.getInitData': 'initData',
}
const STORAGE_OP: Record<string, string> = {
  'CloudStorage.getItems': 'get', 'CloudStorage.setItem': 'set', 'CloudStorage.removeItems': 'remove',
  'CloudStorage.getKeys': 'keys',
}

// 和 App 的 miniapp/theme.dart 同一套取值:Telegram 的 15 个键 + 超级赞的 line_color
const THEMES = {
  light: {
    bg_color: '#F0EEE6', secondary_bg_color: '#FBFAF6', text_color: '#141413', hint_color: '#6B6862',
    link_color: '#2C5F87', button_color: '#C15F3C', button_text_color: '#FBFAF6', accent_text_color: '#C15F3C',
    destructive_text_color: '#D03030', header_bg_color: '#F0EEE6', bottom_bar_bg_color: '#FBFAF6',
    section_bg_color: '#FBFAF6', section_header_text_color: '#6B6862', section_separator_color: '#E2DED2',
    subtitle_text_color: '#6B6862', line_color: '#E2DED2',
  },
  dark: {
    bg_color: '#1B1A17', secondary_bg_color: '#24231F', text_color: '#F2F0E8', hint_color: '#A8A49A',
    link_color: '#7FB2D9', button_color: '#E08A6B', button_text_color: '#1B1A17', accent_text_color: '#E08A6B',
    destructive_text_color: '#E06B6B', header_bg_color: '#1B1A17', bottom_bar_bg_color: '#24231F',
    section_bg_color: '#24231F', section_header_text_color: '#A8A49A', section_separator_color: '#37342D',
    subtitle_text_color: '#A8A49A', line_color: '#37342D',
  },
}
const DEVICES = { phone: { w: 390, h: 844, label: '390 × 844' }, small: { w: 360, h: 800, label: '360 × 800' }, tablet: { w: 768, h: 1024, label: '平板 768 × 1024' } }

interface LogRow { at: string; dir: '→' | '←' | '!'; text: string; bad?: boolean }
interface BottomBtn { text: string; is_visible: boolean; is_active: boolean; is_progress_visible: boolean; color?: string; text_color?: string }

function token(): string {
  const b = new Uint8Array(16)
  crypto.getRandomValues(b)
  return btoa(String.fromCharCode(...b)).replace(/[+/=]/g, (c) => (c === '+' ? '-' : c === '/' ? '_' : ''))
}

export default function Simulator({ appid, versions, kind }: { appid: string; versions: Version[]; kind: string }) {
  const servable = versions.filter((v) => !v.quarantined && v.status !== 'rejected')
  const [versionId, setVersionId] = useState<number | undefined>(servable[0]?.id)
  const [device, setDevice] = useState<keyof typeof DEVICES>('phone')
  const [scheme, setScheme] = useState<'light' | 'dark'>('light')
  const [platform, setPlatform] = useState('android')
  const [safeTop, setSafeTop] = useState(24)
  const [safeBottom, setSafeBottom] = useState(16)
  const [launch, setLaunch] = useState<LaunchPayload | null>(null)
  const [log, setLog] = useState<LogRow[]>([])
  const [main, setMain] = useState<BottomBtn | null>(null)
  const [secondary, setSecondary] = useState<BottomBtn | null>(null)
  const [backVisible, setBackVisible] = useState(false)
  const [settingsVisible, setSettingsVisible] = useState(false)
  const [ready, setReady] = useState(false)
  const [headerColor, setHeaderColor] = useState<string | null>(null)
  const [bottomBarColor, setBottomBarColor] = useState<string | null>(null)
  const [fullscreen, setFullscreen] = useState(kind === 'game')
  const [showPayload, setShowPayload] = useState(false)
  const frame = useRef<HTMLIFrameElement>(null)
  const tok = useRef(token())
  // 导航逃逸(和 App 网页版宿主同一个办法,见 user_app 的 EscapeWatch):iframe 每次 load 后发 ping,
  // 只有托管 origin 上、引了 SDK 的页面答得上;8 秒没有 pong 就在日志里标红
  const pingNonce = useRef<string | null>(null)
  const pingTimer = useRef<number | undefined>(undefined)
  const origin = launch ? new URL(launch.url).origin : ''

  const add = (row: Omit<LogRow, 'at'>) =>
    setLog((l) => [{ at: new Date().toLocaleTimeString('zh-CN', { hour12: false }), ...row }, ...l].slice(0, 300))

  const send = useCallback((msg: Record<string, unknown>) => {
    if (!frame.current?.contentWindow || !origin) return
    frame.current.contentWindow.postMessage({ ...msg, __sz: 2 }, origin)
  }, [origin])

  const vp = DEVICES[device]
  const initMsg = () => ({
    v: 2, type: 'init', token: tok.current, version: PROTOCOL_VERSION, platform, colorScheme: scheme,
    themeParams: THEMES[scheme],
    viewport: { height: vp.h - (fullscreen ? 0 : 56) - (main?.is_visible ? 62 : 0), stableHeight: vp.h - 56, isExpanded: true },
    safeArea: { top: fullscreen ? safeTop : 0, bottom: safeBottom, left: 0, right: 0 },
    contentSafeArea: { top: fullscreen ? safeTop + 48 : 0, bottom: 0, left: 0, right: 0 },
    capabilities: launch?.app.capabilities || [], isFullscreen: fullscreen,
    app: { appid, name: launch?.app.name },
  })

  async function start() {
    if (!versionId) return
    try {
      const r = await api.simLaunch(appid, versionId, { platform, theme: THEMES[scheme] })
      tok.current = token()
      setMain(null); setSecondary(null); setBackVisible(false); setSettingsVisible(false); setReady(false); setHeaderColor(null)
      setBottomBarColor(null)
      setLaunch(r)
      add({ dir: '!', text: `启动 ${r.version.version}(build ${r.version.build}),initData 带 env=sim` })
    } catch (e) {
      message.error(e instanceof ApiError ? e.message : String(e))
    }
  }

  // 宿主收消息:只认 iframe 自己、且 origin 是托管 origin
  useEffect(() => {
    if (!launch) return
    const onMessage = async (e: MessageEvent) => {
      if (e.source !== frame.current?.contentWindow || e.origin !== origin) return
      const m = e.data as Record<string, any>
      if (!m || m.__sz !== 2 || m.v !== 2) return
      if (m.type === 'pong') {
        if (m.nonce && m.nonce === pingNonce.current) pingNonce.current = null
        return
      }
      if (m.type === 'hello') {
        tok.current = token()
        add({ dir: '←', text: `hello(SDK ${m.sdk || '?'})` })
        send(initMsg())
        return
      }
      if (m.type === 'notice') {
        if (m.token === tok.current) add({ dir: '!', text: `CSP 拦截 ${JSON.stringify(m.data)}`, bad: true })
        return
      }
      if (m.type !== 'call') return
      if (m.token !== tok.current) {
        add({ dir: '!', text: `丢弃了一条令牌不对的调用:${m.method}(iframe 冒充或页面已过期)`, bad: true })
        return
      }
      const reply = (ok: boolean, data?: unknown, code?: number, msg?: string) => {
        send(ok ? { v: 2, type: 'reply', id: m.id, ok: true, data } : { v: 2, type: 'reply', id: m.id, ok: false, error: { code, message: msg } })
        add({ dir: '→', text: `${m.method} ${ok ? '✓' : `✗ ${code} ${msg}`}`, bad: !ok })
      }
      add({ dir: '←', text: `${m.method} ${JSON.stringify(m.params || {}).slice(0, 160)}` })
      if (!(m.method in CAP)) return reply(false, null, 4003, '宿主不支持这个方法')
      const cap = CAP[m.method]
      if (cap && !(launch.app.capabilities || []).includes(cap)) return reply(false, null, 4001, '这个小程序没有申请到这项能力')
      const p = (m.params || {}) as Record<string, any>
      try {
        switch (m.method) {
          case 'ready': setReady(true); return reply(true, true)
          case 'expand': return reply(true, true)
          case 'close': message.info('页面请求关闭(真机上容器会关掉)'); return reply(true, true)
          case 'setHeaderColor': setHeaderColor(p.color); return reply(true, true)
          case 'setBackgroundColor': return reply(true, true)
          case 'setBottomBarColor': setBottomBarColor(p.color); return reply(true, true)
          case 'setClosingConfirmation': return reply(true, true)
          case 'mainButton': setMain(p as BottomBtn); return reply(true, true)
          case 'secondaryButton': setSecondary(p as BottomBtn); return reply(true, true)
          case 'backButton': setBackVisible(!!p.is_visible); return reply(true, true)
          case 'settingsButton': setSettingsVisible(!!p.is_visible); return reply(true, true)
          case 'haptic': return reply(true, true)
          case 'showPopup': {
            const buttons = (p.buttons || [{ type: 'close' }]) as Array<{ id?: string; type?: string; text?: string }>
            const id = await new Promise<string | null>((resolve) => {
              const inst = Modal.info({
                title: p.title || undefined, content: p.message, icon: null, footer: (
                  <Space style={{ marginTop: 16, width: '100%', justifyContent: 'flex-end' }}>
                    {buttons.map((b, i) => (
                      <Button key={i} danger={b.type === 'destructive'} type={b.type === 'ok' ? 'primary' : 'default'}
                        onClick={() => { inst.destroy(); resolve(b.id ?? '') }}>
                        {b.text || { ok: '确定', cancel: '取消', destructive: '删除' }[b.type || ''] || '关闭'}
                      </Button>
                    ))}
                  </Space>),
              })
            })
            return reply(true, { button_id: id })
          }
          case 'openLink':
            if (window.confirm(`即将离开超级赞,打开 ${p.url}?`)) { window.open(p.url, '_blank', 'noopener'); return reply(true, true) }
            return reply(false, null, 4002, '用户取消了')
          case 'share':
            await navigator.clipboard?.writeText([p.text, p.url].filter(Boolean).join('\n')).catch(() => undefined)
            message.success('模拟分享:内容已复制')
            return reply(true, { shared: true })
          // 全屏:所有应用都能用(和 App 一样);已经是全屏再要一次回 ALREADY_FULLSCREEN,和 Telegram 同一个约定
          case 'requestFullscreen':
            if (fullscreen) {
              send({ v: 2, type: 'event', name: 'fullscreenFailed', data: { error: 'ALREADY_FULLSCREEN', isFullscreen: true } })
              return reply(true, true)
            }
            setFullscreen(true); send({ v: 2, type: 'event', name: 'fullscreenChanged', data: { isFullscreen: true } }); return reply(true, true)
          case 'exitFullscreen':
            if (!fullscreen) return reply(true, true)
            setFullscreen(false); send({ v: 2, type: 'event', name: 'fullscreenChanged', data: { isFullscreen: false } }); return reply(true, true)
          case 'lockOrientation': case 'unlockOrientation': return reply(true, true)
          case 'requestProfile': {
            const ok = window.confirm(`「${launch.app.name}」想获取你的昵称和头像(模拟授权)`)
            if (!ok) return reply(false, null, 4002, '用户没有同意')
            return reply(true, await api.simProfile(appid))
          }
          case 'legacy.getInitData': return reply(false, null, 4003, '托管应用请用启动片段里的 initData')
          default: {
            const op = STORAGE_OP[m.method]
            const body = m.method === 'CloudStorage.setItem' ? p : m.method === 'CloudStorage.getKeys' ? p : { keys: p.keys }
            return reply(true, await api.simStorage(appid, op, body))
          }
        }
      } catch (err) {
        const d = err instanceof ApiError ? (err.detail as { code?: number; message?: string } | undefined) : undefined
        return reply(false, null, d?.code || 5000, d?.message || (err instanceof Error ? err.message : String(err)))
      }
    }
    window.addEventListener('message', onMessage)
    return () => window.removeEventListener('message', onMessage)
  }, [launch, origin, send, scheme, platform, safeTop, safeBottom, device, fullscreen, main])

  // iframe 每加载一个文档就问一声(见 pingNonce 的注释)。每秒问一次:async 引 SDK 的页面,监听装上前的几问会丢
  const onFrameLoad = () => {
    window.clearInterval(pingTimer.current)
    const nonce = token()
    pingNonce.current = nonce
    let asked = 0
    const ask = () => { asked++; send({ v: 2, type: 'ping', nonce }) }
    ask()
    pingTimer.current = window.setInterval(() => {
      if (pingNonce.current !== nonce) { window.clearInterval(pingTimer.current); return }
      if (asked >= 8) {
        window.clearInterval(pingTimer.current)
        add({ dir: '!', bad: true, text: '页面加载后 8 秒没回应 ping:要么跳到了托管 origin 以外(真机上会被拦下,App 网页版会停止显示),要么这个页面没引 SDK' })
        return
      }
      ask()
    }, 1000)
  }
  useEffect(() => () => window.clearInterval(pingTimer.current), [])

  // 改主题、安全区:照真机一样发事件
  useEffect(() => { if (launch) send({ v: 2, type: 'event', name: 'themeChanged', data: { themeParams: THEMES[scheme], colorScheme: scheme } }) }, [scheme])
  useEffect(() => {
    if (!launch) return
    send({ v: 2, type: 'event', name: 'safeAreaChanged', data: { top: fullscreen ? safeTop : 0, bottom: safeBottom, left: 0, right: 0 } })
    // 全屏时右上角有宿主胶囊:内容安全区从屏幕边算起,把胶囊那一截(离顶 8 + 高 40)算进去
    send({ v: 2, type: 'event', name: 'contentSafeAreaChanged', data: { top: fullscreen ? safeTop + 48 : 0, bottom: 0, left: 0, right: 0 } })
  }, [safeTop, safeBottom, fullscreen])

  const theme = THEMES[scheme]
  const header = headerColor || theme.bg_color
  const btn = (b: BottomBtn, primary: boolean, name: string) => (
    <Button block type={primary ? 'primary' : 'default'} loading={b.is_progress_visible} disabled={!b.is_active}
      style={primary ? { background: b.color || theme.button_color, color: b.text_color || theme.button_text_color, border: 0 } : {}}
      onClick={() => { send({ v: 2, type: 'event', name }); add({ dir: '→', text: name }) }}>
      {b.text || (primary ? '继续' : '取消')}
    </Button>
  )

  if (!servable.length) return <Empty description="先在「版本」里上传一个开发版,再在这里跑" />
  return (
    <Row gutter={16}>
      <Col flex="none">
        <Space direction="vertical" style={{ marginBottom: 12 }}>
          <Space wrap>
            <Select style={{ width: 220 }} value={versionId} onChange={setVersionId}
              options={servable.map((v) => ({ value: v.id, label: `${v.version}(build ${v.build})· ${v.status_label}` }))} />
            <Button type="primary" onClick={start}>{launch ? '重新启动' : '启动'}</Button>
          </Space>
          <Space wrap>
            <Radio.Group size="small" value={device} onChange={(e) => setDevice(e.target.value)}
              options={Object.entries(DEVICES).map(([k, d]) => ({ value: k, label: d.label }))} optionType="button" />
          </Space>
          <Space wrap>
            <Radio.Group size="small" value={scheme} onChange={(e) => setScheme(e.target.value)} optionType="button"
              options={[{ value: 'light', label: '浅色' }, { value: 'dark', label: '深色' }]} />
            <Radio.Group size="small" value={platform} onChange={(e) => setPlatform(e.target.value)} optionType="button"
              options={[{ value: 'android', label: '安卓' }, { value: 'ios', label: 'iOS' }, { value: 'web', label: '网页' }]} />
          </Space>
          <Space wrap>
            安全区 上 <InputNumber size="small" min={0} max={60} value={safeTop} onChange={(v) => setSafeTop(Number(v) || 0)} />
            下 <InputNumber size="small" min={0} max={60} value={safeBottom} onChange={(v) => setSafeBottom(Number(v) || 0)} />
            全屏 <Switch size="small" checked={fullscreen} onChange={(on) => {
              setFullscreen(on)
              if (launch) send({ v: 2, type: 'event', name: 'fullscreenChanged', data: { isFullscreen: on } })
            }} />
          </Space>
          <Space wrap>
            <Button size="small" disabled={!launch} onClick={() => {
              if (backVisible) { send({ v: 2, type: 'event', name: 'backButtonClicked' }); add({ dir: '→', text: 'backButtonClicked(系统返回键)' }) }
              else message.info('页面没显示返回键:真机上这一下会关闭小程序')
            }}>模拟系统返回键</Button>
            <Button size="small" disabled={!launch || !settingsVisible} onClick={() => send({ v: 2, type: 'event', name: 'settingsButtonClicked' })}>··· 里的设置</Button>
            <Button size="small" disabled={!launch} onClick={() => setShowPayload(true)}>看 initData</Button>
          </Space>
        </Space>
        <div style={{
          width: vp.w, height: vp.h, maxWidth: '100%', border: '10px solid #1f1e1b', borderRadius: 28,
          background: theme.bg_color, overflow: 'hidden', display: 'flex', flexDirection: 'column', position: 'relative',
        }}>
          {!fullscreen && (
            <div style={{ height: 56, flex: 'none', background: header, borderBottom: `1px solid ${theme.line_color}`,
              display: 'flex', alignItems: 'center', gap: 8, padding: '0 10px', color: theme.text_color }}>
              {backVisible ? <a onClick={() => send({ v: 2, type: 'event', name: 'backButtonClicked' })} style={{ color: theme.text_color }}>‹</a> : null}
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontWeight: 600, fontSize: 14 }}>{launch?.app.name || '—'}</div>
                <div style={{ fontSize: 11, opacity: 0.65 }}>由 {launch?.app.developer.name || '开发者'} 提供 · {launch?.app.developer.label}</div>
              </div>
              <span>···</span><span>✕</span>
            </div>
          )}
          <div style={{ flex: 1, position: 'relative' }}>
            {launch ? (
              <iframe ref={frame} key={launch.url} src={withHostVersion(launch.url)} title="模拟器" onLoad={onFrameLoad}
                sandbox="allow-scripts allow-same-origin allow-forms"
                style={{ border: 0, width: '100%', height: '100%', background: launch.app.background_color }} />
            ) : (
              <div style={{ padding: 24, color: theme.hint_color }}>选一个版本,点「启动」</div>
            )}
            {launch && !ready && <Tag style={{ position: 'absolute', left: 8, bottom: 8 }}>等 ready()…</Tag>}
            {fullscreen && launch && (
              <div style={{ position: 'absolute', top: safeTop + 8, right: 10, background: theme.secondary_bg_color,
                border: `1px solid ${theme.line_color}`, borderRadius: 20, padding: '4px 12px', color: theme.text_color }}>··· | ✕</div>
            )}
          </div>
          {(main?.is_visible || secondary?.is_visible) && (
            <div style={{ display: 'flex', gap: 8, padding: `8px 12px ${8 + safeBottom}px`, background: bottomBarColor || theme.bottom_bar_bg_color }}>
              {secondary?.is_visible && btn(secondary, false, 'secondaryButtonClicked')}
              {main?.is_visible && btn(main, true, 'mainButtonClicked')}
            </div>
          )}
        </div>
      </Col>
      <Col flex="auto" style={{ minWidth: 280 }}>
        <Card size="small" title="桥调用日志" extra={<a onClick={() => setLog([])}>清空</a>}
          styles={{ body: { maxHeight: 760, overflow: 'auto', fontFamily: 'monospace', fontSize: 12 } }}>
          {log.length === 0 ? <Typography.Text type="secondary">启动后,页面和宿主之间的每一条消息都会出现在这里</Typography.Text>
            : log.map((r, i) => (
              <div key={i} style={{ color: r.bad ? 'var(--sz-danger)' : 'var(--sz-ink)', whiteSpace: 'pre-wrap', wordBreak: 'break-all' }}>
                <span style={{ color: 'var(--sz-ink-muted)' }}>{r.at} {r.dir}</span> {r.text}
              </div>
            ))}
        </Card>
      </Col>
      <Modal open={showPayload} title="这次启动的 initData(env=sim)" onCancel={() => setShowPayload(false)} footer={null} width={640}>
        <Typography.Paragraph type="secondary">原样交给你的后端验签:持 AppSecret 验 hash,或拿平台公钥
          (<a href="/.well-known/superz-webapp-keys.json" target="_blank" rel="noreferrer">/.well-known/superz-webapp-keys.json</a>)验 signature。
          模拟器的包带 env=sim,你的后端应据此区分测试流量。</Typography.Paragraph>
        <Typography.Paragraph code copyable style={{ wordBreak: 'break-all' }}>{launch?.init_data}</Typography.Paragraph>
      </Modal>
    </Row>
  )
}
