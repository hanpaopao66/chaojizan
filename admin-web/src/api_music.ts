/**
 * 音乐治理的后台接口:`/admin/music/…`(DEV-PROMPTS-41 #378)。
 *
 * 形状对着 docs/MUSIC-API.md §10 写 —— 字段名猜错的话页面上就是一片空白,而且不报错。
 *
 * 单独一个文件而不是塞进 api_community.ts:音乐和消息 / 视频的治理接口互不相干,
 * 论坛那边合并进来时也各占一个文件,少几处冲突。
 */
import { get, post } from './api'

export interface MusicReasonCode { code: string; label: string }

export const musicReasonCodes = () =>
  get<{ items: MusicReasonCode[]; copyright_code: string }>('/admin/music/reason-codes')

export interface MusicPerson {
  id: number
  name: string
  username: string | null
  avatar?: string
}

export interface MusicArtistBrief {
  aid: string
  name: string
  avatar: string
  user_id: number
  bio?: string
  status?: string
  user?: MusicPerson | null
}

export interface MusicStreamUrls {
  std: string | null
  hq: string | null
  expires_at: string
}

export interface MusicTrackForAdmin {
  tid: string
  title: string
  track_no: number
  duration_ms: number
  explicit: boolean
  declaration: string
  lyrics_kind: string
  lyrics: string
  credits: Record<string, string[]>
  transcode_status: string
  stream: MusicStreamUrls
}

export interface MusicDecisionOut {
  id: number
  action: string
  reason_code: string
  reason_label: string
  note: string
  admin_id: number | null
  created_at: string
  appeal_text: string
  appeal_at: string | null
  appeal_result: string
  appeal_by: number | null
  appeal_note: string
}

export interface MusicReleaseForAdmin {
  rid: string
  title: string
  kind: string
  status: string
  status_label: string
  description: string
  genre: string
  genre_name: string
  language: string
  language_name: string
  release_date: string | null
  submitted_at: string | null
  created_at: string
  cover: string
  artist: MusicArtistBrief | null
  tracks: MusicTrackForAdmin[]
  reports_open: number
  decisions?: MusicDecisionOut[]
}

export const musicQueue = () => get<{ items: MusicReleaseForAdmin[]; count: number }>('/admin/music/review')

export const musicRelease = (rid: string) => get<MusicReleaseForAdmin>(`/admin/music/releases/${rid}`)

export const decideRelease = (rid: string, body: { action: 'approve' | 'reject'; reason_code?: string; note?: string }) =>
  post<{ decision_id: number; action: string; status: string }>(`/admin/music/releases/${rid}/decide`, body)

export const removeRelease = (rid: string, body: { reason_code: string; note?: string }) =>
  post<{ decision_id: number; status: string }>(`/admin/music/releases/${rid}/remove`, body)

export const restoreRelease = (rid: string, note = '') =>
  post<{ decision_id: number; status: string }>(`/admin/music/releases/${rid}/restore`, { note })

// ---------- 申诉 ----------

export interface MusicAppealItem {
  decision_id: number
  appeal: { text: string; at: string | null }
  original: {
    action: string
    reason_code: string
    reason_label: string
    note: string
    admin_id: number | null
    created_at: string
  }
  release: { rid: string; title: string; status: string; cover: string }
  artist: MusicArtistBrief | null
  you_decided_original: boolean
}

export const musicAppeals = () => get<{ items: MusicAppealItem[] }>('/admin/music/appeals')

export const resolveMusicAppeal = (id: number, body: { result: 'upheld' | 'overturned'; note: string }) =>
  post<{ decision_id: number; result: string; status: string }>(`/admin/music/appeals/${id}/resolve`, body)

// ---------- 举报 ----------

export interface MusicReportItem {
  id: number
  target_type: 'track' | 'release' | 'comment' | 'playlist' | 'artist'
  target_id: number
  reason_code: string
  reason_label: string
  note: string
  contact: string
  is_copyright: boolean
  status: string
  resolution: string
  created_at: string
  track?: { tid: string; title: string; release: { rid: string; title: string; status: string } | null; artist: MusicArtistBrief | null } | null
  release?: { rid: string; title: string; status: string; cover: string; artist: MusicArtistBrief | null } | null
  comment?: { id: number; text: string; user_id: number; status: string } | null
  playlist?: { pid: string; title: string; owner_id: number; is_public: boolean } | null
  artist?: MusicArtistBrief | null
}

export const musicReports = (status: 'open' | 'handled' | 'all' = 'open') =>
  get<{ items: MusicReportItem[] }>(`/admin/music/reports?status=${status}`)

export const handleMusicReport = (
  id: number,
  body: { action: 'dismiss' | 'remove_target'; reason_code?: string; note?: string },
) => post<{ id: number; status: string; resolution: string }>(`/admin/music/reports/${id}/handle`, body)

// ---------- 音乐人 ----------

export interface MusicArtistRow extends MusicArtistBrief {
  cover: string
  genres: string[]
  fans: number
  followed: boolean
  track_count: number
  status: string
  created_at: string
}

export const musicArtists = (q = '') =>
  get<{ items: MusicArtistRow[] }>(`/admin/music/artists${q ? `?q=${encodeURIComponent(q)}` : ''}`)

export const suspendArtist = (aid: string, note = '') =>
  post<{ aid: string; status: string }>(`/admin/music/artists/${aid}/suspend`, { note })

export const restoreArtist = (aid: string) =>
  post<{ aid: string; status: string }>(`/admin/music/artists/${aid}/restore`)

// ---------- 数据 ----------

export interface MusicStats {
  reviewing: number
  approved_7d: number
  rejected_7d: number
  removed_7d: number
  reject_rate_7d: number
  appeals_open: number
  reports_open: number
  artists: number
  published_releases: number
}

export const musicStats = () => get<MusicStats>('/admin/music/stats')
