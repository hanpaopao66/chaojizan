import {
  AccountBookOutlined,
  BellOutlined,
  CalendarOutlined,
  CommentOutlined,
  GiftOutlined,
  LogoutOutlined,
  MenuFoldOutlined,
  ProfileOutlined,
  SettingOutlined,
  ShopOutlined,
} from '@ant-design/icons'
import { Layout, Menu, Switch, Tag, message } from 'antd'
import { useState } from 'react'
import { Navigate, Route, Routes, useLocation, useNavigate } from 'react-router-dom'

import { ApiError, clearToken, Merchant, updateShop } from '../api'
import CalendarPage from '../pages/hotel/CalendarPage'
import PlaceholderPage from '../pages/PlaceholderPage'

interface Props {
  shop: Merchant
  onShopChanged: () => void
}

/** 工作台外壳:左侧菜单按业态渲染,顶栏营业开关与 App 语义一致。 */
export default function ConsoleLayout({ shop, onShopChanged }: Props) {
  const [collapsed, setCollapsed] = useState(false)
  const [isOpen, setIsOpen] = useState(shop.is_open)
  const navigate = useNavigate()
  const location = useLocation()
  const isHotel = shop.biz_type === 'hotel'

  const menuItems = isHotel
    ? [
        { key: '/hotel/orders', icon: <ProfileOutlined />, label: '前台 · 订单' },
        { key: '/hotel/calendar', icon: <CalendarOutlined />, label: '房态中控台' },
        { key: '/hotel/aftersales', icon: <BellOutlined />, label: '售后处理' },
        { key: '/hotel/reviews', icon: <CommentOutlined />, label: '住客点评' },
        { key: '/finance', icon: <AccountBookOutlined />, label: '对账中心' },
        { key: '/settings', icon: <SettingOutlined />, label: '店铺设置' },
      ]
    : [
        { key: '/food/orders', icon: <ProfileOutlined />, label: '接单台' },
        { key: '/food/dishes', icon: <MenuFoldOutlined />, label: '菜品管理' },
        { key: '/food/marketing', icon: <GiftOutlined />, label: '店内营销' },
        { key: '/finance', icon: <AccountBookOutlined />, label: '对账中心' },
        { key: '/settings', icon: <SettingOutlined />, label: '店铺设置' },
      ]

  const home = isHotel ? '/hotel/orders' : '/food/orders'

  async function toggleOpen(v: boolean) {
    setIsOpen(v)
    try {
      await updateShop({ is_open: v })
      onShopChanged()
    } catch (e) {
      setIsOpen(!v)
      message.error(e instanceof ApiError ? e.message : String(e))
    }
  }

  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Layout.Sider
        collapsible
        collapsed={collapsed}
        onCollapse={setCollapsed}
        theme="light"
      >
        <div style={{
          padding: '16px 12px', fontWeight: 700, fontSize: collapsed ? 12 : 16,
          whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
        }}>
          <ShopOutlined style={{ marginRight: 6, color: '#FF5A1F' }} />
          {!collapsed && '超级赞商家'}
        </div>
        <Menu
          mode="inline"
          selectedKeys={[location.pathname]}
          items={menuItems}
          onClick={({ key }) => navigate(key)}
        />
      </Layout.Sider>
      <Layout>
        <Layout.Header style={{
          background: '#fff', padding: '0 20px', display: 'flex',
          alignItems: 'center', gap: 12, borderBottom: '1px solid #eee',
        }}>
          <span style={{ fontWeight: 600, fontSize: 16 }}>{shop.name}</span>
          <Tag color={isHotel ? 'blue' : 'orange'}>
            {isHotel ? '酒店住宿' : '餐饮外卖'}
          </Tag>
          <span style={{ flex: 1 }} />
          <span style={{ color: '#666', fontSize: 13 }}>
            {isOpen ? '营业中' : isHotel ? '已停业' : '已打烊'}
          </span>
          <Switch checked={isOpen} onChange={toggleOpen} />
          <a
            style={{ color: '#999', marginLeft: 12 }}
            onClick={() => {
              clearToken()
              navigate('/login', { replace: true })
            }}
          >
            <LogoutOutlined /> 退出
          </a>
        </Layout.Header>
        <Layout.Content style={{ padding: 16, overflow: 'auto' }}>
          <Routes>
            {isHotel ? (
              <>
                <Route path="/hotel/orders" element={<PlaceholderPage title="前台工作台" note="订单确认/入住/离店(#88)" />} />
                <Route path="/hotel/calendar" element={<CalendarPage />} />
                <Route path="/hotel/aftersales" element={<PlaceholderPage title="售后处理" note="到店无房/协商退(#88)" />} />
                <Route path="/hotel/reviews" element={<PlaceholderPage title="住客点评" note="点评与回复(#88)" />} />
              </>
            ) : (
              <>
                <Route path="/food/orders" element={<PlaceholderPage title="接单台" note="实时听单三栏看板(#85)" />} />
                <Route path="/food/dishes" element={<PlaceholderPage title="菜品管理" note="批量编辑(#86)" />} />
                <Route path="/food/marketing" element={<PlaceholderPage title="店内营销" note="满减/满赠/店铺券(#86)" />} />
              </>
            )}
            <Route path="/finance" element={<PlaceholderPage title="对账中心" note="流水/提现/发票(#89)" />} />
            <Route path="/settings" element={<PlaceholderPage title="店铺设置" note="公告/图集/店员(#90)" />} />
            <Route path="*" element={<Navigate to={home} replace />} />
          </Routes>
        </Layout.Content>
      </Layout>
    </Layout>
  )
}
