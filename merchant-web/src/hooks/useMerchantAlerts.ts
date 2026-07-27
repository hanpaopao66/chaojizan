import { useEffect, useRef, useState } from 'react'

import { merchantWsUrl } from '../api'

export interface AlertMessage {
  type: string
  order_no?: string
  summary?: string
  total_cents?: number
}

/** 网页听单基建:WS(断线自动重连) + 提示音(WebAudio 合成,无需素材) +
 *  浏览器桌面通知。声音受浏览器自动播放限制,需用户先点一次「开启声音」。 */
export function useMerchantAlerts(
  merchantId: number,
  onMessage: (msg: AlertMessage) => void,
) {
  const [connected, setConnected] = useState(false)
  const [soundOn, setSoundOn] = useState(false)
  const ctxRef = useRef<AudioContext | null>(null)
  const onMessageRef = useRef(onMessage)
  onMessageRef.current = onMessage

  function enableSound() {
    if (!ctxRef.current) ctxRef.current = new AudioContext()
    ctxRef.current.resume()
    setSoundOn(true)
    if ('Notification' in window && Notification.permission === 'default') {
      Notification.requestPermission()
    }
  }

  function beep() {
    const ctx = ctxRef.current
    if (!ctx || ctx.state !== 'running') return
    // 双音提示(叮-咚),比单音更容易在嘈杂前台被注意到
    for (const [freq, at] of [[880, 0], [660, 0.18]] as const) {
      const osc = ctx.createOscillator()
      const gain = ctx.createGain()
      osc.frequency.value = freq
      osc.connect(gain)
      gain.connect(ctx.destination)
      gain.gain.setValueAtTime(0.4, ctx.currentTime + at)
      gain.gain.exponentialRampToValueAtTime(0.01, ctx.currentTime + at + 0.4)
      osc.start(ctx.currentTime + at)
      osc.stop(ctx.currentTime + at + 0.45)
    }
  }

  function notify(title: string, body: string) {
    if ('Notification' in window && Notification.permission === 'granted') {
      const n = new Notification(title, { body })
      n.onclick = () => window.focus()
    }
  }

  useEffect(() => {
    let ws: WebSocket | null = null
    let ping: number | undefined
    let reconnect: number | undefined
    let disposed = false

    function connect() {
      if (disposed) return
      try {
        ws = new WebSocket(merchantWsUrl(merchantId))
      } catch {
        reconnect = window.setTimeout(connect, 5000)
        return
      }
      ws.onopen = () => {
        setConnected(true)
        ping = window.setInterval(() => ws?.send('ping'), 30000)
      }
      ws.onmessage = (event) => {
        try {
          onMessageRef.current(JSON.parse(event.data as string) as AlertMessage)
        } catch { /* 非 JSON 消息忽略 */ }
      }
      const onDown = () => {
        setConnected(false)
        if (ping) window.clearInterval(ping)
        if (!disposed) reconnect = window.setTimeout(connect, 5000)
      }
      ws.onerror = onDown
      ws.onclose = onDown
    }
    connect()
    return () => {
      disposed = true
      if (ping) window.clearInterval(ping)
      if (reconnect) window.clearTimeout(reconnect)
      ws?.close()
    }
  }, [merchantId])

  return { connected, soundOn, enableSound, beep, notify }
}
