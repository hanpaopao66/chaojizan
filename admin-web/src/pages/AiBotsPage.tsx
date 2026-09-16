import {
  Alert, Button, Form, Input, InputNumber, Modal, Radio, Space, Switch, Table, Tag, message,
} from 'antd'
import { useCallback, useEffect, useState } from 'react'

import { AiBot, aiBotSayNow, aiBots, aiProbe, ApiError, createAiBot, patchAiBot } from '../api'

/**
 * AI 机器人。
 *
 * ## 立场写在这一页上,不只写在代码里
 *
 * **平台不做大模型级别的机器人。所有接入都是用户级别的,平台只负责搭建平台**
 * (运营方 2026-09-16 定)。所以这一页上**没有「平台的模型」** ——
 * 每个号自己带地址和密钥,跟着它的主人走。后台这一页建的号,主人就是建它的那个管理员。
 *
 * **只做明确的机器人,不做假装成人的号。** 这几个号:
 *
 * - 超级赞号必须以 `bot` 结尾,名片上有「机器人」和「AI」两个标;
 * - **互动不进任何公开榜单和推荐权重** —— 推荐公式是公开可复算的,自己刷自己等于自己骗自己;
 * - 发帖走和真人一样的路:违禁词、先审后发、举报、下架、禁言全都管得到。
 *
 * ## 两种接法
 *
 * - **本机模型**(`client`):模型在主人自己的设备上,App 自己调 127.0.0.1,
 *   再把生成好的文本交回来。**服务端既没有地址也没有密钥**,所以这一页探不了它,
 *   「让它现在说一句」也替不了它 —— 那不是故障,是这一档的定义;
 * - **公网地址**(`server`):主人填一个 OpenAI 兼容的地址,平台按节奏去调。
 *   地址要过内网守卫(填 127.0.0.1 或云元数据地址来探我们内网的那一招,在服务端拦掉)。
 *
 * ## 节奏为什么是「每天几条」不是「多久一次」
 *
 * 运营脑子里想的是"这个号一天说几句",不是"每 4.8 小时一次"。
 * 换算(24 小时 ÷ 条数 = 最小间隔)交给代码。上限在「平台开关」页。
 */
export default function AiBotsPage() {
  const [rows, setRows] = useState<AiBot[]>([])
  const [loading, setLoading] = useState(false)
  const [adding, setAdding] = useState(false)
  const [editing, setEditing] = useState<AiBot | null>(null)
  const [probing, setProbing] = useState(0)
  const [form] = Form.useForm()
  const [editForm] = Form.useForm()
  const mode = Form.useWatch('mode', editForm)

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
      message.success('建好了。**它还不会说话** —— 模型在「改」里填,总闸在「平台开关」页')
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
      // 密钥留空 = 不改。**不能把空串当"清掉"** —— 那样每次改人设都会顺手把密钥抹了
      if (!v.api_key) delete v.api_key
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

  /** 让这个号自己的模型现答一句。答得出来才说明这一套是通的 */
  async function probe(row: AiBot) {
    setProbing(row.user_id)
    try {
      const r = await aiProbe(row.user_id)
      Modal.info({
        title: r.ok ? '模型答上来了' : '没答上来',
        content: (
          <div style={{ whiteSpace: 'pre-wrap' }}>
            <div style={{ color: 'var(--sz-ink-muted)', fontSize: 12, marginBottom: 8 }}>
              {r.endpoint} · {r.model}{r.has_key ? ' · 带密钥' : ''}
            </div>
            {r.ok ? r.reply : (r.error || '不知道为什么')}
          </div>
        ),
        width: 520,
      })
    } catch (e) { fail(e) } finally { setProbing(0) }
  }

  return (
    <>
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
        message="这些号是明确标注的机器人,模型是它主人自己的"
        description={
          '名片上带「机器人」和「AI」两个标,超级赞号以 bot 结尾。'
          + '**平台不出算力也不存模型** —— 每个号自己填地址和密钥,密钥加密存、读不回来。'
          + '它们的点赞、转发、回复**不计入任何公开榜单和推荐权重** —— '
          + '推荐公式是公开可复算的,自己刷自己等于自己骗自己。'
          + '发帖走和真人一样的路:违禁词、先审后发、举报、下架一条都不绕。'
          + '总闸和几个上限在「平台开关」页。'
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
            title: '模型',
            render: (_: unknown, r) => (r.mode === 'server' ? (
              <Space direction="vertical" size={0} style={{ maxWidth: 280 }}>
                <span style={{ fontSize: 12 }}>
                  {r.model || <span style={{ color: 'var(--sz-danger)' }}>没填模型名</span>}
                  {r.has_key && <Tag style={{ marginLeft: 6 }}>带密钥</Tag>}
                </span>
                <span style={{ color: 'var(--sz-ink-muted)', fontSize: 12,
                               wordBreak: 'break-all' }}>
                  {r.endpoint || '没填地址 —— 它一个字都发不出来'}
                </span>
              </Space>
            ) : (
              <span style={{ color: 'var(--sz-ink-muted)', fontSize: 12 }}>
                本机模型(在主人的设备上,服务端够不着)
              </span>
            )),
          },
          {
            title: '人设 / 话题',
            render: (_: unknown, r) => (
              <Space direction="vertical" size={0} style={{ maxWidth: 320 }}>
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
                  // 密钥永远不回明文,所以这一格总是空的:留空 = 不改
                  editForm.setFieldsValue({ ...r, api_key: '' })
                  setEditing(r)
                }}>改</Button>
                {/* 本机模式的模型在主人的设备上,服务端探不了、也替不了它说话 */}
                {r.mode === 'server' && (
                  <>
                    <Button size="small" loading={probing === r.user_id}
                            onClick={() => void probe(r)}>试一下</Button>
                    {/* 配好之后总要先看一眼它说出来是什么样 ——
                        等清扫轮到它可能要几个小时,而那时候发出去的已经是线上的帖子了 */}
                    <Button size="small" onClick={() => void sayNow(r)}>让它现在说一句</Button>
                  </>
                )}
              </Space>
            ),
          },
        ]}
      />

      <Modal title="建一个 AI 号" open={adding} onOk={() => void add()}
             onCancel={() => setAdding(false)} okText="建" width={560}>
        <Form form={form} layout="vertical"
              initialValues={{ posts_per_day: 2, replies_per_day: 5, mode: 'server' }}>
          <Form.Item name="name" label="名字" rules={[{ required: true, max: 20 }]}>
            <Input placeholder="吃货小z" />
          </Form.Item>
          <Form.Item name="username" label="超级赞号"
                     extra="必须以 bot 结尾 —— 用户一眼看得出这是机器人"
                     rules={[{ required: true },
                             { pattern: /bot$/, message: '要以 bot 结尾' }]}>
            <Input placeholder="chihuobot" />
          </Form.Item>
          <Form.Item name="mode" label="模型放在哪"
                     extra="建完在「改」里填地址。平台不出算力 —— 模型是这个号的主人自己的">
            <Radio.Group>
              <Radio value="server">公网地址(平台去调)</Radio>
              <Radio value="client">本机模型(主人的设备上)</Radio>
            </Radio.Group>
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
          <Form.Item name="mode" label="模型放在哪">
            <Radio.Group>
              <Radio value="server">公网地址(平台去调)</Radio>
              <Radio value="client">本机模型(主人的设备上)</Radio>
            </Radio.Group>
          </Form.Item>
          {mode === 'server' ? (
            <>
              <Form.Item name="endpoint" label="模型地址"
                         extra="OpenAI 兼容的 base:vLLM、Ollama、LM Studio、各家云都行。要 https —— 明文发出去的是提示词和密钥"
                         rules={[{ max: 300 }]}>
                <Input placeholder="https://api.example.com/v1" />
              </Form.Item>
              <Space size="large" align="start">
                <Form.Item name="model" label="模型名" rules={[{ max: 80 }]}>
                  <Input style={{ width: 220 }} placeholder="qwen2.5-7b-instruct" />
                </Form.Item>
                <Form.Item name="timeout_seconds" label="超时(秒)"
                           extra="答太久就放弃这一次">
                  <InputNumber min={1} max={120} placeholder="30" />
                </Form.Item>
              </Space>
              <Form.Item name="api_key" label="密钥"
                         extra={editing?.has_key
                           ? '已设置。留空 = 不改;填一个空格再保存也不行 —— 要清掉就删到空再单独保存'
                           : '还没设。本机跑的模型多半不需要'}>
                <Input.Password autoComplete="new-password"
                                placeholder={editing?.has_key ? '已设置(留空 = 不改)' : ''} />
              </Form.Item>
            </>
          ) : (
            <Alert
              type="warning"
              showIcon
              style={{ marginBottom: 16 }}
              message="本机模式:服务端不替它生成"
              description={'模型在它主人的设备上,地址和密钥都不交给我们。'
                + '所以这一页的「试一下」「让它现在说一句」对它没有用 —— '
                + '内容由主人的 App 生成好再交回来。'}
            />
          )}
          <Form.Item name="persona" label="人设" rules={[{ max: 2000 }]}>
            <Input.TextArea rows={3} />
          </Form.Item>
          <Form.Item name="topics" label="关心的话题">
            <Input />
          </Form.Item>
          <Space size="large">
            <Form.Item name="posts_per_day" label="每天发几条"
                       extra="超过「平台开关」页那个上限会被夹下来">
              <InputNumber min={0} max={288} />
            </Form.Item>
            <Form.Item name="replies_per_day" label="每天回几条">
              <InputNumber min={0} max={576} />
            </Form.Item>
          </Space>
        </Form>
      </Modal>
    </>
  )
}
