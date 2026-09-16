import { Alert, Button, Card, Form, Input, Space, Tabs, Typography } from 'antd'
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { ApiError, login, sendLoginCode, smsLogin } from '../api'

/**
 * 平台后台登录。
 *
 * **验证码是生产上唯一进得来的路。** 服务端 `auth.admin_password_login_allowed()`
 * 是「开关 && is_dev」,生产恒为假 —— 管理员用密码登录会被 403
 * 「管理员请使用手机验证码登录」顶回来。密码那一栏只在开发 / 预发用得上,
 * 所以放在第二个页签。
 *
 * 这一页原先只有密码一栏,注释还写着「管理后台不做短信验证码」——
 * 和服务端的口径正好相反,于是**生产的后台登录页根本进不去**
 * (2026-09-16 发现)。开发环境两条都通,所以本地怎么点都是好的。
 */
export default function LoginPage({ onAuthed }: { onAuthed: () => void }) {
  const nav = useNavigate()
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState('')
  const [phone, setPhone] = useState('')
  const [sending, setSending] = useState(false)
  const [left, setLeft] = useState(0)   // 重发倒计时(后端 60 秒冷却)

  useEffect(() => {
    if (left <= 0) return
    const t = setTimeout(() => setLeft(left - 1), 1000)
    return () => clearTimeout(t)
  }, [left])

  async function done(run: () => Promise<unknown>) {
    setErr('')
    setLoading(true)
    try {
      await run()
      // 先告诉 App 已登录,再跳 —— 反过来的话 App 那一层还是旧的登录态,
      // 会把刚跳过去的路由又弹回登录页(见 App.tsx 的注释)
      onAuthed()
      nav('/dashboard', { replace: true })
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }

  async function onSend() {
    const p = phone.trim()
    if (!/^1\d{10}$/.test(p)) {
      setErr('先填管理员手机号')
      return
    }
    setErr('')
    setSending(true)
    try {
      await sendLoginCode(p)
      setLeft(60)
    } catch (e) {
      // 后端那几句原话直接显示:今日上限、滑块(captcha_required)、发送失败。
      // 这一页没有滑块,撞上了要么等明天,要么去用户端登录一次把计数清掉
      setErr(e instanceof ApiError ? e.message : String(e))
    } finally {
      setSending(false)
    }
  }

  const phoneItem = (
    <Form.Item name="phone" label="管理员手机号"
               rules={[{ required: true, message: '请输入手机号' },
                       { pattern: /^1\d{10}$/, message: '手机号格式不对' }]}>
      <Input autoComplete="username" placeholder="管理员手机号" inputMode="numeric"
             onChange={(e) => setPhone(e.target.value)} />
    </Form.Item>
  )

  return (
    <div style={{
      minHeight: '100vh', display: 'flex', alignItems: 'center',
      justifyContent: 'center', background: 'var(--sz-paper)', padding: 16,
    }}>
      <Card style={{ width: 380, maxWidth: '100%' }}>
        <Typography.Title level={4} style={{ textAlign: 'center', marginTop: 0 }}>
          超级赞平台后台
        </Typography.Title>
        <Typography.Paragraph style={{
          textAlign: 'center', color: 'var(--sz-ink-muted)', fontSize: 13,
        }}>
          这里的每一个操作都会留痕
        </Typography.Paragraph>
        {err && (
          <Alert type="error" showIcon message={err}
                 style={{ marginBottom: 12 }} />
        )}
        <Tabs
          defaultActiveKey="code"
          items={[
            {
              key: 'code',
              label: '验证码登录',
              children: (
                <Form layout="vertical" disabled={loading}
                      onFinish={(v: { phone: string; code: string }) =>
                        done(() => smsLogin(v.phone.trim(), v.code.trim()))}>
                  {phoneItem}
                  <Form.Item name="code" label="短信验证码"
                             rules={[{ required: true, message: '请输入验证码' },
                                     { pattern: /^\d{6}$/, message: '验证码是 6 位数字' }]}>
                    <Space.Compact style={{ width: '100%' }}>
                      <Input placeholder="6 位验证码" inputMode="numeric"
                             autoComplete="one-time-code" />
                      <Button onClick={onSend} loading={sending} disabled={left > 0}>
                        {left > 0 ? `${left} 秒后重发` : '发送验证码'}
                      </Button>
                    </Space.Compact>
                  </Form.Item>
                  <Button type="primary" htmlType="submit" block loading={loading}>
                    登录
                  </Button>
                </Form>
              ),
            },
            {
              key: 'password',
              label: '密码登录',
              children: (
                <Form layout="vertical" disabled={loading}
                      onFinish={(v: { phone: string; password: string }) =>
                        done(() => login(v.phone.trim(), v.password))}>
                  {phoneItem}
                  <Form.Item name="password" label="密码"
                             rules={[{ required: true, message: '请输入密码' }]}>
                    <Input.Password autoComplete="current-password" placeholder="密码" />
                  </Form.Item>
                  <Button type="primary" htmlType="submit" block loading={loading}>
                    登录
                  </Button>
                  <Typography.Paragraph style={{
                    marginTop: 10, marginBottom: 0,
                    color: 'var(--sz-ink-muted)', fontSize: 12,
                  }}>
                    生产环境管理员不能用密码登录(服务端只认验证码),这一栏是给开发和预发用的。
                  </Typography.Paragraph>
                </Form>
              ),
            },
          ]}
        />
      </Card>
    </div>
  )
}
