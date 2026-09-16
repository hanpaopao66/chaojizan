import { Select, Space, Tag, Typography } from 'antd'
import { type ReactNode, useEffect, useState } from 'react'

import { ForumPostBrief, ReasonCode, forumReasonCodes } from '../../api_forum'
import { Muted, PersonName, fail, t } from '../community/shared'

/**
 * 论坛几页共用的小件:原因代码表、帖子摘要、状态标签。
 *
 * 规矩都在服务端(docs/FORUM-API.md §8、§9):下架和隐藏话题必须选原因代码、X999 要写说明、
 * 申诉换人。这里只是把它们提前说清楚,少让人撞一次 422。
 */

export { Muted, PersonName, fail, t }

let cached: ReasonCode[] | null = null

/** 论坛的原因代码:共用的 C1xx + X999,加 F401–F403(§5.11)。整个会话只取一次 */
export function useForumReasonCodes(): ReasonCode[] {
  const [codes, setCodes] = useState<ReasonCode[]>(cached ?? [])
  useEffect(() => {
    if (cached) return
    forumReasonCodes().then((r) => { cached = r.items; setCodes(r.items) }).catch(fail)
  }, [])
  return codes
}

export const reasonOptions = (codes: ReasonCode[]) =>
  codes.map((c) => ({ value: c.code, label: `${c.code} ${c.label}` }))

/** 表单能不能提交(和服务端同一套规矩,提前说) */
export function reasonProblem(code: string, note: string): string | null {
  if (!code) return '先选原因代码'
  if (code === 'X999' && note.trim().length < 5) return '选「X999 其他」要写明原因(至少 5 个字)'
  return null
}

export function ReasonPicker({ code, note, onCode, children }: {
  code: string
  note: string
  onCode: (c: string) => void
  children?: ReactNode
}) {
  const codes = useForumReasonCodes()
  return (
    <Space direction="vertical" style={{ width: '100%' }}>
      <Select style={{ width: '100%' }} placeholder="原因代码(必选,§5.11)" showSearch
              optionFilterProp="label" value={code || undefined} onChange={onCode}
              options={reasonOptions(codes)} />
      {children}
      {reasonProblem(code, note) && <Muted>{reasonProblem(code, note)}</Muted>}
    </Space>
  )
}

export const POST_STATUS: Record<string, { label: string; color: string }> = {
  visible: { label: '正常', color: 'green' },
  removed: { label: '已下架', color: 'red' },
  deleted: { label: '作者已删', color: 'default' },
}

export const REPORT_STATUS: Record<string, { label: string; color: string }> = {
  open: { label: '待处理', color: 'processing' },
  actioned: { label: '已处置', color: 'success' },
  dismissed: { label: '不成立', color: 'default' },
}

export const APPEAL_RESULT: Record<string, { label: string; color: string }> = {
  open: { label: '待复核', color: 'processing' },
  upheld: { label: '维持原处理', color: 'default' },
  overturned: { label: '改判恢复', color: 'green' },
}

/** 列表里的帖子摘要:正文一行、作者、状态、计数。点链接去线上那一条 */
export function PostCell({ p }: { p: ForumPostBrief | null }) {
  if (!p) return <span>—</span>
  return (
    <Space direction="vertical" size={0} style={{ maxWidth: 420 }}>
      <Typography.Paragraph style={{ margin: 0 }} ellipsis={{ rows: 2, tooltip: p.text }}>
        {p.text || <Muted>(没有正文:只有图片、卡片或投票)</Muted>}
      </Typography.Paragraph>
      <Space size={4} wrap>
        <Tag color={POST_STATUS[p.status]?.color}>{POST_STATUS[p.status]?.label ?? p.status}</Tag>
        {p.is_reply && <Tag>回复</Tag>}
        {p.media.length > 0 && <Tag>{p.media.length} 张图</Tag>}
        {p.removed_code && <Muted>{p.removed_code} {p.removed_label}</Muted>}
      </Space>
      <Space size={8} wrap>
        <PersonName p={p.author} />
        <Muted>
          赞 {p.counts.likes} · 回复 {p.counts.replies} · 转发 {p.counts.reposts} · 浏览 {p.counts.views}
        </Muted>
      </Space>
      <a href={p.link} target="_blank" rel="noreferrer"><Muted>{p.pid}</Muted></a>
    </Space>
  )
}
