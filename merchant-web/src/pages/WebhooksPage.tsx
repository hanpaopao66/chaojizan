import { DeleteOutlined, PlusOutlined, RedoOutlined } from '@ant-design/icons'
import {
  Alert, Button, Card, Checkbox, Form, Input, Modal, Popconfirm, Space,
  Table, Tag, Typography, message,
} from 'antd'
import { useCallback, useEffect, useState } from 'react'

import {
  addWebhook, ApiError, FailedDelivery, removeWebhook, retryWebhook,
  WebhookRow, webhooks,
} from '../api'

/**
 * 商家系统回调(收银/ERP 主动收单)。
 *
 * 此前开放接口只有两个 GET,收银系统只能轮询 —— 要么慢(轮询间隔就是
 * 延迟),要么把接口打爆(为了快就 1 秒一次)。回调是"来单就推过去"。
 *
 * 页面上必须讲清楚的三件事,因为对接的人不看文档也得能接对:
 * - 签名怎么算(HMAC-SHA256(时间戳.请求体));
 * - 为什么要按 delivery id 去重(我们会重试,同一件事可能到两次);
 * - **密钥只在创建时给一次**。
 *
 * 还有一块是死信:推了五次都没成功的单,**摊开给商家看** ——
 * 他以为收到了、实际没有,比明确失败糟得多。
 */
export default function WebhooksPage() {
  const [items, setItems] = useState<WebhookRow[]>([])
  const [failed, setFailed] = useState<FailedDelivery[]>([])
  const [events, setEvents] = useState<{ value: string; label: string }[]>([])
  const [note, setNote] = useState('')
  const [loading, setLoading] = useState(true)
  const [open, setOpen] = useState(false)
  const [secret, setSecret] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const r = await webhooks()
      setItems(r.items)
      setFailed(r.failed)
      setEvents(r.events)
      setNote(r.note)
    } catch (e) {
      message.error(e instanceof ApiError ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      <Card
        title="订单回调(对接你自己的收银 / ERP)"
        extra={
          <Button type="primary" icon={<PlusOutlined />}
            onClick={() => setOpen(true)}>新增回调地址</Button>
        }
      >
        <Alert
          type="info" showIcon style={{ marginBottom: 12 }}
          message="来单就推给你,不用轮询"
          description={note}
        />
        <Table
          rowKey="id"
          size="small"
          loading={loading}
          dataSource={items}
          pagination={false}
          locale={{ emptyText: '还没有配置回调地址' }}
          columns={[
            { title: '地址', dataIndex: 'url', ellipsis: true },
            {
              title: '订阅事件', dataIndex: 'events', width: 260,
              render: (v: string[]) => v.map((e) => (
                <Tag key={e}>
                  {events.find((x) => x.value === e)?.label ?? e}
                </Tag>)),
            },
            {
              title: '状态', width: 200,
              render: (_, r) => r.active
                ? (r.fail_streak > 0
                  ? <Tag color="orange">连续失败 {r.fail_streak} 次</Tag>
                  : <Tag color="green">正常</Tag>)
                : <Tag color="red">已自动停用</Tag>,
            },
            {
              title: '最近成功', dataIndex: 'last_ok_at', width: 170,
              render: (v: string | null) =>
                v ? new Date(v).toLocaleString('zh-CN') : '—',
            },
            {
              title: '', width: 60,
              render: (_, r) => (
                <Popconfirm
                  title="删掉这个回调?"
                  description="删除后不再推送,已排队的也不会再投。"
                  onConfirm={async () => {
                    try {
                      await removeWebhook(r.id)
                      message.success('已删除')
                      load()
                    } catch (e) {
                      message.error(e instanceof ApiError
                        ? e.message : String(e))
                    }
                  }}
                >
                  <Button type="text" danger size="small"
                    icon={<DeleteOutlined />} />
                </Popconfirm>
              ),
            },
          ]}
        />
        {items.some((i) => !i.active) && (
          <Alert
            type="error" showIcon style={{ marginTop: 12 }}
            message="有回调因连续失败被自动停用"
            description={items.find((i) => !i.active)?.last_error}
          />
        )}
      </Card>

      {failed.length > 0 && (
        <Card
          title={`没推成功的单(${failed.length})`}
          extra={items[0] && (
            <Button icon={<RedoOutlined />} onClick={async () => {
              try {
                const r = await retryWebhook(items[0].id)
                message.success(`已重新排队 ${r.requeued} 条`)
                load()
              } catch (e) {
                message.error(e instanceof ApiError ? e.message : String(e))
              }
            }}>全部重推</Button>
          )}
        >
          <Alert
            type="warning" showIcon style={{ marginBottom: 12 }}
            message="这些单重试五次都没送到你的服务器"
            description="修好之后点「全部重推」。列在这里而不是默默丢掉 —— 你以为收到了、实际没有，比明确失败糟得多。"
          />
          <Table
            rowKey="id"
            size="small"
            dataSource={failed}
            pagination={{ pageSize: 10, hideOnSinglePage: true }}
            columns={[
              { title: '订单号', dataIndex: 'order_no', width: 200 },
              { title: '事件', dataIndex: 'event', width: 140 },
              { title: '重试次数', dataIndex: 'attempts', width: 100 },
              { title: '最后错误', dataIndex: 'last_error', ellipsis: true },
              {
                title: '时间', dataIndex: 'created_at', width: 170,
                render: (v: string) => new Date(v).toLocaleString('zh-CN'),
              },
            ]}
          />
        </Card>
      )}

      <Modal
        open={open} title="新增回调地址" okText="创建"
        onCancel={() => setOpen(false)}
        footer={null}
        destroyOnClose
      >
        <NewWebhookForm
          events={events}
          onDone={(s) => { setOpen(false); setSecret(s); load() }}
        />
      </Modal>

      <Modal
        open={secret !== null}
        title="密钥只显示这一次"
        onCancel={() => setSecret(null)}
        onOk={() => setSecret(null)}
        okText="我已保存"
        cancelButtonProps={{ style: { display: 'none' } }}
      >
        <Alert
          type="warning" showIcon style={{ marginBottom: 12 }}
          message="现在就复制走"
          description="库里只存哈希,关掉这个框就再也看不到明文了。丢了只能重置，重置后旧签名立即失效。"
        />
        <Typography.Paragraph copyable code style={{ wordBreak: 'break-all' }}>
          {secret}
        </Typography.Paragraph>
      </Modal>
    </Space>
  )
}

function NewWebhookForm(
  { events, onDone }: {
    events: { value: string; label: string }[]
    onDone: (secret: string) => void
  },
) {
  const [form] = Form.useForm()
  const [busy, setBusy] = useState(false)
  return (
    <Form
      form={form} layout="vertical"
      initialValues={{ events: ['order.paid'] }}
      onFinish={async (v) => {
        setBusy(true)
        try {
          const r = await addWebhook(v.url.trim(), v.events)
          onDone(r.secret)
        } catch (e) {
          message.error(e instanceof ApiError ? e.message : String(e))
        } finally {
          setBusy(false)
        }
      }}
    >
      <Form.Item
        name="url" label="回调地址"
        rules={[{ required: true, message: '填一个公网可访问的 https 地址' }]}
        extra="只支持 http/https 的默认端口,且必须是公网地址 —— 指向内网或 localhost 的会被拒绝(那是一条安全边界,不是限制)。"
      >
        <Input placeholder="https://your-pos.example.com/superz/hook" />
      </Form.Item>
      <Form.Item
        name="events" label="订阅哪些事件"
        rules={[{ required: true, message: '至少选一个' }]}
      >
        <Checkbox.Group
          options={events.map((e) => ({ value: e.value, label: e.label }))}
          style={{ display: 'flex', flexDirection: 'column', gap: 6 }}
        />
      </Form.Item>
      <Button type="primary" htmlType="submit" loading={busy} block>
        创建
      </Button>
    </Form>
  )
}
