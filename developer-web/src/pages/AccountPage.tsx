import {
  Alert, Button, Card, Descriptions, Form, Input, List, Modal, Popconfirm, Radio, Select, Space, Table, Tag, Typography,
  Upload, message,
} from 'antd'
import { useEffect, useState } from 'react'

import { AgentCall, AgentToken, AgentTokenIssued, ApiError, Me, api, time } from '../api'

function err(e: unknown) {
  message.error(e instanceof ApiError ? e.message : String(e))
}

/**
 * 账号与认证(#329):开发者名、个人实名 / 企业认证、接受开发者规则,以及 AI 助手(MCP)令牌。
 *
 * 个人:姓名 + 身份证号(机器核验,须满 18 岁),**只存密文、页面只显示尾号**;
 * 公开页只显示你自取的开发者名 +「个人开发者 · 已实名」。企业:营业执照 + 统一社会信用代码,人工审核,企业名公开。
 */
export default function AccountPage({ me, onChanged, reload }: { me: Me | null; onChanged: (m: Me) => void; reload: () => void }) {
  const [kind, setKind] = useState<'individual' | 'company'>('individual')
  const [rules, setRules] = useState<{ draft: boolean; sections: Array<{ title: string; items: string[] }> } | null>(null)
  const [license, setLicense] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => { api.rules().then(setRules).catch(() => undefined) }, [])
  if (!me) return null

  const run = async (fn: () => Promise<Me>, ok: string) => {
    setBusy(true)
    try {
      onChanged(await fn())
      message.success(ok)
    } catch (e) {
      message.error(e instanceof ApiError ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }
  const canVerify = me.status === 'unverified' || me.status === 'rejected'

  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      <Card title="开发者信息">
        <Form layout="vertical" initialValues={{ display_name: me.display_name, contact_email: me.contact_email }}
          onFinish={(v) => run(() => api.updateProfile(v), '已保存')} disabled={busy}>
          <Form.Item name="display_name" label="开发者名(公开展示)" rules={[{ required: true, min: 2, max: 40 }]}
            extra="企业认证通过后公开展示公司名;个人开发者公开展示这个名字。不能用「超级赞」「官方」等字样。">
            <Input />
          </Form.Item>
          <Form.Item name="contact_email" label="联系邮箱(不公开,审核有问题时联系你)">
            <Input />
          </Form.Item>
          <Button htmlType="submit">保存</Button>
        </Form>
      </Card>

      <Card title="认证" extra={<Tag>{me.status_label}</Tag>}>
        {me.status === 'verified' && (
          <Descriptions column={1} size="small">
            <Descriptions.Item label="公开显示">{me.public.name} · {me.public.label}</Descriptions.Item>
            {me.kind === 'individual' && <Descriptions.Item label="实名">{me.real_name_masked}(证号尾号 {me.id_no_tail})</Descriptions.Item>}
            {me.kind === 'company' && <Descriptions.Item label="企业">{me.company_name}({me.uscc})</Descriptions.Item>}
          </Descriptions>
        )}
        {me.status === 'pending' && <Alert type="info" showIcon message="企业认证审核中" description="审核结果会出现在「消息」里。平台不承诺具体时限,审核时长的中位数在透明中心公示。" />}
        {me.status === 'rejected' && <Alert type="error" showIcon style={{ marginBottom: 12 }} message="认证没有通过" description={me.reject_reason} />}
        {canVerify && (
          <>
            <Typography.Paragraph type="secondary">
              没认证也能建应用、传开发版、加体验者、用模拟器;**认证通过才能提交审核**。
            </Typography.Paragraph>
            <Radio.Group value={kind} onChange={(e) => setKind(e.target.value)} style={{ marginBottom: 12 }}>
              <Radio.Button value="individual">个人</Radio.Button>
              <Radio.Button value="company">企业</Radio.Button>
            </Radio.Group>
            {kind === 'individual' ? (
              <Form layout="vertical" disabled={busy} onFinish={(v) => run(() => api.verifyIndividual(v), '实名核验通过')}>
                <Form.Item name="real_name" label="真实姓名" rules={[{ required: true, min: 2 }]}><Input /></Form.Item>
                <Form.Item name="id_no" label="身份证号" rules={[{ required: true, len: 18 }]}
                  extra="须年满 18 周岁。只存密文,页面只显示尾号;真名不会公开。"><Input /></Form.Item>
                <Button type="primary" htmlType="submit">提交核验</Button>
              </Form>
            ) : (
              <Form layout="vertical" disabled={busy}
                onFinish={(v) => run(() => api.verifyCompany({ ...v, license_key: license }), '已提交,等待人工审核')}>
                <Form.Item name="company_name" label="企业名称(公开展示)" rules={[{ required: true, min: 4 }]}><Input /></Form.Item>
                <Form.Item name="uscc" label="统一社会信用代码" rules={[{ required: true, len: 18 }]}><Input /></Form.Item>
                <Form.Item label="营业执照" required extra="只有审核员看得到(私有存储)">
                  <Upload accept="image/*" maxCount={1} showUploadList={false}
                    customRequest={async ({ file }) => {
                      try {
                        const r = await api.uploadImage(file as File, 'dev_license')
                        setLicense(r.url)
                        message.success('已上传')
                      } catch (e) {
                        message.error(e instanceof ApiError ? e.message : String(e))
                      }
                    }}>
                    <Button>{license ? '已上传,点击更换' : '上传照片'}</Button>
                  </Upload>
                </Form.Item>
                <Form.Item name="contact_name" label="联系人" rules={[{ required: true, min: 2 }]}><Input /></Form.Item>
                <Button type="primary" htmlType="submit" disabled={!license}>提交审核</Button>
              </Form>
            )}
          </>
        )}
      </Card>

      <Card title="开发者规则" extra={me.agreement.ok ? <Tag color="success">已接受第 {me.agreement.accepted} 版</Tag>
        : <Tag color="warning">待接受第 {me.agreement.required} 版</Tag>}>
        {rules?.draft && <Alert type="warning" message="开发者规则与协议目前是草案,法务定稿前可能调整;每次调整都记在规则留痕里。" style={{ marginBottom: 12 }} />}
        <List
          dataSource={rules?.sections || []}
          renderItem={(s) => (
            <List.Item style={{ display: 'block' }}>
              <Typography.Text strong>{s.title}</Typography.Text>
              <ul style={{ margin: '6px 0 0', paddingLeft: 18 }}>
                {s.items.filter((x) => x).map((x, i) => <li key={i} style={{ color: 'var(--sz-ink)', fontSize: 13 }}>{x.replace(/\*\*/g, '')}</li>)}
              </ul>
            </List.Item>
          )}
        />
        <Space style={{ marginTop: 12 }}>
          <Button type="primary" disabled={me.agreement.ok || busy}
            onClick={() => run(() => api.acceptAgreement(me.agreement.required), '已接受')}>
            我已阅读并接受第 {me.agreement.required} 版
          </Button>
          <a href="/opensource" target="_blank" rel="noreferrer">规则变更留痕 ›</a>
          <a onClick={reload}>刷新</a>
        </Space>
      </Card>

      <AgentCard me={me} />
    </Space>
  )
}

// ---------------------------------------------------------------- AI 助手(MCP)

const MCP_README = 'https://github.com/hanpaopao66/chaojizan/blob/main/mcp-server/README.md'
/** 服务端 create_agent_token 的上限,按「没吊销」计数 —— 过期但没吊销的也占名额 */
const MAX_AGENT_TOKENS = 10

/** 贴进 MCP 客户端的配置。接口和这个后台同源,所以 SUPERZ_API 就是当前页面的 origin */
function mcpConfig(token: string) {
  return JSON.stringify({
    mcpServers: {
      superz: {
        command: 'python3',
        args: ['/绝对路径/mcp-server/server.py'],
        env: { SUPERZ_API: location.origin, SUPERZ_AGENT_TOKEN: token },
      },
    },
  }, null, 2)
}

type CallRow = AgentCall & { key: number }

/**
 * 给 AI 助手签令牌(/auth/agent-tokens)。开发者账号的令牌只有「发布小程序和小游戏」一项,
 * 放行哪些接口见服务端 security.AGENT_MINIAPP;这里的说明照那张表写,改了那边要跟着改。
 * 明文只在签发那一次返回,弹窗关不掉,必须点「我已保存」。
 */
function AgentCard({ me }: { me: Me }) {
  const [tokens, setTokens] = useState<AgentToken[] | null>(null)
  const [calls, setCalls] = useState<AgentCall[] | null>(null)
  const [loadErr, setLoadErr] = useState('')
  const [name, setName] = useState('')
  const [days, setDays] = useState(90)
  const [busy, setBusy] = useState(false)
  const [issued, setIssued] = useState<AgentTokenIssued | null>(null)

  const load = () => Promise.all([api.agentTokens(), api.agentActivity()])
    .then(([t, a]) => { setTokens(t); setCalls(a.items); setLoadErr('') })
    .catch((e) => setLoadErr(e instanceof ApiError ? e.message : String(e)))
  useEffect(() => { load() }, [])

  async function issue() {
    setBusy(true)
    try {
      setIssued(await api.createAgentToken({ name: name.trim(), days }))
      setName('')
      load()
    } catch (e) {
      err(e)
    } finally {
      setBusy(false)
    }
  }

  const live = tokens?.filter((t) => !t.revoked).length ?? 0
  const config = issued ? mcpConfig(issued.token) : ''
  return (
    <Card title="AI 助手(MCP)">
      <Space direction="vertical" size={16} style={{ width: '100%' }}>
        <div>
          {/* 中文句子不在行中间折行:JSX 会把折行变成一个空格 */}
          <Typography.Paragraph type="secondary" style={{ fontSize: 13 }}>
            给支持 MCP 的 AI 助手(比如 Claude)签一个令牌,它就能替你发布小程序和小游戏:
            {'建应用、改展示信息、传包、设体验版、提交审核、撤回审核、把审核通过的版本发布上线、回滚,以及查看审核结论和数据。'}
          </Typography.Paragraph>
          <Typography.Paragraph type="secondary" style={{ fontSize: 13 }}>
            下架和删除应用、改密钥、改服务器域名、加体验者、实名认证、接受开发者规则、申诉,助手都做不了,只能你自己在这个后台里做。
            <Typography.Text strong>审核由平台的人做</Typography.Text>,没过审的版本助手发布不了。
          </Typography.Paragraph>
          <Space size={16} wrap>
            <a href="/developers/ai-publish" target="_blank" rel="noreferrer">操作说明 ›</a>
            <a href={MCP_README} target="_blank" rel="noreferrer">MCP 服务说明(开源仓库)›</a>
          </Space>
        </div>
        {!me.can_submit && (
          <Alert type="info" showIcon message="认证通过、接受最新版开发者规则之后,助手才能提交审核;这两步只能你自己在上面做。" />
        )}
        {loadErr && <Alert type="error" showIcon message={loadErr} action={<a onClick={load}>重试</a>} />}

        <Card size="small" title="签发令牌">
          <Space wrap>
            <Input placeholder="名称,比如「我的 Claude」" maxLength={40} value={name} onChange={(e) => setName(e.target.value)}
              style={{ width: 240 }} />
            <Select value={days} onChange={setDays} style={{ width: 140 }}
              options={[30, 90, 180, 365].map((d) => ({ value: d, label: `有效期 ${d} 天` }))} />
            <Button type="primary" loading={busy} disabled={!tokens || live >= MAX_AGENT_TOKENS} onClick={issue}>签发</Button>
          </Space>
          <Typography.Paragraph type="secondary" style={{ fontSize: 13, margin: '8px 0 0' }}>
            权限只有「发布小程序和小游戏」一项。一个账号最多同时有 {MAX_AGENT_TOKENS} 个没吊销的令牌,过期了没吊销的也算
            {tokens && <>,现在 {live} 个</>}。
          </Typography.Paragraph>
        </Card>

        <Card size="small" title="已签发的令牌">
          <Table<AgentToken> rowKey="id" size="small" loading={!tokens && !loadErr} dataSource={tokens || []}
            pagination={{ pageSize: 10, hideOnSinglePage: true }} scroll={{ x: 'max-content' }}
            locale={{ emptyText: tokens ? '还没签过令牌' : '没拉到' }}
            columns={[
              { title: '名称', dataIndex: 'name' },
              { title: '权限', render: (_, t) => <Space size={4} wrap>{t.scope_labels.map((l) => <Tag key={l}>{l}</Tag>)}</Space> },
              { title: '签发时间', render: (_, t) => time(t.created_at) },
              {
                title: '最近使用',
                render: (_, t) => (t.last_used_at ? time(t.last_used_at) : <Typography.Text type="secondary">还没用过</Typography.Text>),
              },
              { title: '到期时间', render: (_, t) => time(t.expires_at) },
              {
                title: '状态', render: (_, t) => (t.revoked ? <Tag>已吊销</Tag>
                  : new Date(t.expires_at).getTime() <= Date.now() ? <Tag color="warning">已过期</Tag>
                    : <Tag color="success">有效</Tag>),
              },
              {
                title: '操作', render: (_, t) => !t.revoked && (
                  <Popconfirm title="吊销之后,用这个令牌的助手下一次调用就会失败,不能恢复。确定?"
                    okText="吊销" okButtonProps={{ danger: true }}
                    onConfirm={() => api.revokeAgentToken(t.id).then(() => { message.success('已吊销'); load() }).catch(err)}>
                    <a>吊销</a>
                  </Popconfirm>
                ),
              },
            ]} />
        </Card>

        <Card size="small" title="最近的调用" extra={<a onClick={load}>刷新</a>}>
          <Typography.Paragraph type="secondary" style={{ fontSize: 13 }}>
            助手最近的 50 次调用。只记方法、路径、状态码和时间,不记请求内容。
          </Typography.Paragraph>
          <Table<CallRow> size="small" loading={!calls && !loadErr} dataSource={(calls || []).map((c, i) => ({ ...c, key: i }))}
            pagination={{ pageSize: 10, hideOnSinglePage: true }} scroll={{ x: 'max-content' }}
            locale={{ emptyText: calls ? '助手还没调用过' : '没拉到' }}
            columns={[
              { title: '时间', render: (_, c) => time(c.at) },
              { title: '方法', dataIndex: 'method' },
              { title: '路径', render: (_, c) => <span style={{ fontFamily: 'monospace', fontSize: 12 }}>{c.path}</span> },
              {
                title: '状态码',
                render: (_, c) => <Typography.Text type={c.status >= 400 ? 'danger' : undefined}>{c.status}</Typography.Text>,
              },
            ]} />
        </Card>
      </Space>

      <Modal title="令牌只显示这一次" open={!!issued} closable={false} maskClosable={false} keyboard={false} width={600}
        footer={<Button type="primary" onClick={() => setIssued(null)}>我已保存</Button>}>
        <Alert type="warning" showIcon style={{ marginBottom: 12 }}
          message="请立刻复制保存,关掉这个窗口就再也看不到了"
          description="丢了就在列表里吊销它,再签一个。别提交进代码仓库、别发给别人:拿到它的人能以你的名义传包、提交审核、发布审核通过的版本。" />
        <Typography.Paragraph>
          <Typography.Text code copyable={{ text: issued?.token || '' }} style={{ wordBreak: 'break-all' }}>{issued?.token}</Typography.Text>
        </Typography.Paragraph>
        <Typography.Paragraph type="secondary" style={{ fontSize: 13 }}>
          权限:{issued?.scope_labels.join('、')} · 到期:{time(issued?.expires_at)}
        </Typography.Paragraph>
        <Typography.Text strong copyable={{ text: config }}>MCP 客户端配置</Typography.Text>
        <pre style={{
          margin: '6px 0 8px', padding: 12, background: 'var(--sz-surface-alt)', border: '1px solid var(--sz-line)',
          borderRadius: 8, fontSize: 12, lineHeight: 1.5, whiteSpace: 'pre-wrap', wordBreak: 'break-all',
        }}>{config}</pre>
        <Typography.Paragraph type="secondary" style={{ fontSize: 13, marginBottom: 0 }}>
          args 换成你电脑上 server.py 的绝对路径(单独下载的那个文件,或开源仓库里的 mcp-server/server.py 都行);
          {'SUPERZ_API 是这个后台所在的站点,不用改。Claude Code 等客户端的写法见「操作说明」。'}
        </Typography.Paragraph>
      </Modal>
    </Card>
  )
}
