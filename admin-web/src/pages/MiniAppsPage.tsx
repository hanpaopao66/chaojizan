import {
  Alert, Button, Card, Checkbox, Descriptions, Drawer, Empty, Input, InputNumber, List, Modal, Radio, Select, Space,
  Switch, Table, Tabs, Tag, Typography, message,
} from 'antd'
import { useCallback, useEffect, useState } from 'react'

import { ApiError, get, post, request } from '../api'

/**
 * 小程序审核与治理(DEV-PROMPTS-39 #332)。
 *
 * 几条硬规矩在**服务端**钉死,这里只是把它们说清楚:
 * - 驳回、处罚必须选 §5.9 的原因代码,并写给开发者看的说明;内部备注永不公开;
 * - 通过要把审核清单逐项勾完(清单有版本号,记进审核记录);
 * - 申诉**强制换人**:原结论是你作出的,这里的按钮是灰的,接口也会拒;
 * - 处罚、精选的每一次变动都进透明中心(不含内部备注)。
 */

const REASONS: Record<string, string> = {
  R101: '打不开或核心功能不可用', R102: '与名称、描述、截图不符', R103: '空壳、测试页、半成品',
  R201: '违法违规内容', R202: '色情低俗', R203: '赌博、彩票、博彩', R204: '诱导分享、诱导关注、诱导下载',
  R205: '虚假宣传、夸大功效', R206: '侵害未成年人权益', R207: '引导站外交易、绕开平台规则',
  R301: '隐私政策缺失或与实际不符', R302: '超出声明范围收集信息', R303: '未经同意获取敏感信息',
  R401: '缺少类目要求的资质', R402: '游戏缺少版号、含内购或广告', R501: '仿冒平台界面、钓鱼',
  R502: '恶意代码、挖矿、刷量', R503: '请求了未声明的服务器域名', R601: '商标、著作权侵权', R701: '其他',
}
const reasonOptions = Object.entries(REASONS).map(([value, label]) => ({ value, label: `${value} ${label}` }))

const fail = (e: unknown) => message.error(e instanceof ApiError ? e.message : String(e))
const put = <T,>(p: string, b: unknown) => request<T>('PUT', p, b)
const del = <T,>(p: string) => request<T>('DELETE', p)
const t = (s?: string | null) => (s ? s.replace('T', ' ').slice(0, 16) : '—')

export default function MiniAppsPage() {
  const [overview, setOverview] = useState<Record<string, any> | null>(null)
  const reload = useCallback(() => { get<Record<string, any>>('/admin/mini-apps/overview').then(setOverview).catch(fail) }, [])
  useEffect(() => { reload() }, [reload])
  return (
    <Card title="小程序治理" extra={overview && <Space>
      <Tag color="processing">待审版本 {overview.reviewing}</Tag>
      <Tag>待认证 {overview.developer_pending}</Tag>
      <Tag>待批能力 {overview.capabilities_pending}</Tag>
      <Tag color={overview.reports_open ? 'warning' : undefined}>未处理投诉 {overview.reports_open}</Tag>
      <Tag color={overview.appeals_open ? 'error' : undefined}>待处理申诉 {overview.appeals_open}</Tag>
    </Space>}>
      <Tabs onChange={reload} items={[
        { key: 'review', label: '版本审核', children: <ReviewQueue onChanged={reload} /> },
        { key: 'devs', label: '开发者认证', children: <Developers onChanged={reload} /> },
        { key: 'caps', label: '能力审批', children: <CapabilityQueue onChanged={reload} /> },
        { key: 'reports', label: '投诉', children: <Reports onChanged={reload} /> },
        { key: 'appeals', label: '申诉', children: <Appeals onChanged={reload} /> },
        { key: 'apps', label: '应用与处罚', children: <Apps /> },
        { key: 'curation', label: '精选', children: <Curation /> },
        { key: 'signup', label: '开发者注册', children: <Signup /> },
        { key: 'stats', label: '统计', children: <Stats /> },
      ]} />
    </Card>
  )
}

// ---------------------------------------------------------------- 版本审核

function ReviewQueue({ onChanged }: { onChanged: () => void }) {
  const [rows, setRows] = useState<any[]>([])
  const [open, setOpen] = useState<number | null>(null)
  const load = () => get<{ items: any[] }>('/admin/mini-apps/reviews').then((r) => setRows(r.items)).catch(fail)
  useEffect(() => { load() }, [])
  return (
    <>
      <Table rowKey={(r) => r.version.id} size="small" dataSource={rows} locale={{ emptyText: '没有待审的版本' }}
        columns={[
          { title: '应用', render: (_, r) => <Space>{r.app.name}{r.app.kind === 'game' && <Tag>小游戏</Tag>}{r.app.is_official && <Tag color="gold">官方</Tag>}</Space> },
          { title: '开发者', render: (_, r) => `${r.app.developer.name} · ${r.app.developer.label}` },
          { title: '版本', render: (_, r) => `${r.version.version}(build ${r.version.build})` },
          { title: '等了', render: (_, r) => `${r.waiting_hours ?? '—'} 小时` },
          { title: '', render: (_, r) => <a onClick={() => setOpen(r.version.id)}>审核</a> },
        ]} />
      {open && <ReviewDrawer versionId={open} onClose={() => setOpen(null)} onDone={() => { setOpen(null); load(); onChanged() }} />}
    </>
  )
}

function ReviewDrawer({ versionId, onClose, onDone }: { versionId: number; onClose: () => void; onDone: () => void }) {
  const [d, setD] = useState<any>(null)
  const [checks, setChecks] = useState<Record<string, boolean>>({})
  const [reject, setReject] = useState({ code: '', pub: '', internal: '' })
  const [preview, setPreview] = useState<string | null>(null)
  useEffect(() => { get<any>(`/admin/mini-apps/reviews/${versionId}`).then(setD).catch(fail) }, [versionId])

  async function decide(approve: boolean) {
    try {
      await post(`/admin/mini-apps/reviews/${versionId}/decide`, approve
        ? { approve: true, checklist: checks }
        : { approve: false, reason_code: reject.code, note_public: reject.pub, note_internal: reject.internal, checklist: checks })
      message.success(approve ? '已通过' : '已驳回')
      onDone()
    } catch (e) { fail(e) }
  }

  async function openPreview() {
    try {
      const r = await post<{ url: string }>(`/admin/mini-apps/versions/${versionId}/preview`, {})
      setPreview(r.url)
    } catch (e) { fail(e) }
  }

  const diff = d?.diff
  const allChecked = d && d.checklist.every((c: any) => checks[c.key])
  return (
    <Drawer open width={880} onClose={onClose} title={d ? `审核:${d.app.name} ${d.version.version}` : '审核'}>
      {!d ? <Card loading /> : (
        <Space direction="vertical" size={16} style={{ width: '100%' }}>
          <Descriptions bordered size="small" column={2}>
            <Descriptions.Item label="开发者">{d.developer?.public?.name} · {d.developer?.public?.label}</Descriptions.Item>
            <Descriptions.Item label="类型">{d.app.kind === 'game' ? '小游戏' : '应用'}</Descriptions.Item>
            <Descriptions.Item label="SHA-256" span={2}><Typography.Text copyable style={{ fontFamily: 'monospace', fontSize: 12 }}>{d.version.sha256}</Typography.Text></Descriptions.Item>
            <Descriptions.Item label="更新说明" span={2}>{d.version.changelog || '—'}</Descriptions.Item>
            <Descriptions.Item label="给审核员" span={2}>{d.version.review_note || '—'}</Descriptions.Item>
            <Descriptions.Item label="原始包" span={2}><a href={d.version.package_url} target="_blank" rel="noreferrer">下载 zip(私有)</a></Descriptions.Item>
          </Descriptions>
          <Card size="small" title={`与上一个通过版本的差异${diff.baseline ? `(对比 ${diff.baseline.version})` : '(首个版本)'}`}>
            <Space direction="vertical" style={{ width: '100%' }}>
              <div>文件:新增 {diff.files.added.length} · 删除 {diff.files.removed.length} · 改动 {diff.files.changed.length}</div>
              {[...diff.files.added.map((f: string) => `+ ${f}`), ...diff.files.removed.map((f: string) => `- ${f}`), ...diff.files.changed.map((f: string) => `~ ${f}`)]
                .slice(0, 50).map((x: string) => <Typography.Text key={x} style={{ fontFamily: 'monospace', fontSize: 12 }}>{x}</Typography.Text>)}
              {diff.domains.added.length > 0 && <Alert type="warning" message={`新增服务器域名:${diff.domains.added.join('、')}`} />}
              {diff.capabilities.added.length > 0 && <Alert type="warning" message={`新增能力:${diff.capabilities.added.join('、')}`} />}
              {Object.keys(diff.listing).length > 0 && <Alert type="info" message="展示信息有改动" description={
                Object.entries(diff.listing).map(([k, v]: [string, any]) => <div key={k}><b>{k}</b>:{String(v.before ?? '—').slice(0, 80)} → {String(v.after ?? '—').slice(0, 80)}</div>)} />}
              {Object.keys(diff.superz).length > 0 && <div>superz.json:{JSON.stringify(diff.superz)}</div>}
            </Space>
          </Card>
          <Card size="small" title="展示信息(随这个版本送审)">
            <Descriptions size="small" column={1}>
              <Descriptions.Item label="名称">{d.version.listing?.name}</Descriptions.Item>
              <Descriptions.Item label="一句话">{d.version.listing?.tagline}</Descriptions.Item>
              <Descriptions.Item label="描述">{d.version.listing?.description}</Descriptions.Item>
              <Descriptions.Item label="隐私政策"><Typography.Paragraph style={{ whiteSpace: 'pre-wrap', margin: 0 }}>{d.version.listing?.privacy_policy}</Typography.Paragraph></Descriptions.Item>
              <Descriptions.Item label="数据声明">{(d.version.listing?.data_declaration || []).map((x: any) => `${x.field}(${x.purpose})`).join(';') || '声明不收集'}</Descriptions.Item>
              <Descriptions.Item label="服务器域名">{(d.version.request_domains || []).join('、') || '无'}</Descriptions.Item>
            </Descriptions>
          </Card>
          <Card size="small" title="预览" extra={<Button size="small" onClick={openPreview}>在下面打开</Button>}>
            {preview ? (
              <iframe src={preview} title="预览" sandbox="allow-scripts allow-same-origin" style={{ width: 390, height: 700, border: '1px solid var(--sz-line)', borderRadius: 12 }} />
            ) : <Typography.Text type="secondary">不带宿主桥,只看页面长什么样;要走完整流程请用开发者后台同款模拟器或体验版扫码。</Typography.Text>}
          </Card>
          <Card size="small" title={`审核清单(第 ${d.checklist_version} 版)`}>
            <Space direction="vertical">
              {d.checklist.map((c: any) => (
                <Checkbox key={c.key} checked={!!checks[c.key]} onChange={(e) => setChecks({ ...checks, [c.key]: e.target.checked })}>{c.label}</Checkbox>
              ))}
            </Space>
          </Card>
          <Card size="small" title="结论">
            <Space direction="vertical" style={{ width: '100%' }}>
              <Button type="primary" disabled={!allChecked} onClick={() => decide(true)}>通过{!allChecked && '(先逐项勾完清单)'}</Button>
              <Select placeholder="驳回原因(必选)" options={reasonOptions} style={{ width: 360 }} value={reject.code || undefined}
                onChange={(v) => setReject({ ...reject, code: v })} />
              <Input.TextArea placeholder="给开发者看的说明(必填,会记进审核记录)" rows={2} maxLength={500}
                value={reject.pub} onChange={(e) => setReject({ ...reject, pub: e.target.value })} />
              <Input.TextArea placeholder="内部备注(永不公开)" rows={2} maxLength={500}
                value={reject.internal} onChange={(e) => setReject({ ...reject, internal: e.target.value })} />
              <Button danger disabled={!reject.code || !reject.pub.trim()} onClick={() => decide(false)}>驳回</Button>
            </Space>
          </Card>
          <Card size="small" title="这个应用的审核记录">
            <List size="small" dataSource={d.history} renderItem={(h: any) => (
              <List.Item>{t(h.created_at)} · {h.action_label} {h.reason_code} {h.note_public}
                {h.note_internal && <Typography.Text type="secondary">(内部:{h.note_internal})</Typography.Text>} · {h.actor_name}</List.Item>)} />
          </Card>
        </Space>
      )}
    </Drawer>
  )
}

// ---------------------------------------------------------------- 开发者认证

function Developers({ onChanged }: { onChanged: () => void }) {
  const [status, setStatus] = useState('pending')
  const [rows, setRows] = useState<any[]>([])
  const load = () => get<{ items: any[] }>(`/admin/mini-apps/developers?status=${status}`).then((r) => setRows(r.items)).catch(fail)
  useEffect(() => { load() }, [status])
  function decide(d: any, approve: boolean) {
    let reason = ''
    Modal.confirm({
      title: approve ? `通过「${d.company_name || d.display_name}」的认证?` : '驳回认证',
      content: approve ? null : <Input.TextArea rows={2} placeholder="驳回原因(开发者看得到)" onChange={(e) => { reason = e.target.value }} />,
      onOk: async () => {
        try { await post(`/admin/mini-apps/developers/${d.id}/verify`, { approve, reason }); load(); onChanged() } catch (e) { fail(e); throw e }
      },
    })
  }
  return (
    <>
      <Radio.Group value={status} onChange={(e) => setStatus(e.target.value)} optionType="button" style={{ marginBottom: 12 }}
        options={[{ value: 'pending', label: '待审核' }, { value: 'verified', label: '已认证' }, { value: 'rejected', label: '未通过' }, { value: 'suspended', label: '已暂停' }]} />
      <Table rowKey="id" size="small" dataSource={rows} locale={{ emptyText: '没有' }}
        columns={[
          { title: '类型', render: (_, d) => (d.kind === 'company' ? '企业' : '个人') },
          { title: '名称', render: (_, d) => d.company_name || d.display_name },
          { title: '统一社会信用代码 / 实名', render: (_, d) => d.uscc || (d.real_name_masked ? `${d.real_name_masked}(尾号 ${d.id_no_tail})` : '—') },
          { title: '营业执照', render: (_, d) => (d.license_key ? <a href={d.license_key} target="_blank" rel="noreferrer">查看</a> : '—') },
          { title: '联系人', render: (_, d) => `${d.contact_name || '—'} ${d.contact_email || ''}` },
          { title: '提交', render: (_, d) => t(d.submitted_at) },
          { title: '', render: (_, d) => d.status === 'pending' && <Space><a onClick={() => decide(d, true)}>通过</a><a onClick={() => decide(d, false)}>驳回</a></Space> },
        ]} />
    </>
  )
}

// ---------------------------------------------------------------- 能力 / 投诉 / 申诉

function CapabilityQueue({ onChanged }: { onChanged: () => void }) {
  const [rows, setRows] = useState<any[]>([])
  const load = () => get<{ items: any[] }>('/admin/mini-apps/capabilities').then((r) => setRows(r.items)).catch(fail)
  useEffect(() => { load() }, [])
  function decide(c: any, approve: boolean) {
    let note = ''
    Modal.confirm({
      title: `${approve ? '通过' : '驳回'}「${c.app.name}」的 ${c.capability} 申请`,
      content: <Input.TextArea rows={2} placeholder={approve ? '备注(可选)' : '驳回原因(必填)'} onChange={(e) => { note = e.target.value }} />,
      onOk: async () => { try { await post(`/admin/mini-apps/capabilities/${c.id}/decide`, { approve, note }); load(); onChanged() } catch (e) { fail(e); throw e } },
    })
  }
  return (
    <List dataSource={rows} locale={{ emptyText: '没有待批的能力申请' }} renderItem={(c) => (
      <List.Item actions={[<a key="y" onClick={() => decide(c, true)}>通过</a>, <a key="n" onClick={() => decide(c, false)}>驳回</a>]}>
        <List.Item.Meta title={`${c.app.name} · ${c.capability}`} description={<>理由:{c.justification}<br />数据声明:{(c.app.data_declaration || []).map((x: any) => x.field).join('、') || '无'}</>} />
      </List.Item>)} />
  )
}

function Reports({ onChanged }: { onChanged: () => void }) {
  const [groups, setGroups] = useState<any[]>([])
  const load = () => get<{ groups: any[] }>('/admin/mini-apps/reports').then((r) => setGroups(r.groups)).catch(fail)
  useEffect(() => { load() }, [])
  function handle(r: any, dismiss: boolean) {
    let resolution = ''
    Modal.confirm({
      title: dismiss ? '驳回这条投诉' : '标记已处理',
      content: <Input.TextArea rows={2} placeholder="处理结果(开发者看得到;举报人身份不会给出去)" onChange={(e) => { resolution = e.target.value }} />,
      onOk: async () => { try { await post(`/admin/mini-apps/reports/${r.id}/handle`, { resolution, dismiss }); load(); onChanged() } catch (e) { fail(e); throw e } },
    })
  }
  if (!groups.length) return <Empty description="没有未处理的投诉" />
  return (
    <Space direction="vertical" style={{ width: '100%' }}>
      {groups.map((g) => (
        <Card key={g.appid} size="small" title={<Space>{g.name}<Tag>{g.distinct_reporters} 人投诉</Tag>{g.flagged && <Tag color="error">已达复审阈值</Tag>}</Space>}>
          <List size="small" dataSource={g.items} renderItem={(r: any) => (
            <List.Item actions={[<a key="h" onClick={() => handle(r, false)}>已处理</a>, <a key="d" onClick={() => handle(r, true)}>驳回</a>]}>
              {t(r.created_at)} · {r.reason_code} {r.reason_label} · {r.detail || '—'} · 投诉人 {r.reporter}
              {r.evidence_keys?.map((k: string, i: number) => <a key={k} href={k} target="_blank" rel="noreferrer"> 截图{i + 1}</a>)}
            </List.Item>)} />
        </Card>
      ))}
    </Space>
  )
}

function Appeals({ onChanged }: { onChanged: () => void }) {
  const [rows, setRows] = useState<any[]>([])
  const load = () => get<{ items: any[] }>('/admin/mini-apps/appeals').then((r) => setRows(r.items)).catch(fail)
  useEffect(() => { load() }, [])
  function resolve(a: any, overturn: boolean) {
    let pub = ''
    let internal = ''
    Modal.confirm({
      title: overturn ? '申诉成立:撤销原结论' : '维持原结论',
      content: <Space direction="vertical" style={{ width: '100%' }}>
        {overturn && <Alert type="warning" message="撤销后状态真的会回来(驳回的版本回到审核通过、暂停的应用恢复在线……)" />}
        <Input.TextArea rows={2} placeholder="给开发者看的说明(必填)" onChange={(e) => { pub = e.target.value }} />
        <Input.TextArea rows={2} placeholder="内部备注" onChange={(e) => { internal = e.target.value }} />
      </Space>,
      onOk: async () => {
        try { await post(`/admin/mini-apps/appeals/${a.appeal.id}/resolve`, { overturn, note_public: pub, note_internal: internal }); load(); onChanged() }
        catch (e) { fail(e); throw e }
      },
    })
  }
  return (
    <List dataSource={rows} locale={{ emptyText: '没有待处理的申诉' }} renderItem={(a) => (
      <List.Item actions={a.you_decided_original
        ? [<Typography.Text key="x" type="secondary">原结论是你作出的,须由另一名审核员处理</Typography.Text>]
        : [<a key="o" onClick={() => resolve(a, true)}>申诉成立</a>, <a key="u" onClick={() => resolve(a, false)}>维持</a>]}>
        <List.Item.Meta
          title={`${a.appeal.app_name || '开发者账号'} · 对「${a.original?.action_label}」的申诉`}
          description={<>原结论:{a.original?.reason_code} {a.original?.note_public}(by {a.original?.actor_name || '系统'},{t(a.original?.created_at)})<br />申诉:{a.appeal.note_public}</>} />
      </List.Item>)} />
  )
}

// ---------------------------------------------------------------- 应用与处罚

function Apps() {
  const [status, setStatus] = useState<string>('online')
  const [rows, setRows] = useState<any[]>([])
  const load = () => get<{ items: any[] }>(`/admin/mini-apps/apps?status=${status}`).then((r) => setRows(r.items)).catch(fail)
  useEffect(() => { load() }, [status])
  function punish(a: any, kind: 'suspend' | 'remove') {
    const v = { code: '', pub: '', internal: '', quarantine: false }
    Modal.confirm({
      title: kind === 'suspend' ? `暂停「${a.name}」` : `移除「${a.name}」(终态)`,
      width: 520,
      content: <Space direction="vertical" style={{ width: '100%' }}>
        <Select placeholder="原因代码(必选)" options={reasonOptions} style={{ width: '100%' }} onChange={(x) => { v.code = x }} />
        <Input.TextArea rows={2} placeholder="给开发者看、透明中心公示的说明" onChange={(e) => { v.pub = e.target.value }} />
        <Input.TextArea rows={2} placeholder="内部备注(不公开)" onChange={(e) => { v.internal = e.target.value }} />
        {kind === 'suspend' && <Checkbox onChange={(e) => { v.quarantine = e.target.checked }}>同时紧急隔离当前版本(文件立即 404)</Checkbox>}
      </Space>,
      okButtonProps: { danger: true },
      onOk: async () => {
        try {
          await post(`/admin/mini-apps/apps/${a.appid}/${kind}`, { reason_code: v.code, note_public: v.pub, note_internal: v.internal, quarantine: v.quarantine })
          load()
        } catch (e) { fail(e); throw e }
      },
    })
  }
  function restore(a: any) {
    let note = ''
    Modal.confirm({
      title: `恢复「${a.name}」`,
      content: <Input.TextArea rows={2} placeholder="依据(比如哪个版本复审通过了),会公示" onChange={(e) => { note = e.target.value }} />,
      onOk: async () => { try { await post(`/admin/mini-apps/apps/${a.appid}/restore`, { note }); load() } catch (e) { fail(e); throw e } },
    })
  }
  return (
    <>
      <Radio.Group value={status} onChange={(e) => setStatus(e.target.value)} optionType="button" style={{ marginBottom: 12 }}
        options={['online', 'offline', 'draft', 'suspended', 'removed'].map((s) => ({ value: s, label: { online: '在线', offline: '已下架', draft: '草稿', suspended: '已暂停', removed: '已移除' }[s] }))} />
      <Table rowKey="appid" size="small" dataSource={rows}
        columns={[
          { title: '应用', render: (_, a) => <Space>{a.name}{a.is_official && <Tag color="gold">官方</Tag>}{a.curated && <Tag color="processing">精选</Tag>}</Space> },
          { title: 'AppID', dataIndex: 'appid', render: (x) => <span style={{ fontFamily: 'monospace' }}>{x}</span> },
          { title: '开发者', render: (_, a) => `${a.developer.name} · ${a.developer.label}` },
          { title: '首次上架', render: (_, a) => t(a.first_released_at) },
          { title: '', render: (_, a) => <Space>
            {['online', 'offline'].includes(a.status) && <a onClick={() => punish(a, 'suspend')}>暂停</a>}
            {a.status === 'suspended' && <a onClick={() => restore(a)}>恢复</a>}
            {a.status !== 'removed' && <a style={{ color: 'var(--sz-danger)' }} onClick={() => punish(a, 'remove')}>移除</a>}
          </Space> },
        ]} />
    </>
  )
}

// ---------------------------------------------------------------- 精选 / 注册 / 统计

function Curation() {
  const [rows, setRows] = useState<any[]>([])
  const [form, setForm] = useState({ appid: '', position: 1, reason: '' })
  const load = () => get<{ items: any[] }>('/admin/mini-apps/curation').then((r) => setRows(r.items)).catch(fail)
  useEffect(() => { load() }, [])
  return (
    <Space direction="vertical" style={{ width: '100%' }}>
      <Alert type="info" message="精选是人工的,没有任何能买的东西。每次进出精选的理由都在透明中心公示。" />
      <Space wrap>
        <Input placeholder="AppID" value={form.appid} onChange={(e) => setForm({ ...form, appid: e.target.value })} style={{ width: 200 }} />
        <InputNumber min={1} max={99} value={form.position} onChange={(v) => setForm({ ...form, position: Number(v) || 1 })} addonBefore="位置" />
        <Input placeholder="理由(公示)" value={form.reason} onChange={(e) => setForm({ ...form, reason: e.target.value })} style={{ width: 320 }} />
        <Button onClick={() => post('/admin/mini-apps/curation', form).then(() => { load(); message.success('已加入精选') }).catch(fail)}>加入 / 调整</Button>
      </Space>
      <Table rowKey="appid" size="small" dataSource={rows} locale={{ emptyText: '还没有精选' }}
        columns={[
          { title: '位置', dataIndex: 'position' }, { title: '应用', dataIndex: 'name' }, { title: '理由', dataIndex: 'reason' },
          { title: '', render: (_, r) => <a onClick={() => {
            let reason = ''
            Modal.confirm({
              title: `把「${r.name}」移出精选`,
              content: <Input placeholder="理由(公示)" onChange={(e) => { reason = e.target.value }} />,
              onOk: async () => { try { await del(`/admin/mini-apps/curation/${r.appid}?reason=${encodeURIComponent(reason)}`); load() } catch (e) { fail(e); throw e } },
            })
          }}>移出</a> },
        ]} />
    </Space>
  )
}

function Signup() {
  // 注册默认对所有人开放;「仅限邀请」「暂停注册」是出问题时临时收紧用的闸
  const [mode, setMode] = useState('open')
  const [rows, setRows] = useState<any[]>([])
  const [phone, setPhone] = useState('')
  const load = () => get<{ items: any[]; mode: string }>('/admin/mini-apps/invites').then((r) => { setRows(r.items); setMode(r.mode) }).catch(fail)
  useEffect(() => { load() }, [])
  return (
    <Space direction="vertical" style={{ width: '100%' }}>
      <Space>
        <span>开发者注册:</span>
        <Radio.Group value={mode} optionType="button"
          onChange={(e) => put('/admin/mini-apps/signup-mode', { mode: e.target.value }).then(load).catch(fail)}
          options={[{ value: 'open', label: '开放注册(默认)' }, { value: 'invite', label: '仅限邀请' }, { value: 'closed', label: '暂停注册' }]} />
      </Space>
      <Typography.Text type="secondary">
        小程序、小游戏的开发者谁都可以注册。下面的邀请名单只在临时切到「仅限邀请」时起作用;已有开发者不受开关影响。
      </Typography.Text>
      <Space.Compact>
        <Input placeholder="邀请的手机号" value={phone} onChange={(e) => setPhone(e.target.value)} />
        <Button onClick={() => post('/admin/mini-apps/invites', { phone: phone.trim() }).then(() => { setPhone(''); load() }).catch(fail)}>邀请</Button>
      </Space.Compact>
      <Table rowKey="id" size="small" dataSource={rows}
        columns={[
          { title: '手机尾号', dataIndex: 'phone_tail' }, { title: '邀请时间', render: (_, r) => t(r.created_at) },
          { title: '已注册', render: (_, r) => (r.used_at ? t(r.used_at) : '—') },
          { title: '', render: (_, r) => <a onClick={() => del(`/admin/mini-apps/invites/${r.id}`).then(load).catch(fail)}>删除</a> },
        ]} />
    </Space>
  )
}

function Stats() {
  const [days, setDays] = useState(30)
  const [s, setS] = useState<any>(null)
  useEffect(() => { get<any>(`/admin/mini-apps/stats?days=${days}`).then(setS).catch(fail) }, [days])
  return (
    <Space direction="vertical">
      <Space>近 <InputNumber min={1} max={365} value={days} onChange={(v) => setDays(Number(v) || 30)} /> 天 <Switch disabled checked /> 与透明中心同一个算法</Space>
      {s && <Descriptions bordered size="small" column={2}>
        <Descriptions.Item label="提交">{s.submitted}</Descriptions.Item>
        <Descriptions.Item label="通过 / 驳回">{s.approved} / {s.rejected}</Descriptions.Item>
        <Descriptions.Item label="审核时长中位数">{s.median_review_hours ?? '—'} 小时</Descriptions.Item>
        <Descriptions.Item label="驳回原因类别">{Object.entries(s.reject_by_category || {}).map(([k, v]) => `${k} ${v}`).join('、') || '—'}</Descriptions.Item>
      </Descriptions>}
    </Space>
  )
}
