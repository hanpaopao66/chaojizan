import { PlusOutlined } from '@ant-design/icons'
import { Alert, Button, Card, Empty, Form, Input, List, Modal, Space, Tag, Typography, message } from 'antd'
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { ApiError, BotDev, api } from '../api'
import AppIcon from '../components/AppIcon'
import TokenModal from '../components/TokenModal'

/** 机器人列表(#355):建机器人弹窗,建完展示 token(只显示这一次) */
export default function BotsPage() {
  const nav = useNavigate()
  const [data, setData] = useState<{ items: BotDev[]; max: number; enabled: boolean } | null>(null)
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [created, setCreated] = useState<{ id: number; token: string } | null>(null)

  const load = () => api.bots().then(setData).catch((e) => message.error(e instanceof ApiError ? e.message : String(e)))
  useEffect(() => { load() }, [])

  async function create(v: { name: string; username: string }) {
    setBusy(true)
    try {
      const r = await api.createBot({ name: v.name.trim(), username: v.username.trim().replace(/^@/, '') })
      setOpen(false)
      setCreated({ id: r.bot.id, token: r.token })
      load()
    } catch (e) {
      message.error(e instanceof ApiError ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  const full = !!data && data.items.length >= data.max
  return (
    <Card title="机器人" extra={
      <Button type="primary" icon={<PlusOutlined />} onClick={() => setOpen(true)} disabled={!data || full || !data.enabled}>
        新建机器人
      </Button>}>
      {data && !data.enabled && (
        <Alert type="info" showIcon style={{ marginBottom: 12 }} message="机器人功能暂未开放"
          description="平台开关关着:现在不能建新机器人,Bot API 一律返回 503。已有的机器人照样能看、能改、能删。" />
      )}
      <Typography.Paragraph type="secondary" style={{ fontSize: 13 }}>
        机器人用 token 调 Bot API(形状对齐 Telegram 的子集,接口文档见开源仓库的 docs/BOT-API.md),
        在用户的私聊和群里说话。它<Typography.Text strong>不能主动找人</Typography.Text>:
        只能回复和它说过话的用户、只能在拉它进去的群里发言。每个开发者最多 {data?.max ?? 20} 个。
      </Typography.Paragraph>
      {data && data.items.length === 0 ? (
        <Empty description="还没有机器人。建一个,拿到 token 就能用 getUpdates 收消息了。" />
      ) : (
        <List
          loading={!data}
          dataSource={data?.items || []}
          renderItem={(b) => (
            <List.Item style={{ cursor: 'pointer' }} onClick={() => nav(`/bots/${b.id}`)}
              extra={<Space wrap>
                {b.webhook.url ? <Tag color={b.webhook.last_error_message ? 'warning' : 'success'}>webhook</Tag> : <Tag>getUpdates</Tag>}
                {b.webhook.pending_update_count > 0 && <Tag color="processing">待送 {b.webhook.pending_update_count}</Tag>}
                <Tag>{b.privacy_mode ? '隐私模式' : '读全部群消息'}</Tag>
              </Space>}>
              <List.Item.Meta
                avatar={<AppIcon icon={b.avatar} name={b.name} size={44} />}
                title={b.name}
                description={<>@{b.username} · token <span style={{ fontFamily: 'monospace' }}>{b.token_prefix}…</span>
                  {b.about && <> · {b.about}</>}</>}
              />
            </List.Item>
          )}
        />
      )}

      <Modal title="新建机器人" open={open} onCancel={() => setOpen(false)} footer={null} destroyOnClose>
        <Form layout="vertical" onFinish={create} disabled={busy}>
          <Form.Item name="name" label="名字" rules={[{ required: true, max: 32 }]} extra="用户在会话列表、资料卡上看到的名字,之后能改">
            <Input placeholder="点餐助手" />
          </Form.Item>
          <Form.Item name="username" label="用户名" extra="5–32 位字母、数字、下划线,字母开头,必须以 bot 结尾;和用户、群、频道共用一个命名空间,建了不能改"
            rules={[{ required: true }, { pattern: /^@?[A-Za-z][A-Za-z0-9_]{3,31}$/, message: '5–32 位字母、数字、下划线,字母开头' },
              { pattern: /bot$/i, message: '机器人的用户名必须以 bot 结尾' }]}>
            <Input addonBefore="@" placeholder="diancan_bot" />
          </Form.Item>
          <Button type="primary" htmlType="submit" block>创建</Button>
        </Form>
      </Modal>

      <TokenModal token={created?.token ?? null}
        onDone={() => { const id = created!.id; setCreated(null); nav(`/bots/${id}`) }} />
    </Card>
  )
}
