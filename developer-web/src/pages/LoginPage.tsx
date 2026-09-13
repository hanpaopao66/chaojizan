import { Alert, Button, Card, Form, Input, Space, Typography } from 'antd'
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { ApiError, sendCode, smsLogin } from '../api'

/**
 * 开发者登录 / 注册:手机号 + 短信验证码(和三端同一套 /auth,role=developer)。
 * 注册对所有人开放:没注册过的手机号登录一次就是注册。平台临时收紧或暂停注册时,
 * 服务端会回 403 并说明原因,照原样显示。
 */
export default function LoginPage({ onAuthed }: { onAuthed: () => void }) {
  const nav = useNavigate()
  const [phone, setPhone] = useState('')
  const [code, setCode] = useState('')
  const [err, setErr] = useState('')
  const [hint, setHint] = useState('')
  const [cooldown, setCooldown] = useState(0)
  const [loading, setLoading] = useState(false)

  async function onSend() {
    setErr('')
    try {
      const r = await sendCode(phone.trim())
      setCooldown(60)
      const t = setInterval(() => setCooldown((c) => { if (c <= 1) clearInterval(t); return c - 1 }), 1000)
      if (r.dev_code) setHint(`开发环境验证码:${r.dev_code}`)
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : String(e))
    }
  }

  async function onLogin() {
    setErr('')
    setLoading(true)
    try {
      await smsLogin(phone.trim(), code.trim())
      onAuthed()
      nav('/apps', { replace: true })
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div style={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'var(--sz-paper)', padding: 16 }}>
      <Card style={{ width: 400, maxWidth: '100%' }}>
        <Typography.Title level={4} style={{ marginTop: 0 }}>超级赞开发者后台</Typography.Title>
        <Typography.Paragraph type="secondary" style={{ fontSize: 13 }}>
          用手机号登录;第一次登录就是注册。发布免费,没有竞价排名。
          <a href="/developers" target="_blank" rel="noreferrer"> 先看看文档 ›</a>
        </Typography.Paragraph>
        {err && <Alert type="error" showIcon message={err} style={{ marginBottom: 12 }} />}
        {hint && <Alert type="info" message={hint} style={{ marginBottom: 12 }} />}
        <Form layout="vertical" onFinish={onLogin} disabled={loading}>
          <Form.Item label="手机号" required>
            <Input value={phone} onChange={(e) => setPhone(e.target.value)} placeholder="11 位手机号" autoComplete="tel" />
          </Form.Item>
          <Form.Item label="验证码" required>
            <Space.Compact style={{ width: '100%' }}>
              <Input value={code} onChange={(e) => setCode(e.target.value)} placeholder="6 位验证码" autoComplete="one-time-code" />
              <Button onClick={onSend} disabled={!/^1\d{10}$/.test(phone.trim()) || cooldown > 0}>
                {cooldown > 0 ? `${cooldown} 秒` : '获取验证码'}
              </Button>
            </Space.Compact>
          </Form.Item>
          <Button type="primary" htmlType="submit" block loading={loading} disabled={!/^\d{6}$/.test(code.trim())}>
            登录
          </Button>
        </Form>
      </Card>
    </div>
  )
}
