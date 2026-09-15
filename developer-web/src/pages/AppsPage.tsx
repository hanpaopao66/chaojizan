import { PlusOutlined } from '@ant-design/icons'
import { Alert, Button, Card, Empty, Form, Input, List, Modal, Radio, Select, Space, Tag, Typography, message } from 'antd'
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { ApiError, AppCard, CATEGORIES, Me, api } from '../api'
import AppIcon from '../components/AppIcon'

type Row = AppCard & { current_version: string | null; reviewing: boolean }

export default function AppsPage({ me }: { me: Me | null }) {
  const nav = useNavigate()
  const [items, setItems] = useState<Row[] | null>(null)
  const [open, setOpen] = useState(false)
  const [secret, setSecret] = useState<{ appid: string; secret: string } | null>(null)
  const [busy, setBusy] = useState(false)

  const load = () => api.apps().then((r) => setItems(r.items)).catch((e) => message.error(String(e)))
  useEffect(() => { load() }, [])

  async function create(v: { name: string; kind: string; category: string; tagline: string }) {
    setBusy(true)
    try {
      const r = await api.createApp(v)
      setOpen(false)
      setSecret({ appid: r.app.appid, secret: r.app_secret })
      load()
    } catch (e) {
      message.error(e instanceof ApiError ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Card title="我的应用" extra={
      <Button type="primary" icon={<PlusOutlined />} onClick={() => setOpen(true)}
        disabled={!!me && (items?.filter((a) => a.status !== 'removed').length ?? 0) >= me.limits.max_apps}>
        新建应用
      </Button>}>
      {me && <Typography.Paragraph type="secondary" style={{ fontSize: 13 }}>
        最多 {me.limits.max_apps} 个应用(个人 5、企业 50)。流程:建应用 → 上传开发版 → 模拟器 / 扫码真机调通 → 提交审核 → 发布。
      </Typography.Paragraph>}
      {items && items.length === 0 ? (
        <Empty description="还没有应用。先建一个,再上传开发版到模拟器里跑。" />
      ) : (
        <List
          loading={!items}
          dataSource={items || []}
          renderItem={(a) => (
            <List.Item style={{ cursor: 'pointer' }} onClick={() => nav(`/apps/${a.appid}`)}
              extra={<Space>{a.reviewing && <Tag color="processing">审核中</Tag>}<Tag>{a.status_label}</Tag></Space>}>
              <List.Item.Meta
                avatar={<AppIcon icon={a.icon} name={a.name} size={44} />}
                title={<Space>{a.name}{a.kind === 'game' && <Tag>小游戏</Tag>}</Space>}
                description={<>{a.tagline || '—'} · <span style={{ fontFamily: 'monospace' }}>{a.appid}</span>
                  {a.current_version && <> · 当前 {a.current_version}</>}</>}
              />
            </List.Item>
          )}
        />
      )}

      <Modal title="新建应用" open={open} onCancel={() => setOpen(false)} footer={null} destroyOnClose>
        <Form layout="vertical" onFinish={create} disabled={busy} initialValues={{ kind: 'app', category: 'tools' }}>
          <Form.Item name="name" label="名称" rules={[{ required: true, min: 2, max: 20 }]}
            extra="不能用「超级赞」「官方」「客服」「支付」等字样;不能和已有的重名"><Input /></Form.Item>
          <Form.Item name="kind" label="类型">
            <Radio.Group>
              <Radio.Button value="app">应用</Radio.Button>
              <Radio.Button value="game">小游戏(打开即全屏、按 superz.json 锁方向)</Radio.Button>
            </Radio.Group>
          </Form.Item>
          <Form.Item name="category" label="分类">
            <Select options={Object.entries(CATEGORIES).map(([value, label]) => ({ value, label }))} />
          </Form.Item>
          <Form.Item name="tagline" label="一句话介绍" rules={[{ max: 30 }]}><Input /></Form.Item>
          <Button type="primary" htmlType="submit" block>创建</Button>
        </Form>
      </Modal>

      <Modal title="AppSecret 只显示这一次" open={!!secret} closable={false} maskClosable={false}
        footer={<Button type="primary" onClick={() => { const id = secret!.appid; setSecret(null); nav(`/apps/${id}`) }}>我已保存,继续</Button>}>
        <Alert type="warning" showIcon style={{ marginBottom: 12 }}
          message="请立刻保存到你的服务端配置里" description="平台只存密文,关掉这个窗口就再也看不到了;丢了只能在「开发设置」里轮换。" />
        <Typography.Paragraph>AppID:<Typography.Text code copyable>{secret?.appid}</Typography.Text></Typography.Paragraph>
        <Typography.Paragraph>AppSecret:<Typography.Text code copyable>{secret?.secret}</Typography.Text></Typography.Paragraph>
      </Modal>
    </Card>
  )
}
