import {
  Alert, Button, Card, Descriptions, Drawer, Empty, Image, Input, List, Modal, Radio, Select, Space, Table, Tabs, Tag,
  Typography, message,
} from 'antd'
import { useCallback, useEffect, useState } from 'react'

import {
  ChatMessagesView, ChatReportDetail, ChatReportItem, chatMessages, chatReport, chatReports, createSanction,
  handleChatReport, handleVideoReport, VideoReportItem, videoReports,
} from '../../api_community'
import {
  Muted, PersonName, SanctionForm, SanctionFormValue, STATUS_COLORS, emptySanction, fail, reasonOptions,
  sanctionProblem, t, useReasonCodes,
} from './shared'

/**
 * 举报处理:视频 / 评论 / 弹幕举报 + 聊天举报。
 *
 * 两边都是「7 天内 3 个不同的人举报同一个对象」排最前(标「多人举报」);举报人是谁这里一律不给。
 *
 * 聊天举报按 **S8** 办:详情里没有任何消息内容,要看被举报的消息得点一下,
 * 服务端只给举报单里那几条和前后各 5 条,**每次查看都留痕、按月在透明中心公示次数** ——
 * 所以按钮要点第二下才发请求,页面上也写明白。
 */
export default function ReportsPage() {
  return (
    <Card title="举报处理">
      <Tabs items={[
        { key: 'chat', label: '聊天举报', children: <ChatReports /> },
        { key: 'video', label: '视频 / 评论 / 弹幕举报', children: <VideoReports /> },
      ]} />
    </Card>
  )
}

const TARGET_LABELS: Record<string, string> = {
  chat: '整个会话', message: '消息', user: '用户', video: '视频', comment: '评论', danmaku: '弹幕',
}
const VIDEO_REPORT_STATUS: Record<string, string> = {
  open: '待处理', escalated: '多人举报', actioned: '已处置', dismissed: '不成立',
}
const SANCTION_STATUS: Record<string, string> = {
  active: '生效中', expired: '已到期', revoked: '已撤销', done: '已执行',
}

// ---------------------------------------------------------------- 聊天

function ChatReports() {
  const [status, setStatus] = useState('open')
  const [rows, setRows] = useState<ChatReportItem[]>([])
  const [loading, setLoading] = useState(false)
  const [open, setOpen] = useState<number | null>(null)
  const load = useCallback(async () => {
    setLoading(true)
    try { setRows((await chatReports(status)).items) } catch (e) { fail(e) } finally { setLoading(false) }
  }, [status])
  useEffect(() => { void load() }, [load])

  return (
    <>
      <Space style={{ marginBottom: 12 }} wrap>
        <Radio.Group value={status} onChange={(e) => setStatus(e.target.value)} optionType="button"
          options={[{ value: 'open', label: '待处理' }, { value: 'handled', label: '已处理' }, { value: 'all', label: '全部' }]} />
        <Muted>多人举报(7 天内 3 个不同的人举报同一个对象)的排在最前</Muted>
      </Space>
      <Table<ChatReportItem> rowKey="id" size="small" loading={loading} dataSource={rows}
        locale={{ emptyText: '没有举报' }} pagination={{ pageSize: 20 }} scroll={{ x: 1200 }}
        onRow={(r) => ({ onClick: () => setOpen(r.id), style: { cursor: 'pointer' } })}
        columns={[
          { title: '#', dataIndex: 'id', width: 64 },
          { title: '状态', width: 150, render: (_, r) => (
            <Space size={4} wrap>
              <Tag color={STATUS_COLORS[r.status]}>{r.status_label}</Tag>
              {r.escalated && r.status !== 'escalated' && <Tag color="error">多人举报</Tag>}
            </Space>) },
          { title: '被举报', width: 240, render: (_, r) => (
            <Space direction="vertical" size={0}>
              <span>{TARGET_LABELS[r.target_type]}{r.seq_count ? ` · ${r.seq_count} 条消息` : ''}</span>
              {r.subject?.type === 'user' ? <PersonName p={r.subject} />
                : r.subject ? <Muted>会话:{(r.subject as { title?: string }).title}</Muted> : null}
            </Space>) },
          { title: '会话', width: 170, render: (_, r) => (r.chat
            ? <span>{r.chat.type === 'private' ? '私聊' : `${r.chat.type === 'channel' ? '频道' : '群'}「${r.chat.title}」`}<Muted> #{r.chat.id}</Muted></span>
            : '—') },
          { title: '原因', width: 170, render: (_, r) => <span>{r.reason_code} {r.reason_label}</span> },
          { title: '7 天内举报人数', width: 110, dataIndex: 'reporters_7d' },
          { title: '提交', width: 100, render: (_, r) => t(r.created_at) },
          { title: '结果', width: 200, render: (_, r) => r.decision?.resolution ?? '—' },
        ]} />
      {open && <ChatReportDrawer id={open} onClose={() => setOpen(null)}
                                 onDone={() => { setOpen(null); void load() }} />}
    </>
  )
}

function MessageRow({ m }: { m: ChatMessagesView['messages'][number] }) {
  return (
    <div style={{
      padding: '8px 10px', borderRadius: 8, marginBottom: 6,
      border: m.reported ? '2px solid var(--sz-danger, #c0392b)' : '1px solid var(--sz-line, #e5e5e5)',
      background: m.reported ? 'rgba(192, 57, 43, 0.06)' : undefined,
    }}>
      <Space size={6} wrap>
        <Tag>#{m.seq}</Tag>
        {m.as_chat ? <b>以会话名义</b> : <PersonName p={m.sender} />}
        <Muted>{t(m.created_at, 'YYYY-MM-DD HH:mm:ss')}{m.edited_at ? ' · 改过' : ''}</Muted>
        {m.reported && <Tag color="error">被举报</Tag>}
        {m.kind !== 'text' && <Tag>{m.kind}</Tag>}
      </Space>
      {m.deleted ? <div><Muted>这条已被删除</Muted></div> : (
        <>
          {m.text && <Typography.Paragraph style={{ margin: '6px 0 0', whiteSpace: 'pre-wrap' }}>{m.text}</Typography.Paragraph>}
          {m.media.map((x) => (
            <div key={x.id} style={{ marginTop: 6 }}>
              {x.kind === 'photo' || x.kind === 'sticker' ? <Image src={x.url} width={200} />
                : x.kind === 'video' || x.kind === 'gif' || x.kind === 'video_note'
                  ? <video src={x.url} controls preload="metadata" style={{ maxWidth: 360, maxHeight: 240 }} />
                  : x.kind === 'voice' ? <audio src={x.url} controls />
                    : <a href={x.url} target="_blank" rel="noreferrer noopener">{x.name || '文件'}({x.size ?? 0} 字节)</a>}
            </div>
          ))}
          {Object.keys(m.extra || {}).length > 0 && <Muted>{JSON.stringify(m.extra)}</Muted>}
        </>
      )}
    </div>
  )
}

function ChatReportDrawer({ id, onClose, onDone }: { id: number; onClose: () => void; onDone: () => void }) {
  const [d, setD] = useState<ChatReportDetail | null>(null)
  const [view, setView] = useState<ChatMessagesView | null>(null)
  const [form, setForm] = useState<SanctionFormValue>(emptySanction('mute'))
  const [dismissNote, setDismissNote] = useState('')
  const [busy, setBusy] = useState(false)
  const reload = useCallback(() => { chatReport(id).then(setD).catch(fail) }, [id])
  useEffect(() => { reload() }, [reload])

  function askToView() {
    Modal.confirm({
      title: '查看被举报的消息',
      content: (
        <Space direction="vertical">
          <span>只会给你看举报单里那几条和前后各 5 条。</span>
          <span><b>这次查看会被记录</b>(谁、哪张举报单、哪个会话、哪些消息、什么时候),查看次数按月在透明中心公示。</span>
        </Space>),
      okText: '查看', cancelText: '先不看',
      onOk: async () => {
        try { setView(await chatMessages(id)); reload() } catch (e) { fail(e); throw e }
      },
    })
  }

  const r = d?.report
  const handled = r && !['open', 'escalated'].includes(r.status)
  const actions: SanctionFormValue['action'][] = ['mute', 'ban_account', 'warn', 'delete_messages']
  if (d?.candidates.chat) actions.splice(2, 0, 'ban_chat')
  const problem = sanctionProblem(form)

  async function handle() {
    setBusy(true)
    try {
      const out = await handleChatReport(id, {
        action: form.action, reason_code: form.reason_code, note: form.note, note_internal: form.note_internal,
        hours: form.action === 'mute' ? form.hours : undefined,
        days: (form.action === 'ban_account' || form.action === 'ban_chat') && !form.permanent ? form.days : undefined,
        permanent: form.permanent, user_id: form.user_id, also_delete: form.also_delete,
      })
      message.success(out.resolution)
      onDone()
    } catch (e) { fail(e) } finally { setBusy(false) }
  }

  async function dismiss() {
    setBusy(true)
    try {
      await handleChatReport(id, { action: 'dismiss', note: dismissNote })
      message.success('已标为不成立')
      onDone()
    } catch (e) { fail(e) } finally { setBusy(false) }
  }

  return (
    <Drawer open width={860} onClose={onClose} title={`聊天举报 #${id}`}>
      {!d || !r ? <Card loading /> : (
        <Space direction="vertical" size={16} style={{ width: '100%' }}>
          <Descriptions bordered size="small" column={2}>
            <Descriptions.Item label="状态">
              <Tag color={STATUS_COLORS[r.status]}>{r.status_label}</Tag>{r.escalated && <Tag color="error">多人举报</Tag>}
            </Descriptions.Item>
            <Descriptions.Item label="7 天内举报人数">{r.reporters_7d}</Descriptions.Item>
            <Descriptions.Item label="被举报的">{TARGET_LABELS[r.target_type]}{r.seq_count ? `(${r.seq_count} 条消息)` : ''}</Descriptions.Item>
            <Descriptions.Item label="对象">{r.subject?.type === 'user' ? <PersonName p={r.subject} />
              : r.subject ? `会话「${(r.subject as { title?: string }).title}」` : '—'}</Descriptions.Item>
            <Descriptions.Item label="会话">{r.chat ? `${r.chat.type === 'private' ? '私聊' : r.chat.title} #${r.chat.id}` : '—'}</Descriptions.Item>
            <Descriptions.Item label="原因">{r.reason_code} {r.reason_label}</Descriptions.Item>
            <Descriptions.Item label="举报说明" span={2}>{r.note || '—'}</Descriptions.Item>
            {handled && <Descriptions.Item label="处理结果" span={2}>{r.decision?.resolution}(处理于 {t(r.handled_at)})</Descriptions.Item>}
          </Descriptions>

          {d.subject_sanctions.length > 0 && (
            <Card size="small" title="对象身上的处罚">
              <List size="small" dataSource={d.subject_sanctions} renderItem={(s) => (
                <List.Item>{t(s.created_at)} · {s.action_label} · {s.reason_code} · <Tag color={STATUS_COLORS[s.status]}>{SANCTION_STATUS[s.status] ?? s.status}</Tag>{s.until && s.status === 'active' && `到 ${t(s.until)}`}</List.Item>)} />
            </Card>
          )}
          {d.related_open.length > 0 && (
            <Alert type="info" showIcon message={`同一个对象还有 ${d.related_open.length} 张没处理的举报:#${d.related_open.join('、#')}(证据各不相同,各自处理)`} />
          )}

          <Card size="small" title="被举报的消息(S8)" extra={d.can_view_messages && (
            <Button onClick={askToView}>{view ? '再看一次(会再记一次)' : '查看被举报的消息'}</Button>)}>
            {!d.can_view_messages ? <Muted>这张举报单没有指定消息。按 S8 不能查看会话内容,请依据用户资料处置。</Muted>
              : !view ? <Muted>详情里不含任何消息内容。点右上角查看:只给举报单里那几条和前后各 5 条,每次查看都留痕并按月公示次数。</Muted>
                : (
                  <>
                    <Alert type="warning" showIcon style={{ marginBottom: 12 }}
                           message="本次查看已记录并公示次数"
                           description={`${view.audit?.notice ?? ''}(留痕 #${view.audit?.id},${t(view.audit?.at, 'YYYY-MM-DD HH:mm:ss')})。范围:第 ${view.seqs[0] ?? '—'}–${view.seqs[view.seqs.length - 1] ?? '—'} 条,被举报的是 #${view.reported_seqs.join('、#')}`} />
                    {view.messages.length === 0 ? <Empty description="范围里没有消息" />
                      : view.messages.map((m) => <MessageRow key={m.seq} m={m} />)}
                  </>
                )}
          </Card>

          <Card size="small" title={`这张单被看过 ${d.views.length} 次`}>
            <List size="small" dataSource={d.views} locale={{ emptyText: '还没人看过' }} renderItem={(v) => (
              <List.Item>{t(v.at, 'YYYY-MM-DD HH:mm:ss')} · <PersonName p={v.admin} /> · 第 {v.seqs[0] ?? '—'}–{v.seqs[v.seqs.length - 1] ?? '—'} 条({v.seqs.length} 条)</List.Item>)} />
          </Card>

          {!handled && (
            <>
              <Card size="small" title="处置">
                <SanctionForm value={form} onChange={setForm} actions={actions} users={d.candidates.users}
                              allowAlsoDelete={d.can_view_messages} />
                <Button type="primary" danger style={{ marginTop: 12 }} disabled={!!problem} loading={busy} onClick={handle}>
                  执行{problem ? `(${problem})` : ''}
                </Button>
              </Card>
              <Card size="small" title="举报不成立">
                <Space.Compact style={{ width: '100%' }}>
                  <Input placeholder="备注(可选)" value={dismissNote} onChange={(e) => setDismissNote(e.target.value)} />
                  <Button loading={busy} onClick={dismiss}>不成立,结案</Button>
                </Space.Compact>
              </Card>
            </>
          )}
        </Space>
      )}
    </Drawer>
  )
}

// ---------------------------------------------------------------- 视频 / 评论 / 弹幕

function VideoReports() {
  const codes = useReasonCodes()
  const [status, setStatus] = useState('open')
  const [rows, setRows] = useState<VideoReportItem[]>([])
  const [loading, setLoading] = useState(false)
  const [punish, setPunish] = useState<{ report: VideoReportItem; userId: number } | null>(null)
  const load = useCallback(async () => {
    setLoading(true)
    try { setRows((await videoReports(status)).items) } catch (e) { fail(e) } finally { setLoading(false) }
  }, [status])
  useEffect(() => { void load() }, [load])

  function act(r: VideoReportItem, action: 'dismiss' | 'delete' | 'remove') {
    const v = { code: '', note: '' }
    Modal.confirm({
      title: action === 'dismiss' ? '举报不成立' : action === 'remove' ? '下架这个视频' : `删除这条${TARGET_LABELS[r.target_type]}`,
      width: 520,
      content: action === 'dismiss' ? '同一个对象上没处理的举报会一起结案。' : (
        <Space direction="vertical" style={{ width: '100%' }}>
          <Select placeholder="原因代码(必选)" style={{ width: '100%' }} showSearch optionFilterProp="label"
                  options={reasonOptions(codes)} onChange={(x) => { v.code = x }} />
          <Input.TextArea rows={2} placeholder="说明(给当事人看;X999 必须写)" onChange={(e) => { v.note = e.target.value }} />
        </Space>),
      okButtonProps: { danger: action !== 'dismiss' },
      onOk: async () => {
        try {
          const out = await handleVideoReport(r.id, { action, reason_code: v.code, note: v.note })
          message.success(out.resolution)
          void load()
        } catch (e) { fail(e); throw e }
      },
    })
  }

  return (
    <>
      <Space style={{ marginBottom: 12 }}>
        <Radio.Group value={status} onChange={(e) => setStatus(e.target.value)} optionType="button"
          options={[{ value: 'open', label: '待处理' }, { value: 'handled', label: '已处理' }, { value: 'all', label: '全部' }]} />
      </Space>
      <Table<VideoReportItem> rowKey="id" size="small" loading={loading} dataSource={rows}
        locale={{ emptyText: '没有举报' }} pagination={{ pageSize: 20 }} scroll={{ x: 1150 }}
        columns={[
          { title: '#', dataIndex: 'id', width: 64 },
          { title: '状态', width: 110, render: (_, r) => <Tag color={STATUS_COLORS[r.status]}>{VIDEO_REPORT_STATUS[r.status] ?? r.status}</Tag> },
          { title: '被举报', width: 280, render: (_, r) => (
            <Space direction="vertical" size={0}>
              <span><Tag>{TARGET_LABELS[r.target_type]}</Tag>
                {r.target_type === 'video' ? r.video?.title
                  : r.target_type === 'comment' ? r.comment?.text : r.danmaku?.text}
                {(r.comment?.deleted || r.danmaku?.deleted) && <Tag>已删除</Tag>}</span>
              {r.target_type !== 'video' && r.video && <Muted>视频《{r.video.title}》 {r.video.vid}</Muted>}
            </Space>) },
          { title: '原因', width: 170, render: (_, r) => `${r.reason_code} ${r.reason_label}` },
          { title: '举报说明', width: 160, render: (_, r) => r.note || '—' },
          { title: '提交', width: 100, render: (_, r) => t(r.created_at) },
          { title: '', width: 210, render: (_, r) => (['open', 'escalated'].includes(r.status) ? (
            <Space size={4} wrap>
              <a onClick={() => act(r, 'dismiss')}>不成立</a>
              {r.target_type === 'video'
                ? <a style={{ color: 'var(--sz-danger)' }} onClick={() => act(r, 'remove')}>下架</a>
                : <a style={{ color: 'var(--sz-danger)' }} onClick={() => act(r, 'delete')}>删除</a>}
              {r.target_type !== 'video' && (r.comment?.user_id || r.danmaku?.user_id) && (
                <a onClick={() => setPunish({ report: r, userId: (r.comment?.user_id ?? r.danmaku?.user_id)! })}>处罚发的人</a>)}
            </Space>) : <Muted>{r.resolution}</Muted>) },
        ]} />
      {punish && <PunishModal report={punish.report} userId={punish.userId} onClose={() => setPunish(null)} />}
    </>
  )
}

/** 评论 / 弹幕的作者:删掉内容之后再禁言(禁言同时挡发消息、评论、弹幕)或封号 */
function PunishModal({ report, userId, onClose }: { report: VideoReportItem; userId: number; onClose: () => void }) {
  const [form, setForm] = useState<SanctionFormValue>(emptySanction('mute'))
  const [busy, setBusy] = useState(false)
  const problem = sanctionProblem(form)
  return (
    <Modal open width={560} title={`处罚发这条${TARGET_LABELS[report.target_type]}的人 #${userId}`} onCancel={onClose}
      okText={problem ? problem : '执行'} okButtonProps={{ danger: true, disabled: !!problem, loading: busy }}
      onOk={async () => {
        setBusy(true)
        try {
          const a = form.action as 'mute' | 'ban_account' | 'warn'
          await createSanction({
            target_type: 'user', target_id: userId, action: a, reason_code: form.reason_code,
            note: form.note, note_internal: form.note_internal,
            hours: a === 'mute' ? form.hours : undefined,
            days: a === 'ban_account' && !form.permanent ? form.days : undefined,
            permanent: form.permanent, video_report_id: report.id,
          })
          message.success('已处罚,当事人会收到通知')
          onClose()
        } catch (e) { fail(e) } finally { setBusy(false) }
      }}>
      <SanctionForm value={form} onChange={setForm} actions={['mute', 'ban_account', 'warn']} />
    </Modal>
  )
}
