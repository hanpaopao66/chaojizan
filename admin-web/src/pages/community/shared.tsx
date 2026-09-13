import { Checkbox, Input, InputNumber, Radio, Select, Space, Tag, Typography, message } from 'antd'
import dayjs from 'dayjs'
import { type ReactNode, useEffect, useState } from 'react'

import { ApiError } from '../../api'
import { ReasonCode, reasonCodes } from '../../api_community'

/**
 * 社区治理几页共用的小件:原因代码表、时间、标签、处罚表单。
 *
 * 规矩都在服务端(COMMUNITY-GOVERNANCE.md):处罚必须选 §5.11 的原因代码、X999 要写说明、
 * 禁言只能限时、申诉换人。这里的表单只是把它们提前说清楚,少让人撞一次 422。
 */

export const fail = (e: unknown) => message.error(e instanceof ApiError ? e.message : String(e))

/** 服务端给的是 UTC ISO,后台按本机时区显示 */
export const t = (s?: string | null, f = 'MM-DD HH:mm') => (s ? dayjs(s).format(f) : '—')

let cached: ReasonCode[] | null = null

/** §5.11 原因代码(审核、处罚、举报共用一张表),整个会话只取一次 */
export function useReasonCodes(): ReasonCode[] {
  const [codes, setCodes] = useState<ReasonCode[]>(cached ?? [])
  useEffect(() => {
    if (cached) return
    reasonCodes().then((r) => { cached = r.items; setCodes(r.items) }).catch(fail)
  }, [])
  return codes
}

export const reasonOptions = (codes: ReasonCode[], only?: (c: string) => boolean) =>
  codes.filter((c) => !only || only(c.code)).map((c) => ({ value: c.code, label: `${c.code} ${c.label}` }))

export const ACTION_COLORS: Record<string, string> = {
  delete_messages: 'default', warn: 'gold', mute: 'orange', ban_chat: 'volcano', ban_account: 'red',
}

export const STATUS_COLORS: Record<string, string> = {
  active: 'red', expired: 'default', revoked: 'green', done: 'default',
  open: 'processing', escalated: 'error', actioned: 'success', dismissed: 'default',
}

export const APPEAL_COLORS: Record<string, string> = {
  '': 'default', open: 'processing', upheld: 'default', overturned: 'green',
}

export function Muted({ children }: { children: ReactNode }) {
  return <Typography.Text type="secondary" style={{ fontSize: 12 }}>{children}</Typography.Text>
}

export function PersonName({ p }: { p?: { id?: number; name?: string; username?: string | null; deleted?: boolean } | null }) {
  if (!p) return <span>—</span>
  return (
    <span>
      {p.name ?? `用户 ${p.id}`}
      {p.username && <Muted> @{p.username}</Muted>}
      {p.deleted && <Tag style={{ marginLeft: 4 }}>已注销</Tag>}
      <Muted> #{p.id}</Muted>
    </span>
  )
}

// ---------------------------------------------------------------- 处罚表单

export type SanctionKind = 'delete_messages' | 'mute' | 'ban_chat' | 'ban_account' | 'warn'

export const KIND_LABELS: Record<SanctionKind, string> = {
  delete_messages: '删除被举报的消息', mute: '禁言', ban_chat: '封禁群 / 频道', ban_account: '封号', warn: '警告',
}

export interface SanctionFormValue {
  action: SanctionKind
  reason_code: string
  note: string
  note_internal: string
  hours: number
  days: number
  permanent: boolean
  user_id?: number
  also_delete: boolean
}

export const emptySanction = (action: SanctionKind = 'mute'): SanctionFormValue => ({
  action, reason_code: '', note: '', note_internal: '', hours: 24, days: 7, permanent: false,
  also_delete: false,
})

/** 表单能不能提交(和服务端同一套规矩,提前说) */
export function sanctionProblem(v: SanctionFormValue): string | null {
  if (!v.reason_code) return '先选原因代码'
  if (v.reason_code === 'X999' && v.note.trim().length < 5) return '选「X999 其他」要写明原因(至少 5 个字)'
  if (v.action === 'mute' && !(v.hours >= 1 && v.hours <= 720)) return '禁言时长 1–720 小时'
  if ((v.action === 'ban_account' || v.action === 'ban_chat') && !v.permanent
      && !(v.days >= 1 && v.days <= 3650)) return '封禁天数 1–3650 天,或者选永久'
  return null
}

export function SanctionForm({
  value, onChange, actions, users, allowAlsoDelete,
}: {
  value: SanctionFormValue
  onChange: (v: SanctionFormValue) => void
  actions: SanctionKind[]
  /** 能处罚的人(聊天举报:被举报的人、被举报消息的发送人、群主) */
  users?: { id: number; name: string; username?: string | null }[]
  allowAlsoDelete?: boolean
}) {
  const codes = useReasonCodes()
  const set = (p: Partial<SanctionFormValue>) => onChange({ ...value, ...p })
  const onPerson = value.action === 'mute' || value.action === 'ban_account' || value.action === 'warn'
  return (
    <Space direction="vertical" style={{ width: '100%' }}>
      <Radio.Group value={value.action} optionType="button" buttonStyle="solid"
                   onChange={(e) => set({ action: e.target.value })}
                   options={actions.map((a) => ({ value: a, label: KIND_LABELS[a] }))} />
      {onPerson && users && users.length > 0 && (
        <Select style={{ width: '100%' }} placeholder="处罚谁(默认是被举报的人)" allowClear
                value={value.user_id} onChange={(x) => set({ user_id: x })}
                options={users.map((u) => ({
                  value: u.id, label: `${u.name}${u.username ? ` @${u.username}` : ''} #${u.id}`,
                }))} />
      )}
      {value.action === 'mute' && (
        <InputNumber min={1} max={720} value={value.hours} addonBefore="禁言" addonAfter="小时"
                     onChange={(x) => set({ hours: Number(x) || 0 })} />
      )}
      {(value.action === 'ban_account' || value.action === 'ban_chat') && (
        <Space>
          <InputNumber min={1} max={3650} value={value.days} disabled={value.permanent}
                       addonBefore="封禁" addonAfter="天" onChange={(x) => set({ days: Number(x) || 0 })} />
          <Checkbox checked={value.permanent} onChange={(e) => set({ permanent: e.target.checked })}>永久</Checkbox>
        </Space>
      )}
      <Select style={{ width: '100%' }} placeholder="原因代码(必选,§5.11)" showSearch optionFilterProp="label"
              value={value.reason_code || undefined} onChange={(x) => set({ reason_code: x })}
              options={reasonOptions(codes)} />
      <Input.TextArea rows={2} maxLength={500} showCount placeholder="给当事人看的说明(系统通知、处罚记录、被挡时的提示里都有)"
                      value={value.note} onChange={(e) => set({ note: e.target.value })} />
      <Input.TextArea rows={2} maxLength={500} placeholder="内部备注(只在后台看得到,不进透明中心)"
                      value={value.note_internal} onChange={(e) => set({ note_internal: e.target.value })} />
      {allowAlsoDelete && value.action !== 'delete_messages' && (
        <Checkbox checked={value.also_delete} onChange={(e) => set({ also_delete: e.target.checked })}>
          同时删掉被举报的消息
        </Checkbox>
      )}
      <Muted>当事人会收到系统通知,可以申诉一次;申诉由另一名审核员处理,你处理不了自己作出的处罚的申诉。</Muted>
    </Space>
  )
}
