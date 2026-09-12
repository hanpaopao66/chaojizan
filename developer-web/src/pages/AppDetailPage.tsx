import { InboxOutlined } from '@ant-design/icons'
import {
  Alert, Button, Card, Descriptions, Empty, Form, Input, List, Modal, Popconfirm, Progress, QRCode, Select, Space,
  Switch, Table, Tabs, Tag, Typography, Upload, message,
} from 'antd'
import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'

import { ApiError, AppDetail, CATEGORIES, Decision, Me, PackageReport, Version, api, bytes, time } from '../api'
import AppIcon from '../components/AppIcon'
import Simulator from '../components/Simulator'

const CAP_LABEL: Record<string, string> = {
  initData: '身份(initData)', storage: '云存储', share: '系统分享', haptics: '触感', popup: '弹窗', openLink: '打开外链',
  fullscreen: '全屏(小游戏)', orientation: '锁方向(小游戏)', profile: '昵称和头像(需申请)',
}

function err(e: unknown) {
  message.error(e instanceof ApiError ? e.message : String(e))
}

export default function AppDetailPage({ me }: { me: Me | null }) {
  const { appid = '' } = useParams()
  const nav = useNavigate()
  const [app, setApp] = useState<AppDetail | null>(null)
  const [versions, setVersions] = useState<Version[]>([])
  const [tab, setTab] = useState('overview')

  const load = async () => {
    try {
      const [a, v] = await Promise.all([api.app(appid), api.versions(appid)])
      setApp(a)
      setVersions(v.items)
    } catch (e) {
      err(e)
    }
  }
  useEffect(() => { load() }, [appid])
  if (!app) return <Card loading />

  return (
    <Card
      title={<Space><AppIcon icon={app.icon} name={app.name} size={36} />{app.name}
        <Tag>{app.status_label}</Tag>{app.kind === 'game' && <Tag>小游戏</Tag>}</Space>}
      extra={<Space>
        <Typography.Text type="secondary" copyable={{ text: app.appid }} style={{ fontFamily: 'monospace' }}>{app.appid}</Typography.Text>
        <a onClick={() => nav('/apps')}>返回列表</a>
      </Space>}>
      <Tabs activeKey={tab} onChange={setTab} items={[
        { key: 'overview', label: '概览', children: <Overview app={app} reload={load} /> },
        { key: 'versions', label: '版本', children: <Versions app={app} me={me} versions={versions} reload={load} onSimulate={() => setTab('sim')} /> },
        { key: 'sim', label: '模拟器', children: <Simulator appid={app.appid} versions={versions} kind={app.kind} /> },
        { key: 'listing', label: '展示信息', children: <ListingForm app={app} reload={load} /> },
        { key: 'settings', label: '开发设置', children: <DevSettings app={app} reload={load} /> },
        { key: 'caps', label: '能力', children: <Capabilities app={app} reload={load} /> },
        { key: 'testers', label: '体验者', children: <Testers app={app} /> },
        { key: 'stats', label: '数据', children: <Stats appid={app.appid} /> },
        { key: 'reports', label: '用户反馈', children: <Reports appid={app.appid} /> },
        { key: 'decisions', label: '审核记录', children: <Decisions appid={app.appid} /> },
      ]} />
    </Card>
  )
}

// ---------------------------------------------------------------- 概览

function Overview({ app, reload }: { app: AppDetail; reload: () => void }) {
  const [confirm, setConfirm] = useState('')
  const v = (x: Version | null) => (x ? `${x.version}(build ${x.build})` : '—')
  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      {app.status === 'suspended' && <Alert type="error" showIcon message="应用被平台暂停" description="原因写在「审核记录」里,可以在 7 天内申诉一次;整改后提交新版本,复审通过由平台恢复。" />}
      <Descriptions bordered size="small" column={{ xs: 1, md: 2 }}>
        <Descriptions.Item label="当前版本">{v(app.current_version)}</Descriptions.Item>
        <Descriptions.Item label="审核中">{v(app.reviewing_version)}</Descriptions.Item>
        <Descriptions.Item label="体验版">{v(app.trial_version)}</Descriptions.Item>
        <Descriptions.Item label="首次上架">{time(app.first_released_at)}</Descriptions.Item>
        <Descriptions.Item label="公开页"><a href={`/m/${app.appid}`} target="_blank" rel="noreferrer">/m/{app.appid}</a></Descriptions.Item>
        <Descriptions.Item label="托管地址">{app.hosted_origin || '—'}</Descriptions.Item>
      </Descriptions>
      {app.trial_version && (
        <Card size="small" title="体验版二维码">
          <Space align="start">
            <QRCode value={app.trial_link} size={132} />
            <Typography.Paragraph type="secondary" style={{ maxWidth: 420 }}>
              用手机上的超级赞扫码(先在「体验者」里加上自己的手机号并用它登录用户端)。
              安卓真机调试:用户端「我的 → 设置 → 小程序授权与数据 → 开发者选项」打开「小程序调试」,
              电脑 Chrome 打开 chrome://inspect 就能看到页面。
            </Typography.Paragraph>
          </Space>
        </Card>
      )}
      <Space wrap>
        {app.status === 'online' && <Popconfirm title="下架后用户在目录和最近使用里就看不到了,确定?" onConfirm={() => api.offline(app.appid).then(reload).catch(err)}>
          <Button>下架</Button></Popconfirm>}
        {app.status === 'offline' && <Button onClick={() => api.online(app.appid).then(reload).catch(err)}>重新上架</Button>}
        {app.status !== 'removed' && (
          <Popconfirm
            title={<Space direction="vertical">永久移除(不可恢复),输入应用名称确认:<Input size="small" value={confirm} onChange={(e) => setConfirm(e.target.value)} /></Space>}
            onConfirm={() => api.remove(app.appid, confirm).then(() => { message.success('已移除'); reload() }).catch(err)}>
            <Button danger>移除应用</Button>
          </Popconfirm>
        )}
      </Space>
    </Space>
  )
}

// ---------------------------------------------------------------- 版本

function Versions({ app, me, versions, reload, onSimulate }: {
  app: AppDetail; me: Me | null; versions: Version[]; reload: () => void; onSimulate: () => void
}) {
  const [pct, setPct] = useState<number | null>(null)
  const [report, setReport] = useState<PackageReport | null>(null)
  const [version, setVersion] = useState('')
  const [changelog, setChangelog] = useState('')
  const [submitFor, setSubmitFor] = useState<Version | null>(null)
  const [note, setNote] = useState('')

  async function doUpload(file: File) {
    setReport(null)
    setPct(0)
    try {
      const r = await api.uploadVersion(app.appid, file, version, changelog, setPct)
      setReport(r.report)
      message.success(`已上传 ${r.version.version}`)
      reload()
    } catch (e) {
      const d = e instanceof ApiError ? (e.detail as { report?: PackageReport }) : undefined
      if (d?.report) setReport(d.report)
      err(e)
    } finally {
      setPct(null)
    }
  }

  const act = (p: Promise<unknown>, ok: string) => p.then(() => { message.success(ok); reload() }).catch(err)
  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      <Card size="small" title="上传开发版">
        <Space wrap style={{ marginBottom: 8 }}>
          <Input placeholder="版本号,如 1.0.0" value={version} onChange={(e) => setVersion(e.target.value)} style={{ width: 180 }} />
          <Input placeholder="更新说明(给用户看)" value={changelog} onChange={(e) => setChangelog(e.target.value)} style={{ width: 360 }} />
        </Space>
        <Upload.Dragger accept=".zip" showUploadList={false} disabled={pct !== null}
          customRequest={({ file }) => { doUpload(file as File) }}>
          <p className="ant-upload-drag-icon"><InboxOutlined /></p>
          <p>把 zip 拖到这里,或点击选择</p>
          <p style={{ color: 'var(--sz-ink-muted)', fontSize: 12 }}>
            根目录要有 index.html 和 superz.json;应用 ≤ 10 MB、小游戏 ≤ 30 MB,单文件 ≤ 5 MB,最多 1000 个文件。
          </p>
        </Upload.Dragger>
        {pct !== null && <Progress percent={pct} size="small" />}
        {report && (
          <Alert style={{ marginTop: 12 }} type={report.ok ? (report.warnings.length ? 'warning' : 'success') : 'error'} showIcon
            message={report.ok ? `校验通过 · ${bytes(report.size)} · ${report.file_count} 个文件` : '包没有通过校验'}
            description={<>
              {report.errors.map((x, i) => <div key={`e${i}`}>✗ {x}</div>)}
              {report.warnings.map((x, i) => <div key={`w${i}`}>⚠ {x}</div>)}
              {report.sha256 && <div style={{ fontFamily: 'monospace', fontSize: 12 }}>SHA-256 {report.sha256}</div>}
            </>} />
        )}
      </Card>
      <Space>
        <span>审核通过后自动发布</span>
        <Switch checked={app.auto_release} onChange={(v) => act(api.autoRelease(app.appid, v), v ? '已开启' : '已关闭')} />
      </Space>
      <Table<Version>
        rowKey="id" size="small" dataSource={versions} pagination={{ pageSize: 10 }}
        columns={[
          { title: 'build', dataIndex: 'build', width: 64 },
          { title: '版本', render: (_, v) => <Space>{v.version}{v.is_current && <Tag color="success">当前</Tag>}{v.is_trial && <Tag color="processing">体验版</Tag>}</Space> },
          { title: '状态', render: (_, v) => <Space direction="vertical" size={0}>
            <Tag color={v.quarantined ? 'error' : undefined}>{v.quarantined ? '已隔离' : v.status_label}</Tag>
            {v.status === 'rejected' && <Typography.Text type="danger" style={{ fontSize: 12 }}>{v.reject_code} {v.reject_label}:{v.reject_note}</Typography.Text>}
          </Space> },
          { title: '大小', render: (_, v) => bytes(v.size), width: 90 },
          { title: 'SHA-256', render: (_, v) => <Typography.Text copyable={{ text: v.sha256 }} style={{ fontFamily: 'monospace', fontSize: 12 }}>{v.sha256.slice(0, 12)}…</Typography.Text> },
          { title: '上传时间', render: (_, v) => time(v.created_at), width: 140 },
          {
            title: '操作', render: (_, v) => (
              <Space wrap size={4}>
                {!v.quarantined && v.status !== 'rejected' && <a onClick={onSimulate}>模拟器</a>}
                {['uploaded', 'withdrawn'].includes(v.status) && !v.is_trial && <a onClick={() => act(api.setTrial(app.appid, v.id), '已设为体验版')}>设为体验版</a>}
                {['uploaded', 'trial', 'withdrawn'].includes(v.status) && (
                  <a onClick={() => { if (!me?.can_submit) { message.warning('认证通过、接受开发者规则之后才能提交审核'); return } setSubmitFor(v); setNote('') }}>提交审核</a>)}
                {v.status === 'reviewing' && <Popconfirm title="撤回审核?" onConfirm={() => act(api.withdraw(app.appid, v.id), '已撤回')}><a>撤回</a></Popconfirm>}
                {v.status === 'approved' && <Popconfirm title="发布后所有用户下次打开就是这个版本,确定?" onConfirm={() => act(api.release(app.appid, v.id), '已发布')}><a>发布</a></Popconfirm>}
                {v.status === 'superseded' && !v.quarantined && <Popconfirm title={`回滚到 ${v.version}?`} onConfirm={() => act(api.rollback(app.appid, v.id), '已回滚')}><a>回滚到这个版本</a></Popconfirm>}
              </Space>
            ),
          },
        ]}
      />
      <Modal title={`提交审核:${submitFor?.version}`} open={!!submitFor} onCancel={() => setSubmitFor(null)}
        onOk={() => { const v = submitFor!; setSubmitFor(null); act(api.submit(app.appid, v.id, note), '已提交审核') }}>
        <Typography.Paragraph type="secondary">写给审核员:怎么测、需要什么测试账号、哪些功能要连你的后端。
          上架后改过的名称、图标、描述、隐私政策,会随这个版本一起送审。</Typography.Paragraph>
        <Input.TextArea rows={4} maxLength={1000} value={note} onChange={(e) => setNote(e.target.value)} />
      </Modal>
    </Space>
  )
}

// ---------------------------------------------------------------- 展示信息

function ListingForm({ app, reload }: { app: AppDetail; reload: () => void }) {
  const base = app.listing_draft || app
  const [shots, setShots] = useState<string[]>(base.screenshots || [])
  const [decl, setDecl] = useState(base.data_declaration || [])
  const [busy, setBusy] = useState(false)
  const released = !!app.first_released_at

  async function save(v: { name: string; icon: string; tagline: string; description: string; category: string; privacy_policy: string }) {
    setBusy(true)
    try {
      await api.updateApp(app.appid, { ...v, screenshots: shots, data_declaration: decl.filter((d) => d.field && d.purpose) })
      message.success(released ? '已保存,随下一个版本送审' : '已保存')
      reload()
    } catch (e) {
      err(e)
    } finally {
      setBusy(false)
    }
  }

  return (
    <Form layout="vertical" disabled={busy} onFinish={save} style={{ maxWidth: 720 }}
      initialValues={{ name: base.name, icon: base.icon, tagline: base.tagline, description: base.description, category: base.category, privacy_policy: base.privacy_policy }}>
      {released && <Alert type="info" showIcon style={{ marginBottom: 16 }}
        message={app.listing_draft ? '有待生效的改动' : '上架后的改动随下一个版本送审'}
        description="名称、图标、描述、隐私政策改了不会当场生效 —— 否则过审的应用可以当场改名成别的东西。提交下一个版本时它们一起过审,发布时生效。" />}
      <Form.Item name="name" label="名称" rules={[{ required: true, min: 2, max: 20 }]}><Input /></Form.Item>
      <Form.Item name="icon" label="图标" extra="写一个汉字(画成衬线字块),或者上传一张方形图片">
        <Input addonAfter={<Upload accept="image/*" showUploadList={false} customRequest={async ({ file }) => {
          try {
            const r = await api.uploadImage(file as File, 'miniapp_icon')
            await api.updateApp(app.appid, { icon: r.url })
            message.success('图标已上传')
            reload()
          } catch (e) { err(e) }
        }}><a>上传</a></Upload>} />
      </Form.Item>
      <Form.Item name="tagline" label="一句话介绍" rules={[{ required: true, max: 30 }]}><Input /></Form.Item>
      <Form.Item name="category" label="分类"><Select options={Object.entries(CATEGORIES).map(([value, label]) => ({ value, label }))} /></Form.Item>
      <Form.Item name="description" label="描述" rules={[{ required: true, min: 10 }]}><Input.TextArea rows={4} maxLength={2000} showCount /></Form.Item>
      <Form.Item label="截图(最多 6 张)">
        <Space wrap>
          {shots.map((s) => <div key={s} style={{ position: 'relative' }}>
            <img src={s} alt="" style={{ width: 72, height: 128, objectFit: 'cover', borderRadius: 8, border: '1px solid var(--sz-line)' }} />
            <a style={{ position: 'absolute', top: 2, right: 6 }} onClick={() => setShots(shots.filter((x) => x !== s))}>✕</a>
          </div>)}
          {shots.length < 6 && <Upload accept="image/*" showUploadList={false} customRequest={async ({ file }) => {
            try { setShots([...shots, (await api.uploadImage(file as File, 'miniapp_shot')).url]) } catch (e) { err(e) }
          }}><Button>添加截图</Button></Upload>}
        </Space>
      </Form.Item>
      <Form.Item name="privacy_policy" label="隐私政策" rules={[{ required: true, min: 20 }]}
        extra="写清楚收集什么、存在哪、给谁看、怎么删。一个都不收集也要写明。">
        <Input.TextArea rows={6} maxLength={8000} showCount />
      </Form.Item>
      <Form.Item label="数据声明(收集什么、为什么)" extra="审核按这张表核对「超范围收集」(R302)。不收集就留空。">
        <Space direction="vertical" style={{ width: '100%' }}>
          {decl.map((d, i) => (
            <Space key={i}>
              <Input placeholder="收集什么" value={d.field} onChange={(e) => setDecl(decl.map((x, j) => (j === i ? { ...x, field: e.target.value } : x)))} />
              <Input placeholder="为什么" style={{ width: 320 }} value={d.purpose} onChange={(e) => setDecl(decl.map((x, j) => (j === i ? { ...x, purpose: e.target.value } : x)))} />
              <a onClick={() => setDecl(decl.filter((_, j) => j !== i))}>删除</a>
            </Space>
          ))}
          <Button size="small" onClick={() => setDecl([...decl, { field: '', purpose: '' }])}>加一项</Button>
        </Space>
      </Form.Item>
      <Button type="primary" htmlType="submit">保存</Button>
    </Form>
  )
}

// ---------------------------------------------------------------- 开发设置

function DevSettings({ app, reload }: { app: AppDetail; reload: () => void }) {
  const [pending, setPending] = useState<string | null>(null)
  const [domains, setDomains] = useState<string[]>(app.request_domains)
  return (
    <Space direction="vertical" size={16} style={{ width: '100%', maxWidth: 820 }}>
      <Descriptions bordered size="small" column={1}>
        <Descriptions.Item label="AppID"><Typography.Text copyable style={{ fontFamily: 'monospace' }}>{app.appid}</Typography.Text></Descriptions.Item>
        <Descriptions.Item label="AppSecret">
          <Space direction="vertical">
            <span>只在创建和轮换时显示一次。上次轮换:{time(app.secret.rotated_at)}</span>
            {app.secret.pending ? (
              <Space>
                <Tag color="warning">有一把待生效的新密钥</Tag>
                <Popconfirm title="切换后平台用新密钥签 initData,旧密钥验不过了。你的后端部署好新密钥了吗?"
                  onConfirm={() => api.activateSecret(app.appid).then(() => { message.success('已切换'); reload() }).catch(err)}>
                  <Button type="primary" size="small">切换到新密钥</Button>
                </Popconfirm>
                <Button size="small" onClick={() => api.cancelSecret(app.appid).then(reload).catch(err)}>作废新密钥</Button>
              </Space>
            ) : (
              <Button size="small" onClick={() => api.rotateSecret(app.appid).then((r) => { setPending(r.app_secret_pending); reload() }).catch(err)}>
                生成新密钥(两步轮换)
              </Button>
            )}
          </Space>
        </Descriptions.Item>
        <Descriptions.Item label="验签">
          持 AppSecret 验 hash,或拿平台公钥验 signature(<a href="/.well-known/superz-webapp-keys.json" target="_blank" rel="noreferrer">公钥</a>);
          示例代码和测试向量见 <a href="/developers/server" target="_blank" rel="noreferrer">文档 · 服务端</a>。
        </Descriptions.Item>
      </Descriptions>
      <Card size="small" title="服务器域名" extra={<span style={{ color: 'var(--sz-ink-muted)' }}>本月已改 {app.domain_changes.used} / {app.domain_changes.limit} 次</span>}>
        <Typography.Paragraph type="secondary" style={{ fontSize: 13 }}>
          页面只能连这里声明过的服务器(托管页 CSP 的 connect-src / img-src / media-src)。只收 https 的 origin(协议 + 域名,不带路径),
          不收 IP 和 localhost。改完只对新启动生效。
        </Typography.Paragraph>
        <Select mode="tags" style={{ width: '100%' }} value={domains} onChange={setDomains} placeholder="https://api.example.com" tokenSeparators={[',', ' ']} />
        <Button style={{ marginTop: 8 }} onClick={() => api.setDomains(app.appid, domains).then(() => { message.success('已保存'); reload() }).catch(err)}>保存</Button>
      </Card>
      <Modal open={!!pending} title="新密钥只显示这一次" closable={false} maskClosable={false}
        footer={<Button type="primary" onClick={() => setPending(null)}>我已保存</Button>}>
        <Alert type="warning" showIcon style={{ marginBottom: 12 }} message="先把它部署到你的服务端(新旧两把都能验),再回来点「切换到新密钥」。切换前平台照旧用旧密钥签。" />
        <Typography.Text code copyable>{pending}</Typography.Text>
      </Modal>
    </Space>
  )
}

// ---------------------------------------------------------------- 能力

function Capabilities({ app, reload }: { app: AppDetail; reload: () => void }) {
  const [why, setWhy] = useState('')
  const req = app.capability_requests.find((c) => c.capability === 'profile')
  return (
    <Space direction="vertical" size={16} style={{ width: '100%', maxWidth: 760 }}>
      <Card size="small" title="已有的能力">
        <Space wrap>{app.capabilities.map((c) => <Tag key={c}>{CAP_LABEL[c] || c}</Tag>)}</Space>
      </Card>
      <Card size="small" title="昵称和头像(profile)">
        {req && <Alert style={{ marginBottom: 8 }} type={req.status === 'approved' ? 'success' : req.status === 'rejected' ? 'error' : 'info'}
          message={`${req.status_label}${req.note ? `:${req.note}` : ''}`} />}
        <Typography.Paragraph type="secondary" style={{ fontSize: 13 }}>
          用户第一次调用 requestProfile() 时宿主会弹确认,同意后当场签一份带昵称头像的新 initData;用户可以在设置里撤回。
          定位、扫码、剪贴板、手机号这几项暂未开放申请。
        </Typography.Paragraph>
        {req?.status !== 'approved' && req?.status !== 'requested' && (
          <Space.Compact style={{ width: '100%' }}>
            <Input placeholder="为什么需要(至少 10 个字),审核员会看" value={why} onChange={(e) => setWhy(e.target.value)} />
            <Button onClick={() => api.requestCapability(app.appid, 'profile', why).then(() => { message.success('已提交申请'); reload() }).catch(err)}
              disabled={why.trim().length < 10}>申请</Button>
          </Space.Compact>
        )}
      </Card>
    </Space>
  )
}

// ---------------------------------------------------------------- 体验者

function Testers({ app }: { app: AppDetail }) {
  const [rows, setRows] = useState<Array<{ id: number; phone_tail: string; added_at: string }>>([])
  const [phone, setPhone] = useState('')
  const load = () => api.testers(app.appid).then((r) => setRows(r.items)).catch(err)
  useEffect(() => { load() }, [])
  return (
    <Space direction="vertical" size={12} style={{ width: '100%', maxWidth: 640 }}>
      <Typography.Paragraph type="secondary" style={{ fontSize: 13 }}>
        按手机号加(最多 {app.max_testers} 人)。对方用这个手机号登录超级赞用户端,扫「概览」里的体验版二维码就能打开。
        平台只存手机号的假名,这里只显示尾号。
      </Typography.Paragraph>
      <Space.Compact>
        <Input placeholder="手机号" value={phone} onChange={(e) => setPhone(e.target.value)} />
        <Button onClick={() => api.addTester(app.appid, phone.trim()).then(() => { setPhone(''); load() }).catch(err)}>添加</Button>
      </Space.Compact>
      <List bordered dataSource={rows} locale={{ emptyText: '还没有体验者' }} renderItem={(t) => (
        <List.Item actions={[<a key="d" onClick={() => api.removeTester(app.appid, t.id).then(load).catch(err)}>移除</a>]}>
          尾号 {t.phone_tail} · {time(t.added_at)}
        </List.Item>)} />
    </Space>
  )
}

// ---------------------------------------------------------------- 数据 / 反馈 / 审核记录

function Stats({ appid }: { appid: string }) {
  const [data, setData] = useState<{ items: Array<{ day: string; opens: number; users: number | string }>; csp_blocked: Record<string, number> } | null>(null)
  useEffect(() => { api.stats(appid).then(setData).catch(err) }, [appid])
  if (!data) return <Card loading />
  if (!data.items.length) return <Empty description="还没有人打开过(模拟器和体验版不计)" />
  return (
    <Space direction="vertical" style={{ width: '100%' }}>
      <Typography.Paragraph type="secondary" style={{ fontSize: 13 }}>用户数少于 10 的那天只显示「&lt; 10」,防止反推到具体的人。</Typography.Paragraph>
      <Table size="small" rowKey="day" pagination={false} dataSource={data.items}
        columns={[
          { title: '日期', dataIndex: 'day' }, { title: '打开次数', dataIndex: 'opens' }, { title: '用户数', dataIndex: 'users' },
          { title: 'CSP 拦截', render: (_, r) => data.csp_blocked[r.day] || 0 },
        ]} />
    </Space>
  )
}

function Reports({ appid }: { appid: string }) {
  const [rows, setRows] = useState<Array<{ id: number; reason_code: string; reason_label: string; status: string; resolution: string; created_at: string }>>([])
  useEffect(() => { api.reports(appid).then((r) => setRows(r.items)).catch(err) }, [appid])
  return (
    <Space direction="vertical" style={{ width: '100%' }}>
      <Typography.Paragraph type="secondary" style={{ fontSize: 13 }}>用户投诉的原因和处理结果。投诉人是谁、说明原文和截图只给审核员,不给开发者。</Typography.Paragraph>
      <Table size="small" rowKey="id" dataSource={rows} locale={{ emptyText: '没有投诉' }}
        columns={[
          { title: '时间', render: (_, r) => time(r.created_at) },
          { title: '原因', render: (_, r) => `${r.reason_code} ${r.reason_label}` },
          { title: '状态', dataIndex: 'status' },
          { title: '处理结果', dataIndex: 'resolution' },
        ]} />
    </Space>
  )
}

function Decisions({ appid }: { appid: string }) {
  const [rows, setRows] = useState<Decision[]>([])
  const [appealFor, setAppealFor] = useState<Decision | null>(null)
  const [text, setText] = useState('')
  const load = () => api.decisions(appid).then((r) => setRows(r.items)).catch(err)
  useEffect(() => { load() }, [appid])
  return (
    <>
      <List dataSource={rows} locale={{ emptyText: '还没有记录' }} renderItem={(d) => (
        <List.Item actions={d.appealable ? [<a key="a" onClick={() => { setAppealFor(d); setText('') }}>申诉</a>] : []}>
          <List.Item.Meta
            title={<Space>{d.action_label}{d.reason_code && <Tag color="error">{d.reason_code} {d.reason_label}</Tag>}</Space>}
            description={<>{time(d.created_at)}{d.note_public && <> · {d.note_public}</>}</>} />
        </List.Item>)} />
      <Modal title="申诉" open={!!appealFor} onCancel={() => setAppealFor(null)}
        onOk={() => { const d = appealFor!; setAppealFor(null); api.appeal(d.id, text).then(() => { message.success('已提交,会由另一名审核员处理'); load() }).catch(err) }}>
        <Typography.Paragraph type="secondary">每个结论只能申诉一次(7 天内),系统强制换一名审核员复核。写清楚理由和证据。</Typography.Paragraph>
        <Input.TextArea rows={5} maxLength={500} showCount value={text} onChange={(e) => setText(e.target.value)} />
      </Modal>
    </>
  )
}
