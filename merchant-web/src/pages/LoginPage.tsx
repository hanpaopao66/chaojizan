import { Alert, Button, Card, Form, Input, Segmented, Space, message } from 'antd'
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { ApiError, passwordLogin, sendSmsCode, setToken, smsLogin } from '../api'

/** 登录:验证码为主(与 App 一致),密码为辅。role 固定 merchant——
 *  同一手机号的用户/骑手账号不会被误登进来(账号按角色分立)。 */
export default function LoginPage() {
  const [mode, setMode] = useState<'sms' | 'password'>('sms')
  const [phone, setPhone] = useState('')
  const [code, setCode] = useState('')
  const [password, setPassword] = useState('')
  const [devCode, setDevCode] = useState<string | null>(null)
  const [countdown, setCountdown] = useState(0)
  const [busy, setBusy] = useState(false)
  const navigate = useNavigate()

  const validPhone = /^1\d{10}$/.test(phone)

  async function handleSend() {
    if (!validPhone) return message.warning('请输入 11 位手机号')
    try {
      const dev = await sendSmsCode(phone)
      setDevCode(dev)
      setCountdown(60)
      const timer = setInterval(() => {
        setCountdown((n) => {
          if (n <= 1) clearInterval(timer)
          return n - 1
        })
      }, 1000)
      if (!dev) message.success('验证码已发送')
    } catch (e) {
      message.error(e instanceof ApiError ? e.message : String(e))
    }
  }

  async function handleLogin() {
    if (!validPhone) return message.warning('请输入 11 位手机号')
    setBusy(true)
    try {
      const result = mode === 'sms'
        ? await smsLogin(phone, code)
        : await passwordLogin(phone, password)
      setToken(result.token)
      navigate('/', { replace: true })
    } catch (e) {
      message.error(e instanceof ApiError ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div style={{
      minHeight: '100vh', display: 'flex', alignItems: 'center',
      justifyContent: 'center', background: '#f5f5f5',
    }}>
      <Card style={{ width: 380 }}>
        <div style={{ textAlign: 'center', marginBottom: 16 }}>
          <div style={{ fontSize: 22, fontWeight: 700 }}>超级赞商家工作台</div>
          <div style={{ color: '#888', fontSize: 13, marginTop: 4 }}>
            入驻免费 · 外卖 5% 封顶 · 住宿 5% 离店才收
          </div>
        </div>
        <Segmented
          block
          options={[
            { label: '验证码登录', value: 'sms' },
            { label: '密码登录', value: 'password' },
          ]}
          value={mode}
          onChange={(v) => setMode(v as 'sms' | 'password')}
          style={{ marginBottom: 16 }}
        />
        <Form layout="vertical" onFinish={handleLogin}>
          <Form.Item label="手机号">
            <Input
              placeholder="商家手机号"
              maxLength={11}
              value={phone}
              onChange={(e) => setPhone(e.target.value.trim())}
            />
          </Form.Item>
          {mode === 'sms' ? (
            <Form.Item label="验证码">
              <Space.Compact style={{ width: '100%' }}>
                <Input
                  placeholder="6 位验证码"
                  maxLength={6}
                  value={code}
                  onChange={(e) => setCode(e.target.value.trim())}
                />
                <Button onClick={handleSend} disabled={countdown > 0}>
                  {countdown > 0 ? `${countdown}s` : '发验证码'}
                </Button>
              </Space.Compact>
            </Form.Item>
          ) : (
            <Form.Item label="密码">
              <Input.Password
                placeholder="密码"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
            </Form.Item>
          )}
          {devCode && (
            <Alert
              type="info"
              showIcon
              style={{ marginBottom: 12 }}
              message={`开发模式验证码:${devCode}(短信服务未配置时直接返回)`}
            />
          )}
          <Button type="primary" htmlType="submit" block loading={busy}>
            登录
          </Button>
        </Form>
        <div style={{ color: '#999', fontSize: 12, marginTop: 12, textAlign: 'center' }}>
          首次使用?请先在「超级赞商家」App 完成入驻,网页版与 App 同一账号
        </div>
      </Card>
    </div>
  )
}
