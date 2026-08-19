import { Alert, Button, Card, Form, Input, Typography } from 'antd'
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { ApiError, login } from '../api'

/**
 * 平台后台登录。
 *
 * **只有验证码之外的口令登录一条路** —— 管理后台不做短信验证码:
 * 验证码登录的前提是"手机号就是身份",而管理员账号是内部分配的,
 * 换手机号该走内部流程,不该在登录页自助完成。
 */
export default function LoginPage({ onAuthed }: { onAuthed: () => void }) {
  const nav = useNavigate()
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState('')

  async function onFinish(v: { phone: string; password: string }) {
    setErr('')
    setLoading(true)
    try {
      await login(v.phone.trim(), v.password)
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
        <Form layout="vertical" onFinish={onFinish} disabled={loading}>
          <Form.Item name="phone" label="管理员手机号"
                     rules={[{ required: true, message: '请输入手机号' }]}>
            <Input autoComplete="username" placeholder="管理员手机号" />
          </Form.Item>
          <Form.Item name="password" label="密码"
                     rules={[{ required: true, message: '请输入密码' }]}>
            <Input.Password autoComplete="current-password" placeholder="密码" />
          </Form.Item>
          <Button type="primary" htmlType="submit" block loading={loading}>
            登录
          </Button>
        </Form>
      </Card>
    </div>
  )
}
