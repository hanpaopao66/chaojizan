/**
 * 论坛治理的后台接口:`/admin/forum/…`(DEV-PROMPTS-41 #380 §8.3 后台部分)。
 *
 * 形状对着 docs/FORUM-API.md §9 写 —— 字段名猜错的话页面上就是一片空白,而且不报错。
 *
 * 单独一个文件而不是塞进 api_community.ts:那份是消息和视频的,论坛是另一个模块,
 * 而且音乐后端并行在加它自己的一份;分开放合并时不用解冲突。
 */
import { get, post } from './api'
import type { PersonBrief } from './api_community'

export interface ReasonCode { code: string; label: string }
export const forumReasonCodes = () => get<{ items: ReasonCode[] }>('/admin/forum/reason-codes')

/** 后台列表里的帖子简卡(正文、作者、状态、计数、链接) */
export interface ForumPostBrief {
  pid: string
  text: string
  author: PersonBrief | null
  status: 'visible' | 'removed' | 'deleted'
  removed_code: string
  removed_label: string
  media: string[]
  is_reply: boolean
  counts: { replies: number; reposts: number; quotes: number; likes: number; views: number }
  created_at: string | null
  link: string
  /** 只有 /admin/forum/posts 带 */
  reports_open?: number
}

// ---------- 举报 ----------

export interface ForumReportItem {
  id: number
  reason_code: string
  reason_label: string
  /** 举报人写的说明(**不带举报人是谁** —— 举报人对被举报的一方永远匿名) */
  note: string
  status: 'open' | 'actioned' | 'dismissed'
  resolution: string
  created_at: string | null
  handled_at: string | null
  post: ForumPostBrief | null
}

export const forumReports = (status: 'open' | 'handled' | 'all') =>
  get<{ items: ForumReportItem[] }>(`/admin/forum/reports?status=${status}&limit=300`)

export const handleForumReport = (id: number, body: {
  action: 'remove' | 'dismiss'; reason_code?: string; note?: string; note_internal?: string
}) => post<{ id: number; status: string; resolution: string }>(
  `/admin/forum/reports/${id}/handle`, body)

// ---------- 帖子管理 ----------

export interface PostQuery {
  q?: string
  author?: number
  status?: 'visible' | 'removed' | 'deleted' | 'all'
}

export const forumPosts = (f: PostQuery = {}) => {
  const qs = Object.entries(f)
    .filter(([, v]) => v !== undefined && v !== '' && v !== null)
    .map(([k, v]) => `${k}=${encodeURIComponent(String(v))}`)
    .join('&')
  return get<{ items: ForumPostBrief[] }>(`/admin/forum/posts?limit=200${qs ? `&${qs}` : ''}`)
}

export const removeForumPost = (pid: string, body: {
  reason_code: string; note: string; note_internal?: string
}) => post<{ decision_id: number; status: string }>(`/admin/forum/posts/${pid}/remove`, body)

export const restoreForumPost = (pid: string, note = '') =>
  post<{ decision_id: number; status: string }>(`/admin/forum/posts/${pid}/restore`, { note })

// ---------- 申诉 ----------

export interface ForumAppealItem {
  decision_id: number
  appeal: { text: string; at: string | null; result: string; note: string }
  original: {
    action: string
    reason_code: string
    reason_label: string
    note: string
    note_internal: string
    admin_id: number | null
    created_at: string | null
  }
  post: ForumPostBrief | null
  /** 为真的**你不能处理** —— 换人复核,服务端也会 403 */
  you_decided_original: boolean
}

export const forumAppeals = (status: 'open' | 'resolved' | 'all') =>
  get<{ items: ForumAppealItem[] }>(`/admin/forum/appeals?status=${status}`)

export const resolveForumAppeal = (decisionId: number, body: {
  result: 'upheld' | 'overturned'; note: string
}) => post<{ decision_id: number; result: string; status: string | null }>(
  `/admin/forum/appeals/${decisionId}/resolve`, body)

// ---------- 热门话题 ----------

export interface ForumTagItem {
  tag: string
  display: string
  posts: number
  hidden: boolean
  hidden_code: string
  hidden_label: string
  last_used_at: string | null
}

export const forumTags = (f: { hidden?: boolean; q?: string } = {}) => {
  const qs = Object.entries(f)
    .filter(([, v]) => v !== undefined && v !== '' && v !== null)
    .map(([k, v]) => `${k}=${encodeURIComponent(String(v))}`)
    .join('&')
  return get<{ items: ForumTagItem[] }>(`/admin/forum/tags?limit=300${qs ? `&${qs}` : ''}`)
}

/** 隐藏只是不上热门榜:话题页照样能打开、帖子照样在,而且**必须写原因**(§2.2 不偷偷压话题) */
export const hideForumTag = (tag: string, body: { reason_code: string; note: string }) =>
  post<{ decision_id: number; tag: string; hidden: boolean }>(
    `/admin/forum/tags/${encodeURIComponent(tag)}/hide`, body)

export const unhideForumTag = (tag: string) =>
  post<{ decision_id: number; tag: string; hidden: boolean }>(
    `/admin/forum/tags/${encodeURIComponent(tag)}/unhide`)

// ---------- 数据 ----------

export interface ForumStats {
  posts_7d: number
  removed_7d: number
  visible_total: number
  reports_open: number
  appeals_open: number
  tags_hidden: number
  tags_total: number
}

export const forumStats = () => get<ForumStats>('/admin/forum/stats')
