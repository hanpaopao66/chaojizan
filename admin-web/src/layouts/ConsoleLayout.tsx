import {
  AuditOutlined,
  BankOutlined,
  ControlOutlined,
  FileSearchOutlined,
  LogoutOutlined,
  MenuOutlined,
  SafetyCertificateOutlined,
  ShopOutlined,
} from '@ant-design/icons'
import { Button, Drawer, Layout, Menu, Tag } from 'antd'
import { Navigate, Route, Routes, useLocation, useNavigate } from 'react-router-dom'
import { useState } from 'react'

import { clearToken } from '../api'
import { useNarrow } from '../hooks/useNarrow'
import AuditPage from '../pages/AuditPage'
import FlagsPage from '../pages/FlagsPage'
import LogsPage from '../pages/LogsPage'
import MerchantsPage from '../pages/MerchantsPage'
import RidersPage from '../pages/RidersPage'
import WithdrawalsPage from '../pages/WithdrawalsPage'

/**
 * 平台后台外壳。
 *
 * 菜单顺序不是随手排的,是按**不做就会卡住业务**排的:
 * 商家审核和骑手实名不批,人就永远进不来;提现不放,钱就卡着;
 * 平台开关是出事那天要立刻改的;对账自检和留痕是事后看的。
 */
export default function ConsoleLayout({ onLogout }: { onLogout: () => void }) {
  const nav = useNavigate()
  const location = useLocation()
  const narrow = useNarrow()
  const [drawerOpen, setDrawerOpen] = useState(false)

  const items = [
    { key: '/merchants', icon: <ShopOutlined />, label: '商家审核' },
    { key: '/riders', icon: <SafetyCertificateOutlined />, label: '骑手实名' },
    { key: '/withdrawals', icon: <BankOutlined />, label: '提现打款' },
    { key: '/flags', icon: <ControlOutlined />, label: '平台开关' },
    { key: '/audit', icon: <FileSearchOutlined />, label: '对账自检' },
    { key: '/logs', icon: <AuditOutlined />, label: '操作留痕' },
  ]

  const navMenu = (
    <Menu
      mode="inline"
      selectedKeys={[location.pathname]}
      items={items}
      onClick={({ key }) => { nav(key); setDrawerOpen(false) }}
    />
  )

  return (
    <Layout style={{ minHeight: '100vh' }}>
      {!narrow && (
        <Layout.Sider theme="light" width={168}>
          <div style={{
            padding: '16px 12px', fontWeight: 700, fontSize: 16,
            whiteSpace: 'nowrap',
          }}>
            超级赞平台
          </div>
          {navMenu}
        </Layout.Sider>
      )}
      <Drawer
        placement="left"
        open={narrow && drawerOpen}
        onClose={() => setDrawerOpen(false)}
        width={220}
        title="超级赞平台"
        styles={{ body: { padding: 0 } }}
      >
        {navMenu}
      </Drawer>
      <Layout>
        <Layout.Header style={{
          background: 'var(--sz-surface)', display: 'flex', alignItems: 'center',
          gap: 12, borderBottom: '1px solid var(--sz-line)',
          ...(narrow
            ? { padding: '10px 12px', height: 'auto', lineHeight: 1.6 }
            : { padding: '0 20px' }),
        }}>
          {narrow && (
            <Button type="text" icon={<MenuOutlined />} aria-label="打开菜单"
                    onClick={() => setDrawerOpen(true)} />
          )}
          <span style={{ fontWeight: 600 }}>平台管理后台</span>
          {/* 常驻提醒:这不是装饰。这几页碰的是钱和资格,
              让操作的人一直看得见"有人能查到我做了什么" */}
          <Tag color="warning">操作留痕中</Tag>
          <span style={{ flex: 1 }} />
          <a style={{ color: 'var(--sz-ink-muted)' }}
             onClick={() => { clearToken(); onLogout(); nav('/login', { replace: true }) }}>
            <LogoutOutlined /> 退出
          </a>
        </Layout.Header>
        <Layout.Content style={{ padding: 16, overflow: 'auto' }}>
          <Routes>
            <Route path="/merchants" element={<MerchantsPage />} />
            <Route path="/riders" element={<RidersPage />} />
            <Route path="/withdrawals" element={<WithdrawalsPage />} />
            <Route path="/flags" element={<FlagsPage />} />
            <Route path="/audit" element={<AuditPage />} />
            <Route path="/logs" element={<LogsPage />} />
            <Route path="*" element={<Navigate to="/merchants" replace />} />
          </Routes>
        </Layout.Content>
      </Layout>
    </Layout>
  )
}
