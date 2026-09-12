import { AppstoreOutlined, BellOutlined, BookOutlined, IdcardOutlined, LogoutOutlined } from '@ant-design/icons'
import { Alert, Layout, Menu, Tag } from 'antd'
import { useEffect, useState } from 'react'
import { Navigate, Route, Routes, useLocation, useNavigate } from 'react-router-dom'

import { Me, api, clearToken } from '../api'
import AccountPage from '../pages/AccountPage'
import AppDetailPage from '../pages/AppDetailPage'
import AppsPage from '../pages/AppsPage'
import MessagesPage from '../pages/MessagesPage'

export default function ConsoleLayout({ onLogout }: { onLogout: () => void }) {
  const nav = useNavigate()
  const loc = useLocation()
  const [me, setMe] = useState<Me | null>(null)
  const reloadMe = () => api.me().then(setMe).catch(() => undefined)
  useEffect(() => { reloadMe() }, [])

  const selected = loc.pathname.startsWith('/account') ? '/account'
    : loc.pathname.startsWith('/messages') ? '/messages' : '/apps'
  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Layout.Sider theme="light" width={184} breakpoint="md" collapsedWidth={0}>
        <div style={{ padding: '16px 14px 10px', fontWeight: 700, fontSize: 16 }}>超级赞开发者</div>
        <Menu
          mode="inline"
          selectedKeys={[selected]}
          onClick={({ key }) => (key === 'docs' ? window.open('/developers', '_blank') : nav(key))}
          items={[
            { key: '/apps', icon: <AppstoreOutlined />, label: '我的应用' },
            { key: '/account', icon: <IdcardOutlined />, label: '账号与认证' },
            { key: '/messages', icon: <BellOutlined />, label: '消息' },
            { key: 'docs', icon: <BookOutlined />, label: '开发者文档' },
          ]}
        />
      </Layout.Sider>
      <Layout>
        <Layout.Header style={{
          background: 'var(--sz-surface)', borderBottom: '1px solid var(--sz-line)',
          display: 'flex', alignItems: 'center', gap: 12, padding: '0 20px',
        }}>
          <span style={{ fontWeight: 600 }}>{me?.display_name || '开发者'}</span>
          {me && <Tag color={me.status === 'verified' ? 'success' : me.status === 'pending' ? 'processing' : 'default'}>
            {me.public.label}
          </Tag>}
          <span style={{ flex: 1 }} />
          <a style={{ color: 'var(--sz-ink-muted)' }} onClick={() => { clearToken(); onLogout(); nav('/login', { replace: true }) }}>
            <LogoutOutlined /> 退出
          </a>
        </Layout.Header>
        <Layout.Content style={{ padding: 20, maxWidth: 1180, width: '100%', margin: '0 auto' }}>
          {me && !me.agreement.ok && loc.pathname !== '/account' && (
            <Alert type="warning" showIcon style={{ marginBottom: 16 }}
              message={me.agreement.accepted ? '开发者规则有更新' : '还没接受开发者规则'}
              description="接受最新版本的开发者规则后才能提交审核。"
              action={<a onClick={() => nav('/account')}>去看看</a>} />
          )}
          <Routes>
            <Route path="/apps" element={<AppsPage me={me} />} />
            <Route path="/apps/:appid/*" element={<AppDetailPage me={me} />} />
            <Route path="/account" element={<AccountPage me={me} onChanged={setMe} reload={reloadMe} />} />
            <Route path="/messages" element={<MessagesPage />} />
            <Route path="*" element={<Navigate to="/apps" replace />} />
          </Routes>
        </Layout.Content>
      </Layout>
    </Layout>
  )
}
