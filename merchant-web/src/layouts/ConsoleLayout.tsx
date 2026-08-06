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
import {
  Badge, Button, Layout, Menu, Modal, Radio, Switch, Tag, Tooltip, message,
} from 'antd'
import { useEffect, useState } from 'react'
import { Navigate, Route, Routes, useLocation, useNavigate } from 'react-router-dom'

import {
  ApiError, clearToken, Merchant, merchantTodos, setBusy, Todos, updateShop,
} from '../api'
import FinancePage from '../pages/FinancePage'
import SettingsPage from '../pages/SettingsPage'
import DishesPage from '../pages/food/DishesPage'
import FoodOrdersPage from '../pages/food/FoodOrdersPage'
import FoodReviewsPage from '../pages/food/ReviewsPage'
import MarketingPage from '../pages/food/MarketingPage'
import AftersalesPage from '../pages/hotel/AftersalesPage'
import CalendarPage from '../pages/hotel/CalendarPage'
import FrontDeskPage from '../pages/hotel/FrontDeskPage'
import ReviewsPage from '../pages/hotel/ReviewsPage'

interface Props {
  shop: Merchant
  onShopChanged: () => void
}

/** 工作台外壳:左侧菜单按业态渲染,顶栏营业开关与 App 语义一致。 */
export default function ConsoleLayout({ shop, onShopChanged }: Props) {
  const [collapsed, setCollapsed] = useState(false)
  const [isOpen, setIsOpen] = useState(shop.is_open)
  const [todos, setTodos] = useState<Todos | null>(null)
  const navigate = useNavigate()
  const location = useLocation()
  const isHotel = shop.biz_type === 'hotel'

  // 待办角标:30 秒一刷,拉不到保留上次的数,绝不打断操作
  useEffect(() => {
    let alive = true
    const load = () => merchantTodos()
      .then((t) => { if (alive) setTodos(t) })
      .catch(() => { /* 静默 */ })
    load()
    const timer = setInterval(load, 30_000)
    return () => { alive = false; clearInterval(timer) }
  }, [])

  const todoCount = todos
    ? todos.after_sales + todos.bad_reviews_unreplied
      + todos.coupon_batches_low + todos.flash_expiring
      + (todos.messages_unread ?? 0)
    : 0
  const todoTip = todos ? [
    todos.after_sales > 0 && `售后待处理 ${todos.after_sales}`,
    todos.bad_reviews_unreplied > 0 && `差评待回复 ${todos.bad_reviews_unreplied}`,
    todos.coupon_batches_low > 0 && `券快发完 ${todos.coupon_batches_low}`,
    todos.flash_expiring > 0 && `限时折扣将到期 ${todos.flash_expiring}`,
    (todos.messages_unread ?? 0) > 0 && `未读消息 ${todos.messages_unread}`,
  ].filter(Boolean).join(' · ') : ''

  // 忙碌模式:高峰压单不闭店,ETA 放宽 + 用户端亮"出餐较慢"标
  const [busyUntil, setBusyUntil] = useState<string | null>(shop.busy_until)
  const busyActive = !!busyUntil && new Date(busyUntil) > new Date()

  function busyDialog() {
    if (busyActive) {
      const left = Math.max(1, Math.round(
        (new Date(busyUntil!).getTime() - Date.now()) / 60000))
      Modal.confirm({
        title: '忙碌模式生效中',
        content: `还剩约 ${left} 分钟自动恢复;期间新单预计送达已放宽。`,
        okText: '提前结束',
        cancelText: '继续忙碌',
        onOk: async () => {
          try {
            const updated = await setBusy({ off: true })
            setBusyUntil(updated.busy_until)
          } catch (e) {
            message.error(e instanceof ApiError ? e.message : String(e))
          }
        },
      })
      return
    }
    let minutes = 60
    let extra = 10
    Modal.confirm({
      title: '开启忙碌模式(高峰压单)',
      content: (
        <div>
          <p>不闭店:新单预计送达自动放宽,用户下单前就看到「出餐较慢」。到点自动恢复。</p>
          <p>忙碌时长:
            <Radio.Group defaultValue={60} size="small"
              onChange={(e) => { minutes = e.target.value }}>
              <Radio.Button value={30}>30分</Radio.Button>
              <Radio.Button value={60}>1小时</Radio.Button>
              <Radio.Button value={120}>2小时</Radio.Button>
            </Radio.Group>
          </p>
          <p>出餐加时:
            <Radio.Group defaultValue={10} size="small"
              onChange={(e) => { extra = e.target.value }}>
              <Radio.Button value={10}>+10分</Radio.Button>
              <Radio.Button value={15}>+15分</Radio.Button>
              <Radio.Button value={20}>+20分</Radio.Button>
            </Radio.Group>
          </p>
        </div>
      ),
      okText: '开启',
      onOk: async () => {
        try {
          const updated = await setBusy({ minutes, extraMinutes: extra })
          setBusyUntil(updated.busy_until)
          message.success(`忙碌模式已开启,${minutes} 分钟后自动恢复`)
        } catch (e) {
          message.error(e instanceof ApiError ? e.message : String(e))
          return Promise.reject()
        }
      },
    })
  }

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
        { key: '/food/reviews', icon: <CommentOutlined />, label: '顾客评价' },
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
          {todoCount > 0 && (
            <Tooltip title={todoTip}>
              <Badge count={todoCount} size="small">
                <BellOutlined
                  style={{ fontSize: 18, color: '#FF5A1F', cursor: 'pointer' }}
                  onClick={() => navigate(
                    todos && todos.bad_reviews_unreplied > 0 && !isHotel
                      ? '/food/reviews'
                      : isHotel ? '/hotel/aftersales' : '/food/orders')}
                />
              </Badge>
            </Tooltip>
          )}
          {/* 忙碌模式走 owner-only 接口,店员不给入口 */}
          {!isHotel && !shop.viewer_is_staff && (
            <Button size="small" danger={busyActive} onClick={busyDialog}>
              {busyActive ? '🔥 忙碌中' : '忙碌模式'}
            </Button>
          )}
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
                <Route path="/hotel/orders" element={<FrontDeskPage shop={shop} />} />
                <Route path="/hotel/calendar" element={<CalendarPage />} />
                <Route path="/hotel/aftersales" element={<AftersalesPage />} />
                <Route path="/hotel/reviews" element={<ReviewsPage />} />
              </>
            ) : (
              <>
                <Route path="/food/orders" element={<FoodOrdersPage shop={shop} />} />
                <Route path="/food/dishes" element={<DishesPage />} />
                <Route path="/food/marketing" element={<MarketingPage />} />
                <Route path="/food/reviews" element={<FoodReviewsPage />} />
              </>
            )}
            <Route path="/finance" element={<FinancePage shop={shop} />} />
            <Route path="/settings"
              element={<SettingsPage shop={shop} onShopChanged={onShopChanged} />} />
            <Route path="*" element={<Navigate to={home} replace />} />
          </Routes>
        </Layout.Content>
      </Layout>
    </Layout>
  )
}
