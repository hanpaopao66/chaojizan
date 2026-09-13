import {
  Alert, Button, Card, Checkbox, Descriptions, Form, Input, Popconfirm, Radio, Select, Space, Switch, Table, Tabs, Tag,
  Typography, Upload, message,
} from 'antd'
import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'

import { ApiError, AppCard, BotCommand, BotDev, api, time } from '../api'
import AppIcon from '../components/AppIcon'
import TokenModal from '../components/TokenModal'

function err(e: unknown) {
  message.error(e instanceof ApiError ? e.message : String(e))
}

/** 机器人详情(#355):资料、命令、菜单按钮、隐私模式、接收更新(webhook)、token 与删除 */
export default function BotDetailPage() {
  const { id = '' } = useParams()
  const nav = useNavigate()
  const [bot, setBot] = useState<BotDev | null>(null)

  const load = () => api.bot(Number(id)).then(setBot).catch((e) => {
    err(e)
    if (e instanceof ApiError && e.status === 404) nav('/bots', { replace: true })
  })
  useEffect(() => { load() }, [id])
  if (!bot) return <Card loading />

  return (
    <Card
      title={<Space><AppIcon icon={bot.avatar} name={bot.name} size={36} />{bot.name}
        <Typography.Text type="secondary">@{bot.username}</Typography.Text>
        <Tag>{bot.privacy_mode ? '隐私模式' : '读全部群消息'}</Tag></Space>}
      extra={<a onClick={() => nav('/bots')}>返回列表</a>}>
      <Tabs items={[
        { key: 'profile', label: '资料', children: <Profile bot={bot} onChanged={setBot} /> },
        { key: 'commands', label: '命令', children: <Commands bot={bot} onChanged={setBot} /> },
        { key: 'menu', label: '菜单按钮', children: <Menu bot={bot} onChanged={setBot} /> },
        { key: 'updates', label: '接收更新', children: <Updates bot={bot} onChanged={setBot} /> },
        { key: 'token', label: 'token 与删除', children: <TokenAndDelete bot={bot} onChanged={setBot} /> },
      ]} />
    </Card>
  )
}

type Props = { bot: BotDev; onChanged: (b: BotDev) => void }

// ---------------------------------------------------------------- 资料 + 隐私模式

function Profile({ bot, onChanged }: Props) {
  const [busy, setBusy] = useState(false)

  async function save(v: { name: string; about: string; description: string }) {
    setBusy(true)
    try {
      onChanged(await api.updateBot(bot.id, v))
      message.success('已保存')
    } catch (e) {
      err(e)
    } finally {
      setBusy(false)
    }
  }

  return (
    <Space direction="vertical" size={16} style={{ width: '100%', maxWidth: 720 }}>
      <Form layout="vertical" disabled={busy} onFinish={save}
        initialValues={{ name: bot.name, about: bot.about, description: bot.description }}>
        <Form.Item label="头像">
          <Space>
            <AppIcon icon={bot.avatar} name={bot.name} size={56} />
            <Upload accept="image/*" showUploadList={false} customRequest={async ({ file }) => {
              try {
                const r = await api.uploadImage(file as File, 'avatar')
                onChanged(await api.updateBot(bot.id, { avatar: r.url }))
                message.success('头像已更新(和用户头像一样会进图片审核)')
              } catch (e) { err(e) }
            }}><Button>上传头像</Button></Upload>
            {bot.avatar && <a onClick={() => api.updateBot(bot.id, { avatar: '' }).then(onChanged).catch(err)}>去掉</a>}
          </Space>
        </Form.Item>
        <Form.Item name="name" label="名字" rules={[{ required: true, max: 32 }]}><Input /></Form.Item>
        <Form.Item name="about" label="简介" extra="资料卡上的一句话(≤ 120 字)" rules={[{ max: 120 }]}>
          <Input />
        </Form.Item>
        <Form.Item name="description" label="描述" extra="用户第一次打开和它的私聊时,空会话中间显示的那段:它能做什么、怎么用(≤ 512 字)"
          rules={[{ max: 512 }]}>
          <Input.TextArea rows={4} maxLength={512} showCount />
        </Form.Item>
        <Button type="primary" htmlType="submit">保存</Button>
      </Form>
      <Card size="small" title="隐私模式">
        <Space align="start">
          <Switch checked={bot.privacy_mode}
            onChange={(v) => api.updateBot(bot.id, { privacy_mode: v }).then((b) => {
              onChanged(b)
              message.success(v ? '已开启隐私模式' : '已关闭隐私模式')
            }).catch(err)} />
          <Typography.Paragraph type="secondary" style={{ fontSize: 13, marginBottom: 0 }}>
            开着(缺省):群里只收到以 /命令 开头的、@它的、回复它的消息。关掉:收到群里所有消息 ——
            群成员在群资料里看得到这个状态。私聊不受影响,用户发给它的都能收到。
          </Typography.Paragraph>
        </Space>
      </Card>
      <Descriptions bordered size="small" column={1}>
        <Descriptions.Item label="用户找到它">{bot.link ? <Typography.Text copyable>{bot.link}</Typography.Text> : '—'}</Descriptions.Item>
        <Descriptions.Item label="创建时间">{time(bot.created_at)}</Descriptions.Item>
      </Descriptions>
    </Space>
  )
}

// ---------------------------------------------------------------- 命令

type Row = BotCommand & { key: number }
const COMMAND_RE = /^[a-z0-9_]{1,32}$/

function Commands({ bot, onChanged }: Props) {
  const [rows, setRows] = useState<Row[]>(() => bot.commands.map((c, i) => ({ ...c, key: i })))
  const [busy, setBusy] = useState(false)
  const set = (key: number, patch: Partial<BotCommand>) =>
    setRows(rows.map((r) => (r.key === key ? { ...r, ...patch } : r)))
  const bad = rows.filter((r) => !COMMAND_RE.test(r.command.replace(/^\//, '')) || !r.description.trim()
    || r.description.trim().length > 256)
  const dup = rows.length !== new Set(rows.map((r) => r.command.replace(/^\//, ''))).size

  async function save() {
    setBusy(true)
    try {
      const b = await api.setBotCommands(bot.id, rows.map((r) => ({
        command: r.command.replace(/^\//, ''), description: r.description.trim(),
      })))
      onChanged(b)
      setRows(b.commands.map((c, i) => ({ ...c, key: i })))
      message.success('已保存')
    } catch (e) {
      err(e)
    } finally {
      setBusy(false)
    }
  }

  return (
    <Space direction="vertical" size={12} style={{ width: '100%', maxWidth: 820 }}>
      <Typography.Paragraph type="secondary" style={{ fontSize: 13, marginBottom: 0 }}>
        用户在输入框打 / 时联想这些命令,菜单按钮选「命令列表」时也列它们。命令 1–32 位小写字母、数字、下划线,
        说明 1–256 字,最多 100 条。和 Bot API 的 setMyCommands 是同一份。
      </Typography.Paragraph>
      <Table<Row> rowKey="key" size="small" pagination={false} dataSource={rows} locale={{ emptyText: '还没有命令' }}
        columns={[
          {
            title: '命令', width: 240, render: (_, r) => (
              <Input addonBefore="/" value={r.command.replace(/^\//, '')} maxLength={32}
                status={COMMAND_RE.test(r.command.replace(/^\//, '')) ? undefined : 'error'}
                onChange={(e) => set(r.key, { command: e.target.value.trim().toLowerCase() })} />
            ),
          },
          {
            title: '说明', render: (_, r) => (
              <Input value={r.description} maxLength={256} status={r.description.trim() ? undefined : 'error'}
                onChange={(e) => set(r.key, { description: e.target.value })} />
            ),
          },
          { title: '', width: 60, render: (_, r) => <a onClick={() => setRows(rows.filter((x) => x.key !== r.key))}>删除</a> },
        ]} />
      <Space>
        <Button disabled={rows.length >= 100}
          onClick={() => setRows([...rows, { key: Date.now(), command: '', description: '' }])}>加一条</Button>
        <Button type="primary" loading={busy} disabled={bad.length > 0 || dup} onClick={save}>保存</Button>
        {dup && <Typography.Text type="danger">有重复的命令</Typography.Text>}
      </Space>
    </Space>
  )
}

// ---------------------------------------------------------------- 菜单按钮

function Menu({ bot, onChanged }: Props) {
  const cur = bot.menu_button
  const [type, setType] = useState<'default' | 'commands' | 'web_app'>(cur.type)
  const [text, setText] = useState(cur.type === 'web_app' ? cur.text : '')
  const [appId, setAppId] = useState(cur.type === 'web_app' ? cur.app_id : '')
  const [apps, setApps] = useState<AppCard[]>([])
  useEffect(() => {
    api.apps().then((r) => setApps(r.items.filter((a) => a.status === 'online'))).catch(err)
  }, [])

  async function save() {
    try {
      onChanged(await api.setBotMenu(bot.id, type === 'web_app' ? { type, text: text.trim(), app_id: appId } : { type }))
      message.success('已保存')
    } catch (e) {
      err(e)
    }
  }

  return (
    <Space direction="vertical" size={12} style={{ width: '100%', maxWidth: 720 }}>
      {cur.type === 'web_app' && !cur.available && (
        <Alert type="warning" showIcon message="菜单按钮指向的小程序现在不在线"
          description="用户那边暂时不显示这个按钮。小程序重新上架后自动恢复,或者换一个。" />
      )}
      <Typography.Paragraph type="secondary" style={{ fontSize: 13, marginBottom: 0 }}>
        输入栏左边的按钮。可以列出命令,或者直接打开你自己名下一个已上架的小程序(不能是任意网址)。
      </Typography.Paragraph>
      <Radio.Group value={type} onChange={(e) => setType(e.target.value)}>
        <Radio.Button value="default">没有</Radio.Button>
        <Radio.Button value="commands">命令列表</Radio.Button>
        <Radio.Button value="web_app">打开小程序</Radio.Button>
      </Radio.Group>
      {type === 'web_app' && (
        <Space direction="vertical" style={{ width: '100%' }}>
          <Input placeholder="按钮文字,如「点餐」(1–64 字)" maxLength={64} value={text} onChange={(e) => setText(e.target.value)} />
          <Select style={{ width: '100%' }} placeholder={apps.length ? '选一个已上架的小程序' : '你还没有已上架的小程序'}
            value={appId || undefined} onChange={setAppId}
            options={apps.map((a) => ({ value: a.appid, label: <Space><AppIcon icon={a.icon} name={a.name} size={20} />{a.name}</Space> }))} />
        </Space>
      )}
      <Button type="primary" onClick={save} disabled={type === 'web_app' && (!text.trim() || !appId)}>保存</Button>
    </Space>
  )
}

// ---------------------------------------------------------------- 接收更新

function Updates({ bot, onChanged }: Props) {
  const w = bot.webhook
  const [url, setUrl] = useState(w.url)
  const [secret, setSecret] = useState('')
  const [drop, setDrop] = useState(false)
  const [busy, setBusy] = useState(false)

  async function save() {
    setBusy(true)
    try {
      onChanged(await api.setBotWebhook(bot.id, { url: url.trim(), secret_token: secret.trim() || undefined, drop_pending_updates: drop }))
      setSecret('')
      message.success('webhook 已设置')
    } catch (e) {
      err(e)
    } finally {
      setBusy(false)
    }
  }

  return (
    <Space direction="vertical" size={16} style={{ width: '100%', maxWidth: 820 }}>
      <Descriptions bordered size="small" column={1}>
        <Descriptions.Item label="方式">
          {w.url ? <Tag color="success">webhook</Tag> : <Tag>getUpdates(长轮询)</Tag>}
        </Descriptions.Item>
        <Descriptions.Item label="webhook 地址">{w.url || '—'}{w.url && w.has_secret && <Tag style={{ marginLeft: 8 }}>带 secret_token</Tag>}</Descriptions.Item>
        <Descriptions.Item label="待送更新">{w.pending_update_count}</Descriptions.Item>
        <Descriptions.Item label="最近一次投递失败">
          {w.last_error_date ? <Typography.Text type="danger">{time(w.last_error_date)} · {w.last_error_message}</Typography.Text> : '—'}
        </Descriptions.Item>
      </Descriptions>
      <Typography.Paragraph type="secondary" style={{ fontSize: 13, marginBottom: 0 }}>
        两种收更新的方式二选一:不设 webhook 就用 getUpdates 长轮询;设了 webhook,平台把每条更新 POST 到你的地址
        (带 X-Superz-Bot-Api-Secret-Token 头),这时再调 getUpdates 会 409。地址要 https、公网、端口 80 / 88 / 443 / 8443。
        10 秒内回 2xx 算送到;失败按 1 / 2 / 4 / 8… 分钟重试,按顺序送,满 24 小时丢弃。
      </Typography.Paragraph>
      <Card size="small" title="设置 webhook">
        <Space direction="vertical" style={{ width: '100%' }}>
          <Input placeholder="https://bot.example.com/superz/webhook" value={url} onChange={(e) => setUrl(e.target.value)} />
          <Input.Password placeholder={w.has_secret ? 'secret_token(已设置;不填 = 去掉)' : 'secret_token(可选,1–256 位 A-Z a-z 0-9 _ -)'}
            value={secret} onChange={(e) => setSecret(e.target.value)} />
          <Checkbox checked={drop} onChange={(e) => setDrop(e.target.checked)}>丢掉还没送出去的更新</Checkbox>
          <Space>
            <Button type="primary" loading={busy} disabled={!url.trim()} onClick={save}>保存</Button>
            {w.url && (
              <Popconfirm title="删掉 webhook 之后改用 getUpdates 取更新。没送出去的更新保留。"
                onConfirm={() => api.deleteBotWebhook(bot.id, false).then((b) => { onChanged(b); setUrl(''); message.success('已删除') }).catch(err)}>
                <Button>删除 webhook</Button>
              </Popconfirm>
            )}
          </Space>
        </Space>
      </Card>
    </Space>
  )
}

// ---------------------------------------------------------------- token 与删除

function TokenAndDelete({ bot, onChanged }: Props) {
  const nav = useNavigate()
  const [token, setToken] = useState<string | null>(null)
  const [confirm, setConfirm] = useState('')

  return (
    <Space direction="vertical" size={16} style={{ width: '100%', maxWidth: 720 }}>
      <Descriptions bordered size="small" column={1}>
        <Descriptions.Item label="token">
          <Space direction="vertical">
            <span><Typography.Text code>{bot.token_prefix}…</Typography.Text>(平台只存哈希,这里只显示前 6 位)</span>
            <Popconfirm title="重置之后旧 token 当场失效,正在用它的服务会立刻 401。确定?"
              onConfirm={() => api.resetBotToken(bot.id).then((r) => { onChanged(r.bot); setToken(r.token) }).catch(err)}>
              <Button>重置 token</Button>
            </Popconfirm>
          </Space>
        </Descriptions.Item>
      </Descriptions>
      <Card size="small" title="删除机器人">
        <Typography.Paragraph type="secondary" style={{ fontSize: 13 }}>
          不可恢复:它发过的消息在所有会话里清空(和注销账号一样)、它上传的文件删掉、退出所有群、
          用户名 @{bot.username} 释放、token 当场失效。
        </Typography.Paragraph>
        <Popconfirm
          title={<Space direction="vertical">输入用户名确认删除:<Input size="small" placeholder={bot.username || ''} value={confirm} onChange={(e) => setConfirm(e.target.value)} /></Space>}
          okButtonProps={{ danger: true, disabled: confirm.trim().replace(/^@/, '').toLowerCase() !== (bot.username || '').toLowerCase() }}
          onConfirm={() => api.deleteBot(bot.id).then(() => { message.success('已删除'); nav('/bots', { replace: true }) }).catch(err)}>
          <Button danger>删除机器人</Button>
        </Popconfirm>
      </Card>
      <TokenModal token={token} title="新 token 只显示这一次" onDone={() => setToken(null)} />
    </Space>
  )
}
