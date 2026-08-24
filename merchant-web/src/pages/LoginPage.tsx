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
      justifyContent: 'center', background: 'var(--sz-paper)',
    }}>
      <Card style={{ width: 380 }}>
        <div style={{ textAlign: 'center', marginBottom: 16 }}>
          <div style={{ fontSize: 22, fontWeight: 700 }}>超级赞商家工作台</div>
          <div style={{ color: 'var(--sz-ink-muted)', fontSize: 13, marginTop: 4 }}>
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
        <div style={{ color: 'var(--sz-ink-muted)', fontSize: 12, marginTop: 12, textAlign: 'center' }}>
          登录即代表已阅读并同意
          <a href="/legal/terms" target="_blank" rel="noreferrer">《用户协议》</a>
          和
          <a href="/legal/privacy" target="_blank" rel="noreferrer">《隐私政策》</a>
        </div>
        {/* 「先去 App 入驻」必须**给得到 App**。
            原来这句是纯文本:一个店主在手机上打开网页版,被告知去下载
            商家端,却没有任何可点的地方 —— 他得自己去搜。
            这是新用户唯一的入口,不能是条死路。 */}
        <div style={{ color: 'var(--sz-ink-muted)', fontSize: 12, marginTop: 6, textAlign: 'center' }}>
          首次使用?请先用「超级赞商家」App 完成入驻,网页版与 App 同一账号
          <div style={{ marginTop: 6 }}>
            <a href="/appdist/chaojizan-merchant-arm64.apk">下载商家端 App（安卓）</a>
            <span style={{ margin: '0 8px', opacity: .5 }}>·</span>
            <a href="/join/merchant" target="_blank" rel="noreferrer">先看看入驻能省多少</a>
          </div>
        </div>
      </Card>
    </div>
  )
}
