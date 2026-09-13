import { Alert, Card, Input, List, Modal, Radio, Space, Tabs, Tag, Typography, message } from 'antd'
import { useCallback, useEffect, useState } from 'react'

import {
  resolveSocialAppeal, resolveVideoAppeal, SocialAppealItem, socialAppeals, VideoAppealItem, videoAppeals,
} from '../../api_community'
import { ACTION_COLORS, APPEAL_COLORS, Muted, PersonName, fail, t } from './shared'

/**
 * 申诉(S6):视频驳回 / 下架的申诉 + 对人和会话的处罚的申诉。
 *
 * **必须换人**:原结论 / 原处罚是你作出的,这里不给按钮(接口也会 403)。
 * 撤销 = 真的撤:视频回到原来的状态、处罚立刻解除;当事人收到「申诉结果」。
 */
export default function AppealsPage() {
  return (
    <Card title="申诉">
      <Alert type="info" showIcon style={{ marginBottom: 12 }}
             message="申诉必须由另一名审核员处理:你自己作出的结论或处罚,这里没有处理按钮,接口也会拒绝。" />
      <Tabs items={[
        { key: 'social', label: '社区申诉(禁言 / 封号 / 封群 / 删消息)', children: <SocialAppeals /> },
        { key: 'video', label: '视频申诉(驳回 / 下架)', children: <VideoAppeals /> },
      ]} />
    </Card>
  )
}

function ask(title: string, overturn: boolean, onOk: (note: string, internal: string) => Promise<void>) {
  let note = ''
  let internal = ''
  Modal.confirm({
    title,
    width: 520,
    content: (
      <Space direction="vertical" style={{ width: '100%' }}>
        {overturn && <Alert type="warning" message="撤销后立刻生效:限制解除 / 视频恢复,当事人收到通知。" />}
        <Input.TextArea rows={2} placeholder="复核结论(给当事人看,必填)" onChange={(e) => { note = e.target.value }} />
        <Input.TextArea rows={2} placeholder="内部备注(只在后台看得到)" onChange={(e) => { internal = e.target.value }} />
      </Space>),
    okButtonProps: { danger: overturn },
    onOk: async () => {
      try { await onOk(note, internal) } catch (e) { fail(e); throw e }
    },
  })
}

function SocialAppeals() {
  const [status, setStatus] = useState<'open' | 'resolved' | 'all'>('open')
  const [rows, setRows] = useState<SocialAppealItem[]>([])
  const load = useCallback(() => { socialAppeals(status).then((r) => setRows(r.items)).catch(fail) }, [status])
  useEffect(() => { load() }, [load])

  return (
    <>
      <Radio.Group value={status} onChange={(e) => setStatus(e.target.value)} optionType="button" style={{ marginBottom: 12 }}
        options={[{ value: 'open', label: '待处理' }, { value: 'resolved', label: '已处理' }, { value: 'all', label: '全部' }]} />
      <List dataSource={rows} locale={{ emptyText: '没有申诉' }} renderItem={(a) => {
        const s = a.sanction
        const open = a.appeal.status === 'open'
        const actions = !open ? [<Tag key="r" color={APPEAL_COLORS[s.appeal.status]}>{s.appeal.status_label}</Tag>]
          : a.you_decided_original
            ? [<Typography.Text key="x" type="secondary">原处罚是你作出的,须由另一名审核员处理</Typography.Text>]
            : [
              <a key="o" onClick={() => ask(`申诉成立:撤销 #${s.id}「${s.action_label}」`, true, async (note, internal) => {
                await resolveSocialAppeal(a.appeal.id, { overturn: true, note, note_internal: internal })
                message.success('已撤销,限制已解除'); load()
              })}>申诉成立(撤销)</a>,
              <a key="u" onClick={() => ask(`维持 #${s.id}「${s.action_label}」`, false, async (note, internal) => {
                await resolveSocialAppeal(a.appeal.id, { overturn: false, note, note_internal: internal })
                message.success('已维持'); load()
              })}>维持</a>,
            ]
        return (
          <List.Item actions={actions}>
            <List.Item.Meta
              title={<Space wrap>
                <Tag color={ACTION_COLORS[s.action]}>{s.action_label}</Tag>
                {s.target.type === 'user' ? <PersonName p={s.target} />
                  : <span>群 / 频道「{(s.target as { title?: string }).title}」</span>}
                {s.duration && <Muted>{s.duration}</Muted>}
                <Tag>{s.reason_code} {s.reason_label}</Tag>
              </Space>}
              description={<Space direction="vertical" size={2}>
                <span>申诉({t(a.appeal.appealed_at)}):{a.appeal.text}</span>
                <Muted>原处罚:{t(s.created_at)} by {s.admin?.name ?? '—'};给当事人的说明「{s.note || '—'}」
                  {s.note_internal && `;内部备注「${s.note_internal}」`}
                  {s.report && `;来源 ${s.report.kind === 'chat' ? '聊天举报' : '视频举报'} #${s.report.id}`}</Muted>
                {!open && <Muted>复核:{s.appeal.note}(by {s.appeal.admin?.name ?? '—'},{t(s.appeal.resolved_at)})</Muted>}
              </Space>} />
          </List.Item>
        )
      }} />
    </>
  )
}

function VideoAppeals() {
  const [rows, setRows] = useState<VideoAppealItem[]>([])
  const load = useCallback(() => { videoAppeals().then((r) => setRows(r.items)).catch(fail) }, [])
  useEffect(() => { load() }, [load])
  return (
    <List dataSource={rows} locale={{ emptyText: '没有待处理的视频申诉' }} renderItem={(a) => (
      <List.Item actions={a.you_decided_original
        ? [<Typography.Text key="x" type="secondary">原结论是你作出的,须由另一名审核员处理</Typography.Text>]
        : [
          <a key="o" onClick={() => ask(`申诉成立:撤销「${a.original.action_label}」`, true, async (note, internal) => {
            await resolveVideoAppeal(a.appeal.id, { overturn: true, note, note_internal: internal })
            message.success('已撤销原结论'); load()
          })}>申诉成立</a>,
          <a key="u" onClick={() => ask(`维持「${a.original.action_label}」`, false, async (note, internal) => {
            await resolveVideoAppeal(a.appeal.id, { overturn: false, note, note_internal: internal })
            message.success('已维持'); load()
          })}>维持</a>,
        ]}>
        <List.Item.Meta
          avatar={a.video.cover ? <img src={a.video.cover} alt="" style={{ width: 80, height: 45, objectFit: 'cover', borderRadius: 4 }} /> : null}
          title={<Space>《{a.video.title}》<Muted>{a.video.vid} · {a.video.status}</Muted></Space>}
          description={<Space direction="vertical" size={2}>
            <span>申诉({t(a.appeal.created_at)}):{a.appeal.text}</span>
            <Muted>原结论:{a.original.action_label} {a.original.reason_code} {a.original.reason_label}
              「{a.original.note || '—'}」{a.original.note_internal && `(内部:${a.original.note_internal})`},{t(a.original.created_at)}</Muted>
          </Space>} />
      </List.Item>)} />
  )
}
