import { Alert, Button, Form, Input, InputNumber, Modal, Space, Switch, Table, Tag, message } from 'antd'
import { useCallback, useEffect, useState } from 'react'

import { AiBot, aiBotSayNow, aiBots, ApiError, createAiBot, patchAiBot } from '../api'

/**
 * AI 机器人。
 *
 * ## 立场写在这一页上,不只写在代码里
 *
 * **只做明确的机器人,不做假装成人的号。** 这几个号:
 *
 * - 超级赞号必须以 `bot` 结尾,名片上有「机器人」和「AI」两个标;
 * - **互动不进任何公开榜单和推荐权重** —— 推荐公式是公开可复算的,自己刷自己等于自己骗自己;
 * - 发帖走和真人一样的路:违禁词、先审后发、举报、下架、禁言全都管得到。
 *
 * ## 节奏为什么是「每天几条」不是「多久一次」
 *
 * 运营脑子里想的是"这个号一天说几句",不是"每 4.8 小时一次"。
 * 换算(24 小时 ÷ 条数 = 最小间隔)交给代码。
 */
export default function AiBotsPage() {
  const [rows, setRows] = useState<AiBot[]>([])
  const [loading, setLoading] = useState(false)
  const [adding, setAdding] = useState(false)
  const [editing, setEditing] = useState<AiBot | null>(null)
  const [form] = Form.useForm()
  const [editForm] = Form.useForm()

  const fail = (e: unknown) => message.error(e instanceof ApiError ? e.message : String(e))

  const load = useCallback(async () => {
    setLoading(true)
    try {
      setRows((await aiBots()).items)
    } catch (e) { fail(e) } finally { setLoading(false) }
  }, [])

  useEffect(() => { void load() }, [load])

  async function add() {
    try {
      const v = await form.validateFields()
      await createAiBot(v)
      message.success('建好了。**它还不会说话** —— 总闸在「平台开关」页')
      setAdding(false)
      form.resetFields()
      void load()
    } catch (e) {
      if (e instanceof ApiError) fail(e)
    }
  }

  async function saveEdit() {
    if (!editing) return
    try {
      const v = await editForm.validateFields()
      await patchAiBot(editing.user_id, v)
      setEditing(null)
      void load()
    } catch (e) {
      if (e instanceof ApiError) fail(e)
    }
  }

  async function sayNow(row: AiBot) {
    try {
      const r = await aiBotSayNow(row.user_id)
      Modal.info({
        title: `${row.name} 说:`,
        content: <div style={{ whiteSpace: 'pre-wrap' }}>{r.text}</div>,
        width: 520,
      })
      void load()
    } catch (e) { fail(e) }
  }

  return (
    <>
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
        message="这些号是明确标注的机器人"
        description={
          '名片上带「机器人」和「AI」两个标,超级赞号以 bot 结尾。'
          + '它们的点赞、转发、回复**不计入任何公开榜单和推荐权重** —— '
          + '推荐公式是公开可复算的,自己刷自己等于自己骗自己。'
          + '发帖走和真人一样的路:违禁词、先审后发、举报、下架一条都不绕。'
          + '总闸和模型配置在「平台开关」页。'
        }
      />
      <Space style={{ marginBottom: 12 }}>
        <Button type="primary" onClick={() => setAdding(true)}>建一个 AI 号</Button>
        <Button onClick={() => void load()} loading={loading}>刷新</Button>
      </Space>
      <Table<AiBot>
        rowKey="user_id"
        loading={loading}
        dataSource={rows}
        pagination={false}
        columns={[
          {
            title: '号', dataIndex: 'name',
            render: (_: unknown, r) => (
              <Space direction="vertical" size={0}>
                <span>{r.name} <Tag color="purple">AI</Tag></span>
                <span style={{ color: 'var(--sz-ink-muted)', fontSize: 12 }}>@{r.username}</span>
              </Space>
            ),
          },
          {
            title: '人设 / 话题',
            render: (_: unknown, r) => (
              <Space direction="vertical" size={0} style={{ maxWidth: 380 }}>
                <span style={{ fontSize: 12 }}>{r.persona}</span>
                <span style={{ color: 'var(--sz-ink-muted)', fontSize: 12 }}>
                  {r.topics || '(没填话题,发帖时按「身边的小事」)'}
                </span>
              </Space>
            ),
          },
          {
            title: '每天',
            render: (_: unknown, r) => (
              <span style={{ fontSize: 12 }}>
                发 {r.posts_per_day} 条 · 回 {r.replies_per_day} 条
                {r.posts_per_day === 0 && r.replies_per_day === 0 && '(都是 0 = 不说话)'}
              </span>
            ),
          },
          { title: '发过', dataIndex: 'posts' },
          {
            title: '在用', dataIndex: 'active',
            render: (v: boolean, r) => (
              <Switch
                checked={v}
                onChange={async (on) => {
                  try {
                    await patchAiBot(r.user_id, { active: on })
                    void load()
                  } catch (e) { fail(e) }
                }}
              />
            ),
          },
          {
            title: '',
            render: (_: unknown, r) => (
              <Space>
                <Button size="small" onClick={() => {
                  editForm.setFieldsValue(r)
                  setEditing(r)
                }}>改</Button>
                {/* 配好之后总要先看一眼它说出来是什么样 ——
                    等清扫轮到它可能要几个小时,而那时候发出去的已经是线上的帖子了 */}
                <Button size="small" onClick={() => void sayNow(r)}>让它现在说一句</Button>
              </Space>
            ),
          },
        ]}
      />

      <Modal title="建一个 AI 号" open={adding} onOk={() => void add()}
             onCancel={() => setAdding(false)} okText="建" width={560}>
        <Form form={form} layout="vertical" initialValues={{ posts_per_day: 2, replies_per_day: 5 }}>
          <Form.Item name="name" label="名字" rules={[{ required: true, max: 20 }]}>
            <Input placeholder="吃货小z" />
          </Form.Item>
          <Form.Item name="username" label="超级赞号"
                     extra="必须以 bot 结尾 —— 用户一眼看得出这是机器人"
                     rules={[{ required: true },
                             { pattern: /bot$/, message: '要以 bot 结尾' }]}>
            <Input placeholder="chihuobot" />
          </Form.Item>
          <Form.Item name="persona" label="人设(给模型看的)"
                     extra="别写「假装成人」—— 页面上已经标了是机器人"
                     rules={[{ required: true, max: 2000 }]}>
            <Input.TextArea rows={3} placeholder="你是一位爱做饭的成都上班族,说话简短、爱吐槽价格" />
          </Form.Item>
          <Form.Item name="topics" label="关心的话题" extra="逗号分隔;发帖时从里面随机挑一个当由头">
            <Input placeholder="做饭,外卖,夜宵" />
          </Form.Item>
          <Space size="large">
            <Form.Item name="posts_per_day" label="每天发几条">
              <InputNumber min={0} max={24} />
            </Form.Item>
            <Form.Item name="replies_per_day" label="每天回几条"
                       extra="回真人的帖 —— 这一项才是让社区显得有人的那部分">
              <InputNumber min={0} max={48} />
            </Form.Item>
          </Space>
        </Form>
      </Modal>

      <Modal title={`改 ${editing?.name ?? ''}`} open={!!editing} onOk={() => void saveEdit()}
             onCancel={() => setEditing(null)} okText="保存" width={560}>
        <Form form={editForm} layout="vertical">
          <Form.Item name="persona" label="人设" rules={[{ max: 2000 }]}>
            <Input.TextArea rows={3} />
          </Form.Item>
          <Form.Item name="topics" label="关心的话题">
            <Input />
          </Form.Item>
          <Space size="large">
            <Form.Item name="posts_per_day" label="每天发几条">
              <InputNumber min={0} max={24} />
            </Form.Item>
            <Form.Item name="replies_per_day" label="每天回几条">
              <InputNumber min={0} max={48} />
            </Form.Item>
          </Space>
        </Form>
      </Modal>
    </>
  )
}
