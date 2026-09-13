import { Button, Card, Input, InputNumber, Modal, Radio, Select, Space, Table, Tag, Tooltip, message } from 'antd'
import { useCallback, useEffect, useRef, useState } from 'react'

import { createSanction, listSanctions, revokeSanction, Sanction, SanctionFilter } from '../../api_community'
import {
  ACTION_COLORS, APPEAL_COLORS, Muted, PersonName, SanctionForm, SanctionFormValue, STATUS_COLORS, emptySanction,
  fail, reasonOptions, sanctionProblem, t, useReasonCodes,
} from './shared'

/**
 * 处置记录:对人和会话的全部处罚(删消息、禁言、封群 / 频道、封号、警告),能筛、能撤销。
 *
 * - 撤销立刻解除限制(执行点按查询判,不等缓存),当事人收到通知;
 * - 当事人已经申诉的不能在这里撤:申诉必须由另一名审核员在「申诉」里处理(S6);
 * - 「直接处置」给没有聊天举报单的情况用(比如巡查发现的群);删消息只能走聊天举报单(S8 的范围由举报单定)。
 */
export default function SanctionsPage() {
  const codes = useReasonCodes()
  const [f, setF] = useState<SanctionFilter>({ status: 'active' })
  const [rows, setRows] = useState<Sanction[]>([])
  const [next, setNext] = useState<number | null>(null)
  // 翻页游标放 ref:它只在「加载更多」时读,放进依赖会让筛选一变就多拉一次
  const nextRef = useRef<number | null>(null)
  const [loading, setLoading] = useState(false)
  const [creating, setCreating] = useState(false)

  const load = useCallback(async (more = false) => {
    setLoading(true)
    try {
      const r = await listSanctions({ ...f, before: more ? nextRef.current ?? undefined : undefined })
      setRows(more ? (prev) => [...prev, ...r.items] : r.items)
      nextRef.current = r.next_before
      setNext(r.next_before)
    } catch (e) { fail(e) } finally { setLoading(false) }
  }, [f])
  useEffect(() => { void load(false) }, [load])

  function revoke(s: Sanction) {
    let note = ''
    Modal.confirm({
      title: `撤销 #${s.id}「${s.action_label}」`,
      content: <Input.TextArea rows={2} placeholder="撤销理由(会告诉当事人)" onChange={(e) => { note = e.target.value }} />,
      okText: '撤销',
      onOk: async () => {
        try { await revokeSanction(s.id, note); message.success('已撤销,限制已解除'); void load(false) }
        catch (e) { fail(e); throw e }
      },
    })
  }

  return (
    <Card title="处置记录" extra={<Button onClick={() => setCreating(true)}>直接处置</Button>}>
      <Space wrap style={{ marginBottom: 12 }}>
        <Radio.Group value={f.status} optionType="button" onChange={(e) => setF({ ...f, status: e.target.value })}
          options={[{ value: 'active', label: '生效中' }, { value: 'expired', label: '已到期' },
            { value: 'revoked', label: '已撤销' }, { value: 'done', label: '一次性' }, { value: 'all', label: '全部' }]} />
        <Select allowClear placeholder="种类" style={{ width: 150 }} value={f.action || undefined}
                onChange={(v) => setF({ ...f, action: v })}
                options={[{ value: 'delete_messages', label: '删除消息' }, { value: 'mute', label: '禁言' },
                  { value: 'ban_chat', label: '封禁群 / 频道' }, { value: 'ban_account', label: '封号' }, { value: 'warn', label: '警告' }]} />
        <Select allowClear placeholder="对象" style={{ width: 110 }} value={f.target_type || undefined}
                onChange={(v) => setF({ ...f, target_type: v })}
                options={[{ value: 'user', label: '人' }, { value: 'chat', label: '群 / 频道' }]} />
        <Select allowClear showSearch optionFilterProp="label" placeholder="原因代码" style={{ width: 200 }}
                value={f.reason_code || undefined} onChange={(v) => setF({ ...f, reason_code: v })}
                options={reasonOptions(codes)} />
        <Select allowClear placeholder="申诉" style={{ width: 130 }} value={f.appeal || undefined}
                onChange={(v) => setF({ ...f, appeal: v })}
                options={[{ value: 'none', label: '未申诉' }, { value: 'open', label: '申诉处理中' },
                  { value: 'upheld', label: '维持' }, { value: 'overturned', label: '已撤销' }]} />
        <InputNumber placeholder="对象编号" value={f.target_id} onChange={(v) => setF({ ...f, target_id: v ?? undefined })} />
      </Space>
      <Table<Sanction> rowKey="id" size="small" loading={loading} dataSource={rows} pagination={false}
        scroll={{ x: 1300 }} locale={{ emptyText: '没有记录' }}
        columns={[
          { title: '#', dataIndex: 'id', width: 64 },
          { title: '时间', width: 100, render: (_, s) => t(s.created_at) },
          { title: '对象', width: 230, render: (_, s) => (s.target.type === 'user' ? <PersonName p={s.target} />
            : <span>{(s.target as { type: string; title?: string }).title}<Muted> 群 / 频道 #{s.target.id}</Muted></span>) },
          { title: '处置', width: 170, render: (_, s) => (
            <Space size={4} wrap>
              <Tag color={ACTION_COLORS[s.action]}>{s.action_label}</Tag>
              {s.duration && <Muted>{s.duration}</Muted>}
              {s.seqs.length > 0 && <Muted>{s.seqs.length} 条</Muted>}
            </Space>) },
          { title: '原因', width: 180, render: (_, s) => (
            <Tooltip title={<>{s.note && <div>给当事人:{s.note}</div>}{s.note_internal && <div>内部:{s.note_internal}</div>}</>}>
              <span>{s.reason_code} {s.reason_label}</span>
            </Tooltip>) },
          { title: '状态', width: 150, render: (_, s) => (
            <Space direction="vertical" size={0}>
              <Tag color={STATUS_COLORS[s.status]}>{s.status_label}</Tag>
              {s.until && s.status === 'active' && <Muted>到 {t(s.until)}</Muted>}
              {s.revoked_at && <Muted>{t(s.revoked_at)} {s.revoke_note}</Muted>}
            </Space>) },
          { title: '申诉', width: 150, render: (_, s) => (
            <Tooltip title={s.appeal.text ? `申诉:${s.appeal.text}${s.appeal.note ? ` / 复核:${s.appeal.note}` : ''}` : ''}>
              <Tag color={APPEAL_COLORS[s.appeal.status]}>{s.appeal.status_label}</Tag>
            </Tooltip>) },
          { title: '处理人', width: 150, render: (_, s) => (
            <Space direction="vertical" size={0}>
              <span>{s.admin?.name ?? '—'}{s.you_decided && <Tag style={{ marginLeft: 4 }}>你</Tag>}</span>
              {s.report && <Muted>{s.report.kind === 'chat' ? '聊天举报' : '视频举报'} #{s.report.id}</Muted>}
              {s.carried_from && <Muted>注销前账号 #{s.carried_from}</Muted>}
            </Space>) },
          { title: '', width: 90, fixed: 'right', render: (_, s) => (
            s.revoked_at ? null : s.appeal.status === 'open'
              ? <Tooltip title="当事人已申诉:请在「申诉」里由另一名审核员处理"><Muted>待申诉处理</Muted></Tooltip>
              : <a onClick={() => revoke(s)}>撤销</a>) },
        ]} />
      {next && <Button style={{ marginTop: 12 }} loading={loading} onClick={() => load(true)}>加载更多</Button>}
      {creating && <CreateModal onClose={(ok) => { setCreating(false); if (ok) void load(false) }} />}
    </Card>
  )
}

function CreateModal({ onClose }: { onClose: (ok: boolean) => void }) {
  const [targetType, setTargetType] = useState<'user' | 'chat'>('user')
  const [targetId, setTargetId] = useState<number | null>(null)
  const [form, setForm] = useState<SanctionFormValue>(emptySanction('mute'))
  const [busy, setBusy] = useState(false)
  const problem = !targetId ? '填对象编号' : sanctionProblem(form)
  const actions: SanctionFormValue['action'][] = targetType === 'chat' ? ['ban_chat'] : ['mute', 'ban_account', 'warn']
  return (
    <Modal open width={600} title="直接处置" onCancel={() => onClose(false)}
      okText={problem ?? '执行'} okButtonProps={{ danger: true, disabled: !!problem, loading: busy }}
      onOk={async () => {
        setBusy(true)
        try {
          const a = form.action as 'mute' | 'ban_chat' | 'ban_account' | 'warn'
          await createSanction({
            target_type: targetType, target_id: targetId!, action: a, reason_code: form.reason_code,
            note: form.note, note_internal: form.note_internal,
            hours: a === 'mute' ? form.hours : undefined,
            days: (a === 'ban_account' || a === 'ban_chat') && !form.permanent ? form.days : undefined,
            permanent: form.permanent,
          })
          message.success('已处置,当事人会收到通知')
          onClose(true)
        } catch (e) { fail(e) } finally { setBusy(false) }
      }}>
      <Space direction="vertical" style={{ width: '100%' }}>
        <Space>
          <Radio.Group value={targetType} optionType="button" onChange={(e) => {
            const v = e.target.value as 'user' | 'chat'
            setTargetType(v); setForm(emptySanction(v === 'chat' ? 'ban_chat' : 'mute'))
          }} options={[{ value: 'user', label: '人' }, { value: 'chat', label: '群 / 频道' }]} />
          <InputNumber placeholder={targetType === 'user' ? '用户编号' : '会话编号'} value={targetId}
                       onChange={(v) => setTargetId(v ?? null)} style={{ width: 160 }} />
        </Space>
        <SanctionForm value={form} onChange={setForm} actions={actions} />
        <Muted>删消息只能走聊天举报单(管理员看消息的范围由举报单定,S8)。</Muted>
      </Space>
    </Modal>
  )
}
