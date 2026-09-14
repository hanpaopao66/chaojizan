/**
 * 开发者后台的薄 API 客户端(/dev/v1,DEV-PROMPTS-39 §8)。
 *
 * token 的 localStorage 键和两个后台都不一样:同一台电脑上一个人可能既是商家又是开发者,
 * 共用一个键会互相踢下线。登录后校验 role=developer,不是就不给进。
 */

const TOKEN_KEY = 'superz_dev_token'
const TOKEN_AT_KEY = 'superz_dev_token_at'

export const getToken = () => localStorage.getItem(TOKEN_KEY)
export function setToken(token: string) {
  localStorage.setItem(TOKEN_KEY, token)
  localStorage.setItem(TOKEN_AT_KEY, String(Date.now()))
}
export function clearToken() {
  localStorage.removeItem(TOKEN_KEY)
  localStorage.removeItem(TOKEN_AT_KEY)
}

export class ApiError extends Error {
  status: number
  detail: unknown
  constructor(status: number, message: string, detail?: unknown) {
    super(message)
    this.status = status
    this.detail = detail
  }
}

function messageOf(detail: unknown, status: number): string {
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    // pydantic 的 422:取第一条的 msg,去掉 "Value error, " 前缀
    const first = detail[0] as { msg?: string; loc?: unknown[] } | undefined
    if (first?.msg) return first.msg.replace(/^Value error, /, '')
  }
  if (detail && typeof detail === 'object' && 'message' in detail) {
    return String((detail as { message: string }).message)
  }
  return `请求失败(${status})`
}

export async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = {}
  if (body !== undefined) headers['Content-Type'] = 'application/json'
  const token = getToken()
  if (token) headers.Authorization = `Bearer ${token}`
  const resp = await fetch(path, {
    method, headers, body: body === undefined ? undefined : JSON.stringify(body),
  })
  if (resp.status === 401) {
    clearToken()
    if (!location.pathname.endsWith('/login')) location.assign(`${import.meta.env.BASE_URL}login`)
    throw new ApiError(401, '登录已过期,请重新登录')
  }
  if (!resp.ok) {
    let detail: unknown
    try {
      detail = (await resp.json()).detail
    } catch {
      /* 非 JSON */
    }
    throw new ApiError(resp.status, messageOf(detail, resp.status), detail)
  }
  const text = await resp.text()
  return (text ? JSON.parse(text) : undefined) as T
}

export const get = <T>(p: string) => request<T>('GET', p)
export const post = <T>(p: string, b?: unknown) => request<T>('POST', p, b ?? {})
export const put = <T>(p: string, b?: unknown) => request<T>('PUT', p, b ?? {})
export const del = <T>(p: string) => request<T>('DELETE', p)

/** 带进度的上传(fetch 拿不到上传进度) */
export function upload<T>(path: string, form: FormData, onProgress?: (pct: number) => void): Promise<T> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    xhr.open('POST', path)
    const token = getToken()
    if (token) xhr.setRequestHeader('Authorization', `Bearer ${token}`)
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable && onProgress) onProgress(Math.round((e.loaded / e.total) * 100))
    }
    xhr.onload = () => {
      let data: { detail?: unknown } | undefined
      try {
        data = JSON.parse(xhr.responseText)
      } catch {
        /* 非 JSON */
      }
      if (xhr.status >= 200 && xhr.status < 300) resolve(data as T)
      else reject(new ApiError(xhr.status, messageOf(data?.detail, xhr.status), data?.detail))
    }
    xhr.onerror = () => reject(new ApiError(0, '网络断了,检查一下再试'))
    xhr.send(form)
  })
}

// ---------------------------------------------------------------- 登录

export async function sendCode(phone: string): Promise<{ dev_code?: string }> {
  return post('/auth/sms-code', { phone })
}

export async function smsLogin(phone: string, code: string): Promise<void> {
  const out = await post<{ token: string; role: string }>('/auth/sms-login', { phone, code, role: 'developer' })
  if (out.role !== 'developer') throw new ApiError(403, '这个账号不是开发者账号')
  setToken(out.token)
}

// ---------------------------------------------------------------- 类型

export interface DeveloperCard { name: string; kind: string; verified: boolean; official: boolean; label: string }

export interface Me {
  id: number
  kind: 'individual' | 'company'
  display_name: string
  status: string
  status_label: string
  public: DeveloperCard
  real_name_masked: string
  id_no_tail: string
  company_name: string
  uscc: string
  license_uploaded: boolean
  contact_name: string
  contact_email: string
  reject_reason: string
  phone_tail: string
  agreement: { accepted: number; required: number; ok: boolean; rules_url: string }
  can_submit: boolean
  apps: number
  limits: { max_apps: number; max_testers: number }
}

export interface AppCard {
  appid: string
  id: number
  name: string
  icon: string
  tagline: string
  kind: 'app' | 'game'
  category: string
  category_label: string
  hosting: string
  is_official: boolean
  curated: boolean
  developer: DeveloperCard
  first_released_at: string | null
  status: string
  status_label: string
}

export interface Version {
  id: number
  version: string
  build: number
  status: string
  status_label: string
  sha256: string
  size: number
  file_count: number
  changelog: string
  review_note: string
  quarantined: boolean
  reject_code: string
  reject_label: string
  reject_note: string
  warnings: string[]
  superz: Record<string, unknown>
  is_current: boolean
  is_trial: boolean
  created_at: string | null
  submitted_at: string | null
  reviewed_at: string | null
  released_at: string | null
  files?: Array<{ path: string; size: number; sha256: string; type: string }>
}

export interface Listing {
  name: string
  icon: string
  tagline: string
  description: string
  category: string
  screenshots: string[]
  privacy_policy: string
  data_declaration: Array<{ field: string; purpose: string }>
}

export interface AppDetail extends AppCard {
  description: string
  screenshots: string[]
  privacy_policy: string
  data_declaration: Array<{ field: string; purpose: string }>
  listing_draft: Listing | null
  request_domains: string[]
  auto_release: boolean
  hosted_origin: string
  secret: { rotated_at: string | null; pending: boolean }
  current_version: Version | null
  trial_version: Version | null
  reviewing_version: Version | null
  testers: number
  max_testers: number
  capabilities: string[]
  capability_requests: Array<{ id: number; capability: string; status: string; status_label: string; justification: string; note: string }>
  domain_changes: { used: number; limit: number }
  trial_link: string
  removed_at: string | null
}

export interface PackageReport {
  ok: boolean
  errors: string[]
  warnings: string[]
  sha256: string
  size: number
  file_count: number
  manifest: Record<string, unknown>
}

export interface Decision {
  id: number
  target_type: string
  target_id: number
  app_id: number | null
  app_name: string
  action: string
  action_label: string
  reason_code: string
  reason_label: string
  note_public: string
  appeal_of: number | null
  appealable: boolean
  created_at: string | null
}

export interface LaunchPayload {
  url: string
  init_data: string
  app: AppCard & {
    background_color: string
    orientation: string
    allowed_origins: string[]
    capabilities: string[]
    bridge: number
  }
  version: Version
  env: string
}

/** 机器人(#355,docs/BOT-API.md 第 8 节)。**不含 token**,只有前 6 位 */
export interface BotCommand { command: string; description: string }

export type BotMenu =
  | { type: 'default' }
  | { type: 'commands' }
  | {
    type: 'web_app'
    text: string
    app_id: string
    app: { name: string; icon: string; status: string } | null
    /** false = 小程序下架了,用户那边不显示这个按钮 */
    available: boolean
  }

export interface BotDev {
  id: number
  name: string
  username: string | null
  link: string | null
  avatar: string
  about: string
  description: string
  commands: BotCommand[]
  menu_button: BotMenu
  privacy_mode: boolean
  token_prefix: string
  created_at: string | null
  webhook: {
    url: string
    has_secret: boolean
    pending_update_count: number
    last_error_date: string | null
    last_error_message: string
  }
}

/**
 * AI 助手令牌(MCP 接入,/auth/agent-tokens)。开发者账号只能勾 miniapp(发布小程序和小游戏),
 * 能调哪些接口由服务端 security.AGENT_MINIAPP 白名单决定。明文只在签发那一次返回
 */
export interface AgentToken {
  id: number
  name: string
  scopes: string[]
  scope_labels: string[]
  created_at: string | null
  expires_at: string
  last_used_at: string | null
  revoked: boolean
}

export interface AgentTokenIssued {
  /** 明文,只有这一次 */
  token: string
  expires_at: string
  scopes: string[]
  scope_labels: string[]
  note: string
}

/** 助手的一次调用。只有方法、路径、状态码、时间,没有请求体 */
export interface AgentCall { method: string; path: string; status: number; at: string | null }

export const CATEGORIES: Record<string, string> = {
  tools: '工具', productivity: '效率', life: '生活', learning: '学习', casual: '休闲益智', puzzle: '益智解谜',
}

// ---------------------------------------------------------------- 接口

export const api = {
  me: () => get<Me>('/dev/v1/me'),
  updateProfile: (b: { display_name: string; contact_email: string }) => put<Me>('/dev/v1/me/profile', b),
  verifyIndividual: (b: { real_name: string; id_no: string }) => post<Me>('/dev/v1/me/verify/individual', b),
  verifyCompany: (b: { company_name: string; uscc: string; license_key: string; contact_name: string }) =>
    post<Me>('/dev/v1/me/verify/company', b),
  acceptAgreement: (revision: number) => post<Me>('/dev/v1/me/agreement', { revision }),
  rules: () => get<{ draft: boolean; sections: Array<{ title: string; items: string[] }> }>('/rules/developer'),
  messages: () => get<{ decisions: Decision[]; rule_updates: Array<{ revision: number; at: string }> }>('/dev/v1/messages'),

  apps: () => get<{ items: Array<AppCard & { current_version: string | null; reviewing: boolean }> }>('/dev/v1/apps'),
  createApp: (b: { name: string; kind: string; category: string; tagline: string }) =>
    post<{ app: AppDetail; app_secret: string; notice: string }>('/dev/v1/apps', b),
  app: (appid: string) => get<AppDetail>(`/dev/v1/apps/${appid}`),
  updateApp: (appid: string, b: Partial<Listing>) => put<AppDetail>(`/dev/v1/apps/${appid}`, b),
  offline: (appid: string) => post<AppDetail>(`/dev/v1/apps/${appid}/offline`),
  online: (appid: string) => post<AppDetail>(`/dev/v1/apps/${appid}/online`),
  remove: (appid: string, confirm_name: string) => post(`/dev/v1/apps/${appid}/remove`, { confirm_name }),

  versions: (appid: string) => get<{ items: Version[] }>(`/dev/v1/apps/${appid}/versions`),
  version: (appid: string, id: number) => get<Version>(`/dev/v1/apps/${appid}/versions/${id}`),
  uploadVersion: (appid: string, file: File, version: string, changelog: string, onProgress?: (p: number) => void) => {
    const f = new FormData()
    f.append('file', file)
    f.append('version', version)
    f.append('changelog', changelog)
    return upload<{ version: Version; report: PackageReport }>(`/dev/v1/apps/${appid}/versions`, f, onProgress)
  },
  setTrial: (appid: string, id: number) => post<AppDetail>(`/dev/v1/apps/${appid}/versions/${id}/trial`),
  submit: (appid: string, id: number, review_note: string) =>
    post<Version>(`/dev/v1/apps/${appid}/versions/${id}/submit`, { review_note }),
  withdraw: (appid: string, id: number) => post<Version>(`/dev/v1/apps/${appid}/versions/${id}/withdraw`),
  release: (appid: string, id: number) => post<AppDetail>(`/dev/v1/apps/${appid}/versions/${id}/release`),
  rollback: (appid: string, version_id: number) => post<AppDetail>(`/dev/v1/apps/${appid}/rollback`, { version_id }),
  autoRelease: (appid: string, enabled: boolean) => put<AppDetail>(`/dev/v1/apps/${appid}/auto-release`, { enabled }),

  testers: (appid: string) =>
    get<{ items: Array<{ id: number; phone_tail: string; added_at: string }>; max: number }>(`/dev/v1/apps/${appid}/testers`),
  addTester: (appid: string, phone: string) => post(`/dev/v1/apps/${appid}/testers`, { phone }),
  removeTester: (appid: string, id: number) => del(`/dev/v1/apps/${appid}/testers/${id}`),

  requestCapability: (appid: string, capability: string, justification: string) =>
    post(`/dev/v1/apps/${appid}/capabilities`, { capability, justification }),

  rotateSecret: (appid: string) => post<{ app_secret_pending: string; notice: string }>(`/dev/v1/apps/${appid}/secret/rotate`),
  activateSecret: (appid: string) => post(`/dev/v1/apps/${appid}/secret/activate`),
  cancelSecret: (appid: string) => post(`/dev/v1/apps/${appid}/secret/cancel`),
  setDomains: (appid: string, request_domains: string[]) =>
    put<AppDetail>(`/dev/v1/apps/${appid}/domains`, { request_domains }),

  stats: (appid: string, days = 30) =>
    get<{ items: Array<{ day: string; opens: number; users: number | string }>; csp_blocked: Record<string, number> }>(
      `/dev/v1/apps/${appid}/stats?days=${days}`),
  reports: (appid: string) =>
    get<{ items: Array<{ id: number; reason_code: string; reason_label: string; status: string; resolution: string; created_at: string }> }>(
      `/dev/v1/apps/${appid}/reports`),
  decisions: (appid: string) => get<{ items: Decision[] }>(`/dev/v1/apps/${appid}/decisions`),
  appeal: (decisionId: number, text: string) => post(`/dev/v1/decisions/${decisionId}/appeal`, { text }),

  simLaunch: (appid: string, versionId: number, body: { platform: string; theme?: Record<string, string>; start_param?: string }) =>
    post<LaunchPayload>(`/dev/v1/apps/${appid}/sim/launch?version_id=${versionId}`, body),
  simStorage: (appid: string, op: string, body: unknown) => post<unknown>(`/dev/v1/apps/${appid}/sim/storage/${op}`, body),
  simProfile: (appid: string) => post<{ init_data: string }>(`/dev/v1/apps/${appid}/sim/profile`),

  bots: () => get<{ items: BotDev[]; max: number; enabled: boolean }>('/dev/v1/bots'),
  createBot: (b: { name: string; username: string }) =>
    post<{ bot: BotDev; token: string; notice: string }>('/dev/v1/bots', b),
  bot: (id: number) => get<BotDev>(`/dev/v1/bots/${id}`),
  updateBot: (id: number, b: Partial<{ name: string; about: string; description: string; avatar: string; privacy_mode: boolean }>) =>
    put<BotDev>(`/dev/v1/bots/${id}`, b),
  setBotCommands: (id: number, commands: BotCommand[]) => put<BotDev>(`/dev/v1/bots/${id}/commands`, { commands }),
  setBotMenu: (id: number, b: { type: 'default' | 'commands' | 'web_app'; text?: string; app_id?: string }) =>
    put<BotDev>(`/dev/v1/bots/${id}/menu-button`, b),
  setBotWebhook: (id: number, b: { url: string; secret_token?: string; drop_pending_updates?: boolean }) =>
    put<BotDev>(`/dev/v1/bots/${id}/webhook`, b),
  deleteBotWebhook: (id: number, dropPending: boolean) =>
    del<BotDev>(`/dev/v1/bots/${id}/webhook?drop_pending_updates=${dropPending}`),
  resetBotToken: (id: number) => post<{ bot: BotDev; token: string; notice: string }>(`/dev/v1/bots/${id}/token`),
  deleteBot: (id: number) => del<{ deleted: boolean; messages: number; chats_left: number }>(`/dev/v1/bots/${id}`),

  // 开发者账号签的助手令牌只能勾 miniapp,别的权限服务端回 422,所以这里写死
  agentTokens: () => get<AgentToken[]>('/auth/agent-tokens'),
  createAgentToken: (b: { name: string; days: number }) =>
    post<AgentTokenIssued>('/auth/agent-tokens', { ...b, scopes: ['miniapp'] }),
  revokeAgentToken: (id: number) => del<{ ok: boolean }>(`/auth/agent-tokens/${id}`),
  agentActivity: (limit = 50) => get<{ items: AgentCall[]; note: string }>(`/auth/agent-activity?limit=${limit}`),

  uploadImage: async (file: File, purpose: string) => {
    const f = new FormData()
    f.append('file', file)
    f.append('purpose', purpose)
    return upload<{ url: string }>('/upload', f)
  },
}

export function bytes(n: number): string {
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / 1024 / 1024).toFixed(2)} MB`
}

export function time(s: string | null | undefined): string {
  if (!s) return '—'
  const d = new Date(s)
  const pad = (x: number) => String(x).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}
