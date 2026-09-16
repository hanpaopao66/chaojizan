import {
  AppstoreOutlined,
  AuditOutlined,
  CarOutlined,
  CustomerServiceOutlined,
  EyeOutlined,
  MedicineBoxOutlined,
  FileTextOutlined,
  GiftOutlined,
  HeartOutlined,
  HomeOutlined,
  SolutionOutlined,
  ThunderboltOutlined,
  FlagOutlined,
  WarningOutlined,
  DashboardOutlined,
  ExceptionOutlined,
  BankOutlined,
  ControlOutlined,
  FileSearchOutlined,
  FontSizeOutlined,
  LogoutOutlined,
  MenuOutlined,
  MessageOutlined,
  SafetyCertificateOutlined,
  ShopOutlined,
  TeamOutlined,
} from '@ant-design/icons'
import { Button, Drawer, Layout, Menu, Tag } from 'antd'
import { Navigate, Route, Routes, useLocation, useNavigate } from 'react-router-dom'
import { useState } from 'react'

import { clearToken } from '../api'
import { useNarrow } from '../hooks/useNarrow'
import AftersalesPage from '../pages/AftersalesPage'
import AppealsPage from '../pages/AppealsPage'
import AuditPage from '../pages/AuditPage'
import DashboardPage from '../pages/DashboardPage'
import FoodSafetyPage from '../pages/FoodSafetyPage'
import IssuesPage from '../pages/IssuesPage'
import OrderFlagsPage from '../pages/OrderFlagsPage'
import ModerationPage from '../pages/ModerationPage'
import DispatchPage from '../pages/DispatchPage'
import InvoicesPage from '../pages/InvoicesPage'
import MarketingPage from '../pages/MarketingPage'
import RiderCarePage from '../pages/RiderCarePage'
import RiskPage from '../pages/RiskPage'
import StaysPage from '../pages/StaysPage'
import TaxPage from '../pages/TaxPage'
import TicketsPage from '../pages/TicketsPage'
import FlagsPage from '../pages/FlagsPage'
import CopyPage from '../pages/CopyPage'
import LogsPage from '../pages/LogsPage'
import MerchantsPage from '../pages/MerchantsPage'
import MiniAppsPage from '../pages/MiniAppsPage'
import RidersPage from '../pages/RidersPage'
import WithdrawalsPage from '../pages/WithdrawalsPage'
import CommunityAppealsPage from '../pages/community/AppealsPage'
import CommunityReportsPage from '../pages/community/ReportsPage'
import CommunityReviewPage from '../pages/community/ReviewPage'
import CommunitySanctionsPage from '../pages/community/SanctionsPage'
import CommunityStatsPage from '../pages/community/StatsPage'
import CommunityWordsPage from '../pages/community/WordsPage'
// 音乐治理(DEV-PROMPTS-41 #378)
import MusicAppealsPage from '../pages/music/AppealsPage'
import MusicArtistsPage from '../pages/music/ArtistsPage'
import MusicReportsPage from '../pages/music/ReportsPage'
import MusicReviewPage from '../pages/music/ReviewPage'
import ForumAppealsPage from '../pages/forum/AppealsPage'
import ForumPostsPage from '../pages/forum/PostsPage'
import ForumReportsPage from '../pages/forum/ReportsPage'
import ForumTagsPage from '../pages/forum/TagsPage'

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
    { key: '/dashboard', icon: <DashboardOutlined />, label: '数据看板' },
    { key: '/merchants', icon: <ShopOutlined />, label: '商家审核' },
    { key: '/riders', icon: <SafetyCertificateOutlined />, label: '骑手实名' },
    { key: '/withdrawals', icon: <BankOutlined />, label: '提现打款' },
    { key: '/tickets', icon: <CustomerServiceOutlined />, label: '客服工单' },
    { key: '/aftersales', icon: <ExceptionOutlined />, label: '售后仲裁' },
    { key: '/issues', icon: <CarOutlined />, label: '配送异常' },
    { key: '/food-safety', icon: <MedicineBoxOutlined />, label: '食安投诉' },
    { key: '/moderation', icon: <EyeOutlined />, label: '内容审核' },
    // 消息 / 视频的治理(DEV-PROMPTS-40 #370):先审后发的队列、举报(S8 看私聊留痕)、
    // 处罚与申诉(S6 换人)是每天要处理的;屏蔽词和数据是事后看的
    { key: 'community', icon: <TeamOutlined />, label: '社区治理', children: [
      { key: '/community/review', label: '视频审核' },
      { key: '/community/reports', label: '举报处理' },
      { key: '/community/sanctions', label: '处置记录' },
      { key: '/community/appeals', label: '申诉' },
      { key: '/community/words', label: '屏蔽词' },
      { key: '/community/stats', label: '数据' },
      // 音乐(#378):审核的单位是作品,举报里有版权投诉(带联系方式),申诉同样换人复核
      { key: '/music/review', label: '音乐审核' },
      { key: '/music/reports', label: '音乐举报' },
      { key: '/music/artists', label: '音乐人' },
      { key: '/music/appeals', label: '音乐申诉' },
    ] },
    // 论坛(DEV-PROMPTS-41 #380):举报和申诉是每天要处理的;帖子管理是巡查、回查投诉用的;
    // 热门话题单独一页 —— 隐藏一个话题要写原因、留痕(§2.2 不偷偷压话题)
    { key: 'forum', icon: <MessageOutlined />, label: '论坛', children: [
      { key: '/forum/reports', label: '论坛举报' },
      { key: '/forum/posts', label: '帖子管理' },
      { key: '/forum/tags', label: '热门话题' },
      { key: '/forum/appeals', label: '论坛申诉' },
    ] },
    { key: '/mini-apps', icon: <AppstoreOutlined />, label: '小程序' },
    { key: '/risk', icon: <WarningOutlined />, label: '风控' },
    { key: '/order-flags', icon: <FlagOutlined />, label: '异常标记' },
    { key: '/appeals', icon: <SolutionOutlined />, label: '判责申诉' },
    { key: '/rider-care', icon: <HeartOutlined />, label: '骑手关怀' },
    { key: '/dispatch', icon: <ThunderboltOutlined />, label: '运力' },
    { key: '/stays', icon: <HomeOutlined />, label: '住宿' },
    { key: '/marketing', icon: <GiftOutlined />, label: '营销' },
    { key: '/invoices', icon: <FileTextOutlined />, label: '开票' },
    { key: '/tax', icon: <BankOutlined />, label: '税务导出' },
    { key: '/flags', icon: <ControlOutlined />, label: '平台开关' },
    { key: '/copy', icon: <FontSizeOutlined />, label: '文案与显示' },
    { key: '/audit', icon: <FileSearchOutlined />, label: '对账自检' },
    { key: '/logs', icon: <AuditOutlined />, label: '操作留痕' },
  ]

  const navMenu = (
    <Menu
      mode="inline"
      selectedKeys={[location.pathname]}
      // 视频和音乐在「社区治理」下,论坛自己一栏:进到哪一块就展开哪一栏
      defaultOpenKeys={[
        ...(location.pathname.startsWith('/community/')
          || location.pathname.startsWith('/music/') ? ['community'] : []),
        ...(location.pathname.startsWith('/forum/') ? ['forum'] : []),
      ]}
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
            <Route path="/dashboard" element={<DashboardPage />} />
            <Route path="/merchants" element={<MerchantsPage />} />
            <Route path="/tickets" element={<TicketsPage />} />
            <Route path="/aftersales" element={<AftersalesPage />} />
            <Route path="/issues" element={<IssuesPage />} />
            <Route path="/food-safety" element={<FoodSafetyPage />} />
            <Route path="/moderation" element={<ModerationPage />} />
            <Route path="/community/review" element={<CommunityReviewPage />} />
            <Route path="/community/reports" element={<CommunityReportsPage />} />
            <Route path="/community/sanctions" element={<CommunitySanctionsPage />} />
            <Route path="/community/appeals" element={<CommunityAppealsPage />} />
            <Route path="/community/words" element={<CommunityWordsPage />} />
            <Route path="/community/stats" element={<CommunityStatsPage />} />
            <Route path="/music/review" element={<MusicReviewPage />} />
            <Route path="/music/reports" element={<MusicReportsPage />} />
            <Route path="/music/artists" element={<MusicArtistsPage />} />
            <Route path="/music/appeals" element={<MusicAppealsPage />} />
            <Route path="/forum/reports" element={<ForumReportsPage />} />
            <Route path="/forum/posts" element={<ForumPostsPage />} />
            <Route path="/forum/tags" element={<ForumTagsPage />} />
            <Route path="/forum/appeals" element={<ForumAppealsPage />} />
            <Route path="/mini-apps" element={<MiniAppsPage />} />
            <Route path="/risk" element={<RiskPage />} />
            <Route path="/order-flags" element={<OrderFlagsPage />} />
            <Route path="/appeals" element={<AppealsPage />} />
            <Route path="/rider-care" element={<RiderCarePage />} />
            <Route path="/dispatch" element={<DispatchPage />} />
            <Route path="/stays" element={<StaysPage />} />
            <Route path="/marketing" element={<MarketingPage />} />
            <Route path="/invoices" element={<InvoicesPage />} />
            <Route path="/tax" element={<TaxPage />} />
            <Route path="/riders" element={<RidersPage />} />
            <Route path="/withdrawals" element={<WithdrawalsPage />} />
            <Route path="/flags" element={<FlagsPage />} />
            <Route path="/copy" element={<CopyPage />} />
            <Route path="/audit" element={<AuditPage />} />
            <Route path="/logs" element={<LogsPage />} />
            <Route path="*" element={<Navigate to="/dashboard" replace />} />
          </Routes>
        </Layout.Content>
      </Layout>
    </Layout>
  )
}
