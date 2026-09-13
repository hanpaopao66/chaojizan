/**
 * 社区治理(消息 / 视频)的后台接口:`/admin/social/…`。
 *
 * 形状对着 docs/COMMUNITY-GOVERNANCE.md §4.3(对人和会话的处罚、聊天举报、社区申诉、数据)
 * 和 docs/VIDEO-API.md §11(视频审核、视频 / 评论 / 弹幕举报、视频申诉)写 —— 字段名猜错的话
 * 页面上就是一片空白,而且不报错。
 *
 * 单独一个文件而不是塞进 api.ts:这一块接口多、类型多,和商家骑手那些互不相干。
 */
import { get, post } from './api'

// ---------- 通用 ----------

export interface ReasonCode { code: string; label: string }
export const reasonCodes = () => get<{ items: ReasonCode[] }>('/admin/social/reason-codes')

export interface PersonBrief {
  id: number
  name: string
  username: string | null
  deleted?: boolean
  role?: string
  created_at?: string | null
  avatar?: string
}

export interface ChatBrief {
  id: number
  type: 'private' | 'group' | 'channel' | 'saved'
  title: string
  username: string | null
  member_count: number
  owner_id: number | null
  deleted: boolean
}

// ---------- 视频审核 ----------

export interface Rendition { q: number; w: number; h: number; size: number; bitrate: number; url: string }

export interface VideoPartOut {
  id: number
  idx: number
  title: string
  status: string
  duration_ms: number
  w: number
  h: number
  renditions: Rendition[]
  live?: boolean
  error?: string
}

export interface VideoDecisionOut {
  id: number
  action: string
  action_label: string
  reason_code: string
  reason_label: string
  note: string
  note_internal?: string
  actor_id?: number | null
  created_at: string | null
}

export interface PendingOut {
  state: string
  state_label: string
  fields: Record<string, unknown>
  parts: { id: number; title?: string }[] | null
  submitted_at: string | null
  reject_code: string
  reject_label: string
  reject_note: string
  cover_preview?: string | null
}

export interface VideoCard {
  vid: string
  title: string
  cover: string
  duration_ms: number
  is_vertical: boolean
  zone: string
  zone_name: string
  tags: string[]
  status: string
  status_label: string
  submitted_at: string | null
  pending: PendingOut | null
  review?: 'first' | 'changes' | null
  uploader?: PersonBrief | null
}

export interface VideoAdminDetail extends VideoCard {
  description: string
  copyright: 'original' | 'repost'
  source_url: string
  visibility: string
  allow_danmaku: boolean
  allow_comments: boolean
  shop: { id: number; name: string } | null
  shop_collab: boolean | null
  cover_preview: string | null
  link: string
  parts: VideoPartOut[]
  version_part_ids: number[]
  decisions: VideoDecisionOut[]
  reports_open: number
}

export const videoQueue = () =>
  get<{ items: VideoCard[]; count: number }>('/admin/social/videos/review?limit=200')
export const videoDetail = (vid: string) => get<VideoAdminDetail>(`/admin/social/videos/${vid}`)
export const decideVideo = (vid: string, body: {
  approve: boolean; reason_code?: string; note?: string; note_internal?: string
}) => post<{ decision_id: number; action: string; status: string }>(
  `/admin/social/videos/${vid}/decide`, body)
export const removeVideo = (vid: string, body: {
  reason_code: string; note: string; note_internal?: string
}) => post<{ decision_id: number; status: string }>(`/admin/social/videos/${vid}/remove`, body)

export interface VideosStats {
  reviewing: number
  approved_7d: number
  rejected_7d: number
  removed_7d: number
  reject_rate_7d: number
  appeals_open: number
  reports_open: number
}
export const videosStats = () => get<VideosStats>('/admin/social/videos-stats')

export interface VideoAppealItem {
  appeal: { id: number; text: string; created_at: string | null }
  original: VideoDecisionOut
  video: { vid: string; title: string; cover: string; status: string }
  you_decided_original: boolean
}
export const videoAppeals = () => get<{ items: VideoAppealItem[] }>('/admin/social/appeals')
export const resolveVideoAppeal = (id: number, body: {
  overturn: boolean; note: string; note_internal?: string
}) => post(`/admin/social/appeals/${id}/resolve`, body)

export interface VideoReportItem {
  id: number
  target_type: 'video' | 'comment' | 'danmaku'
  target_id: number
  reason_code: string
  reason_label: string
  note: string
  status: 'open' | 'escalated' | 'actioned' | 'dismissed'
  resolution: string
  created_at: string | null
  video?: { vid: string; title: string; cover: string; status?: string } | null
  comment?: { id: number; text: string; user_id: number; deleted: boolean } | null
  danmaku?: { id: number; text: string; user_id: number; time_ms: number; deleted: boolean } | null
}
export const videoReports = (status: string) =>
  get<{ items: VideoReportItem[] }>(`/admin/social/video-reports?status=${status}&limit=300`)
export const handleVideoReport = (id: number, body: {
  action: 'dismiss' | 'delete' | 'remove'; reason_code?: string; note?: string
}) => post<{ id: number; status: string; resolution: string }>(
  `/admin/social/video-reports/${id}/handle`, body)

// ---------- 聊天举报(S8)----------

export interface ChatReportItem {
  id: number
  target_type: 'chat' | 'message' | 'user'
  status: 'open' | 'escalated' | 'actioned' | 'dismissed'
  status_label: string
  escalated: boolean
  reason_code: string
  reason_label: string
  /** 举报人写的说明(不带举报人是谁) */
  note: string
  chat: ChatBrief | null
  subject: ({ type: 'user' } & Partial<PersonBrief>) | ({ type: 'chat' } & Partial<ChatBrief>) | null
  seq_count: number
  reporters_7d: number
  created_at: string | null
  handled_at: string | null
  handled_by: number | null
  decision: { action?: string; resolution?: string; sanction_ids?: number[] }
}

export interface ChatReportDetail {
  report: ChatReportItem
  subject_sanctions: { id: number; action: string; action_label: string; reason_code: string;
                       status: string; until: string | null; created_at: string | null }[]
  related_open: number[]
  views: { id: number; admin: PersonBrief; chat_id: number; seqs: number[]; at: string | null }[]
  can_view_messages: boolean
  messages_path: string | null
  candidates: { users: PersonBrief[]; chat: ChatBrief | null }
}

export interface ViewedMedia {
  id: number
  kind: string
  name: string
  size: number | null
  w: number | null
  h: number | null
  duration_ms: number | null
  mime: string | null
  url: string
  thumb: string | null
}

export interface ViewedMessage {
  seq: number
  sender: PersonBrief | null
  as_chat: boolean
  kind: string
  text: string
  media: ViewedMedia[]
  extra: Record<string, unknown>
  reply_to_seq: number | null
  created_at: string | null
  edited_at: string | null
  deleted: boolean
  reported: boolean
}

export interface ChatMessagesView {
  report_id: number
  chat: ChatBrief | null
  reported_seqs: number[]
  seqs: number[]
  messages: ViewedMessage[]
  audit: { id: number; at: string | null; notice: string } | null
  note?: string
}

export const chatReports = (status: string) =>
  get<{ items: ChatReportItem[]; count: number }>(`/admin/social/chat-reports?status=${status}&limit=300`)
export const chatReport = (id: number) => get<ChatReportDetail>(`/admin/social/chat-reports/${id}`)
/** S8:看被举报的消息。**必须带举报单号**,每次调用都在服务端留痕、按月公示次数 */
export const chatMessages = (reportId: number) =>
  get<ChatMessagesView>(`/admin/social/chat-messages?report_id=${reportId}`)

export type HandleAction = 'dismiss' | 'delete_messages' | 'mute' | 'ban_chat' | 'ban_account' | 'warn'
export interface HandleBody {
  action: HandleAction
  reason_code?: string
  note?: string
  note_internal?: string
  hours?: number
  days?: number
  permanent?: boolean
  user_id?: number
  also_delete?: boolean
}
export const handleChatReport = (id: number, body: HandleBody) =>
  post<{ id: number; status: string; resolution: string; sanction_ids: number[] }>(
    `/admin/social/chat-reports/${id}/handle`, body)

// ---------- 处罚记录 ----------

export interface SanctionAppeal {
  status: '' | 'open' | 'upheld' | 'overturned'
  status_label: string
  text: string
  appealed_at: string | null
  note: string
  note_internal: string
  admin: PersonBrief | null
  resolved_at: string | null
}

export interface Sanction {
  id: number
  target_type: 'user' | 'chat'
  target: ({ type: 'user' } & Partial<PersonBrief>) | ({ type: 'chat' } & Partial<ChatBrief>)
  action: 'delete_messages' | 'mute' | 'ban_chat' | 'ban_account' | 'warn'
  action_label: string
  reason_code: string
  reason_label: string
  note: string
  note_internal: string
  until: string | null
  permanent: boolean
  duration: string
  status: 'active' | 'expired' | 'revoked' | 'done'
  status_label: string
  chat: ChatBrief | null
  seqs: number[]
  admin: PersonBrief | null
  report: { kind: string; id: number | null } | null
  revoked_at: string | null
  revoked_by: PersonBrief | null
  revoke_note: string
  appeal: SanctionAppeal
  carried_from: number | null
  created_at: string | null
  you_decided: boolean
}

export interface SanctionFilter {
  status?: string
  action?: string
  target_type?: string
  reason_code?: string
  appeal?: string
  target_id?: number
  before?: number
}

export const listSanctions = (f: SanctionFilter = {}) => {
  const qs = Object.entries(f)
    .filter(([, v]) => v !== undefined && v !== '' && v !== null)
    .map(([k, v]) => `${k}=${encodeURIComponent(String(v))}`)
    .join('&')
  return get<{ items: Sanction[]; next_before: number | null }>(
    `/admin/social/sanctions?limit=50${qs ? `&${qs}` : ''}`)
}

export interface SanctionBody {
  target_type: 'user' | 'chat'
  target_id: number
  action: 'mute' | 'ban_chat' | 'ban_account' | 'warn'
  reason_code: string
  note?: string
  note_internal?: string
  hours?: number
  days?: number
  permanent?: boolean
  video_report_id?: number
}
export const createSanction = (body: SanctionBody) => post<Sanction>('/admin/social/sanctions', body)
export const revokeSanction = (id: number, note: string) =>
  post<Sanction>(`/admin/social/sanctions/${id}/revoke`, { note })

// ---------- 社区申诉 ----------

export interface SocialAppealItem {
  appeal: { id: number; status: string; text: string; appealed_at: string | null }
  sanction: Sanction
  you_decided_original: boolean
}
export const socialAppeals = (status: 'open' | 'resolved' | 'all') =>
  get<{ items: SocialAppealItem[] }>(`/admin/social/social-appeals?status=${status}`)
export const resolveSocialAppeal = (id: number, body: {
  overturn: boolean; note: string; note_internal?: string
}) => post<{ id: number; appeal_status: string; sanction: Sanction }>(
  `/admin/social/social-appeals/${id}/resolve`, body)

// ---------- 数据 ----------

export interface CommunityDay {
  day: string
  messages: number
  active_chats: number
  video_submissions: number
  review_decisions: number
  review_median_hours: number | null
  reports: number
  sanctions: number
}

export interface CommunityStats {
  days: number
  since: string
  items: CommunityDay[]
  totals: Omit<CommunityDay, 'day'>
  open: { chat_reports: number; video_reports: number; social_appeals: number; review_queue: number }
  notes: Record<string, string>
}
export const communityStats = (days: number) =>
  get<CommunityStats>(`/admin/social/community-stats?days=${days}`)
